#!/usr/bin/env python3
"""Run cuso q-divisor checks over ranked cube JSONL candidates.

This script must be executed with the Sage/cuso Python environment, for example:

    /home/seorii/.local/share/miniforge3/bin/mamba run -n soinsu-sage python \
        cryptotest/solutions/07_sat_cas_explore/run_cuso_qdivisor_candidates.py ...
"""

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


def compact_ranges(raw_ranges: object) -> list[dict[str, int]]:
    if not isinstance(raw_ranges, list):
        raise ValueError("candidate row has no cube_ranges list")
    ranges: list[dict[str, int]] = []
    for raw in raw_ranges:
        if not isinstance(raw, dict):
            raise ValueError("invalid cube range item")
        start = int(raw["start"])
        width = int(raw["width"])
        value = int(raw.get("value", 0))
        if start < 0 or width <= 0 or value < 0 or value >= (1 << width):
            raise ValueError(f"invalid cube range {raw!r}")
        ranges.append({"start": start, "width": width, "value": value})
    return ranges


def read_cube_rows(path: Path, top: int) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    with path.expanduser().open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if top and len(rows) >= top:
                break
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("event") != "cube":
                continue
            rows.append((line_number, row))
    return rows


def factor_from_q_roots(
    roots: list[dict[Any, Any]],
    model: dict[str, Any],
    *,
    n: int,
    e: int,
    ct: int,
    mask: int,
    known: int,
) -> dict[str, str] | None:
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
        return {
            "p_hex": hex(p),
            "q_hex": hex(q),
            "plaintext_hex": plaintext.hex(),
            "plaintext_repr": repr(plaintext),
        }
    return None


def run_candidate(
    *,
    row_index: int,
    line_number: int,
    row: dict[str, Any],
    n: int,
    e: int,
    ct: int,
    mask: int,
    known: int,
    graph: bool | None,
    intermediate: bool,
    partial: bool,
    max_shifts: int | None,
    max_multiplicity: int | None,
    flatter_args: str | None,
    low_bits: int,
    z_bits: int | None,
    monic: bool,
    z_nonnegative: bool,
) -> dict[str, Any]:
    started = time.time()
    cube_ranges = compact_ranges(row.get("cube_ranges"))
    fixed_ranges = [
        (item["start"], item["width"], item["value"])
        for item in cube_ranges
    ]
    known2, ranges = cuso_solver.apply_fixed_ranges(known, cuso_solver.UNKNOWN_RANGES, fixed_ranges)
    model = cuso_solver.build_q_divisor_relation(
        n,
        known2,
        ranges,
        low_bits=low_bits,
        z_bits=z_bits,
        monic=monic,
        z_nonnegative=z_nonnegative,
    )
    base_record: dict[str, Any] = {
        "event": "cuso_qdivisor_candidate",
        "index": row_index,
        "source_line": line_number,
        "cube_ranges": cube_ranges,
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
        "monic": model["monic"],
    }
    roots = cuso_solver.run_cuso(
        [model["relation"]],
        model["bounds"],
        n,
        model["q_min"],
        model["q_max"],
        graph,
        intermediate,
        partial,
        max_shifts,
        None,
        max_multiplicity,
        False,
        None,
        None,
        flatter_args,
    )
    factor = factor_from_q_roots(roots, model, n=n, e=e, ct=ct, mask=mask, known=known)
    return {
        **base_record,
        "elapsed_seconds": time.time() - started,
        "roots_returned": len(roots),
        "status": "factored" if factor else "no_factor",
        "factor": factor,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_jsonl", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top", type=int, default=16)
    parser.add_argument("--qdiv-low-bits", type=int, default=600)
    parser.add_argument("--qdiv-z-bits", type=int)
    parser.add_argument("--qdiv-non-monic", action="store_true")
    parser.add_argument("--qdiv-z-nonnegative", action="store_true")
    parser.add_argument("--no-graph", action="store_true")
    parser.add_argument("--no-intermediate", action="store_true")
    parser.add_argument("--partial", action="store_true")
    parser.add_argument("--max-shifts", type=int, default=512)
    parser.add_argument("--max-multiplicity", type=int, default=2)
    parser.add_argument("--flatter-args", default="-rhf 1.03")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.top < 1:
        raise SystemExit("--top must be positive")
    if args.max_shifts is not None and args.max_shifts <= 0:
        raise SystemExit("--max-shifts must be positive")
    if args.max_multiplicity is not None and args.max_multiplicity <= 0:
        raise SystemExit("--max-multiplicity must be positive")

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    c7 = cuso_solver.load_constants()
    n = int(c7.N_HEX.replace(" ", ""), 16)
    e = int(c7.E)
    ct = int(c7.CT_HEX.replace(" ", ""), 16)
    mask = int(c7.MASK_HEX.replace(" ", ""), 16)
    known = int(c7.P_AND_MASK_HEX.replace(" ", ""), 16) & mask
    graph = False if args.no_graph else None
    intermediate = not args.no_intermediate
    rows = read_cube_rows(args.source_jsonl, args.top)

    args.output.expanduser().parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    solved: dict[str, Any] | None = None
    with args.output.expanduser().open("w", encoding="utf-8") as handle:
        for row_index, (line_number, row) in enumerate(rows, start=1):
            try:
                record = run_candidate(
                    row_index=row_index,
                    line_number=line_number,
                    row=row,
                    n=n,
                    e=e,
                    ct=ct,
                    mask=mask,
                    known=known,
                    graph=graph,
                    intermediate=intermediate,
                    partial=args.partial,
                    max_shifts=args.max_shifts,
                    max_multiplicity=args.max_multiplicity,
                    flatter_args=args.flatter_args,
                    low_bits=args.qdiv_low_bits,
                    z_bits=args.qdiv_z_bits,
                    monic=not args.qdiv_non_monic,
                    z_nonnegative=args.qdiv_z_nonnegative,
                )
            except Exception as exc:
                record = {
                    "event": "cuso_qdivisor_candidate",
                    "index": row_index,
                    "source_line": line_number,
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

        summary = {
            "event": "summary",
            "status": "factored" if solved else "no_factor",
            "elapsed_seconds": time.time() - started,
            "source_jsonl": str(args.source_jsonl),
            "output": str(args.output),
            "records_completed": len(records),
            "candidates_available": len(rows),
            "status_counts": status_counts,
            "solved": solved,
            "parameters": {
                "top": args.top,
                "qdiv_low_bits": args.qdiv_low_bits,
                "qdiv_z_bits": args.qdiv_z_bits,
                "qdiv_non_monic": args.qdiv_non_monic,
                "qdiv_z_nonnegative": args.qdiv_z_nonnegative,
                "no_graph": args.no_graph,
                "no_intermediate": args.no_intermediate,
                "partial": args.partial,
                "max_shifts": args.max_shifts,
                "max_multiplicity": args.max_multiplicity,
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
