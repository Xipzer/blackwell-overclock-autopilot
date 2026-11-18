"""Finds the heavy-scene hang signature in a telemetry log.

On the RTX 5090 every Time Spy Extreme hang looked the same in a 100 ms log: a heavy phase (well over 400 W), then
power collapses to about 120 to 140 W while the GPU still reports 95 to 100 % usage. The GPU has stopped mid-frame;
the clock then jumps up because power fell, and the driver resets a few seconds later. A normal scene change or a
loading screen drops the usage together with the power, so it does not match.

A match: a sample with power >= heavy_w, then within `window` seconds a run of samples with power < low_w and
usage >= busy_pct lasting at least `min_low` seconds. Events closer than `gap` seconds are merged.

Input: a CSV with a header. Column names are matched loosely: time/timestamp, clock, voltage (V or mV), power,
usage/utilization, temp. tools/mahmlog.ps1 writes this format; an nvidia-smi --query-gpu CSV also works.
"""
import csv
import datetime
import re

DEFAULTS = {"heavy_w": 400.0, "low_w": 200.0, "busy_pct": 95.0, "window": 3.0, "min_low": 1.0, "gap": 30.0}


def _num(s):
    m = re.search(r"-?[0-9]+(?:\.[0-9]+)?", s or "")
    return float(m.group(0)) if m else None


def _col(header, *names):
    for i, h in enumerate(header):
        k = h.strip().lower()
        if any(n in k for n in names):
            return i
    return None


def _clock(s, last):
    """'HH:MM:SS.fff' or 'YYYY/MM/DD HH:MM:SS.fff' -> seconds; a bare time that goes backwards rolls over a day."""
    s = s.strip()
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt).timestamp(), s
        except ValueError:
            pass
    h, m, sec = s.split(":")
    t = int(h) * 3600 + int(m) * 60 + float(sec)
    if last is not None:
        while t < last - 43200:
            t += 86400
    return t, s


def samples(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        r = csv.reader(f)
        header = next(r)
        ci = {k: _col(header, *n) for k, n in {
            "time": ("time",), "clock": ("clock", "graphics"), "volt": ("volt",), "power": ("power.draw", "power"),
            "usage": ("usage", "utilization"), "temp": ("temp",)}.items()}
        if ci["time"] is None or ci["power"] is None or ci["usage"] is None:
            raise SystemExit("%s: need time, power and usage columns, got %s" % (path, header))
        last = None
        for row in r:
            if len(row) < len(header) or row[0].strip().lower() in ("time", "timestamp"):
                continue
            try:
                t, label = _clock(row[ci["time"]], last)
            except ValueError:
                continue
            last = t
            get = lambda k: _num(row[ci[k]]) if ci[k] is not None else None  # noqa: E731
            v = get("volt")
            if v is not None and v < 5:
                v *= 1000
            yield {"t": t, "label": label, "clock": get("clock"), "mv": v, "w": get("power"),
                   "usage": get("usage"), "temp": get("temp")}


def scan(path, heavy_w=400.0, low_w=200.0, busy_pct=95.0, window=3.0, min_low=1.0, gap=30.0):
    """-> list of events: dict with the last heavy sample, the first and last hung samples, and the duration."""
    events, heavy, low = [], None, []
    for s in samples(path):
        if s["w"] is None or s["usage"] is None:
            continue
        if s["w"] >= heavy_w:
            heavy, low = s, []
            continue
        if heavy and s["w"] < low_w and s["usage"] >= busy_pct and (low or s["t"] - heavy["t"] <= window):
            low.append(s)
            if low[-1]["t"] - low[0]["t"] >= min_low and not (events and low[0]["t"] - events[-1]["low"]["t"] < gap):
                events.append({"heavy": heavy, "low": low[0], "peak_clock": max(x["clock"] or 0 for x in low)})
            continue
        if low:
            if events and events[-1]["low"] is low[0]:
                events[-1]["seconds"] = low[-1]["t"] - low[0]["t"]
            heavy, low = None, []
    for e in events:
        e.setdefault("seconds", None)
    return events


def report(events):
    rows = ["heavy_time,heavy_mhz,heavy_mv,heavy_w,heavy_temp_c,hang_time,hang_w,hang_usage,peak_mhz_after,low_seconds"]
    for e in events:
        h, l = e["heavy"], e["low"]
        rows.append("%s,%s,%s,%s,%s,%s,%s,%s,%s,%s" % (
            h["label"], _i(h["clock"]), _i(h["mv"]), _i(h["w"]), _i(h["temp"]), l["label"], _i(l["w"]), _i(l["usage"]),
            _i(e["peak_clock"]), "" if e["seconds"] is None else "%.1f" % e["seconds"]))
    return "\n".join(rows)


def _i(x):
    return "" if x is None else "%.0f" % x
