#!/usr/bin/env python3
"""Build synthetic SAT assumption frontiers for problem 7 samplers."""

from __future__ import annotations

import argparse
import itertools
import json
import random
from pathlib import Path

from rank_q_gap_assumption_pairs import parse_values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--range",
        action="append",
        default=[],
        help="assumption range LABEL:START:WIDTH:VALUES; VALUES accepts all, comma lists, or A-B",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    if not args.range:
        raise SystemExit("provide at least one --range LABEL:START:WIDTH:VALUES")
    if args.limit < 0:
        raise SystemExit("--limit must be nonnegative")

    parsed_ranges = []
    for raw_range in args.range:
        parts = raw_range.split(":", 3)
        if len(parts) != 4:
            raise SystemExit(f"invalid --range, expected LABEL:START:WIDTH:VALUES: {raw_range}")
        label, start_text, width_text, values_text = parts
        start = int(start_text, 0)
        width = int(width_text, 0)
        if not label:
            raise SystemExit(f"range label must be nonempty: {raw_range}")
        if start < 0 or width <= 0:
            raise SystemExit(f"invalid start/width in range: {raw_range}")
        values = parse_values(values_text, width)
        parsed_ranges.append(
            {
                "label": label,
                "start": start,
                "width": width,
                "values": values,
            }
        )

    products = itertools.product(*[item["values"] for item in parsed_ranges])
    rows = []
    for combo in products:
        assumption_ranges = []
        for item, value in zip(parsed_ranges, combo, strict=True):
            assumption_ranges.append(
                {
                    "label": item["label"],
                    "start": item["start"],
                    "width": item["width"],
                    "value": int(value),
                }
            )
        rows.append(
            {
                "rank": len(rows) + 1,
                "status": "synthetic",
                "assumption_ranges": assumption_ranges,
                "assumption_values_text": [
                    f"{item['label']}:{item['start']}:{item['width']}=0x{int(item['value']):x}"
                    for item in assumption_ranges
                ],
            }
        )

    if args.shuffle:
        random.Random(args.seed).shuffle(rows)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
    if args.limit:
        rows = rows[: args.limit]

    payload = {
        "event": "synthetic_assumption_frontier",
        "parameters": {
            "ranges": [
                {
                    "label": item["label"],
                    "start": item["start"],
                    "width": item["width"],
                    "values": [int(value) for value in item["values"]],
                    "value_count": len(item["values"]),
                }
                for item in parsed_ranges
            ],
            "limit": args.limit,
            "shuffle": args.shuffle,
            "seed": args.seed,
        },
        "top": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"status=completed rows={len(rows)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
