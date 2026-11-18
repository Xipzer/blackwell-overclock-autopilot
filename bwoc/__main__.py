"""Command line: python -m bwoc <command> [options]. Run python -m bwoc -h for the list."""
import argparse
import sys
import time

from . import abcurve, hangscan, telemetry, tse
from .config import Config
from .elevated import Elevated
from .sweep import Sweep


def journal(cfg):
    path = cfg.state("journal.md")

    def log(line):
        line = "- %s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), line)
        print(line, flush=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return log


def ints(s):
    return [int(x) for x in s.split(",") if x]


def starts(s):
    return {int(k): int(v) for k, v in (x.split(":") for x in s.split(",") if x)} if s else {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bwoc", description="Blackwell OC Autopilot")
    ap.add_argument("--config", help="settings file (default: bwoc.ini next to this package, or $BWOC_CONFIG)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sweep", help="per-voltage maximum clock search (crashes the GPU on purpose)")
    s.add_argument("--volts", required=True, help="comma list in mV, e.g. 1050,1000,950")
    s.add_argument("--mode", choices=["heavy", "light"], default="heavy")
    s.add_argument("--start", default="", help="start offsets per voltage, e.g. 1050:420,1000:450")
    s.add_argument("--results", help="results JSON (default: state/vf-results-<mode>.json)")
    s.add_argument("--bracket", action="store_true", help="after a failure, retry one fine step above the last pass")
    s.add_argument("--resume", action="store_true", help="wait boot_delay first (use from a logon task)")
    s.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    c = sub.add_parser("cap", help="clock range: cap MAX [--min MIN], or cap --reset")
    c.add_argument("max", nargs="?", type=int)
    c.add_argument("--min", type=int)
    c.add_argument("--reset", action="store_true")

    v = sub.add_parser("curve", help="show a profile's V/F curve, or write a uniform offset to the work profile")
    v.add_argument("--profile", type=int, help="profile to show (default: source_profile)")
    v.add_argument("--offset", type=int, help="write this offset to every point of the work profile")
    v.add_argument("--softcap", type=int, help="write the source curve with every point at or under --below mV held "
                   "to at most this clock (points above untouched) to the work profile")
    v.add_argument("--below", type=int, default=1060, help="soft cap voltage limit in mV (default 1060)")
    v.add_argument("--apply", action="store_true", help="also apply the work profile")
    v.add_argument("--range", default="800,1250", help="mV range to show")

    p = sub.add_parser("profile", help="apply an Afterburner profile slot")
    p.add_argument("n", type=int)

    sub.add_parser("telemetry", help="one line of live readings")

    t = sub.add_parser("tse", help="N direct 3DMark test runs (default: Time Spy Extreme GT2), hang detection in ~2 s")
    t.add_argument("--runs", type=int, help="runs (default: trial.runs)")
    t.add_argument("--tests", help="workload names, comma list (default: trial.tests)")
    t.add_argument("--profile", type=int, help="apply this Afterburner slot first and after every failure")
    t.add_argument("--cap", type=int, help="clock cap MHz (nvidia-smi -lgc MIN,CAP), set first and after every failure")
    t.add_argument("--rate", action="store_true", help="do every run and report the hang rate (default: stop at the first hang)")
    t.add_argument("--label", default="tse", help="name used in the journal")

    h = sub.add_parser("hangscan", help="find the heavy-scene hang signature in a telemetry CSV")
    h.add_argument("csv")
    for k, v in hangscan.DEFAULTS.items():
        h.add_argument("--" + k.replace("_", "-"), type=float, default=v)

    a = ap.parse_args(argv)
    cfg = Config(a.config)
    if a.cmd == "telemetry":
        print("nvidia-smi  clock/W/load/C:", telemetry.smi(cfg))
        print("Afterburner clock/mV/W/load:", telemetry.mahm(cfg))
        return 0
    if a.cmd == "hangscan":
        ev = hangscan.scan(a.csv, a.heavy_w, a.low_w, a.busy_pct, a.window, a.min_low, a.gap)
        print(hangscan.report(ev))
        print("%d hang signature(s)" % len(ev), file=sys.stderr)
        return 0
    if a.cmd == "curve" and a.offset is None and a.softcap is None:
        lo, hi = ints(a.range)
        print(abcurve.show(abcurve.read(cfg.profile_file()), a.profile or cfg.int("afterburner", "source_profile"), lo, hi))
        return 0
    el = Elevated(cfg)
    if a.cmd == "curve" and a.softcap:
        src = abcurve.curve(abcurve.read(cfg.profile_file()), cfg.int("afterburner", "source_profile"))[1]
        offs = abcurve.softcap(src, a.softcap, a.below)
        return 0 if abcurve.write_work(cfg, el, lambda mv, f: offs[round(mv)], apply=a.apply) else 1
    if a.cmd == "curve":
        return 0 if abcurve.write_work(cfg, el, lambda mv, f: a.offset, apply=a.apply) else 1
    if a.cmd == "profile":
        return 0 if el.apply(a.n) else 1
    if a.cmd == "cap":
        if a.reset:
            return 0 if el.reset() else 1
        top = a.max or cfg.int("cap", "max_mhz")
        if not top:
            sys.exit("give MAX or set cap.max_mhz")
        return 0 if el.lock(a.min or cfg.int("cap", "min_mhz"), top) else 1
    if a.cmd == "tse":
        log = journal(cfg)
        ts = tse.TimeSpy(cfg, log)

        def setup():
            if a.profile:
                el.apply(a.profile)
                time.sleep(4)
            if a.cap:
                el.lock(cfg.int("cap", "min_mhz"), a.cap)
                time.sleep(2)
        tests = (a.tests or cfg.get("trial", "tests")).split(",")
        r = tse.trial(ts, a.runs or cfg.int("trial", "runs"), tests, setup if (a.profile or a.cap) else None,
                      not a.rate, cfg.int("trial", "relaunch"), cfg.int("trial", "cooldown"), a.label, log)
        log("%s RESULT: %d hang(s) in %d run(s), %d clean test(s), %d not fullscreen" % (
            a.label, r["hangs"], r["runs"], r["passes"], r["not_fullscreen"]))
        return 1 if r["hangs"] else 0
    if a.cmd == "sweep":
        if not (a.yes or a.resume):
            print("This search pushes the GPU until it fails. Expect driver hangs and blue screens (0x133).\n"
                  "Save your work and close other programs. Type YES to start: ", end="", flush=True)
            if sys.stdin.readline().strip() != "YES":
                return 1
        Sweep(cfg, el, ints(a.volts), a.mode, starts(a.start), a.results, a.bracket, journal(cfg)).run(a.resume)
        return 0


if __name__ == "__main__":
    sys.exit(main())
