#!/usr/bin/env python3
"""Promote small challenge-6 native optimizations with adjacent AB/BA pairs.

The broad benchmark matrix is useful for screening large effects.  This runner
instead compares exactly two builds from the same source, pins both to the same
CPU set, validates every result, and places the two fresh processes adjacent in
balanced AB/BA pairs.  A candidate is promotion-eligible only when its paired
median exceeds 1.02x, the deterministic bootstrap interval excludes parity,
both order strata favor it, and four fixed chronological blocks are stable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import resource
import shutil
import statistics
import subprocess
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
BOOTSTRAP_RESAMPLES = 5_000
BLOCK_COUNT = 4
MAX_ABSOLUTE_BLOCK_SPREAD = 0.05
MAX_EFFECT_BLOCK_SPREAD = 0.02
INTERFERING_OPENMP_ENV = (
    "GOMP_CPU_AFFINITY",
    "OMP_NUM_THREADS",
    "OMP_SCHEDULE",
    "OMP_THREAD_LIMIT",
)
CONFIGURATION_KEYS = (
    "field_backend",
    "scan_curve_model",
    "d_multiplication",
    "lift_residue_test",
    "fixed_window_bits",
    "fixed_digit_encoding",
    "fixed_multiplication",
    "inverse_method",
    "sqrt_method",
    "telemetry_strategy",
)


@dataclass(frozen=True)
class Variant:
    label: str
    binary: Path
    defines: tuple[str, ...]


def define_values(defines: tuple[str, ...]) -> dict[str, str | None]:
    values: dict[str, str | None] = {}
    for item in defines:
        name, separator, value = item.partition("=")
        values[name] = value if separator else None
    return values


def expected_configuration(
    variant: Variant, native_bmi2_adx: bool
) -> dict[str, Any]:
    defines = define_values(variant.defines)
    expected: dict[str, Any] = {
        "state_label": (
            "s2" if "CH6_LEGACY_R0_SCAN" in defines else "s3"
        ),
        "scan_curve_model": (
            "original-generic-a"
            if "CH6_ORIGINAL_CURVE_SCAN" in defines
            else "isomorphic-a-minus-3"
        ),
        "d_multiplication": (
            "width-2-naf"
            if "CH6_NAF_D_MULTIPLICATION" in defines
            else "hamburg-co-z"
        ),
        "lift_residue_test": (
            (
                "subtractive-jacobi-deferred-sqrt"
                if "CH6_SUBTRACTIVE_JACOBI" in defines
                else "binary-jacobi-deferred-sqrt"
            )
            if (
                "CH6_SQRT_LIFT" not in defines
                and "CH6_NAF_D_MULTIPLICATION" not in defines
            )
            else "sqrt"
        ),
        "fixed_window_bits": int(
            defines.get("CH6_FIXED_WINDOW_BITS") or "8", 0
        ),
        "fixed_digit_encoding": (
            "balanced-signed"
            if "CH6_SIGNED_FIXED_TABLE" in defines
            else "unsigned"
        ),
        "fixed_multiplication": (
            "row-batched-affine"
            if "CH6_ROW_BATCHED_FIXED_MUL" in defines
            else "candidate-jacobian"
        ),
    }
    if "CH6_GENERIC_MONTGOMERY" in defines:
        expected["field_backend"] = "generic-carry-loop"
    elif "CH6_PORTABLE_ARITHMETIC" in defines:
        expected["field_backend"] = "portable-u128-unrolled"
    elif native_bmi2_adx:
        expected["field_backend"] = "bmi2-adx"
    else:
        expected["field_backend"] = "portable-u128-unrolled"
    return expected


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise RuntimeError(f"expected integer-compatible value, got {value!r}")
    return value if isinstance(value, int) else int(value, 0)


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def bootstrap_median_ci(
    values: list[float], seed: int
) -> tuple[float, float]:
    generator = random.Random(seed)
    samples = sorted(
        statistics.median(generator.choices(values, k=len(values)))
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    return samples[124], samples[4_874]


def stratified_bootstrap_median_ci(
    values: list[float], orders: list[str], seed: int
) -> tuple[float, float]:
    if len(values) != len(orders) or len(values) % BLOCK_COUNT:
        raise RuntimeError("invalid samples for block/order-stratified bootstrap")
    block_size = len(values) // BLOCK_COUNT
    strata: dict[tuple[int, str], list[float]] = {}
    for index, (value, order) in enumerate(zip(values, orders, strict=True)):
        strata.setdefault((index // block_size, order), []).append(value)
    expected_size = block_size // 2
    if (
        len(strata) != BLOCK_COUNT * 2
        or any(len(items) != expected_size for items in strata.values())
    ):
        raise RuntimeError("pair schedule does not balance order within each block")
    generator = random.Random(seed)
    medians: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [
            value
            for items in strata.values()
            for value in generator.choices(items, k=len(items))
        ]
        medians.append(statistics.median(sample))
    medians.sort()
    return medians[124], medians[4_874]


def summarize(values: list[float], seed: int) -> dict[str, float | int]:
    if not values or any(not math.isfinite(value) or value <= 0 for value in values):
        raise RuntimeError("timing samples must be finite and positive")
    median = statistics.median(values)
    low, high = bootstrap_median_ci(values, seed)
    return {
        "samples": len(values),
        "median": median,
        "mad": statistics.median(abs(value - median) for value in values),
        "p05": percentile(values, 0.05),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
        "bootstrap_median_ci95_low": low,
        "bootstrap_median_ci95_high": high,
    }


def parse_cpu_list(text: str) -> set[int]:
    cpus: set[int] = set()
    for group in text.split(","):
        group = group.strip()
        if not group:
            continue
        if "-" in group:
            start_text, stop_text = group.split("-", 1)
            start, stop = int(start_text), int(stop_text)
            if start > stop:
                raise ValueError(f"invalid CPU range: {group}")
            cpus.update(range(start, stop + 1))
        else:
            cpus.add(int(group))
    if not cpus or min(cpus) < 0:
        raise ValueError("CPU list must contain nonnegative indices")
    return cpus


def compiler_version(compiler: str) -> str:
    process = subprocess.run(
        [compiler, "--version"], check=True, capture_output=True, text=True
    )
    return process.stdout.splitlines()[0]


def compiler_predefines(compiler: str) -> set[str]:
    process = subprocess.run(
        (compiler, "-march=native", "-dM", "-E", "-x", "c++", "-"),
        input="",
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"could not query compiler predefines:\n{process.stderr}"
        )
    return {
        parts[1]
        for line in process.stdout.splitlines()
        if len(parts := line.split(maxsplit=2)) >= 2
        and parts[0] == "#define"
    }


def cpu_model_and_flags() -> tuple[str, list[str]]:
    model = platform.processor() or "unknown"
    flags: list[str] = []
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip().lower()
            if key == "model name":
                model = value.strip()
            elif key == "flags" and not flags:
                flags = value.split()
            if model != "unknown" and flags:
                break
    except OSError:
        pass
    return model, flags


def cpu_topology(cpus: set[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    topology_root = Path("/sys/devices/system/cpu")
    for cpu in sorted(cpus):
        row: dict[str, Any] = {"cpu": cpu}
        for output_key, filename in (
            ("package", "physical_package_id"),
            ("core", "core_id"),
            ("thread_siblings", "thread_siblings_list"),
        ):
            path = topology_root / f"cpu{cpu}" / "topology" / filename
            try:
                text = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            row[output_key] = (
                int(text) if output_key != "thread_siblings" else text
            )
        rows.append(row)
    return rows


def build_variant(
    compiler: str, source: Path, variant: Variant
) -> tuple[str, ...]:
    command = (
        compiler,
        "-O3",
        "-DNDEBUG",
        "-march=native",
        "-std=c++20",
        "-fopenmp",
        *(f"-D{item}" for item in variant.defines),
        str(source),
        "-o",
        str(variant.binary),
    )
    process = subprocess.run(command, check=False, capture_output=True, text=True)
    if process.returncode != 0:
        raise RuntimeError(
            f"{variant.label} build failed:\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return command


def validate_result(
    variant: Variant, stdout: str, threads: int, block_size: int,
    schedule: str, native_bmi2_adx: bool,
) -> dict[str, Any]:
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"{variant.label} returned invalid JSON: {stdout!r}"
        ) from error
    if not isinstance(result, dict):
        raise RuntimeError(
            f"{variant.label} returned a non-object JSON result: {result!r}"
        )
    observed = {key: parse_integer(result.get(key)) for key in EXPECTED}
    if observed != EXPECTED:
        raise RuntimeError(
            f"{variant.label} known-answer mismatch: "
            f"observed={observed}, expected={EXPECTED}"
        )
    state_label = result.get("state_label")
    if state_label not in EXPECTED_SCANS:
        raise RuntimeError(
            f"{variant.label} returned invalid state label: {state_label!r}"
        )
    configuration = expected_configuration(variant, native_bmi2_adx)
    for key, expected in configuration.items():
        observed_value = result.get(key)
        if (
            (
                isinstance(expected, bool)
                and not isinstance(observed_value, bool)
            )
            or (
                isinstance(expected, int)
                and not isinstance(expected, bool)
                and (
                    isinstance(observed_value, bool)
                    or not isinstance(observed_value, int)
                )
            )
            or observed_value != expected
        ):
            raise RuntimeError(
                f"{variant.label} configuration mismatch for {key}: "
                f"{observed_value!r} != {expected!r}"
            )
    expected_scan = EXPECTED_SCANS[state_label]
    for key, expected in expected_scan.items():
        observed_value = parse_integer(result.get(key))
        if observed_value != expected:
            raise RuntimeError(
                f"{variant.label} scan mismatch for {key}: "
                f"{observed_value!r} != {expected!r}"
            )
    effective_schedule = (
        "block"
        if schedule == "adaptive" and threads <= 2
        else ("scalar" if schedule == "adaptive" else schedule)
    )
    effective_block_size = (
        32 if schedule == "adaptive" and threads == 2 else block_size
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
        "block_size_requested": block_size,
        "block_size": effective_block_size,
        "inverse_method": "binary",
        "sqrt_method": "window4",
        "telemetry_strategy": "analytic",
    }
    for key, expected in required.items():
        observed_value = result.get(key)
        if (
            (
                isinstance(expected, bool)
                and not isinstance(observed_value, bool)
            )
            or (
                isinstance(expected, int)
                and not isinstance(expected, bool)
                and (
                    isinstance(observed_value, bool)
                    or not isinstance(observed_value, int)
                )
            )
            or observed_value != expected
        ):
            raise RuntimeError(
                f"{variant.label} metadata mismatch for {key}: "
                f"{observed_value!r} != {expected!r}"
            )
    for key in (
        "telemetry_seconds",
        "precompute_seconds",
        "scan_seconds",
        "state_seconds",
        "total_seconds",
    ):
        value = result.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise RuntimeError(
                f"{variant.label} returned invalid {key}: {value!r}"
            )
    total = float(result["total_seconds"])
    parts = float(result["telemetry_seconds"]) + float(result["state_seconds"])
    if not math.isclose(total, parts, rel_tol=1e-5, abs_tol=1e-6):
        raise RuntimeError(
            f"{variant.label} internal total is inconsistent with stages"
        )
    state_parts = (
        float(result["precompute_seconds"]) + float(result["scan_seconds"])
    )
    state_seconds = float(result["state_seconds"])
    stage_residual = state_seconds - state_parts
    if (
        stage_residual < -1e-6
        or stage_residual > max(1e-3, state_seconds * 0.01)
    ):
        raise RuntimeError(
            f"{variant.label} internal state time is inconsistent with stages"
        )
    candidates_started = result.get("candidates_started")
    if (
        isinstance(candidates_started, bool)
        or not isinstance(candidates_started, int)
        or candidates_started < int(expected_scan["lift_low_bits"]) + 1
        or candidates_started > (1 << 16)
    ):
        raise RuntimeError(
            f"{variant.label} returned invalid candidates_started: "
            f"{candidates_started!r}"
        )
    return result


def run_once(
    variant: Variant,
    command: tuple[str, ...],
    timeout: float,
    environment: dict[str, str],
    cpus: set[int],
    threads: int,
    block_size: int,
    schedule: str,
    native_bmi2_adx: bool,
) -> dict[str, Any]:
    usage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started_ns = time.time_ns()
    started = time.perf_counter()
    process = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
        preexec_fn=lambda: os.sched_setaffinity(0, cpus),
    )
    elapsed = time.perf_counter() - started
    ended_ns = time.time_ns()
    usage_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    if process.returncode != 0:
        raise RuntimeError(
            f"{variant.label} exited {process.returncode}:\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    result = validate_result(
        variant, process.stdout, threads, block_size, schedule,
        native_bmi2_adx
    )
    if elapsed + 1e-6 < float(result["total_seconds"]):
        raise RuntimeError(f"{variant.label} external time is below internal time")
    child_cpu = (
        usage_after.ru_utime
        + usage_after.ru_stime
        - usage_before.ru_utime
        - usage_before.ru_stime
    )
    return {
        "label": variant.label,
        "started_unix_ns": started_ns,
        "ended_unix_ns": ended_ns,
        "external_seconds": elapsed,
        "child_cpu_seconds": child_cpu,
        "normalized_cpu_coverage": child_cpu / (elapsed * threads),
        "internal": {
            key: result[key]
            for key in (
                "telemetry_seconds",
                "precompute_seconds",
                "scan_seconds",
                "state_seconds",
                "total_seconds",
                "candidates_started",
            )
        },
        "configuration": {
            key: result[key] for key in CONFIGURATION_KEYS
        },
    }


def pair_orders(pair_count: int, seed: int) -> list[str]:
    if pair_count < 40 or pair_count % (BLOCK_COUNT * 2):
        raise ValueError("pair count must be at least 40 and a multiple of 8")
    orders: list[str] = []
    generator = random.Random(seed)
    for _ in range(BLOCK_COUNT):
        block_size = pair_count // BLOCK_COUNT
        block = ["AB"] * (block_size // 2) + ["BA"] * (block_size // 2)
        generator.shuffle(block)
        orders.extend(block)
    if len(orders) != pair_count:
        raise AssertionError("balanced pair-order construction lost samples")
    return orders


def stationarity(
    baseline: list[float],
    candidate: list[float],
    ratios: list[float],
) -> dict[str, Any]:
    block_ranges = [
        (index * len(ratios) // BLOCK_COUNT, (index + 1) * len(ratios) // BLOCK_COUNT)
        for index in range(BLOCK_COUNT)
    ]
    baseline_blocks = [
        statistics.median(baseline[start:stop]) for start, stop in block_ranges
    ]
    candidate_blocks = [
        statistics.median(candidate[start:stop]) for start, stop in block_ranges
    ]
    ratio_blocks = [
        statistics.median(ratios[start:stop]) for start, stop in block_ranges
    ]
    baseline_spread = max(baseline_blocks) / min(baseline_blocks) - 1
    candidate_spread = max(candidate_blocks) / min(candidate_blocks) - 1
    effect_spread = max(ratio_blocks) / min(ratio_blocks) - 1
    reasons: list[str] = []
    if baseline_spread > MAX_ABSOLUTE_BLOCK_SPREAD:
        reasons.append("baseline absolute block spread exceeds 5%")
    if candidate_spread > MAX_ABSOLUTE_BLOCK_SPREAD:
        reasons.append("candidate absolute block spread exceeds 5%")
    if effect_spread > MAX_EFFECT_BLOCK_SPREAD:
        reasons.append("paired-effect block spread exceeds 2%")
    if min(ratio_blocks) < 0.995 and max(ratio_blocks) > 1.005:
        reasons.append("paired effect changes sign beyond the 0.5% margin")
    return {
        "method": "four-fixed-contiguous-block-medians",
        "block_ranges": [
            {"start": start, "stop": stop} for start, stop in block_ranges
        ],
        "baseline_block_medians": baseline_blocks,
        "candidate_block_medians": candidate_blocks,
        "paired_ratio_block_medians": ratio_blocks,
        "baseline_max_to_min_minus_one": baseline_spread,
        "candidate_max_to_min_minus_one": candidate_spread,
        "effect_max_to_min_minus_one": effect_spread,
        "status": "PASS" if not reasons else "FAIL",
        "eligibility": "eligible" if not reasons else "diagnostic-only",
        "reasons": reasons,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--baseline-label", default="incumbent")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--baseline-define", action="append", default=[])
    parser.add_argument("--candidate-define", action="append", default=[])
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--cpus")
    parser.add_argument("--block-size", type=int, default=64)
    parser.add_argument("--baseline-block-size", type=int)
    parser.add_argument("--candidate-block-size", type=int)
    parser.add_argument(
        "--baseline-schedule",
        choices=("adaptive", "block", "scalar", "static"),
        default="adaptive",
    )
    parser.add_argument(
        "--candidate-schedule",
        choices=("adaptive", "block", "scalar", "static"),
        default="adaptive",
    )
    parser.add_argument("--warmup-pairs", type=int, default=2)
    parser.add_argument("--pairs", type=int, default=40)
    parser.add_argument("--seed", type=int, default=0x06C0FFEE)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--null-calibration",
        action="store_true",
        help="allow an intentionally identical A/A pair to calibrate the protocol",
    )
    args = parser.parse_args()

    directory = Path(__file__).resolve().parent
    source = (args.source or directory / "deep_native_06.cpp").resolve()
    compiler = shutil.which(args.compiler)
    if compiler is None:
        parser.error(f"compiler not found: {args.compiler}")
    predefines = compiler_predefines(compiler)
    native_bmi2_adx = {
        "__x86_64__",
        "__BMI2__",
        "__ADX__",
    } <= predefines
    if not source.is_file():
        parser.error(f"source not found: {source}")
    block_sizes = {
        "A": (
            args.baseline_block_size
            if args.baseline_block_size is not None
            else args.block_size
        ),
        "B": (
            args.candidate_block_size
            if args.candidate_block_size is not None
            else args.block_size
        ),
    }
    schedules = {
        "A": args.baseline_schedule,
        "B": args.candidate_schedule,
    }
    if args.threads < 1 or any(
        not 1 <= block_size <= 256 for block_size in block_sizes.values()
    ):
        parser.error("threads must be positive and block size must be in 1..256")
    if args.warmup_pairs < 1:
        parser.error("warmup pairs must be positive")
    if (
        tuple(args.baseline_define) == tuple(args.candidate_define)
        and block_sizes["A"] == block_sizes["B"]
        and schedules["A"] == schedules["B"]
        and not args.null_calibration
    ):
        parser.error(
            "baseline and candidate have the same effective build/runtime "
            "configuration; use --null-calibration for an intentional A/A run"
        )
    try:
        orders = pair_orders(args.pairs, args.seed)
    except ValueError as error:
        parser.error(str(error))

    allowed_cpus = os.sched_getaffinity(0)
    try:
        chosen_cpus = (
            parse_cpu_list(args.cpus)
            if args.cpus
            else set(sorted(allowed_cpus)[: args.threads])
        )
    except ValueError as error:
        parser.error(str(error))
    if not chosen_cpus <= allowed_cpus:
        parser.error(
            f"chosen CPUs {sorted(chosen_cpus)} are outside allowed mask "
            f"{sorted(allowed_cpus)}"
        )
    if len(chosen_cpus) != args.threads:
        parser.error("chosen CPU count must equal the OpenMP thread count")

    environment = os.environ.copy()
    cleared_openmp = {
        key: environment.pop(key)
        for key in INTERFERING_OPENMP_ENV
        if key in environment
    }
    environment.update(
        {
            "OMP_DYNAMIC": "FALSE",
            "OMP_PROC_BIND": "SPREAD",
            "OMP_PLACES": "THREADS",
        }
    )
    cpu_model, cpu_flags = cpu_model_and_flags()
    runner_path = Path(__file__).resolve()
    runner_hash = sha256(runner_path)
    repository_root = runner_path.parents[2]
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
    preserved_source = (
        args.output.resolve().with_name(args.output.name + ".source.cpp")
        if args.output
        else None
    )

    with tempfile.TemporaryDirectory(prefix="ch6-promotion-") as temporary_text:
        temporary = Path(temporary_text)
        source_snapshot = temporary / source.name
        shutil.copyfile(source, source_snapshot)
        source_hash = sha256(source_snapshot)
        baseline = Variant(
            args.baseline_label,
            temporary / "baseline",
            tuple(args.baseline_define),
        )
        candidate = Variant(
            args.candidate_label,
            temporary / "candidate",
            tuple(args.candidate_define),
        )
        variants = {"A": baseline, "B": candidate}
        build_commands = {
            "A": build_variant(compiler, source_snapshot, baseline),
            "B": build_variant(compiler, source_snapshot, candidate),
        }
        binary_hashes = {key: sha256(item.binary) for key, item in variants.items()}
        if (
            block_sizes["A"] == block_sizes["B"]
            and schedules["A"] == schedules["B"]
            and binary_hashes["A"] == binary_hashes["B"]
            and not args.null_calibration
        ):
            raise RuntimeError(
                "baseline and candidate produced identical binaries; "
                "the requested ablation is not active"
            )

        for variant in variants.values():
            self_test = subprocess.run(
                (str(variant.binary), "--self-test", "--json"),
                check=False,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                env=environment,
                preexec_fn=lambda: os.sched_setaffinity(0, chosen_cpus),
            )
            if self_test.returncode != 0:
                raise RuntimeError(
                    f"{variant.label} self-test failed:\n{self_test.stderr}"
                )
            expected_self_test = {
                "self_test": True,
                "field_vectors": 2000,
                "field_boundary_pairs": 64,
                "point_vectors": 256,
                "hamburg_lift_vectors": 128,
            }
            if json.loads(self_test.stdout) != expected_self_test:
                raise RuntimeError(
                    f"{variant.label} returned unexpected self-test metadata"
                )

        commands = {
            key: (
                str(variant.binary),
                "--threads",
                str(args.threads),
                "--schedule",
                schedules[key],
                "--block-size",
                str(block_sizes[key]),
                "--inverse",
                "binary",
                "--sqrt",
                "window4",
                "--json",
            )
            for key, variant in variants.items()
        }
        print(
            f"environment: {platform.platform()}, cpu={cpu_model}, "
            f"allowed={sorted(allowed_cpus)}, "
            f"chosen={sorted(chosen_cpus)}, threads={args.threads}"
        )
        print(f"compiler: {compiler_version(compiler)}")
        print(
            f"protocol: warmup_pairs={args.warmup_pairs}, pairs={args.pairs}, "
            "adjacent balanced AB/BA, fresh process, known-answer check every sample"
        )

        for index in range(args.warmup_pairs):
            order = "AB" if index % 2 == 0 else "BA"
            for key in order:
                event = run_once(
                    variants[key],
                    commands[key],
                    args.timeout,
                    environment,
                    chosen_cpus,
                    args.threads,
                    block_sizes[key],
                    schedules[key],
                    native_bmi2_adx,
                )
                print(
                    f"warmup {index + 1}/{args.warmup_pairs} "
                    f"{variants[key].label}: "
                    f"{event['external_seconds']:.6f}s [verified/discarded]",
                    flush=True,
                )

        events: list[dict[str, Any]] = []
        baseline_times: list[float] = []
        candidate_times: list[float] = []
        ratios: list[float] = []
        strata: dict[str, list[float]] = {"AB": [], "BA": []}
        for pair_index, order in enumerate(orders):
            pair_events: dict[str, dict[str, Any]] = {}
            for position, key in enumerate(order):
                event = run_once(
                    variants[key],
                    commands[key],
                    args.timeout,
                    environment,
                    chosen_cpus,
                    args.threads,
                    block_sizes[key],
                    schedules[key],
                    native_bmi2_adx,
                )
                event.update(
                    {
                        "pair_index": pair_index,
                        "pair_order": order,
                        "position": position,
                    }
                )
                events.append(event)
                pair_events[key] = event
            baseline_time = float(pair_events["A"]["external_seconds"])
            candidate_time = float(pair_events["B"]["external_seconds"])
            ratio = baseline_time / candidate_time
            baseline_times.append(baseline_time)
            candidate_times.append(candidate_time)
            ratios.append(ratio)
            strata[order].append(ratio)
            print(
                f"pair {pair_index + 1:02d}/{args.pairs} {order}: "
                f"A={baseline_time:.6f}s B={candidate_time:.6f}s "
                f"A/B={ratio:.4f}x",
                flush=True,
            )

        baseline_summary = summarize(baseline_times, args.seed + 1)
        candidate_summary = summarize(candidate_times, args.seed + 2)
        ratio_summary = summarize(ratios, args.seed + 3)
        stratified_low, stratified_high = stratified_bootstrap_median_ci(
            ratios, orders, args.seed + 3
        )
        ratio_summary["bootstrap_median_ci95_low"] = stratified_low
        ratio_summary["bootstrap_median_ci95_high"] = stratified_high
        order_summaries = {
            order: summarize(values, args.seed + 10 + index)
            for index, (order, values) in enumerate(sorted(strata.items()))
        }
        stability = stationarity(baseline_times, candidate_times, ratios)
        promotion_reasons: list[str] = []
        if float(ratio_summary["median"]) <= 1.02:
            promotion_reasons.append("paired median does not exceed 1.02x")
        if float(ratio_summary["bootstrap_median_ci95_low"]) <= 1.0:
            promotion_reasons.append("paired bootstrap CI includes parity")
        if any(float(item["median"]) <= 1.0 for item in order_summaries.values()):
            promotion_reasons.append("at least one process-order stratum does not win")
        if stability["status"] != "PASS":
            promotion_reasons.append("four-block stationarity gate failed")
        promotion = {
            "status": "PASS" if not promotion_reasons else "FAIL",
            "candidate_action": "promote" if not promotion_reasons else "retain-incumbent",
            "thresholds": {
                "minimum_paired_median": 1.02,
                "minimum_ci95_low": 1.0,
                "minimum_each_order_median": 1.0,
                "stationarity_required": True,
            },
            "reasons": promotion_reasons,
        }
        report = {
            "schema": 2,
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "compiler": compiler_version(compiler),
                "compiler_native_bmi2_adx": native_bmi2_adx,
                "git_commit": git_commit,
                "git_dirty": git_dirty,
                "cpu_model": cpu_model,
                "cpu_flags": cpu_flags,
                "allowed_cpus": sorted(allowed_cpus),
                "chosen_cpus": sorted(chosen_cpus),
                "chosen_cpu_topology": cpu_topology(chosen_cpus),
                "openmp": {
                    key: environment[key]
                    for key in ("OMP_DYNAMIC", "OMP_PROC_BIND", "OMP_PLACES")
                },
                "cleared_inherited_openmp": cleared_openmp,
            },
            "build": {
                "source": str(source),
                "source_snapshot": (
                    str(preserved_source)
                    if preserved_source is not None
                    else str(source_snapshot)
                ),
                "source_sha256": source_hash,
                "runner": str(runner_path),
                "runner_sha256": runner_hash,
                "commands": {key: list(value) for key, value in build_commands.items()},
                "binary_sha256": binary_hashes,
            },
            "protocol": {
                "warmup_pairs": args.warmup_pairs,
                "pairs": args.pairs,
                "seed": args.seed,
                "orders": orders,
                "fresh_process_per_sample": True,
                "adjacent_pairs": True,
                "build_and_self_test_excluded": True,
                "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
                "paired_bootstrap": (
                    "resample-within-four-block-by-order-strata"
                ),
                "threads": args.threads,
                "block_sizes": block_sizes,
                "schedules": schedules,
            },
            "variants": {
                "A": {
                    "label": baseline.label,
                    "defines": list(baseline.defines),
                },
                "B": {
                    "label": candidate.label,
                    "defines": list(candidate.defines),
                },
            },
            "events": events,
            "summary": {
                "baseline_external_seconds": baseline_summary,
                "candidate_external_seconds": candidate_summary,
                "paired_baseline_over_candidate": ratio_summary,
                "paired_by_order": order_summaries,
            },
            "stationarity": stability,
            "promotion": promotion,
        }
        print(
            "summary: "
            f"A={baseline_summary['median']:.6f}s, "
            f"B={candidate_summary['median']:.6f}s, "
            f"paired={ratio_summary['median']:.4f}x "
            f"(CI {ratio_summary['bootstrap_median_ci95_low']:.4f}.."
            f"{ratio_summary['bootstrap_median_ci95_high']:.4f}), "
            f"stationarity={stability['status']}, "
            f"promotion={promotion['candidate_action']}"
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if preserved_source is None:
                raise AssertionError("missing preserved source path")
            shutil.copyfile(source_snapshot, preserved_source)
            if sha256(preserved_source) != source_hash:
                raise RuntimeError("preserved source hash mismatch")
            args.output.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(f"wrote JSON report: {args.output}")
            print(f"preserved source snapshot: {preserved_source}")


if __name__ == "__main__":
    main()
