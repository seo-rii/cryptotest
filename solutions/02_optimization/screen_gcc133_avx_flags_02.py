#!/usr/bin/env python3
"""Screen additional GCC 13.3 x86/AVX2 backend flags for challenge 2.

This experiment deliberately performs no host timing.  Every candidate is
compiled in the digest-pinned GCC 13.3 image, the complete clock-delimited
loop in the linked contest binary is audited, and that exact loop is sent to
the available Alder Lake and Zen 2 llvm-mca proxy models.  One representative
of every distinct machine-code stream is then checked with the direct 100k
random-state/random-constant differential verifier.

The manifest inventories the earlier AVX2 and 255H screens and rejects an
accidental exact repetition of any non-reference flag tuple from those tools.
The two preferred-vector-width flags previously tried only on the scalar
submission are retained here because this experiment applies them to the
manual four-lane AVX2 source for the first time.
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
from collections import Counter
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "solutions"))

from challenge02_loop_audit import (  # noqa: E402
    audit_main_timing_loop,
    validate_loop_audit,
)


SOURCE_RELATIVE = "solutions/02_optimization/contest_simd_avx2_lanewise.c"
SOURCE = ROOT / SOURCE_RELATIVE
VERIFIER_RELATIVE = "solutions/02_optimization/verify_contest_candidate_02.c"
VERIFIER = ROOT / VERIFIER_RELATIVE
AUDITOR_RELATIVE = "solutions/challenge02_loop_audit.py"

INPUT_HASHES = {
    SOURCE_RELATIVE: "3a8273cb6f381efb30fb4e104a9741acf158307714216f2a2b2d8c1756b9d751",
    VERIFIER_RELATIVE: "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35",
    AUDITOR_RELATIVE: "e73d27abfbb7eea9ee84e0216baaf7f39f128db0cffdcb79b469656f9c185e23",
}

INVENTORY_ARTIFACTS = {
    "prior_avx2_screen": HERE / "avx2_codegen_screen_02.json",
    "prior_255h_screen": HERE / "255h_toolchain_screen_02.json",
    "prior_scalar_layout_screen": HERE / "gcc133_layout_screen_02.json",
}

IMAGE_DIGEST = "1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
IMAGE = f"gcc@sha256:{IMAGE_DIGEST}"
DEFAULT_OBJDUMP = Path("/usr/bin/x86_64-linux-gnu-objdump")
DEFAULT_SIZE = Path("/usr/bin/x86_64-linux-gnu-size")
DEFAULT_LLVM_MCA = Path("/usr/bin/llvm-mca-16")
PINNED_HOST_TOOL_HASHES = {
    "objdump": "19717049e8ecd98cfbb17fd9eb25e9fd896ecec2fc4af6b931f3dd0bc4e903de",
    "size": "d2dc6eb962bfc841403cc8b72191bfd829b50d8796b611689e92cfb051cf10ee",
    "llvm_mca": "e7f38b12a3c228c8b0bcea0bf63cc56939286adf9ae5397a43d408322e3c6fbf",
}

MCA_MODELS = {
    "alderlake_p_core_proxy": "alderlake",
    "znver2_cross_architecture_proxy": "znver2",
}
MCA_ITERATIONS = 100

COMMON_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-mavx2",
    "-DCH2_SIMD_INLINE",
    "-finline-limit=2000",
]
EXPECTED_VERIFIER_STDOUT = """candidate_random_differential_cases=100000
candidate_random_seed=0x243f6a8885a308d3
candidate_random_state_and_constants=PASS
candidate_round_counts=1,20
candidate_differential=PASS
"""

PRIMARY_DOCUMENTATION = [
    {
        "title": "GCC 13.3 x86 options",
        "url": "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/x86-Options.html",
        "used_for": (
            "preferred vector width, AVX256 unaligned split, SSE-to-VEX, "
            "vzeroupper, move/store width, and developer tune controls"
        ),
    },
    {
        "title": "GCC 13.3 optimization options",
        "url": (
            "https://gcc.gnu.org/onlinedocs/gcc-13.3.0/gcc/"
            "Optimize-Options.html"
        ),
        "used_for": "vectorization and OpenMP SIMD cost-model semantics",
    },
    {
        "title": "LLVM llvm-mca command guide",
        "url": "https://llvm.org/docs/CommandGuide/llvm-mca.html",
        "used_for": "static scheduling-model method and limitations",
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


def add_case(
    cases: dict[str, dict[str, Any]],
    name: str,
    *flags: str,
    group: str,
    reference: bool = False,
) -> None:
    if name in cases:
        raise RuntimeError(f"duplicate case name: {name}")
    cases[name] = {
        "flags": list(flags),
        "group": group,
        "reference": reference,
    }


def build_cases() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    add_case(cases, "reference_generic", group="reference", reference=True)
    add_case(
        cases,
        "reference_alderlake",
        "-mtune=alderlake",
        group="reference",
        reference=True,
    )

    for width in ("none", "128", "256", "512"):
        add_case(
            cases,
            f"prefer_width_{width}",
            f"-mprefer-vector-width={width}",
            group="preferred_vector_width",
        )
    add_case(
        cases,
        "prefer_avx128_alias",
        "-mprefer-avx128",
        group="preferred_vector_width",
    )

    for name, flags in {
        "split_load_on": ["-mavx256-split-unaligned-load"],
        "split_load_off": ["-mno-avx256-split-unaligned-load"],
        "split_store_on": ["-mavx256-split-unaligned-store"],
        "split_store_off": ["-mno-avx256-split-unaligned-store"],
        "split_both_on": [
            "-mavx256-split-unaligned-load",
            "-mavx256-split-unaligned-store",
        ],
        "split_both_off": [
            "-mno-avx256-split-unaligned-load",
            "-mno-avx256-split-unaligned-store",
        ],
    }.items():
        add_case(cases, name, *flags, group="avx256_unaligned_split")

    for name, flag in {
        "vzeroupper_on": "-mvzeroupper",
        "vzeroupper_off": "-mno-vzeroupper",
        "sse2avx_on": "-msse2avx",
        "sse2avx_off": "-mno-sse2avx",
    }.items():
        add_case(cases, name, flag, group="x86_encoding_policy")

    for family in ("move", "store"):
        for width in (128, 256, 512):
            add_case(
                cases,
                f"{family}_max_{width}",
                f"-m{family}-max={width}",
                group="move_store_width",
            )
    for width in (128, 256, 512):
        add_case(
            cases,
            f"move_store_max_{width}",
            f"-mmove-max={width}",
            f"-mstore-max={width}",
            group="move_store_width_cross",
        )

    for model in ("unlimited", "dynamic", "cheap", "very-cheap"):
        add_case(
            cases,
            f"vect_cost_{model.replace('-', '_')}",
            f"-fvect-cost-model={model}",
            group="vector_cost_model",
        )
    for model in ("unlimited", "dynamic", "cheap"):
        add_case(
            cases,
            f"simd_cost_{model}",
            f"-fsimd-cost-model={model}",
            group="simd_cost_model",
        )
    for name, flag in {
        "no_tree_vectorize": "-fno-tree-vectorize",
        "no_tree_loop_vectorize": "-fno-tree-loop-vectorize",
        "no_tree_slp_vectorize": "-fno-tree-slp-vectorize",
    }.items():
        add_case(cases, name, flag, group="vector_pass_control")

    # GCC documents -mtune-ctrl as a developer diagnostic knob and warns that
    # it can reach poorly tested compiler paths.  Keep every probe anchored to
    # Alder Lake and verify each distinct output stream dynamically.
    tune_controls = {
        "no_partial_reg_dependency": "^partial_reg_dependency",
        "partial_reg_stall": "partial_reg_stall",
        "no_sse_partial_reg_dependency": "^sse_partial_reg_dependency",
        "sse_split_regs": "sse_split_regs",
        "avx256_split_regs": "avx256_split_regs",
        "avx128_optimal": "avx128_optimal",
        "avx256_optimal": "avx256_optimal",
        "no_avx256_move_by_pieces": "^avx256_move_by_pieces",
        "no_avx256_store_by_pieces": "^avx256_store_by_pieces",
        "no_inter_unit_moves_to_vec": "^inter_unit_moves_to_vec",
        "no_inter_unit_moves_from_vec": "^inter_unit_moves_from_vec",
        "no_emit_vzeroupper": "^emit_vzeroupper",
        "move_m1_via_or": "move_m1_via_or",
        "no_movx": "^movx",
    }
    for name, control in tune_controls.items():
        add_case(
            cases,
            f"alder_tune_{name}",
            "-mtune=alderlake",
            f"-mtune-ctrl={control}",
            group="alderlake_tune_control",
        )
    add_case(
        cases,
        "alder_tune_partial_bundle_off",
        "-mtune=alderlake",
        (
            "-mtune-ctrl=^partial_reg_dependency,"
            "^sse_partial_reg_dependency,^sse_partial_reg_converts_dependency,"
            "^sse_partial_reg_fp_converts_dependency"
        ),
        group="alderlake_tune_control_cross",
    )
    add_case(
        cases,
        "alder_tune_avx256_bundle",
        "-mtune=alderlake",
        (
            "-mtune-ctrl=avx256_optimal,avx256_split_regs,"
            "avx256_move_by_pieces,avx256_store_by_pieces"
        ),
        group="alderlake_tune_control_cross",
    )

    for name, flags in {
        "alder_prefer_width_128": [
            "-mtune=alderlake",
            "-mprefer-vector-width=128",
        ],
        "alder_prefer_width_256": [
            "-mtune=alderlake",
            "-mprefer-vector-width=256",
        ],
        "alder_split_both_on": [
            "-mtune=alderlake",
            "-mavx256-split-unaligned-load",
            "-mavx256-split-unaligned-store",
        ],
        "alder_split_both_off": [
            "-mtune=alderlake",
            "-mno-avx256-split-unaligned-load",
            "-mno-avx256-split-unaligned-store",
        ],
        "alder_sse2avx_on": ["-mtune=alderlake", "-msse2avx"],
        "alder_vzeroupper_off": ["-mtune=alderlake", "-mno-vzeroupper"],
        "alder_move_store_128": [
            "-mtune=alderlake",
            "-mmove-max=128",
            "-mstore-max=128",
        ],
        "alder_move_store_256": [
            "-mtune=alderlake",
            "-mmove-max=256",
            "-mstore-max=256",
        ],
        "alder_move_store_512": [
            "-mtune=alderlake",
            "-mmove-max=512",
            "-mstore-max=512",
        ],
        "alder_backend_128": [
            "-mtune=alderlake",
            "-mprefer-vector-width=128",
            "-mmove-max=128",
            "-mstore-max=128",
            "-mavx256-split-unaligned-load",
            "-mavx256-split-unaligned-store",
        ],
        "alder_backend_256": [
            "-mtune=alderlake",
            "-mprefer-vector-width=256",
            "-mmove-max=256",
            "-mstore-max=256",
            "-mno-avx256-split-unaligned-load",
            "-mno-avx256-split-unaligned-store",
        ],
        "prefer128_very_cheap": [
            "-mprefer-vector-width=128",
            "-fvect-cost-model=very-cheap",
        ],
        "prefer256_unlimited": [
            "-mprefer-vector-width=256",
            "-fvect-cost-model=unlimited",
        ],
    }.items():
        add_case(cases, name, *flags, group="small_cross")

    if len(cases) != 65:
        raise RuntimeError(f"expected 65 cases, got {len(cases)}")
    return cases


def inventory_prior_work(cases: dict[str, dict[str, Any]]) -> dict[str, Any]:
    prior_avx = json.loads(INVENTORY_ARTIFACTS["prior_avx2_screen"].read_text())
    prior_255h = json.loads(INVENTORY_ARTIFACTS["prior_255h_screen"].read_text())
    prior_layout = json.loads(
        INVENTORY_ARTIFACTS["prior_scalar_layout_screen"].read_text()
    )
    avx_cases = prior_avx["screens"]["gcc"]["cases"]
    followup_cases = prior_255h["gcc_screen"]
    layout_cases = prior_layout["flag_screen"]
    avx_flag_tuples = {
        tuple(case["extra_flags"]) for case in avx_cases.values()
    }
    followup_flag_tuples = {
        tuple(case["flags"]) for case in followup_cases.values()
    }
    new_cases = {
        name: tuple(case["flags"])
        for name, case in cases.items()
        if not case["reference"]
    }
    duplicates = {
        name: list(flags)
        for name, flags in new_cases.items()
        if flags in avx_flag_tuples or flags in followup_flag_tuples
    }
    if duplicates:
        raise RuntimeError(f"new cases repeat prior flag tuples: {duplicates}")

    scalar_layout_by_flags: dict[tuple[str, ...], list[str]] = {}
    for name, case in layout_cases.items():
        scalar_layout_by_flags.setdefault(tuple(case["cflags"]), []).append(name)
    same_flags_different_source = {
        name: scalar_layout_by_flags[flags]
        for name, flags in new_cases.items()
        if flags in scalar_layout_by_flags
    }
    return {
        "prior_avx2_screen": {
            "path": "solutions/02_optimization/screen_avx2_codegen_02.py",
            "source": SOURCE_RELATIVE,
            "gcc_case_count": len(avx_cases),
            "unique_extra_flag_tuple_count": len(avx_flag_tuples),
        },
        "prior_255h_screen": {
            "path": "solutions/02_optimization/screen_255h_toolchains_02.py",
            "source": "submissions/02/contest.c",
            "gcc_case_count": len(followup_cases),
            "unique_extra_flag_tuple_count": len(followup_flag_tuples),
        },
        "prior_scalar_layout_screen": {
            "path": "solutions/02_optimization/screen_gcc133_layout_02.py",
            "source": "submissions/02/contest.c",
            "same_flag_tuples_reused_on_new_avx2_source": (
                same_flags_different_source
            ),
        },
        "reference_cases_intentionally_repeated": [
            name for name, case in cases.items() if case["reference"]
        ],
        "new_nonreference_case_count": len(new_cases),
        "exact_nonreference_flag_tuple_overlap_with_named_prior_screens": {},
        "inventory_artifacts": {
            name: {
                "path": str(path.relative_to(ROOT)),
                "sha256_at_run": sha256(path),
            }
            for name, path in INVENTORY_ARTIFACTS.items()
        },
        "duplicate_check": "PASS",
    }


CONTAINER_BUILD_DRIVER = r'''
import hashlib
import json
import subprocess
from pathlib import Path

manifest = json.loads(Path("/config/manifest.json").read_text())
output = Path("/output")
reports = {}
for name, case in manifest["cases"].items():
    binary = output / name
    command = [
        "gcc",
        *manifest["common_flags"],
        *case["flags"],
        "/repository/solutions/02_optimization/contest_simd_avx2_lanewise.c",
        "-o",
        str(binary),
    ]
    completed = subprocess.run(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    reports[name] = {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "effective_flags": [*manifest["common_flags"], *case["flags"]],
        "binary_sha256": (
            hashlib.sha256(binary.read_bytes()).hexdigest()
            if binary.is_file()
            else None
        ),
    }
Path("/output/compile.json").write_text(json.dumps({
    "compiler": subprocess.run(
        ["gcc", "--version"], text=True, stdout=subprocess.PIPE
    ).stdout.splitlines()[0],
    "binutils": subprocess.run(
        ["objdump", "--version"], text=True, stdout=subprocess.PIPE
    ).stdout.splitlines()[0],
    "reports": reports,
}, indent=2, sort_keys=True) + "\n")
'''


def compile_cases(
    args: argparse.Namespace,
    temporary: Path,
    cases: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], Path]:
    config = temporary / "build-config"
    output = temporary / "build-output"
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
            f"{ROOT}:/repository:ro",
            "--volume",
            f"{output}:/output",
            IMAGE,
            "python3",
            "-c",
            CONTAINER_BUILD_DRIVER,
        ]
    )
    report = json.loads((output / "compile.json").read_text())
    report["container"] = {
        "image": IMAGE,
        "manifest_digest_sha256": IMAGE_DIGEST,
        "local_image_id": image_id,
        "network": "none",
        "repository_mount": "read-only",
    }
    return report, output


def normalize_diagnostic(text: str, temporary: Path) -> str:
    normalized = text.replace(str(temporary), "<temporary>")
    normalized = normalized.replace(str(ROOT), "<repository>")
    lines = [line for line in normalized.strip().splitlines() if line.strip()]
    error = next((line for line in lines if "error:" in line), "")
    return (error or (lines[-1] if lines else "no diagnostic"))[:360]


def selected_mnemonics(mnemonics: dict[str, int]) -> dict[str, int]:
    interesting = (
        "vpsllvq",
        "vpsrlvq",
        "vpor",
        "vpxor",
        "vpshufb",
        "vpaddq",
        "vmovdqa",
        "vmovdqu",
        "vzeroupper",
        "dec",
        "sub",
        "jne",
    )
    return {name: mnemonics[name] for name in interesting if mnemonics.get(name)}


def extract_loop(binary: Path, destination: Path, objdump: Path) -> None:
    """Write the exact final clock-delimited loop as llvm-mca input."""

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
        raise RuntimeError(f"{binary}: timing-loop backedge not found")
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


def audit_cases(
    args: argparse.Namespace,
    temporary: Path,
    compiled: dict[str, Any],
    binaries: Path,
    cases: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, str]]:
    reports: dict[str, Any] = {}
    loop_cache: dict[str, dict[str, Any]] = {}
    representative_by_hash: dict[str, str] = {}
    for name, compile_report in compiled["reports"].items():
        case = cases[name]
        if compile_report["returncode"]:
            reports[name] = {
                "status": "COMPILE_FAIL",
                "group": case["group"],
                "reference": case["reference"],
                "extra_flags": case["flags"],
                "diagnostic": normalize_diagnostic(
                    compile_report["stderr"] or compile_report["stdout"],
                    temporary,
                ),
            }
            continue
        binary = binaries / name
        try:
            audit = audit_main_timing_loop(
                binary,
                objdump=str(args.objdump),
                size_tool=str(args.size),
            )
            loop_hash = audit["normalized_loop_sha256"]
            if loop_hash not in loop_cache:
                loop_assembly = temporary / f"loop-{len(loop_cache):03d}.s"
                extract_loop(binary, loop_assembly, args.objdump)
                loop_cache[loop_hash] = {
                    "loop_artifact_sha256": sha256(loop_assembly),
                    "llvm_mca": analyse_loop(args.llvm_mca, loop_assembly),
                }
                representative_by_hash[loop_hash] = name
            exact_errors = validate_loop_audit(audit, "avx2-inline-lanewise")
            reports[name] = {
                "status": "PASS" if not exact_errors else "STRUCTURAL_VARIANT",
                "group": case["group"],
                "reference": case["reference"],
                "extra_flags": case["flags"],
                "effective_flags": compile_report["effective_flags"],
                "binary_sha256": audit["binary_sha256"],
                "exact_lanewise_audit_errors": exact_errors,
                "loop": {
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
                    "normalized_sha256": loop_hash,
                    "selected_mnemonics": selected_mnemonics(
                        audit["mnemonics"]
                    ),
                },
                **loop_cache[loop_hash],
            }
        except RuntimeError as error:
            reports[name] = {
                "status": "AUDIT_OR_MCA_FAIL",
                "group": case["group"],
                "reference": case["reference"],
                "extra_flags": case["flags"],
                "diagnostic": str(error)[:360],
            }
    names_by_hash: dict[str, list[str]] = {}
    for name, report in reports.items():
        if report["status"] in {"PASS", "STRUCTURAL_VARIANT"}:
            names_by_hash.setdefault(report["loop"]["normalized_sha256"], []).append(
                name
            )
    representative_by_hash = {
        loop_hash: min(
            names,
            key=lambda name: (
                0 if name == "reference_generic" else 1,
                0 if name == "reference_alderlake" else 1,
                name,
            ),
        )
        for loop_hash, names in names_by_hash.items()
    }
    return (
        {
            "counts": dict(
                sorted(Counter(report["status"] for report in reports.values()).items())
            ),
            "unique_complete_loop_hashes": len(loop_cache),
            "cases": reports,
        },
        representative_by_hash,
    )


def score_tuple(report: dict[str, Any]) -> tuple[float, ...]:
    loop = report["loop"]
    mca = report["llvm_mca"]
    return (
        float(loop["calls"]),
        float(loop["push_pop"]),
        float(loop["hot_memory_operands_excluding_lea"]),
        float(loop["instructions"]),
        float(loop["bytes"]),
        float(mca["alderlake_p_core_proxy"]["cycles_per_iteration"]),
        float(mca["znver2_cross_architecture_proxy"]["cycles_per_iteration"]),
    )


def dominates(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_score = score_tuple(left)
    right_score = score_tuple(right)
    return all(a <= b for a, b in zip(left_score, right_score)) and any(
        a < b for a, b in zip(left_score, right_score)
    )


def select_pareto(screen: dict[str, Any]) -> list[str]:
    eligible = [
        (name, report)
        for name, report in screen["cases"].items()
        if report["status"] in {"PASS", "STRUCTURAL_VARIANT"}
        and report["loop"]["calls"] == 0
        and report["loop"]["push_pop"] == 0
        and report["loop"]["hot_memory_operands_excluding_lea"] == 0
    ]
    frontier = [
        (name, report)
        for name, report in eligible
        if not any(
            other_name != name and dominates(other_report, report)
            for other_name, other_report in eligible
        )
    ]
    by_score: dict[tuple[float, ...], list[str]] = {}
    for name, report in frontier:
        by_score.setdefault(score_tuple(report), []).append(name)
    return sorted(
        min(
            names,
            key=lambda name: (
                0 if name == "reference_generic" else 1,
                0 if name == "reference_alderlake" else 1,
                name,
            ),
        )
        for names in by_score.values()
    )


CONTAINER_VERIFY_DRIVER = r'''
import json
import subprocess
from pathlib import Path

manifest = json.loads(Path("/config/manifest.json").read_text())
output = Path("/output")
verifier = output / "verifier.o"
verifier_build = subprocess.run([
    "gcc", "-O3", "-Wall", "-Wextra", "-Werror", "-c",
    "/repository/solutions/02_optimization/verify_contest_candidate_02.c",
    "-o", str(verifier),
], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
reports = {}
for name, case in manifest["cases"].items():
    candidate = output / f"{name}.o"
    executable = output / f"{name}.verify"
    compile_candidate = subprocess.run([
        "gcc", *manifest["common_flags"], *case["flags"],
        "-Dmain=contest_candidate_main", "-c",
        "/repository/solutions/02_optimization/contest_simd_avx2_lanewise.c",
        "-o", str(candidate),
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    link = None
    execution = None
    if verifier_build.returncode == 0 and compile_candidate.returncode == 0:
        link = subprocess.run([
            "gcc", str(candidate), str(verifier), "-o", str(executable)
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if link is not None and link.returncode == 0:
        execution = subprocess.run(
            [str(executable)], text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    reports[name] = {
        "verifier_compile_returncode": verifier_build.returncode,
        "candidate_compile_returncode": compile_candidate.returncode,
        "link_returncode": None if link is None else link.returncode,
        "execution_returncode": (
            None if execution is None else execution.returncode
        ),
        "stdout": "" if execution is None else execution.stdout,
        "stderr": "" if execution is None else execution.stderr,
        "build_stderr": "\n".join(
            part.stderr for part in (verifier_build, compile_candidate, link)
            if part is not None and part.stderr
        ),
    }
Path("/output/verification.json").write_text(
    json.dumps(reports, indent=2, sort_keys=True) + "\n"
)
'''


def verify_representatives(
    args: argparse.Namespace,
    temporary: Path,
    names: list[str],
    cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    config = temporary / "verify-config"
    output = temporary / "verify-output"
    config.mkdir()
    output.mkdir()
    selected = {name: cases[name] for name in names}
    (config / "manifest.json").write_text(
        json.dumps({"common_flags": COMMON_FLAGS, "cases": selected}, sort_keys=True)
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
            f"{output}:/output",
            IMAGE,
            "python3",
            "-c",
            CONTAINER_VERIFY_DRIVER,
        ]
    )
    raw = json.loads((output / "verification.json").read_text())
    reports: dict[str, Any] = {}
    for name, report in raw.items():
        passed = (
            report["verifier_compile_returncode"] == 0
            and report["candidate_compile_returncode"] == 0
            and report["link_returncode"] == 0
            and report["execution_returncode"] == 0
            and report["stdout"] == EXPECTED_VERIFIER_STDOUT
        )
        reports[name] = {
            "status": "PASS" if passed else "FAIL",
            "random_cases": 100_000,
            "seed": "0x243f6a8885a308d3",
            "round_counts": [1, 20],
            "random_state_and_constants": passed,
            **report,
        }
    return reports


def validate_inputs(args: argparse.Namespace) -> dict[str, Any]:
    actual_inputs = {relative: sha256(ROOT / relative) for relative in INPUT_HASHES}
    mismatches = {
        relative: {"expected": INPUT_HASHES[relative], "actual": actual}
        for relative, actual in actual_inputs.items()
        if actual != INPUT_HASHES[relative]
    }
    if mismatches:
        raise RuntimeError(f"input hash mismatch: {mismatches}")
    tools = {
        "objdump": args.objdump,
        "size": args.size,
        "llvm_mca": args.llvm_mca,
    }
    for name, path in tools.items():
        if not path.is_file():
            raise RuntimeError(f"missing host tool: {path}")
        actual = sha256(path)
        if actual != PINNED_HOST_TOOL_HASHES[name]:
            raise RuntimeError(
                f"{name} hash mismatch: expected {PINNED_HOST_TOOL_HASHES[name]}, "
                f"got {actual}"
            )
    return {
        "files": actual_inputs,
        "host_tools": {
            name: {
                "path": str(path),
                "sha256": sha256(path),
                "version": run([str(path), "--version"]).stdout.splitlines()[0],
            }
            for name, path in tools.items()
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Screen additional GCC 13.3 x86/AVX2 backend flags without host timing"
        )
    )
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--objdump", type=Path, default=DEFAULT_OBJDUMP)
    parser.add_argument("--size", type=Path, default=DEFAULT_SIZE)
    parser.add_argument("--llvm-mca", type=Path, default=DEFAULT_LLVM_MCA)
    parser.add_argument(
        "--json",
        type=Path,
        default=HERE / "gcc133_avx_flags_results_02.json",
    )
    args = parser.parse_args()
    if shutil.which(args.runtime) is None:
        parser.error(f"container runtime unavailable: {args.runtime}")

    inputs = validate_inputs(args)
    cases = build_cases()
    inventory = inventory_prior_work(cases)
    with tempfile.TemporaryDirectory(prefix="challenge02-gcc133-avx-flags-") as raw:
        temporary = Path(raw).resolve()
        compiled, binaries = compile_cases(args, temporary, cases)
        if compiled["compiler"] != "gcc (GCC) 13.3.0":
            raise RuntimeError(f"unexpected compiler: {compiled['compiler']}")
        screen, representative_by_hash = audit_cases(
            args, temporary, compiled, binaries, cases
        )
        pareto = select_pareto(screen)
        unique_representatives = sorted(
            representative_by_hash.values(),
            key=lambda name: (
                0 if name == "reference_generic" else 1,
                0 if name == "reference_alderlake" else 1,
                name,
            ),
        )
        baseline = screen["cases"]["reference_generic"]
        alderlake = screen["cases"]["reference_alderlake"]
        reference_stream_rank = {
            baseline["loop"]["normalized_sha256"]: 0,
            alderlake["loop"]["normalized_sha256"]: 1,
        }
        cases_by_alignment: dict[tuple[str, int], list[str]] = {}
        for name, report in screen["cases"].items():
            if report["status"] in {"PASS", "STRUCTURAL_VARIANT"}:
                alignment_key = (
                    report["loop"]["normalized_sha256"],
                    report["loop"]["start_mod_64"],
                )
                cases_by_alignment.setdefault(alignment_key, []).append(name)
        alignment_classes = []
        alignment_representatives = []
        for (loop_hash, start_mod_64), names in sorted(
            cases_by_alignment.items(),
            key=lambda item: (
                reference_stream_rank.get(item[0][0], 2),
                item[0][1],
                item[0][0],
            ),
        ):
            representative = min(
                names,
                key=lambda name: (
                    0 if name == "reference_generic" else 1,
                    0 if name == "reference_alderlake" else 1,
                    name,
                ),
            )
            alignment_representatives.append(representative)
            alignment_classes.append(
                {
                    "normalized_loop_sha256": loop_hash,
                    "stream_family": (
                        "generic"
                        if loop_hash == baseline["loop"]["normalized_sha256"]
                        else (
                            "alderlake"
                            if loop_hash
                            == alderlake["loop"]["normalized_sha256"]
                            else "other"
                        )
                    ),
                    "start_mod_64": start_mod_64,
                    "case_count": len(names),
                    "representative": representative,
                    "cases": sorted(names),
                }
            )
        screen["unique_complete_loop_alignment_classes"] = len(alignment_classes)
        verification_names = sorted(
            set(unique_representatives)
            | set(pareto)
            | set(alignment_representatives)
        )
        verification = verify_representatives(
            args, temporary, verification_names, cases
        )
        if not verification or any(
            report["status"] != "PASS" for report in verification.values()
        ):
            failed = [
                name
                for name, report in verification.items()
                if report["status"] != "PASS"
            ]
            raise RuntimeError(f"differential verification failed: {failed}")

        reference_hashes = {
            baseline["loop"]["normalized_sha256"],
            alderlake["loop"]["normalized_sha256"],
        }
        cases_by_hash: dict[str, list[str]] = {}
        for name, report in screen["cases"].items():
            if report["status"] in {"PASS", "STRUCTURAL_VARIANT"}:
                cases_by_hash.setdefault(
                    report["loop"]["normalized_sha256"], []
                ).append(name)
        new_streams = [
            name
            for name in unique_representatives
            if screen["cases"][name]["loop"]["normalized_sha256"]
            not in reference_hashes
        ]
        strict_improvements = [
            name
            for name, report in screen["cases"].items()
            if not report.get("reference")
            and report["status"] in {"PASS", "STRUCTURAL_VARIANT"}
            and dominates(report, baseline)
        ]
        result: dict[str, Any] = {
            "schema_version": 1,
            "experiment": "challenge02_gcc133_additional_avx_backend_flags",
            "scope": {
                "source": SOURCE_RELATIVE,
                "compiler": "exact GCC 13.3.0 container",
                "host_timing": "not performed",
                "target": "Core Ultra 7 255H; unavailable on this host",
            },
            "protocol": {
                "common_flags": COMMON_FLAGS,
                "complete_binary_loop_boundary": (
                    "last conditional backedge between the final two clock calls"
                ),
                "audit_mode": "avx2-inline-lanewise plus full variant report",
                "normalization": (
                    "branch-and-call-targets-as-relative-displacements-v1"
                ),
                "llvm_mca_models": MCA_MODELS,
                "llvm_mca_iterations": MCA_ITERATIONS,
                "dynamic_verification": (
                    "one representative per unique complete loop hash plus all "
                    "Pareto representatives; 100000 random states and constants, "
                    "round counts 1 and 20"
                ),
            },
            "inputs": inputs,
            "inventory": inventory,
            "toolchain": {
                "compiler": compiled["compiler"],
                "binutils": compiled["binutils"],
                "container": compiled["container"],
            },
            "screen": screen,
            "unique_stream_representatives": unique_representatives,
            "alignment_class_representatives": alignment_representatives,
            "complete_loop_alignment_classes": alignment_classes,
            "pareto_representatives": pareto,
            "verification": verification,
            "decision": {
                "reference_generic_score": score_tuple(baseline),
                "reference_alderlake_score": score_tuple(alderlake),
                "reference_equivalence_classes": {
                    "generic": {
                        "normalized_loop_sha256": baseline["loop"][
                            "normalized_sha256"
                        ],
                        "case_count": len(
                            cases_by_hash[baseline["loop"]["normalized_sha256"]]
                        ),
                    },
                    "alderlake": {
                        "normalized_loop_sha256": alderlake["loop"][
                            "normalized_sha256"
                        ],
                        "case_count": len(
                            cases_by_hash[alderlake["loop"]["normalized_sha256"]]
                        ),
                    },
                },
                "all_nonreference_cases_equal_a_reference_stream": (
                    not new_streams
                ),
                "new_distinct_stream_representatives": new_streams,
                "alignment_only_followup": {
                    "class_count": len(alignment_classes),
                    "representatives": alignment_representatives,
                    "status": "target-timing-required",
                    "reason": (
                        "identical normalized streams begin at different "
                        "mod-64 offsets; LLVM-MCA is alignment-insensitive, "
                        "the earlier AMD explicit-alignment sweep found no "
                        "significant winner, and the newly observed 24/40/48 "
                        "offsets plus every 255H core type remain unmeasured"
                    ),
                },
                "strict_static_improvements_over_generic_reference": (
                    strict_improvements
                ),
                "promotion": (
                    "none"
                    if not strict_improvements
                    else "target timing required before any source promotion"
                ),
                "caveat": (
                    "llvm-mca results are scheduling proxies and do not model "
                    "the unavailable 255H target end to end; two normalized "
                    "instruction streams expand to eight stream/alignment "
                    "classes whose frontend and code-cache effects require "
                    "measurement"
                ),
            },
            "primary_documentation": PRIMARY_DOCUMENTATION,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(
            f"cases={len(cases)} counts={screen['counts']} "
            f"unique_streams={screen['unique_complete_loop_hashes']} "
            f"alignment_classes={screen['unique_complete_loop_alignment_classes']} "
            f"verified={len(verification)}"
        )
        print(f"pareto={','.join(pareto)}")
        print(f"strict_improvements={','.join(strict_improvements) or 'none'}")
        print(f"json={args.json}")


if __name__ == "__main__":
    main()
