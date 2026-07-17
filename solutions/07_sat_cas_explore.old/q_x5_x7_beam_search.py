#!/usr/bin/env python3
"""Sweep x7 while growing the x5 high edge with the q-prefix beam.

This is the high-side variant of ``q_x5_beam_search.py``: keep full x6 fixed
and x0=0, enumerate selected x7 values, then run the same staged x5 beam under
each x7 branch.  The merged final candidates are ranked by q-prefix strength.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from q_interval_sweep import compact_ranges, compact_ranges_key
from q_x5_beam_search import (
    DEFAULT_CHUNK_WIDTHS,
    X5_EDGE_START,
    X5_EDGE_WIDTH,
    candidate_rank_key,
    format_candidate,
    parse_chunk_widths,
    run_search,
)
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


DEFAULT_BASE_RANGES = (
    "784:46:0x245521490bd",
    "150:4:0",
)
X7_START = 920
X7_WIDTH = 4


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beam-width", type=int, default=2)
    parser.add_argument("--per-parent-cubes", type=int, default=8)
    parser.add_argument(
        "--chunk-widths",
        default=DEFAULT_CHUNK_WIDTHS,
        help="comma-separated widths grown from x5 high side; sum must be 48",
    )
    parser.add_argument(
        "--x7-values",
        help="comma-separated x7 values; defaults to all 0..15",
    )
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_fixed_range,
        help="additional fixed p-bit range START:WIDTH:VALUE appended to the base before x7",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def parse_x7_values(text: str | None) -> list[int]:
    if text is None:
        return list(range(1 << X7_WIDTH))
    values: list[int] = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        value = int(item, 0)
        if value < 0 or value >= (1 << X7_WIDTH):
            raise ValueError(f"x7 value does not fit {X7_WIDTH} bits: {item}")
        values.append(value)
    if not values:
        raise ValueError("--x7-values must contain at least one value")
    return values


def with_x7(candidate: dict[str, Any], x7_value: int) -> dict[str, Any]:
    x7_range = f"{X7_START}:{X7_WIDTH}:{hex(x7_value)}"
    all_ranges = [
        parse_fixed_range(x7_range),
        parse_fixed_range(str(candidate["range"])),
    ]
    return {
        **candidate,
        "x7": x7_value,
        "x7_hex": hex(x7_value),
        "x7_range": x7_range,
        "fixed_ranges": compact_ranges(all_ranges),
        "candidate_fix_p_range_args": [x7_range, str(candidate["range"])],
    }


def final_rank_key(candidate: dict[str, Any]) -> tuple[int, int, int, int, tuple[tuple[int, int, int], ...]]:
    return (
        -int(candidate["q_prefix_bits"]),
        -int(candidate["q_known_bits"]),
        -int(candidate["q_low_bits"]),
        int(candidate["q_interval_width_bits"]),
        compact_ranges_key(candidate["fixed_ranges"]),
    )


def summarize_x7_branch(
    instance,
    base_ranges: list[FixedRange],
    x7_value: int,
    chunk_widths: list[int],
    beam_width: int,
    per_parent_cubes: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    x7_range = FixedRange(X7_START, X7_WIDTH, x7_value)
    branch_ranges = base_ranges + [x7_range]
    branch_known, branch_mask = instance.apply_fixed_ranges(branch_ranges)
    branch_q = derive_q_known_bits(instance, branch_known, branch_mask)

    final_beam, stage_summaries = run_search(
        instance,
        branch_ranges,
        chunk_widths,
        beam_width,
        per_parent_cubes,
    )
    final_beam.sort(key=candidate_rank_key)
    final_candidates = [with_x7(format_candidate(candidate), x7_value) for candidate in final_beam]
    branch_report = {
        "x7": x7_value,
        "x7_hex": hex(x7_value),
        "x7_range": f"{X7_START}:{X7_WIDTH}:{hex(x7_value)}",
        "base_fixed_ranges": compact_ranges(branch_ranges),
        "base_p_fixed_bits": branch_mask.bit_count(),
        "base_q_low_bits": branch_q.low_bits,
        "base_q_prefix_bits": branch_q.prefix_bits,
        "base_q_prefix_start": branch_q.prefix_start,
        "base_q_known_bits": branch_q.mask.bit_count(),
        "stages": stage_summaries,
        "final_candidates": final_candidates,
        "best_final_candidate": final_candidates[0] if final_candidates else None,
    }
    return branch_report, final_candidates


def emit_human(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "base "
        f"p_fixed={summary['base_p_fixed_bits']} "
        f"q_low={summary['base_q_low_bits']} "
        f"q_prefix={summary['base_q_prefix_bits']} "
        f"q_known={summary['base_q_known_bits']} "
        f"x7_values={summary['x7_values']}"
    )
    for item in report["per_x7"]:
        best = item["best_final_candidate"] or {}
        print(
            f"x7={item['x7']} emitted_stages={len(item['stages'])} "
            f"best={best.get('range', '(none)')} "
            f"q_prefix={best.get('q_prefix_bits')} "
            f"q_known={best.get('q_known_bits')} "
            f"width_bits={best.get('q_interval_width_bits')}"
        )
    for rank, candidate in enumerate(report["final_candidates"], start=1):
        print(
            f"{rank:02d} x7={candidate['x7']} {candidate['range']} "
            f"q_prefix={candidate['q_prefix_bits']} "
            f"q_known={candidate['q_known_bits']} "
            f"width_bits={candidate['q_interval_width_bits']}"
        )


def main() -> int:
    args = parse_args()
    if args.beam_width < 1:
        raise SystemExit("--beam-width must be positive")
    if args.per_parent_cubes < 1:
        raise SystemExit("--per-parent-cubes must be positive")

    try:
        chunk_widths = parse_chunk_widths(args.chunk_widths)
        x7_values = parse_x7_values(args.x7_values)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    instance = load_instance()
    base_ranges = [parse_fixed_range(item) for item in DEFAULT_BASE_RANGES]
    base_ranges.extend(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)

    per_x7: list[dict[str, Any]] = []
    final_candidates: list[dict[str, Any]] = []
    for x7_value in x7_values:
        branch_report, branch_candidates = summarize_x7_branch(
            instance,
            base_ranges,
            x7_value,
            chunk_widths,
            args.beam_width,
            args.per_parent_cubes,
        )
        per_x7.append(branch_report)
        final_candidates.extend(branch_candidates)

    final_candidates.sort(key=final_rank_key)
    report = {
        "event": "q_x5_x7_beam_search",
        "summary": {
            "ranking_priority": "q_prefix_bits,q_known_bits,q_low_bits,small_interval",
            "base_fixed_ranges": compact_ranges(base_ranges),
            "base_p_fixed_bits": base_mask.bit_count(),
            "base_q_low_bits": base_q.low_bits,
            "base_q_prefix_bits": base_q.prefix_bits,
            "base_q_prefix_start": base_q.prefix_start,
            "base_q_known_bits": base_q.mask.bit_count(),
            "beam_width": args.beam_width,
            "per_parent_cubes": args.per_parent_cubes,
            "chunk_widths": chunk_widths,
            "x7_values": x7_values,
            "x7_count": len(x7_values),
            "x5_final_range": f"{X5_EDGE_START}:{X5_EDGE_WIDTH}",
            "final_candidate_count": len(final_candidates),
            "best_final_candidate": final_candidates[0] if final_candidates else None,
        },
        "per_x7": per_x7,
        "final_candidates": final_candidates,
    }

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        emit_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
