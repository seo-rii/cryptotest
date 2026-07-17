#!/usr/bin/env python3
"""Rank q-prefix candidates and test product/Hensel prefix consistency.

This is a bounded coordinator: it enumerates selected high-side p ranges,
keeps only the best interval-derived q-prefix candidates, then checks whether
the prefix product core can already prove UNSAT before the low-Coppersmith
trigger is reached.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from q_interval_sweep import compact_ranges, compact_ranges_key, parse_cube_ranges
from q_prefix_growth_search import DEFAULT_RANGES, iter_limited_cubes, summarize_candidate
from sat_cas_core import (
    FixedRange,
    derive_q_known_bits,
    load_instance,
    parse_fixed_range,
    z3_hensel_prefix_status,
    z3_product_prefix_status,
)


DEFAULT_PREFIX_BITS = "272,320"


def parse_prefix_bits(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        value = int(part, 0)
        if value <= 0:
            raise argparse.ArgumentTypeError("prefix bits must be positive")
        values.append(value)
    if not values:
        raise argparse.ArgumentTypeError("at least one prefix bit value is required")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ranges",
        action="append",
        default=[],
        help="comma-separated START:WIDTH p-bit ranges to enumerate; may be supplied more than once",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--top", type=int, default=2, help="number of q-prefix candidates to test")
    parser.add_argument("--max-cubes", type=int, default=32, help="maximum cubes per range set")
    parser.add_argument(
        "--prefix-bits",
        action="append",
        default=[],
        type=parse_prefix_bits,
        help="comma-separated product prefix widths to test; may be supplied more than once",
    )
    parser.add_argument("--prefix-core", choices=["bv", "hensel"], default="hensel")
    parser.add_argument("--timeout-ms", type=int, default=500)
    parser.add_argument("--json", action="store_true", help="emit a single JSON object")
    return parser.parse_args()


def flatten_prefix_bits(values: list[list[int]]) -> list[int]:
    if not values:
        return parse_prefix_bits(DEFAULT_PREFIX_BITS)
    flattened: list[int] = []
    seen: set[int] = set()
    for group in values:
        for item in group:
            if item not in seen:
                flattened.append(item)
                seen.add(item)
    return flattened


def fixed_range_text(ranges: list[FixedRange]) -> list[str]:
    return [
        f"{item.start}:{item.width}:{hex(item.value)}"
        for item in sorted(ranges, key=lambda value: value.start)
    ]


def compact_candidate_ranges(candidate: dict[str, Any]) -> list[FixedRange]:
    ranges: list[FixedRange] = []
    for item in candidate.get("fixed_ranges", []):
        ranges.append(FixedRange(int(item["start"]), int(item["width"]), int(item["value"])))
    return ranges


def rank_key(row: dict[str, Any]) -> tuple[int, int, int, int, tuple[tuple[int, int, int], ...]]:
    return (
        -int(row["q_known_bits"]),
        -int(row["q_prefix_bits"]),
        -int(row["q_low_bits"]),
        int(row["q_interval_width_bits"]),
        compact_ranges_key(row["fixed_ranges"]),
    )


def collect_candidates(
    instance,
    base_ranges: list[FixedRange],
    range_sets: list[str],
    max_cubes: int,
    top: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)

    rows: list[dict[str, Any]] = []
    range_summaries: list[dict[str, Any]] = []
    for range_set in range_sets:
        parsed_ranges = parse_cube_ranges(range_set)
        emitted = 0
        skipped = 0
        for index, cube in enumerate(iter_limited_cubes(parsed_ranges, max_cubes), start=1):
            emitted += 1
            try:
                row = summarize_candidate(
                    instance,
                    base_ranges,
                    cube,
                    range_set,
                    index,
                    base_q.mask.bit_count(),
                    base_q.low_bits,
                    base_q.prefix_bits,
                    base_mask.bit_count(),
                )
            except ValueError:
                skipped += 1
                continue
            rows.append(row)
        range_summaries.append(
            {
                "ranges": range_set,
                "parsed_ranges": [{"start": item.start, "width": item.width} for item in parsed_ranges],
                "emitted_cubes": emitted,
                "skipped_inconsistent": skipped,
            }
        )

    rows.sort(key=rank_key)
    return rows[:top], range_summaries


def check_candidate(
    instance,
    base_ranges: list[FixedRange],
    candidate: dict[str, Any],
    prefix_bits: int,
    prefix_core: str,
    timeout_ms: int,
) -> dict[str, Any]:
    candidate_ranges = compact_candidate_ranges(candidate)
    all_ranges = base_ranges + candidate_ranges
    p_known, p_mask = instance.apply_fixed_ranges(all_ranges)
    q_known = derive_q_known_bits(instance, p_known, p_mask)
    if prefix_core == "bv":
        status, details = z3_product_prefix_status(instance, p_known, p_mask, prefix_bits, timeout_ms)
    else:
        status, details = z3_hensel_prefix_status(instance, p_known, p_mask, prefix_bits, timeout_ms)

    return {
        "event": "prefix_check",
        "status": status,
        "prefix_core": prefix_core,
        "prefix_bits": prefix_bits,
        "timeout_ms": timeout_ms,
        "candidate_index": candidate["index"],
        "range_set": candidate["range_set"],
        "candidate_fixed_ranges": compact_ranges(candidate_ranges),
        "base_fixed_ranges": compact_ranges(base_ranges),
        "all_fixed_ranges": compact_ranges(all_ranges),
        "all_fixed_ranges_text": fixed_range_text(all_ranges),
        "p_fixed_bits": p_mask.bit_count(),
        "q_fixed_bits": q_known.mask.bit_count(),
        "q_low_bits": q_known.low_bits,
        "q_prefix_bits": q_known.prefix_bits,
        "q_prefix_start": q_known.prefix_start,
        "q_known_bits": q_known.mask.bit_count(),
        "rank_q_known_bits": candidate["q_known_bits"],
        "rank_q_prefix_bits": candidate["q_prefix_bits"],
        "details": details,
    }


def emit_human(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    print(
        "base "
        f"p_fixed={summary['base_p_fixed_bits']} "
        f"q_low={summary['base_q_low_bits']} "
        f"q_prefix={summary['base_q_prefix_bits']} "
        f"q_known={summary['base_q_known_bits']}"
    )
    for row in results:
        ranges = ",".join(row["all_fixed_ranges_text"]) or "(none)"
        print(
            f"{row['status']:7s} "
            f"core={row['prefix_core']} "
            f"bits={row['prefix_bits']} "
            f"cube={row['candidate_index']} "
            f"ranges={ranges} "
            f"p_fixed={row['p_fixed_bits']} "
            f"q_prefix={row['q_prefix_bits']} "
            f"q_known={row['q_known_bits']} "
            f"p_pref={row['details'].get('p_fixed_bits_in_prefix')} "
            f"q_pref={row['details'].get('q_fixed_bits_in_prefix')}"
        )


def main() -> int:
    args = parse_args()
    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.max_cubes < 0:
        raise SystemExit("--max-cubes must be non-negative")
    if args.timeout_ms < 1:
        raise SystemExit("--timeout-ms must be positive")

    prefix_bits_values = flatten_prefix_bits(args.prefix_bits)
    range_sets = args.ranges or [DEFAULT_RANGES]
    instance = load_instance()
    base_ranges: list[FixedRange] = list(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)

    candidates, range_summaries = collect_candidates(
        instance,
        base_ranges,
        range_sets,
        args.max_cubes,
        args.top,
    )

    results: list[dict[str, Any]] = []
    for candidate in candidates:
        for prefix_bits in prefix_bits_values:
            results.append(
                check_candidate(
                    instance,
                    base_ranges,
                    candidate,
                    prefix_bits,
                    args.prefix_core,
                    args.timeout_ms,
                )
            )

    status_counts: dict[str, int] = {}
    for row in results:
        status_counts[str(row["status"])] = status_counts.get(str(row["status"]), 0) + 1

    summary = {
        "event": "q_hensel_prefix_search",
        "range_sets": range_summaries,
        "base_fixed_ranges": compact_ranges(base_ranges),
        "base_p_fixed_bits": base_mask.bit_count(),
        "base_q_low_bits": base_q.low_bits,
        "base_q_prefix_bits": base_q.prefix_bits,
        "base_q_prefix_start": base_q.prefix_start,
        "base_q_known_bits": base_q.mask.bit_count(),
        "prefix_core": args.prefix_core,
        "prefix_bits": prefix_bits_values,
        "timeout_ms": args.timeout_ms,
        "max_cubes": args.max_cubes,
        "top": args.top,
        "candidate_count": len(candidates),
        "check_count": len(results),
        "status_counts": status_counts,
    }

    if args.json:
        print(json.dumps({"summary": summary, "candidates": candidates, "items": results}, sort_keys=True))
    else:
        emit_human(summary, results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
