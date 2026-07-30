#!/usr/bin/env python3
"""Run ranked q-gap candidates in fast hit-first mode."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_ranked_qgap_hits_{time.strftime('%Y%m%d_%H%M%S')}"


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rank_json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-index", type=int, default=1, help="1-based rank index to start from")
    parser.add_argument("--top", type=int, default=32)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--check-bits", type=int, default=362)
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--q-gap-oracle-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--cube-ranges", default="150:4,265:84,784:46,920:4")
    parser.add_argument("--x2-assume-range", default="265:8")
    parser.add_argument("--x6-assume-range", default="784:4")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.start_index < 1:
        raise SystemExit("--start-index must be positive")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.q_gap_oracle_timeout_seconds < 0:
        raise SystemExit("--q-gap-oracle-timeout-seconds must be nonnegative")

    rank_payload = json.loads(args.rank_json.expanduser().read_text(encoding="utf-8"))
    ranked_rows = list(rank_payload.get("top") or [])
    top_rows = ranked_rows[args.start_index - 1 : args.start_index - 1 + args.top]
    if not top_rows:
        raise SystemExit("rank file has no top records")
    ledgers = [Path(path) for path in rank_payload.get("loaded_ledgers") or []]

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records: list[dict[str, Any]] = []
    solved = None

    x2_start, x2_width = args.x2_assume_range.split(":", 1)
    x6_start, x6_width = args.x6_assume_range.split(":", 1)

    for offset, row in enumerate(top_rows):
        rank_index = args.start_index + offset
        out_jsonl = output_dir / f"hit_{rank_index:04d}.jsonl"
        stderr_path = output_dir / f"hit_{rank_index:04d}.stderr"
        x2_value = int(row["x2_value"])
        x6_value = int(row["x6_value"])
        command = [
            sys.executable,
            str(HERE / "semi_programmatic_sat.py"),
            "--jsonl",
            "--max-cubes",
            "1",
            "--cube-ranges",
            args.cube_ranges,
            "--check-bits",
            str(args.check_bits),
            "--timeout-ms",
            str(args.timeout_ms),
            "--enumerate-p-free-limit",
            str(args.enumerate_p_free_limit),
            "--run-q-gap-coppersmith",
            "--q-gap-max-bits",
            str(args.q_gap_max_bits),
            "--q-gap-epsilon",
            str(args.q_gap_epsilon),
            "--q-gap-min-hard-margin-bits",
            str(args.min_hard_margin_bits),
            "--q-gap-hard-fail",
            "--q-gap-oracle-timeout-seconds",
            str(args.q_gap_oracle_timeout_seconds),
            "--q-gap-minimize-workers",
            str(args.workers),
            "--include-cube-ranges",
            "--cube-assume-p-range",
            f"{x2_start}:{x2_width}:{x2_value}",
            "--cube-assume-p-range",
            f"{x6_start}:{x6_width}:{x6_value}",
        ]
        for ledger in ledgers:
            command.extend(["--load-learned-jsonl", str(ledger)])

        hit_started = time.time()
        with out_jsonl.open("w", encoding="utf-8") as stdout:
            process = subprocess.run(
                command,
                cwd=WORKSPACE,
                text=True,
                stdout=stdout,
                stderr=subprocess.PIPE,
                check=False,
            )
        stderr_path.write_text(process.stderr, encoding="utf-8")
        rows = jsonl_rows(out_jsonl)
        cube = next((item for item in rows if item.get("event") == "cube"), {})
        summary = next((item for item in rows if item.get("event") == "summary"), {})
        q_gap = cube.get("q_gap_coppersmith") or {}
        factors = q_gap.get("factors") or []
        record = {
            "index": len(records) + 1,
            "rank_index": rank_index,
            "returncode": process.returncode,
            "elapsed_seconds": time.time() - hit_started,
            "jsonl": str(out_jsonl),
            "stderr": str(stderr_path),
            "x2_value": x2_value,
            "x6_value": x6_value,
            "ranked_q_gap_bits": row.get("q_gap_bits"),
            "cube_ranges": cube.get("cube_ranges"),
            "product_prefix_status": cube.get("product_prefix_status"),
            "q_gap_status": q_gap.get("status"),
            "q_gap_bits": q_gap.get("q_gap_bits"),
            "q_gap_elapsed_seconds": q_gap.get("elapsed_seconds"),
            "q_gap_coppersmith_calls": summary.get("q_gap_coppersmith_calls"),
            "learned_clause": cube.get("learned_clause"),
            "learned_clause_literal_count": cube.get("learned_clause_literal_count"),
            "factors": factors,
        }
        records.append(record)
        summary_path = output_dir / "hit_summary.json"
        summary_path.write_text(
            json.dumps(
                {
                    "event": "run_ranked_q_gap_hits",
                    "status": "factored" if factors else "running",
                    "output_dir": str(output_dir),
                    "rank_json": str(args.rank_json.expanduser().resolve()),
                    "elapsed_seconds": time.time() - started,
                    "records": records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if factors:
            solved = record
            break
        if process.returncode not in {0, 2}:
            break

    final_payload = {
        "event": "run_ranked_q_gap_hits",
        "status": "factored" if solved else "no_factor",
        "output_dir": str(output_dir),
        "rank_json": str(args.rank_json.expanduser().resolve()),
        "elapsed_seconds": time.time() - started,
        "iterations_completed": len(records),
        "records": records,
        "success": solved,
    }
    summary_path = output_dir / "hit_summary.json"
    summary_path.write_text(json.dumps(final_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({**final_payload, "records": f"{len(records)} rows in {summary_path}"}, sort_keys=True))
    else:
        print(
            "status={status} iterations={iterations} output={output}".format(
                status=final_payload["status"],
                iterations=len(records),
                output=summary_path,
            )
        )
    return 0 if solved else 2


if __name__ == "__main__":
    raise SystemExit(main())
