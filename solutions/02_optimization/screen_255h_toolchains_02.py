#!/usr/bin/env python3
"""Static GCC/Clang follow-up screen for challenge 2 on Core Ultra 7 255H.

The target machine is not available here.  This script therefore keeps target
support, code shape, llvm-mca proxy results, and correctness gates separate.
It never performs a host timing campaign: official-vector validation rewrites
the irrelevant timing-loop trip count to one, and the 100k-case differential
verifier contains no timer.
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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "solutions"))

import screen_gcc133_layout_02 as layout  # noqa: E402
import screen_gcc133_schedules_02 as schedule  # noqa: E402
from challenge02_loop_audit import (  # noqa: E402
    audit_main_timing_loop,
    validate_loop_audit,
)


SOURCE_RELATIVE = "submissions/02/contest.c"
SOURCE = ROOT / SOURCE_RELATIVE
SOURCE_SHA256 = "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71"
ARCHIVE = ROOT / "problems/2_암호구현.zip"
VERIFIER = ROOT / "solutions/02_optimization/verify_contest_candidate_02.c"

INPUT_HASHES = {
    SOURCE_RELATIVE: SOURCE_SHA256,
    "problems/2_암호구현.zip": (
        "d0c3158adda8ba258becfc0e347267c0f2f0112738ec732be6dcb5477342e88e"
    ),
    "solutions/02_optimization/verify_contest_candidate_02.c": (
        "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35"
    ),
    "solutions/challenge02_loop_audit.py": (
        "f2e5f82f4ff88b0b8a743c06e418f93cd4a8f137b0a0335d949939b24c764d45"
    ),
}

DEFAULT_CLANG = Path(
    "/home/seorii/.local/share/swiftly/toolchains/6.3.3/usr/bin/clang-21"
)
DEFAULT_OBJDUMP = Path("/usr/bin/x86_64-linux-gnu-objdump")
DEFAULT_SIZE = Path("/usr/bin/x86_64-linux-gnu-size")
DEFAULT_LD = Path("/usr/bin/x86_64-linux-gnu-ld.bfd")
DEFAULT_LLVM_MCA = Path("/usr/bin/llvm-mca-16")

PINNED_TOOL_HASHES = {
    "clang": "fef5a56e4278a403fcaa23ad46513769dba1e020b0a8a2ce1a6af7eb99d09d9b",
    "ld": "f6d71a1bcd45764550a42dfaa179bc43b63ee879ec6f875bfd39fca013515da7",
    "objdump": "19717049e8ecd98cfbb17fd9eb25e9fd896ecec2fc4af6b931f3dd0bc4e903de",
    "size": "d2dc6eb962bfc841403cc8b72191bfd829b50d8796b611689e92cfb051cf10ee",
    "llvm_mca": "e7f38b12a3c228c8b0bcea0bf63cc56939286adf9ae5397a43d408322e3c6fbf",
}

GCC_BASE_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-mbmi2",
    "-finline-limit=2000",
    "-mtune=alderlake",
    "-fira-algorithm=priority",
]

CLANG_BASE_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-mbmi2",
    "-mllvm",
    "-inline-threshold=2000",
]

TARGET_CPUS = (
    "alderlake",
    "raptorlake",
    "meteorlake",
    "arrowlake",
    "arrowlake-s",
    "lunarlake",
    "pantherlake",
)

MCA_MODELS = {
    "p_core_proxy_alderlake": "alderlake",
    "e_core_proxy_tremont": "tremont",
}
MCA_ITERATIONS = 100

GCC_VERIFICATION_CASES = {
    "gcc_selective_graniterapids": [
        "-fselective-scheduling2",
        "-mtune=graniterapids",
    ],
    "gcc_nosched_graniterapids": [
        "-fno-schedule-insns2",
        "-mtune=graniterapids",
    ],
}

CLANG_VERIFICATION_CASES = {
    "clang_arrow_misched_ilpmax": [
        "-march=arrowlake",
        "-mllvm",
        "-misched=ilpmax",
    ],
    "clang_arrow_misched_ilpmin": [
        "-march=arrowlake",
        "-mllvm",
        "-misched=ilpmin",
    ],
}

PRIMARY_SOURCES = [
    {
        "title": "Intel ARK: Core Ultra 7 255H specifications",
        "url": (
            "https://www.intel.com/content/www/us/en/products/sku/241751/"
            "intel-core-ultra-7-processor-255h-24m-cache-up-to-5-10-ghz/"
            "specifications.html"
        ),
        "used_for": (
            "Arrow Lake Series 2 identity, 6 P + 8 E + 2 LP-E cores, "
            "16 threads, AVX2"
        ),
    },
    {
        "title": "Intel PerfMon: Arrow Lake P-core events",
        "url": "https://perfmon-events.intel.com/platforms/arrowlake/core-events/p-core/",
        "used_for": "Lion Cove P-core, Skymont E-core, Crestmont LP-E identity",
    },
    {
        "title": "Intel consolidated product CPU model table",
        "url": (
            "https://www.intel.com/content/www/us/en/developer/topic-technology/"
            "software-security-guidance/processors-affected-consolidated-product-"
            "cpu-model.html"
        ),
        "used_for": "Arrow Lake H microarchitecture cross-check",
    },
    {
        "title": "GCC 13 release changes",
        "url": "https://gcc.gnu.org/gcc-13/changes.html",
        "used_for": "GCC 13 Raptor Lake and Meteor Lake support scope",
    },
    {
        "title": "GCC 13.3 x86 options",
        "url": "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/x86-Options.html",
        "used_for": "-march versus -mtune semantics",
    },
    {
        "title": "GCC patch archive: Arrow Lake target definitions",
        "url": "https://gcc.gnu.org/pipermail/gcc-patches/2023-August/628312.html",
        "used_for": "later Arrow Lake/Arrow Lake-S/Lunar Lake target relationships",
    },
    {
        "title": "LLVM current X86 target parser",
        "url": (
            "https://github.com/llvm/llvm-project/blob/main/llvm/include/llvm/"
            "TargetParser/X86TargetParser.def"
        ),
        "used_for": "current Arrow Lake family CPU names and aliases",
    },
    {
        "title": "LLVM 16 X86 target parser",
        "url": (
            "https://github.com/llvm/llvm-project/blob/release/16.x/llvm/include/"
            "llvm/TargetParser/X86TargetParser.def"
        ),
        "used_for": "LLVM 16 predates Arrow Lake CPU names",
    },
    {
        "title": "LLVM llvm-mca command guide",
        "url": "https://llvm.org/docs/CommandGuide/llvm-mca.html",
        "used_for": (
            "model-quality caveat and absence of fetch, decode, and branch "
            "prediction modeling"
        ),
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
    return "\n".join(normalized.strip().splitlines()[-4:])


def compact_probe_diagnostic(text: str, temporary: Path) -> str:
    normalized = normalize_diagnostic(text, temporary)
    lines = normalized.splitlines()
    selected = next((line for line in lines if "error:" in line), "")
    if not selected and lines:
        selected = lines[0]
    return selected[:240]


def build_gcc_manifest() -> dict[str, dict[str, Any]]:
    variants: dict[str, dict[str, Any]] = {}

    def add(
        name: str,
        *cflags: str,
        ldflags: tuple[str, ...] = (),
        group: str = "followup",
    ) -> None:
        if name in variants:
            raise RuntimeError(f"duplicate GCC candidate: {name}")
        variants[name] = {
            "cflags": list(cflags),
            "ldflags": list(ldflags),
            "source": SOURCE_RELATIVE,
            "group": group,
        }

    add("ref_ira", group="reference_only")
    add("ref_no_sched2", "-fno-schedule-insns2", group="reference_only")
    add("ref_selective2", "-fselective-scheduling2", group="reference_only")

    for name, flags in {
        "no_sched2_align64": ["-fno-schedule-insns2", "-falign-loops=64"],
        "no_sched2_align128": ["-fno-schedule-insns2", "-falign-loops=128"],
        "no_sched2_lto": ["-fno-schedule-insns2", "-flto"],
        "no_sched2_lto_align64": [
            "-fno-schedule-insns2",
            "-flto",
            "-falign-loops=64",
        ],
        "no_sched2_no_critical": [
            "-fno-schedule-insns2",
            "-fno-sched-critical-path-heuristic",
        ],
        "no_sched2_selective2": [
            "-fno-schedule-insns2",
            "-fselective-scheduling2",
        ],
        "no_sched2_rename": ["-fno-schedule-insns2", "-frename-registers"],
        "no_sched2_ira_all": ["-fno-schedule-insns2", "-fira-region=all"],
        "no_sched2_ira_mixed": ["-fno-schedule-insns2", "-fira-region=mixed"],
        "no_sched2_ira_all_pressure": [
            "-fno-schedule-insns2",
            "-fira-region=all",
            "-fira-loop-pressure",
        ],
        "no_sched2_whole_program": ["-fno-schedule-insns2", "-fwhole-program"],
        "no_sched2_no_plt": ["-fno-schedule-insns2", "-fno-plt"],
        "no_sched2_reorder_simple": [
            "-fno-schedule-insns2",
            "-freorder-blocks-algorithm=simple",
        ],
        "no_sched2_function64": [
            "-fno-schedule-insns2",
            "-falign-functions=64",
        ],
        "selective2_align32": ["-fselective-scheduling2", "-falign-loops=32"],
        "selective2_align64": ["-fselective-scheduling2", "-falign-loops=64"],
        "selective2_lto": ["-fselective-scheduling2", "-flto"],
        "selective2_rename": ["-fselective-scheduling2", "-frename-registers"],
        "selective2_ira_all": ["-fselective-scheduling2", "-fira-region=all"],
        "selective2_no_critical": [
            "-fselective-scheduling2",
            "-fno-sched-critical-path-heuristic",
        ],
        "selective2_function64": [
            "-fselective-scheduling2",
            "-falign-functions=64",
        ],
        "critical_align64": [
            "-fno-sched-critical-path-heuristic",
            "-falign-loops=64",
        ],
    }.items():
        add(name, *flags)

    add(
        "no_sched2_gc",
        "-fno-schedule-insns2",
        "-ffunction-sections",
        "-fdata-sections",
        ldflags=("-Wl,--gc-sections",),
    )
    add(
        "no_sched2_gc_sort_name",
        "-fno-schedule-insns2",
        "-ffunction-sections",
        "-fdata-sections",
        ldflags=("-Wl,--gc-sections", "-Wl,--sort-section=name"),
    )
    add(
        "selective2_gc",
        "-fselective-scheduling2",
        "-ffunction-sections",
        "-fdata-sections",
        ldflags=("-Wl,--gc-sections",),
    )

    for cpu in (
        "raptorlake",
        "meteorlake",
        "gracemont",
        "tremont",
        "sierraforest",
        "grandridge",
        "graniterapids",
        "sapphirerapids",
        "rocketlake",
        "icelake-client",
    ):
        add(
            "no_sched2_tune_" + cpu.replace("-", "_"),
            "-fno-schedule-insns2",
            f"-mtune={cpu}",
            group="target_proxy",
        )
    for cpu in ("meteorlake", "gracemont", "tremont", "graniterapids"):
        add(
            "selective2_tune_" + cpu.replace("-", "_"),
            "-fselective-scheduling2",
            f"-mtune={cpu}",
            group="target_proxy",
        )
    for cpu in ("alderlake", "meteorlake", "x86-64-v3"):
        add(
            "no_sched2_march_" + cpu.replace("-", "_"),
            "-fno-schedule-insns2",
            f"-march={cpu}",
            group="target_proxy",
        )
    add(
        "no_sched2_march_meteor_tune_meteor",
        "-fno-schedule-insns2",
        "-march=meteorlake",
        "-mtune=meteorlake",
        group="target_proxy",
    )
    add(
        "selective2_march_meteor",
        "-fselective-scheduling2",
        "-march=meteorlake",
        group="target_proxy",
    )
    return variants


def build_clang_manifest() -> dict[str, dict[str, Any]]:
    variants: dict[str, dict[str, Any]] = {}

    def add(name: str, *flags: str, group: str = "target_codegen") -> None:
        if name in variants:
            raise RuntimeError(f"duplicate Clang candidate: {name}")
        variants[name] = {"flags": list(flags), "group": group}

    add("clang_ref_bmi2", group="reference_only")
    for cpu in TARGET_CPUS:
        suffix = cpu.replace("-", "_")
        add(f"clang_tune_{suffix}", f"-mtune={cpu}")
        add(f"clang_march_{suffix}", f"-march={cpu}")

    for name, cpu in (
        ("clang_arrow_align64", "arrowlake"),
        ("clang_arrow_s_align64", "arrowlake-s"),
        ("clang_lunar_align64", "lunarlake"),
        ("clang_panther_align64", "pantherlake"),
    ):
        add(name, f"-march={cpu}", "-falign-loops=64", group="layout")

    add(
        "clang_arrow_regalloc_basic",
        "-march=arrowlake",
        "-mllvm",
        "-regalloc=basic",
        group="register_allocation_internal",
    )
    add(
        "clang_arrow_regalloc_pbqp",
        "-march=arrowlake",
        "-mllvm",
        "-regalloc=pbqp",
        group="register_allocation_internal",
    )
    add(
        "clang_arrow_regalloc_fast",
        "-march=arrowlake",
        "-mllvm",
        "-regalloc=fast",
        group="register_allocation_internal",
    )
    add(
        "clang_arrow_greedy_reverse",
        "-march=arrowlake",
        "-mllvm",
        "-greedy-reverse-local-assignment",
        group="register_allocation_internal",
    )

    add(
        "clang_arrow_no_misched",
        "-march=arrowlake",
        "-mllvm",
        "-enable-misched=false",
        group="scheduler_internal",
    )
    add(
        "clang_arrow_no_post_misched",
        "-march=arrowlake",
        "-mllvm",
        "-enable-post-misched=false",
        group="scheduler_internal",
    )
    for policy in ("ilpmax", "converge", "ilpmin"):
        add(
            f"clang_arrow_misched_{policy}",
            "-march=arrowlake",
            "-mllvm",
            f"-misched={policy}",
            group="scheduler_internal",
        )

    for cpu in ("alderlake", "meteorlake", "arrowlake-s", "lunarlake", "pantherlake"):
        add(
            "clang_" + cpu.replace("-", "_") + "_misched_ilpmax",
            f"-march={cpu}",
            "-mllvm",
            "-misched=ilpmax",
            group="target_scheduler_cross_internal",
        )
    add(
        "clang_tune_arrow_misched_ilpmax",
        "-mtune=arrowlake",
        "-mllvm",
        "-misched=ilpmax",
        group="target_scheduler_cross_internal",
    )

    for alignment in (32, 64, 128):
        add(
            f"clang_arrow_misched_ilpmax_align{alignment}",
            "-march=arrowlake",
            f"-falign-loops={alignment}",
            "-mllvm",
            "-misched=ilpmax",
            group="layout_scheduler_cross_internal",
        )

    add(
        "clang_arrow_ilpmax_no_post",
        "-march=arrowlake",
        "-mllvm",
        "-misched=ilpmax",
        "-mllvm",
        "-enable-post-misched=false",
        group="scheduler_internal",
    )
    for allocator in ("basic", "pbqp"):
        add(
            f"clang_arrow_ilpmax_regalloc_{allocator}",
            "-march=arrowlake",
            "-mllvm",
            "-misched=ilpmax",
            "-mllvm",
            f"-regalloc={allocator}",
            group="scheduler_register_cross_internal",
        )
    add(
        "clang_arrow_ilpmax_greedy_reverse",
        "-march=arrowlake",
        "-mllvm",
        "-misched=ilpmax",
        "-mllvm",
        "-greedy-reverse-local-assignment",
        group="scheduler_register_cross_internal",
    )
    for direction in ("topdown", "bottomup", "bidirectional"):
        add(
            f"clang_arrow_ilpmax_prera_{direction}",
            "-march=arrowlake",
            "-mllvm",
            "-misched=ilpmax",
            "-mllvm",
            f"-misched-prera-direction={direction}",
            group="scheduler_direction_internal",
        )
        add(
            f"clang_arrow_ilpmax_postra_{direction}",
            "-march=arrowlake",
            "-mllvm",
            "-misched=ilpmax",
            "-mllvm",
            f"-misched-postra-direction={direction}",
            group="scheduler_direction_internal",
        )
    for name, option in (
        ("no_regpressure", "-misched-regpressure=false"),
        ("no_cluster", "-misched-cluster=false"),
        ("no_fusion", "-misched-fusion=false"),
    ):
        add(
            f"clang_arrow_ilpmax_{name}",
            "-march=arrowlake",
            "-mllvm",
            "-misched=ilpmax",
            "-mllvm",
            option,
            group="scheduler_internal",
        )

    add(
        "clang_arrow_ilpmax_lto",
        "-march=arrowlake",
        "-flto",
        "-mllvm",
        "-misched=ilpmax",
        group="function_placement",
    )
    add(
        "clang_arrow_ilpmax_function64",
        "-march=arrowlake",
        "-falign-functions=64",
        "-mllvm",
        "-misched=ilpmax",
        group="function_placement",
    )
    add(
        "clang_arrow_ilpmax_sections",
        "-march=arrowlake",
        "-ffunction-sections",
        "-fdata-sections",
        "-Wl,--gc-sections",
        "-mllvm",
        "-misched=ilpmax",
        group="function_placement",
    )
    return variants


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
            r"^\s*([0-9a-fA-F]+):\s+([^\s]+)(?:\s+(.*?))?\s*$",
            line,
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
    indices = {
        address: index for index, (address, _, _) in enumerate(instructions)
    }
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


def analyse_loop(llvm_mca: Path, loop: Path) -> dict[str, dict[str, float | int]]:
    results: dict[str, dict[str, float | int]] = {}
    for label, model in MCA_MODELS.items():
        output = run(
            [
                str(llvm_mca),
                f"-mcpu={model}",
                f"-iterations={MCA_ITERATIONS}",
                str(loop),
            ]
        ).stdout
        cycles = int(extract_number(output, "Total Cycles"))
        instructions = int(extract_number(output, "Instructions"))
        results[label] = {
            "model": model,
            "iterations": MCA_ITERATIONS,
            "cycles_per_iteration": cycles / MCA_ITERATIONS,
            "instructions_per_iteration": instructions / MCA_ITERATIONS,
            "block_rthroughput": extract_number(output, "Block RThroughput"),
        }
    return results


def compact_audit(audit: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "binary_sha256",
        "text_bytes",
        "loop_start",
        "loop_start_mod_64",
        "loop_bytes",
        "loop_instructions",
        "calls",
        "push_pop",
        "memory_operands_excluding_lea",
        "core_counts",
        "normalized_loop_sha256",
    )
    return {key: audit[key] for key in keys}


def compile_gcc_screen(
    runtime: str,
    temporary: Path,
    variants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    (temporary / "manifest.json").write_text(
        json.dumps({"base_flags": GCC_BASE_FLAGS, "variants": variants})
    )
    command = [
        runtime,
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{ROOT}:/workspace:ro",
        "--volume",
        f"{temporary}:/output",
        "--workdir",
        "/output",
        schedule.IMAGE,
        "python3",
        "-c",
        layout.CONTAINER_DRIVER,
    ]
    run(command)
    return json.loads((temporary / "compiled.json").read_text())


def compile_clang_screen(
    clang: Path,
    ld: Path,
    objdump: Path,
    size_tool: Path,
    temporary: Path,
    variants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    base_flags = [*CLANG_BASE_FLAGS, f"--ld-path={ld}"]
    for index, (name, item) in enumerate(variants.items(), 1):
        if index == 1 or index % 10 == 0 or index == len(variants):
            print(f"clang static screen {index}/{len(variants)}", flush=True)
        binary = temporary / f"{name}.bin"
        command = [
            str(clang),
            *base_flags,
            *item["flags"],
            str(SOURCE),
            "-o",
            str(binary),
        ]
        completed = run(command, check=False)
        common = {"flags": item["flags"], "group": item["group"]}
        if completed.returncode:
            results[name] = {
                **common,
                "status": "COMPILE_FAIL",
                "diagnostic": normalize_diagnostic(completed.stderr, temporary),
            }
            continue
        audit = audit_main_timing_loop(
            binary,
            objdump=str(objdump),
            size_tool=str(size_tool),
        )
        errors = validate_loop_audit(audit, "full-inline-320")
        loop = temporary / f"{name}.loop.s"
        extract_loop(binary, loop, objdump)
        results[name] = {
            **common,
            "status": "PASS" if not errors else "AUDIT_FAIL",
            "audit": audit,
            "audit_errors": errors,
            "loop_artifact": loop.name,
        }
    return results


def target_probes(
    compiler: str,
    temporary: Path,
) -> dict[str, dict[str, dict[str, Any]]]:
    source = temporary / "target_probe.c"
    source.write_text("int target_probe;\n")
    results: dict[str, dict[str, dict[str, Any]]] = {}
    for kind in ("march", "mtune"):
        results[kind] = {}
        for cpu in TARGET_CPUS:
            output = temporary / f"probe-{kind}-{cpu}.o"
            completed = run(
                [
                    compiler,
                    f"-{kind}={cpu}",
                    "-c",
                    str(source),
                    "-o",
                    str(output),
                ],
                check=False,
            )
            results[kind][cpu] = {
                "accepted": completed.returncode == 0,
                "diagnostic": (
                    ""
                    if completed.returncode == 0
                    else compact_probe_diagnostic(completed.stderr, temporary)
                ),
            }
    return results


def parse_verifier_output(stdout: str, random_cases: int) -> dict[str, Any]:
    expected = (
        f"candidate_random_differential_cases={random_cases}\n"
        "candidate_random_seed=0x243f6a8885a308d3\n"
        "candidate_random_state_and_constants=PASS\n"
        "candidate_round_counts=1,20\n"
        "candidate_differential=PASS\n"
    )
    if stdout != expected:
        raise RuntimeError(f"unexpected verifier output:\n{stdout}")
    fields = dict(line.split("=", 1) for line in stdout.splitlines())
    return {
        "status": fields["candidate_differential"],
        "random_cases": int(fields["candidate_random_differential_cases"]),
        "seed": fields["candidate_random_seed"],
        "random_state_and_constants": (
            fields["candidate_random_state_and_constants"] == "PASS"
        ),
        "round_counts": [
            int(value) for value in fields["candidate_round_counts"].split(",")
        ],
    }


def verify_without_timing(
    compiler: str,
    base_flags: list[str],
    cases: dict[str, list[str]],
    objdump: str,
    size_tool: str,
    random_cases: int,
) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="challenge02-static-verify-") as name:
        temporary = Path(name)
        with ZipFile(ARCHIVE) as zipped:
            (temporary / "testvector.txt").write_bytes(
                zipped.read("code/testvector.txt")
            )
            (temporary / "testvector_20round.txt").write_bytes(
                zipped.read("code/testvector_20round.txt")
            )
        source_text = SOURCE.read_text()
        validation_text, replacements = re.subn(
            r"const int iterations = [0-9]+;",
            "const int iterations = 1;",
            source_text,
        )
        if replacements != 1:
            raise RuntimeError(f"expected one timing trip-count declaration, got {replacements}")
        validation_source = temporary / "vector_validation.c"
        validation_source.write_text(validation_text)

        verifier_object = temporary / "verifier.o"
        run(
            [
                compiler,
                "-O3",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Wpedantic",
                "-Werror",
                "-c",
                str(VERIFIER),
                "-o",
                str(verifier_object),
            ]
        )
        for case, flags in cases.items():
            effective = [*base_flags, *flags]
            compile_effective = [
                flag for flag in effective if not flag.startswith("--ld-path=")
            ]
            link_only_flags = [
                flag for flag in effective if flag.startswith("--ld-path=")
            ]
            candidate_object = temporary / f"{case}.o"
            run(
                [
                    compiler,
                    *compile_effective,
                    "-Dmain=challenge02_contest_main",
                    "-c",
                    str(SOURCE),
                    "-o",
                    str(candidate_object),
                ]
            )
            verifier_binary = temporary / f"{case}.verifier"
            run(
                [
                    compiler,
                    *link_only_flags,
                    str(verifier_object),
                    str(candidate_object),
                    "-o",
                    str(verifier_binary),
                ]
            )
            verified = run([str(verifier_binary), str(random_cases)])
            if verified.stderr:
                raise RuntimeError(f"{case}: verifier wrote stderr: {verified.stderr}")

            audit_binary = temporary / f"{case}.audit"
            run([compiler, *effective, str(SOURCE), "-o", str(audit_binary)])
            audit = audit_main_timing_loop(
                audit_binary,
                objdump=objdump,
                size_tool=size_tool,
            )
            errors = validate_loop_audit(audit, "full-inline-320")
            if errors:
                raise RuntimeError(f"{case}: full-inline audit failed: {'; '.join(errors)}")

            vector_binary = temporary / f"{case}.vectors"
            run(
                [
                    compiler,
                    *effective,
                    str(validation_source),
                    "-o",
                    str(vector_binary),
                ]
            )
            vector_run = run([str(vector_binary)], cwd=temporary)
            official_vectors = (
                "one-round testvector verification: OK (1000 pairs checked)"
                in vector_run.stdout
                and "20-round testvector verification: OK" in vector_run.stdout
            )
            if not official_vectors or vector_run.stderr:
                raise RuntimeError(f"{case}: official-vector validation failed")
            results[case] = {
                "flags": flags,
                "candidate_random_differential": parse_verifier_output(
                    verified.stdout, random_cases
                ),
                "full_inline_audit": compact_audit(audit),
                "official_vectors": {
                    "one_round_pairs": 1000,
                    "twenty_round_vector": "PASS",
                    "status": "PASS",
                },
                "validation_timing_loop_iterations": 1,
                "timing_samples_collected": 0,
            }
    return results


def run_container_gcc_evidence(output: Path, random_cases: int) -> None:
    with tempfile.TemporaryDirectory(prefix="challenge02-gcc-probes-") as name:
        probes = target_probes("gcc", Path(name))
    verification = verify_without_timing(
        "gcc",
        GCC_BASE_FLAGS,
        GCC_VERIFICATION_CASES,
        "objdump",
        "size",
        random_cases,
    )
    payload = {
        "compiler": run(["gcc", "--version"]).stdout.splitlines()[0],
        "binutils": run(["ld", "--version"]).stdout.splitlines()[0],
        "target_probes": probes,
        "verification": verification,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def run_gcc_evidence_container(
    runtime: str,
    temporary: Path,
    random_cases: int,
) -> dict[str, Any]:
    output = temporary / "gcc-evidence.json"
    command = [
        runtime,
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{ROOT}:/workspace:ro",
        "--volume",
        f"{temporary}:/output",
        "--workdir",
        "/workspace",
        schedule.IMAGE,
        "python3",
        "solutions/02_optimization/screen_255h_toolchains_02.py",
        "--container-gcc-evidence",
        "/output/gcc-evidence.json",
        "--random-cases",
        str(random_cases),
    ]
    run(command)
    return json.loads(output.read_text())


def compact_screen(
    family: str,
    results: dict[str, Any],
    temporary: Path,
    llvm_mca: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    representatives: dict[str, str] = {}
    members: dict[str, list[str]] = defaultdict(list)
    for candidate, result in results.items():
        if result["status"] != "PASS":
            continue
        loop_hash = result["audit"]["normalized_loop_sha256"]
        representatives.setdefault(loop_hash, candidate)
        members[loop_hash].append(candidate)

    stream_metrics: dict[str, Any] = {}
    for loop_hash, representative in representatives.items():
        loop = temporary / results[representative]["loop_artifact"]
        stream_metrics[loop_hash] = analyse_loop(llvm_mca, loop)

    compact: dict[str, Any] = {}
    for candidate, result in results.items():
        flags = result.get("flags", result.get("cflags", []))
        item = {
            "group": result["group"],
            "flags": flags,
            "status": result["status"],
        }
        if result.get("ldflags"):
            item["ldflags"] = result["ldflags"]
        if result["status"] in {"PASS", "AUDIT_FAIL"}:
            audit = result["audit"]
            item["loop"] = {
                "normalized_sha256": audit["normalized_loop_sha256"],
                "start_mod_64": audit["loop_start_mod_64"],
                "bytes": audit["loop_bytes"],
                "instructions": audit["loop_instructions"],
                "calls": audit["calls"],
                "memory_operands_excluding_lea": audit[
                    "memory_operands_excluding_lea"
                ],
            }
            if result.get("audit_errors"):
                item["audit_errors"] = result["audit_errors"]
        if result["status"] == "PASS":
            item["static_model_key"] = result["audit"]["normalized_loop_sha256"]
        if result.get("diagnostic"):
            item["diagnostic"] = result["diagnostic"]
        compact[candidate] = item

    streams = {
        loop_hash: {
            "family": family,
            "representative": representatives[loop_hash],
            "members": sorted(members[loop_hash]),
            "audit": compact_audit(results[representatives[loop_hash]]["audit"]),
            "llvm_mca_16_proxies": stream_metrics[loop_hash],
        }
        for loop_hash in sorted(representatives)
    }
    return compact, streams


def cpu_help(llvm_mca: Path) -> dict[str, Any]:
    completed = run([str(llvm_mca), "-mcpu=help"], check=False)
    output = completed.stdout + completed.stderr
    return {
        cpu: bool(re.search(rf"^\s*{re.escape(cpu)}\s+-", output, re.MULTILINE))
        for cpu in (*TARGET_CPUS, "tremont")
    }


def assert_inputs() -> None:
    for relative, expected in INPUT_HASHES.items():
        actual = sha256(ROOT / relative)
        if actual != expected:
            raise RuntimeError(
                f"input hash mismatch for {relative}: expected {expected}, got {actual}"
            )


def assert_tool(
    label: str,
    path: Path,
) -> dict[str, str]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise RuntimeError(f"{label} does not exist: {resolved}")
    actual = sha256(resolved)
    expected = PINNED_TOOL_HASHES[label]
    if actual != expected:
        raise RuntimeError(
            f"{label} hash mismatch: expected {expected}, got {actual} ({resolved})"
        )
    version_flag = "--version"
    version = run([str(resolved), version_flag]).stdout.splitlines()[0]
    return {"path": str(resolved), "sha256": actual, "version": version}


def cycles(streams: dict[str, Any], candidate: dict[str, Any]) -> float:
    key = candidate["static_model_key"]
    return streams[key]["llvm_mca_16_proxies"]["p_core_proxy_alderlake"][
        "cycles_per_iteration"
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--clang", type=Path, default=DEFAULT_CLANG)
    parser.add_argument("--ld", type=Path, default=DEFAULT_LD)
    parser.add_argument("--objdump", type=Path, default=DEFAULT_OBJDUMP)
    parser.add_argument("--size-tool", type=Path, default=DEFAULT_SIZE)
    parser.add_argument("--llvm-mca", type=Path, default=DEFAULT_LLVM_MCA)
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(__file__).with_name("255h_toolchain_screen_02.json"),
    )
    parser.add_argument(
        "--container-gcc-evidence",
        type=Path,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.random_cases <= 0:
        parser.error("--random-cases must be positive")
    if args.container_gcc_evidence is not None:
        run_container_gcc_evidence(args.container_gcc_evidence, args.random_cases)
        return

    assert_inputs()
    tools = {
        "clang": assert_tool("clang", args.clang),
        "ld": assert_tool("ld", args.ld),
        "objdump": assert_tool("objdump", args.objdump),
        "size": assert_tool("size", args.size_tool),
        "llvm_mca": assert_tool("llvm_mca", args.llvm_mca),
    }
    clang = Path(tools["clang"]["path"])
    ld = Path(tools["ld"]["path"])
    objdump = Path(tools["objdump"]["path"])
    size_tool = Path(tools["size"]["path"])
    llvm_mca = Path(tools["llvm_mca"]["path"])

    gcc_manifest = build_gcc_manifest()
    clang_manifest = build_clang_manifest()
    with tempfile.TemporaryDirectory(prefix="challenge02-255h-screen-") as name:
        temporary = Path(name).resolve()
        gcc_dir = temporary / "gcc"
        clang_dir = temporary / "clang"
        gcc_evidence_dir = temporary / "gcc-evidence"
        gcc_dir.mkdir()
        clang_dir.mkdir()
        gcc_evidence_dir.mkdir()

        print(f"GCC static screen: {len(gcc_manifest)} candidates", flush=True)
        gcc_compiled = compile_gcc_screen(args.runtime, gcc_dir, gcc_manifest)
        print(f"Clang static screen: {len(clang_manifest)} candidates", flush=True)
        clang_results = compile_clang_screen(
            clang,
            ld,
            objdump,
            size_tool,
            clang_dir,
            clang_manifest,
        )

        gcc_screen, gcc_streams = compact_screen(
            "gcc13.3", gcc_compiled["variants"], gcc_dir, llvm_mca
        )
        clang_screen, clang_streams = compact_screen(
            "clang21", clang_results, clang_dir, llvm_mca
        )

        print("GCC target probes and no-timing correctness gates", flush=True)
        gcc_evidence = run_gcc_evidence_container(
            args.runtime, gcc_evidence_dir, args.random_cases
        )
        print("Clang target probes and no-timing correctness gates", flush=True)
        clang_probes = target_probes(str(clang), clang_dir)
        clang_verification = verify_without_timing(
            str(clang),
            [*CLANG_BASE_FLAGS, f"--ld-path={ld}"],
            CLANG_VERIFICATION_CASES,
            str(objdump),
            str(size_tool),
            args.random_cases,
        )

        all_streams = {**gcc_streams, **clang_streams}
        if len(all_streams) != len(gcc_streams) + len(clang_streams):
            raise RuntimeError("GCC and Clang unexpectedly produced a shared loop hash")

        expected_gcc_hashes = {
            "ref_ira": "e0e62e1b598890734db04f0983d66c6121a8fb8b4d12cc456f15b7d5c0740d52",
            "ref_no_sched2": "76e114da82da8a44cae3c5b11e0851263a0ba222e6816a2ef352a729bc44502e",
            "ref_selective2": "c097e02f5e4eefb00aa802ce9a29ecb4210eb16a38bb5880ce1b9ea48d2f56d3",
            "no_sched2_tune_graniterapids": (
                "29b8f267fa8436ccfcccaecfa95eb8556cb93d15288bfdd8f1e7d81090ccd4d9"
            ),
            "selective2_tune_graniterapids": (
                "91f4aab962f8f436480d52e8b8b5096a90913873b19aca747bc447bb79da39cd"
            ),
        }
        expected_clang_hashes = {
            "clang_arrow_misched_ilpmax": (
                "0b44d9df1677c73a419a2eafdeaf93b904907ddcaeb1729ef009c5f5bf37685e"
            ),
            "clang_arrow_misched_ilpmin": (
                "dcaaeed0f6fb137f45e6349291a164d6d321d441e3821f7bd0c78cbf09f48d9c"
            ),
        }

        gcc_statuses = Counter(item["status"] for item in gcc_screen.values())
        clang_statuses = Counter(item["status"] for item in clang_screen.values())
        gcc_probe_expectation = {
            cpu: cpu in {"alderlake", "raptorlake", "meteorlake"}
            for cpu in TARGET_CPUS
        }
        checks = {
            "source_and_harness_hashes_match": all(
                sha256(ROOT / relative) == expected
                for relative, expected in INPUT_HASHES.items()
            ),
            "gcc_is_exact_13_3_0": gcc_compiled["compiler"] == "gcc (GCC) 13.3.0",
            "gcc_image_is_digest_pinned": schedule.IMAGE.startswith("gcc@sha256:"),
            "all_gcc_candidates_pass_full_inline_audit": gcc_statuses == {"PASS": len(gcc_screen)},
            "clang_expected_status_partition": clang_statuses
            == {"AUDIT_FAIL": 26, "PASS": 26, "COMPILE_FAIL": 1},
            "gcc_reference_and_new_hashes_reproduce": all(
                gcc_screen[candidate]["loop"]["normalized_sha256"] == expected
                for candidate, expected in expected_gcc_hashes.items()
            ),
            "clang_internal_scheduler_hashes_reproduce": all(
                clang_screen[candidate]["loop"]["normalized_sha256"] == expected
                for candidate, expected in expected_clang_hashes.items()
            ),
            "gcc13_target_support_matches_probe_expectation": all(
                gcc_evidence["target_probes"][kind][cpu]["accepted"]
                == gcc_probe_expectation[cpu]
                for kind in ("march", "mtune")
                for cpu in TARGET_CPUS
            ),
            "clang21_accepts_all_probed_target_names": all(
                clang_probes[kind][cpu]["accepted"]
                for kind in ("march", "mtune")
                for cpu in TARGET_CPUS
            ),
            "gcc_verification_shortlist_passes": all(
                item["candidate_random_differential"]["status"] == "PASS"
                and item["official_vectors"]["status"] == "PASS"
                for item in gcc_evidence["verification"].values()
            ),
            "clang_verification_shortlist_passes": all(
                item["candidate_random_differential"]["status"] == "PASS"
                and item["official_vectors"]["status"] == "PASS"
                for item in clang_verification.values()
            ),
            "no_host_timing_samples_collected": all(
                item["timing_samples_collected"] == 0
                for family in (gcc_evidence["verification"], clang_verification)
                for item in family.values()
            ),
            "gcc_new_combinations_do_not_beat_existing_static_best": min(
                cycles(gcc_streams, item)
                for item in gcc_screen.values()
                if item["status"] == "PASS" and item["group"] != "reference_only"
            )
            >= 120.06,
            "clang_audited_streams_do_not_beat_existing_static_best": min(
                cycles(clang_streams, item)
                for item in clang_screen.values()
                if item["status"] == "PASS"
            )
            >= 120.06,
        }
        if not all(checks.values()):
            raise RuntimeError(
                "255H follow-up checks failed: "
                + ", ".join(key for key, value in checks.items() if not value)
            )

        mca_support = cpu_help(llvm_mca)
        payload = {
            "schema_version": 1,
            "experiment": "challenge02_core_ultra_7_255h_toolchain_static_followup",
            "scope": {
                "result_kind": "static_screen_only",
                "actual_255h_measurements": 0,
                "host_timing_samples_collected": 0,
                "source": SOURCE_RELATIVE,
                "source_sha256": SOURCE_SHA256,
            },
            "target": {
                "processor": "Intel Core Ultra 7 255H",
                "family": "Arrow Lake H / Core Ultra Series 2",
                "cores": {"lion_cove_p": 6, "skymont_e": 8, "crestmont_lp_e": 2},
                "threads": 16,
                "required_target_measurement": (
                    "pin separate repeated campaigns to a verified Lion Cove P-core "
                    "and Skymont E-core on the actual 255H"
                ),
            },
            "toolchains": {
                "gcc": {
                    "image": schedule.IMAGE,
                    "compiler": gcc_compiled["compiler"],
                    "binutils": gcc_compiled["binutils"],
                    "base_flags": GCC_BASE_FLAGS,
                },
                "clang": {
                    **tools["clang"],
                    "provenance_note": (
                        "Swift toolchain build at the recorded llvm-project commit; "
                        "the executable hash, not a release label, is authoritative"
                    ),
                    "base_flags": [*CLANG_BASE_FLAGS, f"--ld-path={ld}"],
                    "internal_flag_warning": (
                        "all -mllvm scheduling/register-allocation flags are hidden "
                        "implementation details and may change without compatibility"
                    ),
                },
                "host_static_tools": {
                    "ld": tools["ld"],
                    "objdump": tools["objdump"],
                    "size": tools["size"],
                    "llvm_mca": tools["llvm_mca"],
                },
            },
            "target_name_probes": {
                "gcc13_3": gcc_evidence["target_probes"],
                "clang21": clang_probes,
                "llvm_mca16_mcpu_help": mca_support,
            },
            "summary": {
                "gcc_candidates": len(gcc_screen),
                "gcc_reference_controls": sum(
                    item["group"] == "reference_only" for item in gcc_screen.values()
                ),
                "gcc_unique_audited_streams": len(gcc_streams),
                "gcc_statuses": dict(sorted(gcc_statuses.items())),
                "clang_candidates": len(clang_screen),
                "clang_unique_audited_streams": len(clang_streams),
                "clang_statuses": dict(sorted(clang_statuses.items())),
                "existing_gcc_selective2_alder_proxy_cycles": 120.06,
                "new_gcc_graniterapids_streams": {
                    "selective2": {
                        "loop_bytes": gcc_screen["selective2_tune_graniterapids"]["loop"]["bytes"],
                        "alder_proxy_cycles": cycles(
                            gcc_streams, gcc_screen["selective2_tune_graniterapids"]
                        ),
                    },
                    "no_sched2": {
                        "loop_bytes": gcc_screen["no_sched2_tune_graniterapids"]["loop"]["bytes"],
                        "alder_proxy_cycles": cycles(
                            gcc_streams, gcc_screen["no_sched2_tune_graniterapids"]
                        ),
                    },
                },
                "clang_arrow_internal_scheduler": {
                    "ilpmax_loop_bytes": clang_screen["clang_arrow_misched_ilpmax"]["loop"]["bytes"],
                    "ilpmax_alder_proxy_cycles": cycles(
                        clang_streams, clang_screen["clang_arrow_misched_ilpmax"]
                    ),
                    "ilpmin_loop_bytes": clang_screen["clang_arrow_misched_ilpmin"]["loop"]["bytes"],
                    "ilpmin_alder_proxy_cycles": cycles(
                        clang_streams, clang_screen["clang_arrow_misched_ilpmin"]
                    ),
                },
                "promotion": "none from static evidence",
            },
            "checks": checks,
            "all_checks_passed": all(checks.values()),
            "verification_shortlist": {
                "gcc13_3": gcc_evidence["verification"],
                "clang21": clang_verification,
            },
            "unique_streams": all_streams,
            "gcc_screen": gcc_screen,
            "clang_screen": clang_screen,
            "model_limitations": [
                (
                    "GCC 13.3 rejects arrowlake, arrowlake-s, lunarlake, and "
                    "pantherlake in the exact probes; Alder/Meteor/E-core-like names "
                    "are only proxies for this 255H."
                ),
                (
                    "llvm-mca 16 has no Lion Cove, Skymont, or Arrow Lake model here; "
                    "Alder Lake and Tremont results are directional proxies only."
                ),
                (
                    "llvm-mca assumes decoded instructions are already queued and "
                    "does not model fetch, decode, or branch prediction, so loop and "
                    "function alignment cannot be ranked by these cycle estimates."
                ),
                (
                    "The Clang ilpmax/ilpmin/regalloc switches are hidden -mllvm "
                    "options. Their output is reproducible for the pinned executable "
                    "but is not a stable compiler interface."
                ),
                (
                    "No result in this file is an actual Core Ultra 7 255H timing. "
                    "Promotion requires repeated, core-type-pinned target data."
                ),
            ],
            "decision": {
                "submission_change": "none",
                "reason": (
                    "No new GCC combination beats the existing 120.06-cycle Alder "
                    "proxy. Clang's only compact no-spill internal-scheduler streams "
                    "are 1208 bytes but score 133.79 cycles on that proxy."
                ),
                "target_measurement_candidates": [
                    {
                        "name": "clang_arrow_misched_ilpmax",
                        "why": (
                            "Arrow Lake target accepted, full-inline/no-spill, 1208-byte "
                            "loop; retain only as an experimental negative/control because "
                            "the available proxy is worse"
                        ),
                    },
                    {
                        "name": "gcc_selective2_tune_graniterapids",
                        "why": (
                            "new 1209-byte encoding with unchanged 120.06 proxy; the tune "
                            "model is not 255H, so it needs actual target evidence"
                        ),
                    },
                ],
            },
            "primary_sources": PRIMARY_SOURCES,
        }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    temporary_json = args.json.with_suffix(args.json.suffix + ".tmp")
    temporary_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_json, args.json)
    print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
