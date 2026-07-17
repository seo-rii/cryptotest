#!/usr/bin/env python3
"""Rank q-prefix growth for x2/x5 chunks under the Coron edge branch.

The default base fixes the batch11 Coron edge branch values x0=0, full x6,
and x7=0, then compares bounded x2/x5 chunk enumerations.  This is a
diagnostic wrapper: it reuses q_prefix_growth_search.py helpers and reports
which chunks are worth handing to a folded Coron success verifier.
"""

from __future__ import annotations

import argparse
import json
from math import prod
from typing import Any

from q_interval_sweep import compact_ranges, compact_ranges_key, parse_cube_ranges
from q_prefix_growth_search import iter_limited_cubes, summarize_candidate
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


DEFAULT_BASE_RANGES = (
    "784:46:0x245521490bd",
    "150:4:0",
    "920:4:0",
)

DEFAULT_RANGE_SETS = (
    ("x2_prefix8", "265:8"),
    ("x2_prefix16", "265:16"),
    ("x5_low8", "682:8"),
    ("x5_high9", "760:9"),
    ("x2_x5_low4", "265:4,682:4"),
    ("x2_x5_edges4", "265:4,760:4"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--range-set",
        action="append",
        default=[],
        help=(
            "range set to compare, either NAME=START:WIDTH[,START:WIDTH...] "
            "or START:WIDTH[,START:WIDTH...]; may be supplied more than once"
        ),
    )
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_fixed_range,
        help="additional fixed p-bit range START:WIDTH:VALUE appended to the default base",
    )
    parser.add_argument("--max-cubes", type=int, default=128)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def parse_range_set(text: str, ordinal: int) -> tuple[str, str]:
    if "=" in text:
        name, ranges = text.split("=", 1)
        name = name.strip()
        ranges = ranges.strip()
        if not name or not ranges:
            raise ValueError("range set NAME=RANGES must include both sides")
        return name, ranges
    return f"custom_{ordinal}", text.strip()


def range_total_size(ranges: str) -> int:
    cube_ranges = parse_cube_ranges(ranges)
    return prod(item.size for item in cube_ranges) if cube_ranges else 1


def row_rank_key(row: dict[str, Any]) -> tuple[int, int, int, int, tuple[tuple[int, int, int], ...]]:
    return (
        -int(row["q_prefix_bits"]),
        -int(row["q_known_bits"]),
        -int(row["q_low_bits"]),
        int(row["q_interval_width_bits"]),
        compact_ranges_key(row["fixed_ranges"]),
    )


def compact_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": row["index"],
        "q_prefix_bits": row["q_prefix_bits"],
        "q_known_bits": row["q_known_bits"],
        "q_low_bits": row["q_low_bits"],
        "q_interval_width_bits": row["q_interval_width_bits"],
        "fixed_ranges": row["fixed_ranges"],
        "fixed_ranges_text": row["fixed_ranges_text"],
        "candidate_fix_p_range_args": row["candidate_fix_p_range_args"],
        "all_fix_p_range_args": row["all_fix_p_range_args"],
    }


def summarize_range_set(
    instance,
    base_ranges: list[FixedRange],
    name: str,
    ranges: str,
    max_cubes: int,
    top: int,
    base_q_known_bits: int,
    base_q_low_bits: int,
    base_q_prefix_bits: int,
    base_p_fixed_bits: int,
) -> dict[str, Any]:
    parsed_ranges = parse_cube_ranges(ranges)
    rows: list[dict[str, Any]] = []
    for index, cube in enumerate(iter_limited_cubes(parsed_ranges, max_cubes), start=1):
        rows.append(
            summarize_candidate(
                instance,
                base_ranges,
                cube,
                name,
                index,
                base_q_known_bits,
                base_q_low_bits,
                base_q_prefix_bits,
                base_p_fixed_bits,
            )
        )
    rows.sort(key=row_rank_key)
    top_rows = [compact_candidate(row) for row in rows[:top]]
    best = top_rows[0] if top_rows else None
    return {
        "name": name,
        "ranges": ranges,
        "parsed_ranges": [{"start": item.start, "width": item.width} for item in parsed_ranges],
        "total_cube_count": range_total_size(ranges),
        "emitted_cubes": len(rows),
        "capped": len(rows) < range_total_size(ranges),
        "best_q_prefix_bits": None if best is None else best["q_prefix_bits"],
        "best_q_known_bits": None if best is None else best["q_known_bits"],
        "best_q_interval_width_bits": None if best is None else best["q_interval_width_bits"],
        "best_fixed_ranges": [] if best is None else best["fixed_ranges"],
        "top_candidates": top_rows,
    }


def emit_human(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "base "
        f"p_fixed={summary['base_p_fixed_bits']} "
        f"q_low={summary['base_q_low_bits']} "
        f"q_prefix={summary['base_q_prefix_bits']} "
        f"q_known={summary['base_q_known_bits']}"
    )
    for item in report["range_sets"]:
        best = item["top_candidates"][0] if item["top_candidates"] else {}
        ranges_text = ",".join(best.get("fixed_ranges_text", [])) or "(none)"
        print(
            f"{item['name']} ranges={item['ranges']} emitted={item['emitted_cubes']}/"
            f"{item['total_cube_count']} best_q_prefix={item['best_q_prefix_bits']} "
            f"best_q_known={item['best_q_known_bits']} "
            f"width_bits={item['best_q_interval_width_bits']} best={ranges_text}"
        )


def main() -> int:
    args = parse_args()
    if args.max_cubes < 0:
        raise SystemExit("--max-cubes must be non-negative")
    if args.top < 1:
        raise SystemExit("--top must be positive")

    if args.range_set:
        range_sets = [parse_range_set(item, index) for index, item in enumerate(args.range_set, start=1)]
    else:
        range_sets = list(DEFAULT_RANGE_SETS)

    instance = load_instance()
    base_ranges = [parse_fixed_range(item) for item in DEFAULT_BASE_RANGES]
    base_ranges.extend(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)
    base_q_known_bits = base_q.mask.bit_count()
    base_p_fixed_bits = base_mask.bit_count()

    range_reports = [
        summarize_range_set(
            instance,
            base_ranges,
            name,
            ranges,
            args.max_cubes,
            args.top,
            base_q_known_bits,
            base_q.low_bits,
            base_q.prefix_bits,
            base_p_fixed_bits,
        )
        for name, ranges in range_sets
    ]

    report = {
        "event": "q_edge_rank_probe",
        "summary": {
            "ranking_priority": "q_prefix_bits,q_known_bits,q_low_bits,small_interval",
            "base_fixed_ranges": compact_ranges(base_ranges),
            "base_p_fixed_bits": base_p_fixed_bits,
            "base_q_low_bits": base_q.low_bits,
            "base_q_prefix_bits": base_q.prefix_bits,
            "base_q_prefix_start": base_q.prefix_start,
            "base_q_known_bits": base_q_known_bits,
            "max_cubes": args.max_cubes,
            "top": args.top,
            "range_set_count": len(range_reports),
        },
        "range_sets": range_reports,
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        emit_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
