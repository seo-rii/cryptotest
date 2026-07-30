#!/usr/bin/env python3
"""Beam search for q middle-gap gateway/diagonal candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from q_interval_sweep import compact_ranges, compact_ranges_key
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


@dataclass(frozen=True)
class Stage:
    name: str
    start: int
    width: int


@dataclass(frozen=True)
class Candidate:
    ranges: tuple[FixedRange, ...]
    p_fixed_bits: int
    q_low_bits: int
    q_prefix_bits: int
    q_prefix_start: int
    q_known_bits: int
    q_gap_bits: int
    q_interval_width_bits: int


def parse_widths(text: str) -> list[int]:
    if text.strip().lower() in {"", "none", "0"}:
        return []
    values = [int(part.strip(), 0) for part in text.split(",") if part.strip()]
    if not values or any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("width list must contain positive integers")
    return values


def parse_values(text: str, width: int) -> list[int]:
    if text.strip().lower() == "all":
        return list(range(1 << width))
    values: list[int] = []
    seen: set[int] = set()
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        value = int(part, 0)
        if value < 0 or value >= (1 << width):
            raise argparse.ArgumentTypeError(f"{value!r} does not fit {width} bits")
        if value not in seen:
            values.append(value)
            seen.add(value)
    if not values:
        raise argparse.ArgumentTypeError("expected at least one value")
    return values


def format_fixed_range(item: FixedRange) -> str:
    return f"{item.start}:{item.width}:{hex(item.value)}"


def fix_p_range_args(ranges: tuple[FixedRange, ...]) -> list[str]:
    args: list[str] = []
    for item in sorted(ranges, key=lambda value: value.start):
        args.extend(["--fix-p-range", format_fixed_range(item)])
    return args


def fixed_ranges_text(ranges: tuple[FixedRange, ...]) -> list[str]:
    return [f"{item.start}:{item.width}=0x{item.value:x}" for item in sorted(ranges, key=lambda value: value.start)]


def lex_tie_key(candidate: Candidate) -> tuple[tuple[int, int, int], ...]:
    return compact_ranges_key(compact_ranges(list(candidate.ranges)))


def hash_tie_key(candidate: Candidate, salt: str) -> int:
    payload = json.dumps(
        [[item.start, item.width, item.value] for item in sorted(candidate.ranges, key=lambda value: value.start)],
        separators=(",", ":"),
    )
    digest = hashlib.blake2b(f"{salt}:{payload}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def q_gap_score_key(
    candidate: Candidate,
    *,
    tie_policy: str = "lex",
    diversity_salt: str = "",
) -> tuple[int, int, int, int, int, tuple[tuple[int, int, int], ...] | int]:
    tie_key: tuple[tuple[int, int, int], ...] | int
    if tie_policy == "hash":
        tie_key = hash_tie_key(candidate, diversity_salt)
    else:
        tie_key = lex_tie_key(candidate)
    return (
        candidate.q_gap_bits,
        -candidate.q_known_bits,
        -candidate.q_low_bits,
        candidate.q_prefix_start,
        candidate.q_interval_width_bits,
        tie_key,
    )


def score_candidate(instance, ranges: tuple[FixedRange, ...]) -> Candidate:
    p_known, p_mask = instance.apply_fixed_ranges(list(ranges))
    q_known = derive_q_known_bits(instance, p_known, p_mask)
    q_gap_bits = max(0, q_known.prefix_start - q_known.low_bits)
    return Candidate(
        ranges=ranges,
        p_fixed_bits=p_mask.bit_count(),
        q_low_bits=q_known.low_bits,
        q_prefix_bits=q_known.prefix_bits,
        q_prefix_start=q_known.prefix_start,
        q_known_bits=q_known.mask.bit_count(),
        q_gap_bits=q_gap_bits,
        q_interval_width_bits=(q_known.q_max - q_known.q_min).bit_length(),
    )


def candidate_record(candidate: Candidate, *, rank: int | None = None) -> dict[str, Any]:
    record = {
        "p_fixed_bits": candidate.p_fixed_bits,
        "q_low_bits": candidate.q_low_bits,
        "q_prefix_bits": candidate.q_prefix_bits,
        "q_prefix_start": candidate.q_prefix_start,
        "q_known_bits": candidate.q_known_bits,
        "q_gap_bits": candidate.q_gap_bits,
        "q_interval_width_bits": candidate.q_interval_width_bits,
        "fixed_ranges": compact_ranges(list(candidate.ranges)),
        "fixed_ranges_text": fixed_ranges_text(candidate.ranges),
        "all_fixed_ranges_text": fixed_ranges_text(candidate.ranges),
        "all_fix_p_range_args": fix_p_range_args(candidate.ranges),
    }
    if rank is not None:
        record["rank"] = rank
    return record


def build_stages(args: argparse.Namespace) -> list[Stage]:
    stages: list[Stage] = []
    if args.include_x0:
        stages.append(Stage("x0", 150, 4))
    if args.include_x7:
        stages.append(Stage("x7", 920, 4))

    x1_start = 210
    for index, width in enumerate(args.x1_widths, start=1):
        stages.append(Stage(f"x1_{index}", x1_start, width))
        x1_start += width
    if args.x1_widths and x1_start != 249:
        raise SystemExit("--x1-widths must sum to 39, or use --x1-widths none")

    x6_stop = 830
    assigned_x6 = 0
    for index, width in enumerate(args.x6_widths, start=1):
        assigned_x6 += width
        stages.append(Stage(f"x6_{index}", x6_stop - assigned_x6, width))
    if assigned_x6 != 46:
        raise SystemExit("--x6-widths must sum to 46")

    x5_stop = 769
    assigned_x5 = 0
    for index, width in enumerate(args.x5_high_widths, start=1):
        assigned_x5 += width
        stages.append(Stage(f"x5high_{index}", x5_stop - assigned_x5, width))
    if assigned_x5 != args.x5_high_bits:
        raise SystemExit("--x5-high-widths must sum to --x5-high-bits")
    if args.x5_high_bits < 0 or args.x5_high_bits > 87:
        raise SystemExit("--x5-high-bits must be in 0..87")

    x2_start = 265
    assigned_x2 = 0
    for index, width in enumerate(args.x2_low_widths, start=1):
        stages.append(Stage(f"x2low_{index}", x2_start + assigned_x2, width))
        assigned_x2 += width
    if assigned_x2 != args.x2_low_bits:
        raise SystemExit("--x2-low-widths must sum to --x2-low-bits")
    return stages


def extend_beam(
    instance,
    beam: list[Candidate],
    stage: Stage,
    beam_width: int,
    per_parent_cubes: int,
    score_key: Callable[[Candidate], tuple[Any, ...]],
) -> tuple[list[Candidate], dict[str, Any]]:
    limit = 1 << stage.width if per_parent_cubes <= 0 else min(1 << stage.width, per_parent_cubes)
    rows: list[Candidate] = []
    for parent in beam:
        for value in range(limit):
            rows.append(score_candidate(instance, parent.ranges + (FixedRange(stage.start, stage.width, value),)))
    rows.sort(key=score_key)
    retained = rows[:beam_width]
    best = retained[0] if retained else None
    return retained, {
        "stage": stage.name,
        "range": {"start": stage.start, "width": stage.width},
        "parents": len(beam),
        "per_parent_limit": limit,
        "emitted": len(rows),
        "retained": len(retained),
        "best": None if best is None else candidate_record(best),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--beam-width", type=int, default=16)
    parser.add_argument("--per-parent-cubes", type=int, default=0, help="0 means enumerate the whole current chunk")
    parser.add_argument("--top", type=int, default=32)
    parser.add_argument("--include-x0", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-x7", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--x1-widths", type=parse_widths, default=parse_widths("none"))
    parser.add_argument("--x6-widths", type=parse_widths, default=parse_widths("8,8,8,8,8,6"))
    parser.add_argument("--x5-high-bits", type=int, default=0)
    parser.add_argument("--x5-high-widths", type=parse_widths, default=parse_widths("none"))
    parser.add_argument("--x2-low-bits", type=int, default=48)
    parser.add_argument("--x2-low-widths", type=parse_widths, default=parse_widths("8,8,8,8,8,8"))
    parser.add_argument(
        "--tie-policy",
        choices=("lex", "hash"),
        default="lex",
        help="lex is reproducible prefix order; hash diversifies candidates with identical q-gap scores",
    )
    parser.add_argument("--diversity-salt", default="", help="salt for --tie-policy hash")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.beam_width < 1:
        raise SystemExit("--beam-width must be positive")
    if args.per_parent_cubes < 0:
        raise SystemExit("--per-parent-cubes must be nonnegative")
    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.x2_low_bits < 0 or args.x2_low_bits > 84:
        raise SystemExit("--x2-low-bits must be in 0..84")
    if args.x5_high_bits < 0 or args.x5_high_bits > 87:
        raise SystemExit("--x5-high-bits must be in 0..87")

    instance = load_instance()
    base_ranges = tuple(args.fix_p_range)
    base = score_candidate(instance, base_ranges)
    beam = [base]
    stages = build_stages(args)
    stage_reports: list[dict[str, Any]] = []
    score_key = lambda candidate: q_gap_score_key(
        candidate,
        tie_policy=args.tie_policy,
        diversity_salt=args.diversity_salt,
    )
    for stage in stages:
        beam, report = extend_beam(instance, beam, stage, args.beam_width, args.per_parent_cubes, score_key)
        stage_reports.append(report)

    beam.sort(key=score_key)
    items = [candidate_record(candidate, rank=rank) for rank, candidate in enumerate(beam[: args.top], start=1)]
    summary = {
        "event": "q_gap_gateway_beam_search",
        "ranking_priority": "q_gap_bits,q_known_bits,q_low_bits,q_prefix_start,interval_width",
        "beam_width": args.beam_width,
        "per_parent_cubes": args.per_parent_cubes,
        "tie_policy": args.tie_policy,
        "diversity_salt": args.diversity_salt,
        "top": args.top,
        "x2_low_bits": args.x2_low_bits,
        "x5_high_bits": args.x5_high_bits,
        "base": candidate_record(base),
        "stage_count": len(stages),
        "stages": stage_reports,
        "best_all_fix_p_range_args": items[0]["all_fix_p_range_args"] if items else [],
    }
    payload = {"summary": summary, "items": items}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "base "
            f"q_low={base.q_low_bits} q_prefix={base.q_prefix_bits} "
            f"q_gap={base.q_gap_bits} q_known={base.q_known_bits}"
        )
        for report in stage_reports:
            best = report["best"] or {}
            print(
                f"{report['stage']} {report['range']['start']}:{report['range']['width']} "
                f"emitted={report['emitted']} retained={report['retained']} "
                f"best_gap={best.get('q_gap_bits')} best_q_known={best.get('q_known_bits')} "
                f"best_q_low={best.get('q_low_bits')} best_prefix_start={best.get('q_prefix_start')}"
            )
        for item in items:
            print(
                f"{item['rank']:02d} gap={item['q_gap_bits']} "
                f"q_low={item['q_low_bits']} prefix_start={item['q_prefix_start']} "
                f"q_known={item['q_known_bits']} ranges={';'.join(item['fixed_ranges_text'])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
