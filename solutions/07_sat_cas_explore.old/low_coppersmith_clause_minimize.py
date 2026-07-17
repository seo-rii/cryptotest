#!/usr/bin/env python3
"""Exhaustive low-Coppersmith no-good literal minimization probe.

This script tries to shrink a sound low-Coppersmith no-good clause by dropping
small windows from a fully assigned low prefix.  A window is marked droppable
only when every completion of that window still returns a sound ``no_roots``
result.  Any other outcome is diagnostic only and must not become a learned
clause.
"""

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
    parser.add_argument(
        "--drop-window",
        action="append",
        default=[],
        help="START:WIDTH window to exhaustively vary while keeping other selected bits fixed",
    )
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--max-completions", type=int, default=16)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.low_bits <= 0 or args.low_bits > 1024:
        raise SystemExit("--low-bits must be in 1..1024")
    if args.max_completions < 1:
        raise SystemExit("--max-completions must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")
    if not args.selected_p_range:
        raise SystemExit("--selected-p-range is required")
    if not args.drop_window:
        raise SystemExit("--drop-window is required")

    instance = load_instance()
    selected_ranges: list[FixedRange] = list(args.selected_p_range)
    fixed_ranges: list[FixedRange] = list(args.fix_p_range)
    started_at = time.time()

    baseline_known, baseline_mask = instance.apply_fixed_ranges(fixed_ranges + selected_ranges)
    baseline_ready = all_bits_known(baseline_mask, 0, args.low_bits)
    baseline_report = run_low_coppersmith(
        p_known=baseline_known,
        p_mask=baseline_mask,
        n=instance.n,
        low_bits=args.low_bits,
        p_bits=instance.p_bits,
        epsilon=args.epsilon,
        min_hard_margin_bits=args.min_hard_margin_bits,
    )
    selected_literal_count = sum(
        max(0, min(item.start + item.width, args.low_bits) - item.start)
        for item in selected_ranges
        if item.start < args.low_bits
    )

    rows = []
    for raw_window in args.drop_window:
        try:
            start_text, width_text = raw_window.split(":", 1)
        except ValueError as exc:
            raise SystemExit("--drop-window must be START:WIDTH") from exc
        drop_start = int(start_text, 0)
        drop_width = int(width_text, 0)
        if drop_start < 0 or drop_width <= 0 or drop_start + drop_width > args.low_bits:
            raise SystemExit("--drop-window must be inside the low-bit oracle range")
        completion_count = 1 << drop_width
        if completion_count > args.max_completions:
            rows.append(
                {
                    "drop_window": {"start": drop_start, "width": drop_width},
                    "status": "skipped_too_many_completions",
                    "completion_count": completion_count,
                    "max_completions": args.max_completions,
                }
            )
            continue

        fixed_without_window: list[FixedRange] = []
        for item in selected_ranges:
            item_end = item.start + item.width
            drop_end = drop_start + drop_width
            overlap_start = max(item.start, drop_start)
            overlap_end = min(item_end, drop_end)
            if overlap_start >= overlap_end:
                fixed_without_window.append(item)
                continue
            before_width = overlap_start - item.start
            if before_width:
                before_value = item.value & ((1 << before_width) - 1)
                fixed_without_window.append(FixedRange(item.start, before_width, before_value))
            after_width = item_end - overlap_end
            if after_width:
                after_shift = overlap_end - item.start
                after_value = (item.value >> after_shift) & ((1 << after_width) - 1)
                fixed_without_window.append(FixedRange(overlap_end, after_width, after_value))

        status_counts: dict[str, int] = {}
        completions = []
        factors = []
        all_no_roots = True
        hard_eligible_count = 0
        for value in range(completion_count):
            completion_range = FixedRange(drop_start, drop_width, value)
            p_known, p_mask = instance.apply_fixed_ranges(
                fixed_ranges + fixed_without_window + [completion_range]
            )
            if not all_bits_known(p_mask, 0, args.low_bits):
                report = {"status": "not_triggered_after_completion"}
            else:
                report = run_low_coppersmith(
                    p_known=p_known,
                    p_mask=p_mask,
                    n=instance.n,
                    low_bits=args.low_bits,
                    p_bits=instance.p_bits,
                    epsilon=args.epsilon,
                    min_hard_margin_bits=args.min_hard_margin_bits,
                )
            status = str(report.get("status"))
            status_counts[status] = status_counts.get(status, 0) + 1
            if status != "no_roots" or not report.get("hard_clause_eligible"):
                all_no_roots = False
            else:
                hard_eligible_count += 1
            if report.get("factors"):
                factors.extend(report.get("factors") or [])
            completions.append(
                {
                    "value": value,
                    "value_hex": hex(value),
                    "status": status,
                    "roots_returned": report.get("roots_returned"),
                    "hard_clause_eligible": report.get("hard_clause_eligible"),
                    "factors": report.get("factors", []),
                }
            )

        dropped_literal_count = min(drop_start + drop_width, args.low_bits) - drop_start
        rows.append(
            {
                "drop_window": {"start": drop_start, "width": drop_width},
                "completion_count": completion_count,
                "status": "droppable_sound_no_root" if all_no_roots else "not_droppable",
                "all_completions_no_roots": all_no_roots,
                "status_counts": status_counts,
                "hard_eligible_completion_count": hard_eligible_count,
                "dropped_literal_count": dropped_literal_count,
                "remaining_literal_count_if_dropped": selected_literal_count - dropped_literal_count,
                "fixed_without_window": compact_ranges(fixed_without_window),
                "factors": factors,
                "completions": completions,
            }
        )

    payload = {
        "event": "low_coppersmith_clause_minimize",
        "summary": {
            "low_bits": args.low_bits,
            "baseline_ready": baseline_ready,
            "baseline_status": baseline_report.get("status"),
            "baseline_hard_clause_eligible": baseline_report.get("hard_clause_eligible"),
            "selected_literal_count": selected_literal_count,
            "fixed_ranges": compact_ranges(fixed_ranges),
            "selected_ranges": compact_ranges(selected_ranges),
            "drop_window_count": len(args.drop_window),
            "droppable_window_count": sum(1 for row in rows if row.get("all_completions_no_roots")),
            "elapsed_seconds": round(time.time() - started_at, 3),
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
