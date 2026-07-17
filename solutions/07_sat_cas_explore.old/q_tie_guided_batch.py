#!/usr/bin/env python3
"""Run low-prefix SAT/CAS probes from full-x6 q-prefix tie groups."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from q_interval_sweep import compact_ranges, parse_cube_ranges
from q_prefix_growth_search import iter_limited_cubes, summarize_candidate
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


HERE = Path(__file__).resolve().parent
DEFAULT_FIX_P_RANGE = "784:46:0x245521490bd"
DEFAULT_TIE_RANGES = "150:4,920:4"
DEFAULT_LOW_RANGES = "210:39,265:84,362:78"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_fixed_range,
        help=(
            "fixed p-bit range START:WIDTH:VALUE; if omitted, defaults to "
            f"full x6 {DEFAULT_FIX_P_RANGE}"
        ),
    )
    parser.add_argument(
        "--tie-ranges",
        default=DEFAULT_TIE_RANGES,
        help="START:WIDTH ranges enumerated to form q-prefix tie groups",
    )
    parser.add_argument(
        "--low-ranges",
        default=DEFAULT_LOW_RANGES,
        help="START:WIDTH ranges passed to deterministic_low_runner.py",
    )
    parser.add_argument("--max-tie-cubes", type=int, default=256)
    parser.add_argument("--max-high-candidates", type=int, default=3)
    parser.add_argument("--max-low-cubes", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--check-bits", type=int, default=608)
    parser.add_argument("--timeout-ms", type=int, default=500)
    parser.add_argument("--low-coppersmith-bits", type=int, default=600)
    parser.add_argument("--low-coppersmith-epsilon", type=float, default=0.02)
    parser.add_argument("--low-coppersmith-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--json", action="store_true", help="emit compact JSON")
    return parser.parse_args()


def format_fixed_range(item: FixedRange) -> str:
    return f"{item.start}:{item.width}:{hex(item.value)}"


def fixed_ranges_from_compact(items: list[dict[str, Any]]) -> list[FixedRange]:
    return [
        FixedRange(int(item["start"]), int(item["width"]), int(item["value"]))
        for item in items
    ]


def low_literal_count_from_compact(items: object, low_bits: int) -> int:
    if not isinstance(items, list):
        return 0
    literal_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        start = int(item["start"])
        width = int(item["width"])
        if start >= low_bits:
            continue
        literal_count += min(width, low_bits - start)
    return literal_count


def sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def normalize_timeout_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return ""


def parse_json_lines(text: str) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    parse_errors = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if isinstance(record, dict):
            records.append(record)
        else:
            parse_errors += 1
    return records, parse_errors


def build_tie_candidates(args: argparse.Namespace) -> dict[str, Any]:
    instance = load_instance()
    base_ranges: list[FixedRange] = list(args.fix_p_range)
    used_default_fix = not base_ranges
    if used_default_fix:
        base_ranges = [parse_fixed_range(DEFAULT_FIX_P_RANGE)]

    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)
    base_q_known_bits = base_q.mask.bit_count()
    base_p_fixed_bits = base_mask.bit_count()

    rows: list[dict[str, Any]] = []
    parsed_tie_ranges = parse_cube_ranges(args.tie_ranges)
    for index, cube in enumerate(
        iter_limited_cubes(parsed_tie_ranges, args.max_tie_cubes),
        start=1,
    ):
        rows.append(
            summarize_candidate(
                instance,
                base_ranges,
                cube,
                args.tie_ranges,
                index,
                base_q_known_bits,
                base_q.low_bits,
                base_q.prefix_bits,
                base_p_fixed_bits,
            )
        )

    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["q_prefix_bits"]), int(row["q_known_bits"]))].append(row)

    groups: list[dict[str, Any]] = []
    for (q_prefix_bits, q_known_bits), candidates in grouped.items():
        groups.append(
            {
                "q_prefix_bits": q_prefix_bits,
                "q_known_bits": q_known_bits,
                "count": len(candidates),
                "min_q_interval_width_bits": min(
                    int(item["q_interval_width_bits"]) for item in candidates
                ),
                "max_q_interval_width_bits": max(
                    int(item["q_interval_width_bits"]) for item in candidates
                ),
            }
        )
    groups.sort(
        key=lambda item: (
            -int(item["q_prefix_bits"]),
            -int(item["q_known_bits"]),
            -int(item["count"]),
        )
    )

    selected: list[dict[str, Any]] = []
    for group_rank, group in enumerate(groups, start=1):
        key = (int(group["q_prefix_bits"]), int(group["q_known_bits"]))
        candidates = sorted(
            grouped[key],
            key=lambda item: (
                int(item["q_interval_width_bits"]),
                tuple(
                    (int(fixed["start"]), int(fixed["width"]), int(fixed["value"]))
                    for fixed in item["fixed_ranges"]
                ),
            ),
        )
        for candidate in candidates:
            candidate = dict(candidate)
            candidate["group_rank"] = group_rank
            candidate["selected_rank"] = len(selected) + 1
            selected.append(candidate)
            if len(selected) >= args.max_high_candidates:
                break
        if len(selected) >= args.max_high_candidates:
            break

    return {
        "base_ranges": base_ranges,
        "used_default_full_x6": used_default_fix,
        "summary": {
            "used_default_full_x6": used_default_fix,
            "base_fixed_ranges": compact_ranges(base_ranges),
            "base_p_fixed_bits": base_p_fixed_bits,
            "base_q_low_bits": base_q.low_bits,
            "base_q_prefix_bits": base_q.prefix_bits,
            "base_q_prefix_start": base_q.prefix_start,
            "base_q_known_bits": base_q_known_bits,
            "tie_ranges": args.tie_ranges,
            "tie_range_specs": [
                {"start": item.start, "width": item.width}
                for item in parsed_tie_ranges
            ],
            "emitted_tie_cubes": len(rows),
            "group_count": len(groups),
            "groups": groups,
        },
        "selected": selected,
    }


def build_child_command(
    args: argparse.Namespace,
    base_ranges: list[FixedRange],
    candidate: dict[str, Any],
) -> list[str]:
    fixed_ranges = base_ranges + fixed_ranges_from_compact(candidate["fixed_ranges"])
    command = [
        sys.executable,
        str(HERE / "deterministic_low_runner.py"),
        "--low-ranges",
        args.low_ranges,
        "--max-low-cubes",
        str(args.max_low_cubes),
        "--check-bits",
        str(args.check_bits),
        "--prefix-core",
        "bv",
        "--timeout-ms",
        str(args.timeout_ms),
        "--run-low-coppersmith",
        "--low-coppersmith-hard-fail",
        "--low-coppersmith-bits",
        str(args.low_coppersmith_bits),
        "--low-coppersmith-epsilon",
        str(args.low_coppersmith_epsilon),
        "--low-coppersmith-min-hard-margin-bits",
        str(args.low_coppersmith_min_hard_margin_bits),
        "--include-ranges",
        "--jsonl",
    ]
    for fixed_range in fixed_ranges:
        command.extend(["--fix-p-range", format_fixed_range(fixed_range)])
    return command


def summarize_child_records(
    candidate: dict[str, Any],
    command: list[str],
    records: list[dict[str, Any]],
    parse_errors: int,
    returncode: int | None,
    timed_out: bool,
    elapsed_seconds: float,
    stderr: str,
    low_coppersmith_bits: int,
) -> dict[str, Any]:
    prefix_status_counts: Counter[str] = Counter()
    learned_literal_counts: Counter[str] = Counter()
    child_learned_literal_counts: Counter[str] = Counter()
    learned_clause_counts: Counter[str] = Counter()
    q_prefix_observed: list[int] = []
    factored_events: list[dict[str, Any]] = []
    low_calls = 0
    low_hard_blocks = 0
    cubes = 0
    summary: dict[str, Any] = {}

    for record in records:
        if record.get("q_prefix_bits") is not None:
            q_prefix_observed.append(int(record["q_prefix_bits"]))
        details = record.get("details")
        if isinstance(details, dict) and details.get("q_prefix_bits") is not None:
            q_prefix_observed.append(int(details["q_prefix_bits"]))

        if record.get("event") == "cube":
            cubes += 1
            prefix_status_counts[str(record.get("product_prefix_status", "missing"))] += 1
            learned_clause_counts[str(record.get("learned_clause", "missing"))] += 1
            if record.get("learned_clause_literal_count") is not None:
                child_learned_literal_counts[str(record["learned_clause_literal_count"])] += 1
            low_report = record.get("low_coppersmith")
            if isinstance(low_report, dict):
                low_calls += 1
                if low_report.get("status") == "factored":
                    factored_events.append(
                        {
                            "selected_rank": candidate["selected_rank"],
                            "high_index": record.get("high_index"),
                            "low_index": record.get("low_index"),
                            "status": low_report.get("status"),
                            "factors": low_report.get("factors", []),
                        }
                    )
            if record.get("learned_clause") == "low_coppersmith_no_root":
                low_hard_blocks += 1
                sound_literal_count = low_literal_count_from_compact(
                    candidate["fixed_ranges"],
                    low_coppersmith_bits,
                ) + low_literal_count_from_compact(
                    record.get("low_fixed_ranges"),
                    low_coppersmith_bits,
                )
                if sound_literal_count:
                    learned_literal_counts[str(sound_literal_count)] += 1
        elif record.get("event") == "summary":
            summary = record

    if summary:
        cubes = cubes or int(summary.get("cubes") or 0)
        low_calls = low_calls or int(summary.get("low_coppersmith_calls") or 0)
        low_hard_blocks = low_hard_blocks or int(
            summary.get("low_coppersmith_hard_blocks") or 0
        )
        if not prefix_status_counts:
            for key in ("prefix_sat", "prefix_unsat", "prefix_unknown"):
                value = int(summary.get(key) or 0)
                if value:
                    prefix_status_counts[key.removeprefix("prefix_")] += value

    return {
        "selected_rank": candidate["selected_rank"],
        "group_rank": candidate["group_rank"],
        "candidate_q_prefix_bits": candidate["q_prefix_bits"],
        "candidate_q_known_bits": candidate["q_known_bits"],
        "candidate_fixed_ranges": candidate["fixed_ranges"],
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "records": len(records),
        "parse_errors": parse_errors,
        "cubes": cubes,
        "prefix_status_counts": sorted_counter(prefix_status_counts),
        "low_coppersmith_calls": low_calls,
        "low_coppersmith_hard_blocks": low_hard_blocks,
        "learned_clause_counts": sorted_counter(learned_clause_counts),
        "learned_literal_counts": sorted_counter(learned_literal_counts),
        "child_learned_literal_counts": sorted_counter(child_learned_literal_counts),
        "factored_events": factored_events,
        "q_prefix_bits_observed": sorted(set(q_prefix_observed)),
        "q_prefix_bits_observed_max": max(q_prefix_observed) if q_prefix_observed else None,
        "stderr_tail": [line for line in stderr.splitlines() if line.strip()][-5:],
    }


def run_candidate(
    args: argparse.Namespace,
    base_ranges: list[FixedRange],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    command = build_child_command(args, base_ranges, candidate)
    started_at = time.time()
    try:
        process = subprocess.run(
            command,
            cwd=HERE,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(1.0, args.timeout_seconds),
            check=False,
        )
        elapsed = time.time() - started_at
        records, parse_errors = parse_json_lines(process.stdout)
        return summarize_child_records(
            candidate,
            command,
            records,
            parse_errors,
            process.returncode,
            False,
            elapsed,
            process.stderr,
            args.low_coppersmith_bits,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - started_at
        stdout = normalize_timeout_text(exc.stdout)
        stderr = normalize_timeout_text(exc.stderr)
        records, parse_errors = parse_json_lines(stdout)
        return summarize_child_records(
            candidate,
            command,
            records,
            parse_errors,
            None,
            True,
            elapsed,
            stderr,
            args.low_coppersmith_bits,
        )


def aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    prefix_status_counts: Counter[str] = Counter()
    learned_literal_counts: Counter[str] = Counter()
    learned_clause_counts: Counter[str] = Counter()
    q_prefix_observed: set[int] = set()
    factored_events: list[dict[str, Any]] = []
    error_details: list[dict[str, Any]] = []

    cubes = 0
    low_calls = 0
    low_hard_blocks = 0
    timeouts = 0
    process_errors = 0
    parse_errors = 0
    stderr_runs = 0

    for run in runs:
        cubes += int(run["cubes"])
        low_calls += int(run["low_coppersmith_calls"])
        low_hard_blocks += int(run["low_coppersmith_hard_blocks"])
        parse_errors += int(run["parse_errors"])
        if run["timed_out"]:
            timeouts += 1
        if run["returncode"] not in (0, None):
            process_errors += 1
        if run["stderr_tail"]:
            stderr_runs += 1
        prefix_status_counts.update(run["prefix_status_counts"])
        learned_literal_counts.update(run["learned_literal_counts"])
        learned_clause_counts.update(run["learned_clause_counts"])
        q_prefix_observed.update(int(value) for value in run["q_prefix_bits_observed"])
        factored_events.extend(run["factored_events"])
        if run["timed_out"] or run["returncode"] not in (0, None) or run["parse_errors"]:
            error_details.append(
                {
                    "selected_rank": run["selected_rank"],
                    "returncode": run["returncode"],
                    "timed_out": run["timed_out"],
                    "parse_errors": run["parse_errors"],
                    "stderr_tail": run["stderr_tail"],
                }
            )

    return {
        "child_runs": len(runs),
        "completed_child_runs": sum(
            1
            for run in runs
            if not run["timed_out"] and run["returncode"] == 0
        ),
        "cubes": cubes,
        "low_coppersmith_calls": low_calls,
        "low_coppersmith_hard_blocks": low_hard_blocks,
        "factored_event_count": len(factored_events),
        "factored_events": factored_events,
        "prefix_status_counts": sorted_counter(prefix_status_counts),
        "learned_clause_counts": sorted_counter(learned_clause_counts),
        "learned_literal_counts": sorted_counter(learned_literal_counts),
        "q_prefix_bits_observed": sorted(q_prefix_observed),
        "q_prefix_bits_observed_max": max(q_prefix_observed) if q_prefix_observed else None,
        "timeouts": timeouts,
        "errors": {
            "process_errors": process_errors,
            "parse_errors": parse_errors,
            "stderr_runs": stderr_runs,
            "details": error_details,
        },
    }


def main() -> int:
    args = parse_args()
    if args.max_tie_cubes < 0:
        raise SystemExit("--max-tie-cubes must be non-negative")
    if args.max_high_candidates < 1:
        raise SystemExit("--max-high-candidates must be positive")
    if args.max_low_cubes < 1:
        raise SystemExit("--max-low-cubes must be positive")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.low_coppersmith_bits <= 0:
        raise SystemExit("--low-coppersmith-bits must be positive")
    if args.low_coppersmith_min_hard_margin_bits < 0:
        raise SystemExit("--low-coppersmith-min-hard-margin-bits must be nonnegative")

    started_at = time.time()
    tie = build_tie_candidates(args)
    selected = tie["selected"]
    runs = [
        run_candidate(args, tie["base_ranges"], candidate)
        for candidate in selected
    ]
    aggregate = aggregate_runs(runs)
    result = {
        "event": "q_tie_guided_batch",
        "parameters": {
            "tie_ranges": args.tie_ranges,
            "low_ranges": args.low_ranges,
            "max_tie_cubes": args.max_tie_cubes,
            "max_high_candidates": args.max_high_candidates,
            "max_low_cubes": args.max_low_cubes,
            "timeout_seconds": args.timeout_seconds,
            "check_bits": args.check_bits,
            "timeout_ms": args.timeout_ms,
            "low_coppersmith_bits": args.low_coppersmith_bits,
            "low_coppersmith_epsilon": args.low_coppersmith_epsilon,
            "low_coppersmith_min_hard_margin_bits": args.low_coppersmith_min_hard_margin_bits,
            "low_coppersmith_hard_fail": True,
        },
        "tie_summary": tie["summary"],
        "high_candidate_count": len(selected),
        "selected_high_candidates": [
            {
                "selected_rank": item["selected_rank"],
                "group_rank": item["group_rank"],
                "q_prefix_bits": item["q_prefix_bits"],
                "q_known_bits": item["q_known_bits"],
                "q_interval_width_bits": item["q_interval_width_bits"],
                "fixed_ranges": item["fixed_ranges"],
            }
            for item in selected
        ],
        "run_summary": aggregate,
        "runs": runs,
        "elapsed_seconds": round(time.time() - started_at, 3),
    }

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
