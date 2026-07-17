#!/usr/bin/env python3
"""Sweep partial edge widths for the folded Coron verifier.

The full x2/x5 profiles reconstruct relations, but SAT only benefits if the
required edge assignment is smaller than the full run.  This probe varies the
contiguous low-edge x2 width or high-edge x5 suffix width and reports when the
folded-Coron margin/reconstruction threshold turns on.
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


def parse_widths(raw_value: str) -> list[int]:
    values: list[int] = []
    for part in raw_value.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            lo_text, hi_text = item.split("-", 1)
            values.extend(range(int(lo_text, 0), int(hi_text, 0) + 1))
        else:
            values.append(int(item, 0))
    if not values:
        raise SystemExit("--widths must contain at least one value")
    return values


def fixed_range_for_edge(edge: str, width: int) -> str:
    if edge == "x2":
        if width < 0 or width > 84:
            raise ValueError("x2 width must be in 0..84")
        return f"265:{width}:0"
    if edge == "x5":
        if width < 0 or width > 87:
            raise ValueError("x5 width must be in 0..87")
        # Fix the high suffix adjacent to known p[769..783], so the p high
        # unknown boundary moves downward as width grows.
        return f"{769 - width}:{width}:0"
    raise ValueError(f"unsupported edge: {edge}")


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


def run_width(args: argparse.Namespace, width: int) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        str(HERE / "coron_reconstruction_sweep.py"),
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
    ]
    if args.metadata_only:
        command.append("--metadata-only")
    if width:
        command.extend(["--fix-p-range", fixed_range_for_edge(args.edge, width)])

    started_at = time.monotonic()
    record: dict[str, Any] = {
        "edge": args.edge,
        "width": int(width),
        "fixed_range": fixed_range_for_edge(args.edge, width) if width else None,
        "metadata_only": bool(args.metadata_only),
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
                record.update(
                    {
                        "status": row.get("status", payload.get("status", "missing_row")),
                        "low_bits": row.get("low_bits"),
                        "high_start": row.get("high_start"),
                        "Xbits": row.get("Xbits"),
                        "Ybits": row.get("Ybits"),
                        "primitive_margin": row.get("primitive_margin"),
                        "short_row_count": row.get("short_row_count"),
                        "reconstructed_polynomial_count": row.get("reconstructed_polynomial_count"),
                    }
                )
    record["elapsed_seconds"] = round(time.monotonic() - started_at, 6)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge", choices=("x2", "x5"), default="x2")
    parser.add_argument("--widths", default="0,8,16,24,32,40,48,56,64,72,80,84")
    parser.add_argument("--variant", choices=("direct", "projected"), default="direct")
    parser.add_argument("--lll-delta", type=float, default=0.8)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=25.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    widths = parse_widths(args.widths)
    rows = [run_width(args, width) for width in widths]
    positive_reconstruction = [
        row for row in rows if int(row.get("reconstructed_polynomial_count") or 0) > 0
    ]
    positive_margin = [
        row for row in rows if row.get("primitive_margin") is not None and float(row["primitive_margin"]) > 0
    ]
    summary = {
        "event": "coron_edge_threshold_sweep",
        "edge": args.edge,
        "widths": widths,
        "metadata_only": bool(args.metadata_only),
        "row_count": len(rows),
        "first_positive_margin_width": positive_margin[0]["width"] if positive_margin else None,
        "first_reconstruction_width": positive_reconstruction[0]["width"] if positive_reconstruction else None,
        "max_reconstructed_polynomial_count": max(
            (int(row.get("reconstructed_polynomial_count") or 0) for row in rows),
            default=0,
        ),
        "timeouts": sum(1 for row in rows if row.get("timeout")),
    }
    payload = {"summary": summary, "rows": rows}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        for row in rows:
            print(
                "edge={edge} width={width} status={status} low={low_bits} high={high_start} "
                "margin={primitive_margin} reconstructed={reconstructed_polynomial_count} "
                "elapsed={elapsed_seconds}s".format(**row)
            )
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
