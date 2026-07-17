#!/usr/bin/env python3
"""Three-variable exact integer-root attempt for challenge 7.

This is the next model after the folded bivariate Coron probe.  It keeps the
known 440..599 p window instead of folding p into one huge middle variable:

    p = p_low210 + 2^210*x + known_440_599 + 2^600*z + p_high830
    q = q_low210 + 2^210*y + q_high*2^H

The equation is exact over the integers: p(x,z) * q(y) - N = 0.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from sage.all import PolynomialRing, ZZ, inverse_mod

from solve_07_hybrid_coron import common_prefix_from_interval, int_to_bytes, load_constants, parse_range_list


DEFAULT_CRYPTO_ATTACKS = Path("/tmp/crypto-attacks")
P_BITS = 1024
LOW_BITS = 210
MID_START = 440
MID_END = 600
HIGH_START = 830
X0_OFFSET = 150
X7_OFFSET = 920


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crypto-attacks", type=Path, default=DEFAULT_CRYPTO_ATTACKS)
    parser.add_argument("--branch-low", type=lambda value: int(value, 0), help="fixed x0 nibble")
    parser.add_argument("--branch-high", type=lambda value: int(value, 0), help="fixed x7 nibble")
    parser.add_argument("--m-values", default="1,2", help="comma/range list, e.g. 1-3")
    parser.add_argument(
        "--strategy",
        choices=["basic", "extended", "ext_x", "ext_z", "ext_y", "ext_xz", "ext_xy", "ext_zy", "ernst1", "ernst2"],
        default="basic",
    )
    parser.add_argument("--t-values", default="0", help="extended/Ernst t values, comma/range list")
    parser.add_argument("--roots-method", choices=["groebner", "resultants", "variety"], default="groebner")
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument("--max-branches", type=int)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not args.crypto_attacks.exists():
        raise SystemExit(f"{args.crypto_attacks} does not exist")
    sys.path.insert(0, str(args.crypto_attacks))

    from shared.small_roots import jochemsz_may_integer

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    constants = load_constants()
    n = ZZ(int(constants.N_HEX.replace(" ", ""), 16))
    e = int(constants.E)
    ct = int(constants.CT_HEX.replace(" ", ""), 16)
    mask = ZZ(int(constants.MASK_HEX.replace(" ", ""), 16))
    known = ZZ(int(constants.P_AND_MASK_HEX.replace(" ", ""), 16)) & mask
    unknown_mask = ((ZZ(1) << P_BITS) - 1) ^ mask

    ring = PolynomialRing(ZZ, names=("x", "z", "y"))
    x, z, y = ring.gens()
    low_mask = (ZZ(1) << LOW_BITS) - 1
    full_mask = (ZZ(1) << P_BITS) - 1
    mid_known_mask = ((ZZ(1) << (MID_END - MID_START)) - 1) << MID_START
    high_mask = full_mask ^ ((ZZ(1) << HIGH_START) - 1)
    x_bound = ZZ(1) << (MID_START - LOW_BITS)
    z_bound = ZZ(1) << (HIGH_START - MID_END)

    inspected = 0
    jm_runs = 0
    started_all = time.time()

    for x0_value in ([args.branch_low] if args.branch_low is not None else range(16)):
        for x7_value in ([args.branch_high] if args.branch_high is not None else range(16)):
            if args.max_branches is not None and inspected >= args.max_branches:
                print("[+] reached --max-branches", flush=True)
                print(f"[+] inspected={inspected}, jm_runs={jm_runs}", flush=True)
                return 1

            fixed = known
            fixed |= ZZ(x0_value) << X0_OFFSET
            fixed |= ZZ(x7_value) << X7_OFFSET
            guessed_mask = ((ZZ(1) << 4) - 1) << X0_OFFSET
            guessed_mask |= ((ZZ(1) << 4) - 1) << X7_OFFSET
            remaining_mask = unknown_mask & (full_mask ^ guessed_mask)
            p_min = fixed
            p_max = fixed | remaining_mask
            q_min = n // p_max
            q_max = n // p_min
            q_prefix_bits, q_high, q_high_start = common_prefix_from_interval(q_min, q_max)
            if q_high_start <= LOW_BITS:
                continue

            p_low = fixed & low_mask
            q_low = (n * inverse_mod(p_low, ZZ(1) << LOW_BITS)) % (ZZ(1) << LOW_BITS)
            p_mid_known = fixed & mid_known_mask
            p_high = fixed & high_mask
            y_bound = ZZ(1) << (q_high_start - LOW_BITS)
            p_expr = p_low + (ZZ(1) << LOW_BITS) * x + p_mid_known + (ZZ(1) << MID_END) * z + p_high
            q_expr = q_low + (ZZ(1) << LOW_BITS) * y + (ZZ(q_high) << q_high_start)
            poly = ring(p_expr * q_expr - n)
            weighted_norm = ZZ(0)
            for exponent, coefficient in poly.dict().items():
                coefficient = ZZ(coefficient)
                if coefficient == 0:
                    continue
                weighted_norm = max(
                    weighted_norm,
                    abs(coefficient)
                    * (x_bound ** exponent[0])
                    * (z_bound ** exponent[1])
                    * (y_bound ** exponent[2]),
                )

            inspected += 1
            print(
                f"[branch] #{inspected} x0={x0_value:x} x7={x7_value:x} "
                f"hq={q_prefix_bits} Xbits={x_bound.nbits() - 1} "
                f"Zbits={z_bound.nbits() - 1} Ybits={y_bound.nbits() - 1} "
                f"Wbits={weighted_norm.nbits()} terms={len(poly.dict())}",
                flush=True,
            )
            if args.diagnose_only:
                continue

            for m in parse_range_list(args.m_values):
                for t in parse_range_list(args.t_values):
                    if args.strategy == "basic":
                        strategy = jochemsz_may_integer.BasicStrategy()
                    elif args.strategy == "extended":
                        strategy = jochemsz_may_integer.ExtendedStrategy([t, t, t])
                    elif args.strategy == "ext_x":
                        strategy = jochemsz_may_integer.ExtendedStrategy([t, 0, 0])
                    elif args.strategy == "ext_z":
                        strategy = jochemsz_may_integer.ExtendedStrategy([0, t, 0])
                    elif args.strategy == "ext_y":
                        strategy = jochemsz_may_integer.ExtendedStrategy([0, 0, t])
                    elif args.strategy == "ext_xz":
                        strategy = jochemsz_may_integer.ExtendedStrategy([t, t, 0])
                    elif args.strategy == "ext_xy":
                        strategy = jochemsz_may_integer.ExtendedStrategy([t, 0, t])
                    elif args.strategy == "ext_zy":
                        strategy = jochemsz_may_integer.ExtendedStrategy([0, t, t])
                    elif args.strategy == "ernst1":
                        strategy = jochemsz_may_integer.Ernst1Strategy(t)
                    else:
                        strategy = jochemsz_may_integer.Ernst2Strategy(t)

                    jm_runs += 1
                    print(f"  [*] JM m={m} strategy={args.strategy} t={t}", flush=True)
                    started = time.time()
                    try:
                        roots = jochemsz_may_integer.integer_multivariate(
                            poly,
                            m,
                            weighted_norm,
                            [x_bound, z_bound, y_bound],
                            strategy,
                            roots_method=args.roots_method,
                        )
                        for x_root, z_root, y_root in roots:
                            x_root = ZZ(x_root)
                            z_root = ZZ(z_root)
                            y_root = ZZ(y_root)
                            if not (0 <= x_root < x_bound and 0 <= z_root < z_bound and 0 <= y_root < y_bound):
                                continue
                            p = ZZ(p_expr(x_root, z_root, y_root))
                            if p <= 1 or n % p != 0:
                                continue
                            if (p & mask) != known:
                                continue
                            q = n // p
                            phi = (p - 1) * (q - 1)
                            d = inverse_mod(e, phi)
                            plaintext_int = ZZ(pow(int(ct), int(d), int(n)))
                            assert pow(int(plaintext_int), e, int(n)) == int(ct)
                            print("[+] FACTORED")
                            print(f"p = {int(p):#x}")
                            print(f"q = {int(q):#x}")
                            print(f"[+] plaintext bytes = {int_to_bytes(int(plaintext_int))!r}")
                            return 0
                    except Exception as exc:  # noqa: BLE001 - investigation script should continue.
                        print(f"  [!] failed: {type(exc).__name__}: {exc}", flush=True)
                    elapsed = time.time() - started
                    print(f"  [-] no factor, elapsed={elapsed:.2f}s", flush=True)

    elapsed_all = time.time() - started_all
    print(f"[-] not found; inspected={inspected}, jm_runs={jm_runs}, elapsed={elapsed_all:.2f}s", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
