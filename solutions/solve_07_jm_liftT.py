#!/usr/bin/env python3
"""Symbolic 2-adic lift models for challenge 7.

For T=600, p mod 2^T depends only on x1, x2, x3:

    delta = 2^210*x1 + 2^265*x2 + 2^362*x3

Since delta^3 has valuation at least 630, (P0 + delta)^-1 modulo 2^600 is a
quadratic polynomial.  This removes q[210..599] from the model and leaves a
much smaller q tail variable than the T=265 affine lift.
"""

from __future__ import annotations

import argparse
import logging
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from sage.all import PolynomialRing, ZZ, gcd, inverse_mod, matrix

from solve_07_hybrid_coron import common_prefix_from_interval, int_to_bytes, load_constants, parse_range_list


DEFAULT_CRYPTO_ATTACKS = Path("/tmp/crypto-attacks")
P_BITS = 1024
X0_OFFSET = 150
X7_OFFSET = 920
HIGH_BOUNDARY = 830

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


def center_poly(poly, modulus: ZZ):
    ring = poly.parent()
    out = ring(0)
    for monomial, coeff in poly.dict().items():
        term = centered_mod(ZZ(coeff), modulus)
        for gen, exponent in zip(ring.gens(), monomial):
            term *= gen**exponent
        out += term
    return out


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


def reduce_lattice_with_fplll(lattice, delta: float):
    free_bytes = shutil.disk_usage(tempfile.gettempdir()).free
    if free_bytes < 512 * 1024 * 1024:
        logging.warning(
            "Skipping fplll reduction because %s has only %.1f MiB free",
            tempfile.gettempdir(),
            free_bytes / 2**20,
        )
        return lattice.LLL(delta)

    with tempfile.TemporaryDirectory(prefix="liftT_fplll_") as tmp_dir:
        input_path = Path(tmp_dir) / "basis.txt"
        output_path = Path(tmp_dir) / "reduced.txt"
        with input_path.open("w", encoding="utf-8") as handle:
            handle.write("[")
            for row in range(lattice.nrows()):
                if row:
                    handle.write("\n")
                entries = " ".join(str(ZZ(lattice[row, col])) for col in range(lattice.ncols()))
                handle.write(f"[{entries} ]")
            handle.write("\n]\n")

        command = ["fplll", "-a", "lll", "-d", str(delta), str(input_path)]
        logging.debug("Reducing with fplll CLI: %s", " ".join(command))
        with output_path.open("w", encoding="utf-8") as output:
            try:
                subprocess.run(command, check=True, stdout=output, stderr=subprocess.PIPE, text=True)
            except subprocess.CalledProcessError as exc:
                logging.warning("fplll failed, falling back to Sage LLL: %s", exc.stderr.strip())
                return lattice.LLL(delta)

        text = output_path.read_text(encoding="utf-8")

    values = [ZZ(part) for part in text.replace("[", " ").replace("]", " ").split()]
    expected = lattice.nrows() * lattice.ncols()
    if len(values) != expected:
        logging.warning(
            "fplll returned %s entries, expected %s; falling back to Sage LLL",
            len(values),
            expected,
        )
        return lattice.LLL(delta)
    return matrix(ZZ, lattice.nrows(), lattice.ncols(), values)


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
    fixed_mask = ((ZZ(1) << width) - 1) ^ (((ZZ(1) << variable_width) - 1) << lo)
    constant = known_value & fixed_mask
    expr = ZZ(constant) + ZZ(scale) * gen
    return RunModel(name, offset, width, ZZ(1) << variable_width, expr, ZZ(constant), ZZ(scale), variable_width)


def inv_poly_mod_power2(p0: ZZ, delta, bits: int):
    ring = delta.parent()
    modulus = ZZ(1) << bits
    inv_p0 = ZZ(inverse_mod(ZZ(p0 % modulus), modulus))

    min_v = None
    for coeff in delta.dict().values():
        coeff = ZZ(coeff)
        if coeff:
            valuation = coeff.valuation(2)
            min_v = valuation if min_v is None else min(min_v, valuation)
    if min_v is None:
        return ring(inv_p0)

    max_power = (bits - 1) // min_v
    z = -ring(inv_p0) * delta
    series = ring(0)
    term = ring(1)
    for _ in range(max_power + 1):
        series += term
        term *= z
    return center_poly(ring(inv_p0) * series, modulus)


def strategy_from_name(jm, name: str, t: int, gens) -> object:
    if name == "basic":
        return jm.BasicStrategy()

    vector = [0] * len(gens)
    index_by_name = {str(gen): index for index, gen in enumerate(gens)}
    if name == "extended":
        vector = [t] * len(gens)
    else:
        for part in name.removeprefix("ext_").split("_"):
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
    parser.add_argument("--T", type=int, default=600)
    parser.add_argument("--coarse-high", action="store_true")
    parser.add_argument("--fine-high", action="store_true")
    parser.add_argument("--branch-low", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--branch-high", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_bit_range_value)
    parser.add_argument("--m-values", default="1,2")
    parser.add_argument("--t-values", default="1")
    parser.add_argument("--strategy", default="basic")
    parser.add_argument("--roots-method", choices=["groebner", "resultants", "variety"], default="resultants")
    parser.add_argument("--reduction", choices=["sage", "fplll"], default="sage")
    parser.add_argument("--fplll-delta", type=float, default=0.8)
    parser.add_argument("--sample-checks", type=int, default=3)
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not args.coarse_high and not args.fine_high:
        args.coarse_high = True
    if args.coarse_high and args.fine_high:
        raise SystemExit("choose only one of --coarse-high or --fine-high")
    if not (0 <= args.branch_low < 16 and 0 <= args.branch_high < 16):
        raise SystemExit("branch nibbles must be in 0..15")
    if args.T < 211 or args.T > HIGH_BOUNDARY:
        raise SystemExit("--T must be in 211..830 for this model")
    if not args.crypto_attacks.exists():
        raise SystemExit(f"{args.crypto_attacks} does not exist")
    sys.path.insert(0, str(args.crypto_attacks))

    from shared.small_roots import jochemsz_may_integer
    from shared import small_roots

    if args.reduction == "fplll":
        small_roots.reduce_lattice = lambda lattice, delta=0.8: reduce_lattice_with_fplll(
            lattice, args.fplll_delta
        )

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
    if q_high_start <= args.T:
        raise SystemExit("q high prefix reaches the lifted low part; model needs adjustment")

    low_specs = []
    for name, offset, width in RUNS:
        if offset >= args.T:
            continue
        low_width = width
        if offset + width > args.T:
            if not args.coarse_high:
                raise SystemExit("partial low run crosses T; use --coarse-high for partial low-run lift")
            low_width = args.T - offset
            name = f"{name}l"
        low_specs.append((name, offset, low_width))

    if args.coarse_high:
        ring = PolynomialRing(ZZ, names=tuple([name for name, _, _ in low_specs] + ["Z", "Y"]))
    else:
        ring = PolynomialRing(ZZ, names=("a", "u2", "u3", "u4", "u5", "b", "Y"))
    gens = ring.gens()
    gen_by_name = {str(gen): gen for gen in gens}

    run_models: dict[str, RunModel] = {}
    if args.coarse_high:
        for name, offset, width in low_specs:
            run_models[name] = build_run_model(name, offset, width, gen_by_name[name], branch_mask, branch_known)
    else:
        for name, offset, width in RUNS:
            if name in gen_by_name:
                run_models[name] = build_run_model(name, offset, width, gen_by_name[name], branch_mask, branch_known)

    modulus = ZZ(1) << args.T
    low_mask = modulus - 1
    low_variable_mask = ZZ(0)
    p_low = ring(ZZ(branch_known & low_mask))
    delta = ring(0)
    low_variable_names = []
    for name, offset, width in low_specs:
        if name not in run_models:
            raise SystemExit(f"low variable {name} is not present in the selected ring")
        run = run_models[name]
        run_mask = ((ZZ(1) << width) - 1) << offset
        low_variable_mask |= run_mask
        p_low -= ring(ZZ(branch_known & run_mask))
        p_low += (ZZ(1) << offset) * run.expr
        delta += (ZZ(1) << offset) * (run.expr - run.constant)
        low_variable_names.append(name)

    p0 = ZZ((branch_known & low_mask) & (low_mask ^ low_variable_mask))
    inv_low = inv_poly_mod_power2(p0, delta, args.T)
    q_low = center_poly(ring(ZZ(n % modulus)) * inv_low, modulus)

    coarse_high_boundary = HIGH_BOUNDARY
    if args.coarse_high:
        z = gen_by_name["Z"]
        while coarse_high_boundary > args.T and ((branch_mask >> (coarse_high_boundary - 1)) & 1):
            coarse_high_boundary -= 1
        high_known = ZZ(branch_known & (full_mask ^ ((ZZ(1) << coarse_high_boundary) - 1)))
        p_expr = p_low + (ZZ(1) << args.T) * z + high_known
        bounds_by_name = {name: run_models[name].bound for name in low_variable_names}
        bounds_by_name["Z"] = ZZ(1) << (coarse_high_boundary - args.T)
    else:
        variable_run_mask = ZZ(0)
        for name, offset, width in RUNS:
            variable_run_mask |= ((ZZ(1) << width) - 1) << offset
        p_base = branch_known & (full_mask ^ variable_run_mask)
        p_expr = ring(ZZ(p_base))
        bounds_by_name = {}
        for name, offset, _ in RUNS:
            run = run_models[name]
            p_expr += (ZZ(1) << offset) * run.expr
            bounds_by_name[name] = run.bound

    c_poly = divide_poly_exact(p_expr * q_low - n, modulus)
    q_low_norm = weighted_norm(q_low, [bounds_by_name[str(gen)] for gen in gens if str(gen) in bounds_by_name])
    slack_bits = max(0, q_low_norm.nbits() - 1 - args.T) + 2
    y_bits = max(q_high_start - args.T, slack_bits)
    y = gen_by_name["Y"]
    g_poly = c_poly + p_expr * y + p_expr * ZZ(q_high) * (ZZ(1) << (q_high_start - args.T))
    bounds_by_name["Y"] = ZZ(1) << y_bits
    bounds = [bounds_by_name[str(gen)] for gen in gens]
    w = weighted_norm(g_poly, bounds)

    rng = random.Random(7)
    for _ in range(args.sample_checks):
        sample = {}
        for gen in gens:
            name = str(gen)
            if name == "Y":
                continue
            sample[gen] = ZZ(rng.randrange(int(bounds_by_name[name])))
        p_low_value = ZZ(p_low.subs(sample))
        q_low_value = ZZ(q_low.subs(sample))
        assert (p_low_value * q_low_value - n) % modulus == 0

    print(f"branch x0={args.branch_low:x}, x7={args.branch_high:x}")
    for fixed_start, fixed_width, fixed_value in args.fix_p_range:
        print(f"fixed p[{fixed_start}..{fixed_start + fixed_width - 1}] = {fixed_value:#x}")
    print(f"T={args.T} mode={'coarse_high' if args.coarse_high else 'fine_high'}")
    if args.coarse_high:
        print(f"coarse_high_boundary={coarse_high_boundary}")
    print(f"q_prefix_bits={q_prefix_bits} q_high_start={q_high_start}")
    print(f"low variables={','.join(low_variable_names)}")
    print(f"divisible=True sample_checks={args.sample_checks}")
    for gen in gens:
        name = str(gen)
        print(f"{name}: bound_bits={bounds_by_name[name].nbits() - 1}")
    print(
        f"q_low terms={len(q_low.dict())} degree={q_low.degree()} "
        f"weighted_bits={q_low_norm.nbits() - 1}"
    )
    print(f"G terms={len(g_poly.dict())} degree={g_poly.degree()} Wbits={w.nbits()}")
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
                print(f"[*] JM liftT m={m} strategy={strategy_name} t={t}", flush=True)
                started = time.time()
                try:
                    roots = jochemsz_may_integer.integer_multivariate(
                        g_poly,
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
