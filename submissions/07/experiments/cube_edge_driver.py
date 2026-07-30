#!/usr/bin/env python3
"""Rank x1/x6 edge-run cubes using the existing carry and CP-SAT probes."""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CARRY_SCRIPT = ROOT / "experiments" / "investigate_carry_limb.py"
CP_SAT_SCRIPT = ROOT / "experiments" / "try_cp_sat_limb.py"
TAIL_CP_SAT_SCRIPT = ROOT / "experiments" / "try_hensel_tail_cp_sat.py"
P_BITS = 1024
TAIL_SCORE_T = 848
FULL_P_MASK = (1 << P_BITS) - 1


METRIC_PATTERNS = {
    "impossible": re.compile(r"impossible by interval carry bounds: (True|False)"),
    "q_low": re.compile(r"q low known bits: (\d+)"),
    "q_high": re.compile(r"q interval high common bits: (\d+)"),
    "low_frontier": re.compile(r"first low frontier feasible pair count: (\d+)"),
    "high_frontier": re.compile(r"first high frontier feasible value count: (\d+)"),
    "max_carry_width": re.compile(r"max carry interval width bits after propagation: (\d+)"),
    "exact_possible": re.compile(r"possible by exact carry sets: (True|False)"),
    "exact_singletons": re.compile(r"exact singleton carry sets: (\d+) /"),
    "exact_max_set": re.compile(r"exact max carry-set cardinality: (\d+)"),
}


@dataclass
class CarryScore:
    branch_low: int
    branch_high: int
    x1_low: int | None
    x1_width: int
    x1_high: int | None
    x1_high_width: int
    x6_high: int | None
    x6_width: int
    impossible: bool
    q_low: int
    q_high: int
    low_frontier: int | None
    high_frontier: int | None
    max_carry_width: int
    exact_possible: bool | None
    exact_singletons: int | None
    exact_max_set: int | None
    elapsed_ok: bool


@dataclass
class TailVariant:
    tail_T: int
    extra_fix_p_ranges: list[str]
    extra_fix_q_ranges: list[str]
    p_unknown_above_T: int
    q_unknown_above_T: int
    tail_unknown_bits: int
    q_prefix_start: int
    q_prefix_bits_inside_T: int
    strict_tail_known: bool
    mixed_tail_enumerated: bool


def folded_span(score: CarryScore) -> int:
    low_boundary = 210 + (score.x1_width if score.x1_low is not None else 0)
    high_boundary = 830 - (score.x6_width if score.x6_high is not None else 0)
    return high_boundary - low_boundary


def composite_score(score: CarryScore) -> float:
    span = folded_span(score)
    exact_singletons = score.exact_singletons or 0
    exact_max = score.exact_max_set or 0
    return (
        -4.0 * span
        + 8.0 * score.q_high
        + 2.0 * exact_singletons
        - 0.01 * exact_max
    )


def tail848_score(score: CarryScore) -> int:
    q_low_end = min(score.q_low, TAIL_SCORE_T)
    q_prefix_start = P_BITS - score.q_high
    prefix_start = max(0, q_prefix_start)
    prefix_end = TAIL_SCORE_T
    if prefix_start >= prefix_end:
        q_fixed = q_low_end
    elif prefix_start >= q_low_end:
        q_fixed = q_low_end + (prefix_end - prefix_start)
    else:
        q_fixed = max(q_low_end, prefix_end)

    x1_fixed = 0
    if score.x1_low is not None:
        x1_fixed += score.x1_width
    if score.x1_high is not None:
        high_start = 39 - score.x1_high_width
        low_end = score.x1_width if score.x1_low is not None else 0
        x1_fixed += max(0, 39 - max(high_start, low_end))

    x6_fixed = score.x6_width if score.x6_high is not None else 0
    p_unknown_848 = 403 - x1_fixed - x6_fixed
    return 2 * q_fixed - p_unknown_848


def parse_range_list(text: str) -> list[int]:
    def parse_int(value: str) -> int:
        try:
            return int(value, 0)
        except ValueError:
            return int(value, 16)

    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_text, hi_text = part.split("-", 1)
            values.extend(range(parse_int(lo_text), parse_int(hi_text) + 1))
        else:
            values.append(parse_int(part))
    return values


def parse_fixed_range(text: str) -> tuple[int, int, int]:
    start_text, width_text, value_text = text.split(":", 2)
    start = int(start_text, 0)
    width = int(width_text, 0)
    value = int(value_text, 0)
    if start < 0 or width <= 0 or start + width > P_BITS:
        raise ValueError(f"invalid fixed range: {text}")
    if value < 0 or value >= (1 << width):
        raise ValueError(f"fixed value does not fit selected width: {text}")
    return start, width, value


def common_prefix_from_interval(lo: int, hi: int, bits: int = P_BITS) -> tuple[int, int, int]:
    if lo > hi:
        lo, hi = hi, lo
    diff = lo ^ hi
    prefix_len = bits if diff == 0 else bits - diff.bit_length()
    suffix_start = bits - prefix_len
    return prefix_len, lo >> suffix_start, suffix_start


def load_challenge_constants() -> tuple[int, int, int]:
    spec = importlib.util.spec_from_file_location(
        "investigate_rsa_partial_bits", ROOT / "src" / "investigate_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise SystemExit("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    n = int(module.N_HEX.replace(" ", ""), 16)
    mask = int(module.MASK_HEX.replace(" ", ""), 16)
    known = int(module.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    return n, mask, known


def apply_fixed_bits(
    branch_known: int,
    branch_mask: int,
    start: int,
    width: int,
    value: int,
) -> tuple[int, int, bool]:
    fixed_mask = ((1 << width) - 1) << start
    fixed_bits = value << start
    if ((branch_known ^ fixed_bits) & (branch_mask & fixed_mask)) != 0:
        return branch_known, branch_mask, False
    return branch_known | fixed_bits, branch_mask | fixed_mask, True


def ranges_from_assignment(bit_positions: list[int], assignment: int) -> list[str]:
    ranges = []
    for index, bit in enumerate(bit_positions):
        value = (assignment >> index) & 1
        ranges.append(f"{bit}:1:{value}")
    return ranges


def tail_variants_for_score(
    constants: tuple[int, int, int],
    args: argparse.Namespace,
    score: CarryScore,
    tail_T: int,
) -> list[TailVariant]:
    n, mask, known = constants
    branch_known = known | (score.branch_low << 150) | (score.branch_high << 920)
    branch_mask = mask | (0xF << 150) | (0xF << 920)

    ok = True
    if score.x1_low is not None:
        branch_known, branch_mask, ok = apply_fixed_bits(branch_known, branch_mask, 210, score.x1_width, score.x1_low)
    if ok and score.x1_high is not None:
        branch_known, branch_mask, ok = apply_fixed_bits(
            branch_known,
            branch_mask,
            249 - score.x1_high_width,
            score.x1_high_width,
            score.x1_high,
        )
    if ok and score.x6_high is not None:
        branch_known, branch_mask, ok = apply_fixed_bits(branch_known, branch_mask, 830 - score.x6_width, score.x6_width, score.x6_high)
    for fixed_range in args.tail_fix_p_range:
        if not ok:
            break
        fixed_start, fixed_width, fixed_value = parse_fixed_range(fixed_range)
        branch_known, branch_mask, ok = apply_fixed_bits(
            branch_known,
            branch_mask,
            fixed_start,
            fixed_width,
            fixed_value,
        )
    if not ok:
        return []

    def compute_q_state(known_value: int, known_mask: int):
        unknown_mask = FULL_P_MASK ^ known_mask
        p_min = known_value
        p_max = known_value | unknown_mask
        q_min = n // p_max
        q_max = n // p_min
        q_prefix_bits, q_prefix, q_prefix_start = common_prefix_from_interval(q_min, q_max)

        q_known = 0
        q_known_mask = 0
        if unknown_mask:
            low_known_bits = (unknown_mask & -unknown_mask).bit_length() - 1
        else:
            low_known_bits = P_BITS
        low_known_bits = min(low_known_bits, tail_T)
        if low_known_bits:
            low_modulus = 1 << low_known_bits
            q_low_known = (n * pow(known_value & (low_modulus - 1), -1, low_modulus)) % low_modulus
            q_known = q_low_known
            q_known_mask = low_modulus - 1

        if q_prefix_bits > 0:
            prefix_mask = ((1 << q_prefix_bits) - 1) << q_prefix_start
            prefix_value = q_prefix << q_prefix_start
            if ((q_known ^ prefix_value) & (q_known_mask & prefix_mask)) != 0:
                return None
            q_known |= prefix_value
            q_known_mask |= prefix_mask

        for fixed_range in args.tail_fix_q_range:
            fixed_start, fixed_width, fixed_value = parse_fixed_range(fixed_range)
            fixed_mask = ((1 << fixed_width) - 1) << fixed_start
            fixed_bits = fixed_value << fixed_start
            if ((q_known ^ fixed_bits) & (q_known_mask & fixed_mask)) != 0:
                return None
            q_known |= fixed_bits
            q_known_mask |= fixed_mask

        return unknown_mask, q_known, q_known_mask, q_prefix_start

    initial_state = compute_q_state(branch_known, branch_mask)
    if initial_state is None:
        return []
    branch_unknown_mask, q_global_known, q_global_known_mask, q_prefix_start = initial_state

    tail_mask = ((1 << (P_BITS - tail_T)) - 1) << tail_T
    p_tail_unknown_mask = branch_unknown_mask & tail_mask
    q_tail_unknown_mask = (~q_global_known_mask) & tail_mask & FULL_P_MASK
    p_unknown_above_T = p_tail_unknown_mask.bit_count()
    q_unknown_above_T = q_tail_unknown_mask.bit_count()
    tail_unknown_bits = p_unknown_above_T + q_unknown_above_T
    base_variant = TailVariant(
        tail_T=tail_T,
        extra_fix_p_ranges=[],
        extra_fix_q_ranges=[],
        p_unknown_above_T=p_unknown_above_T,
        q_unknown_above_T=q_unknown_above_T,
        tail_unknown_bits=tail_unknown_bits,
        q_prefix_start=q_prefix_start,
        q_prefix_bits_inside_T=max(0, tail_T - q_prefix_start),
        strict_tail_known=tail_unknown_bits == 0,
        mixed_tail_enumerated=False,
    )

    if not args.tail_enumerate_small_tail_unknowns:
        return [base_variant]
    if tail_unknown_bits == 0:
        return [base_variant]
    if p_unknown_above_T > args.tail_max_p_tail_unknown_bits:
        return []
    if q_unknown_above_T > args.tail_max_q_tail_unknown_bits:
        return []
    if tail_unknown_bits > args.tail_max_tail_unknown_bits:
        return []

    p_positions = [bit for bit in range(tail_T, P_BITS) if (p_tail_unknown_mask >> bit) & 1]
    variants = []
    for p_assignment in range(1 << len(p_positions)):
        p_ranges = ranges_from_assignment(p_positions, p_assignment)
        known2 = branch_known
        mask2 = branch_mask
        ok2 = True
        for fixed_range in p_ranges:
            fixed_start, fixed_width, fixed_value = parse_fixed_range(fixed_range)
            known2, mask2, ok2 = apply_fixed_bits(known2, mask2, fixed_start, fixed_width, fixed_value)
            if not ok2:
                break
        if not ok2:
            continue
        state2 = compute_q_state(known2, mask2)
        if state2 is None:
            continue
        unknown_mask2, _, q_known_mask2, q_prefix_start2 = state2
        p_tail_unknown_mask2 = unknown_mask2 & tail_mask
        q_tail_unknown_mask2 = (~q_known_mask2) & tail_mask & FULL_P_MASK
        p_unknown_above_T2 = p_tail_unknown_mask2.bit_count()
        q_unknown_above_T2 = q_tail_unknown_mask2.bit_count()
        tail_unknown_bits2 = p_unknown_above_T2 + q_unknown_above_T2
        if p_unknown_above_T2 > args.tail_max_p_tail_unknown_bits:
            continue
        if q_unknown_above_T2 > args.tail_max_q_tail_unknown_bits:
            continue
        if tail_unknown_bits2 > args.tail_max_tail_unknown_bits:
            continue
        q_positions = [bit for bit in range(tail_T, P_BITS) if (q_tail_unknown_mask2 >> bit) & 1]
        for q_assignment in range(1 << len(q_positions)):
            variants.append(
                TailVariant(
                    tail_T=tail_T,
                    extra_fix_p_ranges=p_ranges,
                    extra_fix_q_ranges=ranges_from_assignment(q_positions, q_assignment),
                    p_unknown_above_T=p_unknown_above_T2,
                    q_unknown_above_T=q_unknown_above_T2,
                    tail_unknown_bits=tail_unknown_bits2,
                    q_prefix_start=q_prefix_start2,
                    q_prefix_bits_inside_T=max(0, tail_T - q_prefix_start2),
                    strict_tail_known=False,
                    mixed_tail_enumerated=True,
                )
            )
    return variants


def run_fast_tail(
    constants: tuple[int, int, int],
    args: argparse.Namespace,
    branch_low: int,
    branch_high: int,
    x1_low: int | None,
    x1_high: int | None,
    x6_high: int | None,
) -> CarryScore:
    n, mask, known = constants
    branch_known = known | (branch_low << 150) | (branch_high << 920)
    branch_mask = mask | (0xF << 150) | (0xF << 920)

    ok = True
    if x1_low is not None:
        branch_known, branch_mask, ok = apply_fixed_bits(
            branch_known, branch_mask, 210, args.x1_low_bits, x1_low
        )
    if ok and x1_high is not None:
        branch_known, branch_mask, ok = apply_fixed_bits(
            branch_known,
            branch_mask,
            249 - args.x1_high_bits,
            args.x1_high_bits,
            x1_high,
        )
    if ok and x6_high is not None:
        branch_known, branch_mask, ok = apply_fixed_bits(
            branch_known,
            branch_mask,
            830 - args.x6_high_bits,
            args.x6_high_bits,
            x6_high,
        )
    if not ok:
        return CarryScore(
            branch_low,
            branch_high,
            x1_low,
            args.x1_low_bits,
            x1_high,
            args.x1_high_bits,
            x6_high,
            args.x6_high_bits,
            True,
            0,
            0,
            None,
            None,
            999,
            None,
            None,
            None,
            False,
        )

    branch_unknown_mask = FULL_P_MASK ^ branch_mask
    p_min = branch_known
    p_max = branch_known | branch_unknown_mask
    q_min = n // p_max
    q_max = n // p_min

    if branch_unknown_mask:
        low_bits = (branch_unknown_mask & -branch_unknown_mask).bit_length() - 1
    else:
        low_bits = P_BITS
    high_common = P_BITS - (q_min ^ q_max).bit_length()

    return CarryScore(
        branch_low,
        branch_high,
        x1_low,
        args.x1_low_bits,
        x1_high,
        args.x1_high_bits,
        x6_high,
        args.x6_high_bits,
        False,
        low_bits,
        high_common,
        None,
        None,
        999,
        None,
        None,
        None,
        True,
    )


def parse_metrics(
    output: str,
    branch_low: int,
    branch_high: int,
    x1_low: int | None,
    x1_width: int,
    x1_high: int | None,
    x1_high_width: int,
    x6_high: int | None,
    x6_width: int,
    ok: bool,
) -> CarryScore:
    values: dict[str, object] = {}
    for key, pattern in METRIC_PATTERNS.items():
        match = pattern.search(output)
        if not match:
            continue
        text = match.group(1)
        if text == "True":
            values[key] = True
        elif text == "False":
            values[key] = False
        else:
            values[key] = int(text)
    return CarryScore(
        branch_low=branch_low,
        branch_high=branch_high,
        x1_low=x1_low,
        x1_width=x1_width,
        x1_high=x1_high,
        x1_high_width=x1_high_width,
        x6_high=x6_high,
        x6_width=x6_width,
        impossible=bool(values.get("impossible", False)),
        q_low=int(values.get("q_low", 0)),
        q_high=int(values.get("q_high", 0)),
        low_frontier=values.get("low_frontier"),
        high_frontier=values.get("high_frontier"),
        max_carry_width=int(values.get("max_carry_width", 999)),
        exact_possible=values.get("exact_possible"),
        exact_singletons=values.get("exact_singletons"),
        exact_max_set=values.get("exact_max_set"),
        elapsed_ok=ok,
    )


def run_carry(
    args: argparse.Namespace,
    branch_low: int,
    branch_high: int,
    x1_low: int | None,
    x1_high: int | None,
    x6_high: int | None,
) -> CarryScore:
    command = [
        sys.executable,
        str(CARRY_SCRIPT),
        "--limb-bits",
        str(args.limb_bits),
        "--branch-low",
        hex(branch_low),
        "--branch-high",
        hex(branch_high),
        "--max-frontier-enum",
        str(args.max_frontier_enum),
    ]
    if args.exact_carry:
        command.append("--exact-carry")
    if x1_low is not None:
        command.extend(["--fix-p-range", f"210:{args.x1_low_bits}:{x1_low}"])
    if x1_high is not None:
        command.extend(["--fix-p-range", f"{249 - args.x1_high_bits}:{args.x1_high_bits}:{x1_high}"])
    if x6_high is not None:
        command.extend(["--fix-p-range", f"{830 - args.x6_high_bits}:{args.x6_high_bits}:{x6_high}"])
    try:
        result = subprocess.run(
            command,
            cwd=ROOT.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=args.carry_timeout,
            check=False,
        )
        return parse_metrics(
            result.stdout,
            branch_low,
            branch_high,
            x1_low,
            args.x1_low_bits,
            x1_high,
            args.x1_high_bits,
            x6_high,
            args.x6_high_bits,
            result.returncode == 0,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout if isinstance(exc.stdout, str) else ""
        return parse_metrics(
            output,
            branch_low,
            branch_high,
            x1_low,
            args.x1_low_bits,
            x1_high,
            args.x1_high_bits,
            x6_high,
            args.x6_high_bits,
            False,
        )


def score_key(score: CarryScore) -> tuple[float, int, int, int, int, int, int]:
    rank_by = getattr(score, "_rank_by", "frontier")
    if rank_by == "composite":
        return (-composite_score(score), 0, 0, 0, 0, 0, 0)
    if rank_by == "tail848":
        return (-tail848_score(score), -composite_score(score), folded_span(score), 0, 0, 0, 0)
    impossible_rank = 0 if score.impossible else 1
    high_frontier = score.high_frontier if score.high_frontier is not None else 1 << 30
    low_frontier = score.low_frontier if score.low_frontier is not None else 1 << 30
    exact_max = score.exact_max_set if score.exact_max_set is not None else 1 << 30
    return (impossible_rank, high_frontier, -score.q_low, low_frontier, score.max_carry_width, exact_max, 0)


def print_scores(scores: list[CarryScore], limit: int) -> None:
    print(
        "rank score tail848 span x0 x7 x1low x1high x6high width impossible qlow qhigh low_frontier "
        "high_frontier carry_width exact_possible exact_singletons exact_max_set ok"
    )
    for rank, score in enumerate(sorted(scores, key=score_key)[:limit], 1):
        x1_text = "-" if score.x1_low is None else f"{score.x1_low:0{(score.x1_width + 3) // 4}x}"
        x1_high_text = (
            "-"
            if score.x1_high is None
            else f"{score.x1_high:0{(score.x1_high_width + 3) // 4}x}"
        )
        x6_text = "-" if score.x6_high is None else f"{score.x6_high:0{(score.x6_width + 3) // 4}x}"
        print(
            f"{rank:4d} {composite_score(score):7.2f} {tail848_score(score):7d} {folded_span(score):4d} "
            f"{score.branch_low:x} {score.branch_high:x} "
            f"{x1_text:>5} {x1_high_text:>6} {x6_text:>6} {score.x6_width:5d} "
            f"{score.impossible!s:>10} {score.q_low:4d} {score.q_high:5d} "
            f"{str(score.low_frontier):>12} {str(score.high_frontier):>13} "
            f"{score.max_carry_width:11d} {str(score.exact_possible):>14} "
            f"{str(score.exact_singletons):>16} {str(score.exact_max_set):>13} "
            f"{score.elapsed_ok!s:>5}"
        )


def build_tail_command(
    args: argparse.Namespace,
    score: CarryScore,
    tail_T: int | None = None,
    random_seed: int | None = None,
    tail_variant: TailVariant | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(TAIL_CP_SAT_SCRIPT),
        "--T",
        str(args.tail_T if tail_T is None else tail_T),
        "--limb-bits",
        str(args.tail_limb_bits),
        "--tail-limbs",
        str(args.tail_limbs),
        "--branch-low",
        hex(score.branch_low),
        "--branch-high",
        hex(score.branch_high),
        "--time-limit",
        str(args.tail_time),
        "--workers",
        str(args.tail_workers),
    ]
    for decision_range in args.tail_decision_p_range:
        command.extend(["--decision-p-range", decision_range])
    for decision_range in args.tail_decision_q_range:
        command.extend(["--decision-q-range", decision_range])
    for fixed_range in args.tail_fix_p_range:
        command.extend(["--fix-p-range", fixed_range])
    for fixed_range in args.tail_fix_q_range:
        command.extend(["--fix-q-range", fixed_range])
    if tail_variant is not None:
        for fixed_range in tail_variant.extra_fix_p_ranges:
            command.extend(["--fix-p-range", fixed_range])
        for fixed_range in tail_variant.extra_fix_q_ranges:
            command.extend(["--fix-q-range", fixed_range])
    if args.tail_lowlift_q:
        command.extend(["--lowlift-q", str(args.tail_lowlift_q)])
    if args.tail_compact_q_limbs:
        command.append("--compact-q-limbs")
    if args.tail_skip_known_prefix_limbs:
        command.extend(["--skip-known-prefix-limbs", str(args.tail_skip_known_prefix_limbs)])
    if args.tail_small_prime_filters:
        command.extend(["--small-prime-filters", str(args.tail_small_prime_filters)])
    if args.tail_odd_residue_filters:
        command.extend(["--odd-residue-filters", str(args.tail_odd_residue_filters)])
    if args.tail_odd_residue_primes:
        command.extend(["--odd-residue-primes", args.tail_odd_residue_primes])
    if args.tail_no_q_interval_bound:
        command.append("--no-q-interval-bound")
    if random_seed is not None:
        command.extend(["--random-seed", str(random_seed)])
    if args.tail_randomize_search:
        command.append("--randomize-search")
    if args.tail_no_phase_saving:
        command.append("--no-phase-saving")
    if args.tail_json_summary:
        command.append("--json-summary")
    if score.x1_low is not None:
        command.extend(["--fix-p-range", f"210:{score.x1_width}:{score.x1_low}"])
    if score.x1_high is not None:
        command.extend(["--fix-p-range", f"{249 - score.x1_high_width}:{score.x1_high_width}:{score.x1_high}"])
    if score.x6_high is not None:
        command.extend(["--fix-p-range", f"{830 - score.x6_width}:{score.x6_width}:{score.x6_high}"])
    return command


def score_record(
    score: CarryScore,
    rank: int | None = None,
    args: argparse.Namespace | None = None,
    tail_T: int | None = None,
    random_seed: int | None = None,
    tail_variant: TailVariant | None = None,
) -> dict[str, object]:
    fixed_ranges = []
    if score.x1_low is not None:
        fixed_ranges.append({"start": 210, "width": score.x1_width, "value": score.x1_low})
    if score.x1_high is not None:
        fixed_ranges.append({
            "start": 249 - score.x1_high_width,
            "width": score.x1_high_width,
            "value": score.x1_high,
        })
    if score.x6_high is not None:
        fixed_ranges.append({"start": 830 - score.x6_width, "width": score.x6_width, "value": score.x6_high})

    record: dict[str, object] = {
        "rank": rank,
        "branch_low": score.branch_low,
        "branch_high": score.branch_high,
        "composite_score": composite_score(score),
        "tail848_score": tail848_score(score),
        "folded_span": folded_span(score),
        "x1_low": score.x1_low,
        "x1_width": score.x1_width,
        "x1_high": score.x1_high,
        "x1_high_width": score.x1_high_width,
        "x6_high": score.x6_high,
        "x6_width": score.x6_width,
        "fixed_p_ranges": fixed_ranges,
        "impossible": score.impossible,
        "q_low": score.q_low,
        "q_high": score.q_high,
        "low_frontier": score.low_frontier,
        "high_frontier": score.high_frontier,
        "max_carry_width": score.max_carry_width,
        "exact_possible": score.exact_possible,
        "exact_singletons": score.exact_singletons,
        "exact_max_set": score.exact_max_set,
        "elapsed_ok": score.elapsed_ok,
        "combo_index": getattr(score, "_combo_index", None),
    }
    if args is not None:
        record["tail_cp_sat_argv"] = build_tail_command(args, score, tail_T, random_seed, tail_variant)
    if tail_T is not None:
        record["tail_T"] = tail_T
    if random_seed is not None:
        record["tail_random_seed"] = random_seed
    if tail_variant is not None:
        record.update(
            {
                "tail_T": tail_variant.tail_T,
                "tail_p_unknown_above_T": tail_variant.p_unknown_above_T,
                "tail_q_unknown_above_T": tail_variant.q_unknown_above_T,
                "tail_unknown_bits": tail_variant.tail_unknown_bits,
                "tail_q_prefix_start": tail_variant.q_prefix_start,
                "tail_q_prefix_bits_inside_T": tail_variant.q_prefix_bits_inside_T,
                "tail_strict_known": tail_variant.strict_tail_known,
                "tail_mixed_enumerated": tail_variant.mixed_tail_enumerated,
                "tail_extra_fix_p_ranges": tail_variant.extra_fix_p_ranges,
                "tail_extra_fix_q_ranges": tail_variant.extra_fix_q_ranges,
            }
        )
    return record


def write_scores_jsonl(scores: list[CarryScore], output_path: Path, limit: int, args: argparse.Namespace) -> None:
    sorted_scores = sorted(scores, key=score_key)
    if limit > 0:
        sorted_scores = sorted_scores[:limit]
    with output_path.open("w", encoding="utf-8") as output:
        for rank, score in enumerate(sorted_scores, 1):
            output.write(json.dumps(score_record(score, rank, args), sort_keys=True) + "\n")
    print(f"[jsonl] wrote {len(sorted_scores)} score record(s) to {output_path}")


def write_tail_plan_jsonl(scores: list[CarryScore], output_path: Path, limit: int, args: argparse.Namespace) -> None:
    sorted_scores = sorted(scores, key=score_key)
    if limit > 0:
        sorted_scores = sorted_scores[:limit]
    random_seeds = args.tail_random_seeds or [None]
    constants = load_challenge_constants()
    written = 0
    with output_path.open("w", encoding="utf-8") as output:
        for rank, score in enumerate(sorted_scores, 1):
            for tail_T in args.tail_T_values:
                for tail_variant in tail_variants_for_score(constants, args, score, tail_T):
                    for random_seed in random_seeds:
                        record = score_record(score, rank, args, tail_T, random_seed, tail_variant)
                        record["argv"] = build_tail_command(args, score, tail_T, random_seed, tail_variant)
                        output.write(json.dumps(record, sort_keys=True) + "\n")
                        written += 1
    print(f"[tail-plan] wrote {written} tail probe record(s) to {output_path}")


def run_cp_sat(args: argparse.Namespace, scores: list[CarryScore]) -> None:
    for score in sorted(scores, key=score_key)[: args.cp_sat_top]:
        command = [
            sys.executable,
            str(CP_SAT_SCRIPT),
            "--limb-bits",
            str(args.cp_sat_limb_bits),
            "--branch-low",
            hex(score.branch_low),
            "--branch-high",
            hex(score.branch_high),
            "--time-limit",
            str(args.cp_sat_time),
            "--workers",
            str(args.cp_sat_workers),
        ]
        for decision_range in args.cp_sat_decision_p_range:
            command.extend(["--decision-p-range", decision_range])
        if args.cp_sat_lowlift_q:
            command.extend(["--lowlift-q", str(args.cp_sat_lowlift_q)])
        if score.x1_low is not None:
            command.extend(["--fix-p-range", f"210:{score.x1_width}:{score.x1_low}"])
        if score.x1_high is not None:
            command.extend(["--fix-p-range", f"{249 - score.x1_high_width}:{score.x1_high_width}:{score.x1_high}"])
        if score.x6_high is not None:
            command.extend(["--fix-p-range", f"{830 - score.x6_width}:{score.x6_width}:{score.x6_high}"])
        print("[cp-sat]", " ".join(command), flush=True)
        result = subprocess.run(
            command,
            cwd=ROOT.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=args.cp_sat_time + 30,
            check=False,
        )
        print(result.stdout, flush=True)


def run_tail_cp_sat(args: argparse.Namespace, scores: list[CarryScore]) -> None:
    random_seeds = args.tail_random_seeds or [None]
    constants = load_challenge_constants()
    for score in sorted(scores, key=score_key)[: args.tail_cp_sat_top]:
        for tail_T in args.tail_T_values:
            for tail_variant in tail_variants_for_score(constants, args, score, tail_T):
                for random_seed in random_seeds:
                    command = build_tail_command(args, score, tail_T, random_seed, tail_variant)
                    print("[tail-cp-sat]", " ".join(command), flush=True)
                    result = subprocess.run(
                        command,
                        cwd=ROOT.parent,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        timeout=args.tail_subprocess_timeout,
                        check=False,
                    )
                    print(result.stdout, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch-low", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--branch-high", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--branch-low-values", default="", help="values for x0 branch, e.g. 0-f")
    parser.add_argument("--branch-high-values", default="", help="values for x7 branch, e.g. 0-f")
    parser.add_argument("--limb-bits", type=int, default=4)
    parser.add_argument("--x1-low-bits", type=int, default=4)
    parser.add_argument("--x1-low-values", default="", help="values for low x1 prefix, e.g. 0-f")
    parser.add_argument("--x1-high-bits", type=int, default=4)
    parser.add_argument("--x1-high-values", default="", help="values for high x1 prefix, e.g. 0-f")
    parser.add_argument("--x6-high-bits", type=int, default=4)
    parser.add_argument("--x6-high-values", default="0-f")
    parser.add_argument("--exact-carry", action="store_true")
    parser.add_argument("--max-frontier-enum", type=int, default=1 << 18)
    parser.add_argument("--carry-timeout", type=float, default=30.0)
    parser.add_argument("--top", type=int, default=16)
    parser.add_argument("--rank-by", choices=["frontier", "composite", "tail848"], default="frontier")
    parser.add_argument(
        "--fast-tail-only",
        action="store_true",
        help="compute only in-process q low/high metrics; intended for broad tail848 sweeps",
    )
    parser.add_argument("--score-jsonl", type=Path, help="stream one unsorted JSON record per evaluated cube")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--out-jsonl", type=Path)
    parser.add_argument("--out-jsonl-top", type=int, default=0, help="number of sorted records to write; 0 writes all")
    parser.add_argument("--cp-sat-top", type=int, default=0)
    parser.add_argument("--cp-sat-limb-bits", type=int, default=16)
    parser.add_argument("--cp-sat-lowlift-q", type=int, default=0)
    parser.add_argument(
        "--cp-sat-decision-p-range",
        action="append",
        default=[],
        help="CP-SAT p decision range START:WIDTH; defaults to 210:39 and 784:46",
    )
    parser.add_argument("--cp-sat-time", type=float, default=8.0)
    parser.add_argument("--cp-sat-workers", type=int, default=8)
    parser.add_argument("--tail-cp-sat-top", type=int, default=0)
    parser.add_argument("--tail-T", type=int, default=848)
    parser.add_argument("--tail-T-values", default="", help="comma/range list overriding --tail-T for tail plans/probes")
    parser.add_argument("--tail-limb-bits", type=int, default=16)
    parser.add_argument("--tail-limbs", type=int, default=16)
    parser.add_argument(
        "--tail-decision-p-range",
        action="append",
        default=[],
        help="T=848 exact-tail CP-SAT p decision range START:WIDTH; defaults to 210:39 and 784:46",
    )
    parser.add_argument(
        "--tail-decision-q-range",
        action="append",
        default=[],
        help="tail CP-SAT q limb decision bit range START:WIDTH",
    )
    parser.add_argument("--tail-fix-p-range", action="append", default=[], help="extra fixed p range START:WIDTH:VALUE forwarded to tail CP-SAT")
    parser.add_argument("--tail-fix-q-range", action="append", default=[], help="extra fixed q range START:WIDTH:VALUE forwarded to tail CP-SAT")
    parser.add_argument(
        "--tail-no-default-decision",
        action="store_true",
        help="do not add the default 210:39 and 784:46 tail CP-SAT decision ranges",
    )
    parser.add_argument("--tail-time", type=float, default=20.0)
    parser.add_argument("--tail-workers", type=int, default=8)
    parser.add_argument("--tail-lowlift-q", type=int, default=0)
    parser.add_argument("--tail-compact-q-limbs", action="store_true")
    parser.add_argument(
        "--tail-skip-known-prefix-limbs",
        type=int,
        default=0,
        help="forward --skip-known-prefix-limbs to tail CP-SAT",
    )
    parser.add_argument("--tail-small-prime-filters", type=int, default=0)
    parser.add_argument("--tail-odd-residue-filters", type=int, default=0)
    parser.add_argument("--tail-odd-residue-primes", default="")
    parser.add_argument("--tail-no-q-interval-bound", action="store_true")
    parser.add_argument("--tail-json-summary", action="store_true")
    parser.add_argument(
        "--tail-random-seeds",
        default="",
        help="comma/range list of CP-SAT random seeds used to expand tail probes",
    )
    parser.add_argument("--tail-randomize-search", action="store_true")
    parser.add_argument("--tail-no-phase-saving", action="store_true")
    parser.add_argument(
        "--tail-enumerate-small-tail-unknowns",
        action="store_true",
        help="expand small p/q unknown tails above T into strict-known fixed bit probes",
    )
    parser.add_argument("--tail-max-tail-unknown-bits", type=int, default=8)
    parser.add_argument("--tail-max-p-tail-unknown-bits", type=int, default=8)
    parser.add_argument("--tail-max-q-tail-unknown-bits", type=int, default=8)
    parser.add_argument("--tail-subprocess-timeout", type=float, default=0.0)
    parser.add_argument("--tail-plan-jsonl", type=Path)
    parser.add_argument("--tail-plan-top", type=int, default=0, help="number of sorted tail probe records to write; 0 writes all")
    args = parser.parse_args()
    if args.shard_count <= 0:
        raise SystemExit("--shard-count must be positive")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        raise SystemExit("--shard-index must satisfy 0 <= index < count")
    if args.x1_low_bits <= 0 or args.x1_low_bits > 39:
        raise SystemExit("--x1-low-bits must be in 1..39")
    if args.x1_high_bits <= 0 or args.x1_high_bits > 39:
        raise SystemExit("--x1-high-bits must be in 1..39")
    if args.x6_high_bits <= 0 or args.x6_high_bits > 46:
        raise SystemExit("--x6-high-bits must be in 1..46")
    if not args.cp_sat_decision_p_range:
        args.cp_sat_decision_p_range = ["210:39", "784:46"]
    if not args.tail_decision_p_range and not args.tail_no_default_decision:
        args.tail_decision_p_range = ["210:39", "784:46"]
    if args.tail_subprocess_timeout <= 0:
        args.tail_subprocess_timeout = args.tail_time + 60
    args.tail_T_values = parse_range_list(args.tail_T_values) if args.tail_T_values else [args.tail_T]
    args.tail_random_seeds = parse_range_list(args.tail_random_seeds) if args.tail_random_seeds else []
    for tail_T in args.tail_T_values:
        if tail_T <= 0 or tail_T > P_BITS:
            raise SystemExit("--tail-T-values entries must be in 1..1024")
        if tail_T % args.tail_limb_bits != 0:
            raise SystemExit("--tail-T-values entries must be divisible by --tail-limb-bits")
    for random_seed in args.tail_random_seeds:
        if random_seed < 0:
            raise SystemExit("--tail-random-seeds entries must be non-negative")
    if args.tail_max_tail_unknown_bits < 0:
        raise SystemExit("--tail-max-tail-unknown-bits must be non-negative")
    if args.tail_max_p_tail_unknown_bits < 0:
        raise SystemExit("--tail-max-p-tail-unknown-bits must be non-negative")
    if args.tail_max_q_tail_unknown_bits < 0:
        raise SystemExit("--tail-max-q-tail-unknown-bits must be non-negative")

    x1_values: list[int | None] = [None]
    if args.x1_low_values:
        x1_values = parse_range_list(args.x1_low_values)
    x1_high_values: list[int | None] = [None]
    if args.x1_high_values:
        x1_high_values = parse_range_list(args.x1_high_values)
    x6_values: list[int | None] = [None]
    if args.x6_high_values:
        x6_values = parse_range_list(args.x6_high_values)
    branch_low_values = [args.branch_low]
    if args.branch_low_values:
        branch_low_values = parse_range_list(args.branch_low_values)
    branch_high_values = [args.branch_high]
    if args.branch_high_values:
        branch_high_values = parse_range_list(args.branch_high_values)
    for value in [*branch_low_values, *branch_high_values]:
        if value < 0 or value >= 16:
            raise SystemExit("branch values must be in 0..15")

    scores = []
    constants = load_challenge_constants() if args.fast_tail_only else None
    score_output = args.score_jsonl.open("w", encoding="utf-8") if args.score_jsonl is not None else None
    try:
        for combo_index, (branch_low, branch_high, x1_low, x1_high, x6_high) in enumerate(
            itertools.product(branch_low_values, branch_high_values, x1_values, x1_high_values, x6_values)
        ):
            if combo_index % args.shard_count != args.shard_index:
                continue
            if args.fast_tail_only:
                if constants is None:
                    raise AssertionError("constants should be loaded for --fast-tail-only")
                score = run_fast_tail(constants, args, branch_low, branch_high, x1_low, x1_high, x6_high)
            else:
                score = run_carry(args, branch_low, branch_high, x1_low, x1_high, x6_high)
            setattr(score, "_rank_by", args.rank_by)
            setattr(score, "_combo_index", combo_index)
            scores.append(score)
            if score_output is not None:
                score_output.write(json.dumps(score_record(score, None, args), sort_keys=True) + "\n")
                score_output.flush()
    finally:
        if score_output is not None:
            score_output.close()

    print_scores(scores, args.top)
    if args.out_jsonl is not None:
        write_scores_jsonl(scores, args.out_jsonl, args.out_jsonl_top, args)
    if args.tail_plan_jsonl is not None:
        write_tail_plan_jsonl(scores, args.tail_plan_jsonl, args.tail_plan_top, args)
    if args.cp_sat_top:
        run_cp_sat(args, scores)
    if args.tail_cp_sat_top:
        run_tail_cp_sat(args, scores)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
