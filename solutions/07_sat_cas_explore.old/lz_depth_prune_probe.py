#!/usr/bin/env python3
"""Bounded depth probe for LZ unknown-divisor pruning signals.

This wrapper pushes the existing LZ pruning diagnostics across selected
active-variable subsets and m/t choices while keeping every spawned evaluator
under a strict per-job timeout.
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
from math import comb
from pathlib import Path
from typing import Any

try:
    from lz_relation_eval_probe import RUNS
except Exception:  # pragma: no cover - defensive fallback for path issues
    RUNS = {
        "x0": (150, 4),
        "x1": (210, 39),
        "x2": (265, 84),
        "x3": (362, 78),
        "x4": (600, 69),
        "x5": (682, 87),
        "x6": (784, 46),
        "x7": (920, 4),
    }


DEFAULT_ACTIVE_SUBSETS = "x0,x1,x2,x3;x0,x1,x6,x7;x0,x1,x2,x7"
DEFAULT_M_VALUES = "3,4"
DEFAULT_T_VALUES = "1"
SUPPORTED_EVAL_M_VALUES = {2, 3, 4}


@dataclass(frozen=True)
class Job:
    active: tuple[str, ...]
    anchor: str
    m: int
    t: int
    dimension: int


def parse_int_list(raw: str, option_name: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            values.append(int(item, 0))
        except ValueError as exc:
            raise SystemExit(f"{option_name} contains a non-integer value: {item}") from exc
    if not values:
        raise SystemExit(f"{option_name} must contain at least one integer")
    return values


def parse_active_subsets(raw: str) -> list[tuple[str, ...]]:
    subsets: list[tuple[str, ...]] = []
    for group in raw.split(";"):
        names = tuple(part.strip() for part in group.split(",") if part.strip())
        if not names:
            continue
        if len(set(names)) != len(names):
            raise SystemExit(f"--active-subsets contains a duplicate variable: {group}")
        unknown = [name for name in names if name not in RUNS]
        if unknown:
            raise SystemExit(f"--active-subsets contains unknown variable(s): {unknown}")
        subsets.append(names)
    if not subsets:
        raise SystemExit("--active-subsets must contain at least one subset")
    return subsets


def lattice_dimension(active_count: int, m_value: int) -> int:
    return comb(active_count + m_value, active_count)


def extract_json(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in evaluator stdout")


def relation_signal(payload: dict[str, Any]) -> tuple[str, int, dict[str, int]]:
    if payload.get("status") != "ok":
        return str(payload.get("status", "not_ok")), 0, {}

    conclusion = payload.get("conclusion", {})
    sample_counts = payload.get("sample_counts", {})
    prune_hits = int(sample_counts.get("relation_prunes_projection_pass", 0))
    integer_zero_hits = int(sample_counts.get("relation_integer_zero", 0))
    projection_passes = int(sample_counts.get("projection_mod_zero", 0))
    relation_accepts_projection_fail = int(
        sample_counts.get("relation_accepts_projection_fail", 0)
    )
    derived = bool(conclusion.get("identically_derived_mod_projection"))

    if prune_hits:
        label = "sampled_modular_prune"
    elif derived:
        label = "projection_derived_no_extra_prune"
    elif integer_zero_hits:
        label = "nonderived_integer_zero_only"
    else:
        label = "nonderived_no_sample_prune"

    score = prune_hits * 100
    if not derived:
        score += 10
    if integer_zero_hits and not derived:
        score += min(integer_zero_hits, 9)
    score -= relation_accepts_projection_fail
    return (
        label,
        score,
        {
            "modular_prune_hits": prune_hits,
            "integer_zero_hits": integer_zero_hits,
            "projection_mod_zero_hits": projection_passes,
            "relation_accepts_projection_fail_hits": relation_accepts_projection_fail,
        },
    )


def summarize_payload(
    job: Job,
    payload: dict[str, Any],
    elapsed_seconds: float,
    command: list[str],
) -> dict[str, Any]:
    conclusion = payload.get("conclusion", {})
    selected = payload.get("selected_relation") or {}
    signal, prune_score, hit_counts = relation_signal(payload)
    return {
        "active": list(job.active),
        "anchor": job.anchor,
        "m": job.m,
        "t": job.t,
        "dimension": job.dimension,
        "status": payload.get("status", "ok"),
        "rows": payload.get("rows"),
        "cols": payload.get("cols"),
        "rank": payload.get("rank"),
        "relation_count": int(payload.get("candidate_relation_rows", 0)),
        "signal": signal,
        "prune_score": int(prune_score),
        "sample_hit_counts": hit_counts,
        "selected_degree": selected.get("max_degree"),
        "selected_class": selected.get("category"),
        "selected_row_index": selected.get("row_index"),
        "selected_term_count": selected.get("term_count"),
        "identically_derived_under_projection": conclusion.get(
            "identically_derived_mod_projection"
        ),
        "integer_multiple_of_projection": conclusion.get("integer_multiple_of_projection"),
        "extra_modular_prune_seen": bool(
            conclusion.get("extra_modular_prune_seen", False)
        ),
        "integer_zero_seen": bool(conclusion.get("integer_zero_seen", False)),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "command": command,
    }


def run_job(job: Job, args: argparse.Namespace, script_dir: Path) -> dict[str, Any]:
    eval_script = script_dir / "lz_relation_eval_probe.py"
    command = [
        sys.executable,
        "-B",
        str(eval_script),
        "--active",
        ",".join(job.active),
        "--anchor",
        job.anchor,
        "--m",
        str(job.m),
        "--t",
        str(job.t),
        "--samples",
        str(args.samples),
        "--seed",
        str(args.seed),
        "--relation-threshold-bits",
        str(args.relation_threshold_bits),
        "--small-residue-bits",
        str(args.small_residue_bits),
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
            timeout=args.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - start
        return {
            "active": list(job.active),
            "anchor": job.anchor,
            "m": job.m,
            "t": job.t,
            "dimension": job.dimension,
            "status": "timeout",
            "relation_count": 0,
            "signal": "timeout",
            "prune_score": 0,
            "elapsed_seconds": round(elapsed, 4),
            "timeout_seconds": args.timeout_seconds,
            "stdout_tail": (exc.stdout or "")[-500:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-500:] if isinstance(exc.stderr, str) else "",
            "command": command,
        }

    elapsed = time.monotonic() - start
    if proc.returncode != 0:
        return {
            "active": list(job.active),
            "anchor": job.anchor,
            "m": job.m,
            "t": job.t,
            "dimension": job.dimension,
            "status": "failed",
            "returncode": proc.returncode,
            "relation_count": 0,
            "signal": "failed",
            "prune_score": 0,
            "elapsed_seconds": round(elapsed, 4),
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
            "command": command,
        }

    try:
        payload = extract_json(proc.stdout)
    except ValueError as exc:
        return {
            "active": list(job.active),
            "anchor": job.anchor,
            "m": job.m,
            "t": job.t,
            "dimension": job.dimension,
            "status": "json_parse_failed",
            "relation_count": 0,
            "signal": "json_parse_failed",
            "prune_score": 0,
            "elapsed_seconds": round(elapsed, 4),
            "error": str(exc),
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
            "command": command,
        }

    return summarize_payload(job, payload, elapsed, command)


def build_jobs(args: argparse.Namespace) -> tuple[list[Job], list[dict[str, Any]]]:
    active_subsets = parse_active_subsets(args.active_subsets)
    m_values = parse_int_list(args.m_values, "--m-values")
    t_values = parse_int_list(args.t_values, "--t-values")

    jobs: list[Job] = []
    skipped: list[dict[str, Any]] = []
    for active in active_subsets:
        anchor = args.anchor if args.anchor else active[0]
        if anchor not in active:
            skipped.append(
                {
                    "active": list(active),
                    "anchor": anchor,
                    "status": "skipped_anchor_not_active",
                }
            )
            continue
        for m_value in m_values:
            dimension = lattice_dimension(len(active), m_value)
            for t_value in t_values:
                base = {
                    "active": list(active),
                    "anchor": anchor,
                    "m": m_value,
                    "t": t_value,
                    "dimension": dimension,
                }
                if t_value < 0:
                    skipped.append({**base, "status": "skipped_negative_t"})
                    continue
                if dimension > args.max_dimension:
                    skipped.append(
                        {
                            **base,
                            "max_dimension": args.max_dimension,
                            "status": "skipped_dimension_cap",
                        }
                    )
                    continue
                if m_value not in SUPPORTED_EVAL_M_VALUES:
                    skipped.append(
                        {
                            **base,
                            "evaluator": "lz_relation_eval_probe.py",
                            "supported_m_values": sorted(SUPPORTED_EVAL_M_VALUES),
                            "status": "skipped_unsupported_m",
                        }
                    )
                    continue
                jobs.append(Job(active, anchor, m_value, t_value, dimension))
    return jobs, skipped


def status_key(item: dict[str, Any]) -> str:
    return str(item.get("status", "unknown"))


def subset_m_key(item: dict[str, Any]) -> str:
    active = ",".join(str(value) for value in item.get("active", []))
    return f"{active}|m={item.get('m')}|t={item.get('t')}"


def build_report(
    args: argparse.Namespace,
    jobs: list[Job],
    skipped: list[dict[str, Any]],
    results: list[dict[str, Any]],
    elapsed_seconds: float,
) -> dict[str, Any]:
    status_counts = Counter(status_key(item) for item in results)
    status_counts.update(status_key(item) for item in skipped)
    result_status_counts = Counter(status_key(item) for item in results)
    skipped_status_counts = Counter(status_key(item) for item in skipped)

    timeout_count = result_status_counts["timeout"]
    error_statuses = {"failed", "json_parse_failed"}
    error_count = sum(result_status_counts[status] for status in error_statuses)
    nonderived_count = sum(
        1
        for item in results
        if item.get("status") == "ok"
        and item.get("identically_derived_under_projection") is False
    )
    extra_prune_count = sum(
        1
        for item in results
        if item.get("status") == "ok" and bool(item.get("extra_modular_prune_seen"))
    )
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

    relation_counts_by_subset_m = {
        subset_m_key(item): int(item.get("relation_count", 0))
        for item in results
    }
    skipped_by_subset_m = {subset_m_key(item): status_key(item) for item in skipped}

    return {
        "config": {
            "active_subsets": parse_active_subsets(args.active_subsets),
            "m_values": parse_int_list(args.m_values, "--m-values"),
            "t_values": parse_int_list(args.t_values, "--t-values"),
            "samples": args.samples,
            "timeout_seconds": args.timeout_seconds,
            "jobs": args.jobs,
            "max_dimension": args.max_dimension,
            "seed": args.seed,
            "relation_threshold_bits": args.relation_threshold_bits,
            "small_residue_bits": args.small_residue_bits,
        },
        "summary": {
            "planned_job_count": len(jobs) + len(skipped),
            "executed_job_count": len(jobs),
            "result_count": len(results),
            "skipped_count": len(skipped),
            "status_counts": dict(sorted(status_counts.items())),
            "result_status_counts": dict(sorted(result_status_counts.items())),
            "skipped_status_counts": dict(sorted(skipped_status_counts.items())),
            "relation_counts_by_subset_m": relation_counts_by_subset_m,
            "skipped_by_subset_m": skipped_by_subset_m,
            "nonderived_count": int(nonderived_count),
            "extra_prune_count": int(extra_prune_count),
            "best_prune_score": int(best.get("prune_score", 0)) if best else 0,
            "timeout_count": int(timeout_count),
            "error_count": int(error_count),
            "elapsed_seconds": round(elapsed_seconds, 4),
            "best": best,
        },
        "results": results,
        "skipped": skipped,
    }


def print_text_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "summary: "
        f"planned={summary['planned_job_count']} "
        f"executed={summary['executed_job_count']} "
        f"skipped={summary['skipped_count']} "
        f"best_prune_score={summary['best_prune_score']} "
        f"nonderived={summary['nonderived_count']} "
        f"extra_prune={summary['extra_prune_count']} "
        f"timeouts={summary['timeout_count']} "
        f"errors={summary['error_count']}"
    )
    print("active m t dim status rels score signal derived extra_prune elapsed")
    for item in report["results"]:
        active = ",".join(item.get("active", []))
        print(
            f"{active} {item.get('m')} {item.get('t')} {item.get('dimension')} "
            f"{item.get('status')} {item.get('relation_count')} "
            f"{item.get('prune_score')} {item.get('signal')} "
            f"{item.get('identically_derived_under_projection')} "
            f"{item.get('extra_modular_prune_seen')} {item.get('elapsed_seconds')}"
        )
    if report["skipped"]:
        print("skipped:")
        for item in report["skipped"]:
            print(json.dumps(item, sort_keys=True))


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
    parser.add_argument(
        "--anchor",
        default="",
        help="anchor variable for all subsets; defaults to each subset's first variable",
    )
    parser.add_argument("--m-values", default=DEFAULT_M_VALUES)
    parser.add_argument("--t-values", default=DEFAULT_T_VALUES)
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--max-dimension", type=int, default=80)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--relation-threshold-bits", type=int, default=1024)
    parser.add_argument("--small-residue-bits", type=int, default=64)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")
    if args.max_dimension <= 0:
        raise SystemExit("--max-dimension must be positive")
    if args.relation_threshold_bits <= 0:
        raise SystemExit("--relation-threshold-bits must be positive")
    if args.small_residue_bits < 0:
        raise SystemExit("--small-residue-bits must be nonnegative")

    jobs, skipped = build_jobs(args)
    script_dir = Path(__file__).resolve().parent
    start = time.monotonic()
    results: list[dict[str, Any]] = []
    workers = min(args.jobs, len(jobs)) if jobs else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(run_job, job, args, script_dir): index
            for index, job in enumerate(jobs)
        }
        ordered: dict[int, dict[str, Any]] = {}
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            ordered[index] = future.result()
        for index in range(len(jobs)):
            results.append(ordered[index])
    elapsed = time.monotonic() - start

    report = build_report(args, jobs, skipped, results, elapsed)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_text_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
