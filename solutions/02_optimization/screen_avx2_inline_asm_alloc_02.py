#!/usr/bin/env python3
"""Bounded GCC 13 register-allocation screen for challenge 2's AVX2 core.

It generates a small, enumerated family of single-block extended-assembly
implementations, compiles the complete contest program with the digest-pinned
GCC 13.3 image, audits the exact clock-delimited hot loop, runs LLVM-MCA
scheduling proxies, and checks both the official vectors and 100,000 random
states/constants for 1/20 rounds.  Two later repeated host campaigns are pinned
as diagnostic evidence, not as a substitute for the unavailable 255H target.
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
from pathlib import Path
from typing import Any
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "solutions"))

from challenge02_loop_audit import audit_main_timing_loop  # noqa: E402


BASE_RELATIVE = "solutions/02_optimization/contest_simd_avx2_lanewise.c"
BASE = ROOT / BASE_RELATIVE
BASE_SHA256 = "3a8273cb6f381efb30fb4e104a9741acf158307714216f2a2b2d8c1756b9d751"
RETAINED_RELATIVE = "solutions/02_optimization/contest_simd_avx2_inline_asm.c"
RETAINED = ROOT / RETAINED_RELATIVE
RETAINED_SHA256 = "778187b61a0a769cb012e5205edb5782df2c25418681651cb76d05739198307c"
PHASE_RELATIVE = "solutions/02_optimization/contest_simd_avx2_phase_staggered.c"
PHASE_SHA256 = "1824843868e3747634fd5eb8f39f08ce0b79588da8ca0f19fcaee810c2b12983"
VERIFIER_RELATIVE = "solutions/02_optimization/verify_contest_candidate_02.c"
VERIFIER = ROOT / VERIFIER_RELATIVE
VERIFIER_SHA256 = "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35"
ARCHIVE_RELATIVE = "problems/2_암호구현.zip"
ARCHIVE = ROOT / ARCHIVE_RELATIVE
ARCHIVE_SHA256 = "d0c3158adda8ba258becfc0e347267c0f2f0112738ec732be6dcb5477342e88e"
PRIOR_SCREEN_RELATIVE = "solutions/02_optimization/avx2_codegen_screen_02.json"
PRIOR_SCREEN = ROOT / PRIOR_SCREEN_RELATIVE
PRIOR_SCREEN_SHA256 = "addbc4e937f5fad6ea2bb22508476b7fc185db07eabde9e010549f072e7dd800"
TIMING_PROTOCOL_FILES = {
    "autotune_driver": (
        "solutions/02_optimization/autotune_02_255h.py",
        "36ba5ce6d130aa117c621844cd8c1f8bcb4c96e4518580d25afa688d3b976d09",
    ),
    "benchmark_driver": (
        "solutions/benchmark_02_permutation.py",
        "4262926ecd8e4fcfabcc7c4e74a4c87bbc0450f995b31d4a60137f888bd59d42",
    ),
    "candidate_verifier": (VERIFIER_RELATIVE, VERIFIER_SHA256),
    "loop_audit": (
        "solutions/challenge02_loop_audit.py",
        "e73d27abfbb7eea9ee84e0216baaf7f39f128db0cffdcb79b469656f9c185e23",
    ),
    "problem_archive": (ARCHIVE_RELATIVE, ARCHIVE_SHA256),
    "reference_oracle": (
        "solutions/solve_02_permutation.c",
        "fb6b5128f6777bdb5c9c940541d7052a317b596775d7ec0d7820d0610cb9aa42",
    ),
}
TIMING_SOURCES = {
    "current": {
        "path": BASE_RELATIVE,
        "sha256": BASE_SHA256,
        "case_cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
    },
    "inline_asm": {
        "path": RETAINED_RELATIVE,
        "sha256": RETAINED_SHA256,
        "case_cflags": ["-mavx2", "-DCH2_SIMD_INLINE", "-finline-limit=2000"],
    },
    "phase": {
        "path": PHASE_RELATIVE,
        "sha256": PHASE_SHA256,
        "case_cflags": [
            "-mavx2",
            "-mbmi2",
            "-DCH2_SIMD_INLINE",
            "-finline-limit=2000",
        ],
    },
}

IMAGE_DIGEST = "1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
IMAGE = f"gcc@sha256:{IMAGE_DIGEST}"
EXPECTED_COMPILER = "gcc (GCC) 13.3.0"
DEFAULT_OBJDUMP = Path("/usr/bin/x86_64-linux-gnu-objdump")
DEFAULT_SIZE = Path("/usr/bin/x86_64-linux-gnu-size")
DEFAULT_LLVM_MCA = Path("/usr/bin/llvm-mca-16")
HOST_TOOL_HASHES = {
    "objdump": "19717049e8ecd98cfbb17fd9eb25e9fd896ecec2fc4af6b931f3dd0bc4e903de",
    "size": "d2dc6eb962bfc841403cc8b72191bfd829b50d8796b611689e92cfb051cf10ee",
    "llvm_mca": "e7f38b12a3c228c8b0bcea0bf63cc56939286adf9ae5397a43d408322e3c6fbf",
}

COMMON_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-mavx2",
    "-DCH2_SIMD_INLINE",
    "-finline-limit=2000",
]
SUPPLIED_DEFAULT_FLAGS = ["-O3", "-Wall", "-Wextra"]
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
OFFICIAL_MARKERS = [
    "one-round testvector verification: OK (1000 pairs checked)",
    "20-round testvector verification: OK",
]
MCA_MODELS = {
    "alderlake_p_core_proxy": "alderlake",
    "znver2_cross_architecture_proxy": "znver2",
}
MCA_ITERATIONS = 100
HOST_TIMING_RELATIVES = [
    "solutions/02_optimization/eighth_wave_timing_02_cpu1.json",
    "solutions/02_optimization/eighth_wave_timing_02_cpu3.json",
]

FUNCTION_START = "static inline __m256i keep_in_vector_register"
FUNCTION_END = "#undef PERMUTE20_ATTRIBUTE"
DEFAULT_TARGET_OLD = 'target("bmi2"),'
DEFAULT_TARGET_NEW = 'target("bmi2,avx2"),'
PRIOR_GCC_IRA_ONE_NORMALIZED_SHA256 = (
    "7fd0b713734b306301d0d73102ad98160139da908d0f9c66bd1e26d619a728af"
)


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


def variant_specs() -> dict[str, dict[str, Any]]:
    """Return the deliberately small allocation design, in stable order."""

    constants_first = [
        "xor_forward",
        "add_reverse",
        "xor_reverse",
        "add_forward",
        "left_forward",
        "right_forward",
        "left_reverse",
        "right_reverse",
        "byte_swap",
    ]
    controls_first = [
        "left_forward",
        "right_forward",
        "left_reverse",
        "right_reverse",
        "byte_swap",
        "xor_forward",
        "add_reverse",
        "xor_reverse",
        "add_forward",
    ]
    return {
        "intrinsics_baseline": {
            "kind": "baseline",
            "description": "unchanged lane-wise AVX2 intrinsic implementation",
        },
        "asm_fixed_original_two_scratch": {
            "kind": "asm",
            "scratch_count": 2,
            "input_order": constants_first,
            "pins": {
                "value": 0,
                "xor_forward": 1,
                "add_reverse": 2,
                "xor_reverse": 3,
                "add_forward": 4,
                "shift_left": 5,
                "shift_right": 6,
                "left_forward": 8,
                "right_forward": 9,
                "left_reverse": 10,
                "right_reverse": 11,
                "byte_swap": 12,
            },
            "description": (
                "exact two-scratch low-data/high-control fixed-register shape; "
                "reproduces the reload that motivated this screen"
            ),
        },
        "asm_allocator_two_scratch": {
            "kind": "asm",
            "scratch_count": 2,
            "input_order": constants_first,
            "pins": {},
            "description": (
                "let GCC allocate every operand while preserving the original "
                "two-scratch dataflow"
            ),
        },
        "asm_allocator_one_scratch_constants_first": {
            "kind": "asm",
            "scratch_count": 1,
            "input_order": constants_first,
            "pins": {},
            "description": (
                "allocator-chosen registers, one destructive-shift scratch, "
                "constants listed before controls"
            ),
        },
        "asm_allocator_one_scratch_controls_first": {
            "kind": "asm",
            "scratch_count": 1,
            "input_order": controls_first,
            "pins": {},
            "description": (
                "allocator-chosen registers, one destructive-shift scratch, "
                "controls listed before constants"
            ),
        },
        "asm_pin_value_one_scratch": {
            "kind": "asm",
            "scratch_count": 1,
            "input_order": constants_first,
            "pins": {"value": 0},
            "description": "pin only the changing state to ymm0",
        },
        "asm_pin_low_data_one_scratch": {
            "kind": "asm",
            "scratch_count": 1,
            "input_order": constants_first,
            "pins": {
                "value": 0,
                "xor_forward": 1,
                "add_reverse": 2,
                "xor_reverse": 3,
                "add_forward": 4,
            },
            "description": (
                "pin state and XOR/add constants low; allocate scratch and "
                "shift/shuffle controls"
            ),
        },
        "asm_fixed_low_data_high_controls_one_scratch": {
            "kind": "asm",
            "scratch_count": 1,
            "input_order": constants_first,
            "pins": {
                "value": 0,
                "xor_forward": 1,
                "add_reverse": 2,
                "xor_reverse": 3,
                "add_forward": 4,
                "scratch": 5,
                "left_forward": 8,
                "right_forward": 9,
                "left_reverse": 10,
                "right_reverse": 11,
                "byte_swap": 12,
            },
            "description": (
                "one scratch; keep ModRM sources of VPOR/VPXOR/VPADDQ low and "
                "put VEX3-only shift/shuffle controls high"
            ),
        },
        "asm_fixed_low_constants_high_value_one_scratch": {
            "kind": "asm",
            "scratch_count": 1,
            "input_order": constants_first,
            "pins": {
                "xor_forward": 0,
                "add_reverse": 1,
                "xor_reverse": 2,
                "add_forward": 3,
                "scratch": 4,
                "left_forward": 8,
                "right_forward": 9,
                "left_reverse": 10,
                "right_reverse": 11,
                "byte_swap": 12,
                "value": 15,
            },
            "description": (
                "one scratch; keep simple-op ModRM sources low while moving "
                "the read/write state to ymm15"
            ),
        },
        "asm_fixed_low_constants_mid_value_one_scratch": {
            "kind": "asm",
            "scratch_count": 1,
            "input_order": constants_first,
            "pins": {
                "xor_forward": 0,
                "add_reverse": 1,
                "xor_reverse": 2,
                "add_forward": 3,
                "scratch": 4,
                "value": 7,
                "left_forward": 8,
                "right_forward": 9,
                "left_reverse": 10,
                "right_reverse": 11,
                "byte_swap": 12,
            },
            "description": (
                "same encoding-aware layout with state in the last low register"
            ),
        },
    }


def declaration(name: str, initializer: str, pins: dict[str, int]) -> str:
    if name in pins:
        return (
            f'    register __m256i {name} __asm__("ymm{pins[name]}") =\n'
            f"        {initializer};"
        )
    return f"    __m256i {name} =\n        {initializer};"


def scratch_declaration(name: str, pin_key: str, pins: dict[str, int]) -> str:
    if pin_key in pins:
        return f'    register __m256i {name} __asm__("ymm{pins[pin_key]}");'
    return f"    __m256i {name};"


def asm_implementation(spec: dict[str, Any]) -> str:
    pins = spec["pins"]
    scratches = int(spec["scratch_count"])
    if scratches == 1:
        macro = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpor %[scratch], %[value], %[value]\n\t"                          \
    "vpxor %[" XOR_VALUE "], %[value], %[value]\n\t"                     \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                        \
    "vpaddq %[" ADD_VALUE "], %[value], %[value]\n\t"
'''
    elif scratches == 2:
        macro = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsllvq %[" LEFT "], %[value], %[shift_left]\n\t"                  \
    "vpsrlvq %[" RIGHT "], %[value], %[shift_right]\n\t"                \
    "vpor %[shift_right], %[shift_left], %[value]\n\t"                    \
    "vpxor %[" XOR_VALUE "], %[value], %[value]\n\t"                     \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                        \
    "vpaddq %[" ADD_VALUE "], %[value], %[value]\n\t"
'''
    else:
        raise RuntimeError(f"unsupported scratch count: {scratches}")

    declarations = [
        declaration(
            "value",
            "_mm256_loadu_si256((const __m256i *)(const void *)state)",
            pins,
        ),
        declaration(
            "xor_forward",
            "_mm256_loadu_si256((const __m256i *)(const void *)constants2)",
            pins,
        ),
        declaration(
            "add_reverse",
            "_mm256_permute4x64_epi64(\n"
            "            _mm256_loadu_si256((const __m256i *)(const void *)constants1),\n"
            "            _MM_SHUFFLE(0, 1, 2, 3))",
            pins,
        ),
        declaration(
            "xor_reverse",
            "_mm256_permute4x64_epi64(xor_forward, _MM_SHUFFLE(0, 1, 2, 3))",
            pins,
        ),
        declaration(
            "add_forward",
            "_mm256_loadu_si256((const __m256i *)(const void *)constants1)",
            pins,
        ),
    ]
    if scratches == 1:
        declarations.append(scratch_declaration("scratch", "scratch", pins))
    else:
        declarations.extend(
            [
                scratch_declaration("shift_left", "shift_left", pins),
                scratch_declaration("shift_right", "shift_right", pins),
            ]
        )
    declarations.extend(
        [
            declaration(
                "left_forward", "_mm256_setr_epi64x(43, 7, 29, 14)", pins
            ),
            declaration(
                "right_forward", "_mm256_setr_epi64x(21, 57, 35, 50)", pins
            ),
            declaration(
                "left_reverse", "_mm256_setr_epi64x(14, 29, 7, 43)", pins
            ),
            declaration(
                "right_reverse", "_mm256_setr_epi64x(50, 35, 57, 21)", pins
            ),
            declaration(
                "byte_swap",
                "_mm256_setr_epi8(\n"
                "            7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8,\n"
                "            7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8)",
                pins,
            ),
        ]
    )

    call_pair = (
        '        INLINE_ASM_TRANSFORM("left_forward", "right_forward", '
        '"xor_forward",\n                              "add_reverse")\n'
        '        INLINE_ASM_TRANSFORM("left_reverse", "right_reverse", '
        '"xor_reverse",\n                              "add_forward")'
    )
    calls = "\n".join(call_pair for _ in range(10))
    if scratches == 1:
        outputs = ': [value] "+x"(value), [scratch] "=&x"(scratch)'
    else:
        outputs = (
            ': [value] "+x"(value), [shift_left] "=&x"(shift_left),\n'
            '          [shift_right] "=&x"(shift_right)'
        )
    inputs = [
        f'[{name}] "x"({name})' for name in spec["input_order"]
    ]
    input_lines = []
    for index in range(0, len(inputs), 2):
        input_lines.append("          " + ", ".join(inputs[index : index + 2]))
    constraints = outputs + "\n        : " + ",\n".join(input_lines).lstrip()

    return (
        macro
        + "\nPERMUTE20_ATTRIBUTE static void permute_20rounds_unrolled(\n"
        + "    state256_t *restrict state,\n"
        + "    const uint64_t constants1[restrict 4],\n"
        + "    const uint64_t constants2[restrict 4]) {\n"
        + "\n".join(declarations)
        + "\n\n    __asm__(\n"
        + calls
        + "\n        "
        + constraints
        + ");\n\n"
        + "    _mm256_storeu_si256((__m256i *)(void *)state, value);\n"
        + "}\n\n#undef INLINE_ASM_TRANSFORM\n#undef PERMUTE20_ATTRIBUTE"
    )


def generate_variants(destination: Path) -> dict[str, dict[str, Any]]:
    source = BASE.read_text()
    start = source.index(FUNCTION_START)
    end = source.index(FUNCTION_END, start) + len(FUNCTION_END)
    destination.mkdir()
    reports: dict[str, dict[str, Any]] = {}
    for name, spec in variant_specs().items():
        if spec["kind"] == "baseline":
            text = source
        else:
            text = source[:start] + asm_implementation(spec) + source[end:]
            if text.count(DEFAULT_TARGET_OLD) != 2:
                raise RuntimeError("default GCC target attribute shape changed")
            # The supplied command has no global -mavx2.  Keep the experimental
            # source self-contained by extending the existing noinline local
            # target; score builds use the unchanged always-inline first branch.
            text = text.replace(DEFAULT_TARGET_OLD, DEFAULT_TARGET_NEW)
        path = destination / f"{name}.c"
        path.write_text(text)
        reports[name] = {
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "temporary_path": f"<temporary>/variants/{name}.c",
            "kind": spec["kind"],
            "description": spec["description"],
            "scratch_count": spec.get("scratch_count"),
            "pins": spec.get("pins", {}),
            "input_order": spec.get("input_order", []),
        }
    return reports


CONTAINER_DRIVER = r'''
import json
import subprocess
from pathlib import Path

manifest = json.loads(Path("/config/manifest.json").read_text())
output = Path("/output")
verifier_object = output / "verifier.o"
verifier_build = subprocess.run(
    ["gcc", *manifest["verifier_flags"], "-c", "/repository/" + manifest["verifier"], "-o", str(verifier_object)],
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
reports = {}
for name in manifest["variants"]:
    source = Path("/variants") / (name + ".c")
    binary = output / name
    default_binary = output / (name + ".default")
    candidate_object = output / (name + ".o")
    verifier = output / (name + ".verify")
    default_completed = subprocess.run(
        ["gcc", *manifest["supplied_default_flags"], str(source), "-o", str(default_binary)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    default_build = {
        "returncode": default_completed.returncode,
        "stdout": default_completed.stdout,
        "stderr": default_completed.stderr,
    }
    builds = []
    for command in (
        ["gcc", *manifest["common_flags"], str(source), "-o", str(binary)],
        ["gcc", *manifest["common_flags"], "-Dmain=contest_candidate_main", "-c", str(source), "-o", str(candidate_object)],
    ):
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        builds.append({
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
        if completed.returncode:
            break
    link = None
    verification = None
    official = None
    default_official = None
    if len(builds) == 2 and all(item["returncode"] == 0 for item in builds) and verifier_build.returncode == 0:
        completed = subprocess.run(
            ["gcc", str(candidate_object), str(verifier_object), "-o", str(verifier)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        link = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode == 0:
            completed = subprocess.run(
                [str(verifier), "100000"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            verification = {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        completed = subprocess.run(
            [str(binary)],
            cwd="/vectors",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        official = {
            "returncode": completed.returncode,
            "markers": {
                marker: marker in completed.stdout for marker in manifest["official_markers"]
            },
            "stderr": completed.stderr,
        }
    if default_completed.returncode == 0:
        completed = subprocess.run(
            [str(default_binary)],
            cwd="/vectors",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        default_official = {
            "returncode": completed.returncode,
            "markers": {
                marker: marker in completed.stdout for marker in manifest["official_markers"]
            },
            "stderr": completed.stderr,
        }
    reports[name] = {
        "supplied_default_build": default_build,
        "supplied_default_official_vectors": default_official,
        "full_build": builds[0] if builds else None,
        "candidate_object_build": builds[1] if len(builds) > 1 else None,
        "link": link,
        "verification": verification,
        "official_vectors": official,
    }
Path("/output/build-report.json").write_text(json.dumps({
    "compiler": subprocess.run(["gcc", "--version"], text=True, stdout=subprocess.PIPE).stdout.splitlines()[0],
    "verifier_build": {
        "returncode": verifier_build.returncode,
        "stdout": verifier_build.stdout,
        "stderr": verifier_build.stderr,
    },
    "reports": reports,
}, indent=2) + "\n")
'''


def compile_and_verify(
    args: argparse.Namespace,
    temporary: Path,
    variants: Path,
    reports: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Path]:
    config = temporary / "config"
    output = temporary / "output"
    vectors = temporary / "official-vectors"
    for directory in (config, output, vectors):
        directory.mkdir()
    with ZipFile(ARCHIVE) as zipped:
        (vectors / "testvector.txt").write_bytes(zipped.read("code/testvector.txt"))
        (vectors / "testvector_20round.txt").write_bytes(
            zipped.read("code/testvector_20round.txt")
        )
    manifest = {
        "variants": list(reports),
        "common_flags": COMMON_FLAGS,
        "supplied_default_flags": SUPPLIED_DEFAULT_FLAGS,
        "verifier_flags": VERIFIER_FLAGS,
        "verifier": VERIFIER_RELATIVE,
        "official_markers": OFFICIAL_MARKERS,
    }
    (config / "manifest.json").write_text(json.dumps(manifest))
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
            f"{vectors}:/vectors:ro",
            "--volume",
            f"{output}:/output",
            IMAGE,
            "python3",
            "-c",
            CONTAINER_DRIVER,
        ]
    )
    return json.loads((output / "build-report.json").read_text()), output


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
    reports: dict[str, Any] = {}
    for label, model in MCA_MODELS.items():
        completed = run(
            [
                str(llvm_mca),
                f"-mcpu={model}",
                f"-iterations={MCA_ITERATIONS}",
                str(loop),
            ]
        )
        reports[label] = {
            "model": model,
            "iterations": MCA_ITERATIONS,
            "cycles_per_iteration": (
                extract_number(completed.stdout, "Total Cycles") / MCA_ITERATIONS
            ),
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
    return reports


def structural_errors(audit: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("calls", "push_pop", "memory_operands_excluding_lea"):
        if audit[field] != 0:
            errors.append(f"{field}: expected 0, got {audit[field]}")
    expected = {
        "vpsllvq": 20,
        "vpsrlvq": 20,
        "vpor": 20,
        "vpxor": 20,
        "vpshufb": 20,
        "vpaddq": 20,
    }
    for mnemonic, count in expected.items():
        actual = audit["mnemonics"].get(mnemonic, 0)
        if actual != count:
            errors.append(f"mnemonics.{mnemonic}: expected {count}, got {actual}")
    if audit["loop_instructions"] != 122:
        errors.append(
            f"loop_instructions: expected 122, got {audit['loop_instructions']}"
        )
    return errors


def verification_report(raw: dict[str, Any] | None) -> dict[str, Any]:
    passed = (
        raw is not None
        and raw["returncode"] == 0
        and raw["stdout"] == EXPECTED_VERIFIER_STDOUT
        and raw["stderr"] == ""
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "random_cases": 100_000,
        "random_state_and_constants": True,
        "round_counts": [1, 20],
        "seed": "0x243f6a8885a308d3",
        "returncode": None if raw is None else raw["returncode"],
        "stdout": "" if raw is None else raw["stdout"],
        "stderr": "" if raw is None else raw["stderr"],
    }


def official_report(raw: dict[str, Any] | None) -> dict[str, Any]:
    passed = (
        raw is not None
        and raw["returncode"] == 0
        and all(raw["markers"].values())
        and raw["stderr"] == ""
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "one_round_pairs": 1_000,
        "twenty_round_cases": 1,
        "returncode": None if raw is None else raw["returncode"],
        "validated_stdout_markers": OFFICIAL_MARKERS,
        "stderr": "" if raw is None else raw["stderr"],
        "qualification": (
            "the contest harness's timing line was discarded; this single "
            "execution is correctness evidence, not a timing campaign"
        ),
    }


def compact_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
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
        "mnemonics": audit["mnemonics"],
        "normalized_sha256": audit["normalized_loop_sha256"],
        "binary_sha256": audit["binary_sha256"],
        "text_bytes": audit["text_bytes"],
    }


def screen(args: argparse.Namespace) -> dict[str, Any]:
    input_paths = {
        BASE_RELATIVE: (BASE, BASE_SHA256),
        RETAINED_RELATIVE: (RETAINED, RETAINED_SHA256),
        VERIFIER_RELATIVE: (VERIFIER, VERIFIER_SHA256),
        ARCHIVE_RELATIVE: (ARCHIVE, ARCHIVE_SHA256),
        PRIOR_SCREEN_RELATIVE: (PRIOR_SCREEN, PRIOR_SCREEN_SHA256),
    }
    for label, (path, expected) in input_paths.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"{label}: expected {expected}, got {actual}")
    tools = {
        "objdump": args.objdump,
        "size": args.size,
        "llvm_mca": args.llvm_mca,
    }
    for name, path in tools.items():
        if not path.is_file():
            raise RuntimeError(f"required tool is missing: {path}")
        actual = sha256(path)
        if actual != HOST_TOOL_HASHES[name]:
            raise RuntimeError(
                f"{name} hash mismatch: expected {HOST_TOOL_HASHES[name]}, got {actual}"
            )
    image_id = run(
        [args.runtime, "image", "inspect", "--format", "{{.Id}}", IMAGE]
    ).stdout.strip()
    if image_id != f"sha256:{IMAGE_DIGEST}":
        raise RuntimeError(f"unexpected image id: {image_id}")

    with tempfile.TemporaryDirectory(prefix="ch2-avx2-inline-asm-alloc-") as raw:
        temporary = Path(raw)
        source_reports = generate_variants(temporary / "variants")
        compiled, output = compile_and_verify(
            args, temporary, temporary / "variants", source_reports
        )
        if compiled["compiler"] != EXPECTED_COMPILER:
            raise RuntimeError(f"unexpected compiler: {compiled['compiler']}")
        if compiled["verifier_build"]["returncode"] != 0:
            raise RuntimeError("pinned verifier translation unit failed to compile")

        cases: dict[str, Any] = {}
        mca_cache: dict[str, dict[str, Any]] = {}
        for name, source in source_reports.items():
            raw_case = compiled["reports"][name]
            full_build = raw_case["full_build"]
            if full_build is None or full_build["returncode"] != 0:
                cases[name] = {
                    **source,
                    "status": "COMPILE_FAIL",
                    "diagnostic": "" if full_build is None else (
                        full_build["stderr"].strip()
                        or full_build["stdout"].strip()
                    )[:500],
                    "verification": verification_report(raw_case["verification"]),
                    "official_vectors": official_report(
                        raw_case["official_vectors"]
                    ),
                    "supplied_default_gcc": {
                        "flags": SUPPLIED_DEFAULT_FLAGS,
                        "build_returncode": raw_case[
                            "supplied_default_build"
                        ]["returncode"],
                        "official_vectors": official_report(
                            raw_case["supplied_default_official_vectors"]
                        ),
                    },
                }
                continue
            binary = output / name
            audit = audit_main_timing_loop(
                binary,
                objdump=str(args.objdump),
                size_tool=str(args.size),
            )
            errors = structural_errors(audit)
            loop_hash = audit["normalized_loop_sha256"]
            if loop_hash not in mca_cache:
                loop = temporary / f"loop-{loop_hash}.s"
                extract_loop(binary, loop, args.objdump)
                mca_cache[loop_hash] = {
                    "loop_artifact_sha256": sha256(loop),
                    "llvm_mca": analyse_loop(args.llvm_mca, loop),
                }
            semantic = verification_report(raw_case["verification"])
            official = official_report(raw_case["official_vectors"])
            status = (
                "PASS"
                if not errors
                and semantic["status"] == "PASS"
                and official["status"] == "PASS"
                else "AUDIT_FAIL"
                if errors
                else "CORRECTNESS_FAIL"
            )
            cases[name] = {
                **source,
                "status": status,
                "structural_errors": errors,
                "compile": {
                    "effective_flags": COMMON_FLAGS,
                    "full_build_returncode": full_build["returncode"],
                    "candidate_object_build_returncode": raw_case[
                        "candidate_object_build"
                    ]["returncode"],
                    "link_returncode": raw_case["link"]["returncode"],
                },
                "supplied_default_gcc": {
                    "flags": SUPPLIED_DEFAULT_FLAGS,
                    "build_returncode": raw_case["supplied_default_build"][
                        "returncode"
                    ],
                    "build_stderr": raw_case["supplied_default_build"][
                        "stderr"
                    ],
                    "official_vectors": official_report(
                        raw_case["supplied_default_official_vectors"]
                    ),
                },
                "loop": compact_audit(audit),
                **mca_cache[loop_hash],
                "verification": semantic,
                "official_vectors": official,
            }

    baseline = cases["intrinsics_baseline"]
    if baseline["status"] != "PASS":
        raise RuntimeError("intrinsics baseline failed its exact gates")
    baseline_loop = baseline["loop"]
    for case in cases.values():
        if "loop" not in case:
            continue
        case["delta_vs_intrinsics_baseline"] = {
            "instructions": (
                case["loop"]["instructions"] - baseline_loop["instructions"]
            ),
            "bytes": case["loop"]["bytes"] - baseline_loop["bytes"],
            "memory_operands_excluding_lea": (
                case["loop"]["memory_operands_excluding_lea"]
                - baseline_loop["memory_operands_excluding_lea"]
            ),
            "alderlake_proxy_cycles": (
                case["llvm_mca"]["alderlake_p_core_proxy"][
                    "cycles_per_iteration"
                ]
                - baseline["llvm_mca"]["alderlake_p_core_proxy"][
                    "cycles_per_iteration"
                ]
            ),
            "znver2_proxy_cycles": (
                case["llvm_mca"]["znver2_cross_architecture_proxy"][
                    "cycles_per_iteration"
                ]
                - baseline["llvm_mca"]["znver2_cross_architecture_proxy"][
                    "cycles_per_iteration"
                ]
            ),
        }

    strict_winners = [
        name
        for name, case in cases.items()
        if name != "intrinsics_baseline"
        and case["status"] == "PASS"
        and case["loop"]["instructions"] <= baseline_loop["instructions"]
        and case["loop"]["bytes"] < baseline_loop["bytes"]
        and case["loop"]["memory_operands_excluding_lea"] == 0
        and case["loop"]["calls"] == 0
        and case["loop"]["push_pop"] == 0
        and case["supplied_default_gcc"]["build_returncode"] == 0
        and case["supplied_default_gcc"]["official_vectors"]["status"] == "PASS"
    ]
    strict_winners.sort(
        key=lambda name: (
            cases[name]["loop"]["instructions"],
            cases[name]["loop"]["bytes"],
            name,
        )
    )
    retained = strict_winners[0] if strict_winners else None
    if retained is not None and cases[retained]["sha256"] != RETAINED_SHA256:
        raise RuntimeError(
            "generated retained candidate does not match the pinned retained source"
        )
    prior_case = json.loads(PRIOR_SCREEN.read_text())["screens"]["gcc"]["cases"][
        "gcc_ira_one"
    ]
    if (
        prior_case["status"] != "PASS"
        or prior_case["loop"]["instructions"] != 122
        or prior_case["loop"]["bytes"] != 569
        or prior_case["loop"]["memory_operands_excluding_lea"] != 0
        or prior_case["loop"]["normalized_sha256"]
        != PRIOR_GCC_IRA_ONE_NORMALIZED_SHA256
        or prior_case["llvm_mca"]["alderlake_p_core_proxy"][
            "cycles_per_iteration"
        ]
        != 100.03
        or prior_case["llvm_mca"]["znver2_cross_architecture_proxy"][
            "cycles_per_iteration"
        ]
        != 180.03
    ):
        raise RuntimeError("pinned prior GCC IRA-one comparison changed")
    failures = []
    for name, case in cases.items():
        if name == "intrinsics_baseline" or name in strict_winners:
            continue
        reason = (
            "; ".join(case.get("structural_errors", []))
            if case["status"] != "PASS"
            else "did not strictly reduce exact loop bytes at no instruction/memory cost"
        )
        failures.append({"name": name, "reason": reason})

    host_measurement: dict[str, Any] = {}
    if retained is not None:
        for relative_path in HOST_TIMING_RELATIVES:
            path = ROOT / relative_path
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
                    or sha256(ROOT / expected_path) != expected_hash
                ):
                    raise RuntimeError(
                        f"{relative_path}: stale {protocol_name} timing provenance"
                    )
            for source_name, expected in TIMING_SOURCES.items():
                recorded = timing["sources"].get(source_name)
                expected_context = [
                    "-iquote",
                    str((ROOT / expected["path"]).parent),
                ]
                if (
                    recorded is None
                    or recorded["path"] != expected["path"]
                    or recorded["sha256"] != expected["sha256"]
                    or recorded["case_cflags"] != expected["case_cflags"]
                    or recorded.get("source_context_cflags") != expected_context
                    or sha256(ROOT / expected["path"]) != expected["sha256"]
                ):
                    raise RuntimeError(
                        f"{relative_path}: stale {source_name} timing source provenance"
                    )
            for name in ("current", "inline_asm"):
                if (
                    timing["candidate_verification"][name]["status"] != "PASS"
                    or timing["assembly_audits"][name]["status"] != "PASS"
                ):
                    raise RuntimeError(f"{relative_path}: {name} validation failed")
            if (
                timing["assembly_audits"]["current"]["normalized_loop_sha256"]
                != baseline_loop["normalized_sha256"]
                or timing["assembly_audits"]["inline_asm"][
                    "normalized_loop_sha256"
                ]
                != cases[retained]["loop"]["normalized_sha256"]
            ):
                raise RuntimeError(f"{relative_path}: measured loop hash mismatch")
            host_measurement[f"cpu{affinity[0]}"] = {
                "path": relative_path,
                "sha256": sha256(path),
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
                "baseline_median_ns": timing["summaries"]["current"][
                    "median_ns"
                ],
                "candidate_median_ns": timing["summaries"]["inline_asm"][
                    "median_ns"
                ],
                "paired_median_speedup": timing["comparisons"]["inline_asm"][
                    "paired_median"
                ],
                "paired_bootstrap_ci95": [
                    timing["comparisons"]["inline_asm"][
                        "paired_bootstrap_ci95_low"
                    ],
                    timing["comparisons"]["inline_asm"][
                        "paired_bootstrap_ci95_high"
                    ],
                ],
            }

    return {
        "schema_version": 1,
        "scope": {
            "challenge": 2,
            "question": (
                "Can a bounded single-block AVX2 inline-assembly allocation "
                "remove the fixed-register experiment's hot-loop reload while "
                "preserving or shrinking the exact GCC 13 loop?"
            ),
            "host_timing_performed": True,
            "variants_attempted": len(cases),
            "search_policy": (
                "enumerated allocator-chosen, partial-pinning, and two "
                "encoding-aware low/high layouts; no register-map brute force"
            ),
            "contest_edit_scope": (
                "generated candidates change only the single contest C source; "
                "the public API, vector checks, timing loop, state, and dynamic "
                "constants remain unchanged"
            ),
        },
        "protocol": {
            "compiler_image": IMAGE,
            "compiler_image_id": image_id,
            "compiler": EXPECTED_COMPILER,
            "common_flags": COMMON_FLAGS,
            "supplied_default_command": [
                "gcc",
                *SUPPLIED_DEFAULT_FLAGS,
                "-o",
                "contest",
                "contest.c",
            ],
            "complete_binary_clock_delimited_loop_audit": True,
            "official_vectors": {
                "one_round_pairs": 1_000,
                "twenty_round_cases": 1,
            },
            "random_differential": {
                "cases_per_variant": 100_000,
                "random_state_and_constants": True,
                "round_counts": [1, 20],
                "seed": "0x243f6a8885a308d3",
            },
            "llvm_mca": {
                "iterations": MCA_ITERATIONS,
                "models": MCA_MODELS,
                "qualification": (
                    "static scheduling proxies only; neither model is the "
                    "unavailable Intel 255H target"
                ),
            },
        },
        "inputs": {
            label: {"sha256": expected}
            for label, (_, expected) in input_paths.items()
        },
        "host_tools": {
            name: {"path": str(path), "sha256": HOST_TOOL_HASHES[name]}
            for name, path in tools.items()
        },
        "cases": cases,
        "host_measurement": host_measurement,
        "decision": {
            "baseline": "intrinsics_baseline",
            "baseline_loop": {
                "instructions": baseline_loop["instructions"],
                "bytes": baseline_loop["bytes"],
                "memory_operands_excluding_lea": baseline_loop[
                    "memory_operands_excluding_lea"
                ],
            },
            "strict_winners": strict_winners,
            "best_generated_variant": retained,
            "retained_candidate_path": (
                None if retained is None else RETAINED_RELATIVE
            ),
            "retained_candidate_source_sha256": (
                None if retained is None else cases[retained]["sha256"]
            ),
            "retained_candidate_supplied_default_gcc": (
                None
                if retained is None
                else {
                    "build_passed": (
                        cases[retained]["supplied_default_gcc"][
                            "build_returncode"
                        ]
                        == 0
                    ),
                    "official_vectors_passed": (
                        cases[retained]["supplied_default_gcc"][
                            "official_vectors"
                        ]["status"]
                        == "PASS"
                    ),
                }
            ),
            "comparison_to_prior_gcc_ira_one": (
                None
                if retained is None
                else {
                    "prior_normalized_loop_sha256": (
                        PRIOR_GCC_IRA_ONE_NORMALIZED_SHA256
                    ),
                    "generated_normalized_loop_sha256": cases[retained][
                        "loop"
                    ]["normalized_sha256"],
                    "same_normalized_loop": (
                        cases[retained]["loop"]["normalized_sha256"]
                        == PRIOR_GCC_IRA_ONE_NORMALIZED_SHA256
                    ),
                    "interpretation": (
                        "the generated source ties gcc_ira_one at 122 "
                        "instructions, 569 bytes, zero hot memory, and both "
                        "proxy cycle counts, but its register assignment gives "
                        "a distinct normalized instruction stream"
                    ),
                }
            ),
            "reason": (
                "No generated inline-assembly allocation passed every gate "
                "and strictly reduced exact loop bytes."
                if retained is None
                else (
                    f"{retained} removed the loop reload, retained 122 "
                    f"instructions and zero hot-loop memory operands, and "
                    f"reduced the loop from {baseline_loop['bytes']} to "
                    f"{cases[retained]['loop']['bytes']} bytes."
                )
            ),
            "promotion_limit": (
                "two AMD affinities measured only a statistical tie, and "
                "static code shape and proxy scheduling are not 255H timing; "
                "the candidate requires independent P/E/LP-E timing before "
                "submission promotion"
            ),
        },
        "failed_strategy_summary": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE / "avx2_inline_asm_alloc_results_02.json",
    )
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--objdump", type=Path, default=DEFAULT_OBJDUMP)
    parser.add_argument("--size", type=Path, default=DEFAULT_SIZE)
    parser.add_argument("--llvm-mca", type=Path, default=DEFAULT_LLVM_MCA)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    report = screen(args)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file():
            raise RuntimeError(f"result does not exist: {args.output}")
        if args.output.read_text() != rendered:
            raise RuntimeError(f"result is stale: {args.output}")
        print(f"inline-asm allocation screen: PASS ({len(report['cases'])} cases)")
        return 0
    args.output.write_text(rendered)
    print(f"wrote {args.output}")
    print(report["decision"]["reason"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
