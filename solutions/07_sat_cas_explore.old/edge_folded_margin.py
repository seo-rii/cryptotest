#!/usr/bin/env python3
"""Edge-folded Coron margin probe for challenge 7 assignments."""

from __future__ import annotations

import argparse
import json
from math import gcd

from sat_cas_core import derive_q_known_bits, load_instance, parse_fixed_range


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    instance = load_instance()
    p_known, p_mask = instance.apply_fixed_ranges(list(args.fix_p_range))
    p_unknown_mask = instance.full_mask ^ p_mask
    if p_unknown_mask:
        low_bits = (p_unknown_mask & -p_unknown_mask).bit_length() - 1
        high_start = p_unknown_mask.bit_length()
    else:
        low_bits = instance.p_bits
        high_start = 0

    q_known = derive_q_known_bits(instance, p_known, p_mask)
    x_width = max(0, high_start - low_bits)
    y_width = max(0, q_known.prefix_start - low_bits)
    p_low = p_known & ((1 << low_bits) - 1) if low_bits else 0
    p_high = p_known >> high_start if high_start else 0
    q_low = q_known.known & ((1 << low_bits) - 1) if low_bits else 0
    q_high = q_known.known >> q_known.prefix_start if q_known.prefix_start < instance.p_bits else 0
    p_const = p_low + (p_high << high_start)
    q_const = q_low + (q_high << q_known.prefix_start)
    coefficients = [
        p_const * q_const - instance.n,
        (1 << low_bits) * q_const if x_width else 0,
        (1 << low_bits) * p_const if y_width else 0,
        (1 << (2 * low_bits)) if x_width and y_width else 0,
    ]
    content = 0
    for coeff in coefficients:
        content = gcd(content, abs(coeff))
    primitive_coefficients = [coeff // content for coeff in coefficients] if content else coefficients
    weighted_terms = [
        abs(primitive_coefficients[0]),
        abs(primitive_coefficients[1]) * (1 << x_width) if x_width else 0,
        abs(primitive_coefficients[2]) * (1 << y_width) if y_width else 0,
        abs(primitive_coefficients[3]) * (1 << (x_width + y_width)) if x_width and y_width else 0,
    ]
    primitive_norm_bits = max(value.bit_length() for value in weighted_terms if value)
    xy_bits = x_width + y_width
    primitive_margin = (2.0 * primitive_norm_bits / 3.0) - xy_bits
    report = {
        "low_bits": low_bits,
        "high_start": high_start,
        "x_width": x_width,
        "y_width": y_width,
        "q_low_bits": q_known.low_bits,
        "q_prefix_bits": q_known.prefix_bits,
        "q_prefix_start": q_known.prefix_start,
        "content_bits": content.bit_length() - 1 if content else 0,
        "primitive_norm_bits": primitive_norm_bits,
        "xy_bits": xy_bits,
        "primitive_margin": primitive_margin,
        "x1_fully_fixed": (p_mask & (((1 << 39) - 1) << 210)) == (((1 << 39) - 1) << 210),
        "x6_fully_fixed": (p_mask & (((1 << 46) - 1) << 784)) == (((1 << 46) - 1) << 784),
        "hard_clause_on_failure": False,
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
