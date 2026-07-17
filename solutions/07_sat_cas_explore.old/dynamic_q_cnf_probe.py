#!/usr/bin/env python3
"""Audit interval-derived q bits on exported CNFs.

The Go exporter already turns q low bits into unit clauses and folds the q high
prefix into the high product.  This diagnostic builds the same free-x1/x6high
CNF, derives q bits independently, and solves with the q low literals as
assumptions to confirm whether a proposed dynamic-q hook would add anything on
this CNF path.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


ROOT = Path(__file__).resolve().parents[2]
SOLUTIONS = ROOT / "solutions"
GO_EXPORTER = SOLUTIONS / "go_hensel_tail"
CONSTANTS = SOLUTIONS / "investigate_07_rsa_partial_bits.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x6high-candidate", action="append", type=lambda text: int(text, 0), required=True)
    parser.add_argument("--x6high-bits", type=int, default=32)
    parser.add_argument("--fix-p-range", action="append", default=[], type=parse_fixed_range)
    parser.add_argument("--T", type=int, default=800)
    parser.add_argument("--limb-bits", type=int, default=16)
    parser.add_argument("--tail-limbs", type=int, default=1)
    parser.add_argument("--arith-bits", type=int, default=272)
    parser.add_argument("--skip-known-prefix-bits", type=int, default=208)
    parser.add_argument("--lowlift-q", type=int, default=272)
    parser.add_argument("--q-interval-bound", action="store_true")
    parser.add_argument("--exact-tail-carry-limbs", type=int, default=1)
    parser.add_argument("--exact-carry-bits", type=int, default=272)
    parser.add_argument("--odd-residue-prime", action="append", type=int, default=[])
    parser.add_argument("--branch-low", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--branch-high", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--go-binary", type=Path)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--keep-cnf", action="store_true")
    parser.add_argument("--compare-base", action="store_true")
    parser.add_argument("--model-limit", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not (1 <= args.x6high_bits < 46):
        raise SystemExit("--x6high-bits must be in 1..45")
    if args.T < 830 - args.x6high_bits:
        raise SystemExit("--T must be at or above the fixed x6 high boundary")
    if args.model_limit < 0:
        raise SystemExit("--model-limit must be nonnegative")

    try:
        from pysat.formula import CNF
        from pysat.solvers import Solver
    except ImportError as exc:
        print("python-sat is required for dynamic_q_cnf_probe.py", file=sys.stderr)
        raise SystemExit(2) from exc

    spec = importlib.util.spec_from_file_location("c7_constants", CONSTANTS)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load constants from {CONSTANTS}")
    constants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(constants)
    n_value = int(constants.N_HEX.replace(" ", ""), 16)
    mask_value = int(constants.MASK_HEX.replace(" ", ""), 16)
    known_value = int(constants.P_AND_MASK_HEX.replace(" ", ""), 16) & mask_value

    instance = load_instance()
    fixed_start = 830 - args.x6high_bits
    fixed_width = args.x6high_bits
    workdir_context = tempfile.TemporaryDirectory(prefix="crypto7_dynq_") if args.workdir is None else None
    base_dir = args.workdir if args.workdir is not None else Path(workdir_context.name)
    base_dir.mkdir(parents=True, exist_ok=True)
    go_binary = args.go_binary
    if go_binary is None:
        go_binary = base_dir / "go_hensel_tail"
        subprocess.run(
            ["go", "build", "-o", str(go_binary), "."],
            cwd=GO_EXPORTER,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    rows = []
    try:
        for x6high in args.x6high_candidate:
            if x6high < 0 or x6high >= (1 << args.x6high_bits):
                raise SystemExit(f"x6 high candidate does not fit {args.x6high_bits} bits: {x6high:#x}")

            group_label = f"dynamic_q_x6high_{x6high:x}_{fixed_width}_T_{args.T}"
            input_path = base_dir / f"{group_label}.json"
            cnf_path = base_dir / f"{group_label}.cnf"
            var_map_path = base_dir / f"{group_label}.vars.json"
            fixed_ranges = [FixedRange(fixed_start, fixed_width, x6high)] + list(args.fix_p_range)
            payload = {
                "T": args.T,
                "limb_bits": args.limb_bits,
                "tail_limbs": args.tail_limbs,
                "arithmetic_bits": args.arith_bits,
                "skip_known_prefix_limbs": 0,
                "skip_known_prefix_bits": args.skip_known_prefix_bits,
                "tail_window_start": 0,
                "tail_window_bits": 0,
                "tail_window_carry_bits": 0,
                "exact_tail_carry_limbs": args.exact_tail_carry_limbs,
                "exact_carry_bits": args.exact_carry_bits,
                "lowlift_q_bits": args.lowlift_q,
                "q_interval_bound": args.q_interval_bound,
                "odd_residue_primes": args.odd_residue_prime,
                "no_comments": True,
                "n": hex(n_value),
                "known_p": hex(known_value),
                "mask_p": hex(mask_value),
                "branch_low": args.branch_low,
                "branch_high": args.branch_high,
                "fixed_p_ranges": [
                    {"start": item.start, "width": item.width, "value": hex(item.value)}
                    for item in fixed_ranges
                ],
            }
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            exporter = subprocess.run(
                [
                    str(go_binary),
                    "-input",
                    str(input_path),
                    "-out",
                    str(cnf_path),
                    "-var-map",
                    str(var_map_path),
                    "-no-comments",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if exporter.returncode != 0:
                rows.append(
                    {
                        "x6high": hex(x6high),
                        "status": "exporter_error",
                        "stderr": exporter.stderr.strip(),
                    }
                )
                continue

            cnf = CNF(from_file=str(cnf_path))
            var_map = json.loads(var_map_path.read_text(encoding="utf-8"))
            p_known, p_mask = instance.apply_fixed_ranges(fixed_ranges)
            q_known = derive_q_known_bits(instance, p_known, p_mask)
            q_assumptions = []
            q_missing = 0
            for bit in range(instance.p_bits):
                if ((q_known.mask >> bit) & 1) == 0:
                    continue
                var = var_map.get(f"q_{bit}")
                if var is None:
                    q_missing += 1
                    continue
                q_assumptions.append(int(var) if ((q_known.known >> bit) & 1) else -int(var))

            base_sat = None
            base_elapsed = None
            if args.compare_base:
                with Solver(name=args.solver, bootstrap_with=cnf.clauses) as solver:
                    started_at = time.monotonic()
                    base_sat = bool(solver.solve())
                    base_elapsed = round(time.monotonic() - started_at, 6)

            models = []
            with Solver(name=args.solver, bootstrap_with=cnf.clauses) as solver:
                started_at = time.monotonic()
                q_sat = bool(solver.solve(assumptions=q_assumptions))
                q_elapsed = round(time.monotonic() - started_at, 6)
                if q_sat and args.model_limit:
                    for _ in range(args.model_limit):
                        model_lits = {lit for lit in solver.get_model() if lit > 0}
                        model_row = {}
                        for label, start, width in (("x1", 210, 39), ("x2low7", 265, 7), ("x6", 784, 46)):
                            value = 0
                            complete = True
                            for off in range(width):
                                var = var_map.get(f"p_{start + off}")
                                if var is None:
                                    complete = False
                                    break
                                if int(var) in model_lits:
                                    value |= 1 << off
                            if complete:
                                model_row[label] = hex(value)
                        models.append(model_row)
                        block = []
                        for start, width in ((210, 39), (265, 7), (784, 46)):
                            for off in range(width):
                                var = var_map.get(f"p_{start + off}")
                                if var is None:
                                    continue
                                var_int = int(var)
                                block.append(-var_int if var_int in model_lits else var_int)
                        if not block:
                            break
                        solver.add_clause(block)
                        if not solver.solve(assumptions=q_assumptions):
                            break

            row = {
                "x6high": hex(x6high),
                "fixed_start": fixed_start,
                "fixed_width": fixed_width,
                "T": args.T,
                "arith_bits": args.arith_bits,
                "vars": cnf.nv,
                "clauses": len(cnf.clauses),
                "q_low_bits": q_known.low_bits,
                "q_prefix_bits": q_known.prefix_bits,
                "q_prefix_start": q_known.prefix_start,
                "q_known_bits": q_known.mask.bit_count(),
                "q_unit_assumption_count": len(q_assumptions),
                "q_missing_var_count": q_missing,
                "base_sat": base_sat,
                "base_elapsed_seconds": base_elapsed,
                "q_assumption_sat": q_sat,
                "q_assumption_elapsed_seconds": q_elapsed,
                "model_count": len(models),
                "models": models,
            }
            rows.append(row)
            if not args.keep_cnf:
                input_path.unlink(missing_ok=True)
                cnf_path.unlink(missing_ok=True)
                var_map_path.unlink(missing_ok=True)
    finally:
        if workdir_context is not None:
            workdir_context.cleanup()

    summary = {
        "event": "dynamic_q_cnf_probe",
        "candidate_count": len(args.x6high_candidate),
        "x6high_bits": args.x6high_bits,
        "compare_base": args.compare_base,
        "sat": sum(1 for row in rows if row.get("q_assumption_sat") is True),
        "unsat": sum(1 for row in rows if row.get("q_assumption_sat") is False),
        "errors": sum(1 for row in rows if row.get("status") == "exporter_error"),
    }
    payload = {"summary": summary, "rows": rows}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
