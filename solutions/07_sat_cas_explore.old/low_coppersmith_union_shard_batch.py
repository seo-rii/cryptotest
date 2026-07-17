#!/usr/bin/env python3
"""Resumable batch runner for fixed-union low-Coppersmith shards."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from sat_cas_core import parse_fixed_range


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--label", default="union")
    parser.add_argument("--completion-start", type=int, required=True)
    parser.add_argument("--completion-stop", type=int, required=True)
    parser.add_argument("--chunk-size", type=int, default=64)
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--base-selected-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--variant-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--drop-window", action="append", default=[])
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if args.completion_start < 0:
        raise SystemExit("--completion-start must be nonnegative")
    if args.completion_stop <= args.completion_start:
        raise SystemExit("--completion-stop must be greater than --completion-start")
    if args.chunk_size < 1:
        raise SystemExit("--chunk-size must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.jobs < 1:
        raise SystemExit("--jobs must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")
    if not args.base_selected_p_range or not args.variant_p_range or not args.drop_window:
        raise SystemExit("--base-selected-p-range, --variant-p-range, and --drop-window are required")

    here = Path(__file__).resolve().parent
    checker_path = here / "low_coppersmith_multicube_union_check.py"
    output_dir = Path(args.output_dir)
    output_jsonl = Path(args.output_jsonl)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    completed = 0
    skipped = 0
    failed = 0
    with output_jsonl.open("a", encoding="utf-8") as handle:
        start = args.completion_start
        while start < args.completion_stop:
            count = min(args.chunk_size, args.completion_stop - start)
            output_path = output_dir / f"{args.label}_shard{start}_{count}.json"
            stderr_path = output_dir / f"{args.label}_shard{start}_{count}.stderr"
            if args.resume and output_path.exists() and output_path.stat().st_size > 0:
                try:
                    payload = json.loads(output_path.read_text(encoding="utf-8"))
                    summary = payload["summary"]
                    handle.write(
                        json.dumps(
                            {
                                "event": "shard_skipped_existing",
                                "path": str(output_path),
                                "completion_start": summary.get("completion_start"),
                                "completion_stop": summary.get("completion_stop"),
                                "low_bits": summary.get("low_bits"),
                                "epsilon": summary.get("epsilon"),
                                "min_hard_margin_bits": summary.get("min_hard_margin_bits"),
                                "all_completions_no_roots": summary.get("all_completions_no_roots"),
                                "factor_count": summary.get("factor_count"),
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    handle.flush()
                    skipped += 1
                    start += count
                    continue
                except Exception:
                    pass

            command = [
                sys.executable,
                "-B",
                str(checker_path),
                "--low-bits",
                str(args.low_bits),
                "--epsilon",
                str(args.epsilon),
                "--min-hard-margin-bits",
                str(args.min_hard_margin_bits),
                "--max-completions",
                str(count),
                "--completion-start",
                str(start),
                "--completion-count",
                str(count),
                "--jobs",
                str(args.jobs),
                "--json",
            ]
            for fixed_range in args.fix_p_range:
                command.extend(
                    ["--fix-p-range", f"{fixed_range.start}:{fixed_range.width}:{hex(fixed_range.value)}"]
                )
            for selected_range in args.base_selected_p_range:
                command.extend(
                    [
                        "--base-selected-p-range",
                        f"{selected_range.start}:{selected_range.width}:{hex(selected_range.value)}",
                    ]
                )
            for variant_range in args.variant_p_range:
                command.extend(
                    [
                        "--variant-p-range",
                        f"{variant_range.start}:{variant_range.width}:{hex(variant_range.value)}",
                    ]
                )
            for drop_window in args.drop_window:
                command.extend(["--drop-window", drop_window])

            started_at = time.time()
            row = {
                "event": "shard_done",
                "completion_start": start,
                "completion_stop": start + count,
                "completion_count": count,
                "low_bits": args.low_bits,
                "epsilon": args.epsilon,
                "min_hard_margin_bits": args.min_hard_margin_bits,
                "path": str(output_path),
                "stderr_path": str(stderr_path),
            }
            try:
                process = subprocess.Popen(
                    command,
                    cwd=here,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                try:
                    stdout_text, stderr_text = process.communicate(timeout=args.timeout_seconds)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        stdout_text, stderr_text = process.communicate(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        stdout_text, stderr_text = process.communicate()
                    output_path.write_text(stdout_text or "", encoding="utf-8")
                    stderr_path.write_text(stderr_text or "", encoding="utf-8")
                    row.update(
                        {
                            "status": "timeout",
                            "elapsed_seconds": round(time.time() - started_at, 3),
                            "returncode": process.returncode,
                            "stdout_size": len(stdout_text or ""),
                            "stderr_size": len(stderr_text or ""),
                        }
                    )
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
                    handle.flush()
                    failed += 1
                    start += count
                    continue
                except KeyboardInterrupt:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise

                output_path.write_text(stdout_text or "", encoding="utf-8")
                stderr_path.write_text(stderr_text or "", encoding="utf-8")
                row["elapsed_seconds"] = round(time.time() - started_at, 3)
                row["returncode"] = process.returncode
                try:
                    payload = json.loads(stdout_text or "")
                    summary = payload["summary"]
                    row.update(
                        {
                            "status": "ok" if process.returncode == 0 else "process_error",
                            "all_completions_no_roots": summary.get("all_completions_no_roots"),
                            "unique_oracle_cases": summary.get("unique_oracle_cases"),
                            "total_completion_checks": summary.get("total_completion_checks"),
                            "hard_eligible_total_count": summary.get("hard_eligible_total_count"),
                            "roots_returned_unique_total": summary.get("roots_returned_unique_total"),
                            "factor_count": summary.get("factor_count"),
                        }
                    )
                except Exception as exc:
                    row.update(
                        {
                            "status": "json_parse_error",
                            "stdout_size": len(stdout_text or ""),
                            "stderr_size": len(stderr_text or ""),
                            "error": str(exc),
                        }
                    )
            except Exception as exc:
                row.update(
                    {
                        "status": "launch_error",
                        "elapsed_seconds": round(time.time() - started_at, 3),
                        "returncode": None,
                        "error": str(exc),
                    }
                )

            if row["status"] == "ok" and row.get("all_completions_no_roots") and row.get("factor_count") == 0:
                completed += 1
            else:
                failed += 1
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            start += count

    print(
        json.dumps(
            {
                "event": "shard_batch_summary",
                "completed": completed,
                "failed": failed,
                "skipped": skipped,
                "output_jsonl": str(output_jsonl),
                "output_dir": str(output_dir),
            },
            sort_keys=True,
        )
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
