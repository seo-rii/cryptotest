#!/usr/bin/env python3
"""Compact analyzer for sat_cas_batch_runner.py JSONL output."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", help="JSONL files produced by sat_cas_batch_runner.py")
    parser.add_argument("--json", action="store_true", help="emit JSON summary")
    return parser.parse_args()


def read_records(paths: list[str]) -> tuple[list[dict[str, Any]], Counter[str]]:
    records: list[dict[str, Any]] = []
    errors: Counter[str] = Counter()
    for raw_path in paths:
        path = Path(raw_path)
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    errors[str(path)] += 1
                    continue
                if isinstance(record, dict):
                    record["_source"] = str(path)
                    records.append(record)
                else:
                    errors[str(path)] += 1
    return records, errors


def cube_range_key(record: dict[str, Any]) -> str:
    runner_ranges = record.get("runner_cube_ranges") or record.get("cube_ranges")
    if isinstance(runner_ranges, str):
        return runner_ranges
    if isinstance(runner_ranges, list):
        parts: list[str] = []
        for item in runner_ranges:
            if isinstance(item, dict):
                start = item.get("start")
                width = item.get("width")
                value = item.get("value", 0)
                parts.append(f"{start}:{width}={value}")
        if parts:
            return ",".join(parts)
    return "(unknown)"


def summarize(records: list[dict[str, Any]], parse_errors: Counter[str]) -> dict[str, Any]:
    event_counts: Counter[str] = Counter()
    learned_scope_counts: Counter[str] = Counter()
    learned_clause_counts: Counter[str] = Counter()
    product_prefix_counts: Counter[str] = Counter()
    low_coppersmith_status_counts: Counter[str] = Counter()
    q_gap_coppersmith_status_counts: Counter[str] = Counter()
    q_gap_bits_counts: Counter[str] = Counter()
    learned_literal_counts: Counter[str] = Counter()
    dropped_literal_counts: Counter[str] = Counter()
    dropped_bit_counts: Counter[str] = Counter()
    minimization_status_counts: Counter[str] = Counter()
    minimization_window_counts: Counter[str] = Counter()
    q_prefix_bits_counts: Counter[str] = Counter()
    cube_range_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    factored_events: list[dict[str, Any]] = []

    cube_count = 0
    summary_cube_count = 0
    summary_low_coppersmith_calls = 0
    summary_low_coppersmith_cache_hits = 0
    summary_low_coppersmith_hard_blocks = 0
    summary_hard_product_blocks = 0
    summary_low_coppersmith_minimized_blocks = 0
    summary_low_coppersmith_dropped_literals = 0
    summary_q_gap_coppersmith_calls = 0
    summary_q_gap_coppersmith_cache_hits = 0
    summary_q_gap_coppersmith_skips = 0
    summary_q_gap_coppersmith_hard_blocks = 0
    summary_q_gap_coppersmith_minimized_blocks = 0
    summary_q_gap_coppersmith_dropped_literals = 0
    summary_q_gap_coppersmith_independent_drop_clauses = 0
    summary_q_gap_coppersmith_independent_dropped_literals = 0
    summary_loaded_learned_clauses = 0
    summary_loaded_learned_literals = 0
    derived_loaded_learned_clauses = 0
    derived_loaded_learned_literals = 0
    derived_low_coppersmith_calls = 0
    derived_low_coppersmith_hard_blocks = 0
    derived_low_coppersmith_minimized_blocks = 0
    derived_low_coppersmith_dropped_literals = 0
    derived_q_gap_coppersmith_calls = 0
    derived_q_gap_coppersmith_hard_blocks = 0
    derived_q_gap_coppersmith_minimized_blocks = 0
    derived_q_gap_coppersmith_dropped_literals = 0
    derived_q_gap_coppersmith_independent_drop_clauses = 0
    derived_q_gap_coppersmith_independent_dropped_literals = 0
    derived_hard_product_blocks = 0
    runner_runs = 0
    runner_completed = 0
    runner_timeouts = 0

    for record in records:
        event = str(record.get("event", "(missing)"))
        event_counts[event] += 1
        source_counts[str(record.get("_source", "(unknown)"))] += 1

        if event == "runner_start":
            runner_runs += 1
        elif event == "runner_done":
            if record.get("returncode") == 0 and not record.get("timed_out"):
                runner_completed += 1
            if record.get("timed_out"):
                runner_timeouts += 1

        if event == "cube":
            cube_count += 1
            cube_range_counts[cube_range_key(record)] += 1
            product_prefix_status = record.get("product_prefix_status")
            if product_prefix_status is not None:
                product_prefix_counts[str(product_prefix_status)] += 1
            learned_clause = record.get("learned_clause")
            if learned_clause is not None:
                learned_clause_counts[str(learned_clause)] += 1
            scope = record.get("learned_clause_scope")
            if scope is not None:
                learned_scope_counts[str(scope)] += 1
            literal_count = record.get("learned_clause_literal_count")
            if literal_count is not None:
                learned_literal_counts[str(int(literal_count))] += 1
            dropped_literal_count = int(record.get("learned_clause_dropped_literal_count") or 0)
            if learned_clause == "low_coppersmith_no_root":
                dropped_literal_counts[str(dropped_literal_count)] += 1
            dropped_bits = record.get("learned_clause_dropped_bits")
            if isinstance(dropped_bits, list):
                for bit in dropped_bits:
                    dropped_bit_counts[str(int(bit))] += 1
            learned_clause_variants = record.get("learned_clause_variants")
            if isinstance(learned_clause_variants, list):
                derived_q_gap_coppersmith_independent_drop_clauses += len(learned_clause_variants)
                for variant in learned_clause_variants:
                    if not isinstance(variant, dict):
                        continue
                    variant_dropped_bits = variant.get("dropped_bits")
                    if isinstance(variant_dropped_bits, list):
                        derived_q_gap_coppersmith_independent_dropped_literals += len(variant_dropped_bits)
                        for bit in variant_dropped_bits:
                            dropped_bit_counts[str(int(bit))] += 1
            q_prefix_bits = record.get("q_prefix_bits")
            if q_prefix_bits is not None:
                q_prefix_bits_counts[str(int(q_prefix_bits))] += 1
            q_gap_trigger = record.get("q_gap_trigger")
            if isinstance(q_gap_trigger, dict) and q_gap_trigger.get("q_gap_bits") is not None:
                q_gap_bits_counts[str(int(q_gap_trigger["q_gap_bits"]))] += 1
            minimization_rows = record.get("low_coppersmith_minimization")
            if isinstance(minimization_rows, list):
                for row in minimization_rows:
                    if not isinstance(row, dict):
                        continue
                    minimization_status = row.get("status")
                    if minimization_status is not None:
                        minimization_status_counts[str(minimization_status)] += 1
                    drop_window = row.get("drop_window")
                    if isinstance(drop_window, dict):
                        start = drop_window.get("start")
                        width = drop_window.get("width")
                        if start is not None and width is not None:
                            minimization_window_counts[f"{start}:{width}"] += 1
            low_report = record.get("low_coppersmith")
            if isinstance(low_report, dict):
                low_status = low_report.get("status")
                if low_status is not None:
                    low_coppersmith_status_counts[str(low_status)] += 1
                derived_low_coppersmith_calls += 1
                if record.get("learned_clause") == "low_coppersmith_no_root":
                    derived_low_coppersmith_hard_blocks += 1
                if dropped_literal_count:
                    derived_low_coppersmith_minimized_blocks += 1
                    derived_low_coppersmith_dropped_literals += dropped_literal_count
                if low_report.get("status") == "factored":
                    factored_events.append(compact_factored(record, low_report))
            q_gap_report = record.get("q_gap_coppersmith")
            if isinstance(q_gap_report, dict):
                q_gap_status = q_gap_report.get("status")
                if q_gap_status is not None:
                    q_gap_coppersmith_status_counts[str(q_gap_status)] += 1
                derived_q_gap_coppersmith_calls += 1
                if q_gap_report.get("status") == "factored":
                    factored_events.append(compact_factored(record, q_gap_report))
            if record.get("learned_clause") == "q_gap_coppersmith_no_root":
                derived_q_gap_coppersmith_hard_blocks += 1
                if dropped_literal_count:
                    derived_q_gap_coppersmith_minimized_blocks += 1
                    derived_q_gap_coppersmith_dropped_literals += dropped_literal_count
                if learned_clause_variants:
                    derived_q_gap_coppersmith_minimized_blocks += 1
            if record.get("learned_clause") == "product_prefix_unsat":
                derived_hard_product_blocks += 1
        elif event == "summary":
            summary_cube_count += int(record.get("cubes") or 0)
            summary_low_coppersmith_calls += int(record.get("low_coppersmith_calls") or 0)
            summary_low_coppersmith_cache_hits += int(
                record.get("low_coppersmith_cache_hits") or 0
            )
            summary_low_coppersmith_hard_blocks += int(record.get("low_coppersmith_hard_blocks") or 0)
            summary_hard_product_blocks += int(record.get("hard_product_blocks") or 0)
            summary_low_coppersmith_minimized_blocks += int(
                record.get("low_coppersmith_minimized_blocks") or 0
            )
            summary_low_coppersmith_dropped_literals += int(
                record.get("low_coppersmith_dropped_literals") or 0
            )
            summary_q_gap_coppersmith_calls += int(record.get("q_gap_coppersmith_calls") or 0)
            summary_q_gap_coppersmith_cache_hits += int(
                record.get("q_gap_coppersmith_cache_hits") or 0
            )
            summary_q_gap_coppersmith_skips += int(record.get("q_gap_coppersmith_skips") or 0)
            summary_q_gap_coppersmith_hard_blocks += int(
                record.get("q_gap_coppersmith_hard_blocks") or 0
            )
            summary_q_gap_coppersmith_minimized_blocks += int(
                record.get("q_gap_coppersmith_minimized_blocks") or 0
            )
            summary_q_gap_coppersmith_dropped_literals += int(
                record.get("q_gap_coppersmith_dropped_literals") or 0
            )
            summary_q_gap_coppersmith_independent_drop_clauses += int(
                record.get("q_gap_coppersmith_independent_drop_clauses") or 0
            )
            summary_q_gap_coppersmith_independent_dropped_literals += int(
                record.get("q_gap_coppersmith_independent_dropped_literals") or 0
            )
            summary_loaded_learned_clauses += int(record.get("loaded_learned_clauses") or 0)
            summary_loaded_learned_literals += int(record.get("loaded_learned_literals") or 0)
        elif event == "loaded_learned_clauses":
            derived_loaded_learned_clauses += int(record.get("clauses_added") or 0)
            derived_loaded_learned_literals += int(record.get("literals_added") or 0)
        elif event == "factored":
            factored_events.append(compact_factored(record, record))

    return {
        "sources": dict(sorted(source_counts.items())),
        "records": len(records),
        "parse_errors": dict(sorted(parse_errors.items())),
        "events": dict(sorted(event_counts.items())),
        "runner": {
            "runs": runner_runs,
            "completed": runner_completed,
            "timeouts": runner_timeouts,
        },
        "cubes": cube_count or summary_cube_count,
        "cube_records": cube_count,
        "summary_cubes": summary_cube_count,
        "low_coppersmith_calls": summary_low_coppersmith_calls or derived_low_coppersmith_calls,
        "low_coppersmith_cache_hits": summary_low_coppersmith_cache_hits,
        "low_coppersmith_hard_blocks": (
            summary_low_coppersmith_hard_blocks or derived_low_coppersmith_hard_blocks
        ),
        "hard_product_blocks": summary_hard_product_blocks or derived_hard_product_blocks,
        "low_coppersmith_minimized_blocks": (
            summary_low_coppersmith_minimized_blocks or derived_low_coppersmith_minimized_blocks
        ),
        "low_coppersmith_dropped_literals": (
            summary_low_coppersmith_dropped_literals or derived_low_coppersmith_dropped_literals
        ),
        "q_gap_coppersmith_calls": summary_q_gap_coppersmith_calls or derived_q_gap_coppersmith_calls,
        "q_gap_coppersmith_cache_hits": summary_q_gap_coppersmith_cache_hits,
        "q_gap_coppersmith_skips": summary_q_gap_coppersmith_skips,
        "q_gap_coppersmith_hard_blocks": (
            summary_q_gap_coppersmith_hard_blocks or derived_q_gap_coppersmith_hard_blocks
        ),
        "q_gap_coppersmith_minimized_blocks": (
            summary_q_gap_coppersmith_minimized_blocks or derived_q_gap_coppersmith_minimized_blocks
        ),
        "q_gap_coppersmith_dropped_literals": (
            summary_q_gap_coppersmith_dropped_literals or derived_q_gap_coppersmith_dropped_literals
        ),
        "q_gap_coppersmith_independent_drop_clauses": (
            summary_q_gap_coppersmith_independent_drop_clauses
            or derived_q_gap_coppersmith_independent_drop_clauses
        ),
        "q_gap_coppersmith_independent_dropped_literals": (
            summary_q_gap_coppersmith_independent_dropped_literals
            or derived_q_gap_coppersmith_independent_dropped_literals
        ),
        "loaded_learned_clauses": summary_loaded_learned_clauses or derived_loaded_learned_clauses,
        "loaded_learned_literals": summary_loaded_learned_literals or derived_loaded_learned_literals,
        "factored_events": factored_events,
        "product_prefix_status": dict(sorted(product_prefix_counts.items())),
        "low_coppersmith_status": dict(sorted(low_coppersmith_status_counts.items())),
        "q_gap_coppersmith_status": dict(sorted(q_gap_coppersmith_status_counts.items())),
        "learned_clause": dict(sorted(learned_clause_counts.items())),
        "learned_clause_scope": dict(sorted(learned_scope_counts.items())),
        "learned_clause_literal_count_hist": dict(sorted(learned_literal_counts.items())),
        "learned_clause_dropped_literal_count_hist": dict(sorted(dropped_literal_counts.items())),
        "top_learned_clause_dropped_bits": [
            {"bit": int(bit), "count": count}
            for bit, count in dropped_bit_counts.most_common(16)
        ],
        "low_coppersmith_minimization_status": dict(sorted(minimization_status_counts.items())),
        "low_coppersmith_minimization_windows": dict(sorted(minimization_window_counts.items())),
        "q_gap_bits_hist": dict(sorted(q_gap_bits_counts.items())),
        "q_prefix_bits_hist": dict(sorted(q_prefix_bits_counts.items())),
        "top_cube_ranges": [
            {"cube_ranges": key, "cubes": count}
            for key, count in cube_range_counts.most_common(10)
        ],
    }


def compact_factored(record: dict[str, Any], low_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": record.get("_source"),
        "runner_run_index": record.get("runner_run_index"),
        "cube_index": record.get("index"),
        "cube_ranges": cube_range_key(record),
        "factors": low_report.get("factors", []),
        "status": low_report.get("status"),
    }


def print_text(summary: dict[str, Any]) -> None:
    print(f"records: {summary['records']}")
    print(f"sources: {', '.join(summary['sources'])}")
    if summary["parse_errors"]:
        print(f"parse_errors: {summary['parse_errors']}")
    print(
        "runner: "
        f"{summary['runner']['completed']}/{summary['runner']['runs']} completed, "
        f"{summary['runner']['timeouts']} timed out"
    )
    print(
        "cubes: "
        f"{summary['cubes']} "
        f"(cube_records={summary['cube_records']}, summary_cubes={summary['summary_cubes']})"
    )
    print(
        "blocks: "
        f"low_coppersmith_calls={summary['low_coppersmith_calls']}, "
        f"low_coppersmith_cache_hits={summary['low_coppersmith_cache_hits']}, "
        f"low_coppersmith_hard_blocks={summary['low_coppersmith_hard_blocks']}, "
        f"low_coppersmith_minimized_blocks={summary['low_coppersmith_minimized_blocks']}, "
        f"low_coppersmith_dropped_literals={summary['low_coppersmith_dropped_literals']}, "
        f"q_gap_coppersmith_calls={summary['q_gap_coppersmith_calls']}, "
        f"q_gap_coppersmith_cache_hits={summary['q_gap_coppersmith_cache_hits']}, "
        f"q_gap_coppersmith_skips={summary['q_gap_coppersmith_skips']}, "
        f"q_gap_coppersmith_hard_blocks={summary['q_gap_coppersmith_hard_blocks']}, "
        f"q_gap_coppersmith_minimized_blocks={summary['q_gap_coppersmith_minimized_blocks']}, "
        f"q_gap_coppersmith_dropped_literals={summary['q_gap_coppersmith_dropped_literals']}, "
        "q_gap_coppersmith_independent_drop_clauses="
        f"{summary['q_gap_coppersmith_independent_drop_clauses']}, "
        "q_gap_coppersmith_independent_dropped_literals="
        f"{summary['q_gap_coppersmith_independent_dropped_literals']}, "
        f"loaded_learned_clauses={summary['loaded_learned_clauses']}, "
        f"loaded_learned_literals={summary['loaded_learned_literals']}, "
        f"hard_product_blocks={summary['hard_product_blocks']}"
    )
    print(f"product_prefix_status: {summary['product_prefix_status'] or {}}")
    print(f"low_coppersmith_status: {summary['low_coppersmith_status'] or {}}")
    print(f"q_gap_coppersmith_status: {summary['q_gap_coppersmith_status'] or {}}")
    print(f"learned_clause: {summary['learned_clause'] or {}}")
    print(f"learned_clause_scope: {summary['learned_clause_scope'] or {}}")
    print(f"learned_clause_literal_count_hist: {summary['learned_clause_literal_count_hist'] or {}}")
    print(
        "learned_clause_dropped_literal_count_hist: "
        f"{summary['learned_clause_dropped_literal_count_hist'] or {}}"
    )
    print(
        "low_coppersmith_minimization_status: "
        f"{summary['low_coppersmith_minimization_status'] or {}}"
    )
    print(
        "low_coppersmith_minimization_windows: "
        f"{summary['low_coppersmith_minimization_windows'] or {}}"
    )
    print(f"q_gap_bits_hist: {summary['q_gap_bits_hist'] or {}}")
    print(f"q_prefix_bits_hist: {summary['q_prefix_bits_hist'] or {}}")
    if summary["top_learned_clause_dropped_bits"]:
        print("top_learned_clause_dropped_bits:")
        for item in summary["top_learned_clause_dropped_bits"]:
            print(f"  bit {item['bit']:>4}: {item['count']}")
    print(f"factored_events: {len(summary['factored_events'])}")
    for event in summary["factored_events"]:
        print(f"  factored: {json.dumps(event, sort_keys=True)}")
    print("top_cube_ranges:")
    for item in summary["top_cube_ranges"]:
        print(f"  {item['cubes']:>6}  {item['cube_ranges']}")


def main() -> int:
    args = parse_args()
    records, parse_errors = read_records(args.inputs)
    summary = summarize(records, parse_errors)
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print_text(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
