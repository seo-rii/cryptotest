#!/usr/bin/env python3
"""Subprocess-parallel sweep of greedy low-Coppersmith union-drop orders."""

from __future__ import annotations

import argparse
import concurrent.futures
import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from sat_cas_core import parse_fixed_range


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--selected-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--candidate-window", action="append", default=[], help="START:WIDTH")
    parser.add_argument("--order-size", type=int, default=3)
    parser.add_argument("--max-orders", type=int, default=24)
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--max-union-completions", type=int, default=64)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.selected_p_range:
        raise SystemExit("--selected-p-range is required")
    if not args.candidate_window:
        raise SystemExit("--candidate-window is required")
    if args.order_size < 1:
        raise SystemExit("--order-size must be positive")
    if args.max_orders < 1:
        raise SystemExit("--max-orders must be positive")
    if args.low_bits <= 0 or args.low_bits > 1024:
        raise SystemExit("--low-bits must be in 1..1024")
    if args.max_union_completions < 1:
        raise SystemExit("--max-union-completions must be positive")
    if args.jobs < 1:
        raise SystemExit("--jobs must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")

    started_at = time.monotonic()
    here = Path(__file__).resolve().parent
    greedy_script = here / "low_coppersmith_greedy_minimize.py"
    windows = list(dict.fromkeys(args.candidate_window))
    if args.order_size > len(windows):
        raise SystemExit("--order-size cannot exceed candidate-window count")

    orders = list(itertools.permutations(windows, args.order_size))[: args.max_orders]
    rows: list[dict[str, Any]] = []
    future_to_order: dict[concurrent.futures.Future[subprocess.CompletedProcess[str]], tuple[str, ...]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for order in orders:
            command = [
                sys.executable,
                "-B",
                str(greedy_script),
                "--low-bits",
                str(args.low_bits),
                "--max-union-completions",
                str(args.max_union_completions),
                "--epsilon",
                str(args.epsilon),
                "--min-hard-margin-bits",
                str(args.min_hard_margin_bits),
                "--json",
            ]
            for fixed_range in args.fix_p_range:
                command.extend(
                    ["--fix-p-range", f"{fixed_range.start}:{fixed_range.width}:{hex(fixed_range.value)}"]
                )
            for selected_range in args.selected_p_range:
                command.extend(
                    [
                        "--selected-p-range",
                        f"{selected_range.start}:{selected_range.width}:{hex(selected_range.value)}",
                    ]
                )
            for window in order:
                command.extend(["--candidate-window", window])
            future = executor.submit(
                subprocess.run,
                command,
                cwd=here,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                capture_output=True,
                timeout=args.timeout_seconds,
                check=False,
            )
            future_to_order[future] = order

        for future in concurrent.futures.as_completed(future_to_order):
            order = future_to_order[future]
            row: dict[str, Any] = {
                "order": list(order),
                "order_key": ",".join(order),
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

            summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
            result_rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
            factors: list[object] = []
            status_by_window: list[dict[str, object]] = []
            for result_row in result_rows:
                if not isinstance(result_row, dict):
                    continue
                factors.extend(result_row.get("factors") or [])
                status_by_window.append(
                    {
                        "window": result_row.get("candidate_window"),
                        "status": result_row.get("status"),
                        "completion_count": result_row.get("completion_count"),
                        "status_counts": result_row.get("status_counts"),
                    }
                )
            row.update(
                {
                    "status": "ok",
                    "accepted_window_count": summary.get("accepted_window_count"),
                    "dropped_literal_count": summary.get("dropped_literal_count"),
                    "remaining_literal_count": summary.get("remaining_literal_count"),
                    "dropped_bits": summary.get("dropped_bits", []),
                    "baseline_status": summary.get("baseline_status"),
                    "baseline_hard_clause_eligible": summary.get("baseline_hard_clause_eligible"),
                    "low_coppersmith_calls": summary.get("low_coppersmith_calls"),
                    "low_coppersmith_cache_hits": summary.get("low_coppersmith_cache_hits"),
                    "elapsed_seconds": summary.get("elapsed_seconds"),
                    "factors": factors,
                    "window_status": status_by_window,
                    "stderr_tail": process.stderr[-1000:],
                }
            )
            rows.append(row)

    rows.sort(
        key=lambda row: (
            -int(row.get("dropped_literal_count") or 0),
            int(row.get("remaining_literal_count") or 1_000_000),
            int(row.get("low_coppersmith_calls") or 1_000_000),
            str(row.get("order_key")),
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    summary = {
        "event": "low_coppersmith_union_order_sweep",
        "candidate_window_count": len(windows),
        "order_count": len(orders),
        "row_count": len(rows),
        "order_size": args.order_size,
        "jobs": args.jobs,
        "low_bits": args.low_bits,
        "epsilon": args.epsilon,
        "min_hard_margin_bits": args.min_hard_margin_bits,
        "max_union_completions": args.max_union_completions,
        "timeout_seconds": args.timeout_seconds,
        "ok_count": sum(1 for row in rows if row.get("status") == "ok"),
        "timeout_count": sum(1 for row in rows if row.get("timeout")),
        "max_dropped_literal_count": max((int(row.get("dropped_literal_count") or 0) for row in rows), default=0),
        "min_remaining_literal_count": min(
            (int(row.get("remaining_literal_count") or 1_000_000) for row in rows),
            default=None,
        ),
        "factored_order_count": sum(1 for row in rows if row.get("factors")),
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
