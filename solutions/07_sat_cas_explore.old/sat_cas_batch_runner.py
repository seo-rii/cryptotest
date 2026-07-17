#!/usr/bin/env python3
"""Small batch runner for semi_programmatic_sat.py.

The runner keeps each child invocation bounded, preserves the child's JSONL
records, and adds runner metadata so interrupted or timed-out batches are still
usable as an append-only log.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="JSONL output path")
    parser.add_argument("--max-cubes", type=int, default=8, help="cubes per child invocation")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="deadline per child invocation")
    parser.add_argument(
        "--cube-ranges",
        action="append",
        default=[],
        help="cube range set to run; may be supplied more than once",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], help="fixed p range passed through")
    parser.add_argument("--check-bits", type=int, default=608)
    parser.add_argument("--prefix-core", choices=["bv", "hensel"], default="bv")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--small-primes", type=int, default=0)
    parser.add_argument("--run-low-coppersmith", action="store_true")
    parser.add_argument("--low-coppersmith-bits", type=int, default=600)
    parser.add_argument("--low-coppersmith-epsilon", type=float, default=0.02)
    parser.add_argument("--low-coppersmith-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--low-coppersmith-hard-fail", action="store_true")
    parser.add_argument("--low-coppersmith-preverified-drop-window", action="append", default=[])
    parser.add_argument("--low-coppersmith-preverified-guard-p-range", action="append", default=[])
    parser.add_argument("--low-coppersmith-drop-window", action="append", default=[])
    parser.add_argument("--low-coppersmith-minimize-max-completions", type=int, default=16)
    parser.add_argument("--run-q-gap-coppersmith", action="store_true")
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.02)
    parser.add_argument("--q-gap-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--q-gap-oracle-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--q-gap-hard-fail", action="store_true")
    parser.add_argument("--q-gap-drop-window", action="append", default=[])
    parser.add_argument("--q-gap-minimize-max-completions", type=int, default=16)
    parser.add_argument("--q-gap-independent-drop-clauses", action="store_true")
    parser.add_argument("--q-gap-minimize-workers", type=int, default=1)
    parser.add_argument("--load-learned-jsonl", action="append", default=[])
    parser.add_argument("--load-learned-limit", type=int, default=0)
    parser.add_argument("--load-soft-blocks", action="store_true")
    parser.add_argument("--runs-per-range", type=int, default=1)
    parser.add_argument("--include-cube-ranges", action="store_true")
    return parser.parse_args()


def write_record(handle, record: dict[str, object]) -> None:
    handle.write(json.dumps(record, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def build_command(args: argparse.Namespace, script_path: Path, cube_ranges: str) -> list[str]:
    command = [
        sys.executable,
        str(script_path),
        "--jsonl",
        "--max-cubes",
        str(args.max_cubes),
        "--cube-ranges",
        cube_ranges,
        "--check-bits",
        str(args.check_bits),
        "--prefix-core",
        args.prefix_core,
        "--timeout-ms",
        str(args.timeout_ms),
        "--enumerate-p-free-limit",
        str(args.enumerate_p_free_limit),
        "--small-primes",
        str(args.small_primes),
    ]
    if args.include_cube_ranges:
        command.append("--include-cube-ranges")
    if args.run_low_coppersmith:
        command.append("--run-low-coppersmith")
    if args.low_coppersmith_hard_fail:
        command.append("--low-coppersmith-hard-fail")
    if args.run_q_gap_coppersmith:
        command.append("--run-q-gap-coppersmith")
    if args.q_gap_hard_fail:
        command.append("--q-gap-hard-fail")
    if args.q_gap_independent_drop_clauses:
        command.append("--q-gap-independent-drop-clauses")
    if args.load_soft_blocks:
        command.append("--load-soft-blocks")
    command.extend(["--low-coppersmith-bits", str(args.low_coppersmith_bits)])
    command.extend(["--low-coppersmith-epsilon", str(args.low_coppersmith_epsilon)])
    command.extend(
        [
            "--low-coppersmith-min-hard-margin-bits",
            str(args.low_coppersmith_min_hard_margin_bits),
        ]
    )
    for drop_window in args.low_coppersmith_preverified_drop_window:
        command.extend(["--low-coppersmith-preverified-drop-window", drop_window])
    for guard_range in args.low_coppersmith_preverified_guard_p_range:
        command.extend(["--low-coppersmith-preverified-guard-p-range", guard_range])
    for drop_window in args.low_coppersmith_drop_window:
        command.extend(["--low-coppersmith-drop-window", drop_window])
    command.extend(
        [
            "--low-coppersmith-minimize-max-completions",
            str(args.low_coppersmith_minimize_max_completions),
        ]
    )
    command.extend(["--q-gap-max-bits", str(args.q_gap_max_bits)])
    command.extend(["--q-gap-epsilon", str(args.q_gap_epsilon)])
    command.extend(["--q-gap-min-hard-margin-bits", str(args.q_gap_min_hard_margin_bits)])
    command.extend(["--q-gap-oracle-timeout-seconds", str(args.q_gap_oracle_timeout_seconds)])
    command.extend(["--q-gap-minimize-max-completions", str(args.q_gap_minimize_max_completions)])
    command.extend(["--q-gap-minimize-workers", str(args.q_gap_minimize_workers)])
    command.extend(["--load-learned-limit", str(args.load_learned_limit)])
    for drop_window in args.q_gap_drop_window:
        command.extend(["--q-gap-drop-window", drop_window])
    for learned_jsonl in args.load_learned_jsonl:
        command.extend(["--load-learned-jsonl", learned_jsonl])
    for fixed_range in args.fix_p_range:
        command.extend(["--fix-p-range", fixed_range])
    return command


def main() -> int:
    args = parse_args()
    if args.max_cubes < 1:
        raise SystemExit("--max-cubes must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.runs_per_range < 1:
        raise SystemExit("--runs-per-range must be positive")
    if args.low_coppersmith_bits <= 0:
        raise SystemExit("--low-coppersmith-bits must be positive")
    if args.low_coppersmith_min_hard_margin_bits < 0:
        raise SystemExit("--low-coppersmith-min-hard-margin-bits must be nonnegative")
    if args.q_gap_max_bits < 0:
        raise SystemExit("--q-gap-max-bits must be nonnegative")
    if args.q_gap_min_hard_margin_bits < 0:
        raise SystemExit("--q-gap-min-hard-margin-bits must be nonnegative")
    if args.q_gap_oracle_timeout_seconds < 0:
        raise SystemExit("--q-gap-oracle-timeout-seconds must be nonnegative")
    if args.q_gap_minimize_max_completions < 1:
        raise SystemExit("--q-gap-minimize-max-completions must be positive")
    if args.q_gap_minimize_workers < 1:
        raise SystemExit("--q-gap-minimize-workers must be positive")
    if args.load_learned_limit < 0:
        raise SystemExit("--load-learned-limit must be nonnegative")

    script_path = Path(__file__).resolve().with_name("semi_programmatic_sat.py")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cube_ranges_list = args.cube_ranges or ["150:4,210:8,822:8,920:4"]

    total_runs = 0
    completed_runs = 0
    with output_path.open("a", encoding="utf-8") as handle:
        for cube_ranges in cube_ranges_list:
            for repeat_index in range(args.runs_per_range):
                total_runs += 1
                command = build_command(args, script_path, cube_ranges)
                started_at = time.time()
                write_record(
                    handle,
                    {
                        "event": "runner_start",
                        "run_index": total_runs,
                        "repeat_index": repeat_index + 1,
                        "cube_ranges": cube_ranges,
                        "max_cubes": args.max_cubes,
                        "timeout_seconds": args.timeout_seconds,
                        "fix_p_range": args.fix_p_range,
                        "load_learned_jsonl": args.load_learned_jsonl,
                        "load_learned_limit": args.load_learned_limit,
                        "load_soft_blocks": args.load_soft_blocks,
                        "q_gap_drop_window": args.q_gap_drop_window,
                        "q_gap_independent_drop_clauses": args.q_gap_independent_drop_clauses,
                        "q_gap_minimize_workers": args.q_gap_minimize_workers,
                        "q_gap_oracle_timeout_seconds": args.q_gap_oracle_timeout_seconds,
                    },
                )
                process = subprocess.Popen(
                    command,
                    cwd=script_path.parent,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                timed_out = False
                try:
                    stdout_text, stderr_text = process.communicate(timeout=args.timeout_seconds)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    process.kill()
                    stdout_text, stderr_text = process.communicate()

                for line in stdout_text.splitlines():
                    try:
                        child_record = json.loads(line)
                    except json.JSONDecodeError:
                        child_record = {"event": "child_stdout", "line": line}
                    child_record["runner_run_index"] = total_runs
                    child_record["runner_cube_ranges"] = cube_ranges
                    write_record(handle, child_record)

                stderr_lines = [line for line in stderr_text.splitlines() if line.strip()]
                if stderr_lines:
                    write_record(
                        handle,
                        {
                            "event": "runner_stderr",
                            "run_index": total_runs,
                            "cube_ranges": cube_ranges,
                            "lines": stderr_lines,
                        },
                    )

                elapsed_seconds = time.time() - started_at
                return_code = process.returncode
                if not timed_out and return_code == 0:
                    completed_runs += 1
                write_record(
                    handle,
                    {
                        "event": "runner_done",
                        "run_index": total_runs,
                        "cube_ranges": cube_ranges,
                        "elapsed_seconds": round(elapsed_seconds, 3),
                        "returncode": return_code,
                        "timed_out": timed_out,
                    },
                )

    print(
        json.dumps(
            {
                "event": "batch_summary",
                "output": str(output_path),
                "runs": total_runs,
                "completed_runs": completed_runs,
            },
            sort_keys=True,
        )
    )
    return 0 if completed_runs == total_runs else 1


if __name__ == "__main__":
    raise SystemExit(main())
