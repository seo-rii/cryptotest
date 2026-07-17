#!/usr/bin/env python3
"""Heuristic folded-Coron success oracle for edge-fixed branches.

This is a verifier/ranking hook, not a sound UNSAT oracle.  It runs the
positive folded branch with optional x2/x5 edge fixed ranges, reconstructs
Coron relations, tries resultants, and reports only verified factors as a hard
success signal.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent

PROFILE_RANGES = {
    "base": [],
    "x2": ["265:84:0"],
    "x5": ["682:87:0"],
    "x2_x3": ["265:84:0", "362:78:0"],
    "x4_x5": ["600:69:0", "682:87:0"],
}


def parse_profile(raw_value: str) -> list[str]:
    names = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not names:
        raise SystemExit("--profiles must contain at least one profile")
    unknown = [name for name in names if name not in PROFILE_RANGES]
    if unknown:
        raise SystemExit(f"unknown profile(s): {', '.join(unknown)}")
    return names


def extract_json(stdout: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        start = stdout.find("{")
        end = stdout.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(stdout[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def run_profile(args: argparse.Namespace, profile: str) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        str(HERE / "coron_reconstruction_sweep.py"),
        "--x0",
        hex(args.x0),
        "--x1",
        hex(args.x1),
        "--x7",
        hex(args.x7),
        "--s-values",
        "46",
        "--k-values",
        "6",
        "--variant",
        args.variant,
        "--lll-delta",
        str(args.lll_delta),
        "--max-rows",
        "1",
        "--run-roots",
        "--roots-methods",
        args.roots_methods,
        "--max-roots",
        str(args.max_roots),
    ]
    fixed_ranges = list(PROFILE_RANGES[profile])
    for item in args.fix_p_range:
        fixed_ranges.append(item)
    for fixed_range in fixed_ranges:
        command.extend(["--fix-p-range", fixed_range])

    started_at = time.monotonic()
    record: dict[str, Any] = {
        "profile": profile,
        "fixed_ranges": fixed_ranges,
        "command": command,
        "timeout": False,
    }
    try:
        process = subprocess.run(
            command,
            cwd=HERE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            capture_output=True,
            timeout=args.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        record["status"] = "timeout"
        record["timeout"] = True
        record["stdout_tail"] = (exc.stdout or "")[-1000:] if isinstance(exc.stdout, str) else ""
        record["stderr_tail"] = (exc.stderr or "")[-1000:] if isinstance(exc.stderr, str) else ""
    else:
        record["returncode"] = int(process.returncode)
        record["stdout_tail"] = process.stdout[-1000:]
        record["stderr_tail"] = process.stderr[-1000:]
        if process.returncode != 0:
            record["status"] = "process_error"
        else:
            payload = extract_json(process.stdout)
            if payload is None:
                record["status"] = "json_parse_error"
            else:
                row = (payload.get("rows") or [{}])[0]
                if not isinstance(row, dict):
                    row = {}
                verified_factors = []
                root_count = 0
                for result in (row.get("root_results") or {}).values():
                    if not isinstance(result, dict):
                        continue
                    root_count += int(result.get("root_count") or 0)
                    verified_factors.extend(result.get("verified_factors") or [])
                record.update(
                    {
                        "status": "factored" if verified_factors else str(row.get("status", "missing_row")),
                        "row_status": row.get("status"),
                        "primitive_margin": row.get("primitive_margin"),
                        "short_row_count": row.get("short_row_count"),
                        "reconstructed_polynomial_count": row.get("reconstructed_polynomial_count"),
                        "root_count": root_count,
                        "verified_factor_count": len(verified_factors),
                        "verified_factors": verified_factors,
                        "row": row,
                    }
                )
    record["elapsed_seconds"] = round(time.monotonic() - started_at, 6)
    return record


def summarize(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "missing_status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "event": "coron_edge_oracle",
        "profiles": parse_profile(args.profiles),
        "variant": args.variant,
        "lll_delta": float(args.lll_delta),
        "row_count": len(rows),
        "status_counts": status_counts,
        "timeouts": sum(1 for row in rows if row.get("timeout")),
        "errors": sum(1 for row in rows if str(row.get("status")) in {"process_error", "json_parse_error"}),
        "reconstructed_positive_rows": sum(
            1 for row in rows if int(row.get("reconstructed_polynomial_count") or 0) > 0
        ),
        "root_positive_rows": sum(1 for row in rows if int(row.get("root_count") or 0) > 0),
        "verified_factor_count": sum(int(row.get("verified_factor_count") or 0) for row in rows),
        "compact_rows": [
            {
                "profile": row.get("profile"),
                "status": row.get("status"),
                "fixed_ranges": row.get("fixed_ranges"),
                "primitive_margin": row.get("primitive_margin"),
                "short_row_count": row.get("short_row_count"),
                "reconstructed_polynomial_count": row.get("reconstructed_polynomial_count"),
                "root_count": row.get("root_count"),
                "verified_factor_count": row.get("verified_factor_count"),
                "elapsed_seconds": row.get("elapsed_seconds"),
            }
            for row in rows
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", default="x2,x5")
    parser.add_argument("--fix-p-range", action="append", default=[])
    parser.add_argument("--variant", choices=("direct", "projected"), default="direct")
    parser.add_argument("--x0", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x1", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x7", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--lll-delta", type=float, default=0.8)
    parser.add_argument("--roots-methods", default="resultants")
    parser.add_argument("--max-roots", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.max_roots <= 0:
        raise SystemExit("--max-roots must be positive")
    if args.x0 < 0 or args.x0 >= 16:
        raise SystemExit("--x0 must fit 4 bits")
    if args.x1 < 0 or args.x1 >= (1 << 39):
        raise SystemExit("--x1 must fit 39 bits")
    if args.x7 < 0 or args.x7 >= 16:
        raise SystemExit("--x7 must fit 4 bits")

    profiles = parse_profile(args.profiles)
    rows = [run_profile(args, profile) for profile in profiles]
    payload = {"summary": summarize(rows, args), "rows": rows}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
