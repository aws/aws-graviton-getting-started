#!/usr/bin/env python3
"""
Compare two price dumps produced by `pricer --dump` and report how they differ.

Usage:
  compare.py A.bin B.bin [--abs-tol X] [--rel-tol X] [--ulp-tol X] [--net-tol X]

Without tolerances the script only reports. With one or more tolerances it
also checks them and exits 1 if any is exceeded, so it can gate a CI job.

  --abs-tol   largest allowed absolute difference on any single price
  --rel-tol   largest allowed relative difference on any single price
  --ulp-tol   largest allowed difference in units in the last place (double)
  --net-tol   largest allowed absolute difference between the two book totals
"""
import argparse
import array
import math
import struct
import sys

def load(path):
    a = array.array("d")
    with open(path, "rb") as f:
        a.frombytes(f.read())
    if sys.byteorder != "little":
        a.byteswap()
    return a

def ulp_distance(a, b):
    """Number of representable doubles between a and b (0 if equal)."""
    if a == b:
        return 0
    ia = struct.unpack("<q", struct.pack("<d", a))[0]
    ib = struct.unpack("<q", struct.pack("<d", b))[0]
    # Map the sign-magnitude integer layout onto a monotonic scale.
    if ia < 0: ia = -(ia & 0x7FFFFFFFFFFFFFFF)
    if ib < 0: ib = -(ib & 0x7FFFFFFFFFFFFFFF)
    return abs(ia - ib)

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--abs-tol", type=float)
    p.add_argument("--rel-tol", type=float)
    p.add_argument("--ulp-tol", type=float)
    p.add_argument("--net-tol", type=float)
    args = p.parse_args()

    xa, xb = load(args.a), load(args.b)
    if len(xa) != len(xb):
        print(f"error: {args.a} has {len(xa)} prices, {args.b} has {len(xb)}", file=sys.stderr)
        return 2
    n = len(xa)

    n_diff = 0
    max_abs = 0.0
    max_abs_at = 0.0
    max_rel = 0.0
    max_rel_at = 0.0
    max_ulp = 0
    max_ulp_at = 0.0
    sum_a = 0.0
    sum_b = 0.0
    sum_abs_diff = 0.0

    for a, b in zip(xa, xb):
        sum_a += a
        sum_b += b
        d = abs(a - b)
        if d == 0.0:
            continue
        n_diff += 1
        sum_abs_diff += d
        if d > max_abs:
            max_abs, max_abs_at = d, a
        if a != 0.0 and d / abs(a) > max_rel:
            max_rel, max_rel_at = d / abs(a), a
        u = ulp_distance(a, b)
        if u > max_ulp:
            max_ulp, max_ulp_at = u, a

    net = abs(sum_a - sum_b)

    print(f"prices compared              : {n:,}")
    print(f"prices that differ           : {n_diff:,} ({100.0 * n_diff / n:.3f}%)")
    if n_diff:
        print(f"largest absolute difference  : {max_abs:.3e} (on a price of {max_abs_at:.6f})")
        print(f"largest relative difference  : {max_rel:.3e} (on a price of {max_rel_at:.6e})")
        print(f"largest ULP distance         : {max_ulp} (on a price of {max_ulp_at:.6e})")
        print(f"sum of absolute differences  : {sum_abs_diff:.6e}")
    print(f"book total A                 : {sum_a:.6f}")
    print(f"book total B                 : {sum_b:.6f}")
    print(f"book total difference (net)  : {net:.6e}")

    checks = [
        ("abs-tol", args.abs_tol, max_abs),
        ("rel-tol", args.rel_tol, max_rel),
        ("ulp-tol", args.ulp_tol, float(max_ulp)),
        ("net-tol", args.net_tol, net),
    ]
    enforced = [(name, tol, val) for name, tol, val in checks if tol is not None]
    if not enforced:
        return 0

    print()
    failed = False
    for name, tol, val in enforced:
        ok = val <= tol
        failed |= not ok
        print(f"{name:<8} {val:.3e} <= {tol:.3e}  {'PASS' if ok else 'FAIL'}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
