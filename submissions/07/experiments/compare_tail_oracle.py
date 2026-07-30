#!/usr/bin/env python3
"""Compare the cheap tail-window filter with a product-prefix oracle.

The Go tail-window filter intentionally uses a free carry-in at bit T.  That
makes it useful as a broad conservative filter, but it is not an exact
tail-lock equality.  This wrapper runs the same assumption cube twice:

1. weak:    low product prefix + tail-window bits with bounded free carry
2. oracle: exact product prefix through the same tail window

The comparison is a guardrail for future exact-tail CNF work.  A weak UNSAT
with an oracle SAT is suspicious and usually means the window carry bound is
too small or the two configurations are not comparable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "experiments" / "run_go_sat_filter.py"


def parse_int_list(text: str) -> list[int]:
    out: list[int] = []
    for raw in text.split(","):
        raw = raw.strip()
        if not raw:
            continue
        out.append(int(raw, 0))
    if not out:
        raise argparse.ArgumentTypeError("expected at least one integer")
    return out


def run_filter(args: argparse.Namespace, *, mode: str, summary_path: Path) -> dict:
    if mode == "weak":
        arith_bits = args.base_arith_bits
        tail_window_bits = args.tail_window_bits
        tail_window_carry_bits = args.tail_window_carry_bits
    elif mode == "oracle":
        arith_bits = args.oracle_arith_bits
        tail_window_bits = 0
        tail_window_carry_bits = 0
    else:
        raise ValueError(mode)

    cmd = [
        sys.executable,
        str(RUNNER),
        "--assume-x6low-x1high7-x2low7",
        "--summary-only",
        "--summary-json",
        str(summary_path),
        "--T",
        str(args.T),
        "--arith-bits",
        str(arith_bits),
        "--skip-known-prefix-limbs",
        str(args.skip_known_prefix_limbs),
        "--x6high-bits",
        str(args.x6high_bits),
        "--x6high",
        hex(args.x6high),
        "--x1low32",
        hex(args.x1low32),
        "--x1high7",
        hex(args.x1high7),
        "--x2low7",
        hex(args.x2low7),
        "--x6low",
        hex(args.x6low),
        "--solver",
        args.solver,
    ]
    if args.go_binary:
        cmd.extend(["--go-binary", str(args.go_binary)])
    if args.q_interval_bound:
        cmd.append("--q-interval-bound")
    if tail_window_bits:
        cmd.extend(["--tail-window-bits", str(tail_window_bits)])
        cmd.extend(["--tail-window-carry-bits", str(tail_window_carry_bits)])
        if args.tail_window_start is not None:
            cmd.extend(["--tail-window-start", str(args.tail_window_start)])

    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    data["_mode"] = mode
    data["_arith_bits"] = arith_bits
    data["_tail_window_bits"] = tail_window_bits
    data["_tail_window_carry_bits"] = tail_window_carry_bits
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--T", type=int, default=800)
    parser.add_argument("--base-arith-bits", type=int, default=272)
    parser.add_argument("--oracle-arith-bits", type=int)
    parser.add_argument("--skip-known-prefix-limbs", type=int, default=15)
    parser.add_argument("--tail-window-start", type=int)
    parser.add_argument("--tail-window-bits", type=int, default=16)
    parser.add_argument("--tail-window-carry-bits", type=int, default=12)
    parser.add_argument(
        "--tail-window-carry-bits-list",
        type=parse_int_list,
        help="comma-separated carry-bit values; runs the oracle once and each weak window once",
    )
    parser.add_argument("--q-interval-bound", action="store_true")
    parser.add_argument("--x6high-bits", type=int, default=32)
    parser.add_argument("--x6high", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--x6low", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--x1low32", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--x1high7", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--x2low7", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--go-binary", type=Path)
    parser.add_argument("--summary-json", type=Path)
    args = parser.parse_args()

    if args.oracle_arith_bits is None:
        start = args.tail_window_start if args.tail_window_start is not None else args.T
        args.oracle_arith_bits = start + args.tail_window_bits
    if args.oracle_arith_bits < args.base_arith_bits:
        parser.error("--oracle-arith-bits must be at least --base-arith-bits")
    if args.tail_window_bits <= 0:
        parser.error("--tail-window-bits must be positive for a comparison")

    carry_values = args.tail_window_carry_bits_list or [args.tail_window_carry_bits]

    with tempfile.TemporaryDirectory(prefix="crypto7_tail_oracle_") as tmp_raw:
        tmp = Path(tmp_raw)
        oracle = run_filter(args, mode="oracle", summary_path=tmp / "oracle.json")
        oracle_sat = int(oracle["sat"])
        oracle_unsat = int(oracle["unsat"])
        oracle_summary = {
            "sat": oracle_sat,
            "unsat": oracle_unsat,
            "arith_bits": oracle["_arith_bits"],
            "vars": next(iter(oracle["by_base"].values()))["vars"],
            "clauses": next(iter(oracle["by_base"].values()))["clauses"],
        }

        weak_results = []
        for carry_bits in carry_values:
            old_carry_bits = args.tail_window_carry_bits
            args.tail_window_carry_bits = carry_bits
            weak = run_filter(args, mode="weak", summary_path=tmp / f"weak_carry_{carry_bits}.json")
            args.tail_window_carry_bits = old_carry_bits

            weak_sat = int(weak["sat"])
            weak_unsat = int(weak["unsat"])
            if weak_sat == 0 and oracle_sat > 0:
                verdict = "suspicious_weak_stronger_than_oracle"
            elif weak_sat > 0 and oracle_sat == 0:
                verdict = "weak_missed_oracle_unsat"
            elif weak_sat == 0 and oracle_sat == 0:
                verdict = "both_unsat"
            else:
                verdict = "both_have_sat"
            weak_results.append(
                {
                    "verdict": verdict,
                    "sat": weak_sat,
                    "unsat": weak_unsat,
                    "arith_bits": weak["_arith_bits"],
                    "tail_window_bits": weak["_tail_window_bits"],
                    "tail_window_carry_bits": weak["_tail_window_carry_bits"],
                    "vars": next(iter(weak["by_base"].values()))["vars"],
                    "clauses": next(iter(weak["by_base"].values()))["clauses"],
                }
            )

    if len(weak_results) == 1:
        out = {
            "verdict": weak_results[0]["verdict"],
            "case": {
                "T": args.T,
                "x6high_bits": args.x6high_bits,
                "x6high": hex(args.x6high),
                "x6low": hex(args.x6low),
                "x1low32": hex(args.x1low32),
                "x1high7": hex(args.x1high7),
                "x2low7": hex(args.x2low7),
                "q_interval_bound": args.q_interval_bound,
            },
            "weak": weak_results[0],
            "oracle": oracle_summary,
        }
    else:
        out = {
            "verdict": "sweep",
            "case": {
                "T": args.T,
                "x6high_bits": args.x6high_bits,
                "x6high": hex(args.x6high),
                "x6low": hex(args.x6low),
                "x1low32": hex(args.x1low32),
                "x1high7": hex(args.x1high7),
                "x2low7": hex(args.x2low7),
                "q_interval_bound": args.q_interval_bound,
            },
            "weak_results": weak_results,
            "oracle": oracle_summary,
        }
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
