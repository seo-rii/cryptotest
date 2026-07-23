#!/usr/bin/env python3
"""Exact GCC 13 screen for same-register scalar rotates in challenge 2.

The established scalar loop uses 80 non-destructive BMI2 RORX instructions.
An older portable control lets GCC choose destructive ROL/ROR instructions,
but its exact loop contains one extra MOV.  This bounded experiment forces the
four immediate rotates with read/write inline-assembly operands, checking
whether a genuinely same-register 80-ROL stream removes that move.

The full candidates are compiled in the digest-pinned GCC 13.3 image, audited
over the clock-delimited loop, checked on the official vectors and 100,000
random states/constants, and passed through static scheduling proxies.  Tiny
RORX/ROL/SHLD probes separately preserve exact encodings and dependency-chain
latency evidence; the latency-three same-register SHLD form is not expanded
into a full candidate.
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
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "solutions"))

from challenge02_loop_audit import audit_main_timing_loop  # noqa: E402


BASE_SOURCE_RELATIVE = "solutions/02_optimization/contest_source_order_2103.c"
BASE_SOURCE = ROOT / BASE_SOURCE_RELATIVE
PORTABLE_SOURCE_RELATIVE = (
    "solutions/02_optimization/contest_inline_unrolled.c"
)
PORTABLE_SOURCE = ROOT / PORTABLE_SOURCE_RELATIVE
VERIFIER_RELATIVE = "solutions/02_optimization/verify_contest_candidate_02.c"
AUDITOR_RELATIVE = "solutions/challenge02_loop_audit.py"
ARCHIVE_RELATIVE = "problems/2_암호구현.zip"
ARCHIVE = ROOT / ARCHIVE_RELATIVE

INPUT_HASHES = {
    BASE_SOURCE_RELATIVE: "87099c89743d374bc717e95fe593bac7d7b850426950a256f751a5347d90d392",
    PORTABLE_SOURCE_RELATIVE: (
        "ff1e080f2cdee30e87b9cd8d8c3f97df8088095babf127cc8d6d48145c995f21"
    ),
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

COMMON_FLAGS = ["-O3", "-Wall", "-Wextra", "-Werror"]
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

OLD_ATTRIBUTE = """#if defined(__GNUC__) && !defined(__clang__) && defined(__BMI2__)
#define PERMUTE20_ATTRIBUTE                                                   \\
    __attribute__((always_inline, optimize("no-tree-vectorize"))) inline
#elif defined(__GNUC__) && !defined(__clang__)
#define PERMUTE20_ATTRIBUTE                                                   \\
    __attribute__((noinline, noclone, target("bmi2"),                       \\
                   optimize("no-tree-vectorize"), aligned(64)))
#elif defined(__clang__) && defined(__BMI2__)
#define PERMUTE20_ATTRIBUTE __attribute__((always_inline)) inline
#elif defined(__clang__)
#define PERMUTE20_ATTRIBUTE __attribute__((noinline, target("bmi2"), aligned(64)))
#else
#define PERMUTE20_ATTRIBUTE
#endif
"""

PORTABLE_INLINE_ATTRIBUTE = """#if defined(__GNUC__) && !defined(__clang__)
#define PERMUTE20_ATTRIBUTE                                                   \\
    __attribute__((always_inline, optimize("no-tree-vectorize"))) inline
#elif defined(__GNUC__) || defined(__clang__)
#define PERMUTE20_ATTRIBUTE __attribute__((always_inline)) inline
#else
#define PERMUTE20_ATTRIBUTE
#endif
"""

OLD_TRANSFORM = """static inline uint64_t transform_word(uint64_t value,
                                      unsigned int rotation,
                                      uint64_t xor_constant,
                                      uint64_t add_constant) {
    return bswap64_portable(rotl64(value, rotation) ^ xor_constant) + add_constant;
}
"""

FORCED_TRANSFORMS = r'''#define DEFINE_FORCED_ROL_TRANSFORM(NAME, AMOUNT)                             \
    static inline __attribute__((always_inline)) uint64_t                     \
    transform_word_##NAME(uint64_t value, uint64_t xor_constant,             \
                          uint64_t add_constant) {                             \
        __asm__("rolq $" #AMOUNT ", %0" : "+r"(value) : : "cc");             \
        return bswap64_portable(value ^ xor_constant) + add_constant;         \
    }

DEFINE_FORCED_ROL_TRANSFORM(r43, 43)
DEFINE_FORCED_ROL_TRANSFORM(r7, 7)
DEFINE_FORCED_ROL_TRANSFORM(r29, 29)
DEFINE_FORCED_ROL_TRANSFORM(r14, 14)

#undef DEFINE_FORCED_ROL_TRANSFORM
'''

OLD_APPLY = """#define APPLY_TWO_ROUNDS()                                                    \\
    do {                                                                      \\
        x2 = transform_word(transform_word(x2, 29U, k2, a1), 7U, k1, a2);    \\
        x1 = transform_word(transform_word(x1, 7U, k1, a2), 29U, k2, a1);    \\
        x0 = transform_word(transform_word(x0, 43U, k0, a3), 14U, k3, a0);   \\
        x3 = transform_word(transform_word(x3, 14U, k3, a0), 43U, k0, a3);   \\
    } while (0)
"""

FORCED_APPLY = """#define APPLY_TWO_ROUNDS()                                                    \\
    do {                                                                      \\
        x2 = transform_word_r7(transform_word_r29(x2, k2, a1), k1, a2);      \\
        x1 = transform_word_r29(transform_word_r7(x1, k1, a2), k2, a1);      \\
        x0 = transform_word_r14(transform_word_r43(x0, k0, a3), k3, a0);     \\
        x3 = transform_word_r43(transform_word_r14(x3, k3, a0), k0, a3);     \\
    } while (0)
"""

MICROPROBES = {
    "rorx_same_register": {
        "instruction": "rorx $21, %rax, %rax",
        "requires": "BMI2",
        "semantic": "rotate left by 43 via rotate right by 21",
    },
    "rol_same_register": {
        "instruction": "rolq $43, %rax",
        "requires": "base x86-64",
        "semantic": "rotate left by 43 destructively",
    },
    "shld_same_register": {
        "instruction": "shldq $43, %rax, %rax",
        "requires": "base x86-64",
        "semantic": "same-source/destination SHLD equals rotate left by 43",
    },
}

PRIMARY_DOCUMENTATION = [
    {
        "title": "Intel 64 and IA-32 Architectures Software Developer's Manual",
        "url": (
            "https://www.intel.com/content/www/us/en/developer/articles/"
            "technical/intel-sdm.html"
        ),
        "used_for": "RORX, ROL, and SHLD semantics and encodings",
    },
    {
        "title": "LLVM llvm-mca command guide",
        "url": "https://llvm.org/docs/CommandGuide/llvm-mca.html",
        "used_for": "static latency/uop/throughput proxies and limitations",
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
        raise RuntimeError(f"{label}: expected one site, got {count}")
    return text.replace(old, new)


def case_specs() -> dict[str, dict[str, Any]]:
    return {
        "bmi2_rorx": {
            "group": "incumbent",
            "description": "source-order scalar incumbent with 80 RORX",
            "source_kind": "base",
            "cflags": ["-mbmi2", "-finline-limit=2000"],
            "expected": {
                "instructions": 322,
                "rorx": 80,
                "rol": 0,
                "ror": 0,
                "mov": 0,
            },
        },
        "portable_compiler_rol": {
            "group": "historical_control",
            "description": (
                "GCC-selected destructive ROL/ROR control with its known move"
            ),
            "source_kind": "portable",
            "cflags": ["-finline-limit=2000"],
            "expected": {
                "instructions": 323,
                "rorx": 0,
                "rol": 60,
                "ror": 20,
                "mov": 1,
            },
        },
        "source_order_compiler_rol": {
            "group": "matched_control",
            "description": (
                "compiler-selected ROL/ROR using the incumbent source order "
                "and portable forced-inline attribute"
            ),
            "source_kind": "base_portable_inline",
            "cflags": ["-finline-limit=2000"],
            "expected": {
                "instructions": 323,
                "rorx": 0,
                "rol": 60,
                "ror": 20,
                "mov": 1,
            },
        },
        "forced_same_register_rol": {
            "group": "new_candidate",
            "description": (
                "four immediate ROL helpers with read/write operands, preserving "
                "the incumbent source order"
            ),
            "source_kind": "forced_rol_portable_inline",
            "cflags": ["-finline-limit=2000"],
            "expected": {
                "instructions": 322,
                "rorx": 0,
                "rol": 80,
                "ror": 0,
                "mov": 0,
            },
        },
    }


def generated_sources(
    destination: Path, cases: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    destination.mkdir()
    base = BASE_SOURCE.read_text()
    portable = PORTABLE_SOURCE.read_text()
    base_portable_inline = replace_exact(
        base, OLD_ATTRIBUTE, PORTABLE_INLINE_ATTRIBUTE, "portable attribute"
    )
    forced = replace_exact(
        base, OLD_TRANSFORM, FORCED_TRANSFORMS, "forced transforms"
    )
    forced = replace_exact(
        forced, OLD_APPLY, FORCED_APPLY, "forced APPLY_TWO_ROUNDS"
    )
    forced = replace_exact(
        forced,
        OLD_ATTRIBUTE,
        PORTABLE_INLINE_ATTRIBUTE,
        "forced portable attribute",
    )
    texts = {
        "base": base,
        "portable": portable,
        "base_portable_inline": base_portable_inline,
        "forced_rol_portable_inline": forced,
    }
    reports: dict[str, dict[str, Any]] = {}
    for name, spec in cases.items():
        text = texts[spec["source_kind"]]
        path = destination / f"{name}.c"
        path.write_text(text)
        reports[name] = {
            "generated_source_sha256": sha256_bytes(text.encode()),
            "temporary_path": f"<temporary>/variants/{name}.c",
            "source_kind": spec["source_kind"],
            "base_path": (
                PORTABLE_SOURCE_RELATIVE
                if spec["source_kind"] == "portable"
                else BASE_SOURCE_RELATIVE
            ),
            "recipe": (
                "replace transform_word/APPLY_TWO_ROUNDS with four forced "
                "same-register immediate ROL helpers and force portable inline"
                if spec["source_kind"] == "forced_rol_portable_inline"
                else (
                    "force portable inline while retaining C rotate"
                    if spec["source_kind"] == "base_portable_inline"
                    else "unchanged control source"
                )
            ),
        }
    return reports


def generated_microprobes(destination: Path) -> dict[str, dict[str, Any]]:
    destination.mkdir()
    reports: dict[str, dict[str, Any]] = {}
    for name, spec in MICROPROBES.items():
        object_source = (
            ".text\n"
            f".globl {name}\n"
            f".type {name}, @function\n"
            f"{name}:\n"
            f"\t{spec['instruction']}\n"
            "\tret\n"
        )
        mca_source = ".text\n" f"\t{spec['instruction']}\n"
        (destination / f"{name}.s").write_text(object_source)
        (destination / f"{name}.mca.s").write_text(mca_source)
        reports[name] = {
            **spec,
            "object_source_sha256": sha256_bytes(object_source.encode()),
            "mca_source_sha256": sha256_bytes(mca_source.encode()),
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
            raise RuntimeError(f"{name} hash mismatch: {actual}")
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
        raise RuntimeError(f"container image ID mismatch: {image_id}")
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
                raise RuntimeError(f"archive member count drifted: {member}")
            data = archive.read(member)
            actual = {"sha256": sha256_bytes(data), "bytes": len(data)}
            if actual != expected:
                raise RuntimeError(f"archive member drifted: {member}")
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
        command, cwd=cwd, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
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

probe_reports = {}
for name in manifest["microprobes"]:
    source = Path("/microprobes") / (name + ".s")
    object_path = output / (name + ".probe.o")
    build = invoke(["gcc", "-c", str(source), "-o", str(object_path)])
    probe_reports[name] = {
        "build": build,
        "object_sha256": (
            hashlib.sha256(object_path.read_bytes()).hexdigest()
            if object_path.is_file() else None
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
    "microprobes": probe_reports,
}, indent=2, sort_keys=True) + "\n")
'''


def compile_all(
    args: argparse.Namespace,
    temporary: Path,
    cases: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, Any],
    Path,
    Path,
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    config = temporary / "config"
    output = temporary / "output"
    vectors = temporary / "vectors"
    variants = temporary / "variants"
    probes = temporary / "microprobes"
    config.mkdir()
    output.mkdir()
    vectors.mkdir()
    source_reports = generated_sources(variants, cases)
    probe_reports = generated_microprobes(probes)
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
        "microprobes": sorted(MICROPROBES),
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
            f"{probes}:/microprobes:ro",
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
        probes,
        vector_reports,
        source_reports,
        probe_reports,
    )


def validate_builds(
    report: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    if report["compiler"] != EXPECTED_COMPILER:
        raise RuntimeError(f"unexpected compiler: {report['compiler']}")
    verifier_build = report["verifier_build"]
    if verifier_build["returncode"] != 0 or verifier_build["stderr"]:
        raise RuntimeError(f"verifier build failed: {verifier_build}")
    for name, case in report["cases"].items():
        for label in (
            "supplied_default_build",
            "full_build",
            "candidate_object_build",
            "verifier_link",
        ):
            item = case[label]
            if item is None or item["returncode"] != 0 or item["stderr"]:
                raise RuntimeError(f"{name}: {label} failed: {item}")
        for label in ("supplied_default_official", "official_vectors"):
            official = case[label]
            if (
                official is None
                or official["returncode"] != 0
                or official["stderr"]
                or not all(official["markers"].values())
            ):
                raise RuntimeError(f"{name}: {label} failed: {official}")
        verification = case["verification"]
        if (
            verification is None
            or verification["returncode"] != 0
            or verification["stderr"]
            or verification["stdout"] != EXPECTED_VERIFIER_STDOUT
        ):
            raise RuntimeError(f"{name}: random verification failed")
    if set(report["cases"]) != set(cases):
        raise RuntimeError("case set drifted")
    for name, probe in report["microprobes"].items():
        build = probe["build"]
        if build["returncode"] != 0 or build["stderr"]:
            raise RuntimeError(f"{name}: microprobe build failed: {build}")


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
        raise RuntimeError(f"{binary}: fewer than two clock calls")
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
        raise RuntimeError(f"{binary}: timed-loop backedge missing")
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
    return {
        "instruction_bytes_total": sum(item[3] for item in loop),
        "by_mnemonic_and_bytes": {
            mnemonic: {str(length): count for length, count in sorted(counts.items())}
            for mnemonic, counts in sorted(by_mnemonic.items())
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


def extract_number(output: str, label: str) -> float:
    match = re.search(
        rf"^{re.escape(label)}:\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"llvm-mca output omitted {label!r}")
    return float(match.group(1))


def analyse_mca(llvm_mca: Path, assembly: Path) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for label, model in MCA_MODELS.items():
        completed = run(
            [
                str(llvm_mca),
                f"-mcpu={model}",
                f"-iterations={MCA_ITERATIONS}",
                str(assembly),
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


def verify_scalar_loop(
    name: str, spec: dict[str, Any], audit: dict[str, Any]
) -> None:
    for field in ("calls", "push_pop", "memory_operands_excluding_lea"):
        if audit[field] != 0:
            raise RuntimeError(f"{name}: expected {field}=0, got {audit[field]}")
    expected = spec["expected"]
    if audit["loop_instructions"] != expected["instructions"]:
        raise RuntimeError(
            f"{name}: expected {expected['instructions']} instructions, "
            f"got {audit['loop_instructions']}"
        )
    for mnemonic in ("rorx", "rol", "ror", "mov"):
        actual = audit["mnemonics"].get(mnemonic, 0)
        if actual != expected[mnemonic]:
            raise RuntimeError(
                f"{name}: expected {expected[mnemonic]} {mnemonic}, got {actual}"
            )
    if audit["mnemonics"].get("bswap", 0) != 80:
        raise RuntimeError(f"{name}: expected 80 BSWAP")
    if audit["mnemonics"].get("xor", 0) != 80:
        raise RuntimeError(f"{name}: expected 80 XOR")
    add_count = audit["mnemonics"].get("add", 0) + audit["mnemonics"].get(
        "lea", 0
    )
    if add_count != 80:
        raise RuntimeError(f"{name}: expected 80 ADD/LEA, got {add_count}")
    if audit["mnemonics"].get("sub", 0) != 1:
        raise RuntimeError(f"{name}: expected one SUB")
    if audit["mnemonics"].get("jne", 0) != 1:
        raise RuntimeError(f"{name}: expected one JNE")


def simplify_execution(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "returncode": report["returncode"],
        "markers": report.get("markers"),
        "marker_lines": report.get("marker_lines"),
    }


def parse_probe_encoding(
    object_path: Path, symbol: str, objdump: Path
) -> dict[str, Any]:
    output = run(
        [
            str(objdump),
            "-d",
            "--insn-width=15",
            f"--disassemble={symbol}",
            str(object_path),
        ]
    ).stdout
    pattern = re.compile(
        r"^\s*([0-9a-fA-F]+):\s+"
        r"((?:[0-9a-fA-F]{2}\s+)+)"
        r"([^\s]+)(?:\s+(.*?))?\s*$"
    )
    instructions = []
    for line in output.splitlines():
        match = pattern.match(line)
        if match:
            instructions.append(
                {
                    "address": f"0x{int(match.group(1), 16):x}",
                    "bytes_hex": " ".join(match.group(2).split()),
                    "bytes": len(match.group(2).split()),
                    "mnemonic": match.group(3),
                    "operands": (match.group(4) or "").strip(),
                }
            )
    non_ret = [item for item in instructions if item["mnemonic"] != "ret"]
    if len(non_ret) != 1:
        raise RuntimeError(f"{symbol}: expected one probe instruction: {instructions}")
    return non_ret[0]


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    inputs = validate_inputs(args)
    cases = case_specs()
    with tempfile.TemporaryDirectory(
        prefix="challenge02-tenth-scalar-rotate-"
    ) as raw_temporary:
        temporary = Path(raw_temporary).resolve()
        (
            compiled,
            binaries,
            probes,
            vectors,
            source_reports,
            probe_source_reports,
        ) = compile_all(args, temporary, cases)
        validate_builds(compiled, cases)

        case_results: dict[str, Any] = {}
        for name, spec in cases.items():
            binary = binaries / name
            audit = audit_main_timing_loop(
                binary,
                objdump=str(args.objdump),
                size_tool=str(args.size_tool),
            )
            verify_scalar_loop(name, spec, audit)
            raw = raw_loop_report(binary, args.objdump)
            if raw["instruction_bytes_total"] != audit["loop_bytes"]:
                raise RuntimeError(f"{name}: raw parser disagrees with audit")
            loop_path = temporary / f"{name}.loop.s"
            extract_loop(binary, loop_path, args.objdump)
            raw_case = compiled["cases"][name]
            if raw_case["binary_sha256"] != audit["binary_sha256"]:
                raise RuntimeError(f"{name}: binary hash mismatch")
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
                "encoding": raw,
                "loop_artifact_sha256": sha256(loop_path),
                "llvm_mca": analyse_mca(args.llvm_mca, loop_path),
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

        microprobe_results: dict[str, Any] = {}
        for name, source_report in probe_source_reports.items():
            object_path = binaries / f"{name}.probe.o"
            if compiled["microprobes"][name]["object_sha256"] != sha256(
                object_path
            ):
                raise RuntimeError(f"{name}: probe object hash mismatch")
            mca_path = probes / f"{name}.mca.s"
            microprobe_results[name] = {
                **source_report,
                "object_sha256": sha256(object_path),
                "encoding": parse_probe_encoding(
                    object_path, name, args.objdump
                ),
                "llvm_mca": analyse_mca(args.llvm_mca, mca_path),
            }

        incumbent = case_results["bmi2_rorx"]
        forced = case_results["forced_same_register_rol"]
        portable = case_results["portable_compiler_rol"]
        matched = case_results["source_order_compiler_rol"]
        shld_alder = microprobe_results["shld_same_register"]["llvm_mca"][
            "alderlake_p_core_proxy"
        ]
        rorx_alder = microprobe_results["rorx_same_register"]["llvm_mca"][
            "alderlake_p_core_proxy"
        ]
        if shld_alder["cycles_per_iteration"] <= rorx_alder[
            "cycles_per_iteration"
        ]:
            raise RuntimeError("SHLD dependency-chain rejection assumption drifted")

        return {
            "schema_version": 1,
            "experiment": "challenge02_tenth_scalar_same_register_rotate",
            "scope": {
                "full_candidate_count": len(cases),
                "microprobe_count": len(MICROPROBES),
                "host_timing": False,
                "reason": (
                    "separate compiler-generated portable ROL from a forced "
                    "same-register stream and reject SHLD before full expansion"
                ),
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
                "official_vectors_every_full_case": True,
                "supplied_default_official_vectors_every_full_case": True,
                "random_differential_every_full_case": True,
                "random_cases_per_case": 100_000,
                "random_state_and_constants": True,
                "round_counts": [1, 20],
                "complete_clock_delimited_loop_audit_every_full_case": True,
            },
            "cases": case_results,
            "microprobes": microprobe_results,
            "summary": {
                "all_builds_official_random_audits": "PASS",
                "incumbent": {
                    "case": "bmi2_rorx",
                    "bytes": incumbent["loop"]["bytes"],
                    "instructions": incumbent["loop"]["instructions"],
                    "moves": incumbent["loop"]["mnemonics"].get("mov", 0),
                    "rotate": {"rorx": 80},
                    "llvm_mca": incumbent["llvm_mca"],
                },
                "compiler_portable_control": {
                    "case": "portable_compiler_rol",
                    "bytes": portable["loop"]["bytes"],
                    "instructions": portable["loop"]["instructions"],
                    "moves": portable["loop"]["mnemonics"].get("mov", 0),
                    "rotate": {"rol": 60, "ror": 20},
                    "llvm_mca": portable["llvm_mca"],
                },
                "source_order_compiler_rol": {
                    "case": "source_order_compiler_rol",
                    "bytes": matched["loop"]["bytes"],
                    "instructions": matched["loop"]["instructions"],
                    "moves": matched["loop"]["mnemonics"].get("mov", 0),
                    "rotate": {"rol": 60, "ror": 20},
                    "llvm_mca": matched["llvm_mca"],
                },
                "forced_same_register_rol": {
                    "case": "forced_same_register_rol",
                    "bytes": forced["loop"]["bytes"],
                    "instructions": forced["loop"]["instructions"],
                    "moves": forced["loop"]["mnemonics"].get("mov", 0),
                    "rotate": {"rol": 80},
                    "llvm_mca": forced["llvm_mca"],
                },
            },
            "conclusions": {
                "same_register_rol": {
                    "status": "static-code-size-win-only",
                    "result": (
                        f"The forced read/write form emits {forced['loop']['instructions']} "
                        f"instructions/{forced['loop']['bytes']} bytes with "
                        f"{forced['loop']['mnemonics'].get('mov', 0)} MOV, versus "
                        f"the source-order-matched compiler control's "
                        f"{matched['loop']['instructions']} instructions/"
                        f"{matched['loop']['bytes']} bytes and "
                        f"{matched['loop']['mnemonics'].get('mov', 0)} MOV. "
                        "The older portable control is retained separately."
                    ),
                    "comparison_to_rorx": (
                        f"It is {incumbent['loop']['bytes'] - forced['loop']['bytes']} "
                        "bytes smaller than the RORX incumbent, but the Alder/"
                        "Meteor proxy rises from "
                        f"{incumbent['llvm_mca']['alderlake_p_core_proxy']['cycles_per_iteration']:.2f} "
                        "to "
                        f"{forced['llvm_mca']['alderlake_p_core_proxy']['cycles_per_iteration']:.2f} "
                        "cycles and from "
                        f"{incumbent['llvm_mca']['alderlake_p_core_proxy']['uops_per_iteration']:.0f} "
                        "to "
                        f"{forced['llvm_mca']['alderlake_p_core_proxy']['uops_per_iteration']:.0f} "
                        "uops."
                    ),
                    "promotion": (
                        "not promoted; retain at most as a target-only timing "
                        "diagnostic"
                    ),
                },
                "same_register_shld": {
                    "status": "rejected-before-full-expansion",
                    "reason": (
                        "Although SHLD with identical source/destination is an "
                        "exact rotate, the dependency-chain microprobe has "
                        f"{shld_alder['cycles_per_iteration']:.2f} modeled cycles "
                        "per instruction on Alder Lake versus "
                        f"{rorx_alder['cycles_per_iteration']:.2f} for RORX. "
                        "Eighty serial-chain uses therefore have no credible "
                        "latency path to a win."
                    ),
                    "full_candidate_built": False,
                },
            },
            "model_limits": {
                "llvm_mca": (
                    "LLVM-MCA 16 models instruction scheduling but not the exact "
                    "Core Ultra 7 255H P/E/LP-E implementation, frequency, or "
                    "all front-end effects."
                ),
                "host_timing": (
                    "No host timing is collected; repeated target-core timing is "
                    "required before promotion."
                ),
            },
            "primary_documentation": PRIMARY_DOCUMENTATION,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce challenge 2's same-register rotate screen"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=HERE / "tenth_codegen_scalar_rotate_results_02.json",
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
