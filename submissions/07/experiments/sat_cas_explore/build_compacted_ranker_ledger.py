#!/usr/bin/env python3
"""Build a row-level compacted learned-clause JSONL for q-gap ranking."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--resume-list", action="append", default=[], type=Path)
parser.add_argument("--resume-jsonl", action="append", default=[], type=Path)
parser.add_argument("--output-jsonl", required=True, type=Path)
parser.add_argument("--summary-json", type=Path, default=None)
parser.add_argument("--max-records", type=int, default=12000)
parser.add_argument("--max-per-pair", type=int, default=2)
parser.add_argument("--max-per-source", type=int, default=4096)
parser.add_argument("--x2-range", default="265:8")
parser.add_argument("--x6-range", default="784:4")
args = parser.parse_args()

if args.max_records < 1:
    raise SystemExit("--max-records must be positive")
if args.max_per_pair < 1:
    raise SystemExit("--max-per-pair must be positive")
if args.max_per_source < 1:
    raise SystemExit("--max-per-source must be positive")

try:
    x2_start_text, x2_width_text = args.x2_range.split(":", 1)
    x6_start_text, x6_width_text = args.x6_range.split(":", 1)
    x2_start = int(x2_start_text, 0)
    x2_width = int(x2_width_text, 0)
    x6_start = int(x6_start_text, 0)
    x6_width = int(x6_width_text, 0)
except ValueError as exc:
    raise SystemExit("--x2-range and --x6-range must be START:WIDTH") from exc

resume_paths: list[Path] = []
for resume_list in args.resume_list:
    with resume_list.expanduser().open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line and not line.startswith("#"):
                resume_paths.append(Path(line))
resume_paths.extend(args.resume_jsonl)
resolved_paths = [path.expanduser().resolve() for path in resume_paths]

records: list[
    tuple[
        tuple[object, ...],
        int,
        dict[str, object],
        str,
        tuple[object, ...],
    ]
] = []
source_counts: Counter[str] = Counter()
status_counts: Counter[str] = Counter()
skipped_counts: Counter[str] = Counter()

for path_index, path in enumerate(resolved_paths):
    try:
        handle = path.open(encoding="utf-8")
    except OSError:
        skipped_counts["file_error"] += 1
        continue
    source_name = str(path)
    source_basename = path.name
    with handle:
        for line_index, raw_line in enumerate(handle):
            line = raw_line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                skipped_counts["parse_error"] += 1
                continue
            if not isinstance(row, dict) or row.get("event") != "cube":
                skipped_counts["not_cube"] += 1
                continue
            learned_clause = row.get("learned_clause")
            if learned_clause not in {
                "product_prefix_unsat",
                "q_gap_coppersmith_no_root",
                "low_coppersmith_no_root",
            }:
                skipped_counts["not_hard_clause"] += 1
                continue
            cube_ranges = row.get("cube_ranges")
            if not isinstance(cube_ranges, list):
                skipped_counts["missing_cube_ranges"] += 1
                continue

            bit_values: dict[int, int] = {}
            valid_ranges = True
            selected_literal_count = 0
            for raw_item in cube_ranges:
                if not isinstance(raw_item, dict):
                    valid_ranges = False
                    break
                try:
                    item_start = int(raw_item["start"])
                    item_width = int(raw_item["width"])
                    item_value = int(raw_item.get("value", 0))
                except (KeyError, TypeError, ValueError):
                    valid_ranges = False
                    break
                selected_literal_count += item_width
                for offset in range(item_width):
                    bit_values[item_start + offset] = (item_value >> offset) & 1
            if not valid_ranges:
                skipped_counts["invalid_cube_ranges"] += 1
                continue

            x2_value = 0
            x6_value = 0
            x2_ok = True
            x6_ok = True
            for offset in range(x2_width):
                bit = x2_start + offset
                if bit not in bit_values:
                    x2_ok = False
                    break
                x2_value |= bit_values[bit] << offset
            for offset in range(x6_width):
                bit = x6_start + offset
                if bit not in bit_values:
                    x6_ok = False
                    break
                x6_value |= bit_values[bit] << offset
            pair_key = (x2_value if x2_ok else None, x6_value if x6_ok else None)
            cap_pair_key: tuple[object, ...]
            if pair_key[0] is None or pair_key[1] is None:
                cap_pair_key = ("partial", source_name, line_index)
            else:
                cap_pair_key = ("pair", pair_key[0], pair_key[1])

            variants = row.get("learned_clause_variants")
            if isinstance(variants, list) and variants:
                variant_count = len(variants)
                literal_counts = [
                    int(raw_variant.get("literal_count", selected_literal_count))
                    for raw_variant in variants
                    if isinstance(raw_variant, dict)
                ]
                min_literal_count = min(literal_counts) if literal_counts else selected_literal_count
                variant_rank = 0
            else:
                variant_count = 1
                min_literal_count = int(row.get("learned_clause_literal_count") or selected_literal_count)
                variant_rank = 1

            q_gap = row.get("q_gap_coppersmith")
            q_gap_bits = None
            q_status = None
            if isinstance(q_gap, dict):
                q_status = q_gap.get("status")
                try:
                    q_gap_bits = int(q_gap.get("q_gap_bits"))
                except (TypeError, ValueError):
                    q_gap_bits = None
            status_counts[str(q_status or learned_clause)] += 1
            q_gap_rank = q_gap_bits if q_gap_bits is not None else 10**9
            hard_eligible = False
            if isinstance(q_gap, dict):
                hard_eligible = bool(
                    q_gap.get("no_root_hard_clause_eligible")
                    or q_gap.get("hard_clause_eligible")
                    or q_gap.get("hard_clause_bound_eligible")
                )
            hard_rank = 0 if hard_eligible or learned_clause == "product_prefix_unsat" else 1
            direct_bulk_rank = 1 if "after4956_all_model_top4090" in source_basename else 0
            source_recency_rank = -path_index
            score = (
                variant_rank,
                hard_rank,
                q_gap_rank,
                min_literal_count,
                direct_bulk_rank,
                source_recency_rank,
                -variant_count,
                pair_key[0] if pair_key[0] is not None else 10**9,
                pair_key[1] if pair_key[1] is not None else 10**9,
                line_index,
            )
            records.append((score, line_index, row, source_name, cap_pair_key))

records.sort(key=lambda item: item[0])
selected_rows: list[dict[str, object]] = []
selected_pair_counts: Counter[tuple[object, ...]] = Counter()
seen_clause_keys: set[str] = set()

for _, _, row, source_name, pair_key in records:
    if len(selected_rows) >= args.max_records:
        break
    if source_counts[source_name] >= args.max_per_source:
        skipped_counts["source_cap"] += 1
        continue
    if selected_pair_counts[pair_key] >= args.max_per_pair:
        skipped_counts["pair_cap"] += 1
        continue
    clause_key = json.dumps(row.get("cube_ranges"), sort_keys=True)
    variants = row.get("learned_clause_variants")
    if isinstance(variants, list):
        clause_key += "|" + json.dumps(
            [raw_variant.get("dropped_bits") for raw_variant in variants if isinstance(raw_variant, dict)],
            sort_keys=True,
        )
    else:
        clause_key += "|" + json.dumps(row.get("learned_clause_dropped_bits"), sort_keys=True)
    if clause_key in seen_clause_keys:
        skipped_counts["duplicate_clause"] += 1
        continue
    seen_clause_keys.add(clause_key)
    source_counts[source_name] += 1
    selected_pair_counts[pair_key] += 1
    selected_rows.append(row)

output_jsonl = args.output_jsonl.expanduser().resolve()
output_jsonl.parent.mkdir(parents=True, exist_ok=True)
with output_jsonl.open("w", encoding="utf-8") as handle:
    for row in selected_rows:
        print(json.dumps(row, sort_keys=True), file=handle)

summary = {
    "event": "build_compacted_ranker_ledger",
    "input_files": len(resolved_paths),
    "candidate_records": len(records),
    "selected_records": len(selected_rows),
    "selected_pairs": len(selected_pair_counts),
    "status_counts": dict(sorted(status_counts.items())),
    "skipped_counts": dict(sorted(skipped_counts.items())),
    "source_counts": dict(source_counts.most_common(25)),
    "parameters": {
        "max_records": args.max_records,
        "max_per_pair": args.max_per_pair,
        "max_per_source": args.max_per_source,
        "x2_range": args.x2_range,
        "x6_range": args.x6_range,
    },
    "output_jsonl": str(output_jsonl),
}
summary_json = args.summary_json.expanduser().resolve() if args.summary_json else output_jsonl.with_suffix(".summary.json")
summary_json.parent.mkdir(parents=True, exist_ok=True)
summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(summary, sort_keys=True))
