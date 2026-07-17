#!/usr/bin/env python3
"""Bounded sweep wrapper for small and weighted Lu-Zhang lattice probes."""

from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
PROBES = {
    "small": HERE / "small_lz_lattice_probe.py",
    "weighted": HERE / "weighted_lz_probe.py",
}
DEFAULT_ACTIVE_SETS = "x0,x1,x6,x7"
DEFAULT_BUDGETS = "50"


def parse_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_int_csv(raw: str) -> list[int]:
    values = []
    for part in parse_csv(raw):
        value = int(part, 0)
        if value < 0:
            raise argparse.ArgumentTypeError(f"negative value is not allowed: {part}")
        values.append(value)
    return values


def parse_active_sets(raw: str) -> list[str]:
    active_sets = []
    for item in raw.split(";"):
        names = parse_csv(item)
        if not names:
            continue
        active_sets.append(",".join(names))
    return active_sets


def relation_count(report: dict[str, Any]) -> int:
    return int(report.get("lll_relation_count_under_threshold") or 0)


def first_norm_bits(report: dict[str, Any]) -> int:
    value = report.get("lll_first_norm_bits")
    if value is None:
        return 1 << 60
    return int(value)


def rank_value(report: dict[str, Any]) -> int:
    return int(report.get("rank") or 0)


def ranking_key(item: dict[str, Any]) -> tuple[int, int, int, int, int, int]:
    report = item.get("report") or {}
    cols = int(report.get("cols") or 0)
    rows = int(report.get("rows") or 0)
    return (
        -relation_count(report),
        first_norm_bits(report),
        -rank_value(report),
        cols,
        rows,
        int(item["index"]),
    )


def run_probe(command: list[str], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "timed_out": True,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "stdout": (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else "",
        }

    result: dict[str, Any] = {
        "ok": completed.returncode == 0,
        "timed_out": False,
        "returncode": completed.returncode,
        "elapsed_sec": round(time.monotonic() - started, 3),
    }
    if completed.returncode != 0:
        result["stdout"] = completed.stdout[-2000:]
        result["stderr"] = completed.stderr[-2000:]
        return result
    try:
        result["report"] = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        result.update(
            {
                "ok": False,
                "json_error": str(exc),
                "stdout": completed.stdout[-2000:],
                "stderr": completed.stderr[-2000:],
            }
        )
    return result


def build_command(
    probe: str,
    active: str,
    anchor: str,
    budget: int | None,
    m_value: int,
    t_value: int,
    args: argparse.Namespace,
) -> list[str]:
    command = [
        sys.executable,
        str(PROBES[probe]),
        "--active",
        active,
        "--anchor",
        anchor,
        "--m",
        str(m_value),
        "--t",
        str(t_value),
        "--relation-threshold-bits",
        str(args.relation_threshold_bits),
        "--json",
    ]
    if args.lll:
        command.append("--lll")
    if probe == "weighted":
        command.extend(["--budget", str(budget)])
        command.extend(["--lll-max-dim", str(args.lll_max_dim)])
    return command


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run bounded JSON sweeps over small and weighted LZ probe parameters."
    )
    parser.add_argument("--active-sets", default=DEFAULT_ACTIVE_SETS)
    parser.add_argument("--anchors", default="x0")
    parser.add_argument("--budgets", default=DEFAULT_BUDGETS)
    parser.add_argument("--m-values", default="2")
    parser.add_argument("--t-values", default="1")
    parser.add_argument("--probes", default="small,weighted")
    parser.add_argument("--timeout-sec", type=float, default=20.0)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-runs", type=int, default=32)
    parser.add_argument("--lll", action="store_true")
    parser.add_argument("--lll-max-dim", type=int, default=80)
    parser.add_argument("--relation-threshold-bits", type=int, default=1024)
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    if args.timeout_sec <= 0:
        raise SystemExit("--timeout-sec must be positive")
    if args.limit < 1:
        raise SystemExit("--limit must be positive")
    if args.max_runs < 1:
        raise SystemExit("--max-runs must be positive")

    active_sets = parse_active_sets(args.active_sets)
    if not active_sets:
        raise SystemExit("--active-sets must include at least one nonempty active set")
    anchors = parse_csv(args.anchors)
    budgets = parse_int_csv(args.budgets)
    m_values = parse_int_csv(args.m_values)
    t_values = parse_int_csv(args.t_values)
    probes = parse_csv(args.probes)
    unknown = [probe for probe in probes if probe not in PROBES]
    if unknown:
        raise SystemExit(f"unknown probe(s): {','.join(unknown)}")
    if "weighted" in probes and not budgets:
        raise SystemExit("--budgets must be nonempty when weighted probe is enabled")

    rankings: list[dict[str, Any]] = []
    attempted = 0
    for probe, active, anchor, m_value, t_value in itertools.product(
        probes, active_sets, anchors, m_values, t_values
    ):
        if anchor not in parse_csv(active):
            continue
        probe_budgets: list[int | None] = budgets if probe == "weighted" else [None]
        for budget in probe_budgets:
            if attempted >= args.max_runs:
                break
            attempted += 1
            command = build_command(probe, active, anchor, budget, m_value, t_value, args)
            item: dict[str, Any] = {
                "event": "probe",
                "index": attempted - 1,
                "probe": probe,
                "active": active,
                "anchor": anchor,
                "budget": budget,
                "m": m_value,
                "t": t_value,
                "command": command,
            }
            item.update(run_probe(command, args.timeout_sec))
            rankings.append(item)
            if args.jsonl:
                print(json.dumps(item, sort_keys=True))
        if attempted >= args.max_runs:
            break

    ok_rankings = [item for item in rankings if item.get("ok") and "report" in item]
    ok_rankings.sort(key=ranking_key)
    failure_items = [
        {
            "index": item.get("index"),
            "probe": item.get("probe"),
            "active": item.get("active"),
            "anchor": item.get("anchor"),
            "budget": item.get("budget"),
            "m": item.get("m"),
            "t": item.get("t"),
            "timed_out": item.get("timed_out", False),
            "returncode": item.get("returncode"),
            "elapsed_sec": item.get("elapsed_sec"),
            "json_error": item.get("json_error"),
        }
        for item in rankings
        if not (item.get("ok") and "report" in item)
    ]
    failures = len(rankings) - len(ok_rankings)
    summary = {
        "event": "best",
        "attempted": attempted,
        "completed": len(ok_rankings),
        "failures": failures,
        "failure_items": failure_items[: args.limit],
        "truncated": attempted >= args.max_runs,
        "ranked_by": [
            "relation_count_desc",
            "lll_first_norm_bits_asc",
            "rank_desc",
            "cols_asc",
            "rows_asc",
        ],
        "items": ok_rankings[: args.limit],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0 if ok_rankings or attempted == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
