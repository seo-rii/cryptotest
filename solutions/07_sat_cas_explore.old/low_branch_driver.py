#!/usr/bin/env python3
"""Enumerate low-side p assignments until the low Coppersmith oracle triggers."""

from __future__ import annotations

import argparse
import json

from low_coppersmith_oracle import run_low_coppersmith
from sat_cas_core import FixedRange, load_instance, parse_fixed_range


LOW_RUNS = [
    (150, 4, "x0"),
    (210, 39, "x1"),
    (265, 84, "x2"),
    (362, 78, "x3"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--default-zero-low-runs", action="store_true")
    parser.add_argument("--run-coppersmith", action="store_true")
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.low_bits <= 0:
        raise SystemExit("--low-bits must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")

    instance = load_instance()
    fixed_ranges: list[FixedRange] = list(args.fix_p_range)
    if args.default_zero_low_runs:
        covered = {item.start for item in fixed_ranges}
        for start, width, _name in LOW_RUNS:
            if start not in covered:
                fixed_ranges.append(FixedRange(start, width, 0))
    p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)
    low_known = 0
    for bit in range(instance.p_bits):
        if ((p_mask >> bit) & 1) == 0:
            break
        low_known += 1
    report: dict[str, object] = {
        "low_known_bits": low_known,
        "trigger_ready_600": low_known >= 600,
        "fixed_ranges": [
            {"start": item.start, "width": item.width, "value": item.value}
            for item in fixed_ranges
        ],
    }
    if args.run_coppersmith:
        report["low_coppersmith"] = run_low_coppersmith(
            p_known=p_known,
            p_mask=p_mask,
            n=instance.n,
            low_bits=args.low_bits,
            p_bits=instance.p_bits,
            epsilon=args.epsilon,
            min_hard_margin_bits=args.min_hard_margin_bits,
        )
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
