"""Live readings. nvidia-smi gives clock, power, load and temperature without admin rights. Afterburner's shared
memory (MAHMSharedMemory, read by tools/mahm1.ps1) adds the real core voltage, which nvidia-smi does not report.
The voltage only appears there after enabling the voltage graph in Afterburner (Settings, Monitoring)."""
import os
import subprocess
import time

from .config import HERE, winpath


def smi(cfg):
    """-> (clock MHz, power W, load %, temperature C) or None."""
    r = subprocess.run([cfg.get("paths", "nvidia_smi"), "--query-gpu=clocks.gr,power.draw,utilization.gpu,temperature.gpu",
                        "--format=csv,noheader,nounits"], capture_output=True, text=True)
    try:
        return tuple(float(x) for x in r.stdout.strip().splitlines()[0].split(", "))
    except (ValueError, IndexError):
        return None


def mahm(cfg):
    """-> (clock MHz, voltage mV, power W, load %) from Afterburner, or None if Afterburner or the graph is missing."""
    script = winpath(os.path.join(HERE, "tools", "mahm1.ps1"))
    try:
        r = subprocess.run([cfg.get("paths", "powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                           capture_output=True, text=True, timeout=30)
        c, v, w, u = r.stdout.split()
        return float(c), float(v) * 1000, float(w), float(u)
    except (ValueError, subprocess.TimeoutExpired):
        return None


def driver_resets_since(cfg, t0):
    """Count of display-driver resets (event 4101) and nvlddmkm events in the System log since t0, -1 if unknown."""
    start = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0))
    r = subprocess.run([cfg.get("paths", "powershell"), "-NoProfile", "-Command",
                        "@(Get-WinEvent -FilterHashtable @{LogName='System'; StartTime=[datetime]'%s'} -ErrorAction "
                        "SilentlyContinue | ? { $_.Id -eq 4101 -or $_.ProviderName -match 'nvlddmkm' }).Count" % start],
                       capture_output=True, text=True)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1
