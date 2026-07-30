#!/usr/bin/env python3
"""Paired, isolated benchmark runner for the problem 2 deep review."""

from __future__ import annotations

import argparse
import os
import platform
import random
import re
import shlex
import statistics
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile


CANDIDATES = [
    (0, "full_bmi2_align64", "candidate_full_bmi2_align64"),
    (1, "pair_loop_bmi2", "candidate_pair_loop_bmi2"),
    (2, "unroll2_bmi2", "candidate_unroll2_bmi2"),
    (3, "unroll5_bmi2", "candidate_unroll5_bmi2"),
    (4, "full_bmi2_align16", "candidate_full_bmi2_align16"),
    (5, "full_bmi2_align32", "candidate_full_bmi2_align32"),
    (6, "full_bmi2_align128", "candidate_full_bmi2_align128"),
    (7, "full_bmi2_embedded", "candidate_full_bmi2_embedded"),
    (8, "pair_loop_avx2", "candidate_pair_loop_avx2"),
    (9, "pair_unrolled_avx2", "candidate_pair_unrolled_avx2"),
    (10, "single_round_avx2", "candidate_single_round_avx2"),
    (11, "sequential_chains", "candidate_sequential_chains"),
    (12, "submission_wrapper", "candidate_submission_wrapper"),
    (13, "inline_core", "candidate_inline_core"),
    (14, "full_without_bmi2", "candidate_full_without_bmi2"),
    (15, "register_loop", "candidate_register_loop"),
    (16, "unroll3_bmi2", "candidate_unroll3_bmi2"),
    (17, "unroll4_bmi2", "candidate_unroll4_bmi2"),
]


def cpu_model() -> str:
    path = Path("/proc/cpuinfo")
    if path.exists():
        for line in path.read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def run(command: list[str], *, cpu: int | None = None) -> str:
    effective = command if cpu is None else ["taskset", "-c", str(cpu), *command]
    completed = subprocess.run(
        effective,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def symbol_info(executable: Path, symbol: str) -> tuple[int, int]:
    output = run(["nm", "-S", "--defined-only", str(executable)])
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[3] == symbol:
            return int(fields[0], 16), int(fields[1], 16)
    raise RuntimeError(f"symbol not found: {symbol}")


def text_size(executable: Path) -> int:
    output = run(["size", str(executable)])
    fields = output.splitlines()[1].split()
    return int(fields[0])


def median_mad(values: list[float]) -> tuple[float, float]:
    median = statistics.median(values)
    mad = statistics.median(abs(value - median) for value in values)
    return median, mad


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", default=os.environ.get("CC", "gcc"))
    parser.add_argument("--iterations", type=int, default=2_000_000)
    parser.add_argument("--warmup-iterations", type=int, default=300_000)
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument("--cpu", default="auto")
    parser.add_argument("--extra-cflag", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--only",
        action="append",
        help="benchmark only this candidate name (repeatable); selftest still covers all",
    )
    parser.add_argument(
        "--quiet-raw",
        action="store_true",
        help="retain raw rows in --output but print only metadata and summaries",
    )
    args = parser.parse_args()
    if min(args.iterations, args.warmup_iterations, args.random_cases) <= 0:
        parser.error("iterations, warmup, and random cases must be positive")
    if args.samples < 15:
        parser.error("--samples must be at least 15")

    allowed = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else []
    if args.cpu == "auto":
        cpu = allowed[0] if allowed else None
    elif args.cpu == "none":
        cpu = None
    else:
        cpu = int(args.cpu)
        if allowed and cpu not in allowed:
            parser.error(f"CPU {cpu} unavailable; allowed={allowed}")

    root = Path(__file__).resolve().parents[4]
    source = Path(__file__).with_name("deep_candidates.c")
    archive = Path(__file__).resolve().parents[2] / "2_암호구현.zip"
    compiler_version = run([args.compiler, "--version"]).splitlines()[0]
    flags = [
        "-O3", "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-DNDEBUG", *args.extra_cflag,
    ]
    metadata = [
        f"host={platform.platform()}",
        f"cpu={cpu_model()}",
        f"pinned_cpu={cpu if cpu is not None else 'none'}",
        f"compiler={compiler_version}",
        f"flags={shlex.join(flags)}",
        f"timer=CLOCK_MONOTONIC_RAW",
        f"iterations={args.iterations}",
        f"warmup_iterations={args.warmup_iterations}",
        f"samples={args.samples}",
        f"random_cases={args.random_cases}",
    ]
    output_lines = list(metadata)
    print("\n".join(metadata), flush=True)

    with tempfile.TemporaryDirectory(prefix="p2-deep-") as temporary:
        build = Path(temporary)
        vector1 = build / "testvector.txt"
        vector20 = build / "testvector_20round.txt"
        with ZipFile(archive) as zipped:
            vector1.write_bytes(zipped.read("code/testvector.txt"))
            vector20.write_bytes(zipped.read("code/testvector_20round.txt"))

        all_executable = build / "deep_all"
        run([args.compiler, *flags, str(source), "-o", str(all_executable)])
        selftest = run(
            [str(all_executable), "--selftest", str(vector1), str(vector20),
             str(args.random_cases)],
            cpu=cpu,
        ).strip()
        print(selftest, flush=True)
        output_lines.extend(selftest.splitlines())
        if "selftest=PASS" not in selftest:
            raise RuntimeError("selftest failed")

        selected_candidates = CANDIDATES
        if args.only:
            requested = set(args.only)
            known = {name for _, name, _ in CANDIDATES}
            unknown = requested - known
            if unknown:
                parser.error(f"unknown --only candidate(s): {sorted(unknown)}")
            selected_candidates = [
                item for item in CANDIDATES
                if item[1] == CANDIDATES[0][1] or item[1] in requested
            ]

        executables: dict[str, Path] = {}
        layouts: dict[str, tuple[int, int, int]] = {}
        for identifier, name, symbol in selected_candidates:
            executable = build / f"deep_{identifier:02d}_{name}"
            run([
                args.compiler, *flags, "-Wno-unused-function",
                f"-DSELECT_CANDIDATE={identifier}", str(source), "-o", str(executable),
            ])
            executables[name] = executable
            address, symbol_bytes = symbol_info(executable, symbol)
            layouts[name] = (address, symbol_bytes, text_size(executable))

        layout_header = "layout_candidate,address_mod4096,symbol_bytes,text_bytes"
        print(layout_header)
        output_lines.append(layout_header)
        for _, name, _ in selected_candidates:
            address, symbol_bytes, total_text = layouts[name]
            line = f"{name},{address % 4096},{symbol_bytes},{total_text}"
            print(line)
            output_lines.append(line)

        raw_header = (
            "raw_sample,candidate,order,baseline_ns,candidate_ns,paired_speedup"
        )
        if not args.quiet_raw:
            print(raw_header, flush=True)
        output_lines.append(raw_header)
        generator = random.Random(0x243F6A8885A308D3)
        results: dict[str, tuple[list[float], list[float], list[float]]] = {}
        pattern = re.compile(r"candidate=(\S+) ns=([0-9.]+)")
        baseline_name = CANDIDATES[0][1]

        for identifier, name, _ in selected_candidates[1:]:
            del identifier
            baseline_samples: list[float] = []
            candidate_samples: list[float] = []
            speedups: list[float] = []
            for sample in range(1, args.samples + 1):
                salt = (
                    0x9E3779B97F4A7C15
                    * (sample + 131 * CANDIDATES.index(next(item for item in CANDIDATES if item[1] == name)))
                ) & ((1 << 64) - 1)
                order = [baseline_name, name]
                generator.shuffle(order)
                measured: dict[str, float] = {}
                for current in order:
                    text = run([
                        str(executables[current]), "--bench",
                        str(args.iterations), str(args.warmup_iterations), str(salt),
                    ], cpu=cpu)
                    match = pattern.search(text)
                    if not match or match.group(1) != current:
                        raise RuntimeError(f"cannot parse benchmark output: {text}")
                    measured[current] = float(match.group(2))
                baseline = measured[baseline_name]
                candidate = measured[name]
                speedup = baseline / candidate
                baseline_samples.append(baseline)
                candidate_samples.append(candidate)
                speedups.append(speedup)
                line = (
                    f"{sample},{name},{'>'.join(order)},{baseline:.3f},"
                    f"{candidate:.3f},{speedup:.6f}"
                )
                if not args.quiet_raw:
                    print(line, flush=True)
                output_lines.append(line)
            results[name] = (baseline_samples, candidate_samples, speedups)

        summary_header = (
            "summary_candidate,baseline_median_ns,candidate_median_ns,"
            "candidate_mad_ns,paired_speedup_median,paired_speedup_mad,"
            "candidate_min_ns,candidate_max_ns"
        )
        print(summary_header)
        output_lines.append(summary_header)
        for _, name, _ in selected_candidates[1:]:
            baseline_values, candidate_values, speedups = results[name]
            candidate_median, candidate_mad = median_mad(candidate_values)
            speedup_median, speedup_mad = median_mad(speedups)
            line = (
                f"{name},{statistics.median(baseline_values):.3f},"
                f"{candidate_median:.3f},{candidate_mad:.3f},"
                f"{speedup_median:.6f},{speedup_mad:.6f},"
                f"{min(candidate_values):.3f},{max(candidate_values):.3f}"
            )
            print(line)
            output_lines.append(line)

    if args.output:
        args.output.write_text("\n".join(output_lines) + "\n", encoding="utf-8")
        print(f"saved_output={args.output.resolve()}")


if __name__ == "__main__":
    main()
