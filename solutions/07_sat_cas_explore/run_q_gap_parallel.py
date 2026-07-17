#!/usr/bin/env python3
"""Run q middle-gap Coppersmith candidate ranges in parallel."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from branch_q_gap_coppersmith import DEFAULT_CANDIDATE_JSONS, load_candidates


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def candidate_chunks(start: int, stop: int, chunk_size: int) -> list[tuple[int, int]]:
    chunks: list[tuple[int, int]] = []
    current = start
    while current <= stop:
        end = min(stop, current + chunk_size - 1)
        chunks.append((current, end))
        current = end + 1
    return chunks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-json", action="append", type=Path, default=[])
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "tmp" / f"ct07_q_gap_parallel_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--candidate-start", type=int, default=1)
    parser.add_argument("--candidate-stop", type=int, default=0)
    parser.add_argument("--chunk-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-gap-bits", type=int, default=520)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--oracle-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--no-pdf-check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.candidate_start < 1:
        raise SystemExit("--candidate-start must be at least 1")
    if args.candidate_stop and args.candidate_stop < args.candidate_start:
        raise SystemExit("--candidate-stop must be 0 or at least --candidate-start")
    if args.chunk_size < 1:
        raise SystemExit("--chunk-size must be positive")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.oracle_timeout_seconds < 0:
        raise SystemExit("--oracle-timeout-seconds must be nonnegative")
    args.output_dir = args.output_dir.expanduser().resolve()

    candidate_paths = [
        path.expanduser().resolve() for path in (args.candidate_json or DEFAULT_CANDIDATE_JSONS)
    ]
    all_candidates, source_summaries = load_candidates(candidate_paths, 0)
    if not all_candidates:
        raise SystemExit("no candidates loaded")
    stop = args.candidate_stop or len(all_candidates)
    stop = min(stop, len(all_candidates))
    chunks = candidate_chunks(args.candidate_start, stop, args.chunk_size)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    specs: list[dict[str, Any]] = []
    for start, end in chunks:
        command = [
            sys.executable,
            "-B",
            str(HERE / "branch_q_gap_coppersmith.py"),
            "--candidate-start",
            str(start),
            "--candidate-stop",
            str(end),
            "--summary-json",
            str(args.output_dir / f"q_gap_{start}_{end}.json"),
            "--max-gap-bits",
            str(args.max_gap_bits),
            "--epsilon",
            str(args.epsilon),
            "--min-hard-margin-bits",
            str(args.min_hard_margin_bits),
            "--oracle-timeout-seconds",
            str(args.oracle_timeout_seconds),
        ]
        if args.no_pdf_check:
            command.append("--no-pdf-check")
        for candidate_path in candidate_paths:
            command.extend(["--candidate-json", str(candidate_path)])
        specs.append(
            {
                "candidate_start": start,
                "candidate_stop": end,
                "summary_json": str(args.output_dir / f"q_gap_{start}_{end}.json"),
                "stdout_path": str(args.output_dir / f"q_gap_{start}_{end}.stdout"),
                "stderr_path": str(args.output_dir / f"q_gap_{start}_{end}.stderr"),
                "command": command,
                "command_text": shlex.join(command),
            }
        )

    started = time.time()

    def run_spec(spec: dict[str, Any]) -> dict[str, Any]:
        stdout_path = Path(spec["stdout_path"])
        stderr_path = Path(spec["stderr_path"])
        chunk_started = time.time()
        try:
            process = subprocess.run(
                spec["command"],
                cwd=ROOT,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=args.timeout_seconds,
                check=False,
            )
            stdout_path.write_text(process.stdout, encoding="utf-8")
            stderr_path.write_text(process.stderr, encoding="utf-8")
            return {
                **spec,
                "status": "ok" if process.returncode in {0, 2} else "process_error",
                "returncode": process.returncode,
                "elapsed_seconds": time.time() - chunk_started,
            }
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(exc.stdout if isinstance(exc.stdout, str) else "", encoding="utf-8")
            stderr_path.write_text(exc.stderr if isinstance(exc.stderr, str) else "", encoding="utf-8")
            return {
                **spec,
                "status": "timeout",
                "returncode": None,
                "elapsed_seconds": time.time() - chunk_started,
            }

    chunk_results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.workers, len(specs))) as executor:
        futures = [executor.submit(run_spec, spec) for spec in specs]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            meta_path = args.output_dir / f"q_gap_{result['candidate_start']}_{result['candidate_stop']}.meta.json"
            meta_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
            result["meta_path"] = str(meta_path)
            chunk_results.append(result)

    rows: list[dict[str, Any]] = []
    chunk_summaries: list[dict[str, Any]] = []
    for result in sorted(chunk_results, key=lambda item: item["candidate_start"]):
        summary_path = Path(result["summary_json"])
        if not summary_path.exists():
            chunk_summaries.append({**result, "summary_status": "missing"})
            continue
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        chunk_summaries.append(
            {
                **result,
                "summary_status": data.get("status"),
                "candidates_tested": data.get("candidates_tested"),
                "factors_total": data.get("factors_total"),
                "hard_no_roots": data.get("hard_no_roots"),
                "status_counts": data.get("status_counts"),
                "q_gap_distribution": data.get("q_gap_distribution"),
            }
        )
        rows.extend(data.get("results", []))

    status_counts: dict[str, int] = {}
    gap_distribution: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        if "q_gap_bits" in row:
            key = str(row["q_gap_bits"])
            gap_distribution[key] = gap_distribution.get(key, 0) + 1

    payload = {
        "event": "q_gap_parallel",
        "status": "factored" if any(row.get("status") == "factored" for row in rows) else "no_factor",
        "output_dir": str(args.output_dir),
        "candidate_paths": [str(path) for path in candidate_paths],
        "source_summaries": source_summaries,
        "parameters": {
            "candidate_start": args.candidate_start,
            "candidate_stop": args.candidate_stop,
            "candidate_total_loaded": len(all_candidates),
            "chunk_size": args.chunk_size,
            "workers": args.workers,
            "max_gap_bits": args.max_gap_bits,
            "epsilon": args.epsilon,
            "min_hard_margin_bits": args.min_hard_margin_bits,
            "oracle_timeout_seconds": args.oracle_timeout_seconds,
            "timeout_seconds": args.timeout_seconds,
        },
        "elapsed_seconds": time.time() - started,
        "chunks": chunk_summaries,
        "candidates_tested": len(rows),
        "status_counts": status_counts,
        "q_gap_distribution": gap_distribution,
        "roots_total": sum(int(row.get("roots_returned", 0) or 0) for row in rows),
        "factors_total": sum(len(row.get("factors", []) or []) for row in rows),
        "hard_no_roots": sum(1 for row in rows if row.get("no_root_hard_clause_eligible")),
        "success": next((row for row in rows if row.get("status") == "factored"), None),
        "results": rows,
    }
    summary_path = args.output_dir / "q_gap_parallel_summary.json"
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    payload["summary_path"] = str(summary_path)

    console_payload = dict(payload)
    console_payload["results"] = f"{len(rows)} rows written to {summary_path}"
    if args.json:
        print(json.dumps(console_payload, sort_keys=True))
    else:
        print(
            "status={status} candidates={candidates} factors={factors} hard_no_roots={hard_no_roots} summary={summary}".format(
                status=payload["status"],
                candidates=payload["candidates_tested"],
                factors=payload["factors_total"],
                hard_no_roots=payload["hard_no_roots"],
                summary=summary_path,
            )
        )
    return 0 if payload["status"] == "factored" else 2


if __name__ == "__main__":
    raise SystemExit(main())
