#!/usr/bin/env python3
"""Build or run the updated challenge 7 SAT+CAS work plan.

The default mode is dry-run: print exact commands and do not start search.
Use --execute only when the long-running jobs should actually launch.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_LOW_FIX = ["784:46:0x245521490bd", "920:4:0"]
DEFAULT_LOW_BASE = ["150:4:0", "210:39:0", "265:84:0", "362:78:0"]
DEFAULT_LOW_VARIANTS = ["150:4:0", "150:4:4", "150:4:8", "150:4:12"]
DEFAULT_LOW_DROP_WINDOWS = [
    "150:2",
    "152:2",
    "210:2",
    "212:2",
    "267:2",
    "269:2",
    "362:2",
    "364:2",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="run commands instead of only printing them")
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=Path.cwd() / "tmp" / f"ct07_updated_plan_{time.strftime('%Y%m%d_%H%M%S')}",
    )
    parser.add_argument(
        "--stage",
        action="append",
        choices=["phase-a", "q-gap-smoke", "lowc600-union", "high20-exact", "sat-loop-smoke"],
        help="stage to include; may be repeated. Default excludes sat-loop-smoke.",
    )
    parser.add_argument("--parallel-heavy", action="store_true", help="run lowc600-union and high20-exact together")
    parser.add_argument("--json", action="store_true", help="print the plan/result as JSON")
    parser.add_argument("--low-bits", type=int, default=600)
    parser.add_argument("--epsilon", type=float, default=0.02)
    parser.add_argument("--min-hard-margin-bits", type=float, default=8.0)
    parser.add_argument("--qgap-candidate-json", action="append", type=Path, default=[])
    parser.add_argument("--qgap-max-gap-bits", type=int, default=520)
    parser.add_argument("--qgap-start", type=int, default=1)
    parser.add_argument("--qgap-stop", type=int, default=0)
    parser.add_argument("--qgap-limit", type=int, default=0)
    parser.add_argument("--qgap-chunk-size", type=int, default=10)
    parser.add_argument("--qgap-workers", type=int, default=4)
    parser.add_argument("--lowc-start", type=int, default=0)
    parser.add_argument("--lowc-stop", type=int, default=65536)
    parser.add_argument("--lowc-chunk-size", type=int, default=512)
    parser.add_argument("--lowc-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--lowc-jobs", type=int, default=4)
    parser.add_argument("--lowc-label", default="x0_x1_x2_x3_16bit_lowc600")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--x6high-bits", type=int, default=20)
    parser.add_argument("--x6high-candidate", action="append", default=[], help="high20 candidate, e.g. 0x12345")
    parser.add_argument("--x6high-candidate-file", action="append", type=Path, default=[])
    parser.add_argument("--high20-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--high20-workers", type=int, default=2)
    parser.add_argument("--solver", default="cadical153")
    parser.add_argument("--sat-loop-max-cubes", type=int, default=32)
    parser.add_argument("--sat-loop-timeout-seconds", type=float, default=900.0)
    args = parser.parse_args()
    args.run_dir = args.run_dir.expanduser().resolve()

    if args.low_bits <= 0:
        raise SystemExit("--low-bits must be positive")
    if args.min_hard_margin_bits < 0:
        raise SystemExit("--min-hard-margin-bits must be nonnegative")
    if args.lowc_start < 0 or args.lowc_stop <= args.lowc_start:
        raise SystemExit("--lowc-stop must be greater than --lowc-start, and start must be nonnegative")
    if args.lowc_chunk_size < 1:
        raise SystemExit("--lowc-chunk-size must be positive")
    if args.lowc_timeout_seconds <= 0 or args.high20_timeout_seconds <= 0:
        raise SystemExit("timeouts must be positive")
    if args.lowc_jobs < 1 or args.high20_workers < 1:
        raise SystemExit("worker/job counts must be positive")
    if not (1 <= args.x6high_bits < 46):
        raise SystemExit("--x6high-bits must be in 1..45")
    if args.sat_loop_max_cubes < 1:
        raise SystemExit("--sat-loop-max-cubes must be positive")

    if args.qgap_max_gap_bits < 0:
        raise SystemExit("--qgap-max-gap-bits must be nonnegative")
    if args.qgap_limit < 0:
        raise SystemExit("--qgap-limit must be nonnegative")
    if args.qgap_chunk_size < 1:
        raise SystemExit("--qgap-chunk-size must be positive")
    if args.qgap_workers < 1:
        raise SystemExit("--qgap-workers must be positive")
    if args.qgap_start < 1:
        raise SystemExit("--qgap-start must be at least 1")
    if args.qgap_stop and args.qgap_stop < args.qgap_start:
        raise SystemExit("--qgap-stop must be 0 or at least --qgap-start")

    stages = args.stage or ["phase-a", "q-gap-smoke", "lowc600-union", "high20-exact"]
    x6high_values: list[int] = []
    for raw_value in args.x6high_candidate:
        x6high_values.append(int(raw_value, 0))
    for path in args.x6high_candidate_file:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            for part in line.replace(",", " ").split():
                x6high_values.append(int(part, 0))
    seen_x6high: set[int] = set()
    x6high_candidates: list[int] = []
    for value in x6high_values:
        if value < 0 or value >= (1 << args.x6high_bits):
            raise SystemExit(f"x6 high candidate does not fit {args.x6high_bits} bits: {value:#x}")
        if value not in seen_x6high:
            seen_x6high.add(value)
            x6high_candidates.append(value)

    plan: list[dict[str, Any]] = []
    if "phase-a" in stages:
        plan.append(
            {
                "stage": "phase-a",
                "name": "lowc-margin-audit",
                "command": [
                    sys.executable,
                    "-B",
                    str(HERE / "low_coppersmith_threshold_audit.py"),
                    "--low-bits-values",
                    "513,554,560,600,608,616",
                    "--max-low-cubes",
                    "1",
                    "--epsilon",
                    str(args.epsilon),
                    "--min-hard-margin-bits",
                    str(args.min_hard_margin_bits),
                    "--json",
                ],
                "timeout_seconds": 60.0,
                "log_prefix": "phase_a_lowc_margin_audit",
                "skip_reason": None,
            }
        )

    if "q-gap-smoke" in stages:
        qgap_effective_stop = args.qgap_stop
        if args.qgap_limit:
            limit_stop = args.qgap_start + args.qgap_limit - 1
            qgap_effective_stop = min(qgap_effective_stop, limit_stop) if qgap_effective_stop else limit_stop
        command = [
            sys.executable,
            "-B",
            str(HERE / "run_q_gap_parallel.py"),
            "--output-dir",
            str(args.run_dir / "q_gap_parallel"),
            "--max-gap-bits",
            str(args.qgap_max_gap_bits),
            "--epsilon",
            str(args.epsilon),
            "--min-hard-margin-bits",
            str(args.min_hard_margin_bits),
            "--candidate-start",
            str(args.qgap_start),
            "--candidate-stop",
            str(qgap_effective_stop),
            "--chunk-size",
            str(args.qgap_chunk_size),
            "--workers",
            str(args.qgap_workers),
            "--no-pdf-check",
        ]
        for candidate_path in args.qgap_candidate_json:
            command.extend(["--candidate-json", str(candidate_path)])
        plan.append(
            {
                "stage": "q-gap-smoke",
                "name": "q-gap-coppersmith-smoke",
                "command": command,
                "timeout_seconds": 3600.0,
                "log_prefix": "q_gap_coppersmith_smoke",
                "skip_reason": None,
                "allowed_returncodes": [0, 2],
            }
        )

    if "lowc600-union" in stages:
        output_dir = args.run_dir / "lowc600_union_shards"
        output_jsonl = args.run_dir / f"lowc600_union_{args.lowc_start}_{args.lowc_stop}.jsonl"
        command = [
            sys.executable,
            "-B",
            str(HERE / "low_coppersmith_union_shard_batch.py"),
            "--output-dir",
            str(output_dir),
            "--output-jsonl",
            str(output_jsonl),
            "--label",
            args.lowc_label,
            "--completion-start",
            str(args.lowc_start),
            "--completion-stop",
            str(args.lowc_stop),
            "--chunk-size",
            str(args.lowc_chunk_size),
            "--timeout-seconds",
            str(args.lowc_timeout_seconds),
            "--jobs",
            str(args.lowc_jobs),
            "--low-bits",
            str(args.low_bits),
            "--epsilon",
            str(args.epsilon),
            "--min-hard-margin-bits",
            str(args.min_hard_margin_bits),
        ]
        if not args.no_resume:
            command.append("--resume")
        for fixed_range in DEFAULT_LOW_FIX:
            command.extend(["--fix-p-range", fixed_range])
        for selected_range in DEFAULT_LOW_BASE:
            command.extend(["--base-selected-p-range", selected_range])
        for variant_range in DEFAULT_LOW_VARIANTS:
            command.extend(["--variant-p-range", variant_range])
        for drop_window in DEFAULT_LOW_DROP_WINDOWS:
            command.extend(["--drop-window", drop_window])
        lowc_chunk_count = max(
            1,
            (args.lowc_stop - args.lowc_start + args.lowc_chunk_size - 1) // args.lowc_chunk_size,
        )
        plan.append(
            {
                "stage": "lowc600-union",
                "name": "lowc600-union-shards",
                "command": command,
                "timeout_seconds": args.lowc_timeout_seconds * lowc_chunk_count + 60.0,
                "log_prefix": "lowc600_union_shards",
                "skip_reason": None,
            }
        )

    if "high20-exact" in stages:
        if not x6high_candidates:
            plan.append(
                {
                    "stage": "high20-exact",
                    "name": "high20-exact-q272",
                    "command": [],
                    "timeout_seconds": 0.0,
                    "log_prefix": "high20_exact_q272",
                    "skip_reason": "no --x6high-candidate or --x6high-candidate-file supplied",
                }
            )
        for index, candidate in enumerate(x6high_candidates, start=1):
            plan.append(
                {
                    "stage": "high20-exact",
                    "name": f"high20-exact-q272-{index:04d}",
                    "command": [
                        sys.executable,
                        "-B",
                        str(ROOT / "solutions" / "run_07_go_sat_filter.py"),
                        "--free-x1-x6high-filter",
                        "--branch-low",
                        "0",
                        "--branch-high",
                        "0",
                        "--T",
                        "800",
                        "--arith-bits",
                        "272",
                        "--skip-known-prefix-bits",
                        "208",
                        "--lowlift-q",
                        "272",
                        "--q-interval-bound",
                        "--odd-residue-prime",
                        "3",
                        "--odd-residue-prime",
                        "5",
                        "--odd-residue-prime",
                        "7",
                        "--odd-residue-prime",
                        "11",
                        "--exact-tail-carry-limbs",
                        "1",
                        "--exact-carry-bits",
                        "272",
                        "--x6high-bits",
                        str(args.x6high_bits),
                        "--x6high-candidate",
                        hex(candidate),
                        "--solver",
                        args.solver,
                        "--summary-json",
                        str(args.run_dir / f"high20_exact_q272_{index:04d}_{candidate:x}.json"),
                        "--summary-only",
                    ],
                    "timeout_seconds": args.high20_timeout_seconds,
                    "log_prefix": f"high20_exact_q272_{index:04d}_{candidate:x}",
                    "skip_reason": None,
                }
            )

    if "sat-loop-smoke" in stages:
        plan.append(
            {
                "stage": "sat-loop-smoke",
                "name": "sat-cas-loop-smoke",
                "command": [
                    sys.executable,
                    "-B",
                    str(HERE / "sat_cas_batch_runner.py"),
                    "--output",
                    str(args.run_dir / "sat_loop_smoke.jsonl"),
                    "--cube-ranges",
                    "150:4,210:39,265:84,362:78",
                    "--max-cubes",
                    str(args.sat_loop_max_cubes),
                    "--timeout-seconds",
                    str(args.sat_loop_timeout_seconds),
                    "--check-bits",
                    "608",
                    "--prefix-core",
                    "bv",
                    "--timeout-ms",
                    "1000",
                    "--enumerate-p-free-limit",
                    "24",
                    "--run-low-coppersmith",
                    "--low-coppersmith-hard-fail",
                    "--low-coppersmith-bits",
                    str(args.low_bits),
                    "--low-coppersmith-epsilon",
                    str(args.epsilon),
                    "--low-coppersmith-min-hard-margin-bits",
                    str(args.min_hard_margin_bits),
                    "--include-cube-ranges",
                ],
                "timeout_seconds": args.sat_loop_timeout_seconds + 30.0,
                "log_prefix": "sat_loop_smoke",
                "skip_reason": None,
            }
        )

    for spec in plan:
        spec["command_text"] = shlex.join(spec["command"]) if spec["command"] else ""

    if not args.execute:
        payload = {
            "event": "updated_plan_dry_run",
            "run_dir": str(args.run_dir),
            "parallel_heavy": args.parallel_heavy,
            "commands": plan,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"run_dir={args.run_dir}")
            print("mode=dry-run")
            print(f"parallel_heavy={args.parallel_heavy}")
            for spec in plan:
                if spec["skip_reason"]:
                    print(f"[{spec['stage']}] {spec['name']}: skipped ({spec['skip_reason']})")
                    continue
                print(f"[{spec['stage']}] {spec['name']}:")
                print(spec["command_text"])
        return 0

    args.run_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    phase_a = [spec for spec in plan if spec["stage"] == "phase-a"]
    q_gap = [spec for spec in plan if spec["stage"] == "q-gap-smoke"]
    heavy = [spec for spec in plan if spec["stage"] in {"lowc600-union", "high20-exact"}]
    sat_loop = [spec for spec in plan if spec["stage"] == "sat-loop-smoke"]

    for group in [phase_a, q_gap, sat_loop]:
        if group is sat_loop and args.parallel_heavy:
            pass
        for spec in group:
            if spec["skip_reason"]:
                results.append({**spec, "status": "skipped"})
                continue
            stdout_path = args.run_dir / f"{spec['log_prefix']}.stdout"
            stderr_path = args.run_dir / f"{spec['log_prefix']}.stderr"
            started_at = time.time()
            try:
                process = subprocess.run(
                    spec["command"],
                    cwd=ROOT,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=float(spec["timeout_seconds"]),
                    check=False,
                )
                stdout_path.write_text(process.stdout, encoding="utf-8")
                stderr_path.write_text(process.stderr, encoding="utf-8")
                result = {
                    **spec,
                    "status": "ok"
                    if process.returncode in set(spec.get("allowed_returncodes", [0]))
                    else "process_error",
                    "returncode": process.returncode,
                    "elapsed_seconds": round(time.time() - started_at, 3),
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                }
            except subprocess.TimeoutExpired as exc:
                stdout_text = exc.stdout if isinstance(exc.stdout, str) else ""
                stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
                stdout_path.write_text(stdout_text, encoding="utf-8")
                stderr_path.write_text(stderr_text, encoding="utf-8")
                result = {
                    **spec,
                    "status": "timeout",
                    "returncode": None,
                    "elapsed_seconds": round(time.time() - started_at, 3),
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                }
            meta_path = args.run_dir / f"{spec['log_prefix']}.meta.json"
            meta_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
            result["meta_path"] = str(meta_path)
            results.append(result)

        if group is phase_a:
            if args.parallel_heavy:
                active_heavy = [spec for spec in heavy if not spec["skip_reason"]]
                skipped_heavy = [spec for spec in heavy if spec["skip_reason"]]
                for spec in skipped_heavy:
                    results.append({**spec, "status": "skipped"})
                workers = max(1, min(len(active_heavy), args.high20_workers + 1))
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    future_to_spec: dict[concurrent.futures.Future[subprocess.CompletedProcess[str]], dict[str, Any]] = {}
                    for spec in active_heavy:
                        future_to_spec[
                            executor.submit(
                                subprocess.run,
                                spec["command"],
                                cwd=ROOT,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                text=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                timeout=float(spec["timeout_seconds"]),
                                check=False,
                            )
                        ] = {**spec, "started_at": time.time()}
                    for future in concurrent.futures.as_completed(future_to_spec):
                        spec = future_to_spec[future]
                        stdout_path = args.run_dir / f"{spec['log_prefix']}.stdout"
                        stderr_path = args.run_dir / f"{spec['log_prefix']}.stderr"
                        try:
                            process = future.result()
                            stdout_path.write_text(process.stdout, encoding="utf-8")
                            stderr_path.write_text(process.stderr, encoding="utf-8")
                            result = {
                                **{key: value for key, value in spec.items() if key != "started_at"},
                                "status": "ok"
                                if process.returncode
                                in set(spec.get("allowed_returncodes", [0]))
                                else "process_error",
                                "returncode": process.returncode,
                                "elapsed_seconds": round(time.time() - float(spec["started_at"]), 3),
                                "stdout_path": str(stdout_path),
                                "stderr_path": str(stderr_path),
                            }
                        except subprocess.TimeoutExpired as exc:
                            stdout_text = exc.stdout if isinstance(exc.stdout, str) else ""
                            stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
                            stdout_path.write_text(stdout_text, encoding="utf-8")
                            stderr_path.write_text(stderr_text, encoding="utf-8")
                            result = {
                                **{key: value for key, value in spec.items() if key != "started_at"},
                                "status": "timeout",
                                "returncode": None,
                                "elapsed_seconds": round(time.time() - float(spec["started_at"]), 3),
                                "stdout_path": str(stdout_path),
                                "stderr_path": str(stderr_path),
                            }
                        meta_path = args.run_dir / f"{spec['log_prefix']}.meta.json"
                        meta_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
                        result["meta_path"] = str(meta_path)
                        results.append(result)
            else:
                for spec in heavy:
                    if spec["skip_reason"]:
                        results.append({**spec, "status": "skipped"})
                        continue
                    stdout_path = args.run_dir / f"{spec['log_prefix']}.stdout"
                    stderr_path = args.run_dir / f"{spec['log_prefix']}.stderr"
                    started_at = time.time()
                    try:
                        process = subprocess.run(
                            spec["command"],
                            cwd=ROOT,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                            text=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=float(spec["timeout_seconds"]),
                            check=False,
                        )
                        stdout_path.write_text(process.stdout, encoding="utf-8")
                        stderr_path.write_text(process.stderr, encoding="utf-8")
                        result = {
                            **spec,
                            "status": "ok"
                            if process.returncode in set(spec.get("allowed_returncodes", [0]))
                            else "process_error",
                            "returncode": process.returncode,
                            "elapsed_seconds": round(time.time() - started_at, 3),
                            "stdout_path": str(stdout_path),
                            "stderr_path": str(stderr_path),
                        }
                    except subprocess.TimeoutExpired as exc:
                        stdout_text = exc.stdout if isinstance(exc.stdout, str) else ""
                        stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
                        stdout_path.write_text(stdout_text, encoding="utf-8")
                        stderr_path.write_text(stderr_text, encoding="utf-8")
                        result = {
                            **spec,
                            "status": "timeout",
                            "returncode": None,
                            "elapsed_seconds": round(time.time() - started_at, 3),
                            "stdout_path": str(stdout_path),
                            "stderr_path": str(stderr_path),
                        }
                    meta_path = args.run_dir / f"{spec['log_prefix']}.meta.json"
                    meta_path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
                    result["meta_path"] = str(meta_path)
                    results.append(result)

    payload = {
        "event": "updated_plan_execute",
        "run_dir": str(args.run_dir),
        "parallel_heavy": args.parallel_heavy,
        "results": results,
    }
    summary_path = args.run_dir / "updated_plan_summary.json"
    summary_path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    payload["summary_path"] = str(summary_path)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        for result in results:
            print(
                f"[{result['stage']}] {result['name']} "
                f"status={result['status']} returncode={result.get('returncode')}"
            )
        print(f"summary={summary_path}")
    return 0 if all(result["status"] in {"ok", "skipped"} for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
