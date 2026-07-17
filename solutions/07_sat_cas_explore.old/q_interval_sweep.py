#!/usr/bin/env python3
"""Sweep fixed p-bit cubes and report interval-derived q-known gains."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from itertools import product

from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


@dataclass(frozen=True)
class CubeRange:
    start: int
    width: int

    @property
    def size(self) -> int:
        return 1 << self.width


def parse_cube_ranges(text: str) -> list[CubeRange]:
    ranges: list[CubeRange] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            start_text, width_text = part.split(":", 1)
        except ValueError as exc:
            raise ValueError("cube ranges must be START:WIDTH comma-separated items") from exc
        start = int(start_text, 0)
        width = int(width_text, 0)
        if start < 0 or width <= 0:
            raise ValueError(f"invalid cube range: {part}")
        ranges.append(CubeRange(start, width))
    return ranges


def compact_ranges(ranges: list[FixedRange]) -> list[dict[str, int | str]]:
    if not ranges:
        return []
    compacted: list[dict[str, int | str]] = []
    for item in sorted(ranges, key=lambda value: value.start):
        compacted.append(
            {
                "start": item.start,
                "width": item.width,
                "value": item.value,
                "value_hex": hex(item.value),
            }
        )
    return compacted


def iter_cubes(cube_ranges: list[CubeRange], max_cubes: int):
    if not cube_ranges:
        if max_cubes > 0:
            yield []
        return

    emitted = 0
    for values in product(*(range(item.size) for item in cube_ranges)):
        if emitted >= max_cubes:
            return
        emitted += 1
        yield [
            FixedRange(item.start, item.width, value)
            for item, value in zip(cube_ranges, values, strict=True)
        ]


def summarize_cube(instance, base_ranges: list[FixedRange], cube_ranges: list[FixedRange], index: int):
    p_known, p_mask = instance.apply_fixed_ranges(base_ranges + cube_ranges)
    q_known = derive_q_known_bits(instance, p_known, p_mask)
    return {
        "event": "cube",
        "index": index,
        "cube_ranges": compact_ranges(cube_ranges),
        "p_fixed_bits": p_mask.bit_count(),
        "q_low_bits": q_known.low_bits,
        "q_prefix_bits": q_known.prefix_bits,
        "q_prefix_start": q_known.prefix_start,
        "q_known_bits": q_known.mask.bit_count(),
        "q_min_bits": q_known.q_min.bit_length(),
        "q_max_bits": q_known.q_max.bit_length(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cube-ranges",
        default="150:4,920:4",
        help="comma-separated START:WIDTH p-bit ranges to enumerate",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--max-cubes", type=int, default=64)
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--json", action="store_true", help="emit a single JSON object; this is the default")
    parser.add_argument(
        "--keep-order",
        action="store_true",
        help="preserve enumeration order instead of ranking by q-known gain",
    )
    args = parser.parse_args()

    if args.max_cubes < 0:
        raise SystemExit("--max-cubes must be non-negative")

    instance = load_instance()
    base_ranges: list[FixedRange] = list(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)
    cube_ranges = parse_cube_ranges(args.cube_ranges)

    rows = []
    for index, cube in enumerate(iter_cubes(cube_ranges, args.max_cubes), start=1):
        row = summarize_cube(instance, base_ranges, cube, index)
        row["q_known_gain"] = int(row["q_known_bits"]) - base_q.mask.bit_count()
        row["q_low_gain"] = int(row["q_low_bits"]) - base_q.low_bits
        row["q_prefix_gain"] = int(row["q_prefix_bits"]) - base_q.prefix_bits
        rows.append(row)

    if not args.keep_order:
        rows.sort(
            key=lambda row: (
                -int(row["q_known_gain"]),
                -int(row["q_prefix_gain"]),
                -int(row["q_low_gain"]),
                compact_ranges_key(row["cube_ranges"]),
            )
        )

    summary = {
        "event": "summary",
        "cube_ranges": [{"start": item.start, "width": item.width} for item in cube_ranges],
        "base_fixed_ranges": compact_ranges(base_ranges),
        "base_p_fixed_bits": base_mask.bit_count(),
        "base_q_low_bits": base_q.low_bits,
        "base_q_prefix_bits": base_q.prefix_bits,
        "base_q_prefix_start": base_q.prefix_start,
        "base_q_known_bits": base_q.mask.bit_count(),
        "emitted_cubes": len(rows),
        "max_cubes": args.max_cubes,
    }

    if args.jsonl:
        for row in rows:
            print(json.dumps(row, sort_keys=True), flush=True)
        print(json.dumps(summary, sort_keys=True), flush=True)
    else:
        print(json.dumps({"event": "q_interval_sweep", "summary": summary, "items": rows}, sort_keys=True))
    return 0


def compact_ranges_key(ranges: object) -> tuple[tuple[int, int, int], ...]:
    if not isinstance(ranges, list):
        return ()
    key = []
    for item in ranges:
        if not isinstance(item, dict):
            continue
        key.append((int(item["start"]), int(item["width"]), int(item["value"])))
    return tuple(key)


if __name__ == "__main__":
    raise SystemExit(main())
