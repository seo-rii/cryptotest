#!/usr/bin/env python3
"""Diagnose folded Coron margins after fixing edge runs x1 and x6."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from sage.all import PolynomialRing, ZZ, gcd, inverse_mod


ROOT = Path(__file__).resolve().parents[1]
P_BITS = 1024
X0_OFFSET = 150
X1_OFFSET = 210
X6_OFFSET = 784
X7_OFFSET = 920
X1_BITS = 39
X6_BITS = 46


def load_constants():
    spec = importlib.util.spec_from_file_location(
        "investigate_07", ROOT / "solutions" / "investigate_07_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def common_prefix_from_interval(lo: int, hi: int, bits: int = P_BITS) -> tuple[int, int, int]:
    lo = int(lo)
    hi = int(hi)
    if lo > hi:
        lo, hi = hi, lo
    diff = lo ^ hi
    prefix_len = bits if diff == 0 else bits - diff.bit_length()
    suffix_start = bits - prefix_len
    return prefix_len, lo >> suffix_start, suffix_start


def weighted_norm_bits(poly, x_bound: int, y_bound: int) -> int:
    x_bits = ZZ(x_bound).nbits() - 1
    y_bits = ZZ(y_bound).nbits() - 1
    best = 0
    for (i, j), coeff in poly.dict().items():
        coeff = ZZ(coeff)
        if coeff:
            best = max(best, abs(coeff).nbits() + i * x_bits + j * y_bits)
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x0", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--x7", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--x1", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--x6", type=lambda value: int(value, 0), default=0)
    args = parser.parse_args()

    if not (0 <= args.x0 < 16 and 0 <= args.x7 < 16):
        raise SystemExit("x0 and x7 must be nibbles")
    if not (0 <= args.x1 < (1 << X1_BITS)):
        raise SystemExit("x1 outside 39-bit range")
    if not (0 <= args.x6 < (1 << X6_BITS)):
        raise SystemExit("x6 outside 46-bit range")

    c7 = load_constants()
    n = ZZ(int(c7.N_HEX.replace(" ", ""), 16))
    mask = ZZ(int(c7.MASK_HEX.replace(" ", ""), 16))
    known = ZZ(int(c7.P_AND_MASK_HEX.replace(" ", ""), 16)) & mask
    unknown_mask = ((ZZ(1) << P_BITS) - 1) ^ mask

    fixed = ZZ(known)
    fixed |= ZZ(args.x0) << X0_OFFSET
    fixed |= ZZ(args.x1) << X1_OFFSET
    fixed |= ZZ(args.x6) << X6_OFFSET
    fixed |= ZZ(args.x7) << X7_OFFSET

    guessed_mask = ZZ(0)
    guessed_mask |= ((ZZ(1) << 4) - 1) << X0_OFFSET
    guessed_mask |= ((ZZ(1) << X1_BITS) - 1) << X1_OFFSET
    guessed_mask |= ((ZZ(1) << X6_BITS) - 1) << X6_OFFSET
    guessed_mask |= ((ZZ(1) << 4) - 1) << X7_OFFSET

    remaining_mask = unknown_mask & (((ZZ(1) << P_BITS) - 1) ^ guessed_mask)
    p_min = fixed
    p_max = fixed | remaining_mask
    q_min = n // p_max
    q_max = n // p_min
    q_prefix_bits, q_high, q_high_start = common_prefix_from_interval(q_min, q_max)

    low_bits = 265
    p_hi_start = 769
    p_low = fixed & ((ZZ(1) << low_bits) - 1)
    q_low = (n * inverse_mod(p_low, ZZ(1) << low_bits)) % (ZZ(1) << low_bits)
    p_high = fixed >> p_hi_start
    x_bound = ZZ(1) << (p_hi_start - low_bits)
    y_bound = ZZ(1) << (q_high_start - low_bits)

    ring = PolynomialRing(ZZ, names=("x", "y"))
    x, y = ring.gens()
    p_expr = ZZ(p_low) + (ZZ(1) << low_bits) * x + (ZZ(p_high) << p_hi_start)
    q_expr = ZZ(q_low) + (ZZ(1) << low_bits) * y + (ZZ(q_high) << q_high_start)
    poly = ring(p_expr * q_expr - n)

    content = ZZ(0)
    for coeff in poly.dict().values():
        content = gcd(content, abs(ZZ(coeff)))
    primitive = ring(0)
    for monomial, coeff in poly.dict().items():
        term = ZZ(coeff) // content
        for gen, exponent in zip(ring.gens(), monomial):
            term *= gen**exponent
        primitive += term

    x_bits = x_bound.nbits() - 1
    y_bits = y_bound.nbits() - 1
    w_raw = weighted_norm_bits(poly, x_bound, y_bound)
    w_prim = weighted_norm_bits(primitive, x_bound, y_bound)
    raw_margin = (2.0 * w_raw / 3.0) - (x_bits + y_bits)
    primitive_margin = (2.0 * w_prim / 3.0) - (x_bits + y_bits)

    print(f"x0={args.x0:x} x1={args.x1:#x} x6={args.x6:#x} x7={args.x7:x}")
    print(f"low_bits={low_bits} p_hi_start={p_hi_start} q_high_start={q_high_start}")
    print(f"q_prefix_bits={q_prefix_bits}")
    print(f"Xbits={x_bits} Ybits={y_bits}")
    print(
        f"Wraw={w_raw} Wprim={w_prim} "
        f"content_bits={content.nbits() - 1} v2={content.valuation(2)}"
    )
    print(f"raw_margin={raw_margin:.2f} primitive_margin={primitive_margin:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
