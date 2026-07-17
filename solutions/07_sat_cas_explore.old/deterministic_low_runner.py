#!/usr/bin/env python3
"""Deterministic low-prefix SAT/CAS cube runner for challenge 7.

This keeps the sound-oracle discipline of semi_programmatic_sat.py, but removes
Z3 model-order effects from cube selection.  It is useful for replaying exact
low-prefix assignments and for auditing the low-Coppersmith no-good scope.
"""

from __future__ import annotations

import argparse
import json
import time

from low_coppersmith_oracle import run_low_coppersmith
from q_interval_sweep import compact_ranges, parse_cube_ranges
from q_prefix_growth_search import iter_limited_cubes, rank_key, summarize_candidate
from sat_cas_core import (
    FixedRange,
    all_bits_known,
    derive_q_known_bits,
    load_instance,
    parse_fixed_range,
    z3_hensel_prefix_status,
    z3_product_prefix_status,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--high-ranges",
        default="",
        help="optional START:WIDTH high-side ranges ranked by q-prefix growth",
    )
    parser.add_argument("--high-max-cubes", type=int, default=64)
    parser.add_argument("--top-high", type=int, default=0)
    parser.add_argument(
        "--low-ranges",
        default="150:4,210:39,265:84,362:78",
        help="START:WIDTH low-prefix ranges enumerated deterministically",
    )
    parser.add_argument("--max-low-cubes", type=int, default=2)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--check-bits", type=int, default=608)
    parser.add_argument("--prefix-core", choices=["bv", "hensel"], default="bv")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--run-low-coppersmith", action="store_true")
    parser.add_argument("--low-coppersmith-bits", type=int, default=600)
    parser.add_argument("--low-coppersmith-epsilon", type=float, default=0.02)
    parser.add_argument("--low-coppersmith-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--low-coppersmith-hard-fail", action="store_true")
    parser.add_argument("--include-ranges", action="store_true")
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    if args.high_max_cubes < 0:
        raise SystemExit("--high-max-cubes must be non-negative")
    if args.top_high < 0:
        raise SystemExit("--top-high must be non-negative")
    if args.max_low_cubes < 1:
        raise SystemExit("--max-low-cubes must be positive")
    if args.low_coppersmith_bits <= 0:
        raise SystemExit("--low-coppersmith-bits must be positive")
    if args.low_coppersmith_min_hard_margin_bits < 0:
        raise SystemExit("--low-coppersmith-min-hard-margin-bits must be nonnegative")

    instance = load_instance()
    base_ranges: list[FixedRange] = list(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)
    high_candidates: list[list[FixedRange]] = [[]]
    high_reports: list[dict[str, object]] = []
    if args.high_ranges:
        high_rows = []
        for index, cube in enumerate(
            iter_limited_cubes(parse_cube_ranges(args.high_ranges), args.high_max_cubes),
            start=1,
        ):
            high_rows.append(
                summarize_candidate(
                    instance,
                    base_ranges,
                    cube,
                    args.high_ranges,
                    index,
                    base_q.mask.bit_count(),
                    base_q.low_bits,
                    base_q.prefix_bits,
                    base_mask.bit_count(),
                )
            )
        high_rows.sort(key=rank_key)
        high_rows = high_rows[: args.top_high] if args.top_high else high_rows
        high_candidates = [
            [
                FixedRange(int(item["start"]), int(item["width"]), int(item["value"]))
                for item in row["fixed_ranges"]
            ]
            for row in high_rows
        ]
        high_reports = high_rows

    low_ranges = parse_cube_ranges(args.low_ranges)
    counters = {
        "high_candidates": len(high_candidates),
        "cubes": 0,
        "prefix_unsat": 0,
        "prefix_sat": 0,
        "prefix_unknown": 0,
        "low_coppersmith_calls": 0,
        "low_coppersmith_hard_blocks": 0,
        "factored_events": 0,
    }
    started_at = time.time()

    start_record = {
        "event": "deterministic_low_start",
        "high_ranges": args.high_ranges,
        "high_max_cubes": args.high_max_cubes,
        "top_high": args.top_high,
        "low_ranges": args.low_ranges,
        "max_low_cubes": args.max_low_cubes,
        "check_bits": args.check_bits,
        "prefix_core": args.prefix_core,
        "fixed_ranges": compact_ranges(base_ranges),
        "ranked_high_candidates": high_reports,
    }
    if args.jsonl:
        print(json.dumps(start_record, sort_keys=True), flush=True)
    else:
        print(json.dumps(start_record, indent=2, sort_keys=True), flush=True)

    for high_index, high_fixed in enumerate(high_candidates, start=1):
        for low_index, low_fixed in enumerate(
            iter_limited_cubes(low_ranges, args.max_low_cubes),
            start=1,
        ):
            p_known, p_mask = instance.apply_fixed_ranges(base_ranges + high_fixed + low_fixed)
            if args.prefix_core == "hensel":
                prefix_status, prefix_meta = z3_hensel_prefix_status(
                    instance=instance,
                    p_known=p_known,
                    p_mask=p_mask,
                    prefix_bits=args.check_bits,
                    timeout_ms=args.timeout_ms,
                )
            else:
                prefix_status, prefix_meta = z3_product_prefix_status(
                    instance=instance,
                    p_known=p_known,
                    p_mask=p_mask,
                    check_bits=args.check_bits,
                    timeout_ms=args.timeout_ms,
                    enumerate_p_free_limit=args.enumerate_p_free_limit,
                )
            counters["cubes"] += 1
            if prefix_status == "unsat":
                counters["prefix_unsat"] += 1
            elif prefix_status == "sat":
                counters["prefix_sat"] += 1
            else:
                counters["prefix_unknown"] += 1

            event: dict[str, object] = {
                "event": "cube",
                "high_index": high_index,
                "low_index": low_index,
                "product_prefix_status": prefix_status,
                **prefix_meta,
            }
            if args.include_ranges:
                event["high_fixed_ranges"] = compact_ranges(high_fixed)
                event["low_fixed_ranges"] = compact_ranges(low_fixed)

            if (
                args.run_low_coppersmith
                and all_bits_known(p_mask, 0, args.low_coppersmith_bits)
            ):
                counters["low_coppersmith_calls"] += 1
                low_report = run_low_coppersmith(
                    p_known=p_known,
                    p_mask=p_mask,
                    n=instance.n,
                    low_bits=args.low_coppersmith_bits,
                    p_bits=instance.p_bits,
                    epsilon=args.low_coppersmith_epsilon,
                    min_hard_margin_bits=args.low_coppersmith_min_hard_margin_bits,
                )
                event["low_coppersmith"] = low_report
                if low_report.get("status") == "factored":
                    counters["factored_events"] += 1
                    event["learned_clause"] = "factored"
                elif (
                    args.low_coppersmith_hard_fail
                    and low_report.get("status") == "no_roots"
                    and low_report.get("hard_clause_eligible")
                ):
                    low_literal_count = sum(
                        item.width
                        for item in low_fixed
                        if item.start + item.width <= args.low_coppersmith_bits
                    )
                    partial_low_literal_count = sum(
                        max(0, args.low_coppersmith_bits - item.start)
                        for item in low_fixed
                        if item.start < args.low_coppersmith_bits < item.start + item.width
                    )
                    counters["low_coppersmith_hard_blocks"] += 1
                    event["learned_clause"] = "low_coppersmith_no_root"
                    event["learned_clause_scope"] = "deterministic_low_selected_bits"
                    event["learned_clause_literal_count"] = (
                        low_literal_count + partial_low_literal_count
                    )
                else:
                    event["learned_clause"] = "none"
            else:
                event["learned_clause"] = "none"

            if args.jsonl:
                print(json.dumps(event, sort_keys=True), flush=True)
            else:
                print(json.dumps(event, indent=2, sort_keys=True), flush=True)

    summary = {
        "event": "summary",
        **counters,
        "elapsed_seconds": round(time.time() - started_at, 3),
    }
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
