#!/usr/bin/env python3
"""Reproduce the challenge-2 phase-staggered two-XMM static screen."""

from __future__ import annotations

import argparse
import hashlib
import json
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
    "phase_staggered": {
        "source": (
            "submissions/02/src/optimization/contest_simd_avx2_phase_staggered.c"
        ),
        "cflags": [
            "-mavx2",
            "-mbmi2",
            "-DCH2_SIMD_INLINE",
            "-finline-limit=2000",
        ],
        "audit_mode": "report-only",
    },
}
EXPECTED_SOURCE_HASHES = {
    "scalar": "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71",
    "avx2_current": (
        "3a8273cb6f381efb30fb4e104a9741acf158307714216f2a2b2d8c1756b9d751"
    ),
    "phase_staggered": (
        "1824843868e3747634fd5eb8f39f08ce0b79588da8ca0f19fcaee810c2b12983"
    ),
}
DEPENDENCIES = {
    "included_scalar_source": {
        "path": "submissions/02/contest.c",
        "sha256": EXPECTED_SOURCE_HASHES["scalar"],
        "reason": (
            "the experimental source reuses the contest utility, one-round "
            "implementation, and harness while replacing the 20-round ABI"
        ),
    },
    "candidate_verifier": {
        "path": "submissions/02/src/optimization/verify_contest_candidate.c",
        "sha256": (
            "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35"
        ),
    },
    "problem_archive": {
        "path": "submissions/02/src/2_암호구현.zip",
        "sha256": (
            "d0c3158adda8ba258becfc0e347267c0f2f0112738ec732be6dcb5477342e88e"
        ),
    },
}
EXPECTED_VERIFIER_STDOUT = """candidate_random_differential_cases=100000
candidate_random_seed=0x243f6a8885a308d3
candidate_random_state_and_constants=PASS
candidate_round_counts=1,20
candidate_differential=PASS
"""
VERIFIER_FLAGS = [
    "-O3",
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
]
HOST_TIMING_FILES = {
    "submissions/02/src/optimization/eighth_wave_timing_cpu1.json": (
        "70619e7814fe8ba1e8cfa9da598ed0c626a63e1519e29cf7272e9296b8aebe5c"
    ),
    "submissions/02/src/optimization/eighth_wave_timing_cpu3.json": (
        "ca47c1858a7170e1d0cb7eff48d10cced728eaeb4f08a225f64cc803b4491661"
    ),
}
TIMING_PROTOCOL_FILES = {
    "autotune_driver": (
        "submissions/02/src/optimization/autotune_255h.py",
        "36ba5ce6d130aa117c621844cd8c1f8bcb4c96e4518580d25afa688d3b976d09",
    ),
    "benchmark_driver": (
        "submissions/02/src/benchmark_permutation.py",
        "4262926ecd8e4fcfabcc7c4e74a4c87bbc0450f995b31d4a60137f888bd59d42",
    ),
    "candidate_verifier": (
        "submissions/02/src/optimization/verify_contest_candidate.c",
        "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35",
    ),
    "loop_audit": (
        "submissions/02/src/loop_audit.py",
        "e73d27abfbb7eea9ee84e0216baaf7f39f128db0cffdcb79b469656f9c185e23",
    ),
    "problem_archive": (
        "submissions/02/src/2_암호구현.zip",
        "d0c3158adda8ba258becfc0e347267c0f2f0112738ec732be6dcb5477342e88e",
    ),
    "reference_oracle": (
        "submissions/02/src/solve_permutation.c",
        "fb6b5128f6777bdb5c9c940541d7052a317b596775d7ec0d7820d0610cb9aa42",
    ),
}
TIMING_SOURCES = {
    "current": {
        "path": CASES["avx2_current"]["source"],
        "sha256": EXPECTED_SOURCE_HASHES["avx2_current"],
        "case_cflags": CASES["avx2_current"]["cflags"],
    },
    "inline_asm": {
        "path": "submissions/02/src/optimization/contest_simd_avx2_inline_asm.c",
        "sha256": (
            "778187b61a0a769cb012e5205edb5782df2c25418681651cb76d05739198307c"
        ),
        "case_cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
    },
    "phase": {
        "path": CASES["phase_staggered"]["source"],
        "sha256": EXPECTED_SOURCE_HASHES["phase_staggered"],
        "case_cflags": CASES["phase_staggered"]["cflags"],
    },
}
PHASE_EXPECTED_MNEMONICS = {
    "rorx": 4,
    "xor": 4,
    "bswap": 4,
    "add": 4,
    "vpsllq": 38,
    "vpsrlq": 38,
    "vpor": 38,
    "vpxor": 38,
    "vpshufb": 38,
    "vpaddq": 38,
}


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


def validate_source_contract(repository: Path) -> None:
    for name, case in CASES.items():
        actual = sha256_file(repository / case["source"])
        if actual != EXPECTED_SOURCE_HASHES[name]:
            raise RuntimeError(f"{name}: source hash changed: {actual}")
    for name, dependency in DEPENDENCIES.items():
        actual = sha256_file(repository / dependency["path"])
        if actual != dependency["sha256"]:
            raise RuntimeError(f"{name}: dependency hash changed: {actual}")


def validate_static(static: dict[str, Any]) -> None:
    if static["compiler"] != "gcc (GCC) 13.3.0":
        raise RuntimeError(f"unexpected pinned compiler: {static['compiler']}")
    for name, report in static["cases"].items():
        verification = report["verification"]
        if not (
            verification["returncode"] == 0
            and verification["stdout"] == EXPECTED_VERIFIER_STDOUT
            and verification["stderr"] == ""
            and verification["random_cases"] == 100000
            and verification["random_state_and_constants"] is True
            and verification["round_counts"] == [1, 20]
            and verification["verifier_translation_unit_cflags"]
            == VERIFIER_FLAGS
        ):
            raise RuntimeError(f"{name}: pinned differential verification failed")
        if report["source_sha256"] != EXPECTED_SOURCE_HASHES[name]:
            raise RuntimeError(f"{name}: compiled source hash mismatch")
        audit = report["binary_audit"]
        if (
            audit["status"] != "PASS"
            or audit["calls"] != 0
            or audit["push_pop"] != 0
            or audit["memory_operands_excluding_lea"] != 0
        ):
            raise RuntimeError(f"{name}: exact timed-loop audit failed")

    phase = static["cases"]["phase_staggered"]["binary_audit"]
    if phase["loop_instructions"] != 257 or phase["loop_bytes"] != 1253:
        raise RuntimeError("phase candidate exact loop size changed")
    for mnemonic, expected in PHASE_EXPECTED_MNEMONICS.items():
        actual = phase["mnemonics"].get(mnemonic, 0)
        if actual != expected:
            raise RuntimeError(
                f"phase candidate {mnemonic}: expected {expected}, got {actual}"
            )


def run_official_vector_smoke(
    repository: Path, temporary: Path
) -> dict[str, dict[str, Any]]:
    vector_directory = temporary / "official-vectors"
    vector_directory.mkdir()
    with ZipFile(repository / DEPENDENCIES["problem_archive"]["path"]) as zipped:
        (vector_directory / "testvector.txt").write_bytes(
            zipped.read("code/testvector.txt")
        )
        (vector_directory / "testvector_20round.txt").write_bytes(
            zipped.read("code/testvector_20round.txt")
        )
    reports: dict[str, dict[str, Any]] = {}
    for name in CASES:
        completed = run_checked([str(temporary / "static" / name)], vector_directory)
        required = [
            "one-round testvector verification: OK (1000 pairs checked)",
            "20-round testvector verification: OK",
        ]
        if completed.stderr or not all(marker in completed.stdout for marker in required):
            raise RuntimeError(f"{name}: official-vector smoke failed")
        reports[name] = {
            "status": "PASS",
            "one_round_pairs": 1000,
            "twenty_round_cases": 1,
            "validated_stdout_markers": required,
            "qualification": (
                "the harness timing line was ignored; this execution is "
                "correctness evidence only"
            ),
        }
    return reports


def loop_summary(case: dict[str, Any]) -> dict[str, Any]:
    audit = case["binary_audit"]
    return {
        "instructions": audit["loop_instructions"],
        "bytes": audit["loop_bytes"],
        "memory_operands": audit["memory_operands_excluding_lea"],
        "calls": audit["calls"],
        "push_pop": audit["push_pop"],
        "mnemonics": audit["mnemonics"],
        "normalized_loop_sha256": audit["normalized_loop_sha256"],
        "llvm_mca": case["llvm_mca"],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[4]
    validate_source_contract(repository)
    common.CASES = CASES
    with tempfile.TemporaryDirectory(prefix="ch2-phase-staggered-") as raw:
        temporary = Path(raw)
        static = common.static_screen(
            repository,
            SimpleNamespace(runtime=args.runtime, llvm_mca=args.llvm_mca),
            temporary,
        )
        validate_static(static)
        official_vectors = run_official_vector_smoke(repository, temporary)

    current = static["cases"]["avx2_current"]
    phase = static["cases"]["phase_staggered"]
    relative_cycles = {
        model: (
            phase["llvm_mca"][model]["cycles_per_iteration"]
            / current["llvm_mca"][model]["cycles_per_iteration"]
        )
        for model in common.MODELS
    }
    host_measurement: dict[str, Any] = {}
    for relative_path, expected_timing_hash in HOST_TIMING_FILES.items():
        path = repository / relative_path
        actual_timing_hash = sha256_file(path)
        if actual_timing_hash != expected_timing_hash:
            raise RuntimeError(
                f"{relative_path}: historical timing artifact hash changed: "
                f"{actual_timing_hash}"
            )
        timing = json.loads(path.read_text())
        affinity = timing["environment"]["affinity"]
        if (
            timing["schema_version"] != 4
            or timing["baseline"] != "current"
            or timing["config"]["iterations"] != 3_000_000
            or timing["config"]["warmups"] != 6
            or timing["config"]["samples_per_case"] != 32
            or timing["config"]["candidate_random_differential_cases"]
            != 100_000
            or len(affinity) != 1
        ):
            raise RuntimeError(f"{relative_path}: host timing protocol mismatch")
        protocol_files = timing["measurement_protocol"]["files"]
        for protocol_name, (expected_path, expected_hash) in (
            TIMING_PROTOCOL_FILES.items()
        ):
            recorded = protocol_files.get(protocol_name)
            if (
                recorded is None
                or recorded["path"] != expected_path
                or recorded["sha256"] != expected_hash
            ):
                raise RuntimeError(
                    f"{relative_path}: stale {protocol_name} timing provenance"
                )
        for source_name, expected in TIMING_SOURCES.items():
            recorded = timing["sources"].get(source_name)
            expected_context = [
                "-iquote",
                str((repository / expected["path"]).parent),
            ]
            if (
                recorded is None
                or recorded["path"] != expected["path"]
                or recorded["sha256"] != expected["sha256"]
                or recorded["case_cflags"] != expected["case_cflags"]
                or recorded.get("source_context_cflags") != expected_context
            ):
                raise RuntimeError(
                    f"{relative_path}: stale {source_name} timing source provenance"
                )
        for name in ("current", "phase"):
            if (
                timing["candidate_verification"][name]["status"] != "PASS"
                or timing["assembly_audits"][name]["status"] != "PASS"
            ):
                raise RuntimeError(f"{relative_path}: {name} validation failed")
        if (
            timing["assembly_audits"]["current"]["normalized_loop_sha256"]
            != current["binary_audit"]["normalized_loop_sha256"]
            or timing["assembly_audits"]["phase"]["normalized_loop_sha256"]
            != phase["binary_audit"]["normalized_loop_sha256"]
        ):
            raise RuntimeError(f"{relative_path}: measured loop hash mismatch")
        host_measurement[f"cpu{affinity[0]}"] = {
            "path": relative_path,
            "sha256": actual_timing_hash,
            "host_cpu": timing["environment"]["cpu"],
            "compiler": timing["environment"]["compiler"],
            "affinity": affinity,
            "protocol": {
                "iterations": timing["config"]["iterations"],
                "warmups": timing["config"]["warmups"],
                "samples_per_case": timing["config"]["samples_per_case"],
                "random_cases": timing["config"][
                    "candidate_random_differential_cases"
                ],
                "order": timing["config"]["order"],
            },
            "current_median_ns": timing["summaries"]["current"]["median_ns"],
            "phase_median_ns": timing["summaries"]["phase"]["median_ns"],
            "current_over_phase_paired_median": timing["comparisons"]["phase"][
                "paired_median"
            ],
            "paired_bootstrap_ci95": [
                timing["comparisons"]["phase"]["paired_bootstrap_ci95_low"],
                timing["comparisons"]["phase"]["paired_bootstrap_ci95_high"],
            ],
        }
    return {
        "schema_version": 1,
        "all_required_checks_passed": True,
        "scope": (
            "phase-staggered word-reversal orbits using two XMM chains with "
            "immediate rotations; no Core Ultra 7 255H measurement"
        ),
        "algebra": {
            "transform": (
                "T_j(x)=BSWAP(ROL(x,r_j) XOR constants2[j]) + "
                "constants1[3-j]"
            ),
            "orbit_03": {
                "packing": "[x0, T3(x3)]",
                "shared_stage_order": "(T0,T3)^9,T0 (19 stages)",
                "epilogue": "apply T3 only to lane 0; lane 1 is final x3",
            },
            "orbit_12": {
                "packing": "[x1, T2(x2)]",
                "shared_stage_order": "(T1,T2)^9,T1 (19 stages)",
                "epilogue": "apply T2 only to lane 0; lane 1 is final x2",
            },
            "constant_generality": (
                "each T_j broadcasts its own arbitrary XOR constant and the "
                "arbitrary add constant of destination 3-j; no equality or "
                "fixed-value assumption is used"
            ),
        },
        "sources": {
            name: {
                "path": case["source"],
                "sha256": EXPECTED_SOURCE_HASHES[name],
                "cflags": case["cflags"],
            }
            for name, case in CASES.items()
        },
        "dependencies": DEPENDENCIES,
        "pinned_static_screen": static,
        "official_vector_smoke": official_vectors,
        "comparison_summary": {
            "avx2_current": loop_summary(current),
            "phase_staggered": loop_summary(phase),
            "phase_cycles_relative_to_current": relative_cycles,
            "instruction_ratio": (
                phase["binary_audit"]["loop_instructions"]
                / current["binary_audit"]["loop_instructions"]
            ),
            "byte_ratio": (
                phase["binary_audit"]["loop_bytes"]
                / current["binary_audit"]["loop_bytes"]
            ),
        },
        "decision": {
            "promote_over_scalar_incumbent": False,
            "register_in_autotuner": False,
            "classification": "exploration-only host-rejected candidate",
            "reason": (
                "the phase construction removes variable-count shifts and is "
                "0.795x the current YMM cycle estimate on the znver2 proxy, "
                "but duplicates the vector stream (257 versus 122 exact loop "
                "instructions), is 1.160x on the Intel-adjacent Alder Lake "
                "proxy, and measured only 0.758x/0.756x on two AMD affinities; "
                "without a 255H result it cannot replace the incumbent"
            ),
            "retain_source": True,
        },
        "host_measurement": host_measurement,
        "host_timing_decision": (
            "two controlled AMD-host campaigns contradicted the favorable "
            "znver2 proxy and rejected the phase candidate locally; they are "
            "historical schema-4 diagnostic evidence, not a substitute for "
            "schema-5 repeated-call validation or the 255H"
        ),
        "checks": {
            "pinned_gcc_is_exact_13_3_0": (
                static["compiler"] == "gcc (GCC) 13.3.0"
            ),
            "random_state_and_constants_100k_passed": all(
                case["verification"]["returncode"] == 0
                for case in static["cases"].values()
            ),
            "round_counts_verified": [1, 20],
            "official_vectors_passed": all(
                item["status"] == "PASS" for item in official_vectors.values()
            ),
            "exact_timed_loop_audits_passed": all(
                case["binary_audit"]["status"] == "PASS"
                and case["binary_audit"]["calls"] == 0
                and case["binary_audit"]["push_pop"] == 0
                and case["binary_audit"]["memory_operands_excluding_lea"] == 0
                for case in static["cases"].values()
            ),
            "historical_schema4_host_protocol_ran": True,
            "historical_schema4_timing_artifact_hashes_match": True,
            "historical_schema4_artifacts_correctly_lack_schema5_validation": True,
        },
        "reproduction": {
            "command": (
                "python3 submissions/02/src/optimization/screen_phase_staggered.py "
                "--output "
                "submissions/02/src/optimization/phase_staggered_results.json"
            ),
            "network": "disabled inside the pinned GCC container",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "submissions/02/src/optimization/phase_staggered_results.json"
        ),
    )
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--llvm-mca", default="llvm-mca-16")
    args = parser.parse_args()
    result = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    comparison = result["comparison_summary"]
    for name in ("avx2_current", "phase_staggered"):
        item = comparison[name]
        print(
            f"{name}: {item['instructions']} instructions, "
            f"{item['bytes']} bytes, {item['memory_operands']} memory operands"
        )
        for model, report in item["llvm_mca"].items():
            print(f"  {model}: {report['cycles_per_iteration']:.2f} cycles")
    for model, ratio in comparison["phase_cycles_relative_to_current"].items():
        print(f"phase/current {model}: {ratio:.3f}x")


if __name__ == "__main__":
    main()
