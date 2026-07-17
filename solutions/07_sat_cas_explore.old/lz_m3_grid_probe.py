#!/usr/bin/env python3
"""Bounded m=3 grid probe for LZ unknown-divisor pruning signals.

This script keeps the broader lz_prune_grid.py shape, but fixes the lattice
degree to m=3 and focuses on the active-variable subsets that previously showed
relation-count signals without sampled pruning wins.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_ACTIVE_SUBSETS = "x0,x1,x2,x3;x0,x1,x6,x7;x0,x1,x2,x7"


def run_subset(
    active_subset: str,
    samples: int,
    timeout_seconds: float,
    script_dir: Path,
) -> dict[str, Any]:
    search_script = script_dir / "lz_prune_search.py"
    command = [
        sys.executable,
        "-B",
        str(search_script),
        "--active-subsets",
        active_subset,
        "--m-values",
        "3",
        "--t-values",
        "1",
        "--samples",
        str(samples),
        "--timeout-seconds",
        str(timeout_seconds),
        "--jobs",
        "1",
        "--max-candidates",
        "1",
        "--json",
    ]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=script_dir,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds + 3.0,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        return {
            "active_subset": active_subset,
            "status": "chunk_timeout",
            "elapsed_seconds": round(elapsed, 4),
            "results": [],
            "skipped": [],
            "stdout_tail": (exc.stdout or "")[-500:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-500:] if isinstance(exc.stderr, str) else "",
            "command": command,
        }

    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        return {
            "active_subset": active_subset,
            "status": "chunk_failed",
            "returncode": proc.returncode,
            "elapsed_seconds": round(elapsed, 4),
            "results": [],
            "skipped": [],
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
            "command": command,
        }

    payload = None
    for line in reversed(proc.stdout.splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            payload = json.loads(text)
            break
        except json.JSONDecodeError:
            continue
    if payload is None:
        return {
            "active_subset": active_subset,
            "status": "chunk_json_parse_failed",
            "elapsed_seconds": round(elapsed, 4),
            "results": [],
            "skipped": [],
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
            "command": command,
        }

    return {
        "active_subset": active_subset,
        "status": "ok",
        "elapsed_seconds": round(elapsed, 4),
        "results": payload.get("results", []),
        "skipped": payload.get("skipped", []),
        "best": payload.get("best"),
        "command": command,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--active-subsets",
        default=DEFAULT_ACTIVE_SUBSETS,
        help=(
            "semicolon-separated active sets; default is "
            "'x0,x1,x2,x3;x0,x1,x6,x7;x0,x1,x2,x7'"
        ),
    )
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=24.0)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")

    active_subsets = []
    for group in args.active_subsets.split(";"):
        names = [part.strip() for part in group.split(",") if part.strip()]
        if not names:
            continue
        if len(set(names)) != len(names):
            raise SystemExit(f"--active-subsets contains a duplicate variable: {group}")
        active_subsets.append(",".join(names))
    if not active_subsets:
        raise SystemExit("--active-subsets must contain at least one subset")

    script_dir = Path(__file__).resolve().parent
    chunks: list[dict[str, Any]] = []
    workers = min(args.jobs, len(active_subsets)) if active_subsets else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(
                run_subset,
                active_subset,
                args.samples,
                args.timeout_seconds,
                script_dir,
            ): index
            for index, active_subset in enumerate(active_subsets)
        }
        ordered: dict[int, dict[str, Any]] = {}
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            ordered[index] = future.result()
        for index in range(len(active_subsets)):
            chunks.append(ordered[index])

    results = [item for chunk in chunks for item in chunk.get("results", [])]
    skipped = [item for chunk in chunks for item in chunk.get("skipped", [])]
    chunk_status_counts = Counter(str(chunk.get("status")) for chunk in chunks)
    result_status_counts = Counter(str(item.get("status")) for item in results)
    relation_counts_by_subset = {
        ",".join(item.get("active", [])): int(item.get("relation_count", 0))
        for item in results
    }
    derived_status_by_subset = {
        ",".join(item.get("active", [])): item.get(
            "identically_derived_under_projection"
        )
        for item in results
    }
    extra_prune_count = sum(
        1 for item in results if bool(item.get("extra_modular_prune_seen"))
    )
    timeout_count = int(
        chunk_status_counts["chunk_timeout"] + result_status_counts["timeout"]
    )
    error_statuses = {
        "failed",
        "json_parse_failed",
        "chunk_failed",
        "chunk_json_parse_failed",
    }
    error_count = sum(chunk_status_counts[status] for status in error_statuses)
    error_count += sum(result_status_counts[status] for status in error_statuses)
    best = None
    if results:
        best = max(
            results,
            key=lambda item: (
                int(item.get("prune_score", 0)),
                int(item.get("relation_count", 0)),
                -float(item.get("elapsed_seconds", 0.0)),
            ),
        )

    report = {
        "config": {
            "active_subsets": active_subsets,
            "m": 3,
            "samples": args.samples,
            "timeout_seconds": args.timeout_seconds,
            "jobs": args.jobs,
        },
        "summary": {
            "grid_points": len(active_subsets),
            "result_count": len(results),
            "skipped_count": len(skipped),
            "chunk_status_counts": dict(sorted(chunk_status_counts.items())),
            "result_status_counts": dict(sorted(result_status_counts.items())),
            "relation_counts_by_subset": relation_counts_by_subset,
            "derived_status_by_subset": derived_status_by_subset,
            "extra_prune_count": int(extra_prune_count),
            "timeout_count": timeout_count,
            "error_count": int(error_count),
            "best_prune_score": int(best.get("prune_score", 0)) if best else 0,
            "best": best,
        },
        "results": results,
        "skipped": skipped,
        "chunks": chunks,
    }

    if args.json:
        print(json.dumps(report, sort_keys=True))
        return 0

    summary = report["summary"]
    print(
        "summary: "
        f"grid_points={summary['grid_points']} "
        f"results={summary['result_count']} "
        f"best_prune_score={summary['best_prune_score']} "
        f"extra_prune_count={summary['extra_prune_count']} "
        f"timeouts={summary['timeout_count']} "
        f"errors={summary['error_count']}"
    )
    print("active status rels score signal derived extra_prune elapsed")
    for item in results:
        active = ",".join(item.get("active", []))
        print(
            f"{active} {item.get('status')} "
            f"{item.get('relation_count')} {item.get('prune_score')} "
            f"{item.get('signal')} "
            f"{item.get('identically_derived_under_projection')} "
            f"{item.get('extra_modular_prune_seen')} "
            f"{item.get('elapsed_seconds')}"
        )
    for chunk in chunks:
        if chunk.get("status") != "ok":
            print(
                "chunk: "
                f"active={chunk.get('active_subset')} "
                f"status={chunk.get('status')} "
                f"elapsed={chunk.get('elapsed_seconds')}"
            )
    if best:
        print(
            "best: "
            f"active={','.join(best.get('active', []))} "
            f"score={best.get('prune_score')} "
            f"signal={best.get('signal')} "
            f"derived={best.get('identically_derived_under_projection')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
