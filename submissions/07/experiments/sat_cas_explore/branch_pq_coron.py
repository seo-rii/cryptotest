#!/usr/bin/env python3
"""Run folded p/q bivariate Coron attempts on saved branch candidates."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any

from branch_partial_coppersmith import DEFAULT_CRYPTO_ATTACKS, decrypt_success
from branch_q_gap_coppersmith import item_fixed_ranges, load_candidates
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


HERE = Path(__file__).resolve().parent


def bit_slice(value: int, start: int, stop: int) -> int:
    return (value >> start) & ((1 << (stop - start)) - 1)


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


def build_folded_partials(instance, p_known: int, p_mask: int):
    from shared.partial_integer import PartialInteger

    p_unknown_mask = instance.full_mask ^ p_mask
    if not p_unknown_mask:
        return None, None, {"status": "p_fully_known"}
    p_low_bits = (p_unknown_mask & -p_unknown_mask).bit_length() - 1
    p_high_start = p_unknown_mask.bit_length()
    p_gap_bits = p_high_start - p_low_bits

    q_known = derive_q_known_bits(instance, p_known, p_mask)
    q_gap_bits = q_known.prefix_start - q_known.low_bits
    if p_gap_bits <= 0 or q_gap_bits <= 0:
        return None, None, {
            "status": "nonpositive_gap",
            "p_low_bits": p_low_bits,
            "p_high_start": p_high_start,
            "p_gap_bits": p_gap_bits,
            "q_low_bits": q_known.low_bits,
            "q_prefix_start": q_known.prefix_start,
            "q_gap_bits": q_gap_bits,
        }

    partial_p = PartialInteger()
    partial_p.add_known(bit_slice(p_known, 0, p_low_bits), p_low_bits)
    partial_p.add_unknown(p_gap_bits)
    partial_p.add_known(bit_slice(p_known, p_high_start, instance.p_bits), instance.p_bits - p_high_start)

    partial_q = PartialInteger()
    partial_q.add_known(q_known.known & ((1 << q_known.low_bits) - 1), q_known.low_bits)
    partial_q.add_unknown(q_gap_bits)
    partial_q.add_known(q_known.known >> q_known.prefix_start, instance.p_bits - q_known.prefix_start)

    return partial_p, partial_q, {
        "status": "ok",
        "p_low_bits": p_low_bits,
        "p_high_start": p_high_start,
        "p_gap_bits": p_gap_bits,
        "q_low_bits": q_known.low_bits,
        "q_prefix_start": q_known.prefix_start,
        "q_gap_bits": q_gap_bits,
        "q_prefix_bits": q_known.prefix_bits,
        "q_known_bits": q_known.mask.bit_count(),
    }


def run_factorize_pq_once(
    *,
    crypto_attacks: Path,
    n: int,
    partial_p,
    partial_q,
    k: int,
) -> dict[str, Any]:
    started = time.time()
    if str(crypto_attacks) not in sys.path:
        sys.path.insert(0, str(crypto_attacks))
    from attacks.factorization.coppersmith import factorize_pq

    p_bounds = [int(bound).bit_length() - 1 for bound in partial_p.get_unknown_bounds()]
    q_bounds = [int(bound).bit_length() - 1 for bound in partial_q.get_unknown_bounds()]
    try:
        factors = factorize_pq(n, partial_p, partial_q, k=k)
    except BaseException as exc:  # noqa: BLE001 - records investigative failures.
        return {
            "status": "error",
            "k": k,
            "elapsed_seconds": time.time() - started,
            "p_bounds_bits": p_bounds,
            "q_bounds_bits": q_bounds,
            "failure_reason": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": "factored" if factors else "no_factor",
        "k": k,
        "elapsed_seconds": time.time() - started,
        "p_bounds_bits": p_bounds,
        "q_bounds_bits": q_bounds,
        "factors": None if factors is None else [hex(int(factors[0])), hex(int(factors[1]))],
    }


def run_with_timeout(*, timeout_seconds: float, **kwargs) -> dict[str, Any]:
    if timeout_seconds <= 0:
        return run_factorize_pq_once(**kwargs)

    result_queue: mp.Queue[dict[str, Any]] = mp.Queue(maxsize=1)

    def child() -> None:
        result_queue.put(run_factorize_pq_once(**kwargs))

    started = time.time()
    process = mp.Process(target=child)
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2.0)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(2.0)
        return {
            "status": "timeout",
            "k": kwargs["k"],
            "elapsed_seconds": time.time() - started,
            "failure_reason": f"factorize_pq exceeded {timeout_seconds}s",
        }
    if not result_queue.empty():
        return result_queue.get()
    return {
        "status": "error",
        "k": kwargs["k"],
        "elapsed_seconds": time.time() - started,
        "failure_reason": f"child exited without result, exitcode={process.exitcode}",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-json", action="append", type=Path, default=[])
    parser.add_argument("--summary-json", type=Path, default=HERE / "branch_pq_coron_summary.json")
    parser.add_argument("--candidate-start", type=int, default=1)
    parser.add_argument("--candidate-stop", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--crypto-attacks", type=Path, default=DEFAULT_CRYPTO_ATTACKS)
    parser.add_argument("--k-values", type=parse_range_list, default=parse_range_list("1-4"))
    parser.add_argument("--attempt-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--max-gap-bits", type=int, default=0, help="skip if p or q folded gap exceeds this; 0 disables")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.candidate_start < 1:
        raise SystemExit("--candidate-start must be at least 1")
    if args.candidate_stop and args.candidate_stop < args.candidate_start:
        raise SystemExit("--candidate-stop must be 0 or at least --candidate-start")
    if args.limit < 0:
        raise SystemExit("--limit must be nonnegative")
    if args.attempt_timeout_seconds < 0:
        raise SystemExit("--attempt-timeout-seconds must be nonnegative")
    if args.max_gap_bits < 0:
        raise SystemExit("--max-gap-bits must be nonnegative")

    crypto_attacks = args.crypto_attacks.expanduser().resolve()
    if not (crypto_attacks / "attacks" / "factorization" / "coppersmith.py").exists():
        raise SystemExit(f"crypto-attacks checkout not found: {crypto_attacks}")
    if str(crypto_attacks) not in sys.path:
        sys.path.insert(0, str(crypto_attacks))

    instance = load_instance()
    if args.candidate_json:
        all_candidates, source_summaries = load_candidates(args.candidate_json, 0)
        stop_index = args.candidate_stop or len(all_candidates)
        candidates = all_candidates[args.candidate_start - 1 : stop_index]
        if args.limit:
            candidates = candidates[: args.limit]
    else:
        candidates = [{"source_path": None, "source_event": "direct_fix_p_range", "ordinal_in_source": 1, "item": {}}]
        source_summaries = [{"path": None, "status": "direct", "items": 1}]

    started = time.time()
    results: list[dict[str, Any]] = []
    success: dict[str, Any] | None = None
    for index, candidate in enumerate(candidates, start=1):
        item = candidate["item"]
        if args.candidate_json:
            fixed_ranges, parse_error = item_fixed_ranges(item)
        else:
            fixed_ranges = list(args.fix_p_range)
            parse_error = None
        record: dict[str, Any] = {
            "global_index": index,
            "source_path": candidate["source_path"],
            "source_event": candidate["source_event"],
            "ordinal_in_source": candidate["ordinal_in_source"],
            "rank": item.get("rank"),
            "attempts": [],
        }
        if parse_error is not None:
            record.update({"status": "invalid_candidate", "failure_reason": parse_error})
            results.append(record)
            continue
        try:
            p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)
            partial_p, partial_q, meta = build_folded_partials(instance, p_known, p_mask)
        except Exception as exc:
            record.update({"status": "invalid_branch", "failure_reason": str(exc)})
            results.append(record)
            continue
        record.update(meta)
        record["p_fixed_bits"] = p_mask.bit_count()
        record["all_fixed_ranges_text"] = [
            f"{fixed.start}:{fixed.width}=0x{fixed.value:x}"
            for fixed in sorted(fixed_ranges, key=lambda value: value.start)
        ]
        if partial_p is None or partial_q is None:
            record["status"] = "skipped_no_folded_partial"
            results.append(record)
            continue
        if args.max_gap_bits and (
            int(meta.get("p_gap_bits", 0)) > args.max_gap_bits
            or int(meta.get("q_gap_bits", 0)) > args.max_gap_bits
        ):
            record["status"] = "skipped_gap_above_max"
            results.append(record)
            continue

        for k_value in args.k_values:
            attempt = run_with_timeout(
                timeout_seconds=args.attempt_timeout_seconds,
                crypto_attacks=crypto_attacks,
                n=instance.n,
                partial_p=partial_p,
                partial_q=partial_q,
                k=k_value,
            )
            record["attempts"].append(attempt)
            factors = attempt.get("factors")
            if attempt.get("status") == "factored" and isinstance(factors, list) and len(factors) == 2:
                success = decrypt_success(
                    instance,
                    int(str(factors[0]), 16),
                    int(str(factors[1]), 16),
                    p_known,
                    p_mask,
                )
                record["success"] = success
                record["status"] = "factored" if success else "invalid_factor"
                break
        else:
            status_counts: dict[str, int] = {}
            for attempt in record["attempts"]:
                status = str(attempt.get("status"))
                status_counts[status] = status_counts.get(status, 0) + 1
            record["status"] = "no_factor"
            record["attempt_status_counts"] = status_counts
        results.append(record)
        if success:
            break

    status_counts: dict[str, int] = {}
    for row in results:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "event": "branch_pq_coron",
        "status": "factored" if success else "no_factor",
        "elapsed_seconds": time.time() - started,
        "candidate_paths": [str(path) for path in args.candidate_json],
        "source_summaries": source_summaries,
        "parameters": {
            "crypto_attacks": str(crypto_attacks),
            "k_values": args.k_values,
            "candidate_start": args.candidate_start,
            "candidate_stop": args.candidate_stop,
            "limit": args.limit,
            "attempt_timeout_seconds": args.attempt_timeout_seconds,
            "max_gap_bits": args.max_gap_bits,
        },
        "candidates_tested": len(results),
        "status_counts": status_counts,
        "success": success,
        "results": results,
    }
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        console = dict(summary)
        console["results"] = f"{len(results)} rows written to {args.summary_json}"
        print(json.dumps(console, sort_keys=True))
    else:
        print(f"status={summary['status']} candidates={len(results)} output={args.summary_json}")
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
