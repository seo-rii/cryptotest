#!/usr/bin/env python3
"""Lightweight sumset-style support growth preflight for shift families."""

from __future__ import annotations

import argparse
import itertools
import json


BASE_SUPPORTS = {
    "bilinear": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "linear8": [
        tuple(1 if i == j else 0 for i in range(8))
        for j in range(8)
    ]
    + [tuple(0 for _ in range(8))],
}


def add_exp(left: tuple[int, ...], right: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(a + b for a, b in zip(left, right))


def sumset(left: set[tuple[int, ...]], right: set[tuple[int, ...]]) -> set[tuple[int, ...]]:
    return {add_exp(a, b) for a in left for b in right}


def support_for_family(family: str, t_bits: int) -> tuple[list[str], list[int], set[tuple[int, ...]], str]:
    if family in {"bilinear", "linear8"}:
        support = set(BASE_SUPPORTS[family])
        names = [f"x{i}" for i in range(len(next(iter(support))))]
        bounds = [128 for _ in names]
        return names, bounds, support, "static toy support"

    if family == "cuso8":
        names = [f"x{i}" for i in range(8)]
        bounds = [4, 39, 84, 78, 69, 87, 46, 4]
        zero = tuple(0 for _ in names)
        support = {zero}
        support.update(tuple(1 if index == j else 0 for index in range(8)) for j in range(8))
        return names, bounds, support, "8-var unknown-divisor linear p support"

    if family == "liftT_proxy":
        names = ["a", "u2", "u3", "Z", "Y"]
        z_bits = max(0, 830 - t_bits)
        y_bits = max(1, 824 - t_bits)
        bounds = [39, 84, 78, z_bits, y_bits]
        zero = tuple(0 for _ in names)
        delta = {
            (1, 0, 0, 0, 0),
            (0, 1, 0, 0, 0),
            (0, 0, 1, 0, 0),
        }
        inv_power = max(1, (t_bits - 1) // 210)
        inv_support = {zero}
        running = {zero}
        for _ in range(inv_power):
            running = sumset(running, delta)
            inv_support |= running
        p_support = {zero, (1, 0, 0, 0, 0), (0, 1, 0, 0, 0), (0, 0, 1, 0, 0), (0, 0, 0, 1, 0)}
        c_support = sumset(p_support, inv_support)
        y_support = sumset(p_support, {(0, 0, 0, 0, 1)})
        support = c_support | y_support | p_support
        return names, bounds, support, f"T={t_bits} symbolic-lift proxy with inverse power {inv_power}"

    raise ValueError(f"unknown family {family}")


def weighted_bits(exponent: tuple[int, ...], bounds: list[int]) -> int:
    return sum(power * bound for power, bound in zip(exponent, bounds))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--family",
        choices=["bilinear", "linear8", "cuso8", "liftT_proxy"],
        default="liftT_proxy",
    )
    parser.add_argument("--shift-degree", type=int, default=2)
    parser.add_argument("--T", type=int, default=600)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    names, bounds, support, note = support_for_family(args.family, args.T)
    dim = len(names)
    shifts = set()
    for degree in range(args.shift_degree + 1):
        for exponents in itertools.product(range(degree + 1), repeat=dim):
            if sum(exponents) <= degree:
                shifts.add(exponents)
    shifted_supports: set[tuple[int, ...]] = set()
    for shift in shifts:
        for monomial in support:
            shifted_supports.add(add_exp(shift, monomial))
    minkowski_double = sumset(shifted_supports, support)
    density = len(shifts) / max(1, len(shifted_supports))
    max_weighted_bits = max(weighted_bits(exponent, bounds) for exponent in shifted_supports)
    growth_ratio = len(minkowski_double) / max(1, len(shifted_supports))
    if len(shifted_supports) > 900:
        verdict = "FAIL_DIM"
    elif growth_ratio > 2.25:
        verdict = "FAIL_EXPANDING"
    elif density < 0.75 and len(shifted_supports) > 2 * len(shifts):
        verdict = "FAIL_SPARSE"
    elif args.family == "cuso8" and max_weighted_bits >= 1024:
        verdict = "FAIL_DET_CUSO_PROXY"
    else:
        verdict = "PASS_COMPACT"
    report = {
        "family": args.family,
        "T": args.T,
        "variables": names,
        "bound_bits": bounds,
        "dimension": dim,
        "base_support_size": len(set(support)),
        "shift_count": len(shifts),
        "shifted_support_size": len(shifted_supports),
        "double_sumset_size": len(minkowski_double),
        "density": density,
        "growth_ratio": growth_ratio,
        "max_weighted_bits": max_weighted_bits,
        "preflight_signal": verdict,
        "note": note,
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
