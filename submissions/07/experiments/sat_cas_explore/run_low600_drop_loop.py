#!/usr/bin/env python3
"""Iterate corrected low600 p-Coppersmith drop clauses.

The corrected PDF makes p[0..600) contiguous once 150:4, 265:84, and
362:58 are fixed.  This runner repeatedly asks semi_programmatic_sat.py for one
new cube, runs the hard low-Coppersmith oracle, and reloads all previously
learned JSONL ledgers.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_fresh_low600_drop_loop_{time.strftime('%Y%m%d_%H%M%S')}"
DEFAULT_DROP_WINDOWS = ("150:4",)


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--iterations", type=int, default=4)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--cube-ranges",
        default="150:4,265:84,362:58",
        help="comma-separated START:WIDTH p-bit cube ranges passed to semi_programmatic_sat.py",
    )
    parser.add_argument("--check-bits", type=int, default=600)
    parser.add_argument("--timeout-ms", type=int, default=60000)
    parser.add_argument(
        "--solver-timeout-ms",
        type=int,
        default=0,
        help="Z3 solver timeout for each cube-selection check in semi_programmatic_sat.py",
    )
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--low-coppersmith-bits", type=int, default=600)
    parser.add_argument("--low-coppersmith-epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument(
        "--low-coppersmith-oracle-timeout-seconds",
        type=float,
        default=0.0,
        help="per small_roots call timeout for low-Coppersmith; 0 disables the guard",
    )
    parser.add_argument(
        "--drop-window",
        action="append",
        default=[],
        help="low-Coppersmith drop window START:WIDTH; repeatable. Defaults to 150:4",
    )
    parser.add_argument("--low-coppersmith-minimize-max-completions", type=int, default=16)
    parser.add_argument("--resume-jsonl", action="append", default=[], type=Path)
    parser.add_argument(
        "--resume-list",
        action="append",
        default=[],
        type=Path,
        help="text file containing one resume JSONL path per line; blank lines and # comments are ignored",
    )
    parser.add_argument(
        "--resume-order",
        choices=("as-listed", "newest-first"),
        default="as-listed",
        help="order for ledgers loaded from --resume-jsonl/--resume-list",
    )
    parser.add_argument(
        "--load-learned-limit",
        type=int,
        default=0,
        help="maximum learned clauses to load in each semi_programmatic_sat.py child; 0 means unlimited",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if not args.cube_ranges.strip():
        raise SystemExit("--cube-ranges must not be empty")
    if args.enumerate_p_free_limit < 0:
        raise SystemExit("--enumerate-p-free-limit must be nonnegative")
    if args.solver_timeout_ms < 0:
        raise SystemExit("--solver-timeout-ms must be nonnegative")
    if args.low_coppersmith_bits < 1:
        raise SystemExit("--low-coppersmith-bits must be positive")
    if args.low_coppersmith_oracle_timeout_seconds < 0:
        raise SystemExit("--low-coppersmith-oracle-timeout-seconds must be nonnegative")
    if args.low_coppersmith_minimize_max_completions < 1:
        raise SystemExit("--low-coppersmith-minimize-max-completions must be positive")
    if args.load_learned_limit < 0:
        raise SystemExit("--load-learned-limit must be nonnegative")
    drop_windows = args.drop_window or list(DEFAULT_DROP_WINDOWS)

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ledgers = [path.expanduser().resolve() for path in args.resume_jsonl]
    for resume_list in args.resume_list:
        list_path = resume_list.expanduser()
        with list_path.open(encoding="utf-8") as handle:
            for line in handle:
                raw_line = line.strip()
                if not raw_line or raw_line.startswith("#"):
                    continue
                ledgers.append(Path(raw_line).expanduser().resolve())
    if args.resume_order == "newest-first":
        ledgers.reverse()
    started = time.time()
    records: list[dict[str, Any]] = []
    solved = None
    parameters = {
        "iterations": args.iterations,
        "max_seconds": args.max_seconds,
        "workers": args.workers,
        "cube_ranges": args.cube_ranges,
        "check_bits": args.check_bits,
        "timeout_ms": args.timeout_ms,
        "solver_timeout_ms": args.solver_timeout_ms,
        "enumerate_p_free_limit": args.enumerate_p_free_limit,
        "low_coppersmith_bits": args.low_coppersmith_bits,
        "low_coppersmith_epsilon": args.low_coppersmith_epsilon,
        "low_coppersmith_oracle_timeout_seconds": args.low_coppersmith_oracle_timeout_seconds,
        "min_hard_margin_bits": args.min_hard_margin_bits,
        "low_coppersmith_minimize_max_completions": args.low_coppersmith_minimize_max_completions,
        "drop_windows": drop_windows,
        "resume_order": args.resume_order,
        "load_learned_limit": args.load_learned_limit,
        "initial_ledgers": [str(path) for path in ledgers],
    }

    for iteration in range(1, args.iterations + 1):
        if args.max_seconds and time.time() - started >= args.max_seconds:
            break
        out_jsonl = output_dir / f"iteration_{iteration:04d}.jsonl"
        command = [
            sys.executable,
            str(HERE / "semi_programmatic_sat.py"),
            "--jsonl",
            "--max-cubes",
            "1",
            "--cube-ranges",
            args.cube_ranges,
            "--check-bits",
            str(args.check_bits),
            "--timeout-ms",
            str(args.timeout_ms),
            "--solver-timeout-ms",
            str(args.solver_timeout_ms),
            "--enumerate-p-free-limit",
            str(args.enumerate_p_free_limit),
            "--run-low-coppersmith",
            "--low-coppersmith-bits",
            str(args.low_coppersmith_bits),
            "--low-coppersmith-epsilon",
            str(args.low_coppersmith_epsilon),
            "--low-coppersmith-oracle-timeout-seconds",
            str(args.low_coppersmith_oracle_timeout_seconds),
            "--low-coppersmith-min-hard-margin-bits",
            str(args.min_hard_margin_bits),
            "--low-coppersmith-hard-fail",
            "--low-coppersmith-minimize-max-completions",
            str(args.low_coppersmith_minimize_max_completions),
            "--low-coppersmith-minimize-workers",
            str(args.workers),
            "--include-cube-ranges",
        ]
        if args.load_learned_limit:
            command.extend(["--load-learned-limit", str(args.load_learned_limit)])
        for drop_window in drop_windows:
            command.extend(["--low-coppersmith-drop-window", drop_window])
        for ledger in ledgers:
            command.extend(["--load-learned-jsonl", str(ledger)])

        iteration_started = time.time()
        if args.dry_run:
            record = {
                "iteration": iteration,
                "command": command,
                "command_text": " ".join(command),
                "jsonl": str(out_jsonl),
                "loaded_ledgers": [str(path) for path in ledgers],
            }
            records.append(record)
            break
        run_timeout = None
        if args.max_seconds:
            run_timeout = max(1.0, args.max_seconds - (time.time() - started))
        timed_out = False
        stderr_text = ""
        with out_jsonl.open("w", encoding="utf-8") as stdout:
            process = subprocess.Popen(
                command,
                cwd=WORKSPACE,
                text=True,
                stdout=stdout,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            try:
                _, stderr_text = process.communicate(timeout=run_timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    _, stderr_text = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    _, stderr_text = process.communicate()
        stderr_path = output_dir / f"iteration_{iteration:04d}.stderr"
        stderr_path.write_text(stderr_text, encoding="utf-8")
        rows = jsonl_rows(out_jsonl)
        cube = next((row for row in rows if row.get("event") == "cube"), {})
        summary = next((row for row in rows if row.get("event") == "summary"), {})
        low_coppersmith = cube.get("low_coppersmith") or {}
        factors = low_coppersmith.get("factors") or []
        record = {
            "iteration": iteration,
            "returncode": process.returncode,
            "timed_out": timed_out,
            "timeout_seconds": run_timeout,
            "elapsed_seconds": time.time() - iteration_started,
            "jsonl": str(out_jsonl),
            "stderr": str(stderr_path),
            "cube_ranges": cube.get("cube_ranges"),
            "low_coppersmith_status": low_coppersmith.get("status"),
            "low_coppersmith_low_bits": low_coppersmith.get("low_bits"),
            "low_coppersmith_effective_margin_bits": low_coppersmith.get("effective_margin_bits"),
            "learned_clause": cube.get("learned_clause"),
            "learned_clause_scope": cube.get("learned_clause_scope"),
            "learned_clause_literal_count": cube.get("learned_clause_literal_count"),
            "learned_clause_dropped_literal_count": cube.get("learned_clause_dropped_literal_count"),
            "learned_clause_dropped_bits": cube.get("learned_clause_dropped_bits"),
            "low_coppersmith_minimization": cube.get("low_coppersmith_minimization"),
            "loaded_learned_clauses": summary.get("loaded_learned_clauses"),
            "loaded_learned_literals": summary.get("loaded_learned_literals"),
            "low_coppersmith_calls": summary.get("low_coppersmith_calls"),
            "low_coppersmith_cache_hits": summary.get("low_coppersmith_cache_hits"),
            "low_coppersmith_hard_blocks": summary.get("low_coppersmith_hard_blocks"),
            "low_coppersmith_minimized_blocks": summary.get("low_coppersmith_minimized_blocks"),
            "factors": factors,
        }
        records.append(record)
        if cube and cube.get("learned_clause") != "sample_block_only":
            ledgers.append(out_jsonl)
        summary_path = output_dir / "loop_summary.json"
        payload = {
            "event": "low600_drop_loop",
            "status": "factored" if factors else "running",
            "output_dir": str(output_dir),
            "parameters": parameters,
            "elapsed_seconds": time.time() - started,
            "records": records,
        }
        summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if factors:
            solved = record
            break
        if not cube:
            break
        if cube.get("learned_clause") == "sample_block_only":
            break
        if process.returncode not in {0, 2}:
            break

    final_payload = {
        "event": "low600_drop_loop",
        "status": "factored" if solved else "no_factor",
        "output_dir": str(output_dir),
        "parameters": parameters,
        "elapsed_seconds": time.time() - started,
        "iterations_completed": len(records),
        "records": records,
        "success": solved,
    }
    summary_path = output_dir / "loop_summary.json"
    summary_path.write_text(json.dumps(final_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({**final_payload, "records": f"{len(records)} rows in {summary_path}"}, sort_keys=True))
    else:
        print(
            "status={status} iterations={iterations} output={output}".format(
                status=final_payload["status"],
                iterations=len(records),
                output=summary_path,
            )
        )
    return 0 if solved or args.dry_run else 2


if __name__ == "__main__":
    raise SystemExit(main())
