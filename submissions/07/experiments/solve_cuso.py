#!/usr/bin/env python3
"""Solve challenge 7 with cuso's optimized multivariate Coppersmith.

This script expects SageMath's Python and cuso. In this workspace, use the
dedicated mamba environment:

    /home/seorii/.local/share/miniforge3/bin/mamba run -n soinsu-sage python \
        cryptotest/submissions/07/src/solve_cuso.py --branch

The q-divisor mode derives a low-bit polynomial for q from p mod 2^600
and combines it with the q high-prefix interval:

    /home/seorii/.local/share/miniforge3/bin/mamba run -n soinsu-sage python \
        cryptotest/submissions/07/src/solve_cuso.py --q-divisor --no-graph \
        --partial --max-shifts 1024 --max-multiplicity 2 --flatter-args '-rhf 1.03'

The constants are loaded from investigate_rsa_partial_bits.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import math
import shlex
import sys
import time
from pathlib import Path
from subprocess import PIPE, Popen

from sage.all import PolynomialRing, TermOrder, ZZ, inverse_mod, var


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CUSO_SRC = Path("/tmp/cuso/src")

UNKNOWN_RANGES = [
    (150, 4),
    (265, 84),
    (362, 58),
    (600, 69),
    (682, 87),
    (784, 46),
    (920, 4),
]


def parse_bit_range_value(text: str) -> tuple[int, int, int]:
    try:
        start_text, width_text, value_text = text.split(":", 2)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH:VALUE") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    value = int(value_text, 0)
    if start < 0 or width <= 0 or start + width > 1024:
        raise argparse.ArgumentTypeError("invalid bit range")
    if value < 0 or value >= (1 << width):
        raise argparse.ArgumentTypeError("value does not fit selected width")
    return start, width, value


def maybe_add_cuso_path(path: Path) -> None:
    if path.exists():
        sys.path.insert(0, str(path))


def patch_cuso_boundset_for_sage109() -> None:
    """Make cuso 0.4.0 accept Sage 10.9 libsingular generators."""

    from cuso.data.bounds.bound import Bound
    from cuso.data.bounds.bound_set import BoundSet
    from sage.all import Expression, Polynomial as SagePolynomial
    from sage.rings.polynomial.multi_polynomial import MPolynomial

    if getattr(BoundSet, "_cryptotest_sage109_patch", False):
        return

    def boundset_setitem(self, key, value):
        type_error = "Keys must be symbols or generators of a polynomial ring"
        if isinstance(key, MPolynomial):
            if key not in key.parent().gens():
                raise TypeError(type_error)
        elif isinstance(key, SagePolynomial):
            if not key.is_gen():
                raise TypeError(type_error)
        elif isinstance(key, Expression):
            if not key.is_symbol():
                raise TypeError(type_error)
        else:
            raise TypeError(type_error)
        if not isinstance(value, Bound):
            value = Bound(key, *value)
        super(BoundSet, self).__setitem__(key, value)

    BoundSet.__setitem__ = boundset_setitem
    BoundSet._cryptotest_sage109_patch = True


def load_constants():
    spec = importlib.util.spec_from_file_location(
        "investigate_rsa_partial_bits", ROOT / "src" / "investigate_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def long_to_bytes(value: int) -> bytes:
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def parse_root_value(root: dict, key):
    if key in root:
        return root[key]
    key_text = str(key)
    if key_text in root:
        return root[key_text]
    return None


def install_cuso_shift_cap(max_shifts: int | None, shift_window: tuple[int, int] | None) -> None:
    if max_shifts is None and shift_window is None:
        return
    if max_shifts is not None and max_shifts <= 0:
        raise ValueError("--max-shifts must be positive")
    if shift_window is not None:
        offset, size = shift_window
        if offset < 0 or size <= 0:
            raise ValueError("--shift-window must be OFFSET:SIZE with OFFSET >= 0 and SIZE > 0")

    from cuso.data import RelationSet
    from cuso.strategy.shift_polynomial_selection.optimal import OptimalShiftPolys

    patch_key = (max_shifts, shift_window)
    if getattr(OptimalShiftPolys, "_cryptotest_shift_cap", None) == patch_key:
        return

    original = OptimalShiftPolys._get_shift_polys_for_ideal

    def capped_get_shift_polys_for_ideal(self, ideal, ideal_inf, bounds):
        for shift_polys in original(self, ideal, ideal_inf, bounds):
            if shift_window is not None:
                offset, size = shift_window
                if len(shift_polys) <= offset:
                    continue
                windowed = list(shift_polys)[offset : offset + size]
                self.logger.info(
                    "Using shift polynomial window offset=%u size=%u from %u relation(s)",
                    offset,
                    len(windowed),
                    len(shift_polys),
                )
                yield RelationSet(windowed)
                if len(windowed) >= size:
                    return
                continue
            if max_shifts is not None and len(shift_polys) > max_shifts:
                self.logger.info(
                    "Capping shift polynomial probe at %u of %u relation(s)",
                    max_shifts,
                    len(shift_polys),
                )
                yield RelationSet(list(shift_polys)[:max_shifts])
                return
            yield shift_polys
            if max_shifts is not None and len(shift_polys) >= max_shifts:
                self.logger.info(
                    "Stopping shift polynomial probe at %u relation(s)", max_shifts
                )
                return

    OptimalShiftPolys._get_shift_polys_for_ideal = capped_get_shift_polys_for_ideal
    OptimalShiftPolys._cryptotest_shift_cap = patch_key


def install_cuso_multiplicity_cap(max_multiplicity: int | None) -> None:
    if max_multiplicity is None:
        return
    if max_multiplicity <= 0:
        raise ValueError("--max-multiplicity must be positive")

    from cuso.strategy.ideal_selection.ideal_selection import RelationIdealGenerator

    if getattr(RelationIdealGenerator, "_cryptotest_multiplicity_cap", None) == max_multiplicity:
        return

    original = RelationIdealGenerator.run

    def capped_run(self, relations, bounds):
        for count, ideals in enumerate(original(self, relations, bounds), start=1):
            if count > max_multiplicity:
                self.logger.info(
                    "Stopping ideal generation after %u multiplicity level(s)",
                    max_multiplicity,
                )
                return
            yield ideals

    RelationIdealGenerator.run = capped_run
    RelationIdealGenerator._cryptotest_multiplicity_cap = max_multiplicity


def install_cuso_recenter_patch(disable_recenter: bool) -> None:
    if not disable_recenter:
        return

    from cuso.strategy.problem_converter.chain import ChainConverter

    if getattr(ChainConverter, "_cryptotest_recenter_disabled", False):
        return

    original = ChainConverter.__init__

    def init_without_recenter(self, do_recentering=True, unrav_lin_relations=None):
        original(self, False, unrav_lin_relations)

    ChainConverter.__init__ = init_without_recenter
    ChainConverter._cryptotest_recenter_disabled = True


def install_cuso_weight_bias(small_weight_factor: float | None) -> None:
    if small_weight_factor is None or small_weight_factor == 1:
        return
    if small_weight_factor <= 0:
        raise ValueError("--small-weight-factor must be positive")

    from cuso.strategy.problem_converter.monom_ordering import (
        BoundedMonomialOrderConverter,
    )
    from cuso.strategy.shift_polynomial_selection.optimal import OptimalShiftPolys
    from cuso.utils import weighted_combinations

    if getattr(BoundedMonomialOrderConverter, "_cryptotest_small_weight_factor", None) == small_weight_factor:
        return

    small_bound_bits = 46.5

    def effective_log_bound(bounds, x):
        bound = bounds.get_abs_bound(x)
        weight = math.log2(bound) if bound > 1 else 1
        if weight <= small_bound_bits:
            weight *= small_weight_factor
        return max(1, weight)

    def get_new_ring_with_bias(self, orig_ring, orig_bounds):
        xs = orig_ring.gens()
        if len(xs) == 1:
            return orig_ring
        weights = [effective_log_bound(orig_bounds, x) for x in xs]
        order = TermOrder("wdeglex", tuple(weights))
        return PolynomialRing(ZZ, orig_ring.variable_names(), order=order)

    def get_monomial_set_with_bias(self, modulus, ring, ideal_inf, bounds):
        lg_bounds = [effective_log_bound(bounds, x) for x in ring.gens()]
        if modulus is None:
            inf_lms = []
            max_weight = float("inf")
        else:
            inf_lms = [g.lm() for g in ideal_inf.groebner_basis()]
            max_weight = math.log2(bounds.get_upper_bound(modulus))

        for exps, weight in weighted_combinations(lg_bounds):
            if weight >= max_weight:
                break

            monom = 1
            for xi, ei in zip(ring.gens(), exps):
                monom *= xi**ei

            for g_lm in inf_lms:
                if monom % g_lm == 0:
                    break
            else:
                yield monom

    BoundedMonomialOrderConverter._get_new_ring = get_new_ring_with_bias
    BoundedMonomialOrderConverter._cryptotest_small_weight_factor = small_weight_factor
    OptimalShiftPolys._get_monomial_set = get_monomial_set_with_bias
    OptimalShiftPolys._cryptotest_small_weight_factor = small_weight_factor


def install_cuso_graph_slack(slack_bits: float | None) -> None:
    if slack_bits is None:
        return

    from cuso.data import Relation, RelationSet
    from cuso.strategy.shift_polynomial_selection.graph import GraphShiftPolys

    if getattr(GraphShiftPolys, "_cryptotest_graph_slack_bits", None) == slack_bits:
        return

    def refine_shift_polys_with_slack(self, shift_polys, bounds):
        modulus = shift_polys[0].modulus
        polys = []
        for rel in shift_polys:
            if modulus != rel.modulus:
                raise ValueError("All shift polynomials must share the same modulus")
            polys.append(rel.polynomial)

        while True:
            refined = self._refine_once(polys, bounds)
            if refined is None:
                break
            polys = refined

        log_shvec_len = self._approx_shvec_bound(polys, bounds)
        log_mod = math.log2(bounds.get_lower_bound(modulus))
        self.logger.info(
            "Graph subset %u/%u: expected %.2f-bit vector vs %.2f-bit modulus, slack %.2f",
            len(polys),
            len(shift_polys),
            log_shvec_len,
            log_mod,
            slack_bits,
        )
        if log_shvec_len < log_mod + slack_bits:
            return RelationSet([Relation(poly, modulus) for poly in polys])
        return None

    GraphShiftPolys._refine_shift_polys = refine_shift_polys_with_slack
    GraphShiftPolys._cryptotest_graph_slack_bits = slack_bits


def install_flatter_args(flatter_args: str | None) -> None:
    if not flatter_args:
        return

    from cuso.strategy.lattice_reduction.flatter import Flatter

    parsed_args = tuple(shlex.split(flatter_args))
    if getattr(Flatter, "_cryptotest_flatter_args", None) == parsed_args:
        return

    def reduce_integer_basis_with_args(self, basis):
        proc = Popen(
            ["flatter", *parsed_args],
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
        )
        outs, errs = proc.communicate(self.lattice_to_str(basis).encode())
        if proc.returncode != 0:
            raise RuntimeError(errs.decode(errors="replace"))
        self.logger.info("Reduced lattice basis using flatter %s", " ".join(parsed_args))
        return self.lattice_from_str(outs.decode())

    Flatter.reduce_integer_basis = reduce_integer_basis_with_args
    Flatter._cryptotest_flatter_args = parsed_args


def decrypt(n: int, e: int, ct: int, p: int, q: int) -> bytes:
    phi = (p - 1) * (q - 1)
    d = int(inverse_mod(e, phi))
    m = pow(ct, d, n)
    assert pow(m, e, n) == ct
    return long_to_bytes(m)


def check_roots(roots, xs, f, n: int, e: int, ct: int, mask: int, known: int) -> bool:
    print(f"[+] cuso returned {len(roots)} candidate root(s)", flush=True)
    for root in roots:
        p_value = parse_root_value(root, "p")
        if p_value is not None:
            p = int(ZZ(p_value))
        else:
            subs = {}
            missing = []
            for x in xs:
                value = parse_root_value(root, x)
                if value is None:
                    missing.append(str(x))
                    continue
                subs[x] = ZZ(value)
            if missing:
                print(f"[+] partial root keys={list(root.keys())}, missing={missing}", flush=True)
                continue
            p = int(ZZ(f.subs(subs)))

        if not (1 < p < n):
            continue
        if n % p != 0:
            continue
        if (p & mask) != known:
            continue
        q = n // p
        assert p.bit_length() == 1024
        assert q.bit_length() == 1024
        plaintext = decrypt(n, e, ct, p, q)
        print("[+] FACTORED")
        print(f"p = {p:#x}")
        print(f"q = {q:#x}")
        print(f"plaintext bytes = {plaintext!r}")
        return True
    return False


def check_q_divisor_roots(
    roots,
    model,
    n: int,
    e: int,
    ct: int,
    mask: int,
    known: int,
) -> bool:
    print(f"[+] cuso returned {len(roots)} candidate root(s)", flush=True)
    for root in roots:
        q_value = parse_root_value(root, "p")
        if q_value is not None:
            q = int(ZZ(q_value))
        else:
            subs = {}
            missing = []
            for x in [model["z"], *model["low_gens"]]:
                value = parse_root_value(root, x)
                if value is None:
                    missing.append(str(x))
                    continue
                subs[x] = ZZ(value)
            if missing:
                print(f"[+] partial root keys={list(root.keys())}, missing={missing}", flush=True)
                continue
            q = int(
                ZZ(model["q_low"].subs(subs))
                + ZZ(model["q_high"])
                + ZZ(model["q_modulus"]) * ZZ(subs[model["z"]])
            )

        if not (1 < q < n):
            continue
        if n % q != 0:
            continue
        p = n // q
        if (p & mask) != known:
            continue
        assert p.bit_length() == 1024
        assert q.bit_length() == 1024
        plaintext = decrypt(n, e, ct, p, q)
        print("[+] FACTORED")
        print(f"p = {p:#x}")
        print(f"q = {q:#x}")
        print(f"plaintext bytes = {plaintext!r}")
        return True
    return False


def modulus_interval(known: int, ranges: list[tuple[int, int]]) -> tuple[int, int]:
    unknown_mask = 0
    for offset, width in ranges:
        unknown_mask |= ((1 << width) - 1) << offset
    return known, known | unknown_mask


def common_prefix_from_interval(lo: int, hi: int, bits: int = 1024) -> tuple[int, int, int]:
    if lo <= 0 or hi < lo:
        raise ValueError("invalid interval for common prefix")
    diff = lo ^ hi
    prefix_bits = bits if diff == 0 else max(0, bits - diff.bit_length())
    prefix_start = bits - prefix_bits
    prefix = lo >> prefix_start if prefix_bits else 0
    return prefix_bits, prefix, prefix_start


def ranges_to_mask(ranges: list[tuple[int, int]]) -> int:
    mask = 0
    for offset, width in ranges:
        mask |= ((1 << width) - 1) << offset
    return mask


def mask_to_ranges(mask: int) -> list[tuple[int, int]]:
    ranges = []
    bit = 0
    while bit < 1024:
        if ((mask >> bit) & 1) == 0:
            bit += 1
            continue
        start = bit
        while bit < 1024 and ((mask >> bit) & 1):
            bit += 1
        ranges.append((start, bit - start))
    return ranges


def apply_fixed_ranges(
    known: int,
    ranges: list[tuple[int, int]],
    fixed_ranges: list[tuple[int, int, int]],
) -> tuple[int, list[tuple[int, int]]]:
    unknown_mask = ranges_to_mask(ranges)
    known2 = known
    for start, width, value in fixed_ranges:
        fixed_mask = ((1 << width) - 1) << start
        fixed_bits = value << start
        if fixed_mask & ~unknown_mask:
            if ((known2 ^ fixed_bits) & fixed_mask & ~unknown_mask) != 0:
                raise ValueError(f"inconsistent fixed known bits at {start}:{width}")
        known2 &= ~fixed_mask
        known2 |= fixed_bits
        unknown_mask &= ~fixed_mask
    return known2, mask_to_ranges(unknown_mask)


def run_cuso(
    relations,
    bounds,
    n: int,
    modulus_min: int,
    modulus_max: int,
    graph: bool | None,
    intermediate: bool,
    partial: bool,
    max_shifts: int | None,
    shift_window: tuple[int, int] | None,
    max_multiplicity: int | None,
    disable_recenter: bool,
    small_weight_factor: float | None,
    graph_slack_bits: float | None,
    flatter_args: str | None,
):
    import cuso

    patch_cuso_boundset_for_sage109()
    install_cuso_recenter_patch(disable_recenter)
    install_cuso_weight_bias(small_weight_factor)
    install_cuso_graph_slack(graph_slack_bits)
    install_flatter_args(flatter_args)
    install_cuso_shift_cap(max_shifts, shift_window)
    install_cuso_multiplicity_cap(max_multiplicity)
    try:
        return cuso.find_small_roots(
            relations=relations,
            bounds=bounds,
            modulus="p",
            modulus_multiple=ZZ(n),
            modulus_lower_bound=ZZ(modulus_min - 1),
            modulus_upper_bound=ZZ(modulus_max + 1),
            use_graph_optimization=graph,
            use_intermediate_sizes=intermediate,
            allow_partial_solutions=partial,
        )
    except TypeError as exc:
        if "NoneType" in str(exc):
            return []
        raise


def build_relation(known: int, ranges: list[tuple[int, int]], prefix: str):
    xs = var(",".join(f"{prefix}{i}" for i in range(len(ranges))))
    if len(ranges) == 1:
        xs = (xs,)
    f = ZZ(known)
    bounds = {}
    for x, (offset, width) in zip(xs, ranges):
        f += (ZZ(1) << offset) * x
        bounds[x] = (ZZ(-1), ZZ(1) << width)
    return xs, f, bounds


def monomial_from_exp(ring, exponents):
    if isinstance(exponents, int):
        exponents = (exponents,)
    monomial = ring(1)
    for gen, exponent in zip(ring.gens(), exponents):
        if exponent:
            monomial *= gen**exponent
    return monomial


def reduce_coefficients(poly, modulus: int, centered: bool):
    ring = poly.parent()
    out = ring(0)
    half = modulus // 2
    for exponents, coefficient in poly.dict().items():
        value = int(coefficient) % modulus
        if centered and value > half:
            value -= modulus
        if value:
            out += ring(value) * monomial_from_exp(ring, exponents)
    return out


def build_q_low_polynomial(
    n: int,
    known: int,
    ranges: list[tuple[int, int]],
    low_bits: int,
):
    if low_bits <= 0:
        raise ValueError("low_bits must be positive")
    low_ranges = []
    for offset, width in ranges:
        if offset >= low_bits:
            continue
        if offset + width > low_bits:
            raise ValueError(f"range {offset}:{width} crosses q-divisor low_bits={low_bits}")
        low_ranges.append((offset, width))
    if not low_ranges:
        raise ValueError("q-divisor mode needs at least one low p variable")

    names = [f"u{i}" for i in range(len(low_ranges))]
    ring = PolynomialRing(ZZ, names)
    gens = ring.gens()
    modulus = ZZ(1) << low_bits
    p0 = ZZ(known & (int(modulus) - 1))
    if math.gcd(int(p0), int(modulus)) != 1:
        raise ValueError("known low p part must be odd")
    delta = ring(0)
    bounds = {}
    min_offset = low_bits
    for gen, (offset, width) in zip(gens, low_ranges):
        delta += ring(ZZ(1) << offset) * gen
        bounds[gen] = (ZZ(-1), ZZ(1) << width)
        min_offset = min(min_offset, offset)

    inv_p0 = ZZ(inverse_mod(p0, modulus))
    term = ring(1)
    inv_series = ring(0)
    max_degree = (low_bits - 1) // min_offset
    scale = ring(-inv_p0) * delta
    for _ in range(max_degree + 1):
        inv_series += term
        term *= scale
    q_low = ring(ZZ(n) % modulus) * ring(inv_p0) * inv_series
    return low_ranges, gens, reduce_coefficients(q_low, int(modulus), centered=False), bounds


def build_q_divisor_relation(
    n: int,
    known: int,
    ranges: list[tuple[int, int]],
    low_bits: int,
    z_bits: int | None,
    monic: bool,
    z_nonnegative: bool,
):
    low_ranges, low_gens, q_low, low_bounds = build_q_low_polynomial(n, known, ranges, low_bits)
    q_modulus = ZZ(1) << low_bits
    p_min, p_max = modulus_interval(known, ranges)
    q_min = n // p_max
    q_max = n // p_min
    prefix_bits, q_prefix, prefix_start = common_prefix_from_interval(q_min, q_max, bits=1024)
    if prefix_start < low_bits:
        raise ValueError("q high prefix overlaps q low part")
    gap_bits = prefix_start - low_bits
    z_bound_bits = z_bits if z_bits is not None else gap_bits + 2

    names = ["z", *[str(gen) for gen in low_gens]]
    ring = PolynomialRing(ZZ, names)
    z = ring.gen(0)
    q_low_ring = ring(q_low)
    high = ZZ(q_prefix) << prefix_start
    if monic:
        inv_low_mod = ZZ(inverse_mod(q_modulus % ZZ(n), ZZ(n)))
        f = z + reduce_coefficients(ring(inv_low_mod) * (q_low_ring + ring(high)), n, centered=True)
    else:
        f = q_low_ring + ring(high) + ring(q_modulus) * z

    bounds = {z: (ZZ(-1), ZZ(1) << gap_bits) if z_nonnegative else (-(ZZ(1) << z_bound_bits), ZZ(1) << z_bound_bits)}
    for gen, bound in zip(ring.gens()[1:], low_bounds.values()):
        bounds[gen] = bound

    return {
        "relation": f,
        "bounds": bounds,
        "z": z,
        "low_gens": ring.gens()[1:],
        "q_low": q_low_ring,
        "q_high": int(high),
        "q_modulus": int(q_modulus),
        "q_min": int(q_min),
        "q_max": int(q_max),
        "q_prefix_bits": prefix_bits,
        "q_prefix_start": prefix_start,
        "q_gap_bits": gap_bits,
        "q_z_bound_bits": z_bound_bits,
        "q_low_ranges": low_ranges,
        "monic": monic,
    }


def solve_once(
    n: int,
    e: int,
    ct: int,
    mask: int,
    known: int,
    graph: bool | None,
    intermediate: bool,
    partial: bool,
    max_shifts: int | None,
    shift_window: tuple[int, int] | None,
    max_multiplicity: int | None,
    disable_recenter: bool,
    small_weight_factor: float | None,
    graph_slack_bits: float | None,
    flatter_args: str | None,
    fixed_ranges: list[tuple[int, int, int]],
) -> bool:
    known2, ranges = apply_fixed_ranges(known, UNKNOWN_RANGES, fixed_ranges)
    xs, f, bounds = build_relation(known2, ranges, "x")
    modulus_min, modulus_max = modulus_interval(known2, ranges)
    print("[+] single 8-variable cuso attempt")
    print("[+] bounds bits:", [width for _, width in ranges], flush=True)
    print(f"[+] p interval bits: min={modulus_min.bit_length()}, max={modulus_max.bit_length()}", flush=True)
    started = time.time()
    roots = run_cuso(
        [f],
        bounds,
        n,
        modulus_min,
        modulus_max,
        graph,
        intermediate,
        partial,
        max_shifts,
        shift_window,
        max_multiplicity,
        disable_recenter,
        small_weight_factor,
        graph_slack_bits,
        flatter_args,
    )
    print(f"[+] cuso elapsed {time.time() - started:.2f}s", flush=True)
    return check_roots(roots, xs, f, n, e, ct, mask, known)


def solve_q_divisor(
    n: int,
    e: int,
    ct: int,
    mask: int,
    known: int,
    graph: bool | None,
    intermediate: bool,
    partial: bool,
    max_shifts: int | None,
    shift_window: tuple[int, int] | None,
    max_multiplicity: int | None,
    disable_recenter: bool,
    small_weight_factor: float | None,
    graph_slack_bits: float | None,
    flatter_args: str | None,
    fixed_ranges: list[tuple[int, int, int]],
    low_bits: int,
    z_bits: int | None,
    monic: bool,
    z_nonnegative: bool,
    branch: bool,
    branch_mode: str,
    branch_low: int | None,
    branch_high: int | None,
    max_branches: int | None,
) -> bool:
    if branch:
        if branch_mode == "both":
            low_values = range(16) if branch_low is None else [branch_low]
            high_values = range(16) if branch_high is None else [branch_high]
        elif branch_mode == "low":
            low_values = range(16) if branch_low is None else [branch_low]
            high_values = [None]
        elif branch_mode == "high":
            low_values = [None]
            high_values = range(16) if branch_high is None else [branch_high]
        else:
            raise ValueError(f"unsupported branch mode: {branch_mode}")
    else:
        low_values = [None]
        high_values = [None]

    checked = 0
    for low in low_values:
        for high in high_values:
            if max_branches is not None and checked >= max_branches:
                print(f"[-] Stopped after {checked} q-divisor branch(es).")
                return False
            checked += 1
            branch_fixed_ranges = list(fixed_ranges)
            label_parts = []
            if low is not None:
                branch_fixed_ranges.append((150, 4, low))
                label_parts.append(f"p[150..153]={low:x}")
            if high is not None:
                branch_fixed_ranges.append((920, 4, high))
                label_parts.append(f"p[920..923]={high:x}")
            if label_parts:
                print(f"[+] q-divisor branch {', '.join(label_parts)}", flush=True)

            known2, ranges = apply_fixed_ranges(known, UNKNOWN_RANGES, branch_fixed_ranges)
            model = build_q_divisor_relation(
                n,
                known2,
                ranges,
                low_bits=low_bits,
                z_bits=z_bits,
                monic=monic,
                z_nonnegative=z_nonnegative,
            )
            print("[+] q-divisor cuso attempt")
            print("[+] q-low p ranges:", ", ".join(f"{start}:{width}" for start, width in model["q_low_ranges"]), flush=True)
            print(
                "[+] q prefix/gap:",
                f"prefix_bits={model['q_prefix_bits']}",
                f"prefix_start={model['q_prefix_start']}",
                f"gap_bits={model['q_gap_bits']}",
                f"z_bound_bits={model['q_z_bound_bits']}",
                f"monic={model['monic']}",
                flush=True,
            )
            print(
                f"[+] q interval bits: min={model['q_min'].bit_length()}, max={model['q_max'].bit_length()}",
                flush=True,
            )
            print(
                f"[+] q relation terms={len(model['relation'].dict())}, degree={model['relation'].degree()}",
                flush=True,
            )
            started = time.time()
            try:
                roots = run_cuso(
                    [model["relation"]],
                    model["bounds"],
                    n,
                    model["q_min"],
                    model["q_max"],
                    graph,
                    intermediate,
                    partial,
                    max_shifts,
                    shift_window,
                    max_multiplicity,
                    disable_recenter,
                    small_weight_factor,
                    graph_slack_bits,
                    flatter_args,
                )
            except Exception as exc:
                print(f"[!] q-divisor branch failed: {type(exc).__name__}: {exc}", flush=True)
                continue
            print(f"[+] cuso elapsed {time.time() - started:.2f}s", flush=True)
            if check_q_divisor_roots(roots, model, n, e, ct, mask, known):
                return True
    return False


def solve_branches(
    n: int,
    e: int,
    ct: int,
    mask: int,
    known: int,
    graph: bool | None,
    intermediate: bool,
    partial: bool,
    branch_low: int | None,
    branch_high: int | None,
    max_branches: int | None,
    max_shifts: int | None,
    shift_window: tuple[int, int] | None,
    max_multiplicity: int | None,
    branch_mode: str,
    disable_recenter: bool,
    small_weight_factor: float | None,
    graph_slack_bits: float | None,
    flatter_args: str | None,
    fixed_ranges: list[tuple[int, int, int]],
) -> bool:
    if branch_mode == "both":
        low_values = range(16) if branch_low is None else [branch_low]
        high_values = range(16) if branch_high is None else [branch_high]
    elif branch_mode == "low":
        low_values = range(16) if branch_low is None else [branch_low]
        high_values = [None]
    elif branch_mode == "high":
        low_values = [None]
        high_values = range(16) if branch_high is None else [branch_high]
    else:
        raise ValueError(f"unsupported branch mode: {branch_mode}")

    checked = 0
    for low in low_values:
        for high in high_values:
            if max_branches is not None and checked >= max_branches:
                print(f"[-] Stopped after {checked} branch(es).")
                return False
            checked += 1
            branch_fixed_ranges = list(fixed_ranges)
            label_parts = []
            if low is not None:
                branch_fixed_ranges.append((150, 4, low))
                label_parts.append(f"x0={low:x}")
            if high is not None:
                branch_fixed_ranges.append((920, 4, high))
                label_parts.append(f"x7={high:x}")
            known2, ranges = apply_fixed_ranges(known, UNKNOWN_RANGES, branch_fixed_ranges)
            xs, f, bounds = build_relation(known2, ranges, "y")
            modulus_min, modulus_max = modulus_interval(known2, ranges)
            print(f"[+] branch {', '.join(label_parts)}", flush=True)
            started = time.time()
            try:
                roots = run_cuso(
                    [f],
                    bounds,
                    n,
                    modulus_min,
                    modulus_max,
                    graph,
                    intermediate,
                    partial,
                    max_shifts,
                    shift_window,
                    max_multiplicity,
                    disable_recenter,
                    small_weight_factor,
                    graph_slack_bits,
                    flatter_args,
                )
            except Exception as exc:
                print(f"[!] branch failed: {type(exc).__name__}: {exc}", flush=True)
                continue
            print(f"[+] branch elapsed {time.time() - started:.2f}s", flush=True)
            if check_roots(roots, xs, f, n, e, ct, mask, known):
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--branch", action="store_true", help="branch over x0 and x7")
    parser.add_argument(
        "--q-divisor",
        action="store_true",
        help="derive q low bits from p mod 2^L and run cuso on q | N",
    )
    parser.add_argument(
        "--branch-mode",
        choices=["both", "low", "high"],
        default="both",
        help="branch over both 4-bit ends, only x0, or only x7",
    )
    parser.add_argument("--branch-low", type=lambda x: int(x, 0), help="only run this x0 branch")
    parser.add_argument("--branch-high", type=lambda x: int(x, 0), help="only run this x7 branch")
    parser.add_argument("--max-branches", type=int, help="stop after this many branches")
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_bit_range_value,
        help="fix p bit range START:WIDTH:VALUE before building cuso variables",
    )
    parser.add_argument("--cuso-src", type=Path, default=DEFAULT_CUSO_SRC)
    parser.add_argument("--no-graph", action="store_true", help="disable graph shift optimization")
    parser.add_argument("--no-intermediate", action="store_true", help="disable intermediate shift-set sizes")
    parser.add_argument("--partial", action="store_true", help="allow cuso to return partial solutions")
    parser.add_argument(
        "--max-shifts",
        type=int,
        help="cap cuso's optimal shift-polynomial probe for quick branch sweeps",
    )
    parser.add_argument(
        "--shift-window",
        help="use a shift-polynomial window OFFSET:SIZE instead of the first --max-shifts candidates",
    )
    parser.add_argument(
        "--max-multiplicity",
        type=int,
        help="stop cuso after this many generated relation ideal multiplicity levels",
    )
    parser.add_argument("--debug", action="store_true", help="show cuso debug logs")
    parser.add_argument(
        "--disable-recenter",
        action="store_true",
        help="keep original bit-slice variables instead of cuso's centered variables",
    )
    parser.add_argument(
        "--small-weight-factor",
        type=float,
        help="multiply monomial-order weights for small variables by this factor",
    )
    parser.add_argument(
        "--graph-slack-bits",
        type=float,
        help="allow graph subsets whose expected vector length is this many bits above p",
    )
    parser.add_argument(
        "--flatter-args",
        help='extra flatter arguments, e.g. "--delta 0.999" or "-rhf 1.01"',
    )
    parser.add_argument(
        "--qdiv-low-bits",
        type=int,
        default=600,
        help="number of low q bits derived from p, default matches the first high unknown p block",
    )
    parser.add_argument(
        "--qdiv-z-bits",
        type=int,
        help="signed z carry bound bit size; default is q middle gap bits plus 2",
    )
    parser.add_argument(
        "--qdiv-non-monic",
        action="store_true",
        help="use q_low + 2^L*z + q_high instead of the monic normalized relation",
    )
    parser.add_argument(
        "--qdiv-z-nonnegative",
        action="store_true",
        help="bound z as the nonnegative q middle gap instead of a signed carry",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    maybe_add_cuso_path(args.cuso_src)
    c7 = load_constants()
    shift_window = None
    if args.shift_window:
        try:
            offset_text, size_text = args.shift_window.split(":", 1)
            shift_window = (int(offset_text, 0), int(size_text, 0))
        except ValueError as exc:
            raise SystemExit("--shift-window must be OFFSET:SIZE") from exc
        if args.max_shifts is not None:
            raise SystemExit("--shift-window and --max-shifts are mutually exclusive")
    n = int(c7.N_HEX.replace(" ", ""), 16)
    e = int(c7.E)
    ct = int(c7.CT_HEX.replace(" ", ""), 16)
    mask = int(c7.MASK_HEX.replace(" ", ""), 16)
    known = int(c7.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    graph = False if args.no_graph else None
    intermediate = not args.no_intermediate

    if args.q_divisor:
        solved = solve_q_divisor(
            n,
            e,
            ct,
            mask,
            known,
            graph,
            intermediate,
            args.partial,
            args.max_shifts,
            shift_window,
            args.max_multiplicity,
            args.disable_recenter,
            args.small_weight_factor,
            args.graph_slack_bits,
            args.flatter_args,
            args.fix_p_range,
            args.qdiv_low_bits,
            args.qdiv_z_bits,
            not args.qdiv_non_monic,
            args.qdiv_z_nonnegative,
            args.branch,
            args.branch_mode,
            args.branch_low,
            args.branch_high,
            args.max_branches,
        )
    elif args.branch:
        solved = solve_branches(
            n,
            e,
            ct,
            mask,
            known,
            graph,
            intermediate,
            args.partial,
            args.branch_low,
            args.branch_high,
            args.max_branches,
            args.max_shifts,
            shift_window,
            args.max_multiplicity,
            args.branch_mode,
            args.disable_recenter,
            args.small_weight_factor,
            args.graph_slack_bits,
            args.flatter_args,
            args.fix_p_range,
        )
    else:
        solved = solve_once(
            n,
            e,
            ct,
            mask,
            known,
            graph,
            intermediate,
            args.partial,
            args.max_shifts,
            shift_window,
            args.max_multiplicity,
            args.disable_recenter,
            args.small_weight_factor,
            args.graph_slack_bits,
            args.flatter_args,
            args.fix_p_range,
        )
    if not solved:
        print("[-] No valid factor found.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
