#!/usr/bin/env python3
"""Audit low-Coppersmith trigger thresholds and learned literal counts."""

from __future__ import annotations

import argparse
import json
import time

from low_coppersmith_oracle import low_coppersmith_bound_report, run_low_coppersmith
from q_interval_sweep import compact_ranges, parse_cube_ranges
from q_prefix_growth_search import iter_limited_cubes
from sat_cas_core import FixedRange, all_bits_known, load_instance, parse_fixed_range


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--low-bits-values",
        default="513,554,560,600,608,616",
        help="comma-separated low-bit trigger thresholds to audit",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument(
        "--low-ranges",
        default="150:4,210:39,265:84,362:78",
        help="comma-separated START:WIDTH selected low ranges to enumerate",
    )
    parser.add_argument("--max-low-cubes", type=int, default=1)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--run-oracle", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    low_bits_values: list[int] = []
    for part in args.low_bits_values.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        value = int(stripped, 0)
        if value <= 0:
            raise SystemExit("--low-bits-values entries must be positive")
        low_bits_values.append(value)
    if not low_bits_values:
        raise SystemExit("--low-bits-values must contain at least one threshold")
    if args.max_low_cubes < 1:
        raise SystemExit("--max-low-cubes must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")

    started_at = time.time()
    instance = load_instance()
    base_ranges: list[FixedRange] = list(args.fix_p_range)
    low_ranges = parse_cube_ranges(args.low_ranges)
    max_low_bits = max(low_bits_values)
    if max_low_bits > instance.p_bits:
        raise SystemExit(f"low-bits threshold exceeds p bit length {instance.p_bits}")

    items: list[dict[str, object]] = []
    for cube_index, low_fixed in enumerate(
        iter_limited_cubes(low_ranges, args.max_low_cubes),
        start=1,
    ):
        p_known, p_mask = instance.apply_fixed_ranges(base_ranges + low_fixed)
        for low_bits in low_bits_values:
            low_mask = (1 << low_bits) - 1
            selected_low_literal_count = sum(
                min(item.start + item.width, low_bits) - item.start
                for item in low_fixed
                if item.start < low_bits
            )
            assigned_low_bit_count = (p_mask & low_mask).bit_count()
            trigger_bits_assigned = all_bits_known(p_mask, 0, low_bits)
            bound_report = low_coppersmith_bound_report(
                n=instance.n,
                low_bits=low_bits,
                p_bits=instance.p_bits,
                epsilon=args.epsilon,
                min_hard_margin_bits=args.min_hard_margin_bits,
            )
            item: dict[str, object] = {
                "event": "threshold",
                "cube_index": cube_index,
                "low_bits": low_bits,
                "trigger_bits_assigned": trigger_bits_assigned,
                **bound_report,
                "effective_margin_positive": float(bound_report["effective_margin_bits"]) > 0,
                "selected_low_literal_count": selected_low_literal_count,
                "assigned_low_bit_count": assigned_low_bit_count,
                "base_fixed_ranges": compact_ranges(base_ranges),
                "low_fixed_ranges": compact_ranges(low_fixed),
                "hard_clause_eligible": False,
            }
            if args.run_oracle:
                oracle_report = run_low_coppersmith(
                    p_known=p_known,
                    p_mask=p_mask,
                    n=instance.n,
                    low_bits=low_bits,
                    p_bits=instance.p_bits,
                    epsilon=args.epsilon,
                    min_hard_margin_bits=args.min_hard_margin_bits,
                )
                oracle_status = str(oracle_report.get("status"))
                item["oracle_status"] = oracle_status
                item["oracle_roots_returned"] = oracle_report.get("roots_returned")
                item["oracle_factors"] = oracle_report.get("factors", [])
                item["oracle_reason"] = oracle_report.get("reason")
                item["hard_clause_eligible"] = oracle_report.get("hard_clause_eligible") is True
            items.append(item)

    summary = {
        "event": "low_coppersmith_threshold_audit",
        "low_bits_values": low_bits_values,
        "fix_p_range": compact_ranges(base_ranges),
        "low_ranges": [{"start": item.start, "width": item.width} for item in low_ranges],
        "max_low_cubes": args.max_low_cubes,
        "epsilon": args.epsilon,
        "min_hard_margin_bits": args.min_hard_margin_bits,
        "run_oracle": args.run_oracle,
        "items": len(items),
        "elapsed_seconds": round(time.time() - started_at, 3),
    }
    payload = {"summary": summary, "items": items}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
        return 0

    print(
        "low Coppersmith threshold audit "
        f"cubes={summary['max_low_cubes']} "
        f"run_oracle={summary['run_oracle']}"
    )
    for item in items:
        status = item.get("oracle_status", "not_run")
        print(
            f"cube={item['cube_index']} "
            f"T={item['low_bits']} "
            f"assigned={item['trigger_bits_assigned']} "
            f"effective_margin={item['effective_margin_bits']} "
            f"bound_ok={item['hard_clause_bound_eligible']} "
            f"selected={item['selected_low_literal_count']} "
            f"assigned_bits={item['assigned_low_bit_count']} "
            f"oracle={status} "
            f"hard={item['hard_clause_eligible']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
