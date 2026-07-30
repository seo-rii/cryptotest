#!/usr/bin/env python3
"""Build, verify, and repeatedly benchmark challenge 2 optimization candidates."""

from __future__ import annotations

import argparse
import os
import platform
import random
import shlex
import statistics
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile


def cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def available_cpus() -> list[int]:
    if hasattr(os, "sched_getaffinity"):
        return sorted(os.sched_getaffinity(0))
    return []


def run(
    command: list[str],
    *,
    cpu: int | None = None,
    capture: bool = False,
    echo_output: bool = True,
) -> str:
    effective = command
    if cpu is not None:
        effective = ["taskset", "-c", str(cpu), *command]
    print("$", shlex.join(effective), flush=True)
    completed = subprocess.run(
        effective,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    if capture:
        if echo_output:
            print(completed.stdout, end="")
        return completed.stdout
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Correctness-test all problem 2 candidates, warm them up, then "
            "measure randomized-order repeated samples and report median/MAD."
        )
    )
    parser.add_argument("--compiler", default=os.environ.get("CC", "gcc"))
    parser.add_argument(
        "--profile",
        choices=("portable", "native"),
        default="native",
        help="native enables AVX2 when the host supports it",
    )
    parser.add_argument("--iterations", type=int, default=7_000_000)
    parser.add_argument("--warmup-iterations", type=int, default=30_000_000)
    parser.add_argument("--repeats", type=int, default=21)
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument(
        "--mode",
        choices=("isolated", "combined"),
        default="isolated",
        help=(
            "isolated builds one candidate per binary and interleaves 3-sample "
            "blocks; combined is faster but more sensitive to code layout"
        ),
    )
    parser.add_argument(
        "--cpu",
        default="auto",
        help="Linux CPU number, 'auto' for the first allowed CPU, or 'none'",
    )
    parser.add_argument(
        "--extra-cflag",
        action="append",
        default=[],
        help="additional compiler flag; may be repeated",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="optional path for a copy of metadata and benchmark output",
    )
    args = parser.parse_args()

    for name in ("iterations", "warmup_iterations", "random_cases"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.repeats < 3:
        parser.error("--repeats must be at least 3")

    cpus = available_cpus()
    if args.cpu == "auto":
        cpu = cpus[0] if cpus else None
    elif args.cpu == "none":
        cpu = None
    else:
        try:
            cpu = int(args.cpu)
        except ValueError:
            parser.error("--cpu must be an integer, 'auto', or 'none'")
        if cpus and cpu not in cpus:
            parser.error(f"CPU {cpu} is unavailable; allowed CPUs: {cpus}")

    directory = Path(__file__).resolve().parent
    repository = directory.parents[3]
    source = directory / "benchmark_candidates.c"
    archive = directory.parent / "2_암호구현.zip"

    compiler_version = subprocess.run(
        [args.compiler, "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()[0]
    flags = [
        "-O3",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Werror",
        "-DNDEBUG",
    ]
    if args.profile == "native":
        flags.append("-march=native")
    flags.extend(args.extra_cflag)

    metadata_lines = [
        f"host_os={platform.platform()}",
        f"cpu={cpu_model()}",
        f"available_cpus={','.join(map(str, cpus)) if cpus else 'unknown'}",
        f"pinned_cpu={cpu if cpu is not None else 'none'}",
        f"compiler={compiler_version}",
        f"profile={args.profile}",
        f"cflags={shlex.join(flags)}",
    ]
    print("\n".join(metadata_lines))

    captured_sections: list[str] = []
    with tempfile.TemporaryDirectory(prefix="cryptotest-p2-opt-") as temporary:
        build = Path(temporary)
        executable = build / "benchmark_candidates_all"
        with ZipFile(archive) as zipped:
            vector1 = build / "testvector.txt"
            vector20 = build / "testvector_20round.txt"
            vector1.write_bytes(zipped.read("code/testvector.txt"))
            vector20.write_bytes(zipped.read("code/testvector_20round.txt"))

        run(
            [args.compiler, *flags, str(source), "-lm", "-o", str(executable)],
            cpu=None,
        )
        selftest_output = run(
            [
                str(executable),
                "--selftest",
                str(vector1),
                str(vector20),
                str(args.random_cases),
            ],
            cpu=cpu,
            capture=True,
        )
        captured_sections.append(selftest_output)

        if args.mode == "combined":
            benchmark_output = run(
                [
                    str(executable),
                    "--benchmark",
                    str(args.iterations),
                    str(args.warmup_iterations),
                    str(args.repeats),
                ],
                cpu=cpu,
                capture=True,
            )
            captured_sections.append(benchmark_output)
        else:
            candidates = [
                (0, "current_submission"),
                (1, "register_loop"),
                (2, "paired_loop"),
                (3, "paired_loop_scalar"),
                (4, "paired_unrolled"),
                (5, "paired_unrolled_scalar"),
                (6, "paired_unrolled_bmi2"),
            ]
            if args.profile == "native":
                candidates.append((7, "avx2_single"))

            executables: dict[str, Path] = {}
            for identifier, name in candidates:
                candidate_executable = build / f"benchmark_02_{name}"
                run(
                    [
                        args.compiler,
                        *flags,
                        "-Wno-unused-function",
                        f"-DSELECT_CANDIDATE={identifier}",
                        str(source),
                        "-lm",
                        "-o",
                        str(candidate_executable),
                    ],
                    cpu=None,
                )
                executables[name] = candidate_executable

            block_sizes = [3] * (args.repeats // 3)
            remainder = args.repeats % 3
            if remainder:
                if block_sizes:
                    block_sizes[-1] += remainder
                else:
                    block_sizes = [args.repeats]
            samples: dict[str, list[float]] = {name: [] for _, name in candidates}
            generator = random.Random(0x243F6A8885A308D3)
            print("isolated_measurement=one_candidate_per_binary")
            print(f"isolated_blocks={','.join(map(str, block_sizes))}")
            print("isolated_sample,candidate,ns_per_20round")
            for block_index, block_repeats in enumerate(block_sizes, start=1):
                order = [name for _, name in candidates]
                generator.shuffle(order)
                for name in order:
                    output = run(
                        [
                            str(executables[name]),
                            "--benchmark",
                            str(args.iterations),
                            str(args.warmup_iterations),
                            str(block_repeats),
                        ],
                        cpu=cpu,
                        capture=True,
                        echo_output=False,
                    )
                    captured_sections.append(f"[{name} block={block_index}]\n{output}")
                    for line in output.splitlines():
                        fields = line.split(",")
                        if len(fields) == 3 and fields[0].isdigit() and fields[1] == name:
                            value = float(fields[2])
                            samples[name].append(value)
                            print(f"{len(samples[name])},{name},{value:.3f}")

            baseline = statistics.median(samples["current_submission"])
            register_baseline = statistics.median(samples["register_loop"])
            aggregate_lines = [
                "isolated_summary_candidate,median_ns,mad_ns,min_ns,max_ns,"
                "speedup_vs_submission,speedup_vs_register_loop"
            ]
            for _, name in candidates:
                values = samples[name]
                if len(values) != args.repeats:
                    raise RuntimeError(
                        f"parsed {len(values)} samples for {name}, expected {args.repeats}"
                    )
                median = statistics.median(values)
                mad = statistics.median(abs(value - median) for value in values)
                aggregate_lines.append(
                    f"{name},{median:.3f},{mad:.3f},{min(values):.3f},"
                    f"{max(values):.3f},{baseline / median:.4f},"
                    f"{register_baseline / median:.4f}"
                )
            aggregate = "\n".join(aggregate_lines) + "\n"
            print(aggregate, end="")
            captured_sections.append(aggregate)

    if args.output:
        args.output.write_text(
            "\n".join(metadata_lines)
            + "\n"
            + "\n".join(captured_sections),
            encoding="utf-8",
        )
        print(f"saved_output={args.output.resolve()}")


if __name__ == "__main__":
    main()
