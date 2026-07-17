#!/usr/bin/env python3
"""Sweep partial x1 fixing patterns for folded-Coron margin.

The full edge verifier becomes viable when x1 and x6 are fully fixed.  This
probe asks a narrower question: how much of x1 has to be fixed before the
folded bivariate geometry reaches a positive primitive margin?
"""

from __future__ import annotations

import argparse
import json
from math import gcd
from typing import Any

from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


X0 = (150, 4)
X1 = (210, 39)
X6 = (784, 46)
X7 = (920, 4)


def parse_int_list(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if "-" in item:
            lo_text, hi_text = item.split("-", 1)
            lo = int(lo_text, 0)
            hi = int(hi_text, 0)
            if hi < lo:
                raise argparse.ArgumentTypeError(f"descending range: {item}")
            values.extend(range(lo, hi + 1))
        else:
            values.append(int(item, 0))
    if not values:
        raise argparse.ArgumentTypeError("expected at least one integer")
    return values


def folded_margin(instance, ranges: list[FixedRange]) -> dict[str, Any]:
    p_known, p_mask = instance.apply_fixed_ranges(ranges)
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
    return {
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
        "primitive_margin": (2.0 * primitive_norm_bits / 3.0) - xy_bits,
    }


def x1_ranges_for_mode(mode: str, width: int, value: int) -> list[FixedRange]:
    if width <= 0:
        return []
    if width > X1[1]:
        raise ValueError("x1 width exceeds x1 bit run")
    if value < 0 or value >= (1 << width):
        raise ValueError("x1 partial value does not fit selected width")
    if mode == "low":
        return [FixedRange(X1[0], width, value)]
    if mode == "high":
        return [FixedRange(X1[0] + X1[1] - width, width, value)]
    if mode == "split":
        low_width = width // 2
        high_width = width - low_width
        ranges = []
        if low_width:
            ranges.append(FixedRange(X1[0], low_width, value & ((1 << low_width) - 1)))
        if high_width:
            ranges.append(
                FixedRange(
                    X1[0] + X1[1] - high_width,
                    high_width,
                    value >> low_width,
                )
            )
        return ranges
    raise ValueError(f"unsupported mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--widths", default="0,8,16,24,32,39", type=parse_int_list)
    parser.add_argument("--modes", default="low,high,split")
    parser.add_argument("--x1-value", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x0", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x6", type=lambda text: int(text, 0), default=0x245521490BD)
    parser.add_argument("--x7", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    instance = load_instance()
    base_ranges = [
        FixedRange(X0[0], X0[1], args.x0),
        FixedRange(X6[0], X6[1], args.x6),
        FixedRange(X7[0], X7[1], args.x7),
        *list(args.fix_p_range),
    ]
    rows = []
    for mode in [item.strip() for item in args.modes.split(",") if item.strip()]:
        for width in args.widths:
            selected_value = args.x1_value & ((1 << width) - 1) if width else 0
            try:
                x1_ranges = x1_ranges_for_mode(mode, width, selected_value)
                report = folded_margin(instance, base_ranges + x1_ranges)
                status = "ok"
            except Exception as exc:  # noqa: BLE001 - diagnostic sweep should continue.
                report = {"error": f"{type(exc).__name__}: {exc}"}
                status = "error"
                x1_ranges = []
            rows.append(
                {
                    "event": "partial_x1_margin",
                    "status": status,
                    "mode": mode,
                    "x1_fixed_width": width,
                    "x1_value": selected_value,
                    "x1_ranges": [
                        {"start": item.start, "width": item.width, "value": item.value}
                        for item in x1_ranges
                    ],
                    **report,
                }
            )

    valid_rows = [row for row in rows if row.get("status") == "ok"]
    positive_rows = [row for row in valid_rows if float(row["primitive_margin"]) > 0]
    best = None
    if valid_rows:
        best = max(valid_rows, key=lambda row: float(row["primitive_margin"]))
    summary = {
        "event": "partial_x1_margin_summary",
        "x0": args.x0,
        "x6": hex(args.x6),
        "x7": args.x7,
        "x1_value": args.x1_value,
        "rows": len(rows),
        "positive_rows": len(positive_rows),
        "first_positive_by_mode": {
            mode: min(
                (
                    int(row["x1_fixed_width"])
                    for row in positive_rows
                    if row["mode"] == mode
                ),
                default=None,
            )
            for mode in sorted({str(row["mode"]) for row in rows})
        },
        "best": best,
    }
    payload = {"summary": summary, "items": rows}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(summary, indent=2, sort_keys=True))
        for row in rows:
            if row["status"] != "ok":
                print(json.dumps(row, sort_keys=True))
                continue
            print(
                f"{row['mode']:>5s} width={row['x1_fixed_width']:>2} "
                f"low={row['low_bits']:>3} X={row['x_width']:>3} Y={row['y_width']:>3} "
                f"qpre={row['q_prefix_bits']:>3} margin={row['primitive_margin']:.2f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
