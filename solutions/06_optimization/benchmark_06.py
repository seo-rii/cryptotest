#!/usr/bin/env python3
"""Warm-up and repeatedly benchmark challenge-6 solver variants.

Every invocation is treated as invalid unless it reproduces the telemetry
scalar, its labelled s2/s3 scan state, and predicted r3.  The reported wall
clock includes process startup and input loading, but excludes C++ build time.
Measurement order rotates each round to reduce fixed ordering bias.
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
    "r3": int("2443c8daf1a9d52b09", 16),
}
EXPECTED_SCANS = {
    "s2": {
        "state": int("638d9d631ab436da51e640", 16),
        "lift_low_bits": 21304,
    },
    "s3": {
        "state": int("948173253ad6d120a3f562", 16),
        "lift_low_bits": 15594,
    },
}
INHERITED_OPENMP_VARIABLES = (
    "GOMP_CPU_AFFINITY",
    "OMP_NUM_THREADS",
    "OMP_SCHEDULE",
    "OMP_THREAD_LIMIT",
)
OPENMP_ENVIRONMENT = {
    "OMP_DYNAMIC": "FALSE",
    "OMP_PROC_BIND": "SPREAD",
    "OMP_PLACES": "THREADS",
}


@dataclass(frozen=True)
class Contender:
    name: str
    family: str
    command: tuple[str, ...]


def benchmark_environment() -> tuple[dict[str, str], list[str]]:
    environment = os.environ.copy()
    removed = sorted(
        key for key in INHERITED_OPENMP_VARIABLES if key in environment
    )
    for key in removed:
        del environment[key]
    environment.update(OPENMP_ENVIRONMENT)
    return environment, removed


def cpu_availability() -> tuple[int, list[int] | None, int]:
    logical_cpus = os.cpu_count() or 1
    affinity = (
        sorted(os.sched_getaffinity(0))
        if hasattr(os, "sched_getaffinity")
        else None
    )
    available_cpus = len(affinity) if affinity is not None else logical_cpus
    return logical_cpus, affinity, available_cpus


def parse_integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RuntimeError(f"expected integer-compatible value, got {value!r}")
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
        result: dict[str, Any] = {
            "implementation": "baseline",
            "state_label": "s2",
            "p_equals_dq": True,
        }
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
    if not isinstance(result, dict):
        raise RuntimeError(f"expected a JSON object from {name}, got {result!r}")
    return result


def command_option(contender: Contender, option: str) -> str:
    try:
        index = contender.command.index(option)
        return contender.command[index + 1]
    except (ValueError, IndexError) as error:
        raise RuntimeError(
            f"{contender.name} command is missing {option}"
        ) from error


def validate_result(contender: Contender, result: dict[str, Any]) -> None:
    observed = {key: parse_integer(result.get(key)) for key in EXPECTED}
    if observed != EXPECTED:
        raise RuntimeError(
            f"{contender.name} failed known-answer validation: "
            f"observed={observed}, expected={EXPECTED}"
        )
    state_label = result.get("state_label")
    expected_label = "s3" if contender.family == "native" else "s2"
    if state_label != expected_label:
        raise RuntimeError(
            f"{contender.name} returned invalid state label: "
            f"{state_label!r} != {expected_label!r}"
        )
    expected_scan = EXPECTED_SCANS[expected_label]
    if parse_integer(result.get("state")) != expected_scan["state"]:
        raise RuntimeError(f"{contender.name} returned the wrong scan state")

    if contender.family == "baseline":
        if result.get("p_equals_dq") is not True:
            raise RuntimeError(f"{contender.name} failed P = dQ validation")
        return

    if parse_integer(result.get("lift_low_bits")) != expected_scan["lift_low_bits"]:
        raise RuntimeError(f"{contender.name} returned the wrong lift bits")

    if contender.family == "python":
        match = re.fullmatch(
            r"python-(int|gmpy2)(?:-(analytic|recurrence))?",
            contender.name,
        )
        if match is None:
            raise RuntimeError(f"invalid Python contender name: {contender.name}")
        backend = match.group(1)
        strategy = match.group(2) or "analytic"
        if result.get("implementation") != f"python-{backend}-{strategy}":
            raise RuntimeError(
                f"{contender.name} returned the wrong implementation metadata"
            )
        if result.get("backdoor_relation") != "P = dQ":
            raise RuntimeError(f"{contender.name} failed P = dQ validation")
        required_stages = (
            "telemetry_seconds",
            "state_seconds",
            "total_seconds",
        )
    elif contender.family == "gmp":
        threads = int(command_option(contender, "--threads"))
        strategy = command_option(contender, "--telemetry")
        required = {
            "implementation": f"cpp-gmp-omp-{threads}-{strategy}",
            "p_equals_dq": True,
            "threads": threads,
            "threads_actual": threads,
            "telemetry_strategy": strategy,
            "lift_residue_test": "sqrt",
        }
        for key, expected in required.items():
            observed_metadata = result.get(key)
            if (
                (
                    isinstance(expected, bool)
                    and not isinstance(observed_metadata, bool)
                )
                or (
                    isinstance(expected, int)
                    and not isinstance(expected, bool)
                    and (
                        isinstance(observed_metadata, bool)
                        or not isinstance(observed_metadata, int)
                    )
                )
                or observed_metadata != expected
            ):
                raise RuntimeError(
                    f"{contender.name} metadata mismatch for {key}: "
                    f"{observed_metadata!r} != {expected!r}"
                )
        required_stages = (
            "telemetry_seconds",
            "state_seconds",
            "total_seconds",
        )
    elif contender.family == "native":
        threads = int(command_option(contender, "--threads"))
        schedule = command_option(contender, "--schedule")
        effective_schedule = (
            "block"
            if schedule == "adaptive" and threads <= 2
            else ("scalar" if schedule == "adaptive" else schedule)
        )
        requested_block_size = int(command_option(contender, "--block-size"))
        effective_block_size = (
            32
            if schedule == "adaptive" and threads == 2
            else requested_block_size
        )
        required = {
            "implementation": (
                "cpp-native-montgomery-binary-window4-"
                f"{effective_schedule}-{threads}"
            ),
            "p_equals_dq": True,
            "threads": threads,
            "threads_actual": threads,
            "schedule_requested": schedule,
            "schedule_effective": effective_schedule,
            "block_size_requested": requested_block_size,
            "block_size": effective_block_size,
            "inverse_method": command_option(contender, "--inverse"),
            "sqrt_method": command_option(contender, "--sqrt"),
            "telemetry_strategy": "analytic",
            "scan_curve_model": "isomorphic-a-minus-3",
            "d_multiplication": "hamburg-co-z",
            "lift_residue_test": "binary-jacobi-deferred-sqrt",
            "fixed_window_bits": 8,
            "fixed_digit_encoding": "unsigned",
            "fixed_multiplication": "candidate-jacobian",
            "lift_output_index": 1,
            "filter_output_index": 2,
        }
        for key, expected in required.items():
            observed_metadata = result.get(key)
            if (
                (
                    isinstance(expected, bool)
                    and not isinstance(observed_metadata, bool)
                )
                or (
                    isinstance(expected, int)
                    and not isinstance(expected, bool)
                    and (
                        isinstance(observed_metadata, bool)
                        or not isinstance(observed_metadata, int)
                    )
                )
                or observed_metadata != expected
            ):
                raise RuntimeError(
                    f"{contender.name} metadata mismatch for {key}: "
                    f"{observed_metadata!r} != {expected!r}"
                )
        if result.get("field_backend") not in {
            "bmi2-adx",
            "portable-u128-unrolled",
        }:
            raise RuntimeError(
                f"{contender.name} returned an invalid field backend"
            )
        candidates_started = result.get("candidates_started")
        if (
            isinstance(candidates_started, bool)
            or not isinstance(candidates_started, int)
            or candidates_started < expected_scan["lift_low_bits"] + 1
            or candidates_started > (1 << 16)
        ):
            raise RuntimeError(
                f"{contender.name} returned invalid candidates_started: "
                f"{candidates_started!r}"
            )
        required_stages = (
            "telemetry_seconds",
            "precompute_seconds",
            "scan_seconds",
            "state_seconds",
            "total_seconds",
        )
    else:
        raise RuntimeError(f"unknown contender family: {contender.family}")

    for key in required_stages:
        value = result.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            raise RuntimeError(
                f"{contender.name} returned invalid {key}: {value!r}"
            )
    total = float(result["total_seconds"])
    parts = float(result["telemetry_seconds"]) + float(result["state_seconds"])
    if not math.isclose(total, parts, rel_tol=1e-5, abs_tol=1e-6):
        raise RuntimeError(
            f"{contender.name} internal total is inconsistent with stages"
        )
    if contender.family == "native":
        state = float(result["state_seconds"])
        state_parts = (
            float(result["precompute_seconds"])
            + float(result["scan_seconds"])
        )
        residual = state - state_parts
        if residual < -1e-6 or residual > max(1e-3, state * 0.01):
            raise RuntimeError(
                f"{contender.name} internal state time is inconsistent with stages"
            )


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
    validate_result(contender, result)
    if (
        "total_seconds" in result
        and elapsed + 1e-6 < float(result["total_seconds"])
    ):
        raise RuntimeError(f"{contender.name} external time is below internal time")
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
    if not math.isfinite(args.timeout) or args.timeout <= 0.0:
        parser.error("timeout must be finite and positive")

    directory = Path(__file__).resolve().parent
    names = [name.strip() for name in args.implementations.split(",") if name.strip()]
    if not names or len(set(names)) != len(names):
        parser.error("implementations must be a nonempty list without duplicates")
    logical_cpus, affinity, available_cpus = cpu_availability()
    families: dict[str, str] = {}
    resolved_threads: dict[str, int] = {}
    for name in names:
        thread_text: str | None = None
        if name == "baseline":
            families[name] = "baseline"
        elif re.fullmatch(
            r"python-(int|gmpy2)(?:-(analytic|recurrence))?", name
        ):
            families[name] = "python"
        elif match := re.fullmatch(
            r"cpp-(auto|[1-9][0-9]*)(?:-(analytic|recurrence))?", name
        ):
            families[name] = "gmp"
            thread_text = match.group(1)
        elif match := re.fullmatch(
            r"native-(auto|[1-9][0-9]*)"
            r"(?:-(adaptive|block|scalar|static))?",
            name,
        ):
            families[name] = "native"
            thread_text = match.group(1)
        else:
            parser.error(f"unknown implementation: {name}")
        if thread_text is not None:
            threads = (
                available_cpus if thread_text == "auto" else int(thread_text)
            )
            if threads > available_cpus:
                parser.error(
                    f"thread count in {name} exceeds the {available_cpus} "
                    "CPUs in the current affinity mask"
                )
            resolved_threads[name] = threads

    compiler = shutil.which(args.compiler)
    needs_gmp = "gmp" in families.values()
    needs_native = "native" in families.values()
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

        environment, removed_openmp_variables = benchmark_environment()
        repository_root = directory.parents[1]
        git_commit: str | None = None
        git_dirty: bool | None = None
        git_executable = shutil.which("git")
        if git_executable is not None:
            commit_process = subprocess.run(
                [git_executable, "rev-parse", "HEAD"],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )
            status_process = subprocess.run(
                [
                    git_executable,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=normal",
                ],
                cwd=repository_root,
                check=False,
                capture_output=True,
                text=True,
            )
            if commit_process.returncode == 0:
                git_commit = commit_process.stdout.strip()
            if status_process.returncode == 0:
                git_dirty = bool(status_process.stdout)
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
                "field_boundary_pairs": 64,
                "point_vectors": 256,
                "hamburg_lift_vectors": 128,
            }:
                raise RuntimeError(f"unexpected native self-test result: {native_self_test}")

        contenders: list[Contender] = []
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
                strategy = match.group(2) or "analytic"
                threads = resolved_threads[name]
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
                schedule = match.group(2) or "adaptive"
                threads = resolved_threads[name]
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
                raise AssertionError(f"unvalidated implementation: {name}")
            contenders.append(Contender(name, families[name], command))

        print(
            f"environment: {cpu_model()}, logical_cpus={logical_cpus}, "
            f"available_cpus={available_cpus}, affinity={affinity}, "
            f"Python {platform.python_version()}"
        )
        if compiler is not None and needs_cpp:
            print(f"compiler: {compiler_version(compiler)}")
        print(
            f"protocol: warmup={args.warmup}, repetitions={args.repetitions}, "
            "cyclic/reversed interleaving, external wall clock, "
            "known-answer check every run",
            flush=True,
        )
        if native_self_test is not None:
            print(
                "native preflight: 2000 random + 64 boundary field pairs, "
                "256 point/table vectors, and 128 Hamburg/NAF lift vectors "
                "verified",
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
        metadata: dict[str, dict[str, Any]] = {}
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
                sample_metadata = {
                    key: result[key]
                    for key in (
                        "implementation",
                        "state_label",
                        "lift_output_index",
                        "filter_output_index",
                        "field_backend",
                        "scan_curve_model",
                        "d_multiplication",
                        "lift_residue_test",
                        "fixed_window_bits",
                        "fixed_digit_encoding",
                        "fixed_multiplication",
                        "schedule_requested",
                        "schedule_effective",
                        "block_size_requested",
                        "block_size",
                        "threads",
                        "threads_actual",
                        "inverse_method",
                        "sqrt_method",
                        "telemetry_strategy",
                        "backdoor_relation",
                        "p_equals_dq",
                    )
                    if key in result
                }
                previous_metadata = metadata.get(contender.name)
                if (
                    previous_metadata is not None
                    and sample_metadata != previous_metadata
                ):
                    raise RuntimeError(
                        f"{contender.name} metadata changed between samples"
                    )
                metadata[contender.name] = sample_metadata
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
            print(
                "\nsame-repetition diagnostic speedup "
                "(not adjacent pairs, vs baseline)"
            )
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
                "available_cpus": available_cpus,
                "affinity": affinity,
                "platform": platform.platform(),
                "python": platform.python_version(),
                "compiler": compiler_version(compiler) if compiler and needs_cpp else None,
                "git_commit": git_commit,
                "git_dirty": git_dirty,
            },
            "protocol": {
                "warmup": args.warmup,
                "repetitions": args.repetitions,
                "clock": "time.perf_counter external wall time",
                "ordering": "cyclic rotations, then reversed rotations",
                "comparison_scope": (
                    "broad screening; repetition-index ratios are not "
                    "adjacent AB/BA pairs"
                ),
                "validation": {key: hex(value) for key, value in EXPECTED.items()},
                "cpp_build_commands": build_commands,
                "native_self_test": native_self_test,
                "openmp_environment": {
                    key: environment[key]
                    for key in ("OMP_DYNAMIC", "OMP_PROC_BIND", "OMP_PLACES")
                },
                "removed_inherited_openmp_variables": (
                    removed_openmp_variables
                ),
            },
            "metadata": metadata,
            "raw_seconds": samples,
            "summary": summaries,
            "diagnostic_same_repetition_speedup_vs_baseline": (
                paired_comparisons
            ),
            "internal_stage_summary": internal_summaries,
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            print(f"wrote JSON report: {args.output}")


if __name__ == "__main__":
    main()
