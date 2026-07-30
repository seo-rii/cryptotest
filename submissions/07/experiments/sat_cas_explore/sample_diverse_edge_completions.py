#!/usr/bin/env python3
"""Sample multiple full edge completions per ranked low-pair frontier."""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import z3

from q_middle_gap_oracle import q_gap_bound_report, q_gap_known_parts
from rank_q_gap_assumption_pairs import (
    bit_assumptions,
    parse_cube_ranges,
    parse_start_width,
    range_bit_values,
    read_resume_list,
)
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range
from semi_programmatic_sat import (
    add_bit_value_block_clause,
    compact_unit_ranges,
    load_learned_jsonl_clauses,
)


def cube_bit_values(raw_ranges: object) -> dict[int, int]:
    if not isinstance(raw_ranges, list):
        raise ValueError("missing cube_ranges")
    values: dict[int, int] = {}
    for raw_range in raw_ranges:
        if not isinstance(raw_range, dict):
            raise ValueError("invalid cube range item")
        start = int(raw_range["start"])
        width = int(raw_range["width"])
        value = int(raw_range.get("value", 0))
        if width <= 0 or value < 0 or value >= (1 << width):
            raise ValueError(f"invalid cube range {raw_range!r}")
        for offset in range(width):
            values[start + offset] = (value >> offset) & 1
    return values


def unique_pair_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[tuple[int, int], ...] | tuple[int, int]] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row.get("assumption_ranges"), list):
            try:
                assumption_values, _ = row_assumption_values(row, 0, 0, 0, 0)
            except (KeyError, TypeError, ValueError):
                continue
            key: tuple[tuple[int, int], ...] | tuple[int, int] = tuple(
                sorted(assumption_values.items())
            )
        else:
            try:
                key = (int(row["x2_value"]), int(row["x6_value"]))
            except (KeyError, TypeError, ValueError):
                continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def row_assumption_values(
    row: dict[str, Any],
    x2_start: int,
    x2_width: int,
    x6_start: int,
    x6_width: int,
) -> tuple[dict[int, int], list[str]]:
    raw_ranges = row.get("assumption_ranges")
    if isinstance(raw_ranges, list):
        values: dict[int, int] = {}
        labels: list[str] = []
        for raw_range in raw_ranges:
            if not isinstance(raw_range, dict):
                raise ValueError("invalid assumption range item")
            start = int(raw_range["start"])
            width = int(raw_range["width"])
            value = int(raw_range.get("value", 0))
            label = str(raw_range.get("label", f"{start}:{width}"))
            if width <= 0 or value < 0 or value >= (1 << width):
                raise ValueError(f"invalid assumption range {raw_range!r}")
            labels.append(f"{label}:{start}:{width}=0x{value:x}")
            for bit, bit_value in range_bit_values(start, width, value).items():
                previous = values.get(bit)
                if previous is not None and previous != bit_value:
                    raise ValueError(f"conflicting assumption for p bit {bit}")
                values[bit] = bit_value
        return values, labels

    x2_value = int(row["x2_value"])
    x6_value = int(row["x6_value"])
    return (
        {
            **range_bit_values(x2_start, x2_width, x2_value),
            **range_bit_values(x6_start, x6_width, x6_value),
        },
        [
            f"x2:{x2_start}:{x2_width}=0x{x2_value:x}",
            f"x6:{x6_start}:{x6_width}=0x{x6_value:x}",
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rank_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jsonl-output", type=Path)
    parser.add_argument("--top-pairs", type=int, default=64)
    parser.add_argument("--samples-per-pair", type=int, default=4)
    parser.add_argument("--max-total", type=int, default=0)
    parser.add_argument("--solver-timeout-ms", type=int, default=1000)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--cube-ranges", default="150:4,265:84,784:46,920:4")
    parser.add_argument("--x2-assume-range", default="265:8")
    parser.add_argument("--x6-assume-range", default="784:4")
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--resume-jsonl", action="append", default=[], type=Path)
    parser.add_argument("--resume-list", action="append", default=[], type=Path)
    parser.add_argument("--load-learned-limit", type=int, default=0)
    parser.add_argument(
        "--skip-learned-clauses",
        action="store_true",
        help="do not load resume JSONL clauses into Z3; use the rank JSON novelty only",
    )
    parser.add_argument("--include-source-cube-blocks", action="store_true")
    parser.add_argument("--random-assumption-bits", type=int, default=0)
    parser.add_argument("--random-assumption-retries", type=int, default=8)
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--no-random-fallback", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.top_pairs < 1:
        raise SystemExit("--top-pairs must be positive")
    if args.samples_per_pair < 1:
        raise SystemExit("--samples-per-pair must be positive")
    if args.max_total < 0:
        raise SystemExit("--max-total must be nonnegative")
    if args.solver_timeout_ms < 1:
        raise SystemExit("--solver-timeout-ms must be positive")
    if args.load_learned_limit < 0:
        raise SystemExit("--load-learned-limit must be nonnegative")
    if args.random_assumption_bits < 0:
        raise SystemExit("--random-assumption-bits must be nonnegative")
    if args.random_assumption_retries < 1:
        raise SystemExit("--random-assumption-retries must be positive")

    rank_payload = json.loads(args.rank_json.expanduser().read_text(encoding="utf-8"))
    ranked_rows = rank_payload.get("top")
    if not isinstance(ranked_rows, list):
        raise SystemExit(f"rank JSON has no top array: {args.rank_json}")
    pair_rows = unique_pair_rows([row for row in ranked_rows if isinstance(row, dict)])
    pair_rows = pair_rows[: args.top_pairs]
    if not pair_rows:
        raise SystemExit("no valid low-pair rows in rank JSON")

    resume_paths: list[Path] = []
    if not args.skip_learned_clauses:
        for resume_list in args.resume_list:
            resume_paths.extend(read_resume_list(resume_list.expanduser()))
        resume_paths.extend(args.resume_jsonl)
    ledgers = [path.expanduser().resolve() for path in resume_paths]

    instance = load_instance()
    fixed_ranges = list(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(fixed_ranges)
    all_unknown_bits = [bit for bit in range(instance.p_bits) if ((base_mask >> bit) & 1) == 0]
    bit_vars = {bit: z3.Bool(f"p_{bit}") for bit in all_unknown_bits}
    solver = z3.Solver()
    solver.set(timeout=args.solver_timeout_ms)

    if args.skip_learned_clauses:
        load_report = {
            "skipped": True,
            "reason": "skip_learned_clauses",
            "clauses_added": 0,
            "paths": 0,
        }
    else:
        load_report = load_learned_jsonl_clauses(
            solver=solver,
            bit_vars=bit_vars,
            base_known=base_known,
            base_mask=base_mask,
            p_bits=instance.p_bits,
            paths=[str(path) for path in ledgers],
            include_soft_blocks=False,
            limit=args.load_learned_limit,
        )

    cube_ranges = parse_cube_ranges(args.cube_ranges)
    selected_bits: list[int] = []
    for start, width in cube_ranges:
        selected_bits.extend(range(start, start + width))
    selected_bits = sorted(bit for bit in dict.fromkeys(selected_bits) if bit in bit_vars)
    if not selected_bits:
        raise SystemExit("cube selection has no currently unknown p bits")

    x2_start, x2_width = parse_start_width(args.x2_assume_range)
    x6_start, x6_width = parse_start_width(args.x6_assume_range)
    rng = random.Random(args.random_seed)

    if args.include_source_cube_blocks:
        for row in pair_rows:
            try:
                add_bit_value_block_clause(
                    solver=solver,
                    bit_vars=bit_vars,
                    base_known=base_known,
                    base_mask=base_mask,
                    p_bits=instance.p_bits,
                    bit_values=cube_bit_values(row.get("cube_ranges")),
                )
            except ValueError:
                continue

    started = time.time()
    records: list[dict[str, Any]] = []
    jsonl_handle = None
    if args.jsonl_output is not None:
        args.jsonl_output.parent.mkdir(parents=True, exist_ok=True)
        jsonl_handle = args.jsonl_output.open("w", encoding="utf-8")

    status_counts: dict[str, int] = {}
    pair_reports: list[dict[str, Any]] = []
    try:
        for pair_index, source_row in enumerate(pair_rows, start=1):
            assumption_values, assumption_labels = row_assumption_values(
                source_row,
                x2_start,
                x2_width,
                x6_start,
                x6_width,
            )
            x2_value = source_row.get("x2_value")
            x6_value = source_row.get("x6_value")
            random_candidate_bits = [
                bit for bit in selected_bits if bit not in assumption_values
            ]
            pair_sample_count = 0
            pair_status_counts: dict[str, int] = {}
            for sample_index in range(1, args.samples_per_pair + 1):
                if args.max_total and len(records) >= args.max_total:
                    break
                check_assumptions = bit_assumptions(bit_vars, assumption_values)
                random_values: dict[int, int] = {}
                random_attempts = 0
                if args.random_assumption_bits:
                    random_width = min(
                        args.random_assumption_bits, len(random_candidate_bits)
                    )
                    for random_attempts in range(1, args.random_assumption_retries + 1):
                        shuffled_bits = list(random_candidate_bits)
                        rng.shuffle(shuffled_bits)
                        random_values = {
                            bit: rng.randrange(2) for bit in shuffled_bits[:random_width]
                        }
                        check_assumptions = bit_assumptions(
                            bit_vars, {**assumption_values, **random_values}
                        )
                        result = solver.check(*check_assumptions)
                        if result == z3.sat:
                            break
                    else:
                        if args.no_random_fallback:
                            result = z3.unsat
                        else:
                            random_values = {}
                            check_assumptions = bit_assumptions(bit_vars, assumption_values)
                            result = solver.check(*check_assumptions)
                else:
                    result = solver.check(*check_assumptions)
                status = str(result)
                pair_status_counts[status] = pair_status_counts.get(status, 0) + 1
                status_counts[status] = status_counts.get(status, 0) + 1
                if result != z3.sat:
                    break

                model = solver.model()
                cube_unit_ranges: list[FixedRange] = []
                cube_values: dict[int, int] = {}
                for bit in selected_bits:
                    value = int(bool(model.eval(bit_vars[bit], model_completion=True)))
                    cube_values[bit] = value
                    cube_unit_ranges.append(FixedRange(bit, 1, value))

                p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges + cube_unit_ranges)
                q_known = derive_q_known_bits(instance, p_known, p_mask)
                q_parts = q_gap_known_parts(q_known, q_bits=instance.p_bits)
                q_bound = q_gap_bound_report(
                    n=instance.n,
                    low_bits=int(q_parts["low_bits"]),
                    prefix_start=int(q_parts["prefix_start"]),
                    epsilon=args.q_gap_epsilon,
                    min_hard_margin_bits=args.min_hard_margin_bits,
                )
                compact_ranges = compact_unit_ranges(cube_unit_ranges)
                record = {
                    "rank": len(records) + 1,
                    "status": "sat",
                    "source_pair_rank": pair_index,
                    "sample_index_in_pair": sample_index,
                    "x2_value": None if x2_value is None else int(x2_value),
                    "x6_value": None if x6_value is None else int(x6_value),
                    "source_assumption_ranges": assumption_labels,
                    "source_q_gap_bits": source_row.get("q_gap_bits"),
                    "source_pair_seen_count": source_row.get("pair_seen_count"),
                    "random_assumption_bits_requested": args.random_assumption_bits,
                    "random_assumption_bits_used": len(random_values),
                    "random_assumption_attempts": random_attempts,
                    "random_assumptions": [
                        f"{bit}:{value}" for bit, value in sorted(random_values.items())
                    ],
                    "q_low_bits": q_known.low_bits,
                    "q_prefix_bits": q_known.prefix_bits,
                    "q_prefix_start": q_known.prefix_start,
                    "q_known_bits": q_known.mask.bit_count(),
                    "q_gap_bits": int(q_parts["gap_bits"]),
                    "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                    "q_gap_hard_bound_eligible": bool(q_bound["hard_clause_bound_eligible"]),
                    "q_gap_effective_margin_bits": float(q_bound["effective_margin_bits"]),
                    "cube_ranges": compact_ranges,
                    "all_fixed_ranges_text": [
                        f"{item.start}:{item.width}=0x{item.value:x}"
                        for item in compact_ranges_to_fixed(compact_ranges)
                    ],
                }
                records.append(record)
                pair_sample_count += 1
                if jsonl_handle is not None:
                    print(json.dumps({"event": "sample", **record}, sort_keys=True), file=jsonl_handle)
                    jsonl_handle.flush()

                add_bit_value_block_clause(
                    solver=solver,
                    bit_vars=bit_vars,
                    base_known=base_known,
                    base_mask=base_mask,
                    p_bits=instance.p_bits,
                    bit_values=cube_values,
                )
            pair_reports.append(
                {
                    "source_pair_rank": pair_index,
                    "x2_value": None if x2_value is None else int(x2_value),
                    "x6_value": None if x6_value is None else int(x6_value),
                    "source_assumption_ranges": assumption_labels,
                    "samples": pair_sample_count,
                    "status_counts": pair_status_counts,
                }
            )
            if args.max_total and len(records) >= args.max_total:
                break
    finally:
        if jsonl_handle is not None:
            print(
                json.dumps(
                    {
                        "event": "summary",
                        "records": len(records),
                        "status_counts": status_counts,
                    },
                    sort_keys=True,
                ),
                file=jsonl_handle,
            )
            jsonl_handle.close()

    payload = {
        "event": "sample_diverse_edge_completions",
        "status": "completed",
        "rank_json": str(args.rank_json.expanduser().resolve()),
        "parameters": {
            "top_pairs": args.top_pairs,
            "samples_per_pair": args.samples_per_pair,
            "max_total": args.max_total,
            "solver_timeout_ms": args.solver_timeout_ms,
            "cube_ranges": args.cube_ranges,
            "x2_assume_range": args.x2_assume_range,
            "x6_assume_range": args.x6_assume_range,
            "include_source_cube_blocks": args.include_source_cube_blocks,
            "load_learned_limit": args.load_learned_limit,
            "skip_learned_clauses": args.skip_learned_clauses,
            "random_assumption_bits": args.random_assumption_bits,
            "random_assumption_retries": args.random_assumption_retries,
            "random_seed": args.random_seed,
            "no_random_fallback": args.no_random_fallback,
        },
        "loaded_ledgers": [str(path) for path in ledgers],
        "load_report": load_report,
        "elapsed_seconds": time.time() - started,
        "source_pairs": len(pair_rows),
        "records_completed": len(records),
        "status_counts": status_counts,
        "pair_reports": pair_reports,
        "top": records,
        "results": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        console = dict(payload)
        console["top"] = f"{len(records)} rows in {args.output}"
        console["results"] = f"{len(records)} rows in {args.output}"
        print(json.dumps(console, sort_keys=True))
    else:
        print(f"status=completed records={len(records)} output={args.output}")
    return 0


def compact_ranges_to_fixed(raw_ranges: list[dict[str, int]]) -> list[FixedRange]:
    return [
        FixedRange(int(item["start"]), int(item["width"]), int(item.get("value", 0)))
        for item in raw_ranges
    ]


if __name__ == "__main__":
    raise SystemExit(main())
