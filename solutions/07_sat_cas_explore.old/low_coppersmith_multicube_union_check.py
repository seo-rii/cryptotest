#!/usr/bin/env python3
"""Parallel fixed-union low-Coppersmith no-good checker across low cubes."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time

from low_coppersmith_oracle import run_low_coppersmith
from q_interval_sweep import compact_ranges
from sat_cas_core import FixedRange, all_bits_known, load_instance, parse_fixed_range


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--base-selected-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--variant-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--drop-window", action="append", default=[], help="START:WIDTH window included in the union")
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--max-completions", type=int, default=1024)
    parser.add_argument("--completion-start", type=int, default=0)
    parser.add_argument("--completion-count", type=int)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.low_bits <= 0 or args.low_bits > 1024:
        raise SystemExit("--low-bits must be in 1..1024")
    if args.max_completions < 1:
        raise SystemExit("--max-completions must be positive")
    if args.completion_start < 0:
        raise SystemExit("--completion-start must be nonnegative")
    if args.completion_count is not None and args.completion_count < 1:
        raise SystemExit("--completion-count must be positive")
    if args.jobs < 1:
        raise SystemExit("--jobs must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")
    if not args.base_selected_p_range:
        raise SystemExit("--base-selected-p-range is required")
    if not args.variant_p_range:
        raise SystemExit("--variant-p-range is required")
    if not args.drop_window:
        raise SystemExit("--drop-window is required")

    started_at = time.time()
    instance = load_instance()
    fixed_ranges: list[FixedRange] = list(args.fix_p_range)
    low_coppersmith_mask = (1 << args.low_bits) - 1

    base_bit_values: dict[int, int] = {}
    for item in args.base_selected_p_range:
        if item.start < 0 or item.width <= 0 or item.start + item.width > args.low_bits:
            raise SystemExit("--base-selected-p-range must be inside --low-bits")
        for offset in range(item.width):
            base_bit_values[item.start + offset] = (item.value >> offset) & 1

    variant_bit_values: list[dict[int, int]] = []
    variant_rows = []
    for variant in args.variant_p_range:
        if variant.start < 0 or variant.width <= 0 or variant.start + variant.width > args.low_bits:
            raise SystemExit("--variant-p-range must be inside --low-bits")
        selected_bit_values = dict(base_bit_values)
        for offset in range(variant.width):
            selected_bit_values[variant.start + offset] = (variant.value >> offset) & 1
        variant_bit_values.append(selected_bit_values)
        variant_rows.append(
            {
                "variant": {"start": variant.start, "width": variant.width, "value": variant.value},
                "variant_arg": f"{variant.start}:{variant.width}:{hex(variant.value)}",
                "selected_literal_count": len(selected_bit_values),
            }
        )

    common_selected_bits = set(variant_bit_values[0])
    for selected_bit_values in variant_bit_values[1:]:
        common_selected_bits &= set(selected_bit_values)

    dropped_bits: set[int] = set()
    parsed_windows = []
    for raw_window in args.drop_window:
        try:
            start_text, width_text = raw_window.split(":", 1)
        except ValueError as exc:
            raise SystemExit("--drop-window must be START:WIDTH") from exc
        window_start = int(start_text, 0)
        window_width = int(width_text, 0)
        if window_start < 0 or window_width <= 0 or window_start + window_width > args.low_bits:
            raise SystemExit("--drop-window must be inside --low-bits")
        parsed_windows.append({"start": window_start, "width": window_width})
        for bit in range(window_start, window_start + window_width):
            if bit in common_selected_bits:
                dropped_bits.add(bit)

    completion_bits = sorted(dropped_bits)
    completion_count = 1 << len(completion_bits)
    completion_start = args.completion_start
    if completion_start >= completion_count:
        raise SystemExit("--completion-start is outside the union completion space")
    checked_completion_count = (
        completion_count - completion_start
        if args.completion_count is None
        else min(args.completion_count, completion_count - completion_start)
    )
    completion_stop = completion_start + checked_completion_count
    if checked_completion_count > args.max_completions:
        raise SystemExit(
            f"requested shard checks {checked_completion_count} completions per variant; "
            f"increase --max-completions if intended"
        )

    oracle_cases: dict[tuple[int, int], tuple[int, int]] = {}
    key_multiplicity: dict[tuple[int, int], int] = {}
    not_triggered_count = 0
    for selected_bit_values in variant_bit_values:
        fixed_kept_bits = [
            FixedRange(bit, 1, value)
            for bit, value in sorted(selected_bit_values.items())
            if bit not in dropped_bits
        ]
        for completion_value in range(completion_start, completion_stop):
            completion_ranges = [
                FixedRange(bit, 1, (completion_value >> index) & 1)
                for index, bit in enumerate(completion_bits)
            ]
            completion_known, completion_mask = instance.apply_fixed_ranges(
                fixed_ranges + fixed_kept_bits + completion_ranges
            )
            if not all_bits_known(completion_mask, 0, args.low_bits):
                not_triggered_count += 1
                continue
            cache_key = (
                completion_known & low_coppersmith_mask,
                completion_mask & low_coppersmith_mask,
            )
            oracle_cases.setdefault(cache_key, (completion_known, completion_mask))
            key_multiplicity[cache_key] = key_multiplicity.get(cache_key, 0) + 1

    status_counts_unique: dict[str, int] = {}
    status_counts_total: dict[str, int] = {}
    hard_eligible_unique_count = 0
    hard_eligible_total_count = 0
    roots_returned_unique_total = 0
    factors = []
    future_to_key: dict[concurrent.futures.Future[dict[str, object]], tuple[int, int]] = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as executor:
        for cache_key, (completion_known, completion_mask) in oracle_cases.items():
            future = executor.submit(
                run_low_coppersmith,
                p_known=completion_known,
                p_mask=completion_mask,
                n=instance.n,
                low_bits=args.low_bits,
                p_bits=instance.p_bits,
                epsilon=args.epsilon,
                min_hard_margin_bits=args.min_hard_margin_bits,
            )
            future_to_key[future] = cache_key
        for future in concurrent.futures.as_completed(future_to_key):
            cache_key = future_to_key[future]
            report = future.result()
            status = str(report.get("status"))
            multiplicity = key_multiplicity[cache_key]
            status_counts_unique[status] = status_counts_unique.get(status, 0) + 1
            status_counts_total[status] = status_counts_total.get(status, 0) + multiplicity
            if status == "no_roots" and report.get("hard_clause_eligible"):
                hard_eligible_unique_count += 1
                hard_eligible_total_count += multiplicity
            roots_returned_unique_total += int(report.get("roots_returned") or 0)
            if report.get("factors"):
                factors.extend(report.get("factors") or [])

    all_completions_no_roots = (
        not_triggered_count == 0
        and status_counts_unique == {"no_roots": len(oracle_cases)}
        and hard_eligible_unique_count == len(oracle_cases)
    )
    payload = {
        "event": "low_coppersmith_multicube_union_check",
        "summary": {
            "low_bits": args.low_bits,
            "epsilon": args.epsilon,
            "min_hard_margin_bits": args.min_hard_margin_bits,
            "variant_count": len(variant_bit_values),
            "common_selected_literal_count": len(common_selected_bits),
            "dropped_literal_count": len(dropped_bits),
            "remaining_common_literal_count": len(common_selected_bits) - len(dropped_bits),
            "dropped_bits": completion_bits,
            "drop_windows": parsed_windows,
            "completion_count_per_variant": completion_count,
            "completion_start": completion_start,
            "checked_completion_count_per_variant": checked_completion_count,
            "completion_stop": completion_stop,
            "shard_complete": checked_completion_count == completion_count,
            "total_completion_checks": checked_completion_count * len(variant_bit_values),
            "unique_oracle_cases": len(oracle_cases),
            "deduped_completion_checks": checked_completion_count * len(variant_bit_values) - len(oracle_cases),
            "not_triggered_count": not_triggered_count,
            "status_counts_unique": status_counts_unique,
            "status_counts_total": status_counts_total,
            "hard_eligible_unique_count": hard_eligible_unique_count,
            "hard_eligible_total_count": hard_eligible_total_count,
            "roots_returned_unique_total": roots_returned_unique_total,
            "all_completions_no_roots": all_completions_no_roots,
            "factor_count": len(factors),
            "jobs": args.jobs,
            "elapsed_seconds": round(time.time() - started_at, 3),
            "fixed_ranges": compact_ranges(fixed_ranges),
            "base_selected_ranges": compact_ranges(list(args.base_selected_p_range)),
        },
        "variants": variant_rows,
        "factors": factors,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
