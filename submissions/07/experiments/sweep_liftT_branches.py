#!/usr/bin/env python3
"""Sweep x6 top-edge branches for the challenge 7 symbolic lift model."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from sage.all import PolynomialRing, ZZ

from solve_hybrid_coron import common_prefix_from_interval, load_constants, parse_range_list
from solve_jm_liftT import (
    HIGH_BOUNDARY,
    P_BITS,
    RUNS,
    X0_OFFSET,
    X7_OFFSET,
    build_run_model,
    center_poly,
    divide_poly_exact,
    inv_poly_mod_power2,
    weighted_norm,
)


@dataclass
class LiftScore:
    t_bits: int
    x6_top_bits: int
    x6_top_value: int
    boundary: int
    q_prefix_bits: int
    q_high_start: int
    z_bits: int
    y_bits: int
    q_low_terms: int
    q_low_degree: int
    q_low_weighted_bits: int
    g_terms: int
    g_degree: int
    g_weighted_bits: int
    score: float


def parse_t_values(text: str) -> list[int]:
    return [int(value.strip(), 0) for value in text.split(",") if value.strip()]


def build_score(
    n: ZZ,
    mask: ZZ,
    known: ZZ,
    t_bits: int,
    branch_low: int,
    branch_high: int,
    x6_top_bits: int,
    x6_top_value: int,
) -> LiftScore | None:
    full_mask = (ZZ(1) << P_BITS) - 1
    unknown_mask = full_mask ^ mask
    branch_known = ZZ(known) | (ZZ(branch_low) << X0_OFFSET) | (ZZ(branch_high) << X7_OFFSET)
    branch_mask = ZZ(mask) | (ZZ(0xF) << X0_OFFSET) | (ZZ(0xF) << X7_OFFSET)

    fixed_start = HIGH_BOUNDARY - x6_top_bits
    fixed_width = x6_top_bits
    fixed_mask = ((ZZ(1) << fixed_width) - 1) << fixed_start
    fixed_bits = ZZ(x6_top_value) << fixed_start
    if ((branch_known ^ fixed_bits) & (branch_mask & fixed_mask)) != 0:
        return None
    branch_known |= fixed_bits
    branch_mask |= fixed_mask

    remaining_mask = unknown_mask & (full_mask ^ branch_mask)
    p_min = branch_known
    p_max = branch_known | remaining_mask
    if p_min <= 0 or p_max <= 0:
        return None
    q_min = n // p_max
    q_max = n // p_min
    q_prefix_bits, q_high, q_high_start = common_prefix_from_interval(q_min, q_max)
    if q_high_start <= t_bits:
        return None

    low_specs = []
    for name, offset, width in RUNS:
        if offset >= t_bits:
            continue
        low_width = width
        if offset + width > t_bits:
            low_width = t_bits - offset
            name = f"{name}l"
        low_specs.append((name, offset, low_width))

    ring = PolynomialRing(ZZ, names=tuple([name for name, _, _ in low_specs] + ["Z", "Y"]))
    gen_by_name = {str(gen): gen for gen in ring.gens()}
    run_models = {
        name: build_run_model(name, offset, width, gen_by_name[name], branch_mask, branch_known)
        for name, offset, width in low_specs
    }

    modulus = ZZ(1) << t_bits
    low_mask = modulus - 1
    low_variable_mask = ZZ(0)
    p_low = ring(ZZ(branch_known & low_mask))
    delta = ring(0)
    low_variable_names = []
    for name, offset, width in low_specs:
        run = run_models[name]
        run_mask = ((ZZ(1) << width) - 1) << offset
        low_variable_mask |= run_mask
        p_low -= ring(ZZ(branch_known & run_mask))
        p_low += (ZZ(1) << offset) * run.expr
        delta += (ZZ(1) << offset) * (run.expr - run.constant)
        low_variable_names.append(name)

    p0 = ZZ((branch_known & low_mask) & (low_mask ^ low_variable_mask))
    q_low = center_poly(ring(ZZ(n % modulus)) * inv_poly_mod_power2(p0, delta, t_bits), modulus)

    boundary = HIGH_BOUNDARY
    while boundary > t_bits and ((branch_mask >> (boundary - 1)) & 1):
        boundary -= 1

    z = gen_by_name["Z"]
    y = gen_by_name["Y"]
    high_known = ZZ(branch_known & (full_mask ^ ((ZZ(1) << boundary) - 1)))
    p_expr = p_low + (ZZ(1) << t_bits) * z + high_known
    bounds_by_name = {name: run_models[name].bound for name in low_variable_names}
    bounds_by_name["Z"] = ZZ(1) << (boundary - t_bits)

    c_poly = divide_poly_exact(p_expr * q_low - n, modulus)
    q_low_norm = weighted_norm(q_low, [bounds_by_name[str(gen)] for gen in ring.gens() if str(gen) in bounds_by_name])
    slack_bits = max(0, q_low_norm.nbits() - 1 - t_bits) + 2
    y_bits = max(q_high_start - t_bits, slack_bits)
    g_poly = c_poly + p_expr * y + p_expr * ZZ(q_high) * (ZZ(1) << (q_high_start - t_bits))
    bounds_by_name["Y"] = ZZ(1) << y_bits
    bounds = [bounds_by_name[str(gen)] for gen in ring.gens()]
    g_norm = weighted_norm(g_poly, bounds)

    z_bits = boundary - t_bits
    # Lower is better; put a small bonus on q prefix because it helps folded verifiers too.
    score = float(g_norm.nbits() + 2 * max(z_bits, y_bits) + z_bits + y_bits - q_prefix_bits)
    return LiftScore(
        t_bits=t_bits,
        x6_top_bits=x6_top_bits,
        x6_top_value=x6_top_value,
        boundary=boundary,
        q_prefix_bits=q_prefix_bits,
        q_high_start=q_high_start,
        z_bits=z_bits,
        y_bits=y_bits,
        q_low_terms=len(q_low.dict()),
        q_low_degree=q_low.degree(),
        q_low_weighted_bits=q_low_norm.nbits() - 1,
        g_terms=len(g_poly.dict()),
        g_degree=g_poly.degree(),
        g_weighted_bits=g_norm.nbits(),
        score=score,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--T-values", default="600,608")
    parser.add_argument("--branch-low", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--branch-high", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--x6-top-bits", type=int, default=8)
    parser.add_argument("--values", default=None)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    if not (1 <= args.x6_top_bits <= 46):
        raise SystemExit("--x6-top-bits must be in 1..46")
    if not (0 <= args.branch_low < 16 and 0 <= args.branch_high < 16):
        raise SystemExit("branch nibbles must be in 0..15")

    if args.stride <= 0:
        raise SystemExit("--stride must be positive")
    if args.offset < 0:
        raise SystemExit("--offset must be non-negative")

    values = (
        parse_range_list(args.values)
        if args.values is not None
        else list(range(args.offset, 1 << args.x6_top_bits, args.stride))
    )

    constants = load_constants()
    n = ZZ(int(constants.N_HEX.replace(" ", ""), 16))
    mask = ZZ(int(constants.MASK_HEX.replace(" ", ""), 16))
    known = ZZ(int(constants.P_AND_MASK_HEX.replace(" ", ""), 16)) & mask

    scores = []
    for t_bits in parse_t_values(args.T_values):
        for value in values:
            score = build_score(
                n,
                mask,
                known,
                t_bits,
                args.branch_low,
                args.branch_high,
                args.x6_top_bits,
                value,
            )
            if score is not None:
                scores.append(score)

    scores.sort(key=lambda item: (item.score, -item.q_prefix_bits, item.g_weighted_bits, item.x6_top_value))
    print(
        "rank T x6bits value boundary qpref qstart Zbits Ybits "
        "qlow_terms qlow_deg qlow_W G_terms G_deg G_W score"
    )
    for rank, item in enumerate(scores[: args.top], start=1):
        print(
            f"{rank:02d} {item.t_bits} {item.x6_top_bits} "
            f"0x{item.x6_top_value:0{(item.x6_top_bits + 3) // 4}x} "
            f"{item.boundary} {item.q_prefix_bits} {item.q_high_start} "
            f"{item.z_bits} {item.y_bits} "
            f"{item.q_low_terms} {item.q_low_degree} {item.q_low_weighted_bits} "
            f"{item.g_terms} {item.g_degree} {item.g_weighted_bits} "
            f"{item.score:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
