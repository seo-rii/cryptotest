#!/usr/bin/env python3
"""Shared assembly audit for challenge 2 contest timing binaries."""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


AUDIT_MODES = {
    "report-only",
    "default-call-allowed",
    "full-inline-320",
    "portable-inline-320",
    "bmi2-inline-pair-loop",
    "bmi2-inline-pair-unroll2",
    "bmi2-inline-pair-unroll5",
    "avx2-inline-lanewise",
    "avx2-inline-pair-block2",
}

CORE_COUNTS_BY_MODE = {
    "full-inline-320": 80,
    "portable-inline-320": 80,
    "bmi2-inline-pair-loop": 8,
    "bmi2-inline-pair-unroll2": 16,
    "bmi2-inline-pair-unroll5": 40,
}

MEMORY_OPERANDS_BY_MODE = {
    "full-inline-320": 0,
    "portable-inline-320": 0,
    "bmi2-inline-pair-loop": 0,
    "bmi2-inline-pair-unroll2": 1,
    "bmi2-inline-pair-unroll5": 1,
}


def audit_main_timing_loop(
    binary: Path,
    *,
    objdump: str = "objdump",
    size_tool: str = "size",
) -> dict[str, Any]:
    """Locate and describe the final timed loop in a complete contest binary."""

    binary = binary.resolve()
    if not binary.is_file():
        raise RuntimeError(f"binary does not exist: {binary}")

    disassembly = subprocess.run(
        [objdump, "-d", "--no-show-raw-insn", "--disassemble=main", str(binary)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    instructions: list[dict[str, Any]] = []
    for line in disassembly.splitlines():
        match = re.match(
            r"^\s*([0-9a-fA-F]+):\s+([^\s]+)(?:\s+(.*?))?\s*$",
            line,
        )
        if match:
            instructions.append(
                {
                    "address": int(match.group(1), 16),
                    "mnemonic": match.group(2).lower(),
                    "operands": (match.group(3) or "").strip(),
                }
            )

    clock_indices = [
        index
        for index, instruction in enumerate(instructions)
        if str(instruction["mnemonic"]).startswith("call")
        and re.search(r"<clock(?:@[^>]*)?>", str(instruction["operands"]))
    ]
    if len(clock_indices) < 2:
        raise RuntimeError(
            f"expected two calls to clock() in main, found {len(clock_indices)}"
        )
    first_clock, second_clock = clock_indices[-2:]

    backedges: list[tuple[int, int]] = []
    for index in range(first_clock + 1, second_clock):
        instruction = instructions[index]
        mnemonic = str(instruction["mnemonic"])
        target_match = re.match(
            r"(?:\*?0x)?([0-9a-fA-F]+)", str(instruction["operands"])
        )
        if (
            mnemonic.startswith("j")
            and mnemonic != "jmp"
            and target_match
            and int(target_match.group(1), 16) < int(instruction["address"])
        ):
            backedges.append((index, int(target_match.group(1), 16)))
    if not backedges:
        raise RuntimeError("no conditional timing-loop backedge found")
    branch_index, loop_start = backedges[-1]

    address_to_index = {
        int(instruction["address"]): index for index, instruction in enumerate(instructions)
    }
    if loop_start not in address_to_index:
        raise RuntimeError(f"backedge target 0x{loop_start:x} is not an instruction")
    loop_start_index = address_to_index[loop_start]
    loop = instructions[loop_start_index : branch_index + 1]
    if branch_index + 1 >= len(instructions):
        raise RuntimeError("timing-loop branch is the last disassembled instruction")
    next_address = int(instructions[branch_index + 1]["address"])

    mnemonics = Counter(str(instruction["mnemonic"]) for instruction in loop)
    calls = sum(
        count for mnemonic, count in mnemonics.items() if mnemonic.startswith("call")
    )
    stack_ops = mnemonics["push"] + mnemonics["pop"]
    memory_operands = sum(
        "(" in str(instruction["operands"])
        for instruction in loop
        if instruction["mnemonic"] != "lea"
        and re.search(
            r"(?:^|\s)nop[wlq]?(?:\s|$)",
            f"{instruction['mnemonic']} {instruction['operands']}",
        )
        is None
    )
    rotate_count = mnemonics["rorx"] + mnemonics["rol"] + mnemonics["ror"]
    core_counts = {
        "rotate": rotate_count,
        "xor": mnemonics["xor"],
        "bswap": mnemonics["bswap"],
        "add_or_lea": mnemonics["add"] + mnemonics["lea"],
    }

    legacy_normalized = "\n".join(
        f"{instruction['mnemonic']} {instruction['operands']}".rstrip()
        for instruction in loop
    )
    reloc_normalized_lines: list[str] = []
    for instruction in loop:
        mnemonic = str(instruction["mnemonic"])
        operands = str(instruction["operands"])
        if mnemonic.startswith(("j", "call")):
            target_match = re.match(r"(?:\*?0x)?([0-9a-fA-F]+)", operands)
            if target_match:
                target = int(target_match.group(1), 16)
                operands = f"rel={target - int(instruction['address']):+d}"
        reloc_normalized_lines.append(f"{mnemonic} {operands}".rstrip())
    reloc_normalized = "\n".join(reloc_normalized_lines)

    size_output = subprocess.run(
        [size_tool, str(binary)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()
    if len(size_output) < 2:
        raise RuntimeError(f"unexpected size output for {binary}")
    text_bytes = int(size_output[1].split()[0])

    return {
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "text_bytes": text_bytes,
        "loop_start": f"0x{loop_start:x}",
        "loop_start_mod_16": loop_start % 16,
        "loop_start_mod_32": loop_start % 32,
        "loop_start_mod_64": loop_start % 64,
        "loop_bytes": next_address - loop_start,
        "loop_instructions": len(loop),
        "calls": calls,
        "push_pop": stack_ops,
        "memory_operands_excluding_lea": memory_operands,
        "core_counts": core_counts,
        "mnemonics": dict(sorted(mnemonics.items())),
        "normalized_loop_sha256": hashlib.sha256(
            reloc_normalized.encode()
        ).hexdigest(),
        "legacy_addressed_loop_sha256": hashlib.sha256(
            legacy_normalized.encode()
        ).hexdigest(),
        "normalization": "branch-and-call-targets-as-relative-displacements-v1",
    }


def validate_loop_audit(report: dict[str, Any], mode: str) -> list[str]:
    """Return structural mismatches for one manifest audit mode."""

    if mode not in AUDIT_MODES:
        return [f"unknown audit mode: {mode}"]
    if mode in {"report-only", "default-call-allowed"}:
        return []

    errors: list[str] = []
    if mode in {"avx2-inline-lanewise", "avx2-inline-pair-block2"}:
        for key in ("calls", "push_pop", "memory_operands_excluding_lea"):
            actual = report.get(key)
            if actual != 0:
                errors.append(f"{key}: expected 0, got {actual}")
        vector_count = 20 if mode == "avx2-inline-lanewise" else 4
        expected_mnemonics = {
            "vpsllvq": vector_count,
            "vpsrlvq": vector_count,
            "vpor": vector_count,
            "vpxor": vector_count,
            "vpshufb": vector_count,
            "vpaddq": vector_count,
        }
        mnemonics = report.get("mnemonics", {})
        for mnemonic, expected in expected_mnemonics.items():
            actual = mnemonics.get(mnemonic, 0)
            if actual != expected:
                errors.append(
                    f"mnemonics.{mnemonic}: expected {expected}, got {actual}"
                )
        if mode == "avx2-inline-lanewise":
            expected_instructions = sum(expected_mnemonics.values()) + 2
        else:
            for mnemonic, expected in {
                "sub": 2,
                "jne": 2,
                "mov": 1,
                "nopl": 1,
            }.items():
                actual = mnemonics.get(mnemonic, 0)
                if actual != expected:
                    errors.append(
                        f"mnemonics.{mnemonic}: expected {expected}, got {actual}"
                    )
            expected_instructions = sum(expected_mnemonics.values()) + 6
        actual_instructions = report.get("loop_instructions")
        if actual_instructions != expected_instructions:
            errors.append(
                "loop_instructions: "
                f"expected {expected_instructions}, got {actual_instructions}"
            )
        return errors

    expected_core_count = CORE_COUNTS_BY_MODE[mode]
    expected_counts = {
        "rotate": expected_core_count,
        "xor": expected_core_count,
        "bswap": expected_core_count,
        "add_or_lea": expected_core_count,
    }
    for key, expected in expected_counts.items():
        actual = report.get("core_counts", {}).get(key)
        if actual != expected:
            errors.append(f"core_counts.{key}: expected {expected}, got {actual}")
    for key in ("calls", "push_pop"):
        actual = report.get(key)
        if actual != 0:
            errors.append(f"{key}: expected 0, got {actual}")
    expected_memory = MEMORY_OPERANDS_BY_MODE[mode]
    actual_memory = report.get("memory_operands_excluding_lea")
    if actual_memory != expected_memory:
        errors.append(
            "memory_operands_excluding_lea: "
            f"expected {expected_memory}, got {actual_memory}"
        )

    mnemonics = report.get("mnemonics", {})
    rorx = mnemonics.get("rorx", 0)
    if mode != "portable-inline-320" and rorx != expected_core_count:
        errors.append(
            f"mnemonics.rorx: expected {expected_core_count}, got {rorx}"
        )
    if mode == "portable-inline-320" and rorx != 0:
        errors.append(f"mnemonics.rorx: expected 0, got {rorx}")
    return errors


def format_loop_summary(name: str, report: dict[str, Any]) -> str:
    """Format the compact line shared by the audit and benchmark CLIs."""

    return (
        f"case={name} text={report['text_bytes']} loop={report['loop_start']} "
        f"mod64={report['loop_start_mod_64']} bytes={report['loop_bytes']} "
        f"instructions={report['loop_instructions']} calls={report['calls']} "
        f"push_pop={report['push_pop']} "
        f"memory={report['memory_operands_excluding_lea']} "
        f"core={report['core_counts']}"
    )
