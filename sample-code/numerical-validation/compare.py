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

A NaN or infinity on only one side, or a difference that is not finite, is a
mismatch no tolerance can bound, so it always fails the check regardless of
the tolerances given.

Exit codes:
  0  success: no tolerances given, or every tolerance met
  1  a tolerance was exceeded, or a non-finite difference was found
  2  usage or input error (bad arguments, missing or malformed dump)
"""
import argparse
import array
import math
import struct
import sys

def load(path):
    """Read a dump of raw little-endian doubles. Raises ValueError on a size
    that is not a whole number of doubles, OSError if the file is unreadable."""
    a = array.array("d")
    with open(path, "rb") as f:
        raw = f.read()
    if len(raw) % a.itemsize != 0:
        raise ValueError(f"{path}: {len(raw)} bytes is not a multiple of {a.itemsize}")
    a.frombytes(raw)
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

    try:
        xa, xb = load(args.a), load(args.b)
    except OSError as e:
        print(f"error: cannot read dump: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if len(xa) != len(xb):
        print(f"error: {args.a} has {len(xa)} prices, {args.b} has {len(xb)}", file=sys.stderr)
        return 2
    n = len(xa)
    if n == 0:
        print("error: dumps are empty", file=sys.stderr)
        return 2

    n_diff = 0
    n_nonfinite = 0
    nonfinite_at = None
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

        # A NaN or infinity cannot be bounded by a numeric tolerance. Compare
        # these by value, not by bits: two NaNs are equal regardless of payload
        # or sign (x86 and arm64 emit different NaN encodings for the same
        # invalid operation, which is not a result difference), and infinities
        # are equal when they have the same sign. Any other non-finite pairing
        # (NaN vs a number, +inf vs -inf, inf vs a finite value) is a mismatch
        # that fails the check.
        a_nan, b_nan = math.isnan(a), math.isnan(b)
        if a_nan or b_nan or math.isinf(a) or math.isinf(b):
            if a_nan and b_nan:
                equal = True            # both NaN: equal by value
            elif a_nan or b_nan:
                equal = False           # exactly one NaN
            else:
                equal = (a == b)        # inf vs inf/finite: +inf==+inf only
            if not equal:
                n_diff += 1
                n_nonfinite += 1
                if nonfinite_at is None:
                    nonfinite_at = (a, b)
            continue

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
    if n_nonfinite:
        a0, b0 = nonfinite_at
        print(f"non-finite mismatches        : {n_nonfinite:,} (first: {a0!r} vs {b0!r})")
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
        # Report-only mode. A non-finite mismatch is still a hard error, so
        # it fails even when no tolerance was asked for.
        return 1 if n_nonfinite else 0

    print()
    failed = False
    for name, tol, val in enforced:
        ok = val <= tol
        failed |= not ok
        print(f"{name:<8} {val:.3e} <= {tol:.3e}  {'PASS' if ok else 'FAIL'}")
    if n_nonfinite:
        failed = True
        print(f"{'nonfinite':<8} {n_nonfinite} mismatch(es)        FAIL")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
