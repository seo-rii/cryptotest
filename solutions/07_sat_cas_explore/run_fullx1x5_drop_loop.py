#!/usr/bin/env python3
"""Iterate corrected full-x1/full-x5 q-gap drop clauses.

This runner keeps outputs under the workspace tmp directory and repeatedly
invokes semi_programmatic_sat.py with all previously learned JSONL ledgers.
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
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_fresh_fullx1x5_drop_loop_{time.strftime('%Y%m%d_%H%M%S')}"
DEFAULT_DROP_WINDOWS = ("150:4", "920:4", "784:6")
DEFAULT_HYBRID_CUMULATIVE_DROP_WINDOWS = ("150:4", "920:4")
DEFAULT_HYBRID_INDEPENDENT_DROP_WINDOWS = ("265:8", "273:8", "784:8", "792:8")


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def read_resume_list(path: Path) -> list[Path]:
    rows: list[Path] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append(Path(line))
    return rows


def manifest_path_text(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(WORKSPACE))
    except ValueError:
        return str(resolved)


def append_manifest_entries(path: Path, ledgers: list[Path]) -> None:
    seen: set[str] = set()
    rows: list[str] = []
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or line in seen:
                    continue
                seen.add(line)
                rows.append(line)
    for ledger in ledgers:
        text = manifest_path_text(ledger)
        if text in seen:
            continue
        seen.add(text)
        rows.append(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def run_command(command: list[str], stdout_path: Path, timeout_seconds: float) -> tuple[int, str, bool]:
    with stdout_path.open("w", encoding="utf-8") as stdout:
        process = subprocess.Popen(
            command,
            cwd=WORKSPACE,
            text=True,
            stdout=stdout,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            _, stderr = process.communicate(timeout=timeout_seconds if timeout_seconds > 0 else None)
            return process.returncode, stderr or "", False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                _, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                _, stderr = process.communicate()
            return 124, (stderr or "") + f"\ncommand timed out after {timeout_seconds:.1f}s\n", True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--iterations", type=int, default=4)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument(
        "--iteration-timeout-seconds",
        type=float,
        default=0.0,
        help="wall timeout for each semi_programmatic_sat.py iteration; 0 disables the guard",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--cube-ranges",
        default="150:4,265:84,784:46,920:4",
        help="comma-separated START:WIDTH p-bit cube ranges passed to semi_programmatic_sat.py",
    )
    parser.add_argument(
        "--cube-assume-p-range",
        action="append",
        default=[],
        help=(
            "temporary START:WIDTH:VALUE p-bit assumption for cube selection; "
            "forwarded to semi_programmatic_sat.py and included in emitted cube records"
        ),
    )
    parser.add_argument(
        "--cube-assume-p-range-cycle",
        action="append",
        default=[],
        help=(
            "cycle a temporary p-bit assumption across iterations as START:WIDTH:V0,V1,...; "
            "useful for guarded x6-prefix diversification"
        ),
    )
    parser.add_argument("--check-bits", type=int, default=362)
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument(
        "--q-gap-oracle-timeout-seconds",
        type=float,
        default=0.0,
        help="per q-gap Coppersmith small_roots call timeout; 0 disables the guard",
    )
    parser.add_argument(
        "--drop-mode",
        choices=("none", "independent", "cumulative", "hybrid"),
        default="independent",
        help=(
            "none adds only the full q-gap no-root clause; independent adds one clause per droppable window; "
            "cumulative tests the growing union of windows; hybrid tests edge windows cumulatively plus byte "
            "windows independently"
        ),
    )
    parser.add_argument(
        "--drop-window",
        action="append",
        default=[],
        help="q-gap drop window START:WIDTH; repeatable. Defaults to 150:4, 920:4, and 784:6",
    )
    parser.add_argument(
        "--hybrid-cumulative-drop-window",
        action="append",
        default=[],
        help="hybrid-mode cumulative q-gap drop window START:WIDTH; defaults to 150:4 and 920:4",
    )
    parser.add_argument(
        "--hybrid-independent-drop-window",
        action="append",
        default=[],
        help=(
            "hybrid-mode independent q-gap drop window START:WIDTH; defaults to "
            "265:8, 273:8, 784:8, and 792:8"
        ),
    )
    parser.add_argument("--q-gap-minimize-max-completions", type=int, default=256)
    parser.add_argument(
        "--load-learned-limit",
        type=int,
        default=0,
        help="maximum learned clauses to load into each SAT iteration; 0 means no limit",
    )
    parser.add_argument("--resume-jsonl", action="append", default=[], type=Path)
    parser.add_argument(
        "--resume-list",
        action="append",
        default=[],
        type=Path,
        help="file containing one learned JSONL path per line; repeatable",
    )
    parser.add_argument(
        "--manifest-output",
        type=Path,
        help="write the active learned-ledger manifest after each completed iteration",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")
    if args.iteration_timeout_seconds < 0:
        raise SystemExit("--iteration-timeout-seconds must be nonnegative")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if not args.cube_ranges.strip():
        raise SystemExit("--cube-ranges must not be empty")
    if args.enumerate_p_free_limit < 0:
        raise SystemExit("--enumerate-p-free-limit must be nonnegative")
    if args.q_gap_minimize_max_completions < 1:
        raise SystemExit("--q-gap-minimize-max-completions must be positive")
    if args.load_learned_limit < 0:
        raise SystemExit("--load-learned-limit must be nonnegative")
    if args.q_gap_oracle_timeout_seconds < 0:
        raise SystemExit("--q-gap-oracle-timeout-seconds must be nonnegative")
    assumption_cycles: list[tuple[int, int, list[int]]] = []
    for raw_cycle in args.cube_assume_p_range_cycle:
        try:
            start_text, width_text, values_text = raw_cycle.split(":", 2)
        except ValueError as exc:
            raise SystemExit("--cube-assume-p-range-cycle must be START:WIDTH:V0,V1,...") from exc
        start = int(start_text, 0)
        width = int(width_text, 0)
        values = [int(item.strip(), 0) for item in values_text.split(",") if item.strip()]
        if start < 0 or width <= 0:
            raise SystemExit("--cube-assume-p-range-cycle must have nonnegative start and positive width")
        if not values:
            raise SystemExit("--cube-assume-p-range-cycle must contain at least one value")
        if any(value < 0 or value >= (1 << width) for value in values):
            raise SystemExit("--cube-assume-p-range-cycle value does not fit width")
        assumption_cycles.append((start, width, values))
    drop_windows = args.drop_window or list(DEFAULT_DROP_WINDOWS)
    hybrid_cumulative_drop_windows = (
        args.hybrid_cumulative_drop_window or list(DEFAULT_HYBRID_CUMULATIVE_DROP_WINDOWS)
    )
    hybrid_independent_drop_windows = (
        args.hybrid_independent_drop_window or list(DEFAULT_HYBRID_INDEPENDENT_DROP_WINDOWS)
    )

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    resume_paths: list[Path] = []
    for resume_list in args.resume_list:
        resume_paths.extend(read_resume_list(resume_list.expanduser()))
    resume_paths.extend(args.resume_jsonl)
    ledgers = [path.expanduser().resolve() for path in resume_paths]
    started = time.time()
    records: list[dict[str, Any]] = []
    solved = None
    stopped_reason = "iterations_exhausted"
    parameters = {
        "iterations": args.iterations,
        "max_seconds": args.max_seconds,
        "iteration_timeout_seconds": args.iteration_timeout_seconds,
        "workers": args.workers,
        "cube_ranges": args.cube_ranges,
        "cube_assume_p_ranges": args.cube_assume_p_range,
        "cube_assume_p_range_cycles": args.cube_assume_p_range_cycle,
        "check_bits": args.check_bits,
        "timeout_ms": args.timeout_ms,
        "enumerate_p_free_limit": args.enumerate_p_free_limit,
        "q_gap_max_bits": args.q_gap_max_bits,
        "q_gap_epsilon": args.q_gap_epsilon,
        "q_gap_oracle_timeout_seconds": args.q_gap_oracle_timeout_seconds,
        "min_hard_margin_bits": args.min_hard_margin_bits,
        "drop_mode": args.drop_mode,
        "q_gap_minimize_max_completions": args.q_gap_minimize_max_completions,
        "load_learned_limit": args.load_learned_limit,
        "drop_windows": drop_windows,
        "hybrid_cumulative_drop_windows": hybrid_cumulative_drop_windows,
        "hybrid_independent_drop_windows": hybrid_independent_drop_windows,
        "initial_ledgers": [str(path) for path in ledgers],
        "manifest_output": str(args.manifest_output.expanduser()) if args.manifest_output else None,
    }

    for iteration in range(1, args.iterations + 1):
        if args.max_seconds and time.time() - started >= args.max_seconds:
            stopped_reason = "max_seconds"
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
            "--enumerate-p-free-limit",
            str(args.enumerate_p_free_limit),
            "--run-q-gap-coppersmith",
            "--q-gap-max-bits",
            str(args.q_gap_max_bits),
            "--q-gap-epsilon",
            str(args.q_gap_epsilon),
            "--q-gap-min-hard-margin-bits",
            str(args.min_hard_margin_bits),
            "--q-gap-hard-fail",
            "--q-gap-oracle-timeout-seconds",
            str(args.q_gap_oracle_timeout_seconds),
            "--q-gap-minimize-max-completions",
            str(args.q_gap_minimize_max_completions),
            "--q-gap-minimize-workers",
            str(args.workers),
            "--include-cube-ranges",
        ]
        iteration_assumptions = list(args.cube_assume_p_range)
        for start, width, values in assumption_cycles:
            value = values[(iteration - 1) % len(values)]
            iteration_assumptions.append(f"{start}:{width}:{value}")
        if args.drop_mode in {"independent", "hybrid"}:
            command.append("--q-gap-independent-drop-clauses")
        if args.drop_mode == "hybrid":
            for drop_window in hybrid_cumulative_drop_windows:
                command.extend(["--q-gap-cumulative-drop-window", drop_window])
            for drop_window in hybrid_independent_drop_windows:
                command.extend(["--q-gap-drop-window", drop_window])
        elif args.drop_mode in {"independent", "cumulative"}:
            for drop_window in drop_windows:
                command.extend(["--q-gap-drop-window", drop_window])
        for ledger in ledgers:
            command.extend(["--load-learned-jsonl", str(ledger)])
        if args.load_learned_limit:
            command.extend(["--load-learned-limit", str(args.load_learned_limit)])
        for assumption in iteration_assumptions:
            command.extend(["--cube-assume-p-range", assumption])

        iteration_started = time.time()
        if args.dry_run:
            stopped_reason = "dry_run"
            record = {
                "iteration": iteration,
                "command": command,
                "command_text": " ".join(command),
                "jsonl": str(out_jsonl),
                "loaded_ledgers": [str(path) for path in ledgers],
                "cube_assumptions": iteration_assumptions,
            }
            records.append(record)
            break
        returncode, stderr_text, timed_out = run_command(
            command,
            out_jsonl,
            args.iteration_timeout_seconds,
        )
        stderr_path = output_dir / f"iteration_{iteration:04d}.stderr"
        stderr_path.write_text(stderr_text, encoding="utf-8")
        rows = jsonl_rows(out_jsonl)
        cube = next((row for row in rows if row.get("event") == "cube"), {})
        summary = next((row for row in rows if row.get("event") == "summary"), {})
        q_gap = cube.get("q_gap_coppersmith") or {}
        factors = q_gap.get("factors") or []
        completed_iteration = bool(cube) and returncode in {0, 2}
        record = {
            "iteration": iteration,
            "returncode": returncode,
            "completed": completed_iteration,
            "timed_out": timed_out,
            "elapsed_seconds": time.time() - iteration_started,
            "jsonl": str(out_jsonl),
            "stderr": str(stderr_path),
            "cube_assumptions": iteration_assumptions,
            "cube_ranges": cube.get("cube_ranges"),
            "q_gap_status": q_gap.get("status"),
            "q_gap_bits": q_gap.get("q_gap_bits"),
            "q_gap_elapsed_seconds": q_gap.get("elapsed_seconds"),
            "learned_clause_scope": cube.get("learned_clause_scope"),
            "learned_clause_count": cube.get("learned_clause_count"),
            "learned_clause_literal_count": cube.get("learned_clause_literal_count"),
            "learned_clause_dropped_literal_count": cube.get("learned_clause_dropped_literal_count"),
            "learned_clause_dropped_bits": cube.get("learned_clause_dropped_bits"),
            "learned_clause_variants": cube.get("learned_clause_variants"),
            "q_gap_coppersmith_minimization": cube.get("q_gap_coppersmith_minimization"),
            "q_gap_coppersmith_cumulative_minimization": cube.get(
                "q_gap_coppersmith_cumulative_minimization"
            ),
            "q_gap_coppersmith_independent_minimization": cube.get(
                "q_gap_coppersmith_independent_minimization"
            ),
            "loaded_learned_clauses": summary.get("loaded_learned_clauses"),
            "loaded_learned_literals": summary.get("loaded_learned_literals"),
            "q_gap_coppersmith_calls": summary.get("q_gap_coppersmith_calls"),
            "q_gap_coppersmith_hard_blocks": summary.get("q_gap_coppersmith_hard_blocks"),
            "factors": factors,
        }
        records.append(record)
        if completed_iteration:
            ledgers.append(out_jsonl)
        if completed_iteration and args.manifest_output:
            append_manifest_entries(args.manifest_output.expanduser(), [out_jsonl])
        summary_path = output_dir / "loop_summary.json"
        payload = {
            "event": "fullx1x5_drop_loop",
            "status": "factored" if factors else "running",
            "output_dir": str(output_dir),
            "parameters": parameters,
            "elapsed_seconds": time.time() - started,
            "stopped_reason": stopped_reason,
            "valid_iterations_completed": sum(1 for item in records if item.get("completed")),
            "records": records,
        }
        summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if factors:
            solved = record
            stopped_reason = "factored"
            break
        if not completed_iteration:
            stopped_reason = "incomplete_iteration"
            break

    final_payload = {
        "event": "fullx1x5_drop_loop",
        "status": "factored" if solved else "no_factor",
        "output_dir": str(output_dir),
        "parameters": parameters,
        "elapsed_seconds": time.time() - started,
        "iterations_completed": len(records),
        "valid_iterations_completed": sum(1 for item in records if item.get("completed")),
        "stopped_reason": stopped_reason,
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
