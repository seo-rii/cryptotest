#!/usr/bin/env python3
"""Bounded support-growth sweep for challenge 7 shift families.

This wraps the concrete-ish ``liftT_actual_sumset.py`` model and the lighter
``sumset_preflight.py`` proxy families so T, shift degree, caps, and optional
branch metric rows can be compared in one ranked table.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import liftT_actual_sumset as actual
import sumset_preflight as proxy


ACTUAL_FAMILY = "liftT_actual"
SIGNAL_ORDER = {"PASS": 0, "WARN": 1, "FAIL": 2}


def parse_int_list(spec: str, name: str) -> list[int]:
    values: list[int] = []
    for raw_part in spec.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if ":" in part:
            pieces = [piece.strip() for piece in part.split(":")]
            if len(pieces) not in {2, 3}:
                raise SystemExit(f"--{name} range must be start:end[:step]")
            start = int(pieces[0], 0)
            end = int(pieces[1], 0)
            step = int(pieces[2], 0) if len(pieces) == 3 else 1
            if step <= 0:
                raise SystemExit(f"--{name} range step must be positive")
            values.extend(range(start, end + 1, step))
        else:
            values.append(int(part, 0))
    if not values:
        raise SystemExit(f"--{name} must contain at least one integer")
    return list(dict.fromkeys(values))


def parse_families(spec: str) -> list[str]:
    allowed = {ACTUAL_FAMILY, "bilinear", "linear8", "cuso8", "liftT_proxy"}
    families = [part.strip() for part in spec.split(",") if part.strip()]
    if not families:
        raise SystemExit("--families must contain at least one family")
    unknown = sorted(set(families) - allowed)
    if unknown:
        raise SystemExit(f"unknown family/families: {', '.join(unknown)}")
    return list(dict.fromkeys(families))


def signal_class(signal: str) -> str:
    prefix = signal.split("_", 1)[0]
    if prefix in SIGNAL_ORDER:
        return prefix
    return "FAIL"


def row_from_report(family: str, report: dict[str, Any]) -> dict[str, Any]:
    signal = str(report["preflight_signal"])
    row = {
        "family": family,
        "T": report["T"],
        "shift_degree": report["shift_degree"],
        "cap": report.get("cap"),
        "signal_class": signal_class(signal),
        "preflight_signal": signal,
        "growth_ratio": report["growth_ratio"],
        "shifted_support_size": report["shifted_support_size"],
        "double_sumset_size": report["double_sumset_size"],
        "base_support_size": report["base_support_size"],
        "dimension": report["dimension"],
        "shift_count": report["shift_count"],
        "density": report["density"],
        "capped": report.get("capped", False),
        "metrics_source": report.get("metrics_source", report.get("note", "proxy")),
        "reported_G_terms": report.get("reported_G_terms"),
        "reported_G_degree": report.get("reported_G_degree"),
        "reported_G_weighted_bits": report.get("reported_G_weighted_bits"),
        "rank": report.get("rank"),
        "x6_top_bits": report.get("x6_top_bits"),
        "x6_top_value": report.get("x6_top_value"),
    }
    return row


def parse_metric_row(row: str, source: str) -> list[actual.BranchMetrics]:
    stripped = row.strip()
    if not stripped:
        return []
    if stripped.startswith("{"):
        return actual.parse_metrics_text(stripped, source)

    normalized: dict[str, Any] = {}
    for raw_part in stripped.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(f"--metric-row entries must be JSON or comma key=value pairs: {row}")
        key, value = [piece.strip() for piece in part.split("=", 1)]
        normalized[key] = value
    return actual.parse_json_metrics(normalized, source)


def load_metrics(sweep_output: str | None, metric_rows: list[str]) -> list[actual.BranchMetrics]:
    metrics: list[actual.BranchMetrics] = []
    text, source = actual.read_sweep_text(sweep_output)
    if text:
        metrics.extend(actual.parse_metrics_text(text, source))
    for index, row in enumerate(metric_rows, start=1):
        metrics.extend(parse_metric_row(row, f"metric-row:{index}"))
    return metrics


def fallback_for_t(t_bits: int, args: argparse.Namespace) -> actual.BranchMetrics:
    values = argparse.Namespace(
        T=t_bits,
        zbits=args.zbits,
        ybits=args.ybits,
        G_terms=args.G_terms,
        G_deg=args.G_deg,
        G_W=args.G_W,
        boundary=args.boundary,
        qpref=args.qpref,
        qstart=args.qstart,
    )
    return actual.fallback_metrics(values)


def build_proxy_report(family: str, t_bits: int, shift_degree: int, cap: int) -> dict[str, Any]:
    names, bounds, support, note = proxy.support_for_family(family, t_bits)
    shifts = actual.shift_support(len(names), shift_degree)

    shifted_supports: set[tuple[int, ...]] = set()
    shifted_capped = False
    for shift in shifts:
        for monomial in support:
            shifted_supports.add(proxy.add_exp(shift, monomial))
            if len(shifted_supports) >= cap:
                shifted_capped = True
                break
        if shifted_capped:
            break

    double_sumset, double_capped = actual.sumset(shifted_supports, set(support), cap)
    density = len(shifts) / max(1, len(shifted_supports))
    growth_ratio = len(double_sumset) / max(1, len(shifted_supports))
    max_weighted_bits = max(proxy.weighted_bits(exponent, bounds) for exponent in shifted_supports)

    if shifted_capped or double_capped:
        verdict = "FAIL_CAP"
    elif len(shifted_supports) > 900:
        verdict = "FAIL_DIM"
    elif growth_ratio > 2.25:
        verdict = "FAIL_EXPANDING"
    elif density < 0.75 and len(shifted_supports) > 2 * len(shifts):
        verdict = "FAIL_SPARSE"
    elif family == "cuso8" and max_weighted_bits >= 1024:
        verdict = "FAIL_DET_CUSO_PROXY"
    else:
        verdict = "PASS_COMPACT"

    return {
        "family": family,
        "T": t_bits,
        "variables": names,
        "bound_bits": bounds,
        "dimension": len(names),
        "base_support_size": len(set(support)),
        "shift_degree": shift_degree,
        "shift_count": len(shifts),
        "shifted_support_size": len(shifted_supports),
        "double_sumset_size": len(double_sumset),
        "density": density,
        "growth_ratio": growth_ratio,
        "max_weighted_bits": max_weighted_bits,
        "capped": shifted_capped or double_capped,
        "cap": cap,
        "preflight_signal": verdict,
        "note": note,
    }


def ranked_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows.sort(
        key=lambda row: (
            SIGNAL_ORDER.get(row["signal_class"], 99),
            row["growth_ratio"],
            row["shifted_support_size"],
            row["double_sumset_size"],
            row["family"],
            row["T"],
            row["shift_degree"],
            row["cap"] if row["cap"] is not None else -1,
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["sweep_rank"] = rank
    return rows


def print_table(rows: list[dict[str, Any]]) -> None:
    columns = [
        "sweep_rank",
        "signal_class",
        "preflight_signal",
        "family",
        "T",
        "shift_degree",
        "cap",
        "growth_ratio",
        "shifted_support_size",
        "double_sumset_size",
        "reported_G_terms",
        "reported_G_weighted_bits",
        "metrics_source",
    ]
    print(" ".join(columns))
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if isinstance(value, float):
                values.append(f"{value:.6g}")
            else:
                values.append("-" if value is None else str(value))
        print(" ".join(values))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--T-values", default="600,784", help="comma list and/or inclusive start:end[:step] ranges")
    parser.add_argument("--shift-degrees", default="1,2", help="comma list and/or inclusive start:end[:step] ranges")
    parser.add_argument("--caps", default="5000", help="comma list and/or inclusive start:end[:step] ranges")
    parser.add_argument("--families", default=ACTUAL_FAMILY, help="comma list: liftT_actual,bilinear,linear8,cuso8,liftT_proxy")
    parser.add_argument("--sweep-output", help="file containing liftT branch sweep text, JSON, or JSONL output")
    parser.add_argument("--metric-row", action="append", default=[], help="JSON row or comma key=value row for concrete liftT metrics")
    parser.add_argument("--zbits", type=int)
    parser.add_argument("--ybits", type=int)
    parser.add_argument("--G-terms", type=int)
    parser.add_argument("--G-deg", type=int)
    parser.add_argument("--G-W", type=int)
    parser.add_argument("--boundary", type=int, default=actual.HIGH_BOUNDARY)
    parser.add_argument("--qpref", type=int)
    parser.add_argument("--qstart", type=int)
    parser.add_argument("--limit", type=int, default=0, help="print only the top N rows; 0 prints all")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    t_values = parse_int_list(args.T_values, "T-values")
    shift_degrees = parse_int_list(args.shift_degrees, "shift-degrees")
    caps = parse_int_list(args.caps, "caps")
    families = parse_families(args.families)
    if any(t_bits < 211 or t_bits > actual.HIGH_BOUNDARY for t_bits in t_values if ACTUAL_FAMILY in families):
        raise SystemExit(f"liftT_actual T values must be in 211..{actual.HIGH_BOUNDARY}")
    if any(shift_degree < 0 for shift_degree in shift_degrees):
        raise SystemExit("--shift-degrees must be non-negative")
    if any(cap < 100 for cap in caps):
        raise SystemExit("--caps values must be at least 100")

    metrics_rows = load_metrics(args.sweep_output, args.metric_row)
    rows: list[dict[str, Any]] = []
    for family, t_bits, shift_degree, cap in itertools.product(families, t_values, shift_degrees, caps):
        if family == ACTUAL_FAMILY:
            metrics = actual.choose_metrics(metrics_rows, t_bits) if metrics_rows else None
            if metrics is None:
                metrics = fallback_for_t(t_bits, args)
            report = actual.build_report(metrics, shift_degree, cap)
        else:
            report = build_proxy_report(family, t_bits, shift_degree, cap)
        rows.append(row_from_report(family, report))

    ranked = ranked_rows(rows)
    limited = ranked[: args.limit] if args.limit else ranked
    if args.jsonl:
        for row in limited:
            print(json.dumps(row, sort_keys=True))
    elif args.json:
        print(json.dumps({"rows": limited}, sort_keys=True))
    else:
        print_table(limited)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
