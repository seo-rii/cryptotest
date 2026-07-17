#!/usr/bin/env python3
"""Rank guarded q-gap assumption pairs against the current learned ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import z3

from q_middle_gap_oracle import q_gap_bound_report, q_gap_known_parts
from sat_cas_core import (
    FixedRange,
    derive_q_known_bits,
    load_instance,
    parse_fixed_range,
    z3_hensel_prefix_status,
    z3_product_prefix_status,
)
from semi_programmatic_sat import compact_unit_ranges, load_learned_jsonl_clauses


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
DEFAULT_SCORE_HYBRID_CUMULATIVE_DROP_WINDOWS = ("150:4", "920:4")
DEFAULT_SCORE_HYBRID_INDEPENDENT_DROP_WINDOWS = ("265:8", "273:8", "784:8", "792:8")


def read_resume_list(path: Path) -> list[Path]:
    rows: list[Path] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append(Path(line))
    return rows


def parse_values(text: str, width: int) -> list[int]:
    text = text.strip()
    if text.lower() == "all":
        return list(range(1 << width))
    values: list[int] = []
    seen: set[int] = set()
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, stop_text = part.split("-", 1)
            start = int(start_text, 0)
            stop = int(stop_text, 0)
            if stop < start:
                raise argparse.ArgumentTypeError(f"invalid descending range: {part}")
            candidates = range(start, stop + 1)
        else:
            candidates = [int(part, 0)]
        for value in candidates:
            if value < 0 or value >= (1 << width):
                raise argparse.ArgumentTypeError(f"{value!r} does not fit {width} bits")
            if value not in seen:
                values.append(value)
                seen.add(value)
    if not values:
        raise argparse.ArgumentTypeError("expected at least one value")
    return values


def parse_start_width(text: str) -> tuple[int, int]:
    try:
        start_text, width_text = text.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    if start < 0 or width <= 0:
        raise argparse.ArgumentTypeError("START must be nonnegative and WIDTH positive")
    return start, width


def parse_cube_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for raw_item in text.split(","):
        item = raw_item.strip()
        if not item:
            continue
        ranges.append(parse_start_width(item))
    if not ranges:
        raise argparse.ArgumentTypeError("expected at least one cube range")
    return ranges


def range_bit_values(start: int, width: int, value: int) -> dict[int, int]:
    return {start + offset: (value >> offset) & 1 for offset in range(width)}


def bit_assumptions(
    bit_vars: dict[int, z3.BoolRef],
    bit_values: dict[int, int],
) -> list[z3.BoolRef]:
    return [
        bit_vars[bit] == bool(value)
        for bit, value in sorted(bit_values.items())
        if bit in bit_vars
    ]


def compact_value_from_record(raw_ranges: object, start: int, width: int) -> int | None:
    if not isinstance(raw_ranges, list):
        return None
    values: dict[int, int] = {}
    for raw_item in raw_ranges:
        if not isinstance(raw_item, dict):
            return None
        try:
            item_start = int(raw_item["start"])
            item_width = int(raw_item["width"])
            item_value = int(raw_item.get("value", 0))
        except (KeyError, TypeError, ValueError):
            return None
        for offset in range(item_width):
            bit = item_start + offset
            if start <= bit < start + width:
                values[bit] = (item_value >> offset) & 1
    if any(bit not in values for bit in range(start, start + width)):
        return None
    value = 0
    for offset in range(width):
        value |= values[start + offset] << offset
    return value


def seen_pair_counts(
    paths: list[Path],
    *,
    x2_start: int,
    x2_width: int,
    x6_start: int,
    x6_width: int,
) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}
    for path in paths:
        try:
            handle = path.open(encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict) or row.get("event") != "cube":
                    continue
                x2_value = compact_value_from_record(row.get("cube_ranges"), x2_start, x2_width)
                x6_value = compact_value_from_record(row.get("cube_ranges"), x6_start, x6_width)
                if x2_value is None or x6_value is None:
                    continue
                key = (x2_value, x6_value)
                counts[key] = counts.get(key, 0) + 1
    return counts


def format_cycle_values(values: list[int]) -> str:
    return ",".join(hex(value) for value in values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--top", type=int, default=16)
    parser.add_argument("--solver-timeout-ms", type=int, default=250)
    parser.add_argument("--check-bits", type=int, default=362)
    parser.add_argument("--prefix-core", choices=("bv", "hensel"), default="bv")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--cube-ranges", default="150:4,265:84,784:46,920:4")
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--resume-jsonl", action="append", default=[], type=Path)
    parser.add_argument("--resume-list", action="append", default=[], type=Path)
    parser.add_argument("--load-learned-limit", type=int, default=0)
    parser.add_argument("--include-seen-pairs", action="store_true")
    parser.add_argument(
        "--max-per-x2-value",
        type=int,
        default=0,
        help="0 disables the cap; otherwise retain at most this many top records per x2 value",
    )
    parser.add_argument(
        "--max-per-x6-value",
        type=int,
        default=0,
        help="0 disables the cap; otherwise retain at most this many top records per x6 value",
    )
    parser.add_argument("--x2-assume-range", default="265:8")
    parser.add_argument("--x6-assume-range", default="784:4")
    parser.add_argument("--x2-values", default="all")
    parser.add_argument("--x6-values", default="all")
    parser.add_argument(
        "--score-mode",
        choices=("legacy", "balanced"),
        default="legacy",
        help=(
            "legacy preserves the old q-gap-first ordering; balanced rescoring "
            "adds predicted hybrid drop q-gap cost for the best legacy candidates"
        ),
    )
    parser.add_argument(
        "--balanced-score-candidate-limit",
        type=int,
        default=512,
        help="number of legacy-ranked SAT records to rescore when --score-mode balanced is used; 0 scores all",
    )
    parser.add_argument(
        "--score-hybrid-cumulative-drop-window",
        action="append",
        default=[],
        help="START:WIDTH window used to estimate cumulative hybrid q-gap drop cost",
    )
    parser.add_argument(
        "--score-hybrid-independent-drop-window",
        action="append",
        default=[],
        help="START:WIDTH window used to estimate independent hybrid q-gap drop cost",
    )
    parser.add_argument("--score-max-completions", type=int, default=256)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.solver_timeout_ms < 1:
        raise SystemExit("--solver-timeout-ms must be positive")
    if args.load_learned_limit < 0:
        raise SystemExit("--load-learned-limit must be nonnegative")
    if args.max_per_x2_value < 0:
        raise SystemExit("--max-per-x2-value must be nonnegative")
    if args.max_per_x6_value < 0:
        raise SystemExit("--max-per-x6-value must be nonnegative")
    if args.balanced_score_candidate_limit < 0:
        raise SystemExit("--balanced-score-candidate-limit must be nonnegative")
    if args.score_max_completions < 1:
        raise SystemExit("--score-max-completions must be positive")

    x2_start, x2_width = parse_start_width(args.x2_assume_range)
    x6_start, x6_width = parse_start_width(args.x6_assume_range)
    x2_values = parse_values(args.x2_values, x2_width)
    x6_values = parse_values(args.x6_values, x6_width)
    cube_ranges = parse_cube_ranges(args.cube_ranges)
    score_hybrid_cumulative_drop_windows = [
        parse_start_width(raw)
        for raw in (
            args.score_hybrid_cumulative_drop_window
            or list(DEFAULT_SCORE_HYBRID_CUMULATIVE_DROP_WINDOWS)
        )
    ]
    score_hybrid_independent_drop_windows = [
        parse_start_width(raw)
        for raw in (
            args.score_hybrid_independent_drop_window
            or list(DEFAULT_SCORE_HYBRID_INDEPENDENT_DROP_WINDOWS)
        )
    ]
    for drop_start, drop_width in (
        score_hybrid_cumulative_drop_windows + score_hybrid_independent_drop_windows
    ):
        if 1 << drop_width > args.score_max_completions:
            raise SystemExit(
                f"score drop window {drop_start}:{drop_width} exceeds --score-max-completions"
            )

    resume_paths: list[Path] = []
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

    selected_bits: list[int] = []
    for start, width in cube_ranges:
        selected_bits.extend(range(start, start + width))
    selected_bits = sorted(bit for bit in dict.fromkeys(selected_bits) if bit in bit_vars)
    if not selected_bits:
        raise SystemExit("cube selection has no currently unknown p bits")

    pair_counts = seen_pair_counts(
        ledgers,
        x2_start=x2_start,
        x2_width=x2_width,
        x6_start=x6_start,
        x6_width=x6_width,
    )
    records: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    for x2_value in x2_values:
        x2_bits = range_bit_values(x2_start, x2_width, x2_value)
        for x6_value in x6_values:
            pair_key = (x2_value, x6_value)
            pair_seen_count = pair_counts.get(pair_key, 0)
            if pair_seen_count and not args.include_seen_pairs:
                status_counts["skipped_seen_pair"] = status_counts.get("skipped_seen_pair", 0) + 1
                continue

            assumption_values = {**x2_bits, **range_bit_values(x6_start, x6_width, x6_value)}
            result = solver.check(*bit_assumptions(bit_vars, assumption_values))
            status = str(result)
            status_counts[status] = status_counts.get(status, 0) + 1
            if result != z3.sat:
                records.append(
                    {
                        "status": status,
                        "x2_value": x2_value,
                        "x6_value": x6_value,
                        "pair_seen_count": pair_seen_count,
                    }
                )
                continue

            model = solver.model()
            cube_unit_ranges: list[FixedRange] = []
            for bit in selected_bits:
                value = int(bool(model.eval(bit_vars[bit], model_completion=True)))
                cube_unit_ranges.append(FixedRange(bit, 1, value))
            p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges + cube_unit_ranges)
            if args.prefix_core == "hensel":
                product_status, product_meta = z3_hensel_prefix_status(
                    instance=instance,
                    p_known=p_known,
                    p_mask=p_mask,
                    prefix_bits=args.check_bits,
                    timeout_ms=args.timeout_ms,
                )
            else:
                product_status, product_meta = z3_product_prefix_status(
                    instance=instance,
                    p_known=p_known,
                    p_mask=p_mask,
                    check_bits=args.check_bits,
                    timeout_ms=args.timeout_ms,
                    enumerate_p_free_limit=args.enumerate_p_free_limit,
                )
            q_known = derive_q_known_bits(instance, p_known, p_mask)
            q_parts = q_gap_known_parts(q_known, q_bits=instance.p_bits)
            q_gap_bits = int(q_parts["gap_bits"])
            residual_unknown_blocks: list[int] = []
            residual_position = 0
            while residual_position < instance.p_bits:
                residual_known_bit = (p_mask >> residual_position) & 1
                residual_start = residual_position
                while (
                    residual_position < instance.p_bits
                    and ((p_mask >> residual_position) & 1) == residual_known_bit
                ):
                    residual_position += 1
                if not residual_known_bit:
                    residual_unknown_blocks.append(residual_position - residual_start)
            bound = q_gap_bound_report(
                n=instance.n,
                low_bits=int(q_parts["low_bits"]),
                prefix_start=int(q_parts["prefix_start"]),
                epsilon=args.q_gap_epsilon,
                min_hard_margin_bits=args.min_hard_margin_bits,
            )
            records.append(
                {
                    "status": status,
                    "x2_value": x2_value,
                    "x6_value": x6_value,
                    "pair_seen_count": pair_seen_count,
                    "product_prefix_status": product_status,
                    "product_prefix": product_meta,
                    "q_low_bits": q_known.low_bits,
                    "q_prefix_bits": q_known.prefix_bits,
                    "q_prefix_start": q_known.prefix_start,
                    "q_known_bits": q_known.mask.bit_count(),
                    "q_gap_bits": q_gap_bits,
                    "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                    "q_gap_hard_bound_eligible": bool(bound["hard_clause_bound_eligible"]),
                    "q_gap_effective_margin_bits": bound["effective_margin_bits"],
                    "residual_partial_unknown_bits": instance.p_bits - p_mask.bit_count(),
                    "residual_partial_unknown_blocks": residual_unknown_blocks,
                    "residual_partial_product_bound_bits": sum(residual_unknown_blocks),
                    "cube_ranges": compact_unit_ranges(cube_unit_ranges),
                }
            )

    def legacy_record_score(row: dict[str, Any]) -> tuple[Any, ...]:
        sat_rank = 0 if row.get("status") == "sat" else 1
        prefix_rank = 0 if row.get("product_prefix_status") == "sat" else 1
        hard_rank = 0 if row.get("q_gap_hard_bound_eligible") else 1
        return (
            sat_rank,
            prefix_rank,
            hard_rank,
            int(row.get("q_gap_bits", 10**9)),
            -int(row.get("q_known_bits", -1)),
            int(row.get("q_interval_width_bits", 10**9)),
            int(row.get("pair_seen_count", 0)),
            int(row["x2_value"]),
            int(row["x6_value"]),
        )

    sat_records = [row for row in records if row.get("status") == "sat"]
    if args.score_mode == "balanced" and sat_records:
        score_source_records = sorted(sat_records, key=legacy_record_score)
        if args.balanced_score_candidate_limit:
            score_source_records = score_source_records[: args.balanced_score_candidate_limit]
        cumulative_drop_groups: list[list[tuple[int, int]]] = []
        current_cumulative_group: list[tuple[int, int]] = []
        for drop_window in score_hybrid_cumulative_drop_windows:
            current_cumulative_group = [*current_cumulative_group, drop_window]
            cumulative_drop_groups.append(current_cumulative_group)
        drop_groups = [
            ("cumulative", drop_windows) for drop_windows in cumulative_drop_groups
        ] + [
            ("independent", [drop_window])
            for drop_window in score_hybrid_independent_drop_windows
        ]
        for row in score_source_records:
            cube_unit_ranges: list[FixedRange] = []
            for raw_range in row.get("cube_ranges", []):
                item_start = int(raw_range["start"])
                item_width = int(raw_range["width"])
                item_value = int(raw_range.get("value", 0))
                for offset in range(item_width):
                    cube_unit_ranges.append(
                        FixedRange(item_start + offset, 1, (item_value >> offset) & 1)
                    )

            score_gap_bits = int(row.get("q_gap_bits", 10**9))
            score_q_known_bits_min = int(row.get("q_known_bits", 0))
            score_interval_width_bits_max = int(row.get("q_interval_width_bits", 10**9))
            score_effective_margin_bits_min = float(row.get("q_gap_effective_margin_bits", 0.0))
            score_completion_count = 1
            score_hard_completion_count = 1 if row.get("q_gap_hard_bound_eligible") else 0
            score_conflict_count = 0
            score_truncated = False

            for _, drop_windows in drop_groups:
                completion_width = sum(width for _, width in drop_windows)
                completion_count = 1 << completion_width
                if completion_count > args.score_max_completions:
                    score_truncated = True
                    continue
                dropped_bits = {
                    bit
                    for drop_start, drop_width in drop_windows
                    for bit in range(drop_start, drop_start + drop_width)
                }
                retained_cube_units = [
                    item for item in cube_unit_ranges if item.start not in dropped_bits
                ]
                for completion in range(completion_count):
                    offset = 0
                    completion_ranges: list[FixedRange] = []
                    for drop_start, drop_width in drop_windows:
                        value = (completion >> offset) & ((1 << drop_width) - 1)
                        offset += drop_width
                        completion_ranges.append(FixedRange(drop_start, drop_width, value))
                    try:
                        completion_known, completion_mask = instance.apply_fixed_ranges(
                            fixed_ranges + retained_cube_units + completion_ranges
                        )
                        completion_q_known = derive_q_known_bits(
                            instance, completion_known, completion_mask
                        )
                    except ValueError:
                        score_conflict_count += 1
                        continue
                    completion_q_parts = q_gap_known_parts(
                        completion_q_known, q_bits=instance.p_bits
                    )
                    completion_gap_bits = int(completion_q_parts["gap_bits"])
                    completion_bound = q_gap_bound_report(
                        n=instance.n,
                        low_bits=int(completion_q_parts["low_bits"]),
                        prefix_start=int(completion_q_parts["prefix_start"]),
                        epsilon=args.q_gap_epsilon,
                        min_hard_margin_bits=args.min_hard_margin_bits,
                    )
                    score_completion_count += 1
                    if completion_bound["hard_clause_bound_eligible"]:
                        score_hard_completion_count += 1
                    score_gap_bits = max(score_gap_bits, completion_gap_bits)
                    score_q_known_bits_min = min(
                        score_q_known_bits_min, completion_q_known.mask.bit_count()
                    )
                    score_interval_width_bits_max = max(
                        score_interval_width_bits_max,
                        (completion_q_known.q_max - completion_q_known.q_min).bit_length(),
                    )
                    score_effective_margin_bits_min = min(
                        score_effective_margin_bits_min,
                        float(completion_bound["effective_margin_bits"]),
                    )

            row["score_q_gap_bits"] = score_gap_bits
            row["score_q_known_bits_min"] = score_q_known_bits_min
            row["score_q_interval_width_bits_max"] = score_interval_width_bits_max
            row["score_q_gap_effective_margin_bits_min"] = score_effective_margin_bits_min
            row["score_q_gap_completion_count"] = score_completion_count
            row["score_q_gap_hard_completion_count"] = score_hard_completion_count
            row["score_q_gap_conflict_count"] = score_conflict_count
            row["score_q_gap_truncated"] = score_truncated

    def record_score(row: dict[str, Any]) -> tuple[Any, ...]:
        if args.score_mode == "legacy":
            return legacy_record_score(row)
        sat_rank = 0 if row.get("status") == "sat" else 1
        prefix_status = row.get("product_prefix_status")
        prefix_rank = 0 if prefix_status == "sat" else 1 if prefix_status == "unknown" else 2
        hard_rank = 0 if row.get("q_gap_hard_bound_eligible") else 1
        scored_rank = 0 if "score_q_gap_bits" in row else 1
        return (
            sat_rank,
            prefix_rank,
            hard_rank,
            scored_rank,
            int(row.get("score_q_gap_bits", row.get("q_gap_bits", 10**9))),
            -int(row.get("score_q_known_bits_min", row.get("q_known_bits", -1))),
            int(
                row.get(
                    "score_q_interval_width_bits_max",
                    row.get("q_interval_width_bits", 10**9),
                )
            ),
            int(row.get("residual_partial_product_bound_bits", 10**9)),
            int(row.get("residual_partial_unknown_bits", 10**9)),
            int(row.get("score_q_gap_truncated", False)),
            int(row.get("pair_seen_count", 0)),
            int(row["x2_value"]),
            int(row["x6_value"]),
        )

    ranked_records = sorted(sat_records, key=record_score)
    top_records: list[dict[str, Any]] = []
    x2_retained_counts: dict[int, int] = {}
    x6_retained_counts: dict[int, int] = {}
    for row in ranked_records:
        x2_value = int(row["x2_value"])
        x6_value = int(row["x6_value"])
        if args.max_per_x2_value and x2_retained_counts.get(x2_value, 0) >= args.max_per_x2_value:
            continue
        if args.max_per_x6_value and x6_retained_counts.get(x6_value, 0) >= args.max_per_x6_value:
            continue
        top_records.append(row)
        x2_retained_counts[x2_value] = x2_retained_counts.get(x2_value, 0) + 1
        x6_retained_counts[x6_value] = x6_retained_counts.get(x6_value, 0) + 1
        if len(top_records) >= args.top:
            break
    x2_cycle_values = [int(row["x2_value"]) for row in top_records]
    x6_cycle_values = [int(row["x6_value"]) for row in top_records]
    resume_args = " ".join(f"--resume-jsonl {path}" for path in ledgers)
    run_command = None
    if top_records:
        run_command = (
            "python3 cryptotest/solutions/07_sat_cas_explore/run_fullx1x5_drop_loop.py "
            "--iterations {iterations} --workers 8 --output-dir tmp/ct07_ranked_qgap_pairs_run "
            "{resume_args} "
            "--drop-mode hybrid --q-gap-epsilon {epsilon} --q-gap-max-bits {max_bits} "
            "--q-gap-minimize-max-completions 256 "
            "--cube-assume-p-range-cycle {x2_start}:{x2_width}:{x2_values} "
            "--cube-assume-p-range-cycle {x6_start}:{x6_width}:{x6_values} --json"
        ).format(
            iterations=len(top_records),
            resume_args=resume_args,
            epsilon=args.q_gap_epsilon,
            max_bits=args.q_gap_max_bits,
            x2_start=x2_start,
            x2_width=x2_width,
            x2_values=format_cycle_values(x2_cycle_values),
            x6_start=x6_start,
            x6_width=x6_width,
            x6_values=format_cycle_values(x6_cycle_values),
        )

    payload = {
        "event": "rank_q_gap_assumption_pairs",
        "parameters": {
            "x2_assume_range": args.x2_assume_range,
            "x6_assume_range": args.x6_assume_range,
            "x2_values": args.x2_values,
            "x6_values": args.x6_values,
            "cube_ranges": args.cube_ranges,
            "q_gap_epsilon": args.q_gap_epsilon,
            "q_gap_max_bits": args.q_gap_max_bits,
            "prefix_core": args.prefix_core,
            "score_mode": args.score_mode,
            "balanced_score_candidate_limit": args.balanced_score_candidate_limit,
            "score_hybrid_cumulative_drop_windows": [
                f"{start}:{width}" for start, width in score_hybrid_cumulative_drop_windows
            ],
            "score_hybrid_independent_drop_windows": [
                f"{start}:{width}" for start, width in score_hybrid_independent_drop_windows
            ],
            "score_max_completions": args.score_max_completions,
            "include_seen_pairs": args.include_seen_pairs,
            "max_per_x2_value": args.max_per_x2_value,
            "max_per_x6_value": args.max_per_x6_value,
            "load_learned_limit": args.load_learned_limit,
        },
        "loaded_ledgers": [str(path) for path in ledgers],
        "load_report": load_report,
        "pair_seen_count": len(pair_counts),
        "status_counts": dict(sorted(status_counts.items())),
        "evaluated_records": len(records),
        "sat_records": len(sat_records),
        "ranked_records": len(ranked_records),
        "retained_x2_counts": dict(sorted(x2_retained_counts.items())),
        "retained_x6_counts": dict(sorted(x6_retained_counts.items())),
        "top": top_records,
        "run_command_template": run_command,
    }
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            "loaded={clauses} sat={sat} records={records} skipped_seen={seen}".format(
                clauses=load_report.get("clauses_added"),
                sat=len(sat_records),
                records=len(records),
                seen=status_counts.get("skipped_seen_pair", 0),
            )
        )
        for index, row in enumerate(top_records, start=1):
            print(
                "#{index:02d} x2=0x{x2:x} x6=0x{x6:x} "
                "gap={gap} margin={margin:.2f} prefix={prefix} "
                "q_low={q_low} q_prefix_start={q_prefix_start} seen={seen} "
                "cube={cube}".format(
                    index=index,
                    x2=int(row["x2_value"]),
                    x6=int(row["x6_value"]),
                    gap=int(row["q_gap_bits"]),
                    margin=float(row["q_gap_effective_margin_bits"]),
                    prefix=row.get("product_prefix_status"),
                    q_low=int(row["q_low_bits"]),
                    q_prefix_start=int(row["q_prefix_start"]),
                    seen=int(row["pair_seen_count"]),
                    cube=",".join(
                        f"{item['start']}:{item['width']}={item['value']}"
                        for item in row.get("cube_ranges", [])
                    ),
                )
            )
        if run_command:
            print(run_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
