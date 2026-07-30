#!/usr/bin/env python3
"""Hybrid folded Coron attempt for challenge 7.

This keeps the successful folded p/q idea, but branches on the top bits of
the p[784..829] unknown run so the p high boundary moves downward.  The goal is
to push the bivariate integer-root instance just inside Coron's bound.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import time
from pathlib import Path

from sage.all import PolynomialRing, ZZ, gcd, inverse_mod, matrix, pari


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CRYPTO_ATTACKS = Path("/tmp/crypto-attacks")
P_BITS = 1024
LOW_BITS = 210
X0_OFFSET = 150
X1_OFFSET = 210
X1_WIDTH = 39
X7_OFFSET = 920
X6_TOP_END = 830


def load_constants():
    spec = importlib.util.spec_from_file_location(
        "investigate_rsa_partial_bits", ROOT / "src" / "investigate_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_range_list(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_text, hi_text = part.split("-", 1)
            lo = int(lo_text, 0)
            hi = int(hi_text, 0)
            values.extend(range(lo, hi + 1))
        else:
            values.append(int(part, 0))
    return values


def parse_bit_range_value(text: str) -> tuple[int, int, int]:
    try:
        start_text, width_text, value_text = text.split(":", 2)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH:VALUE") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    value = int(value_text, 0)
    if start < 0 or width <= 0 or value < 0 or value >= (1 << width):
        raise argparse.ArgumentTypeError("invalid START:WIDTH:VALUE")
    return start, width, value


def int_to_bytes(value: int) -> bytes:
    return int(value).to_bytes((int(value).bit_length() + 7) // 8, "big")


def common_prefix_from_interval(lo: int, hi: int, bits: int = P_BITS) -> tuple[int, int, int]:
    lo = int(lo)
    hi = int(hi)
    if lo > hi:
        lo, hi = hi, lo
    diff = lo ^ hi
    prefix_len = bits if diff == 0 else bits - diff.bit_length()
    suffix_start = bits - prefix_len
    return prefix_len, lo >> suffix_start, suffix_start


def weighted_norm_bits(poly, x_bound: int, y_bound: int) -> int:
    x_bits = int(x_bound).bit_length() - 1
    y_bits = int(y_bound).bit_length() - 1
    best = 0
    for (i, j), coeff in poly.dict().items():
        coeff = ZZ(coeff)
        if coeff == 0:
            continue
        best = max(best, abs(coeff).nbits() + i * x_bits + j * y_bits)
    return best


def build_branch(
    ring,
    n: int,
    mask: int,
    known: int,
    unknown_mask: int,
    x0_value: int,
    x1_value: int | None,
    x7_value: int,
    x6_top_value: int,
    x6_top_bits: int,
    q_fixed_range: tuple[int, int, int] | None,
    fixed_p_ranges: list[tuple[int, int, int]],
):
    x, y = ring.gens()
    p_hi_start = X6_TOP_END - x6_top_bits

    fixed = ZZ(known)
    fixed |= ZZ(x0_value) << X0_OFFSET
    fixed |= ZZ(x7_value) << X7_OFFSET
    fixed |= ZZ(x6_top_value) << p_hi_start
    if x1_value is not None:
        fixed |= ZZ(x1_value) << X1_OFFSET

    guessed_mask = ZZ(0)
    guessed_mask |= (ZZ(2**4 - 1)) << X0_OFFSET
    guessed_mask |= (ZZ(2**4 - 1)) << X7_OFFSET
    guessed_mask |= (ZZ(2**x6_top_bits - 1)) << p_hi_start
    if x1_value is not None:
        guessed_mask |= (ZZ(2**X1_WIDTH - 1)) << X1_OFFSET
    for fixed_start, fixed_width, fixed_value in fixed_p_ranges:
        fixed_mask = (ZZ(2**fixed_width - 1)) << fixed_start
        fixed_bits = ZZ(fixed_value) << fixed_start
        overlap = (ZZ(mask) | guessed_mask) & fixed_mask
        if ((fixed ^ fixed_bits) & overlap) != 0:
            return None
        fixed |= fixed_bits
        guessed_mask |= fixed_mask

    full_mask = (ZZ(1) << P_BITS) - 1
    remaining_mask = ZZ(unknown_mask) & (full_mask ^ guessed_mask)
    if remaining_mask:
        low_bits = int((remaining_mask & -remaining_mask).nbits() - 1)
        high_start = int(remaining_mask.nbits())
    else:
        low_bits = P_BITS
        high_start = 0
    p_min = fixed
    p_max = fixed | remaining_mask
    if p_min <= 0 or p_max <= 0:
        return None

    q_min = ZZ(n) // p_max
    q_max = ZZ(n) // p_min
    q_prefix_bits, q_high, q_high_start = common_prefix_from_interval(q_min, q_max)
    if q_high_start <= low_bits:
        return None
    if q_fixed_range is not None:
        q_fixed_start, q_fixed_width, q_fixed_value = q_fixed_range
        q_fixed_end = q_fixed_start + q_fixed_width
        if q_fixed_end < q_high_start:
            return None
        if q_fixed_start < q_high_start:
            extra_width = q_high_start - q_fixed_start
            overlap_width = q_fixed_end - q_high_start
            if overlap_width > 0:
                overlap_value = q_fixed_value >> extra_width
                if overlap_value != (q_high & ((ZZ(1) << overlap_width) - 1)):
                    return None
            q_high = (ZZ(q_high) << extra_width) | (q_fixed_value & ((ZZ(1) << extra_width) - 1))
            q_high_start = q_fixed_start
            q_prefix_bits = P_BITS - q_high_start
        else:
            known_shift = q_fixed_start - q_high_start
            if ((ZZ(q_high) >> known_shift) & ((ZZ(1) << q_fixed_width) - 1)) != q_fixed_value:
                return None

    p_low = fixed & (ZZ(2**low_bits - 1))
    if gcd(p_low, ZZ(1) << low_bits) != 1:
        return None

    q_low = (ZZ(n) * inverse_mod(p_low, ZZ(1) << low_bits)) % (ZZ(1) << low_bits)
    p_high = fixed >> high_start if high_start else ZZ(0)
    x_bound = ZZ(1) << (high_start - low_bits)
    y_bound = ZZ(1) << (q_high_start - low_bits)

    p_expr = ZZ(p_low) + (ZZ(1) << low_bits) * x + (ZZ(p_high) << high_start)
    q_expr = ZZ(q_low) + (ZZ(1) << low_bits) * y + (ZZ(q_high) << q_high_start)
    poly = ring(p_expr * q_expr - ZZ(n))
    content = ZZ(0)
    for coeff in poly.dict().values():
        content = gcd(content, abs(ZZ(coeff)))
    if content:
        primitive_poly = ring(0)
        for monomial, coeff in poly.dict().items():
            term = ZZ(coeff) // content
            for gen, exponent in zip(ring.gens(), monomial):
                term *= gen**exponent
            primitive_poly += term
    else:
        primitive_poly = poly

    raw_norm_bits = weighted_norm_bits(poly, x_bound, y_bound)
    primitive_norm_bits = weighted_norm_bits(primitive_poly, x_bound, y_bound)
    xy_bits = (x_bound.nbits() - 1) + (y_bound.nbits() - 1)
    raw_margin = (2.0 * raw_norm_bits / 3.0) - xy_bits
    primitive_margin = (2.0 * primitive_norm_bits / 3.0) - xy_bits

    return {
        "poly": poly,
        "p_low": p_low,
        "p_high": p_high,
        "p_hi_start": high_start,
        "low_bits": low_bits,
        "x1_fixed": x1_value is not None,
        "x_bound": x_bound,
        "y_bound": y_bound,
        "q_prefix_bits": q_prefix_bits,
        "q_high_start": q_high_start,
        "content_bits": content.nbits() - 1 if content else 0,
        "content_v2": content.valuation(2) if content else 0,
        "raw_norm_bits": raw_norm_bits,
        "primitive_norm_bits": primitive_norm_bits,
        "xy_bits": xy_bits,
        "raw_margin": raw_margin,
        "primitive_margin": primitive_margin,
        "norm_bits": primitive_norm_bits,
        "margin": primitive_margin,
    }


def validate_and_print(n: int, e: int, ct: int, mask: int, known: int, p: int) -> bool:
    p = int(p)
    if not (1 < p < n):
        return False
    if n % p != 0:
        return False
    if (p & mask) != known:
        return False
    q = n // p
    if p.bit_length() != 1024 or q.bit_length() != 1024:
        return False
    phi = (p - 1) * (q - 1)
    d = int(inverse_mod(e, phi))
    m = pow(ct, d, n)
    assert pow(m, e, n) == ct
    print("[+] FACTORED")
    print(f"p = {p:#x}")
    print(f"q = {q:#x}")
    print(f"[+] plaintext int = {m:#x}")
    print(f"[+] plaintext bytes = {int_to_bytes(m)!r}")
    return True


def branch_values(selected: int | None, width: int):
    if selected is None:
        return range(1 << width)
    return [selected]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crypto-attacks", type=Path, default=DEFAULT_CRYPTO_ATTACKS)
    parser.add_argument("--s-values", default="6", help="comma/range list, e.g. 6,7,8")
    parser.add_argument("--k-values", default="6-8", help="comma/range list, e.g. 6-9")
    parser.add_argument("--branch-low", type=lambda x: int(x, 0), help="fixed x0 nibble")
    parser.add_argument("--x1-value", type=lambda x: int(x, 0), help="fixed full x1 value p[210..248]")
    parser.add_argument("--branch-high", type=lambda x: int(x, 0), help="fixed x7 nibble")
    parser.add_argument("--x6-top", type=lambda x: int(x, 0), help="fixed x6 top value for each s")
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_bit_range_value,
        help="additional fixed p bit range START:WIDTH:VALUE",
    )
    parser.add_argument(
        "--q-fixed-range",
        type=parse_bit_range_value,
        help="fix a q bit range as START:WIDTH:VALUE when it touches the high prefix",
    )
    parser.add_argument(
        "--q-fixed-values",
        help="comma/range list overriding the VALUE part of --q-fixed-range, e.g. 0x00-0xff",
    )
    parser.add_argument(
        "--q-fixed-sweep",
        action="store_true",
        help="try every value for the width specified by --q-fixed-range",
    )
    parser.add_argument("--margin-min", type=float, default=-2.0)
    parser.add_argument("--max-branches", type=int, help="maximum branches to inspect")
    parser.add_argument("--max-coron-branches", type=int, help="maximum branches to run Coron on")
    parser.add_argument("--diagnose-only", action="store_true")
    parser.add_argument("--echelon-algorithm", default="flint")
    parser.add_argument(
        "--projected-coron",
        action="store_true",
        help="use a projected right-block Coron lattice to avoid the full rectangular HNF",
    )
    parser.add_argument(
        "--projected-lll-algorithm",
        help="optional Sage LLL algorithm for --projected-coron, e.g. fpLLL:proved",
    )
    parser.add_argument("--projected-lll-delta", type=float, default=0.8)
    parser.add_argument("--pari-stack-gb", type=int, default=0, help="increase PARI stack before Coron calls")
    parser.add_argument("--roots-method", default="groebner", choices=["groebner", "resultants", "variety"])
    parser.add_argument("--log-every", type=int, default=1000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if args.x1_value is not None and not (0 <= args.x1_value < (1 << X1_WIDTH)):
        raise SystemExit("--x1-value must fit 39 bits")

    if not args.crypto_attacks.exists():
        raise SystemExit(f"{args.crypto_attacks} does not exist")
    sys.path.insert(0, str(args.crypto_attacks))

    from shared import small_roots as small_roots_module
    from shared.small_roots import coron_direct

    original_find_roots_resultants = small_roots_module.find_roots_resultants

    def safe_find_roots_resultants(gens, polynomials):
        if len(polynomials) < len(gens):
            return
        yield from original_find_roots_resultants(gens, polynomials)

    small_roots_module.find_roots_resultants = safe_find_roots_resultants

    if args.projected_coron:
        small_roots = small_roots_module
        from shared.polynomial import max_norm

        def projected_integer_bivariate(p, k, X, Y, echelon_algorithm="default", roots_method="groebner"):
            pr = p.parent()
            x, y = pr.gens()
            delta = max(p.degrees())
            (i0, j0), _ = max_norm(p(x * X, y * Y))

            logging.debug("Calculating n for projected Coron...")
            s_matrix = matrix(ZZ, k**2, k**2)
            for a in range(k):
                for b in range(k):
                    shifted = x**a * y**b * p
                    for i in range(k):
                        for j in range(k):
                            s_matrix[a * k + b, i * k + j] = shifted.coefficient([i0 + i, j0 + j])
            n_det = abs(s_matrix.det())
            logging.debug("Found projected n with %s bits", n_det.nbits())

            left_monomials = []
            right_monomials = []
            for i in range(k + delta):
                for j in range(k + delta):
                    monomial = x**i * y**j
                    if 0 <= i - i0 < k and 0 <= j - j0 < k:
                        left_monomials.append(monomial)
                    else:
                        right_monomials.append(monomial)

            logging.debug(
                "Building projected Coron matrix with left=%u right=%u",
                len(left_monomials),
                len(right_monomials),
            )
            t_matrix = matrix(ZZ, k**2, len(right_monomials))
            for a in range(k):
                for b in range(k):
                    shifted = x**a * y**b * p
                    for col, monomial in enumerate(right_monomials):
                        t_matrix[a * k + b, col] = shifted.monomial_coefficient(monomial) * monomial(X, Y)

            projected = s_matrix.adjugate() * t_matrix
            reduced_input = matrix(ZZ, k**2 + len(right_monomials), len(right_monomials))
            reduced_input[: k**2, :] = projected
            for col, monomial in enumerate(right_monomials):
                reduced_input[k**2 + col, col] = n_det * monomial(X, Y)

            logging.debug(
                "Generating projected Echelon form (%u x %u)...",
                reduced_input.nrows(),
                reduced_input.ncols(),
            )
            l2 = reduced_input.echelon_form(algorithm=echelon_algorithm)
            l2 = l2.submatrix(0, 0, len(right_monomials))
            logging.debug("Reducing projected sublattice %u x %u...", l2.nrows(), l2.ncols())
            if args.projected_lll_algorithm:
                l2 = l2.LLL(delta=args.projected_lll_delta, algorithm=args.projected_lll_algorithm)
            else:
                l2 = l2.LLL(args.projected_lll_delta)
            polynomials = small_roots.reconstruct_polynomials(l2, p, n_det, right_monomials, [X, Y])
            for roots in small_roots.find_roots(pr, [p] + polynomials, method=roots_method):
                yield roots[x], roots[y]

        coron_direct.integer_bivariate = projected_integer_bivariate

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.pari_stack_gb > 0:
        pari.allocatemem(args.pari_stack_gb * 1024**3)

    c7 = load_constants()
    n = int(c7.N_HEX.replace(" ", ""), 16)
    e = int(c7.E)
    ct = int(c7.CT_HEX.replace(" ", ""), 16)
    mask = int(c7.MASK_HEX.replace(" ", ""), 16)
    known = int(c7.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    unknown_mask = ((1 << P_BITS) - 1) ^ mask

    ring = PolynomialRing(ZZ, names=("x", "y"))
    inspected = 0
    coron_branches = 0
    skipped_by_margin = 0
    margin_min = float("inf")
    margin_max = float("-inf")
    best_branch = None
    started = time.time()
    q_fixed_ranges = [None]
    if args.q_fixed_range is not None:
        q_start, q_width, q_value = args.q_fixed_range
        if args.q_fixed_sweep:
            q_values = range(1 << q_width)
        elif args.q_fixed_values:
            q_values = parse_range_list(args.q_fixed_values)
        else:
            q_values = [q_value]
        q_fixed_ranges = []
        for candidate_value in q_values:
            if not (0 <= candidate_value < (1 << q_width)):
                raise SystemExit("q fixed value outside selected width")
            q_fixed_ranges.append((q_start, q_width, candidate_value))

    for s in parse_range_list(args.s_values):
        if not (1 <= s <= 46):
            raise SystemExit("each s must be in 1..46")
        x6_values = branch_values(args.x6_top, s)
        x1_values = [args.x1_value]
        print(f"[+] Starting s={s}, k={parse_range_list(args.k_values)}", flush=True)
        for x0_value in branch_values(args.branch_low, 4):
            for x1_value in x1_values:
                for x7_value in branch_values(args.branch_high, 4):
                    for x6_top_value in x6_values:
                        for q_fixed_range in q_fixed_ranges:
                            if args.max_branches is not None and inspected >= args.max_branches:
                                print("[-] reached --max-branches", flush=True)
                                print(
                                    f"[+] inspected={inspected}, coron_branches={coron_branches}, "
                                    f"skipped_by_margin={skipped_by_margin}, margin_range=[{margin_min:.2f}, {margin_max:.2f}]",
                                    flush=True,
                                )
                                if best_branch:
                                    print(f"[+] best_branch={best_branch}", flush=True)
                                return 1

                            branch = build_branch(
                                ring,
                                n,
                                mask,
                                known,
                                unknown_mask,
                                x0_value,
                                x1_value,
                                x7_value,
                                x6_top_value,
                                s,
                                q_fixed_range,
                                args.fix_p_range,
                            )
                            inspected += 1
                            if branch is None:
                                continue
                            margin = branch["margin"]
                            margin_min = min(margin_min, margin)
                            margin_max = max(margin_max, margin)
                            if best_branch is None or margin > best_branch["margin"]:
                                best_branch = {
                                    "s": s,
                                    "x0": x0_value,
                                    "x1": x1_value,
                                    "x7": x7_value,
                                    "x6_top": x6_top_value,
                                    "q_fixed": q_fixed_range,
                                    "low_bits": branch["low_bits"],
                                    "p_hi_start": branch["p_hi_start"],
                                    "hq": branch["q_prefix_bits"],
                                    "x_bits": branch["x_bound"].nbits() - 1,
                                    "y_bits": branch["y_bound"].nbits() - 1,
                                    "w_raw": branch["raw_norm_bits"],
                                    "w_prim": branch["primitive_norm_bits"],
                                    "content_bits": branch["content_bits"],
                                    "content_v2": branch["content_v2"],
                                    "raw_margin": branch["raw_margin"],
                                    "primitive_margin": branch["primitive_margin"],
                                    "margin": margin,
                                }

                            if inspected == 1 or inspected % args.log_every == 0:
                                print(
                                    f"[branch] inspected={inspected} s={s} x0={x0_value:x} "
                                    f"x1={x1_value if x1_value is not None else None} "
                                    f"x7={x7_value:x} x6top={x6_top_value:x} "
                                    f"qfix={q_fixed_range} "
                                    f"low={branch['low_bits']} "
                                    f"p_hi={branch['p_hi_start']} "
                                    f"hq={branch['q_prefix_bits']} "
                                    f"Xbits={branch['x_bound'].nbits() - 1} "
                                    f"Ybits={branch['y_bound'].nbits() - 1} "
                                    f"Wraw={branch['raw_norm_bits']} "
                                    f"Wprim={branch['primitive_norm_bits']} "
                                    f"content_bits={branch['content_bits']} "
                                    f"v2={branch['content_v2']} "
                                    f"raw_margin={branch['raw_margin']:.2f} "
                                    f"primitive_margin={branch['primitive_margin']:.2f}",
                                    flush=True,
                                )

                            if args.diagnose_only:
                                continue
                            if margin < args.margin_min:
                                skipped_by_margin += 1
                                continue
                            if (
                                args.max_coron_branches is not None
                                and coron_branches >= args.max_coron_branches
                            ):
                                continue

                            coron_branches += 1
                            print(
                                f"[coron] #{coron_branches} s={s} x0={x0_value:x} "
                                f"x1={x1_value if x1_value is not None else None} "
                                f"x7={x7_value:x} x6top={x6_top_value:x} "
                                f"qfix={q_fixed_range} "
                                f"low={branch['low_bits']} "
                                f"p_hi={branch['p_hi_start']} "
                                f"hq={branch['q_prefix_bits']} "
                                f"Xbits={branch['x_bound'].nbits() - 1} "
                                f"Ybits={branch['y_bound'].nbits() - 1} "
                                f"Wraw={branch['raw_norm_bits']} "
                                f"Wprim={branch['primitive_norm_bits']} "
                                f"content_bits={branch['content_bits']} "
                                f"v2={branch['content_v2']} "
                                f"raw_margin={branch['raw_margin']:.2f} "
                                f"primitive_margin={branch['primitive_margin']:.2f}",
                                flush=True,
                            )
                            for k in parse_range_list(args.k_values):
                                try:
                                    print(f"  [*] Coron direct k={k}", flush=True)
                                    roots = coron_direct.integer_bivariate(
                                        branch["poly"],
                                        k,
                                        branch["x_bound"],
                                        branch["y_bound"],
                                        echelon_algorithm=args.echelon_algorithm,
                                        roots_method=args.roots_method,
                                    )
                                    for x_root, y_root in roots:
                                        x_root = ZZ(x_root)
                                        y_root = ZZ(y_root)
                                        if not (0 <= x_root < branch["x_bound"]):
                                            continue
                                        if not (0 <= y_root < branch["y_bound"]):
                                            continue
                                        p = (
                                            ZZ(branch["p_low"])
                                            + (x_root << branch["low_bits"])
                                            + (ZZ(branch["p_high"]) << branch["p_hi_start"])
                                        )
                                        if validate_and_print(n, e, ct, mask, known, p):
                                            return 0
                                except Exception as exc:  # noqa: BLE001 - investigation script should continue.
                                    print(f"  [!] k={k} failed: {type(exc).__name__}: {exc}", flush=True)

    elapsed = time.time() - started
    print(
        f"[-] not found; inspected={inspected}, coron_branches={coron_branches}, "
        f"skipped_by_margin={skipped_by_margin}, elapsed={elapsed:.2f}s",
        flush=True,
    )
    print(f"[+] margin_range=[{margin_min:.2f}, {margin_max:.2f}]", flush=True)
    if best_branch:
        print(f"[+] best_branch={best_branch}", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
