#!/usr/bin/env python3
"""Bounded grid runner for LZ pruning probes.

This wrapper runs lz_prune_search.py over a larger active-subset/m grid while
keeping each grid point isolated behind a subprocess timeout.  It is intended
to answer one narrow question: did any sampled relation become both
non-projection-derived and useful as a pruning signal?
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_ACTIVE_SUBSETS = (
    "x0,x1,x2,x3;"
    "x0,x1,x2,x6;"
    "x0,x1,x6,x7;"
    "x0,x4,x6,x7"
)


@dataclass(frozen=True)
class GridPoint:
    active_subset: str
    m_value: int


def parse_active_subsets(raw: str) -> list[str]:
    subsets: list[str] = []
    for group in raw.split(";"):
        names = [part.strip() for part in group.split(",") if part.strip()]
        if not names:
            continue
        if len(set(names)) != len(names):
            raise SystemExit(f"--active-subsets contains a duplicate variable: {group}")
        subsets.append(",".join(names))
    if not subsets:
        raise SystemExit("--active-subsets must contain at least one subset")
    return subsets


def parse_m_values(raw: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            value = int(item, 0)
        except ValueError as exc:
            raise SystemExit(f"--m-values contains a non-integer value: {item}") from exc
        if value not in (2, 3):
            raise SystemExit("--m-values currently supports only 2 and 3")
        values.append(value)
    if not values:
        raise SystemExit("--m-values must contain at least one value")
    return values


def extract_json(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in lz_prune_search.py stdout")


def run_grid_point(
    point: GridPoint,
    args: argparse.Namespace,
    script_dir: Path,
) -> dict[str, Any]:
    search_script = script_dir / "lz_prune_search.py"
    command = [
        sys.executable,
        "-B",
        str(search_script),
        "--active-subsets",
        point.active_subset,
        "--m-values",
        str(point.m_value),
        "--t-values",
        "1",
        "--samples",
        str(args.samples),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--jobs",
        "1",
        "--max-candidates",
        "1",
        "--json",
    ]
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    start = time.monotonic()
    wrapper_timeout = args.timeout_seconds + args.chunk_grace_seconds
    try:
        proc = subprocess.run(
            command,
            cwd=script_dir,
            env=env,
            text=True,
            capture_output=True,
            timeout=wrapper_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        return {
            "active_subset": point.active_subset,
            "m": point.m_value,
            "status": "chunk_timeout",
            "elapsed_seconds": round(elapsed, 4),
            "timeout_seconds": wrapper_timeout,
            "results": [],
            "skipped": [],
            "stdout_tail": (exc.stdout or "")[-500:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-500:] if isinstance(exc.stderr, str) else "",
            "command": command,
        }

    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        return {
            "active_subset": point.active_subset,
            "m": point.m_value,
            "status": "chunk_failed",
            "returncode": proc.returncode,
            "elapsed_seconds": round(elapsed, 4),
            "results": [],
            "skipped": [],
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
            "command": command,
        }

    try:
        payload = extract_json(proc.stdout)
    except ValueError as exc:
        return {
            "active_subset": point.active_subset,
            "m": point.m_value,
            "status": "chunk_json_parse_failed",
            "elapsed_seconds": round(elapsed, 4),
            "error": str(exc),
            "results": [],
            "skipped": [],
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
            "command": command,
        }

    return {
        "active_subset": point.active_subset,
        "m": point.m_value,
        "status": "ok",
        "elapsed_seconds": round(elapsed, 4),
        "results": payload.get("results", []),
        "skipped": payload.get("skipped", []),
        "best": payload.get("best"),
        "command": command,
    }


def result_modular_prune_hits(item: dict[str, Any]) -> int:
    hit_counts = item.get("sample_hit_counts") or {}
    return int(hit_counts.get("modular_prune_hits", 0))


def is_nonderived_relation(item: dict[str, Any]) -> bool:
    return (
        item.get("status") == "ok"
        and int(item.get("relation_count", 0)) > 0
        and item.get("identically_derived_under_projection") is False
    )


def is_nonderived_prune_signal(item: dict[str, Any]) -> bool:
    return is_nonderived_relation(item) and (
        bool(item.get("extra_modular_prune_seen"))
        or result_modular_prune_hits(item) > 0
    )


def summarize(chunks: list[dict[str, Any]], skipped: list[dict[str, Any]]) -> dict[str, Any]:
    results = [
        item
        for chunk in chunks
        for item in chunk.get("results", [])
    ]
    chunk_status_counts = Counter(str(chunk.get("status")) for chunk in chunks)
    result_status_counts = Counter(str(item.get("status")) for item in results)
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

    nonderived_results = [item for item in results if is_nonderived_relation(item)]
    prune_signal_results = [item for item in results if is_nonderived_prune_signal(item)]
    extra_prune_results = [
        item for item in results if bool(item.get("extra_modular_prune_seen"))
    ]
    error_statuses = {
        "failed",
        "json_parse_failed",
        "chunk_failed",
        "chunk_json_parse_failed",
    }
    timeout_count = chunk_status_counts["chunk_timeout"] + result_status_counts["timeout"]
    error_count = sum(chunk_status_counts[status] for status in error_statuses)
    error_count += sum(result_status_counts[status] for status in error_statuses)

    return {
        "grid_points": len(chunks),
        "result_count": len(results),
        "skipped_count": len(skipped),
        "chunk_status_counts": dict(sorted(chunk_status_counts.items())),
        "result_status_counts": dict(sorted(result_status_counts.items())),
        "best_prune_score": int(best.get("prune_score", 0)) if best else 0,
        "best": best,
        "nonderived_relation_count": len(nonderived_results),
        "extra_modular_prune_seen_count": len(extra_prune_results),
        "nonderived_prune_signal_count": len(prune_signal_results),
        "timeout_count": int(timeout_count),
        "error_count": int(error_count),
    }


def print_text_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "summary: "
        f"grid_points={summary['grid_points']} "
        f"results={summary['result_count']} "
        f"best_prune_score={summary['best_prune_score']} "
        f"nonderived_relations={summary['nonderived_relation_count']} "
        f"extra_modular_prune_seen={summary['extra_modular_prune_seen_count']} "
        f"nonderived_prune_signals={summary['nonderived_prune_signal_count']} "
        f"timeouts={summary['timeout_count']} "
        f"errors={summary['error_count']}"
    )
    print("active m status rels score signal derived prune modular_hits elapsed")
    for item in report["results"]:
        active = ",".join(item.get("active", []))
        print(
            f"{active} {item.get('m')} {item.get('status')} "
            f"{item.get('relation_count')} {item.get('prune_score')} "
            f"{item.get('signal')} "
            f"{item.get('identically_derived_under_projection')} "
            f"{item.get('extra_modular_prune_seen')} "
            f"{result_modular_prune_hits(item)} "
            f"{item.get('elapsed_seconds')}"
        )
    for chunk in report["chunks"]:
        if chunk.get("status") != "ok":
            print(
                "chunk: "
                f"active={chunk.get('active_subset')} "
                f"m={chunk.get('m')} "
                f"status={chunk.get('status')} "
                f"elapsed={chunk.get('elapsed_seconds')}"
            )
    best = summary.get("best")
    if best:
        print(
            "best: "
            f"active={','.join(best.get('active', []))} "
            f"m={best.get('m')} "
            f"score={best.get('prune_score')} "
            f"signal={best.get('signal')} "
            f"derived={best.get('identically_derived_under_projection')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--active-subsets",
        default=DEFAULT_ACTIVE_SUBSETS,
        help=(
            "semicolon-separated active sets, e.g. "
            "'x0,x1,x2,x3;x0,x1,x6,x7'"
        ),
    )
    parser.add_argument("--m-values", default="2")
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument(
        "--chunk-grace-seconds",
        type=float,
        default=3.0,
        help="additional subprocess timeout budget around each lz_prune_search chunk",
    )
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--output", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.chunk_grace_seconds < 0:
        raise SystemExit("--chunk-grace-seconds must be nonnegative")
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")

    active_subsets = parse_active_subsets(args.active_subsets)
    m_values = parse_m_values(args.m_values)
    points = [
        GridPoint(active_subset=active_subset, m_value=m_value)
        for active_subset in active_subsets
        for m_value in m_values
    ]

    script_dir = Path(__file__).resolve().parent
    workers = min(args.jobs, len(points)) if points else 1
    chunks: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(run_grid_point, point, args, script_dir): index
            for index, point in enumerate(points)
        }
        ordered: dict[int, dict[str, Any]] = {}
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            ordered[index] = future.result()
        for index in range(len(points)):
            chunks.append(ordered[index])

    skipped = [
        item
        for chunk in chunks
        for item in chunk.get("skipped", [])
    ]
    results = [
        item
        for chunk in chunks
        for item in chunk.get("results", [])
    ]
    report = {
        "config": {
            "active_subsets": active_subsets,
            "m_values": m_values,
            "samples": args.samples,
            "timeout_seconds": args.timeout_seconds,
            "jobs": args.jobs,
        },
        "summary": summarize(chunks, skipped),
        "results": results,
        "skipped": skipped,
        "chunks": chunks,
    }

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_text_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
