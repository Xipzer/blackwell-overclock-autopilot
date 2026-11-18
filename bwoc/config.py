"""Settings from bwoc.ini (see bwoc.example.ini). Every path and limit lives here; nothing is hard-coded."""
import configparser
import glob
import os
import subprocess

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_WSL = os.name != "nt" and os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop")

DEFAULTS = {
    "paths": {
        "gpucheck": os.path.join(HERE, "gpucheck", "gpucheck.exe" if os.name == "nt" else "gpucheck"),
        "nvidia_smi": "/usr/lib/wsl/lib/nvidia-smi" if IN_WSL else "nvidia-smi",
        "powershell": "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" if IN_WSL else "powershell.exe",
        "afterburner_exe": r"C:\Program Files (x86)\MSI Afterburner\MSIAfterburner.exe",
        "afterburner_profiles": ("/mnt/c/Program Files (x86)/MSI Afterburner/Profiles" if IN_WSL
                                 else r"C:\Program Files (x86)\MSI Afterburner\Profiles"),
        "afterburner_profile_file": "",
        "state_dir": os.path.join(HERE, "state"),
    },
    "elevated": {"mode": "helper", "helper_dir": "", "helper_task": "", "timeout": "60"},
    "afterburner": {"source_profile": "1", "work_profile": "5", "safe_profile": "", "final_profile": "",
                    "power_limit": "100", "voltage_boost": "100", "mem_offset_mhz": "0"},
    "cap": {"min_mhz": "210", "max_mhz": ""},
    "sweep": {"seconds": "60", "start_offset": "270", "step": "30", "fine_step": "15", "fine_above": "420",
              "max_offset": "1000", "lock_tolerance": "30", "voltage_tolerance": "20", "boot_delay": "150"},
    "3dmark": {"exe": "", "workdir": "", "workload_dir": "", "adapter_match": "NVIDIA", "timeout": "150", "poll": "2",
               "borderless": "true", "swapchain": "", "window_check": "30"},
    "trial": {"runs": "8", "tests": "gt2", "relaunch": "3", "cooldown": "10"},
}


class Config:
    def __init__(self, path=None):
        self.p = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
        self.p.read_dict(DEFAULTS)
        path = path or os.environ.get("BWOC_CONFIG") or os.path.join(HERE, "bwoc.ini")
        if os.path.exists(path):
            self.p.read(path, encoding="utf-8")
        os.makedirs(self.get("paths", "state_dir"), exist_ok=True)

    def get(self, section, key):
        return self.p.get(section, key).strip()

    def int(self, section, key, default=None):
        v = self.get(section, key)
        return int(v) if v else default

    def state(self, name):
        return os.path.join(self.get("paths", "state_dir"), name)

    def profile_file(self):
        """Afterburner's per-card profile file (needs admin to write; reading is fine)."""
        f = self.get("paths", "afterburner_profile_file")
        if f:
            return f
        found = sorted(glob.glob(os.path.join(self.get("paths", "afterburner_profiles"), "VEN_10DE&DEV_*.cfg")))
        if len(found) != 1:
            raise SystemExit("Set paths.afterburner_profile_file: found %d NVIDIA profile files in %s"
                             % (len(found), self.get("paths", "afterburner_profiles")))
        return found[0]


def winpath(p):
    """A path as Windows programs see it (unchanged on Windows, translated with wslpath under WSL)."""
    if os.name == "nt":
        return p
    return subprocess.run(["wslpath", "-w", p], capture_output=True, text=True).stdout.strip()
