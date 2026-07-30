#!/usr/bin/env python3
"""Reproduce challenge 2's commutative AVX2 encoding/layout screen.

The retained inline-assembly source puts the changing low YMM register in the
ModRM r/m position of VPOR/VPXOR/VPADDQ.  High allocator-chosen operands then
fit in VEX.vvvv, shortening the exact linked timed loop without changing its
instruction count or dependency graph.  This screen compiles 34 explicit
backend/layout cases in the digest-pinned GCC 13.3 image, audits the complete
clock-delimited loop, verifies every case dynamically, and runs each distinct
normalized stream through two llvm-mca proxy models.  It performs no host
timing and makes no claim about an unavailable Core Ultra 7 255H.
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

from loop_audit import (  # noqa: E402
    audit_main_timing_loop,
    validate_loop_audit,
)


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
    AUDITOR_RELATIVE: "7d14dca7b8d4d4d9dbae96a0a5e49a06b488458293ce927018296cde0216952c",
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
    "znver2_cross_architecture_proxy": "znver2",
}
MCA_ITERATIONS = 100

BASELINE_LOOP_SHA256 = "0b4f2686a2a19ce4fe96d12b89d01e38092c088794252c8e1d8460c75bb8ae4b"
INCDEC_LOOP_SHA256 = "313dcc820be6159d23989db6dc37615ea104bd1f9430911d18229ef1241015d7"

PRIMARY_DOCUMENTATION = [
    {
        "title": "GCC 13.3 x86 options",
        "url": "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/x86-Options.html",
        "used_for": "-mtune, -mtune-ctrl, AVX2, and assembler policy",
    },
    {
        "title": "GCC 13.3 optimization options",
        "url": (
            "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/"
            "Optimize-Options.html"
        ),
        "used_for": "alignment, scheduling, IRA, LTO, and vector pass flags",
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


def build_cases() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}

    def add(
        name: str,
        *,
        group: str,
        cflags: tuple[str, ...] = (),
        ldflags: tuple[str, ...] = (),
        reference: bool = False,
    ) -> None:
        if name in cases:
            raise RuntimeError(f"duplicate case: {name}")
        cases[name] = {
            "group": group,
            "cflags": list(cflags),
            "ldflags": list(ldflags),
            "reference": reference,
        }

    add("baseline", group="reference", reference=True)
    for name, flag in (
        ("align_loops_1", "-falign-loops=1"),
        ("align_loops_8", "-falign-loops=8"),
        ("align_loops_16", "-falign-loops=16"),
        ("align_loops_32", "-falign-loops=32"),
        ("align_loops_64", "-falign-loops=64"),
        ("align_loops_128", "-falign-loops=128"),
        ("align_loops_64_15", "-falign-loops=64:15"),
        ("align_loops_64_31", "-falign-loops=64:31"),
        ("align_loops_64_63", "-falign-loops=64:63"),
    ):
        add(name, group="loop_alignment", cflags=(flag,))
    add(
        "no_align_loops",
        group="loop_alignment",
        cflags=("-fno-align-loops",),
    )
    add(
        "align_functions_64",
        group="combined_alignment",
        cflags=("-falign-functions=64",),
    )
    add(
        "align_functions_loops_64",
        group="combined_alignment",
        cflags=("-falign-functions=64", "-falign-loops=64"),
    )
    add(
        "align_all_64",
        group="combined_alignment",
        cflags=(
            "-falign-functions=64",
            "-falign-jumps=64",
            "-falign-labels=64",
            "-falign-loops=64",
        ),
    )
    add(
        "branch_boundary_32",
        group="assembler_layout",
        cflags=("-Wa,-mbranches-within-32B-boundaries",),
    )
    add(
        "no_tree_vectorize",
        group="pass_control",
        cflags=("-fno-tree-vectorize",),
    )
    add(
        "no_tree_slp_vectorize",
        group="pass_control",
        cflags=("-fno-tree-slp-vectorize",),
    )
    add(
        "ira_one",
        group="register_allocation",
        cflags=("-fira-region=one",),
    )
    add(
        "ira_priority",
        group="register_allocation",
        cflags=("-fira-algorithm=priority",),
    )
    add(
        "rename_registers",
        group="register_allocation",
        cflags=("-frename-registers",),
    )
    add(
        "no_schedule_insns2",
        group="scheduler",
        cflags=("-fno-schedule-insns2",),
    )
    add(
        "no_peephole2",
        group="pass_control",
        cflags=("-fno-peephole2",),
    )
    for tune in ("alderlake", "gracemont", "meteorlake", "graniterapids"):
        add(
            f"tune_{tune}",
            group="target_tune",
            cflags=(f"-mtune={tune}",),
        )
    add(
        "incdec_only",
        group="developer_tune_control",
        cflags=("-mtune-ctrl=use_incdec",),
    )
    add(
        "function_sections",
        group="link_layout",
        cflags=("-ffunction-sections", "-fdata-sections"),
    )
    add(
        "function_sections_gc",
        group="link_layout",
        cflags=("-ffunction-sections", "-fdata-sections"),
        ldflags=("-Wl,--gc-sections",),
    )
    add(
        "function_sections_sort_alignment",
        group="link_layout",
        cflags=("-ffunction-sections",),
        ldflags=("-Wl,--sort-section=alignment",),
    )
    add(
        "function_sections_sort_name",
        group="link_layout",
        cflags=("-ffunction-sections",),
        ldflags=("-Wl,--sort-section=name",),
    )
    add("no_relax", group="link_layout", ldflags=("-Wl,--no-relax",))
    add(
        "noseparate_code",
        group="link_layout",
        ldflags=("-Wl,-z,noseparate-code",),
    )
    add(
        "lto",
        group="whole_program",
        cflags=("-flto",),
        ldflags=("-flto",),
    )

    if len(cases) != 34:
        raise RuntimeError(f"expected 34 cases, got {len(cases)}")
    if len({(tuple(c["cflags"]), tuple(c["ldflags"])) for c in cases.values()}) != 34:
        raise RuntimeError("case flag tuples are not unique")
    return cases


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
source = "/repository/" + manifest["source"]
verifier_source = "/repository/" + manifest["verifier"]

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
    # The supplied program prints a nondeterministic timing value.  Preserve
    # only correctness markers in the generated artifact.
    report.pop("stdout")
    return report

verifier_object = output / "verifier.o"
verifier_build = invoke([
    "gcc", *manifest["verifier_flags"], "-c", verifier_source,
    "-o", str(verifier_object),
])

default_binary = output / "supplied_default"
default_build = invoke([
    "gcc", *manifest["supplied_default_flags"], source,
    "-o", str(default_binary),
])
default_official = (
    official(default_binary) if default_build["returncode"] == 0 else None
)

reports = {}
for name, case in manifest["cases"].items():
    binary = output / name
    candidate_object = output / (name + ".o")
    verifier_binary = output / (name + ".verify")
    effective_flags = [*manifest["common_flags"], *case["cflags"]]
    full_build = invoke([
        "gcc", *effective_flags, source, *case["ldflags"],
        "-o", str(binary),
    ])
    candidate_build = invoke([
        "gcc", *effective_flags, "-Dmain=contest_candidate_main", "-c",
        source, "-o", str(candidate_object),
    ])
    link = None
    verification = None
    official_vectors = None
    if (
        verifier_build["returncode"] == 0
        and full_build["returncode"] == 0
        and candidate_build["returncode"] == 0
    ):
        link = invoke([
            "gcc", str(candidate_object), str(verifier_object),
            *case["ldflags"], "-o", str(verifier_binary),
        ])
        if link["returncode"] == 0:
            verification = invoke([str(verifier_binary), "100000"])
        official_vectors = official(binary)
    reports[name] = {
        "effective_cflags": effective_flags,
        "effective_ldflags": case["ldflags"],
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
    "supplied_default": {
        "flags": manifest["supplied_default_flags"],
        "build": default_build,
        "official_vectors": default_official,
        "binary_sha256": (
            hashlib.sha256(default_binary.read_bytes()).hexdigest()
            if default_binary.is_file() else None
        ),
    },
    "cases": reports,
}, indent=2, sort_keys=True) + "\n")
'''


def compile_and_verify(
    args: argparse.Namespace,
    temporary: Path,
    cases: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    config = temporary / "config"
    output = temporary / "output"
    vectors = temporary / "vectors"
    config.mkdir()
    output.mkdir()
    vectors.mkdir()
    vector_reports = extract_vectors(vectors)
    manifest = {
        "source": SOURCE_RELATIVE,
        "verifier": VERIFIER_RELATIVE,
        "common_flags": COMMON_FLAGS,
        "supplied_default_flags": SUPPLIED_DEFAULT_FLAGS,
        "verifier_flags": VERIFIER_FLAGS,
        "official_markers": OFFICIAL_MARKERS,
        "cases": cases,
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
            f"{vectors}:/vectors:ro",
            "--volume",
            f"{output}:/output",
            IMAGE,
            "python3",
            "-c",
            CONTAINER_DRIVER,
        ]
    )
    return json.loads((output / "build-report.json").read_text()), output, vector_reports


def fail_if_build_or_correctness_failed(
    report: dict[str, Any], cases: dict[str, dict[str, Any]]
) -> None:
    if report["compiler"] != EXPECTED_COMPILER:
        raise RuntimeError(f"unexpected compiler: {report['compiler']}")
    verifier_build = report["verifier_build"]
    if verifier_build["returncode"] != 0 or verifier_build["stderr"]:
        raise RuntimeError(f"verifier build failed or warned: {verifier_build}")

    default = report["supplied_default"]
    if default["build"]["returncode"] != 0 or default["build"]["stderr"]:
        raise RuntimeError(f"supplied-default build failed or warned: {default['build']}")
    default_official = default["official_vectors"]
    if (
        default_official is None
        or default_official["returncode"] != 0
        or default_official["stderr"]
        or not all(default_official["markers"].values())
    ):
        raise RuntimeError(
            f"supplied-default official verification failed: {default_official}"
        )

    if set(report["cases"]) != set(cases):
        raise RuntimeError("container case set differs from manifest")
    for name, case_report in report["cases"].items():
        for label in ("full_build", "candidate_object_build", "verifier_link"):
            item = case_report[label]
            if item is None or item["returncode"] != 0 or item["stderr"]:
                raise RuntimeError(f"{name}: {label} failed or warned: {item}")
        verification = case_report["verification"]
        if (
            verification is None
            or verification["returncode"] != 0
            or verification["stderr"]
            or verification["stdout"] != EXPECTED_VERIFIER_STDOUT
        ):
            raise RuntimeError(f"{name}: random verification failed: {verification}")
        official = case_report["official_vectors"]
        if (
            official is None
            or official["returncode"] != 0
            or official["stderr"]
            or not all(official["markers"].values())
        ):
            raise RuntimeError(f"{name}: official vectors failed: {official}")


def extract_number(output: str, label: str) -> float:
    match = re.search(
        rf"^{re.escape(label)}:\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"llvm-mca output omitted {label!r}")
    return float(match.group(1))


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
    clock_indices = [
        index
        for index, (_, opcode, operands) in enumerate(instructions)
        if opcode.startswith("call")
        and re.search(r"<clock(?:@[^>]*)?>", operands)
    ]
    if len(clock_indices) < 2:
        raise RuntimeError(f"{binary}: fewer than two clock calls")
    backedges: list[tuple[int, int]] = []
    for index in range(clock_indices[-2] + 1, clock_indices[-1]):
        address, opcode, operands = instructions[index]
        target = re.match(r"(?:\*?0x)?([0-9a-fA-F]+)", operands)
        if (
            opcode.startswith("j")
            and opcode != "jmp"
            and target
            and int(target.group(1), 16) < address
        ):
            backedges.append((index, int(target.group(1), 16)))
    if not backedges:
        raise RuntimeError(f"{binary}: timed-loop backedge not found")
    end_index, start_address = backedges[-1]
    index_by_address = {
        address: index for index, (address, _, _) in enumerate(instructions)
    }
    loop = instructions[index_by_address[start_address] : end_index + 1]
    lines = [".text", ".Ltimed_loop:"]
    for index, (_, opcode, operands) in enumerate(loop):
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


def raw_loop_instruction_lengths(binary: Path, objdump: Path) -> dict[str, Any]:
    disassembly = run(
        [str(objdump), "-d", "--disassemble=main", str(binary)]
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
        raise RuntimeError(f"{binary}: raw parser found no loop backedge")
    end_index, start_address = backedges[-1]
    start_index = next(
        index
        for index, (address, _, _, _) in enumerate(instructions)
        if address == start_address
    )
    loop = instructions[start_index : end_index + 1]
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


def verify_loop_shape(name: str, audit: dict[str, Any]) -> None:
    errors = validate_loop_audit(audit, "avx2-inline-lanewise")
    if errors:
        raise RuntimeError(f"{name}: structural audit failed: {errors}")
    expected_mnemonics = {
        "vpaddq": 20,
        "vpor": 20,
        "vpshufb": 20,
        "vpsllvq": 20,
        "vpsrlvq": 20,
        "vpxor": 20,
        "jne": 1,
    }
    for mnemonic, count in expected_mnemonics.items():
        if audit["mnemonics"].get(mnemonic) != count:
            raise RuntimeError(
                f"{name}: expected {count} {mnemonic}, "
                f"got {audit['mnemonics'].get(mnemonic)}"
            )
    counter_count = audit["mnemonics"].get("sub", 0) + audit["mnemonics"].get(
        "dec", 0
    )
    if counter_count != 1:
        raise RuntimeError(f"{name}: expected one sub/dec loop counter")
    if audit["loop_bytes"] < 548:
        raise RuntimeError(
            f"{name}: observed {audit['loop_bytes']} bytes below the justified bound"
        )


def simplify_execution(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "returncode": report["returncode"],
        "markers": report.get("markers"),
        "marker_lines": report.get("marker_lines"),
    }


def build_result(args: argparse.Namespace) -> dict[str, Any]:
    inputs = validate_inputs(args)
    cases = build_cases()
    with tempfile.TemporaryDirectory(
        prefix="challenge-avx2-commutative-layout-"
    ) as raw_temporary:
        temporary = Path(raw_temporary).resolve()
        compiled, binaries, vectors = compile_and_verify(
            args, temporary, cases
        )
        fail_if_build_or_correctness_failed(compiled, cases)

        case_results: dict[str, Any] = {}
        stream_members: dict[str, list[str]] = {}
        stream_representatives: dict[str, str] = {}
        stream_reports: dict[str, Any] = {}

        for name, spec in cases.items():
            binary = binaries / name
            audit = audit_main_timing_loop(
                binary,
                objdump=str(args.objdump),
                size_tool=str(args.size_tool),
            )
            verify_loop_shape(name, audit)
            loop_hash = audit["normalized_loop_sha256"]
            encoding = raw_loop_instruction_lengths(binary, args.objdump)
            if encoding["instruction_bytes_total"] != audit["loop_bytes"]:
                raise RuntimeError(f"{name}: raw-byte parser disagrees with loop audit")
            raw_case = compiled["cases"][name]
            if raw_case["binary_sha256"] != audit["binary_sha256"]:
                raise RuntimeError(f"{name}: container and host binary hashes differ")
            case_results[name] = {
                **spec,
                "effective_cflags": raw_case["effective_cflags"],
                "effective_ldflags": raw_case["effective_ldflags"],
                "build": {
                    "status": "PASS",
                    "binary_sha256": raw_case["binary_sha256"],
                },
                "loop": compact_audit(audit),
                "encoding": encoding,
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
            }
            stream_members.setdefault(loop_hash, []).append(name)
            preferred = min(
                stream_members[loop_hash],
                key=lambda candidate: (
                    0 if candidate == "baseline" else 1,
                    0 if candidate == "incdec_only" else 1,
                    candidate,
                ),
            )
            stream_representatives[loop_hash] = preferred

        baseline = case_results["baseline"]
        if (
            baseline["loop"]["normalized_sha256"] != BASELINE_LOOP_SHA256
            or baseline["loop"]["bytes"] != 549
            or baseline["loop"]["instructions"] != 122
            or baseline["loop"]["hot_memory_operands_excluding_lea"] != 0
            or baseline["loop"]["start_mod_64"] != 0
        ):
            raise RuntimeError(f"baseline exact GCC 13 loop drifted: {baseline['loop']}")

        for incdec_name in ("incdec_only", "tune_graniterapids"):
            incdec = case_results[incdec_name]
            if (
                incdec["loop"]["normalized_sha256"] != INCDEC_LOOP_SHA256
                or incdec["loop"]["bytes"] != 548
                or incdec["loop"]["instructions"] != 122
                or incdec["loop"]["hot_memory_operands_excluding_lea"] != 0
                or incdec["loop"]["mnemonics"].get("dec") != 1
            ):
                raise RuntimeError(f"{incdec_name} exact loop drifted: {incdec['loop']}")

        expected_baseline_encoding = {
            "jne": {"6": 1},
            "sub": {"3": 1},
            "vpaddq": {"4": 20},
            "vpor": {"4": 20},
            "vpshufb": {"5": 20},
            "vpsllvq": {"5": 20},
            "vpsrlvq": {"5": 20},
            "vpxor": {"4": 20},
        }
        if baseline["encoding"]["by_mnemonic_and_bytes"] != expected_baseline_encoding:
            raise RuntimeError(
                "baseline encoding breakdown drifted: "
                f"{baseline['encoding']['by_mnemonic_and_bytes']}"
            )
        expected_incdec_encoding = dict(expected_baseline_encoding)
        expected_incdec_encoding.pop("sub")
        expected_incdec_encoding["dec"] = {"2": 1}
        expected_incdec_encoding = dict(sorted(expected_incdec_encoding.items()))
        if (
            case_results["incdec_only"]["encoding"][
                "by_mnemonic_and_bytes"
            ]
            != expected_incdec_encoding
        ):
            raise RuntimeError("incdec encoding breakdown drifted")

        for loop_hash, members in sorted(stream_members.items()):
            representative = stream_representatives[loop_hash]
            loop_path = temporary / f"stream-{len(stream_reports):02d}.s"
            extract_loop(binaries / representative, loop_path, args.objdump)
            stream_reports[loop_hash] = {
                "representative": representative,
                "members": sorted(members),
                "loop_artifact_sha256": sha256(loop_path),
                "loop": case_results[representative]["loop"],
                "encoding": case_results[representative]["encoding"],
                "llvm_mca": analyse_loop(args.llvm_mca, loop_path),
            }

        alignment_groups: dict[tuple[str, int], list[str]] = {}
        for name, report in case_results.items():
            key = (
                report["loop"]["normalized_sha256"],
                report["loop"]["start_mod_64"],
            )
            alignment_groups.setdefault(key, []).append(name)
        alignment_classes = []
        for (loop_hash, start_mod_64), names in sorted(alignment_groups.items()):
            representative = min(
                names,
                key=lambda candidate: (
                    0 if candidate == "baseline" else 1,
                    0 if candidate == "incdec_only" else 1,
                    candidate,
                ),
            )
            loop_bytes = case_results[representative]["loop"]["bytes"]
            alignment_classes.append(
                {
                    "normalized_sha256": loop_hash,
                    "start_mod_64": start_mod_64,
                    "representative": representative,
                    "members": sorted(names),
                    "loop_bytes": loop_bytes,
                    "spanned_64_byte_lines": (
                        start_mod_64 + loop_bytes + 63
                    )
                    // 64,
                }
            )

        mca_signatures = {
            json.dumps(stream["llvm_mca"], sort_keys=True)
            for stream in stream_reports.values()
        }
        supplied_default = compiled["supplied_default"]
        result = {
            "schema_version": 1,
            "experiment": "challenge_avx2_commutative_encoding_and_layout",
            "scope": {
                "question": (
                    "Does placing the low changing value in ModRM r/m for "
                    "commutative AVX2 operations shorten the exact GCC 13.3 "
                    "timed loop, and how stable is that stream across bounded "
                    "backend and linked-layout controls?"
                ),
                "host_timing": False,
                "target_timing": False,
                "target": "Intel Core Ultra 7 255H",
            },
            "primary_documentation": PRIMARY_DOCUMENTATION,
            "protocol": {
                "compiler_image": IMAGE,
                "expected_compiler": EXPECTED_COMPILER,
                "case_count": len(cases),
                "common_flags": COMMON_FLAGS,
                "supplied_default_command": [
                    "gcc",
                    *SUPPLIED_DEFAULT_FLAGS,
                    "contest.c",
                    "-o",
                    "contest",
                ],
                "complete_binary_clock_delimited_loop_audit": True,
                "audit_mode": "avx2-inline-lanewise",
                "random_differential": {
                    "per_case": True,
                    "cases": 100_000,
                    "seed": "0x243f6a8885a308d3",
                    "random_state_and_constants": True,
                    "round_counts": [1, 20],
                },
                "official_vectors": {
                    "per_case": True,
                    "one_round_pairs": 1_000,
                    "twenty_round_cases": 1,
                },
                "llvm_mca": {
                    "distinct_normalized_streams_only": True,
                    "iterations": MCA_ITERATIONS,
                    "models": MCA_MODELS,
                    "interpretation": "static scheduling proxy, not target timing",
                },
                "determinism": (
                    "no timestamps or raw timing stdout; --check regenerates "
                    "and compares canonical JSON bytes"
                ),
            },
            "inputs": {
                **inputs,
                "extracted_vectors": vectors,
            },
            "toolchain": {
                "compiler": compiled["compiler"],
                "binutils": compiled["binutils"],
                "container": inputs["container"],
            },
            "supplied_default": {
                "flags": supplied_default["flags"],
                "build_status": "PASS",
                "binary_sha256": supplied_default["binary_sha256"],
                "official_vectors": simplify_execution(
                    supplied_default["official_vectors"]
                ),
            },
            "counts": {
                "cases": len(case_results),
                "build_pass": len(case_results),
                "audit_pass": len(case_results),
                "random_differential_pass": len(case_results),
                "official_vectors_pass": len(case_results),
                "unique_normalized_streams": len(stream_reports),
                "stream_alignment_classes": len(alignment_classes),
                "unique_mca_signatures": len(mca_signatures),
            },
            "cases": case_results,
            "streams": stream_reports,
            "alignment_classes": alignment_classes,
            "encoding_lower_bound": {
                "scope": (
                    "current six-instruction AVX2 round dataflow with a "
                    "32-bit loop counter and rel32 backedge"
                ),
                "per_round_bytes": {
                    "vpsrlvq": 5,
                    "vpsllvq": 5,
                    "vpor": 4,
                    "vpxor": 4,
                    "vpshufb": 5,
                    "vpaddq": 4,
                    "total": 27,
                },
                "rounds": 20,
                "round_body_bytes": 540,
                "default_loop_control_bytes": {
                    "sub_eax_1": 3,
                    "jne_rel32": 6,
                    "total": 9,
                },
                "default_total_bytes": 549,
                "incdec_loop_control_bytes": {
                    "dec_eax": 2,
                    "jne_rel32": 6,
                    "total": 8,
                },
                "incdec_total_bytes": 548,
                "observed_default_case": "baseline",
                "observed_incdec_cases": [
                    "incdec_only",
                    "tune_graniterapids",
                ],
                "caveat": (
                    "This is an encoding bound for the retained dataflow, not "
                    "a proof that no different algorithm can use fewer instructions."
                ),
            },
            "decision": {
                "commutative_encoding": {
                    "status": "retain",
                    "source": SOURCE_RELATIVE,
                    "source_sha256": INPUT_HASHES[SOURCE_RELATIVE],
                    "exact_gcc13_loop": {
                        "instructions": baseline["loop"]["instructions"],
                        "bytes": baseline["loop"]["bytes"],
                        "hot_memory_operands_excluding_lea": baseline["loop"][
                            "hot_memory_operands_excluding_lea"
                        ],
                        "normalized_sha256": baseline["loop"][
                            "normalized_sha256"
                        ],
                        "start_mod_64": baseline["loop"]["start_mod_64"],
                    },
                    "reason": (
                        "The low changing value occupies ModRM r/m while high "
                        "scratch/constants use VEX.vvvv; all 20 VPOR encodings "
                        "shrink by one byte without changing instruction count, "
                        "hot memory, correctness, or proxy scheduling."
                    ),
                },
                "incdec_548": {
                    "status": "target-only",
                    "case": "incdec_only",
                    "equivalent_tune_case": "tune_graniterapids",
                    "reason": (
                        "The sole byte reduction is the supplied harness outer "
                        "counter changing from three-byte SUB to two-byte DEC; "
                        "it needs independent P/E/LP-E timing before promotion."
                    ),
                },
                "layout": {
                    "status": "default-retained-pending-target-timing",
                    "default_start_mod_64": baseline["loop"]["start_mod_64"],
                    "alignment_class_count": len(alignment_classes),
                    "reason": (
                        "Identical normalized streams at different offsets have "
                        "front-end effects that llvm-mca does not model."
                    ),
                },
                "mca": {
                    "unique_signatures": len(mca_signatures),
                    "caveat": (
                        "Alder Lake and Zen 2 are static proxies and cannot "
                        "select a Core Ultra 7 255H P/E/LP-E winner."
                    ),
                },
                "promotion_limit": (
                    "Correctness and exact code shape are established; actual "
                    "255H core-type timing remains required for submission choice."
                ),
            },
        }
        return result


def canonical_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce the exact GCC 13.3 commutative AVX2 encoding/layout screen"
        )
    )
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--objdump", type=Path, default=DEFAULT_OBJDUMP)
    parser.add_argument("--size-tool", type=Path, default=DEFAULT_SIZE)
    parser.add_argument("--llvm-mca", type=Path, default=DEFAULT_LLVM_MCA)
    parser.add_argument(
        "--json",
        type=Path,
        default=HERE / "avx2_commutative_layout_results.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and require exact canonical JSON equality",
    )
    args = parser.parse_args()

    rendered = canonical_json(build_result(args))
    if args.check:
        if not args.json.is_file():
            parser.error(f"missing result for --check: {args.json}")
        existing = args.json.read_text()
        if existing != rendered:
            raise RuntimeError(
                f"generated result differs from {args.json}; regenerate it"
            )
        print(f"check=PASS json={args.json}")
        return

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(rendered)
    print(f"json={args.json}")


if __name__ == "__main__":
    main()
