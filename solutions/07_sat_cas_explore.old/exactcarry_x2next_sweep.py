#!/usr/bin/env python3
"""Run and aggregate exact-carry x2 next-byte SAT sweeps for problem 7.

The manual one-liners for these sweeps are easy to duplicate accidentally.
This wrapper keeps the prefix, shard list, resume behavior, and aggregate
validation in one place while still delegating CNF construction and solving to
``run_07_go_sat_filter.py``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "solutions" / "run_07_go_sat_filter.py"
DEFAULT_PYTHON = Path("/tmp/cryptotest_sat_venv/bin/python")


def parse_int(text: str) -> int:
    return int(text, 0)


def shard_ranges(value_start: int, value_stop: int, shard_width: int) -> list[tuple[int, int]]:
    if value_start < 0 or value_stop > 256 or value_start >= value_stop:
        raise ValueError("value range must be non-empty and inside 0..256")
    if shard_width < 1:
        raise ValueError("shard width must be positive")
    ranges = []
    start = value_start
    while start < value_stop:
        end = min(start + shard_width, value_stop) - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def summary_path(prefix: str, start: int, end: int) -> Path:
    return Path(f"{prefix}_{start:02x}_{end:02x}_sweep_summary.json")


def stdout_path(prefix: str, start: int, end: int) -> Path:
    return Path(f"{prefix}_{start:02x}_{end:02x}_stdout.json")


def load_summary(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def complete_shard(path: Path, start: int, end: int) -> bool:
    data = load_summary(path)
    if data is None:
        return False
    seen = set()
    for row in data.get("rows", []):
        if not isinstance(row, dict):
            continue
        fixed = row.get("fix_p_range_sweep")
        if not isinstance(fixed, dict):
            continue
        if fixed.get("start") != 272 or fixed.get("width") != 8:
            continue
        value = fixed.get("value")
        try:
            seen.add(int(value, 0) if isinstance(value, str) else int(value))
        except (TypeError, ValueError):
            continue
    return seen == set(range(start, end + 1))


def aggregate(prefix: str, ranges: list[tuple[int, int]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    bad_files = []
    values = []
    vars_seen = []
    clauses_seen = []
    sat = 0
    unsat = 0
    existing_files = []

    for start, end in ranges:
        path = summary_path(prefix, start, end)
        data = load_summary(path)
        if data is None:
            bad_files.append(str(path))
            continue
        existing_files.append(str(path))
        sat += int(data.get("sat", 0) or 0)
        unsat += int(data.get("unsat", 0) or 0)
        for row in data.get("rows", []):
            if not isinstance(row, dict):
                continue
            rows.append(row)
            if isinstance(row.get("vars"), int):
                vars_seen.append(row["vars"])
            if isinstance(row.get("clauses"), int):
                clauses_seen.append(row["clauses"])
            fixed = row.get("fix_p_range_sweep")
            if isinstance(fixed, dict) and fixed.get("start") == 272 and fixed.get("width") == 8:
                value = fixed.get("value")
                try:
                    values.append(int(value, 0) if isinstance(value, str) else int(value))
                except (TypeError, ValueError):
                    pass

    expected_values = {
        value
        for start, end in ranges
        for value in range(start, end + 1)
    }
    seen_values = set(values)
    missing = sorted(expected_values - seen_values)
    duplicate_count = len(values) - len(seen_values)

    result: dict[str, Any] = {
        "prefix": prefix,
        "files": len(existing_files),
        "expected_files": len(ranges),
        "rows": len(rows),
        "sat": sat,
        "unsat": unsat,
        "bad_files": bad_files,
        "missing_values": [hex(value) for value in missing],
        "missing_count": len(missing),
        "duplicate_value_count": duplicate_count,
        "complete": not bad_files and not missing and duplicate_count == 0,
    }
    if values:
        result["value_min"] = hex(min(values))
        result["value_max"] = hex(max(values))
    if vars_seen:
        result["vars_min"] = min(vars_seen)
        result["vars_max"] = max(vars_seen)
    if clauses_seen:
        result["clauses_min"] = min(clauses_seen)
        result["clauses_max"] = max(clauses_seen)
    return result


def run_shard(args: argparse.Namespace, start: int, end: int) -> dict[str, Any]:
    summary = summary_path(args.prefix, start, end)
    if args.resume and complete_shard(summary, start, end):
        return {"start": start, "end": end, "returncode": 0, "summary": str(summary), "skipped": True}

    values = ",".join(f"0x{value:02x}" for value in range(start, end + 1))
    label = f"{args.label_prefix}_{start:02x}_{end:02x}"
    command = [
        str(args.python),
        str(args.runner),
        "--summary-only",
        "--summary-json",
        str(summary),
        "--case",
        f"{hex(args.x1)}:{hex(args.x2low7)}:{label}",
        "--T",
        str(args.T),
        "--tail-limbs",
        str(args.tail_limbs),
        "--arith-bits",
        "0",
        "--exact-tail-carry-limbs",
        str(args.exact_tail_carry_limbs),
        "--exact-carry-bits",
        str(args.exact_carry_bits),
        "--lowlift-q",
        str(args.lowlift_q),
        "--x6",
        hex(args.x6),
        "--branch-low",
        str(args.branch_low),
        "--branch-high",
        str(args.branch_high),
        "--fix-p-range-sweep",
        f"272:8:{values}",
    ]
    if args.q_interval_bound:
        command.append("--q-interval-bound")
    for prime in args.odd_residue_prime:
        command.extend(["--odd-residue-prime", str(prime)])

    if args.dry_run:
        return {
            "start": start,
            "end": end,
            "returncode": 0,
            "summary": str(summary),
            "stdout": str(stdout_path(args.prefix, start, end)),
            "command": command,
            "skipped": False,
        }

    with stdout_path(args.prefix, start, end).open("w", encoding="utf-8") as stdout:
        process = subprocess.run(
            ["timeout", f"{args.timeout_seconds}s", *command],
            cwd=ROOT,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    return {
        "start": start,
        "end": end,
        "returncode": process.returncode,
        "summary": str(summary),
        "stdout": str(stdout_path(args.prefix, start, end)),
        "skipped": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x1", type=parse_int, default=0x9B183CDCC)
    parser.add_argument("--x2low7", type=parse_int, required=True)
    parser.add_argument("--x6", type=parse_int, default=0x245521490BD)
    parser.add_argument("--branch-low", type=int, default=0)
    parser.add_argument("--branch-high", type=int, default=0)
    parser.add_argument("--prefix")
    parser.add_argument("--label-prefix")
    parser.add_argument("--value-start", type=parse_int, default=0)
    parser.add_argument("--value-stop", type=parse_int, default=0x100)
    parser.add_argument("--shard-width", type=int, default=8)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--runner", type=Path, default=RUNNER)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--T", type=int, default=784)
    parser.add_argument("--tail-limbs", type=int, default=1)
    parser.add_argument("--exact-tail-carry-limbs", type=int, default=1)
    parser.add_argument("--exact-carry-bits", type=int, default=272)
    parser.add_argument("--lowlift-q", type=int, default=272)
    parser.add_argument("--q-interval-bound", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--odd-residue-prime", action="append", type=int, default=[3, 5, 7, 11])
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.x2low7 < 0 or args.x2low7 >= 128:
        raise SystemExit("--x2low7 must be in 0..127")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    ranges = shard_ranges(args.value_start, args.value_stop, args.shard_width)
    if args.prefix is None:
        args.prefix = f"/tmp/ct07_exactcarry_x2low7_{args.x2low7:02x}_x2next8"
    if args.label_prefix is None:
        args.label_prefix = f"exactcarry_fixed_x2_{args.x2low7:02x}_sweep"

    shard_results = []
    if not args.aggregate_only:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_to_range = {
                executor.submit(run_shard, args, start, end): (start, end)
                for start, end in ranges
            }
            for future in concurrent.futures.as_completed(future_to_range):
                shard_results.append(future.result())
    shard_results.sort(key=lambda item: (item["start"], item["end"]))

    payload = {
        "event": "exactcarry_x2next_sweep",
        "x1": hex(args.x1),
        "x2low7": hex(args.x2low7),
        "x6": hex(args.x6),
        "prefix": args.prefix,
        "ranges": [{"start": start, "end": end} for start, end in ranges],
        "shards": shard_results,
        "aggregate": aggregate(args.prefix, ranges),
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    failures = [item for item in shard_results if item.get("returncode") not in (0, None)]
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
