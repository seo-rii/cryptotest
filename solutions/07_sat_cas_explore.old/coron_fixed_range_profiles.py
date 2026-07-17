#!/usr/bin/env python3
"""Compare edge fixed-range profiles for the folded Coron verifier.

The base positive-margin branch fixes x0, x1, x6, and x7.  This wrapper checks
whether additionally fixing contiguous low-edge or high-edge p-ranges changes
the actual Coron reconstruction signal.  Interior fixed ranges are intentionally
not part of the defaults because the folded x variable models one contiguous
middle block.
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

DEFAULT_PROFILES = {
    "base": [],
    "x2": ["265:84:0"],
    "x2_x3": ["265:84:0", "362:78:0"],
    "x5": ["682:87:0"],
    "x4_x5": ["600:69:0", "682:87:0"],
    "x2_x3_x4_x5": ["265:84:0", "362:78:0", "600:69:0", "682:87:0"],
}


def parse_profile_names(raw_value: str) -> list[str]:
    names = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not names:
        raise SystemExit("--profiles must contain at least one profile")
    unknown = [name for name in names if name not in DEFAULT_PROFILES]
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


def run_profile(
    name: str,
    fixed_ranges: list[str],
    variant: str,
    lll_delta: float,
    timeout_seconds: float,
    metadata_only: bool,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        str(HERE / "coron_reconstruction_sweep.py"),
        "--s-values",
        "46",
        "--k-values",
        "6",
        "--variant",
        variant,
        "--lll-delta",
        str(lll_delta),
        "--max-rows",
        "1",
    ]
    if metadata_only:
        command.append("--metadata-only")
    for fixed_range in fixed_ranges:
        command.extend(["--fix-p-range", fixed_range])

    started_at = time.monotonic()
    record: dict[str, Any] = {
        "profile": name,
        "fixed_ranges": fixed_ranges,
        "variant": variant,
        "lll_delta": float(lll_delta),
        "metadata_only": bool(metadata_only),
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
            timeout=timeout_seconds,
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
                record["status"] = str(row.get("status", payload.get("status", "missing_row")))
                record["row"] = row
    record["elapsed_seconds"] = round(time.monotonic() - started_at, 6)
    return record


def summarize(rows: list[dict[str, Any]], profiles: list[str], args: argparse.Namespace) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "missing_status"))
        status_counts[status] = status_counts.get(status, 0) + 1

    reconstructed_counts = []
    margins = []
    compact_rows = []
    for record in rows:
        row = record.get("row") or {}
        if not isinstance(row, dict):
            row = {}
        reconstructed = row.get("reconstructed_polynomial_count")
        if reconstructed is not None:
            reconstructed_counts.append(int(reconstructed))
        margin = row.get("primitive_margin")
        if margin is not None:
            margins.append(float(margin))
        compact_rows.append(
            {
                "profile": record.get("profile"),
                "status": record.get("status"),
                "fixed_ranges": record.get("fixed_ranges"),
                "low_bits": row.get("low_bits"),
                "high_start": row.get("high_start"),
                "Xbits": row.get("Xbits"),
                "Ybits": row.get("Ybits"),
                "primitive_margin": row.get("primitive_margin"),
                "short_row_count": row.get("short_row_count"),
                "reconstructed_polynomial_count": row.get("reconstructed_polynomial_count"),
                "elapsed_seconds": record.get("elapsed_seconds"),
            }
        )
    return {
        "event": "coron_fixed_range_profiles",
        "profiles": profiles,
        "variant": args.variant,
        "lll_delta": float(args.lll_delta),
        "metadata_only": bool(args.metadata_only),
        "row_count": len(rows),
        "status_counts": status_counts,
        "timeouts": sum(1 for row in rows if row.get("timeout")),
        "errors": sum(1 for row in rows if str(row.get("status")) in {"process_error", "json_parse_error"}),
        "reconstructed_positive_rows": sum(1 for value in reconstructed_counts if value > 0),
        "max_reconstructed_polynomial_count": max(reconstructed_counts) if reconstructed_counts else 0,
        "best_primitive_margin": max(margins) if margins else None,
        "compact_rows": compact_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", default="base,x2,x2_x3,x5,x4_x5,x2_x3_x4_x5")
    parser.add_argument("--variant", choices=("direct", "projected"), default="direct")
    parser.add_argument("--lll-delta", type=float, default=0.8)
    parser.add_argument("--timeout-seconds", type=float, default=25.0)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    profiles = parse_profile_names(args.profiles)
    rows = [
        run_profile(
            name,
            DEFAULT_PROFILES[name],
            args.variant,
            args.lll_delta,
            args.timeout_seconds,
            args.metadata_only,
        )
        for name in profiles
    ]
    report = {"summary": summarize(rows, profiles, args), "rows": rows}
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for item in report["summary"]["compact_rows"]:
            print(
                "profile={profile} status={status} low={low_bits} high={high_start} "
                "X={Xbits} Y={Ybits} margin={primitive_margin} short={short_row_count} "
                "reconstructed={reconstructed_polynomial_count} elapsed={elapsed_seconds}s".format(**item)
            )
        print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
