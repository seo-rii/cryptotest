#!/usr/bin/env python3
"""Bounded semi-programmatic loop for folded-Coron edge candidates.

This runner is intentionally small: it builds candidate edge assignments that
are strong enough to trigger the folded-Coron reconstruction threshold, invokes
``coron_edge_oracle.py`` for each candidate, and summarizes verified factors.

It is not a sound pruning oracle.  Failed Coron runs are only diagnostic; only
verified factors are success.
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


def parse_int_csv(raw_value: str, option_name: str) -> list[int]:
    values: list[int] = []
    for part in raw_value.split(","):
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


def parse_optional_int_csv(raw_value: str, option_name: str) -> list[int]:
    if not raw_value.strip():
        return []
    return parse_int_csv(raw_value, option_name)


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


def qrank_x5_high9(max_cubes: int, top: int) -> list[dict[str, Any]]:
    command = [
        sys.executable,
        "-B",
        str(HERE / "q_edge_rank_probe.py"),
        "--range-set",
        "x5_high9=760:9",
        "--max-cubes",
        str(max_cubes),
        "--top",
        str(top),
        "--json",
    ]
    process = subprocess.run(
        command,
        cwd=HERE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        return [
            {
                "status": "qrank_process_error",
                "command": command,
                "returncode": process.returncode,
                "stderr_tail": process.stderr[-1000:],
            }
        ]
    payload = extract_json(process.stdout)
    if payload is None:
        return [
            {
                "status": "qrank_json_parse_error",
                "command": command,
                "stdout_tail": process.stdout[-1000:],
                "stderr_tail": process.stderr[-1000:],
            }
        ]
    reports = payload.get("range_sets") or []
    if not reports:
        return []
    return list(reports[0].get("top_candidates") or [])


def qbeam_x5_high48(beam_width: int, per_parent_cubes: int) -> list[dict[str, Any]]:
    command = [
        sys.executable,
        "-B",
        str(HERE / "q_x5_beam_search.py"),
        "--beam-width",
        str(beam_width),
        "--per-parent-cubes",
        str(per_parent_cubes),
        "--json",
    ]
    process = subprocess.run(
        command,
        cwd=HERE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        return [
            {
                "status": "qbeam_process_error",
                "command": command,
                "returncode": process.returncode,
                "stderr_tail": process.stderr[-1000:],
            }
        ]
    payload = extract_json(process.stdout)
    if payload is None:
        return [
            {
                "status": "qbeam_json_parse_error",
                "command": command,
                "stdout_tail": process.stdout[-1000:],
                "stderr_tail": process.stderr[-1000:],
            }
        ]
    return list(payload.get("final_candidates") or [])


def qbeam_x5_x7_high48(beam_width: int, per_parent_cubes: int, x7_values: str) -> list[dict[str, Any]]:
    command = [
        sys.executable,
        "-B",
        str(HERE / "q_x5_x7_beam_search.py"),
        "--beam-width",
        str(beam_width),
        "--per-parent-cubes",
        str(per_parent_cubes),
        "--json",
    ]
    if x7_values.strip():
        command.extend(["--x7-values", x7_values])
    process = subprocess.run(
        command,
        cwd=HERE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        return [
            {
                "status": "qbeam_x7_process_error",
                "command": command,
                "returncode": process.returncode,
                "stderr_tail": process.stderr[-1000:],
            }
        ]
    payload = extract_json(process.stdout)
    if payload is None:
        return [
            {
                "status": "qbeam_x7_json_parse_error",
                "command": command,
                "stdout_tail": process.stdout[-1000:],
                "stderr_tail": process.stderr[-1000:],
            }
        ]
    return list(payload.get("final_candidates") or [])


def qbeam_x5_extended(
    width: int,
    beam_width: int,
    per_parent_cubes: int,
    x0: int,
    x1: int | None,
    x7: int,
) -> list[dict[str, Any]]:
    command = [
        sys.executable,
        "-B",
        str(HERE / "q_x5_extended_beam_search.py"),
        "--x5-width",
        str(width),
        "--x0",
        hex(x0),
    ]
    if x1 is not None:
        command.extend(["--x1", hex(x1)])
    command.extend(
        [
            "--x7",
            hex(x7),
            "--beam-width",
            str(beam_width),
            "--per-parent-cubes",
            str(per_parent_cubes),
            "--json",
        ]
    )
    process = subprocess.run(
        command,
        cwd=HERE,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        return [
            {
                "status": "qbeam_extended_process_error",
                "command": command,
                "returncode": process.returncode,
                "stderr_tail": process.stderr[-1000:],
            }
        ]
    payload = extract_json(process.stdout)
    if payload is None:
        return [
            {
                "status": "qbeam_extended_json_parse_error",
                "command": command,
                "stdout_tail": process.stdout[-1000:],
                "stderr_tail": process.stderr[-1000:],
            }
        ]
    return list(payload.get("final_candidates") or [])


def make_candidates(args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    if args.include_x2:
        x2_values = parse_int_csv(args.x2_values, "--x2-values")
        for value in x2_values[: args.max_x2_candidates]:
            if value < 0 or value >= (1 << 32):
                diagnostics.append({"status": "skipped_x2_value_out_of_range", "value": value})
                continue
            candidates.append(
                {
                    "kind": "x2_low32",
                    "fixed_range": f"265:32:{hex(value)}",
                    "value": value,
                    "value_hex": hex(value),
                    "source": "explicit_values",
                }
            )

    if args.include_x5:
        for value in parse_optional_int_csv(args.x5_values, "--x5-values"):
            if value < 0 or value >= (1 << 48):
                diagnostics.append({"status": "skipped_x5_value_out_of_range", "value": value})
                continue
            candidates.append(
                {
                    "kind": "x5_high48",
                    "fixed_range": f"721:48:{hex(value)}",
                    "value": value,
                    "value_hex": hex(value),
                    "source": "explicit_values",
                }
            )
        if args.x5_beam:
            for item in qbeam_x5_high48(args.x5_beam_width, args.x5_per_parent_cubes):
                if item.get("status", "").startswith("qbeam_"):
                    diagnostics.append(item)
                    continue
                value = int(item["value"])
                candidates.append(
                    {
                        "kind": "x5_high48",
                        "fixed_range": f"721:48:{hex(value)}",
                        "value": value,
                        "value_hex": hex(value),
                        "source": "q_x5_beam_search",
                        "q_prefix_bits": item.get("q_prefix_bits"),
                        "q_known_bits": item.get("q_known_bits"),
                        "q_interval_width_bits": item.get("q_interval_width_bits"),
                    }
                )
        if args.x5_x7_beam:
            for item in qbeam_x5_x7_high48(args.x5_beam_width, args.x5_per_parent_cubes, args.x7_values):
                if item.get("status", "").startswith("qbeam_x7_"):
                    diagnostics.append(item)
                    continue
                value = int(item["value"])
                x7_value = int(item["x7"])
                candidates.append(
                    {
                        "kind": "x5_high48_x7",
                        "fixed_range": f"721:48:{hex(value)}",
                        "value": value,
                        "value_hex": hex(value),
                        "x7": x7_value,
                        "x7_hex": hex(x7_value),
                        "source": "q_x5_x7_beam_search",
                        "q_prefix_bits": item.get("q_prefix_bits"),
                        "q_known_bits": item.get("q_known_bits"),
                        "q_interval_width_bits": item.get("q_interval_width_bits"),
                        "fixed_ranges": item.get("fixed_ranges"),
                    }
                )
        if args.x5_extended_beam:
            for item in qbeam_x5_extended(
                args.x5_extended_width,
                args.x5_beam_width,
                args.x5_per_parent_cubes,
                args.x0,
                args.x1,
                args.x7,
            ):
                if item.get("status", "").startswith("qbeam_extended_"):
                    diagnostics.append(item)
                    continue
                candidates.append(
                    {
                        "kind": f"x5_high{args.x5_extended_width}",
                        "fixed_range": str(item["range"]),
                        "value": int(item["value"]),
                        "value_hex": item.get("value_hex"),
                        "source": "q_x5_extended_beam_search",
                        "x0": args.x0,
                        "x0_hex": hex(args.x0),
                        "x1": args.x1,
                        "x1_hex": None if args.x1 is None else hex(args.x1),
                        "x7": args.x7,
                        "x7_hex": hex(args.x7),
                        "q_prefix_bits": item.get("q_prefix_bits"),
                        "q_known_bits": item.get("q_known_bits"),
                        "q_interval_width_bits": item.get("q_interval_width_bits"),
                    }
                )
        top_high9 = []
        if args.x5_high9_top:
            top_high9 = qrank_x5_high9(args.x5_qrank_max_cubes, args.x5_high9_top)
        suffix_values = parse_int_csv(args.x5_suffix_values, "--x5-suffix-values")
        for item in top_high9:
            if item.get("status", "").startswith("qrank_"):
                diagnostics.append(item)
                continue
            fixed_ranges = item.get("fixed_ranges") or []
            if not fixed_ranges:
                continue
            high9 = int(fixed_ranges[0]["value"])
            for suffix in suffix_values:
                if suffix < 0 or suffix >= (1 << 39):
                    diagnostics.append(
                        {
                            "status": "skipped_x5_suffix_out_of_range",
                            "high9": high9,
                            "suffix": suffix,
                        }
                    )
                    continue
                value = (high9 << 39) | suffix
                candidates.append(
                    {
                        "kind": "x5_high48",
                        "fixed_range": f"721:48:{hex(value)}",
                        "value": value,
                        "value_hex": hex(value),
                        "high9": high9,
                        "high9_hex": hex(high9),
                        "suffix39": suffix,
                        "suffix39_hex": hex(suffix),
                        "source": "q_edge_rank_probe",
                        "q_prefix_bits": item.get("q_prefix_bits"),
                        "q_known_bits": item.get("q_known_bits"),
                        "q_interval_width_bits": item.get("q_interval_width_bits"),
                    }
                )
    return candidates[: args.max_candidates], diagnostics


def run_candidate(args: argparse.Namespace, candidate: dict[str, Any]) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        str(HERE / "coron_edge_oracle.py"),
        "--profiles",
        "base",
    ]
    if "x0" in candidate:
        command.extend(["--x0", hex(int(candidate["x0"]))])
    if candidate.get("x1") is not None:
        command.extend(["--x1", hex(int(candidate["x1"]))])
    if "x7" in candidate:
        command.extend(["--x7", hex(int(candidate["x7"]))])
    command.extend(
        [
            "--fix-p-range",
            str(candidate["fixed_range"]),
            "--timeout-seconds",
            str(args.oracle_timeout_seconds),
            "--max-roots",
            str(args.max_roots),
            "--json",
        ]
    )
    started_at = time.monotonic()
    record: dict[str, Any] = {
        "candidate": candidate,
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
            timeout=args.oracle_timeout_seconds + 5.0,
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
                summary = payload.get("summary") or {}
                rows = payload.get("rows") or []
                first_row = rows[0] if rows and isinstance(rows[0], dict) else {}
                record.update(
                    {
                        "status": first_row.get("status", summary.get("status", "missing_row")),
                        "verified_factor_count": summary.get("verified_factor_count", 0),
                        "reconstructed_polynomial_count": first_row.get("reconstructed_polynomial_count"),
                        "short_row_count": first_row.get("short_row_count"),
                        "root_count": first_row.get("root_count"),
                        "primitive_margin": first_row.get("primitive_margin"),
                        "summary": summary,
                    }
                )
    record["elapsed_seconds"] = round(time.monotonic() - started_at, 6)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-x2", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-x5", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--x2-values", default="0")
    parser.add_argument("--max-x2-candidates", type=int, default=1)
    parser.add_argument("--x5-high9-top", type=int, default=2)
    parser.add_argument("--x5-qrank-max-cubes", type=int, default=128)
    parser.add_argument("--x5-beam", action="store_true")
    parser.add_argument("--x5-x7-beam", action="store_true")
    parser.add_argument("--x5-extended-beam", action="store_true")
    parser.add_argument("--x5-extended-width", type=int, default=87)
    parser.add_argument("--x0", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x1", type=lambda text: int(text, 0))
    parser.add_argument("--x7", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x5-beam-width", type=int, default=2)
    parser.add_argument("--x5-per-parent-cubes", type=int, default=8)
    parser.add_argument("--x7-values", default="")
    parser.add_argument("--x5-values", default="")
    parser.add_argument("--x5-suffix-values", default="0")
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--oracle-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--max-roots", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true", help="build candidates without invoking Coron")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.max_candidates < 1:
        raise SystemExit("--max-candidates must be positive")
    if args.max_x2_candidates < 0:
        raise SystemExit("--max-x2-candidates must be nonnegative")
    if args.x5_high9_top < 0:
        raise SystemExit("--x5-high9-top must be nonnegative")
    if args.x5_qrank_max_cubes < 0:
        raise SystemExit("--x5-qrank-max-cubes must be nonnegative")
    if args.x5_beam_width < 1:
        raise SystemExit("--x5-beam-width must be positive")
    if args.x5_per_parent_cubes < 1:
        raise SystemExit("--x5-per-parent-cubes must be positive")
    if args.x5_extended_width <= 0 or args.x5_extended_width > 87:
        raise SystemExit("--x5-extended-width must be in 1..87")
    if args.x0 < 0 or args.x0 >= 16:
        raise SystemExit("--x0 must fit 4 bits")
    if args.x1 is not None and (args.x1 < 0 or args.x1 >= (1 << 39)):
        raise SystemExit("--x1 must fit 39 bits")
    if args.x7 < 0 or args.x7 >= 16:
        raise SystemExit("--x7 must fit 4 bits")
    if args.oracle_timeout_seconds <= 0:
        raise SystemExit("--oracle-timeout-seconds must be positive")

    started_at = time.monotonic()
    candidates, diagnostics = make_candidates(args)
    rows = [] if args.dry_run else [run_candidate(args, candidate) for candidate in candidates]
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "missing_status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "event": "coron_edge_candidate_loop",
        "dry_run": bool(args.dry_run),
        "candidate_count": len(candidates),
        "diagnostic_count": len(diagnostics),
        "row_count": len(rows),
        "status_counts": status_counts,
        "verified_factor_count": sum(int(row.get("verified_factor_count") or 0) for row in rows),
        "reconstructed_positive_rows": sum(
            1 for row in rows if int(row.get("reconstructed_polynomial_count") or 0) > 0
        ),
        "root_positive_rows": sum(1 for row in rows if int(row.get("root_count") or 0) > 0),
        "timeouts": sum(1 for row in rows if row.get("timeout")),
        "errors": sum(1 for row in rows if str(row.get("status")) in {"process_error", "json_parse_error"}),
        "elapsed_seconds": round(time.monotonic() - started_at, 6),
    }
    payload = {
        "summary": summary,
        "candidates": candidates,
        "diagnostics": diagnostics,
        "rows": rows,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
