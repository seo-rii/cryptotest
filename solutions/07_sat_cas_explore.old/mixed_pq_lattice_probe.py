#!/usr/bin/env python3
"""Diagnostic mixed p/q lattice probe for challenge 7.

This is not a sound pruning oracle.  It is a small basis-family smoke test that
adds one explicit q-window variable to the product equation, so the generated
rows are not confined to the older anchored p-projection ideal.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from typing import Any

from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


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
Q_NAME = "yq"


def parse_q_window(text: str) -> tuple[int, int]:
    if text == "auto":
        return (-1, -1)
    try:
        start_text, width_text = text.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH or auto") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    if start < 0 or width <= 0 or start + width > 1024:
        raise argparse.ArgumentTypeError("q window must be within 0..1024")
    return (start, width)


def bit_ranges(mask: int, bits: int = 1024) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for bit in range(bits):
        if (mask >> bit) & 1:
            if start is None:
                start = bit
        elif start is not None:
            ranges.append((start, bit - start))
            start = None
    if start is not None:
        ranges.append((start, bits - start))
    return ranges


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
    out.sort(key=lambda item: (sum(item), item))
    return out


def degree(exponent: tuple[int, ...]) -> int:
    return sum(exponent)


def bit_length_abs(value: Any) -> int:
    return int(abs(value).nbits()) if value else 0


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


def relation_terms(
    coeffs: dict[tuple[int, ...], Any], variables: list[str], limit: int
) -> list[dict[str, Any]]:
    terms = []
    for exponent, coeff in sorted(coeffs.items(), key=lambda item: (degree(item[0]), item[0])):
        if not coeff:
            continue
        terms.append(
            {
                "coeff_bits": bit_length_abs(coeff),
                "coeff_sign": 1 if coeff > 0 else -1,
                "degree": degree(exponent),
                "exponents": {
                    name: power for name, power in zip(variables, exponent, strict=True) if power
                },
            }
        )
        if len(terms) == limit:
            break
    return terms


def coeff_dict(poly: Any) -> dict[tuple[int, ...], Any]:
    return {
        tuple(int(value) for value in exponent): coeff
        for exponent, coeff in poly.dict().items()
        if coeff
    }


def format_fixed_range(item: FixedRange) -> str:
    return f"{item.start}:{item.width}:{hex(item.value)}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--active-p", default="x0,x7")
    parser.add_argument("--anchor-p", default=None)
    parser.add_argument(
        "--q-window",
        action="append",
        default=None,
        type=parse_q_window,
        help="START:WIDTH q window; may be repeated. Default: auto",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--m", type=int, default=1)
    parser.add_argument("--shift-degree", type=int, default=1)
    parser.add_argument("--lll", action="store_true")
    parser.add_argument("--lll-max-dim", type=int, default=100)
    parser.add_argument("--relation-threshold-bits", type=int, default=4096)
    parser.add_argument("--term-limit", type=int, default=16)
    parser.add_argument("--evaluate-samples", action="store_true")
    parser.add_argument("--samples", type=int, default=16)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--small-residue-bits", type=int, default=64)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.m < 1:
        raise SystemExit("--m must be at least 1")
    if args.shift_degree < 0:
        raise SystemExit("--shift-degree must be nonnegative")
    if args.term_limit <= 0:
        raise SystemExit("--term-limit must be positive")
    if args.samples <= 0:
        raise SystemExit("--samples must be positive")
    if args.small_residue_bits < 0:
        raise SystemExit("--small-residue-bits must be nonnegative")

    active_p = [part.strip() for part in args.active_p.split(",") if part.strip()]
    if not active_p:
        raise SystemExit("--active-p must name at least one p variable")
    for name in active_p:
        if name not in RUNS:
            raise SystemExit(f"unknown p variable: {name}")
    anchor_p = args.anchor_p or active_p[0]
    if anchor_p not in active_p:
        raise SystemExit("--anchor-p must be included in --active-p")

    try:
        from sage.all import PolynomialRing, ZZ, inverse_mod, matrix
    except Exception as exc:  # pragma: no cover - local Sage packaging dependent
        raise SystemExit(f"Sage import failed: {exc}") from exc

    instance = load_instance()
    fixed_ranges: list[FixedRange] = list(args.fix_p_range)
    p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)

    active_mask = 0
    for name in active_p:
        start, width = RUNS[name]
        item_mask = ((1 << width) - 1) << start
        if p_mask & item_mask:
            raise SystemExit(f"active variable {name} overlaps known/fixed p bits")
        active_mask |= item_mask

    q_known = derive_q_known_bits(instance, p_known, p_mask)
    q_unknown_mask = instance.full_mask ^ q_known.mask
    requested_q_windows = args.q_window or [(-1, -1)]
    q_windows: list[dict[str, int | str]] = []
    selected_q_mask = 0
    available_q_mask = q_unknown_mask
    for requested_start, requested_width in requested_q_windows:
        q_window_source = "explicit"
        if requested_start < 0:
            ranges = bit_ranges(available_q_mask, instance.p_bits)
            if not ranges:
                raise SystemExit("no q window available: all q bits are known or selected")
            requested_start, requested_width = max(ranges, key=lambda item: (item[1], -item[0]))
            q_window_source = "auto_largest_unknown_q_range"
        q_window_mask = ((1 << requested_width) - 1) << requested_start
        if q_known.mask & q_window_mask:
            raise SystemExit("q window overlaps already-known q bits")
        if selected_q_mask & q_window_mask:
            raise SystemExit("q windows overlap each other")
        selected_q_mask |= q_window_mask
        available_q_mask &= ~q_window_mask
        q_windows.append(
            {
                "start": requested_start,
                "width": requested_width,
                "source": q_window_source,
            }
        )

    p_accounted_mask = p_mask | active_mask
    q_accounted_mask = q_known.mask | selected_q_mask
    omitted_p_bits = (instance.full_mask ^ p_accounted_mask).bit_count()
    omitted_q_bits = (instance.full_mask ^ q_accounted_mask).bit_count()
    q_sample_mod_bits = max(int(item["start"]) + int(item["width"]) for item in q_windows)
    if q_sample_mod_bits > instance.p_bits:
        q_sample_mod_bits = instance.p_bits
    q_sample_mask = (1 << q_sample_mod_bits) - 1
    q_gap_mask_inside_sample_modulus = q_sample_mask & ~q_accounted_mask
    q_gap_ranges_inside_sample_modulus = bit_ranges(
        q_gap_mask_inside_sample_modulus, q_sample_mod_bits
    )
    q_gap_bits_inside_sample_modulus = q_gap_mask_inside_sample_modulus.bit_count()

    q_names = [Q_NAME] if len(q_windows) == 1 else [f"{Q_NAME}{index}" for index in range(len(q_windows))]
    variables = active_p + q_names
    q_indices = list(range(len(active_p), len(variables)))
    bound_bits = [RUNS[name][1] for name in active_p] + [
        int(item["width"]) for item in q_windows
    ]
    bounds = [ZZ(1) << width for width in bound_bits]

    ring = PolynomialRing(ZZ, names=tuple(variables))
    gens = ring.gens()
    gen_by_name = {str(gen): gen for gen in gens}

    p_poly = ring(ZZ(p_known))
    for name in active_p:
        offset, _width = RUNS[name]
        p_poly += (ZZ(1) << offset) * gen_by_name[name]

    q_poly = ring(ZZ(q_known.known))
    for q_name, item in zip(q_names, q_windows, strict=True):
        q_poly += (ZZ(1) << int(item["start"])) * gen_by_name[q_name]
    product_poly = p_poly * q_poly - ZZ(instance.n)

    anchor_offset, _anchor_width = RUNS[anchor_p]
    inv_anchor = ZZ(inverse_mod((ZZ(1) << anchor_offset) % instance.n, instance.n))
    projection = ring(ZZ(instance.known) * inv_anchor)
    for name in active_p:
        offset, _width = RUNS[name]
        coeff = (ZZ(1) << offset) * inv_anchor
        projection += gen_by_name[name] if name == anchor_p else coeff * gen_by_name[name]

    column_degree = args.shift_degree + 2 * args.m
    columns = compositions_leq(column_degree, len(variables))
    column_index = {exponent: index for index, exponent in enumerate(columns)}
    column_scales = []
    for exponent in columns:
        scale = ZZ(1)
        for bound, power in zip(bounds, exponent, strict=True):
            scale *= bound**power
        column_scales.append(scale)

    rows = []
    row_specs = []
    dropped_terms = 0
    shifts = compositions_leq(args.shift_degree, len(variables))
    for k_value in range(1, args.m + 1):
        base = product_poly**k_value
        for shift_exp in shifts:
            shift = ring(1)
            for gen, power in zip(gens, shift_exp, strict=True):
                if power:
                    shift *= gen**power
            poly = shift * base
            row = [ZZ(0)] * len(columns)
            for exponent, coeff in poly.dict().items():
                exponent_tuple = tuple(int(value) for value in exponent)
                index = column_index.get(exponent_tuple)
                if index is None:
                    dropped_terms += 1
                    continue
                row[index] = ZZ(coeff) * column_scales[index]
            if any(row):
                rows.append(row)
                row_specs.append({"k": k_value, "shift_exp": shift_exp})

    mat = matrix(ZZ, rows)
    report: dict[str, Any] = {
        "event": "mixed_pq_lattice_probe",
        "active_p": active_p,
        "anchor_p": anchor_p,
        "fixed_p_ranges": [format_fixed_range(item) for item in fixed_ranges],
        "q_window": q_windows[0],
        "q_windows": q_windows,
        "q_window_count": len(q_windows),
        "q_sample_mod_bits": q_sample_mod_bits,
        "q_gap_bits_inside_sample_modulus": q_gap_bits_inside_sample_modulus,
        "q_gap_ranges_inside_sample_modulus": [
            {"start": start, "width": width}
            for start, width in q_gap_ranges_inside_sample_modulus
        ],
        "q_known": {
            "low_bits": q_known.low_bits,
            "prefix_bits": q_known.prefix_bits,
            "prefix_start": q_known.prefix_start,
            "known_bit_count": q_known.mask.bit_count(),
        },
        "omitted_p_bits": omitted_p_bits,
        "omitted_q_bits": omitted_q_bits,
        "sound_pruning_oracle": False,
        "sampled_pruning_oracle": False,
        "basis_family": "mixed_product_shifts_G_equals_PQ_minus_N",
        "projection_audit_note": (
            "Rows built from P*Q-N are expected to reduce to 0 modulo N after "
            "the anchored p-projection.  A useful smoke signal is q-term "
            "presence plus not being an integer multiple of the p-projection; "
            "sampled pruning needs a separate exact-product evaluator."
        ),
        "m": args.m,
        "shift_degree": args.shift_degree,
        "column_degree": column_degree,
        "variables": variables,
        "bound_bits": bound_bits,
        "rows": int(mat.nrows()),
        "cols": int(mat.ncols()),
        "rank": int(mat.rank()) if mat.nrows() and mat.ncols() else 0,
        "dropped_terms": dropped_terms,
        "lll_requested": bool(args.lll),
        "sample_evaluation_requested": bool(args.evaluate_samples),
    }

    if args.lll:
        if mat.nrows() > args.lll_max_dim or mat.ncols() > args.lll_max_dim:
            report["lll_status"] = "skipped_dimension_limit"
        else:
            try:
                reduced = mat.LLL()
            except Exception as exc:  # pragma: no cover - Sage/backend dependent
                report["lll_status"] = "error"
                report["lll_error"] = str(exc)
            else:
                class_counts: Counter[str] = Counter()
                first_candidate: dict[str, Any] | None = None
                first_nonderived: dict[str, Any] | None = None
                first_sample_pruning_candidate: dict[str, Any] | None = None
                anchor_index = variables.index(anchor_p)
                for row_index in range(reduced.nrows()):
                    weighted = [ZZ(value) for value in reduced[row_index]]
                    weighted_max_bits = max(bit_length_abs(value) for value in weighted)
                    if weighted_max_bits > args.relation_threshold_bits:
                        class_counts["over_threshold"] += 1
                        continue
                    unscaled = []
                    for value, scale in zip(weighted, column_scales, strict=True):
                        if value % scale != 0:
                            class_counts["non_integral_unscale"] += 1
                            break
                        unscaled.append(value // scale)
                    else:
                        coeffs = {
                            exponent: coeff
                            for exponent, coeff in zip(columns, unscaled, strict=True)
                            if coeff
                        }
                        if not coeffs:
                            class_counts["zero"] += 1
                            continue
                        relation = ring(0)
                        for exponent, coeff in coeffs.items():
                            monomial = ring(1)
                            for gen, power in zip(gens, exponent, strict=True):
                                if power:
                                    monomial *= gen**power
                            relation += coeff * monomial
                        remainder = reduce_mod_projection(relation, projection, anchor_index)
                        remainder_coeffs = coeff_dict(remainder)
                        derived = all(
                            coeff % ZZ(instance.n) == 0 for coeff in remainder_coeffs.values()
                        )
                        integer_projection_multiple = bool(relation.quo_rem(projection)[1] == 0)
                        contains_q = any(
                            any(exponent[index] for index in q_indices)
                            for exponent in coeffs
                        )
                        class_counts["candidate"] += 1
                        class_counts[
                            "projection_derived" if derived else "not_projection_derived"
                        ] += 1
                        class_counts[
                            "integer_projection_multiple"
                            if integer_projection_multiple
                            else "not_integer_projection_multiple"
                        ] += 1
                        if contains_q:
                            class_counts["contains_q_terms"] += 1
                        preview = {
                            "row_index": row_index,
                            "weighted_max_bits": weighted_max_bits,
                            "coeff_max_bits": max(bit_length_abs(value) for value in coeffs.values()),
                            "max_degree": max(degree(exponent) for exponent in coeffs),
                            "term_count": len(coeffs),
                            "contains_q_terms": contains_q,
                            "projection_derived_mod_n": derived,
                            "integer_multiple_of_projection": integer_projection_multiple,
                            "projection_remainder_coeff_count": len(remainder_coeffs),
                            "projection_remainder_coeff_max_bits": max(
                                [bit_length_abs(coeff) for coeff in remainder_coeffs.values()],
                                default=0,
                            ),
                            "terms": relation_terms(coeffs, variables, args.term_limit),
                        }
                        if args.evaluate_samples:
                            rng = random.Random(args.seed)
                            sample_rows: list[dict[str, Any]] = []
                            active_bounds = [1 << RUNS[name][1] for name in active_p]
                            raw_samples: list[tuple[str, list[int]]] = [
                                ("zero", [0] * len(active_p)),
                                ("max_minus_1", [bound - 1 for bound in active_bounds]),
                            ]
                            while len(raw_samples) < args.samples:
                                raw_samples.append(
                                    (
                                        "random",
                                        [rng.randrange(bound) for bound in active_bounds],
                                    )
                                )
                            modulus = 1 << q_sample_mod_bits
                            small_limit = (
                                1 << args.small_residue_bits
                                if args.small_residue_bits
                                else 0
                            )
                            sample_counts: Counter[str] = Counter()
                            for sample_kind, p_values in raw_samples[: args.samples]:
                                p_sample = int(p_known)
                                for name, value in zip(active_p, p_values, strict=True):
                                    p_sample |= value << RUNS[name][0]
                                if p_sample & 1 == 0:
                                    sample_counts["even_p_skipped"] += 1
                                    continue
                                q_mod = (instance.n * pow(p_sample % modulus, -1, modulus)) % modulus
                                yq_samples = [
                                    (q_mod >> int(item["start"])) & ((1 << int(item["width"])) - 1)
                                    for item in q_windows
                                ]
                                values = list(p_values) + yq_samples
                                relation_value = 0
                                for exponent, coeff in coeffs.items():
                                    term = int(coeff)
                                    for value, power in zip(values, exponent, strict=True):
                                        if power:
                                            term *= value**power
                                    relation_value += term
                                product_value = p_sample * q_mod - instance.n
                                product_mod_window_zero = product_value % modulus == 0
                                relation_mod_window_zero = relation_value % modulus == 0
                                relation_mod_n_zero = relation_value % instance.n == 0
                                relation_center = relation_value % instance.n
                                if relation_center > instance.n // 2:
                                    relation_center -= instance.n
                                sample_counts["total"] += 1
                                if product_mod_window_zero:
                                    sample_counts["product_mod_window_zero"] += 1
                                if relation_mod_window_zero:
                                    sample_counts["relation_mod_window_zero"] += 1
                                if relation_mod_n_zero:
                                    sample_counts["relation_mod_n_zero"] += 1
                                if (
                                    product_mod_window_zero
                                    and not relation_mod_window_zero
                                ):
                                    sample_counts["relation_prunes_product_window"] += 1
                                if small_limit and abs(relation_center) < small_limit:
                                    sample_counts["relation_small_centered_residue"] += 1
                                if len(sample_rows) < 6:
                                    sample_rows.append(
                                        {
                                            "kind": sample_kind,
                                            "q_completion_mode": "canonical_modulus_prefix",
                                            "p_values": {
                                                name: value
                                                for name, value in zip(
                                                    active_p, p_values, strict=True
                                                )
                                            },
                                            "yq_bits": {
                                                name: value.bit_length()
                                                for name, value in zip(q_names, yq_samples, strict=True)
                                            },
                                            "product_mod_window_zero": product_mod_window_zero,
                                            "product_value_bits": bit_length_abs(
                                                ZZ(product_value)
                                            ),
                                            "relation_integer_bits": bit_length_abs(
                                                ZZ(relation_value)
                                            ),
                                            "relation_center_bits": bit_length_abs(
                                                ZZ(relation_center)
                                            ),
                                            "relation_mod_window_zero": relation_mod_window_zero,
                                            "relation_mod_n_zero": relation_mod_n_zero,
                                        }
                                    )
                            preview["sample_evaluation"] = {
                                "mode": "canonical_q_window_from_sampled_p",
                                "mod_bits": q_sample_mod_bits,
                                "q_gap_bits_inside_modulus": q_gap_bits_inside_sample_modulus,
                                "q_gap_ranges_inside_modulus": [
                                    {"start": start, "width": width}
                                    for start, width in q_gap_ranges_inside_sample_modulus
                                ],
                                "sample_count_requested": args.samples,
                                "sample_counts": dict(sorted(sample_counts.items())),
                                "previews": sample_rows,
                                "sound_pruning_oracle": False,
                            }
                            if sample_counts["relation_prunes_product_window"]:
                                class_counts["sample_pruning_candidate"] += 1
                                if q_gap_bits_inside_sample_modulus:
                                    class_counts["sample_pruning_candidate_with_q_gap"] += 1
                                else:
                                    class_counts["sample_pruning_candidate_gap_free"] += 1
                                if first_sample_pruning_candidate is None:
                                    first_sample_pruning_candidate = preview
                        if first_candidate is None:
                            first_candidate = preview
                        if not derived and first_nonderived is None:
                            first_nonderived = preview

                report["lll_status"] = "ok"
                report["lll_class_counts"] = dict(sorted(class_counts.items()))
                report["first_candidate"] = first_candidate
                report["first_nonderived_candidate"] = first_nonderived
                report["first_sample_pruning_candidate"] = first_sample_pruning_candidate

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
