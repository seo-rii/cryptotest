#!/usr/bin/env python3
"""Compare tiny q-guided low-prefix SAT/CAS batches.

The wrapper keeps all strategies on deterministic_low_runner.py so the results
are directly comparable: each strategy gets a bounded high-side guide, then the
same sound low-Coppersmith oracle is run over a tiny deterministic low cube set.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = Path("/tmp/ct07_q_guided_batch_compare.json")
FULL_X6_FIXED = "784:46:0x245521490bd"
LOW_X0_X3 = "150:4,210:39,265:84,362:78"
LOW_X1_X3 = "210:39,265:84,362:78"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-low-cubes", type=int, default=1)
    parser.add_argument("--low-coppersmith-bits", type=int, default=600)
    parser.add_argument("--low-coppersmith-epsilon", type=float, default=0.02)
    parser.add_argument("--low-coppersmith-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=25.0,
        help="subprocess timeout per strategy",
    )
    parser.add_argument("--json", action="store_true", help="emit comparison JSON to stdout")
    return parser.parse_args()


def strategy_specs(max_low_cubes: int) -> list[dict[str, Any]]:
    return [
        {
            "name": "partial_822_920",
            "description": "rank partial high-side ranges 822:8,920:4",
            "args": [
                "--high-ranges",
                "822:8,920:4",
                "--high-max-cubes",
                "32",
                "--top-high",
                "1",
                "--low-ranges",
                LOW_X0_X3,
                "--max-low-cubes",
                str(max_low_cubes),
            ],
        },
        {
            "name": "full_x6_x0_x7",
            "description": "fix full x6 and rank x0/x7, then enumerate x1/x2/x3 low cubes",
            "args": [
                "--fix-p-range",
                FULL_X6_FIXED,
                "--high-ranges",
                "150:4,920:4",
                "--high-max-cubes",
                "32",
                "--top-high",
                "1",
                "--low-ranges",
                LOW_X1_X3,
                "--max-low-cubes",
                str(max_low_cubes),
            ],
        },
        {
            "name": "no_high_guide",
            "description": "enumerate low cubes without a high-side q guide",
            "args": [
                "--low-ranges",
                LOW_X0_X3,
                "--max-low-cubes",
                str(max_low_cubes),
            ],
        },
    ]


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


def sorted_counter(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def collect_q_prefix_candidates(records: list[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for record in records:
        if record.get("event") != "deterministic_low_start":
            continue
        for candidate in record.get("ranked_high_candidates", []):
            if isinstance(candidate, dict) and candidate.get("q_prefix_bits") is not None:
                values.append(int(candidate["q_prefix_bits"]))
    return values


def collect_observed_q_prefix(records: list[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for record in records:
        if record.get("q_prefix_bits") is not None:
            values.append(int(record["q_prefix_bits"]))
        details = record.get("details")
        if isinstance(details, dict) and details.get("q_prefix_bits") is not None:
            values.append(int(details["q_prefix_bits"]))
    return values


def summarize_strategy(
    spec: dict[str, Any],
    command: list[str],
    records: list[dict[str, Any]],
    parse_errors: int,
    returncode: int | None,
    timed_out: bool,
    elapsed: float,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    prefix_counts: Counter[str] = Counter()
    learned_literal_counts: Counter[str] = Counter()
    learned_scope_counts: Counter[str] = Counter()
    factored_events: list[dict[str, Any]] = []
    cube_records = 0
    low_coppersmith_calls = 0
    low_coppersmith_hard_blocks = 0
    summary: dict[str, Any] = {}

    for record in records:
        if record.get("event") == "cube":
            cube_records += 1
            status = str(record.get("product_prefix_status", "missing"))
            prefix_counts[status] += 1
            low_report = record.get("low_coppersmith")
            if isinstance(low_report, dict):
                low_coppersmith_calls += 1
                if low_report.get("status") == "factored":
                    factored_events.append(
                        {
                            "high_index": record.get("high_index"),
                            "low_index": record.get("low_index"),
                            "status": low_report.get("status"),
                            "factors": low_report.get("factors", []),
                        }
                    )
            if record.get("learned_clause") == "low_coppersmith_no_root":
                low_coppersmith_hard_blocks += 1
            if record.get("learned_clause_literal_count") is not None:
                learned_literal_counts[str(record["learned_clause_literal_count"])] += 1
            if record.get("learned_clause_scope") is not None:
                learned_scope_counts[str(record["learned_clause_scope"])] += 1
        elif record.get("event") == "summary":
            summary = record

    if summary:
        cube_records = cube_records or int(summary.get("cubes") or 0)
        low_coppersmith_calls = low_coppersmith_calls or int(
            summary.get("low_coppersmith_calls") or 0
        )
        low_coppersmith_hard_blocks = low_coppersmith_hard_blocks or int(
            summary.get("low_coppersmith_hard_blocks") or 0
        )
        if not prefix_counts:
            for key in ("prefix_sat", "prefix_unsat", "prefix_unknown"):
                value = int(summary.get(key) or 0)
                if value:
                    prefix_counts[key.removeprefix("prefix_")] += value

    candidate_q_prefix = collect_q_prefix_candidates(records)
    observed_q_prefix = collect_observed_q_prefix(records)
    return {
        "strategy": spec["name"],
        "description": spec["description"],
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "elapsed_seconds": round(elapsed, 3),
        "runner_elapsed_seconds": summary.get("elapsed_seconds"),
        "records": len(records),
        "parse_errors": parse_errors,
        "cubes": cube_records,
        "q_prefix_bits_best_candidate": max(candidate_q_prefix) if candidate_q_prefix else None,
        "q_prefix_bits_observed_max": max(observed_q_prefix) if observed_q_prefix else None,
        "q_prefix_bits_observed": sorted(set(observed_q_prefix)),
        "prefix_status_counts": sorted_counter(prefix_counts),
        "low_coppersmith_calls": low_coppersmith_calls,
        "low_coppersmith_hard_blocks": low_coppersmith_hard_blocks,
        "learned_literal_counts": sorted_counter(learned_literal_counts),
        "learned_scope_counts": sorted_counter(learned_scope_counts),
        "factored_events": factored_events,
        "stdout_line_count": len(stdout.splitlines()),
        "stderr_tail": stderr.splitlines()[-5:],
    }


def run_strategy(spec: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    command = [
        sys.executable,
        str(HERE / "deterministic_low_runner.py"),
        *spec["args"],
        "--check-bits",
        "608",
        "--prefix-core",
        "bv",
        "--timeout-ms",
        "500",
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
        return summarize_strategy(
            spec,
            command,
            records,
            parse_errors,
            process.returncode,
            False,
            elapsed,
            process.stdout,
            process.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - started_at
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        records, parse_errors = parse_json_lines(stdout)
        return summarize_strategy(
            spec,
            command,
            records,
            parse_errors,
            None,
            True,
            elapsed,
            stdout,
            stderr,
        )


def emit_text(result: dict[str, Any]) -> None:
    for row in result["strategies"]:
        print(
            f"{row['strategy']}: "
            f"cubes={row['cubes']} "
            f"q_best={row['q_prefix_bits_best_candidate']} "
            f"q_obs={row['q_prefix_bits_observed_max']} "
            f"prefix={row['prefix_status_counts']} "
            f"low={row['low_coppersmith_calls']}/{row['low_coppersmith_hard_blocks']} "
            f"learned={row['learned_literal_counts']} "
            f"factored={len(row['factored_events'])} "
            f"elapsed={row['elapsed_seconds']}"
        )
    print(f"output={result['output']}")


def main() -> int:
    args = parse_args()
    if args.max_low_cubes < 1:
        raise SystemExit("--max-low-cubes must be positive")
    if args.low_coppersmith_bits <= 0:
        raise SystemExit("--low-coppersmith-bits must be positive")
    if args.low_coppersmith_min_hard_margin_bits < 0:
        raise SystemExit("--low-coppersmith-min-hard-margin-bits must be nonnegative")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")

    started_at = time.time()
    rows = [
        run_strategy(spec, args)
        for spec in strategy_specs(args.max_low_cubes)
    ]
    result = {
        "event": "q_guided_batch_compare",
        "output": str(args.output),
        "max_low_cubes": args.max_low_cubes,
        "low_coppersmith_bits": args.low_coppersmith_bits,
        "low_coppersmith_epsilon": args.low_coppersmith_epsilon,
        "low_coppersmith_min_hard_margin_bits": args.low_coppersmith_min_hard_margin_bits,
        "timeout_seconds": args.timeout_seconds,
        "strategy_count": len(rows),
        "elapsed_seconds": round(time.time() - started_at, 3),
        "strategies": rows,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        emit_text(result)

    if any(row["timed_out"] or row["returncode"] not in (0, None) for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
