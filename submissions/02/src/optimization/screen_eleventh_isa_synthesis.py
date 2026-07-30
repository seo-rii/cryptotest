#!/usr/bin/env python3
"""Reproduce challenge 2's final bounded AVX2 ISA-synthesis screen.

This experiment deliberately starts outside the retained six-instruction
round dataflow.  It asks whether BSWAP64 and a non-byte ROL can be fused into
a three-instruction AVX2 linear network, checks the tempting shuffle/rotate
and cross-round shuffle-cancellation identities on all basis bits or concrete
counterexamples, and compiles three exact seven-instruction split-shuffle
networks as constructive controls.

The generated C variants are derived from a pinned source in a pinned GCC
13.3 container.  Every compiled variant must pass the official vectors and a
100,000-case arbitrary-state/arbitrary-constant differential verifier for
1/20 rounds.  The complete clock-delimited loop is independently audited and
each distinct stream is passed through LLVM-MCA scheduling proxies.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
TENTH_DRIVER = HERE / "screen_tenth_codegen.py"
TENTH_DRIVER_SHA256 = (
    "ba0cba40aba083e18010ba0fd0de27e4a3df6c8528b2c5ca9ca7467ec4ca5b19"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_tenth_harness() -> Any:
    actual = sha256(TENTH_DRIVER)
    if actual != TENTH_DRIVER_SHA256:
        raise RuntimeError(
            "tenth-pass harness drifted: "
            f"expected {TENTH_DRIVER_SHA256}, got {actual}"
        )
    spec = importlib.util.spec_from_file_location(
        "challenge_tenth_codegen_harness", TENTH_DRIVER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import pinned harness: {TENTH_DRIVER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HARNESS = load_tenth_harness()

BASELINE_LOOP_SHA256 = HARNESS.BASELINE_LOOP_SHA256
BASELINE_BYTES = HARNESS.BASELINE_LOOP_BYTES
BASELINE_INSTRUCTIONS = HARNESS.BASELINE_LOOP_INSTRUCTIONS
MASK64 = (1 << 64) - 1
ROTATIONS = (43, 7, 29, 14)
ADD_CONSTANTS = (
    0x8F4A2C1E9B7D3F61,
    0x3C6E9A1D5B7F2840,
    0xA7E2D9C4B1F60853,
    0x5D0F3A8E2C6B4197,
)
LLVM19_MCA = Path("/tmp/llvm19-root/usr/lib/llvm-19/bin/llvm-mca")
LLVM19_MCA_SHA256 = (
    "e270ee6e5cc86a6751d05fb0dc2233b42bc5e6d51a3db36cee2c0e0d30db62e8"
)
LLVM19_LIB_DIR = Path("/tmp/llvm19-root/usr/lib/x86_64-linux-gnu")
LLVM19_LIBLLVM_SHA256 = (
    "e7f2b36074692218cb7bbd3db64f76f1e4c6771c5411ff23376639dbfdd6f516"
)
LLVM19_EXPECTED_VERSION = "Debian LLVM version 19.1.7"
LLVM19_DEBIAN_VERSION = "1:19.1.7-3~deb12u1"
LLVM19_DEBIAN_PACKAGES = {
    "llvm-19": {
        "deb_sha256": (
            "f91492c5b361ff12f540b9f6145cf638b5e0fb3f145fceabd6c4b9540eab4bf9"
        )
    },
    "libllvm19": {
        "deb_sha256": (
            "6edf3a8b28495cdba883d9760e0dca1a81983fc497a5f989dc64d0d96d23b4aa"
        )
    },
}
LLVM19_X86_TD_URL = (
    "https://github.com/llvm/llvm-project/blob/llvmorg-19.1.7/"
    "llvm/lib/Target/X86/X86.td"
)
LLVM19_X86_TD_RAW_URL = (
    "https://raw.githubusercontent.com/llvm/llvm-project/llvmorg-19.1.7/"
    "llvm/lib/Target/X86/X86.td"
)
LLVM19_X86_TD_SHA256 = (
    "508d06091c7eff91833a23fe4272dac8d7e99515cc335264b039f7812c1c8c3a"
)
LLVM19_MODELS = {
    "alderlake_llvm19_control": "alderlake",
    "meteorlake_llvm19_control": "meteorlake",
    "arrowlake_mobile_proxy": "arrowlake",
    "arrowlake_s_proxy": "arrowlake-s",
    "lunarlake_related_proxy": "lunarlake",
    "sierraforest_e_core_proxy": "sierraforest",
}
LLVM19_ITERATIONS = 100


SPLIT_SHUFFLE_LATE_XOR = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpshufb %[byte_swap], %[scratch], %[scratch]\n\t"                  \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                      \
    "vpxor %[scratch], %[value], %[value]\n\t"                          \
    "vpxor %[value], %[" XOR_VALUE "], %[value]\n\t"                    \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"
'''

SPLIT_SHUFFLE_LATE_ADD = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpshufb %[byte_swap], %[scratch], %[scratch]\n\t"                  \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                      \
    "vpaddq %[scratch], %[value], %[value]\n\t"                         \
    "vpxor %[value], %[" XOR_VALUE "], %[value]\n\t"                    \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"
'''

SPLIT_SHUFFLE_EARLY_XOR = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpxor %[scratch], %[" XOR_VALUE "], %[scratch]\n\t"                \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpshufb %[byte_swap], %[scratch], %[scratch]\n\t"                  \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                      \
    "vpxor %[scratch], %[value], %[value]\n\t"                          \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"
'''

ONE_ROUND_HOOK_SITE = """PERMUTE20_ATTRIBUTE static void permute_20rounds_unrolled(
"""
ONE_ROUND_ORIGINAL_BODY = (
    "    rotate_words_left_64wise(state, rot); "
    "xor_constants_256wise(state, constants2); "
    "shuffle_bytes_256(state, shuffle_map); "
    "add_constants_64wise(state, constants1);\n"
)


def one_round_hook(pre_swap_xor: bool) -> str:
    pre_swap = (
        "    xor_forward = _mm256_shuffle_epi8(xor_forward, byte_swap);\n"
        if pre_swap_xor
        else ""
    )
    return f"""__attribute__((noinline, target("avx2")))
static void eleventh_candidate_one_round(
    state256_t *restrict state,
    const uint64_t constants2[restrict 4],
    const uint64_t constants1[restrict 4]) {{
    register __m256i value __asm__("ymm0") =
        _mm256_loadu_si256((const __m256i *)(const void *)state);
    __m256i xor_forward =
        _mm256_loadu_si256((const __m256i *)(const void *)constants2);
    __m256i add_reverse =
        _mm256_permute4x64_epi64(
            _mm256_loadu_si256((const __m256i *)(const void *)constants1),
            _MM_SHUFFLE(0, 1, 2, 3));
    __m256i scratch;
    __m256i left_forward =
        _mm256_setr_epi64x(43, 7, 29, 14);
    __m256i right_forward =
        _mm256_setr_epi64x(21, 57, 35, 50);
    __m256i byte_swap =
        _mm256_setr_epi8(
            7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8,
            7, 6, 5, 4, 3, 2, 1, 0, 15, 14, 13, 12, 11, 10, 9, 8);
{pre_swap}
    __asm__(
        INLINE_ASM_TRANSFORM("left_forward", "right_forward", "xor_forward",
                             "add_reverse")
        : [value] "+x"(value), [scratch] "=&x"(scratch)
        : [xor_forward] "x"(xor_forward), [add_reverse] "x"(add_reverse),
          [left_forward] "x"(left_forward), [right_forward] "x"(right_forward),
          [byte_swap] "x"(byte_swap));

    value = _mm256_permute4x64_epi64(value, _MM_SHUFFLE(0, 1, 2, 3));
    _mm256_storeu_si256((__m256i *)(void *)state, value);
}}

PERMUTE20_ATTRIBUTE static void permute_20rounds_unrolled(
"""


def case_specs() -> dict[str, dict[str, Any]]:
    return {
        "baseline": {
            "description": "retained six-instruction transform",
            "macro": HARNESS.CURRENT_MACRO,
            "pre_swap_xor": False,
            "expected_bytes": 549,
            "expected_instructions": 122,
            "expected_mnemonics": {
                "vpsrlvq": 20,
                "vpsllvq": 20,
                "vpor": 20,
                "vpxor": 20,
                "vpshufb": 20,
                "vpaddq": 20,
                "sub": 1,
                "jne": 1,
            },
        },
        "split_shuffle_late_xor": {
            "description": (
                "shuffle the two complementary shift branches independently, "
                "XOR-merge them, then apply the pre-shuffled XOR constant"
            ),
            "macro": SPLIT_SHUFFLE_LATE_XOR,
            "pre_swap_xor": True,
            "expected_bytes": 669,
            "expected_instructions": 142,
            "expected_mnemonics": {
                "vpsrlvq": 20,
                "vpsllvq": 20,
                "vpor": 0,
                "vpxor": 40,
                "vpshufb": 40,
                "vpaddq": 20,
                "sub": 1,
                "jne": 1,
            },
        },
        "split_shuffle_late_add": {
            "description": (
                "same split-shuffle network, using carry-free VPADDQ to merge "
                "the disjoint shifted bit fields"
            ),
            "macro": SPLIT_SHUFFLE_LATE_ADD,
            "pre_swap_xor": True,
            "expected_bytes": 669,
            "expected_instructions": 142,
            "expected_mnemonics": {
                "vpsrlvq": 20,
                "vpsllvq": 20,
                "vpor": 0,
                "vpxor": 20,
                "vpshufb": 40,
                "vpaddq": 40,
                "sub": 1,
                "jne": 1,
            },
        },
        "split_shuffle_early_xor": {
            "description": (
                "put the round XOR on the right-shift branch before the two "
                "independent byte shuffles"
            ),
            "macro": SPLIT_SHUFFLE_EARLY_XOR,
            "pre_swap_xor": False,
            "expected_bytes": 689,
            "expected_instructions": 142,
            "expected_mnemonics": {
                "vpsrlvq": 20,
                "vpsllvq": 20,
                "vpor": 0,
                "vpxor": 40,
                "vpshufb": 40,
                "vpaddq": 20,
                "sub": 1,
                "jne": 1,
            },
        },
    }


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one replacement site, got {count}")
    return text.replace(old, new)


def generate_sources(
    destination: Path, cases: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    base = HARNESS.SOURCE.read_text()
    if base.count(HARNESS.CURRENT_MACRO) != 1:
        raise RuntimeError("retained inline-assembly macro drifted")
    destination.mkdir()
    reports: dict[str, dict[str, Any]] = {}
    for name, case in cases.items():
        text = base
        if case["macro"] != HARNESS.CURRENT_MACRO:
            text = replace_exact(
                text,
                HARNESS.CURRENT_MACRO,
                case["macro"],
                f"{name} transform",
            )
        if case["pre_swap_xor"]:
            text = replace_exact(
                text,
                HARNESS.PRE_SWAP_INSERTION_POINT,
                HARNESS.PRE_SWAP_INSERTION,
                f"{name} pre-shuffled constants",
            )
        text = replace_exact(
            text,
            ONE_ROUND_HOOK_SITE,
            one_round_hook(bool(case["pre_swap_xor"])),
            f"{name} candidate one-round hook",
        )
        text = replace_exact(
            text,
            ONE_ROUND_ORIGINAL_BODY,
            (
                "    (void)rot;\n"
                "    (void)shuffle_map;\n"
                "    eleventh_candidate_one_round(state, constants2, "
                "constants1);\n"
            ),
            f"{name} one-round candidate dispatch",
        )
        path = destination / f"{name}.c"
        path.write_text(text)
        reports[name] = {
            "base_source": HARNESS.SOURCE_RELATIVE,
            "base_source_sha256": sha256(HARNESS.SOURCE),
            "generated_source_sha256": sha256_bytes(text.encode()),
            "recipe": {
                "macro_sha256": sha256_bytes(case["macro"].encode()),
                "pre_swap_xor_constants": case["pre_swap_xor"],
                "candidate_one_round_hook": True,
            },
        }
    return reports


def validate_inputs(args: argparse.Namespace) -> dict[str, Any]:
    inputs = HARNESS.validate_inputs(args)
    inputs["reused_harness"] = {
        "path": str(TENTH_DRIVER.relative_to(ROOT)),
        "expected_sha256": TENTH_DRIVER_SHA256,
        "actual_sha256": sha256(TENTH_DRIVER),
        "scope": (
            "container build, official/random verifier, loop parser, and "
            "LLVM-MCA plumbing only; candidate generation and shape contracts "
            "are defined by this driver"
        ),
    }
    inputs["driver"] = {
        "path": str(Path(__file__).resolve().relative_to(ROOT)),
        "sha256": sha256(Path(__file__).resolve()),
    }
    if not args.llvm19_mca.is_file():
        raise RuntimeError(f"missing LLVM 19 llvm-mca: {args.llvm19_mca}")
    if not args.llvm19_lib_dir.is_dir():
        raise RuntimeError(
            f"missing LLVM 19 library directory: {args.llvm19_lib_dir}"
        )
    llvm19_library = args.llvm19_lib_dir / "libLLVM.so.19.1"
    if not llvm19_library.is_file():
        raise RuntimeError(f"missing LLVM 19 libLLVM: {llvm19_library}")
    actual_binary = sha256(args.llvm19_mca)
    actual_library = sha256(llvm19_library)
    if actual_binary != LLVM19_MCA_SHA256:
        raise RuntimeError(
            "LLVM 19 llvm-mca hash mismatch: "
            f"expected {LLVM19_MCA_SHA256}, got {actual_binary}"
        )
    if actual_library != LLVM19_LIBLLVM_SHA256:
        raise RuntimeError(
            "LLVM 19 libLLVM hash mismatch: "
            f"expected {LLVM19_LIBLLVM_SHA256}, got {actual_library}"
        )
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = str(args.llvm19_lib_dir)
    version = subprocess.run(
        [str(args.llvm19_mca), "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    ).stdout.splitlines()[0]
    if version != LLVM19_EXPECTED_VERSION:
        raise RuntimeError(
            f"unexpected LLVM 19 version: expected {LLVM19_EXPECTED_VERSION}, "
            f"got {version}"
        )
    help_probe = subprocess.run(
        [str(args.llvm19_mca), "-mcpu=help"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    if help_probe.returncode != 1:
        raise RuntimeError(
            "unexpected LLVM 19 -mcpu=help status: "
            f"expected 1, got {help_probe.returncode}"
        )
    help_report = help_probe.stdout
    missing_models = [
        model
        for model in LLVM19_MODELS.values()
        if re.search(rf"^\s*{re.escape(model)}\s+-", help_report, re.MULTILINE)
        is None
    ]
    if missing_models:
        raise RuntimeError(f"LLVM 19 omitted expected models: {missing_models}")
    inputs["llvm19"] = {
        "binary": {
            "path": "<provided-by---llvm19-mca>",
            "sha256": actual_binary,
            "version": version,
        },
        "libLLVM": {
            "path": "<provided-by---llvm19-lib-dir>/libLLVM.so.19.1",
            "sha256": actual_library,
        },
        "runtime_environment": {
            "LD_LIBRARY_PATH": "<provided-by---llvm19-lib-dir>",
        },
        "models": LLVM19_MODELS,
        "acquisition": {
            "distribution": "Debian 12 bookworm/main",
            "packages": LLVM19_DEBIAN_PACKAGES,
            "package_version": LLVM19_DEBIAN_VERSION,
            "method": (
                "download the pinned llvm-19 and libllvm19 .deb files, extract "
                "them under any directory, and pass the resulting llvm-mca "
                "and library-directory paths through --llvm19-mca and "
                "--llvm19-lib-dir; runtime files remain content-addressed"
            ),
        },
        "scheduler_source_evidence": {
            "release_tag": "llvmorg-19.1.7",
            "path": "llvm/lib/Target/X86/X86.td",
            "url": LLVM19_X86_TD_URL,
            "raw_url": LLVM19_X86_TD_RAW_URL,
            "sha256": LLVM19_X86_TD_SHA256,
            "declaration": (
                'def : ProcModel<"arrowlake", AlderlakePModel, '
                "ProcessorFeatures.SRFFeatures, ProcessorFeatures.ADLTuning>;"
            ),
            "interpretation": (
                "LLVM 19 exposes the Arrow Lake CPU name but assigns it the "
                "AlderlakePModel scheduler. It is not an exact 255H model."
            ),
        },
    }
    return inputs


def compile_and_verify(
    args: argparse.Namespace,
    temporary: Path,
    cases: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Path, dict[str, Any], dict[str, dict[str, Any]]]:
    config = temporary / "config"
    output = temporary / "output"
    vectors = temporary / "vectors"
    variants = temporary / "variants"
    config.mkdir()
    output.mkdir()
    vectors.mkdir()
    source_reports = generate_sources(variants, cases)
    vector_reports = HARNESS.extract_vectors(vectors)
    manifest = {
        "verifier": HARNESS.VERIFIER_RELATIVE,
        "common_flags": HARNESS.COMMON_FLAGS,
        "supplied_default_flags": HARNESS.SUPPLIED_DEFAULT_FLAGS,
        "verifier_flags": HARNESS.VERIFIER_FLAGS,
        "official_markers": HARNESS.OFFICIAL_MARKERS,
        "cases": {name: {"cflags": []} for name in cases},
    }
    (config / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    HARNESS.run(
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
            f"{ROOT}:/repository:ro",
            "--volume",
            f"{variants}:/variants:ro",
            "--volume",
            f"{vectors}:/vectors:ro",
            "--volume",
            f"{output}:/output",
            HARNESS.IMAGE,
            "python3",
            "-c",
            HARNESS.CONTAINER_DRIVER,
        ]
    )
    report = json.loads((output / "build-report.json").read_text())
    return report, output, vector_reports, source_reports


def assert_loop_shape(
    name: str, case: dict[str, Any], audit: dict[str, Any]
) -> None:
    for key in ("calls", "push_pop", "memory_operands_excluding_lea"):
        if audit[key] != 0:
            raise RuntimeError(f"{name}: expected {key}=0, got {audit[key]}")
    if audit["loop_instructions"] != case["expected_instructions"]:
        raise RuntimeError(
            f"{name}: expected {case['expected_instructions']} instructions, "
            f"got {audit['loop_instructions']}"
        )
    if audit["loop_bytes"] != case["expected_bytes"]:
        raise RuntimeError(
            f"{name}: expected {case['expected_bytes']} bytes, "
            f"got {audit['loop_bytes']}"
        )
    relevant = {
        "vpsrlvq",
        "vpsllvq",
        "vpor",
        "vpxor",
        "vpshufb",
        "vpaddq",
        "sub",
        "dec",
        "jne",
    }
    for mnemonic in sorted(relevant | set(case["expected_mnemonics"])):
        wanted = case["expected_mnemonics"].get(mnemonic, 0)
        actual = audit["mnemonics"].get(mnemonic, 0)
        if actual != wanted:
            raise RuntimeError(
                f"{name}: expected {wanted} {mnemonic}, got {actual}"
            )


def rol64(value: int, amount: int) -> int:
    return ((value << amount) | (value >> (64 - amount))) & MASK64


def ror64(value: int, amount: int) -> int:
    return ((value >> amount) | (value << (64 - amount))) & MASK64


def bswap64(value: int) -> int:
    return int.from_bytes(value.to_bytes(8, "little"), "big")


def permutation_map(function: Any) -> tuple[int, ...]:
    """Return output-bit -> input-bit for a one-bit-preserving transform."""

    inverse = [-1] * 64
    for source in range(64):
        output = function(1 << source)
        if output == 0 or output & (output - 1):
            raise RuntimeError("expected a one-bit-preserving transform")
        destination = output.bit_length() - 1
        if inverse[destination] != -1:
            raise RuntimeError("transform is not a permutation")
        inverse[destination] = source
    if any(source < 0 for source in inverse):
        raise RuntimeError("transform is not onto")
    return tuple(inverse)


def shift_map(direction: str, amount: int) -> tuple[int | None, ...]:
    result: list[int | None] = []
    for output in range(64):
        source = output - amount if direction == "left" else output + amount
        result.append(source if 0 <= source < 64 else None)
    return tuple(result)


def shuffle_byte_map(choice: int | None) -> tuple[int | None, ...]:
    """Map one output byte for an arbitrary word-local VPSHUFB selector."""

    if choice is None:
        return (None,) * 8
    return tuple(8 * choice + bit for bit in range(8))


def combine_matches(
    left: int | None,
    right: int | None,
    target: int,
    operation: str,
) -> bool:
    if operation == "xor":
        return (
            (left == target and right is None)
            or (right == target and left is None)
        )
    if operation == "or":
        return (
            left in (None, target)
            and right in (None, target)
            and (left == target or right == target)
        )
    raise ValueError(operation)


def two_shift_solutions(
    target: tuple[int, ...], operation: str
) -> list[dict[str, Any]]:
    solutions: list[dict[str, Any]] = []
    for left_direction in ("left", "right"):
        for right_direction in ("left", "right"):
            for left_amount in range(64):
                left = shift_map(left_direction, left_amount)
                for right_amount in range(64):
                    right = shift_map(right_direction, right_amount)
                    if all(
                        combine_matches(a, b, wanted, operation)
                        for a, b, wanted in zip(
                            left, right, target, strict=True
                        )
                    ):
                        solutions.append(
                            {
                                "left": [left_direction, left_amount],
                                "right": [right_direction, right_amount],
                            }
                        )
    return solutions


def shift_shuffle_solutions(
    target: tuple[int, ...], operation: str
) -> list[dict[str, Any]]:
    solutions: list[dict[str, Any]] = []
    choices: tuple[int | None, ...] = (*range(8), None)
    for direction in ("left", "right"):
        for amount in range(64):
            shifted = shift_map(direction, amount)
            mask: list[int | None] = []
            possible = True
            for byte in range(8):
                byte_shift = shifted[8 * byte : 8 * byte + 8]
                matching = [
                    choice
                    for choice in choices
                    if all(
                        combine_matches(a, b, wanted, operation)
                        for a, b, wanted in zip(
                            byte_shift,
                            shuffle_byte_map(choice),
                            target[8 * byte : 8 * byte + 8],
                            strict=True,
                        )
                    )
                ]
                if not matching:
                    possible = False
                    break
                mask.append(matching[0])
            if possible:
                solutions.append(
                    {
                        "shift": [direction, amount],
                        "shuffle_output_byte_sources": mask,
                    }
                )
    return solutions


def two_shuffle_solutions(
    target: tuple[int, ...], operation: str
) -> list[dict[str, Any]]:
    choices: tuple[int | None, ...] = (*range(8), None)
    masks: list[list[list[int | None]]] = []
    for byte in range(8):
        matching: list[list[int | None]] = []
        wanted_byte = target[8 * byte : 8 * byte + 8]
        for left_choice in choices:
            for right_choice in choices:
                if all(
                    combine_matches(a, b, wanted, operation)
                    for a, b, wanted in zip(
                        shuffle_byte_map(left_choice),
                        shuffle_byte_map(right_choice),
                        wanted_byte,
                        strict=True,
                    )
                ):
                    matching.append([left_choice, right_choice])
        if not matching:
            return []
        masks.append(matching)
    return [
        {
            "per_output_byte_choice_count": [len(options) for options in masks],
            "representative": [options[0] for options in masks],
        }
    ]


def one_instruction_solutions(
    target: tuple[int, ...],
) -> dict[str, list[Any]]:
    shifts = [
        [direction, amount]
        for direction in ("left", "right")
        for amount in range(64)
        if shift_map(direction, amount) == target
    ]
    byte_sources: list[int] = []
    byte_shuffle_possible = True
    for byte in range(8):
        wanted = target[8 * byte : 8 * byte + 8]
        matching = [
            source
            for source in range(8)
            if shuffle_byte_map(source) == wanted
        ]
        if not matching:
            byte_shuffle_possible = False
            break
        byte_sources.append(matching[0])
    return {
        "qword_shifts": shifts,
        "byte_shuffles": [byte_sources] if byte_shuffle_possible else [],
    }


def three_instruction_linear_search() -> dict[str, Any]:
    by_rotation: dict[str, Any] = {}
    all_solution_count = 0
    one_instruction_solution_count = 0
    for rotation in ROTATIONS:
        target = permutation_map(
            lambda value, amount=rotation: bswap64(rol64(value, amount))
        )
        one_instruction = one_instruction_solutions(target)
        one_instruction_solution_count += sum(
            len(solutions) for solutions in one_instruction.values()
        )
        shapes: dict[str, Any] = {}
        for operation in ("xor", "or"):
            results = {
                "two_qword_shifts": two_shift_solutions(target, operation),
                "qword_shift_plus_arbitrary_byte_shuffle": (
                    shift_shuffle_solutions(target, operation)
                ),
                "two_arbitrary_byte_shuffles": (
                    two_shuffle_solutions(target, operation)
                ),
            }
            counts = {name: len(items) for name, items in results.items()}
            all_solution_count += sum(counts.values())
            shapes[operation] = {
                "solution_counts": counts,
                "solutions": results,
            }
        by_rotation[str(rotation)] = {
            "target_output_to_input_bits": list(target),
            "one_instruction_solutions": one_instruction,
            "combine_shapes": shapes,
        }
    if one_instruction_solution_count:
        raise RuntimeError("unexpected one-instruction target")
    return {
        "status": "UNSAT" if all_solution_count == 0 else "SAT",
        "parallel_two_unary_plus_combine_solution_count": all_solution_count,
        "one_instruction_solution_count": one_instruction_solution_count,
        "rotations": by_rotation,
        "grammar": {
            "exhaustively_enumerated_program_shape": (
                "two independent unary instructions from the input followed "
                "by XOR/OR; identity is admitted as a zero-count shift"
            ),
            "qword_shift": (
                "logical left/right by any independently chosen lane count "
                "0..63, granting more freedom than one shared immediate"
            ),
            "byte_shuffle": (
                "each output byte may independently choose any byte of the "
                "same 64-bit word or zero; this is a word-local superset of "
                "the selections useful to exact lane-preserving VPSHUFB"
            ),
            "combine": (
                "XOR or OR; carry-free ADD is identical to OR/XOR on disjoint "
                "bit fields and is therefore covered"
            ),
        },
        "other_three_instruction_dag_shapes": {
            "three_serial_unaries": (
                "A nonzero logical shift in a one-register unary chain leaves "
                "fewer than 64 distinct live source bits. A chain containing "
                "only byte shuffles preserves source/destination bit positions "
                "modulo eight. Neither can implement this 64-bit permutation "
                "with a non-byte rotate."
            ),
            "two_serial_unaries_then_combine_with_raw_or_intermediate": (
                "If the first unary is lossy, neither descendant branch can "
                "recover all 64 source bits. If it is bijective, it is an "
                "identity shift or byte permutation. Factoring that bijection "
                "leaves identity combined with one unary; XOR/OR can equal a "
                "one-bit projection at every output only when that projection "
                "is the identity. The whole DAG then collapses to the first "
                "one-instruction transform, for which the exhaustive solution "
                "count above is zero."
            ),
            "unary_after_one_unary_plus_raw_combine": (
                "The last unary must be bijective, because the target uses all "
                "64 source bits exactly once. Pulling back through it again "
                "leaves identity combined with one unary, which can only be "
                "the identity projection; the last unary would then have to "
                "be the target, contradicted by the zero one-instruction "
                "solution count."
            ),
            "one_unary_and_two_binary_combines": (
                "At each bit these DAGs compute one fixed two-input Boolean "
                "function of the raw bit and the unary-produced bit. To equal "
                "a bit permutation for every input, that function must reduce "
                "globally to one projection; the result is therefore identity "
                "or the sole unary, neither of which is the target."
            ),
            "coverage": (
                "Together with the exhaustively enumerated parallel branch "
                "shape, these are all topological placements of zero, one, or "
                "two binary operations in a three-operation single-input DAG."
            ),
        },
        "scope_limit": (
            "This is a lower bound only for AVX2 networks built from qword "
            "logical shifts, arbitrary fixed byte selections, and XOR/OR or "
            "carry-free ADD. It is not a lower bound over every x86 opcode."
        ),
    }


def first_basis_counterexample(left: Any, right: Any) -> dict[str, str] | None:
    for bit in range(64):
        value = 1 << bit
        expected = left(value)
        actual = right(value)
        if expected != actual:
            return {
                "input": f"0x{value:016x}",
                "left": f"0x{expected:016x}",
                "right": f"0x{actual:016x}",
            }
    return None


def identity_checks() -> dict[str, Any]:
    conjugation: dict[str, Any] = {}
    for rotation in ROTATIONS:
        counterexample = first_basis_counterexample(
            lambda value, amount=rotation: bswap64(rol64(value, amount)),
            lambda value, amount=rotation: ror64(bswap64(value), amount),
        )
        conjugation[str(rotation)] = {
            "identity": "BSWAP64(ROL_r(x)) == ROR_r(BSWAP64(x))",
            "basis_check": "FAIL" if counterexample else "PASS",
            "counterexample": counterexample,
            "qualification": (
                "The identity does hold when r is a multiple of eight, but "
                "none of the four challenge rotations is byte-aligned."
            ),
        }

    add_commutation: dict[str, Any] = {}
    for constant in ADD_CONSTANTS:
        swapped = bswap64(constant)
        counterexample = None
        # z=0 fixes any putative translated constant to BSWAP64(A).
        for value in range(1, 1 << 16):
            left = bswap64((value + constant) & MASK64)
            right = (bswap64(value) + swapped) & MASK64
            if left != right:
                counterexample = {
                    "input": f"0x{value:016x}",
                    "left": f"0x{left:016x}",
                    "right": f"0x{right:016x}",
                }
                break
        if counterexample is None:
            raise RuntimeError("unexpected missing BSWAP/ADD counterexample")
        add_commutation[f"0x{constant:016x}"] = {
            "identity": "BSWAP64(z + A) == BSWAP64(z) + BSWAP64(A)",
            "bounded_check": "FAIL",
            "counterexample": counterexample,
            "constant_at_zero_is_forced": f"0x{swapped:016x}",
        }

    byte_aligned_controls = {
        str(rotation): all(
            bswap64(rol64(1 << bit, rotation))
            == ror64(bswap64(1 << bit), rotation)
            for bit in range(64)
        )
        for rotation in range(0, 64, 8)
    }
    return {
        "shuffle_rotate_conjugation": conjugation,
        "byte_aligned_positive_controls": byte_aligned_controls,
        "shuffle_add_commutation": add_commutation,
        "cross_round_conclusion": (
            "XOR commutes with BSWAP after swapping the constant, but modular "
            "addition does not. The intervening first-round ADD therefore "
            "blocks cancellation of the two round-boundary byte shuffles."
        ),
    }


def simplified_execution(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "returncode": report["returncode"],
        "markers": report.get("markers"),
        "marker_lines": report.get("marker_lines"),
    }


def analyse_loop_llvm19(
    llvm_mca: Path, library_directory: Path, loop: Path
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = str(library_directory)
    reports: dict[str, Any] = {}
    for label, model in LLVM19_MODELS.items():
        completed = subprocess.run(
            [
                str(llvm_mca),
                f"-mcpu={model}",
                f"-iterations={LLVM19_ITERATIONS}",
                str(loop),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        reports[label] = {
            "model": model,
            "iterations": LLVM19_ITERATIONS,
            "cycles_per_iteration": (
                HARNESS.extract_number(completed.stdout, "Total Cycles")
                / LLVM19_ITERATIONS
            ),
            "instructions_per_iteration": (
                HARNESS.extract_number(completed.stdout, "Instructions")
                / LLVM19_ITERATIONS
            ),
            "uops_per_iteration": (
                HARNESS.extract_number(completed.stdout, "Total uOps")
                / LLVM19_ITERATIONS
            ),
            "block_rthroughput": HARNESS.extract_number(
                completed.stdout, "Block RThroughput"
            ),
        }
    return reports


def model_metric_signature(report: dict[str, Any]) -> str:
    metrics = {
        key: value
        for key, value in report.items()
        if key not in {"model", "iterations"}
    }
    return sha256_bytes(
        json.dumps(metrics, sort_keys=True, separators=(",", ":")).encode()
    )


def model_equivalence_groups(
    stream_reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    per_stream: dict[str, list[list[str]]] = {}
    same_partition_for_every_stream = True
    reference_partition: list[list[str]] | None = None
    for loop_hash, reports in sorted(stream_reports.items()):
        groups: dict[str, list[str]] = {}
        for label, report in reports.items():
            groups.setdefault(model_metric_signature(report), []).append(label)
        partition = sorted(sorted(group) for group in groups.values())
        per_stream[loop_hash] = partition
        if reference_partition is None:
            reference_partition = partition
        elif partition != reference_partition:
            same_partition_for_every_stream = False
    return {
        "metric": (
            "exact equality of cycles, instructions, uops, and block "
            "RThroughput for the same normalized stream"
        ),
        "same_partition_for_every_stream": same_partition_for_every_stream,
        "partitions_by_stream": per_stream,
        "common_partition": (
            reference_partition if same_partition_for_every_stream else None
        ),
    }


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    inputs = validate_inputs(args)
    cases = case_specs()
    synthesis = three_instruction_linear_search()
    if synthesis["status"] != "UNSAT":
        raise RuntimeError("unexpected three-instruction solution")
    identities = identity_checks()

    with tempfile.TemporaryDirectory(
        prefix="challenge-eleventh-isa-"
    ) as raw_temporary:
        temporary = Path(raw_temporary).resolve()
        compiled, binaries, vectors, source_reports = compile_and_verify(
            args, temporary, cases
        )
        HARNESS.fail_if_build_or_correctness_failed(compiled, cases)

        case_results: dict[str, Any] = {}
        stream_members: dict[str, list[str]] = {}
        representatives: dict[str, str] = {}
        for name, case in cases.items():
            binary = binaries / name
            audit = HARNESS.audit_main_timing_loop(
                binary,
                objdump=str(args.objdump),
                size_tool=str(args.size_tool),
            )
            assert_loop_shape(name, case, audit)
            raw = HARNESS.raw_loop_report(binary, args.objdump)
            if raw["instruction_bytes_total"] != audit["loop_bytes"]:
                raise RuntimeError(f"{name}: independent byte parsers disagree")
            raw_case = compiled["cases"][name]
            if raw_case["binary_sha256"] != audit["binary_sha256"]:
                raise RuntimeError(f"{name}: container/host binary hashes differ")
            loop_hash = audit["normalized_loop_sha256"]
            stream_members.setdefault(loop_hash, []).append(name)
            representatives.setdefault(loop_hash, name)
            case_results[name] = {
                "description": case["description"],
                "source": source_reports[name],
                "build": {
                    "status": "PASS",
                    "binary_sha256": raw_case["binary_sha256"],
                    "supplied_default": "PASS",
                    "exact_gcc13": "PASS",
                    "effective_cflags": raw_case["effective_cflags"],
                },
                "loop": HARNESS.compact_audit(audit),
                "encoding": {
                    "instruction_bytes_total": raw[
                        "instruction_bytes_total"
                    ],
                    "by_mnemonic_and_bytes": raw[
                        "by_mnemonic_and_bytes"
                    ],
                },
                "official_vectors": simplified_execution(
                    raw_case["official_vectors"]
                ),
                "supplied_default_official_vectors": simplified_execution(
                    raw_case["supplied_default_official"]
                ),
                "random_differential": {
                    "status": "PASS",
                    "cases": 100_000,
                    "seed": "0x243f6a8885a308d3",
                    "random_state_and_constants": True,
                    "round_counts": [1, 20],
                    "stdout": raw_case["verification"]["stdout"],
                },
            }

        baseline = case_results["baseline"]["loop"]
        if (
            baseline["normalized_sha256"] != BASELINE_LOOP_SHA256
            or baseline["bytes"] != BASELINE_BYTES
            or baseline["instructions"] != BASELINE_INSTRUCTIONS
            or baseline["hot_memory_operands_excluding_lea"] != 0
        ):
            raise RuntimeError(f"baseline drifted: {baseline}")

        streams: dict[str, Any] = {}
        for index, (loop_hash, members) in enumerate(
            sorted(stream_members.items())
        ):
            representative = representatives[loop_hash]
            loop_path = temporary / f"stream-{index:02d}.s"
            HARNESS.extract_loop(
                binaries / representative, loop_path, args.objdump
            )
            streams[loop_hash] = {
                "representative": representative,
                "members": sorted(members),
                "loop_artifact_sha256": sha256(loop_path),
                "llvm_mca_16": HARNESS.analyse_loop(
                    args.llvm_mca, loop_path
                ),
                "llvm_mca_19": analyse_loop_llvm19(
                    args.llvm19_mca, args.llvm19_lib_dir, loop_path
                ),
            }
        for name, report in case_results.items():
            stream = streams[
                report["loop"]["normalized_sha256"]
            ]
            report["llvm_mca_16"] = stream["llvm_mca_16"]
            report["llvm_mca_19"] = stream["llvm_mca_19"]

        baseline_mca_16 = case_results["baseline"]["llvm_mca_16"]
        baseline_mca_19 = case_results["baseline"]["llvm_mca_19"]
        llvm19_equivalence = model_equivalence_groups(
            {
                loop_hash: stream["llvm_mca_19"]
                for loop_hash, stream in streams.items()
            }
        )
        static_table = {
            name: {
                "bytes": report["loop"]["bytes"],
                "instructions": report["loop"]["instructions"],
                "hot_memory_operands_excluding_lea": report["loop"][
                    "hot_memory_operands_excluding_lea"
                ],
                "llvm_mca_16": report["llvm_mca_16"],
                "llvm_mca_19": report["llvm_mca_19"],
            }
            for name, report in case_results.items()
        }
        candidate_names = [name for name in cases if name != "baseline"]
        strictly_static_better = [
            name
            for name in candidate_names
            if (
                case_results[name]["loop"]["bytes"] < baseline["bytes"]
                or case_results[name]["loop"]["instructions"]
                < baseline["instructions"]
            )
        ]
        if strictly_static_better:
            raise RuntimeError(
                f"unexpected static candidate win: {strictly_static_better}"
            )

        return {
            "schema_version": 1,
            "experiment": "challenge_eleventh_bounded_isa_synthesis",
            "scope": {
                "new_axes": [
                    "three-instruction BSWAP64-plus-non-byte-rotate synthesis",
                    "split-shuffle branch dataflows",
                    "cross-round shuffle cancellation through ADD",
                ],
                "intentionally_not_repeated": [
                    "register allocation and VEX operand-position screens",
                    "loop alignment and block-size frontends",
                    "scalar ROL/RORX/SHLD code generation",
                    "host timing",
                ],
            },
            "inputs": inputs,
            "compiler": {
                "reported": compiled["compiler"],
                "binutils_reported": compiled["binutils"],
                "common_flags": HARNESS.COMMON_FLAGS,
                "supplied_default_flags": HARNESS.SUPPLIED_DEFAULT_FLAGS,
                "verifier_flags": HARNESS.VERIFIER_FLAGS,
            },
            "vectors": vectors,
            "verification_protocol": {
                "official_vectors_every_case": True,
                "supplied_default_official_vectors_every_case": True,
                "random_differential_every_case": True,
                "random_cases_per_case": 100_000,
                "random_state_and_constants": True,
                "round_counts": [1, 20],
                "candidate_dataflow_round_counts": [1, 20],
                "one_round_candidate_hook_every_case": True,
                "one_round_hook_uses_same_inline_assembly_macro_as_20_rounds": (
                    True
                ),
                "complete_clock_delimited_loop_audit_every_case": True,
                "expected_calls_push_pop_hot_memory": [0, 0, 0],
            },
            "formal_and_exhaustive_checks": {
                "three_instruction_linear_network": synthesis,
                "identity_and_pair_boundary_checks": identities,
            },
            "cases": case_results,
            "streams": streams,
            "summary": {
                "all_builds_official_random_audits": "PASS",
                "three_instruction_scoped_search": synthesis["status"],
                "case_count": len(cases),
                "distinct_normalized_streams": len(streams),
                "loop_bytes_distribution": {
                    str(size): count
                    for size, count in sorted(
                        Counter(
                            report["loop"]["bytes"]
                            for report in case_results.values()
                        ).items()
                    )
                },
                "static_table": static_table,
                "baseline_llvm_mca_16": baseline_mca_16,
                "baseline_llvm_mca_19": baseline_mca_19,
                "llvm19_model_metric_equivalence": llvm19_equivalence,
                "strict_static_wins": strictly_static_better,
            },
            "conclusion": {
                "candidate_found": False,
                "result": (
                    "No three-instruction BSWAP64-plus-rotate network exists "
                    "in the scoped AVX2 shift/shuffle/bitwise grammar. The "
                    "three constructive split-shuffle controls are exact but "
                    "add one VPSHUFB per round, increasing the measured loop "
                    "from 122 to 142 instructions."
                ),
                "cross_round_result": (
                    "Byte shuffle commutes with XOR after transforming the "
                    "constant, but not with the intervening modular ADD; two "
                    "round-boundary shuffles cannot be cancelled."
                ),
                "promotion": "none",
                "incumbent": "retained six-instruction AVX2 transform",
                "qualification": (
                    "The UNSAT result is grammar-scoped, and LLVM-MCA is only "
                    "a scheduling proxy rather than a Core Ultra 7 255H "
                    "measurement."
                ),
            },
            "model_limits": {
                "synthesis": synthesis["scope_limit"],
                "llvm_mca": (
                    "LLVM-MCA 16 Alder/Meteor/Zen 2 and LLVM-MCA 19 "
                    "Arrow Lake/Arrow Lake-S/Lunar Lake/Sierra Forest models "
                    "are public scheduling proxies. None is asserted to be "
                    "an exact Core Ultra 7 255H P/E/LP-E model, and none "
                    "models frequency effects."
                ),
                "target_timing": (
                    "No host result can promote a candidate; exact 255H "
                    "confirmation remains a separate hardware task."
                ),
            },
            "primary_documentation": [
                {
                    "title": (
                        "Intel 64 and IA-32 Architectures Software "
                        "Developer's Manual"
                    ),
                    "url": (
                        "https://www.intel.com/content/www/us/en/developer/"
                        "articles/technical/intel-sdm.html"
                    ),
                    "used_for": (
                        "VPSLLVQ, VPSRLVQ, VPSHUFB, VPXOR, VPOR, and "
                        "VPADDQ semantics"
                    ),
                },
                {
                    "title": "Intel Core Ultra 7 processor 255H specifications",
                    "url": (
                        "https://www.intel.com/content/www/us/en/products/sku/"
                        "241751/intel-core-ultra-7-processor-255h-24m-cache-up-"
                        "to-5-10-ghz/specifications.html"
                    ),
                    "used_for": "AVX2 target scope and AVX-512 exclusion",
                },
                {
                    "title": "LLVM llvm-mca command guide",
                    "url": "https://llvm.org/docs/CommandGuide/llvm-mca.html",
                    "used_for": "static scheduling proxies and their limits",
                },
                {
                    "title": "LLVM 19.1.7 X86 processor-model definitions",
                    "url": LLVM19_X86_TD_URL,
                    "used_for": (
                        "confirming that the exposed arrowlake name still "
                        "selects AlderlakePModel in this LLVM release"
                    ),
                },
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce challenge 2's eleventh ISA-synthesis screen"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE / "eleventh_isa_synthesis_results.json",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--runtime", default="docker")
    parser.add_argument(
        "--objdump", type=Path, default=HARNESS.DEFAULT_OBJDUMP
    )
    parser.add_argument(
        "--size-tool", type=Path, default=HARNESS.DEFAULT_SIZE
    )
    parser.add_argument(
        "--llvm-mca", type=Path, default=HARNESS.DEFAULT_LLVM_MCA
    )
    parser.add_argument("--llvm19-mca", type=Path, default=LLVM19_MCA)
    parser.add_argument(
        "--llvm19-lib-dir", type=Path, default=LLVM19_LIB_DIR
    )
    args = parser.parse_args()

    result = build_result(args)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file():
            raise SystemExit(f"missing result for --check: {args.output}")
        if args.output.read_text() != rendered:
            raise SystemExit(
                f"result drift: regenerate {args.output} without --check"
            )
        print(f"PASS: {args.output} is reproducible")
        return
    args.output.write_text(rendered)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
