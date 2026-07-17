#!/usr/bin/env python3
"""Search small unknown-divisor relation candidates for pruning signal.

This is a bounded wrapper around lz_relation_eval_probe.py.  It runs the
existing single-candidate evaluator over several active-variable/m/t choices,
then normalizes the result fields that matter for SAT pruning.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import time
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


DEFAULT_ACTIVE_SUBSETS = "x0,x1,x2,x3;x0,x1,x6,x7;x0,x4,x6,x7"


@dataclass(frozen=True)
class Candidate:
    active: tuple[str, ...]
    anchor: str
    m: int
    t: int


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
            raise SystemExit(f"active subset contains a duplicate variable: {group}")
        unknown = [name for name in names if name not in RUNS]
        if unknown:
            raise SystemExit(f"unknown variable(s) in active subset {group}: {unknown}")
        subsets.append(names)
    if not subsets:
        raise SystemExit("--active-subsets must contain at least one subset")
    return subsets


def lattice_dimension(active_count: int, m_value: int) -> int:
    return comb(active_count + m_value, active_count)


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


def extract_json(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise ValueError("no JSON object found in evaluator stdout")


def summarize_payload(
    candidate: Candidate,
    payload: dict[str, Any],
    elapsed_seconds: float,
    command: list[str],
) -> dict[str, Any]:
    conclusion = payload.get("conclusion", {})
    selected = payload.get("selected_relation") or {}
    signal_label, score, hit_counts = relation_signal(payload)
    return {
        "active": list(candidate.active),
        "anchor": candidate.anchor,
        "m": candidate.m,
        "t": candidate.t,
        "status": payload.get("status", "ok"),
        "rows": payload.get("rows"),
        "cols": payload.get("cols"),
        "rank": payload.get("rank"),
        "relation_count": payload.get("candidate_relation_rows", 0),
        "signal": signal_label,
        "prune_score": score,
        "sample_hit_counts": hit_counts,
        "selected_degree": selected.get("max_degree"),
        "selected_class": selected.get("category"),
        "selected_row_index": selected.get("row_index"),
        "selected_term_count": selected.get("term_count"),
        "identically_derived_under_projection": conclusion.get(
            "identically_derived_mod_projection"
        ),
        "integer_multiple_of_projection": conclusion.get("integer_multiple_of_projection"),
        "extra_modular_prune_seen": conclusion.get("extra_modular_prune_seen", False),
        "integer_zero_seen": conclusion.get("integer_zero_seen", False),
        "elapsed_seconds": round(elapsed_seconds, 4),
        "command": command,
    }


def run_candidate(
    candidate: Candidate,
    args: argparse.Namespace,
    script_dir: Path,
) -> dict[str, Any]:
    eval_script = script_dir / "lz_relation_eval_probe.py"
    command = [
        sys.executable,
        "-B",
        str(eval_script),
        "--active",
        ",".join(candidate.active),
        "--anchor",
        candidate.anchor,
        "--m",
        str(candidate.m),
        "--t",
        str(candidate.t),
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
            "active": list(candidate.active),
            "anchor": candidate.anchor,
            "m": candidate.m,
            "t": candidate.t,
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
            "active": list(candidate.active),
            "anchor": candidate.anchor,
            "m": candidate.m,
            "t": candidate.t,
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
            "active": list(candidate.active),
            "anchor": candidate.anchor,
            "m": candidate.m,
            "t": candidate.t,
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

    return summarize_payload(candidate, payload, elapsed, command)


def build_candidates(args: argparse.Namespace) -> tuple[list[Candidate], list[dict[str, Any]]]:
    active_subsets = parse_active_subsets(args.active_subsets)
    m_values = parse_int_list(args.m_values, "--m-values")
    t_values = parse_int_list(args.t_values, "--t-values")

    candidates: list[Candidate] = []
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
            if m_value not in (2, 3):
                skipped.append(
                    {
                        "active": list(active),
                        "anchor": anchor,
                        "m": m_value,
                        "status": "skipped_unsupported_m",
                    }
                )
                continue
            dim = lattice_dimension(len(active), m_value)
            for t_value in t_values:
                if t_value < 0:
                    skipped.append(
                        {
                            "active": list(active),
                            "anchor": anchor,
                            "m": m_value,
                            "t": t_value,
                            "status": "skipped_negative_t",
                        }
                    )
                    continue
                if dim > args.dim_cap:
                    skipped.append(
                        {
                            "active": list(active),
                            "anchor": anchor,
                            "m": m_value,
                            "t": t_value,
                            "dim": dim,
                            "dim_cap": args.dim_cap,
                            "status": "skipped_dim_cap",
                        }
                    )
                    continue
                candidates.append(Candidate(active, anchor, m_value, t_value))
                if len(candidates) >= args.max_candidates:
                    return candidates, skipped
    return candidates, skipped


def print_text_report(report: dict[str, Any]) -> None:
    print(
        "active anchor m t status rels score signal degree class derived prune integer_zero elapsed"
    )
    for item in report["results"]:
        active = ",".join(item["active"])
        print(
            f"{active} {item.get('anchor')} {item.get('m')} {item.get('t')} "
            f"{item.get('status')} {item.get('relation_count')} "
            f"{item.get('prune_score')} {item.get('signal')} "
            f"{item.get('selected_degree')} {item.get('selected_class')} "
            f"{item.get('identically_derived_under_projection')} "
            f"{item.get('extra_modular_prune_seen')} {item.get('integer_zero_seen')} "
            f"{item.get('elapsed_seconds')}"
        )
    if report["skipped"]:
        print("skipped:")
        for item in report["skipped"]:
            print(json.dumps(item, sort_keys=True))
    best = report.get("best")
    if best:
        print(
            "best: "
            f"active={','.join(best['active'])} m={best['m']} t={best['t']} "
            f"score={best['prune_score']} signal={best['signal']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--active-subsets",
        default=DEFAULT_ACTIVE_SUBSETS,
        help="semicolon-separated active sets, e.g. 'x0,x1,x2,x3;x0,x1,x6,x7'",
    )
    parser.add_argument(
        "--anchor",
        default="",
        help="anchor variable for all subsets; defaults to the first variable in each subset",
    )
    parser.add_argument("--m-values", default="2,3")
    parser.add_argument("--t-values", default="1")
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--relation-threshold-bits", type=int, default=1024)
    parser.add_argument("--small-residue-bits", type=int, default=64)
    parser.add_argument("--dim-cap", type=int, default=60)
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.relation_threshold_bits <= 0:
        raise SystemExit("--relation-threshold-bits must be positive")
    if args.small_residue_bits < 0:
        raise SystemExit("--small-residue-bits must be nonnegative")
    if args.dim_cap <= 0:
        raise SystemExit("--dim-cap must be positive")
    if args.max_candidates <= 0:
        raise SystemExit("--max-candidates must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.jobs <= 0:
        raise SystemExit("--jobs must be positive")

    candidates, skipped = build_candidates(args)
    script_dir = Path(__file__).resolve().parent
    results: list[dict[str, Any]] = []
    workers = min(args.jobs, len(candidates)) if candidates else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_index = {
            executor.submit(run_candidate, candidate, args, script_dir): index
            for index, candidate in enumerate(candidates)
        }
        ordered: dict[int, dict[str, Any]] = {}
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            ordered[index] = future.result()
        for index in range(len(candidates)):
            results.append(ordered[index])

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
        "active_subsets": [list(candidate.active) for candidate in candidates],
        "candidate_count": len(candidates),
        "skipped": skipped,
        "results": results,
        "best": best,
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_text_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
