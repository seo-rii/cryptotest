#!/usr/bin/env python3
"""Explore fixed p-bit ranges that grow interval-derived q prefixes.

This script is intentionally a thin layer over q_interval_sweep.py helpers.  It
keeps the ranking logic local, but reuses the existing cube parsing,
enumeration, range compaction, and q-known derivation pipeline.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from q_interval_sweep import compact_ranges, compact_ranges_key, parse_cube_ranges
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


DEFAULT_RANGES = "822:8,920:4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ranges",
        action="append",
        default=[],
        help="comma-separated START:WIDTH p-bit ranges to enumerate; may be supplied more than once",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--max-cubes", type=int, default=64, help="maximum cubes per range set")
    parser.add_argument("--top", type=int, default=10, help="number of ranked candidates to report")
    parser.add_argument("--json", action="store_true", help="emit a single JSON object")
    parser.add_argument(
        "--emit-fix-p-range",
        action="store_true",
        help="emit only the best candidate as sat_cas_batch_runner.py --fix-p-range arguments",
    )
    return parser.parse_args()


def format_fixed_range(item: FixedRange) -> str:
    return f"{item.start}:{item.width}:{hex(item.value)}"


def format_range_label(item: dict[str, Any]) -> str:
    return f"{int(item['start'])}:{int(item['width'])}={hex(int(item['value']))}"


def fix_p_range_args(ranges: list[FixedRange]) -> list[str]:
    args: list[str] = []
    for item in sorted(ranges, key=lambda value: value.start):
        args.extend(["--fix-p-range", format_fixed_range(item)])
    return args


def iter_limited_cubes(cube_ranges, max_cubes: int):
    if not cube_ranges:
        if max_cubes > 0:
            yield []
        return

    sizes = [item.size for item in cube_ranges]
    for ordinal in range(max_cubes):
        residual = ordinal
        values_reversed: list[int] = []
        for size in reversed(sizes):
            values_reversed.append(residual % size)
            residual //= size
        if residual:
            return
        values = list(reversed(values_reversed))
        yield [
            FixedRange(item.start, item.width, value)
            for item, value in zip(cube_ranges, values, strict=True)
        ]


def summarize_candidate(
    instance,
    base_ranges: list[FixedRange],
    cube_ranges: list[FixedRange],
    range_set: str,
    index: int,
    base_q_known_bits: int,
    base_q_low_bits: int,
    base_q_prefix_bits: int,
    base_p_fixed_bits: int,
) -> dict[str, Any]:
    p_known, p_mask = instance.apply_fixed_ranges(base_ranges + cube_ranges)
    q_known = derive_q_known_bits(instance, p_known, p_mask)
    compact_cube = compact_ranges(cube_ranges)
    all_ranges = base_ranges + cube_ranges
    interval_width = q_known.q_max - q_known.q_min
    return {
        "event": "candidate",
        "range_set": range_set,
        "index": index,
        "fixed_ranges": compact_cube,
        "fixed_ranges_text": [format_range_label(item) for item in compact_cube],
        "p_fixed_bits": p_mask.bit_count(),
        "p_fixed_gain": p_mask.bit_count() - base_p_fixed_bits,
        "q_low_bits": q_known.low_bits,
        "q_low_gain": q_known.low_bits - base_q_low_bits,
        "q_prefix_bits": q_known.prefix_bits,
        "q_prefix_gain": q_known.prefix_bits - base_q_prefix_bits,
        "q_prefix_start": q_known.prefix_start,
        "q_known_bits": q_known.mask.bit_count(),
        "q_known_gain": q_known.mask.bit_count() - base_q_known_bits,
        "q_interval_width_bits": interval_width.bit_length(),
        "q_interval_width_hex": hex(interval_width),
        "q_min_bits": q_known.q_min.bit_length(),
        "q_max_bits": q_known.q_max.bit_length(),
        "candidate_fix_p_range_args": fix_p_range_args(cube_ranges),
        "all_fix_p_range_args": fix_p_range_args(all_ranges),
    }


def rank_key(row: dict[str, Any]) -> tuple[int, int, int, int, tuple[tuple[int, int, int], ...]]:
    return (
        -int(row["q_known_bits"]),
        -int(row["q_prefix_bits"]),
        -int(row["q_low_bits"]),
        int(row["q_interval_width_bits"]),
        compact_ranges_key(row["fixed_ranges"]),
    )


def emit_human(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    print(
        "base "
        f"p_fixed={summary['base_p_fixed_bits']} "
        f"q_low={summary['base_q_low_bits']} "
        f"q_prefix={summary['base_q_prefix_bits']} "
        f"q_known={summary['base_q_known_bits']}"
    )
    if not rows:
        print("no candidates")
        return

    for rank, row in enumerate(rows, start=1):
        ranges_text = ",".join(row["fixed_ranges_text"]) or "(none)"
        print(
            f"{rank:02d} "
            f"set={row['range_set']} "
            f"cube={row['index']} "
            f"ranges={ranges_text} "
            f"q_low={row['q_low_bits']} "
            f"q_prefix={row['q_prefix_bits']} "
            f"q_known={row['q_known_bits']} "
            f"width_bits={row['q_interval_width_bits']} "
            f"gains=+{row['q_low_gain']}/+{row['q_prefix_gain']}/+{row['q_known_gain']}"
        )


def main() -> int:
    args = parse_args()
    if args.max_cubes < 0:
        raise SystemExit("--max-cubes must be non-negative")
    if args.top < 1:
        raise SystemExit("--top must be positive")

    range_sets = args.ranges or [DEFAULT_RANGES]
    instance = load_instance()
    base_ranges: list[FixedRange] = list(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)
    base_q_known_bits = base_q.mask.bit_count()
    base_p_fixed_bits = base_mask.bit_count()

    rows: list[dict[str, Any]] = []
    range_summaries: list[dict[str, Any]] = []
    for range_set in range_sets:
        parsed_ranges = parse_cube_ranges(range_set)
        emitted = 0
        for index, cube in enumerate(iter_limited_cubes(parsed_ranges, args.max_cubes), start=1):
            emitted += 1
            rows.append(
                summarize_candidate(
                    instance,
                    base_ranges,
                    cube,
                    range_set,
                    index,
                    base_q_known_bits,
                    base_q.low_bits,
                    base_q.prefix_bits,
                    base_p_fixed_bits,
                )
            )
        range_summaries.append(
            {
                "ranges": range_set,
                "parsed_ranges": [{"start": item.start, "width": item.width} for item in parsed_ranges],
                "emitted_cubes": emitted,
            }
        )

    rows.sort(key=rank_key)
    top_rows = rows[: args.top]
    summary = {
        "event": "q_prefix_growth_search",
        "range_sets": range_summaries,
        "base_fixed_ranges": compact_ranges(base_ranges),
        "base_p_fixed_bits": base_p_fixed_bits,
        "base_q_low_bits": base_q.low_bits,
        "base_q_prefix_bits": base_q.prefix_bits,
        "base_q_prefix_start": base_q.prefix_start,
        "base_q_known_bits": base_q_known_bits,
        "emitted_cubes": len(rows),
        "top": args.top,
        "best_all_fix_p_range_args": top_rows[0]["all_fix_p_range_args"] if top_rows else [],
    }

    if args.emit_fix_p_range:
        print(" ".join(summary["best_all_fix_p_range_args"]))
    elif args.json:
        print(json.dumps({"summary": summary, "items": top_rows}, sort_keys=True))
    else:
        emit_human(summary, top_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
