#!/usr/bin/env python3
"""Run challenge 7 tail CP-SAT probe plans and collect JSON summaries."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_summary(output: str) -> dict[str, object] | None:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def load_plan(path: Path, limit: int, skip: int) -> list[dict[str, object]]:
    records = []
    with path.open("r", encoding="utf-8") as source:
        for line_index, line in enumerate(source):
            if line_index < skip:
                continue
            if limit > 0 and len(records) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if "argv" not in record:
                raise SystemExit(f"plan line {line_index + 1} has no argv")
            record["_plan_line"] = line_index + 1
            records.append(record)
    return records


def run_one(record: dict[str, object], timeout: float, cwd: Path) -> dict[str, object]:
    argv = record["argv"]
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise ValueError(f"invalid argv on plan line {record.get('_plan_line')}")

    started = time.monotonic()
    result_record: dict[str, object] = {
        "plan_line": record.get("_plan_line"),
        "rank": record.get("rank"),
        "tail_T": record.get("tail_T"),
        "branch_low": record.get("branch_low"),
        "branch_high": record.get("branch_high"),
        "x1_low": record.get("x1_low"),
        "x1_width": record.get("x1_width"),
        "x6_high": record.get("x6_high"),
        "x6_width": record.get("x6_width"),
        "argv": argv,
    }

    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        result_record.update(
            {
                "returncode": None,
                "runner_status": "TIMEOUT",
                "elapsed": time.monotonic() - started,
                "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            }
        )
        return result_record

    summary = parse_summary(completed.stdout)
    result_record.update(
        {
            "returncode": completed.returncode,
            "runner_status": "DONE",
            "elapsed": time.monotonic() - started,
            "stdout_tail": completed.stdout[-4000:],
        }
    )
    if summary is None:
        result_record["summary_missing"] = True
    else:
        result_record.update(summary)
    return result_record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-jsonl", type=Path, required=True)
    parser.add_argument("--out-jsonl", type=Path, required=True)
    parser.add_argument("--parallel", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument("--cwd", type=Path, default=ROOT.parent)
    args = parser.parse_args()

    if args.parallel <= 0:
        raise SystemExit("--parallel must be positive")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")

    records = load_plan(args.plan_jsonl, args.limit, args.skip)
    done = 0
    with args.out_jsonl.open("w", encoding="utf-8") as output:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as executor:
            futures = [executor.submit(run_one, record, args.timeout, args.cwd) for record in records]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                output.write(json.dumps(result, sort_keys=True) + "\n")
                output.flush()
                done += 1
                status = result.get("status") or result.get("runner_status")
                conflicts = result.get("conflicts", "-")
                branches = result.get("branches", "-")
                conflicts_per_sec = result.get("conflicts_per_sec", "-")
                print(
                    f"[{done}/{len(records)}] T={result.get('tail_T')} "
                    f"x1={result.get('x1_low')} x6={result.get('x6_high')} "
                    f"status={status} branches={branches} conflicts={conflicts} "
                    f"conflicts/sec={conflicts_per_sec}",
                    flush=True,
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
