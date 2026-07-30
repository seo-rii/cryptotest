#!/usr/bin/env python3
"""Sweep corrected challenge 7 CP-SAT tail probes over x0 with x7 free."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAIL_SCRIPT = ROOT / "experiments" / "try_hensel_tail_cp_sat.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="tmp/ct07_tail_cpsat_x0_free_x7")
    parser.add_argument("--branch-lows", default="0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15")
    parser.add_argument("--seeds", default="7")
    parser.add_argument("--max-seconds", type=float, default=0.0)
    parser.add_argument("--time-limit", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--T", type=int, default=928)
    parser.add_argument("--tail-limbs", type=int, default=70)
    parser.add_argument("--skip-known-prefix-limbs", type=int, default=16)
    parser.add_argument("--small-prime-filters", type=int, default=6)
    parser.add_argument("--odd-residue-filters", type=int, default=6)
    parser.add_argument(
        "--lowlift-q",
        type=int,
        default=0,
        help="forward --lowlift-q to the CP-SAT tail model",
    )
    parser.add_argument("--decision-p-range", action="append", default=[])
    parser.add_argument("--decision-q-range", action="append", default=[])
    parser.add_argument("--decision-select", choices=("min", "max"), default="min")
    parser.add_argument("--no-compact-q-limbs", action="store_true")
    parser.add_argument("--no-randomize-search", action="store_true")
    parser.add_argument("--keep-phase-saving", action="store_true")
    parser.add_argument("--resume", action="store_true", help="skip runs whose log already has a JSON summary")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    branch_lows = [int(part.strip(), 0) for part in args.branch_lows.split(",") if part.strip()]
    seeds = [int(part.strip(), 0) for part in args.seeds.split(",") if part.strip()]
    if not branch_lows:
        raise SystemExit("--branch-lows produced no values")
    if not seeds:
        raise SystemExit("--seeds produced no values")
    if any(value < 0 or value >= 16 for value in branch_lows):
        raise SystemExit("--branch-lows values must be in 0..15")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.jsonl"
    summary = {
        "output_dir": str(output_dir),
        "branch_lows": branch_lows,
        "seeds": seeds,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "runs": 0,
        "factored": False,
        "factor_log": None,
    }

    start_time = time.monotonic()
    with manifest_path.open("a", encoding="utf-8") as manifest:
        for branch_low in branch_lows:
            for seed in seeds:
                if args.max_seconds > 0 and time.monotonic() - start_time >= args.max_seconds:
                    summary["stopped_reason"] = "max_seconds"
                    if args.json:
                        print(json.dumps(summary, sort_keys=True))
                    return 0

                stem = f"x0_{branch_low:02x}_seed_{seed}"
                log_path = output_dir / f"{stem}.log"
                if args.resume and log_path.exists():
                    existing_summary = None
                    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
                        line = line.strip()
                        if line.startswith("{") and line.endswith("}"):
                            existing_summary = json.loads(line)
                            break
                    if existing_summary is not None:
                        summary["runs"] += 1
                        if existing_summary.get("p") and existing_summary.get("q"):
                            summary["factored"] = True
                            summary["factor_log"] = str(log_path)
                            summary["stopped_reason"] = "factored"
                            print(f"[+] FACTORED in existing {log_path}")
                            print(f"p = {existing_summary['p']}")
                            print(f"q = {existing_summary['q']}")
                            print(f"plaintext hex = {existing_summary.get('plaintext_hex')}")
                            if args.json:
                                print(json.dumps(summary, sort_keys=True))
                            return 0
                        print(f"{stem}: skipped existing log={log_path}", flush=True)
                        continue
                command = [
                    sys.executable,
                    str(TAIL_SCRIPT),
                    "--T",
                    str(args.T),
                    "--tail-limbs",
                    str(args.tail_limbs),
                    "--skip-known-prefix-limbs",
                    str(args.skip_known_prefix_limbs),
                    "--branch-low",
                    str(branch_low),
                    "--free-branch-high",
                    "--time-limit",
                    str(args.time_limit),
                    "--workers",
                    str(args.workers),
                    "--small-prime-filters",
                    str(args.small_prime_filters),
                    "--odd-residue-filters",
                    str(args.odd_residue_filters),
                    "--lowlift-q",
                    str(args.lowlift_q),
                    "--decision-select",
                    args.decision_select,
                    "--random-seed",
                    str(seed),
                    "--json-summary",
                ]
                if not args.no_compact_q_limbs:
                    command.append("--compact-q-limbs")
                if not args.no_randomize_search:
                    command.append("--randomize-search")
                if not args.keep_phase_saving:
                    command.append("--no-phase-saving")
                for decision_range in args.decision_p_range:
                    command.extend(["--decision-p-range", decision_range])
                for decision_range in args.decision_q_range:
                    command.extend(["--decision-q-range", decision_range])

                run_started = time.monotonic()
                result = subprocess.run(command, text=True, capture_output=True, check=False)
                elapsed = time.monotonic() - run_started
                log_path.write_text(result.stdout + result.stderr, encoding="utf-8")

                json_summary = None
                for line in reversed(result.stdout.splitlines()):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        json_summary = json.loads(line)
                        break
                record = {
                    "branch_low": branch_low,
                    "seed": seed,
                    "elapsed": elapsed,
                    "returncode": result.returncode,
                    "log": str(log_path),
                    "summary": json_summary,
                }
                manifest.write(json.dumps(record, sort_keys=True) + "\n")
                manifest.flush()
                summary["runs"] += 1

                if json_summary and json_summary.get("p") and json_summary.get("q"):
                    summary["factored"] = True
                    summary["factor_log"] = str(log_path)
                    summary["stopped_reason"] = "factored"
                    print(f"[+] FACTORED in {log_path}")
                    print(f"p = {json_summary['p']}")
                    print(f"q = {json_summary['q']}")
                    print(f"plaintext hex = {json_summary.get('plaintext_hex')}")
                    if args.json:
                        print(json.dumps(summary, sort_keys=True))
                    return 0

                status = json_summary.get("status") if json_summary else "NO_JSON"
                print(
                    f"{stem}: status={status} returncode={result.returncode} "
                    f"elapsed={elapsed:.1f}s log={log_path}",
                    flush=True,
                )

    summary["stopped_reason"] = "completed"
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
