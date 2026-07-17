#!/usr/bin/env python3
"""Greedy, union-checked low-Coppersmith no-good minimization probe."""

from __future__ import annotations

import argparse
import json
import time

from low_coppersmith_oracle import run_low_coppersmith
from q_interval_sweep import compact_ranges
from sat_cas_core import FixedRange, all_bits_known, load_instance, parse_fixed_range


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--selected-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--candidate-window", action="append", default=[], help="START:WIDTH drop candidate")
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--max-union-completions", type=int, default=16)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.low_bits <= 0 or args.low_bits > 1024:
        raise SystemExit("--low-bits must be in 1..1024")
    if args.max_union_completions < 1:
        raise SystemExit("--max-union-completions must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")
    if not args.selected_p_range:
        raise SystemExit("--selected-p-range is required")
    if not args.candidate_window:
        raise SystemExit("--candidate-window is required")

    started_at = time.time()
    instance = load_instance()
    fixed_ranges: list[FixedRange] = list(args.fix_p_range)
    low_coppersmith_mask = (1 << args.low_bits) - 1
    low_coppersmith_cache: dict[tuple[int, int], dict[str, object]] = {}
    selected_ranges: list[FixedRange] = list(args.selected_p_range)
    selected_bit_values: dict[int, int] = {}
    for item in selected_ranges:
        if item.start < 0 or item.width <= 0 or item.start + item.width > args.low_bits:
            raise SystemExit("--selected-p-range must be inside --low-bits for this probe")
        for offset in range(item.width):
            bit = item.start + offset
            value = (item.value >> offset) & 1
            existing = selected_bit_values.get(bit)
            if existing is not None and existing != value:
                raise SystemExit(f"conflicting selected bit {bit}")
            selected_bit_values[bit] = value

    baseline_selected = [FixedRange(bit, 1, value) for bit, value in sorted(selected_bit_values.items())]
    baseline_known, baseline_mask = instance.apply_fixed_ranges(fixed_ranges + baseline_selected)
    baseline_cache_key = (baseline_known & low_coppersmith_mask, baseline_mask & low_coppersmith_mask)
    baseline_report = run_low_coppersmith(
        p_known=baseline_known,
        p_mask=baseline_mask,
        n=instance.n,
        low_bits=args.low_bits,
        p_bits=instance.p_bits,
        epsilon=args.epsilon,
        min_hard_margin_bits=args.min_hard_margin_bits,
    )
    low_coppersmith_cache[baseline_cache_key] = baseline_report

    dropped_bits: set[int] = set()
    rows = []
    low_coppersmith_calls = 1
    low_coppersmith_cache_hits = 0
    for raw_window in args.candidate_window:
        try:
            start_text, width_text = raw_window.split(":", 1)
        except ValueError as exc:
            raise SystemExit("--candidate-window must be START:WIDTH") from exc
        window_start = int(start_text, 0)
        window_width = int(width_text, 0)
        if window_start < 0 or window_width <= 0 or window_start + window_width > args.low_bits:
            raise SystemExit("--candidate-window must be inside --low-bits")

        candidate_bits = [
            bit
            for bit in range(window_start, window_start + window_width)
            if bit in selected_bit_values and bit not in dropped_bits
        ]
        if not candidate_bits:
            rows.append(
                {
                    "candidate_window": {"start": window_start, "width": window_width},
                    "status": "no_new_selected_literals_in_window",
                    "candidate_drop_literal_count": 0,
                    "dropped_literal_count_before": len(dropped_bits),
                    "dropped_literal_count_after": len(dropped_bits),
                }
            )
            continue

        proposed_dropped = dropped_bits | set(candidate_bits)
        completion_bits = sorted(proposed_dropped)
        completion_count = 1 << len(completion_bits)
        if completion_count > args.max_union_completions:
            rows.append(
                {
                    "candidate_window": {"start": window_start, "width": window_width},
                    "status": "skipped_union_too_many_completions",
                    "candidate_drop_literal_count": len(candidate_bits),
                    "dropped_literal_count_before": len(dropped_bits),
                    "proposed_dropped_literal_count": len(completion_bits),
                    "completion_count": completion_count,
                    "max_union_completions": args.max_union_completions,
                }
            )
            continue

        fixed_kept_bits = [
            FixedRange(bit, 1, value)
            for bit, value in sorted(selected_bit_values.items())
            if bit not in proposed_dropped
        ]
        status_counts: dict[str, int] = {}
        hard_eligible_completion_count = 0
        factors = []
        all_no_roots = True
        for completion_value in range(completion_count):
            completion_ranges = [
                FixedRange(bit, 1, (completion_value >> index) & 1)
                for index, bit in enumerate(completion_bits)
            ]
            completion_known, completion_mask = instance.apply_fixed_ranges(
                fixed_ranges + fixed_kept_bits + completion_ranges
            )
            if not all_bits_known(completion_mask, 0, args.low_bits):
                report = {"status": "not_triggered_after_completion"}
            else:
                completion_cache_key = (
                    completion_known & low_coppersmith_mask,
                    completion_mask & low_coppersmith_mask,
                )
                report = low_coppersmith_cache.get(completion_cache_key)
                if report is None:
                    low_coppersmith_calls += 1
                    report = run_low_coppersmith(
                        p_known=completion_known,
                        p_mask=completion_mask,
                        n=instance.n,
                        low_bits=args.low_bits,
                        p_bits=instance.p_bits,
                        epsilon=args.epsilon,
                        min_hard_margin_bits=args.min_hard_margin_bits,
                    )
                    low_coppersmith_cache[completion_cache_key] = report
                else:
                    low_coppersmith_cache_hits += 1
            status = str(report.get("status"))
            status_counts[status] = status_counts.get(status, 0) + 1
            if status == "no_roots" and report.get("hard_clause_eligible"):
                hard_eligible_completion_count += 1
            else:
                all_no_roots = False
            if report.get("factors"):
                factors.extend(report.get("factors") or [])

        if all_no_roots:
            dropped_bits = proposed_dropped
        rows.append(
            {
                "candidate_window": {"start": window_start, "width": window_width},
                "status": "droppable_sound_no_root" if all_no_roots else "not_droppable",
                "candidate_drop_literal_count": len(candidate_bits),
                "dropped_literal_count_before": len(completion_bits) - len(candidate_bits),
                "dropped_literal_count_after": len(dropped_bits),
                "remaining_literal_count_after": len(selected_bit_values) - len(dropped_bits),
                "completion_count": completion_count,
                "hard_eligible_completion_count": hard_eligible_completion_count,
                "status_counts": status_counts,
                "factors": factors,
                "low_coppersmith_cache_hits": low_coppersmith_cache_hits,
            }
        )

    payload = {
        "event": "low_coppersmith_greedy_minimize",
        "summary": {
            "low_bits": args.low_bits,
            "selected_literal_count": len(selected_bit_values),
            "dropped_literal_count": len(dropped_bits),
            "remaining_literal_count": len(selected_bit_values) - len(dropped_bits),
            "dropped_bits": sorted(dropped_bits),
            "candidate_window_count": len(args.candidate_window),
            "accepted_window_count": sum(1 for row in rows if row.get("status") == "droppable_sound_no_root"),
            "baseline_status": baseline_report.get("status"),
            "baseline_hard_clause_eligible": baseline_report.get("hard_clause_eligible"),
            "low_coppersmith_calls": low_coppersmith_calls,
            "low_coppersmith_cache_hits": low_coppersmith_cache_hits,
            "elapsed_seconds": round(time.time() - started_at, 3),
            "fixed_ranges": compact_ranges(fixed_ranges),
            "selected_ranges": compact_ranges(selected_ranges),
        },
        "baseline": baseline_report,
        "rows": rows,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
