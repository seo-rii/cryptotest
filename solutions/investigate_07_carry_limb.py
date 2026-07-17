#!/usr/bin/env python3
"""Inspect 16-bit limb carry constraints for challenge 7.

This is not a complete solver.  It quantifies how much pruning is available
from the low/high bit leaks before using a heavier SMT/CP-SAT or lattice step.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--limb-bits", type=int, default=16)
parser.add_argument("--branch-low", type=lambda x: int(x, 0), default=0)
parser.add_argument("--branch-high", type=lambda x: int(x, 0), default=0)
parser.add_argument("--x6-top-bits", type=int, default=0, help="number of top bits of p[784..829] fixed")
parser.add_argument("--x6-top", type=lambda x: int(x, 0), default=0, help="value for the fixed x6 top bits")
parser.add_argument(
    "--fix-p-range",
    action="append",
    default=[],
    help="fix p bits as START:WIDTH:VALUE; can be repeated for cube experiments",
)
parser.add_argument("--sweep", action="store_true", help="check all 256 nibble branches")
parser.add_argument("--max-frontier-enum", type=int, default=1 << 18)
parser.add_argument(
    "--exact-carry",
    action="store_true",
    help="run exact local carry-set propagation; intended for 4-bit limbs",
)
parser.add_argument(
    "--emit-frontier-values",
    action="store_true",
    help="print sample low/high frontier assignments for a single branch",
)
parser.add_argument(
    "--frontier-value-limit",
    type=int,
    default=64,
    help="maximum frontier assignments to print per branch",
)
args = parser.parse_args()

if args.limb_bits <= 0 or 1024 % args.limb_bits != 0:
    raise SystemExit("--limb-bits must divide 1024")
if args.exact_carry and args.limb_bits > 8:
    raise SystemExit("--exact-carry is intentionally limited to limb sizes <= 8")
if not (0 <= args.x6_top_bits <= 46):
    raise SystemExit("--x6-top-bits must be in 0..46")
if args.x6_top_bits and not (0 <= args.x6_top < (1 << args.x6_top_bits)):
    raise SystemExit("--x6-top must fit in --x6-top-bits")


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


fixed_p_ranges = [parse_fixed_range(item) for item in args.fix_p_range]

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "investigate_07", root / "solutions" / "investigate_07_rsa_partial_bits.py"
)
if spec is None or spec.loader is None:
    raise SystemExit("failed to load challenge 7 constants")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

n = int(module.N_HEX.replace(" ", ""), 16)
mask = int(module.MASK_HEX.replace(" ", ""), 16)
known = int(module.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
full_p_mask = (1 << 1024) - 1
unknown_mask = full_p_mask ^ mask
base = 1 << args.limb_bits
limb_mask = base - 1
p_limbs_count = 1024 // args.limb_bits
n_limbs_count = 2048 // args.limb_bits
n_limbs = [(n >> (args.limb_bits * i)) & limb_mask for i in range(n_limbs_count)]

branches = [(args.branch_low, args.branch_high)]
if args.sweep:
    branches = [(lo, hi) for lo in range(16) for hi in range(16)]

summary = []


def iter_set_bits(value: int):
    while value:
        low_bit = value & -value
        yield low_bit.bit_length() - 1
        value ^= low_bit


def bit_range(lo: int, hi: int) -> int:
    if hi < lo:
        return 0
    return ((1 << (hi - lo + 1)) - 1) << lo


def shift_bits(value: int, offset: int) -> int:
    if offset >= 0:
        return value << offset
    return value >> -offset


def limb_domain(known_mask: int, known_value: int) -> tuple[int, ...]:
    return tuple(
        value
        for value in range(base)
        if (value & known_mask) == (known_value & known_mask)
    )


@functools.lru_cache(maxsize=None)
def product_domain(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted({a * b for a in left for b in right}))


def column_sum_quotients(
    column: int,
    p_domains: list[tuple[int, ...]],
    q_domains: list[tuple[int, ...]],
) -> list[int]:
    sum_bits = 1
    for i in range(max(0, column - p_limbs_count + 1), min(p_limbs_count - 1, column) + 1):
        j = column - i
        if 0 <= j < p_limbs_count:
            values = product_domain(p_domains[i], q_domains[j])
            next_bits = 0
            for value in values:
                next_bits |= sum_bits << value
            sum_bits = next_bits

    quotient_bits = [0] * base
    for value in iter_set_bits(sum_bits):
        quotient_bits[value & limb_mask] |= 1 << (value >> args.limb_bits)
    return quotient_bits


def exact_carry_propagation(
    p_domains: list[tuple[int, ...]],
    q_domains: list[tuple[int, ...]],
    carry_min: list[int],
    carry_max: list[int],
) -> tuple[bool, list[int], int]:
    quotient_sets = [
        column_sum_quotients(column, p_domains, q_domains)
        for column in range(n_limbs_count)
    ]
    carry_sets = [
        bit_range(carry_min[column], carry_max[column])
        for column in range(n_limbs_count + 1)
    ]
    carry_sets[0] &= 1
    carry_sets[n_limbs_count] &= 1

    def next_carries(column: int, carry: int) -> int:
        residue = (n_limbs[column] - carry) & limb_mask
        offset = (carry + residue - n_limbs[column]) // base
        return shift_bits(quotient_sets[column][residue], offset)

    iterations = 0
    for iterations in range(1, 101):
        changed = False
        for column in range(n_limbs_count):
            allowed_next = 0
            for carry in iter_set_bits(carry_sets[column]):
                allowed_next |= next_carries(column, carry)
            new_next = carry_sets[column + 1] & allowed_next
            if new_next != carry_sets[column + 1]:
                carry_sets[column + 1] = new_next
                changed = True

        for column in range(n_limbs_count - 1, -1, -1):
            allowed_current = 0
            for carry in iter_set_bits(carry_sets[column]):
                if next_carries(column, carry) & carry_sets[column + 1]:
                    allowed_current |= 1 << carry
            if allowed_current != carry_sets[column]:
                carry_sets[column] = allowed_current
                changed = True

        if any(value == 0 for value in carry_sets):
            return False, carry_sets, iterations
        if not changed:
            break

    return True, carry_sets, iterations

for branch_low, branch_high in branches:
    if not (0 <= branch_low < 16 and 0 <= branch_high < 16):
        raise SystemExit("branch nibbles must be in 0..15")

    branch_known = known | (branch_low << 150) | (branch_high << 920)
    branch_mask = mask | (0xF << 150) | (0xF << 920)
    if args.x6_top_bits:
        x6_top_offset = 830 - args.x6_top_bits
        branch_known |= args.x6_top << x6_top_offset
        branch_mask |= ((1 << args.x6_top_bits) - 1) << x6_top_offset
    for fixed_start, fixed_width, fixed_value in fixed_p_ranges:
        fixed_mask = ((1 << fixed_width) - 1) << fixed_start
        fixed_bits = fixed_value << fixed_start
        if ((branch_known ^ fixed_bits) & (branch_mask & fixed_mask)) != 0:
            raise SystemExit(
                f"inconsistent --fix-p-range {fixed_start}:{fixed_width}:{fixed_value:#x}"
            )
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

    p_limb_min = []
    p_limb_max = []
    p_limb_known_mask = []
    p_limb_known = []
    q_limb_min = []
    q_limb_max = []
    q_limb_known_mask = []
    q_limb_known = []

    for i in range(p_limbs_count):
        shift = args.limb_bits * i
        p_known_mask_i = (branch_mask >> shift) & limb_mask
        p_known_i = (branch_known >> shift) & limb_mask
        p_limb_known_mask.append(p_known_mask_i)
        p_limb_known.append(p_known_i & p_known_mask_i)
        p_limb_min.append(p_known_i & p_known_mask_i)
        p_limb_max.append((p_known_i & p_known_mask_i) | (limb_mask ^ p_known_mask_i))

        q_known_mask_i = (q_known_mask >> shift) & limb_mask
        q_known_i = (q_known >> shift) & limb_mask
        q_limb_known_mask.append(q_known_mask_i)
        q_limb_known.append(q_known_i & q_known_mask_i)
        q_limb_min.append(q_known_i & q_known_mask_i)
        q_limb_max.append((q_known_i & q_known_mask_i) | (limb_mask ^ q_known_mask_i))

    carry_min = [0] + [0] * n_limbs_count
    carry_max = [0] + [10**100] * n_limbs_count
    carry_min[n_limbs_count] = 0
    carry_max[n_limbs_count] = 0

    for _ in range(100):
        changed = False
        for k in range(n_limbs_count):
            s_min = 0
            s_max = 0
            for i in range(max(0, k - p_limbs_count + 1), min(p_limbs_count - 1, k) + 1):
                j = k - i
                if 0 <= j < p_limbs_count:
                    s_min += p_limb_min[i] * q_limb_min[j]
                    s_max += p_limb_max[i] * q_limb_max[j]
            next_min = max(0, (carry_min[k] + s_min - n_limbs[k] + base - 1) // base)
            next_max = max(0, (carry_max[k] + s_max - n_limbs[k]) // base)
            if next_min > carry_min[k + 1]:
                carry_min[k + 1] = next_min
                changed = True
            if next_max < carry_max[k + 1]:
                carry_max[k + 1] = next_max
                changed = True
        for k in range(n_limbs_count - 1, -1, -1):
            s_min = 0
            s_max = 0
            for i in range(max(0, k - p_limbs_count + 1), min(p_limbs_count - 1, k) + 1):
                j = k - i
                if 0 <= j < p_limbs_count:
                    s_min += p_limb_min[i] * q_limb_min[j]
                    s_max += p_limb_max[i] * q_limb_max[j]
            prev_min = max(0, n_limbs[k] + base * carry_min[k + 1] - s_max)
            prev_max = max(0, n_limbs[k] + base * carry_max[k + 1] - s_min)
            if prev_min > carry_min[k]:
                carry_min[k] = prev_min
                changed = True
            if prev_max < carry_max[k]:
                carry_max[k] = prev_max
                changed = True
        if not changed:
            break

    impossible = any(lo > hi for lo, hi in zip(carry_min, carry_max))
    deterministic_low_columns = 0
    exact_carry = 0
    for k in range(n_limbs_count):
        all_singleton = True
        s_value = 0
        for i in range(max(0, k - p_limbs_count + 1), min(p_limbs_count - 1, k) + 1):
            j = k - i
            if 0 <= j < p_limbs_count:
                if p_limb_min[i] != p_limb_max[i] or q_limb_min[j] != q_limb_max[j]:
                    all_singleton = False
                    break
                s_value += p_limb_min[i] * q_limb_min[j]
        if not all_singleton:
            break
        exact_carry = (exact_carry + s_value - n_limbs[k]) // base
        deterministic_low_columns += 1

    frontier_pairs = None
    frontier_carry_min = None
    frontier_carry_max = None
    frontier_records = []
    frontier_column = deterministic_low_columns
    if frontier_column < n_limbs_count and exact_carry >= 0:
        variable_terms = []
        constant_sum = 0
        for i in range(
            max(0, frontier_column - p_limbs_count + 1),
            min(p_limbs_count - 1, frontier_column) + 1,
        ):
            j = frontier_column - i
            if 0 <= j < p_limbs_count:
                p_single = p_limb_min[i] == p_limb_max[i]
                q_single = q_limb_min[j] == q_limb_max[j]
                if p_single and q_single:
                    constant_sum += p_limb_min[i] * q_limb_min[j]
                elif not p_single and q_single:
                    variable_terms.append(("p", i, q_limb_min[j]))
                elif p_single and not q_single:
                    variable_terms.append(("q", j, p_limb_min[i]))
                else:
                    variable_terms.append(("pq", i, j))
        if (
            len(variable_terms) == 2
            and variable_terms[0][0] in {"p", "q"}
            and variable_terms[1][0] in {"p", "q"}
            and variable_terms[0][0] != variable_terms[1][0]
        ):
            first_kind, first_index, first_coeff = variable_terms[0]
            second_kind, second_index, second_coeff = variable_terms[1]
            if second_coeff % 2 == 1:
                inv_second = pow(second_coeff, -1, base)
                target = (n_limbs[frontier_column] - exact_carry - constant_sum) % base
                if first_kind == "p":
                    first_known_mask = p_limb_known_mask[first_index]
                    first_known = p_limb_known[first_index]
                else:
                    first_known_mask = q_limb_known_mask[first_index]
                    first_known = q_limb_known[first_index]
                if second_kind == "p":
                    second_known_mask = p_limb_known_mask[second_index]
                    second_known = p_limb_known[second_index]
                else:
                    second_known_mask = q_limb_known_mask[second_index]
                    second_known = q_limb_known[second_index]

                first_unknown_bits = args.limb_bits - first_known_mask.bit_count()
                if (1 << first_unknown_bits) <= args.max_frontier_enum:
                    frontier_pairs = 0
                    carry_values = set()
                    unknown_positions = [
                        bit for bit in range(args.limb_bits) if ((first_known_mask >> bit) & 1) == 0
                    ]
                    for value_index in range(1 << first_unknown_bits):
                        first_value = first_known
                        for pos_index, bit in enumerate(unknown_positions):
                            if (value_index >> pos_index) & 1:
                                first_value |= 1 << bit
                        second_value = ((target - first_coeff * first_value) * inv_second) % base
                        if (second_value & second_known_mask) != second_known:
                            continue
                        frontier_pairs += 1
                        total = constant_sum + first_coeff * first_value + second_coeff * second_value
                        carry = (exact_carry + total - n_limbs[frontier_column]) // base
                        carry_values.add(carry)
                        if args.emit_frontier_values and len(frontier_records) < args.frontier_value_limit:
                            frontier_records.append(
                                (
                                    frontier_column,
                                    first_kind,
                                    first_index,
                                    first_value,
                                    second_kind,
                                    second_index,
                                    second_value,
                                    carry,
                                )
                            )
                    if carry_values:
                        frontier_carry_min = min(carry_values)
                        frontier_carry_max = max(carry_values)

    deterministic_high_columns = 0
    next_high_carry = 0
    for k in range(n_limbs_count - 1, -1, -1):
        all_singleton = True
        s_value = 0
        for i in range(max(0, k - p_limbs_count + 1), min(p_limbs_count - 1, k) + 1):
            j = k - i
            if 0 <= j < p_limbs_count:
                if p_limb_min[i] != p_limb_max[i] or q_limb_min[j] != q_limb_max[j]:
                    all_singleton = False
                    break
                s_value += p_limb_min[i] * q_limb_min[j]
        if not all_singleton:
            break
        previous_carry = n_limbs[k] + base * next_high_carry - s_value
        if previous_carry < 0:
            break
        next_high_carry = previous_carry
        deterministic_high_columns += 1

    high_frontier_values = None
    high_frontier_carry_min = None
    high_frontier_carry_max = None
    high_frontier_records = []
    high_frontier_column = n_limbs_count - 1 - deterministic_high_columns
    if high_frontier_column >= 0:
        var_coeffs = {}
        nonlinear = False
        constant_sum = 0
        for i in range(
            max(0, high_frontier_column - p_limbs_count + 1),
            min(p_limbs_count - 1, high_frontier_column) + 1,
        ):
            j = high_frontier_column - i
            if 0 <= j < p_limbs_count:
                p_single = p_limb_min[i] == p_limb_max[i]
                q_single = q_limb_min[j] == q_limb_max[j]
                if p_single and q_single:
                    constant_sum += p_limb_min[i] * q_limb_min[j]
                elif not p_single and q_single:
                    key = ("p", i)
                    var_coeffs[key] = var_coeffs.get(key, 0) + q_limb_min[j]
                elif p_single and not q_single:
                    key = ("q", j)
                    var_coeffs[key] = var_coeffs.get(key, 0) + p_limb_min[i]
                else:
                    nonlinear = True
                    break
        if not nonlinear and len(var_coeffs) <= 2:
            value_options = []
            total_options = 1
            for kind, index in var_coeffs:
                if kind == "p":
                    known_mask_i = p_limb_known_mask[index]
                    known_i = p_limb_known[index]
                else:
                    known_mask_i = q_limb_known_mask[index]
                    known_i = q_limb_known[index]
                positions = [
                    bit for bit in range(args.limb_bits) if ((known_mask_i >> bit) & 1) == 0
                ]
                total_options *= 1 << len(positions)
                value_options.append((kind, index, known_i, positions))
            if total_options <= args.max_frontier_enum:
                high_frontier_values = 0
                high_carries = set()
                if not value_options:
                    carry = n_limbs[high_frontier_column] + base * next_high_carry - constant_sum
                    if carry_min[high_frontier_column] <= carry <= carry_max[high_frontier_column]:
                        high_frontier_values = 1
                        high_carries.add(carry)
                elif len(value_options) == 1:
                    kind, index, known_i, positions = value_options[0]
                    coeff = var_coeffs[(kind, index)]
                    for value_index in range(1 << len(positions)):
                        value = known_i
                        for pos_index, bit in enumerate(positions):
                            if (value_index >> pos_index) & 1:
                                value |= 1 << bit
                        total = constant_sum + coeff * value
                        carry = n_limbs[high_frontier_column] + base * next_high_carry - total
                        if carry_min[high_frontier_column] <= carry <= carry_max[high_frontier_column]:
                            high_frontier_values += 1
                            high_carries.add(carry)
                            if args.emit_frontier_values and len(high_frontier_records) < args.frontier_value_limit:
                                high_frontier_records.append(
                                    (
                                        high_frontier_column,
                                        kind,
                                        index,
                                        value,
                                        carry,
                                    )
                                )
                elif len(value_options) == 2:
                    first = value_options[0]
                    second = value_options[1]
                    first_coeff = var_coeffs[(first[0], first[1])]
                    second_coeff = var_coeffs[(second[0], second[1])]
                    for first_index in range(1 << len(first[3])):
                        first_value = first[2]
                        for pos_index, bit in enumerate(first[3]):
                            if (first_index >> pos_index) & 1:
                                first_value |= 1 << bit
                        for second_index in range(1 << len(second[3])):
                            second_value = second[2]
                            for pos_index, bit in enumerate(second[3]):
                                if (second_index >> pos_index) & 1:
                                    second_value |= 1 << bit
                            total = constant_sum + first_coeff * first_value + second_coeff * second_value
                            carry = n_limbs[high_frontier_column] + base * next_high_carry - total
                            if carry_min[high_frontier_column] <= carry <= carry_max[high_frontier_column]:
                                high_frontier_values += 1
                                high_carries.add(carry)
                                if args.emit_frontier_values and len(high_frontier_records) < args.frontier_value_limit:
                                    high_frontier_records.append(
                                        (
                                            high_frontier_column,
                                            first[0],
                                            first[1],
                                            first_value,
                                            second[0],
                                            second[1],
                                            second_value,
                                            carry,
                                        )
                                    )
                if high_carries:
                    high_frontier_carry_min = min(high_carries)
                    high_frontier_carry_max = max(high_carries)

    singleton_carries = sum(1 for lo, hi in zip(carry_min, carry_max) if lo == hi)
    max_carry_width_bits = 0
    for lo, hi in zip(carry_min, carry_max):
        if lo <= hi:
            max_carry_width_bits = max(max_carry_width_bits, (hi - lo + 1).bit_length())

    exact_possible = None
    exact_iterations = None
    exact_singleton_carries = None
    exact_max_carry_set_size = None
    if args.exact_carry and not impossible:
        p_domains = [
            limb_domain(p_limb_known_mask[i], p_limb_known[i])
            for i in range(p_limbs_count)
        ]
        q_domains = [
            limb_domain(q_limb_known_mask[i], q_limb_known[i])
            for i in range(p_limbs_count)
        ]
        exact_possible, exact_carry_sets, exact_iterations = exact_carry_propagation(
            p_domains,
            q_domains,
            carry_min,
            carry_max,
        )
        exact_singleton_carries = sum(
            1 for carry_set in exact_carry_sets if carry_set.bit_count() == 1
        )
        exact_max_carry_set_size = max(carry_set.bit_count() for carry_set in exact_carry_sets)

    summary.append(
        (
            branch_low,
            branch_high,
            impossible,
            high_common,
            deterministic_low_columns,
            frontier_column,
            frontier_pairs,
            frontier_carry_min,
            frontier_carry_max,
            deterministic_high_columns,
            high_frontier_column,
            high_frontier_values,
            high_frontier_carry_min,
            high_frontier_carry_max,
            singleton_carries,
            max_carry_width_bits,
            exact_possible,
            exact_iterations,
            exact_singleton_carries,
            exact_max_carry_set_size,
            low_bits,
        )
    )

if args.sweep:
    possible = [row for row in summary if not row[2]]
    print(f"branches checked: {len(summary)}")
    print(f"branches impossible by interval carry bounds: {len(summary) - len(possible)}")
    print(
        "q high common bits: "
        f"min={min(row[3] for row in possible)}, max={max(row[3] for row in possible)}"
    )
    print(
        "q low known bits: "
        f"min={min(row[20] for row in possible)}, max={max(row[20] for row in possible)}"
    )
    print(
        "deterministic low limb columns: "
        f"min={min(row[4] for row in possible)}, max={max(row[4] for row in possible)}"
    )
    print(
        "deterministic high limb columns: "
        f"min={min(row[9] for row in possible)}, max={max(row[9] for row in possible)}"
    )
    frontier_counts = [row[6] for row in possible if row[6] is not None]
    if frontier_counts:
        print(
            f"first low frontier pair count (enumerated {len(frontier_counts)}/{len(possible)}): "
            f"min={min(frontier_counts)}, max={max(frontier_counts)}"
        )
    high_frontier_counts = [row[11] for row in possible if row[11] is not None]
    if high_frontier_counts:
        print(
            f"first high frontier value count (enumerated {len(high_frontier_counts)}/{len(possible)}): "
            f"min={min(high_frontier_counts)}, max={max(high_frontier_counts)}"
        )
    print(
        "max carry interval width bits after propagation: "
        f"min={min(row[15] for row in possible)}, max={max(row[15] for row in possible)}"
    )
    exact_rows = [row for row in summary if row[16] is not None]
    if exact_rows:
        exact_possible = [row for row in exact_rows if row[16]]
        print(
            "branches impossible by exact carry sets: "
            f"{len(exact_rows) - len(exact_possible)} / {len(exact_rows)}"
        )
        if exact_possible:
            print(
                "exact carry propagation iterations: "
                f"min={min(row[17] for row in exact_possible)}, max={max(row[17] for row in exact_possible)}"
            )
            print(
                "exact singleton carry sets: "
                f"min={min(row[18] for row in exact_possible)}, max={max(row[18] for row in exact_possible)}"
            )
            print(
                "exact max carry-set cardinality: "
                f"min={min(row[19] for row in exact_possible)}, max={max(row[19] for row in exact_possible)}"
            )
else:
    row = summary[0]
    branch_label = f"branch x0={row[0]:x}, x7={row[1]:x}"
    if args.x6_top_bits:
        branch_label += f", x6_top[{args.x6_top_bits}]={args.x6_top:x}"
    for fixed_start, fixed_width, fixed_value in fixed_p_ranges:
        branch_label += f", p[{fixed_start}..{fixed_start + fixed_width - 1}]={fixed_value:#x}"
    print(branch_label)
    print(f"impossible by interval carry bounds: {row[2]}")
    print(f"q interval high common bits: {row[3]}")
    print(f"q low known bits: {row[20]}")
    print(f"deterministic low limb columns: {row[4]}")
    print(f"first low frontier column: {row[5]}")
    if row[6] is not None:
        print(f"first low frontier feasible pair count: {row[6]}")
        print(f"first low frontier next carry range: [{row[7]}, {row[8]}]")
    else:
        print("first low frontier pair count: not enumerated")
    print(f"deterministic high limb columns: {row[9]}")
    print(f"first high frontier column: {row[10]}")
    if row[11] is not None:
        print(f"first high frontier feasible value count: {row[11]}")
        print(f"first high frontier previous carry range: [{row[12]}, {row[13]}]")
    else:
        print("first high frontier value count: not enumerated")
    print(f"singleton carry bounds after propagation: {row[14]} / {n_limbs_count + 1}")
    print(f"max carry interval width bits after propagation: {row[15]}")
    if row[16] is not None:
        print(f"possible by exact carry sets: {row[16]}")
        print(f"exact carry propagation iterations: {row[17]}")
        print(f"exact singleton carry sets: {row[18]} / {n_limbs_count + 1}")
        print(f"exact max carry-set cardinality: {row[19]}")
    if args.emit_frontier_values:
        for record in frontier_records:
            column, kind1, index1, value1, kind2, index2, value2, carry = record
            print(
                "low frontier assignment: "
                f"column={column} {kind1}[{index1}]={value1:#x} "
                f"{kind2}[{index2}]={value2:#x} next_carry={carry}"
            )
        for record in high_frontier_records:
            if len(record) == 5:
                column, kind, index, value, carry = record
                print(
                    "high frontier assignment: "
                    f"column={column} {kind}[{index}]={value:#x} previous_carry={carry}"
                )
            else:
                column, kind1, index1, value1, kind2, index2, value2, carry = record
                print(
                    "high frontier assignment: "
                    f"column={column} {kind1}[{index1}]={value1:#x} "
                    f"{kind2}[{index2}]={value2:#x} previous_carry={carry}"
                )
