#!/usr/bin/env python3
"""Run the current no-x7 q-gap direct/minimization cycle.

This is a thin orchestrator around the already-verified pieces:

1. run_projection_frontier_batches.py for one no-x7 direct q-gap batch.
2. run_cube_representative_minimization.py for selected cumulative drops.

The child runners own SAT/q-gap semantics and manifest appends.  This script
only sequences them, keeps paths predictable, and writes one top-level summary.
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
DEFAULT_MANIFEST = WORKSPACE / "tmp" / "ct07_pwindow420_scored_qgap_ledgers_20260607.txt"
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_nox7_cumulative_cycle_{time.strftime('%Y%m%d_%H%M%S')}"
DEFAULT_PROJECTIONS = ("150:4:x0", "265:8:x2low8", "362:4:x3low4")
NOX7_CUBE_RANGES = "150:4,265:84,362:58"
NOX7_SHAPE = NOX7_CUBE_RANGES


def run_command(
    command: list[str],
    stdout_path: Path,
    stderr_path: Path,
    *,
    timeout_seconds: float = 0.0,
) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
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
            _, stderr = process.communicate(
                timeout=timeout_seconds if timeout_seconds > 0 else None
            )
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                _, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                _, stderr = process.communicate()
            stderr_path.write_text(
                (stderr or "") + f"\ncommand timed out after {timeout_seconds:.1f}s\n",
                encoding="utf-8",
            )
            return 124
    stderr_path.write_text(stderr or "", encoding="utf-8")
    return int(process.returncode)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def read_stdout_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    rows = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        return {}
    try:
        payload = json.loads(rows[-1])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def command_record(
    *,
    name: str,
    command: list[str],
    returncode: int | None,
    stdout_path: Path,
    stderr_path: Path,
    summary_path: Path | None = None,
    elapsed_seconds: float = 0.0,
    skipped_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "returncode": returncode,
        "elapsed_seconds": elapsed_seconds,
        "stdout": str(stdout_path),
        "stderr": str(stderr_path),
        "summary": str(summary_path) if summary_path else None,
        "skipped_reason": skipped_reason,
        "command": command,
    }


def minimization_command(
    *,
    source_jsonl: Path,
    output_dir: Path,
    manifest: Path,
    top: int,
    start_index: int,
    drop_windows: list[str],
    args: argparse.Namespace,
) -> list[str]:
    command = [
        sys.executable,
        str(HERE / "run_cube_representative_minimization.py"),
        "--source-jsonl",
        str(source_jsonl),
        "--output-dir",
        str(output_dir),
        "--append-manifest",
        str(manifest),
        "--start-index",
        str(start_index),
        "--top",
        str(top),
        "--cube-ranges",
        NOX7_CUBE_RANGES,
        "--shape",
        NOX7_SHAPE,
        "--drop-mode",
        "cumulative",
        "--q-gap-minimize-max-completions",
        str(args.cumulative_max_completions),
        "--workers",
        str(args.workers),
        "--item-timeout-seconds",
        str(args.cumulative_item_timeout_seconds),
        "--q-gap-epsilon",
        str(args.q_gap_epsilon),
        "--q-gap-max-bits",
        str(args.q_gap_max_bits),
        "--q-gap-oracle-timeout-seconds",
        str(args.oracle_timeout_seconds),
        "--json",
    ]
    for projection in args.projection:
        command.extend(["--projection", projection])
    for window in drop_windows:
        command.extend(["--cumulative-drop-window", window])
    return command


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--seed-base", type=int, default=20260663)
    parser.add_argument("--skip-direct", action="store_true")
    parser.add_argument("--source-jsonl", type=Path, help="use an existing direct q-gap JSONL")
    parser.add_argument("--direct-max-total", type=int, default=256)
    parser.add_argument("--frontier-top", type=int, default=320)
    parser.add_argument("--candidate-pool", type=int, default=32768)
    parser.add_argument("--top-pairs", type=int, default=128)
    parser.add_argument("--samples-per-pair", type=int, default=2)
    parser.add_argument("--solver-timeout-ms", type=int, default=1000)
    parser.add_argument("--random-assumption-bits", type=int, default=32)
    parser.add_argument("--random-assumption-retries", type=int, default=8)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--oracle-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--frontier-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--sample-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--direct-qgap-timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--direct-command-timeout-seconds", type=float, default=2400.0)
    parser.add_argument(
        "--skip-sampler-learned-clauses",
        action="store_true",
        help="make the direct sampler rely on projection novelty instead of loading learned clauses",
    )
    parser.add_argument("--x2-cumulative-top", type=int, default=2)
    parser.add_argument("--x3-cumulative-top", type=int, default=2)
    parser.add_argument("--cumulative-start-index", type=int, default=1)
    parser.add_argument("--cumulative-max-completions", type=int, default=256)
    parser.add_argument("--cumulative-item-timeout-seconds", type=float, default=360.0)
    parser.add_argument("--cumulative-command-timeout-seconds", type=float, default=1800.0)
    parser.add_argument(
        "--projection",
        action="append",
        default=[],
        help="optional START:WIDTH[:LABEL] projection; repeat to override defaults",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.projection:
        args.projection = list(DEFAULT_PROJECTIONS)
    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")
    if args.direct_max_total < 1:
        raise SystemExit("--direct-max-total must be positive")
    if args.frontier_top < 1 or args.candidate_pool < args.frontier_top:
        raise SystemExit("--candidate-pool must be at least --frontier-top")
    if args.top_pairs < 1 or args.samples_per_pair < 1:
        raise SystemExit("--top-pairs and --samples-per-pair must be positive")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.x2_cumulative_top < 0 or args.x3_cumulative_top < 0:
        raise SystemExit("cumulative top counts must be nonnegative")
    if args.cumulative_start_index < 1:
        raise SystemExit("--cumulative-start-index must be positive")
    if args.cumulative_max_completions < 1:
        raise SystemExit("--cumulative-max-completions must be positive")
    if args.skip_direct and args.source_jsonl is None:
        raise SystemExit("--skip-direct requires --source-jsonl")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.manifest.expanduser()
    started = time.time()
    summary_path = output_dir / "cycle_summary.json"
    records: list[dict[str, Any]] = []
    solved = None
    stopped_reason = "completed"

    for iteration in range(1, args.iterations + 1):
        if args.max_seconds and time.time() - started >= args.max_seconds:
            stopped_reason = "max_seconds"
            break
        iteration_started = time.time()
        iteration_dir = output_dir / f"iteration_{iteration:04d}"
        iteration_dir.mkdir(parents=True, exist_ok=True)
        seed = args.seed_base + iteration - 1
        iteration_record: dict[str, Any] = {
            "iteration": iteration,
            "seed": seed,
            "steps": [],
            "elapsed_seconds": 0.0,
            "status": "running",
        }
        skip_minimization = False

        if args.skip_direct:
            direct_qgap_jsonl = args.source_jsonl.expanduser().resolve()
            direct_summary = {}
        else:
            direct_dir = iteration_dir / "direct"
            direct_stdout = iteration_dir / "direct.stdout.json"
            direct_stderr = iteration_dir / "direct.stderr.txt"
            direct_command = [
                sys.executable,
                str(HERE / "run_projection_frontier_batches.py"),
                "--iterations",
                "1",
                "--output-dir",
                str(direct_dir),
                "--manifest",
                str(manifest),
                "--seed-base",
                str(seed - 1),
                "--cube-ranges",
                NOX7_CUBE_RANGES,
                "--frontier-top",
                str(args.frontier_top),
                "--candidate-pool",
                str(args.candidate_pool),
                "--top-pairs",
                str(args.top_pairs),
                "--samples-per-pair",
                str(args.samples_per_pair),
                "--max-total",
                str(args.direct_max_total),
                "--workers",
                str(args.workers),
                "--solver-timeout-ms",
                str(args.solver_timeout_ms),
                "--random-assumption-bits",
                str(args.random_assumption_bits),
                "--random-assumption-retries",
                str(args.random_assumption_retries),
                "--frontier-timeout-seconds",
                str(args.frontier_timeout_seconds),
                "--sample-timeout-seconds",
                str(args.sample_timeout_seconds),
                "--qgap-timeout-seconds",
                str(args.direct_qgap_timeout_seconds),
                "--q-gap-epsilon",
                str(args.q_gap_epsilon),
                "--q-gap-max-bits",
                str(args.q_gap_max_bits),
                "--oracle-timeout-seconds",
                str(args.oracle_timeout_seconds),
                "--json",
            ]
            if args.skip_sampler_learned_clauses:
                direct_command.append("--skip-sampler-learned-clauses")
            for projection in args.projection:
                direct_command.extend(["--projection", projection])
            direct_summary_path = direct_dir / "loop_summary.json"
            direct_started = time.time()
            if args.dry_run:
                direct_returncode = None
            else:
                direct_returncode = run_command(
                    direct_command,
                    direct_stdout,
                    direct_stderr,
                    timeout_seconds=args.direct_command_timeout_seconds,
                )
            direct_elapsed = time.time() - direct_started
            direct_summary = load_json(direct_summary_path)
            if not direct_summary:
                direct_summary = read_stdout_json(direct_stdout)
            direct_qgap_jsonl = direct_dir / "iteration_0001_qgap.jsonl"
            step = command_record(
                name="direct",
                command=direct_command,
                returncode=direct_returncode,
                stdout_path=direct_stdout,
                stderr_path=direct_stderr,
                summary_path=direct_summary_path,
                elapsed_seconds=direct_elapsed,
                skipped_reason="dry_run" if args.dry_run else None,
            )
            step["payload_status"] = direct_summary.get("status")
            step["stopped_reason"] = direct_summary.get("stopped_reason")
            step["qgap_jsonl"] = str(direct_qgap_jsonl)
            step["qgap_records"] = (
                (direct_summary.get("records") or [{}])[0].get("qgap_records")
                if isinstance(direct_summary.get("records"), list) and direct_summary.get("records")
                else None
            )
            iteration_record["steps"].append(step)
            if direct_summary.get("success"):
                solved = direct_summary.get("success")
                iteration_record["status"] = "factored"
                stopped_reason = "factored"
                records.append(iteration_record)
                break
            if not args.dry_run and direct_returncode not in {0, 2}:
                iteration_record["status"] = "direct_failed"
                stopped_reason = "direct_failed"
                records.append(iteration_record)
                break
            if not args.dry_run and not direct_qgap_jsonl.exists():
                iteration_record["status"] = "direct_no_qgap_jsonl"
                iteration_record["direct_stopped_reason"] = direct_summary.get("stopped_reason")
                skip_minimization = True

        minimization_specs = []
        if not skip_minimization and args.x2_cumulative_top:
            minimization_specs.append(
                ("cumulative_x2low4", args.x2_cumulative_top, ["150:4", "265:4"])
            )
        if not skip_minimization and args.x3_cumulative_top:
            minimization_specs.append(
                ("cumulative_x3low4", args.x3_cumulative_top, ["150:4", "362:4"])
            )
        for name, top, windows in minimization_specs:
            if args.max_seconds and time.time() - started >= args.max_seconds:
                stopped_reason = "max_seconds"
                break
            min_dir = iteration_dir / name
            min_stdout = iteration_dir / f"{name}.stdout.json"
            min_stderr = iteration_dir / f"{name}.stderr.txt"
            min_summary_path = min_dir / "representative_minimization_summary.json"
            command = minimization_command(
                source_jsonl=direct_qgap_jsonl,
                output_dir=min_dir,
                manifest=manifest,
                top=top,
                start_index=args.cumulative_start_index,
                drop_windows=windows,
                args=args,
            )
            min_started = time.time()
            if args.dry_run:
                returncode = None
            else:
                returncode = run_command(
                    command,
                    min_stdout,
                    min_stderr,
                    timeout_seconds=args.cumulative_command_timeout_seconds,
                )
            min_elapsed = time.time() - min_started
            payload = load_json(min_summary_path)
            if not payload:
                payload = read_stdout_json(min_stdout)
            step = command_record(
                name=name,
                command=command,
                returncode=returncode,
                stdout_path=min_stdout,
                stderr_path=min_stderr,
                summary_path=min_summary_path,
                elapsed_seconds=min_elapsed,
                skipped_reason="dry_run" if args.dry_run else None,
            )
            step["payload_status"] = payload.get("status")
            step["records_completed"] = payload.get("records_completed")
            step["manifest_ledgers"] = payload.get("manifest_ledgers")
            step["success"] = payload.get("success")
            iteration_record["steps"].append(step)
            if payload.get("success"):
                solved = payload.get("success")
                iteration_record["status"] = "factored"
                stopped_reason = "factored"
                break
            if not args.dry_run and returncode not in {0, 2}:
                iteration_record["status"] = f"{name}_failed"
                stopped_reason = iteration_record["status"]
                break
        iteration_record["elapsed_seconds"] = time.time() - iteration_started
        if iteration_record["status"] == "running":
            iteration_record["status"] = "no_factor"
        records.append(iteration_record)
        summary_path.write_text(
            json.dumps(
                {
                    "event": "nox7_cumulative_cycle",
                    "status": "factored" if solved else "running",
                    "stopped_reason": stopped_reason,
                    "output_dir": str(output_dir),
                    "manifest": str(manifest),
                    "elapsed_seconds": time.time() - started,
                    "records": records,
                    "success": solved,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if solved or stopped_reason not in {"completed", "max_seconds"}:
            break

    final_payload = {
        "event": "nox7_cumulative_cycle",
        "status": "factored" if solved else "no_factor",
        "stopped_reason": stopped_reason,
        "output_dir": str(output_dir),
        "manifest": str(manifest),
        "elapsed_seconds": time.time() - started,
        "iterations_completed": len(records),
        "parameters": {
            "iterations": args.iterations,
            "max_seconds": args.max_seconds,
            "seed_base": args.seed_base,
            "cube_ranges": NOX7_CUBE_RANGES,
            "projection": args.projection,
            "direct_max_total": args.direct_max_total,
            "frontier_top": args.frontier_top,
            "candidate_pool": args.candidate_pool,
            "top_pairs": args.top_pairs,
            "samples_per_pair": args.samples_per_pair,
            "workers": args.workers,
            "q_gap_epsilon": args.q_gap_epsilon,
            "q_gap_max_bits": args.q_gap_max_bits,
            "x2_cumulative_top": args.x2_cumulative_top,
            "x3_cumulative_top": args.x3_cumulative_top,
            "skip_sampler_learned_clauses": args.skip_sampler_learned_clauses,
            "cumulative_start_index": args.cumulative_start_index,
            "cumulative_max_completions": args.cumulative_max_completions,
            "dry_run": args.dry_run,
        },
        "records": records,
        "success": solved,
    }
    summary_path.write_text(json.dumps(final_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({**final_payload, "records": f"{len(records)} rows in {summary_path}"}, sort_keys=True))
    else:
        print(
            "status={status} iterations={iterations} stopped={stopped} output={output}".format(
                status=final_payload["status"],
                iterations=final_payload["iterations_completed"],
                stopped=final_payload["stopped_reason"],
                output=summary_path,
            )
        )
    return 0 if solved or args.dry_run else 2


if __name__ == "__main__":
    raise SystemExit(main())
