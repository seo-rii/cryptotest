#!/usr/bin/env python3
"""Rank sampled value/pruning signals from the existing LZ relation probe.

This is a bounded diagnostic wrapper around lz_relation_eval_probe.py.  It does
not rebuild relation polynomials itself; instead it records what the evaluator
already exposes and makes the value-evaluation gap explicit when only preview
metadata is available.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
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


def parse_active(raw: str) -> list[str]:
    active = [part.strip() for part in raw.split(",") if part.strip()]
    if not active:
        raise SystemExit("--active must name at least one variable")
    if len(set(active)) != len(active):
        raise SystemExit("--active contains duplicate variables")
    unknown = [name for name in active if name not in RUNS]
    if unknown:
        raise SystemExit(f"--active contains unknown variable(s): {unknown}")
    return active


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


def run_eval_probe(args: argparse.Namespace, active: list[str], script_dir: Path) -> dict[str, Any]:
    eval_script = script_dir / "lz_relation_eval_probe.py"
    command = [
        sys.executable,
        "-B",
        str(eval_script),
        "--active",
        ",".join(active),
        "--anchor",
        active[0],
        "--m",
        str(args.m),
        "--t",
        str(args.t),
        "--samples",
        str(args.samples),
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
        return {
            "status": "timeout",
            "elapsed_seconds": round(time.monotonic() - start, 4),
            "timeout_seconds": args.timeout_seconds,
            "stdout_tail": (exc.stdout or "")[-500:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-500:] if isinstance(exc.stderr, str) else "",
            "command": command,
        }

    elapsed = round(time.monotonic() - start, 4)
    if proc.returncode != 0:
        return {
            "status": "failed",
            "returncode": proc.returncode,
            "elapsed_seconds": elapsed,
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
            "command": command,
        }

    try:
        payload = extract_json(proc.stdout)
    except ValueError as exc:
        return {
            "status": "json_parse_failed",
            "elapsed_seconds": elapsed,
            "error": str(exc),
            "stdout_tail": proc.stdout[-500:],
            "stderr_tail": proc.stderr[-500:],
            "command": command,
        }

    payload["elapsed_seconds"] = elapsed
    payload["command"] = command
    return payload


def distinct_preview_values(previews: list[dict[str, Any]], key: str) -> int:
    return len({preview.get(key) for preview in previews if key in preview})


def summarize_value_signal(payload: dict[str, Any]) -> dict[str, Any]:
    sample_counts = payload.get("sample_counts") or {}
    previews = payload.get("sample_previews") or []
    conclusion = payload.get("conclusion") or {}
    selected = payload.get("selected_relation") or {}

    prune_hits = int(sample_counts.get("relation_prunes_projection_pass", 0))
    relation_mod_zero_hits = int(sample_counts.get("relation_mod_zero", 0))
    relation_integer_zero_hits = int(sample_counts.get("relation_integer_zero", 0))
    small_residue_hits = int(sample_counts.get("relation_small_centered_residue", 0))
    total_samples = int(sample_counts.get("total", 0))
    integer_bit_variants = distinct_preview_values(previews, "relation_integer_bits")
    centered_bit_variants = distinct_preview_values(previews, "relation_center_bits")
    relation_mod_variants = distinct_preview_values(previews, "relation_mod_zero")

    value_eval_status = "sampled_preview_bits_no_raw_values"
    value_eval_reason = (
        "lz_relation_eval_probe.py evaluates the selected relation internally, "
        "but its JSON exposes only counters and preview bit sizes, not raw "
        "relation values or all candidate relation polynomials."
    )
    if payload.get("status") != "ok":
        value_eval_status = "metadata_only_no_value_eval"
        value_eval_reason = "the evaluator did not return an ok relation payload"

    derived = conclusion.get("identically_derived_mod_projection")
    score = 0
    score += prune_hits * 100
    if derived is False:
        score += 25
    score += min(integer_bit_variants, 8) * 4
    score += min(centered_bit_variants, 8) * 3
    score += min(relation_mod_variants, 2) * 5
    if relation_mod_zero_hits == total_samples and total_samples:
        score -= 20
    if relation_integer_zero_hits == total_samples and total_samples:
        score -= 20
    if small_residue_hits and small_residue_hits < total_samples:
        score += 5

    if prune_hits:
        label = "sampled_extra_prune"
    elif derived is True:
        label = "derived_no_extra_prune"
    elif integer_bit_variants > 1 or centered_bit_variants > 1:
        label = "nonderived_value_varies_no_sample_prune"
    elif payload.get("status") == "ok":
        label = "nonderived_or_unknown_low_variation"
    else:
        label = str(payload.get("status", "not_ok"))

    return {
        "row_index": selected.get("row_index"),
        "category": selected.get("category"),
        "max_degree": selected.get("max_degree"),
        "term_count": selected.get("term_count"),
        "coeff_max_bits": selected.get("coeff_max_bits"),
        "weighted_max_bits": selected.get("weighted_max_bits"),
        "rank_score": int(score),
        "rank_label": label,
        "value_eval_status": value_eval_status,
        "value_eval_reason": value_eval_reason,
        "sample_variation": {
            "preview_count": len(previews),
            "relation_integer_bits_distinct": integer_bit_variants,
            "relation_center_bits_distinct": centered_bit_variants,
            "relation_mod_zero_distinct": relation_mod_variants,
        },
        "sample_counts": {
            "total": total_samples,
            "relation_prunes_projection_pass": prune_hits,
            "relation_mod_zero": relation_mod_zero_hits,
            "relation_integer_zero": relation_integer_zero_hits,
            "relation_small_centered_residue": small_residue_hits,
        },
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    active = parse_active(args.active)
    dimension = lattice_dimension(len(active), args.m)
    base: dict[str, Any] = {
        "config": {
            "active": active,
            "anchor": active[0],
            "m": args.m,
            "t": args.t,
            "samples": args.samples,
            "max_dimension": args.max_dimension,
            "timeout_seconds": args.timeout_seconds,
            "dimension": dimension,
        }
    }
    if args.m not in (2, 3, 4):
        return {
            **base,
            "summary": {
                "status": "skipped_unsupported_m",
                "supported_m_values": [2, 3, 4],
                "relation_count": 0,
                "nonderived_count": 0,
                "extra_prune_count": 0,
                "value_eval_status": "metadata_only_no_value_eval",
                "value_eval_reason": "lz_relation_eval_probe.py supports only m=2,3,4",
            },
            "ranked_relations": [],
        }
    if dimension > args.max_dimension:
        return {
            **base,
            "summary": {
                "status": "skipped_dimension_cap",
                "dimension": dimension,
                "max_dimension": args.max_dimension,
                "relation_count": 0,
                "nonderived_count": 0,
                "extra_prune_count": 0,
                "value_eval_status": "metadata_only_no_value_eval",
                "value_eval_reason": "dimension cap skipped evaluator subprocess",
            },
            "ranked_relations": [],
        }

    script_dir = Path(__file__).resolve().parent
    payload = run_eval_probe(args, active, script_dir)
    status = str(payload.get("status", "ok"))
    relation_count = int(payload.get("candidate_relation_rows", 0))
    conclusion = payload.get("conclusion") or {}
    nonderived_count = int(status == "ok" and conclusion.get("identically_derived_mod_projection") is False)
    extra_prune_count = int(status == "ok" and bool(conclusion.get("extra_modular_prune_seen")))
    relation_rank = summarize_value_signal(payload)

    return {
        **base,
        "summary": {
            "status": status,
            "rows": payload.get("rows"),
            "cols": payload.get("cols"),
            "rank": payload.get("rank"),
            "relation_count": relation_count,
            "nonderived_count": nonderived_count,
            "extra_prune_count": extra_prune_count,
            "best_rank_score": relation_rank["rank_score"],
            "best_rank_label": relation_rank["rank_label"],
            "value_eval_status": relation_rank["value_eval_status"],
            "value_eval_reason": relation_rank["value_eval_reason"],
            "elapsed_seconds": payload.get("elapsed_seconds"),
        },
        "ranked_relations": [relation_rank] if payload.get("selected_relation") else [],
        "evaluator_payload": payload,
    }


def print_text_report(report: dict[str, Any]) -> None:
    config = report["config"]
    summary = report["summary"]
    print(
        "summary: "
        f"active={','.join(config['active'])} m={config['m']} t={config['t']} "
        f"dim={config['dimension']} status={summary['status']} "
        f"relations={summary['relation_count']} "
        f"nonderived={summary['nonderived_count']} "
        f"extra_prune={summary['extra_prune_count']} "
        f"best_score={summary.get('best_rank_score', 0)} "
        f"best={summary.get('best_rank_label')}"
    )
    print(f"value_eval: {summary['value_eval_status']}")
    print(f"why: {summary['value_eval_reason']}")
    if report["ranked_relations"]:
        print("row score label category degree terms int_bits_var center_bits_var prune_hits")
    for item in report["ranked_relations"]:
        variation = item["sample_variation"]
        counts = item["sample_counts"]
        print(
            f"{item.get('row_index')} {item['rank_score']} {item['rank_label']} "
            f"{item.get('category')} {item.get('max_degree')} {item.get('term_count')} "
            f"{variation['relation_integer_bits_distinct']} "
            f"{variation['relation_center_bits_distinct']} "
            f"{counts['relation_prunes_projection_pass']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active", default="x0,x1,x2,x3")
    parser.add_argument("--m", type=int, default=4)
    parser.add_argument("--t", type=int, default=1)
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--max-dimension", type=int, default=90)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.m < 0:
        raise SystemExit("--m must be nonnegative")
    if args.t < 0:
        raise SystemExit("--t must be nonnegative")
    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.max_dimension <= 0:
        raise SystemExit("--max-dimension must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")

    report = build_report(args)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print_text_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
