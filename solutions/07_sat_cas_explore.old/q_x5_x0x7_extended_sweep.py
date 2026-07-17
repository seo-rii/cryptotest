#!/usr/bin/env python3
"""Sweep x0/x7 branches around q_x5_extended_beam_search.py.

This wrapper runs the full-x5 high-edge beam search for selected 4-bit x0/x7
values, merges each branch's final candidates, and ranks the combined list by
the same q-prefix priority used by the underlying search.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
BEAM_SCRIPT = HERE / "q_x5_extended_beam_search.py"
DEFAULT_NIBBLES = tuple(range(16))


def parse_nibble_values(text: str | None) -> list[int]:
    if text is None or not text.strip():
        return list(DEFAULT_NIBBLES)
    if text.strip().lower() == "all":
        return list(DEFAULT_NIBBLES)

    values: list[int] = []
    seen: set[int] = set()
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        value = int(part, 0)
        if value < 0 or value >= 16:
            raise argparse.ArgumentTypeError(f"{value!r} does not fit 4 bits")
        if value not in seen:
            values.append(value)
            seen.add(value)
    if not values:
        raise argparse.ArgumentTypeError("expected at least one value")
    return values


def parse_x1_values(text: str | None) -> list[int | None]:
    if text is None or not text.strip():
        return [None]
    if text.strip().lower() in {"none", "unset"}:
        return [None]
    values: list[int | None] = []
    seen: set[int | None] = set()
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if part.lower() in {"none", "unset"}:
            value: int | None = None
        else:
            value = int(part, 0)
            if value < 0 or value >= (1 << 39):
                raise argparse.ArgumentTypeError(f"{value!r} does not fit 39 bits")
        if value not in seen:
            values.append(value)
            seen.add(value)
    if not values:
        raise argparse.ArgumentTypeError("expected at least one x1 value")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x0-values", type=parse_nibble_values, default=list(DEFAULT_NIBBLES))
    parser.add_argument("--x1-values", type=parse_x1_values, default=[None])
    parser.add_argument("--x7-values", type=parse_nibble_values, default=list(DEFAULT_NIBBLES))
    parser.add_argument("--x5-width", type=int, default=87)
    parser.add_argument("--beam-width", type=int, default=2)
    parser.add_argument("--per-parent-cubes", type=int, default=8)
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.x5_width <= 0 or args.x5_width > 87:
        raise SystemExit("--x5-width must be in 1..87")
    if args.beam_width < 1:
        raise SystemExit("--beam-width must be positive")
    if args.per_parent_cubes < 1:
        raise SystemExit("--per-parent-cubes must be positive")
    if args.top < 1:
        raise SystemExit("--top must be positive")
    return args


def parse_json_stdout(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise ValueError("subprocess produced no stdout")
    try:
        record = json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        else:
            raise
    if not isinstance(record, dict):
        raise ValueError("subprocess JSON root is not an object")
    return record


def range_key(candidate: dict[str, Any]) -> tuple[int, int, int]:
    range_text = str(candidate.get("range", "0:0:0"))
    try:
        start_text, width_text, value_text = range_text.split(":", 2)
        return (int(start_text, 0), int(width_text, 0), int(value_text, 0))
    except ValueError:
        return (0, 0, 0)


def candidate_rank_key(candidate: dict[str, Any]) -> tuple[int, int, int, int, tuple[int, int, int], int, int, int]:
    x1_value = candidate.get("x1")
    return (
        -int(candidate.get("q_prefix_bits") or 0),
        -int(candidate.get("q_known_bits") or 0),
        -int(candidate.get("q_low_bits") or 0),
        int(candidate.get("q_interval_width_bits") or 0),
        range_key(candidate),
        int(candidate.get("x0") or 0),
        -1 if x1_value is None else int(x1_value),
        int(candidate.get("x7") or 0),
    )


def run_branch(args: argparse.Namespace, x0: int, x1: int | None, x7: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(BEAM_SCRIPT),
        "--x5-width",
        str(args.x5_width),
        "--beam-width",
        str(args.beam_width),
        "--per-parent-cubes",
        str(args.per_parent_cubes),
        "--x0",
        str(x0),
    ]
    if x1 is not None:
        command.extend(["--x1", str(x1)])
    command.extend(
        [
            "--x7",
            str(x7),
            "--json",
        ]
    )
    started = time.monotonic()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    elapsed = time.monotonic() - started
    branch: dict[str, Any] = {
        "x0": x0,
        "x0_hex": hex(x0),
        "x1": x1,
        "x1_hex": None if x1 is None else hex(x1),
        "x7": x7,
        "x7_hex": hex(x7),
        "command": command,
        "returncode": completed.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "stderr_tail": completed.stderr.splitlines()[-5:],
        "stdout_line_count": len(completed.stdout.splitlines()),
    }

    if completed.returncode != 0:
        branch["status"] = "failed"
        branch["error"] = "subprocess returned non-zero"
        return branch

    try:
        report = parse_json_stdout(completed.stdout)
    except (ValueError, json.JSONDecodeError) as exc:
        branch["status"] = "failed"
        branch["error"] = f"failed to parse JSON: {exc}"
        return branch

    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    final_candidates = report.get("final_candidates")
    if not isinstance(final_candidates, list):
        final_candidates = []

    branch["status"] = "ok"
    branch["base_q_low_bits"] = summary.get("base_q_low_bits")
    branch["base_q_prefix_bits"] = summary.get("base_q_prefix_bits")
    branch["base_q_known_bits"] = summary.get("base_q_known_bits")
    branch["final_candidate_count"] = len(final_candidates)
    branch["best_final_candidate"] = summary.get("best_final_candidate")
    branch["stage_count"] = len(report.get("stages") or [])
    return branch | {"_report": report}


def annotated_candidates(branch: dict[str, Any]) -> list[dict[str, Any]]:
    report = branch.get("_report")
    if not isinstance(report, dict):
        return []

    summary = report.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    branch_best = summary.get("best_final_candidate")
    final_candidates = report.get("final_candidates")
    if not isinstance(final_candidates, list):
        final_candidates = []

    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int | None, int, str]] = set()

    def add_candidate(candidate: object, source: str, branch_rank: int | None) -> None:
        if not isinstance(candidate, dict):
            return
        row = dict(candidate)
        x1_value = branch.get("x1")
        key = (
            int(branch["x0"]),
            None if x1_value is None else int(x1_value),
            int(branch["x7"]),
            str(row.get("range", "")),
        )
        if key in seen:
            for existing in rows:
                existing_key = (
                    int(existing["x0"]),
                    None if existing.get("x1") is None else int(existing["x1"]),
                    int(existing["x7"]),
                    str(existing.get("range", "")),
                )
                if existing_key == key and source == "best_final_candidate":
                    existing["branch_best"] = True
                break
            return
        seen.add(key)
        row.update(
            {
                "x0": branch["x0"],
                "x0_hex": branch["x0_hex"],
                "x1": branch["x1"],
                "x1_hex": branch["x1_hex"],
                "x7": branch["x7"],
                "x7_hex": branch["x7_hex"],
                "branch_rank": branch_rank,
                "branch_best": source == "best_final_candidate",
                "source": source,
            }
        )
        rows.append(row)

    add_candidate(branch_best, "best_final_candidate", None)
    for index, candidate in enumerate(final_candidates, start=1):
        add_candidate(candidate, "final_candidates", index)
    return rows


def public_branch_summary(branch: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in branch.items() if key != "_report"}


def main() -> int:
    args = parse_args()
    per_branch: list[dict[str, Any]] = []
    all_candidates: list[dict[str, Any]] = []
    started = time.monotonic()

    for x0 in args.x0_values:
        for x1 in args.x1_values:
            for x7 in args.x7_values:
                branch = run_branch(args, x0, x1, x7)
                per_branch.append(branch)
                all_candidates.extend(annotated_candidates(branch))

    all_candidates.sort(key=candidate_rank_key)
    top_candidates = all_candidates[: args.top]
    ok_branches = [branch for branch in per_branch if branch.get("status") == "ok"]
    failed_branches = [branch for branch in per_branch if branch.get("status") != "ok"]
    elapsed = time.monotonic() - started
    report = {
        "event": "q_x5_x0x7_extended_sweep",
        "summary": {
            "ranking_priority": "q_prefix_bits,q_known_bits,q_low_bits,small_interval,ranges",
            "x0_values": args.x0_values,
            "x1_values": args.x1_values,
            "x7_values": args.x7_values,
            "x5_width": args.x5_width,
            "beam_width": args.beam_width,
            "per_parent_cubes": args.per_parent_cubes,
            "top": args.top,
            "branch_count": len(per_branch),
            "ok_branch_count": len(ok_branches),
            "failed_branch_count": len(failed_branches),
            "merged_final_candidate_count": len(all_candidates),
            "elapsed_seconds": round(elapsed, 3),
            "best_final_candidate": top_candidates[0] if top_candidates else None,
        },
        "per_branch": [public_branch_summary(branch) for branch in per_branch],
        "final_candidates": top_candidates,
    }

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            f"branches ok={summary['ok_branch_count']}/{summary['branch_count']} "
            f"candidates={summary['merged_final_candidate_count']} "
            f"elapsed={summary['elapsed_seconds']}s"
        )
        print("branch bests:")
        for branch in sorted(
            per_branch,
            key=lambda row: (
                int(row["x0"]),
                -1 if row.get("x1") is None else int(row["x1"]),
                int(row["x7"]),
            ),
        ):
            best = branch.get("best_final_candidate")
            if not isinstance(best, dict):
                status = branch.get("status")
                error = branch.get("error", "")
                print(f"x0={branch['x0_hex']} x7={branch['x7_hex']} status={status} {error}")
                continue
            print(
                f"x0={branch['x0_hex']} x1={branch['x1_hex']} x7={branch['x7_hex']} "
                f"{best.get('range')} q_prefix={best.get('q_prefix_bits')} "
                f"q_known={best.get('q_known_bits')} q_low={best.get('q_low_bits')} "
                f"width_bits={best.get('q_interval_width_bits')}"
            )
        print("top candidates:")
        for rank, candidate in enumerate(top_candidates, start=1):
            print(
                f"{rank:02d} x0={candidate['x0_hex']} x1={candidate['x1_hex']} x7={candidate['x7_hex']} "
                f"{candidate.get('range')} q_prefix={candidate.get('q_prefix_bits')} "
                f"q_known={candidate.get('q_known_bits')} q_low={candidate.get('q_low_bits')} "
                f"width_bits={candidate.get('q_interval_width_bits')}"
            )
    return 1 if failed_branches else 0


if __name__ == "__main__":
    raise SystemExit(main())
