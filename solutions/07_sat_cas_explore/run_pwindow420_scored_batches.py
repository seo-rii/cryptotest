#!/usr/bin/env python3
"""Iterate pwindow420 free sampling, scoring, and q-gap direct checks."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_pwindow420_scored_loop_{time.strftime('%Y%m%d_%H%M%S')}"
DEFAULT_FRONTIER = WORKSPACE / "tmp" / "ct07_pwindow420_free_frontier_20260607.json"


def read_resume_list(path: Path) -> list[Path]:
    rows: list[Path] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append(Path(line))
    return rows


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def cube_key(row: dict[str, Any]) -> tuple[tuple[int, int, int], ...] | str:
    raw_ranges = row.get("cube_ranges")
    if not isinstance(raw_ranges, list):
        return json.dumps(row, sort_keys=True)
    key: list[tuple[int, int, int]] = []
    for raw_range in raw_ranges:
        if not isinstance(raw_range, dict):
            return json.dumps(row, sort_keys=True)
        key.append(
            (
                int(raw_range["start"]),
                int(raw_range["width"]),
                int(raw_range.get("value", 0)),
            )
        )
    return tuple(key)


def write_manifest(path: Path, ledgers: list[Path]) -> None:
    seen: set[str] = set()
    rows: list[str] = []
    for ledger in ledgers:
        resolved = str(ledger.expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        rows.append(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def ensure_frontier(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event": "pwindow420_free_frontier", "top": [{"assumption_ranges": []}]}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_command(command: list[str], *, stdout_path: Path | None = None) -> tuple[int, str]:
    if stdout_path is None:
        process = subprocess.run(
            command,
            cwd=WORKSPACE,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    else:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("w", encoding="utf-8") as stdout:
            process = subprocess.run(
                command,
                cwd=WORKSPACE,
                text=True,
                stdout=stdout,
                stderr=subprocess.PIPE,
                check=False,
            )
    return process.returncode, process.stderr


def merge_sample_shards(
    *,
    output_dir: Path,
    iteration: int,
    sample_json: Path,
    sample_jsonl: Path,
    shard_jobs: list[dict[str, Any]],
    target_records: int,
    parameters: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    shard_reports: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    seen: set[tuple[tuple[int, int, int], ...] | str] = set()

    for job in shard_jobs:
        shard_json = Path(job["sample_json"])
        payload = json.loads(shard_json.read_text(encoding="utf-8")) if shard_json.exists() else {}
        shard_status_counts = payload.get("status_counts") or {}
        if isinstance(shard_status_counts, dict):
            for key, value in shard_status_counts.items():
                status_counts[str(key)] = status_counts.get(str(key), 0) + int(value)

        for row in payload.get("top") or payload.get("results") or []:
            if not isinstance(row, dict) or row.get("status") != "sat":
                continue
            key = cube_key(row)
            if key in seen:
                continue
            seen.add(key)
            merged = dict(row)
            merged["rank"] = len(rows) + 1
            merged["source_sample_shard"] = int(job["shard_index"])
            rows.append(merged)
            if len(rows) >= target_records:
                break

        shard_reports.append(
            {
                "shard_index": int(job["shard_index"]),
                "returncode": int(job["returncode"]),
                "sample_json": str(shard_json),
                "sample_jsonl": str(job["sample_jsonl"]),
                "records_completed": int(payload.get("records_completed") or 0),
                "status_counts": shard_status_counts,
                "stderr": str(job["stderr_path"]),
            }
        )
        if len(rows) >= target_records:
            break

    if status_counts.get("sat", 0) < len(rows):
        status_counts["sat"] = len(rows)

    payload = {
        "event": "merged_sample_diverse_edge_completions",
        "status": "completed",
        "iteration": iteration,
        "output_dir": str(output_dir),
        "parameters": parameters,
        "shard_reports": shard_reports,
        "records_completed": len(rows),
        "status_counts": status_counts,
        "top": rows,
        "results": rows,
    }
    sample_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with sample_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            print(json.dumps({"event": "sample", **row}, sort_keys=True), file=handle)
        print(
            json.dumps(
                {
                    "event": "summary",
                    "records": len(rows),
                    "status_counts": status_counts,
                    "shards": len(shard_reports),
                },
                sort_keys=True,
            ),
            file=handle,
        )

    first_error = next(
        (int(job["returncode"]) for job in shard_jobs if int(job["returncode"]) != 0),
        0,
    )
    return first_error if len(rows) == 0 else 0, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--frontier", type=Path, default=DEFAULT_FRONTIER)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--sample-shards", type=int, default=1)
    parser.add_argument("--sample-workers", type=int, default=1)
    parser.add_argument("--cube-ranges", default="150:4,265:84,362:58,920:4")
    parser.add_argument("--solver-timeout-ms", type=int, default=10000)
    parser.add_argument("--random-assumption-bits", type=int, default=64)
    parser.add_argument("--random-assumption-retries", type=int, default=32)
    parser.add_argument("--random-seed-base", type=int, default=20260650)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--oracle-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--q-gap-max-seconds", type=float, default=900.0)
    parser.add_argument("--score-max-per-x0", type=int, default=0)
    parser.add_argument("--score-max-per-x7", type=int, default=0)
    parser.add_argument("--score-max-per-x2mid", type=int, default=0)
    parser.add_argument("--score-max-per-x3low", type=int, default=0)
    parser.add_argument("--score-max-per-x3mid", type=int, default=0)
    parser.add_argument("--score-max-per-x3high", type=int, default=0)
    parser.add_argument("--resume-jsonl", action="append", default=[], type=Path)
    parser.add_argument("--resume-list", action="append", default=[], type=Path)
    parser.add_argument(
        "--active-manifest",
        type=Path,
        default=None,
        help="optional manifest seeded with initial ledgers and updated with each new q-gap JSONL",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be positive")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.sample_shards < 1:
        raise SystemExit("--sample-shards must be positive")
    if args.sample_workers < 1:
        raise SystemExit("--sample-workers must be positive")
    if args.solver_timeout_ms < 1:
        raise SystemExit("--solver-timeout-ms must be positive")
    if args.random_assumption_bits < 0:
        raise SystemExit("--random-assumption-bits must be nonnegative")
    if args.random_assumption_retries < 1:
        raise SystemExit("--random-assumption-retries must be positive")
    if args.oracle_timeout_seconds < 0:
        raise SystemExit("--oracle-timeout-seconds must be nonnegative")
    if args.q_gap_max_seconds < 0:
        raise SystemExit("--q-gap-max-seconds must be nonnegative")
    for name in (
        "score_max_per_x0",
        "score_max_per_x7",
        "score_max_per_x2mid",
        "score_max_per_x3low",
        "score_max_per_x3mid",
        "score_max_per_x3high",
    ):
        if int(getattr(args, name)) < 0:
            raise SystemExit(f"--{name.replace('_', '-')} must be nonnegative")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    frontier = args.frontier.expanduser().resolve()
    ensure_frontier(frontier)

    ledgers: list[Path] = []
    for resume_list in args.resume_list:
        ledgers.extend(read_resume_list(resume_list.expanduser()))
    ledgers.extend(args.resume_jsonl)
    ledgers = [path.expanduser().resolve() for path in ledgers]
    active_manifest = (
        args.active_manifest.expanduser().resolve()
        if args.active_manifest is not None
        else output_dir / "active_ledgers.txt"
    )
    write_manifest(active_manifest, ledgers)

    parameters = {
        "iterations": args.iterations,
        "batch_size": args.batch_size,
        "max_seconds": args.max_seconds,
        "workers": args.workers,
        "sample_shards": args.sample_shards,
        "sample_workers": args.sample_workers,
        "cube_ranges": args.cube_ranges,
        "solver_timeout_ms": args.solver_timeout_ms,
        "random_assumption_bits": args.random_assumption_bits,
        "random_assumption_retries": args.random_assumption_retries,
        "random_seed_base": args.random_seed_base,
        "q_gap_epsilon": args.q_gap_epsilon,
        "q_gap_max_bits": args.q_gap_max_bits,
        "oracle_timeout_seconds": args.oracle_timeout_seconds,
        "q_gap_max_seconds": args.q_gap_max_seconds,
        "score_max_per_x0": args.score_max_per_x0,
        "score_max_per_x7": args.score_max_per_x7,
        "score_max_per_x2mid": args.score_max_per_x2mid,
        "score_max_per_x3low": args.score_max_per_x3low,
        "score_max_per_x3mid": args.score_max_per_x3mid,
        "score_max_per_x3high": args.score_max_per_x3high,
        "frontier": str(frontier),
        "initial_ledgers": [str(path) for path in ledgers],
        "active_manifest": str(active_manifest),
    }

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
        sample_json = output_dir / f"iteration_{iteration:04d}_samples.json"
        sample_jsonl = output_dir / f"iteration_{iteration:04d}_samples.jsonl"
        scored_json = output_dir / f"iteration_{iteration:04d}_scored.json"
        qgap_json = output_dir / f"iteration_{iteration:04d}_qgap_direct.json"
        qgap_jsonl = output_dir / f"iteration_{iteration:04d}_qgap_direct.jsonl"

        sample_stdout = output_dir / f"iteration_{iteration:04d}_sample.stdout.json"
        if args.sample_shards == 1:
            sample_command = [
                sys.executable,
                str(HERE / "sample_diverse_edge_completions.py"),
                str(frontier),
                "--resume-list",
                str(active_manifest),
                "--output",
                str(sample_json),
                "--jsonl-output",
                str(sample_jsonl),
                "--top-pairs",
                "1",
                "--samples-per-pair",
                str(args.batch_size),
                "--cube-ranges",
                args.cube_ranges,
                "--solver-timeout-ms",
                str(args.solver_timeout_ms),
                "--random-assumption-bits",
                str(args.random_assumption_bits),
                "--random-assumption-retries",
                str(args.random_assumption_retries),
                "--random-seed",
                str(args.random_seed_base + iteration),
                "--json",
            ]
            sample_returncode, sample_stderr = run_command(sample_command, stdout_path=sample_stdout)
            (output_dir / f"iteration_{iteration:04d}_sample.stderr").write_text(
                sample_stderr,
                encoding="utf-8",
            )
            sample_payload = json.loads(sample_json.read_text(encoding="utf-8")) if sample_json.exists() else {}
        else:
            shard_count = min(args.sample_shards, args.batch_size)
            base_shard_size = args.batch_size // shard_count
            extra_records = args.batch_size % shard_count
            shard_commands: list[dict[str, Any]] = []
            for shard_index in range(1, shard_count + 1):
                shard_size = base_shard_size + (1 if shard_index <= extra_records else 0)
                shard_json = output_dir / f"iteration_{iteration:04d}_sample_shard_{shard_index:04d}.json"
                shard_jsonl = output_dir / f"iteration_{iteration:04d}_sample_shard_{shard_index:04d}.jsonl"
                shard_stdout = output_dir / f"iteration_{iteration:04d}_sample_shard_{shard_index:04d}.stdout.json"
                shard_stderr = output_dir / f"iteration_{iteration:04d}_sample_shard_{shard_index:04d}.stderr"
                shard_commands.append(
                    {
                        "shard_index": shard_index,
                        "sample_json": shard_json,
                        "sample_jsonl": shard_jsonl,
                        "stdout_path": shard_stdout,
                        "stderr_path": shard_stderr,
                        "command": [
                            sys.executable,
                            str(HERE / "sample_diverse_edge_completions.py"),
                            str(frontier),
                            "--resume-list",
                            str(active_manifest),
                            "--output",
                            str(shard_json),
                            "--jsonl-output",
                            str(shard_jsonl),
                            "--top-pairs",
                            "1",
                            "--samples-per-pair",
                            str(shard_size),
                            "--cube-ranges",
                            args.cube_ranges,
                            "--solver-timeout-ms",
                            str(args.solver_timeout_ms),
                            "--random-assumption-bits",
                            str(args.random_assumption_bits),
                            "--random-assumption-retries",
                            str(args.random_assumption_retries),
                            "--random-seed",
                            str(args.random_seed_base + iteration * 1000 + shard_index),
                            "--json",
                        ],
                    }
                )

            def run_shard(job: dict[str, Any]) -> dict[str, Any]:
                returncode, stderr = run_command(
                    job["command"],
                    stdout_path=Path(job["stdout_path"]),
                )
                Path(job["stderr_path"]).write_text(stderr, encoding="utf-8")
                return {**job, "returncode": returncode}

            completed_shards: list[dict[str, Any]] = []
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(args.sample_workers, shard_count)
            ) as executor:
                futures = [executor.submit(run_shard, job) for job in shard_commands]
                for future in concurrent.futures.as_completed(futures):
                    completed_shards.append(future.result())
            completed_shards.sort(key=lambda item: int(item["shard_index"]))
            sample_returncode, sample_payload = merge_sample_shards(
                output_dir=output_dir,
                iteration=iteration,
                sample_json=sample_json,
                sample_jsonl=sample_jsonl,
                shard_jobs=completed_shards,
                target_records=args.batch_size,
                parameters={
                    "sample_shards": shard_count,
                    "sample_workers": args.sample_workers,
                    "batch_size": args.batch_size,
                    "solver_timeout_ms": args.solver_timeout_ms,
                    "random_assumption_bits": args.random_assumption_bits,
                    "random_assumption_retries": args.random_assumption_retries,
                    "random_seed_base": args.random_seed_base,
                },
            )
            sample_stdout.write_text(
                json.dumps(
                    {
                        "event": "parallel_sample_merge",
                        "records_completed": sample_payload.get("records_completed", 0),
                        "shards": len(completed_shards),
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (output_dir / f"iteration_{iteration:04d}_sample.stderr").write_text(
                "\n".join(
                    str(job["stderr_path"])
                    for job in completed_shards
                    if int(job["returncode"]) != 0
                ),
                encoding="utf-8",
            )
        sample_records = int(sample_payload.get("records_completed") or 0)
        if sample_returncode != 0 or sample_records == 0:
            record = {
                "iteration": iteration,
                "elapsed_seconds": time.time() - iteration_started,
                "sample_returncode": sample_returncode,
                "sample_json": str(sample_json),
                "sample_jsonl": str(sample_jsonl),
                "sample_records": sample_records,
                "sample_status_counts": sample_payload.get("status_counts"),
                "status": "sample_failed" if sample_returncode != 0 else "sample_empty",
            }
            records.append(record)
            stopped_reason = record["status"]
            break

        score_command = [
            sys.executable,
            str(HERE / "score_selected_cube_samples.py"),
            str(sample_json),
            "--output",
            str(scored_json),
            "--top",
            str(sample_records),
            "--json",
        ]
        for option_name, value in (
            ("--max-per-x0", args.score_max_per_x0),
            ("--max-per-x7", args.score_max_per_x7),
            ("--max-per-x2mid", args.score_max_per_x2mid),
            ("--max-per-x3low", args.score_max_per_x3low),
            ("--max-per-x3mid", args.score_max_per_x3mid),
            ("--max-per-x3high", args.score_max_per_x3high),
        ):
            if value:
                score_command.extend([option_name, str(value)])
        score_stdout = output_dir / f"iteration_{iteration:04d}_score.stdout.json"
        score_returncode, score_stderr = run_command(score_command, stdout_path=score_stdout)
        (output_dir / f"iteration_{iteration:04d}_score.stderr").write_text(
            score_stderr,
            encoding="utf-8",
        )
        scored_payload = json.loads(scored_json.read_text(encoding="utf-8")) if scored_json.exists() else {}
        scored_records = int(scored_payload.get("retained_records") or 0)
        if score_returncode != 0 or scored_records == 0:
            record = {
                "iteration": iteration,
                "elapsed_seconds": time.time() - iteration_started,
                "sample_returncode": sample_returncode,
                "sample_records": sample_records,
                "score_returncode": score_returncode,
                "scored_json": str(scored_json),
                "scored_records": scored_records,
                "status": "score_failed" if score_returncode != 0 else "score_empty",
            }
            records.append(record)
            stopped_reason = record["status"]
            break

        qgap_command = [
            sys.executable,
            str(HERE / "run_ranked_q_gap_direct.py"),
            str(scored_json),
            "--output",
            str(qgap_json),
            "--jsonl-output",
            str(qgap_jsonl),
            "--top",
            str(scored_records),
            "--workers",
            str(args.workers),
            "--q-gap-epsilon",
            str(args.q_gap_epsilon),
            "--q-gap-max-bits",
            str(args.q_gap_max_bits),
            "--oracle-timeout-seconds",
            str(args.oracle_timeout_seconds),
            "--max-seconds",
            str(args.q_gap_max_seconds),
            "--json",
        ]
        qgap_stdout = output_dir / f"iteration_{iteration:04d}_qgap.stdout.json"
        qgap_returncode, qgap_stderr = run_command(qgap_command, stdout_path=qgap_stdout)
        (output_dir / f"iteration_{iteration:04d}_qgap.stderr").write_text(
            qgap_stderr,
            encoding="utf-8",
        )
        qgap_payload = json.loads(qgap_json.read_text(encoding="utf-8")) if qgap_json.exists() else {}
        qgap_rows = jsonl_rows(qgap_jsonl) if qgap_jsonl.exists() else []
        qgap_status_counts = qgap_payload.get("status_counts") or {}
        factors = [
            row
            for row in qgap_rows
            if row.get("event") == "cube"
            and (row.get("q_gap_coppersmith") or {}).get("factors")
        ]
        record = {
            "iteration": iteration,
            "elapsed_seconds": time.time() - iteration_started,
            "sample_returncode": sample_returncode,
            "sample_records": sample_records,
            "sample_status_counts": sample_payload.get("status_counts"),
            "score_returncode": score_returncode,
            "scored_records": scored_records,
            "qgap_returncode": qgap_returncode,
            "qgap_json": str(qgap_json),
            "qgap_jsonl": str(qgap_jsonl),
            "qgap_records_completed": qgap_payload.get("records_completed"),
            "qgap_status_counts": qgap_status_counts,
            "qgap_stopped_reason": qgap_payload.get("stopped_reason"),
            "factors": factors,
            "status": "factored" if factors else "no_factor",
        }
        records.append(record)
        if factors:
            success = record
            stopped_reason = "factored"
            break
        if qgap_returncode not in {0, 2}:
            stopped_reason = "qgap_failed"
            break
        ledgers.append(qgap_jsonl.resolve())
        write_manifest(active_manifest, ledgers)

        summary_path.write_text(
            json.dumps(
                {
                    "event": "pwindow420_scored_batches",
                    "status": "running",
                    "output_dir": str(output_dir),
                    "elapsed_seconds": time.time() - started,
                    "parameters": parameters,
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
        "event": "pwindow420_scored_batches",
        "status": "factored" if success else "no_factor",
        "stopped_reason": stopped_reason,
        "output_dir": str(output_dir),
        "elapsed_seconds": time.time() - started,
        "iterations_completed": len(records),
        "parameters": parameters,
        "active_manifest": str(active_manifest),
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
                stopped=stopped_reason,
                output=summary_path,
            )
        )
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
