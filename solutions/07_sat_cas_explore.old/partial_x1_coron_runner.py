#!/usr/bin/env python3
"""Probe folded Coron geometry when only low x1 bits are fixed.

The current actual reconstruction runner builds branches through
solve_07_hybrid_coron.build_branch(), which supports full x1 assignments but
not partial x1 ranges.  This script therefore reports exact folded geometry
for partial x1 widths and only delegates actual reconstruction when x1 is
fully fixed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from math import gcd
from pathlib import Path
from typing import Any

from sat_cas_core import FixedRange, derive_q_known_bits, load_instance


X0_OFFSET = 150
X0_WIDTH = 4
X1_OFFSET = 210
X1_WIDTH = 39
X6_OFFSET = 784
X6_WIDTH = 46
X7_OFFSET = 920
X7_WIDTH = 4


def parse_int_list(text: str) -> list[int]:
    values: list[int] = []
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            lo_text, hi_text = part.split("-", 1)
            lo = int(lo_text, 0)
            hi = int(hi_text, 0)
            step = 1 if lo <= hi else -1
            values.extend(range(lo, hi + step, step))
        else:
            values.append(int(part, 0))
    return values


def fixed_ranges_for(width: int, x1_low_value: int, x0: int, x6: int, x7: int) -> list[FixedRange]:
    if width < 0 or width > X1_WIDTH:
        raise ValueError(f"x1 low width must be in 0..{X1_WIDTH}: {width}")
    if x0 < 0 or x0 >= (1 << X0_WIDTH):
        raise ValueError(f"x0 does not fit {X0_WIDTH} bits")
    if x6 < 0 or x6 >= (1 << X6_WIDTH):
        raise ValueError(f"x6 does not fit {X6_WIDTH} bits")
    if x7 < 0 or x7 >= (1 << X7_WIDTH):
        raise ValueError(f"x7 does not fit {X7_WIDTH} bits")

    ranges = [
        FixedRange(X0_OFFSET, X0_WIDTH, x0),
        FixedRange(X6_OFFSET, X6_WIDTH, x6),
        FixedRange(X7_OFFSET, X7_WIDTH, x7),
    ]
    if width:
        ranges.append(FixedRange(X1_OFFSET, width, x1_low_value & ((1 << width) - 1)))
    return ranges


def folded_margin_report(width: int, x1_low_value: int, x0: int, x6: int, x7: int) -> dict[str, Any]:
    instance = load_instance()
    p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges_for(width, x1_low_value, x0, x6, x7))
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
    return {
        "x1_low_width": width,
        "x1_low_value": hex(x1_low_value & ((1 << width) - 1)) if width else "0x0",
        "fixed_ranges": [
            {"start": item.start, "width": item.width, "value": hex(item.value)}
            for item in fixed_ranges_for(width, x1_low_value, x0, x6, x7)
        ],
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
        "margin_positive": primitive_margin > 0,
        "x1_fully_fixed": width == X1_WIDTH,
        "x6_fully_fixed": True,
    }


def run_actual_reconstruction(width: int, x1_low_value: int, x0: int, x6: int, x7: int, k: int, timeout: int) -> dict[str, Any]:
    if width != X1_WIDTH:
        return {
            "actual_reconstruction_supported": False,
            "actual_reconstruction_attempted": False,
            "reason": "coron_reconstruction_sweep.py currently requires full x1 via build_branch()",
        }
    if timeout <= 0:
        return {
            "actual_reconstruction_supported": True,
            "actual_reconstruction_attempted": False,
            "reason": "timeout_seconds <= 0",
        }

    script = Path(__file__).with_name("coron_reconstruction_sweep.py")
    command = [
        sys.executable,
        "-B",
        str(script),
        "--s-values",
        str(X6_WIDTH),
        "--k-values",
        str(k),
        "--variant",
        "direct",
        "--x0",
        str(x0),
        "--x1",
        str(x1_low_value & ((1 << X1_WIDTH) - 1)),
        "--x6",
        hex(x6),
        "--x7",
        str(x7),
        "--max-rows",
        "1",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "actual_reconstruction_supported": True,
            "actual_reconstruction_attempted": True,
            "status": "timeout",
            "timeout_seconds": timeout,
            "stdout_prefix": (exc.stdout or "")[:500] if isinstance(exc.stdout, str) else "",
            "stderr_prefix": (exc.stderr or "")[:500] if isinstance(exc.stderr, str) else "",
        }

    result: dict[str, Any] = {
        "actual_reconstruction_supported": True,
        "actual_reconstruction_attempted": True,
        "returncode": completed.returncode,
    }
    try:
        parsed = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result.update(
            {
                "status": "json_parse_error",
                "stdout_prefix": completed.stdout[:500],
                "stderr_prefix": completed.stderr[:500],
            }
        )
        return result

    rows = parsed.get("rows", [])
    first_row = rows[0] if rows else {}
    result.update(
        {
            "status": first_row.get("status", parsed.get("status")),
            "elapsed_seconds": first_row.get("elapsed_seconds"),
            "reconstructed_polynomial_count": first_row.get("reconstructed_polynomial_count"),
            "short_row_count": first_row.get("short_row_count"),
            "primitive_margin": first_row.get("primitive_margin"),
            "matrix_dimension": first_row.get("matrix_dimension"),
            "right_dimension": first_row.get("right_dimension"),
        }
    )
    if completed.stderr:
        result["stderr_prefix"] = completed.stderr[:500]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x1-low-widths", default="0,8,16,24,32,39")
    parser.add_argument("--x1-low-value", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x6", type=lambda text: int(text, 0), default=0x245521490BD)
    parser.add_argument("--x0", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x7", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    widths = parse_int_list(args.x1_low_widths)
    rows: list[dict[str, Any]] = []
    for width in widths:
        row = folded_margin_report(width, args.x1_low_value, args.x0, args.x6, args.x7)
        if row["margin_positive"]:
            row["actual_reconstruction"] = run_actual_reconstruction(
                width,
                args.x1_low_value,
                args.x0,
                args.x6,
                args.x7,
                args.k,
                args.timeout_seconds,
            )
        else:
            row["actual_reconstruction"] = {
                "actual_reconstruction_supported": width == X1_WIDTH,
                "actual_reconstruction_attempted": False,
                "reason": "primitive_margin <= 0",
            }
        rows.append(row)

    report = {
        "script": Path(__file__).name,
        "x0": args.x0,
        "x6": hex(args.x6),
        "x7": args.x7,
        "x1_low_value": hex(args.x1_low_value),
        "k": args.k,
        "timeout_seconds": args.timeout_seconds,
        "rows": rows,
        "positive_margin_widths": [row["x1_low_width"] for row in rows if row["margin_positive"]],
        "actual_reconstruction_supported_widths": [
            row["x1_low_width"]
            for row in rows
            if row["actual_reconstruction"]["actual_reconstruction_supported"]
        ],
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"x0={args.x0} x6={args.x6:#x} x7={args.x7} x1_low_value={args.x1_low_value:#x}")
        for row in rows:
            actual = row["actual_reconstruction"]
            print(
                "width={x1_low_width:2d} margin={primitive_margin:8.3f} "
                "low={low_bits:3d} high={high_start:3d} X={x_width:3d} Y={y_width:3d} "
                "q_prefix={q_prefix_bits:3d} actual={status}".format(
                    **row,
                    status=actual.get("status", actual.get("reason")),
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
