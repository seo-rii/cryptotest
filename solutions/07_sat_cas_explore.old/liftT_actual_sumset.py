#!/usr/bin/env python3
"""Actual-ish support-growth preflight for challenge 7 liftT branches.

This is a lightweight companion to ``sumset_preflight.py``.  It prefers
concrete branch metrics from ``sweep_07_liftT_branches.py`` output when
available, then falls back to a bounded synthetic support shaped like the
liftT coarse-high polynomial.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HIGH_BOUNDARY = 830
RUNS = [
    ("a", 210, 39),
    ("u2", 265, 84),
    ("u3", 362, 78),
    ("u4", 600, 69),
    ("u5", 682, 87),
    ("b", 784, 46),
]

SWEEP_COLUMNS = [
    "rank",
    "T",
    "x6bits",
    "value",
    "boundary",
    "qpref",
    "qstart",
    "Zbits",
    "Ybits",
    "qlow_terms",
    "qlow_deg",
    "qlow_W",
    "G_terms",
    "G_deg",
    "G_W",
    "score",
]


@dataclass(frozen=True)
class BranchMetrics:
    T: int
    zbits: int
    ybits: int
    g_terms: int
    g_degree: int | None
    g_weighted_bits: int
    boundary: int | None
    q_prefix_bits: int | None
    q_high_start: int | None
    source: str
    rank: int | None = None
    x6_top_bits: int | None = None
    x6_top_value: str | None = None
    score: float | None = None


def add_exp(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(a + b for a, b in zip(left, right))


def sumset(left: set[tuple[int, ...]], right: set[tuple[int, ...]], cap: int) -> tuple[set[tuple[int, ...]], bool]:
    out: set[tuple[int, ...]] = set()
    capped = False
    for a in left:
        for b in right:
            out.add(add_exp(a, b))
            if len(out) >= cap:
                capped = True
                return out, capped
    return out, capped


def weighted_bits(exponent: tuple[int, ...], bounds: list[int]) -> int:
    return sum(power * bound for power, bound in zip(exponent, bounds))


def liftT_variables(t_bits: int, zbits: int, ybits: int) -> tuple[list[str], list[int]]:
    names: list[str] = []
    bounds: list[int] = []
    for name, offset, width in RUNS:
        if offset >= t_bits:
            continue
        low_width = min(width, t_bits - offset)
        names.append(name if low_width == width else f"{name}l")
        bounds.append(low_width)
    names.extend(["Z", "Y"])
    bounds.extend([zbits, ybits])
    return names, bounds


def low_degree_exponents(dim: int, degree: int) -> set[tuple[int, ...]]:
    support: set[tuple[int, ...]] = set()
    for exponents in itertools.product(range(degree + 1), repeat=dim):
        if sum(exponents) <= degree:
            support.add(exponents)
    return support


def synthetic_liftT_support(
    names: list[str],
    bounds: list[int],
    t_bits: int,
    g_terms: int,
    g_degree: int | None,
) -> set[tuple[int, ...]]:
    dim = len(names)
    zero = tuple(0 for _ in names)
    z_index = names.index("Z")
    y_index = names.index("Y")
    low_indices = [index for index, name in enumerate(names) if name not in {"Z", "Y"}]
    max_degree = max(1, min(g_degree or 3, 4))
    inv_degree = max(1, min(max_degree, (t_bits - 1) // 210))

    support = {zero}
    p_terms = {zero}
    for index in low_indices + [z_index]:
        exp = [0] * dim
        exp[index] = 1
        p_terms.add(tuple(exp))
    support |= p_terms

    y_exp = [0] * dim
    y_exp[y_index] = 1
    y_term = tuple(y_exp)
    support.add(y_term)
    for term in p_terms:
        support.add(add_exp(term, y_term))

    low_support: set[tuple[int, ...]] = {zero}
    for exponents in low_degree_exponents(len(low_indices), inv_degree):
        lifted = [0] * dim
        for local_index, power in enumerate(exponents):
            lifted[low_indices[local_index]] = power
        low_support.add(tuple(lifted))
    support |= low_support
    for left in p_terms:
        for right in low_support:
            term = add_exp(left, right)
            if sum(term) <= max_degree:
                support.add(term)

    if len(support) > g_terms:
        ordered = sorted(
            support,
            key=lambda exp: (
                sum(exp),
                weighted_bits(exp, bounds),
                exp[y_index],
                exp[z_index],
                exp,
            ),
        )
        support = set(ordered[:g_terms])
    elif len(support) < g_terms:
        candidates = sorted(
            low_degree_exponents(dim, max_degree),
            key=lambda exp: (sum(exp), weighted_bits(exp, bounds), exp),
        )
        for candidate in candidates:
            support.add(candidate)
            if len(support) >= g_terms:
                break
    return support


def shift_support(dim: int, shift_degree: int) -> set[tuple[int, ...]]:
    shifts: set[tuple[int, ...]] = set()
    for degree in range(shift_degree + 1):
        for exponents in itertools.product(range(degree + 1), repeat=dim):
            if sum(exponents) <= degree:
                shifts.add(exponents)
    return shifts


def parse_json_metrics(payload: Any, source: str) -> list[BranchMetrics]:
    if isinstance(payload, dict):
        rows = payload.get("scores") or payload.get("branches") or payload.get("results") or [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        return []

    metrics: list[BranchMetrics] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        t_bits = row.get("T", row.get("t_bits"))
        zbits = row.get("Zbits", row.get("z_bits"))
        ybits = row.get("Ybits", row.get("y_bits"))
        g_terms = row.get("G_terms", row.get("g_terms"))
        g_w = row.get("G_W", row.get("g_weighted_bits", row.get("g_W")))
        if None in {t_bits, zbits, ybits, g_terms, g_w}:
            continue
        metrics.append(
            BranchMetrics(
                T=int(t_bits),
                zbits=int(zbits),
                ybits=int(ybits),
                g_terms=int(g_terms),
                g_degree=int(row["G_deg"]) if "G_deg" in row else int(row["g_degree"]) if "g_degree" in row else None,
                g_weighted_bits=int(g_w),
                boundary=int(row["boundary"]) if "boundary" in row else None,
                q_prefix_bits=int(row["qpref"]) if "qpref" in row else int(row["q_prefix_bits"]) if "q_prefix_bits" in row else None,
                q_high_start=int(row["qstart"]) if "qstart" in row else int(row["q_high_start"]) if "q_high_start" in row else None,
                source=source,
                rank=int(row["rank"]) if "rank" in row else None,
                x6_top_bits=int(row["x6bits"]) if "x6bits" in row else int(row["x6_top_bits"]) if "x6_top_bits" in row else None,
                x6_top_value=str(row["value"]) if "value" in row else str(row["x6_top_value"]) if "x6_top_value" in row else None,
                score=float(row["score"]) if "score" in row else None,
            )
        )
    return metrics


def parse_text_metrics(text: str, source: str) -> list[BranchMetrics]:
    metrics: list[BranchMetrics] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != len(SWEEP_COLUMNS):
            continue
        if not re.fullmatch(r"\d+", parts[0]) or not re.fullmatch(r"\d+", parts[1]):
            continue
        row = dict(zip(SWEEP_COLUMNS, parts))
        metrics.append(
            BranchMetrics(
                T=int(row["T"]),
                zbits=int(row["Zbits"]),
                ybits=int(row["Ybits"]),
                g_terms=int(row["G_terms"]),
                g_degree=int(row["G_deg"]),
                g_weighted_bits=int(row["G_W"]),
                boundary=int(row["boundary"]),
                q_prefix_bits=int(row["qpref"]),
                q_high_start=int(row["qstart"]),
                source=source,
                rank=int(row["rank"]),
                x6_top_bits=int(row["x6bits"]),
                x6_top_value=row["value"],
                score=float(row["score"]),
            )
        )
    return metrics


def parse_metrics_text(text: str, source: str) -> list[BranchMetrics]:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return parse_json_metrics(json.loads(stripped), source)
    except json.JSONDecodeError:
        pass

    metrics: list[BranchMetrics] = []
    for line in stripped.splitlines():
        try:
            metrics.extend(parse_json_metrics(json.loads(line), source))
        except json.JSONDecodeError:
            continue
    if metrics:
        return metrics
    return parse_text_metrics(text, source)


def fallback_metrics(args: argparse.Namespace) -> BranchMetrics:
    zbits = args.zbits if args.zbits is not None else max(1, args.boundary - args.T)
    ybits = args.ybits if args.ybits is not None else zbits
    g_terms = args.G_terms if args.G_terms is not None else 31
    g_weighted_bits = args.G_W if args.G_W is not None else max(1, 1024 + max(zbits, ybits))
    return BranchMetrics(
        T=args.T,
        zbits=zbits,
        ybits=ybits,
        g_terms=g_terms,
        g_degree=args.G_deg,
        g_weighted_bits=g_weighted_bits,
        boundary=args.boundary,
        q_prefix_bits=args.qpref,
        q_high_start=args.qstart,
        source="parameters",
    )


def choose_metrics(metrics: list[BranchMetrics], t_bits: int) -> BranchMetrics | None:
    candidates = [item for item in metrics if item.T == t_bits]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            item.rank if item.rank is not None else 10**9,
            item.score if item.score is not None else float("inf"),
            item.g_weighted_bits,
        ),
    )[0]


def build_report(metrics: BranchMetrics, shift_degree: int, cap: int) -> dict[str, Any]:
    names, bounds = liftT_variables(metrics.T, metrics.zbits, metrics.ybits)
    support = synthetic_liftT_support(names, bounds, metrics.T, metrics.g_terms, metrics.g_degree)
    shifts = shift_support(len(names), shift_degree)

    shifted_supports: set[tuple[int, ...]] = set()
    shifted_capped = False
    for shift in shifts:
        for monomial in support:
            shifted_supports.add(add_exp(shift, monomial))
            if len(shifted_supports) >= cap:
                shifted_capped = True
                break
        if shifted_capped:
            break

    double_sumset, double_capped = sumset(shifted_supports, support, cap)
    density = len(shifts) / max(1, len(shifted_supports))
    growth_ratio = len(double_sumset) / max(1, len(shifted_supports))
    max_weighted_bits = max(weighted_bits(exponent, bounds) for exponent in shifted_supports)

    if len(shifted_supports) >= cap or len(double_sumset) >= cap:
        verdict = "FAIL_CAP"
    elif len(shifted_supports) > 900:
        verdict = "FAIL_DIM"
    elif growth_ratio > 2.25:
        verdict = "FAIL_EXPANDING"
    elif density < 0.75 and len(shifted_supports) > 2 * len(shifts):
        verdict = "FAIL_SPARSE"
    elif metrics.g_weighted_bits >= 1280:
        verdict = "WARN_TALL_G"
    else:
        verdict = "PASS_COMPACT_ACTUALISH"

    return {
        "T": metrics.T,
        "metrics_source": metrics.source,
        "rank": metrics.rank,
        "x6_top_bits": metrics.x6_top_bits,
        "x6_top_value": metrics.x6_top_value,
        "boundary": metrics.boundary,
        "q_prefix_bits": metrics.q_prefix_bits,
        "q_high_start": metrics.q_high_start,
        "variables": names,
        "bound_bits": bounds,
        "dimension": len(names),
        "base_support_size": len(support),
        "reported_G_terms": metrics.g_terms,
        "reported_G_degree": metrics.g_degree,
        "reported_G_weighted_bits": metrics.g_weighted_bits,
        "shift_degree": shift_degree,
        "shift_count": len(shifts),
        "shifted_support_size": len(shifted_supports),
        "double_sumset_size": len(double_sumset),
        "density": density,
        "growth_ratio": growth_ratio,
        "max_support_weighted_bits": max_weighted_bits,
        "capped": shifted_capped or double_capped,
        "cap": cap,
        "preflight_signal": verdict,
        "note": "uses concrete liftT branch metrics when supplied; support is bounded synthetic monomial shape",
    }


def read_sweep_text(path: str | None) -> tuple[str, str]:
    if path is None:
        return "", ""
    if path == "-":
        return sys.stdin.read(), "stdin"
    return Path(path).read_text(), path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--T", type=int, default=600)
    parser.add_argument("--sweep-output", help="file containing sweep_07_liftT_branches.py text, JSON, or JSONL output")
    parser.add_argument("--shift-degree", type=int, default=2)
    parser.add_argument("--cap", type=int, default=5000)
    parser.add_argument("--zbits", type=int)
    parser.add_argument("--ybits", type=int)
    parser.add_argument("--G-terms", type=int)
    parser.add_argument("--G-deg", type=int)
    parser.add_argument("--G-W", type=int)
    parser.add_argument("--boundary", type=int, default=HIGH_BOUNDARY)
    parser.add_argument("--qpref", type=int)
    parser.add_argument("--qstart", type=int)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.T < 211 or args.T > HIGH_BOUNDARY:
        raise SystemExit("--T must be in 211..830 for this model")
    if args.shift_degree < 0:
        raise SystemExit("--shift-degree must be non-negative")
    if args.cap < 100:
        raise SystemExit("--cap must be at least 100")

    text, source = read_sweep_text(args.sweep_output)
    parsed = parse_metrics_text(text, source) if text else []
    metrics = choose_metrics(parsed, args.T) if parsed else None
    if metrics is None:
        metrics = fallback_metrics(args)

    report = build_report(metrics, args.shift_degree, args.cap)
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
