#!/usr/bin/env python3
"""Build a novelty frontier from learned p-window projection counts.

The output is a rank JSON consumable by sample_diverse_edge_completions.py.
It does not call Z3; it only avoids projection combinations that are already
overrepresented in existing JSONL ledgers.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_PROJECTION_RANGES = ("150:4:x0", "265:8:x2low8", "362:4:x3low4", "920:4:x7")


def read_manifest(path: Path) -> list[Path]:
    rows: list[Path] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append(Path(line))
    return rows


def parse_projection(text: str) -> tuple[int, int, str]:
    parts = text.split(":")
    if len(parts) not in {2, 3}:
        raise argparse.ArgumentTypeError("projection must be START:WIDTH[:LABEL]")
    start = int(parts[0], 0)
    width = int(parts[1], 0)
    if start < 0 or width <= 0:
        raise argparse.ArgumentTypeError("projection START must be nonnegative and WIDTH positive")
    label = parts[2] if len(parts) == 3 else f"{start}:{width}"
    return start, width, label


def range_bit_values(raw_ranges: object) -> dict[int, int] | None:
    if not isinstance(raw_ranges, list):
        return None
    bit_values: dict[int, int] = {}
    for raw_range in raw_ranges:
        if not isinstance(raw_range, dict):
            return None
        try:
            item_start = int(raw_range["start"])
            item_width = int(raw_range["width"])
            item_value = int(raw_range.get("value", 0))
        except (KeyError, TypeError, ValueError):
            return None
        if item_width <= 0 or item_value < 0 or item_value >= (1 << item_width):
            return None
        for offset in range(item_width):
            bit = item_start + offset
            bit_values[bit] = (item_value >> offset) & 1
    return bit_values


def compact_value(raw_ranges: object, start: int, width: int) -> int | None:
    bit_values = range_bit_values(raw_ranges)
    if bit_values is None:
        return None
    if any((start + offset) not in bit_values for offset in range(width)):
        return None
    value = 0
    for offset in range(width):
        value |= bit_values[start + offset] << offset
    return value


def cube_projection_key(
    raw_ranges: object,
    projections: list[tuple[int, int, str]],
) -> tuple[int, ...] | None:
    values: list[int] = []
    for start, width, _ in projections:
        value = compact_value(raw_ranges, start, width)
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def projection_key_variants(
    raw_ranges: object,
    projections: list[tuple[int, int, str]],
    dropped_bits: set[int],
    *,
    expansion_limit: int,
) -> tuple[list[tuple[int, ...]], str]:
    bit_values = range_bit_values(raw_ranges)
    if bit_values is None:
        return [], "missing_or_invalid_cube_ranges"

    projection_value_options: list[list[int]] = []
    expansion_count = 1
    for start, width, _ in projections:
        base_value = 0
        wildcard_offsets: list[int] = []
        for offset in range(width):
            bit = start + offset
            if bit not in bit_values:
                return [], "missing_projection_bits"
            if bit in dropped_bits:
                wildcard_offsets.append(offset)
            elif bit_values[bit]:
                base_value |= 1 << offset
        expansion_count *= 1 << len(wildcard_offsets)
        if expansion_count > expansion_limit:
            key = cube_projection_key(raw_ranges, projections)
            return ([key] if key is not None else []), "variant_expansion_limit_fallback_exact"
        values: list[int] = []
        for wildcard_value in range(1 << len(wildcard_offsets)):
            value = base_value
            for index, offset in enumerate(wildcard_offsets):
                if (wildcard_value >> index) & 1:
                    value |= 1 << offset
            values.append(value)
        projection_value_options.append(values)

    return [tuple(values) for values in itertools.product(*projection_value_options)], "ok"


def record_dropped_bit_sets(row: dict[str, Any]) -> list[set[int]]:
    variants = row.get("learned_clause_variants")
    if isinstance(variants, list) and variants:
        rows: list[set[int]] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            raw_dropped_bits = variant.get("dropped_bits")
            if not isinstance(raw_dropped_bits, list):
                rows.append(set())
                continue
            try:
                rows.append({int(bit) for bit in raw_dropped_bits})
            except (TypeError, ValueError):
                continue
        return rows or [set()]

    raw_dropped_bits = row.get("learned_clause_dropped_bits")
    if isinstance(raw_dropped_bits, list):
        try:
            return [{int(bit) for bit in raw_dropped_bits}]
        except (TypeError, ValueError):
            return [set()]
    return [set()]


def count_projection_keys(
    paths: list[Path],
    projections: list[tuple[int, int, str]],
    *,
    variant_expansion_limit: int,
) -> tuple[Counter[tuple[int, ...]], dict[str, int]]:
    counts: Counter[tuple[int, ...]] = Counter()
    stats = {
        "files": 0,
        "missing_files": 0,
        "records": 0,
        "cube_records": 0,
        "counted_cube_records": 0,
        "counted_projection_key_instances": 0,
        "variant_records": 0,
        "variant_projection_key_instances": 0,
        "variant_expansion_limit_fallback_exact": 0,
        "parse_errors": 0,
    }
    for path in paths:
        if not path.exists():
            stats["missing_files"] += 1
            continue
        stats["files"] += 1
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                stats["records"] += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    stats["parse_errors"] += 1
                    continue
                if not isinstance(row, dict) or row.get("event") != "cube":
                    continue
                stats["cube_records"] += 1
                variants = row.get("learned_clause_variants")
                dropped_bit_sets = record_dropped_bit_sets(row)
                if isinstance(variants, list) and variants:
                    stats["variant_records"] += 1
                counted_row = False
                for dropped_bits in dropped_bit_sets:
                    keys, status = projection_key_variants(
                        row.get("cube_ranges"),
                        projections,
                        dropped_bits,
                        expansion_limit=variant_expansion_limit,
                    )
                    if status == "variant_expansion_limit_fallback_exact":
                        stats["variant_expansion_limit_fallback_exact"] += 1
                    if not keys:
                        continue
                    for key in keys:
                        counts[key] += 1
                    stats["counted_projection_key_instances"] += len(keys)
                    if dropped_bits:
                        stats["variant_projection_key_instances"] += len(keys)
                    counted_row = True
                if not counted_row:
                    continue
                stats["counted_cube_records"] += 1
    return counts, stats


def key_to_assumption_ranges(
    key: tuple[int, ...],
    projections: list[tuple[int, int, str]],
) -> list[dict[str, int | str]]:
    ranges: list[dict[str, int | str]] = []
    for value, (start, width, label) in zip(key, projections, strict=True):
        ranges.append({"start": start, "width": width, "value": value, "label": label})
    return ranges


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--projection",
        action="append",
        default=[],
        type=parse_projection,
        help="START:WIDTH[:LABEL] projection to balance; repeatable",
    )
    parser.add_argument("--top", type=int, default=64)
    parser.add_argument("--candidate-pool", type=int, default=4096)
    parser.add_argument("--max-seen-count", type=int, default=0)
    parser.add_argument(
        "--variant-expansion-limit",
        type=int,
        default=4096,
        help="maximum projection keys to expand per learned-clause variant before falling back to the exact cube key",
    )
    parser.add_argument("--prefer-unseen", action="store_true")
    parser.add_argument("--seed", type=int, default=20260608)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.candidate_pool < args.top:
        raise SystemExit("--candidate-pool must be at least --top")
    if args.max_seen_count < 0:
        raise SystemExit("--max-seen-count must be nonnegative")
    if args.variant_expansion_limit < 1:
        raise SystemExit("--variant-expansion-limit must be positive")

    projections = args.projection or [parse_projection(item) for item in DEFAULT_PROJECTION_RANGES]
    total_space = 1
    for _, width, _ in projections:
        total_space *= 1 << width
    if total_space <= 0:
        raise SystemExit("empty projection space")

    manifest_paths = read_manifest(args.manifest.expanduser())
    counts, stats = count_projection_keys(
        manifest_paths,
        projections,
        variant_expansion_limit=args.variant_expansion_limit,
    )

    rng = random.Random(args.seed)
    candidate_keys: set[tuple[int, ...]] = set()
    widths = [width for _, width, _ in projections]
    if total_space <= args.candidate_pool:
        ranges = [range(1 << width) for width in widths]
        candidate_keys.update(tuple(values) for values in itertools.product(*ranges))
    else:
        attempts = 0
        max_attempts = max(args.candidate_pool * 100, args.candidate_pool + 1000)
        while len(candidate_keys) < args.candidate_pool and attempts < max_attempts:
            attempts += 1
            candidate_keys.add(tuple(rng.randrange(1 << width) for width in widths))
        if len(candidate_keys) < args.candidate_pool:
            ranges = [range(1 << width) for width in widths]
            for values in itertools.product(*ranges):
                candidate_keys.add(tuple(values))
                if len(candidate_keys) >= args.candidate_pool:
                    break

    def sort_key(key: tuple[int, ...]) -> tuple[int, float, tuple[int, ...]]:
        seen_count = counts.get(key, 0)
        unseen_rank = 0 if seen_count == 0 else 1
        if args.prefer_unseen:
            primary = unseen_rank
        else:
            primary = seen_count
        return (primary, rng.random(), key)

    eligible = [
        key
        for key in candidate_keys
        if args.max_seen_count == 0 or counts.get(key, 0) <= args.max_seen_count
    ]
    ranked_keys = sorted(eligible, key=sort_key)[: args.top]
    top = [
        {
            "rank": index,
            "status": "projection_candidate",
            "projection_key": list(key),
            "projection_seen_count": counts.get(key, 0),
            "assumption_ranges": key_to_assumption_ranges(key, projections),
        }
        for index, key in enumerate(ranked_keys, start=1)
    ]
    payload: dict[str, Any] = {
        "event": "build_projection_frontier",
        "status": "completed",
        "manifest": str(args.manifest.expanduser().resolve()),
        "parameters": {
            "projection": [
                {"start": start, "width": width, "label": label}
                for start, width, label in projections
            ],
            "top": args.top,
            "candidate_pool": args.candidate_pool,
            "max_seen_count": args.max_seen_count,
            "prefer_unseen": args.prefer_unseen,
            "seed": args.seed,
            "projection_space": total_space,
            "variant_expansion_limit": args.variant_expansion_limit,
        },
        "manifest_stats": stats,
        "unique_seen_projection_keys": len(counts),
        "candidate_keys": len(candidate_keys),
        "eligible_keys": len(eligible),
        "seen_count_histogram": {
            str(key): value
            for key, value in sorted(Counter(counts.values()).items())
        },
        "top": top,
        "results": top,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        console = dict(payload)
        console["top"] = f"{len(top)} rows in {args.output}"
        console["results"] = f"{len(top)} rows in {args.output}"
        print(json.dumps(console, sort_keys=True))
    else:
        print(
            "status=completed top={top} unique_seen={seen} output={output}".format(
                top=len(top),
                seen=len(counts),
                output=args.output,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
