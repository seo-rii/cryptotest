#!/usr/bin/env python3
"""Reproduce the challenge-2 split-width AVX2 experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zipfile import ZipFile

import screen_simd as common


CASES = {
    "scalar": {
        "source": "submissions/02/contest.c",
        "cflags": ["-mbmi2", "-finline-limit=2000"],
        "audit_mode": "full-inline-320",
    },
    "avx2_current": {
        "source": "submissions/02/src/optimization/contest_simd_avx2_lanewise.c",
        "cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
        "audit_mode": "avx2-inline-lanewise",
    },
    "splitxmm": {
        "source": "submissions/02/src/optimization/contest_simd_avx2_splitxmm.c",
        "cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
        "audit_mode": "report-only",
    },
    "splitpair": {
        "source": "submissions/02/src/optimization/contest_simd_avx2_splitpair.c",
        "cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
        "audit_mode": "report-only",
    },
    "splitserial": {
        "source": "submissions/02/src/optimization/contest_simd_avx2_splitserial.c",
        "cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
        "audit_mode": "report-only",
    },
    "splitrecompute": {
        "source": "submissions/02/src/optimization/contest_simd_avx2_splitrecompute.c",
        "cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
        "audit_mode": "report-only",
    },
}
EXPECTED_SOURCE_HASHES = {
    "scalar": "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71",
    "avx2_current": "3a8273cb6f381efb30fb4e104a9741acf158307714216f2a2b2d8c1756b9d751",
    "splitxmm": "688c5d1daf9cca52e3b33292ebd52fe23f4adc9f93ddf49a89059e1e2e65925b",
    "splitpair": "962529c07990fe74a0214bddf465b4befb111ea57bb7ab6c5769a09fb0f30ac1",
    "splitserial": "b04736b1219112a2f46176f8caa0ba7dc7921caca3d72be0f68d06738f3d75e9",
    "splitrecompute": "f264f0317d3bc7b7b42479396fc297810c6cb420bc0012dee4082a6c26407fd5",
}
VERIFIER_FLAGS = [
    "-O3",
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
]
EXPECTED_VERIFIER_STDOUT = """candidate_random_differential_cases=100000
candidate_random_seed=0x243f6a8885a308d3
candidate_random_state_and_constants=PASS
candidate_round_counts=1,20
candidate_differential=PASS
"""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_checked(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"command failed ({completed.returncode}): "
            f"{subprocess.list2cmdline(command)}\n{detail}"
        )
    return completed


def validate_source_hashes(repository: Path) -> None:
    for name, case in CASES.items():
        actual = sha256_file(repository / case["source"])
        expected = EXPECTED_SOURCE_HASHES[name]
        if expected == "TO_BE_FILLED":
            continue
        if actual != expected:
            raise RuntimeError(f"{name}: source hash changed: {actual}")


def active_benchmark_processes() -> list[dict[str, Any]]:
    """Return other benchmark processes that would contaminate host timing."""

    current = os.getpid()
    matches = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == current:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        command = raw.replace(b"\0", b" ").decode(errors="replace")
        if any(
            marker in command
            for marker in (
                "benchmark_permutation.py",
                "autotune_02.py screen",
                "autotune_02.py confirm",
            )
        ):
            matches.append({"pid": int(entry.name), "command": command})
    return sorted(matches, key=lambda item: item["pid"])


def cpu_topology(cpu: int) -> dict[str, Any]:
    root = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
    return {
        "cpu": cpu,
        "core_id": int((root / "core_id").read_text().strip()),
        "physical_package_id": int(
            (root / "physical_package_id").read_text().strip()
        ),
        "thread_siblings_list": (root / "thread_siblings_list").read_text().strip(),
        "allowed_affinity": sorted(os.sched_getaffinity(0)),
    }


def validate_static(result: dict[str, Any], repository: Path) -> None:
    if result["compiler"] != "gcc (GCC) 13.3.0":
        raise RuntimeError(f"unexpected pinned compiler: {result['compiler']}")
    for name, report in result["cases"].items():
        verification = report["verification"]
        if not (
            verification["returncode"] == 0
            and verification["stdout"] == EXPECTED_VERIFIER_STDOUT
            and verification["stderr"] == ""
            and verification["random_cases"] == 100000
            and verification["random_state_and_constants"] is True
            and verification["round_counts"] == [1, 20]
            and verification["verifier_translation_unit_cflags"] == VERIFIER_FLAGS
        ):
            raise RuntimeError(f"{name}: pinned differential verification failed")
        if report["source_sha256"] != sha256_file(
            repository / CASES[name]["source"]
        ):
            raise RuntimeError(f"{name}: pinned source digest mismatch")
        audit = report["binary_audit"]
        if (
            audit["status"] != "PASS"
            or audit["calls"] != 0
            or audit["push_pop"] != 0
        ):
            raise RuntimeError(f"{name}: exact timed-loop audit failed")


def run_official_vector_smoke(
    repository: Path, temporary: Path
) -> dict[str, Any]:
    """Run each pinned-GCC binary against the supplied vector files once."""

    vector_directory = temporary / "official-vectors"
    vector_directory.mkdir()
    with ZipFile(repository / "problems" / "2_암호구현.zip") as zipped:
        (vector_directory / "testvector.txt").write_bytes(
            zipped.read("code/testvector.txt")
        )
        (vector_directory / "testvector_20round.txt").write_bytes(
            zipped.read("code/testvector_20round.txt")
        )
    reports = {}
    for name in CASES:
        completed = subprocess.run(
            [str(temporary / "static" / name)],
            cwd=vector_directory,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        passed = (
            completed.returncode == 0
            and "one-round testvector verification: OK (1000 pairs checked)"
            in completed.stdout
            and "20-round testvector verification: OK" in completed.stdout
            and completed.stderr == ""
        )
        if not passed:
            raise RuntimeError(f"{name}: official-vector smoke failed")
        reports[name] = {
            "status": "PASS",
            "one_round_pairs": 1000,
            "twenty_round_cases": 1,
            "validated_stdout_markers": [
                "one-round testvector verification: OK (1000 pairs checked)",
                "20-round testvector verification: OK",
            ],
            "qualification": (
                "the harness timing line was ignored; this single execution "
                "is correctness evidence, not a timing campaign"
            ),
        }
    return reports


def benchmark_command(
    repository: Path, args: argparse.Namespace, output: Path
) -> list[str]:
    command = [
        sys.executable,
        str(repository / "submissions/02/src/benchmark_permutation.py"),
    ]
    for name, case in CASES.items():
        command.extend(["--case", f"{name}={repository / case['source']}"])
    command.extend(
        [
            "--baseline",
            "avx2_current",
            "--compiler",
            args.compiler,
            "--iterations",
            str(args.iterations),
            "--warmups",
            str(args.warmups),
            "--samples",
            str(args.samples),
            "--random-cases",
            str(args.random_cases),
            "--cpu",
            "0",
            "--extra-cflag=-Werror",
        ]
    )
    for name, case in CASES.items():
        for flag in case["cflags"]:
            command.extend(["--case-cflag", f"{name}={flag}"])
        command.extend(["--audit-mode", f"{name}={case['audit_mode']}"])
    command.extend(
        [
            "--campaign-id",
            "split-simd-amd-cpu0",
            "--json",
            str(output),
        ]
    )
    return command


def validate_host(
    report: dict[str, Any], args: argparse.Namespace, repository: Path
) -> None:
    common.validate_timed_main_validation(
        report,
        set(CASES),
        args.iterations,
        args.warmups,
        args.samples,
        "host",
    )
    expected_config = {
        "iterations": args.iterations,
        "warmups": args.warmups,
        "samples_per_case": args.samples,
        "candidate_random_differential_cases": args.random_cases,
        "timed_main_repeated_call_validation": True,
    }
    for key, expected in expected_config.items():
        if report.get("config", {}).get(key) != expected:
            raise RuntimeError(f"host config {key} does not equal {expected}")
    if report.get("environment", {}).get("affinity") != [0]:
        raise RuntimeError("host benchmark did not remain pinned to CPU 0")
    for name, case in CASES.items():
        source = report["sources"][name]
        expected_hash = sha256_file(repository / case["source"])
        if source["sha256"] != expected_hash:
            raise RuntimeError(f"{name}: host source hash mismatch")
        verification = report["candidate_verification"][name]
        if not (
            verification["status"] == "PASS"
            and verification["random_cases"] == args.random_cases
            and verification["random_state_and_constants"] is True
            and verification["round_counts"] == [1, 20]
            and verification["verifier_only_flag_overrides"] == []
            and verification["verifier_translation_unit_cflags"] == VERIFIER_FLAGS
        ):
            raise RuntimeError(f"{name}: host differential verification failed")
        audit = report["assembly_audits"][name]
        if (
            audit["status"] != "PASS"
            or audit["calls"] != 0
            or audit["push_pop"] != 0
        ):
            raise RuntimeError(f"{name}: measured binary audit failed")
    for name in CASES:
        samples = report["internal_ns_per_20round"][name]
        if len(samples) != args.samples or not all(
            isinstance(value, (int, float)) and math.isfinite(value)
            for value in samples
        ):
            raise RuntimeError(f"{name}: malformed timing samples")


def compact_host(report: dict[str, Any], artifact_hash: str) -> dict[str, Any]:
    return {
        "artifact_sha256": artifact_hash,
        "schema_version": report["schema_version"],
        "campaign_id": report["campaign_id"],
        "measurement_protocol": report["measurement_protocol"],
        "environment": report["environment"],
        "config": report["config"],
        "sources": report["sources"],
        "candidate_verification": report["candidate_verification"],
        "timed_main_validation": report["timed_main_validation"],
        "assembly_audits": report["assembly_audits"],
        "summaries": report["summaries"],
        "comparisons": report["comparisons"],
        "internal_ns_per_20round": report["internal_ns_per_20round"],
        "outer_wall_seconds": report["outer_wall_seconds"],
    }


def summarize_designs(static: dict[str, Any], host: dict[str, Any] | None) -> dict[str, Any]:
    designs = {}
    for name in ("splitxmm", "splitpair", "splitserial", "splitrecompute"):
        case = static["cases"][name]
        current = static["cases"]["avx2_current"]
        item = {
            "pinned_gcc13_timed_loop": {
                "instructions": case["binary_audit"]["loop_instructions"],
                "bytes": case["binary_audit"]["loop_bytes"],
                "memory_operands": case["binary_audit"][
                    "memory_operands_excluding_lea"
                ],
                "mnemonics": case["binary_audit"]["mnemonics"],
            },
            "llvm_mca": case["llvm_mca"],
            "static_cycles_relative_to_current": {
                model: (
                    case["llvm_mca"][model]["cycles_per_iteration"]
                    / current["llvm_mca"][model]["cycles_per_iteration"]
                )
                for model in common.MODELS
            },
        }
        if host is not None:
            item["host_comparison_against_current"] = host["comparisons"][name]
        designs[name] = item
    return designs


def run(args: argparse.Namespace) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[4]
    validate_source_hashes(repository)
    common.CASES = CASES
    with tempfile.TemporaryDirectory(prefix="ch2-split-simd-") as raw:
        temporary = Path(raw)
        static = common.static_screen(
            repository,
            SimpleNamespace(runtime=args.runtime, llvm_mca=args.llvm_mca),
            temporary,
        )
        validate_static(static, repository)
        official_vectors = run_official_vector_smoke(repository, temporary)
        host = None
        topology = cpu_topology(0)
        preflight_processes = active_benchmark_processes()
        if args.run_host:
            if args.iterations < 3_000_000 or args.warmups < 6 or args.samples < 32:
                raise RuntimeError(
                    "host protocol requires iterations>=3000000, warmups>=6, samples>=32"
                )
            if args.random_cases != 100000:
                raise RuntimeError("host protocol requires exactly 100000 random cases")
            if 0 not in topology["allowed_affinity"]:
                raise RuntimeError("CPU 0 is not in this process's allowed affinity")
            if preflight_processes:
                raise RuntimeError(
                    f"other challenge-2 benchmark processes are active: "
                    f"{preflight_processes}"
                )
            host_path = temporary / "host.json"
            run_checked(benchmark_command(repository, args, host_path), repository)
            full_host = json.loads(host_path.read_text())
            validate_host(full_host, args, repository)
            host = compact_host(full_host, sha256_file(host_path))
    designs = summarize_designs(static, host)
    current = static["cases"]["avx2_current"]
    return {
        "schema_version": 1,
        "all_required_checks_passed": True,
        "scope": (
            "two 128-bit AVX2 dependency-chain layouts versus the existing "
            "four-lane YMM candidate; no actual 255H P/E/LP-E measurement"
        ),
        "designs": {
            "splitxmm": (
                "contiguous word groups (0,1) and (2,3); reversed constants "
                "cross from the other XMM group"
            ),
            "splitpair": (
                "word-reversal orbits (0,3) and (1,2); all reversed constants "
                "and rotations are in-group lane swaps"
            ),
            "splitserial": (
                "the same word-reversal orbit packing, but complete one XMM "
                "chain before starting the other to reduce live ranges"
            ),
            "splitrecompute": (
                "two parallel reversal-orbit groups, recomputing reversed "
                "dynamic constants with four VPSHUFD instructions per pair"
            ),
        },
        "pinned_static_screen": static,
        "official_vector_smoke": official_vectors,
        "host_preflight": {
            "topology": topology,
            "active_benchmark_processes": preflight_processes,
        },
        "host_measurement": host,
        "host_timing_decision": (
            "skipped by the staged screen: every split design has at least "
            "1.361x the current YMM LLVM-MCA cycle estimate, at least 242 "
            "instructions, and at least 30 timed-loop memory operands; no "
            "split candidate qualified for a performance campaign"
            if host is None
            else "explicitly requested after the static screen"
        ),
        "integration_status": {
            "candidate_found": False,
            "autotune_manifest_registered": False,
            "classification": "exploration-only negative results",
            "source_retention_reason": (
                "four small contest-shaped sources isolate contiguous packing, "
                "reversal-orbit packing, serialized live ranges, and explicit "
                "shuffle-for-spill tradeoffs; together they make the negative "
                "result reproducible without generated binary assets"
            ),
        },
        "comparison_summary": {
            "current_y_mm": {
                "instructions": current["binary_audit"]["loop_instructions"],
                "bytes": current["binary_audit"]["loop_bytes"],
                "memory_operands": current["binary_audit"][
                    "memory_operands_excluding_lea"
                ],
                "llvm_mca": current["llvm_mca"],
            },
            "split_designs": designs,
        },
        "rejected_designs": {
            "splitxmm": (
                "reject unless host timing overturns its duplicated instruction "
                "stream and static scheduler cost"
            ),
            "splitpair": (
                "orbit packing removes cross-group setup dependencies, but does "
                "not remove any of the 240 core vector operations"
            ),
            "splitserial": (
                "serializing groups may reduce spills but gives up the only "
                "instruction-level parallelism that could hide chain latency"
            ),
            "splitrecompute": (
                "explicitly trades four invariant spills for four in-register "
                "lane swaps per two-round pair; retain only if static cost wins"
            ),
            "scalarized_immediate_rotates": (
                "not implemented: four distinct rotations would require lane "
                "extract/insert or compute-and-select sequences, increasing the "
                "instruction stream beyond AVX2 variable shifts"
            ),
        },
        "checks": {
            "pinned_gcc_is_exact_13_3_0": static["compiler"]
            == "gcc (GCC) 13.3.0",
            "pinned_random_state_and_constants_100k_passed": all(
                case["verification"]["returncode"] == 0
                for case in static["cases"].values()
            ),
            "official_vectors_passed": all(
                item["status"] == "PASS"
                for item in official_vectors.values()
            ),
            "exact_timed_loop_audits_passed": all(
                case["binary_audit"]["status"] == "PASS"
                for case in static["cases"].values()
            ),
            "optional_host_protocol_ran": host is not None,
            "optional_host_random_state_and_constants_100k_passed": (
                None
                if host is None
                else all(
                    item["status"] == "PASS"
                    for item in host["candidate_verification"].values()
                )
            ),
            "optional_host_timed_main_validation_passed": (
                None
                if host is None
                else host["schema_version"] == 5
                and host["timed_main_validation"]["oracle"]["status"] == "PASS"
                and all(
                    item["status"] == "PASS"
                    for item in host["timed_main_validation"]["cases"].values()
                )
            ),
        },
        "reproduction": {
            "static_and_correctness": (
                "python3 optimization/screen_split_simd.py "
                "--output optimization/split_simd_results.json"
            ),
            "host_campaign_not_recommended": (
                "append --run-host only to override the static rejection; the "
                "script then enforces CPU 0, >=3000000 iterations, >=6 warmups, "
                ">=32 samples, and 100000 random differential cases"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().with_name("split_simd_results.json"),
    )
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--llvm-mca", default="llvm-mca-16")
    parser.add_argument("--compiler", default="gcc")
    parser.add_argument("--run-host", action="store_true")
    parser.add_argument("--iterations", type=int, default=3_000_000)
    parser.add_argument("--warmups", type=int, default=6)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--random-cases", type=int, default=100_000)
    args = parser.parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for name, item in result["comparison_summary"]["split_designs"].items():
        loop = item["pinned_gcc13_timed_loop"]
        print(
            f"{name}: {loop['instructions']} instructions, "
            f"{loop['bytes']} bytes, {loop['memory_operands']} memory operands"
        )
        for model, ratio in item["static_cycles_relative_to_current"].items():
            print(f"  {model}: {ratio:.3f}x current cycles")
        if result["host_measurement"] is not None:
            comparison = item["host_comparison_against_current"]
            print(
                f"  host current/candidate={comparison['paired_median']:.3f} "
                f"CI95=[{comparison['paired_bootstrap_ci95_low']:.3f}, "
                f"{comparison['paired_bootstrap_ci95_high']:.3f}]"
            )


if __name__ == "__main__":
    main()
