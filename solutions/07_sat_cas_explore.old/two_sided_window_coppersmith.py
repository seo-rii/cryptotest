#!/usr/bin/env python3
"""Two-sided p middle-window Coppersmith oracle for challenge 7."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from pathlib import Path
from typing import Any

from sat_cas_core import FixedRange, load_instance, parse_fixed_range


DEFAULT_EPSILON = 0.005
DEFAULT_MIN_HARD_MARGIN_BITS = 8.0


def parse_window(text: str) -> tuple[int, int]:
    try:
        low_text, high_text = text.replace(":", ",").split(",", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected L:H") from exc
    low = int(low_text, 0)
    high = int(high_text, 0)
    if low < 0 or high <= low or high > 1024:
        raise argparse.ArgumentTypeError("window must satisfy 0 <= L < H <= 1024")
    return low, high


def fixed_range_from_record(row: dict[str, Any]) -> FixedRange:
    return FixedRange(int(row["start"]), int(row["width"]), int(row["value"]))


def load_candidate_ranges(path: Path) -> list[list[FixedRange]]:
    with path.open() as handle:
        data = json.load(handle)
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError(f"{path} does not contain an items list")
    result: list[list[FixedRange]] = []
    for item in items:
        ranges = item.get("fixed_ranges")
        if not isinstance(ranges, list):
            raise ValueError(f"candidate missing fixed_ranges: {item!r}")
        result.append([fixed_range_from_record(row) for row in ranges])
    return result


def bound_report(
    *,
    n_bits: int,
    middle_bits: int,
    epsilon: float,
    min_hard_margin_bits: float,
) -> dict[str, Any]:
    effective_bound_bits = (0.25 - epsilon) * n_bits - 1.0
    effective_margin_bits = effective_bound_bits - middle_bits
    return {
        "middle_bits": middle_bits,
        "epsilon": epsilon,
        "n_bit_length": n_bits,
        "effective_bound_bits": effective_bound_bits,
        "effective_margin_bits": effective_margin_bits,
        "theorem_margin_bits": n_bits / 4.0 - middle_bits,
        "min_hard_margin_bits": min_hard_margin_bits,
        "hard_clause_bound_eligible": effective_margin_bits >= min_hard_margin_bits,
    }


def direct_oracle(
    *,
    n: int,
    e: int,
    ct: int,
    p_known: int,
    p_mask: int,
    low: int,
    high: int,
    epsilon: float,
    min_hard_margin_bits: float,
) -> dict[str, Any]:
    started = time.time()
    all_bits_mask = (1 << 1024) - 1
    low_part = p_known & ((1 << low) - 1)
    high_part = p_known & (all_bits_mask ^ ((1 << high) - 1))
    const = low_part | high_part
    middle_bits = high - low
    outside_mask = ((1 << low) - 1) | (all_bits_mask ^ ((1 << high) - 1))
    missing_outside_mask = outside_mask & ~p_mask
    report: dict[str, Any] = {
        "window": [low, high],
        "low_part_hex": hex(low_part),
        "high_part_hex": hex(high_part),
        "const_hex": hex(const),
        "p_fixed_bits": int(p_mask).bit_count(),
        "missing_outside_bits": int(missing_outside_mask).bit_count(),
        **bound_report(
            n_bits=int(n).bit_length(),
            middle_bits=middle_bits,
            epsilon=epsilon,
            min_hard_margin_bits=min_hard_margin_bits,
        ),
    }
    if missing_outside_mask:
        return {
            **report,
            "status": "insufficient_fixed_bits",
            "elapsed_seconds": time.time() - started,
            "roots_returned": 0,
            "roots_sample": [],
            "factors": [],
            "failure_reason": "bits outside the middle window are not fully fixed",
            "hard_clause_eligible": False,
            "no_root_hard_clause_eligible": False,
        }

    try:
        from sage.all import PolynomialRing, ZZ, Zmod

        ring = Zmod(n)
        poly_ring = PolynomialRing(ring, "y")
        y = poly_ring.gen()
        polynomial = (ring(const) + ring(1 << low) * y).monic()
        roots = polynomial.small_roots(X=ZZ(1) << middle_bits, beta=0.5, epsilon=epsilon)
    except Exception as exc:
        return {
            **report,
            "status": "coppersmith_error",
            "elapsed_seconds": time.time() - started,
            "roots_returned": 0,
            "roots_sample": [],
            "factors": [],
            "failure_reason": str(exc),
            "hard_clause_eligible": False,
            "no_root_hard_clause_eligible": False,
        }

    factors: list[dict[str, Any]] = []
    for root in roots:
        p = int(const + (int(root) << low))
        if not (1 < p < n) or n % p != 0:
            continue
        q = n // p
        if (p & p_mask) != (p_known & p_mask):
            continue
        phi = (p - 1) * (q - 1)
        d = pow(e, -1, phi)
        plaintext = pow(ct, d, n)
        plaintext_bytes = plaintext.to_bytes((plaintext.bit_length() + 7) // 8, "big")
        factors.append(
            {
                "root": int(root),
                "p_hex": hex(p),
                "q_hex": hex(q),
                "p_bit_length": p.bit_length(),
                "q_bit_length": q.bit_length(),
                "p_times_q_equals_n": p * q == n,
                "p_matches_mask": (p & p_mask) == (p_known & p_mask),
                "plaintext_hex": plaintext_bytes.hex(),
                "plaintext_utf8": plaintext_bytes.decode("utf-8", errors="replace"),
            }
        )

    status = "factored" if factors else "no_roots"
    hard = status == "no_roots" and bool(report["hard_clause_bound_eligible"])
    return {
        **report,
        "status": status,
        "elapsed_seconds": time.time() - started,
        "roots_returned": len(roots),
        "roots_sample": [int(root) for root in roots[:8]],
        "factors": factors,
        "failure_reason": None if factors else "small_roots returned no valid divisor of N",
        "hard_clause_eligible": hard,
        "no_root_hard_clause_eligible": hard,
    }


def run_oracle_with_timeout(
    *,
    timeout_seconds: float,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        return direct_oracle(**kwargs)
    queue: mp.Queue[dict[str, Any]] = mp.Queue(maxsize=1)

    def child() -> None:
        queue.put(direct_oracle(**kwargs))

    process = mp.Process(target=child)
    started = time.time()
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2.0)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(2.0)
        low = kwargs["low"]
        high = kwargs["high"]
        return {
            "window": [low, high],
            "status": "timeout",
            "elapsed_seconds": time.time() - started,
            "middle_bits": high - low,
            "epsilon": kwargs["epsilon"],
            "roots_returned": 0,
            "roots_sample": [],
            "factors": [],
            "failure_reason": f"small_roots exceeded {timeout_seconds}s",
            "hard_clause_eligible": False,
            "no_root_hard_clause_eligible": False,
        }
    if queue.empty():
        return {
            "window": [kwargs["low"], kwargs["high"]],
            "status": "coppersmith_error",
            "elapsed_seconds": time.time() - started,
            "roots_returned": 0,
            "roots_sample": [],
            "factors": [],
            "failure_reason": f"child exited without result, exitcode={process.exitcode}",
            "hard_clause_eligible": False,
            "no_root_hard_clause_eligible": False,
        }
    return queue.get()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=parse_window, required=True, help="middle p window L:H")
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--candidate-json", type=Path)
    parser.add_argument("--candidate-start", type=int, default=1)
    parser.add_argument("--candidate-stop", type=int, default=0)
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON)
    parser.add_argument("--min-hard-margin-bits", type=float, default=DEFAULT_MIN_HARD_MARGIN_BITS)
    parser.add_argument("--oracle-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    low, high = args.window
    instance = load_instance()
    candidate_ranges = [[]]
    if args.candidate_json is not None:
        candidate_ranges = load_candidate_ranges(args.candidate_json)
    start_index = max(1, args.candidate_start)
    stop_index = args.candidate_stop or len(candidate_ranges)
    selected = candidate_ranges[start_index - 1 : stop_index]

    records: list[dict[str, Any]] = []
    for offset, ranges in enumerate(selected, start=start_index):
        all_ranges = list(args.fix_p_range) + list(ranges)
        try:
            p_known, p_mask = instance.apply_fixed_ranges(all_ranges)
        except ValueError as exc:
            records.append({"index": offset, "status": "inconsistent_fixed_ranges", "failure_reason": str(exc)})
            continue
        report = run_oracle_with_timeout(
            timeout_seconds=args.oracle_timeout_seconds,
            kwargs={
                "n": instance.n,
                "e": instance.e,
                "ct": instance.ct,
                "p_known": p_known,
                "p_mask": p_mask,
                "low": low,
                "high": high,
                "epsilon": args.epsilon,
                "min_hard_margin_bits": args.min_hard_margin_bits,
            },
        )
        records.append(
            {
                "index": offset,
                "fixed_ranges": [
                    {"start": item.start, "width": item.width, "value": item.value}
                    for item in all_ranges
                ],
                **report,
            }
        )
        if report.get("factors"):
            break

    status_counts: dict[str, int] = {}
    factor_count = 0
    for row in records:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        factor_count += len(row.get("factors") or [])
    summary = {
        "event": "two_sided_window_coppersmith",
        "window": [low, high],
        "candidate_count": len(records),
        "status_counts": status_counts,
        "factor_count": factor_count,
        "records": records,
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(
            f"status={'factored' if factor_count else 'no_factor'} "
            f"candidates={len(records)} factors={factor_count}"
        )
        for row in records:
            print(json.dumps(row, sort_keys=True))
    return 0 if factor_count else 2


if __name__ == "__main__":
    raise SystemExit(main())
