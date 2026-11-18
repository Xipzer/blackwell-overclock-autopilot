"""Direct 3DMark test launches and the N-run trial harness.

3DMark runs each graphics test as its own process: 3DMarkTimeSpy.exe --in <workload.json> --out <result.json>.
Copy the workload JSON of one test from a normal run (see docs/VALIDATION.md) and this module starts that test
directly, with no clicking, as often as needed.

What makes it reliable:

- Display mode. A direct launch does not reliably go fullscreen. With "is_windowed": false alone (exclusive
  fullscreen), on an RTX 5090 with four monitors only the first run after a boot went fullscreen; every later run
  silently fell back to an ordinary 3840x2160 window (style 0x14CF0000) spread over several monitors, at about
  141 fps instead of 172 in GT2. A copied workload can also carry "is_windowed": true. The fallback window is a
  lighter, composited load: results in it understate GPU load and stability margin, and its fps do not compare
  with fullscreen. The fix that held on every run: "is_windowed": false, "is_borderless": true and
  "swapchain_resolution" = the target display's native size (borderless fullscreen, window 1920x1080 at style
  0x94000000 on a 1080p display). The harness writes all three before every launch, and reads the test window
  once per run (tools/winrect.ps1) so each result records the mode it really ran in.
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
        self.borderless = cfg.get("3dmark", "borderless").lower() not in ("0", "false", "no", "off")
        self.swapchain = cfg.get("3dmark", "swapchain")
        self.window_check = cfg.int("3dmark", "window_check", 30)
        self._luid = None
        self._size = None
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

    def _tool(self, name, *args, timeout=60):
        return subprocess.run([self.ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                               winpath(os.path.join(HERE, "tools", name))] + list(args),
                              capture_output=True, text=True, timeout=timeout).stdout.strip()

    def size(self):
        """[width, height] for swapchain_resolution: [3dmark] swapchain, else the primary display's native size."""
        if self._size is None:
            m = re.match(r"\s*(\d+)\s*x\s*(\d+)", self.swapchain or self._tool("screen.ps1"))
            if not m:
                raise SystemExit("set [3dmark] swapchain (for example 1920x1080) in bwoc.ini")
            self._size = [int(m.group(1)), int(m.group(2))]
        return self._size

    def window(self):
        """The test window now -> (mode, raw text). mode: borderless, fullscreen, windowed, none or other."""
        name = re.sub(r"(?i)\.exe$", "", self.exe.rsplit("\\", 1)[-1])
        raw = self._tool("winrect.ps1", "-Name", name, timeout=30)
        m = re.match(r"rect (-?\d+),(-?\d+) -> (-?\d+),(-?\d+) style 0x([0-9A-Fa-f]+)", raw)
        if not m:
            return "none", raw
        l, t, r, b, style = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5), 16)
        if style & 0x00C00000:  # WS_CAPTION: an ordinary window (the silent fallback)
            return "windowed", raw
        if [r - l, b - t] == self.size():
            return ("borderless" if self.borderless else "fullscreen"), raw
        return "other", raw

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
        -> dict(status=exit|reset|timeout, ok=bool, ran=bool, seconds, fps,
                mode=borderless|fullscreen|windowed|other|none|unchecked, window=raw window text)."""
        src = os.path.join(self.workloads, test + ".json")
        w = json.load(open(src, encoding="utf-8-sig"))
        want = {"dxgi_adapter_luid": self.luid(), "is_windowed": False, "is_borderless": self.borderless,
                "swapchain_resolution": self.size()}
        if any(w.get(k) != v for k, v in want.items()):
            w.update(want)
            json.dump(w, open(src, "w", encoding="utf-8"))
        win_in, out = winpath(src), os.path.join(self.workloads, test + "-out.json")
        win_out = winpath(out)
        if os.path.exists(out):
            os.remove(out)
        t0 = time.time()
        start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0 - 1))
        pid = self._pscmd("(Start-Process -FilePath '%s' -ArgumentList '--in','\"%s\"','--out','\"%s\"' "
                          "-WorkingDirectory '%s' -PassThru).Id" % (self.exe, win_in, win_out, self.workdir)) or "0"
        status, mode, raw = "timeout", "unchecked", ""
        while time.time() - t0 < self.timeout:
            time.sleep(self.poll)
            if mode == "unchecked" and self.window_check and time.time() - t0 >= self.window_check:
                mode, raw = self.window()
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
                "seconds": round(secs), "fps": fps, "mode": mode, "window": raw}

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
            log("%s run %d %s: %s (%s after %d s, fps %s, window %s)" % (
                label, i + 1, test, "PASS" if r["ok"] else "FAIL", r["status"], r["seconds"], r["fps"], r["mode"]))
            if r["mode"] in ("windowed", "other"):
                log("%s run %d: WARNING the test ran in a %s window (%s), not fullscreen on one display; this run is a "
                    "lighter load and does not compare with fullscreen runs" % (label, i + 1, r["mode"], r["window"]))
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
    return {"runs": runs, "hangs": hangs, "passes": sum(1 for r in results if r["ok"]),
            "not_fullscreen": sum(1 for r in results if r.get("mode") in ("windowed", "other")), "results": results}
