#!/usr/bin/env python3
"""Verify and repeatedly benchmark contest-shaped challenge 2 submissions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import shlex
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from zipfile import ZipFile


TIMING_PATTERN = re.compile(r"average per 20rounds = ([0-9.]+) us")
ITERATIONS_PATTERN = re.compile(r"const int iterations = [0-9]+;")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compile complete contest.c variants separately, discard warmups, "
            "interleave repeated runs, and report robust paired statistics."
        )
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        metavar="NAME=SOURCE",
        help="contest.c variant; defaults to the preserved before/final pair",
    )
    parser.add_argument("--baseline", help="case name used as the speedup denominator")
    parser.add_argument("--compiler", default=os.environ.get("CC", "gcc"))
    parser.add_argument(
        "--iterations",
        type=int,
        default=5_000_000,
        help="timed outer-loop calls per process (official harness uses 1000000)",
    )
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--samples", "--repeats", dest="samples", type=int, default=21)
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument(
        "--cpu",
        default="auto",
        help="Linux logical CPU number, 'auto' for the first allowed CPU, or 'none'",
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="add -march=native; default flags match the supplied run script",
    )
    parser.add_argument("--json", type=Path, help="write metadata, raw samples, and summaries")
    args = parser.parse_args()

    if args.iterations <= 0 or args.random_cases <= 0:
        parser.error("--iterations and --random-cases must be positive")
    if args.warmups < 1:
        parser.error("--warmups must be at least 1")
    if args.samples < 5:
        parser.error("--samples must be at least 5")

    root = Path(__file__).resolve().parents[1]
    specifications = args.case or [
        "before=solutions/02_optimization/contest_before.c",
        "optimized=submissions/02/contest.c",
    ]
    cases: list[tuple[str, Path]] = []
    seen_names: set[str] = set()
    for specification in specifications:
        if "=" not in specification:
            parser.error(f"invalid --case {specification!r}; expected NAME=SOURCE")
        name, source_text = specification.split("=", 1)
        source = Path(source_text)
        if not source.is_absolute():
            source = root / source
        name = name.strip()
        if not name or name in seen_names:
            parser.error(f"empty or duplicate case name: {name!r}")
        if not source.is_file():
            parser.error(f"source does not exist: {source}")
        seen_names.add(name)
        cases.append((name, source))
    if len(cases) < 2:
        parser.error("provide at least two cases so speedup can be measured")

    baseline = args.baseline or cases[0][0]
    if baseline not in seen_names:
        parser.error(f"unknown --baseline case: {baseline}")

    affinity: list[int] | None = None
    if hasattr(os, "sched_getaffinity"):
        available = sorted(os.sched_getaffinity(0))
        if args.cpu == "auto":
            os.sched_setaffinity(0, {available[0]})
        elif args.cpu != "none":
            try:
                selected_cpu = int(args.cpu)
            except ValueError:
                parser.error("--cpu must be an integer, 'auto', or 'none'")
            if selected_cpu not in available:
                parser.error(f"CPU {selected_cpu} is unavailable; choose one of {available}")
            os.sched_setaffinity(0, {selected_cpu})
        affinity = sorted(os.sched_getaffinity(0))
    elif args.cpu not in ("auto", "none"):
        parser.error("numeric --cpu requires sched_setaffinity support")

    cpu = platform.processor() or "unknown"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break

    compiler_version = subprocess.run(
        [args.compiler, "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()[0]
    flags = ["-O3", "-Wall", "-Wextra"]
    if args.native:
        flags.append("-march=native")

    print(f"host={platform.platform()}")
    print(f"cpu={cpu}")
    print(f"affinity={affinity if affinity is not None else 'unsupported'}")
    print(f"compiler={compiler_version}")
    print(f"cflags={shlex.join(flags)}")
    print("inner_timer=clock() from supplied contest harness")
    print("outer_timer=time.perf_counter_ns")
    print(f"iterations={args.iterations} warmups={args.warmups} samples={args.samples}")
    print("order=balanced cyclic rotations, then reversed rotations", flush=True)

    archive = root / "problems" / "2_암호구현.zip"
    internal_samples: dict[str, list[float]] = {name: [] for name, _ in cases}
    wall_samples: dict[str, list[float]] = {name: [] for name, _ in cases}
    source_hashes = {
        name: hashlib.sha256(source.read_bytes()).hexdigest() for name, source in cases
    }

    with tempfile.TemporaryDirectory(prefix="challenge02-repeat-") as directory:
        temporary = Path(directory)
        with ZipFile(archive) as zipped:
            vector1 = temporary / "testvector.txt"
            vector20 = temporary / "testvector_20round.txt"
            vector1.write_bytes(zipped.read("code/testvector.txt"))
            vector20.write_bytes(zipped.read("code/testvector_20round.txt"))

        oracle = temporary / "differential_oracle"
        oracle_compile = [
            args.compiler,
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            str(root / "solutions" / "solve_02_permutation.c"),
            "-o",
            str(oracle),
        ]
        print("$", shlex.join(oracle_compile), flush=True)
        subprocess.run(oracle_compile, check=True)
        oracle_run = [
            str(oracle),
            "--selftest",
            str(vector1),
            str(vector20),
            str(args.random_cases),
        ]
        print("$", shlex.join(oracle_run), flush=True)
        subprocess.run(oracle_run, check=True)

        executables: dict[str, Path] = {}
        for name, source in cases:
            rewritten, replacements = ITERATIONS_PATTERN.subn(
                f"const int iterations = {args.iterations};",
                source.read_text(),
            )
            if replacements != 1:
                raise RuntimeError(
                    f"expected exactly one timing iteration declaration in {source}, "
                    f"found {replacements}"
                )
            temporary_source = temporary / f"{name}.c"
            temporary_source.write_text(rewritten)
            executable = temporary / name
            command = [args.compiler, *flags, str(temporary_source), "-o", str(executable)]
            print("$", shlex.join(command), flush=True)
            subprocess.run(command, check=True)
            executables[name] = executable

        for warmup in range(args.warmups):
            shift = warmup % len(cases)
            order = cases[shift:] + cases[:shift]
            if (warmup // len(cases)) % 2:
                order = list(reversed(order))
            for name, _ in order:
                print(f"warmup={warmup + 1} case={name}", flush=True)
                completed = subprocess.run(
                    [str(executables[name])],
                    cwd=temporary,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                valid = (
                    completed.returncode == 0
                    and "one-round testvector verification: OK (1000 pairs checked)"
                    in completed.stdout
                    and "20-round testvector verification: OK" in completed.stdout
                    and TIMING_PATTERN.search(completed.stdout) is not None
                )
                if not valid:
                    parser.error(
                        f"warmup validation failed for {name} (exit {completed.returncode})\n"
                        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                    )

        for sample in range(args.samples):
            shift = sample % len(cases)
            order = cases[shift:] + cases[:shift]
            if (sample // len(cases)) % 2:
                order = list(reversed(order))
            for name, _ in order:
                start_ns = time.perf_counter_ns()
                completed = subprocess.run(
                    [str(executables[name])],
                    cwd=temporary,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                elapsed_s = (time.perf_counter_ns() - start_ns) / 1_000_000_000.0
                match = TIMING_PATTERN.search(completed.stdout)
                valid = (
                    completed.returncode == 0
                    and "one-round testvector verification: OK (1000 pairs checked)"
                    in completed.stdout
                    and "20-round testvector verification: OK" in completed.stdout
                    and match is not None
                )
                if not valid:
                    parser.error(
                        f"sample {sample + 1} validation failed for {name} "
                        f"(exit {completed.returncode})\nstdout:\n{completed.stdout}\n"
                        f"stderr:\n{completed.stderr}"
                    )
                assert match is not None
                internal_ns = float(match.group(1)) * 1_000.0
                internal_samples[name].append(internal_ns)
                wall_samples[name].append(elapsed_s)
                print(
                    f"sample={sample + 1} case={name} "
                    f"internal_ns={internal_ns:.3f} wall_s={elapsed_s:.6f}",
                    flush=True,
                )

    summaries: dict[str, dict[str, float | int]] = {}
    print("summary:")
    for case_index, (name, _) in enumerate(cases):
        values = internal_samples[name]
        median = statistics.median(values)
        deviations = [abs(value - median) for value in values]
        vingtiles = statistics.quantiles(values, n=20, method="inclusive")
        generator = random.Random(0x9E3779B97F4A7C15 + case_index)
        bootstrap = sorted(
            statistics.median(generator.choices(values, k=len(values)))
            for _ in range(5_000)
        )
        mad = statistics.median(deviations)
        summaries[name] = {
            "median_ns": median,
            "mad_ns": mad,
            "mad_percent": mad / median * 100.0,
            "p05_ns": vingtiles[0],
            "p25_ns": vingtiles[4],
            "p75_ns": vingtiles[14],
            "p95_ns": vingtiles[18],
            "min_ns": min(values),
            "max_ns": max(values),
            "bootstrap_median_ci95_low_ns": bootstrap[124],
            "bootstrap_median_ci95_high_ns": bootstrap[4_874],
            "outliers_beyond_3mad": (
                sum(abs(value - median) > 3.0 * mad for value in values) if mad else 0
            ),
        }
        summary = summaries[name]
        print(
            f"case={name} median_ns={summary['median_ns']:.3f} "
            f"mad_ns={summary['mad_ns']:.3f} "
            f"mad_percent={summary['mad_percent']:.2f} "
            f"p05_ns={summary['p05_ns']:.3f} p95_ns={summary['p95_ns']:.3f} "
            f"median_ci95={summary['bootstrap_median_ci95_low_ns']:.3f}.."
            f"{summary['bootstrap_median_ci95_high_ns']:.3f} "
            f"outliers_3mad={summary['outliers_beyond_3mad']}"
        )

    comparisons: dict[str, dict[str, float]] = {}
    baseline_values = internal_samples[baseline]
    for case_index, (name, _) in enumerate(cases):
        if name == baseline:
            continue
        paired = [
            baseline_ns / candidate_ns
            for baseline_ns, candidate_ns in zip(baseline_values, internal_samples[name])
        ]
        paired_median = statistics.median(paired)
        paired_mad = statistics.median(abs(value - paired_median) for value in paired)
        paired_vingtiles = statistics.quantiles(paired, n=20, method="inclusive")
        generator = random.Random(0xD1B54A32D192ED03 + case_index)
        bootstrap = sorted(
            statistics.median(generator.choices(paired, k=len(paired)))
            for _ in range(5_000)
        )
        comparisons[name] = {
            "ratio_of_medians": float(summaries[baseline]["median_ns"])
            / float(summaries[name]["median_ns"]),
            "paired_median": paired_median,
            "paired_mad": paired_mad,
            "paired_p05": paired_vingtiles[0],
            "paired_p95": paired_vingtiles[18],
            "paired_bootstrap_ci95_low": bootstrap[124],
            "paired_bootstrap_ci95_high": bootstrap[4_874],
        }
        comparison = comparisons[name]
        print(
            f"speedup baseline={baseline} candidate={name} "
            f"ratio_of_medians={comparison['ratio_of_medians']:.3f} "
            f"paired_median={comparison['paired_median']:.3f} "
            f"paired_mad={comparison['paired_mad']:.3f} "
            f"paired_p05={comparison['paired_p05']:.3f} "
            f"paired_p95={comparison['paired_p95']:.3f} "
            f"paired_ci95={comparison['paired_bootstrap_ci95_low']:.3f}.."
            f"{comparison['paired_bootstrap_ci95_high']:.3f}"
        )

    if args.json:
        report = {
            "schema_version": 1,
            "benchmark": "challenge02_contest_shaped",
            "environment": {
                "host": platform.platform(),
                "cpu": cpu,
                "affinity": affinity,
                "compiler": compiler_version,
                "flags": flags,
                "inner_timer": "clock()",
                "outer_timer": "time.perf_counter_ns",
            },
            "config": {
                "iterations": args.iterations,
                "official_iterations": 1_000_000,
                "warmups": args.warmups,
                "samples_per_case": args.samples,
                "order": "balanced-cyclic-reversed",
                "bootstrap_resamples": 5_000,
            },
            "baseline": baseline,
            "sources": {
                name: {"path": str(source.relative_to(root)), "sha256": source_hashes[name]}
                for name, source in cases
            },
            "internal_ns_per_20round": internal_samples,
            "outer_wall_seconds": wall_samples,
            "summaries": summaries,
            "comparisons": comparisons,
        }
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
