#!/usr/bin/env python3
"""Preflight unknown-divisor linear-equation lattice directions.

This does not claim to implement Takayasu-Kunihiro or Lu-Zhang completely.
It records the current unknown-divisor linear model from the problem mask and
estimates where HM-like monomial budgets lose determinant margin before running
LLL.
"""

from __future__ import annotations

import argparse
import json
import math
from math import comb

from sat_cas_core import load_instance


def current_runs(instance) -> list[tuple[str, int, int]]:
    return [
        (f"x{index}", start, end - start + 1)
        for index, (start, end) in enumerate(instance.unknown_ranges())
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-weight", type=float, default=140.0)
    parser.add_argument("--max-degree", type=int, default=3)
    parser.add_argument(
        "--active",
        default="all",
        help="comma-separated active variable names for determinant margin",
    )
    parser.add_argument("--m-max", type=int, default=8)
    parser.add_argument("--t-max", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    instance = load_instance()
    runs = current_runs(instance)
    by_name = {name: (offset, width) for name, offset, width in runs}
    if args.active.strip().lower() in {"", "all"}:
        active_names = [name for name, _offset, _width in runs]
    else:
        active_names = [part.strip() for part in args.active.split(",") if part.strip()]
    for name in active_names:
        if name not in by_name:
            raise SystemExit(f"unknown active variable: {name}")
    weights = [by_name[name][1] for name in active_names]
    monomials = []
    for degree in range(args.max_degree + 1):
        stack = [(0, degree, [])]
        while stack:
            index, remaining, prefix = stack.pop()
            if index == len(weights) - 1:
                exponents = tuple(prefix + [remaining])
                weighted = sum(power * weight for power, weight in zip(exponents, weights))
                if weighted <= args.max_weight:
                    monomials.append((exponents, weighted))
                continue
            for value in range(remaining + 1):
                stack.append((index + 1, remaining - value, prefix + [value]))
    monomials.sort(key=lambda item: (item[1], sum(item[0]), item[0]))
    determinant_proxy = sum(weighted for _exponents, weighted in monomials)
    modulus_bits = instance.n.bit_length()
    unknown_sum = sum(width for _name, _offset, width in runs)
    active_sum = sum(weights)

    margin_records = []
    beta = 0.5
    nvars = len(active_names)
    for m_value in range(1, args.m_max + 1):
        d = comb(m_value + nvars, nvars)
        sx = comb(m_value + nvars, nvars + 1)
        for t_value in range(1, args.t_max + 1):
            sn = 0
            for k in range(min(t_value - 1, m_value) + 1):
                sn += (t_value - k) * comb(m_value - k + nvars - 1, nvars - 1)
            denom = d - nvars + 1
            logdet_bits = sx * active_sum + sn * modulus_bits
            lhs_bits = d * (d - 1) / (4.0 * denom) + logdet_bits / denom
            rhs_bits = beta * t_value * modulus_bits - 0.5 * math.log2(d)
            margin_records.append(
                {
                    "m": m_value,
                    "t": t_value,
                    "dimension": d,
                    "s_x": sx,
                    "s_N": sn,
                    "logdet_bits": logdet_bits,
                    "lhs_bits": lhs_bits,
                    "rhs_bits": rhs_bits,
                    "margin_bits": rhs_bits - lhs_bits,
                }
            )
    margin_records.sort(key=lambda item: item["margin_bits"], reverse=True)
    report = {
        "model": "linear_unknown_divisor",
        "variables": [
            {"name": name, "offset": offset, "bound_bits": width}
            for name, offset, width in runs
        ],
        "active": [
            {"name": name, "offset": by_name[name][0], "bound_bits": by_name[name][1]}
            for name in active_names
        ],
        "unknown_sum_bits": unknown_sum,
        "active_sum_bits": active_sum,
        "small_variable_bits": [width for width in [item[2] for item in runs] if width <= 4],
        "max_weight": args.max_weight,
        "max_degree": args.max_degree,
        "monomial_count": len(monomials),
        "determinant_proxy_bits": determinant_proxy,
        "n_bits": modulus_bits,
        "beta_half_threshold_bits": modulus_bits / 2.0,
        "small_variables_kept": True,
        "tk_lz_status": "preflight_only_formula_not_claimed",
        "best_lz_hm_margin": margin_records[0] if margin_records else None,
        "top_monomials": [
            {
                "exponents": dict(
                    (active_names[index], power)
                    for index, power in enumerate(exponents)
                    if power
                ),
                "weighted_bits": weighted,
            }
            for exponents, weighted in monomials[:20]
        ],
        "density_warning": len(monomials) < len(runs) + 2,
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
