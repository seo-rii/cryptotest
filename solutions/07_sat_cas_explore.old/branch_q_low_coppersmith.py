#!/usr/bin/env python3
"""Branch-conditional q-low Coppersmith factor probe for challenge 7.

This is an independent probe: it reads q-growth candidate summaries and derives
q low bits from each candidate's full fixed p ranges, then tries to recover the
factor with q = q0 + 2^t * y.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from low_coppersmith_oracle import low_coppersmith_bound_report
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CANDIDATE_JSONS = [
    Path("/tmp/ct07_round39_qgrowth_after_q888_low600_high728_top40_20260604.json"),
    Path("/tmp/ct07_round38_qgrowth_after_q888_low470_highscan_top40_20260604.json"),
    Path("/tmp/ct07_round39_side_qgrowth_q904base_r608_720_full65536_top20_20260604.json"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate-json",
        action="append",
        type=Path,
        default=[],
        help="q-growth JSON candidate file; repeatable, defaults to the three requested /tmp files",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=SCRIPT_DIR / "branch_q_low_coppersmith_summary_20260604.json",
        help="path for the JSON summary",
    )
    parser.add_argument("--min-low-bits", type=int, default=512)
    parser.add_argument("--epsilon", type=float, default=0.03)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--limit", type=int, default=0, help="optional global candidate limit for smoke tests")
    parser.add_argument("--pdf", type=Path, default=ROOT / "problems" / "7_소인수분해.pdf")
    parser.add_argument("--no-pdf-check", action="store_true")
    args = parser.parse_args()

    if args.min_low_bits < 1:
        raise SystemExit("--min-low-bits must be positive")
    if args.limit < 0:
        raise SystemExit("--limit must be non-negative")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")

    candidate_paths = args.candidate_json or DEFAULT_CANDIDATE_JSONS
    instance = load_instance()

    constants_path = ROOT / "solutions" / "investigate_07_rsa_partial_bits.py"
    spec = importlib.util.spec_from_file_location("c7_constants", constants_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load constants from {constants_path}")
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)

    n_from_constants = int(constants.N_HEX.replace(" ", ""), 16)
    ct_from_constants = int(constants.CT_HEX.replace(" ", ""), 16)
    mask_from_constants = int(constants.MASK_HEX.replace(" ", ""), 16)
    raw_p_and_mask = int(constants.P_AND_MASK_HEX.replace(" ", ""), 16)
    known_from_constants = raw_p_and_mask & mask_from_constants
    base_unknown_mask = ((1 << instance.p_bits) - 1) ^ instance.mask
    base_low_bits = (base_unknown_mask & -base_unknown_mask).bit_length() - 1
    base_low_modulus = 1 << base_low_bits
    base_p_low = instance.known & (base_low_modulus - 1)
    base_q_low = (instance.n * pow(base_p_low, -1, base_low_modulus)) % base_low_modulus

    pdf_check: dict[str, Any] = {
        "status": "skipped" if args.no_pdf_check else "not_run",
        "path": str(args.pdf),
    }
    if not args.no_pdf_check:
        pdftotext = shutil.which("pdftotext")
        if pdftotext is None:
            pdf_check = {"status": "unavailable", "path": str(args.pdf), "reason": "pdftotext not found"}
        elif not args.pdf.exists():
            pdf_check = {"status": "missing", "path": str(args.pdf)}
        else:
            proc = subprocess.run(
                [pdftotext, str(args.pdf), "-"],
                check=False,
                text=True,
                capture_output=True,
            )
            if proc.returncode != 0:
                pdf_check = {
                    "status": "failed",
                    "path": str(args.pdf),
                    "returncode": proc.returncode,
                    "stderr": proc.stderr.strip(),
                }
            else:
                normalized_pdf = "".join(proc.stdout.lower().split())
                pdf_matches = {
                    "N": constants.N_HEX.replace(" ", "").lower() in normalized_pdf
                    or all(part.lower() in normalized_pdf for part in constants.N_HEX.split()),
                    "e": f"{int(constants.E):016x}" in normalized_pdf,
                    "ct": constants.CT_HEX.replace(" ", "").lower() in normalized_pdf
                    or all(part.lower() in normalized_pdf for part in constants.CT_HEX.split()),
                    "MASK": constants.MASK_HEX.replace(" ", "").lower() in normalized_pdf
                    or all(part.lower() in normalized_pdf for part in constants.MASK_HEX.split()),
                    "p_and_MASK": constants.P_AND_MASK_HEX.replace(" ", "").lower() in normalized_pdf
                    or all(part.lower() in normalized_pdf for part in constants.P_AND_MASK_HEX.split()),
                }
                pdf_check = {
                    "status": "matched" if all(pdf_matches.values()) else "mismatch",
                    "path": str(args.pdf),
                    "matches": pdf_matches,
                }

    sanity = {
        "constants_path": str(constants_path),
        "n_matches_loaded_instance": n_from_constants == instance.n,
        "e_matches_loaded_instance": int(constants.E) == instance.e,
        "ct_matches_loaded_instance": ct_from_constants == instance.ct,
        "mask_matches_loaded_instance": mask_from_constants == instance.mask,
        "known_matches_loaded_instance": known_from_constants == instance.known,
        "n_bit_length": instance.n.bit_length(),
        "ct_bit_length": instance.ct.bit_length(),
        "e": instance.e,
        "mask_bit_length": instance.mask.bit_length(),
        "known_bit_length": instance.known.bit_length(),
        "known_p_bits": instance.mask.bit_count(),
        "raw_p_and_mask_has_no_bits_outside_mask": (raw_p_and_mask & ~mask_from_constants) == 0,
        "base_p_low_bits": base_low_bits,
        "base_q_low_product_check": ((base_p_low * base_q_low - instance.n) % base_low_modulus) == 0,
        "pdf_check": pdf_check,
    }

    candidates: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    for candidate_path in candidate_paths:
        data = json.loads(candidate_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            items = data
            source_event = None
            source_summary = {}
        elif isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data["items"]
            source_event = data.get("event") or data.get("summary", {}).get("event")
            source_summary = data.get("summary", {})
        elif isinstance(data, dict) and isinstance(data.get("payload"), dict) and isinstance(data["payload"].get("items"), list):
            items = data["payload"]["items"]
            source_event = data.get("event") or data["payload"].get("summary", {}).get("event")
            source_summary = data.get("probe_summary", {}) or data["payload"].get("summary", {})
        else:
            raise RuntimeError(f"unsupported candidate JSON format: {candidate_path}")

        source_summaries.append(
            {
                "path": str(candidate_path),
                "event": source_event,
                "items": len(items),
                "summary_best_q_low_bits": source_summary.get("best_q_low_bits"),
                "summary_best_q_known_bits": source_summary.get("best_q_known_bits"),
                "summary_best_q_prefix_bits": source_summary.get("best_q_prefix_bits"),
            }
        )
        for ordinal, item in enumerate(items, start=1):
            if args.limit and len(candidates) >= args.limit:
                break
            if not isinstance(item, dict):
                continue
            candidates.append(
                {
                    "source_path": str(candidate_path),
                    "source_event": source_event,
                    "ordinal_in_source": ordinal,
                    "item": item,
                }
            )
        if args.limit and len(candidates) >= args.limit:
            break

    try:
        from sage.all import PolynomialRing, Zmod, ZZ
    except Exception as exc:
        summary = {
            "event": "branch_q_low_coppersmith",
            "status": "sage_unavailable",
            "reason": f"Sage import failed: {exc}",
            "independent_from_exact_carry_low_c": True,
            "independence_note": "Read existing scripts and requested /tmp q-growth logs only; wrote only this script and the configured summary JSON.",
            "candidate_paths": [str(path) for path in candidate_paths],
            "source_summaries": source_summaries,
            "sanity": sanity,
            "candidates_total_loaded": len(candidates),
            "candidates_tested": 0,
            "results": [],
        }
        args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        console_summary = dict(summary)
        console_summary["results"] = f"{len(summary['results'])} rows written to {args.summary_json}"
        print(json.dumps(console_summary, sort_keys=True))
        return 1

    ring = PolynomialRing(Zmod(instance.n), "y")
    y = ring.gen()
    cache: dict[tuple[int, int], dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    success: dict[str, Any] | None = None
    started = time.time()

    for global_index, candidate in enumerate(candidates, start=1):
        item = candidate["item"]
        record: dict[str, Any] = {
            "global_index": global_index,
            "source_path": candidate["source_path"],
            "source_event": candidate["source_event"],
            "ordinal_in_source": candidate["ordinal_in_source"],
            "rank": item.get("rank"),
            "candidate_index": item.get("index"),
            "range_set": item.get("range_set"),
            "fixed_ranges_text": item.get("fixed_ranges_text", []),
            "log_q_low_bits": item.get("q_low_bits"),
            "log_q_known_bits": item.get("q_known_bits"),
            "log_q_prefix_bits": item.get("q_prefix_bits"),
        }
        raw_args = item.get("all_fix_p_range_args")
        if not isinstance(raw_args, list):
            record.update({"status": "invalid_candidate", "failure_reason": "missing all_fix_p_range_args"})
            results.append(record)
            continue
        if len(raw_args) % 2:
            record.update({"status": "invalid_candidate", "failure_reason": "odd-length all_fix_p_range_args"})
            results.append(record)
            continue

        fixed_ranges: list[FixedRange] = []
        parse_error = None
        for offset in range(0, len(raw_args), 2):
            if raw_args[offset] != "--fix-p-range":
                parse_error = f"expected --fix-p-range at argument offset {offset}"
                break
            try:
                start_text, width_text, value_text = str(raw_args[offset + 1]).split(":", 2)
                fixed_ranges.append(FixedRange(int(start_text, 0), int(width_text, 0), int(value_text, 0)))
            except Exception as exc:
                parse_error = f"failed to parse {raw_args[offset + 1]!r}: {exc}"
                break
        if parse_error is not None:
            record.update({"status": "invalid_candidate", "failure_reason": parse_error})
            results.append(record)
            continue

        record["all_fixed_ranges_text"] = [
            f"{fixed.start}:{fixed.width}=0x{fixed.value:x}" for fixed in sorted(fixed_ranges, key=lambda value: value.start)
        ]
        try:
            p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)
            q_known = derive_q_known_bits(instance, p_known, p_mask)
        except Exception as exc:
            record.update({"status": "invalid_branch", "failure_reason": str(exc)})
            results.append(record)
            continue

        t = q_known.low_bits
        q0 = q_known.known & ((1 << t) - 1)
        bound_report = low_coppersmith_bound_report(
            n=instance.n,
            low_bits=t,
            p_bits=instance.p_bits,
            epsilon=args.epsilon,
            min_hard_margin_bits=args.min_hard_margin_bits,
        )
        record.update(
            {
                "p_fixed_bits": p_mask.bit_count(),
                "q_low_bits": t,
                "q_known_bits": q_known.mask.bit_count(),
                "q_prefix_bits": q_known.prefix_bits,
                "q_prefix_start": q_known.prefix_start,
                "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                "q0_hex": hex(q0),
                **bound_report,
                "hard_clause_eligible": False,
                "oracle_bound_eligible": bound_report["hard_clause_bound_eligible"],
                "q_low_product_check": ((q0 * (p_known & ((1 << t) - 1)) - instance.n) % (1 << t)) == 0,
            }
        )
        if t < args.min_low_bits:
            record.update(
                {
                    "status": "skipped_low_bits_below_min",
                    "failure_reason": f"q_low_bits={t} < min_low_bits={args.min_low_bits}",
                }
            )
            results.append(record)
            continue

        cache_key = (t, q0)
        if cache_key not in cache:
            root_started = time.time()
            try:
                roots = (ring(ZZ(q0)) + (ZZ(1) << t) * y).monic().small_roots(
                    X=ZZ(1) << (instance.p_bits - t),
                    beta=0.5,
                    epsilon=args.epsilon,
                )
                factor_rows = []
                root_values = [int(root) for root in roots]
                for root_value in root_values:
                    q_candidate = int(q0 + (1 << t) * root_value)
                    if 1 < q_candidate < instance.n and instance.n % q_candidate == 0:
                        p_candidate = instance.n // q_candidate
                        factor_rows.append(
                            {
                                "root": root_value,
                                "q_hex": hex(q_candidate),
                                "p_hex": hex(p_candidate),
                                "q_bit_length": q_candidate.bit_length(),
                                "p_bit_length": p_candidate.bit_length(),
                                "n_mod_q_zero": instance.n % q_candidate == 0,
                                "p_times_q_equals_n": p_candidate * q_candidate == instance.n,
                                "p_matches_mask": (p_candidate & instance.mask) == instance.known,
                                "q_matches_low": (q_candidate & ((1 << t) - 1)) == q0,
                            }
                        )
                cache[cache_key] = {
                    "status": "factored" if factor_rows else "no_roots",
                    "elapsed_seconds": time.time() - root_started,
                    "roots_returned": len(root_values),
                    "roots_sample": root_values[:5],
                    "factors": factor_rows,
                    "failure_reason": None if factor_rows else "small_roots returned no valid divisor of N",
                }
            except Exception as exc:
                cache[cache_key] = {
                    "status": "coppersmith_error",
                    "elapsed_seconds": time.time() - root_started,
                    "roots_returned": 0,
                    "roots_sample": [],
                    "factors": [],
                    "failure_reason": str(exc),
                }

        cached = cache[cache_key]
        record.update(cached)
        record["no_root_hard_clause_eligible"] = (
            record.get("status") == "no_roots" and bool(record.get("oracle_bound_eligible"))
        )
        if record["status"] == "factored" and success is None:
            factor = record["factors"][0]
            p_int = int(str(factor["p_hex"]), 16)
            q_int = int(str(factor["q_hex"]), 16)
            phi = (p_int - 1) * (q_int - 1)
            d = pow(instance.e, -1, phi)
            plaintext_int = pow(instance.ct, d, instance.n)
            plaintext_bytes = plaintext_int.to_bytes(max(1, (plaintext_int.bit_length() + 7) // 8), "big")
            try:
                plaintext_utf8 = plaintext_bytes.decode("utf-8")
            except UnicodeDecodeError:
                plaintext_utf8 = None
            success = {
                "candidate_global_index": global_index,
                "source_path": candidate["source_path"],
                "candidate_index": item.get("index"),
                "rank": item.get("rank"),
                "range_set": item.get("range_set"),
                "p_hex": factor["p_hex"],
                "q_hex": factor["q_hex"],
                "n_mod_q_zero": instance.n % q_int == 0,
                "p_times_q_equals_n": p_int * q_int == instance.n,
                "p_matches_mask": (p_int & instance.mask) == instance.known,
                "plaintext_hex_big_endian": plaintext_bytes.hex(),
                "plaintext_utf8": plaintext_utf8,
            }
        results.append(record)

    status_counts: dict[str, int] = {}
    q_low_distribution: dict[str, int] = {}
    roots_total = 0
    factors_total = 0
    for row in results:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        if "q_low_bits" in row:
            key = str(row["q_low_bits"])
            q_low_distribution[key] = q_low_distribution.get(key, 0) + 1
        roots_total += int(row.get("roots_returned", 0) or 0)
        factors_total += len(row.get("factors", []) or [])

    summary = {
        "event": "branch_q_low_coppersmith",
        "status": "factored" if success else "no_factor",
        "independent_from_exact_carry_low_c": True,
        "independence_note": "Read existing scripts and requested /tmp q-growth logs only; did not touch existing processes or /tmp artifacts; wrote only this new probe and summary JSON under cryptotest/solutions/07_sat_cas_explore.",
        "candidate_paths": [str(path) for path in candidate_paths],
        "source_summaries": source_summaries,
        "parameters": {
            "min_low_bits": args.min_low_bits,
            "epsilon": args.epsilon,
            "min_hard_margin_bits": args.min_hard_margin_bits,
            "limit": args.limit,
            "coppersmith_model": "q = q0 + 2^t*y over Zmod(N), beta=0.5",
        },
        "sanity": sanity,
        "elapsed_seconds": time.time() - started,
        "candidates_total_loaded": len(candidates),
        "candidates_tested": len(results),
        "q_low_distribution": q_low_distribution,
        "status_counts": status_counts,
        "roots_total": roots_total,
        "factors_total": factors_total,
        "success": success,
        "results": results,
    }
    args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    console_summary = dict(summary)
    console_summary["results"] = f"{len(results)} rows written to {args.summary_json}"
    print(json.dumps(console_summary, sort_keys=True))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
