#!/usr/bin/env python3
"""Run crypto-attacks partial-p Coppersmith on saved branch candidates."""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from typing import Any

from branch_q_gap_coppersmith import item_fixed_ranges, load_candidates
from sat_cas_core import FixedRange, load_instance, parse_fixed_range


HERE = Path(__file__).resolve().parent
CRYPTOTEST_ROOT = HERE.parents[1]
WORKSPACE = HERE.parents[2]
DEFAULT_CRYPTO_ATTACKS = WORKSPACE / "tmp" / "crypto-attacks"


def int_to_bytes(value: int) -> bytes:
    return int(value).to_bytes(max(1, (int(value).bit_length() + 7) // 8), "big")


def build_partial_integer(*, p_known: int, p_mask: int, p_bits: int):
    from shared.partial_integer import PartialInteger

    partial = PartialInteger()
    position = 0
    while position < p_bits:
        known_bit = (p_mask >> position) & 1
        start = position
        while position < p_bits and ((p_mask >> position) & 1) == known_bit:
            position += 1
        width = position - start
        if known_bit:
            partial.add_known((p_known >> start) & ((1 << width) - 1), width)
        else:
            partial.add_unknown(width)
    return partial


def decrypt_success(instance, p: int, q: int, p_known: int, p_mask: int) -> dict[str, Any] | None:
    p = int(p)
    q = int(q)
    if not (1 < p < instance.n) or p * q != instance.n:
        return None
    if (p & instance.mask) != instance.known:
        return None
    if (p & p_mask) != (p_known & p_mask):
        return None
    phi = (p - 1) * (q - 1)
    d = pow(instance.e, -1, phi)
    plaintext_int = pow(instance.ct, d, instance.n)
    plaintext_bytes = int_to_bytes(plaintext_int)
    try:
        plaintext_utf8 = plaintext_bytes.decode("utf-8")
    except UnicodeDecodeError:
        plaintext_utf8 = None
    return {
        "p_hex": hex(p),
        "q_hex": hex(q),
        "p_bit_length": p.bit_length(),
        "q_bit_length": q.bit_length(),
        "p_times_q_equals_n": p * q == instance.n,
        "p_matches_original_mask": (p & instance.mask) == instance.known,
        "p_matches_branch_mask": (p & p_mask) == (p_known & p_mask),
        "plaintext_hex_big_endian": plaintext_bytes.hex(),
        "plaintext_utf8": plaintext_utf8,
    }


def run_factorize_p_once(
    *,
    crypto_attacks: Path,
    n: int,
    p_known: int,
    p_mask: int,
    p_bits: int,
    m: int,
    t: int,
) -> dict[str, Any]:
    started = time.time()
    if str(crypto_attacks) not in sys.path:
        sys.path.insert(0, str(crypto_attacks))
    from attacks.factorization.coppersmith import factorize_p

    partial = build_partial_integer(p_known=p_known, p_mask=p_mask, p_bits=p_bits)
    bounds_bits = [int(bound).bit_length() - 1 for bound in partial.get_unknown_bounds()]
    try:
        factors = factorize_p(n, partial, beta=0.5, m=m, t=t)
    except BaseException as exc:  # noqa: BLE001 - investigation driver records failures.
        return {
            "status": "error",
            "m": m,
            "t": t,
            "elapsed_seconds": time.time() - started,
            "unknowns": partial.unknowns,
            "bounds_bits": bounds_bits,
            "failure_reason": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": "factored" if factors else "no_factor",
        "m": m,
        "t": t,
        "elapsed_seconds": time.time() - started,
        "unknowns": partial.unknowns,
        "bounds_bits": bounds_bits,
        "factors": None if factors is None else [hex(int(factors[0])), hex(int(factors[1]))],
    }


def run_factorize_with_optional_timeout(
    *,
    crypto_attacks: Path,
    n: int,
    p_known: int,
    p_mask: int,
    p_bits: int,
    m: int,
    t: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        return run_factorize_p_once(
            crypto_attacks=crypto_attacks,
            n=n,
            p_known=p_known,
            p_mask=p_mask,
            p_bits=p_bits,
            m=m,
            t=t,
        )

    result_queue: mp.Queue[dict[str, Any]] = mp.Queue(maxsize=1)

    def child() -> None:
        result_queue.put(
            run_factorize_p_once(
                crypto_attacks=crypto_attacks,
                n=n,
                p_known=p_known,
                p_mask=p_mask,
                p_bits=p_bits,
                m=m,
                t=t,
            )
        )

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
            "m": m,
            "t": t,
            "elapsed_seconds": time.time() - started,
            "failure_reason": f"factorize_p exceeded {timeout_seconds}s",
        }
    if not result_queue.empty():
        return result_queue.get()
    return {
        "status": "error",
        "m": m,
        "t": t,
        "elapsed_seconds": time.time() - started,
        "failure_reason": f"child exited without result, exitcode={process.exitcode}",
    }


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


def constants_sanity() -> dict[str, Any]:
    constants_path = CRYPTOTEST_ROOT / "src" / "investigate_rsa_partial_bits.py"
    spec = importlib.util.spec_from_file_location("c7_constants", constants_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load constants from {constants_path}")
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)
    return {
        "constants_path": str(constants_path),
        "n_bit_length": int(constants.N_HEX.replace(" ", ""), 16).bit_length(),
        "e": int(constants.E),
        "ct_bit_length": int(constants.CT_HEX.replace(" ", ""), 16).bit_length(),
    }


def evaluate_candidate_task(task: dict[str, Any]) -> dict[str, Any]:
    crypto_attacks = Path(str(task["crypto_attacks"]))
    instance = load_instance()
    candidate = task["candidate"]
    item = candidate["item"]
    if bool(task["use_candidate_json"]):
        fixed_ranges, parse_error = item_fixed_ranges(item)
    else:
        fixed_ranges = [
            FixedRange(int(start), int(width), int(value))
            for start, width, value in task["fix_p_ranges"]
        ]
        parse_error = None
    record: dict[str, Any] = {
        "global_index": int(task["global_index"]),
        "source_path": candidate["source_path"],
        "source_event": candidate["source_event"],
        "ordinal_in_source": candidate["ordinal_in_source"],
        "rank": item.get("rank"),
        "attempts": [],
    }
    if parse_error is not None:
        record.update({"status": "invalid_candidate", "failure_reason": parse_error})
        return {"record": record, "success": None}

    try:
        p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)
    except Exception as exc:
        record.update({"status": "invalid_branch", "failure_reason": str(exc)})
        return {"record": record, "success": None}

    partial = build_partial_integer(p_known=p_known, p_mask=p_mask, p_bits=instance.p_bits)
    record.update(
        {
            "status": "running",
            "p_fixed_bits": p_mask.bit_count(),
            "remaining_unknown_bits": instance.p_bits - p_mask.bit_count(),
            "remaining_unknown_blocks": partial.unknowns,
            "remaining_bounds_bits": [
                int(bound).bit_length() - 1 for bound in partial.get_unknown_bounds()
            ],
            "all_fixed_ranges_text": [
                f"{item.start}:{item.width}=0x{item.value:x}"
                for item in sorted(fixed_ranges, key=lambda value: value.start)
            ],
        }
    )

    success = None
    for m in task["m_values"]:
        for t in task["t_values"]:
            attempt = run_factorize_with_optional_timeout(
                crypto_attacks=crypto_attacks,
                n=instance.n,
                p_known=p_known,
                p_mask=p_mask,
                p_bits=instance.p_bits,
                m=int(m),
                t=int(t),
                timeout_seconds=float(task["attempt_timeout_seconds"]),
            )
            record["attempts"].append(attempt)
            if attempt.get("status") == "factored":
                factor_hex = attempt.get("factors") or []
                if len(factor_hex) == 2:
                    success = decrypt_success(
                        instance,
                        int(str(factor_hex[0]), 16),
                        int(str(factor_hex[1]), 16),
                        p_known,
                        p_mask,
                    )
                record["status"] = "factored" if success else "invalid_factor"
                record["success"] = success
                break
        if success:
            break
    else:
        status_counts: dict[str, int] = {}
        for attempt in record["attempts"]:
            status = str(attempt.get("status"))
            status_counts[status] = status_counts.get(status, 0) + 1
        record["status"] = "no_factor"
        record["attempt_status_counts"] = status_counts
    return {"record": record, "success": success}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-json", action="append", type=Path, default=[])
    parser.add_argument("--summary-json", type=Path, default=HERE / "branch_partial_coppersmith_summary.json")
    parser.add_argument("--candidate-start", type=int, default=1)
    parser.add_argument("--candidate-stop", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--crypto-attacks", type=Path, default=DEFAULT_CRYPTO_ATTACKS)
    parser.add_argument("--m-values", type=parse_range_list, default=parse_range_list("2"))
    parser.add_argument("--t-values", type=parse_range_list, default=parse_range_list("1"))
    parser.add_argument("--attempt-timeout-seconds", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--jsonl", type=Path)
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
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    crypto_attacks = args.crypto_attacks.expanduser().resolve()
    if not (crypto_attacks / "attacks" / "factorization" / "coppersmith.py").exists():
        raise SystemExit(f"crypto-attacks checkout not found: {crypto_attacks}")
    if str(crypto_attacks) not in sys.path:
        sys.path.insert(0, str(crypto_attacks))

    instance = load_instance()
    candidates: list[dict[str, Any]]
    source_summaries: list[dict[str, Any]]
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
    task_template = {
        "crypto_attacks": str(crypto_attacks),
        "use_candidate_json": bool(args.candidate_json),
        "fix_p_ranges": [
            (item.start, item.width, item.value) for item in args.fix_p_range
        ],
        "m_values": args.m_values,
        "t_values": args.t_values,
        "attempt_timeout_seconds": args.attempt_timeout_seconds,
    }
    tasks = [
        dict(task_template, global_index=index, candidate=candidate)
        for index, candidate in enumerate(candidates, start=1)
    ]
    jsonl_handle = None
    if args.jsonl is not None:
        args.jsonl.parent.mkdir(parents=True, exist_ok=True)
        jsonl_handle = args.jsonl.open("w", encoding="utf-8")
    try:
        if args.workers == 1:
            for task in tasks:
                payload = evaluate_candidate_task(task)
                record = payload["record"]
                results.append(record)
                if jsonl_handle is not None:
                    jsonl_handle.write(json.dumps(record, sort_keys=True) + "\n")
                    jsonl_handle.flush()
                if payload.get("success"):
                    success = payload["success"]
                    break
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
                future_to_index = {
                    executor.submit(evaluate_candidate_task, task): int(task["global_index"])
                    for task in tasks
                }
                for future in concurrent.futures.as_completed(future_to_index):
                    payload = future.result()
                    record = payload["record"]
                    results.append(record)
                    if jsonl_handle is not None:
                        jsonl_handle.write(json.dumps(record, sort_keys=True) + "\n")
                        jsonl_handle.flush()
                    if payload.get("success"):
                        success = payload["success"]
                        for pending in future_to_index:
                            if not pending.done():
                                pending.cancel()
                        break
    finally:
        if jsonl_handle is not None:
            jsonl_handle.close()
    results.sort(key=lambda row: int(row.get("global_index", 0)))

    status_counts: dict[str, int] = {}
    for row in results:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = {
        "event": "branch_partial_coppersmith",
        "status": "factored" if success else "no_factor",
        "elapsed_seconds": time.time() - started,
        "candidate_paths": [str(path) for path in args.candidate_json],
        "source_summaries": source_summaries,
        "parameters": {
            "crypto_attacks": str(crypto_attacks),
            "m_values": args.m_values,
            "t_values": args.t_values,
            "candidate_start": args.candidate_start,
            "candidate_stop": args.candidate_stop,
            "limit": args.limit,
            "attempt_timeout_seconds": args.attempt_timeout_seconds,
            "workers": args.workers,
            "jsonl": None if args.jsonl is None else str(args.jsonl),
        },
        "sanity": constants_sanity(),
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
