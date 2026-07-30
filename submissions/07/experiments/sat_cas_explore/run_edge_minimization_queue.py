#!/usr/bin/env python3
"""Run small edge-only q-gap minimization probes over ranked pairs."""

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
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_edge_min_queue_{time.strftime('%Y%m%d_%H%M%S')}"


def read_resume_list(path: Path) -> list[Path]:
    rows: list[Path] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append(Path(line))
    return rows


def parse_start_width(raw: str) -> tuple[int, int]:
    try:
        start_text, width_text = raw.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("range must be START:WIDTH") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    if start < 0 or width <= 0:
        raise argparse.ArgumentTypeError("range must have nonnegative start and positive width")
    return start, width


def summarize_loop(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") or []
    first = records[0] if records else {}
    return {
        "status": payload.get("status"),
        "elapsed_seconds": payload.get("elapsed_seconds"),
        "iterations_completed": payload.get("iterations_completed"),
        "q_gap_status": first.get("q_gap_status"),
        "q_gap_bits": first.get("q_gap_bits"),
        "q_gap_calls": first.get("q_gap_coppersmith_calls"),
        "q_gap_hard_blocks": first.get("q_gap_coppersmith_hard_blocks"),
        "learned_clause_scope": first.get("learned_clause_scope"),
        "learned_clause_count": first.get("learned_clause_count"),
        "learned_clause_literal_count": first.get("learned_clause_literal_count"),
        "learned_clause_dropped_bits": first.get("learned_clause_dropped_bits"),
        "learned_clause_variants": first.get("learned_clause_variants"),
        "q_gap_coppersmith_cumulative_minimization": first.get(
            "q_gap_coppersmith_cumulative_minimization"
        ),
        "q_gap_coppersmith_independent_minimization": first.get(
            "q_gap_coppersmith_independent_minimization"
        ),
        "cube_ranges": first.get("cube_ranges"),
        "cube_assumptions": first.get("cube_assumptions"),
        "factors": first.get("factors") or [],
        "jsonl": first.get("jsonl"),
        "stderr": first.get("stderr"),
    }


def write_manifest(path: Path | None, ledgers: list[Path]) -> str | None:
    if path is None:
        return None
    output = path.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    rows: list[str] = []
    for ledger in ledgers:
        resolved = str(ledger.expanduser().resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        rows.append(resolved)
    output.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rank_json", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--resume-list", action="append", default=[], type=Path)
    parser.add_argument("--resume-jsonl", action="append", default=[], type=Path)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--top", type=int, default=4)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--x2-range", default="265:8")
    parser.add_argument("--x6-range", default="784:4")
    parser.add_argument(
        "--drop-window",
        action="append",
        default=["150:4"],
        help="edge drop window START:WIDTH; repeatable. Default only tests x0=150:4",
    )
    parser.add_argument(
        "--drop-mode",
        choices=("independent", "cumulative", "hybrid"),
        default="cumulative",
        help="drop mode forwarded to run_fullx1x5_drop_loop.py",
    )
    parser.add_argument(
        "--hybrid-cumulative-drop-window",
        action="append",
        default=[],
        help="hybrid-mode cumulative q-gap drop window START:WIDTH; uses run_fullx1x5_drop_loop.py defaults if omitted",
    )
    parser.add_argument(
        "--hybrid-independent-drop-window",
        action="append",
        default=[],
        help="hybrid-mode independent q-gap drop window START:WIDTH; uses run_fullx1x5_drop_loop.py defaults if omitted",
    )
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--q-gap-oracle-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--q-gap-minimize-max-completions", type=int, default=64)
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=None,
        help="optional output file containing the initial ledgers plus any successful queue JSONLs",
    )
    parser.add_argument("--unique-pairs", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.start_index < 1:
        raise SystemExit("--start-index must be positive")
    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.q_gap_oracle_timeout_seconds < 0:
        raise SystemExit("--q-gap-oracle-timeout-seconds must be nonnegative")
    if args.q_gap_minimize_max_completions < 1:
        raise SystemExit("--q-gap-minimize-max-completions must be positive")
    x2_start, x2_width = parse_start_width(args.x2_range)
    x6_start, x6_width = parse_start_width(args.x6_range)

    rank_payload = json.loads(args.rank_json.expanduser().read_text(encoding="utf-8"))
    ranked_rows = list(rank_payload.get("top") or [])
    if not ranked_rows:
        raise SystemExit("rank JSON has no top rows")

    selected: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int]] = set()
    for rank_index, row in enumerate(ranked_rows, start=1):
        if rank_index < args.start_index:
            continue
        if "x2_value" not in row or "x6_value" not in row:
            continue
        x2_value = int(row["x2_value"])
        x6_value = int(row["x6_value"])
        pair = (x2_value, x6_value)
        if args.unique_pairs and pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        selected.append({"rank_index": rank_index, "row": row})
        if len(selected) >= args.top:
            break
    if not selected:
        raise SystemExit("no selected rows")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    initial_ledgers: list[Path] = []
    for resume_list in args.resume_list:
        initial_ledgers.extend(read_resume_list(resume_list.expanduser()))
    initial_ledgers.extend(args.resume_jsonl)
    ledgers = [path.expanduser().resolve() for path in initial_ledgers]

    started = time.time()
    records: list[dict[str, Any]] = []
    solved = None
    for item_index, item in enumerate(selected, start=1):
        if args.max_seconds and time.time() - started >= args.max_seconds:
            break
        row = item["row"]
        rank_index = int(item["rank_index"])
        x2_value = int(row["x2_value"])
        x6_value = int(row["x6_value"])
        item_dir = output_dir / f"item_{item_index:04d}_rank_{rank_index:04d}_x2_{x2_value:x}_x6_{x6_value:x}"
        item_dir.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(HERE / "run_fullx1x5_drop_loop.py"),
            "--iterations",
            "1",
            "--drop-mode",
            args.drop_mode,
            "--workers",
            str(args.workers),
            "--output-dir",
            str(item_dir),
            "--q-gap-epsilon",
            str(args.q_gap_epsilon),
            "--q-gap-max-bits",
            str(args.q_gap_max_bits),
            "--q-gap-oracle-timeout-seconds",
            str(args.q_gap_oracle_timeout_seconds),
            "--q-gap-minimize-max-completions",
            str(args.q_gap_minimize_max_completions),
            "--cube-assume-p-range",
            f"{x2_start}:{x2_width}:{hex(x2_value)}",
            "--cube-assume-p-range",
            f"{x6_start}:{x6_width}:{hex(x6_value)}",
            "--json",
        ]
        if args.drop_mode == "hybrid":
            for drop_window in args.hybrid_cumulative_drop_window:
                command.extend(["--hybrid-cumulative-drop-window", drop_window])
            for drop_window in args.hybrid_independent_drop_window:
                command.extend(["--hybrid-independent-drop-window", drop_window])
        else:
            for drop_window in args.drop_window:
                command.extend(["--drop-window", drop_window])
        for ledger in ledgers:
            command.extend(["--resume-jsonl", str(ledger)])

        command_path = item_dir / "command.json"
        command_path.write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
        item_started = time.time()
        if args.dry_run:
            record = {
                "item": item_index,
                "rank_index": rank_index,
                "x2_value": x2_value,
                "x6_value": x6_value,
                "command": command,
                "output_dir": str(item_dir),
                "status": "dry_run",
            }
            records.append(record)
            continue
        process = subprocess.run(
            command,
            cwd=WORKSPACE,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        (item_dir / "queue_stdout.json").write_text(process.stdout, encoding="utf-8")
        (item_dir / "queue_stderr.txt").write_text(process.stderr, encoding="utf-8")
        loop_summary = item_dir / "loop_summary.json"
        loop = summarize_loop(loop_summary) if loop_summary.exists() else {}
        record = {
            "item": item_index,
            "rank_index": rank_index,
            "x2_value": x2_value,
            "x6_value": x6_value,
            "pair_seen_count": row.get("pair_seen_count"),
            "ranked_q_gap_bits": row.get("q_gap_bits"),
            "returncode": process.returncode,
            "elapsed_seconds": time.time() - item_started,
            "output_dir": str(item_dir),
            "loop_summary": str(loop_summary),
            **loop,
        }
        records.append(record)
        jsonl = loop.get("jsonl")
        if jsonl and Path(jsonl).exists():
            ledgers.append(Path(jsonl).resolve())
        if loop.get("factors"):
            solved = record
            break
        if process.returncode not in {0, 2}:
            break
        queue_summary = {
            "event": "edge_minimization_queue",
            "status": "factored" if solved else "running",
            "rank_json": str(args.rank_json.expanduser().resolve()),
            "output_dir": str(output_dir),
            "elapsed_seconds": time.time() - started,
            "manifest_output": write_manifest(args.manifest_output, ledgers),
            "records": records,
        }
        (output_dir / "queue_summary.json").write_text(
            json.dumps(queue_summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    final_payload = {
        "event": "edge_minimization_queue",
        "status": "factored" if solved else "no_factor",
        "rank_json": str(args.rank_json.expanduser().resolve()),
        "output_dir": str(output_dir),
        "parameters": {
            "start_index": args.start_index,
            "top": args.top,
            "workers": args.workers,
            "drop_mode": args.drop_mode,
            "drop_windows": args.drop_window,
            "hybrid_cumulative_drop_windows": args.hybrid_cumulative_drop_window,
            "hybrid_independent_drop_windows": args.hybrid_independent_drop_window,
            "q_gap_epsilon": args.q_gap_epsilon,
            "q_gap_max_bits": args.q_gap_max_bits,
            "q_gap_oracle_timeout_seconds": args.q_gap_oracle_timeout_seconds,
            "q_gap_minimize_max_completions": args.q_gap_minimize_max_completions,
            "unique_pairs": args.unique_pairs,
            "initial_ledgers": [str(path) for path in ledgers[: len(initial_ledgers)]],
        },
        "elapsed_seconds": time.time() - started,
        "manifest_output": write_manifest(args.manifest_output, ledgers),
        "records_completed": len(records),
        "records": records,
        "success": solved,
    }
    summary_path = output_dir / "queue_summary.json"
    summary_path.write_text(json.dumps(final_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({**final_payload, "records": f"{len(records)} rows in {summary_path}"}, sort_keys=True))
    else:
        print(
            "status={status} records={records} output={output}".format(
                status=final_payload["status"],
                records=len(records),
                output=summary_path,
            )
        )
    return 0 if solved or args.dry_run else 2


if __name__ == "__main__":
    raise SystemExit(main())
