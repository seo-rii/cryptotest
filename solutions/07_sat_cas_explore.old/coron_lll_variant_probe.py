#!/usr/bin/env python3
"""Bounded LLL/echelon variant probe for the s=46,k=6 Coron row."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ERROR_STATUSES = {"process_error", "json_parse_error", "runner_error", "error"}


def parse_csv(raw_value: str, option_name: str) -> list[str]:
    values = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not values:
        raise SystemExit(f"{option_name} must contain at least one value")
    return values


def parse_float_csv(raw_value: str, option_name: str) -> list[float]:
    values: list[float] = []
    for part in parse_csv(raw_value, option_name):
        try:
            value = float(part)
        except ValueError as exc:
            raise SystemExit(f"{option_name} contains a non-float value: {part}") from exc
        if not 0 < value < 1:
            raise SystemExit(f"{option_name} values must be between 0 and 1: {part}")
        values.append(value)
    return values


def parse_variants(raw_value: str) -> list[str]:
    variants: list[str] = []
    for value in parse_csv(raw_value, "--variants"):
        if value == "both":
            variants.extend(("direct", "projected"))
            continue
        if value not in {"direct", "projected"}:
            raise SystemExit(f"--variants contains an unsupported variant: {value}")
        variants.append(value)
    deduped: list[str] = []
    for variant in variants:
        if variant not in deduped:
            deduped.append(variant)
    return deduped


def extract_json(stdout: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        stripped = stdout.strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    if isinstance(payload, dict):
        return payload
    return None


def row_number(row: dict[str, Any], key: str) -> int | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def row_float(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run_combination(
    sweep_script: Path,
    script_dir: Path,
    lll_delta: float,
    echelon_algorithm: str,
    variant: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-B",
        str(sweep_script),
        "--s-values",
        "46",
        "--k-values",
        "6",
        "--variant",
        variant,
        "--lll-delta",
        str(lll_delta),
        "--echelon-algorithm",
        echelon_algorithm,
        "--max-rows",
        "1",
    ]
    record: dict[str, Any] = {
        "event": "coron_lll_variant_row",
        "s": 46,
        "k": 6,
        "variant": variant,
        "lll_delta": float(lll_delta),
        "echelon_algorithm": echelon_algorithm,
        "timeout_seconds": float(timeout_seconds),
        "command": command,
        "timeout": False,
    }
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    started_at = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=script_dir,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        record["status"] = "timeout"
        record["timeout"] = True
        record["stdout_tail"] = (exc.stdout or "")[-2000:] if isinstance(exc.stdout, str) else ""
        record["stderr_tail"] = (exc.stderr or "")[-2000:] if isinstance(exc.stderr, str) else ""
    except Exception as exc:  # noqa: BLE001 - diagnostic runner should keep sweeping.
        record["status"] = "runner_error"
        record["error"] = f"{type(exc).__name__}: {exc}"
    else:
        record["returncode"] = int(proc.returncode)
        record["stdout_tail"] = proc.stdout[-2000:]
        record["stderr_tail"] = proc.stderr[-2000:]
        if proc.returncode != 0:
            record["status"] = "process_error"
        else:
            payload = extract_json(proc.stdout)
            if payload is None:
                record["status"] = "json_parse_error"
            else:
                sweep_rows = payload.get("rows") or []
                row = sweep_rows[0] if sweep_rows else {}
                if not isinstance(row, dict):
                    row = {}
                record["report_status"] = payload.get("status")
                record["row"] = row
                record["status"] = str(row.get("status", payload.get("status", "missing_row")))
    finally:
        record["elapsed_seconds"] = round(time.monotonic() - started_at, 6)
    return record


def summarize(
    rows: list[dict[str, Any]],
    lll_deltas: list[float],
    echelon_algorithms: list[str],
    variants: list[str],
    timeout_seconds: float,
    elapsed_seconds: float,
) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    reconstructed_counts: list[int] = []
    short_row_counts: list[int] = []
    margins: list[float] = []

    for record in rows:
        status = str(record.get("status", "missing_status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        row = record.get("row") or {}
        if not isinstance(row, dict):
            continue
        reconstructed_count = row_number(row, "reconstructed_polynomial_count")
        if reconstructed_count is not None:
            reconstructed_counts.append(reconstructed_count)
        short_row_count = row_number(row, "short_row_count")
        if short_row_count is not None:
            short_row_counts.append(short_row_count)
        margin = row_float(row, "primitive_margin")
        if margin is not None:
            margins.append(margin)

    max_reconstructed = max(reconstructed_counts) if reconstructed_counts else 0
    best_rows = [
        record
        for record in rows
        if row_number(record.get("row") or {}, "reconstructed_polynomial_count") == max_reconstructed
    ]
    return {
        "event": "coron_lll_variant_summary",
        "status": "ok",
        "s": 46,
        "k": 6,
        "lll_deltas": lll_deltas,
        "echelon_algorithms": echelon_algorithms,
        "variants": variants,
        "timeout_seconds": float(timeout_seconds),
        "row_count": len(rows),
        "status_counts": status_counts,
        "timeouts": sum(1 for row in rows if row.get("timeout")),
        "errors": sum(1 for row in rows if str(row.get("status")) in ERROR_STATUSES),
        "reconstructed_polynomial_counts": reconstructed_counts,
        "short_row_counts": short_row_counts,
        "reconstructed_positive_rows": sum(1 for value in reconstructed_counts if value > 0),
        "max_reconstructed_polynomial_count": max_reconstructed,
        "max_short_row_count": max(short_row_counts) if short_row_counts else None,
        "best_primitive_margin": max(margins) if margins else None,
        "best_rows": [
            {
                "variant": record.get("variant"),
                "lll_delta": record.get("lll_delta"),
                "echelon_algorithm": record.get("echelon_algorithm"),
                "status": record.get("status"),
                "reconstructed_polynomial_count": row_number(record.get("row") or {}, "reconstructed_polynomial_count"),
                "short_row_count": row_number(record.get("row") or {}, "short_row_count"),
                "primitive_margin": row_float(record.get("row") or {}, "primitive_margin"),
                "elapsed_seconds": record.get("elapsed_seconds"),
            }
            for record in best_rows
        ],
        "elapsed_seconds": round(elapsed_seconds, 6),
    }


def print_text_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    for record in rows:
        row = record.get("row") or {}
        if not isinstance(row, dict):
            row = {}
        reconstructed_count = row_number(row, "reconstructed_polynomial_count")
        short_row_count = row_number(row, "short_row_count")
        margin = row_float(row, "primitive_margin")
        print(
            "variant={variant} delta={delta:g} echelon={echelon} status={status} "
            "reconstructed={reconstructed} short_rows={short_rows} margin={margin} "
            "timeout={timeout} elapsed={elapsed}s".format(
                variant=record.get("variant"),
                delta=float(record.get("lll_delta", 0.0)),
                echelon=record.get("echelon_algorithm"),
                status=record.get("status"),
                reconstructed="NA" if reconstructed_count is None else reconstructed_count,
                short_rows="NA" if short_row_count is None else short_row_count,
                margin="NA" if margin is None else f"{margin:.6g}",
                timeout=record.get("timeout"),
                elapsed=record.get("elapsed_seconds"),
            )
        )
    print(
        "rows={row_count} reconstructed_positive={reconstructed_positive_rows} "
        "max_reconstructed={max_reconstructed_polynomial_count} "
        "max_short_rows={max_short_row_count} timeouts={timeouts} errors={errors} "
        "best_margin={best_primitive_margin} elapsed={elapsed_seconds}s".format(**summary)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lll-deltas", default="0.75,0.8,0.99")
    parser.add_argument("--echelon-algorithms", default="default")
    parser.add_argument("--variants", default="direct,projected")
    parser.add_argument("--timeout-seconds", type=float, default=25.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")

    lll_deltas = parse_float_csv(args.lll_deltas, "--lll-deltas")
    echelon_algorithms = parse_csv(args.echelon_algorithms, "--echelon-algorithms")
    variants = parse_variants(args.variants)
    script_dir = Path(__file__).resolve().parent
    sweep_script = script_dir / "coron_reconstruction_sweep.py"
    if not sweep_script.exists():
        raise SystemExit(f"missing sweep script: {sweep_script}")

    started_at = time.monotonic()
    rows: list[dict[str, Any]] = []
    for echelon_algorithm in echelon_algorithms:
        for lll_delta in lll_deltas:
            for variant in variants:
                rows.append(
                    run_combination(
                        sweep_script,
                        script_dir,
                        lll_delta,
                        echelon_algorithm,
                        variant,
                        args.timeout_seconds,
                    )
                )

    summary = summarize(
        rows,
        lll_deltas,
        echelon_algorithms,
        variants,
        args.timeout_seconds,
        time.monotonic() - started_at,
    )
    payload = {"summary": summary, "rows": rows}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print_text_report(summary, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
