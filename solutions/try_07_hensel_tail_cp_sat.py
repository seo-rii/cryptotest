#!/usr/bin/env python3
"""CP-SAT Hensel exact-tail prototype for challenge 7.

For a limb-aligned T, this encodes:

    pL*qL = N mod 2^T

with Hensel carry recurrence, then adds the high equality after dividing by
2^T:

    carry_T + PH*qL + QH*pL + 2^T*PH*QH = floor(N / 2^T)

The first tail limbs are added incrementally with --tail-limbs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from ortools.sat.python import cp_model


P_BITS = 1024
X0_OFFSET = 150
X7_OFFSET = 920
ROOT = Path(__file__).resolve().parents[1]
CP_SAT_INT_LIMIT = (1 << 63) - 1


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


def int_limbs(value: int, limb_bits: int, count: int) -> list[int]:
    mask = (1 << limb_bits) - 1
    return [(value >> (limb_bits * index)) & mask for index in range(count)]


def load_constants():
    spec = importlib.util.spec_from_file_location(
        "investigate_07", ROOT / "solutions" / "investigate_07_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--T", type=int, default=848)
    parser.add_argument("--limb-bits", type=int, default=16)
    parser.add_argument("--tail-limbs", type=int, default=8)
    parser.add_argument("--branch-low", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--branch-high", type=lambda value: int(value, 0), default=0)
    parser.add_argument(
        "--free-branch-low",
        action="store_true",
        help="leave p[150..153] free instead of fixing it to --branch-low",
    )
    parser.add_argument(
        "--free-branch-high",
        action="store_true",
        help="leave p[920..923] free instead of fixing it to --branch-high",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_bit_range_value)
    parser.add_argument("--fix-q-range", action="append", default=[], type=parse_bit_range_value)
    parser.add_argument("--decision-p-range", action="append", default=[], type=parse_bit_range)
    parser.add_argument("--decision-q-range", action="append", default=[], type=parse_bit_range)
    parser.add_argument(
        "--decision-select",
        choices=("min", "max"),
        default="min",
        help="value selection strategy for explicit p/q decision ranges",
    )
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--small-prime-filters",
        type=int,
        default=0,
        help="add p %% r != 0 and q %% r != 0 for the first N odd primes not dividing N",
    )
    parser.add_argument(
        "--odd-residue-filters",
        type=int,
        default=0,
        help="add p*q == N modulo the first N odd primes not dividing N",
    )
    parser.add_argument(
        "--odd-residue-primes",
        default="",
        help="comma-separated odd primes for p*q == N residue constraints",
    )
    parser.add_argument(
        "--no-q-interval-bound",
        action="store_true",
        help="disable lexicographic q_min <= q <= q_max bounds inside qL",
    )
    parser.add_argument(
        "--lowlift-q",
        type=int,
        default=0,
        help="add symbolic q mod 2^t constraint; currently supports 265 and limb-aligned 272",
    )
    parser.add_argument(
        "--compact-q-limbs",
        action="store_true",
        help="encode q lower limbs directly as domain IntVars instead of per-bit BoolVars",
    )
    parser.add_argument(
        "--skip-known-prefix-limbs",
        type=int,
        default=0,
        help=(
            "skip the first N lower Hensel columns when p/q limbs 0..N-1 are fully "
            "known; carry_N is computed exactly and used as the recurrence seed"
        ),
    )
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--json-summary", action="store_true")
    parser.add_argument(
        "--random-seed",
        type=int,
        help="set OR-Tools CP-SAT random_seed for repeated probe diversification",
    )
    parser.add_argument(
        "--randomize-search",
        action="store_true",
        help="enable OR-Tools randomized search decisions",
    )
    parser.add_argument(
        "--no-phase-saving",
        action="store_true",
        help="disable OR-Tools phase saving during search",
    )
    args = parser.parse_args()

    if not (1 <= args.T <= P_BITS):
        raise SystemExit("--T must be in 1..1024")
    if args.T % args.limb_bits != 0:
        raise SystemExit("--T must be divisible by --limb-bits for this prototype")
    if args.tail_limbs < 0:
        raise SystemExit("--tail-limbs must be non-negative")
    if args.skip_known_prefix_limbs < 0:
        raise SystemExit("--skip-known-prefix-limbs must be non-negative")
    if args.lowlift_q not in {0, 265, 272}:
        raise SystemExit("--lowlift-q currently supports only 265 and 272")
    if args.compact_q_limbs and args.lowlift_q == 265:
        raise SystemExit("--compact-q-limbs is compatible with --lowlift-q 0 or 272")
    if not (0 <= args.branch_low < 16 and 0 <= args.branch_high < 16):
        raise SystemExit("branch nibbles must be in 0..15")

    constants = load_constants()
    n = int(constants.N_HEX.replace(" ", ""), 16)
    mask = int(constants.MASK_HEX.replace(" ", ""), 16)
    known = int(constants.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    full_mask = (1 << P_BITS) - 1

    branch_known = known
    branch_mask = mask
    if not args.free_branch_low:
        branch_known |= args.branch_low << X0_OFFSET
        branch_mask |= 0xF << X0_OFFSET
    if not args.free_branch_high:
        branch_known |= args.branch_high << X7_OFFSET
        branch_mask |= 0xF << X7_OFFSET
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

    lower_mask = (1 << args.T) - 1
    q_known_mask = q_global_known_mask & lower_mask
    q_known = q_global_known & lower_mask

    p_high = branch_known >> args.T
    q_tail_width = P_BITS - args.T
    q_high_known_mask = (q_global_known_mask >> args.T) & ((1 << q_tail_width) - 1)
    q_unknown_above_t = q_tail_width - q_high_known_mask.bit_count()
    if q_unknown_above_t:
        raise SystemExit(
            f"q tail is not fully known above T; unknown bits above T = {q_unknown_above_t}"
        )
    q_high = q_global_known >> args.T
    q_low_min = max(0, q_min - (q_high << args.T))
    q_low_max = min((1 << args.T) - 1, q_max - (q_high << args.T))
    if q_low_min > q_low_max:
        raise SystemExit("q interval does not intersect selected q high prefix")

    model = cp_model.CpModel()
    base = 1 << args.limb_bits
    limb_mask = base - 1
    lower_limb_count = args.T // args.limb_bits
    if args.skip_known_prefix_limbs > lower_limb_count:
        raise SystemExit("--skip-known-prefix-limbs exceeds lower limb count")
    total_product_limb_count = (2 * P_BITS) // args.limb_bits
    complete_tail_limb_count = total_product_limb_count - lower_limb_count
    n_lower_limbs = int_limbs(n, args.limb_bits, lower_limb_count)

    p_unknown_by_bit = {}
    q_unknown_bools = []
    q_unknown_by_bit = {}

    def limb_domain_values(known_value: int, known_mask: int) -> list[int]:
        target = known_value & known_mask
        return [value for value in range(base) if (value & known_mask) == target]

    def build_limb(name: str, limb_index: int, known_value: int, known_mask: int, track_p_bits: bool):
        if known_mask == limb_mask:
            return known_value & limb_mask, 0

        limb_min = known_value & known_mask
        limb_max = limb_min | (limb_mask ^ known_mask)
        if (not track_p_bits) and args.compact_q_limbs:
            if known_mask == 0:
                limb = model.NewIntVar(0, limb_mask, f"{name}_{limb_index}")
            else:
                limb = model.NewIntVarFromDomain(
                    cp_model.Domain.FromValues(limb_domain_values(known_value, known_mask)),
                    f"{name}_{limb_index}",
                )
            return limb, args.limb_bits - known_mask.bit_count()

        limb = model.NewIntVar(limb_min, limb_max, f"{name}_{limb_index}")
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
                    q_unknown_by_bit[shift + bit] = var
        model.Add(limb == expr)
        return limb, unknown_bits

    p_limbs = []
    q_limbs = []
    p_limb_min = []
    p_limb_max = []
    q_limb_min = []
    q_limb_max = []
    p_unknown_bits = 0
    q_unknown_bits = 0
    p_variable_limbs = 0
    q_variable_limbs = 0
    for index in range(lower_limb_count):
        shift = args.limb_bits * index
        p_known_mask = (branch_mask >> shift) & limb_mask
        p_known_value = (branch_known >> shift) & limb_mask
        p_min = p_known_value & p_known_mask
        p_max = p_min | (limb_mask ^ p_known_mask)
        p_limb_min.append(p_min)
        p_limb_max.append(p_max)
        p_limb, p_unknown_count = build_limb("p", index, p_known_value, p_known_mask, True)
        p_limbs.append(p_limb)
        p_unknown_bits += p_unknown_count
        p_variable_limbs += int(not isinstance(p_limb, int))

        q_known_mask_limb = (q_known_mask >> shift) & limb_mask
        q_known_value = (q_known >> shift) & limb_mask
        q_min = q_known_value & q_known_mask_limb
        q_max = q_min | (limb_mask ^ q_known_mask_limb)
        q_limb_min.append(q_min)
        q_limb_max.append(q_max)
        q_limb, q_unknown_count = build_limb("q", index, q_known_value, q_known_mask_limb, False)
        q_limbs.append(q_limb)
        q_unknown_bits += q_unknown_count
        q_variable_limbs += int(not isinstance(q_limb, int))

    skipped_prefix_carry = None
    if args.skip_known_prefix_limbs:
        for index in range(args.skip_known_prefix_limbs):
            if not isinstance(p_limbs[index], int) or not isinstance(q_limbs[index], int):
                raise SystemExit(
                    "--skip-known-prefix-limbs requires fully known p/q limbs in the skipped prefix"
                )

        carry = 0
        for index in range(args.skip_known_prefix_limbs):
            column_sum = carry
            for j in range(index + 1):
                column_sum += p_limbs[j] * q_limbs[index - j]
            target = n_lower_limbs[index]
            if column_sum % base != target:
                raise SystemExit(
                    f"known prefix column {index} is inconsistent: "
                    f"{column_sum % base:#x} != {target:#x}"
                )
            carry = (column_sum - target) // base
            if carry < 0:
                raise SystemExit(f"known prefix column {index} produced negative carry")
        skipped_prefix_carry = carry

    def equality_bool(limb, value: int, name: str):
        if isinstance(limb, int):
            return None if limb == value else False
        flag = model.NewBoolVar(name)
        model.Add(limb == value).OnlyEnforceIf(flag)
        model.Add(limb != value).OnlyEnforceIf(flag.Not())
        return flag

    def add_lex_bound(limbs, bound: int, is_upper: bool, name: str) -> int:
        bound_limbs = int_limbs(bound, args.limb_bits, len(limbs))
        prefix = None
        constraints = 0
        for index in range(len(limbs) - 1, -1, -1):
            limb = limbs[index]
            limit = bound_limbs[index]
            if prefix is None:
                if isinstance(limb, int):
                    if (is_upper and limb > limit) or ((not is_upper) and limb < limit):
                        raise SystemExit(f"{name} bound inconsistent at limb {index}")
                    if limb != limit:
                        break
                    continue
                if is_upper:
                    model.Add(limb <= limit)
                else:
                    model.Add(limb >= limit)
                constraints += 1
                prefix = equality_bool(limb, limit, f"{name}_eq_{index}")
                if prefix is False:
                    break
                continue

            if isinstance(limb, int):
                violates = (is_upper and limb > limit) or ((not is_upper) and limb < limit)
                if violates:
                    model.Add(prefix == 0)
                    constraints += 1
                    break
                if limb != limit:
                    break
                continue

            if is_upper:
                model.Add(limb <= limit).OnlyEnforceIf(prefix)
            else:
                model.Add(limb >= limit).OnlyEnforceIf(prefix)
            constraints += 1
            eq = equality_bool(limb, limit, f"{name}_eq_{index}")
            if eq is False:
                break
            next_prefix = model.NewBoolVar(f"{name}_prefix_{index}")
            model.AddImplication(next_prefix, prefix)
            model.AddImplication(next_prefix, eq)
            model.AddBoolOr([prefix.Not(), eq.Not(), next_prefix])
            prefix = next_prefix
        return constraints

    q_interval_constraints = 0
    if not args.no_q_interval_bound:
        q_interval_constraints += add_lex_bound(q_limbs, q_low_min, False, "q_interval_lower")
        q_interval_constraints += add_lex_bound(q_limbs, q_low_max, True, "q_interval_upper")

    lowlift_q_constraints = 0
    if args.lowlift_q:
        lift_bits = args.lowlift_q
        if lift_bits > args.T:
            raise SystemExit("--lowlift-q must be <= T")

        if lift_bits == 265:
            lift_modulus = 1 << lift_bits
            x1_mask = ((1 << 39) - 1) << 210
            p0 = (branch_known & (lift_modulus - 1)) & ~x1_mask
            inv_p0 = pow(p0, -1, lift_modulus)
            q0 = (n * inv_p0) % lift_modulus
            mid_modulus = 1 << 55
            q0_mid = (q0 >> 210) & (mid_modulus - 1)
            c_mid = (-n * inv_p0 * inv_p0) % mid_modulus

            q_mid_terms = []
            q_mid_const = 0
            for offset in range(55):
                bit = 210 + offset
                coeff = 1 << offset
                var = q_unknown_by_bit.get(bit)
                if var is None:
                    if (q_known >> bit) & 1:
                        q_mid_const += coeff
                else:
                    q_mid_terms.append(coeff * var)
            q_mid = model.NewIntVar(0, mid_modulus - 1, "lowlift_q_mid")
            model.Add(q_mid == sum(q_mid_terms) + q_mid_const)
            lowlift_q_constraints += 1

            total_terms = []
            total_const = q0_mid
            total_max = q0_mid
            for offset in range(39):
                bit = 210 + offset
                coeff = (c_mid * (1 << offset)) % mid_modulus
                var = p_unknown_by_bit.get(bit)
                if var is None:
                    if (branch_known >> bit) & 1:
                        total_const += coeff
                        total_max += coeff
                else:
                    total_terms.append(coeff * var)
                    total_max += coeff

            total = model.NewIntVar(0, total_max, "lowlift_q_total")
            model.Add(total == sum(total_terms) + total_const)
            model.AddModuloEquality(q_mid, total, mid_modulus)
            lowlift_q_constraints += 2
        else:
            if lift_bits % args.limb_bits != 0:
                raise SystemExit("--lowlift-q 272 requires a limb-aligned lift")
            if lift_bits != 272:
                raise AssertionError("only lift_bits=272 reaches this branch")

            lift_modulus = 1 << lift_bits
            lift_limb_count = lift_bits // args.limb_bits
            p0 = branch_known & (lift_modulus - 1)
            variable_bits = []
            for bit in range(lift_bits):
                if (branch_mask >> bit) & 1:
                    continue
                var = p_unknown_by_bit.get(bit)
                if var is not None:
                    variable_bits.append((bit, var))
                    p0 &= ~(1 << bit)

            inv_p0 = pow(p0, -1, lift_modulus)
            q0 = (n * inv_p0) % lift_modulus
            linear_base = (-n * inv_p0 * inv_p0) % lift_modulus
            q0_limbs = int_limbs(q0, args.limb_bits, lift_limb_count)
            coeff_limbs = [
                (bit, var, int_limbs((linear_base * (1 << bit)) % lift_modulus, args.limb_bits, lift_limb_count))
                for bit, var in variable_bits
            ]

            carry_bound = len(coeff_limbs) + 2
            lowlift_carry = [model.NewConstant(0)]
            for index in range(1, lift_limb_count + 1):
                lowlift_carry.append(model.NewIntVar(0, carry_bound, f"lowlift272_carry_{index}"))

            for index in range(lift_limb_count):
                terms = [lowlift_carry[index]]
                constant_sum = q0_limbs[index]
                for _, var, limbs in coeff_limbs:
                    coeff = limbs[index]
                    if coeff:
                        terms.append(coeff * var)
                model.Add(sum(terms) + constant_sum == q_limbs[index] + base * lowlift_carry[index + 1])
                lowlift_q_constraints += 1

    p_high_limb_count = max(1, (p_high.bit_length() + args.limb_bits - 1) // args.limb_bits)
    q_high_limb_count = max(1, (q_high.bit_length() + args.limb_bits - 1) // args.limb_bits)
    p_high_limbs = int_limbs(p_high, args.limb_bits, p_high_limb_count)
    q_high_limbs = int_limbs(q_high, args.limb_bits, q_high_limb_count)
    high_product = p_high * q_high
    high_product_limb_count = max(1, (high_product.bit_length() + args.limb_bits - 1) // args.limb_bits)
    high_product_limbs = int_limbs(high_product, args.limb_bits, high_product_limb_count)
    n_tail = n >> args.T
    max_tail_limbs = max(
        args.tail_limbs,
        (n_tail.bit_length() + args.limb_bits - 1) // args.limb_bits,
        lower_limb_count + high_product_limb_count,
    )
    n_tail_limbs = int_limbs(n_tail, args.limb_bits, max_tail_limbs)

    lower_carry_bound = lower_limb_count * limb_mask * limb_mask
    tail_carry_bound = (2 * lower_limb_count + args.tail_limbs + 4) * limb_mask * limb_mask
    final_carry_zero = args.tail_limbs >= complete_tail_limb_count

    def low_low_column_bounds(column: int) -> tuple[int, int]:
        min_sum = 0
        max_sum = 0
        lo = max(0, column - lower_limb_count + 1)
        hi = min(lower_limb_count - 1, column)
        for i in range(lo, hi + 1):
            j = column - i
            min_sum += p_limb_min[i] * q_limb_min[j]
            max_sum += p_limb_max[i] * q_limb_max[j]
        return min_sum, max_sum

    def tail_column_bounds(index: int) -> tuple[int, int]:
        min_sum, max_sum = low_low_column_bounds(lower_limb_count + index)
        for i in range(lower_limb_count):
            h = index - i
            if 0 <= h < len(p_high_limbs) and p_high_limbs[h]:
                min_sum += p_high_limbs[h] * q_limb_min[i]
                max_sum += p_high_limbs[h] * q_limb_max[i]
            if 0 <= h < len(q_high_limbs) and q_high_limbs[h]:
                min_sum += q_high_limbs[h] * p_limb_min[i]
                max_sum += q_high_limbs[h] * p_limb_max[i]
        if index >= lower_limb_count:
            product_index = index - lower_limb_count
            if product_index < len(high_product_limbs):
                min_sum += high_product_limbs[product_index]
                max_sum += high_product_limbs[product_index]
        return min_sum, max_sum

    def column_bounds(column: int) -> tuple[int, int, int]:
        if column < lower_limb_count:
            min_sum, max_sum = low_low_column_bounds(column)
            return min_sum, max_sum, n_lower_limbs[column]
        tail_index = column - lower_limb_count
        min_sum, max_sum = tail_column_bounds(tail_index)
        return min_sum, max_sum, n_tail_limbs[tail_index]

    def ceil_div(value: int, divisor: int) -> int:
        return -((-value) // divisor)

    total_columns = lower_limb_count + args.tail_limbs
    carry_global_bound = max(lower_carry_bound, tail_carry_bound)
    carry_min = [0] + [0] * total_columns
    carry_max = [0] + [carry_global_bound] * total_columns
    if skipped_prefix_carry is not None:
        carry_min[args.skip_known_prefix_limbs] = skipped_prefix_carry
        carry_max[args.skip_known_prefix_limbs] = skipped_prefix_carry
    if final_carry_zero:
        carry_min[lower_limb_count + complete_tail_limb_count] = 0
        carry_max[lower_limb_count + complete_tail_limb_count] = 0

    for _ in range(200):
        changed = False
        for index in range(total_columns):
            sum_min, sum_max, target = column_bounds(index)
            next_min = max(0, ceil_div(carry_min[index] + sum_min - target, base))
            next_max = max(0, (carry_max[index] + sum_max - target) // base)
            if next_min > carry_min[index + 1]:
                carry_min[index + 1] = next_min
                changed = True
            if next_max < carry_max[index + 1]:
                carry_max[index + 1] = next_max
                changed = True
        for index in range(total_columns - 1, -1, -1):
            sum_min, sum_max, target = column_bounds(index)
            prev_min = max(0, target + base * carry_min[index + 1] - sum_max)
            prev_max = max(0, target + base * carry_max[index + 1] - sum_min)
            if prev_min > carry_min[index]:
                carry_min[index] = prev_min
                changed = True
            if prev_max < carry_max[index]:
                carry_max[index] = prev_max
                changed = True
        if not changed:
            break
    if any(lo > hi for lo, hi in zip(carry_min, carry_max)):
        raise SystemExit("carry interval propagation made the model inconsistent")
    tightened_carry_singletons = sum(1 for lo, hi in zip(carry_min, carry_max) if lo == hi)
    tightened_carry_width_bits = max((hi - lo + 1).bit_length() for lo, hi in zip(carry_min, carry_max))

    lower_carries = [model.NewConstant(0)]
    for index in range(1, lower_limb_count + 1):
        lo = carry_min[index]
        hi = carry_max[index]
        if lo == hi:
            lower_carries.append(model.NewConstant(lo))
        else:
            lower_carries.append(model.NewIntVar(lo, hi, f"c_{index}"))

    lower_product_vars = []
    lower_linear_terms = 0
    lower_constant_terms = 0
    for index in range(args.skip_known_prefix_limbs, lower_limb_count):
        terms = []
        constant_sum = 0
        for j in range(index + 1):
            p_term = p_limbs[j]
            q_term = q_limbs[index - j]
            if (isinstance(p_term, int) and p_term == 0) or (isinstance(q_term, int) and q_term == 0):
                continue
            if isinstance(p_term, int) and isinstance(q_term, int):
                constant_sum += p_term * q_term
                lower_constant_terms += 1
            elif isinstance(p_term, int):
                terms.append(p_term * q_term)
                lower_linear_terms += 1
            elif isinstance(q_term, int):
                terms.append(q_term * p_term)
                lower_linear_terms += 1
            else:
                product_min = p_limb_min[j] * q_limb_min[index - j]
                product_max = p_limb_max[j] * q_limb_max[index - j]
                product = model.NewIntVar(product_min, product_max, f"pq_{j}_{index - j}")
                model.AddMultiplicationEquality(product, [p_term, q_term])
                lower_product_vars.append(product)
                terms.append(product)

        model.Add(
            sum(terms) + constant_sum + lower_carries[index]
            == n_lower_limbs[index] + base * lower_carries[index + 1]
        )

    tail_carries = [lower_carries[lower_limb_count]]
    for index in range(1, args.tail_limbs + 1):
        carry_index = lower_limb_count + index
        lo = carry_min[carry_index]
        hi = carry_max[carry_index]
        if lo == hi:
            tail_carries.append(model.NewConstant(lo))
        else:
            tail_carries.append(model.NewIntVar(lo, hi, f"tc_{index}"))

    tail_low_product_vars = []
    tail_linear_terms = 0
    tail_constant_terms = 0
    for index in range(args.tail_limbs):
        terms = [tail_carries[index]]
        constant_sum = 0

        low_column = lower_limb_count + index
        lo = max(0, low_column - lower_limb_count + 1)
        hi = min(lower_limb_count - 1, low_column)
        for i in range(lo, hi + 1):
            p_term = p_limbs[i]
            q_term = q_limbs[low_column - i]
            if (isinstance(p_term, int) and p_term == 0) or (isinstance(q_term, int) and q_term == 0):
                continue
            if isinstance(p_term, int) and isinstance(q_term, int):
                constant_sum += p_term * q_term
                tail_constant_terms += 1
            elif isinstance(p_term, int):
                terms.append(p_term * q_term)
                tail_linear_terms += 1
            elif isinstance(q_term, int):
                terms.append(q_term * p_term)
                tail_linear_terms += 1
            else:
                product_min = p_limb_min[i] * q_limb_min[low_column - i]
                product_max = p_limb_max[i] * q_limb_max[low_column - i]
                product = model.NewIntVar(product_min, product_max, f"tail_pq_{i}_{low_column - i}")
                model.AddMultiplicationEquality(product, [p_term, q_term])
                tail_low_product_vars.append(product)
                terms.append(product)

        for i, q_limb in enumerate(q_limbs):
            h = index - i
            if 0 <= h < len(p_high_limbs) and p_high_limbs[h]:
                terms.append(p_high_limbs[h] * q_limb)
                tail_linear_terms += int(not isinstance(q_limb, int))
                tail_constant_terms += int(isinstance(q_limb, int))

        for i, p_limb in enumerate(p_limbs):
            h = index - i
            if 0 <= h < len(q_high_limbs) and q_high_limbs[h]:
                terms.append(q_high_limbs[h] * p_limb)
                tail_linear_terms += int(not isinstance(p_limb, int))
                tail_constant_terms += int(isinstance(p_limb, int))

        if index >= lower_limb_count:
            product_index = index - lower_limb_count
            if product_index < len(high_product_limbs):
                constant_sum += high_product_limbs[product_index]

        model.Add(sum(terms) + constant_sum == n_tail_limbs[index] + base * tail_carries[index + 1])

    if final_carry_zero:
        model.Add(tail_carries[complete_tail_limb_count] == 0)

    decision_vars = []
    decision_p_vars = []
    decision_q_vars = []
    seen_p_bits = set()
    for start, width in args.decision_p_range:
        for bit in range(start, start + width):
            var = p_unknown_by_bit.get(bit)
            if var is not None and bit not in seen_p_bits:
                decision_vars.append(var)
                decision_p_vars.append(var)
                seen_p_bits.add(bit)

    seen_q_limb_indices = set()
    for start, width in args.decision_q_range:
        first_limb = start // args.limb_bits
        last_limb = (start + width - 1) // args.limb_bits
        for index in range(first_limb, min(last_limb + 1, len(q_limbs))):
            limb = q_limbs[index]
            if isinstance(limb, int) or index in seen_q_limb_indices:
                continue
            decision_vars.append(limb)
            decision_q_vars.append(limb)
            seen_q_limb_indices.add(index)
    if decision_vars:
        select_strategy = (
            cp_model.SELECT_MAX_VALUE
            if args.decision_select == "max"
            else cp_model.SELECT_MIN_VALUE
        )
        model.AddDecisionStrategy(decision_vars, cp_model.CHOOSE_FIRST, select_strategy)

    small_prime_filters = []
    odd_residue_primes = []

    def is_odd_prime(candidate: int) -> bool:
        if candidate < 3 or candidate % 2 == 0:
            return False
        divisor = 3
        while divisor * divisor <= candidate:
            if candidate % divisor == 0:
                return False
            divisor += 2
        return True

    def first_odd_primes(count: int) -> list[int]:
        primes = []
        candidate = 3
        while len(primes) < count:
            if is_odd_prime(candidate) and n % candidate != 0:
                primes.append(candidate)
            candidate += 2
        return primes

    def parse_prime_list(text: str) -> list[int]:
        primes = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            prime = int(part, 0)
            if not is_odd_prime(prime):
                raise SystemExit(f"not an odd prime: {prime}")
            if n % prime == 0:
                continue
            if (prime - 1) * (prime - 1) > CP_SAT_INT_LIMIT:
                raise SystemExit(f"odd residue prime too large for CP-SAT product domain: {prime}")
            mod_input_bound = prime * limb_mask * lower_limb_count + prime
            if mod_input_bound > CP_SAT_INT_LIMIT:
                raise SystemExit(f"odd residue prime too large for CP-SAT linear domain: {prime}")
            primes.append(prime)
        return primes

    def add_mod_input(prefix: str, prime: int, limbs, high_value: int):
        terms = []
        const = (high_value * pow(base, lower_limb_count, prime)) % prime
        weight = 1
        max_total = const
        for limb in limbs:
            if isinstance(limb, int):
                const = (const + weight * limb) % prime
            else:
                terms.append(weight * limb)
                max_total += weight * limb.Proto().domain[-1]
            weight = (weight * base) % prime
        total = model.NewIntVar(0, max_total, f"{prefix}_mod_input_{prime}")
        model.Add(total == sum(terms) + const)
        rem = model.NewIntVar(0, prime - 1, f"{prefix}_mod_{prime}")
        model.AddModuloEquality(rem, total, prime)
        return rem

    if args.small_prime_filters > 0:
        small_prime_filters = first_odd_primes(args.small_prime_filters)

        for prime in small_prime_filters:
            p_rem = add_mod_input("p", prime, p_limbs, p_high)
            q_rem = add_mod_input("q", prime, q_limbs, q_high)
            model.Add(p_rem != 0)
            model.Add(q_rem != 0)

    if args.odd_residue_filters > 0:
        odd_residue_primes.extend(first_odd_primes(args.odd_residue_filters))
    if args.odd_residue_primes:
        odd_residue_primes.extend(parse_prime_list(args.odd_residue_primes))
    odd_residue_primes = sorted(set(odd_residue_primes))
    for prime in odd_residue_primes:
        p_rem = add_mod_input("p_res", prime, p_limbs, p_high)
        q_rem = add_mod_input("q_res", prime, q_limbs, q_high)
        product = model.NewIntVar(0, (prime - 1) * (prime - 1), f"pq_mod_product_{prime}")
        model.AddMultiplicationEquality(product, [p_rem, q_rem])
        residue = model.NewIntVar(0, prime - 1, f"pq_mod_{prime}")
        model.AddModuloEquality(residue, product, prime)
        model.Add(residue == n % prime)

    print(f"T={args.T}")
    print(f"limb bits: {args.limb_bits}")
    print(f"lower limbs: {lower_limb_count}")
    print(f"tail limbs enforced: {args.tail_limbs}")
    branch_low_text = "free" if args.free_branch_low else f"{args.branch_low:x}"
    branch_high_text = "free" if args.free_branch_high else f"{args.branch_high:x}"
    print(f"branch x0={branch_low_text}, x7={branch_high_text}")
    for fixed_start, fixed_width, fixed_value in args.fix_p_range:
        print(f"fixed p[{fixed_start}..{fixed_start + fixed_width - 1}] = {fixed_value:#x}")
    for fixed_start, fixed_width, fixed_value in args.fix_q_range:
        print(f"fixed q[{fixed_start}..{fixed_start + fixed_width - 1}] = {fixed_value:#x}")
    print(f"q low known bits: {low_known_bits}")
    print(f"q high common bits: {q_prefix_bits}")
    print(f"q prefix start: {q_prefix_start}")
    print(f"q prefix bits inside T: {max(0, args.T - q_prefix_start)}")
    print(f"q interval lower bits: {q_low_min.bit_length()}")
    print(f"q interval upper bits: {q_low_max.bit_length()}")
    print(f"q interval constraints: {q_interval_constraints}")
    print(f"lowlift q bits: {args.lowlift_q}")
    print(f"lowlift q constraints: {lowlift_q_constraints}")
    print(f"p tail known: {p_unknown_above_t == 0}")
    print(f"q tail known: {q_unknown_above_t == 0}")
    print(f"p_high bits: {p_high.bit_length()}")
    print(f"q_high bits: {q_high.bit_length()}")
    print(f"p unknown bools in T: {p_unknown_bits}")
    print(f"q fixed bits in T: {args.T - q_unknown_bits}")
    print(f"q bools in T: {q_unknown_bits}")
    print(f"q BoolVars in T: {len(q_unknown_bools)}")
    print(f"compact q limbs: {args.compact_q_limbs}")
    print(f"p variable limbs: {p_variable_limbs}")
    print(f"q variable limbs: {q_variable_limbs}")
    print(f"skip known prefix limbs: {args.skip_known_prefix_limbs}")
    print(f"skipped prefix carry: {skipped_prefix_carry}")
    print(f"lower product vars: {len(lower_product_vars)}")
    print(f"tail low-low product vars: {len(tail_low_product_vars)}")
    print(f"lower linear product terms: {lower_linear_terms}")
    print(f"lower constant product terms: {lower_constant_terms}")
    print(f"tail linear terms: {tail_linear_terms}")
    print(f"tail constant terms: {tail_constant_terms}")
    print(f"lower carry bound: {lower_carry_bound}")
    print(f"tail carry bound: {tail_carry_bound}")
    print(f"tightened carry singletons: {tightened_carry_singletons} / {len(carry_min)}")
    print(f"tightened max carry width bits: {tightened_carry_width_bits}")
    print(f"complete tail limbs: {complete_tail_limb_count}")
    print(f"final carry zero enforced: {final_carry_zero}")
    print(f"small prime filters: {len(small_prime_filters)}")
    print(f"odd residue filters: {len(odd_residue_primes)}")
    print(f"decision p bools: {len(decision_p_vars)}")
    print(f"decision q limbs: {len(decision_q_vars)}")
    print(f"decision select: {args.decision_select}")
    print(f"random seed: {args.random_seed}")
    print(f"randomize search: {args.randomize_search}")
    print(f"phase saving: {not args.no_phase_saving}")

    summary = {
        "T": args.T,
        "limb_bits": args.limb_bits,
        "lower_limbs": lower_limb_count,
        "tail_limbs": args.tail_limbs,
        "branch_low": None if args.free_branch_low else args.branch_low,
        "branch_high": None if args.free_branch_high else args.branch_high,
        "free_branch_low": args.free_branch_low,
        "free_branch_high": args.free_branch_high,
        "fixed_p_ranges": [
            {"start": fixed_start, "width": fixed_width, "value": fixed_value}
            for fixed_start, fixed_width, fixed_value in args.fix_p_range
        ],
        "fixed_q_ranges": [
            {"start": fixed_start, "width": fixed_width, "value": fixed_value}
            for fixed_start, fixed_width, fixed_value in args.fix_q_range
        ],
        "q_low_known_bits": low_known_bits,
        "q_high_common_bits": q_prefix_bits,
        "q_prefix_start": q_prefix_start,
        "q_prefix_bits_inside_T": max(0, args.T - q_prefix_start),
        "q_interval_lower_bits": q_low_min.bit_length(),
        "q_interval_upper_bits": q_low_max.bit_length(),
        "q_interval_constraints": q_interval_constraints,
        "lowlift_q_bits": args.lowlift_q,
        "lowlift_q_constraints": lowlift_q_constraints,
        "p_tail_known": p_unknown_above_t == 0,
        "q_tail_known": q_unknown_above_t == 0,
        "p_high_bits": p_high.bit_length(),
        "q_high_bits": q_high.bit_length(),
        "p_unknown_bools_in_T": p_unknown_bits,
        "q_fixed_bits_in_T": args.T - q_unknown_bits,
        "q_bools_in_T": q_unknown_bits,
        "q_bool_vars_in_T": len(q_unknown_bools),
        "compact_q_limbs": args.compact_q_limbs,
        "p_variable_limbs": p_variable_limbs,
        "q_variable_limbs": q_variable_limbs,
        "skip_known_prefix_limbs": args.skip_known_prefix_limbs,
        "skipped_prefix_carry": skipped_prefix_carry,
        "lower_product_vars": len(lower_product_vars),
        "tail_low_low_product_vars": len(tail_low_product_vars),
        "lower_linear_product_terms": lower_linear_terms,
        "lower_constant_product_terms": lower_constant_terms,
        "tail_linear_terms": tail_linear_terms,
        "tail_constant_terms": tail_constant_terms,
        "lower_carry_bound": lower_carry_bound,
        "tail_carry_bound": tail_carry_bound,
        "tightened_carry_singletons": tightened_carry_singletons,
        "tightened_max_carry_width_bits": tightened_carry_width_bits,
        "complete_tail_limb_count": complete_tail_limb_count,
        "final_carry_zero_enforced": final_carry_zero,
        "small_prime_filters": len(small_prime_filters),
        "odd_residue_filters": len(odd_residue_primes),
        "decision_p_bools": len(decision_p_vars),
        "decision_q_limbs": len(decision_q_vars),
        "decision_select": args.decision_select,
        "random_seed": args.random_seed,
        "randomize_search": args.randomize_search,
        "phase_saving": not args.no_phase_saving,
        "status": "BUILD_ONLY" if args.build_only else None,
    }

    if args.build_only:
        if args.json_summary:
            print(json.dumps(summary, sort_keys=True))
        return 0

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.time_limit
    solver.parameters.num_search_workers = args.workers
    solver.parameters.log_search_progress = args.log
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 2
    if args.random_seed is not None:
        solver.parameters.random_seed = args.random_seed
    solver.parameters.randomize_search = args.randomize_search
    solver.parameters.use_phase_saving = not args.no_phase_saving
    if decision_vars:
        solver.parameters.search_branching = cp_model.FIXED_SEARCH

    status = solver.Solve(model)
    status_name = solver.StatusName(status)
    wall_time = solver.WallTime()
    branches = solver.NumBranches()
    conflicts = solver.NumConflicts()
    branches_per_sec = branches / wall_time if wall_time > 0 else 0.0
    conflicts_per_sec = conflicts / wall_time if wall_time > 0 else 0.0
    print(f"status: {status_name}")
    print(f"wall time: {wall_time:.2f}s")
    print(f"branches: {branches}")
    print(f"conflicts: {conflicts}")
    print(f"branches/sec: {branches_per_sec:.2f}")
    print(f"conflicts/sec: {conflicts_per_sec:.2f}")

    if status in {cp_model.FEASIBLE, cp_model.OPTIMAL}:
        def solved_value(value):
            return value if isinstance(value, int) else solver.Value(value)

        p_low_value = sum(solved_value(limb) << (args.limb_bits * index) for index, limb in enumerate(p_limbs))
        q_low_value = sum(solved_value(limb) << (args.limb_bits * index) for index, limb in enumerate(q_limbs))
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
            d = pow(constants.E, -1, phi)
            plaintext = pow(int(constants.CT_HEX.replace(" ", ""), 16), d, n)
            plaintext_bytes = plaintext.to_bytes((plaintext.bit_length() + 7) // 8, "big")
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
        summary.update({
            "status": status_name,
            "wall_time": wall_time,
            "branches": branches,
            "conflicts": conflicts,
            "branches_per_sec": branches_per_sec,
            "conflicts_per_sec": conflicts_per_sec,
        })
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
