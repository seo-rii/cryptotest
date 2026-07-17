#!/usr/bin/env python3
"""Group interval-derived q-prefix candidates and inspect top-group ties."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from typing import Any

from q_interval_sweep import compact_ranges, parse_cube_ranges
from q_prefix_growth_search import iter_limited_cubes, summarize_candidate
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


DEFAULT_FIX_P_RANGE = "784:46:0x245521490bd"
DEFAULT_RANGES = "150:4,920:4"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_fixed_range,
        help=(
            "fixed p-bit range START:WIDTH:VALUE; if omitted, defaults to "
            f"full x6 {DEFAULT_FIX_P_RANGE}"
        ),
    )
    parser.add_argument(
        "--ranges",
        action="append",
        default=[],
        help=(
            "comma-separated START:WIDTH p-bit ranges to enumerate; may be "
            "supplied more than once"
        ),
    )
    parser.add_argument("--max-cubes", type=int, default=256, help="maximum cubes per range set")
    parser.add_argument("--top-groups", type=int, default=8, help="number of tie groups to report")
    parser.add_argument("--json", action="store_true", help="emit a single JSON object")
    args = parser.parse_args()

    if args.max_cubes < 0:
        raise SystemExit("--max-cubes must be non-negative")
    if args.top_groups < 1:
        raise SystemExit("--top-groups must be positive")

    instance = load_instance()
    base_ranges: list[FixedRange] = list(args.fix_p_range)
    used_default_fix = not base_ranges
    if used_default_fix:
        base_ranges = [parse_fixed_range(DEFAULT_FIX_P_RANGE)]
    range_sets = args.ranges or [DEFAULT_RANGES]

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

    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["q_prefix_bits"]), int(row["q_known_bits"]))].append(row)

    group_rows: list[dict[str, Any]] = []
    for (q_prefix_bits, q_known_bits), candidates in grouped.items():
        q_low_histogram = Counter(str(int(item["q_low_bits"])) for item in candidates)
        range_set_histogram = Counter(str(item["range_set"]) for item in candidates)
        group_rows.append(
            {
                "q_prefix_bits": q_prefix_bits,
                "q_known_bits": q_known_bits,
                "count": len(candidates),
                "q_low_bits_histogram": dict(sorted(q_low_histogram.items(), key=lambda item: int(item[0]))),
                "range_set_histogram": dict(sorted(range_set_histogram.items())),
                "min_q_interval_width_bits": min(int(item["q_interval_width_bits"]) for item in candidates),
                "max_q_interval_width_bits": max(int(item["q_interval_width_bits"]) for item in candidates),
            }
        )
    group_rows.sort(
        key=lambda item: (
            -int(item["q_prefix_bits"]),
            -int(item["q_known_bits"]),
            -int(item["count"]),
        )
    )

    top_group_histograms: dict[str, list[dict[str, int | str]]] = {}
    top_group_sample: list[dict[str, Any]] = []
    if group_rows:
        top_key = (int(group_rows[0]["q_prefix_bits"]), int(group_rows[0]["q_known_bits"]))
        top_candidates = grouped[top_key]
        histogram_by_range: dict[str, Counter[int]] = defaultdict(Counter)
        for row in top_candidates:
            for item in row["fixed_ranges"]:
                label = f"{int(item['start'])}:{int(item['width'])}"
                histogram_by_range[label][int(item["value"])] += 1
        for label, histogram in sorted(
            histogram_by_range.items(),
            key=lambda item: tuple(int(part) for part in item[0].split(":", 1)),
        ):
            top_group_histograms[label] = [
                {"value": value, "value_hex": hex(value), "count": count}
                for value, count in sorted(histogram.items())
            ]
        for row in sorted(
            top_candidates,
            key=lambda item: (
                int(item["q_interval_width_bits"]),
                tuple(
                    (int(fixed["start"]), int(fixed["width"]), int(fixed["value"]))
                    for fixed in item["fixed_ranges"]
                ),
            ),
        )[: min(8, len(top_candidates))]:
            top_group_sample.append(
                {
                    "range_set": row["range_set"],
                    "index": row["index"],
                    "fixed_ranges": row["fixed_ranges"],
                    "q_low_bits": row["q_low_bits"],
                    "q_prefix_bits": row["q_prefix_bits"],
                    "q_known_bits": row["q_known_bits"],
                    "q_interval_width_bits": row["q_interval_width_bits"],
                }
            )

    summary = {
        "event": "q_prefix_tie_analyzer",
        "range_sets": range_summaries,
        "base_fixed_ranges": compact_ranges(base_ranges),
        "used_default_full_x6": used_default_fix,
        "base_p_fixed_bits": base_p_fixed_bits,
        "base_q_low_bits": base_q.low_bits,
        "base_q_prefix_bits": base_q.prefix_bits,
        "base_q_prefix_start": base_q.prefix_start,
        "base_q_known_bits": base_q_known_bits,
        "emitted_cubes": len(rows),
        "group_count": len(group_rows),
        "top_groups": args.top_groups,
    }
    output = {
        "summary": summary,
        "groups": group_rows[: args.top_groups],
        "top_group_histograms": top_group_histograms,
        "top_group_sample": top_group_sample,
    }

    if args.json:
        print(json.dumps(output, sort_keys=True))
    else:
        print(
            "base "
            f"p_fixed={summary['base_p_fixed_bits']} "
            f"q_low={summary['base_q_low_bits']} "
            f"q_prefix={summary['base_q_prefix_bits']} "
            f"q_known={summary['base_q_known_bits']} "
            f"cubes={summary['emitted_cubes']} "
            f"groups={summary['group_count']}"
        )
        for rank, group in enumerate(output["groups"], start=1):
            print(
                f"{rank:02d} "
                f"q_prefix={group['q_prefix_bits']} "
                f"q_known={group['q_known_bits']} "
                f"count={group['count']} "
                f"width_bits={group['min_q_interval_width_bits']}..{group['max_q_interval_width_bits']}"
            )
        if top_group_histograms:
            print("top group histograms:")
            for label, histogram in top_group_histograms.items():
                values = " ".join(f"{item['value_hex']}:{item['count']}" for item in histogram)
                print(f"  {label} {values}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
