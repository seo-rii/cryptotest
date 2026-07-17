#!/usr/bin/env python3
"""Run cuso q-divisor branch sweeps with machine-readable output."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SOLUTIONS = HERE.parent
if str(SOLUTIONS) not in sys.path:
    sys.path.insert(0, str(SOLUTIONS))

import solve_07_cuso as cuso_solver  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--branch-mode",
        choices=("none", "low", "high", "both"),
        default="high",
    )
    parser.add_argument(
        "--branch-low-values",
        default="all",
        help="comma/range list such as all, 0xb, or 0-3; used for low/both",
    )
    parser.add_argument(
        "--branch-high-values",
        default="all",
        help="comma/range list such as all, 0xa, or 0-3; used for high/both",
    )
    parser.add_argument("--fix-p-range", action="append", default=[], type=cuso_solver.parse_bit_range_value)
    parser.add_argument("--qdiv-low-bits", type=int, default=600)
    parser.add_argument("--qdiv-z-bits", type=int)
    parser.add_argument("--qdiv-non-monic", action="store_true")
    parser.add_argument("--qdiv-z-nonnegative", action="store_true")
    parser.add_argument("--no-graph", action="store_true")
    parser.add_argument("--no-intermediate", action="store_true")
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--max-shifts", type=int, default=256)
    parser.add_argument("--shift-window")
    parser.add_argument("--max-multiplicity", type=int, default=1)
    parser.add_argument("--disable-recenter", action="store_true")
    parser.add_argument("--small-weight-factor", type=float)
    parser.add_argument("--graph-slack-bits", type=float)
    parser.add_argument("--flatter-args", default="-rhf 1.03")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.qdiv_low_bits <= 0:
        raise SystemExit("--qdiv-low-bits must be positive")
    if args.max_shifts is not None and args.max_shifts <= 0:
        raise SystemExit("--max-shifts must be positive")
    if args.max_multiplicity is not None and args.max_multiplicity <= 0:
        raise SystemExit("--max-multiplicity must be positive")
    if args.shift_window and args.max_shifts is not None:
        raise SystemExit("--shift-window and --max-shifts are mutually exclusive")

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.branch_low_values.strip().lower() == "all":
        low_values: list[int | None] = list(range(16))
    else:
        low_values = []
        for raw_part in args.branch_low_values.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if "-" in part:
                left, right = part.split("-", 1)
                low_values.extend(range(int(left, 0), int(right, 0) + 1))
            else:
                low_values.append(int(part, 0))
    if args.branch_high_values.strip().lower() == "all":
        high_values: list[int | None] = list(range(16))
    else:
        high_values = []
        for raw_part in args.branch_high_values.split(","):
            part = raw_part.strip()
            if not part:
                continue
            if "-" in part:
                left, right = part.split("-", 1)
                high_values.extend(range(int(left, 0), int(right, 0) + 1))
            else:
                high_values.append(int(part, 0))
    low_values = sorted(dict.fromkeys(low_values))
    high_values = sorted(dict.fromkeys(high_values))
    if any(value is not None and not (0 <= value < 16) for value in low_values + high_values):
        raise SystemExit("branch nibble values must be in 0..15")
    if args.branch_mode == "none":
        low_values = [None]
        high_values = [None]
    elif args.branch_mode == "low":
        high_values = [None]
    elif args.branch_mode == "high":
        low_values = [None]
    if not low_values or not high_values:
        raise SystemExit("empty branch value set")

    shift_window = None
    if args.shift_window:
        try:
            offset_text, size_text = args.shift_window.split(":", 1)
            shift_window = (int(offset_text, 0), int(size_text, 0))
        except ValueError as exc:
            raise SystemExit("--shift-window must be OFFSET:SIZE") from exc

    c7 = cuso_solver.load_constants()
    n = int(c7.N_HEX.replace(" ", ""), 16)
    e = int(c7.E)
    ct = int(c7.CT_HEX.replace(" ", ""), 16)
    mask = int(c7.MASK_HEX.replace(" ", ""), 16)
    known = int(c7.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    graph = False if args.no_graph else None
    intermediate = not args.no_intermediate
    args.output.expanduser().parent.mkdir(parents=True, exist_ok=True)

    started = time.time()
    records: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    solved: dict[str, Any] | None = None
    with args.output.expanduser().open("w", encoding="utf-8") as handle:
        for low in low_values:
            for high in high_values:
                fixed_ranges = list(args.fix_p_range)
                if low is not None:
                    fixed_ranges.append((150, 4, low))
                if high is not None:
                    fixed_ranges.append((920, 4, high))
                branch_started = time.time()
                base_record: dict[str, Any] = {
                    "event": "cuso_qdivisor_branch",
                    "index": len(records) + 1,
                    "branch_low": low,
                    "branch_high": high,
                    "fixed_ranges": [
                        {"start": start, "width": width, "value": value}
                        for start, width, value in fixed_ranges
                    ],
                }
                try:
                    known2, ranges = cuso_solver.apply_fixed_ranges(
                        known,
                        cuso_solver.UNKNOWN_RANGES,
                        fixed_ranges,
                    )
                    model = cuso_solver.build_q_divisor_relation(
                        n,
                        known2,
                        ranges,
                        low_bits=args.qdiv_low_bits,
                        z_bits=args.qdiv_z_bits,
                        monic=not args.qdiv_non_monic,
                        z_nonnegative=args.qdiv_z_nonnegative,
                    )
                    base_record.update(
                        {
                            "remaining_ranges": [
                                {"start": start, "width": width}
                                for start, width in ranges
                            ],
                            "q_low_ranges": [
                                {"start": start, "width": width}
                                for start, width in model["q_low_ranges"]
                            ],
                            "q_prefix_bits": int(model["q_prefix_bits"]),
                            "q_prefix_start": int(model["q_prefix_start"]),
                            "q_gap_bits": int(model["q_gap_bits"]),
                            "q_z_bound_bits": int(model["q_z_bound_bits"]),
                            "relation_terms": len(model["relation"].dict()),
                            "relation_degree": int(model["relation"].degree()),
                            "monic": bool(model["monic"]),
                            "bounds_bits": [
                                int(bound[1]).bit_length() - 1
                                for bound in model["bounds"].values()
                            ],
                        }
                    )
                    roots = cuso_solver.run_cuso(
                        [model["relation"]],
                        model["bounds"],
                        n,
                        model["q_min"],
                        model["q_max"],
                        graph,
                        intermediate,
                        args.partial,
                        args.max_shifts,
                        shift_window,
                        args.max_multiplicity,
                        args.disable_recenter,
                        args.small_weight_factor,
                        args.graph_slack_bits,
                        args.flatter_args,
                    )
                    factor = None
                    for root in roots:
                        q_value = cuso_solver.parse_root_value(root, "p")
                        if q_value is not None:
                            q = int(cuso_solver.ZZ(q_value))
                        else:
                            subs = {}
                            missing = []
                            for x in [model["z"], *model["low_gens"]]:
                                value = cuso_solver.parse_root_value(root, x)
                                if value is None:
                                    missing.append(str(x))
                                    continue
                                subs[x] = cuso_solver.ZZ(value)
                            if missing:
                                continue
                            q = int(
                                cuso_solver.ZZ(model["q_low"].subs(subs))
                                + cuso_solver.ZZ(model["q_high"])
                                + cuso_solver.ZZ(model["q_modulus"]) * cuso_solver.ZZ(subs[model["z"]])
                            )
                        if not (1 < q < n) or n % q != 0:
                            continue
                        p = n // q
                        if (p & mask) != known:
                            continue
                        plaintext = cuso_solver.decrypt(n, e, ct, p, q)
                        factor = {
                            "p_hex": hex(p),
                            "q_hex": hex(q),
                            "plaintext_hex": plaintext.hex(),
                            "plaintext_repr": repr(plaintext),
                        }
                        break
                    record = {
                        **base_record,
                        "elapsed_seconds": time.time() - branch_started,
                        "roots_returned": len(roots),
                        "status": "factored" if factor else "no_factor",
                        "factor": factor,
                    }
                except Exception as exc:
                    record = {
                        **base_record,
                        "elapsed_seconds": time.time() - branch_started,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                records.append(record)
                status = str(record.get("status"))
                status_counts[status] = status_counts.get(status, 0) + 1
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                if record.get("factor"):
                    solved = record
                    break
            if solved:
                break

        summary = {
            "event": "summary",
            "status": "factored" if solved else "no_factor",
            "elapsed_seconds": time.time() - started,
            "output": str(args.output),
            "records_completed": len(records),
            "status_counts": status_counts,
            "solved": solved,
            "parameters": {
                "branch_mode": args.branch_mode,
                "branch_low_values": args.branch_low_values,
                "branch_high_values": args.branch_high_values,
                "qdiv_low_bits": args.qdiv_low_bits,
                "qdiv_z_bits": args.qdiv_z_bits,
                "qdiv_non_monic": args.qdiv_non_monic,
                "qdiv_z_nonnegative": args.qdiv_z_nonnegative,
                "no_graph": args.no_graph,
                "no_intermediate": args.no_intermediate,
                "partial": args.partial,
                "max_shifts": args.max_shifts,
                "shift_window": args.shift_window,
                "max_multiplicity": args.max_multiplicity,
                "disable_recenter": args.disable_recenter,
                "small_weight_factor": args.small_weight_factor,
                "graph_slack_bits": args.graph_slack_bits,
                "flatter_args": args.flatter_args,
            },
        }
        handle.write(json.dumps(summary, sort_keys=True) + "\n")

    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(
            "status={status} records={records} output={output}".format(
                status=summary["status"],
                records=summary["records_completed"],
                output=args.output,
            )
        )
    return 0 if solved else 2


if __name__ == "__main__":
    raise SystemExit(main())
