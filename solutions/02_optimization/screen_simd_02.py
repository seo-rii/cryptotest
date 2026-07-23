#!/usr/bin/env python3
"""Verify, measure, and statically inspect lane-wise SIMD for challenge 2."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any


IMAGE_DIGEST = "1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
IMAGE = f"gcc@sha256:{IMAGE_DIGEST}"
EXPECTED_SOURCE_HASHES = {
    "scalar": "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71",
    "avx2": "3a8273cb6f381efb30fb4e104a9741acf158307714216f2a2b2d8c1756b9d751",
    "sse2": "d3cdf1c5a773eae0df18433e8a8127833a976f0506644a825c1643fa4fb80138",
}
PRE_HOIST_AVX2_SHA256 = (
    "e9bc8537e8d66a1ed101277ac826bb476c8215b15bb9603df0c64ec2190f34fa"
)
CASES = {
    "scalar": {
        "source": "submissions/02/contest.c",
        "cflags": ["-mbmi2", "-finline-limit=2000"],
        "audit_mode": "full-inline-320",
    },
    "avx2": {
        "source": "solutions/02_optimization/contest_simd_avx2_lanewise.c",
        "cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
        "audit_mode": "report-only",
    },
    "sse2": {
        "source": "solutions/02_optimization/contest_simd_sse2_twolanes.c",
        "cflags": [
            "-msse2",
            "-mno-avx",
            "-DCH2_SIMD_INLINE",
            "-finline-limit=2000",
        ],
        "audit_mode": "report-only",
    },
}
MODELS = ("alderlake", "znver2")
RESIDENCY_VARIANT_NAMES = (
    "current_volatile_plusx",
    "nonvolatile_plusx",
    "state_inputs_x",
    "state_inputs_v",
    "state_all_constants_x",
    "tied_alias_outputs",
    "register_keyword_state_inputs",
    "state_inputs_memory_clobber",
    "swapped_current",
    "swapped_state_inputs",
    "identity_helper",
    "register_asm_ops",
)
RESIDENCY_VARIANT_NOTES = {
    "current_volatile_plusx": {
        "strategy": "volatile empty asm with tied +x outputs on both forward constants",
        "reason": (
            "rejected: volatility and read-write operands keep two vmovdqa loads in "
            "the timed loop"
        ),
    },
    "nonvolatile_plusx": {
        "strategy": "non-volatile empty asm with tied +x outputs on both constants",
        "reason": (
            "rejected: removing volatile alone leaves the constants as loop-carried "
            "read-write operands and retains two loads"
        ),
    },
    "state_inputs_x": {
        "strategy": "tie the evolving state, list forward constants as x inputs",
        "reason": (
            "rejected: GCC still reloads both forward constants and the loop grows "
            "from 587 to 605 bytes"
        ),
    },
    "state_inputs_v": {
        "strategy": "use generic vector v constraints for state and constant inputs",
        "reason": (
            "rejected: v versus x does not alter allocation; it emits the same "
            "two-load loop as state_inputs_x"
        ),
    },
    "state_all_constants_x": {
        "strategy": "list forward and reversed constants as x inputs",
        "reason": (
            "rejected: additional input constraints do not reserve registers across "
            "the fully inlined outer loop"
        ),
    },
    "tied_alias_outputs": {
        "strategy": "copy constants through explicit =x outputs tied to numbered inputs",
        "reason": (
            "rejected: explicit aliases reproduce the nonvolatile_plusx two-load loop"
        ),
    },
    "register_keyword_state_inputs": {
        "strategy": "add C register hints and constrain constants as x inputs",
        "reason": (
            "rejected: the register keyword is only a hint and does not change GCC's "
            "allocation"
        ),
    },
    "state_inputs_memory_clobber": {
        "strategy": "volatile state/input constraint plus a memory clobber",
        "reason": (
            "rejected: the compiler barrier retains both loads and increases the loop "
            "to 126 instructions"
        ),
    },
    "swapped_current": {
        "strategy": "swap operands of commutative forward XOR and ADD intrinsics",
        "reason": (
            "rejected: GCC canonicalizes the commutative operands to the current loop"
        ),
    },
    "swapped_state_inputs": {
        "strategy": "combine swapped operands with state/input constraints",
        "reason": (
            "rejected: operand order does not improve the state_inputs_x allocation"
        ),
    },
    "identity_helper": {
        "strategy": "pass each constant through an inline non-volatile +x identity helper",
        "reason": (
            "selected for code generation: the only variant with zero timed-loop "
            "memory operands, 122 instructions, and 579 bytes"
        ),
    },
    "register_asm_ops": {
        "strategy": "spell forward VPXOR and VPADDQ directly in tied-register asm",
        "reason": (
            "rejected: it retains two loads and adds register moves, reaching 126 "
            "instructions and 615 bytes"
        ),
    },
}
VERIFIER_TU_FLAGS = [
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


CONTAINER_DRIVER = textwrap.dedent(
    r"""
    import hashlib
    import json
    import re
    import subprocess
    from pathlib import Path

    repository = Path("/repository")
    output = Path("/output")
    manifest = json.loads(Path("/config/manifest.json").read_text())
    reports = {}
    verifier_object = output / "verifier.o"
    subprocess.run(
        [
            "gcc", "-O3", "-std=c11", "-Wall", "-Wextra", "-Wpedantic",
            "-Werror", "-c",
            "/repository/solutions/02_optimization/verify_contest_candidate_02.c",
            "-o", str(verifier_object),
        ],
        check=True,
    )

    def sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    for name, case in manifest["cases"].items():
        source = repository / case["source"]
        assembly = output / f"{name}.s"
        binary = output / name
        flags = ["-O3", "-Wall", "-Wextra", "-Werror", *case["cflags"]]
        subprocess.run(
            ["gcc", *flags, "-S", str(source), "-o", str(assembly)], check=True
        )
        subprocess.run(
            ["gcc", *flags, str(source), "-o", str(binary)], check=True
        )
        candidate_object = output / f"{name}.candidate.o"
        verifier = output / f"{name}.verifier"
        subprocess.run(
            [
                "gcc", *flags, "-Dmain=contest_candidate_main", "-c",
                str(source), "-o", str(candidate_object),
            ],
            check=True,
        )
        subprocess.run(
            ["gcc", *flags, str(candidate_object), str(verifier_object),
             "-o", str(verifier)],
            check=True,
        )
        verified = subprocess.run(
            [str(verifier), "100000"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        text = assembly.read_text()
        clocks = [
            match.start()
            for match in re.finditer(
                r"^\s*call\s+clock(?:@PLT)?\s*$", text, re.MULTILINE
            )
        ]
        if len(clocks) < 2:
            raise RuntimeError(f"{name}: timing clock calls not found")
        region = text[clocks[-2] : clocks[-1]]
        backedges = list(
            re.finditer(r"^\s*jne\s+(\.L\d+)\s*$", region, re.MULTILINE)
        )
        if not backedges:
            raise RuntimeError(f"{name}: timing loop backedge not found")
        target = backedges[-1].group(1)
        loop = (
            ".text\n"
            + region[region.index(target + ":") : backedges[-1].end()]
            + "\n"
        )
        loop_path = output / f"{name}.loop.s"
        loop_path.write_text(loop)
        reports[name] = {
            "source": case["source"],
            "source_sha256": sha256(source),
            "effective_flags": flags,
            "binary_sha256": sha256(binary),
            "assembly_sha256": sha256(assembly),
            "loop_text_sha256": hashlib.sha256(loop.encode()).hexdigest(),
            "loop_artifact": loop_path.name,
            "verification": {
                "returncode": verified.returncode,
                "stdout": verified.stdout,
                "stderr": verified.stderr,
                "random_cases": 100000,
                "random_state_and_constants": True,
                "round_counts": [1, 20],
                "verifier_translation_unit_cflags": [
                    "-O3", "-std=c11", "-Wall", "-Wextra", "-Wpedantic",
                    "-Werror",
                ],
            },
        }

    result = {
        "compiler": subprocess.run(
            ["gcc", "--version"], check=True, text=True, stdout=subprocess.PIPE
        ).stdout.splitlines()[0],
        "binutils": subprocess.run(
            ["ld", "--version"], check=True, text=True, stdout=subprocess.PIPE
        ).stdout.splitlines()[0],
        "reports": reports,
    }
    (output / "compile.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    """
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one exact source fragment")
    return text.replace(old, new, 1)


def generate_residency_variants(identity_source: str) -> dict[str, str]:
    """Derive the complete GCC register-residency screen from one source."""
    helper = (
        "static inline __m256i keep_in_vector_register(__m256i value) {\n"
        "    __asm__(\"\" : \"+x\"(value));\n"
        "    return value;\n"
        "}\n\n"
    )
    identity_calls = (
        "    add_forward = keep_in_vector_register(add_forward);\n"
        "    xor_forward = keep_in_vector_register(xor_forward);"
    )
    volatile_plusx = (
        "    __asm__ __volatile__(\"\" : \"+x\"(add_forward), "
        "\"+x\"(xor_forward));"
    )
    base = replace_once(identity_source, helper, "", "remove identity helper")
    base = replace_once(
        base, identity_calls, volatile_plusx, "restore volatile tied outputs"
    )
    state_inputs_x = replace_once(
        base,
        volatile_plusx,
        '    __asm__("" : "+x"(value) : "x"(add_forward), "x"(xor_forward));',
        "state input x constraints",
    )
    swapped_current = replace_once(
        replace_once(
            base,
            "_mm256_xor_si256(value, xor_forward)",
            "_mm256_xor_si256(xor_forward, value)",
            "swap xor operands",
        ),
        "_mm256_add_epi64(value, add_forward)",
        "_mm256_add_epi64(add_forward, value)",
        "swap add operands",
    )
    tied_alias = (
        "    __m256i add_register;\n"
        "    __m256i xor_register;\n"
        "    __asm__(\"\" : \"=x\"(add_register), \"=x\"(xor_register)\n"
        "               : \"0\"(add_forward), \"1\"(xor_forward));\n"
        "    add_forward = add_register;\n"
        "    xor_forward = xor_register;"
    )
    register_helpers = (
        "static inline __m256i xor_vector_register(__m256i value,\n"
        "                                                __m256i constant) {\n"
        "    __asm__(\"vpxor %2, %1, %0\" : \"=x\"(value) : "
        "\"0\"(value), \"x\"(constant));\n"
        "    return value;\n"
        "}\n\n"
        "static inline __m256i add_vector_register(__m256i value,\n"
        "                                                __m256i constant) {\n"
        "    __asm__(\"vpaddq %2, %1, %0\" : \"=x\"(value) : "
        "\"0\"(value), \"x\"(constant));\n"
        "    return value;\n"
        "}\n\n"
    )
    register_asm = replace_once(
        base,
        "static inline __m256i rotl64_lanes_avx2",
        register_helpers + "static inline __m256i rotl64_lanes_avx2",
        "insert register-operation helpers",
    )
    register_asm = replace_once(
        register_asm,
        "_mm256_xor_si256(value, xor_forward)",
        "xor_vector_register(value, xor_forward)",
        "use register xor",
    )
    register_asm = replace_once(
        register_asm,
        "_mm256_add_epi64(value, add_forward)",
        "add_vector_register(value, add_forward)",
        "use register add",
    )
    register_asm = replace_once(
        register_asm, volatile_plusx, "", "remove register-residency barrier"
    )
    register_keyword = replace_once(
        base,
        "    __m256i add_forward =\n",
        "    register __m256i add_forward =\n",
        "register add declaration",
    )
    register_keyword = replace_once(
        register_keyword,
        "    __m256i xor_forward =\n",
        "    register __m256i xor_forward =\n",
        "register xor declaration",
    )
    register_keyword = replace_once(
        register_keyword,
        volatile_plusx,
        '    __asm__("" : "+x"(value) : "x"(add_forward), "x"(xor_forward));',
        "register keyword input constraints",
    )
    variants = {
        "current_volatile_plusx": base,
        "nonvolatile_plusx": replace_once(
            base,
            volatile_plusx,
            '    __asm__("" : "+x"(add_forward), "+x"(xor_forward));',
            "nonvolatile tied outputs",
        ),
        "state_inputs_x": state_inputs_x,
        "state_inputs_v": replace_once(
            base,
            volatile_plusx,
            '    __asm__("" : "+v"(value) : "v"(add_forward), "v"(xor_forward));',
            "state input v constraints",
        ),
        "state_all_constants_x": replace_once(
            base,
            volatile_plusx,
            '    __asm__("" : "+x"(value) : "x"(add_forward), "x"(xor_forward),\n'
            '                                  "x"(add_reverse), "x"(xor_reverse));',
            "all constant input constraints",
        ),
        "tied_alias_outputs": replace_once(
            base, volatile_plusx, tied_alias, "tied alias outputs"
        ),
        "register_keyword_state_inputs": register_keyword,
        "state_inputs_memory_clobber": replace_once(
            base,
            volatile_plusx,
            '    __asm__ __volatile__("" : "+x"(value) : "x"(add_forward),\n'
            '                                           "x"(xor_forward) : "memory");',
            "state inputs with memory clobber",
        ),
        "swapped_current": swapped_current,
        "swapped_state_inputs": replace_once(
            swapped_current,
            volatile_plusx,
            '    __asm__("" : "+x"(value) : "x"(add_forward), "x"(xor_forward));',
            "swapped state input constraints",
        ),
        "identity_helper": identity_source,
        "register_asm_ops": register_asm,
    }
    if tuple(variants) != RESIDENCY_VARIANT_NAMES:
        raise RuntimeError("residency variant order or membership changed")
    return variants


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
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


def parse_cpu_list(value: str) -> list[int]:
    allowed = sorted(os.sched_getaffinity(0))
    if value == "auto":
        return [allowed[0]]
    cpus = list(dict.fromkeys(int(part) for part in value.split(",")))
    unavailable = [cpu for cpu in cpus if cpu not in allowed]
    if not cpus or unavailable:
        raise RuntimeError(f"requested CPUs are not affinity-allowed: {unavailable}")
    return cpus


def benchmark_command(
    repository: Path,
    args: argparse.Namespace,
    cpu: int,
    output: Path,
) -> list[str]:
    command = [
        sys.executable,
        str(repository / "solutions/benchmark_02_permutation.py"),
    ]
    for name, case in CASES.items():
        command.extend(["--case", f"{name}={repository / case['source']}"])
    command.extend(
        [
            "--baseline",
            "scalar",
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
            str(cpu),
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
            f"simd-amd-cpu{cpu}",
            "--json",
            str(output),
        ]
    )
    return command


def validate_timed_main_validation(
    report: dict[str, Any],
    expected_names: set[str],
    iterations: int,
    warmups: int,
    samples: int,
    label: str,
) -> None:
    if report.get("schema_version") != 5:
        raise RuntimeError(
            f"{label} report schema is not 5: {report.get('schema_version')!r}"
        )
    if report.get("config", {}).get("timed_main_repeated_call_validation") is not True:
        raise RuntimeError(f"{label} timed-main config gate is not true")
    validation = report.get("timed_main_validation")
    if not isinstance(validation, dict):
        raise RuntimeError(f"{label} report omitted timed_main_validation")
    if set(validation) != {"oracle", "cases"}:
        raise RuntimeError(f"{label} timed-main validation shape changed")
    oracle = validation.get("oracle")
    cases = validation.get("cases")
    if not isinstance(oracle, dict) or not isinstance(cases, dict):
        raise RuntimeError(f"{label} timed-main validation is malformed")
    if set(oracle) != {
        "mode",
        "iterations",
        "expected_final_state",
        "stdout_sha256",
        "status",
    }:
        raise RuntimeError(f"{label} timed-main oracle shape changed")
    if set(cases) != expected_names:
        raise RuntimeError(
            f"{label} timed-main case set changed: {sorted(cases)!r}"
        )
    expected_state = oracle.get("expected_final_state")
    valid_state = (
        isinstance(expected_state, list)
        and len(expected_state) == 4
        and all(
            isinstance(word, str) and re.fullmatch(r"[0-9a-f]{16}", word)
            for word in expected_state
        )
    )
    canonical_oracle_hash = (
        hashlib.sha256(
            (
                f"oracle_final_state_iterations={iterations}\n"
                f"oracle_final_state={' '.join(expected_state)}\n"
            ).encode()
        ).hexdigest()
        if valid_state
        else None
    )
    if not (
        oracle.get("mode") == "independent-reference-repeated-20-rounds"
        and type(oracle.get("iterations")) is int
        and oracle.get("iterations") == iterations
        and iterations > 0
        and valid_state
        and isinstance(oracle.get("stdout_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", oracle["stdout_sha256"])
        and oracle.get("stdout_sha256") == canonical_oracle_hash
        and oracle.get("status") == "PASS"
    ):
        raise RuntimeError(f"{label} timed-main oracle did not pass")
    validated_processes = 1 + warmups + samples
    for name, case in cases.items():
        if isinstance(case, dict) and set(case) != {
            "iterations",
            "observed_final_state",
            "preflight_processes",
            "warmup_processes",
            "measured_processes",
            "validated_processes",
            "status",
        }:
            raise RuntimeError(f"{label} {name}: timed-main case shape changed")
        if not isinstance(case, dict) or not (
            all(
                type(case.get(field)) is int
                for field in (
                    "iterations",
                    "preflight_processes",
                    "warmup_processes",
                    "measured_processes",
                    "validated_processes",
                )
            )
            and case.get("iterations") == iterations
            and case.get("observed_final_state") == expected_state
            and case.get("preflight_processes") == 1
            and case.get("warmup_processes") == warmups
            and case.get("measured_processes") == samples
            and case.get("validated_processes") == validated_processes
            and case.get("status") == "PASS"
        ):
            raise RuntimeError(f"{label} {name}: timed-main validation failed")


def validate_host_report(report: dict[str, Any], args: argparse.Namespace) -> None:
    validate_timed_main_validation(
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
    }
    for key, expected in expected_config.items():
        if report.get("config", {}).get(key) != expected:
            raise RuntimeError(f"host report config {key} does not equal {expected}")
    for name in CASES:
        verification = report.get("candidate_verification", {}).get(name, {})
        if not (
            verification.get("status") == "PASS"
            and verification.get("random_cases") == args.random_cases
            and verification.get("random_state_and_constants") is True
            and verification.get("round_counts") == [1, 20]
            and verification.get("verifier_only_flag_overrides") == []
            and verification.get("verifier_translation_unit_cflags")
            == VERIFIER_TU_FLAGS
        ):
            raise RuntimeError(f"{name}: exact candidate verification did not pass")
        source = report.get("sources", {}).get(name, {})
        allowed_hashes = {EXPECTED_SOURCE_HASHES[name]}
        if name == "avx2":
            allowed_hashes.add(PRE_HOIST_AVX2_SHA256)
        if source.get("sha256") not in allowed_hashes:
            raise RuntimeError(f"{name}: measured source hash changed")
        audit = report.get("assembly_audits", {}).get(name, {})
        if audit.get("status") != "PASS":
            raise RuntimeError(f"{name}: measured binary audit failed")
    for name in ("avx2", "sse2"):
        comparison = report.get("comparisons", {}).get(name, {})
        if any(
            not isinstance(comparison.get(key), (int, float))
            or not math.isfinite(float(comparison[key]))
            for key in (
                "paired_median",
                "paired_bootstrap_ci95_low",
                "paired_bootstrap_ci95_high",
            )
        ):
            raise RuntimeError(f"{name}: paired comparison is malformed")


def compact_host_report(
    report: dict[str, Any], artifact_sha256: str
) -> dict[str, Any]:
    compact = {
        "artifact_sha256": artifact_sha256,
        "schema_version": report["schema_version"],
        "campaign_id": report["campaign_id"],
        "measurement_protocol_fingerprint_sha256": report[
            "measurement_protocol"
        ]["fingerprint_sha256"],
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
    avx2_hash = report["sources"]["avx2"]["sha256"]
    compact["avx2_source_revision"] = (
        "pre_identity_helper"
        if avx2_hash == PRE_HOIST_AVX2_SHA256
        else "identity_helper"
    )
    return compact


def hoist_benchmark_command(
    repository: Path,
    args: argparse.Namespace,
    cpu: int,
    pre_hoist_source: Path,
    output: Path,
) -> list[str]:
    benchmark = repository / "solutions/benchmark_02_permutation.py"
    command = [
        sys.executable,
        str(benchmark),
        "--case",
        f"scalar={repository / CASES['scalar']['source']}",
        "--case",
        f"avx2_current={pre_hoist_source}",
        "--case",
        f"avx2_hoisted={repository / CASES['avx2']['source']}",
        "--baseline",
        "scalar",
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
        str(cpu),
        "--extra-cflag=-Werror",
    ]
    for name in ("avx2_current", "avx2_hoisted"):
        for flag in CASES["avx2"]["cflags"]:
            command.extend(["--case-cflag", f"{name}={flag}"])
        command.extend(["--audit-mode", f"{name}=report-only"])
    for flag in CASES["scalar"]["cflags"]:
        command.extend(["--case-cflag", f"scalar={flag}"])
    command.extend(
        [
            "--audit-mode",
            "scalar=full-inline-320",
            "--campaign-id",
            f"simd-hoist-cpu{cpu}",
            "--json",
            str(output),
        ]
    )
    return command


def validate_hoist_report(
    report: dict[str, Any], args: argparse.Namespace, cpu: int
) -> None:
    expected_hashes = {
        "scalar": EXPECTED_SOURCE_HASHES["scalar"],
        "avx2_current": PRE_HOIST_AVX2_SHA256,
        "avx2_hoisted": EXPECTED_SOURCE_HASHES["avx2"],
    }
    validate_timed_main_validation(
        report,
        set(expected_hashes),
        args.iterations,
        args.warmups,
        args.samples,
        "hoist",
    )
    expected_config = {
        "iterations": args.iterations,
        "warmups": args.warmups,
        "samples_per_case": args.samples,
        "candidate_random_differential_cases": args.random_cases,
    }
    for key, expected in expected_config.items():
        if report.get("config", {}).get(key) != expected:
            raise RuntimeError(f"hoist report config {key} does not equal {expected}")
    if report.get("environment", {}).get("affinity") != [cpu]:
        raise RuntimeError("hoist report did not run only on its requested CPU")
    for name, expected_hash in expected_hashes.items():
        if report.get("sources", {}).get(name, {}).get("sha256") != expected_hash:
            raise RuntimeError(f"{name}: hoist report source hash changed")
        verification = report.get("candidate_verification", {}).get(name, {})
        if not (
            verification.get("status") == "PASS"
            and verification.get("random_cases") == args.random_cases
            and verification.get("random_state_and_constants") is True
            and verification.get("round_counts") == [1, 20]
            and verification.get("verifier_only_flag_overrides") == []
            and verification.get("verifier_translation_unit_cflags")
            == VERIFIER_TU_FLAGS
        ):
            raise RuntimeError(f"{name}: hoist candidate verification did not pass")
        if report.get("assembly_audits", {}).get(name, {}).get("status") != "PASS":
            raise RuntimeError(f"{name}: hoist measured binary audit failed")
    for name in expected_hashes:
        values = report.get("internal_ns_per_20round", {}).get(name)
        if not isinstance(values, list) or len(values) != args.samples:
            raise RuntimeError(f"{name}: hoist sample count changed")


def direct_paired_hoist_comparison(report: dict[str, Any]) -> dict[str, Any]:
    current = report["internal_ns_per_20round"]["avx2_current"]
    hoisted = report["internal_ns_per_20round"]["avx2_hoisted"]
    paired = [before / after for before, after in zip(current, hoisted)]
    median = statistics.median(paired)
    vingtiles = statistics.quantiles(paired, n=20, method="inclusive")
    bootstrap_seed = 0xD1B54A32D192ED05
    generator = random.Random(bootstrap_seed)
    bootstrap = sorted(
        statistics.median(generator.choices(paired, k=len(paired)))
        for _ in range(5_000)
    )
    return {
        "baseline": "avx2_current",
        "candidate": "avx2_hoisted",
        "speedup_definition": "current_ns / hoisted_ns",
        "samples": len(paired),
        "ratio_of_medians": statistics.median(current) / statistics.median(hoisted),
        "paired_median": median,
        "paired_mad": statistics.median(abs(value - median) for value in paired),
        "paired_p05": vingtiles[0],
        "paired_p95": vingtiles[18],
        "bootstrap_resamples": 5_000,
        "bootstrap_seed": f"0x{bootstrap_seed:016x}",
        "paired_bootstrap_ci95_low": bootstrap[124],
        "paired_bootstrap_ci95_high": bootstrap[4_874],
        "conclusion": (
            "statistical tie: the paired 95% bootstrap interval includes 1.0"
        ),
    }


def compact_hoist_report(
    report: dict[str, Any], artifact_sha256: str
) -> dict[str, Any]:
    return {
        "artifact_sha256": artifact_sha256,
        "schema_version": report["schema_version"],
        "campaign_id": report["campaign_id"],
        "measurement_protocol_fingerprint_sha256": report[
            "measurement_protocol"
        ]["fingerprint_sha256"],
        "environment": report["environment"],
        "config": report["config"],
        "sources": report["sources"],
        "candidate_verification": report["candidate_verification"],
        "timed_main_validation": report["timed_main_validation"],
        "assembly_audits": report["assembly_audits"],
        "summaries": report["summaries"],
        "comparisons_against_scalar": report["comparisons"],
        "direct_hoisted_vs_current": direct_paired_hoist_comparison(report),
        "internal_ns_per_20round": report["internal_ns_per_20round"],
        "outer_wall_seconds": report["outer_wall_seconds"],
    }


def extract_number(output: str, label: str) -> float:
    match = re.search(
        rf"^{re.escape(label)}:\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"llvm-mca output omitted {label!r}")
    return float(match.group(1))


def analyse_loop(llvm_mca: str, loop: Path, model: str) -> dict[str, Any]:
    completed = run_checked(
        [llvm_mca, f"-mcpu={model}", "-iterations=100", str(loop)]
    )
    cycles = extract_number(completed.stdout, "Total Cycles")
    return {
        "iterations": 100,
        "total_cycles": int(cycles),
        "cycles_per_iteration": cycles / 100.0,
        "instructions_per_iteration": extract_number(
            completed.stdout, "Instructions"
        )
        / 100.0,
        "uops_per_iteration": extract_number(completed.stdout, "Total uOps")
        / 100.0,
        "block_rthroughput": extract_number(completed.stdout, "Block RThroughput"),
    }


def simd_operation_counts(mnemonics: dict[str, int]) -> dict[str, int]:
    selected = (
        "vpsllvq",
        "vpsrlvq",
        "vpor",
        "vpxor",
        "vpshufb",
        "vpaddq",
        "psllq",
        "psrlq",
        "psllw",
        "psrlw",
        "por",
        "pxor",
        "xorpd",
        "pshufd",
        "pshuflw",
        "pshufhw",
        "shufpd",
        "paddq",
        "movdqa",
        "movapd",
        "movsd",
    )
    return {name: mnemonics.get(name, 0) for name in selected if mnemonics.get(name)}


def static_screen(
    repository: Path, args: argparse.Namespace, temporary: Path
) -> dict[str, Any]:
    artifacts = temporary / "static"
    artifacts.mkdir()
    manifest = {"cases": CASES}
    (temporary / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    image_id = run_checked(
        [args.runtime, "image", "inspect", "--format", "{{.Id}}", IMAGE]
    ).stdout.strip()
    run_checked(
        [
            args.runtime,
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{repository}:/repository:ro",
            "--volume",
            f"{temporary}:/config:ro",
            "--volume",
            f"{artifacts}:/output",
            IMAGE,
            "python3",
            "-c",
            CONTAINER_DRIVER,
        ]
    )
    compiled = json.loads((artifacts / "compile.json").read_text())
    sys.path.insert(0, str(repository / "solutions"))
    from challenge02_loop_audit import (  # pylint: disable=import-outside-toplevel
        audit_main_timing_loop,
        validate_loop_audit,
    )

    for name, report in compiled["reports"].items():
        loop = artifacts / report.pop("loop_artifact")
        report["llvm_mca"] = {
            model: analyse_loop(args.llvm_mca, loop, model) for model in MODELS
        }
        audit = audit_main_timing_loop(artifacts / name)
        mode = CASES[name]["audit_mode"]
        errors = validate_loop_audit(audit, mode)
        report["binary_audit"] = {
            **audit,
            "mode": mode,
            "status": "PASS" if not errors else "FAIL",
            "errors": errors,
            "selected_simd_operation_counts": simd_operation_counts(
                audit["mnemonics"]
            ),
        }
    return {
        "container": {
            "image": IMAGE,
            "pinned_manifest_digest_sha256": IMAGE_DIGEST,
            "local_image_id": image_id,
            "network": "none",
            "repository_mount": "read-only",
        },
        "compiler": compiled["compiler"],
        "binutils": compiled["binutils"],
        "llvm_mca": {
            "executable": args.llvm_mca,
            "version": run_checked([args.llvm_mca, "--version"]).stdout.splitlines()[
                0
            ],
            "models": list(MODELS),
            "qualification": (
                "static scheduler models only; neither model is Lion Cove or Skymont"
            ),
        },
        "cases": compiled["reports"],
    }


def run_residency_static_screen(
    repository: Path,
    args: argparse.Namespace,
    temporary: Path,
    variant_sources: Path,
) -> dict[str, Any]:
    artifacts = temporary / "residency-static"
    artifacts.mkdir()
    config = temporary / "residency-config"
    config.mkdir()
    cflags = CASES["avx2"]["cflags"]
    manifest = {
        "cases": {
            name: {
                "source": f"/variants/{name}.c",
                "cflags": cflags,
                "audit_mode": "report-only",
            }
            for name in RESIDENCY_VARIANT_NAMES
        }
    }
    (config / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    run_checked(
        [
            args.runtime,
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{repository}:/repository:ro",
            "--volume",
            f"{variant_sources}:/variants:ro",
            "--volume",
            f"{config}:/config:ro",
            "--volume",
            f"{artifacts}:/output",
            IMAGE,
            "python3",
            "-c",
            CONTAINER_DRIVER,
        ]
    )
    compiled = json.loads((artifacts / "compile.json").read_text())
    sys.path.insert(0, str(repository / "solutions"))
    from challenge02_loop_audit import (  # pylint: disable=import-outside-toplevel
        audit_main_timing_loop,
        validate_loop_audit,
    )

    reports: dict[str, Any] = {}
    audit_keys = (
        "binary_sha256",
        "calls",
        "loop_bytes",
        "loop_instructions",
        "memory_operands_excluding_lea",
        "mnemonics",
        "normalized_loop_sha256",
        "push_pop",
    )
    for name in RESIDENCY_VARIANT_NAMES:
        compiled_report = compiled["reports"][name]
        loop = artifacts / compiled_report["loop_artifact"]
        audit = audit_main_timing_loop(artifacts / name)
        errors = validate_loop_audit(audit, "report-only")
        mca: dict[str, Any] = {}
        for model in MODELS:
            analysis = analyse_loop(args.llvm_mca, loop, model)
            mca[model] = {
                "cycles": analysis["cycles_per_iteration"],
                "instructions": int(analysis["instructions_per_iteration"]),
                "rthroughput": analysis["block_rthroughput"],
                "uops": int(analysis["uops_per_iteration"]),
            }
        verification = compiled_report["verification"]
        verification_compact = {
            "returncode": verification["returncode"],
            "stdout": verification["stdout"],
            "stderr": verification["stderr"],
        }
        reports[name] = {
            "status": "PASS",
            "source_sha256": compiled_report["source_sha256"],
            "binary_sha256": compiled_report["binary_sha256"],
            "assembly_sha256": compiled_report["assembly_sha256"],
            "loop_text_sha256": compiled_report["loop_text_sha256"],
            "verification": verification_compact,
            "verification_pass": (
                verification_compact["returncode"] == 0
                and verification_compact["stdout"] == EXPECTED_VERIFIER_STDOUT
                and verification_compact["stderr"] == ""
            ),
            "audit": {
                **{key: audit[key] for key in audit_keys},
                "status": "PASS" if not errors else "FAIL",
                "errors": errors,
            },
            "llvm_mca": mca,
        }
    return {"compiler": compiled["compiler"], "reports": reports}


def validate_and_enrich_residency_screen(
    raw: dict[str, Any],
    variants: dict[str, str],
    artifact_sha256: str | None,
) -> dict[str, Any]:
    if raw.get("compiler") != "gcc (GCC) 13.3.0":
        raise RuntimeError("residency screen did not use exact GCC 13.3.0")
    reports = raw.get("reports", {})
    if tuple(reports) != RESIDENCY_VARIANT_NAMES:
        if set(reports) != set(RESIDENCY_VARIANT_NAMES):
            raise RuntimeError("residency screen variants changed")
    outcomes: dict[str, Any] = {}
    loop_hashes: set[str] = set()
    for name in RESIDENCY_VARIANT_NAMES:
        report = reports[name]
        expected_source_hash = hashlib.sha256(variants[name].encode()).hexdigest()
        if report.get("source_sha256") != expected_source_hash:
            raise RuntimeError(f"{name}: generated source hash changed")
        verification = report.get("verification", {})
        if not (
            report.get("status") == "PASS"
            and report.get("verification_pass") is True
            and verification.get("returncode") == 0
            and verification.get("stdout") == EXPECTED_VERIFIER_STDOUT
            and verification.get("stderr") == ""
        ):
            raise RuntimeError(f"{name}: dynamic-constant verification failed")
        audit = report.get("audit", {})
        if not (
            audit.get("status") == "PASS"
            and audit.get("errors") == []
            and audit.get("calls") == 0
            and audit.get("push_pop") == 0
        ):
            raise RuntimeError(f"{name}: complete measured-binary audit failed")
        if not all(model in report.get("llvm_mca", {}) for model in MODELS):
            raise RuntimeError(f"{name}: LLVM-MCA model result missing")
        loop_hash = report.get("loop_text_sha256")
        if not isinstance(loop_hash, str) or len(loop_hash) != 64:
            raise RuntimeError(f"{name}: loop hash missing")
        loop_hashes.add(loop_hash)
        outcomes[name] = {
            **report,
            **RESIDENCY_VARIANT_NOTES[name],
            "outcome": "SELECTED_CODEGEN" if name == "identity_helper" else "REJECTED",
        }
    selected = outcomes["identity_helper"]
    previous = outcomes["current_volatile_plusx"]
    if not (
        selected["audit"]["memory_operands_excluding_lea"] == 0
        and previous["audit"]["memory_operands_excluding_lea"] == 2
        and selected["audit"]["loop_instructions"]
        < previous["audit"]["loop_instructions"]
        and selected["audit"]["loop_bytes"] < previous["audit"]["loop_bytes"]
    ):
        raise RuntimeError("selected identity helper no longer improves machine code")
    return {
        "input_artifact_sha256": artifact_sha256,
        "compiler": raw["compiler"],
        "cflags": ["-O3", "-Wall", "-Wextra", "-Werror", *CASES["avx2"]["cflags"]],
        "protocol": {
            "generated_from": CASES["avx2"]["source"],
            "generated_from_sha256": EXPECTED_SOURCE_HASHES["avx2"],
            "candidate_random_state_and_constants": 100_000,
            "round_counts": [1, 20],
            "audit_scope": "complete candidate binary, report-only loop contract",
            "llvm_mca_models": list(MODELS),
            "screen_order": "pinned GCC 13.3 plus LLVM-MCA before host timing",
        },
        "counts": {
            "attempted": len(RESIDENCY_VARIANT_NAMES),
            "compiled": len(RESIDENCY_VARIANT_NAMES),
            "dynamic_verification_passed": len(RESIDENCY_VARIANT_NAMES),
            "complete_binary_audit_passed": len(RESIDENCY_VARIANT_NAMES),
            "selected": 1,
            "rejected": len(RESIDENCY_VARIANT_NAMES) - 1,
            "unique_loop_text_hashes": len(loop_hashes),
        },
        "selected": "identity_helper",
        "machine_code_delta_vs_current": {
            "loop_instructions": (
                selected["audit"]["loop_instructions"]
                - previous["audit"]["loop_instructions"]
            ),
            "loop_bytes": selected["audit"]["loop_bytes"] - previous["audit"]["loop_bytes"],
            "memory_operands_excluding_lea": (
                selected["audit"]["memory_operands_excluding_lea"]
                - previous["audit"]["memory_operands_excluding_lea"]
            ),
            "alderlake_mca_cycles": (
                round(
                    selected["llvm_mca"]["alderlake"]["cycles"]
                    - previous["llvm_mca"]["alderlake"]["cycles"],
                    2,
                )
            ),
            "znver2_mca_cycles": (
                round(
                    selected["llvm_mca"]["znver2"]["cycles"]
                    - previous["llvm_mca"]["znver2"]["cycles"],
                    2,
                )
            ),
        },
        "variant_outcomes": outcomes,
    }


def replace_static_avx2_with_selected_residency(
    static: dict[str, Any], residency_raw: dict[str, Any]
) -> dict[str, Any]:
    selected = residency_raw["reports"]["identity_helper"]
    audit = selected["audit"]
    verification = selected["verification"]
    static = json.loads(json.dumps(static))
    static["cases"]["avx2"] = {
        "source": CASES["avx2"]["source"],
        "source_sha256": selected["source_sha256"],
        "effective_flags": [
            "-O3",
            "-Wall",
            "-Wextra",
            "-Werror",
            *CASES["avx2"]["cflags"],
        ],
        "binary_sha256": selected["binary_sha256"],
        "assembly_sha256": selected["assembly_sha256"],
        "loop_text_sha256": selected["loop_text_sha256"],
        "provenance": "constant_residency_screen.identity_helper",
        "verification": {
            **verification,
            "random_cases": 100_000,
            "random_state_and_constants": True,
            "round_counts": [1, 20],
            "verifier_translation_unit_cflags": VERIFIER_TU_FLAGS,
        },
        "binary_audit": {
            **audit,
            "mode": "report-only",
            "selected_simd_operation_counts": simd_operation_counts(
                audit["mnemonics"]
            ),
        },
        "llvm_mca": {
            model: {
                "iterations": 100,
                "total_cycles": int(round(result["cycles"] * 100)),
                "cycles_per_iteration": result["cycles"],
                "instructions_per_iteration": result["instructions"],
                "uops_per_iteration": result["uops"],
                "block_rthroughput": result["rthroughput"],
            }
            for model, result in selected["llvm_mca"].items()
        },
    }
    return static


def parse_host_json(values: list[str]) -> dict[int, Path]:
    parsed: dict[int, Path] = {}
    for value in values:
        cpu_text, separator, path_text = value.partition("=")
        if not separator:
            raise RuntimeError("--host-json must be CPU=PATH")
        parsed[int(cpu_text)] = Path(path_text).resolve()
    return parsed


def run_experiment(args: argparse.Namespace) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[2]
    for name, case in CASES.items():
        actual = sha256_file(repository / case["source"])
        if actual != EXPECTED_SOURCE_HASHES[name]:
            raise RuntimeError(f"{name}: expected source hash changed: {actual}")
    if (
        (args.static_json is None or args.residency_json is None)
        and (shutil.which(args.runtime) is None or shutil.which(args.llvm_mca) is None)
    ):
        raise RuntimeError("docker and llvm-mca-16 are required")
    imported = parse_host_json(args.host_json)
    cpus = sorted(imported) if imported else parse_cpu_list(args.cpus)
    hoist_cpus = parse_cpu_list(args.hoist_cpu)
    if len(hoist_cpus) != 1:
        raise RuntimeError("--hoist-cpu must select exactly one logical CPU")
    hoist_cpu = hoist_cpus[0]
    host_reports: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="challenge02-simd-") as name:
        temporary = Path(name).resolve()
        identity_source = (repository / CASES["avx2"]["source"]).read_text()
        variants = generate_residency_variants(identity_source)
        variant_sources = temporary / "residency-sources"
        variant_sources.mkdir()
        for variant_name, source in variants.items():
            (variant_sources / f"{variant_name}.c").write_text(source)
        for cpu in cpus:
            if cpu in imported:
                path = imported[cpu]
            else:
                path = temporary / f"host-cpu{cpu}.json"
                run_checked(benchmark_command(repository, args, cpu, path))
            report = json.loads(path.read_text())
            validate_host_report(report, args)
            affinity = report.get("environment", {}).get("affinity")
            if affinity != [cpu]:
                raise RuntimeError(f"host report affinity {affinity!r} != [{cpu}]")
            host_reports.append(compact_host_report(report, sha256_file(path)))
        if args.residency_json is not None:
            residency_path = args.residency_json.resolve()
            residency_raw = json.loads(residency_path.read_text())
            residency_artifact_hash: str | None = sha256_file(residency_path)
        else:
            residency_raw = run_residency_static_screen(
                repository, args, temporary, variant_sources
            )
            residency_artifact_hash = None
        residency = validate_and_enrich_residency_screen(
            residency_raw, variants, residency_artifact_hash
        )
        if args.static_json is not None:
            static_path = args.static_json.resolve()
            static_document = json.loads(static_path.read_text())
            static = static_document.get("static_analysis", static_document)
            static = json.loads(json.dumps(static))
            static.pop("input_artifact_sha256", None)
        else:
            static = static_screen(repository, args, temporary)
        static = replace_static_avx2_with_selected_residency(static, residency_raw)
        if args.hoist_json is not None:
            hoist_path = args.hoist_json.resolve()
        else:
            hoist_path = temporary / f"hoist-cpu{hoist_cpu}.json"
            run_checked(
                hoist_benchmark_command(
                    repository,
                    args,
                    hoist_cpu,
                    variant_sources / "current_volatile_plusx.c",
                    hoist_path,
                )
            )
        hoist_raw = json.loads(hoist_path.read_text())
        validate_hoist_report(hoist_raw, args, hoist_cpu)
        hoist_confirmation = compact_hoist_report(
            hoist_raw, sha256_file(hoist_path)
        )

    checks = {
        "source_hashes_match": all(
            sha256_file(repository / case["source"])
            == EXPECTED_SOURCE_HASHES[name]
            for name, case in CASES.items()
        ),
        "host_random_state_and_constants_100k_passed": all(
            verification["status"] == "PASS"
            and verification["random_cases"] == args.random_cases
            and verification["round_counts"] == [1, 20]
            and verification["random_state_and_constants"] is True
            for host in host_reports
            for verification in host["candidate_verification"].values()
        ),
        "host_timed_main_validations_passed": all(
            host["schema_version"] == 5
            and host["timed_main_validation"]["oracle"]["status"] == "PASS"
            and all(
                validation["status"] == "PASS"
                for validation in host["timed_main_validation"]["cases"].values()
            )
            for host in host_reports
        ),
        "host_measured_binary_audits_passed": all(
            audit["status"] == "PASS"
            for host in host_reports
            for audit in host["assembly_audits"].values()
        ),
        "pinned_gcc_is_exact_13_3_0": static["compiler"] == "gcc (GCC) 13.3.0",
        "pinned_gcc_random_state_and_constants_100k_passed": all(
            case["verification"]["returncode"] == 0
            and case["verification"]["stderr"] == ""
            and case["verification"]["stdout"] == EXPECTED_VERIFIER_STDOUT
            for case in static["cases"].values()
        ),
        "static_binary_audits_passed": all(
            case["binary_audit"]["status"] == "PASS"
            for case in static["cases"].values()
        ),
        "simd_loops_have_no_calls_or_push_pop": all(
            static["cases"][name]["binary_audit"]["calls"] == 0
            and static["cases"][name]["binary_audit"]["push_pop"] == 0
            for name in ("avx2", "sse2")
        ),
        "all_12_residency_variants_verified_and_audited": (
            residency["counts"]["attempted"] == 12
            and residency["counts"]["dynamic_verification_passed"] == 12
            and residency["counts"]["complete_binary_audit_passed"] == 12
            and residency["counts"]["rejected"] == 11
        ),
        "identity_helper_removes_timed_loop_memory_operands": (
            residency["variant_outcomes"]["identity_helper"]["audit"][
                "memory_operands_excluding_lea"
            ]
            == 0
        ),
        "hoist_confirmation_used_only_requested_cpu": (
            hoist_confirmation["environment"]["affinity"] == [hoist_cpu]
        ),
        "hoist_confirmation_verified_all_dynamic_candidates": all(
            verification["status"] == "PASS"
            and verification["random_cases"] == args.random_cases
            and verification["random_state_and_constants"] is True
            and verification["round_counts"] == [1, 20]
            for verification in hoist_confirmation[
                "candidate_verification"
            ].values()
        ),
        "hoist_confirmation_timed_main_validations_passed": (
            hoist_confirmation["schema_version"] == 5
            and hoist_confirmation["timed_main_validation"]["oracle"]["status"]
            == "PASS"
            and all(
                validation["status"] == "PASS"
                for validation in hoist_confirmation["timed_main_validation"][
                    "cases"
                ].values()
            )
        ),
        "hoisted_vs_current_runtime_ci_includes_tie": (
            hoist_confirmation["direct_hoisted_vs_current"][
                "paired_bootstrap_ci95_low"
            ]
            <= 1.0
            <= hoist_confirmation["direct_hoisted_vs_current"][
                "paired_bootstrap_ci95_high"
            ]
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(
            "SIMD checks failed: "
            + ", ".join(name for name, passed in checks.items() if not passed)
        )
    return {
        "schema_version": 2,
        "experiment": "challenge02_lane_wise_simd_screen",
        "candidate_designs": {
            "avx2": (
                "four independent two-round chains in four YMM lanes; each "
                "lane-wise rotate is VPSLLVQ+VPSRLVQ+VPOR; two non-volatile "
                "+x identity helpers keep dynamic forward constants resident "
                "and eliminate all timed-loop memory operands under GCC 13.3"
            ),
            "sse2": (
                "two chains per XMM; compute both immediate rotates and select "
                "lanes, with five-instruction SSE2 byte swap"
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
        "host_measurement": {
            "qualification": (
                "historical pre-identity-helper balanced measurements on two AMD "
                "CPUs; retained for SIMD-versus-scalar context, not 255H evidence"
            ),
            "runs": host_reports,
        },
        "constant_residency_screen": residency,
        "constant_residency_host_confirmation": {
            "qualification": (
                "CPU-pinned balanced AMD host confirmation after the pinned GCC "
                "static screen; it establishes a runtime tie, not a 255H speedup"
            ),
            **hoist_confirmation,
        },
        "static_analysis": static,
        "checks": checks,
        "all_checks_passed": True,
        "decision": {
            "sse2": "rejected: much larger loop and slower on both AMD CPUs",
            "avx2": (
                "identity helper selected for strictly better GCC 13.3 machine "
                "code; direct CPU 2 runtime is a statistical tie, and scalar is "
                "faster there, so 255H P/E/LP-E confirmation is still required"
            ),
            "adoption": "deferred pending independent Intel Core Ultra 7 255H runs",
        },
        "interpretation": [
            "AVX2 reduces instruction count but merges four scalar dependency chains into one vector chain.",
            "The identity-helper form removes the final two vmovdqa operations from the GCC 13.3 timed loop: 124 to 122 instructions and 587 to 579 bytes.",
            "All twelve register-constraint variants passed 100,000 random dynamic state/constant cases for one and twenty rounds and complete-binary audits; eleven were rejected on code generation, not correctness.",
            "On CPU 2, hoisted versus prior AVX2 measured 1.0013x with a 95% paired bootstrap interval of 0.9983x to 1.0039x, so no runtime improvement is claimed.",
            "LLVM-MCA's approximate models are used only to screen machine code and are not treated as timing evidence for the 255H.",
            "SSE2 lacks per-lane variable shifts and PSHUFB, so selection, shuffle, and register-copy overhead dominate.",
            "Static models and AMD measurements are deliberately reported separately and cannot substitute for 255H data.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", default="gcc")
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--llvm-mca", default="llvm-mca-16")
    parser.add_argument("--cpus", default="auto")
    parser.add_argument("--iterations", type=int, default=3_000_000)
    parser.add_argument("--warmups", type=int, default=6)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument(
        "--host-json",
        action="append",
        default=[],
        metavar="CPU=PATH",
        help="reuse and validate a full benchmark JSON instead of rerunning that CPU",
    )
    parser.add_argument(
        "--static-json",
        type=Path,
        help=(
            "reuse the static_analysis object in an earlier result; the AVX2 case "
            "is replaced by the selected residency-screen binary"
        ),
    )
    parser.add_argument(
        "--residency-json",
        type=Path,
        help="reuse and validate a full pinned-GCC 12-variant residency screen",
    )
    parser.add_argument(
        "--hoist-json",
        type=Path,
        help="reuse and validate the direct current/hoisted/scalar host campaign",
    )
    parser.add_argument(
        "--hoist-cpu",
        default="2",
        help="single logical CPU for the direct hoist campaign (default: 2)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(__file__).with_name("simd_results_02.json"),
    )
    args = parser.parse_args()
    result = run_experiment(args)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    for host in result["host_measurement"]["runs"]:
        cpu = host["environment"]["affinity"][0]
        avx2 = host["comparisons"]["avx2"]
        sse2 = host["comparisons"]["sse2"]
        print(
            f"cpu={cpu} avx2={avx2['paired_median']:.3f}x "
            f"[{avx2['paired_bootstrap_ci95_low']:.3f},"
            f"{avx2['paired_bootstrap_ci95_high']:.3f}] "
            f"sse2={sse2['paired_median']:.3f}x "
            f"[{sse2['paired_bootstrap_ci95_low']:.3f},"
            f"{sse2['paired_bootstrap_ci95_high']:.3f}]"
        )
    for name, case in result["static_analysis"]["cases"].items():
        audit = case["binary_audit"]
        alder = case["llvm_mca"]["alderlake"]
        print(
            f"static={name} instructions={audit['loop_instructions']} "
            f"bytes={audit['loop_bytes']} alder_cycles={alder['cycles_per_iteration']:.2f}"
        )
    direct = result["constant_residency_host_confirmation"][
        "direct_hoisted_vs_current"
    ]
    print(
        f"hoisted_vs_current={direct['paired_median']:.6f}x "
        f"[{direct['paired_bootstrap_ci95_low']:.6f},"
        f"{direct['paired_bootstrap_ci95_high']:.6f}] conclusion=TIE"
    )
    residency = result["constant_residency_screen"]
    print(
        f"residency_attempted={residency['counts']['attempted']} "
        f"selected={residency['selected']} "
        f"rejected={residency['counts']['rejected']}"
    )
    print("adoption=DEFERRED_255H")
    print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
