#!/usr/bin/env python3
"""Try a 16-bit limb CP-SAT model for challenge 7.

The model is intentionally direct: p and q are represented as 16-bit limbs,
known bits are linear Boolean constraints, and N = p*q is encoded column by
column with carry variables.  It is a reproducible non-lattice baseline for
the partial-bit RSA instance.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

from ortools.sat.python import cp_model


parser = argparse.ArgumentParser()
parser.add_argument("--limb-bits", type=int, default=16)
parser.add_argument("--branch-low", type=lambda x: int(x, 0), default=0)
parser.add_argument("--branch-high", type=lambda x: int(x, 0), default=0)
parser.add_argument("--time-limit", type=float, default=60.0)
parser.add_argument("--workers", type=int, default=8)
parser.add_argument("--log", action="store_true")
parser.add_argument(
    "--fix-p-range",
    action="append",
    default=[],
    help="fix p bits as START:WIDTH:VALUE; can be repeated",
)
parser.add_argument(
    "--decision-p-range",
    action="append",
    default=[],
    help="prioritize p bit variables in START:WIDTH order; can be repeated",
)
parser.add_argument(
    "--lowlift-q",
    type=int,
    default=0,
    help="bind q low bits using q_low = Q0 + C1*x1 mod 2^bits; currently supports 265",
)
args = parser.parse_args()

if args.limb_bits <= 0 or 1024 % args.limb_bits != 0:
    raise SystemExit("--limb-bits must divide 1024")
if not (0 <= args.branch_low < 16 and 0 <= args.branch_high < 16):
    raise SystemExit("branch nibbles must be in 0..15")
if args.lowlift_q and args.lowlift_q != 265:
    raise SystemExit("--lowlift-q currently supports only 265")
if args.lowlift_q and args.limb_bits > 16:
    raise SystemExit("--lowlift-q uses linear coefficients sized for limb_bits <= 16")


def parse_fixed_range(text: str) -> tuple[int, int, int]:
    try:
        start_text, width_text, value_text = text.split(":", 2)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH:VALUE") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    value = int(value_text, 0)
    if start < 0 or width <= 0 or start + width > 1024:
        raise argparse.ArgumentTypeError("invalid bit range")
    if value < 0 or value >= (1 << width):
        raise argparse.ArgumentTypeError("value does not fit selected width")
    return start, width, value


def parse_range(text: str) -> tuple[int, int]:
    try:
        start_text, width_text = text.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    if start < 0 or width <= 0 or start + width > 1024:
        raise argparse.ArgumentTypeError("invalid bit range")
    return start, width


fixed_p_ranges = [parse_fixed_range(item) for item in args.fix_p_range]
decision_p_ranges = [parse_range(item) for item in args.decision_p_range]

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "investigate_07", root / "solutions" / "investigate_07_rsa_partial_bits.py"
)
if spec is None or spec.loader is None:
    raise SystemExit("failed to load challenge 7 constants")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

n = int(module.N_HEX.replace(" ", ""), 16)
ct = int(module.CT_HEX.replace(" ", ""), 16)
e = int(module.E)
mask = int(module.MASK_HEX.replace(" ", ""), 16)
known = int(module.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
full_p_mask = (1 << 1024) - 1
base = 1 << args.limb_bits
limb_mask = base - 1
p_limb_count = 1024 // args.limb_bits
n_limb_count = 2048 // args.limb_bits
n_limbs = [(n >> (args.limb_bits * i)) & limb_mask for i in range(n_limb_count)]

branch_known = known | (args.branch_low << 150) | (args.branch_high << 920)
branch_mask = mask | (0xF << 150) | (0xF << 920)
for fixed_start, fixed_width, fixed_value in fixed_p_ranges:
    fixed_mask = ((1 << fixed_width) - 1) << fixed_start
    fixed_bits = fixed_value << fixed_start
    if ((branch_known ^ fixed_bits) & (branch_mask & fixed_mask)) != 0:
        raise SystemExit(f"inconsistent --fix-p-range {fixed_start}:{fixed_width}:{fixed_value:#x}")
    branch_known |= fixed_bits
    branch_mask |= fixed_mask
branch_unknown_mask = full_p_mask ^ branch_mask
p_min = branch_known
p_max = branch_known | branch_unknown_mask
q_min = n // p_max
q_max = n // p_min

q_known_mask = 0
q_known = 0
if branch_unknown_mask:
    low_bits = (branch_unknown_mask & -branch_unknown_mask).bit_length() - 1
else:
    low_bits = 1024
low_modulus = 1 << low_bits
p_mod = branch_known & (low_modulus - 1)
q_mod = (n * pow(p_mod, -1, low_modulus)) % low_modulus
q_known_mask |= low_modulus - 1
q_known |= q_mod

high_common = 1024 - (q_min ^ q_max).bit_length()
if high_common > 0:
    prefix_mask = ((1 << high_common) - 1) << (1024 - high_common)
    prefix_value = q_min & prefix_mask
    if ((q_known ^ prefix_value) & (q_known_mask & prefix_mask)) != 0:
        raise SystemExit("inconsistent q low/high fixed bits")
    q_known |= prefix_value
    q_known_mask |= prefix_mask

model = cp_model.CpModel()
p_limbs = []
q_limbs = []
p_unknown_bools = []
q_unknown_bools = []
p_unknown_by_bit = {}
q_lowlift_parts = {}

for i in range(p_limb_count):
    shift = args.limb_bits * i
    local_known_mask = (branch_mask >> shift) & limb_mask
    local_known = (branch_known >> shift) & limb_mask
    if local_known_mask == limb_mask:
        p_limbs.append(model.NewConstant(local_known))
    else:
        limb = model.NewIntVar(0, limb_mask, f"p_{i}")
        expr = local_known & local_known_mask
        for bit in range(args.limb_bits):
            if ((local_known_mask >> bit) & 1) == 0:
                bit_var = model.NewBoolVar(f"p_{i}_{bit}")
                p_unknown_bools.append(bit_var)
                p_unknown_by_bit[shift + bit] = bit_var
                expr += (1 << bit) * bit_var
        model.Add(limb == expr)
        p_limbs.append(limb)

for i in range(p_limb_count):
    shift = args.limb_bits * i
    local_known_mask = (q_known_mask >> shift) & limb_mask
    local_known = (q_known >> shift) & limb_mask
    if args.lowlift_q and shift < args.lowlift_q and shift + args.limb_bits > low_bits:
        lift_lo = max(low_bits, shift)
        lift_hi = min(args.lowlift_q, shift + args.limb_bits)
        lift_width = lift_hi - lift_lo
        lift_offset = lift_lo - shift
        lowlift_part = model.NewIntVar(0, (1 << lift_width) - 1, f"q_{i}_ll")
        q_lowlift_parts[i] = lowlift_part
        expr = lowlift_part * (1 << lift_offset)
        expr += local_known & local_known_mask

        below_mask = (1 << lift_offset) - 1
        variable_below_mask = below_mask & (limb_mask ^ local_known_mask)
        if variable_below_mask:
            below = model.NewIntVar(0, variable_below_mask, f"q_{i}_below")
            model.AddAllowedAssignments(
                [below],
                [(value,) for value in range(variable_below_mask + 1) if (value & ~variable_below_mask) == 0],
            )
            expr += below

        upper_start = lift_offset + lift_width
        if upper_start < args.limb_bits:
            upper_width = args.limb_bits - upper_start
            upper = model.NewIntVar(0, (1 << upper_width) - 1, f"q_{i}_upper")
            expr += upper * (1 << upper_start)

        limb = model.NewIntVar(0, limb_mask, f"q_{i}")
        model.Add(limb == expr)
        q_limbs.append(limb)
        continue
    if local_known_mask == limb_mask:
        q_limbs.append(model.NewConstant(local_known))
    else:
        limb = model.NewIntVar(0, limb_mask, f"q_{i}")
        expr = local_known & local_known_mask
        for bit in range(args.limb_bits):
            if ((local_known_mask >> bit) & 1) == 0:
                bit_var = model.NewBoolVar(f"q_{i}_{bit}")
                q_unknown_bools.append(bit_var)
                expr += (1 << bit) * bit_var
        model.Add(limb == expr)
        q_limbs.append(limb)

if args.lowlift_q:
    lift_bits = args.lowlift_q
    lift_modulus = 1 << lift_bits
    x1_mask = ((1 << 39) - 1) << 210
    p0 = branch_known & (lift_modulus - 1) & ((lift_modulus - 1) ^ x1_mask)
    inv_p0 = pow(p0, -1, lift_modulus)
    q0_lift = (n * inv_p0) % lift_modulus
    c1_lift = (-(1 << 210) * n * inv_p0 * inv_p0) % lift_modulus

    x1_expr = 0
    for bit in range(39):
        absolute_bit = 210 + bit
        coeff = 1 << bit
        if (branch_mask >> absolute_bit) & 1:
            x1_expr += coeff * ((branch_known >> absolute_bit) & 1)
        else:
            x1_expr += coeff * p_unknown_by_bit[absolute_bit]

    full_lift_limbs = lift_bits // args.limb_bits
    partial_lift_bits = lift_bits % args.limb_bits
    # c1_limb * x1 is below 2^55 for 16-bit limbs; the propagated carry is
    # therefore around 2^39. Keep the bound small enough that base * carry
    # stays inside CP-SAT's signed 64-bit coefficient limits.
    lowlift_carry_bound = 1 << 45
    lowlift_carries = [model.NewConstant(0)]
    for i in range(1, full_lift_limbs + 1):
        lowlift_carries.append(model.NewIntVar(0, lowlift_carry_bound, f"llq_c_{i}"))

    for i in range(full_lift_limbs):
        q0_limb = (q0_lift >> (args.limb_bits * i)) & limb_mask
        c1_limb = (c1_lift >> (args.limb_bits * i)) & limb_mask
        model.Add(
            q_limbs[i] + base * lowlift_carries[i + 1]
            == q0_limb + c1_limb * x1_expr + lowlift_carries[i]
        )

    if partial_lift_bits:
        partial_mask = (1 << partial_lift_bits) - 1
        q0_part = (q0_lift >> (args.limb_bits * full_lift_limbs)) & partial_mask
        c1_part = (c1_lift >> (args.limb_bits * full_lift_limbs)) & partial_mask
        q_part_expr = q_lowlift_parts[full_lift_limbs]
        wrap = model.NewIntVar(0, lowlift_carry_bound, "llq_wrap")
        model.Add(
            q_part_expr + (1 << partial_lift_bits) * wrap
            == q0_part + c1_part * x1_expr + lowlift_carries[full_lift_limbs]
        )

carry_bound = 1 << 32
carries = [model.NewConstant(0)]
for i in range(1, n_limb_count):
    carries.append(model.NewIntVar(0, carry_bound, f"c_{i}"))
carries.append(model.NewConstant(0))

products = []
for k in range(n_limb_count):
    column_terms = []
    for i in range(max(0, k - p_limb_count + 1), min(p_limb_count - 1, k) + 1):
        j = k - i
        if 0 <= j < p_limb_count:
            product = model.NewIntVar(0, limb_mask * limb_mask, f"m_{i}_{j}")
            model.AddMultiplicationEquality(product, [p_limbs[i], q_limbs[j]])
            products.append(product)
            column_terms.append(product)
    model.Add(sum(column_terms) + carries[k] == n_limbs[k] + base * carries[k + 1])

decision_vars = []
seen_decision_bits = set()
for start, width in decision_p_ranges:
    for bit in range(start, start + width):
        var = p_unknown_by_bit.get(bit)
        if var is not None and bit not in seen_decision_bits:
            decision_vars.append(var)
            seen_decision_bits.add(bit)
if decision_vars:
    model.AddDecisionStrategy(
        decision_vars,
        cp_model.CHOOSE_FIRST,
        cp_model.SELECT_MIN_VALUE,
    )

solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = args.time_limit
solver.parameters.num_search_workers = args.workers
solver.parameters.log_search_progress = args.log
solver.parameters.cp_model_presolve = True
solver.parameters.linearization_level = 2
if decision_vars:
    solver.parameters.search_branching = cp_model.FIXED_SEARCH

print(f"branch x0={args.branch_low:x}, x7={args.branch_high:x}")
for fixed_start, fixed_width, fixed_value in fixed_p_ranges:
    print(f"fixed p[{fixed_start}..{fixed_start + fixed_width - 1}] = {fixed_value:#x}")
if decision_p_ranges:
    print("decision p ranges:", ", ".join(f"{start}:{width}" for start, width in decision_p_ranges))
print(f"q low known bits: {low_bits}")
if args.lowlift_q:
    print(f"q lowlift affine bits: {args.lowlift_q}")
print(f"q high common bits: {high_common}")
print(f"p unknown bools: {len(p_unknown_bools)}")
print(f"q unknown bools: {len(q_unknown_bools)}")
print(f"priority decision p bools: {len(decision_vars)}")
print(f"product vars: {len(products)}")
print(f"carry vars: {n_limb_count - 1}")

status = solver.Solve(model)
print(f"status: {solver.StatusName(status)}")
print(f"wall time: {solver.WallTime():.2f}s")
print(f"branches: {solver.NumBranches()}")
print(f"conflicts: {solver.NumConflicts()}")

if status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
    p = 0
    q = 0
    for i, limb in enumerate(p_limbs):
        p |= int(solver.Value(limb)) << (args.limb_bits * i)
    for i, limb in enumerate(q_limbs):
        q |= int(solver.Value(limb)) << (args.limb_bits * i)
    print(f"N % p == 0: {n % p == 0}")
    print(f"p mask check: {(p & mask) == (known & mask)}")
    if n % p == 0 and p * q == n:
        phi = (p - 1) * (q - 1)
        d = pow(e, -1, phi)
        m = pow(ct, d, n)
        plaintext = m.to_bytes((m.bit_length() + 7) // 8, "big")
        print(f"p = {p:#x}")
        print(f"q = {q:#x}")
        print(f"plaintext bytes = {plaintext!r}")
