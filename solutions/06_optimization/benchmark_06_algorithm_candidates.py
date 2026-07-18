#!/usr/bin/env python3
"""Repeated orthogonal benchmark for challenge-6 state-recovery algorithms."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


EXPECTED = {
    "d": int("1c3cdd6b221806db0a7b28", 16),
    "state": int("638d9d631ab436da51e640", 16),
    "r3": int("2443c8daf1a9d52b09", 16),
}


@dataclass(frozen=True)
class Case:
    name: str
    executable: str
    arguments: tuple[str, ...]


def run(case: Case, timeout: float) -> tuple[float, float]:
    started = time.perf_counter()
    process = subprocess.run(
        (case.executable, *case.arguments, "--json"),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    external = time.perf_counter() - started
    if process.returncode:
        raise RuntimeError(f"{case.name} failed: {process.stderr}\n{process.stdout}")
    result = json.loads(process.stdout)
    observed = {
        key: int(result[key], 0) if isinstance(result[key], str) else int(result[key])
        for key in EXPECTED
    }
    if observed != EXPECTED or result.get("state_label") != "s2":
        raise RuntimeError(f"{case.name} known-answer failure: {result}")
    internal = float(result["state_seconds"])
    return external, internal


def summary(values: list[float]) -> dict[str, float]:
    median = statistics.median(values)
    return {
        "median": median,
        "mean": statistics.fmean(values),
        "stdev": statistics.stdev(values),
        "mad": statistics.median(abs(value - median) for value in values),
        "min": min(values),
        "max": max(values),
    }


def compile_source(source: Path, output: Path) -> None:
    process = subprocess.run(
        (
            "g++",
            "-O3",
            "-DNDEBUG",
            "-std=c++20",
            "-fopenmp",
            str(source),
            "-lgmpxx",
            "-lgmp",
            "-o",
            str(output),
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    if process.returncode:
        raise RuntimeError(f"build failed for {source}:\n{process.stderr}")


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.warmup < 1 or args.repetitions < 5 or args.threads < 1:
        parser.error("require warmup >= 1, repetitions >= 5, and threads >= 1")

    directory = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="bench06deep-") as temporary:
        temporary_path = Path(temporary)
        baseline = temporary_path / "baseline"
        candidates = temporary_path / "candidates"
        compile_source(directory / "solve_06_gmp.cpp", baseline)
        compile_source(directory / "solve_06_algorithm_candidates.cpp", candidates)

        common = ("--threads", str(args.threads))
        cases = [
            Case("baseline-w5", str(baseline), (*common, "--telemetry", "analytic")),
            Case(
                "scalar-w5-basic",
                str(candidates),
                ("--mode", "jacobian-scalar", *common, "--wnaf-width", "5", "--no-legendre"),
            ),
            Case(
                "scalar-w5-legendre",
                str(candidates),
                ("--mode", "jacobian-scalar", *common, "--wnaf-width", "5"),
            ),
            Case(
                "scalar-w4-basic",
                str(candidates),
                ("--mode", "jacobian-scalar", *common, "--wnaf-width", "4", "--no-legendre"),
            ),
            Case(
                "scalar-w4-legendre",
                str(candidates),
                ("--mode", "jacobian-scalar", *common, "--wnaf-width", "4"),
            ),
            Case(
                "batch-w3-b32",
                str(candidates),
                ("--mode", "jacobian-batch", *common, "--wnaf-width", "3", "--block-size", "32"),
            ),
            Case(
                "batch-w4-b32",
                str(candidates),
                ("--mode", "jacobian-batch", *common, "--wnaf-width", "4", "--block-size", "32"),
            ),
            Case(
                "batch-w5-b32",
                str(candidates),
                ("--mode", "jacobian-batch", *common, "--wnaf-width", "5", "--block-size", "32"),
            ),
            Case(
                "batch-w4-direct-cubic",
                str(candidates),
                (
                    "--mode",
                    "jacobian-batch",
                    *common,
                    "--wnaf-width",
                    "4",
                    "--block-size",
                    "32",
                    "--direct-cubic",
                ),
            ),
            Case(
                "batch-w4-no-legendre",
                str(candidates),
                (
                    "--mode",
                    "jacobian-batch",
                    *common,
                    "--wnaf-width",
                    "4",
                    "--block-size",
                    "32",
                    "--no-legendre",
                ),
            ),
            Case(
                "xonly-b32-deferred",
                str(candidates),
                (
                    "--mode",
                    "xonly-batch",
                    *common,
                    "--block-size",
                    "32",
                    "--no-legendre",
                ),
            ),
            Case(
                "xonly-b32-legendre",
                str(candidates),
                ("--mode", "xonly-batch", *common, "--block-size", "32"),
            ),
        ]

        print(
            f"{cpu_model()}, logical_cpus={os.cpu_count()}, threads={args.threads}, "
            f"warmup={args.warmup}, repetitions={args.repetitions}",
            flush=True,
        )
        for case in cases:
            for _ in range(args.warmup):
                external, internal = run(case, args.timeout)
                print(
                    f"warmup {case.name}: external={external:.6f}s "
                    f"state={internal:.6f}s verified",
                    flush=True,
                )

        external_samples = {case.name: [] for case in cases}
        internal_samples = {case.name: [] for case in cases}
        for repetition in range(args.repetitions):
            offset = repetition % len(cases)
            for case in cases[offset:] + cases[:offset]:
                external, internal = run(case, args.timeout)
                external_samples[case.name].append(external)
                internal_samples[case.name].append(internal)
                print(
                    f"measure {repetition + 1}/{args.repetitions} {case.name}: "
                    f"external={external:.6f}s state={internal:.6f}s verified",
                    flush=True,
                )

        external_summary = {name: summary(values) for name, values in external_samples.items()}
        internal_summary = {name: summary(values) for name, values in internal_samples.items()}
        baseline_median = internal_summary["baseline-w5"]["median"]
        print("\ninternal state-recovery summary")
        for case in cases:
            item = internal_summary[case.name]
            speedup = baseline_median / item["median"]
            print(
                f"{case.name:25s} median={item['median']:.6f}s "
                f"stdev={item['stdev']:.6f}s MAD={item['mad']:.6f}s "
                f"min={item['min']:.6f}s max={item['max']:.6f}s "
                f"speedup={speedup:.3f}x"
            )

        report = {
            "environment": {
                "cpu": cpu_model(),
                "logical_cpus": os.cpu_count(),
                "threads": args.threads,
                "python": platform.python_version(),
            },
            "protocol": {
                "warmup": args.warmup,
                "repetitions": args.repetitions,
                "rotating_order": True,
                "known_answer_each_run": {key: hex(value) for key, value in EXPECTED.items()},
            },
            "external_samples": external_samples,
            "internal_samples": internal_samples,
            "external_summary": external_summary,
            "internal_summary": internal_summary,
        }
        if args.output:
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
