#!/usr/bin/env python3
"""Evaluate one small LZ relation against bounded low-prefix candidates.

This is a diagnostic companion to small_lz_lattice_probe.py and
lz_relation_audit.py.  It reconstructs a small active-variable relation from
the bounded total-degree lattice, checks whether the relation is only a
projection consequence, then evaluates it on zero and sampled assignments.

It is not a solver and does not search the full candidate space.
"""

from __future__ import annotations

import argparse
import json
import random
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


def bit_length_abs(value: Any) -> int:
    return int(abs(value).nbits()) if value else 0


def exponent_degree(exponent: tuple[int, ...]) -> int:
    return sum(exponent)


def centered_residue(value: int, modulus: int) -> int:
    residue = value % modulus
    if residue > modulus // 2:
        residue -= modulus
    return residue


def eval_coeffs(coeffs: dict[tuple[int, ...], Any], values: list[int]) -> int:
    total = 0
    for exponent, coeff in coeffs.items():
        term = int(coeff)
        for value, power in zip(values, exponent):
            if power:
                term *= value**power
        total += term
    return total


def relation_terms(
    coeffs: dict[tuple[int, ...], Any], active: list[str], limit: int
) -> list[dict[str, Any]]:
    terms = []
    for exponent, coeff in sorted(
        coeffs.items(), key=lambda item: (exponent_degree(item[0]), item[0])
    ):
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


def relation_class(
    coeffs: dict[tuple[int, ...], Any],
    f_coeffs: dict[tuple[int, ...], Any],
    modulus: Any,
) -> str:
    nonzero = [(exponent, coeff) for exponent, coeff in coeffs.items() if coeff]
    if not nonzero:
        return "zero"
    if all(coeff % modulus == 0 for _exponent, coeff in nonzero):
        return "n_multiple"
    max_degree = max(exponent_degree(exponent) for exponent, _coeff in nonzero)
    if max_degree == 1:
        scalar = None
        for exponent, base_coeff in f_coeffs.items():
            coeff = coeffs.get(exponent, 0)
            if base_coeff and coeff % base_coeff == 0:
                scalar = coeff // base_coeff
                break
        if scalar is not None and all(
            coeffs.get(exponent, 0) == f_coeffs.get(exponent, 0) * scalar
            for exponent in set(coeffs) | set(f_coeffs)
        ):
            return "linear_projection_multiple"
        return "linear_other"
    return "higher_degree"


def reduce_mod_projection(poly: Any, projection: Any, anchor_index: int) -> Any:
    ring = poly.parent()
    gens = ring.gens()
    anchor = gens[anchor_index]
    replacement = -(projection - anchor)
    reduced = ring(0)
    for exponent, coeff in poly.dict().items():
        exponent_tuple = tuple(int(value) for value in exponent)
        anchor_power = exponent_tuple[anchor_index]
        term = ring(coeff)
        for index, power in enumerate(exponent_tuple):
            if index != anchor_index and power:
                term *= gens[index] ** power
        if anchor_power:
            term *= replacement**anchor_power
        reduced += term
    return reduced


def coeff_dict_from_poly(poly: Any) -> dict[tuple[int, ...], Any]:
    return {
        tuple(int(value) for value in exponent): coeff
        for exponent, coeff in poly.dict().items()
        if coeff
    }


def sample_assignments(
    bounds: list[int], sample_count: int, seed: int
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    samples: list[dict[str, Any]] = [{"kind": "zero", "values": [0] * len(bounds)}]
    if sample_count <= 1:
        return samples[:sample_count]

    samples.append({"kind": "edge_max_minus_1", "values": [bound - 1 for bound in bounds]})
    while len(samples) < sample_count:
        samples.append(
            {
                "kind": "random",
                "values": [rng.randrange(bound) for bound in bounds],
            }
        )
    return samples


def choose_relation(
    reduced: Any,
    columns: list[tuple[int, ...]],
    column_scales: list[Any],
    threshold_bits: int,
    relation_index: int | None,
    zz: Any,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], Counter[str]]:
    candidates = []
    class_counts: Counter[str] = Counter()
    for row_index in range(reduced.nrows()):
        weighted = [zz(value) for value in reduced[row_index]]
        weighted_max_bits = max(bit_length_abs(value) for value in weighted)
        if weighted_max_bits > threshold_bits:
            continue

        unscaled = []
        for value, scale in zip(weighted, column_scales):
            if value % scale != 0:
                class_counts["non_integral_unscale"] += 1
                break
            unscaled.append(value // scale)
        else:
            coeffs = {
                exponent: coeff
                for exponent, coeff in zip(columns, unscaled)
                if coeff
            }
            if not coeffs:
                class_counts["zero"] += 1
                continue
            max_degree = max(exponent_degree(exponent) for exponent in coeffs)
            record = {
                "row_index": row_index,
                "weighted_max_bits": weighted_max_bits,
                "coeff_max_bits": max(bit_length_abs(coeff) for coeff in coeffs.values()),
                "max_degree": max_degree,
                "term_count": len(coeffs),
                "coeffs": coeffs,
            }
            candidates.append(record)

    if relation_index is not None:
        for candidate in candidates:
            if candidate["row_index"] == relation_index:
                return candidate, candidates, class_counts
        return None, candidates, class_counts

    if not candidates:
        return None, candidates, class_counts

    candidates.sort(
        key=lambda item: (
            0 if item["max_degree"] >= 2 else 1,
            item["weighted_max_bits"],
            item["term_count"],
            item["row_index"],
        )
    )
    return candidates[0], candidates, class_counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active", default="x0,x1,x2,x3")
    parser.add_argument("--anchor", default="x0")
    parser.add_argument("--m", type=int, default=2, choices=(2, 3, 4))
    parser.add_argument("--t", type=int, default=1)
    parser.add_argument("--relation-threshold-bits", type=int, default=1024)
    parser.add_argument("--relation-index", type=int)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--small-residue-bits", type=int, default=64)
    parser.add_argument("--term-limit", type=int, default=16)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.t < 0:
        raise SystemExit("--t must be nonnegative")
    if args.relation_threshold_bits <= 0:
        raise SystemExit("--relation-threshold-bits must be positive")
    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.small_residue_bits < 0:
        raise SystemExit("--small-residue-bits must be nonnegative")
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
    projection = ring(ZZ(instance.known) * inv_anchor)
    for name in active:
        offset, _width = RUNS[name]
        coeff = (ZZ(1) << offset) * inv_anchor
        if name == args.anchor:
            projection += gen_by_name[name]
        else:
            projection += coeff * gen_by_name[name]

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
    for k_value in range(args.m + 1):
        for other_exp in compositions_leq(args.m - k_value, len(other_names)):
            monomial = ring(1)
            for name, power in zip(other_names, other_exp):
                monomial *= gen_by_name[name] ** power
            poly = (ZZ(instance.n) ** max(args.t - k_value, 0)) * monomial
            poly *= projection**k_value
            row = [ZZ(0)] * len(columns)
            for exponent, coeff in poly.dict().items():
                exponent_tuple = tuple(int(value) for value in exponent)
                if exponent_tuple in column_index:
                    index = column_index[exponent_tuple]
                    row[index] = ZZ(coeff) * column_scales[index]
            rows.append(row)

    mat = matrix(ZZ, rows)
    reduced = mat.LLL()
    selected, candidates, non_integral_counts = choose_relation(
        reduced,
        columns,
        column_scales,
        args.relation_threshold_bits,
        args.relation_index,
        ZZ,
    )

    report: dict[str, Any] = {
        "active": active,
        "anchor": args.anchor,
        "bound_bits": bound_bits,
        "m": args.m,
        "t": args.t,
        "rows": int(mat.nrows()),
        "cols": int(mat.ncols()),
        "rank": int(mat.rank()),
        "relation_threshold_bits": args.relation_threshold_bits,
        "candidate_relation_rows": len(candidates),
        "non_integral_counts": dict(sorted(non_integral_counts.items())),
    }
    if selected is None:
        report["status"] = "no_relation_under_threshold"
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            for key, value in report.items():
                print(f"{key}: {value}")
        return 0

    relation = ring(0)
    for exponent, coeff in selected["coeffs"].items():
        monomial = ring(1)
        for gen, power in zip(gens, exponent):
            if power:
                monomial *= gen**power
        relation += coeff * monomial

    f_coeffs = coeff_dict_from_poly(projection)
    relation_coeffs = coeff_dict_from_poly(relation)
    relation_kind = relation_class(relation_coeffs, f_coeffs, ZZ(instance.n))
    anchor_index = active.index(args.anchor)
    projection_remainder = reduce_mod_projection(relation, projection, anchor_index)
    remainder_coeffs = coeff_dict_from_poly(projection_remainder)
    derived_mod_projection = all(
        coeff % ZZ(instance.n) == 0 for coeff in remainder_coeffs.values()
    )
    integer_projection_multiple = bool(relation.quo_rem(projection)[1] == 0)

    samples = sample_assignments([int(bound) for bound in bounds], args.samples, args.seed)
    sample_counts: Counter[str] = Counter()
    previews = []
    small_limit = 1 << args.small_residue_bits if args.small_residue_bits else 0
    for sample in samples:
        values = sample["values"]
        projection_value = eval_coeffs(f_coeffs, values)
        relation_value = eval_coeffs(relation_coeffs, values)
        projection_mod_zero = projection_value % instance.n == 0
        relation_mod_zero = relation_value % instance.n == 0
        projection_center = centered_residue(projection_value, instance.n)
        relation_center = centered_residue(relation_value, instance.n)

        sample_counts["total"] += 1
        if projection_mod_zero:
            sample_counts["projection_mod_zero"] += 1
        if relation_mod_zero:
            sample_counts["relation_mod_zero"] += 1
        if projection_mod_zero and not relation_mod_zero:
            sample_counts["relation_prunes_projection_pass"] += 1
        if relation_mod_zero and not projection_mod_zero:
            sample_counts["relation_accepts_projection_fail"] += 1
        if relation_value == 0:
            sample_counts["relation_integer_zero"] += 1
        if small_limit and abs(relation_center) < small_limit:
            sample_counts["relation_small_centered_residue"] += 1

        if len(previews) < 6:
            previews.append(
                {
                    "kind": sample["kind"],
                    "values": {
                        name: value for name, value in zip(active, values)
                    },
                    "projection_mod_zero": projection_mod_zero,
                    "relation_mod_zero": relation_mod_zero,
                    "projection_center_bits": bit_length_abs(ZZ(projection_center)),
                    "relation_center_bits": bit_length_abs(ZZ(relation_center)),
                    "relation_integer_bits": bit_length_abs(ZZ(relation_value)),
                }
            )

    conclusion = {
        "identically_derived_mod_projection": derived_mod_projection,
        "integer_multiple_of_projection": integer_projection_multiple,
        "extra_modular_prune_seen": sample_counts["relation_prunes_projection_pass"] > 0,
        "relation_zero_without_projection_seen": (
            sample_counts["relation_accepts_projection_fail"] > 0
        ),
        "integer_zero_seen": sample_counts["relation_integer_zero"] > 0,
    }
    report.update(
        {
            "status": "ok",
            "selected_relation": {
                "row_index": selected["row_index"],
                "category": relation_kind,
                "weighted_max_bits": selected["weighted_max_bits"],
                "coeff_max_bits": selected["coeff_max_bits"],
                "max_degree": selected["max_degree"],
                "term_count": selected["term_count"],
                "terms": relation_terms(relation_coeffs, active, args.term_limit),
            },
            "projection_remainder": {
                "coeff_count": len(remainder_coeffs),
                "coeff_max_bits": max(
                    [bit_length_abs(coeff) for coeff in remainder_coeffs.values()],
                    default=0,
                ),
                "all_coefficients_0_mod_n": derived_mod_projection,
            },
            "sample_counts": dict(sorted(sample_counts.items())),
            "sample_previews": previews,
            "conclusion": conclusion,
        }
    )

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
