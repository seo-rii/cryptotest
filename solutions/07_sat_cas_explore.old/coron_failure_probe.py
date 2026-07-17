#!/usr/bin/env python3
"""Diagnose Coron-direct lattice shape for the challenge 7 folded branch.

This script mirrors the positive-margin x1-fixed branch used by
``solve_07_hybrid_coron.py`` and reports the exact dimensions that
``shared.small_roots.coron_direct.integer_bivariate`` will feed into the
right-block reconstruction step.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from sage.all import PolynomialRing, ZZ, matrix


THIS_FILE = Path(__file__).resolve()
SOLUTIONS_DIR = THIS_FILE.parents[1]
DEFAULT_CRYPTO_ATTACKS = Path("/tmp/crypto-attacks")


def parse_k_values(text: str) -> list[int]:
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


def load_solution_module():
    module_path = SOLUTIONS_DIR / "solve_07_hybrid_coron.py"
    spec = importlib.util.spec_from_file_location("solve_07_hybrid_coron_probe", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_max_norm(crypto_attacks: Path):
    if str(crypto_attacks) not in sys.path:
        sys.path.insert(0, str(crypto_attacks))
    from shared.polynomial import max_norm

    return max_norm


def build_target_branch(solution_module):
    c7 = solution_module.load_constants()
    n = int(c7.N_HEX.replace(" ", ""), 16)
    mask = int(c7.MASK_HEX.replace(" ", ""), 16)
    known = int(c7.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    unknown_mask = ((1 << solution_module.P_BITS) - 1) ^ mask
    ring = PolynomialRing(ZZ, names=("x", "y"))
    return solution_module.build_branch(
        ring,
        n,
        mask,
        known,
        unknown_mask,
        x0_value=0,
        x1_value=0,
        x7_value=0,
        x6_top_value=0x245521490BD,
        x6_top_bits=46,
        q_fixed_range=None,
        fixed_p_ranges=[],
    )


def matrix_shape_for_k(poly, k: int, delta: int, i0: int, j0: int, x_bound, y_bound):
    pr = poly.parent()
    x, y = pr.gens()
    left_monomials = []
    right_monomials = []
    for i in range(k + delta):
        for j in range(k + delta):
            monomial = x**i * y**j
            if 0 <= i - i0 < k and 0 <= j - j0 < k:
                left_monomials.append(monomial)
            else:
                right_monomials.append(monomial)

    monomials = left_monomials + right_monomials
    shifts_count = k**2 + len(monomials)
    lattice_cols = len(monomials)
    submatrix_start_row = k**2
    submatrix_start_col = k**2
    submatrix_size = (k + delta) ** 2 - k**2
    submatrix_rows_available = max(0, shifts_count - submatrix_start_row)
    submatrix_cols_available = max(0, lattice_cols - submatrix_start_col)
    empty_right = len(right_monomials) == 0
    malformed_right = len(right_monomials) != submatrix_size
    malformed_submatrix = (
        submatrix_size <= 0
        or submatrix_size > submatrix_rows_available
        or submatrix_size > submatrix_cols_available
    )

    support_outside_grid = []
    for shifted_a in range(k):
        for shifted_b in range(k):
            shifted = x**shifted_a * y**shifted_b * poly
            for exp, coeff in shifted.dict().items():
                if coeff and (exp[0] >= k + delta or exp[1] >= k + delta):
                    support_outside_grid.append((shifted_a, shifted_b, exp))

    s_matrix = matrix(ZZ, k**2, k**2)
    for a in range(k):
        for b in range(k):
            shifted = x**a * y**b * poly
            for i in range(k):
                for j in range(k):
                    s_matrix[a * k + b, i * k + j] = shifted.coefficient([i0 + i, j0 + j])

    det = abs(s_matrix.det())
    return {
        "k": k,
        "left_monomials": len(left_monomials),
        "right_monomials": len(right_monomials),
        "expected_left": k**2,
        "expected_right": submatrix_size,
        "all_monomials": len(monomials),
        "shifts": shifts_count,
        "full_lattice_rows": shifts_count,
        "full_lattice_cols": lattice_cols,
        "submatrix_start": [submatrix_start_row, submatrix_start_col],
        "submatrix_requested": [submatrix_size, submatrix_size],
        "submatrix_available_after_start": [submatrix_rows_available, submatrix_cols_available],
        "reconstruct_basis_rows": submatrix_size,
        "reconstruct_basis_cols": submatrix_size,
        "reconstruct_monomials": len(right_monomials),
        "empty_right_monomials": empty_right,
        "malformed_right_monomials": malformed_right,
        "malformed_submatrix_request": malformed_submatrix,
        "support_outside_grid_count": len(support_outside_grid),
        "support_outside_grid_examples": support_outside_grid[:5],
        "s_det_bits": det.nbits(),
        "s_det_zero": det == 0,
        "prediction": (
            "malformed"
            if empty_right or malformed_right or malformed_submatrix or det == 0
            else "right_monomials and reconstruct input are non-empty and dimensionally consistent"
        ),
        "bounds_bits": [bits_minus_one(x_bound), bits_minus_one(y_bound)],
    }


def stringify_for_json(value):
    if isinstance(value, dict):
        return {str(key): stringify_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [stringify_for_json(item) for item in value]
    if isinstance(value, tuple):
        return [stringify_for_json(item) for item in value]
    if isinstance(value, (int, str, float, bool)) or value is None:
        return value
    return str(value)


def bits_minus_one(value) -> int:
    return int(value).bit_length() - 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crypto-attacks", type=Path, default=DEFAULT_CRYPTO_ATTACKS)
    parser.add_argument("--k-values", default="6,7")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    solution_module = load_solution_module()
    max_norm = load_max_norm(args.crypto_attacks)
    branch = build_target_branch(solution_module)
    if branch is None:
        raise SystemExit("target branch did not build")

    poly = branch["poly"]
    x, y = poly.parent().gens()
    delta = max(poly.degrees())
    (i0, j0), weighted_norm = max_norm(poly(x * branch["x_bound"], y * branch["y_bound"]))

    report = {
        "branch": {
            "x0": 0,
            "x1": 0,
            "x7": 0,
            "x6_top": "0x245521490bd",
            "s": 46,
            "low_bits": int(branch["low_bits"]),
            "p_hi_start": int(branch["p_hi_start"]),
            "q_prefix_bits": int(branch["q_prefix_bits"]),
            "q_high_start": int(branch["q_high_start"]),
            "x_bound_bits": bits_minus_one(branch["x_bound"]),
            "y_bound_bits": bits_minus_one(branch["y_bound"]),
            "content_bits": int(branch["content_bits"]),
            "content_v2": int(branch["content_v2"]),
            "raw_norm_bits": int(branch["raw_norm_bits"]),
            "primitive_norm_bits": int(branch["primitive_norm_bits"]),
            "xy_bits": int(branch["xy_bits"]),
            "raw_margin": float(branch["raw_margin"]),
            "primitive_margin": float(branch["primitive_margin"]),
        },
        "coron_direct": {
            "delta": int(delta),
            "max_norm_monomial": [int(i0), int(j0)],
            "max_norm_coeff_bits": int(abs(ZZ(weighted_norm)).nbits()),
            "poly_degrees": [int(degree) for degree in poly.degrees()],
            "poly_terms": len(poly.dict()),
        },
        "k_reports": [
            matrix_shape_for_k(poly, k, delta, int(i0), int(j0), branch["x_bound"], branch["y_bound"])
            for k in parse_k_values(args.k_values)
        ],
    }

    if args.json:
        print(json.dumps(stringify_for_json(report), indent=2, sort_keys=True))
    else:
        print("branch:")
        for key, value in report["branch"].items():
            print(f"  {key}: {value}")
        print("coron_direct:")
        for key, value in report["coron_direct"].items():
            print(f"  {key}: {value}")
        print("k reports:")
        for item in report["k_reports"]:
            print(f"  k={item['k']}:")
            for key, value in item.items():
                if key != "k":
                    print(f"    {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
