#!/usr/bin/env python3
"""Weighted Lu-Zhang/HM-style unknown-divisor lattice sanity probe.

This is a compact companion to small_lz_lattice_probe.py.  It keeps the same
linear unknown-divisor model, but builds monomial columns from a weighted bit
budget instead of a total-degree budget.
"""

from __future__ import annotations

import argparse
import json

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


def weighted_exponents_leq(weights: list[int], budget: int) -> list[tuple[int, ...]]:
    out: list[tuple[int, ...]] = []
    stack = [(0, budget, [])]
    while stack:
        index, remaining, prefix = stack.pop()
        if index == len(weights):
            out.append(tuple(prefix))
            continue
        weight = weights[index]
        for power in range(remaining // weight + 1):
            stack.append((index + 1, remaining - power * weight, prefix + [power]))
    out.sort(
        key=lambda exponent: (
            sum(power * weight for power, weight in zip(exponent, weights)),
            sum(exponent),
            exponent,
        )
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active", default="x0,x1,x6,x7")
    parser.add_argument("--anchor", default="x0")
    parser.add_argument("--budget", type=int, default=50)
    parser.add_argument("--m", type=int, default=2)
    parser.add_argument("--t", type=int, default=1)
    parser.add_argument("--lll", action="store_true")
    parser.add_argument("--lll-max-dim", type=int, default=80)
    parser.add_argument("--relation-threshold-bits", type=int, default=1024)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.budget < 0:
        raise SystemExit("--budget must be nonnegative")
    if args.m < 0:
        raise SystemExit("--m must be nonnegative")
    if args.t < 0:
        raise SystemExit("--t must be nonnegative")

    try:
        from sage.all import PolynomialRing, ZZ, inverse_mod, matrix
    except Exception as exc:  # pragma: no cover - local Sage packaging dependent
        raise SystemExit(f"Sage import failed: {exc}") from exc

    active = [part.strip() for part in args.active.split(",") if part.strip()]
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

    columns = weighted_exponents_leq(bound_bits, args.budget)
    column_index = {exponent: index for index, exponent in enumerate(columns)}
    column_weights = [
        sum(power * width for power, width in zip(exponent, bound_bits))
        for exponent in columns
    ]
    column_scales = []
    for exponent in columns:
        scale = ZZ(1)
        for bound, power in zip(bounds, exponent):
            scale *= bound**power
        column_scales.append(scale)

    other_names = [name for name in active if name != args.anchor]
    other_weights = [RUNS[name][1] for name in other_names]
    max_active_weight = max(bound_bits)
    rows = []
    row_specs = []
    dropped_terms = 0
    for k_value in range(args.m + 1):
        remaining_budget = args.budget - k_value * max_active_weight
        if remaining_budget < 0:
            continue
        for other_exp in weighted_exponents_leq(other_weights, remaining_budget):
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
                else:
                    dropped_terms += 1
            rows.append(row)
            row_specs.append({"k": k_value, "other_exp": other_exp})

    mat = matrix(ZZ, rows)
    rank = int(mat.rank())
    report: dict[str, object] = {
        "active": active,
        "anchor": args.anchor,
        "bound_bits": bound_bits,
        "budget": args.budget,
        "m": args.m,
        "t": args.t,
        "rows": int(mat.nrows()),
        "cols": int(mat.ncols()),
        "rank": rank,
        "square": mat.nrows() == mat.ncols(),
        "full_rank": rank == min(mat.nrows(), mat.ncols()),
        "column_count_expected": len(columns),
        "row_count_expected": len(row_specs),
        "min_column_weight": min(column_weights) if column_weights else None,
        "max_column_weight": max(column_weights) if column_weights else None,
        "dropped_terms": dropped_terms,
        "complete_row_policy": "shift_weight_plus_k_max_active_weight_le_budget",
    }
    if mat.nrows() == mat.ncols() and mat.nrows() <= args.lll_max_dim:
        det = abs(mat.det())
        report["det_bits"] = int(det.nbits()) if det else 0
    if args.lll and mat.nrows() <= args.lll_max_dim and mat.ncols() <= args.lll_max_dim:
        reduced = mat.LLL()
        first = [ZZ(value) for value in reduced[0]]
        first_norm = sum(value * value for value in first).isqrt()
        report["lll_first_norm_bits"] = int(first_norm.nbits()) if first_norm else 0
        report["lll_first_max_weighted_bits"] = max(
            int(abs(value).nbits()) if value else 0 for value in first
        )
        relation_count = 0
        integral_unscale_count = 0
        first_nontrivial_relation = None
        for row_index in range(reduced.nrows()):
            row = [ZZ(value) for value in reduced[row_index]]
            weighted_max_bits = max(int(abs(value).nbits()) if value else 0 for value in row)
            if weighted_max_bits > args.relation_threshold_bits:
                continue
            unscaled = []
            for value, scale in zip(row, column_scales):
                if value % scale != 0:
                    break
                unscaled.append(value // scale)
            else:
                integral_unscale_count += 1
                coeff_max_bits = max(int(abs(value).nbits()) if value else 0 for value in unscaled)
                if any(value for value in unscaled):
                    relation_count += 1
                    if first_nontrivial_relation is None:
                        terms = []
                        for coeff, exponent in zip(unscaled, columns):
                            if coeff:
                                terms.append(
                                    {
                                        "coeff_bits": int(abs(coeff).nbits()),
                                        "coeff_sign": 1 if coeff > 0 else -1,
                                        "exponents": {
                                            name: power
                                            for name, power in zip(active, exponent)
                                            if power
                                        },
                                    }
                                )
                        first_nontrivial_relation = {
                            "row_index": row_index,
                            "weighted_max_bits": weighted_max_bits,
                            "coeff_max_bits": coeff_max_bits,
                            "term_count": len(terms),
                            "terms": terms[:20],
                        }
        report["lll_integral_unscale_count"] = integral_unscale_count
        report["lll_relation_count_under_threshold"] = relation_count
        report["lll_relation_threshold_bits"] = args.relation_threshold_bits
        report["lll_first_relation_preview"] = first_nontrivial_relation
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
