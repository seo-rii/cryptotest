#!/usr/bin/env python3
"""Reproducible static code-generation screen for challenge 2's AVX2 core.

This deliberately performs no host timing.  It compiles the complete contest
binary, audits the final clock-delimited loop, feeds that exact loop to the
available LLVM-MCA proxy models, and runs the 100k-case dynamic-constant
differential verifier only for the Pareto shortlist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "solutions"))

from challenge02_loop_audit import audit_main_timing_loop  # noqa: E402


SOURCE_RELATIVE = "solutions/02_optimization/contest_simd_avx2_lanewise.c"
SOURCE = ROOT / SOURCE_RELATIVE
SOURCE_SHA256 = "3a8273cb6f381efb30fb4e104a9741acf158307714216f2a2b2d8c1756b9d751"
VERIFIER_RELATIVE = "solutions/02_optimization/verify_contest_candidate_02.c"
VERIFIER = ROOT / VERIFIER_RELATIVE
VERIFIER_SHA256 = "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35"

IMAGE_DIGEST = "1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
IMAGE = f"gcc@sha256:{IMAGE_DIGEST}"
DEFAULT_CLANG = Path(
    "/home/seorii/.local/share/swiftly/toolchains/6.3.3/usr/bin/clang-21"
)
DEFAULT_OBJDUMP = Path("/usr/bin/x86_64-linux-gnu-objdump")
DEFAULT_SIZE = Path("/usr/bin/x86_64-linux-gnu-size")
DEFAULT_LLVM_MCA = Path("/usr/bin/llvm-mca-16")

COMMON_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-mavx2",
    "-DCH2_SIMD_INLINE",
    "-finline-limit=2000",
]
CLANG_COMMON_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-Wno-unused-function",
    "-mavx2",
    "-mbmi2",
    "-DCH2_SIMD_INLINE",
    "-mllvm",
    "-inline-threshold=2000",
]
EXPECTED_VERIFIER_STDOUT = """candidate_random_differential_cases=100000
candidate_random_seed=0x243f6a8885a308d3
candidate_random_state_and_constants=PASS
candidate_round_counts=1,20
candidate_differential=PASS
"""

MCA_MODELS = {
    "alderlake_p_core_proxy": "alderlake",
    "znver2_cross_architecture_proxy": "znver2",
}
MCA_ITERATIONS = 100

PRIMARY_DOCUMENTATION = [
    {
        "title": "GCC 13.3 x86 options",
        "url": "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/x86-Options.html",
        "used_for": "-march and -mtune target semantics and GCC 13 CPU-name scope",
    },
    {
        "title": "GCC optimization options",
        "url": "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/Optimize-Options.html",
        "used_for": "scheduler, IRA, register-renaming, and loop-alignment controls",
    },
    {
        "title": "Clang command-line argument reference",
        "url": "https://clang.llvm.org/docs/ClangCommandLineReference.html",
        "used_for": "X86 -march/-mtune and loop-alignment controls",
    },
    {
        "title": "LLVM llvm-mca command guide",
        "url": "https://llvm.org/docs/CommandGuide/llvm-mca.html",
        "used_for": "static scheduling-model interpretation and limitations",
    },
    {
        "title": "LLVM X86 target parser",
        "url": (
            "https://github.com/llvm/llvm-project/blob/main/llvm/include/llvm/"
            "TargetParser/X86TargetParser.def"
        ),
        "used_for": "Arrow Lake, Lunar Lake, and Panther Lake CPU spellings",
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"command failed ({completed.returncode}): "
            f"{subprocess.list2cmdline(command)}\n{detail}"
        )
    return completed


def normalize_diagnostic(text: str, temporary: Path) -> str:
    normalized = text.replace(str(temporary), "<temporary>")
    normalized = normalized.replace(str(ROOT), "<repository>")
    lines = [line for line in normalized.strip().splitlines() if line.strip()]
    error = next((line for line in lines if "error:" in line), "")
    return (error or (lines[-1] if lines else "no diagnostic"))[:360]


def add_case(
    cases: dict[str, dict[str, Any]],
    name: str,
    flags: tuple[str, ...] = (),
    *,
    group: str,
    source_variant: str = "current",
) -> None:
    if name in cases:
        raise RuntimeError(f"duplicate case: {name}")
    cases[name] = {
        "flags": list(flags),
        "group": group,
        "source_variant": source_variant,
    }


def build_gcc_cases() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    add_case(cases, "gcc_baseline", group="baseline")

    for cpu in (
        "alderlake",
        "raptorlake",
        "meteorlake",
        "gracemont",
        "tremont",
        "sierraforest",
        "grandridge",
        "graniterapids",
        "sapphirerapids",
        "znver4",
        "arrowlake",
        "arrowlake-s",
        "lunarlake",
        "pantherlake",
    ):
        add_case(
            cases,
            "gcc_tune_" + cpu.replace("-", "_"),
            (f"-mtune={cpu}",),
            group="target_tune",
        )
    for cpu in (
        "alderlake",
        "raptorlake",
        "meteorlake",
        "x86-64-v3",
        "arrowlake",
        "arrowlake-s",
        "lunarlake",
        "pantherlake",
    ):
        add_case(
            cases,
            "gcc_march_" + cpu.replace("-", "_"),
            (f"-march={cpu}",),
            group="target_isa_and_tune",
        )

    scheduler = {
        "no_sched1": ("-fno-schedule-insns",),
        "no_sched2": ("-fno-schedule-insns2",),
        "no_sched_both": ("-fno-schedule-insns", "-fno-schedule-insns2"),
        "selective1": ("-fselective-scheduling",),
        "selective2": ("-fselective-scheduling2",),
        "selective_both": ("-fselective-scheduling", "-fselective-scheduling2"),
        "rename": ("-frename-registers",),
        "no_critical": ("-fno-sched-critical-path-heuristic",),
        "no_dep_count": ("-fno-sched-dep-count-heuristic",),
        "no_rank": ("-fno-sched-rank-heuristic",),
        "no_last_insn": ("-fno-sched-last-insn-heuristic",),
        "no_spec": ("-fno-sched-spec",),
    }
    for name, flags in scheduler.items():
        add_case(cases, f"gcc_{name}", flags, group="scheduler")

    ira = {
        "ira_priority": ("-fira-algorithm=priority",),
        "ira_cb": ("-fira-algorithm=CB",),
        "ira_one": ("-fira-region=one",),
        "ira_all": ("-fira-region=all",),
        "ira_mixed": ("-fira-region=mixed",),
        "ira_all_pressure": ("-fira-region=all", "-fira-loop-pressure"),
        "ira_priority_rename": ("-fira-algorithm=priority", "-frename-registers"),
        "ira_cb_rename": ("-fira-algorithm=CB", "-frename-registers"),
    }
    for name, flags in ira.items():
        add_case(cases, f"gcc_{name}", flags, group="register_allocation")

    for boundary in (1, 16, 32, 64, 128):
        add_case(
            cases,
            f"gcc_align_loop_{boundary}",
            (f"-falign-loops={boundary}",),
            group="loop_alignment",
        )
    add_case(
        cases,
        "gcc_align_loop64_function64",
        ("-falign-loops=64", "-falign-functions=64"),
        group="layout_cross",
    )
    for cpu in ("alderlake", "meteorlake", "graniterapids"):
        for scheduler_name, scheduler_flags in (
            ("no_sched2", ("-fno-schedule-insns2",)),
            ("selective2", ("-fselective-scheduling2",)),
            ("rename", ("-frename-registers",)),
        ):
            add_case(
                cases,
                f"gcc_{cpu}_{scheduler_name}",
                (f"-mtune={cpu}", *scheduler_flags),
                group="target_scheduler_cross",
            )

    for variant in (
        "explicit_rotate_temporaries",
        "swapped_rotate_or",
        "xor_rotate_merge",
        "swapped_commutative_operands",
        "always_inline_rotate_helper",
        "fixed_register_inline_asm",
    ):
        add_case(
            cases,
            "gcc_source_" + variant,
            group="temporary_source_expression",
            source_variant=variant,
        )
    return cases


def build_clang_cases() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    add_case(cases, "clang_baseline", group="baseline")
    cpus = (
        "alderlake",
        "raptorlake",
        "meteorlake",
        "arrowlake",
        "arrowlake-s",
        "lunarlake",
        "pantherlake",
    )
    for cpu in cpus:
        suffix = cpu.replace("-", "_")
        add_case(
            cases,
            f"clang_march_{suffix}",
            (f"-march={cpu}",),
            group="target_isa_and_tune",
        )
        add_case(
            cases,
            f"clang_tune_{suffix}",
            (f"-mtune={cpu}",),
            group="target_tune",
        )

    scheduler = {
        "no_misched": ("-mllvm", "-enable-misched=false"),
        "no_post_misched": ("-mllvm", "-enable-post-misched=false"),
        "misched_ilpmax": ("-mllvm", "-misched=ilpmax"),
        "misched_ilpmin": ("-mllvm", "-misched=ilpmin"),
        "misched_converge": ("-mllvm", "-misched=converge"),
        "greedy_reverse": ("-mllvm", "-greedy-reverse-local-assignment"),
        "regalloc_basic": ("-mllvm", "-regalloc=basic"),
        "regalloc_pbqp": ("-mllvm", "-regalloc=pbqp"),
        "regalloc_fast": ("-mllvm", "-regalloc=fast"),
    }
    for name, flags in scheduler.items():
        add_case(cases, f"clang_{name}", flags, group="llvm_backend_internal")

    for direction in ("topdown", "bottomup", "bidirectional"):
        add_case(
            cases,
            f"clang_prera_{direction}",
            ("-mllvm", f"-misched-prera-direction={direction}"),
            group="llvm_backend_internal",
        )
        add_case(
            cases,
            f"clang_postra_{direction}",
            ("-mllvm", f"-misched-postra-direction={direction}"),
            group="llvm_backend_internal",
        )

    for boundary in (1, 16, 32, 64, 128):
        add_case(
            cases,
            f"clang_align_loop_{boundary}",
            (f"-falign-loops={boundary}",),
            group="loop_alignment",
        )
    for cpu in ("alderlake", "meteorlake", "arrowlake", "lunarlake"):
        for policy in ("ilpmax", "ilpmin"):
            add_case(
                cases,
                f"clang_{cpu}_{policy}",
                (f"-march={cpu}", "-mllvm", f"-misched={policy}"),
                group="target_scheduler_cross",
            )
    add_case(
        cases,
        "clang_arrow_ilpmax_align64",
        ("-march=arrowlake", "-falign-loops=64", "-mllvm", "-misched=ilpmax"),
        group="target_scheduler_layout_cross",
    )
    for variant in (
        "explicit_rotate_temporaries",
        "swapped_rotate_or",
        "xor_rotate_merge",
        "swapped_commutative_operands",
        "always_inline_rotate_helper",
    ):
        add_case(
            cases,
            "clang_source_" + variant,
            group="temporary_source_expression",
            source_variant=variant,
        )
    return cases


def generate_source_variants(destination: Path) -> dict[str, dict[str, str]]:
    source = SOURCE.read_text()
    variants = {"current": source}

    old_rotate = """    return _mm256_or_si256(_mm256_sllv_epi64(value, left),
                           _mm256_srlv_epi64(value, right));"""
    explicit = """    const __m256i shifted_left = _mm256_sllv_epi64(value, left);
    const __m256i shifted_right = _mm256_srlv_epi64(value, right);
    return _mm256_or_si256(shifted_left, shifted_right);"""
    swapped = """    return _mm256_or_si256(_mm256_srlv_epi64(value, right),
                           _mm256_sllv_epi64(value, left));"""
    xor_merge = """    return _mm256_xor_si256(_mm256_sllv_epi64(value, left),
                            _mm256_srlv_epi64(value, right));"""
    if source.count(old_rotate) != 1:
        raise RuntimeError("AVX2 rotate helper shape changed")
    variants["explicit_rotate_temporaries"] = source.replace(old_rotate, explicit)
    variants["swapped_rotate_or"] = source.replace(old_rotate, swapped)
    # Every lane uses complementary nonzero shift counts, so the shifted bit
    # fields are disjoint and XOR is exactly equivalent to OR.  Keep this as a
    # generated screen variant unless its complete timed loop strictly wins.
    variants["xor_rotate_merge"] = source.replace(old_rotate, xor_merge)

    commutative = source
    replacements = {
        "_mm256_xor_si256(value, xor_forward)": (
            "_mm256_xor_si256(xor_forward, value)"
        ),
        "_mm256_add_epi64(value, add_reverse)": (
            "_mm256_add_epi64(add_reverse, value)"
        ),
        "_mm256_xor_si256(value, xor_reverse)": (
            "_mm256_xor_si256(xor_reverse, value)"
        ),
        "_mm256_add_epi64(value, add_forward)": (
            "_mm256_add_epi64(add_forward, value)"
        ),
    }
    for old, new in replacements.items():
        if commutative.count(old) != 1:
            raise RuntimeError(f"AVX2 macro shape changed at {old}")
        commutative = commutative.replace(old, new)
    variants["swapped_commutative_operands"] = commutative

    helper_signature = "static inline __m256i rotl64_lanes_avx2"
    if source.count(helper_signature) != 1:
        raise RuntimeError("AVX2 rotate helper signature changed")
    variants["always_inline_rotate_helper"] = source.replace(
        helper_signature,
        "static inline __attribute__((always_inline)) __m256i rotl64_lanes_avx2",
    )

    fixed_start_marker = "static inline __m256i keep_in_vector_register"
    fixed_end_marker = "#undef PERMUTE20_ATTRIBUTE"
    fixed_start = source.index(fixed_start_marker)
    fixed_end = source.index(fixed_end_marker, fixed_start) + len(fixed_end_marker)
    fixed_register_implementation = r'''#define FIXEDREG_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)                \
    "vpsllvq %[" LEFT "], %[value], %[shift_left]\n\t"                     \
    "vpsrlvq %[" RIGHT "], %[value], %[shift_right]\n\t"                   \
    "vpor %[shift_right], %[shift_left], %[value]\n\t"                     \
    "vpxor %[" XOR_VALUE "], %[value], %[value]\n\t"                      \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                       \
    "vpaddq %[" ADD_VALUE "], %[value], %[value]\n\t"

PERMUTE20_ATTRIBUTE static void permute_20rounds_unrolled(
    state256_t *restrict state,
    const uint64_t constants1[restrict 4],
    const uint64_t constants2[restrict 4]) {
    register __m256i value __asm__("ymm0") =
        _mm256_loadu_si256((const __m256i *)(const void *)state);
    register __m256i xor_forward __asm__("ymm1") =
        _mm256_loadu_si256((const __m256i *)(const void *)constants2);
    register __m256i add_reverse __asm__("ymm2") =
        _mm256_permute4x64_epi64(
            _mm256_loadu_si256((const __m256i *)(const void *)constants1),
            _MM_SHUFFLE(0, 1, 2, 3));
    register __m256i xor_reverse __asm__("ymm3") =
        _mm256_permute4x64_epi64(xor_forward, _MM_SHUFFLE(0, 1, 2, 3));
    register __m256i add_forward __asm__("ymm4") =
        _mm256_loadu_si256((const __m256i *)(const void *)constants1);
    register __m256i shift_left __asm__("ymm5");
    register __m256i shift_right __asm__("ymm6");
    register __m256i left_forward __asm__("ymm8") =
        _mm256_setr_epi64x(43, 7, 29, 14);
    register __m256i right_forward __asm__("ymm9") =
        _mm256_setr_epi64x(21, 57, 35, 50);
    register __m256i left_reverse __asm__("ymm10") =
        _mm256_setr_epi64x(14, 29, 7, 43);
    register __m256i right_reverse __asm__("ymm11") =
        _mm256_setr_epi64x(50, 35, 57, 21);
    register __m256i byte_swap __asm__("ymm12") = _mm256_setr_epi8(
        7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8,
        7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8);

    __asm__(
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        FIXEDREG_TRANSFORM("left_forward", "right_forward", "xor_forward",
                           "add_reverse")
        FIXEDREG_TRANSFORM("left_reverse", "right_reverse", "xor_reverse",
                           "add_forward")
        : [value] "+x"(value), [shift_left] "=&x"(shift_left),
          [shift_right] "=&x"(shift_right)
        : [xor_forward] "x"(xor_forward), [add_reverse] "x"(add_reverse),
          [xor_reverse] "x"(xor_reverse), [add_forward] "x"(add_forward),
          [left_forward] "x"(left_forward), [right_forward] "x"(right_forward),
          [left_reverse] "x"(left_reverse), [right_reverse] "x"(right_reverse),
          [byte_swap] "x"(byte_swap));

    _mm256_storeu_si256((__m256i *)(void *)state, value);
}

#undef FIXEDREG_TRANSFORM
#undef PERMUTE20_ATTRIBUTE'''
    variants["fixed_register_inline_asm"] = (
        source[:fixed_start] + fixed_register_implementation + source[fixed_end:]
    )

    destination.mkdir()
    reports: dict[str, dict[str, str]] = {}
    for name, text in variants.items():
        path = destination / f"{name}.c"
        path.write_text(text)
        reports[name] = {
            "temporary_path": f"<temporary>/variants/{name}.c",
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
    return reports


GCC_CONTAINER_DRIVER = r'''
import hashlib
import json
import subprocess
from pathlib import Path

manifest = json.loads(Path("/config/manifest.json").read_text())
output = Path("/output")
reports = {}
for name, case in manifest["cases"].items():
    source = Path("/variants") / (case["source_variant"] + ".c")
    binary = output / name
    command = ["gcc", *manifest["common_flags"], *case["flags"], str(source), "-o", str(binary)]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    reports[name] = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "effective_flags": [*manifest["common_flags"], *case["flags"]],
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest() if binary.is_file() else None,
    }
Path("/output/compile.json").write_text(json.dumps({
    "compiler": subprocess.run(["gcc", "--version"], text=True, stdout=subprocess.PIPE).stdout.splitlines()[0],
    "binutils": subprocess.run(["objdump", "--version"], text=True, stdout=subprocess.PIPE).stdout.splitlines()[0],
    "reports": reports,
}, indent=2, sort_keys=True) + "\n")
'''


def compile_gcc(
    args: argparse.Namespace,
    temporary: Path,
    variants: Path,
    cases: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Path]:
    config = temporary / "gcc-config"
    output = temporary / "gcc-output"
    config.mkdir()
    output.mkdir()
    (config / "manifest.json").write_text(
        json.dumps({"common_flags": COMMON_FLAGS, "cases": cases}, sort_keys=True)
    )
    image_id = run(
        [args.runtime, "image", "inspect", "--format", "{{.Id}}", IMAGE]
    ).stdout.strip()
    run(
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
            f"{config}:/config:ro",
            "--volume",
            f"{variants}:/variants:ro",
            "--volume",
            f"{output}:/output",
            IMAGE,
            "python3",
            "-c",
            GCC_CONTAINER_DRIVER,
        ]
    )
    report = json.loads((output / "compile.json").read_text())
    report["container"] = {
        "image": IMAGE,
        "manifest_digest_sha256": IMAGE_DIGEST,
        "local_image_id": image_id,
        "network": "none",
        "source_mount": "read-only",
    }
    return report, output


def compile_clang(
    args: argparse.Namespace,
    temporary: Path,
    variants: Path,
    cases: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Path]:
    output = temporary / "clang-output"
    output.mkdir()
    reports: dict[str, Any] = {}
    for name, case in cases.items():
        binary = output / name
        command = [
            str(args.clang),
            *CLANG_COMMON_FLAGS,
            *case["flags"],
            str(variants / f"{case['source_variant']}.c"),
            "-o",
            str(binary),
        ]
        completed = run(command, check=False)
        reports[name] = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "effective_flags": [*CLANG_COMMON_FLAGS, *case["flags"]],
            "binary_sha256": sha256(binary) if binary.is_file() else None,
        }
    return {
        "compiler": run([str(args.clang), "--version"]).stdout.splitlines()[0],
        "compiler_executable": str(args.clang),
        "compiler_sha256": sha256(args.clang),
        "reports": reports,
    }, output


def extract_loop(binary: Path, destination: Path, objdump: Path) -> None:
    disassembly = run(
        [
            str(objdump),
            "-d",
            "--no-show-raw-insn",
            "--disassemble=main",
            str(binary),
        ]
    ).stdout
    instructions: list[tuple[int, str, str]] = []
    for line in disassembly.splitlines():
        match = re.match(
            r"^\s*([0-9a-fA-F]+):\s+([^\s]+)(?:\s+(.*?))?\s*$", line
        )
        if match:
            instructions.append(
                (
                    int(match.group(1), 16),
                    match.group(2),
                    (match.group(3) or "").strip(),
                )
            )
    clocks = [
        index
        for index, (_, opcode, operands) in enumerate(instructions)
        if opcode.startswith("call")
        and re.search(r"<clock(?:@[^>]*)?>", operands)
    ]
    if len(clocks) < 2:
        raise RuntimeError(f"{binary}: fewer than two clock calls")
    edges: list[tuple[int, int]] = []
    for index in range(clocks[-2] + 1, clocks[-1]):
        address, opcode, operands = instructions[index]
        target = re.match(r"(?:\*?0x)?([0-9a-fA-F]+)", operands)
        if (
            opcode.startswith("j")
            and opcode != "jmp"
            and target
            and int(target.group(1), 16) < address
        ):
            edges.append((index, int(target.group(1), 16)))
    if not edges:
        raise RuntimeError(f"{binary}: timing-loop backedge not found")
    end_index, start_address = edges[-1]
    indices = {address: index for index, (address, _, _) in enumerate(instructions)}
    loop = instructions[indices[start_address] : end_index + 1]
    lines = [".text", ".Ltimed_loop:"]
    for index, (_, opcode, operands) in enumerate(loop):
        operands = re.sub(r"\s+#.*$", "", operands).strip()
        if index == len(loop) - 1 and opcode.startswith("j"):
            operands = ".Ltimed_loop"
        lines.append(f"\t{opcode}\t{operands}".rstrip())
    destination.write_text("\n".join(lines) + "\n")


def extract_number(output: str, label: str) -> float:
    match = re.search(
        rf"^{re.escape(label)}:\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"llvm-mca output omitted {label!r}")
    return float(match.group(1))


def analyse_loop(llvm_mca: Path, loop: Path) -> dict[str, Any]:
    models: dict[str, Any] = {}
    for label, model in MCA_MODELS.items():
        completed = run(
            [
                str(llvm_mca),
                f"-mcpu={model}",
                f"-iterations={MCA_ITERATIONS}",
                str(loop),
            ]
        )
        cycles = extract_number(completed.stdout, "Total Cycles")
        models[label] = {
            "model": model,
            "iterations": MCA_ITERATIONS,
            "cycles_per_iteration": cycles / MCA_ITERATIONS,
            "instructions_per_iteration": (
                extract_number(completed.stdout, "Instructions") / MCA_ITERATIONS
            ),
            "uops_per_iteration": (
                extract_number(completed.stdout, "Total uOps") / MCA_ITERATIONS
            ),
            "block_rthroughput": extract_number(
                completed.stdout, "Block RThroughput"
            ),
        }
    return models


def selected_mnemonics(mnemonics: dict[str, int]) -> dict[str, int]:
    names = (
        "vpsllvq",
        "vpsrlvq",
        "vpor",
        "vpxor",
        "vpshufb",
        "vpaddq",
        "vmovdqa",
        "vmovdqu",
        "dec",
        "sub",
        "jne",
    )
    return {name: mnemonics.get(name, 0) for name in names if mnemonics.get(name)}


def audit_compilations(
    args: argparse.Namespace,
    temporary: Path,
    toolchain: str,
    compiled: dict[str, Any],
    output: Path,
    cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    loop_cache: dict[str, dict[str, Any]] = {}
    for name, compile_report in compiled["reports"].items():
        case = cases[name]
        if compile_report["returncode"] != 0:
            results[name] = {
                "status": "COMPILE_FAIL",
                "group": case["group"],
                "source_variant": case["source_variant"],
                "extra_flags": case["flags"],
                "diagnostic": normalize_diagnostic(
                    compile_report["stderr"] or compile_report["stdout"], temporary
                ),
            }
            continue
        binary = output / name
        try:
            audit = audit_main_timing_loop(
                binary,
                objdump=str(args.objdump),
                size_tool=str(args.size),
            )
            if audit["normalized_loop_sha256"] not in loop_cache:
                loop = temporary / f"{toolchain}-{name}.s"
                extract_loop(binary, loop, args.objdump)
                loop_cache[audit["normalized_loop_sha256"]] = {
                    "loop_artifact_sha256": sha256(loop),
                    "llvm_mca": analyse_loop(args.llvm_mca, loop),
                }
            static = loop_cache[audit["normalized_loop_sha256"]]
            structural_errors: list[str] = []
            for field in ("calls", "push_pop", "memory_operands_excluding_lea"):
                if audit[field] != 0:
                    structural_errors.append(f"{field}: expected 0, got {audit[field]}")
            expected_opcodes = {
                "vpsllvq": 20,
                "vpsrlvq": 20,
                "vpor": 20,
                "vpxor": 20,
                "vpshufb": 20,
                "vpaddq": 20,
            }
            if case["source_variant"] == "xor_rotate_merge":
                expected_opcodes["vpor"] = 0
                expected_opcodes["vpxor"] = 40
            for opcode, expected in expected_opcodes.items():
                actual = audit["mnemonics"].get(opcode, 0)
                if actual != expected:
                    structural_errors.append(
                        f"mnemonic {opcode}: expected {expected}, got {actual}"
                    )
            structural_pass = not structural_errors
            results[name] = {
                "status": "PASS" if structural_pass else "AUDIT_FAIL",
                "group": case["group"],
                "source_variant": case["source_variant"],
                "extra_flags": case["flags"],
                "structural_errors": structural_errors,
                "effective_flags": compile_report["effective_flags"],
                "binary_sha256": audit["binary_sha256"],
                "loop": {
                    "start_mod_16": audit["loop_start_mod_16"],
                    "start_mod_32": audit["loop_start_mod_32"],
                    "start_mod_64": audit["loop_start_mod_64"],
                    "bytes": audit["loop_bytes"],
                    "instructions": audit["loop_instructions"],
                    "calls": audit["calls"],
                    "push_pop": audit["push_pop"],
                    "memory_operands_excluding_lea": audit[
                        "memory_operands_excluding_lea"
                    ],
                    "normalized_sha256": audit["normalized_loop_sha256"],
                    "selected_mnemonics": selected_mnemonics(audit["mnemonics"]),
                },
                **static,
            }
        except RuntimeError as error:
            results[name] = {
                "status": "AUDIT_TOOL_FAIL",
                "group": case["group"],
                "source_variant": case["source_variant"],
                "extra_flags": case["flags"],
                "diagnostic": str(error)[:360],
            }
    return {
        "counts": dict(sorted(Counter(r["status"] for r in results.values()).items())),
        "unique_static_loop_hashes": len(loop_cache),
        "cases": results,
    }


def score_tuple(report: dict[str, Any]) -> tuple[float, ...]:
    loop = report["loop"]
    return (
        float(loop["memory_operands_excluding_lea"]),
        float(loop["instructions"]),
        float(loop["bytes"]),
        float(report["llvm_mca"]["alderlake_p_core_proxy"]["cycles_per_iteration"]),
        float(
            report["llvm_mca"]["znver2_cross_architecture_proxy"]
            ["cycles_per_iteration"]
        ),
    )


def dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a = score_tuple(left)
    b = score_tuple(right)
    return all(x <= y for x, y in zip(a, b)) and any(
        x < y for x, y in zip(a, b)
    )


def select_shortlist(screens: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str, dict[str, Any]]] = [
        (toolchain, name, report)
        for toolchain, screen in screens.items()
        for name, report in screen["cases"].items()
        if report["status"] == "PASS"
    ]
    selected: set[tuple[str, str]] = {
        ("gcc", "gcc_baseline"),
        ("clang", "clang_baseline"),
    }

    # Generated source rewrites make semantic claims that static metrics cannot
    # validate.  Verify every rewrite whose complete loop was extracted, even
    # when a structural audit rejects it for a hot load or another performance
    # defect; this keeps negative source experiments reproducible as well.
    selected.update(
        (toolchain, name)
        for toolchain, screen in screens.items()
        for name, report in screen["cases"].items()
        if report["group"] == "temporary_source_expression"
        and report["status"] in {"PASS", "AUDIT_FAIL"}
        and "loop" in report
    )

    # Preserve each toolchain's own Pareto winner even when the other compiler
    # globally dominates it.  Equal-score schedule/register permutations have
    # no static basis for separate dynamic verification, so choose one stable
    # representative per score tuple and toolchain.
    for toolchain in ("gcc", "clang"):
        local = [item for item in candidates if item[0] == toolchain]
        frontier = [
            item
            for item in local
            if not any(other is not item and dominates(other[2], item[2]) for other in local)
        ]
        by_score: dict[tuple[float, ...], list[tuple[str, str, dict[str, Any]]]] = {}
        for item in frontier:
            by_score.setdefault(score_tuple(item[2]), []).append(item)
        for equivalent in by_score.values():
            equivalent.sort(
                key=lambda item: (
                    0 if item[1].endswith("_baseline") else 1,
                    item[1],
                )
            )
            selected.add((equivalent[0][0], equivalent[0][1]))

    # Also retain one representative of every global trade-off frontier point.
    global_frontier = [
        item
        for item in candidates
        if not any(
            other is not item and dominates(other[2], item[2]) for other in candidates
        )
    ]
    by_score: dict[tuple[float, ...], list[tuple[str, str, dict[str, Any]]]] = {}
    for item in global_frontier:
        by_score.setdefault(score_tuple(item[2]), []).append(item)
    for equivalent in by_score.values():
        equivalent.sort(
            key=lambda item: (
                0 if item[1].endswith("_baseline") else 1,
                item[1],
            )
        )
        selected.add((equivalent[0][0], equivalent[0][1]))
    return sorted(selected)


def verify_candidate(
    args: argparse.Namespace,
    temporary: Path,
    toolchain: str,
    name: str,
    case: dict[str, Any],
    variants: Path,
) -> dict[str, Any]:
    output = temporary / "verification"
    output.mkdir(exist_ok=True)
    compiler = "gcc" if toolchain == "gcc" else str(args.clang)
    common = COMMON_FLAGS if toolchain == "gcc" else CLANG_COMMON_FLAGS
    source = variants / f"{case['source_variant']}.c"
    candidate_object = output / f"{name}.candidate.o"
    verifier_object = output / f"{toolchain}.verifier.o"
    executable = output / f"{name}.verifier"

    if toolchain == "gcc":
        config = temporary / f"verify-{name}-config"
        artifacts = temporary / f"verify-{name}-output"
        config.mkdir()
        artifacts.mkdir()
        manifest = {
            "common": common,
            "flags": case["flags"],
            "source_variant": case["source_variant"],
        }
        (config / "manifest.json").write_text(json.dumps(manifest))
        driver = r'''
import json
import subprocess
from pathlib import Path
m = json.loads(Path("/config/manifest.json").read_text())
source = Path("/variants") / (m["source_variant"] + ".c")
candidate = Path("/output/candidate.o")
verifier = Path("/output/verifier.o")
exe = Path("/output/verify")
commands = [
    ["gcc", *m["common"], *m["flags"], "-Dmain=contest_candidate_main", "-c", str(source), "-o", str(candidate)],
    ["gcc", "-O3", "-Wall", "-Wextra", "-Werror", "-c", "/repository/solutions/02_optimization/verify_contest_candidate_02.c", "-o", str(verifier)],
    ["gcc", str(candidate), str(verifier), "-o", str(exe)],
]
records = []
for command in commands:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    records.append({"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr})
    if completed.returncode:
        break
execution = subprocess.run([str(exe)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) if exe.is_file() else None
Path("/output/result.json").write_text(json.dumps({"build": records, "execution": None if execution is None else {"returncode": execution.returncode, "stdout": execution.stdout, "stderr": execution.stderr}}, indent=2) + "\n")
'''
        run(
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
                f"{config}:/config:ro",
                "--volume",
                f"{variants}:/variants:ro",
                "--volume",
                f"{ROOT}:/repository:ro",
                "--volume",
                f"{artifacts}:/output",
                IMAGE,
                "python3",
                "-c",
                driver,
            ]
        )
        raw = json.loads((artifacts / "result.json").read_text())
    else:
        commands = [
            [
                compiler,
                *common,
                *case["flags"],
                "-Dmain=contest_candidate_main",
                "-c",
                str(source),
                "-o",
                str(candidate_object),
            ],
            [
                compiler,
                "-O3",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-c",
                str(VERIFIER),
                "-o",
                str(verifier_object),
            ],
            [compiler, str(candidate_object), str(verifier_object), "-o", str(executable)],
        ]
        records: list[dict[str, Any]] = []
        for command in commands:
            completed = run(command, check=False)
            records.append(
                {
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            )
            if completed.returncode:
                break
        execution = run([str(executable)], check=False) if executable.is_file() else None
        raw = {
            "build": records,
            "execution": None
            if execution is None
            else {
                "returncode": execution.returncode,
                "stdout": execution.stdout,
                "stderr": execution.stderr,
            },
        }
    execution = raw["execution"]
    passed = (
        len(raw["build"]) == 3
        and all(item["returncode"] == 0 for item in raw["build"])
        and execution is not None
        and execution["returncode"] == 0
        and execution["stdout"] == EXPECTED_VERIFIER_STDOUT
        and execution["stderr"] == ""
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "random_cases": 100_000,
        "random_state_and_constants": True,
        "round_counts": [1, 20],
        "seed": "0x243f6a8885a308d3",
        "stdout": execution["stdout"] if execution else "",
        "stderr": execution["stderr"] if execution else "",
        "build_returncodes": [item["returncode"] for item in raw["build"]],
    }


def summarize_failures(
    toolchain: str,
    screen: dict[str, Any],
    baseline_name: str,
) -> list[dict[str, Any]]:
    baseline = screen["cases"][baseline_name]
    summaries: list[dict[str, Any]] = []
    by_group: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for name, report in screen["cases"].items():
        if name == baseline_name:
            continue
        by_group.setdefault(report["group"], []).append((name, report))
    for group, reports in sorted(by_group.items()):
        compiled = [report for _, report in reports if "loop" in report]
        equal_hash = sum(
            report["loop"]["normalized_sha256"]
            == baseline["loop"]["normalized_sha256"]
            for report in compiled
        )
        better = [name for name, report in reports if report.get("status") == "PASS" and dominates(report, baseline)]
        worse_or_equal = [
            name
            for name, report in reports
            if report.get("status") == "PASS" and not dominates(report, baseline)
        ]
        failed = [name for name, report in reports if report["status"] != "PASS"]
        summaries.append(
            {
                "toolchain": toolchain,
                "strategy_group": group,
                "attempted": len(reports),
                "same_loop_as_toolchain_baseline": equal_hash,
                "strictly_dominates_toolchain_baseline": better,
                "not_strictly_better": worse_or_equal,
                "compile_or_audit_failures": failed,
            }
        )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=HERE / "avx2_codegen_screen_02.json")
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--clang", type=Path, default=DEFAULT_CLANG)
    parser.add_argument("--objdump", type=Path, default=DEFAULT_OBJDUMP)
    parser.add_argument("--size", type=Path, default=DEFAULT_SIZE)
    parser.add_argument("--llvm-mca", type=Path, default=DEFAULT_LLVM_MCA)
    args = parser.parse_args()

    if sha256(SOURCE) != SOURCE_SHA256:
        raise RuntimeError("AVX2 source hash changed; review transformations and baseline")
    if sha256(VERIFIER) != VERIFIER_SHA256:
        raise RuntimeError("differential verifier hash changed")
    for path in (args.clang, args.objdump, args.size, args.llvm_mca):
        if not path.is_file():
            raise RuntimeError(f"required tool does not exist: {path}")

    gcc_cases = build_gcc_cases()
    clang_cases = build_clang_cases()
    with tempfile.TemporaryDirectory(prefix="challenge02-avx2-codegen-") as raw:
        temporary = Path(raw)
        variant_reports = generate_source_variants(temporary / "variants")
        gcc_compiled, gcc_output = compile_gcc(
            args, temporary, temporary / "variants", gcc_cases
        )
        clang_compiled, clang_output = compile_clang(
            args, temporary, temporary / "variants", clang_cases
        )
        screens = {
            "gcc": audit_compilations(
                args, temporary, "gcc", gcc_compiled, gcc_output, gcc_cases
            ),
            "clang": audit_compilations(
                args, temporary, "clang", clang_compiled, clang_output, clang_cases
            ),
        }
        shortlist = select_shortlist(screens)
        verification: dict[str, Any] = {}
        for toolchain, name in shortlist:
            cases = gcc_cases if toolchain == "gcc" else clang_cases
            verification[name] = verify_candidate(
                args,
                temporary,
                toolchain,
                name,
                cases[name],
                temporary / "variants",
            )

        all_pass = all(item["status"] == "PASS" for item in verification.values())
        gcc_baseline = screens["gcc"]["cases"]["gcc_baseline"]
        verified_strict_winners: list[str] = []
        verified_winner_details: list[dict[str, Any]] = []
        for toolchain, name in shortlist:
            report = screens[toolchain]["cases"][name]
            if (
                name != "gcc_baseline"
                and verification[name]["status"] == "PASS"
                and dominates(report, gcc_baseline)
            ):
                verified_strict_winners.append(name)
                verified_winner_details.append(
                    {
                        "name": name,
                        "toolchain": toolchain,
                        "source_variant": report["source_variant"],
                        "extra_flags": report["extra_flags"],
                        "delta_vs_gcc_baseline": {
                            "loop_bytes": (
                                report["loop"]["bytes"]
                                - gcc_baseline["loop"]["bytes"]
                            ),
                            "loop_instructions": (
                                report["loop"]["instructions"]
                                - gcc_baseline["loop"]["instructions"]
                            ),
                            "memory_operands_excluding_lea": (
                                report["loop"]["memory_operands_excluding_lea"]
                                - gcc_baseline["loop"][
                                    "memory_operands_excluding_lea"
                                ]
                            ),
                            "alderlake_proxy_cycles": (
                                report["llvm_mca"]["alderlake_p_core_proxy"][
                                    "cycles_per_iteration"
                                ]
                                - gcc_baseline["llvm_mca"][
                                    "alderlake_p_core_proxy"
                                ]["cycles_per_iteration"]
                            ),
                            "znver2_proxy_cycles": (
                                report["llvm_mca"][
                                    "znver2_cross_architecture_proxy"
                                ]["cycles_per_iteration"]
                                - gcc_baseline["llvm_mca"][
                                    "znver2_cross_architecture_proxy"
                                ]["cycles_per_iteration"]
                            ),
                        },
                    }
                )

        failed_strategies = [
            *summarize_failures("gcc", screens["gcc"], "gcc_baseline"),
            *summarize_failures("clang", screens["clang"], "clang_baseline"),
        ]
        fixed_register = screens["gcc"]["cases"][
            "gcc_source_fixed_register_inline_asm"
        ]
        report = {
            "schema_version": 1,
            "scope": {
                "challenge": 2,
                "host_timing_performed": False,
                "claim_scope": "static code generation plus differential correctness",
                "source": SOURCE_RELATIVE,
                "source_sha256": SOURCE_SHA256,
                "verifier": VERIFIER_RELATIVE,
                "verifier_sha256": VERIFIER_SHA256,
            },
            "protocol": {
                "complete_binary_loop_boundary": "last two clock calls in main",
                "screen_order": "compile, exact-binary audit, LLVM-MCA, Pareto shortlist, differential verification",
                "pareto_dimensions": [
                    "memory operands",
                    "instruction count",
                    "loop bytes",
                    "Alder Lake proxy cycles",
                    "Zen 2 cross-architecture proxy cycles",
                ],
                "strict_winner_rule": "no dimension worse and at least one dimension better",
                "random_cases_for_shortlist": 100_000,
                "round_counts": [1, 20],
                "unsupported_proxy_record": {
                    "model": "tremont",
                    "outcome": "REJECTED_FOR_AVX2_ANALYSIS",
                    "diagnostic": (
                        "LLVM-MCA 16 reports VPSRLVQ as unsupported for its Tremont model."
                    ),
                },
            },
            "toolchains": {
                "gcc": {
                    "compiler": gcc_compiled["compiler"],
                    "binutils": gcc_compiled["binutils"],
                    "container": gcc_compiled["container"],
                    "common_flags": COMMON_FLAGS,
                },
                "clang": {
                    "compiler": clang_compiled["compiler"],
                    "compiler_executable": str(args.clang),
                    "compiler_sha256": clang_compiled["compiler_sha256"],
                    "common_flags": CLANG_COMMON_FLAGS,
                },
                "host_analysis_tools": {
                    "objdump": {
                        "path": str(args.objdump),
                        "sha256": sha256(args.objdump),
                        "version": run([str(args.objdump), "--version"]).stdout.splitlines()[0],
                    },
                    "size": {
                        "path": str(args.size),
                        "sha256": sha256(args.size),
                        "version": run([str(args.size), "--version"]).stdout.splitlines()[0],
                    },
                    "llvm_mca": {
                        "path": str(args.llvm_mca),
                        "sha256": sha256(args.llvm_mca),
                        "version": run([str(args.llvm_mca), "--version"]).stdout.splitlines()[0],
                        "models": MCA_MODELS,
                        "qualification": (
                            "LLVM-MCA 16 has neither Lion Cove nor Skymont. Its Tremont model cannot parse AVX2 variable shifts, so Alder Lake is only a directional Intel P-core proxy and Zen 2 is retained solely as a cross-architecture sensitivity check. "
                            "Neither scheduling-model estimate replaces measurement on each Core Ultra 7 255H core type."
                        ),
                    },
                },
            },
            "temporary_source_variants": variant_reports,
            "screens": screens,
            "shortlist": [name for _, name in shortlist],
            "verification": verification,
            "failed_strategy_summary": failed_strategies,
            "decision": {
                "all_shortlist_verifications_pass": all_pass,
                "verified_strict_winners_vs_gcc_baseline": verified_strict_winners,
                "verified_winner_details": verified_winner_details,
                "fixed_register_inline_asm": {
                    "status": fixed_register["status"],
                    "verification": verification[
                        "gcc_source_fixed_register_inline_asm"
                    ]["status"],
                    "loop_instructions": fixed_register["loop"]["instructions"],
                    "loop_bytes": fixed_register["loop"]["bytes"],
                    "memory_operands_excluding_lea": fixed_register["loop"][
                        "memory_operands_excluding_lea"
                    ],
                    "reason_not_promoted": (
                        "pinning the vector state and constants shortened VEX encodings, "
                        "but GCC reloaded one XOR constant and rebuilt its reverse form "
                        "inside every timed iteration"
                    ),
                },
                "new_persisted_source_candidate": False,
                "reason": (
                    "No generated source-expression variant strictly dominated the current source under the exact GCC baseline; "
                    "a flag-only winner, if present, must still be timed independently on each 255H core type before submission promotion."
                ),
            },
            "primary_documentation": PRIMARY_DOCUMENTATION,
        }
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(
        f"gcc={screens['gcc']['counts']} clang={screens['clang']['counts']} "
        f"shortlist={len(shortlist)} verified={all_pass} "
        f"strict_winners={verified_strict_winners} output={args.output}"
    )
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
