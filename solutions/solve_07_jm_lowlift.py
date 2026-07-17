#!/usr/bin/env python3
"""Low-lifted Jochemsz-May attempt for challenge 7.

This model keeps x1 as an explicit variable and removes q[210..264] by using
the affine inverse modulo 2^265:

    q_low(a) = N * (P0 + 2^210 a)^-1
             = Q0 + C1 a  (mod 2^265)

The equation is then lifted to an exact integer polynomial:

    G = (p(a, u2, u3, u4, u5, b) * q(a, Y) - N) / 2^265.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from sage.all import PolynomialRing, ZZ, gcd, inverse_mod

from solve_07_hybrid_coron import common_prefix_from_interval, int_to_bytes, load_constants, parse_range_list


DEFAULT_CRYPTO_ATTACKS = Path("/tmp/crypto-attacks")
P_BITS = 1024
LIFT_BITS = 265
X0_OFFSET = 150
X1_OFFSET = 210
X7_OFFSET = 920
RUNS = [
    ("a", 210, 39),
    ("u2", 265, 84),
    ("u3", 362, 78),
    ("u4", 600, 69),
    ("u5", 682, 87),
    ("b", 784, 46),
]


@dataclass
class RunModel:
    name: str
    offset: int
    width: int
    bound: ZZ
    expr: object
    constant: ZZ
    scale: ZZ
    variable_width: int


def parse_bit_range_value(text: str) -> tuple[int, int, int]:
    try:
        start_text, width_text, value_text = text.split(":", 2)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH:VALUE") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    value = int(value_text, 0)
    if start < 0 or width <= 0 or start + width > P_BITS:
        raise argparse.ArgumentTypeError("invalid bit range")
    if value < 0 or value >= (1 << width):
        raise argparse.ArgumentTypeError("value does not fit selected width")
    return start, width, value


def centered_mod(value: ZZ, modulus: ZZ) -> ZZ:
    value = ZZ(value % modulus)
    if value > modulus // 2:
        value -= modulus
    return value


def divide_poly_exact(poly, divisor: ZZ):
    ring = poly.parent()
    out = ring(0)
    for monomial, coeff in poly.dict().items():
        coeff = ZZ(coeff)
        assert coeff % divisor == 0
        term = coeff // divisor
        for gen, exponent in zip(ring.gens(), monomial):
            term *= gen**exponent
        out += term
    return out


def weighted_norm(poly, bounds: list[ZZ]) -> ZZ:
    best = ZZ(0)
    for exponent, coeff in poly.dict().items():
        coeff = abs(ZZ(coeff))
        if coeff == 0:
            continue
        value = coeff
        for bound, power in zip(bounds, exponent):
            value *= bound**power
        best = max(best, value)
    return best


def contiguous_unknown_run(mask_bits: list[bool]) -> tuple[int, int] | None:
    unknown = [index for index, fixed in enumerate(mask_bits) if not fixed]
    if not unknown:
        return None
    lo = min(unknown)
    hi = max(unknown)
    if len(unknown) != hi - lo + 1:
        raise ValueError("fixed bits must leave a contiguous variable interval inside each run")
    return lo, hi


def build_run_model(name: str, offset: int, width: int, gen, branch_mask: ZZ, branch_known: ZZ) -> RunModel:
    fixed_bits = [bool((branch_mask >> (offset + bit)) & 1) for bit in range(width)]
    known_value = ZZ((branch_known >> offset) & ((ZZ(1) << width) - 1))
    unknown_span = contiguous_unknown_run(fixed_bits)
    if unknown_span is None:
        return RunModel(name, offset, width, ZZ(1), ZZ(known_value), known_value, ZZ(0), 0)

    lo, hi = unknown_span
    variable_width = hi - lo + 1
    scale = ZZ(1) << lo
    # Clear the unknown interval; fixed low/high edge bits remain in the constant.
    fixed_mask = ((ZZ(1) << width) - 1) ^ (((ZZ(1) << variable_width) - 1) << lo)
    constant = known_value & fixed_mask
    expr = ZZ(constant) + ZZ(scale) * gen
    return RunModel(name, offset, width, ZZ(1) << variable_width, expr, ZZ(constant), ZZ(scale), variable_width)


def strategy_from_name(jm, name: str, t: int, gens) -> object:
    if name == "basic":
        return jm.BasicStrategy()

    vector = [0] * len(gens)
    index_by_name = {str(gen): index for index, gen in enumerate(gens)}
    if name == "extended":
        vector = [t] * len(gens)
    else:
        suffix = name.removeprefix("ext_")
        for part in suffix.split("_"):
            if not part:
                continue
            if part == "edge":
                selected = ["a", "b"]
            else:
                selected = [part]
            for var_name in selected:
                if var_name not in index_by_name:
                    raise ValueError(f"unknown strategy variable {var_name!r}")
                vector[index_by_name[var_name]] = t
    return jm.ExtendedStrategy(vector)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crypto-attacks", type=Path, default=DEFAULT_CRYPTO_ATTACKS)
    parser.add_argument("--branch-low", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--branch-high", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_bit_range_value)
    parser.add_argument("--m-values", default="1,2")
    parser.add_argument("--t-values", default="1")
    parser.add_argument(
        "--strategy",
        default="basic",
        help="comma list: basic,extended,ext_a,ext_b,ext_edge,ext_a_b,ext_Y,...",
    )
    parser.add_argument("--roots-method", choices=["groebner", "resultants", "variety"], default="resultants")
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not args.crypto_attacks.exists():
        raise SystemExit(f"{args.crypto_attacks} does not exist")
    if not (0 <= args.branch_low < 16 and 0 <= args.branch_high < 16):
        raise SystemExit("branch nibbles must be in 0..15")
    sys.path.insert(0, str(args.crypto_attacks))

    from shared.small_roots import jochemsz_may_integer

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    constants = load_constants()
    n = ZZ(int(constants.N_HEX.replace(" ", ""), 16))
    e = int(constants.E)
    ct = int(constants.CT_HEX.replace(" ", ""), 16)
    mask = ZZ(int(constants.MASK_HEX.replace(" ", ""), 16))
    known = ZZ(int(constants.P_AND_MASK_HEX.replace(" ", ""), 16)) & mask
    full_mask = (ZZ(1) << P_BITS) - 1
    unknown_mask = full_mask ^ mask

    branch_known = ZZ(known) | (ZZ(args.branch_low) << X0_OFFSET) | (ZZ(args.branch_high) << X7_OFFSET)
    branch_mask = ZZ(mask) | (ZZ(0xF) << X0_OFFSET) | (ZZ(0xF) << X7_OFFSET)
    for fixed_start, fixed_width, fixed_value in args.fix_p_range:
        fixed_mask = ((ZZ(1) << fixed_width) - 1) << fixed_start
        fixed_bits = ZZ(fixed_value) << fixed_start
        if ((branch_known ^ fixed_bits) & (branch_mask & fixed_mask)) != 0:
            raise SystemExit(f"inconsistent --fix-p-range {fixed_start}:{fixed_width}:{fixed_value:#x}")
        branch_known |= fixed_bits
        branch_mask |= fixed_mask

    remaining_mask = unknown_mask & (full_mask ^ branch_mask)
    p_min = branch_known
    p_max = branch_known | remaining_mask
    q_min = n // p_max
    q_max = n // p_min
    q_prefix_bits, q_high, q_high_start = common_prefix_from_interval(q_min, q_max)
    if q_high_start <= LIFT_BITS:
        raise SystemExit("q high prefix reaches the lifted low part; model needs adjustment")

    ring = PolynomialRing(ZZ, names=("a", "u2", "u3", "u4", "u5", "b", "Y"))
    gens = ring.gens()
    gen_by_name = {str(gen): gen for gen in gens}
    run_models = [
        build_run_model(name, offset, width, gen_by_name[name], branch_mask, branch_known)
        for name, offset, width in RUNS
    ]
    run_by_name = {run.name: run for run in run_models}

    variable_run_mask = ZZ(0)
    for _, offset, width in RUNS:
        variable_run_mask |= ((ZZ(1) << width) - 1) << offset
    p_base = branch_known & (full_mask ^ variable_run_mask)
    p_expr = ring(ZZ(p_base))
    for run in run_models:
        p_expr += (ZZ(1) << run.offset) * run.expr

    modulus = ZZ(1) << LIFT_BITS
    low_lift_mask = (ZZ(1) << LIFT_BITS) - 1
    x1_mask = ((ZZ(1) << 39) - 1) << X1_OFFSET
    p0 = ZZ(branch_known & low_lift_mask & (low_lift_mask ^ x1_mask))
    inv_p0 = inverse_mod(p0, modulus)
    q0 = ZZ(n * inv_p0) % modulus
    c1 = centered_mod(-((ZZ(1) << X1_OFFSET) * n * inv_p0 * inv_p0), modulus)
    q_aff = ring(ZZ(q0)) + ring(ZZ(c1)) * run_by_name["a"].expr
    q_expr = q_aff + modulus * gen_by_name["Y"] + (ZZ(q_high) << q_high_start)

    lifted = ring(p_expr * q_expr - n)
    for coeff in lifted.coefficients():
        assert ZZ(coeff) % modulus == 0
    poly = divide_poly_exact(lifted, modulus)

    y_slack_bits = max(40, run_by_name["a"].variable_width + 1)
    bounds_by_name = {run.name: run.bound for run in run_models}
    bounds_by_name["Y"] = (ZZ(1) << (q_high_start - LIFT_BITS)) + (ZZ(1) << y_slack_bits)
    bounds = [bounds_by_name[str(gen)] for gen in gens]
    w = weighted_norm(poly, bounds)

    print(f"branch x0={args.branch_low:x}, x7={args.branch_high:x}")
    for fixed_start, fixed_width, fixed_value in args.fix_p_range:
        print(f"fixed p[{fixed_start}..{fixed_start + fixed_width - 1}] = {fixed_value:#x}")
    print(f"q_prefix_bits={q_prefix_bits} q_high_start={q_high_start}")
    print(f"lift_bits={LIFT_BITS} divisible=True")
    print(f"P0 odd={bool(p0 & 1)} C1_v2={gcd(abs(c1), modulus).valuation(2) if c1 else LIFT_BITS}")
    for run in run_models:
        print(
            f"{run.name}: offset={run.offset} original_bits={run.width} "
            f"variable_bits={run.variable_width} bound_bits={run.bound.nbits() - 1} "
            f"scale={int(run.scale):#x} const={int(run.constant):#x}"
        )
    print(f"Y bound bits={bounds_by_name['Y'].nbits() - 1}")
    print(f"terms={len(poly.dict())} degree={poly.degree()} Wbits={w.nbits()}")
    if args.diagnose_only:
        return 0

    strategy_names = [part.strip() for part in args.strategy.split(",") if part.strip()]
    jm_runs = 0
    started_all = time.time()
    for strategy_name in strategy_names:
        for m in parse_range_list(args.m_values):
            for t in parse_range_list(args.t_values):
                try:
                    strategy = strategy_from_name(jochemsz_may_integer, strategy_name, t, gens)
                except ValueError as exc:
                    raise SystemExit(str(exc)) from exc
                jm_runs += 1
                print(f"[*] JM lowlift m={m} strategy={strategy_name} t={t}", flush=True)
                started = time.time()
                try:
                    roots = jochemsz_may_integer.integer_multivariate(
                        poly,
                        m,
                        w,
                        list(bounds),
                        strategy,
                        roots_method=args.roots_method,
                    )
                    for root_tuple in roots:
                        root_map = {gen: ZZ(value) for gen, value in zip(gens, root_tuple)}
                        if any(root_map[gen] < 0 or root_map[gen] >= bound for gen, bound in zip(gens, bounds)):
                            continue
                        p = ZZ(p_expr.subs(root_map))
                        if p <= 1 or n % p != 0:
                            continue
                        if (p & mask) != known:
                            continue
                        q = n // p
                        phi = (p - 1) * (q - 1)
                        d = inverse_mod(e, phi)
                        plaintext_int = ZZ(pow(int(ct), int(d), int(n)))
                        assert pow(int(plaintext_int), e, int(n)) == int(ct)
                        print("[+] FACTORED")
                        print(f"p = {int(p):#x}")
                        print(f"q = {int(q):#x}")
                        print(f"[+] plaintext bytes = {int_to_bytes(int(plaintext_int))!r}")
                        return 0
                except Exception as exc:  # noqa: BLE001 - investigation script should keep sweeping.
                    print(f"[!] failed: {type(exc).__name__}: {exc}", flush=True)
                print(f"[-] no factor, elapsed={time.time() - started:.2f}s", flush=True)

    print(f"[-] not found; jm_runs={jm_runs}, elapsed={time.time() - started_all:.2f}s", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
