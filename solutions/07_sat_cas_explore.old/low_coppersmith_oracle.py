#!/usr/bin/env python3
"""Low contiguous p-bit Coppersmith oracle for challenge 7."""

from __future__ import annotations

import argparse
import json

from sat_cas_core import FixedRange, all_bits_known, load_instance, parse_fixed_range


DEFAULT_EPSILON = 0.02
DEFAULT_MIN_HARD_MARGIN_BITS = 8.0
COPPERSMITH_BETA = 0.5
COPPERSMITH_DEGREE = 1


def low_coppersmith_bound_report(
    *,
    n: int,
    low_bits: int,
    p_bits: int = 1024,
    epsilon: float = DEFAULT_EPSILON,
    min_hard_margin_bits: float = DEFAULT_MIN_HARD_MARGIN_BITS,
) -> dict[str, object]:
    unknown_bits = p_bits - low_bits
    n_bits = int(n).bit_length()
    effective_bound_bits = (
        (COPPERSMITH_BETA * COPPERSMITH_BETA / COPPERSMITH_DEGREE - epsilon) * n_bits
        - 1.0
    )
    effective_margin_bits = effective_bound_bits - unknown_bits
    return {
        "low_bits": low_bits,
        "epsilon": epsilon,
        "beta": COPPERSMITH_BETA,
        "degree": COPPERSMITH_DEGREE,
        "n_bit_length": n_bits,
        "unknown_bits": unknown_bits,
        "unknown_bound_bits": unknown_bits,
        "effective_bound_bits": effective_bound_bits,
        "effective_margin_bits": effective_margin_bits,
        "theorem_margin_bits": n_bits / 4.0 - unknown_bits,
        "min_hard_margin_bits": min_hard_margin_bits,
        "n_quarter_margin_bits": n_bits / 4.0 - unknown_bits,
        "hard_clause_bound_eligible": effective_margin_bits >= min_hard_margin_bits,
    }


def run_low_coppersmith(
    p_known: int,
    p_mask: int,
    n: int,
    low_bits: int,
    p_bits: int = 1024,
    epsilon: float = DEFAULT_EPSILON,
    min_hard_margin_bits: float = DEFAULT_MIN_HARD_MARGIN_BITS,
) -> dict[str, object]:
    bound_report = low_coppersmith_bound_report(
        n=n,
        low_bits=low_bits,
        p_bits=p_bits,
        epsilon=epsilon,
        min_hard_margin_bits=min_hard_margin_bits,
    )
    if not all_bits_known(p_mask, 0, low_bits):
        return {
            "status": "not_triggered",
            "reason": f"p[0..{low_bits - 1}] is not fully assigned",
            "hard_clause_eligible": False,
            **bound_report,
        }

    try:
        from sage.all import PolynomialRing, Zmod, ZZ
    except Exception as exc:  # pragma: no cover - depends on local Sage packaging
        return {
            "status": "unavailable",
            "reason": f"Sage import failed: {exc}",
            "hard_clause_eligible": False,
            **bound_report,
        }

    p0 = p_known & ((1 << low_bits) - 1)
    unknown_bound = ZZ(1) << (p_bits - low_bits)
    ring = PolynomialRing(Zmod(n), "x")
    x = ring.gen()
    roots = (ring(p0) + (ZZ(1) << low_bits) * x).monic().small_roots(
        X=unknown_bound,
        beta=0.5,
        epsilon=epsilon,
    )
    candidates = []
    for root in roots:
        p_candidate = int(p0 + (1 << low_bits) * int(root))
        if 1 < p_candidate < n and n % p_candidate == 0:
            candidates.append(p_candidate)

    status = "factored" if candidates else "no_roots"
    return {
        "status": status,
        **bound_report,
        "hard_clause_eligible": (
            status == "no_roots" and bool(bound_report["hard_clause_bound_eligible"])
        ),
        "roots_returned": len(roots),
        "factors": [hex(value) for value in candidates],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    parser.add_argument("--min-hard-margin-bits", type=float, default=DEFAULT_MIN_HARD_MARGIN_BITS)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    instance = load_instance()
    fixed_ranges: list[FixedRange] = list(args.fix_p_range)
    p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)
    report = run_low_coppersmith(
        p_known=p_known,
        p_mask=p_mask,
        n=instance.n,
        low_bits=args.low_bits,
        p_bits=instance.p_bits,
        epsilon=args.epsilon,
        min_hard_margin_bits=args.min_hard_margin_bits,
    )
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
