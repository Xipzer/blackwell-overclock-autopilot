"""Per-voltage maximum clock search.

For each voltage V: write a uniform offset O to the work profile, then pin the clock to F = base(V) + O with
nvidia-smi -lgc F,F, so the driver runs exactly the V/F point under test. Run gpucheck for a fixed time.
Raise F by `step` (then `fine_step` once the offset passes `fine_above`) until the first failure.

  pass        gpucheck reports 0 errors, no driver reset in the window, and the card ran the lock
  fail        checksum error, CUDA error, driver reset (event 4101 / nvlddmkm), or the PC went down
  not reached the card did not run the point (power, current or voltage limit): no result, the search stops

Modes:
  heavy  3 blocks per SM, 2000 ms busy / 400 ms idle; the clock is checked with nvidia-smi
  light  1 block per SM, 1500 ms busy / 600 ms idle, so power limits do not hold the voltage down; the real
         voltage is read from Afterburner and a step more than voltage_tolerance under V is "not reached".
         Use it for the top of the curve (about 1.10 V and up), which the card only runs at light load.

A limit usually ends in a driver hang and a bugcheck, not a clean reset. Before each step a marker file is
written; if the process starts and finds it, that step is recorded as the voltage's first failure and the
search goes on with the next voltage. Start it from a logon task with --resume to continue after a crash.
"""
import json
import os
import statistics
import subprocess
import time

from . import abcurve, telemetry

MODES = {"heavy": ("3", "2000", "400"), "light": ("1", "1500", "600")}


class Sweep:
    def __init__(self, cfg, elevated, volts, mode="heavy", starts=None, results=None, bracket=False, log=print):
        self.cfg, self.el, self.volts, self.mode = cfg, elevated, volts, mode
        self.starts = starts or {}
        self.out = results or cfg.state("vf-results-%s.json" % mode)
        self.marker = cfg.state("vf-running-%s.json" % mode)
        self.bracket, self.log = bracket, log
        s = lambda k: cfg.int("sweep", k)  # noqa: E731
        self.seconds, self.step_mhz, self.fine, self.fine_above = s("seconds"), s("step"), s("fine_step"), s("fine_above")
        self.max_offset, self.lock_tol, self.volt_tol = s("max_offset"), s("lock_tolerance"), s("voltage_tolerance")

    def safe(self):
        """After a failure: back to a known-good profile and a clock cap."""
        safe = self.cfg.int("afterburner", "safe_profile")
        if safe:
            self.el.apply(safe)
            time.sleep(5)
        cap = self.cfg.int("cap", "max_mhz")
        if cap:
            self.el.lock(self.cfg.int("cap", "min_mhz"), cap)
        else:
            self.el.reset()
        time.sleep(3)

    def step(self, V, base, F, good):
        O = F - base
        if O > self.max_offset:
            return None, "offset +%d above the per-point limit +%d" % (O, self.max_offset)
        json.dump({"V": V, "F": F, "O": O, "base": base, "good": good, "t": time.time()}, open(self.marker, "w"))
        abcurve.write_work(self.cfg, self.el, lambda v, f: O)
        self.el.lock(F, F)
        time.sleep(3)
        t0 = time.time()
        blocks, busy, idle = MODES[self.mode]
        p = subprocess.Popen([self.cfg.get("paths", "gpucheck"), str(self.seconds), blocks, busy, idle],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        samples = []
        while p.poll() is None:
            time.sleep(5)
            if self.mode == "light":
                x = telemetry.mahm(self.cfg)                       # clock, mV, W, load
                if x and x[3] > 30:
                    samples.append((x[0], x[1], x[2]))
            else:
                x = telemetry.smi(self.cfg)                        # clock, W, load, C
                if x and x[2] > 50:
                    samples.append((x[0], None, x[1]))
        out = p.stdout.read()
        res = [line for line in out.splitlines() if line.startswith("RESULT")]
        resets = telemetry.driver_resets_since(self.cfg, t0 - 5)
        os.remove(self.marker)
        result = res[-1] if res else "no result (%s)" % out.strip()[-120:]
        bad = not res or "errors=0 " not in res[-1] + " " or resets != 0
        lo = min((s[0] for s in samples), default=0)
        hi = max((s[0] for s in samples), default=0)
        watts = max((s[2] for s in samples), default=0)
        mv = statistics.median(s[1] for s in samples) if self.mode == "light" and samples else None
        d = "V %d mV, F %d MHz (+%d): %s; clock %d-%d MHz%s, up to %.0f W; driver resets %d" % (
            V, F, O, result, lo, hi, ", median %d mV" % mv if mv else "", watts, resets)
        # The reported clock sits 15 to 23 MHz under any lock, hence the tolerance.
        if not bad and (hi < F - self.lock_tol or (mv is not None and mv < V - self.volt_tol)):
            return None, "NOT REACHED: " + d
        return (not bad), d

    def run(self, resume=False):
        _, pts, _ = abcurve.curve(abcurve.read(self.cfg.profile_file()), self.cfg.int("afterburner", "source_profile"))
        results = json.load(open(self.out)) if os.path.exists(self.out) else {}
        if os.path.exists(self.marker):
            r = json.load(open(self.marker))
            os.remove(self.marker)
            results[str(r["V"])] = {"base": r["base"], "max_pass": r["good"],
                                    "first_fail": "%d (system went down during the step)" % r["F"]}
            json.dump(results, open(self.out, "w"), indent=1)
            self.log("the PC went down during the %d mV step at %d MHz (+%d): that voltage's first failure" % (r["V"], r["F"], r["O"]))
            resume = True
        todo = [V for V in self.volts if str(V) not in results]
        if not todo:
            self.log("nothing to do: every voltage has a result in %s" % self.out)
            return results
        if resume:
            time.sleep(self.cfg.int("sweep", "boot_delay"))   # after a boot: let Afterburner and the helper start
        self.log("start (%s): voltages %s, %d s per step" % (self.mode, todo, self.seconds))
        for V in todo:
            base = abcurve.base_at(pts, V)
            F = base + self.starts.get(V, self.cfg.int("sweep", "start_offset"))
            good, fail, log = None, None, []
            while True:
                ok, d = self.step(V, base, F, good)
                log.append(d)
                self.log("step %s: %s" % ({True: "PASS", False: "FAIL", None: "SKIP"}[ok], d))
                if ok is None:
                    fail = fail or "not reached at %d" % F
                    break
                if ok:
                    good = F
                    F += self.step_mhz if F - base < self.fine_above else self.fine
                    continue
                fail = F
                self.safe()
                time.sleep(20)
                if self.bracket and good is not None and fail - good > self.fine:
                    ok2, d2 = self.step(V, base, good + self.fine, good)
                    log.append(d2)
                    self.log("bracket %s: %s" % ("PASS" if ok2 else "FAIL", d2))
                    if ok2:
                        good += self.fine
                    else:
                        fail = good + self.fine
                        self.safe()
                        time.sleep(20)
                break
            results[str(V)] = {"base": base, "max_pass": good, "first_fail": fail, "log": log}
            json.dump(results, open(self.out, "w"), indent=1)
            self.log("%d mV: highest pass %s MHz, first fail %s (base %d)" % (V, good, fail, base))
            self.safe()
            time.sleep(10)
        self.finish()
        self.log("done: " + ", ".join("%s mV: %s/%s" % (v, r["max_pass"], r["first_fail"]) for v, r in results.items()))
        return results

    def finish(self):
        self.el.reset()
        time.sleep(2)
        final = self.cfg.int("afterburner", "final_profile") or self.cfg.int("afterburner", "source_profile")
        self.el.apply(final)
        time.sleep(5)
        cap = self.cfg.int("cap", "max_mhz")
        if cap:
            self.el.lock(self.cfg.int("cap", "min_mhz"), cap)
