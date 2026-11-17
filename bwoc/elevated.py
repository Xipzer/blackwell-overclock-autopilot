"""The four actions that need administrator rights, behind one small interface.

  lock(lo, hi)        nvidia-smi -lgc lo,hi     (clock range; lo == hi pins one V/F point)
  reset()             nvidia-smi -rgc
  install(staged)     copy a staged Afterburner profile file over the real one (Program Files needs admin)
  apply(n)            MSIAfterburner.exe -Profile<n>

mode = direct: this process is elevated (Python on Windows started as administrator) and does it itself.
mode = helper: this process is not elevated (normal Windows user, or WSL). It drops one command line into
helper_dir/cmd.txt and waits for helper_dir/ack.txt, written by tools/helper.ps1 running elevated
(for example as a scheduled task with "Run with highest privileges"). See docs/METHOD.md.
"""
import os
import shutil
import subprocess
import time


class Elevated:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = cfg.get("elevated", "mode")
        self.dir = cfg.get("elevated", "helper_dir")
        self.timeout = cfg.int("elevated", "timeout", 60)
        if self.mode == "helper" and not self.dir:
            raise SystemExit("elevated.mode = helper needs elevated.helper_dir")

    def staged_path(self):
        return os.path.join(self.dir, "ab-stage.cfg") if self.mode == "helper" else self.cfg.state("ab-stage.cfg")

    def lock(self, lo, hi):
        return self._run("lgc %d %d" % (lo, hi), [self.cfg.get("paths", "nvidia_smi"), "-lgc", "%d,%d" % (lo, hi)])

    def reset(self):
        return self._run("rgc", [self.cfg.get("paths", "nvidia_smi"), "-rgc"])

    def install(self, staged):
        if self.mode == "helper":
            return self._send("abwrite")
        shutil.copyfile(staged, self.cfg.profile_file())
        return True

    def apply(self, n):
        if self.mode == "helper":
            return self._send("abprof %d" % n)
        subprocess.Popen([self.cfg.get("paths", "afterburner_exe"), "-Profile%d" % n])
        return True

    def _run(self, cmd, argv):
        if self.mode == "helper":
            return self._send(cmd)
        return subprocess.run(argv, capture_output=True).returncode == 0

    def _send(self, cmd):
        ack, box = os.path.join(self.dir, "ack.txt"), os.path.join(self.dir, "cmd.txt")
        for attempt in (0, 1):
            try:
                os.remove(ack)
            except FileNotFoundError:
                pass
            with open(box, "w") as f:
                f.write(cmd)
            for _ in range(self.timeout):
                if os.path.exists(ack):
                    return open(ack, encoding="utf-8", errors="replace").read().startswith("ok")
                time.sleep(1)
            task = self.cfg.get("elevated", "helper_task")
            if attempt or not task:
                return False
            schtasks = "schtasks.exe" if os.name == "nt" else "/mnt/c/Windows/System32/schtasks.exe"
            subprocess.run([schtasks, "/Run", "/TN", task], capture_output=True)
        return False
