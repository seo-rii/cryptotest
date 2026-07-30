#!/usr/bin/env python3
"""Sweep the two corrected 4-bit edge gaps with partial-p Coppersmith."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path
from typing import Any

from branch_partial_coppersmith import (
    DEFAULT_CRYPTO_ATTACKS,
    build_partial_integer,
    decrypt_success,
)
from sat_cas_core import FixedRange, load_instance


HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[2]


def parse_range_list(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            values.extend(range(int(left, 0), int(right, 0) + 1))
        else:
            values.append(int(part, 0))
    if not values:
        raise argparse.ArgumentTypeError("expected at least one value")
    return values


def bit_slice(value: int, start: int, stop: int) -> int:
    return (value >> start) & ((1 << (stop - start)) - 1)


def build_edge_partial(*, p_known: int, p_mask: int, p_bits: int, model: str):
    if model == "exact":
        return build_partial_integer(p_known=p_known, p_mask=p_mask, p_bits=p_bits)
    if model == "x1_middle362":
        from shared.partial_integer import PartialInteger

        partial = PartialInteger()
        partial.add_known(bit_slice(p_known, 0, 265), 265)
        partial.add_unknown(84)
        partial.add_known(bit_slice(p_known, 349, 362), 13)
        partial.add_unknown(468)
        partial.add_known(bit_slice(p_known, 830, 1024), 194)
        return partial

    if model != "middle_x5":
        raise ValueError(f"unknown model: {model}")

    from shared.partial_integer import PartialInteger

    partial = PartialInteger()
    partial.add_known(bit_slice(p_known, 0, 265), 265)
    partial.add_unknown(504)
    partial.add_known(bit_slice(p_known, 769, 784), 15)
    partial.add_unknown(46)
    partial.add_known(bit_slice(p_known, 830, 1024), 194)
    return partial


def edge_task(task: dict[str, Any]) -> dict[str, Any]:
    crypto_attacks = Path(task["crypto_attacks"])
    if str(crypto_attacks) not in sys.path:
        sys.path.insert(0, str(crypto_attacks))
    from attacks.factorization.coppersmith import factorize_p

    instance = load_instance()
    x0 = int(task["x0"])
    x7 = int(task["x7"])
    m = int(task["m"])
    t = int(task["t"])
    model = str(task["model"])
    fixed_ranges = [FixedRange(150, 4, x0), FixedRange(920, 4, x7)]
    started = time.time()
    p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)
    partial = build_edge_partial(p_known=p_known, p_mask=p_mask, p_bits=instance.p_bits, model=model)
    bounds_bits = [int(bound).bit_length() - 1 for bound in partial.get_unknown_bounds()]
    try:
        factors = factorize_p(instance.n, partial, beta=0.5, m=m, t=t)
        attempt: dict[str, Any] = {
            "status": "factored" if factors else "no_factor",
            "m": m,
            "t": t,
            "elapsed_seconds": time.time() - started,
            "unknowns": partial.unknowns,
            "bounds_bits": bounds_bits,
            "factors": None if factors is None else [hex(int(factors[0])), hex(int(factors[1]))],
        }
    except BaseException as exc:  # noqa: BLE001 - investigation driver records failures.
        attempt = {
            "status": "error",
            "m": m,
            "t": t,
            "elapsed_seconds": time.time() - started,
            "unknowns": partial.unknowns,
            "bounds_bits": bounds_bits,
            "failure_reason": f"{type(exc).__name__}: {exc}",
        }
    success = None
    factors = attempt.get("factors")
    if attempt.get("status") == "factored" and isinstance(factors, list) and len(factors) == 2:
        success = decrypt_success(instance, int(str(factors[0]), 16), int(str(factors[1]), 16), p_known, p_mask)
    return {
        "x0": x0,
        "x7": x7,
        "m": m,
        "t": t,
        "model": model,
        "status": "factored" if success else str(attempt.get("status")),
        "elapsed_seconds": time.time() - started,
        "p_fixed_bits": p_mask.bit_count(),
        "remaining_unknown_blocks": partial.unknowns,
        "remaining_bounds_bits": [
            int(bound).bit_length() - 1 for bound in partial.get_unknown_bounds()
        ],
        "attempt": attempt,
        "success": success,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-json", type=Path, default=HERE / "edge_partial_coppersmith_summary.json")
    parser.add_argument("--crypto-attacks", type=Path, default=DEFAULT_CRYPTO_ATTACKS)
    parser.add_argument("--m-values", type=parse_range_list, default=parse_range_list("2"))
    parser.add_argument("--t-values", type=parse_range_list, default=parse_range_list("1"))
    parser.add_argument(
        "--model",
        choices=("exact", "middle_x5", "x1_middle362"),
        default="exact",
        help=(
            "exact keeps every corrected unknown block; middle_x5 coarsens "
            "[265,769) plus x5 into two variables; x1_middle362 coarsens "
            "x1 plus [362,830) into two variables"
        ),
    )
    parser.add_argument("--x0-values", type=parse_range_list, default=parse_range_list("0-15"))
    parser.add_argument("--x7-values", type=parse_range_list, default=parse_range_list("0-15"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--jsonl", type=Path, help="optional streaming JSONL result path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    crypto_attacks = args.crypto_attacks.expanduser().resolve()
    if not (crypto_attacks / "attacks" / "factorization" / "coppersmith.py").exists():
        raise SystemExit(f"crypto-attacks checkout not found: {crypto_attacks}")
    if args.workers < 1:
        raise SystemExit("--workers must be positive")

    tasks = [
        {
            "crypto_attacks": str(crypto_attacks),
            "x0": x0,
            "x7": x7,
            "m": m,
            "t": t,
            "model": args.model,
        }
        for m in args.m_values
        for t in args.t_values
        for x0 in args.x0_values
        for x7 in args.x7_values
    ]
    started = time.time()
    results: list[dict[str, Any]] = []
    success: dict[str, Any] | None = None
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    jsonl_handle = None
    if args.jsonl is not None:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        jsonl_handle = args.jsonl.open("w", encoding="utf-8")
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
            future_to_task = {executor.submit(edge_task, task): task for task in tasks}
            for future in concurrent.futures.as_completed(future_to_task):
                row = future.result()
                results.append(row)
                if jsonl_handle is not None:
                    jsonl_handle.write(json.dumps(row, sort_keys=True) + "\n")
                    jsonl_handle.flush()
                if row.get("success") and success is None:
                    success = row["success"]
                    for pending in future_to_task:
                        if not pending.done():
                            pending.cancel()
                    break
    finally:
        if jsonl_handle is not None:
            jsonl_handle.close()

    status_counts: dict[str, int] = {}
    for row in results:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "event": "edge_partial_coppersmith_sweep",
        "status": "factored" if success else "no_factor",
        "elapsed_seconds": time.time() - started,
        "parameters": {
            "crypto_attacks": str(crypto_attacks),
            "m_values": args.m_values,
            "t_values": args.t_values,
            "model": args.model,
            "x0_values": args.x0_values,
            "x7_values": args.x7_values,
            "workers": args.workers,
            "task_count": len(tasks),
        },
        "results_completed": len(results),
        "status_counts": dict(sorted(status_counts.items())),
        "success": success,
        "results": sorted(results, key=lambda row: (int(row["m"]), int(row["t"]), int(row["x0"]), int(row["x7"]))),
    }
    args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        console = dict(summary)
        console["results"] = f"{len(results)} rows written to {args.summary_json}"
        print(json.dumps(console, sort_keys=True))
    else:
        print(f"status={summary['status']} completed={len(results)} output={args.summary_json}")
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
