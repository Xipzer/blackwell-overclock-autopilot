"""Direct 3DMark test launches and the N-run trial harness.

3DMark runs each graphics test as its own process: 3DMarkTimeSpy.exe --in <workload.json> --out <result.json>.
Copy the workload JSON of one test from a normal run (see docs/VALIDATION.md) and this module starts that test
directly, with no clicking, as often as needed.

Four things make it reliable:

- The workload copied from a run can carry "is_windowed": true. A window (here one spanning several monitors) is a
  different load from fullscreen: on an RTX 5090, GT2 ran about 149 fps windowed and 154 to 170 fps fullscreen, so
  results from the two modes do not compare. The harness always writes "is_windowed": false.
- The workload names the GPU by its DXGI adapter LUID, and the LUID changes on every boot. A stale one makes
  3DMark refuse the launch ("No DXGI adapter with given luid found"), which looks like a failed run. The LUID is
  looked up once per process (tools/luid.ps1) and written into the workload before each launch.
- A hang is noticed in about 2 s: every `poll` seconds one PowerShell call checks the process and the System log
  for event 4101 or any nvlddmkm event since the launch. Waiting for the process alone cost up to 150 s per hang.
- A launch that never ran (no result, no driver reset) is not a stability result. The trial harness relaunches it
  up to `relaunch` times before counting anything.

The display must stay awake during a run: 3DMark aborts with "window_focus_lost: Display resolution changed" if a
screen sleeps (tools/awake.ps1).
"""
import json
import os
import re
import subprocess
import time

from .config import HERE, winpath


class TimeSpy:
    def __init__(self, cfg, log=print):
        self.cfg, self.log = cfg, log
        g = lambda k: cfg.get("3dmark", k)  # noqa: E731
        self.exe, self.workdir, self.workloads = g("exe"), g("workdir"), g("workload_dir")
        self.match = g("adapter_match")
        self.timeout = cfg.int("3dmark", "timeout", 150)
        self.poll = cfg.int("3dmark", "poll", 2)
        self.ps = cfg.get("paths", "powershell")
        self._luid = None
        if not (self.exe and self.workloads):
            raise SystemExit("set [3dmark] exe and workload_dir in bwoc.ini (see bwoc.example.ini)")
        if not self.workdir:
            self.workdir = self.exe.rsplit("\\", 1)[0]

    def _pscmd(self, cmd, timeout=60):
        return subprocess.run([self.ps, "-NoProfile", "-Command", cmd], capture_output=True, text=True,
                              timeout=timeout).stdout.strip()

    def luid(self):
        """The GPU's DXGI adapter LUID as one 64-bit integer (high << 32 | low), looked up once per process."""
        if self._luid is None:
            r = subprocess.run([self.ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                winpath(os.path.join(HERE, "tools", "luid.ps1"))], capture_output=True, text=True)
            for line in r.stdout.splitlines():
                low, high, name = (line.split(",", 2) + ["", ""])[:3]
                if self.match.lower() in name.lower():
                    self._luid = (int(high) << 32) | int(low)
                    break
            if self._luid is None:
                raise SystemExit("no DXGI adapter matching %r in:\n%s" % (self.match, r.stdout))
        return self._luid

    def preflight(self):
        """None if a run can start, else the reason (3DMark missing, for example on a locked drive; GPU busy)."""
        if self._pscmd("Test-Path -LiteralPath '%s'" % self.exe) != "True":
            return "3DMark not found at %s (drive locked or not mounted?)" % self.exe
        r = subprocess.run([self.cfg.get("paths", "nvidia_smi"), "--query-gpu=utilization.gpu",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True)
        try:
            busy = int(r.stdout.split()[0])
        except (ValueError, IndexError):
            return None
        return "GPU already %d %% busy: something else is using it" % busy if busy > 20 else None

    def run(self, test):
        """Start one test (workload file <test>.json in workload_dir) and wait.
        -> dict(status=exit|reset|timeout, ok=bool, ran=bool, seconds, fps)."""
        src = os.path.join(self.workloads, test + ".json")
        w = json.load(open(src, encoding="utf-8-sig"))
        if w.get("dxgi_adapter_luid") != self.luid() or w.get("is_windowed") is not False:
            w["dxgi_adapter_luid"] = self.luid()
            w["is_windowed"] = False
            json.dump(w, open(src, "w", encoding="utf-8"))
        win_in, out = winpath(src), os.path.join(self.workloads, test + "-out.json")
        win_out = winpath(out)
        if os.path.exists(out):
            os.remove(out)
        t0 = time.time()
        start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0 - 1))
        pid = self._pscmd("(Start-Process -FilePath '%s' -ArgumentList '--in','\"%s\"','--out','\"%s\"' "
                          "-WorkingDirectory '%s' -PassThru).Id" % (self.exe, win_in, win_out, self.workdir)) or "0"
        status = "timeout"
        while time.time() - t0 < self.timeout:
            time.sleep(self.poll)
            q = self._pscmd(
                "$p = Get-Process -Id %s -ErrorAction SilentlyContinue; $e = @(Get-WinEvent -FilterHashtable "
                "@{LogName='System'; StartTime=[datetime]'%s'} -ErrorAction SilentlyContinue | "
                "? { $_.Id -eq 4101 -or $_.ProviderName -match 'nvlddmkm' }).Count; "
                "if ($e) { 'reset' } elseif (-not $p) { 'exit' } else { 'run' }" % (pid, start), timeout=30)
            if q in ("reset", "exit"):
                status = q
                break
        secs = time.time() - t0
        if status != "exit":
            self.kill()
        fps = self.fps(out)
        return {"status": status, "ok": status == "exit" and fps is not None, "ran": fps is not None or status == "reset",
                "seconds": round(secs), "fps": fps}

    def kill(self):
        name = re.sub(r"(?i)\.exe$", "", self.exe.rsplit("\\", 1)[-1])
        self._pscmd("Stop-Process -Name '%s' -Force -ErrorAction SilentlyContinue" % name)

    @staticmethod
    def fps(out):
        try:
            s = open(out, encoding="utf-8-sig").read()
        except OSError:
            return None
        m = re.findall(r'"(?:[A-Za-z_]*[Ff]ps[A-Za-z_]*|value)"\s*:\s*([0-9.]+)', s)
        return float(m[0]) if m else None


def trial(ts, runs, tests=("gt2",), setup=None, stop_on_fail=True, relaunch=3, cooldown=10, label="trial", log=print):
    """Run the tests `runs` times. setup() (re-apply profile and cap) runs first and after every failure, because a
    driver reset drops the curve, the memory offset and the clock cap.
    -> dict(runs, hangs, passes, results). With stop_on_fail the first hang ends the trial (a pass/fail gate);
    without it every run is done and the hang rate is measured."""
    why = ts.preflight()
    if why:
        raise SystemExit("not starting: " + why)
    if setup:
        setup()
    results, hangs, i, retries = [], 0, 0, 0
    while i < runs:
        for test in tests:
            r = ts.run(test)
            time.sleep(2)
            if not r["ran"] and retries < relaunch:
                retries += 1
                log("%s run %d %s: test did not run (%s), relaunching" % (label, i + 1, test, r["status"]))
                time.sleep(cooldown)
                if setup:
                    setup()
                break
            retries = 0
            r.update(run=i + 1, test=test)
            results.append(r)
            log("%s run %d %s: %s (%s after %d s, fps %s)" % (label, i + 1, test, "PASS" if r["ok"] else "FAIL",
                                                               r["status"], r["seconds"], r["fps"]))
            if not r["ok"]:
                hangs += 1
                time.sleep(cooldown)
                if setup:
                    setup()
                if stop_on_fail:
                    return _summary(i + 1, hangs, results)
        else:
            i += 1
    return _summary(runs, hangs, results)


def _summary(runs, hangs, results):
    return {"runs": runs, "hangs": hangs, "passes": sum(1 for r in results if r["ok"]), "results": results}
