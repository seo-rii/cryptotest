#!/usr/bin/env python3
"""Score sampled selected-cube candidates before q-gap direct runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def range_value(raw_ranges: object, start: int, width: int) -> int | None:
    if not isinstance(raw_ranges, list):
        return None
    values: dict[int, int] = {}
    for raw_item in raw_ranges:
        if not isinstance(raw_item, dict):
            return None
        item_start = int(raw_item["start"])
        item_width = int(raw_item["width"])
        item_value = int(raw_item.get("value", 0))
        for offset in range(item_width):
            values[item_start + offset] = (item_value >> offset) & 1
    result = 0
    for offset in range(width):
        bit = start + offset
        if bit not in values:
            return None
        result |= values[bit] << offset
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top", type=int, default=1024)
    parser.add_argument("--max-per-x0", type=int, default=0)
    parser.add_argument("--max-per-x7", type=int, default=0)
    parser.add_argument("--max-per-x2mid", type=int, default=0)
    parser.add_argument("--max-per-x3low", type=int, default=0)
    parser.add_argument("--max-per-x3mid", type=int, default=0)
    parser.add_argument("--max-per-x3high", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.top < 1:
        raise SystemExit("--top must be positive")
    for name in (
        "max_per_x0",
        "max_per_x7",
        "max_per_x2mid",
        "max_per_x3low",
        "max_per_x3mid",
        "max_per_x3high",
    ):
        if int(getattr(args, name)) < 0:
            raise SystemExit(f"--{name.replace('_', '-')} must be nonnegative")

    payload = json.loads(args.sample_json.expanduser().read_text(encoding="utf-8"))
    rows = payload.get("top") or payload.get("results") or []
    if not isinstance(rows, list):
        raise SystemExit("sample JSON has no top/results array")

    enriched: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") != "sat":
            continue
        cube_ranges = row.get("cube_ranges")
        scored = dict(row)
        scored["score_x0"] = range_value(cube_ranges, 150, 4)
        scored["score_x7"] = range_value(cube_ranges, 920, 4)
        scored["score_x2mid"] = range_value(cube_ranges, 305, 8)
        scored["score_x3low"] = range_value(cube_ranges, 362, 8)
        scored["score_x3mid"] = range_value(cube_ranges, 382, 8)
        scored["score_x3high"] = range_value(cube_ranges, 412, 8)
        enriched.append(scored)

    def sort_key(row: dict[str, Any]) -> tuple[int, int, int, int, int]:
        return (
            int(row.get("q_gap_bits", 10**9)),
            -int(row.get("q_known_bits", -1)),
            int(row.get("q_interval_width_bits", 10**9)),
            int(row.get("random_assumption_bits_used", 10**9)),
            int(row.get("rank", 10**9)),
        )

    ranked = sorted(enriched, key=sort_key)
    retained: list[dict[str, Any]] = []
    cap_specs = [
        ("score_x0", args.max_per_x0),
        ("score_x7", args.max_per_x7),
        ("score_x2mid", args.max_per_x2mid),
        ("score_x3low", args.max_per_x3low),
        ("score_x3mid", args.max_per_x3mid),
        ("score_x3high", args.max_per_x3high),
    ]
    counts: dict[str, dict[int | None, int]] = {name: {} for name, _ in cap_specs}
    for row in ranked:
        blocked = False
        for name, cap in cap_specs:
            if cap and counts[name].get(row.get(name), 0) >= cap:
                blocked = True
                break
        if blocked:
            continue
        retained.append(row)
        for name, _ in cap_specs:
            value = row.get(name)
            counts[name][value] = counts[name].get(value, 0) + 1
        if len(retained) >= args.top:
            break

    output_payload = {
        "event": "score_selected_cube_samples",
        "sample_json": str(args.sample_json.expanduser().resolve()),
        "parameters": {
            "top": args.top,
            "max_per_x0": args.max_per_x0,
            "max_per_x7": args.max_per_x7,
            "max_per_x2mid": args.max_per_x2mid,
            "max_per_x3low": args.max_per_x3low,
            "max_per_x3mid": args.max_per_x3mid,
            "max_per_x3high": args.max_per_x3high,
        },
        "input_records": len(rows),
        "scored_records": len(enriched),
        "retained_records": len(retained),
        "selector_counts": {
            name: {str(key): value for key, value in sorted(counter.items(), key=lambda item: str(item[0]))}
            for name, counter in counts.items()
        },
        "top": retained,
        "results": retained,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        console = dict(output_payload)
        console["top"] = f"{len(retained)} rows in {args.output}"
        console["results"] = f"{len(retained)} rows in {args.output}"
        print(json.dumps(console, sort_keys=True))
    else:
        print(f"status=completed retained={len(retained)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
