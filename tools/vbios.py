#!/usr/bin/env python3
"""Offline VBIOS edit and check workflow around Panchovix's Vix Editor command line (nvbios). See docs/VBIOS.md.

Nothing here touches the GPU. The editor runs with no network access (a private network namespace through
`unshare -rn` on Linux or WSL; set BWOC_OFFLINE="" to run it as is, or to another wrapper command).

  vbios.py check ROM                  size, SHA-256 and the editor's own integrity check; warns on a truncated dump
  vbios.py fields ROM [-o OUT.json]   every field the editor knows, with its current value
  vbios.py edit SRC OUT --set k=v ... make the edit, then diff every field of SRC and OUT and fail if anything changed
                                      that was not asked for (or that the editor did not list as a linked field)
  vbios.py diff A B                   field diff and byte count between two images

Environment:
  NVBIOS        path to the editor's command line binary (default: nvbios on PATH)
  BWOC_OFFLINE  wrapper that cuts network access (default: "unshare -rn"; empty = none)
"""
import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys

# A full RTX 5090 (GB202) image saved with nvflash --save; NvAPI_GPU_GetVbiosImage returned only 458,240 bytes.
KNOWN_FULL = {"10de:2b85": 1961983}


def editor(*argv):
    exe = os.environ.get("NVBIOS") or shutil.which("nvbios")
    if not exe:
        sys.exit("set NVBIOS to the Vix Editor command line binary")
    wrap = shlex.split(os.environ.get("BWOC_OFFLINE", "unshare -rn"))
    r = subprocess.run(wrap + [exe] + list(argv) + ["--json"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        sys.exit("editor failed (%d): %s %s" % (r.returncode, r.stdout[-500:], r.stderr[-500:]))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def fields(path):
    d = editor("fields", path)
    if not d.get("ok"):
        sys.exit("fields failed: %s" % json.dumps(d)[:500])
    return {f["key"]: f.get("current") for f in d["result"]["fields"]}, d


def diff(a, b):
    fa, fb = fields(a)[0], fields(b)[0]
    changed = {k: (fa.get(k), fb.get(k)) for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)}
    ba, bb = open(a, "rb").read(), open(b, "rb").read()
    nbytes = sum(x != y for x, y in zip(ba, bb)) + abs(len(ba) - len(bb))
    return changed, len(fa), nbytes


def cmd_check(a):
    size = os.path.getsize(a.rom)
    print("size %d bytes, sha256 %s" % (size, sha(a.rom)))
    d = editor("verify", a.rom)
    print(json.dumps(d.get("result", d), indent=1)[:2000])
    ins = editor("inspect", a.rom).get("result", {})
    dev = ins.get("pci_device") or ins.get("identity", {}).get("pci_device")
    want = KNOWN_FULL.get(dev)
    if want and size != want:
        print("WARNING: a full image for %s is %d bytes; this one is %d. A truncated dump (NvAPI) is not editable: "
              "save the image with nvflash --save." % (dev, want, size))


def cmd_fields(a):
    f, raw = fields(a.rom)
    if a.out:
        json.dump(raw, open(a.out, "w"), indent=1)
    for k, v in f.items():
        print("%-40s %s" % (k, v))
    print("%d fields" % len(f))


def cmd_edit(a):
    src_sha = sha(a.src)
    sets = []
    for s in a.set:
        sets += ["--set", s]
    m = editor("edit", "--expect-sha256", src_sha, *sets, a.src, a.out)
    json.dump(m, open(a.out + ".json", "w"), indent=1)
    if not m.get("ok", True) or not os.path.exists(a.out):
        sys.exit("edit failed: %s" % json.dumps(m)[:800])
    res = m.get("result", m)
    linked = {f["field"] for f in res.get("affected_fields", [])}
    asked = {s.split("=", 1)[0] for s in a.set}
    changed, total, nbytes = diff(a.src, a.out)
    print("%d fields compared, %d changed, %d bytes differ" % (total, len(changed), nbytes))
    for k, (x, y) in changed.items():
        tag = "asked" if k in asked else ("linked" if k in linked else "UNEXPECTED")
        print("  %-36s %s -> %s  (%s)" % (k, x, y, tag))
    integ = res.get("integrity", {})
    print("integrity valid: %s (%s)" % (integ.get("valid"), integ.get("scope", "")))
    bad = [k for k in changed if k not in asked and k not in linked] + [k for k in asked if k not in changed]
    if bad or integ.get("valid") is False:
        sys.exit("NOT SAFE TO LOAD: unexpected or missing changes: %s" % bad)
    print("manifest: %s.json; output sha256 %s" % (a.out, sha(a.out)))


def cmd_diff(a):
    changed, total, nbytes = diff(a.a, a.b)
    print("%d fields compared, %d changed, %d bytes differ" % (total, len(changed), nbytes))
    for k, (x, y) in changed.items():
        print("  %-36s %s -> %s" % (k, x, y))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check"); p.add_argument("rom"); p.set_defaults(f=cmd_check)  # noqa: E702
    p = sub.add_parser("fields"); p.add_argument("rom"); p.add_argument("-o", "--out"); p.set_defaults(f=cmd_fields)  # noqa: E702
    p = sub.add_parser("edit"); p.add_argument("src"); p.add_argument("out")  # noqa: E702
    p.add_argument("--set", action="append", required=True, metavar="FIELD=VALUE"); p.set_defaults(f=cmd_edit)  # noqa: E702
    p = sub.add_parser("diff"); p.add_argument("a"); p.add_argument("b"); p.set_defaults(f=cmd_diff)  # noqa: E702
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
