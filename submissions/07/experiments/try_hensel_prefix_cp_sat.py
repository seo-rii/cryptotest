#!/usr/bin/env python3
"""CP-SAT prototype for Hensel prefix filtering in challenge 7.

This model only encodes the lower product recurrence modulo 2^T:

    sum_{j=0..k} p_j q_{k-j} + carry_k = N_k + B*carry_{k+1}

The q bits are not free: low q bits are fixed where p is fully known modulo a
power of two, and q high-prefix bits inside [0, T) are fixed from the p branch
interval.  This is intended as a cube filter before an exact tail model.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from ortools.sat.python import cp_model


P_BITS = 1024
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


def parse_bit_range(text: str) -> tuple[int, int]:
    try:
        start_text, width_text = text.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    if start < 0 or width <= 0 or start + width > P_BITS:
        raise argparse.ArgumentTypeError("invalid bit range")
    return start, width


def common_prefix_from_interval(lo: int, hi: int, bits: int = P_BITS) -> tuple[int, int, int]:
    if lo > hi:
        lo, hi = hi, lo
    diff = lo ^ hi
    prefix_len = bits if diff == 0 else bits - diff.bit_length()
    suffix_start = bits - prefix_len
    return prefix_len, lo >> suffix_start, suffix_start


def load_constants():
    spec = importlib.util.spec_from_file_location(
        "investigate_rsa_partial_bits", ROOT / "src" / "investigate_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--T", type=int, default=924)
    parser.add_argument("--limb-bits", type=int, default=12)
    parser.add_argument("--branch-low", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--branch-high", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_bit_range_value)
    parser.add_argument("--decision-p-range", action="append", default=[], type=parse_bit_range)
    parser.add_argument("--time-limit", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--log", action="store_true")
    args = parser.parse_args()

    if not (1 <= args.T <= P_BITS):
        raise SystemExit("--T must be in 1..1024")
    if args.T % args.limb_bits != 0:
        raise SystemExit("--T must be divisible by --limb-bits for this prototype")
    if not (0 <= args.branch_low < 16 and 0 <= args.branch_high < 16):
        raise SystemExit("branch nibbles must be in 0..15")

    constants = load_constants()
    n = int(constants.N_HEX.replace(" ", ""), 16)
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
    q_low = (n * pow(branch_known & (low_modulus - 1), -1, low_modulus)) % low_modulus

    q_known_mask = (1 << low_known_bits) - 1
    q_known = q_low
    if q_prefix_start < args.T:
        prefix_width = args.T - q_prefix_start
        prefix_mask = ((1 << prefix_width) - 1) << q_prefix_start
        prefix_value = (q_prefix & ((1 << prefix_width) - 1)) << q_prefix_start
        if ((q_known ^ prefix_value) & (q_known_mask & prefix_mask)) != 0:
            raise SystemExit("inconsistent q low/prefix fixed bits")
        q_known |= prefix_value
        q_known_mask |= prefix_mask

    model = cp_model.CpModel()
    base = 1 << args.limb_bits
    limb_mask = base - 1
    limb_count = args.T // args.limb_bits
    n_limbs = [(n >> (args.limb_bits * index)) & limb_mask for index in range(limb_count)]

    p_unknown_by_bit = {}
    q_unknown_bools = []

    def build_limb(name: str, limb_index: int, known_value: int, known_mask: int, track_p_bits: bool):
        if known_mask == limb_mask:
            return known_value & limb_mask, 0

        limb = model.NewIntVar(0, limb_mask, f"{name}_{limb_index}")
        expr = known_value & known_mask
        unknown_bits = 0
        shift = args.limb_bits * limb_index
        for bit in range(args.limb_bits):
            if ((known_mask >> bit) & 1) == 0:
                var = model.NewBoolVar(f"{name}_{shift + bit}")
                expr += (1 << bit) * var
                unknown_bits += 1
                if track_p_bits:
                    p_unknown_by_bit[shift + bit] = var
                else:
                    q_unknown_bools.append(var)
        model.Add(limb == expr)
        return limb, unknown_bits

    p_limbs = []
    q_limbs = []
    p_unknown_bits = 0
    q_unknown_bits = 0
    p_variable_limbs = 0
    q_variable_limbs = 0
    for index in range(limb_count):
        shift = args.limb_bits * index
        p_known_mask = (branch_mask >> shift) & limb_mask
        p_known_value = (branch_known >> shift) & limb_mask
        p_limb, p_unknown_count = build_limb("p", index, p_known_value, p_known_mask, True)
        p_limbs.append(p_limb)
        p_unknown_bits += p_unknown_count
        p_variable_limbs += int(not isinstance(p_limb, int))

        q_known_mask_limb = (q_known_mask >> shift) & limb_mask
        q_known_value = (q_known >> shift) & limb_mask
        q_limb, q_unknown_count = build_limb("q", index, q_known_value, q_known_mask_limb, False)
        q_limbs.append(q_limb)
        q_unknown_bits += q_unknown_count
        q_variable_limbs += int(not isinstance(q_limb, int))

    carry_bound = limb_count * limb_mask * limb_mask
    carries = [model.NewConstant(0)]
    for index in range(1, limb_count + 1):
        carries.append(model.NewIntVar(0, carry_bound, f"c_{index}"))

    product_vars = []
    linear_terms = 0
    constant_terms = 0
    for index in range(limb_count):
        terms = []
        constant_sum = 0
        for j in range(index + 1):
            p_term = p_limbs[j]
            q_term = q_limbs[index - j]
            if (isinstance(p_term, int) and p_term == 0) or (isinstance(q_term, int) and q_term == 0):
                continue
            if isinstance(p_term, int) and isinstance(q_term, int):
                constant_sum += p_term * q_term
                constant_terms += 1
            elif isinstance(p_term, int):
                terms.append(p_term * q_term)
                linear_terms += 1
            elif isinstance(q_term, int):
                terms.append(q_term * p_term)
                linear_terms += 1
            else:
                product = model.NewIntVar(0, limb_mask * limb_mask, f"pq_{j}_{index - j}")
                model.AddMultiplicationEquality(product, [p_term, q_term])
                product_vars.append(product)
                terms.append(product)

        model.Add(sum(terms) + constant_sum + carries[index] == n_limbs[index] + base * carries[index + 1])

    decision_vars = []
    seen = set()
    for start, width in args.decision_p_range:
        for bit in range(start, start + width):
            var = p_unknown_by_bit.get(bit)
            if var is not None and bit not in seen:
                decision_vars.append(var)
                seen.add(bit)
    if decision_vars:
        model.AddDecisionStrategy(decision_vars, cp_model.CHOOSE_FIRST, cp_model.SELECT_MIN_VALUE)

    print(f"T={args.T}")
    print(f"limb bits: {args.limb_bits}")
    print(f"limbs: {limb_count}")
    print(f"branch x0={args.branch_low:x}, x7={args.branch_high:x}")
    for fixed_start, fixed_width, fixed_value in args.fix_p_range:
        print(f"fixed p[{fixed_start}..{fixed_start + fixed_width - 1}] = {fixed_value:#x}")
    print(f"q low known bits: {low_known_bits}")
    print(f"q high common bits: {q_prefix_bits}")
    print(f"q prefix start: {q_prefix_start}")
    print(f"q prefix bits inside T: {max(0, args.T - q_prefix_start)}")
    print(f"p unknown bools in T: {p_unknown_bits}")
    print(f"q fixed bits in T: {args.T - q_unknown_bits}")
    print(f"q bools in T: {q_unknown_bits}")
    print(f"p variable limbs: {p_variable_limbs}")
    print(f"q variable limbs: {q_variable_limbs}")
    print(f"product vars: {len(product_vars)}")
    print(f"linear product terms: {linear_terms}")
    print(f"constant product terms: {constant_terms}")
    print(f"carry vars: {limb_count}")
    print(f"carry bound: {carry_bound}")
    print(f"decision p bools: {len(decision_vars)}")

    if args.build_only:
        return 0

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.time_limit
    solver.parameters.num_search_workers = args.workers
    solver.parameters.log_search_progress = args.log
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 2
    if decision_vars:
        solver.parameters.search_branching = cp_model.FIXED_SEARCH

    status = solver.Solve(model)
    print(f"status: {solver.StatusName(status)}")
    print(f"wall time: {solver.WallTime():.2f}s")
    print(f"branches: {solver.NumBranches()}")
    print(f"conflicts: {solver.NumConflicts()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
