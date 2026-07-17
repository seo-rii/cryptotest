#!/usr/bin/env python3
"""Rank bounded full contiguous-low samples by cheap exact signals.

This explores non-zero x0+x1+x2+x3 low samples without invoking Sage by
default.  The optional oracle path mirrors low_contiguous_sample_probe.py, but
non-oracle rows only report the literal count that would be available if an
oracle later returned no roots.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from itertools import product
from pathlib import Path

from low_contiguous_sample_probe import DEFAULT_X6, DEFAULT_X7, LOW_RANGES
from low_coppersmith_oracle import low_coppersmith_bound_report
from q_interval_sweep import compact_ranges
from sat_cas_core import FixedRange, all_bits_known, derive_q_known_bits, load_instance, z3_product_prefix_status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x0-values", default="0,1", help="CSV integer values for x0 range 150:4")
    parser.add_argument("--x1-values", default="0,1", help="CSV integer values for x1 range 210:39")
    parser.add_argument("--x2-values", default="0,1", help="CSV integer values for x2 range 265:84")
    parser.add_argument("--x3-values", default="0,1", help="CSV integer values for x3 range 362:78")
    parser.add_argument("--max-candidates", type=int, default=16)
    parser.add_argument("--low-bits", default="513,600,608,616", help="CSV low-Coppersmith thresholds")
    parser.add_argument("--check-bits", default="320,384", help="CSV product-prefix checks")
    parser.add_argument("--timeout-ms", type=int, default=100)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--run-oracle", action="store_true", help="invoke low_coppersmith_oracle.py for ready rows")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.max_candidates < 0:
        raise SystemExit("--max-candidates must be non-negative")
    if args.timeout_ms < 1:
        raise SystemExit("--timeout-ms must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")

    parsed_values: dict[str, list[int]] = {}
    for name, text in [
        ("x0", args.x0_values),
        ("x1", args.x1_values),
        ("x2", args.x2_values),
        ("x3", args.x3_values),
    ]:
        values: list[int] = []
        start, width = LOW_RANGES[name]
        for part in text.split(","):
            stripped = part.strip()
            if not stripped:
                continue
            value = int(stripped, 0)
            if value < 0 or value >= (1 << width):
                raise SystemExit(f"--{name}-values entry {value!r} does not fit {start}:{width}")
            values.append(value)
        if not values:
            raise SystemExit(f"--{name}-values must contain at least one integer")
        parsed_values[name] = values

    low_bits_values: list[int] = []
    for part in args.low_bits.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        value = int(stripped, 0)
        if value <= 0:
            raise SystemExit("--low-bits entries must be positive")
        low_bits_values.append(value)
    if not low_bits_values:
        raise SystemExit("--low-bits must contain at least one threshold")

    check_bits_values: list[int] = []
    for part in args.check_bits.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        value = int(stripped, 0)
        if value <= 0:
            raise SystemExit("--check-bits entries must be positive")
        check_bits_values.append(value)

    started_at = time.time()
    instance = load_instance()
    fixed_high = [DEFAULT_X6, DEFAULT_X7]
    candidates: list[dict[str, object]] = []
    total_possible = (
        len(parsed_values["x0"])
        * len(parsed_values["x1"])
        * len(parsed_values["x2"])
        * len(parsed_values["x3"])
    )

    for index, values in enumerate(
        product(
            parsed_values["x0"],
            parsed_values["x1"],
            parsed_values["x2"],
            parsed_values["x3"],
        ),
        start=1,
    ):
        if len(candidates) >= args.max_candidates:
            break

        low_fixed = [
            FixedRange(LOW_RANGES[name][0], LOW_RANGES[name][1], value)
            for name, value in zip(["x0", "x1", "x2", "x3"], values, strict=True)
        ]
        all_fixed = fixed_high + low_fixed
        p_known, p_mask = instance.apply_fixed_ranges(all_fixed)
        q_known = derive_q_known_bits(instance, p_known, p_mask)

        p_contiguous_low_bits = 0
        while p_contiguous_low_bits < instance.p_bits and ((p_mask >> p_contiguous_low_bits) & 1):
            p_contiguous_low_bits += 1

        hard_clause_literal_count_if_no_roots: dict[str, int] = {}
        low_coppersmith: dict[str, object] = {}
        for low_bits in low_bits_values:
            trigger_bits_assigned = all_bits_known(p_mask, 0, low_bits)
            bound_report = low_coppersmith_bound_report(
                n=instance.n,
                low_bits=low_bits,
                p_bits=instance.p_bits,
                epsilon=args.epsilon,
                min_hard_margin_bits=args.min_hard_margin_bits,
            )
            selected_low_literal_count = sum(
                min(item.start + item.width, low_bits) - item.start
                for item in low_fixed
                if item.start < low_bits
            )
            hard_clause_literal_count_if_no_roots[str(low_bits)] = selected_low_literal_count
            row: dict[str, object] = {
                "low_bits": low_bits,
                "trigger_bits_assigned": trigger_bits_assigned,
                **bound_report,
                "sound_trigger_ready": trigger_bits_assigned
                and bool(bound_report["hard_clause_bound_eligible"]),
                "selected_low_literal_count": selected_low_literal_count,
                "assigned_low_bit_count": (p_mask & ((1 << low_bits) - 1)).bit_count(),
                "hard_clause_literal_count_if_no_roots": selected_low_literal_count,
                "hard_clause_eligible": False,
            }
            if args.run_oracle and trigger_bits_assigned:
                command = [
                    sys.executable,
                    str(Path(__file__).with_name("low_coppersmith_oracle.py")),
                    "--low-bits",
                    str(low_bits),
                    "--epsilon",
                    str(args.epsilon),
                    "--min-hard-margin-bits",
                    str(args.min_hard_margin_bits),
                    "--json",
                ]
                for fixed_range in all_fixed:
                    command.extend(
                        [
                            "--fix-p-range",
                            f"{fixed_range.start}:{fixed_range.width}:{hex(fixed_range.value)}",
                        ]
                    )
                try:
                    completed = subprocess.run(
                        command,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=args.timeout_ms / 1000.0,
                    )
                    row["oracle_returncode"] = completed.returncode
                    if completed.returncode == 0:
                        oracle_report = json.loads(completed.stdout)
                        oracle_status = str(oracle_report.get("status"))
                        row["oracle_status"] = oracle_status
                        row["oracle_roots_returned"] = oracle_report.get("roots_returned")
                        row["oracle_factors"] = oracle_report.get("factors", [])
                        row["oracle_reason"] = oracle_report.get("reason")
                        row["hard_clause_eligible"] = oracle_report.get("hard_clause_eligible") is True
                    else:
                        row["oracle_status"] = "error"
                        row["oracle_stderr"] = completed.stderr.strip()[-500:]
                except subprocess.TimeoutExpired:
                    row["oracle_status"] = "timeout"
                    row["oracle_timeout_ms"] = args.timeout_ms
            elif args.run_oracle:
                row["oracle_status"] = "not_triggered"
            else:
                row["oracle_status"] = "not_run"
            low_coppersmith[str(low_bits)] = row

        product_prefix_checks: dict[str, object] = {}
        sat_product_prefix_check_count = 0
        for check_bits in check_bits_values:
            status, details = z3_product_prefix_status(
                instance=instance,
                p_known=p_known,
                p_mask=p_mask,
                check_bits=check_bits,
                timeout_ms=args.timeout_ms,
            )
            if status == "sat":
                sat_product_prefix_check_count += 1
            product_prefix_checks[str(check_bits)] = {"status": status, **details}

        compact_low_ranges = compact_ranges(low_fixed)
        compact_full_ranges = compact_ranges(all_fixed)
        candidates.append(
            {
                "event": "candidate",
                "enumeration_index": index,
                "low_values": {
                    "x0": values[0],
                    "x1": values[1],
                    "x2": values[2],
                    "x3": values[3],
                },
                "fixed_high_ranges": compact_ranges(fixed_high),
                "low_fixed_ranges": compact_low_ranges,
                "fixed_ranges": compact_full_ranges,
                "p_contiguous_low_bits": p_contiguous_low_bits,
                "q_low_bits": q_known.low_bits,
                "q_prefix_bits": q_known.prefix_bits,
                "q_prefix_start": q_known.prefix_start,
                "q_known_bits": q_known.mask.bit_count(),
                "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                "sat_product_prefix_check_count": sat_product_prefix_check_count,
                "hard_clause_literal_count_if_no_roots": hard_clause_literal_count_if_no_roots,
                "low_coppersmith": low_coppersmith,
                "product_prefix_checks": product_prefix_checks,
            }
        )

    candidates.sort(
        key=lambda row: (
            -int(row["q_low_bits"]),
            -int(row["q_known_bits"]),
            -int(row["sat_product_prefix_check_count"]),
            tuple(
                (int(item["start"]), int(item["width"]), int(item["value"]))
                for item in row["fixed_ranges"]  # type: ignore[index]
            ),
        )
    )
    for rank, candidate in enumerate(candidates, start=1):
        candidate["rank"] = rank

    summary = {
        "event": "summary",
        "total_possible_candidates": total_possible,
        "emitted_candidates": len(candidates),
        "max_candidates": args.max_candidates,
        "rank_order": ["q_low_bits_desc", "q_known_bits_desc", "sat_product_prefix_check_count_desc", "fixed_ranges_asc"],
        "low_bits": low_bits_values,
        "check_bits": check_bits_values,
        "timeout_ms": args.timeout_ms,
        "epsilon": args.epsilon,
        "min_hard_margin_bits": args.min_hard_margin_bits,
        "run_oracle": args.run_oracle,
        "fixed_high_ranges": compact_ranges(fixed_high),
        "low_ranges": {
            name: {"start": start, "width": width}
            for name, (start, width) in LOW_RANGES.items()
        },
        "value_counts": {name: len(values) for name, values in parsed_values.items()},
        "elapsed_seconds": round(time.time() - started_at, 3),
    }
    payload = {"event": "low_contiguous_rank_batch", "summary": summary, "candidates": candidates}

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "low contiguous rank batch "
            f"candidates={summary['emitted_candidates']}/{summary['total_possible_candidates']} "
            f"oracle={summary['run_oracle']}"
        )
        for candidate in candidates:
            print(
                f"rank={candidate['rank']} "
                f"enum={candidate['enumeration_index']} "
                f"x={candidate['low_values']} "
                f"q_low={candidate['q_low_bits']} "
                f"q_known={candidate['q_known_bits']} "
                f"sat_prefix={candidate['sat_product_prefix_check_count']} "
                f"ranges={candidate['low_fixed_ranges']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
