#!/usr/bin/env python3
"""Resumable q-gap cumulative union proof runner.

This verifies that every completion of a set of dropped p bits still gives a
hard q-gap Coppersmith no-root.  When all shards pass, it writes a compact
learned-clause JSONL record that semi_programmatic_sat.py can load.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
from pathlib import Path
from typing import Any

from sat_cas_core import FixedRange, load_instance, parse_fixed_range
from semi_programmatic_sat import compact_unit_ranges, evaluate_q_gap_completion_task


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]
DEFAULT_OUTPUT_DIR = WORKSPACE / "tmp" / f"ct07_qgap_union_{time.strftime('%Y%m%d_%H%M%S')}"


def parse_window(text: str) -> tuple[int, int]:
    try:
        start_text, width_text = text.split(":", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected START:WIDTH") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    if start < 0 or width <= 0:
        raise argparse.ArgumentTypeError("START must be nonnegative and WIDTH positive")
    return start, width


def expand_ranges_to_units(ranges: list[FixedRange]) -> list[FixedRange]:
    units: list[FixedRange] = []
    for item in ranges:
        for offset in range(item.width):
            units.append(FixedRange(item.start + offset, 1, (item.value >> offset) & 1))
    return units


def json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def shard_path(output_dir: Path, shard_index: int) -> Path:
    return output_dir / f"shard_{shard_index:06d}.json"


def load_existing_shard(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("event") != "q_gap_union_shard":
        return None
    return payload


def proof_parameters_from(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "cube_ranges": parameters["cube_ranges"],
        "cube_ranges_without_drop": parameters["cube_ranges_without_drop"],
        "drop_windows": parameters["drop_windows"],
        "drop_bits": parameters["drop_bits"],
        "completion_count": parameters["completion_count"],
        "shard_size": parameters["shard_size"],
        "shard_count": parameters["shard_count"],
        "q_gap_max_bits": parameters["q_gap_max_bits"],
        "q_gap_epsilon": parameters["q_gap_epsilon"],
        "q_gap_min_hard_margin_bits": parameters["q_gap_min_hard_margin_bits"],
        "q_gap_oracle_timeout_seconds": parameters["q_gap_oracle_timeout_seconds"],
    }


def proof_key_from(proof_parameters: dict[str, Any]) -> str:
    return json.dumps(proof_parameters, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--cube-range",
        action="append",
        default=[],
        type=parse_fixed_range,
        help="fixed selected p range START:WIDTH:VALUE; repeatable",
    )
    parser.add_argument(
        "--drop-window",
        action="append",
        default=[],
        type=parse_window,
        help="cumulative dropped p-bit window START:WIDTH; repeatable",
    )
    parser.add_argument("--shard-size", type=int, default=512)
    parser.add_argument("--shard-start", type=int, default=0)
    parser.add_argument("--shard-stop", type=int, default=0, help="exclusive shard index; 0 means all")
    parser.add_argument("--max-new-shards", type=int, default=0, help="maximum new shards to process; 0 means no limit")
    parser.add_argument("--max-seconds", type=float, default=0.0, help="stop before starting a new shard after this many seconds; 0 means no limit")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--q-gap-max-bits", type=int, default=445)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.028)
    parser.add_argument("--q-gap-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--q-gap-oracle-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not args.cube_range:
        raise SystemExit("provide at least one --cube-range START:WIDTH:VALUE")
    if not args.drop_window:
        raise SystemExit("provide at least one --drop-window START:WIDTH")
    if args.shard_size < 1:
        raise SystemExit("--shard-size must be positive")
    if args.shard_start < 0:
        raise SystemExit("--shard-start must be nonnegative")
    if args.shard_stop < 0:
        raise SystemExit("--shard-stop must be nonnegative")
    if args.max_new_shards < 0:
        raise SystemExit("--max-new-shards must be nonnegative")
    if args.max_seconds < 0:
        raise SystemExit("--max-seconds must be nonnegative")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.q_gap_max_bits < 0:
        raise SystemExit("--q-gap-max-bits must be nonnegative")
    if args.q_gap_min_hard_margin_bits < 0:
        raise SystemExit("--q-gap-min-hard-margin-bits must be nonnegative")
    if args.q_gap_oracle_timeout_seconds < 0:
        raise SystemExit("--q-gap-oracle-timeout-seconds must be nonnegative")

    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    instance = load_instance()
    cube_units = expand_ranges_to_units(list(args.cube_range))
    cube_bit_values = {item.start: item.value for item in cube_units}
    drop_bits: list[int] = []
    for start, width in args.drop_window:
        for bit in range(start, start + width):
            if bit not in cube_bit_values:
                raise SystemExit(f"drop bit {bit} is not present in --cube-range")
            if bit not in drop_bits:
                drop_bits.append(bit)
    drop_bits.sort()
    completion_count = 1 << len(drop_bits)
    shard_count = (completion_count + args.shard_size - 1) // args.shard_size
    shard_stop = args.shard_stop or shard_count
    if args.shard_start >= shard_count:
        raise SystemExit("--shard-start is outside the completion range")
    if shard_stop > shard_count:
        raise SystemExit("--shard-stop exceeds the completion range")
    if shard_stop <= args.shard_start:
        raise SystemExit("--shard-stop must be greater than --shard-start")

    cube_ranges_without_drop = [item for item in cube_units if item.start not in set(drop_bits)]
    parameters = {
        "cube_ranges": compact_unit_ranges(cube_units),
        "cube_ranges_without_drop": compact_unit_ranges(cube_ranges_without_drop),
        "drop_windows": [{"start": start, "width": width} for start, width in args.drop_window],
        "drop_bits": drop_bits,
        "completion_count": completion_count,
        "shard_size": args.shard_size,
        "shard_count": shard_count,
        "shard_start": args.shard_start,
        "shard_stop": shard_stop,
        "max_new_shards": args.max_new_shards,
        "max_seconds": args.max_seconds,
        "workers": args.workers,
        "q_gap_max_bits": args.q_gap_max_bits,
        "q_gap_epsilon": args.q_gap_epsilon,
        "q_gap_min_hard_margin_bits": args.q_gap_min_hard_margin_bits,
        "q_gap_oracle_timeout_seconds": args.q_gap_oracle_timeout_seconds,
    }
    proof_parameters = proof_parameters_from(parameters)
    proof_key = proof_key_from(proof_parameters)
    parameters["proof_parameters"] = proof_parameters
    parameters["proof_key"] = proof_key
    parameters_path = output_dir / "parameters.json"
    if args.resume and parameters_path.exists():
        try:
            existing_parameters = json.loads(parameters_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"could not read existing parameters.json: {exc}") from exc
        existing_proof_key = existing_parameters.get("proof_key")
        if existing_proof_key is not None and existing_proof_key != proof_key:
            raise SystemExit("existing parameters.json proof_key does not match current proof parameters")
    if args.dry_run:
        payload = {
            "event": "q_gap_union_dry_run",
            "output_dir": str(output_dir),
            **parameters,
        }
        print(json.dumps(payload, sort_keys=True) if args.json else json.dumps(payload, indent=2, sort_keys=True))
        return 0
    json_dump(parameters_path, {"event": "q_gap_union_parameters", **parameters})

    started = time.time()
    processed_shards = 0
    skipped_shards = 0
    hard_eligible_total = 0
    oracle_calls_total = 0
    status_counts_total: dict[str, int] = {}
    factors: list[object] = []
    failed_shards: list[int] = []

    for shard_index in range(args.shard_start, shard_stop):
        path = shard_path(output_dir, shard_index)
        existing = load_existing_shard(path) if args.resume else None
        if existing is not None and existing.get("status") == "passed":
            if existing.get("proof_key") != proof_key:
                raise SystemExit(
                    f"existing shard {path} has mismatched or missing proof_key; "
                    "do not resume with different proof parameters"
                )
            skipped_shards += 1
            hard_eligible_total += int(existing.get("hard_eligible_completion_count", 0))
            oracle_calls_total += int(existing.get("oracle_called_count", 0))
            for status, count in dict(existing.get("status_counts", {})).items():
                status_counts_total[str(status)] = status_counts_total.get(str(status), 0) + int(count)
            continue

        if args.max_new_shards and processed_shards >= args.max_new_shards:
            break
        if args.max_seconds and time.time() - started >= args.max_seconds:
            break

        completion_start = shard_index * args.shard_size
        completion_stop = min(completion_count, completion_start + args.shard_size)
        tasks = [
            {
                "instance": instance,
                "fixed_ranges": [],
                "cube_ranges_without_window": cube_ranges_without_drop,
                "completion_bits": drop_bits,
                "completion_value": completion_value,
                "q_gap_max_bits": args.q_gap_max_bits,
                "q_gap_epsilon": args.q_gap_epsilon,
                "q_gap_min_hard_margin_bits": args.q_gap_min_hard_margin_bits,
                "q_gap_oracle_timeout_seconds": args.q_gap_oracle_timeout_seconds,
            }
            for completion_value in range(completion_start, completion_stop)
        ]

        shard_started = time.time()
        with concurrent.futures.ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as executor:
            results = list(executor.map(evaluate_q_gap_completion_task, tasks))

        status_counts: dict[str, int] = {}
        hard_eligible_count = 0
        oracle_called_count = 0
        shard_factors: list[object] = []
        bad_examples: list[dict[str, Any]] = []
        for result in results:
            status = str(result.get("status"))
            status_counts[status] = status_counts.get(status, 0) + 1
            status_counts_total[status] = status_counts_total.get(status, 0) + 1
            if result.get("oracle_called"):
                oracle_called_count += 1
            if result.get("hard_eligible"):
                hard_eligible_count += 1
            else:
                if len(bad_examples) < 8:
                    bad_examples.append(
                        {
                            "completion_value": result.get("completion_value"),
                            "status": status,
                            "q_gap_bits": result.get("q_gap_bits"),
                            "report": result.get("report"),
                        }
                    )
            if result.get("factors"):
                shard_factors.extend(result.get("factors") or [])

        oracle_calls_total += oracle_called_count
        hard_eligible_total += hard_eligible_count
        shard_status = "passed" if hard_eligible_count == len(tasks) and not shard_factors else "factored" if shard_factors else "failed"
        shard_payload = {
            "event": "q_gap_union_shard",
            "status": shard_status,
            "proof_key": proof_key,
            "proof_parameters": proof_parameters,
            "shard_index": shard_index,
            "completion_start": completion_start,
            "completion_stop": completion_stop,
            "completion_count": len(tasks),
            "elapsed_seconds": time.time() - shard_started,
            "hard_eligible_completion_count": hard_eligible_count,
            "oracle_called_count": oracle_called_count,
            "status_counts": status_counts,
            "factors": shard_factors,
            "bad_examples": bad_examples,
        }
        json_dump(path, shard_payload)
        processed_shards += 1
        if shard_factors:
            factors.extend(shard_factors)
            json_dump(output_dir / "factored.json", {"event": "factored", "factors": factors, **parameters})
            break
        if shard_status != "passed":
            failed_shards.append(shard_index)

        summary = {
            "event": "q_gap_union_progress",
            "status": "running",
            "output_dir": str(output_dir),
            "elapsed_seconds": time.time() - started,
            "processed_shards": processed_shards,
            "skipped_shards": skipped_shards,
            "failed_shards": failed_shards,
            "hard_eligible_total": hard_eligible_total,
            "oracle_calls_total": oracle_calls_total,
            "status_counts": dict(sorted(status_counts_total.items())),
            **parameters,
        }
        json_dump(output_dir / "summary.json", summary)

    all_shards = []
    missing_shards = []
    final_status_counts: dict[str, int] = {}
    for shard_index in range(shard_count):
        payload = load_existing_shard(shard_path(output_dir, shard_index))
        if payload is None:
            missing_shards.append(shard_index)
        else:
            if payload.get("proof_key") != proof_key:
                raise SystemExit(
                    f"shard_{shard_index:06d}.json has mismatched or missing proof_key; "
                    "proof summary cannot mix parameters"
                )
            all_shards.append(payload)
            for status, count in dict(payload.get("status_counts", {})).items():
                final_status_counts[str(status)] = final_status_counts.get(str(status), 0) + int(count)

    all_completed = not missing_shards and all(item.get("status") == "passed" for item in all_shards)
    final_status = "factored" if factors else "proved" if all_completed else "partial"
    final_payload = {
        "event": "q_gap_union_summary",
        "status": final_status,
        "output_dir": str(output_dir),
        "elapsed_seconds": time.time() - started,
        "processed_shards": processed_shards,
        "skipped_shards": skipped_shards,
        "missing_shards": missing_shards[:20],
        "missing_shard_count": len(missing_shards),
        "failed_shards": failed_shards,
        "hard_eligible_total": sum(int(item.get("hard_eligible_completion_count", 0)) for item in all_shards),
        "oracle_calls_total": sum(int(item.get("oracle_called_count", 0)) for item in all_shards),
        "status_counts": dict(sorted(final_status_counts.items())),
        "factors": factors,
        **parameters,
    }
    json_dump(output_dir / "summary.json", final_payload)

    if all_completed:
        learned_record = {
            "event": "cube",
            "index": 1,
            "selected_bits": len(cube_units),
            "cube_ranges": compact_unit_ranges(cube_units),
            "learned_clause": "q_gap_coppersmith_no_root",
            "learned_clause_scope": "minimized_q_gap_selected_bits",
            "learned_clause_literal_count": len(cube_units) - len(drop_bits),
            "learned_clause_dropped_literal_count": len(drop_bits),
            "learned_clause_dropped_bits": drop_bits,
            "q_gap_coppersmith_union_proof": {
                "status": "proved",
                "completion_count": completion_count,
                "shard_count": shard_count,
                "hard_eligible_completion_count": final_payload["hard_eligible_total"],
                "oracle_calls": final_payload["oracle_calls_total"],
                "q_gap_max_bits": args.q_gap_max_bits,
                "q_gap_epsilon": args.q_gap_epsilon,
                "q_gap_min_hard_margin_bits": args.q_gap_min_hard_margin_bits,
                "proof_key": proof_key,
            },
        }
        learned_path = output_dir / "learned_clause.jsonl"
        learned_path.write_text(json.dumps(learned_record, sort_keys=True) + "\n", encoding="utf-8")
        final_payload["learned_clause_jsonl"] = str(learned_path)
        json_dump(output_dir / "summary.json", final_payload)

    if args.json:
        print(json.dumps(final_payload, sort_keys=True))
    else:
        print(
            "status={status} processed={processed} skipped={skipped} missing={missing} output={output}".format(
                status=final_status,
                processed=processed_shards,
                skipped=skipped_shards,
                missing=len(missing_shards),
                output=output_dir / "summary.json",
            )
        )
    return 0 if final_status in {"proved", "factored", "partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
