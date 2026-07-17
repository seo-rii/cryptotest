#!/usr/bin/env python3
"""Sweep partial x6 high-bit fixing patterns for folded-Coron margin."""

from __future__ import annotations

import argparse
import json
from typing import Any

from partial_x1_margin_sweep import folded_margin, parse_int_list
from sat_cas_core import FixedRange, load_instance, parse_fixed_range


X0 = (150, 4)
X1 = (210, 39)
X6 = (784, 46)
X7 = (920, 4)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--widths", default="0,8,16,24,32,38,40,42,44,45,46", type=parse_int_list)
    parser.add_argument("--x0", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x1", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x6", type=lambda text: int(text, 0), default=0x245521490BD)
    parser.add_argument("--x7", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    instance = load_instance()
    base_ranges = [
        FixedRange(X0[0], X0[1], args.x0),
        FixedRange(X1[0], X1[1], args.x1),
        FixedRange(X7[0], X7[1], args.x7),
        *list(args.fix_p_range),
    ]

    rows: list[dict[str, Any]] = []
    for width in args.widths:
        try:
            if width < 0 or width > X6[1]:
                raise ValueError("x6 width must be in 0..46")
            x6_ranges = []
            if width:
                start = X6[0] + X6[1] - width
                value = args.x6 >> (X6[1] - width)
                x6_ranges.append(FixedRange(start, width, value))
            report = folded_margin(instance, base_ranges + x6_ranges)
            status = "ok"
        except Exception as exc:  # noqa: BLE001 - diagnostic sweep should continue.
            report = {"error": f"{type(exc).__name__}: {exc}"}
            status = "error"
            x6_ranges = []
        rows.append(
            {
                "event": "partial_x6_margin",
                "status": status,
                "x6_fixed_high_width": width,
                "x6_ranges": [
                    {"start": item.start, "width": item.width, "value": item.value}
                    for item in x6_ranges
                ],
                **report,
            }
        )

    valid_rows = [row for row in rows if row.get("status") == "ok"]
    positive_rows = [row for row in valid_rows if float(row["primitive_margin"]) > 0]
    best = max(valid_rows, key=lambda row: float(row["primitive_margin"])) if valid_rows else None
    summary = {
        "event": "partial_x6_margin_summary",
        "x0": args.x0,
        "x1": args.x1,
        "x6": hex(args.x6),
        "x7": args.x7,
        "rows": len(rows),
        "positive_rows": len(positive_rows),
        "first_positive_width": min(
            (int(row["x6_fixed_high_width"]) for row in positive_rows),
            default=None,
        ),
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
                f"width={row['x6_fixed_high_width']:>2} "
                f"high={row['high_start']:>3} X={row['x_width']:>3} Y={row['y_width']:>3} "
                f"qpre={row['q_prefix_bits']:>3} margin={row['primitive_margin']:.2f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
