#!/usr/bin/env python3
"""Bounded diagnostics for the low-side x2 low32 Coron path.

Batch12 showed that fixing the low edge of x2 at width 32 is enough to make
folded Coron reconstruction produce candidate polynomials.  This script checks
the cheaper SAT/CAS signals for a small set of x2 low32 values: derived q low
bits, q interval prefix bits, product-prefix consistency, and whether common
low-Coppersmith trigger widths are fully assigned.
"""

from __future__ import annotations

import argparse
import json
from itertools import product
from typing import Any

from sat_cas_core import (
    FixedRange,
    all_bits_known,
    derive_q_known_bits,
    load_instance,
    z3_product_prefix_status,
)


X1_START = 210
X1_WIDTH = 39
X2_LOW32_START = 265
X2_LOW32_WIDTH = 32

DEFAULT_X2_VALUES = "0,1,2,3"
DEFAULT_CHECK_BITS = "218,272,297,380"
DEFAULT_LOW_COPPERSMITH_BITS = "513,560,600"
DEFAULT_BASE_RANGES = (
    FixedRange(784, 46, 0x245521490BD),
    FixedRange(150, 4, 0),
    FixedRange(920, 4, 0),
)


def parse_int_list(text: str, *, default_none: bool = False) -> list[int | None]:
    if text.strip() == "":
        return [None] if default_none else []
    return [int(item.strip(), 0) for item in text.split(",") if item.strip()]


def parse_positive_int_list(text: str) -> list[int]:
    values = [int(item.strip(), 0) for item in text.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("expected at least one integer")
    if any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("values must be positive")
    return values


def fixed_range_label(item: FixedRange) -> str:
    return f"{item.start}:{item.width}:{hex(item.value)}"


def fixed_range_record(item: FixedRange) -> dict[str, int | str]:
    return {
        "start": item.start,
        "width": item.width,
        "value": item.value,
        "arg": fixed_range_label(item),
    }


def checked_fixed_range(start: int, width: int, value: int, label: str) -> FixedRange:
    if width <= 0:
        raise ValueError(f"{label} width must be positive")
    if value < 0 or value >= (1 << width):
        raise ValueError(f"{label} value {hex(value)} does not fit {width} bits")
    return FixedRange(start, width, value)


def x1_low_range(value: int, width: int) -> FixedRange:
    return checked_fixed_range(X1_START, width, value, "x1 low")


def x1_high_range(value: int, width: int) -> FixedRange:
    if width > X1_WIDTH:
        raise ValueError(f"x1 high width must be <= {X1_WIDTH}")
    return checked_fixed_range(X1_START + X1_WIDTH - width, width, value, "x1 high")


def build_candidate_ranges(
    x2_value: int,
    x1_low_value: int | None,
    x1_low_width: int,
    x1_high_value: int | None,
    x1_high_width: int,
) -> list[FixedRange]:
    ranges = [checked_fixed_range(X2_LOW32_START, X2_LOW32_WIDTH, x2_value, "x2 low32")]
    if x1_low_value is not None:
        ranges.append(x1_low_range(x1_low_value, x1_low_width))
    if x1_high_value is not None:
        ranges.append(x1_high_range(x1_high_value, x1_high_width))
    return ranges


def summarize_candidate(
    instance,
    candidate_index: int,
    base_ranges: list[FixedRange],
    candidate_ranges: list[FixedRange],
    check_bits: list[int],
    timeout_ms: int,
    low_coppersmith_bits: list[int],
) -> dict[str, Any]:
    p_known, p_mask = instance.apply_fixed_ranges(base_ranges + candidate_ranges)
    q_known = derive_q_known_bits(instance, p_known, p_mask)
    prefix_statuses = []
    for bits in check_bits:
        status, meta = z3_product_prefix_status(
            instance=instance,
            p_known=p_known,
            p_mask=p_mask,
            check_bits=bits,
            timeout_ms=timeout_ms,
        )
        prefix_statuses.append({"status": status, **meta})

    return {
        "index": candidate_index,
        "candidate_ranges": [fixed_range_record(item) for item in candidate_ranges],
        "all_fixed_ranges": [fixed_range_record(item) for item in base_ranges + candidate_ranges],
        "p_fixed_bits": p_mask.bit_count(),
        "p_contiguous_low_bits": q_known.low_bits,
        "q_low_bits": q_known.low_bits,
        "q_prefix_bits": q_known.prefix_bits,
        "q_prefix_start": q_known.prefix_start,
        "q_known_bits": q_known.mask.bit_count(),
        "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
        "low_coppersmith_triggers": {
            str(bits): all_bits_known(p_mask, 0, bits) for bits in low_coppersmith_bits
        },
        "product_prefix_statuses": prefix_statuses,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--x2-values",
        default=DEFAULT_X2_VALUES,
        help="comma-separated x2 low32 values; default is a small ordinal list",
    )
    parser.add_argument(
        "--x1-low-values",
        default="",
        help="optional comma-separated values for an x1 low chunk at p[210..]",
    )
    parser.add_argument("--x1-low-width", type=int, default=16)
    parser.add_argument(
        "--x1-high-values",
        default="",
        help="optional comma-separated values for an x1 high chunk ending at p[248]",
    )
    parser.add_argument("--x1-high-width", type=int, default=16)
    parser.add_argument(
        "--check-bits",
        type=parse_positive_int_list,
        default=parse_positive_int_list(DEFAULT_CHECK_BITS),
        help="comma-separated product-prefix widths checked with z3_product_prefix_status",
    )
    parser.add_argument("--timeout-ms", type=int, default=250)
    parser.add_argument(
        "--low-coppersmith-bits",
        type=parse_positive_int_list,
        default=parse_positive_int_list(DEFAULT_LOW_COPPERSMITH_BITS),
        help="comma-separated low-Coppersmith trigger widths to report",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def emit_human(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "base "
        f"p_fixed={summary['base_p_fixed_bits']} "
        f"q_low={summary['base_q_low_bits']} "
        f"q_prefix={summary['base_q_prefix_bits']} "
        f"q_known={summary['base_q_known_bits']}"
    )
    for item in report["candidates"]:
        ranges = ",".join(row["arg"] for row in item["candidate_ranges"])
        statuses = ",".join(
            f"{row['check_bits']}:{row['status']}" for row in item["product_prefix_statuses"]
        )
        triggers = ",".join(
            f"{bits}:{'Y' if enabled else 'n'}"
            for bits, enabled in item["low_coppersmith_triggers"].items()
        )
        print(
            f"{item['index']:02d} ranges={ranges} "
            f"q_low={item['q_low_bits']} "
            f"q_prefix={item['q_prefix_bits']} "
            f"q_known={item['q_known_bits']} "
            f"width_bits={item['q_interval_width_bits']} "
            f"prefix=[{statuses}] "
            f"low_coppersmith=[{triggers}]"
        )


def main() -> int:
    args = parse_args()
    if args.timeout_ms <= 0:
        raise SystemExit("--timeout-ms must be positive")
    if args.x1_low_width <= 0 or args.x1_low_width > X1_WIDTH:
        raise SystemExit(f"--x1-low-width must be in 1..{X1_WIDTH}")
    if args.x1_high_width <= 0 or args.x1_high_width > X1_WIDTH:
        raise SystemExit(f"--x1-high-width must be in 1..{X1_WIDTH}")

    x2_values = parse_int_list(args.x2_values)
    if not x2_values:
        raise SystemExit("--x2-values must contain at least one value")
    x1_low_values = parse_int_list(args.x1_low_values, default_none=True)
    x1_high_values = parse_int_list(args.x1_high_values, default_none=True)

    instance = load_instance()
    base_ranges = list(DEFAULT_BASE_RANGES)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)

    candidates = []
    for candidate_index, (x2_value, x1_low_value, x1_high_value) in enumerate(
        product(x2_values, x1_low_values, x1_high_values),
        start=1,
    ):
        candidate_ranges = build_candidate_ranges(
            int(x2_value),
            None if x1_low_value is None else int(x1_low_value),
            args.x1_low_width,
            None if x1_high_value is None else int(x1_high_value),
            args.x1_high_width,
        )
        candidates.append(
            summarize_candidate(
                instance,
                candidate_index,
                base_ranges,
                candidate_ranges,
                args.check_bits,
                args.timeout_ms,
                args.low_coppersmith_bits,
            )
        )

    report = {
        "event": "x2_low_prefix_probe",
        "summary": {
            "base_fixed_ranges": [fixed_range_record(item) for item in base_ranges],
            "base_p_fixed_bits": base_mask.bit_count(),
            "base_q_low_bits": base_q.low_bits,
            "base_q_prefix_bits": base_q.prefix_bits,
            "base_q_prefix_start": base_q.prefix_start,
            "base_q_known_bits": base_q.mask.bit_count(),
            "x2_low32_start": X2_LOW32_START,
            "x2_low32_width": X2_LOW32_WIDTH,
            "x1_low_width": args.x1_low_width,
            "x1_high_width": args.x1_high_width,
            "check_bits": args.check_bits,
            "timeout_ms": args.timeout_ms,
            "low_coppersmith_bits": args.low_coppersmith_bits,
            "candidate_count": len(candidates),
        },
        "candidates": candidates,
    }

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        emit_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
