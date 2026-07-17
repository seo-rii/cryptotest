#!/usr/bin/env python3
"""Sample full contiguous-low assignments for the challenge 7 low-Coppersmith trigger.

The default branch fixes the recent high-side probe values x6=0x245521490bd
and x7=0.  By default this script does not invoke Sage: trigger readiness is a
sound precondition audit only.  When --run-oracle is supplied, the companion
low_coppersmith_oracle.py is executed in a subprocess with a timeout guard for
each sampled full-contiguous assignment/threshold.  Timeout, unavailable Sage,
or any other heuristic failure is reported as diagnostic only and is never
treated as a hard no-good clause.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from itertools import product
from pathlib import Path

from low_coppersmith_oracle import low_coppersmith_bound_report
from q_interval_sweep import compact_ranges
from sat_cas_core import (
    FixedRange,
    all_bits_known,
    derive_q_known_bits,
    load_instance,
    z3_product_prefix_status,
)


LOW_RANGES = {
    "x0": (150, 4),
    "x1": (210, 39),
    "x2": (265, 84),
    "x3": (362, 78),
}
DEFAULT_X6 = FixedRange(784, 46, 0x245521490BD)
DEFAULT_X7 = FixedRange(920, 4, 0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x0-values", default="0", help="CSV integer values for x0 range 150:4")
    parser.add_argument("--x1-values", default="0", help="CSV integer values for x1 range 210:39")
    parser.add_argument("--x2-values", default="0", help="CSV integer values for x2 range 265:84")
    parser.add_argument("--x3-values", default="0", help="CSV integer values for x3 range 362:78")
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--low-bits", default="513,554,560,600,608,616", help="CSV low-Coppersmith thresholds")
    parser.add_argument("--check-bits", default="320,384", help="CSV product-prefix checks")
    parser.add_argument("--timeout-ms", type=int, default=100)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--run-oracle", action="store_true")
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
        p_known, p_mask = instance.apply_fixed_ranges(fixed_high + low_fixed)
        q_known = derive_q_known_bits(instance, p_known, p_mask)

        p_contiguous_low_bits = 0
        while p_contiguous_low_bits < instance.p_bits and ((p_mask >> p_contiguous_low_bits) & 1):
            p_contiguous_low_bits += 1

        trigger_readiness: dict[str, object] = {}
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
            row: dict[str, object] = {
                "low_bits": low_bits,
                "trigger_bits_assigned": trigger_bits_assigned,
                **bound_report,
                "sound_trigger_ready": trigger_bits_assigned
                and bool(bound_report["hard_clause_bound_eligible"]),
                "selected_low_literal_count": selected_low_literal_count,
                "assigned_low_bit_count": (p_mask & ((1 << low_bits) - 1)).bit_count(),
                "hard_no_good_literals_if_oracle_no_roots": selected_low_literal_count,
                "hard_clause_eligible": False,
            }
            if args.run_oracle and trigger_bits_assigned:
                oracle_script = Path(__file__).with_name("low_coppersmith_oracle.py")
                command = [
                    sys.executable,
                    str(oracle_script),
                    "--low-bits",
                    str(low_bits),
                    "--epsilon",
                    str(args.epsilon),
                    "--min-hard-margin-bits",
                    str(args.min_hard_margin_bits),
                    "--json",
                ]
                for fixed_range in fixed_high + low_fixed:
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
            trigger_readiness[str(low_bits)] = row

        prefix_checks: dict[str, object] = {}
        for check_bits in check_bits_values:
            status, details = z3_product_prefix_status(
                instance=instance,
                p_known=p_known,
                p_mask=p_mask,
                check_bits=check_bits,
                timeout_ms=args.timeout_ms,
            )
            prefix_checks[str(check_bits)] = {"status": status, **details}

        candidates.append(
            {
                "event": "candidate",
                "index": index,
                "low_values": {
                    "x0": values[0],
                    "x1": values[1],
                    "x2": values[2],
                    "x3": values[3],
                },
                "fixed_high_ranges": compact_ranges(fixed_high),
                "low_fixed_ranges": compact_ranges(low_fixed),
                "p_contiguous_low_bits": p_contiguous_low_bits,
                "q_low_bits": q_known.low_bits,
                "q_prefix_bits": q_known.prefix_bits,
                "q_prefix_start": q_known.prefix_start,
                "q_known_bits": q_known.mask.bit_count(),
                "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                "low_coppersmith": trigger_readiness,
                "product_prefix_checks": prefix_checks,
            }
        )

    summary = {
        "event": "low_contiguous_sample_probe",
        "fixed_high_ranges": compact_ranges(fixed_high),
        "low_ranges": {
            name: {"start": start, "width": width}
            for name, (start, width) in LOW_RANGES.items()
        },
        "value_counts": {name: len(values) for name, values in parsed_values.items()},
        "total_possible_candidates": total_possible,
        "emitted_candidates": len(candidates),
        "max_candidates": args.max_candidates,
        "low_bits": low_bits_values,
        "check_bits": check_bits_values,
        "timeout_ms": args.timeout_ms,
        "epsilon": args.epsilon,
        "min_hard_margin_bits": args.min_hard_margin_bits,
        "run_oracle": args.run_oracle,
        "elapsed_seconds": round(time.time() - started_at, 3),
    }
    payload = {"event": "low_contiguous_sample_probe", "candidates": candidates, "summary": summary}

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "low contiguous sample probe "
            f"candidates={summary['emitted_candidates']}/{summary['total_possible_candidates']} "
            f"oracle={summary['run_oracle']}"
        )
        for candidate in candidates:
            trigger_bits = []
            for low_bits in low_bits_values:
                row = candidate["low_coppersmith"][str(low_bits)]  # type: ignore[index]
                ready = "ready" if row["sound_trigger_ready"] else "not-ready"  # type: ignore[index]
                hard = row["hard_no_good_literals_if_oracle_no_roots"]  # type: ignore[index]
                trigger_bits.append(f"T{low_bits}:{ready}:lits={hard}")
            print(
                f"candidate={candidate['index']} "
                f"x={candidate['low_values']} "
                f"p_contig={candidate['p_contiguous_low_bits']} "
                f"q_low={candidate['q_low_bits']} "
                f"q_prefix={candidate['q_prefix_bits']} "
                f"q_known={candidate['q_known_bits']} "
                + " ".join(trigger_bits)
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
