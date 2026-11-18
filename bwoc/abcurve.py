"""MSI Afterburner V/F curve profiles: read, decode, encode, write.

Afterburner keeps one .cfg file per card in its Profiles folder. Each [ProfileN] section has a VFCurve= line:
a hex blob of a 12-byte header (uint32 format, uint32 point count, uint32 zero), then per point three
little-endian floats (voltage mV, base clock MHz, offset MHz), then zero padding. The padding is kept as is.
Only the work profile (default 5) is ever written; every other profile is left untouched.
"""
import re
import struct
import time


def read(path):
    return open(path, encoding="latin-1").read()


def section(text, name):
    return re.search(r"(?ms)^\[%s\]\r?\n(.*?)(?=^\[|\Z)" % re.escape(name), text)


def decode(blob_hex):
    """-> (header bytes, [[mV, base MHz, offset MHz], ...], padding bytes)."""
    h = bytes.fromhex(blob_hex)
    count = struct.unpack("<I", h[4:8])[0]
    end = 12 + count * 12
    pts = [list(struct.unpack("<fff", h[12 + i * 12:24 + i * 12])) for i in range(count)]
    return h[:12], pts, h[end:]


def encode(head, pts, pad=b""):
    return (head + b"".join(struct.pack("<fff", *p) for p in pts) + pad).hex().upper()


def curve(text, profile=1):
    s = section(text, "Profile%d" % profile)
    m = s and re.search(r"VFCurve=([0-9A-Fa-f]+)", s.group(1))
    if not m:
        raise SystemExit("Profile%d has no VFCurve: save a curve to that slot in Afterburner first" % profile)
    return decode(m.group(1))


def base_at(pts, mv):
    """Factory (base) clock of the curve point nearest to mv."""
    return int(round(min(pts, key=lambda p: abs(p[0] - mv))[1]))


def monotonic(target):
    """{mV: MHz} -> the same with every point capped at the lowest clock of any higher-voltage point (suffix
    minimum). Raising one voltage band above the band over it makes the curve non-monotonic; the driver then picks
    clocks that do not follow the bands, and hangs get blamed on the wrong band."""
    out, m = {}, float("inf")
    for v in sorted(target, reverse=True):
        m = min(m, target[v])
        out[v] = m
    return out


def softcap(pts, cap, below=1060):
    """Offsets {mV: MHz} for a soft cap: the source curve (base + its offset) with every point at or under `below` mV
    held to at most `cap` MHz and the points above left as they are, so light loads still reach the top of the curve
    at higher voltage while heavy scenes stop at the cap on a flat stretch."""
    tgt = {round(v): (min(b + o, cap) if round(v) <= below else b + o) for v, b, o in pts}
    tgt = monotonic(tgt)
    return {round(v): tgt[round(v)] - b for v, b, _ in pts}


def build(text, offset_fn, source=1, work=5, power=100, vboost=100, mem_mhz=0):
    """The profile file text with the work slot replaced: source slot's curve, offset_fn(mV, base) per point."""
    head, pts, pad = curve(text, source)
    for p in pts:
        p[2] = float(offset_fn(p[0], p[1]))
    body = ("Format=2\r\nCoreVoltageBoost=%d\r\nPowerLimit=%d\r\nThermalLimit=\r\nThermalPrioritize=\r\n"
            "CoreClkBoost=%d\r\nVFCurve=%s\r\nMemClkBoost=%d\r\nFanMode=\r\nFanSpeed=\r\nFanMode2=\r\nFanSpeed2=\r\n") % (
        vboost, power, int(round(pts[len(pts) // 2][2])) * 1000, encode(head, pts, pad), mem_mhz * 1000)
    s = section(text, "Profile%d" % work)
    if s:
        return text[:s.start(1)] + body + text[s.end(1):]
    return text.rstrip("\r\n") + "\r\n[Profile%d]\r\n" % work + body


def write_work(cfg, elevated, offset_fn, apply=True):
    """Stage the new file, install it (admin), optionally apply the work profile. Returns True on success."""
    a = lambda k: cfg.int("afterburner", k)  # noqa: E731
    work, source = a("work_profile"), a("source_profile")
    if work == source:
        raise SystemExit("work_profile must differ from source_profile")
    text = build(read(cfg.profile_file()), offset_fn, source, work, a("power_limit"), a("voltage_boost"),
                 a("mem_offset_mhz"))
    staged = elevated.staged_path()
    open(staged, "w", encoding="latin-1", newline="").write(text)
    ok = elevated.install(staged) and (elevated.apply(work) if apply else True)
    time.sleep(4)
    return ok


def show(text, profile=1, lo=800, hi=1250, every=1):
    _, pts, _ = curve(text, profile)
    rows = [p for p in pts if lo <= p[0] <= hi][::every]
    return "%d points in Profile%d\n" % (len(pts), profile) + "\n".join(
        "%6.0f mV  base %5.0f MHz  offset %+5.0f  -> %5.0f MHz" % (v, f, o, f + o) for v, f, o in rows)
