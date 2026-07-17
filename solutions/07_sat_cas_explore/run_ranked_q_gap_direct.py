#!/usr/bin/env python3
"""Run q-gap Coppersmith directly on ranked cube records."""

from __future__ import annotations

import argparse
import concurrent.futures
import fcntl
import json
import os
import time
from pathlib import Path
from typing import Any

from branch_partial_coppersmith import decrypt_success
from q_middle_gap_oracle import q_gap_known_parts, run_q_middle_gap_coppersmith
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
DEFAULT_OUTPUT = WORKSPACE / "tmp" / f"ct07_ranked_qgap_direct_{time.strftime('%Y%m%d_%H%M%S')}.json"


def acquire_output_locks(paths: list[Path | None]):
    locks = []
    seen: set[Path] = set()
    for raw_path in paths:
        if raw_path is None:
            continue
        path = raw_path.expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f"{path.name}.lock")
        handle = lock_path.open("w", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise SystemExit(f"output path is locked by another run: {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
        locks.append(handle)
    return locks


def fixed_ranges_from_cube(raw_ranges: object) -> list[FixedRange]:
    if not isinstance(raw_ranges, list):
        raise ValueError("missing cube_ranges")
    ranges: list[FixedRange] = []
    for raw_item in raw_ranges:
        if not isinstance(raw_item, dict):
            raise ValueError("invalid cube range item")
        start = int(raw_item["start"])
        width = int(raw_item["width"])
        value = int(raw_item.get("value", 0))
        ranges.append(FixedRange(start, width, value))
    return ranges


def run_task(task: dict[str, Any]) -> dict[str, Any]:
    instance = load_instance()
    row = task["row"]
    rank_index = int(task["rank_index"])
    try:
        cube_ranges = fixed_ranges_from_cube(row.get("cube_ranges"))
        p_known, p_mask = instance.apply_fixed_ranges(cube_ranges)
        q_known = derive_q_known_bits(instance, p_known, p_mask)
        q_parts = q_gap_known_parts(q_known, q_bits=instance.p_bits)
        if int(q_parts["gap_bits"]) > int(task["q_gap_max_bits"]):
            return {
                "rank_index": rank_index,
                "status": "skipped_gap_above_max",
                "q_gap_bits": int(q_parts["gap_bits"]),
                "x2_value": row.get("x2_value"),
                "x6_value": row.get("x6_value"),
                "cube_ranges": row.get("cube_ranges"),
            }
        report = run_q_middle_gap_coppersmith(
            q_known=q_known,
            n=instance.n,
            q_bits=instance.p_bits,
            p_known=p_known,
            p_mask=p_mask,
            epsilon=float(task["q_gap_epsilon"]),
            min_hard_margin_bits=float(task["min_hard_margin_bits"]),
            timeout_seconds=(
                float(task["oracle_timeout_seconds"])
                if float(task["oracle_timeout_seconds"]) > 0
                else None
            ),
        )
        factors = report.get("factors") or []
        success = None
        if report.get("status") == "factored" and factors:
            first = factors[0]
            success = decrypt_success(
                instance,
                int(str(first["p_hex"]), 16),
                int(str(first["q_hex"]), 16),
                p_known,
                p_mask,
            )
        return {
            "rank_index": rank_index,
            "status": report.get("status"),
            "x2_value": row.get("x2_value"),
            "x6_value": row.get("x6_value"),
            "ranked_q_gap_bits": row.get("q_gap_bits"),
            "q_gap_bits": report.get("q_gap_bits"),
            "q_low_bits": report.get("q_low_bits"),
            "q_prefix_start": report.get("q_prefix_start"),
            "q_known_bits": report.get("q_known_bits"),
            "effective_margin_bits": report.get("effective_margin_bits"),
            "elapsed_seconds": report.get("elapsed_seconds"),
            "roots_returned": report.get("roots_returned"),
            "no_root_hard_clause_eligible": report.get("no_root_hard_clause_eligible"),
            "failure_reason": report.get("failure_reason"),
            "factors": factors,
            "success": success,
            "cube_ranges": row.get("cube_ranges"),
            "learned_clause": (
                "q_gap_coppersmith_no_root"
                if report.get("status") == "no_roots"
                and report.get("no_root_hard_clause_eligible")
                else None
            ),
        }
    except Exception as exc:  # noqa: BLE001 - investigation runner records failures.
        return {
            "rank_index": rank_index,
            "status": "error",
            "x2_value": row.get("x2_value"),
            "x6_value": row.get("x6_value"),
            "failure_reason": f"{type(exc).__name__}: {exc}",
            "cube_ranges": row.get("cube_ranges"),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("rank_json", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--jsonl-output",
        type=Path,
        default=None,
        help="optional JSONL ledger with cube records compatible with --load-learned-jsonl",
    )
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--top", type=int, default=64)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--oracle-timeout-seconds", type=float, default=0.0)
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=0.0,
        help="stop after this wall-clock budget and write a partial summary; 0 disables",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.start_index < 1:
        raise SystemExit("--start-index must be positive")
    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.oracle_timeout_seconds < 0:
        raise SystemExit("--oracle-timeout-seconds must be nonnegative")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")

    output_locks = acquire_output_locks([args.output, args.jsonl_output])

    rank_payload = json.loads(args.rank_json.expanduser().read_text(encoding="utf-8"))
    ranked_rows = list(rank_payload.get("top") or [])
    selected = ranked_rows[args.start_index - 1 : args.start_index - 1 + args.top]
    if not selected:
        raise SystemExit("rank file has no selected rows")

    tasks = [
        {
            "rank_index": args.start_index + offset,
            "row": row,
            "q_gap_max_bits": args.q_gap_max_bits,
            "q_gap_epsilon": args.q_gap_epsilon,
            "min_hard_margin_bits": args.min_hard_margin_bits,
            "oracle_timeout_seconds": args.oracle_timeout_seconds,
        }
        for offset, row in enumerate(selected)
    ]

    started = time.time()
    records: list[dict[str, Any]] = []
    success = None
    stopped_reason = "completed"
    jsonl_handle = None
    if args.jsonl_output is not None:
        jsonl_output = args.jsonl_output.expanduser().resolve()
        jsonl_output.parent.mkdir(parents=True, exist_ok=True)
        jsonl_handle = jsonl_output.open("w", encoding="utf-8")
    executor = concurrent.futures.ProcessPoolExecutor(max_workers=args.workers)
    try:
        pending = {
            executor.submit(run_task, task): int(task["rank_index"])
            for task in tasks
        }
        while pending:
            if args.max_seconds and time.time() - started >= args.max_seconds:
                stopped_reason = "max_seconds"
                for future in pending:
                    future.cancel()
                break
            done, _ = concurrent.futures.wait(
                pending,
                timeout=1.0,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not done:
                continue
            for future in done:
                rank_index = pending.pop(future)
                try:
                    record = future.result()
                except Exception as exc:  # noqa: BLE001 - investigation runner records failures.
                    record = {
                        "rank_index": rank_index,
                        "status": "error",
                        "failure_reason": f"{type(exc).__name__}: {exc}",
                    }
                records.append(record)
                if jsonl_handle is not None:
                    row = {
                        "event": "cube",
                        "source": "run_ranked_q_gap_direct",
                        "rank_index": record.get("rank_index"),
                        "cube_ranges": record.get("cube_ranges"),
                        "q_gap_coppersmith": {
                            "status": record.get("status"),
                            "q_gap_bits": record.get("q_gap_bits"),
                            "q_low_bits": record.get("q_low_bits"),
                            "q_prefix_start": record.get("q_prefix_start"),
                            "q_known_bits": record.get("q_known_bits"),
                            "elapsed_seconds": record.get("elapsed_seconds"),
                            "roots_returned": record.get("roots_returned"),
                            "no_root_hard_clause_eligible": record.get(
                                "no_root_hard_clause_eligible"
                            ),
                            "failure_reason": record.get("failure_reason"),
                            "factors": record.get("factors") or [],
                        },
                        "learned_clause": record.get("learned_clause"),
                        "learned_clause_scope": (
                            "q_gap_selected_bits" if record.get("learned_clause") else None
                        ),
                        "learned_clause_literal_count": sum(
                            int(item.get("width", 0))
                            for item in record.get("cube_ranges") or []
                            if isinstance(item, dict)
                        ),
                    }
                    print(json.dumps(row, sort_keys=True), file=jsonl_handle)
                    jsonl_handle.flush()
                if record.get("success") is not None:
                    success = record
                    stopped_reason = "factored"
                    for future in pending:
                        future.cancel()
                    pending.clear()
                    break
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        if jsonl_handle is not None:
            jsonl_handle.close()

    records.sort(key=lambda item: int(item.get("rank_index", 0)))
    status_counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1

    payload = {
        "event": "run_ranked_q_gap_direct",
        "status": "factored" if success else "no_factor",
        "rank_json": str(args.rank_json.expanduser().resolve()),
        "parameters": {
            "start_index": args.start_index,
            "top": args.top,
            "workers": args.workers,
            "q_gap_max_bits": args.q_gap_max_bits,
            "q_gap_epsilon": args.q_gap_epsilon,
            "min_hard_margin_bits": args.min_hard_margin_bits,
            "oracle_timeout_seconds": args.oracle_timeout_seconds,
            "max_seconds": args.max_seconds,
        },
        "elapsed_seconds": time.time() - started,
        "records_completed": len(records),
        "records_requested": len(tasks),
        "stopped_reason": stopped_reason,
        "status_counts": dict(sorted(status_counts.items())),
        "success": success,
        "records": records,
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.jsonl_output is not None:
        jsonl_output = args.jsonl_output.expanduser().resolve()
        jsonl_output.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_output.open("a", encoding="utf-8") as handle:
            print(
                json.dumps(
                    {
                        "event": "summary",
                        "source": "run_ranked_q_gap_direct",
                        "records": len(records),
                        "records_requested": len(tasks),
                        "stopped_reason": stopped_reason,
                        "status_counts": status_counts,
                    },
                    sort_keys=True,
                ),
                file=handle,
            )
    if args.json:
        console = dict(payload)
        console["records"] = f"{len(records)} rows in {output}"
        print(json.dumps(console, sort_keys=True))
    else:
        print(f"status={payload['status']} records={len(records)} output={output}")
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
