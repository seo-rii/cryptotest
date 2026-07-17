#!/usr/bin/env python3
"""Measure dynamic q-bit leakage from partial p assignments."""

from __future__ import annotations

import argparse
import json

from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cube-ranges", default="150:4,210:8,822:8,920:4")
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--max-cubes", type=int, default=64)
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    instance = load_instance()
    fixed_ranges: list[FixedRange] = list(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(fixed_ranges)
    selected_bits = []
    for item in args.cube_ranges.split(","):
        if not item.strip():
            continue
        start_text, width_text = item.split(":", 1)
        selected_bits.extend(range(int(start_text, 0), int(start_text, 0) + int(width_text, 0)))
    selected_bits = [bit for bit in sorted(dict.fromkeys(selected_bits)) if ((base_mask >> bit) & 1) == 0]
    if not selected_bits:
        raise SystemExit("selected cube ranges contain no unknown p bits")

    limit = min(args.max_cubes, 1 << len(selected_bits))
    totals = {
        "cubes": 0,
        "min_q_known": 10**9,
        "max_q_known": 0,
        "min_q_low": 10**9,
        "max_q_low": 0,
        "min_q_prefix": 10**9,
        "max_q_prefix": 0,
    }
    for cube in range(limit):
        cube_ranges = [
            FixedRange(bit, 1, (cube >> index) & 1)
            for index, bit in enumerate(selected_bits)
        ]
        p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges + cube_ranges)
        q_known = derive_q_known_bits(instance, p_known, p_mask)
        q_known_count = q_known.mask.bit_count()
        event = {
            "event": "dynamic_q",
            "cube": cube,
            "selected_bits": len(selected_bits),
            "q_known_bits": q_known_count,
            "q_low_bits": q_known.low_bits,
            "q_prefix_bits": q_known.prefix_bits,
            "q_prefix_start": q_known.prefix_start,
        }
        totals["cubes"] += 1
        totals["min_q_known"] = min(totals["min_q_known"], q_known_count)
        totals["max_q_known"] = max(totals["max_q_known"], q_known_count)
        totals["min_q_low"] = min(totals["min_q_low"], q_known.low_bits)
        totals["max_q_low"] = max(totals["max_q_low"], q_known.low_bits)
        totals["min_q_prefix"] = min(totals["min_q_prefix"], q_known.prefix_bits)
        totals["max_q_prefix"] = max(totals["max_q_prefix"], q_known.prefix_bits)
        if args.jsonl:
            print(json.dumps(event, sort_keys=True))
        else:
            print(
                f"cube={cube} q_known={q_known_count} "
                f"q_low={q_known.low_bits} q_prefix={q_known.prefix_bits}@{q_known.prefix_start}"
            )
    print(json.dumps({"event": "summary", **totals}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
