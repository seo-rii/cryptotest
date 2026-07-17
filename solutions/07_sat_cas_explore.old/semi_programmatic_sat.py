#!/usr/bin/env python3
"""Semi-programmatic SAT+CAS exploration loop for challenge 7.

This is intentionally a cube/oracle harness, not another CP-SAT monolith.  Z3
enumerates priority p-bit cubes, sound external checks either learn hard
no-good cubes or report candidates, and heuristic CAS failures are kept out of
the learned clause stream.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from pathlib import Path

import z3

from low_coppersmith_oracle import run_low_coppersmith
from q_middle_gap_oracle import q_gap_known_parts, run_q_middle_gap_coppersmith
from sat_cas_core import (
    FixedRange,
    all_bits_known,
    derive_q_known_bits,
    load_instance,
    parse_fixed_range,
    z3_product_prefix_status,
    z3_hensel_prefix_status,
)


HARD_LEARNED_CLAUSES = {
    "product_prefix_unsat",
    "low_coppersmith_no_root",
    "q_gap_coppersmith_no_root",
}


def compact_unit_ranges(ranges: list[FixedRange]) -> list[dict[str, int]]:
    if not ranges:
        return []
    items = sorted(ranges, key=lambda item: item.start)
    compacted = []
    start = items[0].start
    width = items[0].width
    value = items[0].value
    previous_end = start + width
    for item in items[1:]:
        if item.width == 1 and item.start == previous_end:
            if item.value:
                value |= 1 << width
            width += 1
            previous_end += 1
            continue
        compacted.append({"start": start, "width": width, "value": value})
        start = item.start
        width = item.width
        value = item.value
        previous_end = start + width
    compacted.append({"start": start, "width": width, "value": value})
    return compacted


def expand_record_cube_ranges(raw_ranges: object) -> dict[int, int] | None:
    if not isinstance(raw_ranges, list):
        return None
    values: dict[int, int] = {}
    for raw_item in raw_ranges:
        if not isinstance(raw_item, dict):
            return None
        try:
            start = int(raw_item["start"])
            width = int(raw_item["width"])
            value = int(raw_item.get("value", 0))
        except (KeyError, TypeError, ValueError):
            return None
        if start < 0 or width <= 0 or value < 0 or value >= (1 << width):
            return None
        for offset in range(width):
            values[start + offset] = (value >> offset) & 1
    return values


def learned_clause_bit_values(
    record: dict[str, object],
    *,
    include_soft_blocks: bool = False,
    dropped_bits_override: object | None = None,
) -> tuple[dict[int, int] | None, str]:
    learned_clause = record.get("learned_clause")
    if learned_clause not in HARD_LEARNED_CLAUSES:
        if include_soft_blocks and learned_clause == "sample_block_only":
            pass
        else:
            return None, "not_a_loaded_clause"

    bit_values = expand_record_cube_ranges(record.get("cube_ranges"))
    if bit_values is None:
        return None, "missing_or_invalid_cube_ranges"

    raw_dropped_bits = dropped_bits_override
    if raw_dropped_bits is None:
        raw_dropped_bits = record.get("learned_clause_dropped_bits")
    if isinstance(raw_dropped_bits, list):
        for raw_bit in raw_dropped_bits:
            try:
                bit_values.pop(int(raw_bit), None)
            except (TypeError, ValueError):
                return None, "invalid_dropped_bits"

    if not bit_values:
        return None, "empty_after_drops"
    return bit_values, "ok"


def learned_clause_bit_value_variants(
    record: dict[str, object],
    *,
    include_soft_blocks: bool = False,
) -> list[tuple[dict[int, int] | None, str]]:
    variants = record.get("learned_clause_variants")
    if not isinstance(variants, list):
        return [learned_clause_bit_values(record, include_soft_blocks=include_soft_blocks)]

    rows: list[tuple[dict[int, int] | None, str]] = []
    for raw_variant in variants:
        if not isinstance(raw_variant, dict):
            rows.append((None, "invalid_learned_clause_variant"))
            continue
        rows.append(
            learned_clause_bit_values(
                record,
                include_soft_blocks=include_soft_blocks,
                dropped_bits_override=raw_variant.get("dropped_bits"),
            )
        )
    return rows


def add_bit_value_block_clause(
    *,
    solver: z3.Solver,
    bit_vars: dict[int, z3.BoolRef],
    base_known: int,
    base_mask: int,
    p_bits: int,
    bit_values: dict[int, int],
) -> tuple[str, int]:
    literals = []
    for bit, value in sorted(bit_values.items()):
        if bit < 0 or bit >= p_bits or value not in {0, 1}:
            return "invalid_bit_value", 0
        if (base_mask >> bit) & 1:
            if ((base_known >> bit) & 1) != value:
                return "already_satisfied_by_fixed_bits", 0
            continue
        var = bit_vars.get(bit)
        if var is None:
            return "missing_bit_variable", 0
        literals.append(var != bool(value))

    if not literals:
        solver.add(z3.BoolVal(False))
        return "contradiction", 0
    solver.add(z3.Or(literals))
    return "added", len(literals)


def load_learned_jsonl_clauses(
    *,
    solver: z3.Solver,
    bit_vars: dict[int, z3.BoolRef],
    base_known: int,
    base_mask: int,
    p_bits: int,
    paths: list[str],
    include_soft_blocks: bool = False,
    limit: int = 0,
) -> dict[str, object]:
    report: dict[str, object] = {
        "files": len(paths),
        "records": 0,
        "cube_records": 0,
        "candidate_clause_records": 0,
        "clauses_added": 0,
        "literals_added": 0,
        "duplicates": 0,
        "parse_errors": 0,
        "file_errors": 0,
        "status_counts": {},
    }
    status_counts: dict[str, int] = {}
    seen: set[tuple[tuple[int, int], ...]] = set()

    def count_status(status: str) -> None:
        status_counts[status] = status_counts.get(status, 0) + 1

    stop_loading = False
    for raw_path in paths:
        if stop_loading:
            break
        path = Path(raw_path)
        try:
            handle = path.open(encoding="utf-8")
        except OSError:
            report["file_errors"] = int(report["file_errors"]) + 1
            continue
        with handle:
            for line in handle:
                if stop_loading:
                    break
                line = line.strip()
                if not line:
                    continue
                report["records"] = int(report["records"]) + 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    report["parse_errors"] = int(report["parse_errors"]) + 1
                    continue
                if not isinstance(record, dict):
                    report["parse_errors"] = int(report["parse_errors"]) + 1
                    continue
                if record.get("event") != "cube":
                    continue
                report["cube_records"] = int(report["cube_records"]) + 1
                variant_rows = learned_clause_bit_value_variants(
                    record,
                    include_soft_blocks=include_soft_blocks,
                )
                for bit_values, status in variant_rows:
                    count_status(status)
                    if bit_values is None:
                        continue
                    report["candidate_clause_records"] = int(report["candidate_clause_records"]) + 1
                    clause_key = tuple(sorted(bit_values.items()))
                    if clause_key in seen:
                        report["duplicates"] = int(report["duplicates"]) + 1
                        count_status("duplicate")
                        continue
                    seen.add(clause_key)
                    add_status, literal_count = add_bit_value_block_clause(
                        solver=solver,
                        bit_vars=bit_vars,
                        base_known=base_known,
                        base_mask=base_mask,
                        p_bits=p_bits,
                        bit_values=bit_values,
                    )
                    count_status(add_status)
                    if add_status in {"added", "contradiction"}:
                        report["clauses_added"] = int(report["clauses_added"]) + 1
                        report["literals_added"] = int(report["literals_added"]) + literal_count
                        if limit and int(report["clauses_added"]) >= limit:
                            stop_loading = True
                            break
    report["status_counts"] = dict(sorted(status_counts.items()))
    return report


def evaluate_q_gap_completion_task(task: dict[str, object]) -> dict[str, object]:
    instance = task["instance"]
    fixed_ranges = task["fixed_ranges"]
    cube_ranges_without_window = task["cube_ranges_without_window"]
    completion_bits = task["completion_bits"]
    completion_value = int(task["completion_value"])
    q_gap_max_bits = int(task["q_gap_max_bits"])
    q_gap_epsilon = float(task["q_gap_epsilon"])
    q_gap_min_hard_margin_bits = float(task["q_gap_min_hard_margin_bits"])
    q_gap_oracle_timeout_seconds = float(task.get("q_gap_oracle_timeout_seconds", 0.0))

    completion_ranges = [
        FixedRange(int(bit), 1, (completion_value >> index) & 1)
        for index, bit in enumerate(completion_bits)
    ]
    try:
        completion_known, completion_mask = instance.apply_fixed_ranges(
            list(fixed_ranges) + list(cube_ranges_without_window) + completion_ranges
        )
        completion_q_known = derive_q_known_bits(instance, completion_known, completion_mask)
        completion_q_parts = q_gap_known_parts(completion_q_known, q_bits=instance.p_bits)
    except Exception as exc:
        return {
            "completion_value": completion_value,
            "status": f"derive_error:{exc}",
            "oracle_called": False,
            "hard_eligible": False,
            "factors": [],
        }

    if int(completion_q_parts["gap_bits"]) > q_gap_max_bits:
        return {
            "completion_value": completion_value,
            "status": "skipped_gap_above_max",
            "oracle_called": False,
            "hard_eligible": False,
            "factors": [],
            "q_gap_bits": int(completion_q_parts["gap_bits"]),
        }

    completion_report = run_q_middle_gap_coppersmith(
        q_known=completion_q_known,
        n=instance.n,
        q_bits=instance.p_bits,
        p_known=completion_known,
        p_mask=completion_mask,
        epsilon=q_gap_epsilon,
        min_hard_margin_bits=q_gap_min_hard_margin_bits,
        timeout_seconds=q_gap_oracle_timeout_seconds if q_gap_oracle_timeout_seconds > 0 else None,
    )
    completion_status = str(completion_report.get("status"))
    return {
        "completion_value": completion_value,
        "status": completion_status,
        "oracle_called": True,
        "hard_eligible": (
            completion_status == "no_roots"
            and bool(completion_report.get("no_root_hard_clause_eligible"))
        ),
        "factors": completion_report.get("factors") or [],
        "report": completion_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cube-ranges",
        default="150:4,210:8,822:8,920:4",
        help="comma-separated START:WIDTH priority p-bit ranges to enumerate",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--check-bits", type=int, default=608)
    parser.add_argument("--prefix-core", choices=["bv", "hensel"], default="bv")
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--enumerate-p-free-limit", type=int, default=24)
    parser.add_argument("--max-cubes", type=int, default=32)
    parser.add_argument("--small-primes", type=int, default=0)
    parser.add_argument("--run-low-coppersmith", action="store_true")
    parser.add_argument("--low-coppersmith-bits", type=int, default=600)
    parser.add_argument("--low-coppersmith-epsilon", type=float, default=0.02)
    parser.add_argument("--low-coppersmith-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--low-coppersmith-hard-fail", action="store_true")
    parser.add_argument(
        "--low-coppersmith-preverified-drop-window",
        action="append",
        default=[],
        help=(
            "START:WIDTH selected low-bit window to omit from the learned "
            "low-Coppersmith clause without rechecking; use only for externally "
            "proved no-root unions"
        ),
    )
    parser.add_argument(
        "--low-coppersmith-preverified-guard-p-range",
        action="append",
        default=[],
        type=parse_fixed_range,
        help=(
            "START:WIDTH:VALUE p-bit range that must already be fixed in the "
            "current cube before preverified drop windows are applied"
        ),
    )
    parser.add_argument(
        "--low-coppersmith-drop-window",
        action="append",
        default=[],
        help=(
            "START:WIDTH selected low-bit window to try dropping from a "
            "low-Coppersmith hard clause after exhaustive no-root checks"
        ),
    )
    parser.add_argument("--low-coppersmith-minimize-max-completions", type=int, default=16)
    parser.add_argument("--run-q-gap-coppersmith", action="store_true")
    parser.add_argument("--q-gap-max-bits", type=int, default=462)
    parser.add_argument("--q-gap-epsilon", type=float, default=0.02)
    parser.add_argument("--q-gap-min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument(
        "--q-gap-oracle-timeout-seconds",
        type=float,
        default=0.0,
        help="per small_roots call timeout for q-gap Coppersmith; 0 disables the guard",
    )
    parser.add_argument("--q-gap-hard-fail", action="store_true")
    parser.add_argument("--q-gap-drop-window", action="append", default=[])
    parser.add_argument("--q-gap-minimize-max-completions", type=int, default=16)
    parser.add_argument(
        "--q-gap-independent-drop-clauses",
        action="store_true",
        help="verify each q-gap drop window independently and add one learned clause per droppable window",
    )
    parser.add_argument("--q-gap-minimize-workers", type=int, default=1)
    parser.add_argument(
        "--load-learned-jsonl",
        action="append",
        default=[],
        help="load hard learned clauses from prior JSONL cube records with --include-cube-ranges",
    )
    parser.add_argument(
        "--load-learned-limit",
        type=int,
        default=0,
        help="maximum loaded clauses across all --load-learned-jsonl inputs; 0 means no limit",
    )
    parser.add_argument(
        "--load-soft-blocks",
        action="store_true",
        help="also load sample_block_only clauses from prior JSONL; normally keep this off",
    )
    parser.add_argument("--include-cube-ranges", action="store_true")
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    if args.low_coppersmith_bits <= 0:
        raise SystemExit("--low-coppersmith-bits must be positive")
    if args.low_coppersmith_min_hard_margin_bits < 0:
        raise SystemExit("--low-coppersmith-min-hard-margin-bits must be nonnegative")
    if args.low_coppersmith_minimize_max_completions < 1:
        raise SystemExit("--low-coppersmith-minimize-max-completions must be positive")
    if args.q_gap_max_bits < 0:
        raise SystemExit("--q-gap-max-bits must be nonnegative")
    if args.q_gap_min_hard_margin_bits < 0:
        raise SystemExit("--q-gap-min-hard-margin-bits must be nonnegative")
    if args.q_gap_oracle_timeout_seconds < 0:
        raise SystemExit("--q-gap-oracle-timeout-seconds must be nonnegative")
    if args.q_gap_minimize_max_completions < 1:
        raise SystemExit("--q-gap-minimize-max-completions must be positive")
    if args.q_gap_minimize_workers < 1:
        raise SystemExit("--q-gap-minimize-workers must be positive")
    if args.load_learned_limit < 0:
        raise SystemExit("--load-learned-limit must be nonnegative")
    q_gap_drop_windows: list[tuple[int, int]] = []
    for raw_window in args.q_gap_drop_window:
        try:
            start_text, width_text = raw_window.split(":", 1)
        except ValueError as exc:
            raise SystemExit("--q-gap-drop-window must be START:WIDTH") from exc
        drop_start = int(start_text, 0)
        drop_width = int(width_text, 0)
        if drop_start < 0 or drop_width <= 0:
            raise SystemExit("--q-gap-drop-window must have nonnegative start and positive width")
        if (1 << drop_width) > args.q_gap_minimize_max_completions:
            raise SystemExit("--q-gap-drop-window exceeds --q-gap-minimize-max-completions")
        q_gap_drop_windows.append((drop_start, drop_width))
    low_preverified_drop_windows: list[tuple[int, int]] = []
    for raw_window in args.low_coppersmith_preverified_drop_window:
        try:
            start_text, width_text = raw_window.split(":", 1)
        except ValueError as exc:
            raise SystemExit("--low-coppersmith-preverified-drop-window must be START:WIDTH") from exc
        drop_start = int(start_text, 0)
        drop_width = int(width_text, 0)
        if drop_start < 0 or drop_width <= 0:
            raise SystemExit(
                "--low-coppersmith-preverified-drop-window must have nonnegative start and positive width"
            )
        if drop_start + drop_width > args.low_coppersmith_bits:
            raise SystemExit(
                "--low-coppersmith-preverified-drop-window must stay inside --low-coppersmith-bits"
            )
        low_preverified_drop_windows.append((drop_start, drop_width))
    low_drop_windows: list[tuple[int, int]] = []
    for raw_window in args.low_coppersmith_drop_window:
        try:
            start_text, width_text = raw_window.split(":", 1)
        except ValueError as exc:
            raise SystemExit("--low-coppersmith-drop-window must be START:WIDTH") from exc
        drop_start = int(start_text, 0)
        drop_width = int(width_text, 0)
        if drop_start < 0 or drop_width <= 0:
            raise SystemExit("--low-coppersmith-drop-window must have nonnegative start and positive width")
        if drop_start + drop_width > args.low_coppersmith_bits:
            raise SystemExit("--low-coppersmith-drop-window must stay inside --low-coppersmith-bits")
        if (1 << drop_width) > args.low_coppersmith_minimize_max_completions:
            raise SystemExit(
                "--low-coppersmith-drop-window exceeds --low-coppersmith-minimize-max-completions"
            )
        low_drop_windows.append((drop_start, drop_width))

    instance = load_instance()
    fixed_ranges: list[FixedRange] = list(args.fix_p_range)
    preverified_guard_ranges: list[FixedRange] = list(args.low_coppersmith_preverified_guard_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(fixed_ranges)
    all_unknown_bits = [bit for bit in range(instance.p_bits) if ((base_mask >> bit) & 1) == 0]
    bit_vars = {bit: z3.Bool(f"p_{bit}") for bit in all_unknown_bits}
    solver = z3.Solver()

    if args.small_primes:
        primes = []
        candidate = 3
        while len(primes) < args.small_primes:
            is_prime = True
            divisor = 3
            while divisor * divisor <= candidate:
                if candidate % divisor == 0:
                    is_prime = False
                    break
                divisor += 2
            if is_prime and instance.n % candidate != 0:
                primes.append(candidate)
            candidate += 2
        for prime in primes:
            terms = [base_known % prime]
            for bit, var in bit_vars.items():
                terms.append(((1 << bit) % prime) * z3.If(var, 1, 0))
            solver.add(sum(terms) % prime != 0)

    selected_bits = []
    for item in args.cube_ranges.split(","):
        item = item.strip()
        if not item:
            continue
        start_text, width_text = item.split(":", 1)
        start = int(start_text, 0)
        width = int(width_text, 0)
        selected_bits.extend(range(start, start + width))
    selected_bits = sorted(dict.fromkeys(selected_bits))
    selected_vars = [bit_vars[bit] for bit in selected_bits if bit in bit_vars]
    if not selected_vars:
        raise SystemExit("cube selection has no currently unknown p bits")

    counters = {
        "cubes": 0,
        "hard_product_blocks": 0,
        "soft_blocks": 0,
        "low_coppersmith_calls": 0,
        "low_coppersmith_cache_hits": 0,
        "low_coppersmith_hard_blocks": 0,
        "low_coppersmith_minimized_blocks": 0,
        "low_coppersmith_dropped_literals": 0,
        "q_gap_coppersmith_calls": 0,
        "q_gap_coppersmith_cache_hits": 0,
        "q_gap_coppersmith_skips": 0,
        "q_gap_coppersmith_hard_blocks": 0,
        "q_gap_coppersmith_minimized_blocks": 0,
        "q_gap_coppersmith_dropped_literals": 0,
        "q_gap_coppersmith_independent_drop_clauses": 0,
        "q_gap_coppersmith_independent_dropped_literals": 0,
        "q_gap_coppersmith_minimize_workers": args.q_gap_minimize_workers,
        "q_gap_coppersmith_oracle_timeout_seconds": args.q_gap_oracle_timeout_seconds,
        "loaded_learned_clauses": 0,
        "loaded_learned_literals": 0,
    }
    if args.load_learned_jsonl:
        learned_load_report = load_learned_jsonl_clauses(
            solver=solver,
            bit_vars=bit_vars,
            base_known=base_known,
            base_mask=base_mask,
            p_bits=instance.p_bits,
            paths=args.load_learned_jsonl,
            include_soft_blocks=args.load_soft_blocks,
            limit=args.load_learned_limit,
        )
        counters["loaded_learned_clauses"] = int(learned_load_report["clauses_added"])
        counters["loaded_learned_literals"] = int(learned_load_report["literals_added"])
        if args.jsonl:
            print(
                json.dumps({"event": "loaded_learned_clauses", **learned_load_report}, sort_keys=True),
                flush=True,
            )
        else:
            print(
                "loaded learned clauses: "
                f"{learned_load_report['clauses_added']} clauses, "
                f"{learned_load_report['literals_added']} literals",
                flush=True,
            )
    low_coppersmith_cache: dict[tuple[int, int], dict[str, object]] = {}
    q_gap_coppersmith_cache: dict[tuple[int, int, int, int, float], dict[str, object]] = {}
    low_coppersmith_mask = (1 << args.low_coppersmith_bits) - 1
    while counters["cubes"] < args.max_cubes:
        result = solver.check()
        if result != z3.sat:
            print(
                json.dumps({"event": "solver_done", "status": str(result), **counters}, sort_keys=True),
                flush=True,
            )
            break

        model = solver.model()
        cube_ranges = []
        cube_literals = []
        cube_literal_by_bit = {}
        for bit in selected_bits:
            if bit not in bit_vars:
                continue
            value = bool(model.eval(bit_vars[bit], model_completion=True))
            cube_ranges.append(FixedRange(bit, 1, int(value)))
            literal = bit_vars[bit] != value
            cube_literals.append(literal)
            cube_literal_by_bit[bit] = literal

        p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges + cube_ranges)
        if args.prefix_core == "hensel":
            prefix_status, prefix_meta = z3_hensel_prefix_status(
                instance=instance,
                p_known=p_known,
                p_mask=p_mask,
                prefix_bits=args.check_bits,
                timeout_ms=args.timeout_ms,
            )
        else:
            prefix_status, prefix_meta = z3_product_prefix_status(
                instance=instance,
                p_known=p_known,
                p_mask=p_mask,
                check_bits=args.check_bits,
                timeout_ms=args.timeout_ms,
                enumerate_p_free_limit=args.enumerate_p_free_limit,
            )
        counters["cubes"] += 1
        event: dict[str, object] = {
            "event": "cube",
            "index": counters["cubes"],
            "selected_bits": len(selected_bits),
            "product_prefix_status": prefix_status,
            **prefix_meta,
        }
        if args.include_cube_ranges:
            event["cube_ranges"] = compact_unit_ranges(cube_ranges)

        hard_blocked = False
        if prefix_status == "unsat":
            solver.add(z3.Or(cube_literals))
            counters["hard_product_blocks"] += 1
            event["learned_clause"] = "product_prefix_unsat"
            hard_blocked = True

        if not hard_blocked and args.run_q_gap_coppersmith:
            try:
                q_known = derive_q_known_bits(instance, p_known, p_mask)
                q_parts = q_gap_known_parts(q_known, q_bits=instance.p_bits)
                q_gap_bits = int(q_parts["gap_bits"])
                event["q_gap_trigger"] = {
                    "q_low_bits": q_known.low_bits,
                    "q_prefix_bits": q_known.prefix_bits,
                    "q_prefix_start": q_known.prefix_start,
                    "q_gap_bits": q_gap_bits,
                    "q_known_bits": q_known.mask.bit_count(),
                    "q_gap_max_bits": args.q_gap_max_bits,
                    "triggered": q_gap_bits <= args.q_gap_max_bits,
                }
            except Exception as exc:
                event["q_gap_trigger"] = {
                    "triggered": False,
                    "status": "derive_error",
                    "reason": str(exc),
                }
                counters["q_gap_coppersmith_skips"] += 1
            else:
                if q_gap_bits > args.q_gap_max_bits:
                    counters["q_gap_coppersmith_skips"] += 1
                else:
                    q_gap_cache_key = (
                        int(q_parts["low_bits"]),
                        int(q_parts["prefix_start"]),
                        int(q_parts["q_lo"]),
                        int(q_parts["q_hi"]),
                        args.q_gap_epsilon,
                        args.q_gap_oracle_timeout_seconds,
                    )
                    q_gap_report = q_gap_coppersmith_cache.get(q_gap_cache_key)
                    if q_gap_report is None:
                        counters["q_gap_coppersmith_calls"] += 1
                        q_gap_report = run_q_middle_gap_coppersmith(
                            q_known=q_known,
                            n=instance.n,
                            q_bits=instance.p_bits,
                            p_known=p_known,
                            p_mask=p_mask,
                            epsilon=args.q_gap_epsilon,
                            min_hard_margin_bits=args.q_gap_min_hard_margin_bits,
                            timeout_seconds=(
                                args.q_gap_oracle_timeout_seconds
                                if args.q_gap_oracle_timeout_seconds > 0
                                else None
                            ),
                        )
                        q_gap_coppersmith_cache[q_gap_cache_key] = q_gap_report
                    else:
                        counters["q_gap_coppersmith_cache_hits"] += 1
                    event["q_gap_coppersmith"] = q_gap_report
                    if q_gap_report.get("status") == "factored":
                        print(json.dumps(event, sort_keys=True), flush=True)
                        print(json.dumps({"event": "factored", **q_gap_report}, sort_keys=True), flush=True)
                        return 0
                    if (
                        args.q_gap_hard_fail
                        and q_gap_report.get("status") == "no_roots"
                        and q_gap_report.get("no_root_hard_clause_eligible")
                    ):
                        selected_q_gap_bits = sorted(cube_literal_by_bit)
                        if args.q_gap_independent_drop_clauses:
                            independent_rows: list[dict[str, object]] = []
                            learned_clause_variants: list[dict[str, object]] = []
                            for drop_start, drop_width in q_gap_drop_windows:
                                drop_bits = set(range(drop_start, drop_start + drop_width))
                                candidate_drop_bits = sorted(bit for bit in selected_q_gap_bits if bit in drop_bits)
                                if not candidate_drop_bits:
                                    independent_rows.append(
                                        {
                                            "drop_window": {"start": drop_start, "width": drop_width},
                                            "status": "no_selected_literals_in_window",
                                            "candidate_drop_literal_count": 0,
                                        }
                                    )
                                    continue

                                completion_bits = candidate_drop_bits
                                completion_count = 1 << len(completion_bits)
                                if completion_count > args.q_gap_minimize_max_completions:
                                    independent_rows.append(
                                        {
                                            "drop_window": {"start": drop_start, "width": drop_width},
                                            "status": "skipped_union_too_many_completions",
                                            "candidate_drop_literal_count": len(candidate_drop_bits),
                                            "completion_count": completion_count,
                                            "max_completions": args.q_gap_minimize_max_completions,
                                        }
                                    )
                                    continue

                                cube_ranges_without_window = [
                                    item for item in cube_ranges if item.start not in candidate_drop_bits
                                ]
                                status_counts: dict[str, int] = {}
                                hard_eligible_completion_count = 0
                                all_no_roots = True
                                factors: list[object] = []
                                if args.q_gap_minimize_workers > 1 and completion_count > 1:
                                    tasks = [
                                        {
                                            "instance": instance,
                                            "fixed_ranges": fixed_ranges,
                                            "cube_ranges_without_window": cube_ranges_without_window,
                                            "completion_bits": completion_bits,
                                            "completion_value": completion_value,
                                            "q_gap_max_bits": args.q_gap_max_bits,
                                            "q_gap_epsilon": args.q_gap_epsilon,
                                            "q_gap_min_hard_margin_bits": args.q_gap_min_hard_margin_bits,
                                            "q_gap_oracle_timeout_seconds": args.q_gap_oracle_timeout_seconds,
                                        }
                                        for completion_value in range(completion_count)
                                    ]
                                    with concurrent.futures.ProcessPoolExecutor(
                                        max_workers=min(args.q_gap_minimize_workers, completion_count)
                                    ) as executor:
                                        completion_results = list(executor.map(evaluate_q_gap_completion_task, tasks))
                                    for completion_result in completion_results:
                                        completion_status = str(completion_result.get("status"))
                                        status_counts[completion_status] = status_counts.get(completion_status, 0) + 1
                                        if completion_result.get("oracle_called"):
                                            counters["q_gap_coppersmith_calls"] += 1
                                        if completion_result.get("factors"):
                                            factors.extend(completion_result.get("factors") or [])
                                        if completion_status == "factored":
                                            event["q_gap_coppersmith_minimization_factor"] = completion_result.get(
                                                "report", completion_result
                                            )
                                            print(json.dumps(event, sort_keys=True), flush=True)
                                            print(
                                                json.dumps(
                                                    {
                                                        "event": "factored",
                                                        **dict(completion_result.get("report", completion_result)),
                                                    },
                                                    sort_keys=True,
                                                ),
                                                flush=True,
                                            )
                                            return 0
                                        if completion_result.get("hard_eligible"):
                                            hard_eligible_completion_count += 1
                                        else:
                                            all_no_roots = False
                                else:
                                    for completion_value in range(completion_count):
                                        completion_ranges = [
                                            FixedRange(bit, 1, (completion_value >> index) & 1)
                                            for index, bit in enumerate(completion_bits)
                                        ]
                                        try:
                                            completion_known, completion_mask = instance.apply_fixed_ranges(
                                                fixed_ranges + cube_ranges_without_window + completion_ranges
                                            )
                                            completion_q_known = derive_q_known_bits(
                                                instance, completion_known, completion_mask
                                            )
                                            completion_q_parts = q_gap_known_parts(
                                                completion_q_known, q_bits=instance.p_bits
                                            )
                                        except Exception as exc:
                                            completion_status = f"derive_error:{exc}"
                                            status_counts[completion_status] = (
                                                status_counts.get(completion_status, 0) + 1
                                            )
                                            all_no_roots = False
                                            continue

                                        if int(completion_q_parts["gap_bits"]) > args.q_gap_max_bits:
                                            completion_status = "skipped_gap_above_max"
                                            status_counts[completion_status] = (
                                                status_counts.get(completion_status, 0) + 1
                                            )
                                            all_no_roots = False
                                            continue

                                        completion_cache_key = (
                                            int(completion_q_parts["low_bits"]),
                                            int(completion_q_parts["prefix_start"]),
                                            int(completion_q_parts["q_lo"]),
                                            int(completion_q_parts["q_hi"]),
                                            args.q_gap_epsilon,
                                            args.q_gap_oracle_timeout_seconds,
                                        )
                                        completion_report = q_gap_coppersmith_cache.get(completion_cache_key)
                                        if completion_report is None:
                                            counters["q_gap_coppersmith_calls"] += 1
                                            completion_report = run_q_middle_gap_coppersmith(
                                                q_known=completion_q_known,
                                                n=instance.n,
                                                q_bits=instance.p_bits,
                                                p_known=completion_known,
                                                p_mask=completion_mask,
                                                epsilon=args.q_gap_epsilon,
                                                min_hard_margin_bits=args.q_gap_min_hard_margin_bits,
                                                timeout_seconds=(
                                                    args.q_gap_oracle_timeout_seconds
                                                    if args.q_gap_oracle_timeout_seconds > 0
                                                    else None
                                                ),
                                            )
                                            q_gap_coppersmith_cache[completion_cache_key] = completion_report
                                        else:
                                            counters["q_gap_coppersmith_cache_hits"] += 1

                                        completion_status = str(completion_report.get("status"))
                                        status_counts[completion_status] = status_counts.get(completion_status, 0) + 1
                                        if completion_report.get("factors"):
                                            factors.extend(completion_report.get("factors") or [])
                                        if completion_status == "factored":
                                            event["q_gap_coppersmith_minimization_factor"] = completion_report
                                            print(json.dumps(event, sort_keys=True), flush=True)
                                            print(
                                                json.dumps({"event": "factored", **completion_report}, sort_keys=True),
                                                flush=True,
                                            )
                                            return 0
                                        if (
                                            completion_status == "no_roots"
                                            and completion_report.get("no_root_hard_clause_eligible")
                                        ):
                                            hard_eligible_completion_count += 1
                                        else:
                                            all_no_roots = False

                                droppable = all_no_roots and hard_eligible_completion_count == completion_count
                                row: dict[str, object] = {
                                    "drop_window": {"start": drop_start, "width": drop_width},
                                    "status": "droppable_sound_no_root" if droppable else "not_droppable",
                                    "candidate_drop_literal_count": len(candidate_drop_bits),
                                    "completion_count": completion_count,
                                    "hard_eligible_completion_count": hard_eligible_completion_count,
                                    "status_counts": status_counts,
                                    "factors": factors,
                                }
                                if droppable:
                                    literal_count = len(selected_q_gap_bits) - len(candidate_drop_bits)
                                    learned_clause_variants.append(
                                        {
                                            "scope": "independent_minimized_q_gap_selected_bits",
                                            "drop_window": {"start": drop_start, "width": drop_width},
                                            "dropped_bits": candidate_drop_bits,
                                            "dropped_literal_count": len(candidate_drop_bits),
                                            "literal_count": literal_count,
                                        }
                                    )
                                    row["learned_clause_literal_count"] = literal_count
                                independent_rows.append(row)

                            if learned_clause_variants:
                                for variant in learned_clause_variants:
                                    dropped_bits = set(int(bit) for bit in variant["dropped_bits"])
                                    literals = [
                                        cube_literal_by_bit[bit]
                                        for bit in selected_q_gap_bits
                                        if bit not in dropped_bits
                                    ]
                                    solver.add(z3.Or(literals) if literals else z3.BoolVal(False))
                                event["learned_clause_scope"] = "independent_minimized_q_gap_selected_bits"
                                event["learned_clause_count"] = len(learned_clause_variants)
                                event["learned_clause_literal_count"] = sum(
                                    int(variant["literal_count"]) for variant in learned_clause_variants
                                )
                                event["learned_clause_variants"] = learned_clause_variants
                                counters["q_gap_coppersmith_independent_drop_clauses"] += len(
                                    learned_clause_variants
                                )
                                counters["q_gap_coppersmith_independent_dropped_literals"] += sum(
                                    int(variant["dropped_literal_count"]) for variant in learned_clause_variants
                                )
                                counters["q_gap_coppersmith_minimized_blocks"] += 1
                                counters["q_gap_coppersmith_dropped_literals"] += sum(
                                    int(variant["dropped_literal_count"]) for variant in learned_clause_variants
                                )
                            else:
                                q_gap_literals = [cube_literal_by_bit[bit] for bit in selected_q_gap_bits]
                                solver.add(z3.Or(q_gap_literals))
                                event["learned_clause_scope"] = "q_gap_selected_bits"
                                event["learned_clause_literal_count"] = len(q_gap_literals)
                            if independent_rows:
                                event["q_gap_coppersmith_independent_minimization"] = independent_rows
                            counters["q_gap_coppersmith_hard_blocks"] += 1
                            event["learned_clause"] = "q_gap_coppersmith_no_root"
                            hard_blocked = True
                        else:
                            dropped_q_gap_bits: set[int] = set()
                            minimization_rows: list[dict[str, object]] = []
                            for drop_start, drop_width in q_gap_drop_windows:
                                drop_bits = set(range(drop_start, drop_start + drop_width))
                                candidate_drop_bits = sorted(
                                    bit
                                    for bit in selected_q_gap_bits
                                    if bit in drop_bits and bit not in dropped_q_gap_bits
                                )
                                if not candidate_drop_bits:
                                    minimization_rows.append(
                                        {
                                            "drop_window": {"start": drop_start, "width": drop_width},
                                            "status": "no_new_selected_literals_in_window",
                                            "candidate_drop_literal_count": 0,
                                            "already_dropped_literal_count": len(dropped_q_gap_bits),
                                        }
                                    )
                                    continue

                                proposed_dropped_bits = dropped_q_gap_bits | set(candidate_drop_bits)
                                completion_bits = sorted(proposed_dropped_bits)
                                completion_count = 1 << len(completion_bits)
                                if completion_count > args.q_gap_minimize_max_completions:
                                    minimization_rows.append(
                                        {
                                            "drop_window": {"start": drop_start, "width": drop_width},
                                            "status": "skipped_union_too_many_completions",
                                            "candidate_drop_literal_count": len(candidate_drop_bits),
                                            "already_dropped_literal_count": len(dropped_q_gap_bits),
                                            "proposed_dropped_literal_count": len(completion_bits),
                                            "completion_count": completion_count,
                                            "max_completions": args.q_gap_minimize_max_completions,
                                        }
                                    )
                                    continue

                                cube_ranges_without_window = [
                                    item for item in cube_ranges if item.start not in proposed_dropped_bits
                                ]
                                status_counts: dict[str, int] = {}
                                hard_eligible_completion_count = 0
                                all_no_roots = True
                                factors: list[object] = []
                                for completion_value in range(completion_count):
                                    completion_ranges = [
                                        FixedRange(bit, 1, (completion_value >> index) & 1)
                                        for index, bit in enumerate(completion_bits)
                                    ]
                                    try:
                                        completion_known, completion_mask = instance.apply_fixed_ranges(
                                            fixed_ranges + cube_ranges_without_window + completion_ranges
                                        )
                                        completion_q_known = derive_q_known_bits(
                                            instance, completion_known, completion_mask
                                        )
                                        completion_q_parts = q_gap_known_parts(
                                            completion_q_known, q_bits=instance.p_bits
                                        )
                                    except Exception as exc:
                                        completion_status = f"derive_error:{exc}"
                                        status_counts[completion_status] = (
                                            status_counts.get(completion_status, 0) + 1
                                        )
                                        all_no_roots = False
                                        continue

                                    if int(completion_q_parts["gap_bits"]) > args.q_gap_max_bits:
                                        completion_status = "skipped_gap_above_max"
                                        status_counts[completion_status] = status_counts.get(completion_status, 0) + 1
                                        all_no_roots = False
                                        continue

                                    completion_cache_key = (
                                        int(completion_q_parts["low_bits"]),
                                        int(completion_q_parts["prefix_start"]),
                                        int(completion_q_parts["q_lo"]),
                                        int(completion_q_parts["q_hi"]),
                                        args.q_gap_epsilon,
                                        args.q_gap_oracle_timeout_seconds,
                                    )
                                    completion_report = q_gap_coppersmith_cache.get(completion_cache_key)
                                    if completion_report is None:
                                        counters["q_gap_coppersmith_calls"] += 1
                                        completion_report = run_q_middle_gap_coppersmith(
                                            q_known=completion_q_known,
                                            n=instance.n,
                                            q_bits=instance.p_bits,
                                            p_known=completion_known,
                                            p_mask=completion_mask,
                                            epsilon=args.q_gap_epsilon,
                                            min_hard_margin_bits=args.q_gap_min_hard_margin_bits,
                                            timeout_seconds=(
                                                args.q_gap_oracle_timeout_seconds
                                                if args.q_gap_oracle_timeout_seconds > 0
                                                else None
                                            ),
                                        )
                                        q_gap_coppersmith_cache[completion_cache_key] = completion_report
                                    else:
                                        counters["q_gap_coppersmith_cache_hits"] += 1

                                    completion_status = str(completion_report.get("status"))
                                    status_counts[completion_status] = status_counts.get(completion_status, 0) + 1
                                    if completion_report.get("factors"):
                                        factors.extend(completion_report.get("factors") or [])
                                    if completion_status == "factored":
                                        event["q_gap_coppersmith_minimization_factor"] = completion_report
                                        print(json.dumps(event, sort_keys=True), flush=True)
                                        print(
                                            json.dumps({"event": "factored", **completion_report}, sort_keys=True),
                                            flush=True,
                                        )
                                        return 0
                                    if (
                                        completion_status == "no_roots"
                                        and completion_report.get("no_root_hard_clause_eligible")
                                    ):
                                        hard_eligible_completion_count += 1
                                    else:
                                        all_no_roots = False

                                droppable = all_no_roots and hard_eligible_completion_count == completion_count
                                if droppable:
                                    dropped_q_gap_bits = proposed_dropped_bits
                                minimization_rows.append(
                                    {
                                        "drop_window": {"start": drop_start, "width": drop_width},
                                        "status": "droppable_sound_no_root" if droppable else "not_droppable",
                                        "candidate_drop_literal_count": len(candidate_drop_bits),
                                        "already_dropped_literal_count": len(completion_bits)
                                        - len(candidate_drop_bits),
                                        "proposed_dropped_literal_count": len(completion_bits),
                                        "completion_count": completion_count,
                                        "hard_eligible_completion_count": hard_eligible_completion_count,
                                        "status_counts": status_counts,
                                        "factors": factors,
                                    }
                                )

                            q_gap_literals = [
                                cube_literal_by_bit[bit]
                                for bit in selected_q_gap_bits
                                if bit not in dropped_q_gap_bits
                            ]
                            if q_gap_literals:
                                solver.add(z3.Or(q_gap_literals))
                                event["learned_clause_scope"] = "q_gap_selected_bits"
                                event["learned_clause_literal_count"] = len(q_gap_literals)
                            else:
                                solver.add(z3.BoolVal(False))
                                event["learned_clause_scope"] = "fixed_q_gap_cube"
                                event["learned_clause_literal_count"] = 0
                            counters["q_gap_coppersmith_hard_blocks"] += 1
                            if dropped_q_gap_bits:
                                counters["q_gap_coppersmith_minimized_blocks"] += 1
                                counters["q_gap_coppersmith_dropped_literals"] += len(dropped_q_gap_bits)
                                event["learned_clause_scope"] = "minimized_q_gap_selected_bits"
                                event["learned_clause_dropped_literal_count"] = len(dropped_q_gap_bits)
                                event["learned_clause_dropped_bits"] = sorted(dropped_q_gap_bits)
                            if minimization_rows:
                                event["q_gap_coppersmith_minimization"] = minimization_rows
                            event["learned_clause"] = "q_gap_coppersmith_no_root"
                            hard_blocked = True

        if (
            not hard_blocked
            and args.run_low_coppersmith
            and all_bits_known(p_mask, 0, args.low_coppersmith_bits)
        ):
            low_cache_key = (p_known & low_coppersmith_mask, p_mask & low_coppersmith_mask)
            low_report = low_coppersmith_cache.get(low_cache_key)
            if low_report is None:
                counters["low_coppersmith_calls"] += 1
                low_report = run_low_coppersmith(
                    p_known=p_known,
                    p_mask=p_mask,
                    n=instance.n,
                    low_bits=args.low_coppersmith_bits,
                    p_bits=instance.p_bits,
                    epsilon=args.low_coppersmith_epsilon,
                    min_hard_margin_bits=args.low_coppersmith_min_hard_margin_bits,
                )
                low_coppersmith_cache[low_cache_key] = low_report
            else:
                counters["low_coppersmith_cache_hits"] += 1
            event["low_coppersmith"] = low_report
            if low_report.get("status") == "factored":
                print(json.dumps(event, sort_keys=True), flush=True)
                print(json.dumps({"event": "factored", **low_report}, sort_keys=True), flush=True)
                return 0
            if (
                args.low_coppersmith_hard_fail
                and low_report.get("status") == "no_roots"
                and low_report.get("hard_clause_eligible")
            ):
                selected_low_bits = sorted(
                    bit for bit in cube_literal_by_bit if bit < args.low_coppersmith_bits
                )
                preverified_guard_matched = True
                for guard_range in preverified_guard_ranges:
                    guard_mask = guard_range.mask
                    if (p_mask & guard_mask) != guard_mask:
                        preverified_guard_matched = False
                        break
                    if (p_known & guard_mask) != guard_range.shifted_value:
                        preverified_guard_matched = False
                        break
                if low_preverified_drop_windows:
                    event["low_coppersmith_preverified_guard_matched"] = preverified_guard_matched
                dropped_low_bits: set[int] = set()
                if preverified_guard_matched:
                    dropped_low_bits = {
                        bit
                        for drop_start, drop_width in low_preverified_drop_windows
                        for bit in range(drop_start, drop_start + drop_width)
                        if bit in selected_low_bits
                    }
                if dropped_low_bits:
                    event["low_coppersmith_preverified_drop_windows"] = [
                        {"start": drop_start, "width": drop_width}
                        for drop_start, drop_width in low_preverified_drop_windows
                    ]
                    event["low_coppersmith_preverified_dropped_bits"] = sorted(dropped_low_bits)
                minimization_rows: list[dict[str, object]] = []
                for drop_start, drop_width in low_drop_windows:
                    drop_bits = set(range(drop_start, drop_start + drop_width))
                    candidate_drop_bits = sorted(
                        bit for bit in selected_low_bits if bit in drop_bits and bit not in dropped_low_bits
                    )
                    if not candidate_drop_bits:
                        minimization_rows.append(
                            {
                                "drop_window": {"start": drop_start, "width": drop_width},
                                "status": "no_new_selected_literals_in_window",
                                "candidate_drop_literal_count": 0,
                                "already_dropped_literal_count": len(dropped_low_bits),
                            }
                        )
                        continue

                    proposed_dropped_low_bits = dropped_low_bits | set(candidate_drop_bits)
                    completion_bits = sorted(proposed_dropped_low_bits)
                    completion_count = 1 << len(completion_bits)
                    if completion_count > args.low_coppersmith_minimize_max_completions:
                        minimization_rows.append(
                            {
                                "drop_window": {"start": drop_start, "width": drop_width},
                                "status": "skipped_union_too_many_completions",
                                "candidate_drop_literal_count": len(candidate_drop_bits),
                                "already_dropped_literal_count": len(dropped_low_bits),
                                "proposed_dropped_literal_count": len(completion_bits),
                                "completion_count": completion_count,
                                "max_completions": args.low_coppersmith_minimize_max_completions,
                            }
                        )
                        continue

                    cube_ranges_without_window = [
                        item
                        for item in cube_ranges
                        if item.start not in proposed_dropped_low_bits
                    ]
                    status_counts: dict[str, int] = {}
                    consistent_completion_count = 0
                    hard_eligible_completion_count = 0
                    factors: list[object] = []
                    all_no_roots = True
                    for completion_value in range(completion_count):
                        completion_ranges = [
                            FixedRange(bit, 1, (completion_value >> index) & 1)
                            for index, bit in enumerate(completion_bits)
                        ]
                        try:
                            completion_known, completion_mask = instance.apply_fixed_ranges(
                                fixed_ranges + cube_ranges_without_window + completion_ranges
                            )
                        except ValueError:
                            status_counts["inconsistent_completion"] = (
                                status_counts.get("inconsistent_completion", 0) + 1
                            )
                            continue
                        consistent_completion_count += 1
                        if not all_bits_known(completion_mask, 0, args.low_coppersmith_bits):
                            completion_report = {"status": "not_triggered_after_completion"}
                        else:
                            completion_cache_key = (
                                completion_known & low_coppersmith_mask,
                                completion_mask & low_coppersmith_mask,
                            )
                            completion_report = low_coppersmith_cache.get(completion_cache_key)
                            if completion_report is None:
                                counters["low_coppersmith_calls"] += 1
                                completion_report = run_low_coppersmith(
                                    p_known=completion_known,
                                    p_mask=completion_mask,
                                    n=instance.n,
                                    low_bits=args.low_coppersmith_bits,
                                    p_bits=instance.p_bits,
                                    epsilon=args.low_coppersmith_epsilon,
                                    min_hard_margin_bits=args.low_coppersmith_min_hard_margin_bits,
                                )
                                low_coppersmith_cache[completion_cache_key] = completion_report
                            else:
                                counters["low_coppersmith_cache_hits"] += 1
                        completion_status = str(completion_report.get("status"))
                        status_counts[completion_status] = status_counts.get(completion_status, 0) + 1
                        if completion_report.get("factors"):
                            factors.extend(completion_report.get("factors") or [])
                        if completion_status == "no_roots" and completion_report.get("hard_clause_eligible"):
                            hard_eligible_completion_count += 1
                        else:
                            all_no_roots = False

                    droppable = all_no_roots and consistent_completion_count > 0
                    if droppable:
                        dropped_low_bits = proposed_dropped_low_bits
                    minimization_rows.append(
                        {
                            "drop_window": {"start": drop_start, "width": drop_width},
                            "status": "droppable_sound_no_root" if droppable else "not_droppable",
                            "candidate_drop_literal_count": len(candidate_drop_bits),
                            "already_dropped_literal_count": len(completion_bits) - len(candidate_drop_bits),
                            "proposed_dropped_literal_count": len(completion_bits),
                            "completion_count": completion_count,
                            "consistent_completion_count": consistent_completion_count,
                            "hard_eligible_completion_count": hard_eligible_completion_count,
                            "status_counts": status_counts,
                            "factors": factors,
                        }
                    )

                low_prefix_literals = [
                    cube_literal_by_bit[bit]
                    for bit in selected_low_bits
                    if bit not in dropped_low_bits
                ]
                if low_prefix_literals:
                    solver.add(z3.Or(low_prefix_literals))
                    event["learned_clause_scope"] = "low_prefix_selected_bits"
                    event["learned_clause_literal_count"] = len(low_prefix_literals)
                else:
                    solver.add(z3.BoolVal(False))
                    event["learned_clause_scope"] = "fixed_low_prefix"
                    event["learned_clause_literal_count"] = 0
                counters["low_coppersmith_hard_blocks"] += 1
                if dropped_low_bits:
                    counters["low_coppersmith_minimized_blocks"] += 1
                    counters["low_coppersmith_dropped_literals"] += len(dropped_low_bits)
                    event["learned_clause_scope"] = "minimized_low_prefix_selected_bits"
                    event["learned_clause_dropped_literal_count"] = len(dropped_low_bits)
                    event["learned_clause_dropped_bits"] = sorted(dropped_low_bits)
                if minimization_rows:
                    event["low_coppersmith_minimization"] = minimization_rows
                event["learned_clause"] = "low_coppersmith_no_root"
                hard_blocked = True

        if not hard_blocked:
            solver.add(z3.Or(cube_literals))
            counters["soft_blocks"] += 1
            event["learned_clause"] = "sample_block_only"

        if args.jsonl:
            print(json.dumps(event, sort_keys=True), flush=True)
        else:
            print(
                f"cube {event['index']}: prefix={prefix_status}, "
                f"p_fixed={event['p_fixed_bits_in_prefix']}, "
                f"q_fixed={event['q_fixed_bits_in_prefix']}, "
                f"q_low={event['q_low_bits']}, clause={event['learned_clause']}",
                flush=True,
            )

    print(json.dumps({"event": "summary", **counters}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
