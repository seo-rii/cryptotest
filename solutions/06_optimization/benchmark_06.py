#!/usr/bin/env python3
"""Warm-up and repeatedly benchmark challenge-6 solver variants.

Every invocation is treated as invalid unless it reproduces all three known
values: the telemetry scalar, recovered state, and predicted r3.  The reported
wall clock includes process startup and input loading, but excludes C++ build
time.  Measurement order rotates each round to reduce fixed ordering bias.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXPECTED = {
    "d": int("1c3cdd6b221806db0a7b28", 16),
    "state": int("638d9d631ab436da51e640", 16),
    "r3": int("2443c8daf1a9d52b09", 16),
}


@dataclass(frozen=True)
class Contender:
    name: str
    command: tuple[str, ...]


def parse_integer(value: Any) -> int:
    if isinstance(value, int):
        return value
    return int(value, 0)


def parse_result(name: str, stdout: str) -> dict[str, Any]:
    if name == "baseline":
        if "P == d*Q: True" not in stdout:
            raise RuntimeError(f"baseline did not verify P = dQ: {stdout!r}")
        patterns = {
            "d": r"backdoor scalar d = (0x[0-9a-f]+)",
            "state": r"recovered state s1 = (0x[0-9a-f]+)",
            "r3": r"predicted r3 = (0x[0-9a-f]+)",
        }
        result: dict[str, Any] = {"implementation": "baseline"}
        for key, pattern in patterns.items():
            match = re.search(pattern, stdout)
            if match is None:
                raise RuntimeError(f"could not parse {key} from baseline output: {stdout!r}")
            result[key] = int(match.group(1), 16)
        return result

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"invalid JSON from {name}: {stdout!r}") from error
    return result


def run_once(
    contender: Contender, timeout: float, environment: dict[str, str]
) -> tuple[float, dict[str, Any]]:
    started = time.perf_counter()
    process = subprocess.run(
        contender.command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
    )
    elapsed = time.perf_counter() - started
    if process.returncode != 0:
        raise RuntimeError(
            f"{contender.name} exited {process.returncode}:\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    result = parse_result(contender.name, process.stdout)
    observed = {key: parse_integer(result[key]) for key in EXPECTED}
    if observed != EXPECTED:
        raise RuntimeError(
            f"{contender.name} failed known-answer validation: "
            f"observed={observed}, expected={EXPECTED}"
        )
    if contender.name != "baseline" and result.get("state_label") != "s2":
        raise RuntimeError(f"{contender.name} did not label the recovered state as s2")
    if "p_equals_dq" in result and result["p_equals_dq"] is not True:
        raise RuntimeError(f"{contender.name} failed P = dQ validation")
    return elapsed, result


def percentile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = fraction * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def summarize(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    median = statistics.median(ordered)
    deviations = [abs(value - median) for value in ordered]
    mad = statistics.median(deviations)
    return {
        "samples": len(values),
        "median_seconds": median,
        "mean_seconds": statistics.fmean(values),
        "stdev_seconds": statistics.stdev(values) if len(values) > 1 else 0.0,
        "mad_seconds": mad,
        "mad_percent": mad / median * 100.0,
        "min_seconds": ordered[0],
        "p05_seconds": percentile(ordered, 0.05),
        "p95_seconds": percentile(ordered, 0.95),
        "max_seconds": ordered[-1],
    }


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def compiler_version(compiler: str) -> str:
    output = subprocess.run(
        [compiler, "--version"], check=True, capture_output=True, text=True
    ).stdout
    return output.splitlines()[0]


def compile_cpp(
    source: Path,
    destination: Path,
    compiler: str,
    libraries: tuple[str, ...] = (),
) -> tuple[str, ...]:
    command = (
        compiler,
        "-O3",
        "-DNDEBUG",
        "-march=native",
        "-std=c++20",
        "-fopenmp",
        str(source),
        *libraries,
        "-o",
        str(destination),
    )
    process = subprocess.run(command, check=False, capture_output=True, text=True)
    if process.returncode != 0:
        raise RuntimeError(
            f"C++ build failed:\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--implementations",
        default=(
            "baseline,python-int-analytic,python-gmpy2-analytic,"
            "cpp-1-analytic,cpp-auto-analytic,"
            "native-1-adaptive,native-auto-adaptive"
        ),
        help=(
            "comma-separated baseline, python-{int,gmpy2}-{analytic,recurrence}, "
            "cpp-{N,auto}-{analytic,recurrence}, or "
            "native-{N,auto}-{adaptive,block,scalar,static}"
        ),
    )
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.warmup < 1 or args.repetitions < 5:
        parser.error("warmup must be positive and repetitions must be at least 5")

    directory = Path(__file__).resolve().parent
    names = [name.strip() for name in args.implementations.split(",") if name.strip()]
    if not names or len(set(names)) != len(names):
        parser.error("implementations must be a nonempty list without duplicates")

    compiler = shutil.which(args.compiler)
    needs_gmp = any(name.startswith("cpp-") for name in names)
    needs_native = any(name.startswith("native-") for name in names)
    needs_cpp = needs_gmp or needs_native
    if needs_cpp and compiler is None:
        parser.error(f"compiler not found: {args.compiler}")

    with tempfile.TemporaryDirectory(prefix="bench06-") as temporary:
        gmp_binary = Path(temporary) / "solve_06_gmp"
        native_binary = Path(temporary) / "deep_native_06"
        build_commands: dict[str, list[str]] = {}
        if needs_gmp:
            assert compiler is not None
            build_commands["gmp"] = list(
                compile_cpp(
                    directory / "solve_06_gmp.cpp",
                    gmp_binary,
                    compiler,
                    ("-lgmpxx", "-lgmp"),
                )
            )
        native_self_test: dict[str, Any] | None = None
        if needs_native:
            assert compiler is not None
            build_commands["native"] = list(
                compile_cpp(
                    directory / "deep_native_06.cpp", native_binary, compiler
                )
            )

        environment = os.environ.copy()
        environment.update(
            {
                "OMP_DYNAMIC": "FALSE",
                "OMP_PROC_BIND": "SPREAD",
                "OMP_PLACES": "THREADS",
            }
        )
        if needs_native:
            self_test = subprocess.run(
                (str(native_binary), "--self-test", "--json"),
                check=False,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                env=environment,
            )
            if self_test.returncode != 0:
                raise RuntimeError(
                    "native self-test failed:\n"
                    f"stdout:\n{self_test.stdout}\nstderr:\n{self_test.stderr}"
                )
            native_self_test = json.loads(self_test.stdout)
            if native_self_test != {
                "self_test": True,
                "field_vectors": 2000,
                "point_vectors": 256,
            }:
                raise RuntimeError(f"unexpected native self-test result: {native_self_test}")

        contenders: list[Contender] = []
        logical_cpus = os.cpu_count() or 1
        for name in names:
            if name == "baseline":
                command = (sys.executable, str(directory / "solve_06_baseline.py"))
            elif match := re.fullmatch(
                r"python-(int|gmpy2)(?:-(analytic|recurrence))?", name
            ):
                backend = match.group(1)
                strategy = match.group(2) or "analytic"
                command = (
                    sys.executable,
                    str(directory.parent / "solve_06_prng.py"),
                    "--backend",
                    backend,
                    "--telemetry",
                    strategy,
                    "--json",
                )
            elif match := re.fullmatch(
                r"cpp-(auto|[1-9][0-9]*)(?:-(analytic|recurrence))?", name
            ):
                thread_text = match.group(1)
                strategy = match.group(2) or "analytic"
                threads = logical_cpus if thread_text == "auto" else int(thread_text)
                if threads < 1:
                    parser.error(f"invalid thread count in {name}")
                command = (
                    str(gmp_binary),
                    "--threads",
                    str(threads),
                    "--telemetry",
                    strategy,
                    "--json",
                )
            elif match := re.fullmatch(
                r"native-(auto|[1-9][0-9]*)"
                r"(?:-(adaptive|block|scalar|static))?",
                name,
            ):
                thread_text = match.group(1)
                schedule = match.group(2) or "adaptive"
                threads = logical_cpus if thread_text == "auto" else int(thread_text)
                command = (
                    str(native_binary),
                    "--threads",
                    str(threads),
                    "--schedule",
                    schedule,
                    "--block-size",
                    "64",
                    "--inverse",
                    "binary",
                    "--sqrt",
                    "window4",
                    "--json",
                )
            else:
                parser.error(f"unknown implementation: {name}")
            contenders.append(Contender(name, command))

        print(
            f"environment: {cpu_model()}, logical_cpus={logical_cpus}, "
            f"Python {platform.python_version()}"
        )
        if compiler is not None and needs_cpp:
            print(f"compiler: {compiler_version(compiler)}")
        print(
            f"protocol: warmup={args.warmup}, repetitions={args.repetitions}, "
            "balanced cyclic/reversed order, external wall clock, "
            "known-answer check every run",
            flush=True,
        )
        if native_self_test is not None:
            print(
                "native preflight: 2000 field vectors and 256 point/table "
                "vectors verified",
                flush=True,
            )

        for contender in contenders:
            for index in range(args.warmup):
                elapsed, _result = run_once(contender, args.timeout, environment)
                print(
                    f"warmup {index + 1}/{args.warmup} {contender.name}: "
                    f"{elapsed:.6f}s [verified]",
                    flush=True,
                )

        samples: dict[str, list[float]] = {item.name: [] for item in contenders}
        internal_samples: dict[str, dict[str, list[float]]] = {
            item.name: {
                "telemetry_seconds": [],
                "precompute_seconds": [],
                "scan_seconds": [],
                "state_seconds": [],
                "total_seconds": [],
            }
            for item in contenders
        }
        for repetition in range(args.repetitions):
            offset = repetition % len(contenders)
            measurement_order = contenders[offset:] + contenders[:offset]
            if (repetition // len(contenders)) % 2:
                measurement_order = list(reversed(measurement_order))
            for contender in measurement_order:
                elapsed, result = run_once(contender, args.timeout, environment)
                samples[contender.name].append(elapsed)
                for key in internal_samples[contender.name]:
                    if key in result:
                        internal_samples[contender.name][key].append(float(result[key]))
                print(
                    f"measure {repetition + 1}/{args.repetitions} {contender.name}: "
                    f"{elapsed:.6f}s [verified]",
                    flush=True,
                )

        summaries = {name: summarize(values) for name, values in samples.items()}
        internal_summaries: dict[str, dict[str, dict[str, float | int]]] = {}
        for name, stages in internal_samples.items():
            present = {stage: summarize(values) for stage, values in stages.items() if values}
            if present:
                internal_summaries[name] = present

        baseline_median = summaries.get("baseline", {}).get("median_seconds")
        if baseline_median is not None:
            for summary in summaries.values():
                summary["speedup_vs_baseline"] = (
                    float(baseline_median) / float(summary["median_seconds"])
                )

        paired_comparisons: dict[str, dict[str, float]] = {}
        if "baseline" in samples:
            for name, values in samples.items():
                if name == "baseline":
                    continue
                paired = [
                    baseline_elapsed / candidate_elapsed
                    for baseline_elapsed, candidate_elapsed in zip(samples["baseline"], values)
                ]
                ordered = sorted(paired)
                paired_median = statistics.median(ordered)
                paired_comparisons[name] = {
                    "median": paired_median,
                    "mad": statistics.median(
                        abs(value - paired_median) for value in ordered
                    ),
                    "p05": percentile(ordered, 0.05),
                    "p95": percentile(ordered, 0.95),
                    "min": ordered[0],
                    "max": ordered[-1],
                }

        print("\nsummary (external end-to-end wall clock)")
        for name in names:
            summary = summaries[name]
            speedup = summary.get("speedup_vs_baseline")
            suffix = f", speedup={speedup:.2f}x" if speedup is not None else ""
            print(
                f"{name:14s} median={summary['median_seconds']:.6f}s, "
                f"mean={summary['mean_seconds']:.6f}s, "
                f"stdev={summary['stdev_seconds']:.6f}s, "
                f"MAD={summary['mad_seconds']:.6f}s "
                f"({summary['mad_percent']:.2f}%), "
                f"min={summary['min_seconds']:.6f}s, "
                f"p05={summary['p05_seconds']:.6f}s, "
                f"p95={summary['p95_seconds']:.6f}s, "
                f"max={summary['max_seconds']:.6f}s{suffix}"
            )

        if paired_comparisons:
            print("\npaired speedup (same measurement round vs baseline)")
            for name, comparison in paired_comparisons.items():
                print(
                    f"{name:14s} median={comparison['median']:.2f}x, "
                    f"MAD={comparison['mad']:.2f}x, "
                    f"p05={comparison['p05']:.2f}x, "
                    f"p95={comparison['p95']:.2f}x"
                )

        report = {
            "schema": 1,
            "environment": {
                "cpu": cpu_model(),
                "logical_cpus": logical_cpus,
                "platform": platform.platform(),
                "python": platform.python_version(),
                "compiler": compiler_version(compiler) if compiler and needs_cpp else None,
            },
            "protocol": {
                "warmup": args.warmup,
                "repetitions": args.repetitions,
                "clock": "time.perf_counter external wall time",
                "ordering": "balanced cyclic rotations, then reversed rotations",
                "validation": {key: hex(value) for key, value in EXPECTED.items()},
                "cpp_build_commands": build_commands,
                "native_self_test": native_self_test,
                "openmp_environment": {
                    key: environment[key]
                    for key in ("OMP_DYNAMIC", "OMP_PROC_BIND", "OMP_PLACES")
                },
            },
            "raw_seconds": samples,
            "summary": summaries,
            "paired_speedup_vs_baseline": paired_comparisons,
            "internal_stage_summary": internal_summaries,
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            print(f"wrote JSON report: {args.output}")


if __name__ == "__main__":
    main()
