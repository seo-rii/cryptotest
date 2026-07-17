#!/usr/bin/env python3
"""Z3 bit-vector tail-lock prototype for challenge 7."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import z3


P_BITS = 1024
PRODUCT_BITS = 2048
X0_OFFSET = 150
X7_OFFSET = 920
ROOT = Path(__file__).resolve().parents[1]


def parse_bit_range_value(text: str) -> tuple[int, int, int]:
    try:
        start_text, width_text, value_text = text.split(":", 2)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH:VALUE") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    value = int(value_text, 0)
    if start < 0 or width <= 0 or start + width > P_BITS:
        raise argparse.ArgumentTypeError("invalid bit range")
    if value < 0 or value >= (1 << width):
        raise argparse.ArgumentTypeError("value does not fit selected width")
    return start, width, value


def common_prefix_from_interval(lo: int, hi: int, bits: int = P_BITS) -> tuple[int, int, int]:
    if lo > hi:
        lo, hi = hi, lo
    diff = lo ^ hi
    prefix_len = bits if diff == 0 else bits - diff.bit_length()
    suffix_start = bits - prefix_len
    return prefix_len, lo >> suffix_start, suffix_start


def load_constants():
    spec = importlib.util.spec_from_file_location(
        "investigate_07", ROOT / "solutions" / "investigate_07_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def int_to_bytes(value: int) -> bytes:
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--T", type=int, default=784)
    parser.add_argument("--limb-bits", type=int, default=16)
    parser.add_argument("--tail-limbs", type=int, default=16)
    parser.add_argument("--branch-low", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--branch-high", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_bit_range_value)
    parser.add_argument("--fix-q-range", action="append", default=[], type=parse_bit_range_value)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--no-q-interval-bound", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--json-summary", action="store_true")
    args = parser.parse_args()

    if not (1 <= args.T <= P_BITS):
        raise SystemExit("--T must be in 1..1024")
    if args.T % args.limb_bits != 0:
        raise SystemExit("--T must be divisible by --limb-bits")
    if args.tail_limbs < 0:
        raise SystemExit("--tail-limbs must be non-negative")
    if not (0 <= args.branch_low < 16 and 0 <= args.branch_high < 16):
        raise SystemExit("branch nibbles must be in 0..15")

    constants = load_constants()
    n = int(constants.N_HEX.replace(" ", ""), 16)
    ct = int(constants.CT_HEX.replace(" ", ""), 16)
    e = int(constants.E)
    mask = int(constants.MASK_HEX.replace(" ", ""), 16)
    known = int(constants.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    full_mask = (1 << P_BITS) - 1

    branch_known = known | (args.branch_low << X0_OFFSET) | (args.branch_high << X7_OFFSET)
    branch_mask = mask | (0xF << X0_OFFSET) | (0xF << X7_OFFSET)
    for fixed_start, fixed_width, fixed_value in args.fix_p_range:
        fixed_mask = ((1 << fixed_width) - 1) << fixed_start
        fixed_bits = fixed_value << fixed_start
        if ((branch_known ^ fixed_bits) & (branch_mask & fixed_mask)) != 0:
            raise SystemExit(f"inconsistent --fix-p-range {fixed_start}:{fixed_width}:{fixed_value:#x}")
        branch_known |= fixed_bits
        branch_mask |= fixed_mask

    branch_unknown_mask = full_mask ^ branch_mask
    p_unknown_above_t = (branch_unknown_mask >> args.T).bit_count()
    if p_unknown_above_t:
        raise SystemExit(f"p tail is not fully known above T; unknown bits above T = {p_unknown_above_t}")

    p_min = branch_known
    p_max = branch_known | branch_unknown_mask
    q_min = n // p_max
    q_max = n // p_min
    q_prefix_bits, q_prefix, q_prefix_start = common_prefix_from_interval(q_min, q_max)

    if branch_unknown_mask:
        low_known_bits = (branch_unknown_mask & -branch_unknown_mask).bit_length() - 1
    else:
        low_known_bits = P_BITS
    low_known_bits = min(low_known_bits, args.T)
    low_modulus = 1 << low_known_bits
    q_low_known = (n * pow(branch_known & (low_modulus - 1), -1, low_modulus)) % low_modulus

    q_global_known_mask = (1 << low_known_bits) - 1
    q_global_known = q_low_known
    if q_prefix_bits > 0:
        prefix_mask = ((1 << q_prefix_bits) - 1) << q_prefix_start
        prefix_value = q_prefix << q_prefix_start
        if ((q_global_known ^ prefix_value) & (q_global_known_mask & prefix_mask)) != 0:
            raise SystemExit("inconsistent q low/high fixed bits")
        q_global_known |= prefix_value
        q_global_known_mask |= prefix_mask
    for fixed_start, fixed_width, fixed_value in args.fix_q_range:
        fixed_mask = ((1 << fixed_width) - 1) << fixed_start
        fixed_bits = fixed_value << fixed_start
        if ((q_global_known ^ fixed_bits) & (q_global_known_mask & fixed_mask)) != 0:
            raise SystemExit(f"inconsistent --fix-q-range {fixed_start}:{fixed_width}:{fixed_value:#x}")
        q_global_known |= fixed_bits
        q_global_known_mask |= fixed_mask

    q_tail_width = P_BITS - args.T
    q_high_known_mask = (q_global_known_mask >> args.T) & ((1 << q_tail_width) - 1)
    q_unknown_above_t = q_tail_width - q_high_known_mask.bit_count()
    if q_unknown_above_t:
        raise SystemExit(f"q tail is not fully known above T; unknown bits above T = {q_unknown_above_t}")

    q_high = q_global_known >> args.T
    p_high = branch_known >> args.T
    q_low_min = max(0, q_min - (q_high << args.T))
    q_low_max = min((1 << args.T) - 1, q_max - (q_high << args.T))
    if q_low_min > q_low_max:
        raise SystemExit("q interval does not intersect selected q high prefix")

    lower_mask = (1 << args.T) - 1
    p_known_mask = branch_mask & lower_mask
    p_known_value = branch_known & lower_mask
    q_known_mask = q_global_known_mask & lower_mask
    q_known_value = q_global_known & lower_mask
    check_bits = min(PRODUCT_BITS, args.T + args.tail_limbs * args.limb_bits)
    high_width = check_bits - args.T
    check_mask = (1 << check_bits) - 1

    p_low = z3.BitVec("p_low", args.T)
    q_low = z3.BitVec("q_low", args.T)
    solver = z3.SolverFor("QF_BV")
    solver.set(timeout=max(1, int(args.time_limit * 1000)))

    solver.add((p_low & z3.BitVecVal(p_known_mask, args.T)) == z3.BitVecVal(p_known_value, args.T))
    solver.add((q_low & z3.BitVecVal(q_known_mask, args.T)) == z3.BitVecVal(q_known_value, args.T))
    if not args.no_q_interval_bound:
        solver.add(z3.UGE(q_low, z3.BitVecVal(q_low_min, args.T)))
        solver.add(z3.ULE(q_low, z3.BitVecVal(q_low_max, args.T)))

    p_mod_check = z3.ZeroExt(high_width, p_low) | z3.BitVecVal((p_high << args.T) & check_mask, check_bits)
    q_mod_check = z3.ZeroExt(high_width, q_low) | z3.BitVecVal((q_high << args.T) & check_mask, check_bits)
    solver.add(p_mod_check * q_mod_check == z3.BitVecVal(n & check_mask, check_bits))

    summary: dict[str, object] = {
        "T": args.T,
        "tail_limbs": args.tail_limbs,
        "check_bits": check_bits,
        "branch_low": args.branch_low,
        "branch_high": args.branch_high,
        "fixed_p_ranges": [
            {"start": start, "width": width, "value": value}
            for start, width, value in args.fix_p_range
        ],
        "fixed_q_ranges": [
            {"start": start, "width": width, "value": value}
            for start, width, value in args.fix_q_range
        ],
        "p_unknown_bools_in_T": args.T - p_known_mask.bit_count(),
        "q_bools_in_T": args.T - q_known_mask.bit_count(),
        "q_fixed_bits_in_T": q_known_mask.bit_count(),
        "q_high_common_bits": q_prefix_bits,
        "q_prefix_start": q_prefix_start,
        "q_prefix_bits_inside_T": max(0, args.T - q_prefix_start),
    }

    print(f"T={args.T}")
    print(f"tail limbs: {args.tail_limbs}")
    print(f"check bits: {check_bits}")
    print(f"p unknown bools in T: {summary['p_unknown_bools_in_T']}")
    print(f"q bools in T: {summary['q_bools_in_T']}")
    print(f"q fixed bits in T: {summary['q_fixed_bits_in_T']}")
    print(f"q prefix start: {q_prefix_start}")
    print(f"q prefix bits inside T: {summary['q_prefix_bits_inside_T']}")
    if args.build_only:
        summary["status"] = "BUILD_ONLY"
        if args.json_summary:
            print(json.dumps(summary, sort_keys=True))
        return 0

    result = solver.check()
    summary["status"] = str(result).upper()
    print(f"status: {result}")

    if result == z3.sat:
        model = solver.model()
        p_low_value = model.eval(p_low, model_completion=True).as_long()
        q_low_value = model.eval(q_low, model_completion=True).as_long()
        p_candidate = p_low_value | (p_high << args.T)
        q_candidate = q_low_value | (q_high << args.T)
        product_matches = p_candidate * q_candidate == n
        p_divides = p_candidate > 1 and n % p_candidate == 0
        summary.update(
            {
                "candidate_product_matches": product_matches,
                "candidate_p_divides": p_divides,
                "candidate_p_bits": p_candidate.bit_length(),
                "candidate_q_bits": q_candidate.bit_length(),
            }
        )
        print(f"candidate product matches N: {product_matches}")
        print(f"candidate p divides N: {p_divides}")
        if p_divides:
            q_factor = n // p_candidate
            phi = (p_candidate - 1) * (q_factor - 1)
            d = pow(e, -1, phi)
            plaintext = pow(ct, d, n)
            plaintext_bytes = int_to_bytes(plaintext)
            summary.update(
                {
                    "p": hex(p_candidate),
                    "q": hex(q_factor),
                    "plaintext_hex": plaintext_bytes.hex(),
                }
            )
            print("[+] FACTORED")
            print(f"p = {hex(p_candidate)}")
            print(f"q = {hex(q_factor)}")
            print(f"plaintext hex = {plaintext_bytes.hex()}")

    if args.json_summary:
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
