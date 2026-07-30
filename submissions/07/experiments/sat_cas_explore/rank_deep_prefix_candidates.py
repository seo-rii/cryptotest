#!/usr/bin/env python3
"""Rescore saved q-gap candidates with deeper exact Hensel prefix checks."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from branch_q_gap_coppersmith import item_fixed_ranges
from q_middle_gap_oracle import q_gap_bound_report, q_gap_known_parts
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, z3_hensel_prefix_status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--partial-candidates-output", type=Path)
    parser.add_argument("--candidate-start", type=int, default=1)
    parser.add_argument("--candidate-stop", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--partial-limit", type=int, default=0)
    parser.add_argument("--prefix-bits", action="append", type=int, default=[])
    parser.add_argument("--timeout-ms", type=int, default=1500)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.04)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.candidate_start < 1:
        raise SystemExit("--candidate-start must be at least 1")
    if args.candidate_stop and args.candidate_stop < args.candidate_start:
        raise SystemExit("--candidate-stop must be 0 or at least --candidate-start")
    if args.limit < 0:
        raise SystemExit("--limit must be nonnegative")
    if args.partial_limit < 0:
        raise SystemExit("--partial-limit must be nonnegative")
    if args.timeout_ms < 1:
        raise SystemExit("--timeout-ms must be positive")

    prefix_bits = args.prefix_bits or [430, 500, 600]
    if any(value <= 0 or value > 1024 for value in prefix_bits):
        raise SystemExit("--prefix-bits values must be in 1..1024")
    prefix_bits = sorted(dict.fromkeys(prefix_bits))

    data = json.loads(args.input_json.read_text(encoding="utf-8"))
    source_event: str | None = None
    source_key = "list"
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("top"), list):
        items = data["top"]
        source_event = data.get("event")
        source_key = "top"
    elif isinstance(data, dict) and isinstance(data.get("results"), list):
        items = data["results"]
        source_event = data.get("event")
        source_key = "results"
    elif isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
        source_event = data.get("event")
        source_key = "items"
    else:
        raise SystemExit(f"unsupported candidate JSON format: {args.input_json}")

    stop_index = args.candidate_stop or len(items)
    items = items[args.candidate_start - 1 : stop_index]
    if args.limit:
        items = items[: args.limit]

    instance = load_instance()
    started = time.time()
    results: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    prefix_status_counts: dict[str, dict[str, int]] = {
        str(prefix): {} for prefix in prefix_bits
    }

    for ordinal, item in enumerate(items, start=args.candidate_start):
        if not isinstance(item, dict):
            results.append(
                {
                    "status": "invalid_candidate",
                    "ordinal_in_source": ordinal,
                    "failure_reason": "candidate item is not an object",
                }
            )
            status_counts["invalid_candidate"] = status_counts.get("invalid_candidate", 0) + 1
            continue

        fixed_ranges, parse_error = item_fixed_ranges(item)
        if parse_error is not None and isinstance(item.get("cube_ranges"), list):
            try:
                fixed_ranges = [
                    FixedRange(
                        int(raw_range["start"]),
                        int(raw_range["width"]),
                        int(raw_range.get("value", 0)),
                    )
                    for raw_range in item["cube_ranges"]
                ]
                parse_error = None
            except Exception as exc:  # noqa: BLE001 - scorer records malformed input.
                parse_error = f"failed to parse cube_ranges: {exc}"

        record: dict[str, Any] = {
            "source_path": str(args.input_json),
            "source_event": source_event,
            "source_key": source_key,
            "ordinal_in_source": ordinal,
            "source_rank": item.get("rank"),
            "x2_value": item.get("x2_value"),
            "x6_value": item.get("x6_value"),
            "source_q_gap_bits": item.get("q_gap_bits"),
            "source_score_q_gap_bits": item.get("score_q_gap_bits"),
            "source_pair_seen_count": item.get("pair_seen_count"),
        }
        if parse_error is not None:
            record.update({"status": "invalid_candidate", "failure_reason": parse_error})
            results.append(record)
            status_counts["invalid_candidate"] = status_counts.get("invalid_candidate", 0) + 1
            continue

        fixed_ranges = sorted(fixed_ranges, key=lambda value: value.start)
        record["all_fixed_ranges_text"] = [
            f"{fixed.start}:{fixed.width}=0x{fixed.value:x}" for fixed in fixed_ranges
        ]

        try:
            p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)
            q_known = derive_q_known_bits(instance, p_known, p_mask)
        except Exception as exc:  # noqa: BLE001 - exact branch inconsistency is useful output.
            record.update({"status": "invalid_branch", "failure_reason": str(exc)})
            results.append(record)
            status_counts["invalid_branch"] = status_counts.get("invalid_branch", 0) + 1
            continue

        q_parts = q_gap_known_parts(q_known, q_bits=instance.p_bits)
        q_bound = q_gap_bound_report(
            n=instance.n,
            low_bits=int(q_parts["low_bits"]),
            prefix_start=int(q_parts["prefix_start"]),
            epsilon=args.q_gap_epsilon,
            min_hard_margin_bits=args.min_hard_margin_bits,
        )
        residual_unknown_blocks: list[int] = []
        position = 0
        while position < instance.p_bits:
            known_bit = (p_mask >> position) & 1
            start = position
            while position < instance.p_bits and ((p_mask >> position) & 1) == known_bit:
                position += 1
            if not known_bit:
                residual_unknown_blocks.append(position - start)

        record.update(
            {
                "p_fixed_bits": p_mask.bit_count(),
                "remaining_unknown_bits": instance.p_bits - p_mask.bit_count(),
                "remaining_unknown_blocks": residual_unknown_blocks,
                "remaining_product_bound_bits": sum(residual_unknown_blocks),
                "q_low_bits": q_known.low_bits,
                "q_prefix_bits": q_known.prefix_bits,
                "q_prefix_start": q_known.prefix_start,
                "q_known_bits": q_known.mask.bit_count(),
                "q_gap_bits": int(q_parts["gap_bits"]),
                "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                "q_gap_hard_bound_eligible": bool(q_bound["hard_clause_bound_eligible"]),
                "q_gap_effective_margin_bits": float(q_bound["effective_margin_bits"]),
                "deep_prefix_checks": [],
            }
        )

        overall_status = "sat"
        max_sat_prefix_bits = 0
        max_checked_prefix_bits = 0
        unknown_count = 0
        unsat_prefix_bits: int | None = None
        for prefix in prefix_bits:
            check_started = time.time()
            status, meta = z3_hensel_prefix_status(
                instance=instance,
                p_known=p_known,
                p_mask=p_mask,
                prefix_bits=prefix,
                timeout_ms=args.timeout_ms,
            )
            elapsed = time.time() - check_started
            prefix_status_counts[str(prefix)][status] = (
                prefix_status_counts[str(prefix)].get(status, 0) + 1
            )
            max_checked_prefix_bits = max(max_checked_prefix_bits, prefix)
            if status == "sat":
                max_sat_prefix_bits = max(max_sat_prefix_bits, prefix)
            elif status == "unknown":
                unknown_count += 1
                if overall_status == "sat":
                    overall_status = "unknown"
            else:
                overall_status = "unsat"
                unsat_prefix_bits = prefix
            record["deep_prefix_checks"].append(
                {
                    "prefix_bits": prefix,
                    "status": status,
                    "elapsed_seconds": elapsed,
                    "meta": meta,
                }
            )
            if status == "unsat":
                break

        record.update(
            {
                "status": overall_status,
                "deep_prefix_status": overall_status,
                "max_sat_prefix_bits": max_sat_prefix_bits,
                "max_checked_prefix_bits": max_checked_prefix_bits,
                "deep_prefix_unknown_count": unknown_count,
                "unsat_prefix_bits": unsat_prefix_bits,
            }
        )
        results.append(record)
        status_counts[overall_status] = status_counts.get(overall_status, 0) + 1

    def score_key(row: dict[str, Any]) -> tuple[Any, ...]:
        status = row.get("status")
        status_rank = 0 if status == "sat" else 1 if status == "unknown" else 2
        return (
            status_rank,
            -int(row.get("max_sat_prefix_bits", -1)),
            int(row.get("deep_prefix_unknown_count", 10**9)),
            int(row.get("q_gap_bits", row.get("source_q_gap_bits", 10**9))),
            int(row.get("source_score_q_gap_bits", 10**9)),
            -int(row.get("q_known_bits", -1)),
            int(row.get("q_interval_width_bits", 10**9)),
            int(row.get("remaining_product_bound_bits", 10**9)),
            int(row.get("source_pair_seen_count", 0) or 0),
            int(row.get("ordinal_in_source", 10**9)),
        )

    ranked_results = sorted(results, key=score_key)
    viable_results = [
        row for row in ranked_results if row.get("status") in {"sat", "unknown"}
    ]
    partial_limit = args.partial_limit or len(viable_results)
    partial_results = [
        dict(row, rank=index)
        for index, row in enumerate(viable_results[:partial_limit], start=1)
    ]

    summary = {
        "event": "rank_deep_prefix_candidates",
        "status": "completed",
        "input_json": str(args.input_json),
        "parameters": {
            "candidate_start": args.candidate_start,
            "candidate_stop": args.candidate_stop,
            "limit": args.limit,
            "partial_limit": args.partial_limit,
            "prefix_bits": prefix_bits,
            "timeout_ms": args.timeout_ms,
            "q_gap_epsilon": args.q_gap_epsilon,
            "min_hard_margin_bits": args.min_hard_margin_bits,
        },
        "elapsed_seconds": time.time() - started,
        "source_event": source_event,
        "source_key": source_key,
        "candidates_tested": len(results),
        "status_counts": status_counts,
        "prefix_status_counts": prefix_status_counts,
        "viable_count": len(viable_results),
        "dead_unsat_count": sum(1 for row in results if row.get("status") == "unsat"),
        "top_viable": partial_results,
        "results": ranked_results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.partial_candidates_output is not None:
        args.partial_candidates_output.parent.mkdir(parents=True, exist_ok=True)
        partial_payload = {
            "event": "rank_deep_prefix_partial_candidates",
            "source_summary": {
                "path": str(args.output),
                "status_counts": status_counts,
                "prefix_status_counts": prefix_status_counts,
                "viable_count": len(viable_results),
            },
            "results": partial_results,
        }
        args.partial_candidates_output.write_text(
            json.dumps(partial_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if args.json:
        console = dict(summary)
        console["results"] = f"{len(ranked_results)} rows written to {args.output}"
        console["top_viable"] = f"{len(partial_results)} rows"
        print(json.dumps(console, sort_keys=True))
    else:
        print(
            "status=completed "
            f"candidates={len(results)} viable={len(viable_results)} output={args.output}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
