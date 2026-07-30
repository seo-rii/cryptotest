#!/usr/bin/env python3
"""Run q-gap minimization on representative cube records.

This runner consumes existing JSONL cube ledgers, selects q-gap no-root cube
records, forces each selected cube with --cube-assume-p-range, and invokes
semi_programmatic_sat.py directly.  It intentionally does not load prior learned
clauses: a selected cube is often already blocked by its source ledger, and the
minimization proof only needs the q-gap oracle over the forced cube.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_cube_rep_min_{time.strftime('%Y%m%d_%H%M%S')}"


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


def parse_projection(raw: str) -> tuple[int, int, str]:
    parts = raw.split(":")
    if len(parts) not in {2, 3}:
        raise argparse.ArgumentTypeError("projection must be START:WIDTH[:LABEL]")
    start = int(parts[0], 0)
    width = int(parts[1], 0)
    if start < 0 or width <= 0:
        raise argparse.ArgumentTypeError("projection must have nonnegative start and positive width")
    label = parts[2] if len(parts) == 3 else f"{start}:{width}"
    return start, width, label


def read_path_list(path: Path) -> list[Path]:
    rows: list[Path] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                rows.append(Path(line))
    return rows


def manifest_path_text(path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return str(resolved.relative_to(WORKSPACE))
    except ValueError:
        return str(resolved)


def append_manifest_entries(path: Path, ledgers: list[Path]) -> None:
    seen: set[str] = set()
    rows: list[str] = []
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or line in seen:
                    continue
                seen.add(line)
                rows.append(line)
    for ledger in ledgers:
        text = manifest_path_text(ledger)
        if text in seen:
            continue
        seen.add(text)
        rows.append(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def cube_shape(raw_ranges: object) -> tuple[tuple[int, int], ...] | None:
    if not isinstance(raw_ranges, list):
        return None
    shape: list[tuple[int, int]] = []
    for item in raw_ranges:
        if not isinstance(item, dict):
            return None
        try:
            start = int(item["start"])
            width = int(item["width"])
        except (KeyError, TypeError, ValueError):
            return None
        shape.append((start, width))
    return tuple(sorted(shape))


def compact_value(raw_ranges: object, start: int, width: int) -> int | None:
    if not isinstance(raw_ranges, list):
        return None
    bit_values: dict[int, int] = {}
    for item in raw_ranges:
        if not isinstance(item, dict):
            return None
        try:
            item_start = int(item["start"])
            item_width = int(item["width"])
            item_value = int(item.get("value", 0))
        except (KeyError, TypeError, ValueError):
            return None
        if item_width <= 0 or item_value < 0 or item_value >= (1 << item_width):
            return None
        for offset in range(item_width):
            bit = item_start + offset
            if start <= bit < start + width:
                bit_values[bit] = (item_value >> offset) & 1
    if any((start + offset) not in bit_values for offset in range(width)):
        return None
    value = 0
    for offset in range(width):
        value |= bit_values[start + offset] << offset
    return value


def projection_key(
    raw_ranges: object,
    projections: list[tuple[int, int, str]],
) -> tuple[int, ...] | None:
    values: list[int] = []
    for start, width, _ in projections:
        value = compact_value(raw_ranges, start, width)
        if value is None:
            return None
        values.append(value)
    return tuple(values)


def load_candidate_rows(
    paths: list[Path],
    *,
    shape_filter: tuple[tuple[int, int], ...] | None,
    projections: list[tuple[int, int, str]],
    q_gap_max_bits: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    stats = {
        "files": 0,
        "missing_files": 0,
        "records": 0,
        "cube_records": 0,
        "candidate_records": 0,
        "shape_filtered": 0,
        "status_filtered": 0,
        "gap_filtered": 0,
        "duplicate_projection_filtered": 0,
        "parse_errors": 0,
    }
    seen_projection_keys: set[tuple[int, ...]] = set()
    for path in paths:
        expanded = path.expanduser()
        if not expanded.exists():
            stats["missing_files"] += 1
            continue
        stats["files"] += 1
        with expanded.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                stats["records"] += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    stats["parse_errors"] += 1
                    continue
                if not isinstance(row, dict) or row.get("event") != "cube":
                    continue
                stats["cube_records"] += 1
                raw_ranges = row.get("cube_ranges")
                if shape_filter is not None and cube_shape(raw_ranges) != shape_filter:
                    stats["shape_filtered"] += 1
                    continue
                q_gap = row.get("q_gap_coppersmith") or row
                if q_gap.get("status") != "no_roots" or not q_gap.get("no_root_hard_clause_eligible", True):
                    stats["status_filtered"] += 1
                    continue
                gap_bits = q_gap.get("q_gap_bits", q_gap.get("gap_bits"))
                if gap_bits is not None and int(gap_bits) > q_gap_max_bits:
                    stats["gap_filtered"] += 1
                    continue
                key = projection_key(raw_ranges, projections) if projections else None
                if key is not None:
                    if key in seen_projection_keys:
                        stats["duplicate_projection_filtered"] += 1
                        continue
                    seen_projection_keys.add(key)
                rows.append(
                    {
                        "source_jsonl": str(expanded),
                        "source_line": line_number,
                        "projection_key": list(key) if key is not None else None,
                        "cube_ranges": raw_ranges,
                        "source_q_gap_bits": gap_bits,
                    }
                )
                stats["candidate_records"] += 1
    return rows, stats


def run_command(command: list[str], stdout_path: Path, stderr_path: Path, timeout_seconds: float) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as stdout:
        process = subprocess.Popen(
            command,
            cwd=WORKSPACE,
            text=True,
            stdout=stdout,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            _, stderr = process.communicate(
                timeout=timeout_seconds if timeout_seconds > 0 else None
            )
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                _, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                _, stderr = process.communicate()
            stderr_path.write_text(
                (stderr or "") + f"\ncommand timed out after {timeout_seconds:.1f}s\n",
                encoding="utf-8",
            )
            return 124
    stderr_path.write_text(stderr or "", encoding="utf-8")
    return int(process.returncode)


def jsonl_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-jsonl", action="append", default=[], type=Path)
    parser.add_argument("--source-list", action="append", default=[], type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--append-manifest", type=Path)
    parser.add_argument("--start-index", type=int, default=1)
    parser.add_argument("--top", type=int, default=4)
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--item-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--cube-ranges", default="150:4,265:84,362:58")
    parser.add_argument("--shape", default="150:4,265:84,362:58")
    parser.add_argument("--projection", action="append", default=[], type=parse_projection)
    parser.add_argument("--check-bits", type=int, default=600)
    parser.add_argument("--timeout-ms", type=int, default=2000)
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--q-gap-oracle-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--q-gap-minimize-max-completions", type=int, default=16)
    parser.add_argument(
        "--drop-mode",
        choices=("independent", "cumulative", "hybrid"),
        default="independent",
        help=(
            "independent verifies each --drop-window separately; cumulative verifies "
            "--cumulative-drop-window as a growing union; hybrid does both"
        ),
    )
    parser.add_argument("--drop-window", action="append", default=[])
    parser.add_argument(
        "--cumulative-drop-window",
        action="append",
        default=[],
        help="optional cumulative q-gap drop window START:WIDTH",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.start_index < 1:
        raise SystemExit("--start-index must be positive")
    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")
    if args.item_timeout_seconds < 0:
        raise SystemExit("--item-timeout-seconds must be nonnegative")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.q_gap_minimize_max_completions < 1:
        raise SystemExit("--q-gap-minimize-max-completions must be positive")
    drop_windows = args.drop_window or (["150:4"] if args.drop_mode in {"independent", "hybrid"} else [])
    cumulative_drop_windows = args.cumulative_drop_window or (
        ["150:4"] if args.drop_mode == "cumulative" else []
    )
    if args.drop_mode in {"independent", "hybrid"} and not drop_windows:
        raise SystemExit("drop mode requires at least one --drop-window")
    if args.drop_mode in {"cumulative", "hybrid"} and not cumulative_drop_windows:
        raise SystemExit("drop mode requires at least one --cumulative-drop-window")
    for raw_window in [*drop_windows, *cumulative_drop_windows]:
        _, width = parse_start_width(raw_window)
        if (1 << width) > args.q_gap_minimize_max_completions:
            raise SystemExit(f"drop window {raw_window} exceeds --q-gap-minimize-max-completions")

    sources: list[Path] = []
    for source_list in args.source_list:
        sources.extend(read_path_list(source_list.expanduser()))
    sources.extend(args.source_jsonl)
    if not sources:
        raise SystemExit("at least one --source-jsonl or --source-list is required")

    shape_filter = tuple(sorted(parse_start_width(item.strip()) for item in args.shape.split(",") if item.strip()))
    candidates, load_stats = load_candidate_rows(
        sources,
        shape_filter=shape_filter,
        projections=args.projection,
        q_gap_max_bits=args.q_gap_max_bits,
    )
    selected = candidates[args.start_index - 1 : args.start_index - 1 + args.top]
    if not selected:
        raise SystemExit("no selected candidate rows")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records: list[dict[str, Any]] = []
    manifest_ledgers: list[Path] = []
    solved = None

    for item_index, source in enumerate(selected, start=1):
        if args.max_seconds and time.time() - started >= args.max_seconds:
            break
        item_dir = output_dir / f"item_{item_index:04d}_line_{int(source['source_line']):06d}"
        item_dir.mkdir(parents=True, exist_ok=True)
        out_jsonl = item_dir / "minimization.jsonl"
        stdout_path = item_dir / "stdout.jsonl"
        stderr_path = item_dir / "stderr.txt"
        if out_jsonl.exists():
            rows = jsonl_rows(out_jsonl)
            cube = next((row for row in rows if row.get("event") == "cube"), {})
            summary = next((row for row in rows if row.get("event") == "summary"), {})
            q_gap = cube.get("q_gap_coppersmith") or {}
            factors = q_gap.get("factors") or []
            record = {
                "item": item_index,
                "returncode": None,
                "elapsed_seconds": 0.0,
                "source": source,
                "output_dir": str(item_dir),
                "jsonl": str(out_jsonl),
                "stderr": str(stderr_path),
                "q_gap_status": q_gap.get("status"),
                "q_gap_bits": q_gap.get("q_gap_bits"),
                "learned_clause_scope": cube.get("learned_clause_scope"),
                "learned_clause_count": cube.get("learned_clause_count"),
                "learned_clause_literal_count": cube.get("learned_clause_literal_count"),
                "learned_clause_variants": cube.get("learned_clause_variants"),
                "q_gap_coppersmith_independent_minimization": cube.get(
                    "q_gap_coppersmith_independent_minimization"
                ),
                "q_gap_coppersmith_cumulative_minimization": cube.get(
                    "q_gap_coppersmith_cumulative_minimization"
                ),
                "q_gap_coppersmith_calls": summary.get("q_gap_coppersmith_calls"),
                "q_gap_coppersmith_hard_blocks": summary.get("q_gap_coppersmith_hard_blocks"),
                "q_gap_coppersmith_minimized_blocks": summary.get(
                    "q_gap_coppersmith_minimized_blocks"
                ),
                "factors": factors,
                "resumed": True,
            }
            records.append(record)
            if cube.get("learned_clause") == "q_gap_coppersmith_no_root":
                manifest_ledgers.append(out_jsonl)
            if factors:
                solved = record
                break
            continue
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
            "--q-gap-minimize-max-completions",
            str(args.q_gap_minimize_max_completions),
            "--q-gap-minimize-workers",
            str(args.workers),
            "--q-gap-independent-drop-clauses",
            "--include-cube-ranges",
        ]
        if args.drop_mode in {"independent", "hybrid"}:
            for drop_window in drop_windows:
                command.extend(["--q-gap-drop-window", drop_window])
        if args.drop_mode in {"cumulative", "hybrid"}:
            for drop_window in cumulative_drop_windows:
                command.extend(["--q-gap-cumulative-drop-window", drop_window])
        for raw_range in source["cube_ranges"]:
            command.extend(
                [
                    "--cube-assume-p-range",
                    "{start}:{width}:{value}".format(
                        start=int(raw_range["start"]),
                        width=int(raw_range["width"]),
                        value=int(raw_range.get("value", 0)),
                    ),
                ]
            )
        (item_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
        if args.dry_run:
            record = {
                "item": item_index,
                "status": "dry_run",
                "source": source,
                "output_jsonl": str(out_jsonl),
                "command": command,
            }
            records.append(record)
            continue

        item_started = time.time()
        returncode = run_command(command, stdout_path, stderr_path, args.item_timeout_seconds)
        if stdout_path.exists():
            stdout_path.replace(out_jsonl)
        elif not out_jsonl.exists():
            raise FileNotFoundError(f"missing child JSONL output: {stdout_path}")
        rows = jsonl_rows(out_jsonl)
        cube = next((row for row in rows if row.get("event") == "cube"), {})
        summary = next((row for row in rows if row.get("event") == "summary"), {})
        q_gap = cube.get("q_gap_coppersmith") or {}
        factors = q_gap.get("factors") or []
        record = {
            "item": item_index,
            "returncode": returncode,
            "elapsed_seconds": time.time() - item_started,
            "source": source,
            "output_dir": str(item_dir),
            "jsonl": str(out_jsonl),
            "stderr": str(stderr_path),
            "q_gap_status": q_gap.get("status"),
            "q_gap_bits": q_gap.get("q_gap_bits"),
            "learned_clause_scope": cube.get("learned_clause_scope"),
            "learned_clause_count": cube.get("learned_clause_count"),
            "learned_clause_literal_count": cube.get("learned_clause_literal_count"),
            "learned_clause_variants": cube.get("learned_clause_variants"),
            "q_gap_coppersmith_independent_minimization": cube.get(
                "q_gap_coppersmith_independent_minimization"
            ),
            "q_gap_coppersmith_cumulative_minimization": cube.get(
                "q_gap_coppersmith_cumulative_minimization"
            ),
            "q_gap_coppersmith_calls": summary.get("q_gap_coppersmith_calls"),
            "q_gap_coppersmith_hard_blocks": summary.get("q_gap_coppersmith_hard_blocks"),
            "q_gap_coppersmith_minimized_blocks": summary.get(
                "q_gap_coppersmith_minimized_blocks"
            ),
            "factors": factors,
        }
        records.append(record)
        if cube.get("learned_clause") == "q_gap_coppersmith_no_root":
            manifest_ledgers.append(out_jsonl)
        if factors:
            solved = record
            break
        if returncode not in {0, 2}:
            break

    if args.append_manifest and manifest_ledgers:
        append_manifest_entries(args.append_manifest.expanduser(), manifest_ledgers)

    payload = {
        "event": "cube_representative_minimization",
        "status": "factored" if solved else "no_factor",
        "output_dir": str(output_dir),
        "parameters": {
            "source_jsonl": [str(path) for path in args.source_jsonl],
            "source_list": [str(path) for path in args.source_list],
            "append_manifest": str(args.append_manifest) if args.append_manifest else None,
            "start_index": args.start_index,
            "top": args.top,
            "cube_ranges": args.cube_ranges,
            "shape": args.shape,
            "projection": [
                {"start": start, "width": width, "label": label}
                for start, width, label in args.projection
            ],
            "workers": args.workers,
            "q_gap_epsilon": args.q_gap_epsilon,
            "q_gap_max_bits": args.q_gap_max_bits,
            "q_gap_minimize_max_completions": args.q_gap_minimize_max_completions,
            "drop_mode": args.drop_mode,
            "drop_windows": drop_windows,
            "cumulative_drop_windows": cumulative_drop_windows,
        },
        "load_stats": load_stats,
        "candidates_available": len(candidates),
        "records_completed": len(records),
        "manifest_ledgers": [manifest_path_text(path) for path in manifest_ledgers],
        "elapsed_seconds": time.time() - started,
        "records": records,
        "success": solved,
    }
    summary_path = output_dir / "representative_minimization_summary.json"
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({**payload, "records": f"{len(records)} rows in {summary_path}"}, sort_keys=True))
    else:
        print(
            "status={status} records={records} output={output}".format(
                status=payload["status"],
                records=len(records),
                output=summary_path,
            )
        )
    return 0 if solved or args.dry_run else 2


if __name__ == "__main__":
    raise SystemExit(main())
