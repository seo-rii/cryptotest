#!/usr/bin/env python3
"""Analyze fixed-union low-Coppersmith shard JSON outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for raw_path in args.inputs:
        path = Path(raw_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary = payload["summary"] if isinstance(payload.get("summary"), dict) else payload
        rows.append(
            {
                "path": str(path),
                "low_bits": int(summary.get("low_bits", 0) or 0),
                "epsilon": summary.get("epsilon"),
                "min_hard_margin_bits": summary.get("min_hard_margin_bits"),
                "completion_start": int(summary["completion_start"]),
                "completion_stop": int(summary["completion_stop"]),
                "checked_completion_count_per_variant": int(
                    summary["checked_completion_count_per_variant"]
                ),
                "completion_count_per_variant": int(summary["completion_count_per_variant"]),
                "dropped_literal_count": int(summary["dropped_literal_count"]),
                "remaining_common_literal_count": int(summary["remaining_common_literal_count"]),
                "unique_oracle_cases": int(summary["unique_oracle_cases"]),
                "total_completion_checks": int(summary["total_completion_checks"]),
                "hard_eligible_total_count": int(summary["hard_eligible_total_count"]),
                "all_completions_no_roots": bool(summary["all_completions_no_roots"]),
                "factor_count": int(summary["factor_count"]),
                "roots_returned_unique_total": int(summary["roots_returned_unique_total"]),
                "status_counts_unique": summary.get("status_counts_unique", {}),
                "status_counts_total": summary.get("status_counts_total", {}),
                "dropped_bits": summary.get("dropped_bits", []),
            }
        )

    rows.sort(key=lambda row: (row["completion_start"], row["completion_stop"], row["path"]))
    merged: list[dict[str, int]] = []
    for row in rows:
        start = row["completion_start"]
        stop = row["completion_stop"]
        if merged and start <= merged[-1]["stop"]:
            if stop > merged[-1]["stop"]:
                merged[-1]["stop"] = stop
            continue
        merged.append({"start": start, "stop": stop})

    completion_count = rows[0]["completion_count_per_variant"] if rows else 0
    missing: list[dict[str, int]] = []
    cursor = 0
    for item in merged:
        if item["start"] > cursor:
            missing.append({"start": cursor, "stop": item["start"]})
        cursor = max(cursor, item["stop"])
    if completion_count and cursor < completion_count:
        missing.append({"start": cursor, "stop": completion_count})

    covered = sum(item["stop"] - item["start"] for item in merged)
    checked_completion_count = sum(row["checked_completion_count_per_variant"] for row in rows)
    summary_out = {
        "event": "low_coppersmith_union_shard_analyzer",
        "input_count": len(rows),
        "low_bits_values": sorted({row["low_bits"] for row in rows}),
        "epsilon_values": sorted({str(row["epsilon"]) for row in rows}),
        "min_hard_margin_bits_values": sorted({str(row["min_hard_margin_bits"]) for row in rows}),
        "completion_count_per_variant": completion_count,
        "covered_completion_count_per_variant": covered,
        "checked_completion_count_per_variant": checked_completion_count,
        "overlap_completion_count_per_variant": checked_completion_count - covered,
        "coverage_fraction": (covered / completion_count) if completion_count else 0,
        "merged_ranges": merged,
        "missing_ranges": missing,
        "all_shards_no_roots": all(row["all_completions_no_roots"] for row in rows),
        "factor_count_total": sum(row["factor_count"] for row in rows),
        "roots_returned_unique_total": sum(row["roots_returned_unique_total"] for row in rows),
        "total_completion_checks": sum(row["total_completion_checks"] for row in rows),
        "unique_oracle_cases_total": sum(row["unique_oracle_cases"] for row in rows),
        "hard_eligible_total_count": sum(row["hard_eligible_total_count"] for row in rows),
        "dropped_literal_count": rows[0]["dropped_literal_count"] if rows else 0,
        "remaining_common_literal_count": rows[0]["remaining_common_literal_count"] if rows else 0,
        "dropped_bits": rows[0]["dropped_bits"] if rows else [],
    }
    payload_out = {"summary": summary_out, "rows": rows}
    if args.json:
        print(json.dumps(payload_out, sort_keys=True))
    else:
        print(
            "coverage "
            f"{covered}/{completion_count} "
            f"inputs={len(rows)} "
            f"all_no_roots={summary_out['all_shards_no_roots']} "
            f"factors={summary_out['factor_count_total']}"
        )
        print(f"merged: {merged}")
        print(f"missing: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
