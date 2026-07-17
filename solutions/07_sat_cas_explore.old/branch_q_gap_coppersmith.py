#!/usr/bin/env python3
"""Branch-conditional q middle-gap Coppersmith probe for challenge 7."""

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

from q_middle_gap_oracle import q_gap_known_parts, run_q_middle_gap_coppersmith
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CANDIDATE_JSONS = [
    SCRIPT_DIR / "branch_q_low_coppersmith_summary_20260604.json",
    Path("/tmp/ct07_round39_qgrowth_after_q888_low600_high728_top40_20260604.json"),
    Path("/tmp/ct07_round38_qgrowth_after_q888_low470_highscan_top40_20260604.json"),
    Path("/tmp/ct07_round39_side_qgrowth_q904base_r608_720_full65536_top20_20260604.json"),
]


def parse_fixed_range_text(text: str) -> FixedRange:
    if "=" in text:
        left, value_text = text.split("=", 1)
        start_text, width_text = left.split(":", 1)
    else:
        start_text, width_text, value_text = text.split(":", 2)
    return FixedRange(int(start_text, 0), int(width_text, 0), int(value_text, 0))


def item_fixed_ranges(item: dict[str, Any]) -> tuple[list[FixedRange], str | None]:
    raw_args = item.get("all_fix_p_range_args")
    if isinstance(raw_args, list):
        if len(raw_args) % 2:
            return [], "odd-length all_fix_p_range_args"
        fixed_ranges: list[FixedRange] = []
        for offset in range(0, len(raw_args), 2):
            if raw_args[offset] != "--fix-p-range":
                return [], f"expected --fix-p-range at argument offset {offset}"
            try:
                fixed_ranges.append(parse_fixed_range_text(str(raw_args[offset + 1])))
            except Exception as exc:
                return [], f"failed to parse {raw_args[offset + 1]!r}: {exc}"
        return fixed_ranges, None

    fixed_text = item.get("all_fixed_ranges_text") or item.get("fixed_ranges_text")
    if isinstance(fixed_text, list):
        fixed_ranges = []
        for raw_text in fixed_text:
            try:
                fixed_ranges.append(parse_fixed_range_text(str(raw_text)))
            except Exception as exc:
                return [], f"failed to parse {raw_text!r}: {exc}"
        return fixed_ranges, None

    return [], "missing all_fix_p_range_args/all_fixed_ranges_text"


def load_candidates(candidate_paths: list[Path], limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    source_summaries: list[dict[str, Any]] = []
    for candidate_path in candidate_paths:
        if not candidate_path.exists():
            source_summaries.append({"path": str(candidate_path), "status": "missing", "items": 0})
            continue
        data = json.loads(candidate_path.read_text(encoding="utf-8"))
        source_event = None
        source_summary: dict[str, Any] = {}
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict) and isinstance(data.get("items"), list):
            items = data["items"]
            source_event = data.get("event") or data.get("summary", {}).get("event")
            source_summary = data.get("summary", {})
        elif isinstance(data, dict) and isinstance(data.get("payload"), dict) and isinstance(data["payload"].get("items"), list):
            items = data["payload"]["items"]
            source_event = data.get("event") or data["payload"].get("summary", {}).get("event")
            source_summary = data.get("probe_summary", {}) or data["payload"].get("summary", {})
        elif isinstance(data, dict) and isinstance(data.get("results"), list):
            items = data["results"]
            source_event = data.get("event")
            source_summary = data
        else:
            raise RuntimeError(f"unsupported candidate JSON format: {candidate_path}")

        source_summaries.append(
            {
                "path": str(candidate_path),
                "status": "loaded",
                "event": source_event,
                "items": len(items),
                "summary_best_q_low_bits": source_summary.get("best_q_low_bits"),
                "summary_best_q_known_bits": source_summary.get("best_q_known_bits"),
                "summary_best_q_prefix_bits": source_summary.get("best_q_prefix_bits"),
            }
        )
        for ordinal, item in enumerate(items, start=1):
            if limit and len(candidates) >= limit:
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
        if limit and len(candidates) >= limit:
            break
    return candidates, source_summaries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate-json",
        action="append",
        type=Path,
        default=[],
        help="candidate JSON file; repeatable. Defaults to the saved q-low summary, then the old /tmp q-growth files if present",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=SCRIPT_DIR / "branch_q_gap_coppersmith_summary_20260605.json",
        help="path for the JSON summary",
    )
    parser.add_argument("--max-gap-bits", type=int, default=520)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument(
        "--oracle-timeout-seconds",
        type=float,
        default=0.0,
        help="per small_roots call timeout; 0 disables the guard",
    )
    parser.add_argument("--candidate-start", type=int, default=1, help="1-based inclusive candidate start after loading")
    parser.add_argument("--candidate-stop", type=int, default=0, help="1-based inclusive candidate stop after loading; 0 means end")
    parser.add_argument("--limit", type=int, default=0, help="optional global candidate limit for smoke tests")
    parser.add_argument("--pdf", type=Path, default=ROOT / "problems" / "7_소인수분해.pdf")
    parser.add_argument("--no-pdf-check", action="store_true")
    args = parser.parse_args()

    if args.limit < 0:
        raise SystemExit("--limit must be non-negative")
    if args.max_gap_bits < 0:
        raise SystemExit("--max-gap-bits must be non-negative")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")
    if args.oracle_timeout_seconds < 0:
        raise SystemExit("--oracle-timeout-seconds must be nonnegative")
    if args.candidate_start < 1:
        raise SystemExit("--candidate-start must be at least 1")
    if args.candidate_stop and args.candidate_stop < args.candidate_start:
        raise SystemExit("--candidate-stop must be 0 or at least --candidate-start")

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
        "pdf_check": pdf_check,
    }

    all_candidates, source_summaries = load_candidates(candidate_paths, 0)
    stop_index = args.candidate_stop or len(all_candidates)
    candidates = all_candidates[args.candidate_start - 1 : stop_index]
    if args.limit:
        candidates = candidates[: args.limit]
    cache: dict[tuple[int, int, int, int, float], dict[str, Any]] = {}
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
            "candidate_index": item.get("index") or item.get("candidate_index"),
            "range_set": item.get("range_set"),
            "log_q_low_bits": item.get("q_low_bits"),
            "log_q_known_bits": item.get("q_known_bits"),
            "log_q_prefix_bits": item.get("q_prefix_bits"),
            "log_q_prefix_start": item.get("q_prefix_start"),
        }
        fixed_ranges, parse_error = item_fixed_ranges(item)
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
            parts = q_gap_known_parts(q_known, q_bits=instance.p_bits)
        except Exception as exc:
            record.update({"status": "invalid_branch", "failure_reason": str(exc)})
            results.append(record)
            continue

        record.update(
            {
                "p_fixed_bits": p_mask.bit_count(),
                "q_low_bits": q_known.low_bits,
                "q_known_bits": q_known.mask.bit_count(),
                "q_prefix_bits": q_known.prefix_bits,
                "q_prefix_start": q_known.prefix_start,
                "q_gap_bits": parts["gap_bits"],
                "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                "q_lo_hex": hex(parts["q_lo"]),
                "q_hi_hex": hex(parts["q_hi"]),
                "q_const_hex": hex(parts["const"]),
            }
        )
        if parts["gap_bits"] > args.max_gap_bits:
            record.update(
                {
                    "status": "skipped_gap_above_max",
                    "failure_reason": f"q_gap_bits={parts['gap_bits']} > max_gap_bits={args.max_gap_bits}",
                }
            )
            results.append(record)
            continue

        cache_key = (
            parts["low_bits"],
            parts["prefix_start"],
            parts["q_lo"],
            parts["q_hi"],
            args.epsilon,
            args.oracle_timeout_seconds,
        )
        cache_hit = cache_key in cache
        if not cache_hit:
            cache[cache_key] = run_q_middle_gap_coppersmith(
                q_known=q_known,
                n=instance.n,
                q_bits=instance.p_bits,
                p_known=p_known,
                p_mask=p_mask,
                epsilon=args.epsilon,
                min_hard_margin_bits=args.min_hard_margin_bits,
                timeout_seconds=args.oracle_timeout_seconds if args.oracle_timeout_seconds > 0 else None,
            )
        record.update(cache[cache_key])
        record["cache_hit"] = cache_hit

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
                "candidate_index": item.get("index") or item.get("candidate_index"),
                "rank": item.get("rank"),
                "range_set": item.get("range_set"),
                "p_hex": factor["p_hex"],
                "q_hex": factor["q_hex"],
                "n_mod_q_zero": instance.n % q_int == 0,
                "p_times_q_equals_n": p_int * q_int == instance.n,
                "p_matches_original_mask": (p_int & instance.mask) == instance.known,
                "p_matches_branch_mask": (p_int & p_mask) == (p_known & p_mask),
                "plaintext_hex_big_endian": plaintext_bytes.hex(),
                "plaintext_utf8": plaintext_utf8,
            }
        results.append(record)

    status_counts: dict[str, int] = {}
    q_gap_distribution: dict[str, int] = {}
    roots_total = 0
    factors_total = 0
    hard_no_roots = 0
    for row in results:
        status = str(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
        if "q_gap_bits" in row:
            key = str(row["q_gap_bits"])
            q_gap_distribution[key] = q_gap_distribution.get(key, 0) + 1
        roots_total += int(row.get("roots_returned", 0) or 0)
        factors_total += len(row.get("factors", []) or [])
        if row.get("no_root_hard_clause_eligible"):
            hard_no_roots += 1

    summary = {
        "event": "branch_q_gap_coppersmith",
        "status": "factored" if success else "no_factor",
        "candidate_paths": [str(path) for path in candidate_paths],
        "source_summaries": source_summaries,
        "parameters": {
            "max_gap_bits": args.max_gap_bits,
            "epsilon": args.epsilon,
            "min_hard_margin_bits": args.min_hard_margin_bits,
            "limit": args.limit,
            "candidate_start": args.candidate_start,
            "candidate_stop": args.candidate_stop,
            "candidate_total_before_slice": len(all_candidates),
            "coppersmith_model": "q = q_lo + q_hi + 2^q_low_bits*y over Zmod(N), beta=0.5",
            "cache_key": "(q_low_bits, q_prefix_start, q_lo, q_hi, epsilon)",
        },
        "sanity": sanity,
        "elapsed_seconds": time.time() - started,
        "candidates_total_loaded": len(candidates),
        "candidates_tested": len(results),
        "cache_entries": len(cache),
        "q_gap_distribution": q_gap_distribution,
        "status_counts": status_counts,
        "roots_total": roots_total,
        "factors_total": factors_total,
        "hard_no_roots": hard_no_roots,
        "success": success,
        "results": results,
    }
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    console_summary = dict(summary)
    console_summary["results"] = f"{len(results)} rows written to {args.summary_json}"
    print(json.dumps(console_summary, sort_keys=True))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
