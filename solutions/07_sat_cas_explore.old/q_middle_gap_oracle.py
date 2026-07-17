#!/usr/bin/env python3
"""Two-sided q middle-gap Coppersmith oracle for challenge 7."""

from __future__ import annotations

import time
from typing import Any

from sat_cas_core import QKnownBits


DEFAULT_EPSILON = 0.02
DEFAULT_MIN_HARD_MARGIN_BITS = 8.0
COPPERSMITH_BETA = 0.5
COPPERSMITH_DEGREE = 1


def q_gap_bound_report(
    *,
    n: int,
    low_bits: int,
    prefix_start: int,
    epsilon: float = DEFAULT_EPSILON,
    min_hard_margin_bits: float = DEFAULT_MIN_HARD_MARGIN_BITS,
) -> dict[str, object]:
    gap_bits = max(0, prefix_start - low_bits)
    n_bits = int(n).bit_length()
    effective_bound_bits = (
        (COPPERSMITH_BETA * COPPERSMITH_BETA / COPPERSMITH_DEGREE - epsilon) * n_bits
        - 1.0
    )
    effective_margin_bits = effective_bound_bits - gap_bits
    return {
        "q_low_bits": low_bits,
        "q_prefix_start": prefix_start,
        "q_gap_bits": gap_bits,
        "root_bound_bits": gap_bits,
        "epsilon": epsilon,
        "beta": COPPERSMITH_BETA,
        "degree": COPPERSMITH_DEGREE,
        "n_bit_length": n_bits,
        "effective_bound_bits": effective_bound_bits,
        "effective_margin_bits": effective_margin_bits,
        "theorem_margin_bits": n_bits / 4.0 - gap_bits,
        "min_hard_margin_bits": min_hard_margin_bits,
        "hard_clause_bound_eligible": effective_margin_bits >= min_hard_margin_bits,
    }


def q_gap_known_parts(q_known: QKnownBits, q_bits: int = 1024) -> dict[str, int]:
    if not (0 <= q_known.low_bits <= q_bits):
        raise ValueError(f"q low bit count out of range: {q_known.low_bits}")
    if not (0 <= q_known.prefix_start <= q_bits):
        raise ValueError(f"q prefix start out of range: {q_known.prefix_start}")

    full_mask = (1 << q_bits) - 1
    t = q_known.low_bits
    s = q_known.prefix_start
    low_mask = (1 << t) - 1 if t else 0
    high_mask = full_mask ^ ((1 << s) - 1)
    q_lo = q_known.known & low_mask
    q_hi = q_known.known & high_mask
    gap_bits = max(0, s - t)
    gap_mask = ((1 << gap_bits) - 1) << t if gap_bits else 0
    return {
        "q_bits": q_bits,
        "low_bits": t,
        "prefix_start": s,
        "gap_bits": gap_bits,
        "low_mask": low_mask,
        "high_mask": high_mask,
        "known_mask": low_mask | high_mask,
        "gap_mask": gap_mask,
        "q_lo": q_lo,
        "q_hi": q_hi,
        "const": (q_lo | q_hi) & full_mask,
    }


def run_q_middle_gap_coppersmith(
    *,
    q_known: QKnownBits,
    n: int,
    q_bits: int = 1024,
    p_known: int | None = None,
    p_mask: int | None = None,
    epsilon: float = DEFAULT_EPSILON,
    min_hard_margin_bits: float = DEFAULT_MIN_HARD_MARGIN_BITS,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    parts = q_gap_known_parts(q_known, q_bits=q_bits)
    bound_report = q_gap_bound_report(
        n=n,
        low_bits=parts["low_bits"],
        prefix_start=parts["prefix_start"],
        epsilon=epsilon,
        min_hard_margin_bits=min_hard_margin_bits,
    )
    base_report: dict[str, Any] = {
        **bound_report,
        "q_bits": q_bits,
        "q_known_bits": int(q_known.mask).bit_count(),
        "q_prefix_bits": q_known.prefix_bits,
        "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
        "q_lo_hex": hex(parts["q_lo"]),
        "q_hi_hex": hex(parts["q_hi"]),
        "q_const_hex": hex(parts["const"]),
        "oracle_timeout_seconds": timeout_seconds,
        "cache_key": [
            parts["low_bits"],
            parts["prefix_start"],
            hex(parts["q_lo"]),
            hex(parts["q_hi"]),
            epsilon,
            timeout_seconds,
        ],
    }

    def factor_rows_for_root(root_value: int) -> list[dict[str, Any]]:
        q_candidate = int(parts["const"] + (int(root_value) << parts["low_bits"]))
        if not (1 < q_candidate < n) or n % q_candidate != 0:
            return []
        p_candidate = n // q_candidate
        row = {
            "root": int(root_value),
            "q_hex": hex(q_candidate),
            "p_hex": hex(p_candidate),
            "q_bit_length": q_candidate.bit_length(),
            "p_bit_length": p_candidate.bit_length(),
            "n_mod_q_zero": n % q_candidate == 0,
            "p_times_q_equals_n": p_candidate * q_candidate == n,
            "q_matches_low": (q_candidate & parts["low_mask"]) == parts["q_lo"],
            "q_matches_high": (q_candidate & parts["high_mask"]) == parts["q_hi"],
        }
        if p_known is not None and p_mask is not None:
            row["p_matches_mask"] = (p_candidate & p_mask) == (p_known & p_mask)
        return [row]

    started = time.time()
    if parts["gap_bits"] == 0:
        factors = factor_rows_for_root(0)
        status = "factored" if factors else "no_roots"
        return {
            "status": status,
            **base_report,
            "elapsed_seconds": time.time() - started,
            "roots_returned": 1,
            "roots_sample": [0],
            "factors": factors,
            "failure_reason": None if factors else "known q candidate is not a divisor of N",
            "hard_clause_eligible": status == "no_roots",
            "no_root_hard_clause_eligible": status == "no_roots",
        }

    if timeout_seconds is not None and timeout_seconds > 0:
        import multiprocessing as mp

        result_queue: mp.Queue[dict[str, Any]] = mp.Queue(maxsize=1)

        def child_run() -> None:
            try:
                result_queue.put(
                    run_q_middle_gap_coppersmith(
                        q_known=q_known,
                        n=n,
                        q_bits=q_bits,
                        p_known=p_known,
                        p_mask=p_mask,
                        epsilon=epsilon,
                        min_hard_margin_bits=min_hard_margin_bits,
                        timeout_seconds=None,
                    )
                )
            except BaseException as exc:  # pragma: no cover - defensive child guard
                result_queue.put(
                    {
                        "status": "coppersmith_error",
                        **base_report,
                        "elapsed_seconds": time.time() - started,
                        "roots_returned": 0,
                        "roots_sample": [],
                        "factors": [],
                        "failure_reason": f"child oracle failed: {exc}",
                        "hard_clause_eligible": False,
                        "no_root_hard_clause_eligible": False,
                    }
                )

        process = mp.Process(target=child_run)
        try:
            process.start()
        except Exception as exc:
            return {
                "status": "coppersmith_error",
                **base_report,
                "elapsed_seconds": time.time() - started,
                "roots_returned": 0,
                "roots_sample": [],
                "factors": [],
                "failure_reason": f"failed to start timeout child: {exc}",
                "hard_clause_eligible": False,
                "no_root_hard_clause_eligible": False,
            }
        process.join(float(timeout_seconds))
        if process.is_alive():
            process.terminate()
            process.join(2.0)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(2.0)
            return {
                "status": "timeout",
                **base_report,
                "elapsed_seconds": time.time() - started,
                "roots_returned": 0,
                "roots_sample": [],
                "factors": [],
                "failure_reason": f"q-gap small_roots exceeded {timeout_seconds}s",
                "hard_clause_eligible": False,
                "no_root_hard_clause_eligible": False,
            }
        if not result_queue.empty():
            child_report = result_queue.get()
            child_report["oracle_timeout_seconds"] = timeout_seconds
            if isinstance(child_report.get("cache_key"), list):
                child_report["cache_key"][-1] = timeout_seconds
            return child_report
        return {
            "status": "coppersmith_error",
            **base_report,
            "elapsed_seconds": time.time() - started,
            "roots_returned": 0,
            "roots_sample": [],
            "factors": [],
            "failure_reason": f"timeout child exited without result, exitcode={process.exitcode}",
            "hard_clause_eligible": False,
            "no_root_hard_clause_eligible": False,
        }

    try:
        from sage.all import PolynomialRing, Zmod, ZZ
    except Exception as exc:  # pragma: no cover - depends on local Sage packaging
        return {
            "status": "unavailable",
            **base_report,
            "elapsed_seconds": time.time() - started,
            "roots_returned": 0,
            "roots_sample": [],
            "factors": [],
            "failure_reason": f"Sage import failed: {exc}",
            "hard_clause_eligible": False,
            "no_root_hard_clause_eligible": False,
        }

    try:
        ring = PolynomialRing(Zmod(n), "y")
        y = ring.gen()
        roots = (ring(ZZ(parts["const"])) + (ZZ(1) << parts["low_bits"]) * y).monic().small_roots(
            X=ZZ(1) << parts["gap_bits"],
            beta=COPPERSMITH_BETA,
            epsilon=epsilon,
        )
        root_values = [int(root) for root in roots]
        factors: list[dict[str, Any]] = []
        for root_value in root_values:
            factors.extend(factor_rows_for_root(root_value))
        status = "factored" if factors else "no_roots"
        no_root_hard = status == "no_roots" and bool(bound_report["hard_clause_bound_eligible"])
        return {
            "status": status,
            **base_report,
            "elapsed_seconds": time.time() - started,
            "roots_returned": len(root_values),
            "roots_sample": root_values[:5],
            "factors": factors,
            "failure_reason": None if factors else "small_roots returned no valid divisor of N",
            "hard_clause_eligible": no_root_hard,
            "no_root_hard_clause_eligible": no_root_hard,
        }
    except Exception as exc:
        return {
            "status": "coppersmith_error",
            **base_report,
            "elapsed_seconds": time.time() - started,
            "roots_returned": 0,
            "roots_sample": [],
            "factors": [],
            "failure_reason": str(exc),
            "hard_clause_eligible": False,
            "no_root_hard_clause_eligible": False,
        }
