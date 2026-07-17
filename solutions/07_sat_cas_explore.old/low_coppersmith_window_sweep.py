#!/usr/bin/env python3
"""Parallel wrapper for low-Coppersmith no-good window minimization."""

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

from sat_cas_core import parse_fixed_range


HERE = Path(__file__).resolve().parent
MINIMIZER = HERE / "low_coppersmith_clause_minimize.py"


def parse_drop_window(text: str) -> tuple[int, int]:
    try:
        start_text, width_text = text.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    if start < 0 or width <= 0:
        raise argparse.ArgumentTypeError("drop window must have nonnegative start and positive width")
    return start, width


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--selected-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--drop-window", action="append", default=[], type=parse_drop_window)
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--max-completions", type=int, default=16)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.selected_p_range:
        raise SystemExit("--selected-p-range is required")
    if not args.drop_window:
        raise SystemExit("--drop-window is required")
    if args.low_bits <= 0 or args.low_bits > 1024:
        raise SystemExit("--low-bits must be in 1..1024")
    if args.max_completions < 1:
        raise SystemExit("--max-completions must be positive")
    if args.jobs < 1:
        raise SystemExit("--jobs must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")
    return args


def fixed_range_arg(item: Any) -> str:
    return f"{item.start}:{item.width}:{hex(item.value)}"


def extract_json(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def run_window(args: argparse.Namespace, window: tuple[int, int]) -> dict[str, Any]:
    start, width = window
    command = [
        sys.executable,
        "-B",
        str(MINIMIZER),
        "--low-bits",
        str(args.low_bits),
        "--max-completions",
        str(args.max_completions),
        "--epsilon",
        str(args.epsilon),
        "--min-hard-margin-bits",
        str(args.min_hard_margin_bits),
        "--drop-window",
        f"{start}:{width}",
        "--json",
    ]
    for fixed_range in args.fix_p_range:
        command.extend(["--fix-p-range", fixed_range_arg(fixed_range)])
    for selected_range in args.selected_p_range:
        command.extend(["--selected-p-range", fixed_range_arg(selected_range)])

    started_at = time.monotonic()
    try:
        process = subprocess.run(
            command,
            cwd=HERE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            timeout=args.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "drop_window": {"start": start, "width": width},
            "status": "timeout",
            "timeout": True,
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "timeout_seconds": args.timeout_seconds,
            "stdout_tail": (exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-1000:] if isinstance(exc.stderr, str) else "",
            "command": command,
        }

    row: dict[str, Any] = {
        "drop_window": {"start": start, "width": width},
        "status": "process_error" if process.returncode else "json_parse_error",
        "timeout": False,
        "returncode": process.returncode,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "stdout_tail": process.stdout[-1000:],
        "stderr_tail": process.stderr[-1000:],
        "command": command,
    }
    if process.returncode != 0:
        return row

    payload = extract_json(process.stdout)
    if payload is None:
        return row

    result_rows = payload.get("rows") or []
    result = result_rows[0] if result_rows and isinstance(result_rows[0], dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    row.update(
        {
            "status": result.get("status", "missing_result"),
            "baseline_status": summary.get("baseline_status"),
            "baseline_hard_clause_eligible": summary.get("baseline_hard_clause_eligible"),
            "selected_literal_count": summary.get("selected_literal_count"),
            "all_completions_no_roots": result.get("all_completions_no_roots", False),
            "completion_count": result.get("completion_count"),
            "status_counts": result.get("status_counts", {}),
            "hard_eligible_completion_count": result.get("hard_eligible_completion_count"),
            "dropped_literal_count": result.get("dropped_literal_count"),
            "remaining_literal_count_if_dropped": result.get("remaining_literal_count_if_dropped"),
            "factors": result.get("factors", []),
            "stdout_tail": "",
            "stderr_tail": process.stderr[-1000:],
        }
    )
    return row


def rank_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(
        key=lambda row: (
            0 if row.get("all_completions_no_roots") else 1,
            int(row.get("remaining_literal_count_if_dropped") or 1_000_000),
            int(row.get("drop_window", {}).get("start") or 0),
            int(row.get("drop_window", {}).get("width") or 0),
        )
    )
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def main() -> int:
    args = parse_args()
    started_at = time.monotonic()
    windows = list(dict.fromkeys(args.drop_window))
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(run_window, args, window) for window in windows]
        rows = [future.result() for future in concurrent.futures.as_completed(futures)]
    rows = rank_rows(rows)
    summary = {
        "event": "low_coppersmith_window_sweep",
        "window_count": len(windows),
        "row_count": len(rows),
        "jobs": args.jobs,
        "low_bits": args.low_bits,
        "epsilon": args.epsilon,
        "min_hard_margin_bits": args.min_hard_margin_bits,
        "max_completions": args.max_completions,
        "timeout_seconds": args.timeout_seconds,
        "droppable_window_count": sum(1 for row in rows if row.get("all_completions_no_roots")),
        "timeout_count": sum(1 for row in rows if row.get("timeout")),
        "error_count": sum(
            1
            for row in rows
            if row.get("status") in {"process_error", "json_parse_error", "missing_result"}
        ),
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
    }
    payload = {"summary": summary, "rows": rows}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "window sweep "
            f"windows={summary['window_count']} "
            f"droppable={summary['droppable_window_count']} "
            f"timeouts={summary['timeout_count']} "
            f"errors={summary['error_count']} "
            f"elapsed={summary['elapsed_seconds']}s"
        )
        for row in rows:
            window = row["drop_window"]
            print(
                f"{window['start']}:{window['width']} "
                f"status={row.get('status')} "
                f"all_no_roots={row.get('all_completions_no_roots')} "
                f"remaining={row.get('remaining_literal_count_if_dropped')} "
                f"counts={row.get('status_counts')}"
            )
    return 0 if summary["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
