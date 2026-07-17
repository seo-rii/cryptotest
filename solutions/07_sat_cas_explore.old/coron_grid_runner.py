#!/usr/bin/env python3
"""Bounded subprocess grid runner for Coron reconstruction counts.

Runs coron_reconstruction_sweep.py one row at a time with per-row timeouts.
This keeps slow k/variant choices from hanging the whole grid.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s-values", default="45-46", help="comma/range list, e.g. 45-46,48")
    parser.add_argument("--k-values", default="5-6", help="comma/range list, e.g. 5-7")
    parser.add_argument("--variant", choices=("direct", "projected", "both"), default="direct")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--max-jobs", type=int, default=1)
    parser.add_argument("--output", type=Path, help="append JSONL row records to this path")
    parser.add_argument("--json", action="store_true", help="emit summary as JSON")
    args = parser.parse_args()

    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.max_jobs < 1:
        raise SystemExit("--max-jobs must be positive")

    s_values: list[int] = []
    k_values: list[int] = []
    for option_name, raw_value, target in (
        ("--s-values", args.s_values, s_values),
        ("--k-values", args.k_values, k_values),
    ):
        for raw_part in raw_value.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if "-" in part:
                lo_text, hi_text = part.split("-", 1)
                try:
                    lo_value = int(lo_text, 0)
                    hi_value = int(hi_text, 0)
                except ValueError as exc:
                    raise SystemExit(f"{option_name} contains a non-integer range: {part}") from exc
                if hi_value < lo_value:
                    raise SystemExit(f"{option_name} contains a descending range: {part}")
                target.extend(range(lo_value, hi_value + 1))
            else:
                try:
                    target.append(int(part, 0))
                except ValueError as exc:
                    raise SystemExit(f"{option_name} contains a non-integer value: {part}") from exc
        if not target:
            raise SystemExit(f"{option_name} must contain at least one integer")

    variants = ["direct", "projected"] if args.variant == "both" else [args.variant]
    script_dir = Path(__file__).resolve().parent
    sweep_script = script_dir / "coron_reconstruction_sweep.py"
    if not sweep_script.exists():
        raise SystemExit(f"missing sweep script: {sweep_script}")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    futures: dict[concurrent.futures.Future[subprocess.CompletedProcess[str]], dict[str, object]] = {}
    started_at = time.monotonic()
    rows: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_jobs) as executor:
        for s_value in s_values:
            for k_value in k_values:
                for variant in variants:
                    command = [
                        sys.executable,
                        "-B",
                        str(sweep_script),
                        "--s-values",
                        str(s_value),
                        "--k-values",
                        str(k_value),
                        "--variant",
                        variant,
                        "--max-rows",
                        "1",
                    ]
                    submitted_at = time.monotonic()
                    future = executor.submit(
                        subprocess.run,
                        command,
                        cwd=script_dir,
                        env=env,
                        text=True,
                        capture_output=True,
                        timeout=args.timeout_seconds,
                        check=False,
                    )
                    futures[future] = {
                        "event": "coron_grid_row",
                        "s": int(s_value),
                        "k": int(k_value),
                        "variant": variant,
                        "command": command,
                        "timeout_seconds": float(args.timeout_seconds),
                        "submitted_at_monotonic": submitted_at,
                    }

        for future in concurrent.futures.as_completed(futures):
            record = futures[future]
            elapsed = time.monotonic() - float(record.pop("submitted_at_monotonic"))
            record["elapsed_seconds"] = round(elapsed, 6)
            record["timeout"] = False
            try:
                proc = future.result()
            except subprocess.TimeoutExpired as exc:
                record["status"] = "timeout"
                record["timeout"] = True
                record["stdout_tail"] = (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else ""
                record["stderr_tail"] = (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else ""
            except Exception as exc:  # noqa: BLE001 - diagnostic runner should keep draining rows.
                record["status"] = "runner_error"
                record["error"] = f"{type(exc).__name__}: {exc}"
            else:
                record["returncode"] = int(proc.returncode)
                record["stdout_tail"] = proc.stdout[-2000:]
                record["stderr_tail"] = proc.stderr[-2000:]
                if proc.returncode != 0:
                    record["status"] = "process_error"
                else:
                    try:
                        payload = json.loads(proc.stdout)
                    except json.JSONDecodeError as exc:
                        stripped = proc.stdout.strip()
                        start = stripped.find("{")
                        end = stripped.rfind("}")
                        if start >= 0 and end > start:
                            try:
                                payload = json.loads(stripped[start : end + 1])
                            except json.JSONDecodeError:
                                record["status"] = "json_parse_error"
                                record["error"] = f"{type(exc).__name__}: {exc}"
                            else:
                                sweep_rows = payload.get("rows") or []
                                row = sweep_rows[0] if sweep_rows else {}
                                record["status"] = str(row.get("status", payload.get("status", "missing_row")))
                                record["report_status"] = payload.get("status")
                                record["row"] = row
                        else:
                            record["status"] = "json_parse_error"
                            record["error"] = f"{type(exc).__name__}: {exc}"
                    else:
                        sweep_rows = payload.get("rows") or []
                        row = sweep_rows[0] if sweep_rows else {}
                        record["status"] = str(row.get("status", payload.get("status", "missing_row")))
                        record["report_status"] = payload.get("status")
                        record["row"] = row

            rows.append(record)
            if args.output is not None:
                with args.output.open("a", encoding="utf-8") as output_file:
                    output_file.write(json.dumps(record, sort_keys=True) + "\n")

    rows.sort(key=lambda item: (int(item["s"]), int(item["k"]), str(item["variant"])))
    reconstructed_rows = [
        row
        for row in rows
        if int((row.get("row") or {}).get("reconstructed_polynomial_count") or 0) > 0
    ]
    timeout_rows = [row for row in rows if row.get("timeout")]
    error_rows = [
        row
        for row in rows
        if str(row.get("status")) in {"process_error", "json_parse_error", "runner_error", "error"}
    ]
    margins = [
        float((row.get("row") or {})["primitive_margin"])
        for row in rows
        if "primitive_margin" in (row.get("row") or {})
    ]
    summary = {
        "event": "coron_grid_summary",
        "status": "ok",
        "s_values": s_values,
        "k_values": k_values,
        "variants": variants,
        "timeout_seconds": args.timeout_seconds,
        "max_jobs": args.max_jobs,
        "output": str(args.output) if args.output is not None else None,
        "row_count": len(rows),
        "reconstructed_positive_rows": len(reconstructed_rows),
        "timeouts": len(timeout_rows),
        "errors": len(error_rows),
        "best_primitive_margin": max(margins) if margins else None,
        "elapsed_seconds": round(time.monotonic() - started_at, 6),
    }

    if args.json:
        print(json.dumps({"summary": summary, "rows": rows}, sort_keys=True))
    else:
        print(
            "rows={row_count} reconstructed_positive={reconstructed_positive_rows} "
            "timeouts={timeouts} errors={errors} best_margin={best_primitive_margin} "
            "elapsed={elapsed_seconds}s".format(**summary)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
