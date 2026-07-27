#!/usr/bin/env python3
"""Repeated, verified benchmark for challenge-6 GMP and native-field solvers.

Build time and the native randomized self-test are outside the timed region.
Each timed sample is a fresh complete process, follows at least one discarded
warm-up, and must reproduce d, its labelled s2/s3 scan state, r3, P=dQ, and
the corresponding lift bits.
"""

from __future__ import annotations

import argparse
import hashlib
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
        "lift_output_index": 0,
        "filter_output_index": 1,
    },
    "s3": {
        "state": int("948173253ad6d120a3f562", 16),
        "lift_low_bits": 15594,
        "lift_output_index": 1,
        "filter_output_index": 2,
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
    threads: int
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


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def compiler_version(compiler: str) -> str:
    process = subprocess.run(
        [compiler, "--version"], check=True, capture_output=True, text=True
    )
    return process.stdout.splitlines()[0]


def compile_source(
    compiler: str,
    source: Path,
    output: Path,
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
        str(output),
    )
    process = subprocess.run(command, check=False, capture_output=True, text=True)
    if process.returncode != 0:
        raise RuntimeError(
            f"build failed for {source.name}:\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return command


def parse_integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RuntimeError(f"expected integer-compatible value, got {value!r}")
    if isinstance(value, int):
        return value
    return int(value, 0)


def command_option(contender: Contender, option: str) -> str:
    try:
        index = contender.command.index(option)
        return contender.command[index + 1]
    except (ValueError, IndexError) as error:
        raise RuntimeError(
            f"{contender.name} command is missing {option}"
        ) from error


def validate_result(contender: Contender, stdout: str) -> dict[str, Any]:
    if contender.family == "python-original":
        if "P == d*Q: True" not in stdout:
            raise RuntimeError("original Python solver failed P=dQ validation")
        patterns = {
            "d": r"backdoor scalar d = (0x[0-9a-f]+)",
            "state": r"recovered state s1 = (0x[0-9a-f]+)",
            "r3": r"predicted r3 = (0x[0-9a-f]+)",
        }
        result: dict[str, Any] = {
            "implementation": "python-original",
            "state_label": "s2",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, stdout)
            if match is None:
                raise RuntimeError(
                    f"could not parse {key} from original Python output"
                )
            result[key] = int(match.group(1), 16)
            expected = (
                EXPECTED_SCANS["s2"]["state"]
                if key == "state"
                else EXPECTED[key]
            )
            if result[key] != expected:
                raise RuntimeError(
                    f"original Python {key} mismatch: "
                    f"observed={result[key]:#x}, expected={expected:#x}"
                )
        return result

    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"{contender.name} returned invalid JSON: {stdout!r}"
        ) from error
    if not isinstance(result, dict):
        raise RuntimeError(
            f"{contender.name} returned a non-object JSON result: {result!r}"
        )
    observed = {key: parse_integer(result.get(key)) for key in EXPECTED}
    if observed != EXPECTED:
        raise RuntimeError(
            f"{contender.name} known-answer mismatch: "
            f"observed={observed}, expected={EXPECTED}"
        )
    state_label = result.get("state_label")
    expected_label = "s2" if contender.family == "gmp" else "s3"
    if state_label != expected_label:
        raise RuntimeError(
            f"{contender.name} returned invalid state label: "
            f"{state_label!r} != {expected_label!r}"
        )
    expected_scan = EXPECTED_SCANS[state_label]
    for key in ("state", "lift_low_bits"):
        observed_value = parse_integer(result[key])
        if observed_value != expected_scan[key]:
            raise RuntimeError(
                f"{contender.name} scan mismatch for {key}: "
                f"{observed_value:#x} != {expected_scan[key]:#x}"
            )
    if contender.family != "gmp":
        for key in ("lift_output_index", "filter_output_index"):
            observed_index = result.get(key)
            if (
                isinstance(observed_index, bool)
                or not isinstance(observed_index, int)
                or observed_index != expected_scan[key]
            ):
                raise RuntimeError(
                    f"{contender.name} scan metadata mismatch for {key}"
                )
    if result.get("p_equals_dq") is not True:
        raise RuntimeError(f"{contender.name} failed P=dQ validation")
    expected_threads = contender.threads
    for key in ("threads", "threads_actual"):
        observed_threads = result.get(key)
        if (
            isinstance(observed_threads, bool)
            or not isinstance(observed_threads, int)
            or observed_threads != expected_threads
        ):
            raise RuntimeError(
                f"{contender.name} returned the wrong thread count for {key}"
            )
    if contender.family == "gmp":
        strategy = command_option(contender, "--telemetry")
        expected_metadata: dict[str, Any] = {
            "implementation": f"cpp-gmp-omp-{expected_threads}-{strategy}",
            "telemetry_strategy": strategy,
            "lift_residue_test": "sqrt",
        }
        required_stages = (
            "telemetry_seconds",
            "state_seconds",
            "total_seconds",
        )
    else:
        requested_schedule = command_option(contender, "--schedule")
        effective_schedule = (
            "block"
            if requested_schedule == "adaptive" and expected_threads <= 2
            else (
                "scalar"
                if requested_schedule == "adaptive"
                else requested_schedule
            )
        )
        requested_block_size = int(command_option(contender, "--block-size"))
        effective_block_size = (
            32
            if requested_schedule == "adaptive" and expected_threads == 2
            else requested_block_size
        )
        expected_metadata = {
            "implementation": (
                f"cpp-native-montgomery-"
                f"{command_option(contender, '--inverse')}-"
                f"{command_option(contender, '--sqrt')}-"
                f"{effective_schedule}-{expected_threads}"
            ),
            "schedule_requested": command_option(contender, "--schedule"),
            "schedule_effective": effective_schedule,
            "block_size_requested": requested_block_size,
            "block_size": effective_block_size,
            "inverse_method": command_option(contender, "--inverse"),
            "sqrt_method": command_option(contender, "--sqrt"),
            "telemetry_strategy": "analytic",
            "scan_curve_model": "isomorphic-a-minus-3",
            "d_multiplication": "hamburg-co-z",
            "lift_residue_test": (
                "montgomery-residue-hybrid-u128-u64-"
                "euclidean-jacobi-deferred-sqrt"
            ),
            "subgroup_membership_test": (
                "cofactor-5-frobenius-tate-trace-prac-20-generic"
            ),
            "subgroup_constant_layout": "constexpr-montgomery",
            "subgroup_batch_layout": "direct-in-place-fraction",
            "subgroup_trace_formula": "degree-5-reciprocal-polynomial",
            "subgroup_lucas_bit_scan": "variable-u128-shift",
            "subgroup_lucas_step": "fixed-prac-schedule",
            "scan_buffer_initialization": "write-before-read",
            "curve_constant_layout": "constexpr-montgomery",
            "fixed_window_bits": 8,
            "fixed_digit_encoding": "unsigned",
            "fixed_multiplication": "candidate-jacobian",
        }
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
            or candidates_started < int(expected_scan["lift_low_bits"]) + 1
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
    for key, expected in expected_metadata.items():
        observed_metadata = result.get(key)
        if (
            (
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
    if contender.family != "gmp":
        state_seconds = float(result["state_seconds"])
        state_parts = (
            float(result["precompute_seconds"])
            + float(result["scan_seconds"])
        )
        residual = state_seconds - state_parts
        if residual < -1e-6 or residual > max(1e-3, state_seconds * 0.01):
            raise RuntimeError(
                f"{contender.name} internal state time is inconsistent with stages"
            )
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
    result = validate_result(contender, process.stdout)
    if (
        "total_seconds" in result
        and elapsed + 1e-6 < float(result["total_seconds"])
    ):
        raise RuntimeError(f"{contender.name} external time is below internal time")
    return elapsed, result


def percentile(ordered: list[float], fraction: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


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
        "mad_percent": 100.0 * mad / median,
        "min_seconds": ordered[0],
        "p05_seconds": percentile(ordered, 0.05),
        "p95_seconds": percentile(ordered, 0.95),
        "max_seconds": ordered[-1],
    }


def parse_positive_csv(text: str, label: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in text.split(",") if item.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{label} must be comma-separated integers") from error
    if not values or any(value < 1 for value in values) or len(set(values)) != len(values):
        raise argparse.ArgumentTypeError(
            f"{label} must be unique positive comma-separated integers"
        )
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--threads", default="1,8")
    parser.add_argument(
        "--native-schedules",
        default="block,scalar",
        help="comma-separated adaptive, block, scalar, and/or static",
    )
    parser.add_argument(
        "--native-inverses",
        default="binary",
        help="comma-separated binary and/or fermat",
    )
    parser.add_argument(
        "--native-sqrts",
        default="window4",
        help="comma-separated window4 and/or binary",
    )
    parser.add_argument("--block-size", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument(
        "--include-original-python",
        action="store_true",
        help="include the slow unmodified Python attack in the same rounds",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.warmup < 1 or args.repetitions < 5:
        parser.error("warmup must be positive and repetitions must be at least 5")
    if not math.isfinite(args.timeout) or args.timeout <= 0.0:
        parser.error("timeout must be finite and positive")
    if not 1 <= args.block_size <= 256:
        parser.error("block size must be in 1..256")
    try:
        thread_counts = parse_positive_csv(args.threads, "threads")
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    schedules = [
        item.strip() for item in args.native_schedules.split(",") if item.strip()
    ]
    if (
        not schedules
        or len(set(schedules)) != len(schedules)
        or any(
            schedule not in {"adaptive", "block", "scalar", "static"}
            for schedule in schedules
        )
    ):
        parser.error(
            "native schedules must be unique values from adaptive,block,scalar,static"
        )
    inverses = [
        item.strip() for item in args.native_inverses.split(",") if item.strip()
    ]
    if (
        not inverses
        or len(set(inverses)) != len(inverses)
        or any(inverse not in {"binary", "fermat"} for inverse in inverses)
    ):
        parser.error("native inverses must be unique values from binary,fermat")
    square_roots = [
        item.strip() for item in args.native_sqrts.split(",") if item.strip()
    ]
    if (
        not square_roots
        or len(set(square_roots)) != len(square_roots)
        or any(square_root not in {"window4", "binary"} for square_root in square_roots)
    ):
        parser.error("native square roots must be unique values from window4,binary")

    compiler = shutil.which(args.compiler)
    if compiler is None:
        parser.error(f"compiler not found: {args.compiler}")
    directory = Path(__file__).resolve().parent
    repository_root = directory.parents[1]
    native_source = directory / "deep_native_06.cpp"
    gmp_source = directory / "solve_06_gmp.cpp"
    runner_path = Path(__file__).resolve()
    source_hashes = {
        "native": hashlib.sha256(native_source.read_bytes()).hexdigest(),
        "gmp": hashlib.sha256(gmp_source.read_bytes()).hexdigest(),
        "runner": hashlib.sha256(runner_path.read_bytes()).hexdigest(),
    }
    logical_cpus, affinity, available_cpus = cpu_availability()
    if any(threads > available_cpus for threads in thread_counts):
        parser.error(
            f"requested thread count exceeds the {available_cpus} CPUs in the "
            "current affinity mask"
        )
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
            [git_executable, "status", "--porcelain=v1", "--untracked-files=normal"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if commit_process.returncode == 0:
            git_commit = commit_process.stdout.strip()
        if status_process.returncode == 0:
            git_dirty = bool(status_process.stdout)
    environment, removed_openmp_variables = benchmark_environment()

    with tempfile.TemporaryDirectory(prefix="deep-bench06-") as temporary_text:
        temporary = Path(temporary_text)
        native_binary = temporary / "deep_native_06"
        gmp_binary = temporary / "solve_06_gmp"
        native_build = compile_source(
            compiler, native_source, native_binary
        )
        gmp_build = compile_source(
            compiler,
            gmp_source,
            gmp_binary,
            ("-lgmpxx", "-lgmp"),
        )

        self_test = subprocess.run(
            [str(native_binary), "--self-test", "--json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            env=environment,
        )
        expected_self_test = {
            "self_test": True,
            "field_vectors": 2000,
            "field_boundary_pairs": 64,
            "point_vectors": 256,
            "hamburg_lift_vectors": 128,
            "subgroup_lift_vectors": 128,
        }
        if (
            self_test.returncode != 0
            or json.loads(self_test.stdout) != expected_self_test
        ):
            raise RuntimeError(
                "native field self-test failed:\n"
                f"stdout:\n{self_test.stdout}\nstderr:\n{self_test.stderr}"
            )

        contenders: list[Contender] = []
        if args.include_original_python:
            contenders.append(
                Contender(
                    "python-original",
                    "python-original",
                    0,
                    (sys.executable, str(directory / "solve_06_baseline.py")),
                )
            )
        for threads in thread_counts:
            contenders.append(
                Contender(
                    f"gmp-{threads}t",
                    "gmp",
                    threads,
                    (
                        str(gmp_binary),
                        "--threads",
                        str(threads),
                        "--telemetry",
                        "analytic",
                        "--json",
                    ),
                )
            )
            for inverse in inverses:
                for square_root in square_roots:
                    for schedule in schedules:
                        name = (
                            f"native-{inverse}-{square_root}-{schedule}-{threads}t"
                        )
                        contenders.append(
                            Contender(
                                name,
                                f"native-{inverse}-{square_root}-{schedule}",
                                threads,
                                (
                                    str(native_binary),
                                    "--threads",
                                    str(threads),
                                    "--inverse",
                                    inverse,
                                    "--sqrt",
                                    square_root,
                                    "--schedule",
                                    schedule,
                                    "--block-size",
                                    str(args.block_size),
                                    "--json",
                                ),
                            )
                        )

        print(
            f"environment: {cpu_model()}, logical_cpus={logical_cpus}, "
            f"available_cpus={available_cpus}, affinity={affinity}, "
            f"Python {platform.python_version()}"
        )
        print(f"compiler: {compiler_version(compiler)}")
        print(
            f"protocol: warmup={args.warmup}, repetitions={args.repetitions}, "
            "fresh process, cyclic/reversed interleaving, external wall clock, "
            "known-answer check every sample, native 2000 random + 64 boundary "
            "field pairs, 256 point/table, and 128 Hamburg/NAF + subgroup "
            "lift vector self-test passed",
            flush=True,
        )

        for contender in contenders:
            for index in range(args.warmup):
                elapsed, _ = run_once(contender, args.timeout, environment)
                print(
                    f"warmup {index + 1}/{args.warmup} {contender.name}: "
                    f"{elapsed:.6f}s [verified/discarded]",
                    flush=True,
                )

        raw: dict[str, list[float]] = {item.name: [] for item in contenders}
        stage_names = (
            "telemetry_seconds",
            "precompute_seconds",
            "scan_seconds",
            "state_seconds",
            "total_seconds",
        )
        internal: dict[str, dict[str, list[float]]] = {
            item.name: {stage: [] for stage in stage_names} for item in contenders
        }
        work_counts: dict[str, list[int]] = {
            item.name: [] for item in contenders
        }
        metadata: dict[str, dict[str, Any]] = {}
        for repetition in range(args.repetitions):
            offset = repetition % len(contenders)
            order = contenders[offset:] + contenders[:offset]
            if (repetition // len(contenders)) % 2:
                order = list(reversed(order))
            for contender in order:
                elapsed, result = run_once(contender, args.timeout, environment)
                raw[contender.name].append(elapsed)
                for stage in stage_names:
                    if stage in result:
                        internal[contender.name][stage].append(float(result[stage]))
                if "candidates_started" in result:
                    work_counts[contender.name].append(
                        int(result["candidates_started"])
                    )
                sample_metadata = {
                    key: result[key]
                    for key in (
                        "implementation",
                        "field_bytes",
                        "jacobian_bytes",
                        "fixed_table_bytes",
                        "fixed_window_bits",
                        "field_backend",
                        "scan_curve_model",
                        "d_multiplication",
                        "schedule_requested",
                        "schedule_effective",
                        "block_size_requested",
                        "block_size",
                        "threads",
                        "threads_actual",
                        "inverse_method",
                        "sqrt_method",
                        "telemetry_strategy",
                        "lift_residue_test",
                        "subgroup_membership_test",
                        "subgroup_constant_layout",
                        "subgroup_batch_layout",
                        "subgroup_trace_formula",
                        "subgroup_lucas_bit_scan",
                        "subgroup_lucas_step",
                        "scan_buffer_initialization",
                        "curve_constant_layout",
                        "fixed_digit_encoding",
                        "fixed_multiplication",
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
                    f"measure {repetition + 1}/{args.repetitions} "
                    f"{contender.name}: {elapsed:.6f}s [verified]",
                    flush=True,
                )

        summary = {name: summarize(samples) for name, samples in raw.items()}
        stage_summary = {
            name: {
                stage: summarize(samples)
                for stage, samples in stages.items()
                if samples
            }
            for name, stages in internal.items()
        }
        same_repetition_vs_gmp: dict[str, dict[str, float | int]] = {}
        for contender in contenders:
            if not contender.family.startswith("native-"):
                continue
            baseline_name = f"gmp-{contender.threads}t"
            ratios = [
                baseline / candidate
                for baseline, candidate in zip(
                    raw[baseline_name], raw[contender.name], strict=True
                )
            ]
            ratio_summary = summarize(ratios)
            same_repetition_vs_gmp[contender.name] = ratio_summary
            summary[contender.name]["ratio_of_medians_vs_same_thread_gmp"] = (
                float(summary[baseline_name]["median_seconds"])
                / float(summary[contender.name]["median_seconds"])
            )

        same_repetition_vs_original: dict[str, dict[str, float | int]] = {}
        if "python-original" in raw:
            original_median = float(
                summary["python-original"]["median_seconds"]
            )
            for contender in contenders:
                if not contender.family.startswith("native-"):
                    continue
                ratios = [
                    baseline / candidate
                    for baseline, candidate in zip(
                        raw["python-original"], raw[contender.name], strict=True
                    )
                ]
                same_repetition_vs_original[contender.name] = summarize(ratios)
                summary[contender.name]["ratio_of_medians_vs_original_python"] = (
                    original_median
                    / float(summary[contender.name]["median_seconds"])
                )

        print("\nsummary (external end-to-end wall clock)")
        for contender in contenders:
            item = summary[contender.name]
            speedup = item.get("ratio_of_medians_vs_same_thread_gmp")
            suffix = f", vs GMP={speedup:.2f}x" if speedup is not None else ""
            original_speedup = item.get("ratio_of_medians_vs_original_python")
            if original_speedup is not None:
                suffix += f", vs original Python={original_speedup:.2f}x"
            print(
                f"{contender.name:24s} median={item['median_seconds']:.6f}s, "
                f"MAD={item['mad_seconds']:.6f}s ({item['mad_percent']:.2f}%), "
                f"p05={item['p05_seconds']:.6f}s, "
                f"p95={item['p95_seconds']:.6f}s{suffix}"
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
                "compiler": compiler_version(compiler),
                "git_commit": git_commit,
                "git_dirty": git_dirty,
                "openmp_environment": {
                    key: environment[key]
                    for key in ("OMP_DYNAMIC", "OMP_PROC_BIND", "OMP_PLACES")
                },
                "removed_inherited_openmp_variables": (
                    removed_openmp_variables
                ),
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
                "fresh_process_per_sample": True,
                "build_excluded": True,
                "native_self_test_excluded": True,
                "native_self_test": expected_self_test,
                "validation": {key: hex(value) for key, value in EXPECTED.items()},
                "scan_validation": {
                    label: {
                        key: hex(value) if key in {"state", "lift_low_bits"} else value
                        for key, value in expected.items()
                    }
                    for label, expected in EXPECTED_SCANS.items()
                },
                "native_build": list(native_build),
                "gmp_build": list(gmp_build),
                "source_sha256": source_hashes,
                "block_size": args.block_size,
            },
            "metadata": metadata,
            "raw_seconds": raw,
            "internal_raw_seconds": internal,
            "raw_candidates_started": work_counts,
            "summary": summary,
            "internal_stage_summary": stage_summary,
            "diagnostic_same_repetition_speedup_vs_same_thread_gmp": (
                same_repetition_vs_gmp
            ),
            "diagnostic_same_repetition_speedup_vs_original_python": (
                same_repetition_vs_original
            ),
        }
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"wrote JSON report: {args.output}")


if __name__ == "__main__":
    main()
