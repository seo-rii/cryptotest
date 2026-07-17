#!/usr/bin/env python3
"""Bounded audit for relation-like rows in the small LZ lattice.

This deliberately mirrors small_lz_lattice_probe.py's total-degree lattice.
It is not a solver.  It only asks whether short LLL rows under a coefficient
threshold look like the original linear equation or N-multiples, versus rows
with genuinely higher-degree support.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from sat_cas_core import load_instance


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


def compositions_leq(total: int, parts: int) -> list[tuple[int, ...]]:
    out: list[tuple[int, ...]] = []
    stack = [(0, total, [])]
    while stack:
        index, remaining, prefix = stack.pop()
        if index == parts - 1:
            for value in range(remaining + 1):
                out.append(tuple(prefix + [value]))
            continue
        for value in range(remaining + 1):
            stack.append((index + 1, remaining - value, prefix + [value]))
    return out


def exponent_degree(exponent: tuple[int, ...]) -> int:
    return sum(exponent)


def bit_length_abs(value: Any) -> int:
    return int(abs(value).nbits()) if value else 0


def relation_terms(
    coeffs: list[Any], columns: list[tuple[int, ...]], active: list[str], limit: int
) -> list[dict[str, Any]]:
    terms = []
    for coeff, exponent in zip(coeffs, columns):
        if not coeff:
            continue
        terms.append(
            {
                "coeff_bits": bit_length_abs(coeff),
                "coeff_sign": 1 if coeff > 0 else -1,
                "degree": exponent_degree(exponent),
                "exponents": {
                    name: power for name, power in zip(active, exponent) if power
                },
            }
        )
        if len(terms) == limit:
            break
    return terms


def classify_unscaled(
    coeffs: list[Any],
    columns: list[tuple[int, ...]],
    f_coeffs: dict[tuple[int, ...], Any],
    modulus: Any,
) -> str:
    nonzero = [(exponent, coeff) for coeff, exponent in zip(coeffs, columns) if coeff]
    if not nonzero:
        return "zero"
    if all(coeff % modulus == 0 for _exponent, coeff in nonzero):
        return "integral_unscaled_n_multiple"

    max_degree = max(exponent_degree(exponent) for exponent, _coeff in nonzero)
    if max_degree == 1:
        scalar = None
        for exponent, base_coeff in f_coeffs.items():
            coeff = coeffs[columns.index(exponent)]
            if base_coeff and coeff % base_coeff == 0:
                scalar = coeff // base_coeff
                break
        if scalar is not None:
            for exponent, coeff in zip(columns, coeffs):
                expected = f_coeffs.get(exponent, 0) * scalar
                if coeff != expected:
                    break
            else:
                return "linear_baseline_f_multiple"
        return "linear_other"

    return "higher_degree"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active", default="x0,x1,x2,x3")
    parser.add_argument("--anchor", default="x0")
    parser.add_argument("--m", type=int, default=2)
    parser.add_argument("--t", type=int, default=1)
    parser.add_argument("--dim-cap", type=int, default=80)
    parser.add_argument("--relation-threshold-bits", type=int, default=1024)
    parser.add_argument("--max-rows", type=int, default=20)
    parser.add_argument("--term-limit", type=int, default=16)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.m < 0:
        raise SystemExit("--m must be nonnegative")
    if args.t < 0:
        raise SystemExit("--t must be nonnegative")
    if args.dim_cap <= 0:
        raise SystemExit("--dim-cap must be positive")
    if args.max_rows < 0:
        raise SystemExit("--max-rows must be nonnegative")
    if args.term_limit <= 0:
        raise SystemExit("--term-limit must be positive")

    try:
        from sage.all import PolynomialRing, ZZ, inverse_mod, matrix
    except Exception as exc:  # pragma: no cover - local Sage packaging dependent
        raise SystemExit(f"Sage import failed: {exc}") from exc

    active = [part.strip() for part in args.active.split(",") if part.strip()]
    if not active:
        raise SystemExit("--active must name at least one variable")
    if args.anchor not in active:
        raise SystemExit("--anchor must be one of --active")
    for name in active:
        if name not in RUNS:
            raise SystemExit(f"unknown variable: {name}")

    instance = load_instance()
    ring = PolynomialRing(ZZ, names=tuple(active))
    gens = ring.gens()
    gen_by_name = {str(gen): gen for gen in gens}
    bound_bits = [RUNS[name][1] for name in active]
    bounds = [ZZ(1) << width for width in bound_bits]

    anchor_offset, _anchor_width = RUNS[args.anchor]
    anchor_coeff = ZZ(1) << anchor_offset
    inv_anchor = ZZ(inverse_mod(anchor_coeff % instance.n, instance.n))
    f = ring(ZZ(instance.known) * inv_anchor)
    for name in active:
        offset, _width = RUNS[name]
        coeff = (ZZ(1) << offset) * inv_anchor
        if name == args.anchor:
            f += gen_by_name[name]
        else:
            f += coeff * gen_by_name[name]

    columns = compositions_leq(args.m, len(active))
    column_index = {exponent: index for index, exponent in enumerate(columns)}
    column_scales = []
    for exponent in columns:
        scale = ZZ(1)
        for bound, power in zip(bounds, exponent):
            scale *= bound**power
        column_scales.append(scale)

    other_names = [name for name in active if name != args.anchor]
    rows = []
    row_specs = []
    for k_value in range(args.m + 1):
        for other_exp in compositions_leq(args.m - k_value, len(other_names)):
            monomial = ring(1)
            for name, power in zip(other_names, other_exp):
                monomial *= gen_by_name[name] ** power
            poly = (ZZ(instance.n) ** max(args.t - k_value, 0)) * monomial * (f**k_value)
            row = [ZZ(0)] * len(columns)
            for exponent, coeff in poly.dict().items():
                exponent_tuple = tuple(int(value) for value in exponent)
                if exponent_tuple in column_index:
                    index = column_index[exponent_tuple]
                    row[index] = ZZ(coeff) * column_scales[index]
            rows.append(row)
            row_specs.append({"k": k_value, "other_exp": other_exp})

    mat = matrix(ZZ, rows)
    report: dict[str, Any] = {
        "active": active,
        "anchor": args.anchor,
        "bound_bits": bound_bits,
        "m": args.m,
        "t": args.t,
        "rows": int(mat.nrows()),
        "cols": int(mat.ncols()),
        "rank": int(mat.rank()),
        "dim_cap": args.dim_cap,
        "lll_ran": False,
        "relation_threshold_bits": args.relation_threshold_bits,
    }
    if mat.nrows() > args.dim_cap or mat.ncols() > args.dim_cap:
        report["status"] = "skipped_dim_cap"
    else:
        f_coeffs = {
            tuple(int(value) for value in exponent): ZZ(coeff)
            for exponent, coeff in f.dict().items()
        }
        reduced = mat.LLL()
        report["lll_ran"] = True
        class_counts: Counter[str] = Counter()
        inspected = []
        under_threshold_count = 0
        integral_unscale_count = 0
        for row_index in range(reduced.nrows()):
            row = [ZZ(value) for value in reduced[row_index]]
            weighted_max_bits = max(bit_length_abs(value) for value in row)
            if weighted_max_bits > args.relation_threshold_bits:
                continue
            under_threshold_count += 1
            unscaled = []
            for value, scale in zip(row, column_scales):
                if value % scale != 0:
                    category = "non_integral_unscale"
                    class_counts[category] += 1
                    if len(inspected) < args.max_rows:
                        inspected.append(
                            {
                                "row_index": row_index,
                                "category": category,
                                "weighted_max_bits": weighted_max_bits,
                            }
                        )
                    break
                unscaled.append(value // scale)
            else:
                integral_unscale_count += 1
                category = classify_unscaled(unscaled, columns, f_coeffs, ZZ(instance.n))
                class_counts[category] += 1
                if len(inspected) < args.max_rows:
                    nonzero = [
                        (exponent, coeff)
                        for coeff, exponent in zip(unscaled, columns)
                        if coeff
                    ]
                    inspected.append(
                        {
                            "row_index": row_index,
                            "category": category,
                            "weighted_max_bits": weighted_max_bits,
                            "coeff_max_bits": max(
                                [bit_length_abs(coeff) for _exponent, coeff in nonzero],
                                default=0,
                            ),
                            "max_degree": max(
                                [exponent_degree(exponent) for exponent, _coeff in nonzero],
                                default=0,
                            ),
                            "term_count": len(nonzero),
                            "terms": relation_terms(
                                unscaled, columns, active, args.term_limit
                            ),
                        }
                    )
        report["status"] = "ok"
        report["lll_rows_under_threshold"] = under_threshold_count
        report["lll_integral_unscale_count"] = integral_unscale_count
        report["classification_counts"] = dict(sorted(class_counts.items()))
        report["inspected_rows"] = inspected

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
