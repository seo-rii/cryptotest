#!/usr/bin/env python3
"""Bounded Coron reconstruction-count sweep for challenge 7.

The edge-folded branches can now reach positive primitive margin, but the
expensive part is not useful unless Coron reconstructs enough non-constant
polynomials.  This probe stops before root solving by default and reports the
direct/projected right-block metadata plus the actual reconstructed polynomial
count.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

from sage.all import PolynomialRing, ZZ, matrix


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crypto-attacks", type=Path, default=Path("/tmp/crypto-attacks"))
    parser.add_argument("--s-values", default="44-46", help="comma/range list for fixed x6 top bits")
    parser.add_argument("--k-values", default="5-8", help="comma/range list for Coron k")
    parser.add_argument("--variant", choices=("direct", "projected", "both"), default="direct")
    parser.add_argument("--x0", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x1", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x6", type=lambda text: int(text, 0), default=0x245521490BD)
    parser.add_argument("--x7", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x6-width", type=int, default=46)
    parser.add_argument("--echelon-algorithm", default="default")
    parser.add_argument("--lll-delta", type=float, default=0.8)
    parser.add_argument("--metadata-only", action="store_true", help="skip echelon/LLL and report dimensions only")
    parser.add_argument("--run-roots", action="store_true", help="try root solving after reconstruction")
    parser.add_argument("--roots-methods", default="resultants", help="comma list used only with --run-roots")
    parser.add_argument("--max-roots", type=int, default=4)
    parser.add_argument("--max-rows", type=int, help="stop after this many s/k/variant rows")
    parser.add_argument("--smoke", action="store_true", help="single fast direct row: s=46,k=6")
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_bit_range_value,
        help=(
            "extra fixed p-bit range START:WIDTH:VALUE. This is mainly useful "
            "for edge ranges that move the folded low/high boundary."
        ),
    )
    parser.add_argument(
        "--q-fixed-range",
        type=parse_bit_range_value,
        help="extra fixed q-bit range START:WIDTH:VALUE that overlaps or extends the q high prefix",
    )
    args = parser.parse_args()

    s_values: list[int] = []
    k_values: list[int] = []
    for source, target in ((args.s_values, s_values), (args.k_values, k_values)):
        for raw_part in source.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if "-" in part:
                lo_text, hi_text = part.split("-", 1)
                lo = int(lo_text, 0)
                hi = int(hi_text, 0)
                target.extend(range(lo, hi + 1))
            else:
                target.append(int(part, 0))
    if args.smoke:
        s_values = [46]
        k_values = [6]
        args.variant = "direct"
        args.max_rows = 1

    roots_methods = [part.strip() for part in args.roots_methods.split(",") if part.strip()]
    variants = ["direct", "projected"] if args.variant == "both" else [args.variant]
    started_at = time.monotonic()
    rows: list[dict[str, object]] = []
    report: dict[str, object] = {
        "script": Path(__file__).name,
        "crypto_attacks": str(args.crypto_attacks),
        "branch_defaults": {
            "x0": args.x0,
            "x1": args.x1,
            "x6": hex(args.x6),
            "x7": args.x7,
            "x6_width": args.x6_width,
            "fixed_p_ranges": [
                {"start": start, "width": width, "value": value, "value_hex": hex(value)}
                for start, width, value in args.fix_p_range
            ],
            "q_fixed_range": None
            if args.q_fixed_range is None
            else {
                "start": args.q_fixed_range[0],
                "width": args.q_fixed_range[1],
                "value": args.q_fixed_range[2],
                "value_hex": hex(args.q_fixed_range[2]),
            },
        },
        "s_values": s_values,
        "k_values": k_values,
        "variants": variants,
        "metadata_only": bool(args.metadata_only),
        "run_roots": bool(args.run_roots),
        "rows": rows,
    }

    if not args.crypto_attacks.exists():
        report["status"] = "crypto_attacks_missing"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    if str(args.crypto_attacks) not in sys.path:
        sys.path.insert(0, str(args.crypto_attacks))

    from shared import small_roots
    from shared.polynomial import max_norm

    solutions_dir = Path(__file__).resolve().parents[1]
    solution_path = solutions_dir / "solve_07_hybrid_coron.py"
    spec = importlib.util.spec_from_file_location("solve_07_hybrid_coron_reconstruction_probe", solution_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {solution_path}")
    solution = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(solution)

    constants = solution.load_constants()
    n = int(constants.N_HEX.replace(" ", ""), 16)
    mask = int(constants.MASK_HEX.replace(" ", ""), 16)
    known = int(constants.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    unknown_mask = ((1 << solution.P_BITS) - 1) ^ mask
    ring = PolynomialRing(ZZ, names=("x", "y"))

    for s in s_values:
        if args.max_rows is not None and len(rows) >= args.max_rows:
            break
        if s <= 0 or s > args.x6_width:
            rows.append(
                {
                    "s": int(s),
                    "status": "invalid_s",
                    "elapsed_seconds": 0.0,
                }
            )
            continue

        x6_top = args.x6 >> (args.x6_width - s)
        branch = solution.build_branch(
            ring,
            n,
            mask,
            known,
            unknown_mask,
            x0_value=args.x0,
            x1_value=args.x1,
            x7_value=args.x7,
            x6_top_value=x6_top,
            x6_top_bits=s,
            q_fixed_range=args.q_fixed_range,
            fixed_p_ranges=args.fix_p_range,
        )

        for k in k_values:
            for variant in variants:
                if args.max_rows is not None and len(rows) >= args.max_rows:
                    break
                row_started = time.monotonic()
                row: dict[str, object] = {
                    "s": int(s),
                    "k": int(k),
                    "variant": variant,
                    "x0": int(args.x0),
                    "x1": int(args.x1),
                    "x6_top": hex(int(x6_top)),
                    "x6_top_bits": int(s),
                    "x7": int(args.x7),
                    "fixed_p_ranges": [
                        {"start": start, "width": width, "value": value, "value_hex": hex(value)}
                        for start, width, value in args.fix_p_range
                    ],
                    "q_fixed_range": None
                    if args.q_fixed_range is None
                    else {
                        "start": args.q_fixed_range[0],
                        "width": args.q_fixed_range[1],
                        "value": args.q_fixed_range[2],
                        "value_hex": hex(args.q_fixed_range[2]),
                    },
                    "root_methods": roots_methods if args.run_roots else [],
                    "status": "started",
                }
                rows.append(row)
                if branch is None:
                    row["status"] = "branch_infeasible"
                    row["elapsed_seconds"] = round(time.monotonic() - row_started, 6)
                    continue

                try:
                    poly = branch["poly"]
                    pr = poly.parent()
                    x, y = pr.gens()
                    delta = int(max(poly.degrees()))
                    (i0, j0), weighted_norm = max_norm(poly(x * branch["x_bound"], y * branch["y_bound"]))
                    i0 = int(i0)
                    j0 = int(j0)

                    left_monomials = []
                    right_monomials = []
                    for i in range(k + delta):
                        for j in range(k + delta):
                            monomial = x**i * y**j
                            if 0 <= i - i0 < k and 0 <= j - j0 < k:
                                left_monomials.append(monomial)
                            else:
                                right_monomials.append(monomial)

                    expected_right = (k + delta) ** 2 - k**2
                    row.update(
                        {
                            "low_bits": int(branch["low_bits"]),
                            "high_start": int(branch["p_hi_start"]),
                            "Xbits": int(branch["x_bound"]).bit_length() - 1,
                            "Ybits": int(branch["y_bound"]).bit_length() - 1,
                            "q_prefix_bits": int(branch["q_prefix_bits"]),
                            "q_high_start": int(branch["q_high_start"]),
                            "content_bits": int(branch["content_bits"]),
                            "content_v2": int(branch["content_v2"]),
                            "raw_norm_bits": int(branch["raw_norm_bits"]),
                            "primitive_norm_bits": int(branch["primitive_norm_bits"]),
                            "xy_bits": int(branch["xy_bits"]),
                            "raw_margin": float(branch["raw_margin"]),
                            "primitive_margin": float(branch["primitive_margin"]),
                            "delta": delta,
                            "max_norm_monomial": [i0, j0],
                            "max_norm_coeff_bits": int(abs(ZZ(weighted_norm)).nbits()),
                            "poly_terms": int(len(poly.dict())),
                            "left_monomials": int(len(left_monomials)),
                            "right_monomials": int(len(right_monomials)),
                            "expected_left_monomials": int(k**2),
                            "expected_right_monomials": int(expected_right),
                            "resultants_min_extra_polynomials": max(0, pr.ngens() - 1),
                            "reconstructed_polynomial_count": None,
                            "short_row_count": None,
                        }
                    )

                    if len(left_monomials) != k**2 or len(right_monomials) != expected_right:
                        row["status"] = "monomial_partition_mismatch"
                        row["elapsed_seconds"] = round(time.monotonic() - row_started, 6)
                        continue

                    if variant == "direct":
                        monomials = left_monomials + right_monomials
                        row["matrix_dimension"] = [int(k**2 + len(monomials)), int(len(monomials))]
                        row["right_dimension"] = [int(expected_right), int(expected_right)]
                        row["reconstruction_input_dimension"] = [int(expected_right), int(expected_right)]
                        if args.metadata_only:
                            row["status"] = "metadata_only"
                            row["elapsed_seconds"] = round(time.monotonic() - row_started, 6)
                            continue

                        shifts = []
                        for a in range(k):
                            for b in range(k):
                                shifts.append(x**a * y**b * poly)
                        S = matrix(ZZ, k**2, k**2)
                        for a in range(k):
                            for b in range(k):
                                shifted = shifts[a * k + b]
                                for i in range(k):
                                    for j in range(k):
                                        S[a * k + b, i * k + j] = shifted.coefficient([i0 + i, j0 + j])
                        det_n = abs(S.det())
                        row["det_bits"] = int(det_n.nbits())
                        row["det_zero"] = bool(det_n == 0)
                        if det_n == 0:
                            row["status"] = "zero_determinant"
                            row["elapsed_seconds"] = round(time.monotonic() - row_started, 6)
                            continue

                        for monomial in monomials:
                            shifts.append(monomial * det_n)
                        L = matrix(ZZ, len(shifts), len(monomials))
                        for shift_row, shifted in enumerate(shifts):
                            for col, monomial in enumerate(monomials):
                                L[shift_row, col] = shifted.monomial_coefficient(monomial) * monomial(
                                    branch["x_bound"], branch["y_bound"]
                                )
                        L = L.echelon_form(algorithm=args.echelon_algorithm)
                        L2 = L.submatrix(k**2, k**2, expected_right, expected_right)
                        L2 = L2.LLL(args.lll_delta)

                    else:
                        row["matrix_dimension"] = [int(k**2 + len(right_monomials)), int(len(right_monomials))]
                        row["right_dimension"] = [int(expected_right), int(expected_right)]
                        row["reconstruction_input_dimension"] = [int(expected_right), int(expected_right)]
                        if args.metadata_only:
                            row["status"] = "metadata_only"
                            row["elapsed_seconds"] = round(time.monotonic() - row_started, 6)
                            continue

                        S = matrix(ZZ, k**2, k**2)
                        for a in range(k):
                            for b in range(k):
                                shifted = x**a * y**b * poly
                                for i in range(k):
                                    for j in range(k):
                                        S[a * k + b, i * k + j] = shifted.coefficient([i0 + i, j0 + j])
                        det_n = abs(S.det())
                        row["det_bits"] = int(det_n.nbits())
                        row["det_zero"] = bool(det_n == 0)
                        if det_n == 0:
                            row["status"] = "zero_determinant"
                            row["elapsed_seconds"] = round(time.monotonic() - row_started, 6)
                            continue

                        T = matrix(ZZ, k**2, len(right_monomials))
                        for a in range(k):
                            for b in range(k):
                                shifted = x**a * y**b * poly
                                for col, monomial in enumerate(right_monomials):
                                    T[a * k + b, col] = shifted.monomial_coefficient(monomial) * monomial(
                                        branch["x_bound"], branch["y_bound"]
                                    )
                        projected = S.adjugate() * T
                        reduced_input = matrix(ZZ, k**2 + len(right_monomials), len(right_monomials))
                        reduced_input[: k**2, :] = projected
                        for col, monomial in enumerate(right_monomials):
                            reduced_input[k**2 + col, col] = det_n * monomial(
                                branch["x_bound"], branch["y_bound"]
                            )
                        L2 = reduced_input.echelon_form(algorithm=args.echelon_algorithm)
                        L2 = L2.submatrix(0, 0, len(right_monomials), len(right_monomials))
                        L2 = L2.LLL(args.lll_delta)

                    short_rows = 0
                    for lll_row in range(L2.nrows()):
                        norm_squared = ZZ(0)
                        nonzero = 0
                        for col, monomial in enumerate(right_monomials):
                            value = L2[lll_row, col]
                            if value == 0:
                                continue
                            norm_squared += value**2
                            nonzero += 1
                        if nonzero and norm_squared * nonzero < det_n**2:
                            short_rows += 1

                    polynomials = small_roots.reconstruct_polynomials(
                        L2,
                        poly,
                        det_n,
                        right_monomials,
                        [branch["x_bound"], branch["y_bound"]],
                    )
                    row["short_row_count"] = int(short_rows)
                    row["reconstructed_polynomial_count"] = int(len(polynomials))
                    row["has_resultants_input"] = bool(len(polynomials) + 1 >= pr.ngens())
                    row["status"] = "ok" if polynomials else "no_reconstructed_polynomials"

                    if args.run_roots:
                        root_results: dict[str, object] = {}
                        for method in roots_methods:
                            method_started = time.monotonic()
                            if method == "resultants" and len(polynomials) + 1 < pr.ngens():
                                root_results[method] = {
                                    "status": "skipped_not_enough_polynomials",
                                    "elapsed_seconds": round(time.monotonic() - method_started, 6),
                                }
                                continue
                            method_roots = []
                            verified_factors = []
                            for roots in small_roots.find_roots(pr, [poly] + polynomials, method=method):
                                root_values = {str(gen): int(value) for gen, value in roots.items()}
                                method_roots.append(root_values)
                                x_value = root_values.get(str(x))
                                if x_value is not None:
                                    p_candidate = (
                                        int(branch["p_low"])
                                        + (1 << int(branch["low_bits"])) * int(x_value)
                                        + (int(branch["p_high"]) << int(branch["p_hi_start"]))
                                    )
                                    if 1 < p_candidate < n and n % p_candidate == 0:
                                        verified_factors.append(
                                            {
                                                "p": hex(p_candidate),
                                                "q": hex(n // p_candidate),
                                            }
                                        )
                                if len(method_roots) >= args.max_roots:
                                    break
                            root_results[method] = {
                                "status": "ok",
                                "root_count": int(len(method_roots)),
                                "roots": method_roots,
                                "verified_factor_count": int(len(verified_factors)),
                                "verified_factors": verified_factors,
                                "elapsed_seconds": round(time.monotonic() - method_started, 6),
                            }
                        row["root_results"] = root_results

                except Exception as exc:  # noqa: BLE001 - diagnostic script should keep sweeping.
                    row["status"] = "error"
                    row["error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    row["elapsed_seconds"] = round(time.monotonic() - row_started, 6)

            if args.max_rows is not None and len(rows) >= args.max_rows:
                break

    report["status"] = "ok"
    report["elapsed_seconds"] = round(time.monotonic() - started_at, 6)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
