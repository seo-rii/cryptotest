#!/usr/bin/env python3
"""Q-interval guided low-prefix SAT/CAS batch helper.

This is a small coordinator around the existing tools:

1. rank high-side p assignments with q_interval_sweep.py;
2. fix the best high-side ranges, especially x6/x7 by default;
3. run low-prefix cubes through sat_cas_batch_runner.py with low-Coppersmith.

High-side decisions are passed as fixed p ranges, not selected cube bits, so
low-Coppersmith hard no-goods remain scoped to the selected low-prefix bits in
semi_programmatic_sat.py.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from sat_batch_analyzer import read_records, summarize


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path("/tmp/ct07_q_guided_low_batch.jsonl")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--analysis-output",
        type=Path,
        help="analysis JSON path; default is OUTPUT.analysis.json",
    )
    parser.add_argument(
        "--high-cube-ranges",
        default="822:8,920:4",
        help="high-side START:WIDTH ranges ranked by q_interval_sweep",
    )
    parser.add_argument("--high-max-cubes", type=int, default=256)
    parser.add_argument("--top-high", type=int, default=4)
    parser.add_argument(
        "--low-cube-ranges",
        default="150:4,210:39,265:84,362:78",
        help="low-prefix ranges selected by semi_programmatic_sat",
    )
    parser.add_argument("--max-cubes", type=int, default=2, help="low-prefix cubes per high assignment")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--check-bits", type=int, default=608)
    parser.add_argument("--prefix-core", choices=["bv", "hensel"], default="bv")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--small-primes", type=int, default=0)
    parser.add_argument("--low-coppersmith-bits", type=int, default=600)
    parser.add_argument("--low-coppersmith-epsilon", type=float, default=0.02)
    parser.add_argument("--low-coppersmith-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument(
        "--append",
        action="store_true",
        help="append to output instead of replacing it first",
    )
    return parser.parse_args()


def run_json(command: list[str]) -> dict[str, Any]:
    process = subprocess.run(
        command,
        cwd=HERE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise SystemExit(
            json.dumps(
                {
                    "event": "helper_error",
                    "command": command,
                    "returncode": process.returncode,
                    "stderr": process.stderr.splitlines(),
                },
                sort_keys=True,
            )
        )
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse JSON from {command[1]}: {exc}") from exc


def compact_range_text(range_items: list[dict[str, Any]]) -> list[str]:
    fixed_ranges = []
    for item in sorted(range_items, key=lambda value: int(value["start"])):
        fixed_ranges.append(f"{int(item['start'])}:{int(item['width'])}:{int(item['value'])}")
    return fixed_ranges


def write_record(handle, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, sort_keys=True) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def run_batch(args: argparse.Namespace, fixed_ranges: list[str], high_index: int) -> int:
    command = [
        sys.executable,
        str(HERE / "sat_cas_batch_runner.py"),
        "--output",
        str(args.output),
        "--cube-ranges",
        args.low_cube_ranges,
        "--max-cubes",
        str(args.max_cubes),
        "--timeout-seconds",
        str(args.timeout_seconds),
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
        "--run-low-coppersmith",
        "--low-coppersmith-hard-fail",
        "--low-coppersmith-bits",
        str(args.low_coppersmith_bits),
        "--low-coppersmith-epsilon",
        str(args.low_coppersmith_epsilon),
        "--low-coppersmith-min-hard-margin-bits",
        str(args.low_coppersmith_min_hard_margin_bits),
        "--include-cube-ranges",
    ]
    for fixed_range in fixed_ranges:
        command.extend(["--fix-p-range", fixed_range])

    process = subprocess.run(
        command,
        cwd=HERE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    with args.output.open("a", encoding="utf-8") as handle:
        write_record(
            handle,
            {
                "event": "q_guided_batch_done",
                "high_index": high_index,
                "returncode": process.returncode,
                "stdout": process.stdout.splitlines(),
                "stderr": process.stderr.splitlines(),
            },
        )
    return process.returncode


def main() -> int:
    args = parse_args()
    if args.high_max_cubes < 1:
        raise SystemExit("--high-max-cubes must be positive")
    if args.top_high < 1:
        raise SystemExit("--top-high must be positive")
    if args.max_cubes < 1:
        raise SystemExit("--max-cubes must be positive")
    if args.low_coppersmith_bits <= 0:
        raise SystemExit("--low-coppersmith-bits must be positive")
    if args.low_coppersmith_min_hard_margin_bits < 0:
        raise SystemExit("--low-coppersmith-min-hard-margin-bits must be nonnegative")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.append and args.output.exists():
        args.output.unlink()

    ranking_command = [
        sys.executable,
        str(HERE / "q_interval_sweep.py"),
        "--cube-ranges",
        args.high_cube_ranges,
        "--max-cubes",
        str(args.high_max_cubes),
        "--json",
    ]
    ranking = run_json(ranking_command)
    ranked_items = list(ranking.get("items", []))[: args.top_high]
    if not ranked_items:
        raise SystemExit("q_interval_sweep produced no high-side candidates")

    with args.output.open("a", encoding="utf-8") as handle:
        write_record(
            handle,
            {
                "event": "q_guided_start",
                "high_cube_ranges": args.high_cube_ranges,
                "high_max_cubes": args.high_max_cubes,
                "top_high": args.top_high,
                "low_cube_ranges": args.low_cube_ranges,
                "max_cubes": args.max_cubes,
                "low_coppersmith_bits": args.low_coppersmith_bits,
                "low_coppersmith_epsilon": args.low_coppersmith_epsilon,
                "low_coppersmith_min_hard_margin_bits": args.low_coppersmith_min_hard_margin_bits,
                "ranking_command": ranking_command,
            },
        )
        for index, item in enumerate(ranked_items, start=1):
            write_record(
                handle,
                {
                    "event": "q_guided_high_candidate",
                    "high_index": index,
                    "q_known_gain": item.get("q_known_gain"),
                    "q_prefix_gain": item.get("q_prefix_gain"),
                    "q_low_gain": item.get("q_low_gain"),
                    "fixed_ranges": compact_range_text(item.get("cube_ranges", [])),
                    "ranked_cube": item,
                },
            )

    failures = 0
    for index, item in enumerate(ranked_items, start=1):
        fixed_ranges = compact_range_text(item.get("cube_ranges", []))
        failures += int(run_batch(args, fixed_ranges, index) != 0)

    records, parse_errors = read_records([str(args.output)])
    analysis = summarize(records, parse_errors)
    analysis_path = args.analysis_output or args.output.with_suffix(args.output.suffix + ".analysis.json")
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(json.dumps(analysis, sort_keys=True) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "event": "q_guided_summary",
                "output": str(args.output),
                "analysis_output": str(analysis_path),
                "high_candidates": len(ranked_items),
                "batch_failures": failures,
                "cubes": analysis["cubes"],
                "low_coppersmith_calls": analysis["low_coppersmith_calls"],
                "low_coppersmith_hard_blocks": analysis["low_coppersmith_hard_blocks"],
                "learned_clause_scope": analysis["learned_clause_scope"],
                "factored_events": len(analysis["factored_events"]),
            },
            sort_keys=True,
        )
    )
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
