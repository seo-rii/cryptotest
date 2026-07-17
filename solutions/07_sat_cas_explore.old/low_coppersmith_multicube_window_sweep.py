#!/usr/bin/env python3
"""Compare low-Coppersmith single-window drops across several low cubes."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from sat_cas_core import FixedRange, parse_fixed_range


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--base-selected-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--variant-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--drop-window", action="append", default=[])
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--max-completions", type=int, default=4)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--child-jobs", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.base_selected_p_range:
        raise SystemExit("--base-selected-p-range is required")
    if not args.variant_p_range:
        raise SystemExit("--variant-p-range is required")
    if not args.drop_window:
        raise SystemExit("--drop-window is required")
    if args.low_bits <= 0 or args.low_bits > 1024:
        raise SystemExit("--low-bits must be in 1..1024")
    if args.max_completions < 1:
        raise SystemExit("--max-completions must be positive")
    if args.jobs < 1 or args.child_jobs < 1:
        raise SystemExit("--jobs and --child-jobs must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")

    started_at = time.monotonic()
    here = Path(__file__).resolve().parent
    sweep_script = here / "low_coppersmith_window_sweep.py"
    rows: list[dict[str, Any]] = []
    future_to_variant: dict[concurrent.futures.Future[subprocess.CompletedProcess[str]], FixedRange] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for variant in args.variant_p_range:
            selected_bit_values: dict[int, int] = {}
            for item in args.base_selected_p_range:
                if item.start < 0 or item.width <= 0 or item.start + item.width > args.low_bits:
                    raise SystemExit("--base-selected-p-range must be inside --low-bits")
                for offset in range(item.width):
                    selected_bit_values[item.start + offset] = (item.value >> offset) & 1
            if variant.start < 0 or variant.width <= 0 or variant.start + variant.width > args.low_bits:
                raise SystemExit("--variant-p-range must be inside --low-bits")
            for offset in range(variant.width):
                selected_bit_values[variant.start + offset] = (variant.value >> offset) & 1

            compacted_selected: list[FixedRange] = []
            ordered_bits = sorted(selected_bit_values)
            if ordered_bits:
                start = ordered_bits[0]
                width = 1
                value = selected_bit_values[start]
                previous_bit = start
                for bit in ordered_bits[1:]:
                    if bit == previous_bit + 1:
                        if selected_bit_values[bit]:
                            value |= 1 << width
                        width += 1
                        previous_bit = bit
                        continue
                    compacted_selected.append(FixedRange(start, width, value))
                    start = bit
                    width = 1
                    value = selected_bit_values[bit]
                    previous_bit = bit
                compacted_selected.append(FixedRange(start, width, value))

            command = [
                sys.executable,
                "-B",
                str(sweep_script),
                "--low-bits",
                str(args.low_bits),
                "--max-completions",
                str(args.max_completions),
                "--epsilon",
                str(args.epsilon),
                "--min-hard-margin-bits",
                str(args.min_hard_margin_bits),
                "--jobs",
                str(args.child_jobs),
                "--timeout-seconds",
                str(args.timeout_seconds),
                "--json",
            ]
            for fixed_range in args.fix_p_range:
                command.extend(
                    ["--fix-p-range", f"{fixed_range.start}:{fixed_range.width}:{hex(fixed_range.value)}"]
                )
            for selected_range in compacted_selected:
                command.extend(
                    [
                        "--selected-p-range",
                        f"{selected_range.start}:{selected_range.width}:{hex(selected_range.value)}",
                    ]
                )
            for drop_window in args.drop_window:
                command.extend(["--drop-window", drop_window])

            future = executor.submit(
                subprocess.run,
                command,
                cwd=here,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
                timeout=args.timeout_seconds + 10.0,
                check=False,
            )
            future_to_variant[future] = variant

        for future in concurrent.futures.as_completed(future_to_variant):
            variant = future_to_variant[future]
            row: dict[str, Any] = {
                "variant": {"start": variant.start, "width": variant.width, "value": variant.value},
                "variant_arg": f"{variant.start}:{variant.width}:{hex(variant.value)}",
                "timeout": False,
            }
            try:
                process = future.result()
            except subprocess.TimeoutExpired as exc:
                row.update(
                    {
                        "status": "timeout",
                        "timeout": True,
                        "stdout_tail": (exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else "",
                        "stderr_tail": (exc.stderr or "")[-1000:] if isinstance(exc.stderr, str) else "",
                    }
                )
                rows.append(row)
                continue

            row["returncode"] = process.returncode
            if process.returncode != 0:
                row.update(
                    {
                        "status": "process_error",
                        "stdout_tail": process.stdout[-1000:],
                        "stderr_tail": process.stderr[-1000:],
                    }
                )
                rows.append(row)
                continue
            try:
                payload = json.loads(process.stdout.strip())
            except json.JSONDecodeError:
                row.update(
                    {
                        "status": "json_parse_error",
                        "stdout_tail": process.stdout[-1000:],
                        "stderr_tail": process.stderr[-1000:],
                    }
                )
                rows.append(row)
                continue

            result_rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
            row.update(
                {
                    "status": "ok",
                    "summary": payload.get("summary", {}),
                    "windows": [
                        {
                            "drop_window": item.get("drop_window"),
                            "status": item.get("status"),
                            "all_completions_no_roots": item.get("all_completions_no_roots"),
                            "completion_count": item.get("completion_count"),
                            "status_counts": item.get("status_counts"),
                            "remaining_literal_count_if_dropped": item.get(
                                "remaining_literal_count_if_dropped"
                            ),
                            "factors": item.get("factors", []),
                        }
                        for item in result_rows
                        if isinstance(item, dict)
                    ],
                    "stderr_tail": process.stderr[-1000:],
                }
            )
            rows.append(row)

    rows.sort(key=lambda item: (int(item.get("variant", {}).get("start", 0)), int(item.get("variant", {}).get("value", 0))))
    window_totals: dict[str, dict[str, int]] = {}
    factored_variant_count = 0
    for row in rows:
        for item in row.get("windows", []):
            drop_window = item.get("drop_window")
            if not isinstance(drop_window, dict):
                continue
            key = f"{drop_window.get('start')}:{drop_window.get('width')}"
            totals = window_totals.setdefault(key, {"tested": 0, "droppable": 0, "factored": 0})
            totals["tested"] += 1
            if item.get("all_completions_no_roots"):
                totals["droppable"] += 1
            if item.get("factors"):
                totals["factored"] += 1
                factored_variant_count += 1

    summary = {
        "event": "low_coppersmith_multicube_window_sweep",
        "variant_count": len(args.variant_p_range),
        "row_count": len(rows),
        "drop_window_count": len(args.drop_window),
        "jobs": args.jobs,
        "child_jobs": args.child_jobs,
        "low_bits": args.low_bits,
        "epsilon": args.epsilon,
        "min_hard_margin_bits": args.min_hard_margin_bits,
        "max_completions": args.max_completions,
        "ok_count": sum(1 for row in rows if row.get("status") == "ok"),
        "timeout_count": sum(1 for row in rows if row.get("timeout")),
        "factored_variant_count": factored_variant_count,
        "window_totals": window_totals,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }
    payload = {"summary": summary, "rows": rows}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if summary["ok_count"] == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
