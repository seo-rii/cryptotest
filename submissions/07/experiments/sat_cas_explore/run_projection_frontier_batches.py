#!/usr/bin/env python3
"""Iterate projection-novelty pwindow420 sampling and q-gap direct checks."""

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
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_projection_frontier_batches_{time.strftime('%Y%m%d_%H%M%S')}"


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


def run_command(
    command: list[str],
    stdout_path: Path,
    *,
    timeout_seconds: float = 0.0,
) -> tuple[int, str]:
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
            return 124, (stderr or "") + f"\ncommand timed out after {timeout_seconds:.1f}s\n"
    return int(process.returncode), stderr or ""


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--seed-base", type=int, default=20260610)
    parser.add_argument("--frontier-top", type=int, default=256)
    parser.add_argument("--candidate-pool", type=int, default=32768)
    parser.add_argument("--top-pairs", type=int, default=128)
    parser.add_argument("--samples-per-pair", type=int, default=2)
    parser.add_argument("--max-total", type=int, default=256)
    parser.add_argument("--cube-ranges", default="150:4,265:84,362:58,920:4")
    parser.add_argument("--solver-timeout-ms", type=int, default=5000)
    parser.add_argument("--random-assumption-bits", type=int, default=64)
    parser.add_argument("--random-assumption-retries", type=int, default=16)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--oracle-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--frontier-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--sample-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--qgap-timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--skip-sampler-learned-clauses",
        action="store_true",
        help="pass --skip-learned-clauses to sample_diverse_edge_completions.py",
    )
    parser.add_argument(
        "--projection",
        action="append",
        default=[],
        help="optional START:WIDTH[:LABEL] projection; repeat to override defaults",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")
    if args.frontier_top < 1:
        raise SystemExit("--frontier-top must be positive")
    if args.candidate_pool < args.frontier_top:
        raise SystemExit("--candidate-pool must be at least --frontier-top")
    if args.top_pairs < 1:
        raise SystemExit("--top-pairs must be positive")
    if args.samples_per_pair < 1:
        raise SystemExit("--samples-per-pair must be positive")
    if args.max_total < 1:
        raise SystemExit("--max-total must be positive")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.solver_timeout_ms < 1:
        raise SystemExit("--solver-timeout-ms must be positive")
    if args.random_assumption_bits < 0:
        raise SystemExit("--random-assumption-bits must be nonnegative")
    if args.random_assumption_retries < 1:
        raise SystemExit("--random-assumption-retries must be positive")
    if args.oracle_timeout_seconds < 0:
        raise SystemExit("--oracle-timeout-seconds must be nonnegative")
    if args.frontier_timeout_seconds < 0:
        raise SystemExit("--frontier-timeout-seconds must be nonnegative")
    if args.sample_timeout_seconds < 0:
        raise SystemExit("--sample-timeout-seconds must be nonnegative")
    if args.qgap_timeout_seconds < 0:
        raise SystemExit("--qgap-timeout-seconds must be nonnegative")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = args.manifest.expanduser()
    started = time.time()
    records: list[dict[str, Any]] = []
    success = None
    stopped_reason = "completed"
    summary_path = output_dir / "loop_summary.json"

    for iteration in range(1, args.iterations + 1):
        if args.max_seconds and time.time() - started >= args.max_seconds:
            stopped_reason = "max_seconds"
            break
        iteration_started = time.time()
        seed = args.seed_base + iteration
        frontier_json = output_dir / f"iteration_{iteration:04d}_frontier.json"
        sample_json = output_dir / f"iteration_{iteration:04d}_samples.json"
        sample_jsonl = output_dir / f"iteration_{iteration:04d}_samples.jsonl"
        qgap_json = output_dir / f"iteration_{iteration:04d}_qgap.json"
        qgap_jsonl = output_dir / f"iteration_{iteration:04d}_qgap.jsonl"

        frontier_command = [
            sys.executable,
            str(HERE / "build_projection_frontier.py"),
            "--manifest",
            str(manifest),
            "--output",
            str(frontier_json),
            "--top",
            str(args.frontier_top),
            "--candidate-pool",
            str(args.candidate_pool),
            "--max-seen-count",
            "0",
            "--prefer-unseen",
            "--seed",
            str(seed),
            "--json",
        ]
        for projection in args.projection:
            frontier_command.extend(["--projection", projection])
        frontier_returncode, frontier_stderr = run_command(
            frontier_command,
            output_dir / f"iteration_{iteration:04d}_frontier.stdout.json",
            timeout_seconds=args.frontier_timeout_seconds,
        )
        (output_dir / f"iteration_{iteration:04d}_frontier.stderr").write_text(
            frontier_stderr,
            encoding="utf-8",
        )
        frontier_payload = load_json(frontier_json)
        frontier_records = len(frontier_payload.get("top") or [])
        if frontier_returncode != 0 or frontier_records == 0:
            record = {
                "iteration": iteration,
                "status": "frontier_failed" if frontier_returncode != 0 else "frontier_empty",
                "elapsed_seconds": time.time() - iteration_started,
                "frontier_returncode": frontier_returncode,
                "frontier_records": frontier_records,
                "frontier_json": str(frontier_json),
            }
            records.append(record)
            stopped_reason = record["status"]
            break

        sample_command = [
            sys.executable,
            str(HERE / "sample_diverse_edge_completions.py"),
            str(frontier_json),
            "--output",
            str(sample_json),
            "--jsonl-output",
            str(sample_jsonl),
            "--top-pairs",
            str(args.top_pairs),
            "--samples-per-pair",
            str(args.samples_per_pair),
            "--max-total",
            str(args.max_total),
            "--cube-ranges",
            args.cube_ranges,
            "--solver-timeout-ms",
            str(args.solver_timeout_ms),
            "--random-assumption-bits",
            str(args.random_assumption_bits),
            "--random-assumption-retries",
            str(args.random_assumption_retries),
            "--random-seed",
            str(seed),
            "--resume-list",
            str(manifest),
            "--json",
        ]
        if args.skip_sampler_learned_clauses:
            sample_command.append("--skip-learned-clauses")
        sample_returncode, sample_stderr = run_command(
            sample_command,
            output_dir / f"iteration_{iteration:04d}_sample.stdout.json",
            timeout_seconds=args.sample_timeout_seconds,
        )
        (output_dir / f"iteration_{iteration:04d}_sample.stderr").write_text(
            sample_stderr,
            encoding="utf-8",
        )
        sample_payload = load_json(sample_json)
        sample_records = int(sample_payload.get("records_completed") or 0)
        if sample_returncode != 0 or sample_records == 0:
            record = {
                "iteration": iteration,
                "status": "sample_failed" if sample_returncode != 0 else "sample_empty",
                "elapsed_seconds": time.time() - iteration_started,
                "frontier_records": frontier_records,
                "sample_returncode": sample_returncode,
                "sample_records": sample_records,
                "sample_status_counts": sample_payload.get("status_counts"),
                "frontier_json": str(frontier_json),
                "sample_json": str(sample_json),
            }
            records.append(record)
            stopped_reason = record["status"]
            break

        qgap_command = [
            sys.executable,
            str(HERE / "run_ranked_q_gap_direct.py"),
            str(sample_json),
            "--output",
            str(qgap_json),
            "--jsonl-output",
            str(qgap_jsonl),
            "--top",
            str(sample_records),
            "--workers",
            str(args.workers),
            "--q-gap-epsilon",
            str(args.q_gap_epsilon),
            "--q-gap-max-bits",
            str(args.q_gap_max_bits),
            "--oracle-timeout-seconds",
            str(args.oracle_timeout_seconds),
            "--json",
        ]
        qgap_returncode, qgap_stderr = run_command(
            qgap_command,
            output_dir / f"iteration_{iteration:04d}_qgap.stdout.json",
            timeout_seconds=args.qgap_timeout_seconds,
        )
        (output_dir / f"iteration_{iteration:04d}_qgap.stderr").write_text(
            qgap_stderr,
            encoding="utf-8",
        )
        qgap_payload = load_json(qgap_json)
        qgap_records = int(qgap_payload.get("records_completed") or 0)
        factors = [
            record
            for record in qgap_payload.get("records", [])
            if isinstance(record, dict) and record.get("factors")
        ]
        record = {
            "iteration": iteration,
            "status": "factored" if factors else "no_factor",
            "elapsed_seconds": time.time() - iteration_started,
            "seed": seed,
            "frontier_records": frontier_records,
            "frontier_unique_seen_projection_keys": frontier_payload.get(
                "unique_seen_projection_keys"
            ),
            "sample_records": sample_records,
            "sample_status_counts": sample_payload.get("status_counts"),
            "qgap_returncode": qgap_returncode,
            "qgap_records": qgap_records,
            "qgap_status_counts": qgap_payload.get("status_counts"),
            "frontier_json": str(frontier_json),
            "sample_json": str(sample_json),
            "sample_jsonl": str(sample_jsonl),
            "qgap_json": str(qgap_json),
            "qgap_jsonl": str(qgap_jsonl),
            "factors": factors,
        }
        records.append(record)
        if qgap_records:
            append_manifest_entries(manifest, [qgap_jsonl])
        if factors:
            success = record
            stopped_reason = "factored"
            break
        if qgap_returncode not in {0, 2}:
            stopped_reason = "qgap_failed"
            break

        summary_path.write_text(
            json.dumps(
                {
                    "event": "projection_frontier_batches",
                    "status": "running",
                    "output_dir": str(output_dir),
                    "manifest": str(manifest),
                    "elapsed_seconds": time.time() - started,
                    "records": records,
                    "success": success,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    final_payload = {
        "event": "projection_frontier_batches",
        "status": "factored" if success else "no_factor",
        "stopped_reason": stopped_reason,
        "output_dir": str(output_dir),
        "manifest": str(manifest),
        "elapsed_seconds": time.time() - started,
        "iterations_completed": len(records),
        "parameters": {
            "iterations": args.iterations,
            "max_seconds": args.max_seconds,
            "seed_base": args.seed_base,
            "frontier_top": args.frontier_top,
            "candidate_pool": args.candidate_pool,
            "top_pairs": args.top_pairs,
            "samples_per_pair": args.samples_per_pair,
            "max_total": args.max_total,
            "cube_ranges": args.cube_ranges,
            "solver_timeout_ms": args.solver_timeout_ms,
            "random_assumption_bits": args.random_assumption_bits,
            "random_assumption_retries": args.random_assumption_retries,
            "workers": args.workers,
            "q_gap_epsilon": args.q_gap_epsilon,
            "q_gap_max_bits": args.q_gap_max_bits,
            "oracle_timeout_seconds": args.oracle_timeout_seconds,
            "frontier_timeout_seconds": args.frontier_timeout_seconds,
            "sample_timeout_seconds": args.sample_timeout_seconds,
            "qgap_timeout_seconds": args.qgap_timeout_seconds,
            "skip_sampler_learned_clauses": args.skip_sampler_learned_clauses,
            "projection": args.projection,
        },
        "records": records,
        "success": success,
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
                output=output_dir,
            )
        )
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
