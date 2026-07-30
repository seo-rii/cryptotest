#!/usr/bin/env python3
"""Bounded tenth-pass code-generation screen for challenge 2.

This experiment starts from the retained 549-byte AVX2 inline-assembly loop
and deliberately avoids repeating the earlier 11-case allocation and 34-case
flag/layout screens.  It checks three narrower questions:

* Can a high changing-state register retain four-byte VPOR/VPXOR/VPADDQ
  encodings when their low scratch/constants, rather than the state, occupy
  ModRM r/m?
* Do exact rotate/XOR reassociations or swapping XOR with the byte shuffle
  improve the dependency/scheduling proxy without changing semantics?
* What exact fetch-line geometry results from source-controlled byte placement
  around 16/32/64-byte boundaries when compiler loop alignment is disabled?

Every generated source is built in the digest-pinned GCC 13.3 container, run
on the official vectors, checked on 100,000 random states and constants for
1/20 rounds, and audited over the complete clock-delimited timing loop.
LLVM-MCA is run once per distinct normalized instruction stream.  It is a
static scheduling proxy and intentionally is not used to rank the controlled
address placements because it does not model their linked fetch addresses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent))

from loop_audit import audit_main_timing_loop  # noqa: E402


SOURCE_RELATIVE = "submissions/02/src/optimization/contest_simd_avx2_inline_asm.c"
SOURCE = HERE / SOURCE_RELATIVE.rsplit("/", 1)[-1]
VERIFIER_RELATIVE = "submissions/02/src/optimization/verify_contest_candidate.c"
VERIFIER = HERE / VERIFIER_RELATIVE.rsplit("/", 1)[-1]
AUDITOR_RELATIVE = "submissions/02/src/loop_audit.py"
ARCHIVE_RELATIVE = "submissions/02/src/2_암호구현.zip"
ARCHIVE = ROOT / ARCHIVE_RELATIVE

INPUT_HASHES = {
    SOURCE_RELATIVE: "c6f43f26dcf1bb0cd83d51dd52495e264c6b8303c0b06e89cb84b1cae62d45dc",
    VERIFIER_RELATIVE: "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35",
    AUDITOR_RELATIVE: "8b4e1e90af9d4224500ead177bc02ddc5912805757ce2137ab89a990af0128b1",
    ARCHIVE_RELATIVE: "d0c3158adda8ba258becfc0e347267c0f2f0112738ec732be6dcb5477342e88e",
}

VECTOR_MEMBERS = {
    "code/testvector.txt": {
        "sha256": "4852415779f00d2a9020bc13690ece3ec2febf42af4b29a9f03185c1f63d2801",
        "bytes": 153_893,
    },
    "code/testvector_20round.txt": {
        "sha256": "5625484c45ac7e2fb3ee865fb5078477522c2231f3abca0707133261916b4488",
        "bytes": 149,
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
    "meteorlake_proxy": "meteorlake",
    "znver2_cross_architecture_proxy": "znver2",
}
MCA_ITERATIONS = 100

BASELINE_LOOP_SHA256 = "0b4f2686a2a19ce4fe96d12b89d01e38092c088794252c8e1d8460c75bb8ae4b"
BASELINE_LOOP_BYTES = 549
BASELINE_LOOP_INSTRUCTIONS = 122

CURRENT_MACRO = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpor %[value], %[scratch], %[value]\n\t"                          \
    "vpxor %[value], %[" XOR_VALUE "], %[value]\n\t"                     \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                        \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"
'''

OTHER_MODRM_MACRO = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpor %[scratch], %[value], %[value]\n\t"                          \
    "vpxor %[" XOR_VALUE "], %[value], %[value]\n\t"                     \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                        \
    "vpaddq %[" ADD_VALUE "], %[value], %[value]\n\t"
'''

SHIFT_DEST_SWAPPED_MACRO = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsllvq %[" LEFT "], %[value], %[scratch]\n\t"                     \
    "vpsrlvq %[" RIGHT "], %[value], %[value]\n\t"                       \
    "vpor %[value], %[scratch], %[value]\n\t"                          \
    "vpxor %[value], %[" XOR_VALUE "], %[value]\n\t"                     \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                        \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"
'''

ROTATE_ADD_MACRO = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpaddq %[value], %[scratch], %[value]\n\t"                          \
    "vpxor %[value], %[" XOR_VALUE "], %[value]\n\t"                     \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                        \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"
'''

XOR_REASSOCIATED_MACRO = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpxor %[" XOR_VALUE "], %[scratch], %[scratch]\n\t"                 \
    "vpxor %[value], %[scratch], %[value]\n\t"                           \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                        \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"
'''

XOR_AFTER_SHUFFLE_MACRO = r'''#define INLINE_ASM_TRANSFORM(LEFT, RIGHT, XOR_VALUE, ADD_VALUE)              \
    "vpsrlvq %[" RIGHT "], %[value], %[scratch]\n\t"                     \
    "vpsllvq %[" LEFT "], %[value], %[value]\n\t"                       \
    "vpor %[value], %[scratch], %[value]\n\t"                          \
    "vpshufb %[byte_swap], %[value], %[value]\n\t"                        \
    "vpxor %[value], %[" XOR_VALUE "], %[value]\n\t"                     \
    "vpaddq %[value], %[" ADD_VALUE "], %[value]\n\t"
'''

PRE_SWAP_INSERTION_POINT = """    __asm__(
"""
PRE_SWAP_INSERTION = """    xor_forward = _mm256_shuffle_epi8(xor_forward, byte_swap);
    xor_reverse = _mm256_shuffle_epi8(xor_reverse, byte_swap);

    __asm__(
"""
PLACEMENT_INSERTION_POINT = """        clock_t start = clock();
        for (int i = 0; i < iterations; i++) {
"""

PRIMARY_DOCUMENTATION = [
    {
        "title": "Intel 64 and IA-32 Architectures Software Developer's Manual",
        "url": (
            "https://www.intel.com/content/www/us/en/developer/articles/"
            "technical/intel-sdm.html"
        ),
        "used_for": (
            "VEX2/VEX3 register-extension and opcode-map encoding constraints"
        ),
    },
    {
        "title": "GCC 13.3 x86 options",
        "url": "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/x86-Options.html",
        "used_for": "AVX2 target and tuning controls",
    },
    {
        "title": "GCC 13.3 optimization options",
        "url": (
            "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/"
            "Optimize-Options.html"
        ),
        "used_for": "loop, jump, and label alignment controls",
    },
    {
        "title": "LLVM llvm-mca command guide",
        "url": "https://llvm.org/docs/CommandGuide/llvm-mca.html",
        "used_for": "static scheduling proxies and their limitations",
    },
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one replacement site, got {count}")
    return text.replace(old, new)


def case_specs() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}

    def add(name: str, *, group: str, description: str, **kwargs: Any) -> None:
        if name in cases:
            raise RuntimeError(f"duplicate case: {name}")
        cases[name] = {
            "group": group,
            "description": description,
            "cflags": [],
            "pins": {},
            "macro": "current",
            "placement_fill": None,
            **kwargs,
        }

    add(
        "baseline",
        group="reference",
        description="retained low-state/ModRM 549-byte source",
    )
    for register in (1, 4, 6):
        add(
            f"low_state_ymm{register}",
            group="state_register_class",
            description=(
                f"move the changing state to unused low ymm{register}; "
                "keep state in ModRM r/m"
            ),
            pins={"value": register},
        )
    for register in (8, 12, 15):
        add(
            f"high_state_ymm{register}_low_scratch7",
            group="state_register_class",
            description=(
                f"put state in high ymm{register}, pin scratch to low ymm7, "
                "and put scratch/constants in ModRM r/m"
            ),
            pins={"value": register, "scratch": 7},
            macro="other_modrm",
        )
    add(
        "high_state_ymm15_allocator_scratch",
        group="operand_position_control",
        description=(
            "high state with low constants in ModRM but allocator-chosen scratch; "
            "isolates the VPOR scratch-register extension"
        ),
        pins={"value": 15},
        macro="other_modrm",
    )
    add(
        "high_state_ymm15_wrong_modrm",
        group="operand_position_control",
        description=(
            "negative control: high state remains in ModRM for all three "
            "commutative operations"
        ),
        pins={"value": 15},
    )
    add(
        "inverted_fixed_register_classes",
        group="register_class_layout",
        description=(
            "low state, low shift controls, high XOR/add constants and scratch; "
            "negative control for the inverse of the earlier fixed class layout"
        ),
        pins={
            "value": 0,
            "left_forward": 1,
            "right_forward": 2,
            "left_reverse": 3,
            "right_reverse": 4,
            "xor_forward": 8,
            "add_reverse": 9,
            "xor_reverse": 10,
            "add_forward": 11,
            "byte_swap": 12,
            "scratch": 13,
        },
        expected_instructions=124,
        expected_hot_memory=1,
        expected_mnemonics={"vmovdqa": 1, "vpermq": 1},
    )
    add(
        "high_shuffle_mask_ymm15",
        group="register_class_layout",
        description=(
            "pin the VPSHUFB mask high; its 0F38 map already requires VEX3"
        ),
        pins={"byte_swap": 15},
    )
    add(
        "shift_destinations_swapped",
        group="exact_reassociation",
        description=(
            "left shift writes scratch and right shift destructively writes state"
        ),
        macro="shift_dest_swapped",
    )
    add(
        "rotate_merge_add",
        group="exact_reassociation",
        description=(
            "replace rotate VPOR by VPADDQ; complementary shifted bit fields "
            "are disjoint"
        ),
        macro="rotate_add",
        expected_mnemonics={"vpor": 0, "vpaddq": 40, "vpxor": 20},
    )
    add(
        "xor_constant_on_right_branch",
        group="exact_reassociation",
        description=(
            "use rotate OR=XOR and apply the round XOR on the right-shift "
            "branch before merging"
        ),
        macro="xor_reassociated",
        expected_mnemonics={"vpor": 0, "vpaddq": 20, "vpxor": 40},
    )
    add(
        "xor_after_byte_shuffle",
        group="exact_reassociation",
        description=(
            "pre-byte-swap XOR constants outside the hot loop, then exchange "
            "the per-stage VPSHUFB and VPXOR"
        ),
        macro="xor_after_shuffle",
        pre_swap_xor_constants=True,
    )

    # With GCC loop/jump/label alignment disabled, the retained source begins
    # at mod-64 61.  These fills put starts immediately around 0/16/32/48 and
    # also preserve the unfilled anchor.  The exact expected offsets are
    # asserted after linking, so any backend drift fails closed.
    placements = {
        0: 61,
        1: 62,
        2: 63,
        3: 0,
        4: 1,
        18: 15,
        19: 16,
        20: 17,
        34: 31,
        35: 32,
        36: 33,
        50: 47,
        51: 48,
        52: 49,
    }
    placement_flags = [
        "-falign-loops=1",
        "-falign-jumps=1",
        "-falign-labels=1",
    ]
    for fill, expected_mod64 in placements.items():
        add(
            f"placement_fill_{fill:02d}",
            group="source_controlled_placement",
            description=(
                f"insert {fill} literal pre-loop NOP bytes with compiler loop/"
                f"jump/label alignment disabled; expect start mod 64 "
                f"{expected_mod64}"
            ),
            cflags=placement_flags,
            placement_fill=fill,
            expected_start_mod64=expected_mod64,
        )

    if len(cases) != 29:
        raise RuntimeError(f"expected 29 cases, got {len(cases)}")
    return cases


MACROS = {
    "current": CURRENT_MACRO,
    "other_modrm": OTHER_MODRM_MACRO,
    "shift_dest_swapped": SHIFT_DEST_SWAPPED_MACRO,
    "rotate_add": ROTATE_ADD_MACRO,
    "xor_reassociated": XOR_REASSOCIATED_MACRO,
    "xor_after_shuffle": XOR_AFTER_SHUFFLE_MACRO,
}


def pin_variable(text: str, name: str, register: int) -> str:
    if not 0 <= register <= 15:
        raise RuntimeError(f"invalid YMM register for {name}: {register}")
    if name == "value":
        old = 'register __m256i value __asm__("ymm0") ='
        new = f'register __m256i value __asm__("ymm{register}") ='
        return replace_exact(text, old, new, f"pin {name}")
    if name == "scratch":
        old = "    __m256i scratch;"
        new = (
            f'    register __m256i scratch __asm__("ymm{register}");'
        )
        return replace_exact(text, old, new, f"pin {name}")
    old = f"    __m256i {name} ="
    new = (
        f'    register __m256i {name} __asm__("ymm{register}") ='
    )
    return replace_exact(text, old, new, f"pin {name}")


def generate_sources(
    destination: Path, cases: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    base = SOURCE.read_text()
    if base.count(CURRENT_MACRO) != 1:
        raise RuntimeError("retained inline-assembly macro drifted")
    destination.mkdir()
    reports: dict[str, dict[str, Any]] = {}
    for name, spec in cases.items():
        text = base
        macro_name = spec["macro"]
        macro = MACROS[macro_name]
        if macro != CURRENT_MACRO:
            text = replace_exact(
                text, CURRENT_MACRO, macro, f"{name} macro {macro_name}"
            )
        for variable, register in spec["pins"].items():
            text = pin_variable(text, variable, int(register))
        if spec.get("pre_swap_xor_constants", False):
            text = replace_exact(
                text,
                PRE_SWAP_INSERTION_POINT,
                PRE_SWAP_INSERTION,
                f"{name} pre-swap insertion",
            )
        fill = spec.get("placement_fill")
        if fill is not None:
            placement = (
                "        clock_t start = clock();\n"
                f'        __asm__ volatile(".fill {fill},1,0x90");\n'
                "        for (int i = 0; i < iterations; i++) {\n"
            )
            text = replace_exact(
                text,
                PLACEMENT_INSERTION_POINT,
                placement,
                f"{name} placement insertion",
            )
        path = destination / f"{name}.c"
        path.write_text(text)
        reports[name] = {
            "generated_source_sha256": sha256_bytes(text.encode()),
            "temporary_path": f"<temporary>/variants/{name}.c",
            "recipe": {
                "macro": macro_name,
                "pins": spec["pins"],
                "pre_swap_xor_constants": spec.get(
                    "pre_swap_xor_constants", False
                ),
                "placement_fill": fill,
            },
        }
    return reports


def validate_inputs(args: argparse.Namespace) -> dict[str, Any]:
    actual_files = {relative: sha256(ROOT / relative) for relative in INPUT_HASHES}
    mismatches = {
        relative: {"expected": INPUT_HASHES[relative], "actual": actual}
        for relative, actual in actual_files.items()
        if actual != INPUT_HASHES[relative]
    }
    if mismatches:
        raise RuntimeError(f"input hash mismatch: {mismatches}")

    tools = {
        "objdump": args.objdump,
        "size": args.size_tool,
        "llvm_mca": args.llvm_mca,
    }
    tool_reports: dict[str, Any] = {}
    for name, path in tools.items():
        if not path.is_file():
            raise RuntimeError(f"missing host tool: {path}")
        actual = sha256(path)
        if actual != HOST_TOOL_HASHES[name]:
            raise RuntimeError(
                f"{name} hash mismatch: expected {HOST_TOOL_HASHES[name]}, got {actual}"
            )
        tool_reports[name] = {
            "path": str(path),
            "sha256": actual,
            "version": run([str(path), "--version"]).stdout.splitlines()[0],
        }

    if shutil.which(args.runtime) is None:
        raise RuntimeError(f"container runtime unavailable: {args.runtime}")
    image_id = run(
        [args.runtime, "image", "inspect", "--format", "{{.Id}}", IMAGE]
    ).stdout.strip()
    if image_id != f"sha256:{IMAGE_DIGEST}":
        raise RuntimeError(
            f"container image ID mismatch: expected sha256:{IMAGE_DIGEST}, got {image_id}"
        )

    return {
        "files": {
            relative: {
                "expected_sha256": INPUT_HASHES[relative],
                "actual_sha256": actual_files[relative],
            }
            for relative in INPUT_HASHES
        },
        "driver": {
            "path": str(Path(__file__).resolve().relative_to(ROOT)),
            "sha256": sha256(Path(__file__).resolve()),
        },
        "host_tools": tool_reports,
        "container": {
            "image": IMAGE,
            "manifest_digest_sha256": IMAGE_DIGEST,
            "local_image_id": image_id,
            "network": "none",
            "repository_mount": "read-only",
            "generated_sources_mount": "read-only",
        },
    }


def extract_vectors(destination: Path) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    with zipfile.ZipFile(ARCHIVE) as archive:
        names = archive.namelist()
        for member, expected in VECTOR_MEMBERS.items():
            if names.count(member) != 1:
                raise RuntimeError(
                    f"archive member {member!r} appears {names.count(member)} times"
                )
            data = archive.read(member)
            actual = {"sha256": sha256_bytes(data), "bytes": len(data)}
            if actual != expected:
                raise RuntimeError(
                    f"archive member mismatch for {member}: expected {expected}, got {actual}"
                )
            output = destination / Path(member).name
            output.write_bytes(data)
            reports[member] = {
                "archive_member": member,
                "extracted_name": output.name,
                **actual,
            }
    return reports


CONTAINER_DRIVER = r'''
import hashlib
import json
import subprocess
from pathlib import Path

manifest = json.loads(Path("/config/manifest.json").read_text())
output = Path("/output")

def invoke(command, cwd=None):
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }

def official(executable):
    report = invoke([str(executable)], cwd="/vectors")
    report["markers"] = {
        marker: marker in report["stdout"]
        for marker in manifest["official_markers"]
    }
    report["marker_lines"] = [
        marker for marker in manifest["official_markers"]
        if marker in report["stdout"]
    ]
    report.pop("stdout")
    return report

verifier_object = output / "verifier.o"
verifier_build = invoke([
    "gcc", *manifest["verifier_flags"], "-c",
    "/repository/" + manifest["verifier"], "-o", str(verifier_object),
])

reports = {}
for name, case in manifest["cases"].items():
    source = Path("/variants") / (name + ".c")
    binary = output / name
    default_binary = output / (name + ".default")
    candidate_object = output / (name + ".o")
    verifier_binary = output / (name + ".verify")
    effective_flags = [*manifest["common_flags"], *case["cflags"]]
    default_build = invoke([
        "gcc", *manifest["supplied_default_flags"], str(source),
        "-o", str(default_binary),
    ])
    full_build = invoke([
        "gcc", *effective_flags, str(source), "-o", str(binary),
    ])
    candidate_build = invoke([
        "gcc", *effective_flags, "-Dmain=contest_candidate_main", "-c",
        str(source), "-o", str(candidate_object),
    ])
    default_official = None
    link = None
    verification = None
    official_vectors = None
    if default_build["returncode"] == 0:
        default_official = official(default_binary)
    if (
        verifier_build["returncode"] == 0
        and full_build["returncode"] == 0
        and candidate_build["returncode"] == 0
    ):
        link = invoke([
            "gcc", str(candidate_object), str(verifier_object),
            "-o", str(verifier_binary),
        ])
        if link["returncode"] == 0:
            verification = invoke([str(verifier_binary), "100000"])
        official_vectors = official(binary)
    reports[name] = {
        "effective_cflags": effective_flags,
        "supplied_default_build": default_build,
        "supplied_default_official": default_official,
        "full_build": full_build,
        "candidate_object_build": candidate_build,
        "verifier_link": link,
        "verification": verification,
        "official_vectors": official_vectors,
        "binary_sha256": (
            hashlib.sha256(binary.read_bytes()).hexdigest()
            if binary.is_file() else None
        ),
    }

Path("/output/build-report.json").write_text(json.dumps({
    "compiler": subprocess.run(
        ["gcc", "--version"], text=True, stdout=subprocess.PIPE
    ).stdout.splitlines()[0],
    "binutils": subprocess.run(
        ["objdump", "--version"], text=True, stdout=subprocess.PIPE
    ).stdout.splitlines()[0],
    "verifier_build": verifier_build,
    "cases": reports,
}, indent=2, sort_keys=True) + "\n")
'''


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
    vector_reports = extract_vectors(vectors)
    manifest = {
        "verifier": VERIFIER_RELATIVE,
        "common_flags": COMMON_FLAGS,
        "supplied_default_flags": SUPPLIED_DEFAULT_FLAGS,
        "verifier_flags": VERIFIER_FLAGS,
        "official_markers": OFFICIAL_MARKERS,
        "cases": {
            name: {"cflags": spec["cflags"]} for name, spec in cases.items()
        },
    }
    (config / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
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
            f"{ROOT}:/repository:ro",
            "--volume",
            f"{variants}:/variants:ro",
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
    return (
        json.loads((output / "build-report.json").read_text()),
        output,
        vector_reports,
        source_reports,
    )


def fail_if_build_or_correctness_failed(
    report: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    if report["compiler"] != EXPECTED_COMPILER:
        raise RuntimeError(f"unexpected compiler: {report['compiler']}")
    verifier_build = report["verifier_build"]
    if verifier_build["returncode"] != 0 or verifier_build["stderr"]:
        raise RuntimeError(f"verifier build failed or warned: {verifier_build}")
    if set(report["cases"]) != set(cases):
        raise RuntimeError("container case set differs from manifest")
    for name, case_report in report["cases"].items():
        for label in (
            "supplied_default_build",
            "full_build",
            "candidate_object_build",
            "verifier_link",
        ):
            item = case_report[label]
            if item is None or item["returncode"] != 0 or item["stderr"]:
                raise RuntimeError(f"{name}: {label} failed or warned: {item}")
        for label in ("supplied_default_official", "official_vectors"):
            official = case_report[label]
            if (
                official is None
                or official["returncode"] != 0
                or official["stderr"]
                or not all(official["markers"].values())
            ):
                raise RuntimeError(f"{name}: {label} failed: {official}")
        verification = case_report["verification"]
        if (
            verification is None
            or verification["returncode"] != 0
            or verification["stderr"]
            or verification["stdout"] != EXPECTED_VERIFIER_STDOUT
        ):
            raise RuntimeError(f"{name}: random verification failed: {verification}")


def extract_number(output: str, label: str) -> float:
    match = re.search(
        rf"^{re.escape(label)}:\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"llvm-mca output omitted {label!r}")
    return float(match.group(1))


def parse_clock_loop(
    binary: Path, objdump: Path
) -> list[tuple[int, str, str, int]]:
    disassembly = run(
        [
            str(objdump),
            "-d",
            "--insn-width=15",
            "--disassemble=main",
            str(binary),
        ]
    ).stdout
    instructions: list[tuple[int, str, str, int]] = []
    pattern = re.compile(
        r"^\s*([0-9a-fA-F]+):\s+"
        r"((?:[0-9a-fA-F]{2}\s+)+)"
        r"([^\s]+)(?:\s+(.*?))?\s*$"
    )
    for line in disassembly.splitlines():
        match = pattern.match(line)
        if match:
            instructions.append(
                (
                    int(match.group(1), 16),
                    match.group(3),
                    (match.group(4) or "").strip(),
                    len(match.group(2).split()),
                )
            )
    clock_indices = [
        index
        for index, (_, opcode, operands, _) in enumerate(instructions)
        if opcode.startswith("call")
        and re.search(r"<clock(?:@[^>]*)?>", operands)
    ]
    if len(clock_indices) < 2:
        raise RuntimeError(f"{binary}: raw parser found fewer than two clocks")
    backedges: list[tuple[int, int]] = []
    for index in range(clock_indices[-2] + 1, clock_indices[-1]):
        address, opcode, operands, _ = instructions[index]
        target = re.match(r"(?:\*?0x)?([0-9a-fA-F]+)", operands)
        if (
            opcode.startswith("j")
            and opcode != "jmp"
            and target
            and int(target.group(1), 16) < address
        ):
            backedges.append((index, int(target.group(1), 16)))
    if not backedges:
        raise RuntimeError(f"{binary}: raw parser found no timed-loop backedge")
    end_index, start_address = backedges[-1]
    start_index = next(
        index
        for index, (address, _, _, _) in enumerate(instructions)
        if address == start_address
    )
    return instructions[start_index : end_index + 1]


def raw_loop_report(binary: Path, objdump: Path) -> dict[str, Any]:
    loop = parse_clock_loop(binary, objdump)
    by_mnemonic: dict[str, Counter[int]] = {}
    for _, mnemonic, _, length in loop:
        by_mnemonic.setdefault(mnemonic, Counter())[length] += 1
    start = loop[0][0]
    end = loop[-1][0] + loop[-1][3]
    boundaries: dict[str, Any] = {}
    for width in (16, 32, 64):
        crossing = [
            {
                "address": f"0x{address:x}",
                "mnemonic": mnemonic,
                "bytes": length,
            }
            for address, mnemonic, _, length in loop
            if address // width != (address + length - 1) // width
        ]
        boundaries[str(width)] = {
            "lines_touched": (end - 1) // width - start // width + 1,
            "instructions_crossing_boundary": len(crossing),
            "crossing_instructions": crossing,
        }
    branch_address, branch_mnemonic, branch_operands, branch_bytes = loop[-1]
    return {
        "instruction_bytes_total": sum(item[3] for item in loop),
        "by_mnemonic_and_bytes": {
            mnemonic: {str(length): count for length, count in sorted(counts.items())}
            for mnemonic, counts in sorted(by_mnemonic.items())
        },
        "geometry": {
            "start": f"0x{start:x}",
            "end_exclusive": f"0x{end:x}",
            "start_mod_64": start % 64,
            "end_mod_64": end % 64,
            "boundaries": boundaries,
            "backedge": {
                "address": f"0x{branch_address:x}",
                "mnemonic": branch_mnemonic,
                "operands": branch_operands,
                "bytes": branch_bytes,
            },
        },
    }


def extract_loop(binary: Path, destination: Path, objdump: Path) -> None:
    loop = parse_clock_loop(binary, objdump)
    lines = [".text", ".Ltimed_loop:"]
    for index, (_, opcode, operands, _) in enumerate(loop):
        operands = re.sub(r"\s+#.*$", "", operands).strip()
        if index == len(loop) - 1 and opcode.startswith("j"):
            operands = ".Ltimed_loop"
        lines.append(f"\t{opcode}\t{operands}".rstrip())
    destination.write_text("\n".join(lines) + "\n")


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
                extract_number(completed.stdout, "Total Cycles")
                / MCA_ITERATIONS
            ),
            "instructions_per_iteration": (
                extract_number(completed.stdout, "Instructions")
                / MCA_ITERATIONS
            ),
            "uops_per_iteration": (
                extract_number(completed.stdout, "Total uOps")
                / MCA_ITERATIONS
            ),
            "block_rthroughput": extract_number(
                completed.stdout, "Block RThroughput"
            ),
        }
    return reports


def compact_audit(audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "binary_sha256": audit["binary_sha256"],
        "text_bytes": audit["text_bytes"],
        "start": audit["loop_start"],
        "start_mod_16": audit["loop_start_mod_16"],
        "start_mod_32": audit["loop_start_mod_32"],
        "start_mod_64": audit["loop_start_mod_64"],
        "bytes": audit["loop_bytes"],
        "instructions": audit["loop_instructions"],
        "calls": audit["calls"],
        "push_pop": audit["push_pop"],
        "hot_memory_operands_excluding_lea": audit[
            "memory_operands_excluding_lea"
        ],
        "mnemonics": dict(sorted(audit["mnemonics"].items())),
        "normalized_sha256": audit["normalized_loop_sha256"],
        "legacy_addressed_sha256": audit["legacy_addressed_loop_sha256"],
        "normalization": audit["normalization"],
    }


def expected_mnemonics(spec: dict[str, Any]) -> dict[str, int]:
    expected = {
        "vpsllvq": 20,
        "vpsrlvq": 20,
        "vpor": 20,
        "vpxor": 20,
        "vpshufb": 20,
        "vpaddq": 20,
        "sub": 1,
        "jne": 1,
    }
    expected.update(spec.get("expected_mnemonics", {}))
    return expected


def verify_loop_shape(name: str, spec: dict[str, Any], audit: dict[str, Any]) -> None:
    expected_fields = {
        "calls": 0,
        "push_pop": 0,
        "memory_operands_excluding_lea": spec.get("expected_hot_memory", 0),
    }
    for field, wanted in expected_fields.items():
        if audit[field] != wanted:
            raise RuntimeError(
                f"{name}: expected {field}={wanted}, got {audit[field]}"
            )
    instruction_count = int(
        spec.get("expected_instructions", BASELINE_LOOP_INSTRUCTIONS)
    )
    if audit["loop_instructions"] != instruction_count:
        raise RuntimeError(
            f"{name}: expected {instruction_count} instructions, "
            f"got {audit['loop_instructions']}"
        )
    expected = expected_mnemonics(spec)
    relevant = set(expected) | {
        "vpsllvq",
        "vpsrlvq",
        "vpor",
        "vpxor",
        "vpshufb",
        "vpaddq",
        "sub",
        "dec",
        "jne",
    }
    for mnemonic in sorted(relevant):
        actual = audit["mnemonics"].get(mnemonic, 0)
        wanted = expected.get(mnemonic, 0)
        if actual != wanted:
            raise RuntimeError(
                f"{name}: expected {wanted} {mnemonic}, got {actual}"
            )
    expected_mod64 = spec.get("expected_start_mod64")
    if (
        expected_mod64 is not None
        and audit["loop_start_mod_64"] != expected_mod64
    ):
        raise RuntimeError(
            f"{name}: expected start mod 64 {expected_mod64}, "
            f"got {audit['loop_start_mod_64']}"
        )


def simplify_execution(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "returncode": report["returncode"],
        "markers": report.get("markers"),
        "marker_lines": report.get("marker_lines"),
    }


def mca_signature(report: dict[str, Any]) -> str:
    compact = {
        label: {
            key: value
            for key, value in model.items()
            if key not in ("model", "iterations")
        }
        for label, model in report.items()
    }
    return sha256_bytes(
        json.dumps(compact, sort_keys=True, separators=(",", ":")).encode()
    )


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    inputs = validate_inputs(args)
    cases = case_specs()
    with tempfile.TemporaryDirectory(
        prefix="challenge-tenth-codegen-"
    ) as raw_temporary:
        temporary = Path(raw_temporary).resolve()
        compiled, binaries, vectors, source_reports = compile_and_verify(
            args, temporary, cases
        )
        fail_if_build_or_correctness_failed(compiled, cases)

        case_results: dict[str, Any] = {}
        stream_members: dict[str, list[str]] = {}
        stream_representatives: dict[str, str] = {}

        for name, spec in cases.items():
            binary = binaries / name
            audit = audit_main_timing_loop(
                binary,
                objdump=str(args.objdump),
                size_tool=str(args.size_tool),
            )
            verify_loop_shape(name, spec, audit)
            raw = raw_loop_report(binary, args.objdump)
            if raw["instruction_bytes_total"] != audit["loop_bytes"]:
                raise RuntimeError(f"{name}: raw parser and loop audit disagree")
            raw_case = compiled["cases"][name]
            if raw_case["binary_sha256"] != audit["binary_sha256"]:
                raise RuntimeError(f"{name}: container and host hashes differ")
            loop_hash = audit["normalized_loop_sha256"]
            stream_members.setdefault(loop_hash, []).append(name)
            stream_representatives.setdefault(loop_hash, name)
            case_results[name] = {
                "group": spec["group"],
                "description": spec["description"],
                "cflags": spec["cflags"],
                "effective_cflags": raw_case["effective_cflags"],
                "source": source_reports[name],
                "build": {
                    "status": "PASS",
                    "binary_sha256": raw_case["binary_sha256"],
                    "supplied_default": "PASS",
                    "exact_gcc13": "PASS",
                },
                "loop": compact_audit(audit),
                "encoding": {
                    "instruction_bytes_total": raw[
                        "instruction_bytes_total"
                    ],
                    "by_mnemonic_and_bytes": raw[
                        "by_mnemonic_and_bytes"
                    ],
                },
                "geometry": raw["geometry"],
                "random_differential": {
                    "status": "PASS",
                    "cases": 100_000,
                    "seed": "0x243f6a8885a308d3",
                    "random_state_and_constants": True,
                    "round_counts": [1, 20],
                    "stdout": raw_case["verification"]["stdout"],
                },
                "official_vectors": simplify_execution(
                    raw_case["official_vectors"]
                ),
                "supplied_default_official_vectors": simplify_execution(
                    raw_case["supplied_default_official"]
                ),
            }

        baseline = case_results["baseline"]
        if (
            baseline["loop"]["normalized_sha256"] != BASELINE_LOOP_SHA256
            or baseline["loop"]["bytes"] != BASELINE_LOOP_BYTES
            or baseline["loop"]["instructions"] != BASELINE_LOOP_INSTRUCTIONS
            or baseline["loop"]["hot_memory_operands_excluding_lea"] != 0
        ):
            raise RuntimeError(f"baseline exact loop drifted: {baseline['loop']}")

        stream_reports: dict[str, Any] = {}
        for index, (loop_hash, members) in enumerate(sorted(stream_members.items())):
            representative = stream_representatives[loop_hash]
            loop_path = temporary / f"stream-{index:02d}.s"
            extract_loop(binaries / representative, loop_path, args.objdump)
            mca = analyse_loop(args.llvm_mca, loop_path)
            stream_reports[loop_hash] = {
                "representative": representative,
                "members": sorted(members),
                "loop_artifact_sha256": sha256(loop_path),
                "loop": case_results[representative]["loop"],
                "encoding": case_results[representative]["encoding"],
                "llvm_mca": mca,
                "llvm_mca_signature": mca_signature(mca),
            }

        baseline_mca = stream_reports[BASELINE_LOOP_SHA256]["llvm_mca"]
        baseline_mca_signature = mca_signature(baseline_mca)
        xor_branch_stream = stream_reports[
            case_results["xor_constant_on_right_branch"]["loop"][
                "normalized_sha256"
            ]
        ]
        xor_branch_mca = xor_branch_stream["llvm_mca"]
        for name, report in case_results.items():
            stream = stream_reports[report["loop"]["normalized_sha256"]]
            report["static_stream"] = {
                "llvm_mca_signature": stream["llvm_mca_signature"],
                "same_mca_signature_as_baseline": (
                    stream["llvm_mca_signature"] == baseline_mca_signature
                ),
            }

        placement_names = [
            name
            for name, spec in cases.items()
            if spec["group"] == "source_controlled_placement"
        ]
        placement_offsets = {
            case_results[name]["loop"]["start_mod_64"] for name in placement_names
        }
        expected_offsets = {
            int(cases[name]["expected_start_mod64"]) for name in placement_names
        }
        if placement_offsets != expected_offsets:
            raise RuntimeError(
                f"placement offset coverage drifted: {placement_offsets} "
                f"!= {expected_offsets}"
            )
        placement_hashes = {
            case_results[name]["loop"]["normalized_sha256"]
            for name in placement_names
        }
        if placement_hashes != {BASELINE_LOOP_SHA256}:
            raise RuntimeError(
                f"placement cases changed normalized stream: {placement_hashes}"
            )

        high_optimized = [
            f"high_state_ymm{register}_low_scratch7"
            for register in (8, 12, 15)
        ]
        for name in high_optimized:
            report = case_results[name]
            if (
                report["loop"]["bytes"] != 549
                or report["loop"]["instructions"] != 122
                or report["loop"]["hot_memory_operands_excluding_lea"] != 0
            ):
                raise RuntimeError(f"{name}: high-state dual drifted")

        codegen_names = [
            name
            for name, spec in cases.items()
            if spec["group"] != "source_controlled_placement"
        ]
        loop_bytes_distribution = Counter(
            case_results[name]["loop"]["bytes"] for name in codegen_names
        )
        mca_signature_members: dict[str, list[str]] = {}
        for loop_hash, stream in stream_reports.items():
            signature = stream["llvm_mca_signature"]
            mca_signature_members.setdefault(signature, []).extend(
                stream["members"]
            )

        return {
            "schema_version": 1,
            "experiment": "challenge_tenth_codegen_and_boundary_screen",
            "scope": {
                "case_count": len(cases),
                "codegen_case_count": len(codegen_names),
                "source_controlled_placement_case_count": len(placement_names),
                "not_repeated": [
                    "the prior 11-case allocation family",
                    "the prior 34 flag/link layout cases",
                    "host timing",
                ],
            },
            "inputs": inputs,
            "compiler": {
                "reported": compiled["compiler"],
                "binutils_reported": compiled["binutils"],
                "common_flags": COMMON_FLAGS,
                "supplied_default_flags": SUPPLIED_DEFAULT_FLAGS,
                "verifier_flags": VERIFIER_FLAGS,
            },
            "vectors": vectors,
            "verification_protocol": {
                "official_vectors_every_case": True,
                "supplied_default_official_vectors_every_case": True,
                "random_differential_every_case": True,
                "random_cases_per_case": 100_000,
                "random_state_and_constants": True,
                "round_counts": [1, 20],
                "complete_clock_delimited_loop_audit_every_case": True,
                "eligible_case_expected_calls_push_pop_hot_memory": [0, 0, 0],
                "negative_control_overrides": {
                    "inverted_fixed_register_classes": {
                        "expected_instructions": 124,
                        "expected_hot_memory_operands": 1,
                        "purpose": (
                            "preserve the reload/permute failure caused by "
                            "over-constraining the inverted fixed map"
                        ),
                    }
                },
            },
            "cases": case_results,
            "streams": stream_reports,
            "summary": {
                "all_builds_official_random_audits": "PASS",
                "loop_bytes_distribution_for_codegen_cases": {
                    str(size): count
                    for size, count in sorted(loop_bytes_distribution.items())
                },
                "distinct_normalized_streams": len(stream_reports),
                "distinct_llvm_mca_signatures": len(mca_signature_members),
                "llvm_mca_signature_members": {
                    signature: sorted(names)
                    for signature, names in sorted(mca_signature_members.items())
                },
                "controlled_start_mod64_offsets": sorted(placement_offsets),
                "placement_stream_sha256": BASELINE_LOOP_SHA256,
                "baseline": {
                    "bytes": baseline["loop"]["bytes"],
                    "instructions": baseline["loop"]["instructions"],
                    "hot_memory_operands_excluding_lea": baseline["loop"][
                        "hot_memory_operands_excluding_lea"
                    ],
                    "normalized_sha256": baseline["loop"][
                        "normalized_sha256"
                    ],
                    "llvm_mca": baseline_mca,
                },
            },
            "conclusions": {
                "high_state_encoding_dual": {
                    "status": "exact-code-shape-tie",
                    "cases": high_optimized,
                    "result": (
                        "All three high-state cases are 549 bytes, 122 "
                        "instructions, and zero hot memory. VEX2 carries the "
                        "high state in vvvv/destination while low scratch and "
                        "XOR/add constants occupy ModRM r/m."
                    ),
                    "promotion": (
                        "No strict static win over the retained low-state "
                        "stream; keep as a target-timing/register-allocation "
                        "alternative rather than replacing the source."
                    ),
                },
                "operand_position_controls": {
                    "allocator_scratch_case": {
                        "case": "high_state_ymm15_allocator_scratch",
                        "bytes": case_results[
                            "high_state_ymm15_allocator_scratch"
                        ]["loop"]["bytes"],
                        "reason": (
                            "allocator places scratch high, lengthening only "
                            "the 20 VPOR encodings"
                        ),
                    },
                    "wrong_modrm_case": {
                        "case": "high_state_ymm15_wrong_modrm",
                        "bytes": case_results[
                            "high_state_ymm15_wrong_modrm"
                        ]["loop"]["bytes"],
                        "reason": (
                            "putting high state in ModRM lengthens VPOR, "
                            "VPXOR, and VPADDQ in every transform"
                        ),
                    },
                },
                "exact_reassociations": {
                    "encoding_and_instruction_ties": [
                        "shift_destinations_swapped",
                        "rotate_merge_add",
                        "xor_constant_on_right_branch",
                        "xor_after_byte_shuffle",
                    ],
                    "neutral_cases": [
                        "shift_destinations_swapped",
                        "rotate_merge_add",
                        "xor_after_byte_shuffle",
                    ],
                    "right_branch_xor": {
                        "case": "xor_constant_on_right_branch",
                        "baseline_llvm_mca": baseline_mca,
                        "candidate_llvm_mca": xor_branch_mca,
                        "result": (
                            "Moving the constant XOR onto the right-shift "
                            "branch keeps Alder Lake and Meteor Lake at "
                            f"{xor_branch_mca['alderlake_p_core_proxy']['cycles_per_iteration']:.2f} "
                            "cycles, but reduces the Zen 2 cross-architecture "
                            "proxy from "
                            f"{baseline_mca['znver2_cross_architecture_proxy']['cycles_per_iteration']:.2f} "
                            "to "
                            f"{xor_branch_mca['znver2_cross_architecture_proxy']['cycles_per_iteration']:.2f}."
                        ),
                    },
                    "result": (
                        "All four preserve 122 instructions, zero hot memory, "
                        "and the 549-byte floor. Only right-branch XOR changes "
                        "proxy scheduling, and its gain is absent from both "
                        "Intel target proxies."
                    ),
                    "promotion": (
                        "retain right-branch XOR as a cross-architecture/"
                        "target-timing diagnostic; do not replace the Intel "
                        "target candidate from static evidence"
                    ),
                },
                "overconstrained_fixed_map": {
                    "case": "inverted_fixed_register_classes",
                    "bytes": case_results[
                        "inverted_fixed_register_classes"
                    ]["loop"]["bytes"],
                    "instructions": case_results[
                        "inverted_fixed_register_classes"
                    ]["loop"]["instructions"],
                    "hot_memory_operands": case_results[
                        "inverted_fixed_register_classes"
                    ]["loop"]["hot_memory_operands_excluding_lea"],
                    "result": (
                        "Pinning every inverted register class forces one "
                        "constant reload and one reverse permute into the hot "
                        "loop; relaxed high-state/low-scratch pinning avoids it."
                    ),
                    "promotion": "rejected",
                },
                "source_controlled_placement": {
                    "status": "code-shape-only",
                    "start_mod64_offsets": sorted(placement_offsets),
                    "normalized_streams": len(placement_hashes),
                    "result": (
                        "All linked placements retain the exact 549-byte "
                        "normalized stream. Their recorded 16/32/64-byte "
                        "crossing geometry is real, but llvm-mca strips linked "
                        "addresses and cannot rank front-end boundary effects."
                    ),
                    "promotion": (
                        "Requires repeated target-core timing; no placement "
                        "is promoted from static evidence."
                    ),
                },
                "lower_bound": {
                    "status": "unchanged-for-this-dataflow",
                    "bytes": 549,
                    "derivation": "20*(5+5+4+4+5+4)+3+6",
                    "qualification": (
                        "This is an encoding floor for the current six-"
                        "instruction transform and SUB/JNE outer loop, not an "
                        "algorithmic lower bound."
                    ),
                },
            },
            "model_limits": {
                "llvm_mca": (
                    "LLVM-MCA 16 Alder Lake and Zen 2 are scheduling proxies. "
                    "They do not model Core Ultra 7 255H P/E/LP-E cores or "
                    "linked fetch/decode boundary placement."
                ),
                "host_timing": (
                    "No host timing is collected; exact 255H core-type timing "
                    "is required for any promotion."
                ),
            },
            "primary_documentation": PRIMARY_DOCUMENTATION,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce challenge 2's tenth code-generation screen"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE / "tenth_codegen_results.json",
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--objdump", type=Path, default=DEFAULT_OBJDUMP)
    parser.add_argument("--size-tool", type=Path, default=DEFAULT_SIZE)
    parser.add_argument("--llvm-mca", type=Path, default=DEFAULT_LLVM_MCA)
    args = parser.parse_args()

    result = build_result(args)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file():
            raise SystemExit(f"missing result for --check: {args.output}")
        existing = args.output.read_text()
        if existing != rendered:
            raise SystemExit(
                f"result drift: regenerate {args.output} without --check"
            )
        print(f"PASS: {args.output} is reproducible")
        return
    args.output.write_text(rendered)
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
