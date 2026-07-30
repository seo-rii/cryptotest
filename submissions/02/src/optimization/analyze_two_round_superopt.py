#!/usr/bin/env python3
"""Search for shorter challenge 2 scalar one- and two-stage ARX chains."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence
from zipfile import ZipFile

try:
    import z3
except ImportError as error:  # pragma: no cover - depends on the host toolchain
    raise SystemExit("z3-solver is required: python3 -m pip install z3-solver") from error


SCRIPT = Path(__file__).resolve()
REPOSITORY = SCRIPT.parents[4]
SOLUTIONS = SCRIPT.parents[1]
if str(SOLUTIONS) not in sys.path:
    sys.path.insert(0, str(SOLUTIONS))

from loop_audit import (  # noqa: E402
    audit_main_timing_loop,
    validate_loop_audit,
)


MASK = (1 << 64) - 1
TOP = 1 << 63
OPS = ("R", "X", "B", "A")
RANDOM_SEED = 0xBB67AE8584CAA73B
WITNESS_SEED = 0x3C6EF372FE94F82B
ROTATIONS = (43, 7, 29, 14)
XOR_CONSTANTS = (
    0xE7B92D4A6C1F8035,
    0x1A4F8C3E9D2B6074,
    0xC3F05A2E8D6194B7,
    0x6B2E9D1A4F7C3085,
)
ADD_CONSTANTS = (
    0x8F4A2C1E9B7D3F61,
    0x3C6E9A1D5B7F2840,
    0xA7E2D9C4B1F60853,
    0x5D0F3A8E2C6B4197,
)
CHAIN_SPECS = (
    {
        "word": 0,
        "first": (43, XOR_CONSTANTS[0], ADD_CONSTANTS[3]),
        "second": (14, XOR_CONSTANTS[3], ADD_CONSTANTS[0]),
    },
    {
        "word": 1,
        "first": (7, XOR_CONSTANTS[1], ADD_CONSTANTS[2]),
        "second": (29, XOR_CONSTANTS[2], ADD_CONSTANTS[1]),
    },
    {
        "word": 2,
        "first": (29, XOR_CONSTANTS[2], ADD_CONSTANTS[1]),
        "second": (7, XOR_CONSTANTS[1], ADD_CONSTANTS[2]),
    },
    {
        "word": 3,
        "first": (14, XOR_CONSTANTS[3], ADD_CONSTANTS[0]),
        "second": (43, XOR_CONSTANTS[0], ADD_CONSTANTS[3]),
    },
)


def rol(value: int, amount: int) -> int:
    return ((value << amount) | (value >> (64 - amount))) & MASK


def ror(value: int, amount: int) -> int:
    return ((value >> amount) | (value << (64 - amount))) & MASK


def bswap(value: int) -> int:
    return int.from_bytes(value.to_bytes(8, "little"), "big")


def stage(value: int, rotation: int, xor_constant: int, add_constant: int) -> int:
    return (bswap(rol(value, rotation) ^ xor_constant) + add_constant) & MASK


def pair(value: int, spec: dict[str, Any]) -> int:
    return stage(stage(value, *spec["first"]), *spec["second"])


def fits_sign_extended_imm32(value: int) -> bool:
    low = value & 0xFFFF_FFFF
    extension = low | (0xFFFF_FFFF_0000_0000 if low & 0x8000_0000 else 0)
    return extension == value


def bv(value: int) -> Any:
    return z3.BitVecVal(value & MASK, 64)


def z3_bswap(value: Any) -> Any:
    return z3.Concat(*(z3.Extract(8 * index + 7, 8 * index, value) for index in range(8)))


def z3_apply(value: Any, operation: str, parameter: Any | None) -> Any:
    if operation == "R":
        return z3.RotateLeft(value, parameter)
    if operation == "X":
        return value ^ parameter
    if operation == "B":
        return z3_bswap(value)
    if operation == "A":
        return value + parameter
    raise ValueError(f"unknown operation: {operation}")


def z3_stage(value: Any, transform: Sequence[int]) -> Any:
    rotation, xor_constant, add_constant = transform
    return z3_bswap(z3.RotateLeft(value, rotation) ^ bv(xor_constant)) + bv(
        add_constant
    )


def witness_values() -> list[int]:
    values = [
        0,
        1,
        MASK,
        TOP,
        TOP - 1,
        0x0123456789ABCDEF,
        0xFEDCBA9876543210,
        0x5555555555555555,
        0xAAAAAAAAAAAAAAAA,
    ]
    generator = random.Random(WITNESS_SEED)
    values.extend(generator.getrandbits(64) for _ in range(15))
    return values


def template_cegis(
    *,
    name: str,
    operations: Sequence[tuple[str, int | None]],
    target: Callable[[Any], Any],
    witnesses: Sequence[int],
    timeout_ms: int,
    max_iterations: int = 8,
    symbolic_rotations: bool = True,
) -> dict[str, Any]:
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    parameters: list[Any | None] = []
    for position, (operation, fixed_parameter) in enumerate(operations):
        if operation in {"X", "A"}:
            parameter = z3.BitVec(f"{name}_p{position}", 64)
        elif operation == "R" and symbolic_rotations:
            parameter = z3.BitVec(f"{name}_p{position}", 64)
            solver.add(z3.UGE(parameter, 1), z3.ULE(parameter, 63))
        elif operation == "R":
            if fixed_parameter is None:
                raise ValueError("a fixed rotation is missing")
            parameter = bv(fixed_parameter)
        else:
            parameter = None
        parameters.append(parameter)

    def expression(value: Any, concrete: Sequence[Any | None] = parameters) -> Any:
        for (operation, _), parameter in zip(operations, concrete, strict=True):
            value = z3_apply(value, operation, parameter)
        return value

    active_witnesses = list(dict.fromkeys(witnesses))
    for value in active_witnesses:
        symbolic_value = bv(value)
        solver.add(expression(symbolic_value) == target(symbolic_value))

    for iteration in range(max_iterations):
        status = solver.check()
        if status == z3.unsat:
            return {
                "status": "UNSAT_ON_WITNESSES",
                "cegis_iterations": iteration,
                "witness_count": len(active_witnesses),
            }
        if status == z3.unknown:
            return {
                "status": "UNKNOWN",
                "cegis_iterations": iteration,
                "reason": solver.reason_unknown(),
                "witness_count": len(active_witnesses),
            }

        model = solver.model()
        concrete = [
            None
            if parameter is None
            else bv(model.eval(parameter, model_completion=True).as_long())
            for parameter in parameters
        ]
        value = z3.BitVec(f"{name}_counterexample_{iteration}", 64)
        verifier = z3.Solver()
        verifier.set(timeout=timeout_ms)
        verifier.add(expression(value, concrete) != target(value))
        verification_status = verifier.check()
        model_parameters = [
            None
            if parameter is None
            else f"0x{parameter.as_long():016x}"
            for parameter in concrete
        ]
        if verification_status == z3.unsat:
            return {
                "status": "EQUIVALENT_FOUND",
                "cegis_iterations": iteration,
                "parameters": model_parameters,
                "witness_count": len(active_witnesses),
            }
        if verification_status == z3.unknown:
            return {
                "status": "UNKNOWN",
                "cegis_iterations": iteration,
                "reason": "verification: " + verifier.reason_unknown(),
                "parameters": model_parameters,
                "witness_count": len(active_witnesses),
            }
        counterexample = verifier.model().eval(value, model_completion=True).as_long()
        active_witnesses.append(counterexample)
        symbolic_counterexample = bv(counterexample)
        solver.add(
            expression(symbolic_counterexample) == target(symbolic_counterexample)
        )

    return {
        "status": "CEGIS_LIMIT",
        "cegis_iterations": max_iterations,
        "witness_count": len(active_witnesses),
    }


def stage_superoptimization(
    witnesses: Sequence[int], timeout_ms: int
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    occurrences: dict[tuple[int, int, int], list[int]] = {}
    for occurrence, transform in enumerate(
        spec[part] for spec in CHAIN_SPECS for part in ("first", "second")
    ):
        occurrences.setdefault(tuple(transform), []).append(occurrence)
    for stage_index, (transform, stage_occurrences) in enumerate(occurrences.items()):
        rotation, xor_constant, add_constant = transform

        def target(value: Any, current: Sequence[int] = transform) -> Any:
            return z3_stage(value, current)

        templates: list[dict[str, Any]] = []
        for operation_tuple in itertools.product(OPS, repeat=3):
            name = f"stage{stage_index}_{''.join(operation_tuple)}"
            search = template_cegis(
                name=name,
                operations=[(operation, None) for operation in operation_tuple],
                target=target,
                witnesses=witnesses,
                timeout_ms=timeout_ms,
            )
            templates.append({"template": "".join(operation_tuple), **search})
        results.append(
            {
                "stage_id": stage_index,
                "stage_occurrences": stage_occurrences,
                "rotation": rotation,
                "xor_constant": f"0x{xor_constant:016x}",
                "add_constant": f"0x{add_constant:016x}",
                "status_counts": dict(
                    sorted(
                        {
                            status: sum(
                                item["status"] == status for item in templates
                            )
                            for status in {item["status"] for item in templates}
                        }.items()
                    )
                ),
                "all_length_three_templates_unsat": all(
                    item["status"] == "UNSAT_ON_WITNESSES" for item in templates
                ),
                "non_unsat_templates": [
                    item
                    for item in templates
                    if item["status"] != "UNSAT_ON_WITNESSES"
                ],
            }
        )
    return {
        "grammar": {
            "R": "ROL by an arbitrary amount 1..63",
            "X": "XOR by an arbitrary 64-bit constant",
            "B": "BSWAP64",
            "A": "ADD modulo 2^64 by an arbitrary 64-bit constant",
        },
        "searched_length": 3,
        "template_count_per_stage": len(OPS) ** 3,
        "shorter_sequence_padding": (
            "Any length-0/1/2 expression is included by padding it with XOR 0."
        ),
        "stages": results,
        "all_templates_unsat": all(
            result["all_length_three_templates_unsat"] for result in results
        ),
    }


def pair_single_deletion_search(
    witnesses: Sequence[int], timeout_ms: int
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for spec in CHAIN_SPECS:
        first = spec["first"]
        second = spec["second"]
        original: list[tuple[str, int | None]] = [
            ("R", first[0]),
            ("X", first[1]),
            ("B", None),
            ("A", first[2]),
            ("R", second[0]),
            ("X", second[1]),
            ("B", None),
            ("A", second[2]),
        ]

        def target(value: Any, current: dict[str, Any] = spec) -> Any:
            return z3_stage(z3_stage(value, current["first"]), current["second"])

        deletions: list[dict[str, Any]] = []
        for deleted_index, deleted in enumerate(original):
            operations = original[:deleted_index] + original[deleted_index + 1 :]
            search = template_cegis(
                name=f"pair{spec['word']}_delete{deleted_index}",
                operations=operations,
                target=target,
                witnesses=witnesses,
                timeout_ms=timeout_ms,
                symbolic_rotations=False,
            )
            deletions.append(
                {
                    "deleted_index": deleted_index,
                    "deleted_operation": deleted[0],
                    "remaining_template": "".join(item[0] for item in operations),
                    **search,
                }
            )
        results.append({"word": spec["word"], "deletions": deletions})
    return {
        "scope": (
            "Delete one operation from RXBARXBA, retain the remaining rotation "
            "amounts and order, and resynthesize every remaining XOR/ADD constant."
        ),
        "pairs": results,
        "all_deletions_unsat": all(
            deletion["status"] == "UNSAT_ON_WITNESSES"
            for result in results
            for deletion in result["deletions"]
        ),
    }


def xor_add_reordering_search(
    witnesses: Sequence[int], timeout_ms: int
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    occurrences: dict[tuple[int, int, int], list[int]] = {}
    for occurrence, transform in enumerate(
        spec[part] for spec in CHAIN_SPECS for part in ("first", "second")
    ):
        occurrences.setdefault(tuple(transform), []).append(occurrence)
    for index, (transform, stage_occurrences) in enumerate(occurrences.items()):
        _, xor_constant, add_constant = transform
        post_bswap_xor = bswap(xor_constant)
        leading_add = z3.BitVec(f"reorder{index}_add", 64)
        trailing_xor = z3.BitVec(f"reorder{index}_xor", 64)
        solver = z3.Solver()
        solver.set(timeout=timeout_ms)
        for value in witnesses:
            x = bv(value)
            solver.add(
                (x ^ bv(post_bswap_xor)) + bv(add_constant)
                == (x + leading_add) ^ trailing_xor
            )
        status = solver.check()
        result: dict[str, Any] = {
            "stage_id": index,
            "stage_occurrences": stage_occurrences,
            "xor_after_bswap": f"0x{post_bswap_xor:016x}",
            "add_constant": f"0x{add_constant:016x}",
            "status": (
                "UNSAT_ON_WITNESSES"
                if status == z3.unsat
                else "UNKNOWN"
                if status == z3.unknown
                else "WITNESS_MODEL_FOUND"
            ),
        }
        if status == z3.unknown:
            result["reason"] = solver.reason_unknown()
        elif status == z3.sat:
            model = solver.model()
            result["leading_add"] = (
                f"0x{model.eval(leading_add, model_completion=True).as_long():016x}"
            )
            result["trailing_xor"] = (
                f"0x{model.eval(trailing_xor, model_completion=True).as_long():016x}"
            )
        results.append(result)
    return {
        "equation": "(x xor K) + A == (x + D) xor E",
        "results": results,
        "all_reorderings_unsat": all(
            result["status"] == "UNSAT_ON_WITNESSES" for result in results
        ),
    }


def boundary_commutation_search(
    witnesses: Sequence[int], timeout_ms: int
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for spec in CHAIN_SPECS:
        first_add = spec["first"][2]
        second_rotation = spec["second"][0]
        for output_operation in ("A", "X"):
            constant = z3.BitVec(
                f"boundary{spec['word']}_{output_operation.lower()}", 64
            )
            solver = z3.Solver()
            solver.set(timeout=timeout_ms)
            for value in witnesses:
                x = bv(value)
                left = z3_bswap(z3.RotateLeft(x + bv(first_add), second_rotation))
                linear = z3_bswap(z3.RotateLeft(x, second_rotation))
                right = linear + constant if output_operation == "A" else linear ^ constant
                solver.add(left == right)
            status = solver.check()
            results.append(
                {
                    "word": spec["word"],
                    "first_add": f"0x{first_add:016x}",
                    "next_linear": f"BSWAP(ROL(x,{second_rotation}))",
                    "candidate_tail": output_operation,
                    "status": (
                        "UNSAT_ON_WITNESSES"
                        if status == z3.unsat
                        else "UNKNOWN"
                        if status == z3.unknown
                        else "WITNESS_MODEL_FOUND"
                    ),
                    **(
                        {"reason": solver.reason_unknown()}
                        if status == z3.unknown
                        else {}
                    ),
                }
            )
    return {
        "equations": (
            "P(x + A) == P(x) + D and P(x + A) == P(x) xor E, "
            "where P is the next BSWAP-after-rotate permutation"
        ),
        "results": results,
        "all_commutations_unsat": all(
            result["status"] == "UNSAT_ON_WITNESSES" for result in results
        ),
    }


def bit_permutation(operations: Sequence[tuple[str, int | None]]) -> tuple[int, ...]:
    permutation: list[int] = []
    for source_bit in range(64):
        value = 1 << source_bit
        for operation, parameter in operations:
            if operation == "R":
                assert parameter is not None
                value = rol(value, parameter)
            elif operation == "B":
                value = bswap(value)
            else:
                raise ValueError("linear permutation accepts only R and B")
        permutation.append(value.bit_length() - 1)
    return tuple(permutation)


def linear_skeleton_search() -> dict[str, Any]:
    candidates: list[tuple[str, list[tuple[str, int | None]]]] = [("I", [])]
    candidates.append(("B", [("B", None)]))
    candidates.extend((f"R{r}", [("R", r)]) for r in range(1, 64))
    candidates.extend(
        (f"BR{r}", [("B", None), ("R", r)]) for r in range(1, 64)
    )
    candidates.extend(
        (f"R{r}B", [("R", r), ("B", None)]) for r in range(1, 64)
    )
    candidates.extend(
        (f"BR{r}B", [("B", None), ("R", r), ("B", None)])
        for r in range(1, 64)
    )
    candidates.extend(
        (
            f"R{first}BR{second}",
            [("R", first), ("B", None), ("R", second)],
        )
        for first in range(1, 64)
        for second in range(1, 64)
    )
    candidate_permutations: dict[tuple[int, ...], list[str]] = {}
    for name, operations in candidates:
        candidate_permutations.setdefault(bit_permutation(operations), []).append(name)

    results: list[dict[str, Any]] = []
    for spec in CHAIN_SPECS:
        first_rotation = spec["first"][0]
        second_rotation = spec["second"][0]
        target = bit_permutation(
            [
                ("R", first_rotation),
                ("B", None),
                ("R", second_rotation),
                ("B", None),
            ]
        )
        results.append(
            {
                "word": spec["word"],
                "rotations": [first_rotation, second_rotation],
                "matches_at_most_three_linear_instructions": candidate_permutations.get(
                    target, []
                ),
            }
        )
    return {
        "grammar": "canonical reduced sequences of ROL and BSWAP of length <= 3",
        "enumerated_syntaxes": len(candidates),
        "distinct_permutations": len(candidate_permutations),
        "results": results,
        "all_pair_skeletons_need_four": all(
            not result["matches_at_most_three_linear_instructions"]
            for result in results
        ),
    }


def random_identity_checks(random_cases: int) -> dict[str, Any]:
    generator = random.Random(RANDOM_SEED)
    checked = 0
    for case_index in range(random_cases):
        spec = CHAIN_SPECS[case_index % len(CHAIN_SPECS)]
        first_rotation = spec["first"][0]
        second_rotation = spec["second"][0]
        value = generator.getrandbits(64)
        first_xor = generator.getrandbits(64)
        first_add = generator.getrandbits(64)
        second_xor = generator.getrandbits(64)
        second_add = generator.getrandbits(64)
        baseline = stage(
            stage(value, first_rotation, first_xor, first_add),
            second_rotation,
            second_xor,
            second_add,
        )
        post = (
            bswap(
                rol(
                    (bswap(rol(value, first_rotation)) ^ bswap(first_xor))
                    + first_add
                    & MASK,
                    second_rotation,
                )
            )
            ^ bswap(second_xor)
        ) + second_add & MASK
        pre_first = ror(first_xor, first_rotation)
        pre_second = ror(second_xor, second_rotation)
        pre = (
            bswap(
                rol(
                    bswap(rol(value ^ pre_first, first_rotation))
                    + first_add
                    & MASK
                    ^ pre_second,
                    second_rotation,
                )
            )
            + second_add
        ) & MASK
        if baseline != post or baseline != pre:
            raise RuntimeError(f"constant-placement identity failed at case {case_index}")
        checked += 1
    return {
        "seed": f"0x{RANDOM_SEED:016x}",
        "random_state_and_constants": True,
        "cases": checked,
        "status": "PASS",
    }


def official_vector_checks() -> dict[str, Any]:
    archive = REPOSITORY / "submissions/02/src/2_암호구현.zip"
    with ZipFile(archive) as zipped:
        one_round_text = zipped.read("code/testvector.txt").decode()
        twenty_round_text = zipped.read("code/testvector_20round.txt").decode()

    one_round_values = [
        int(token, 16)
        for token in re.findall(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{16}(?![0-9A-Fa-f])", one_round_text)
    ]
    if not one_round_values or len(one_round_values) % 8:
        raise RuntimeError("could not parse the official one-round vectors")
    one_round_cases = 0
    for offset in range(0, len(one_round_values), 8):
        input_words = one_round_values[offset : offset + 4]
        expected = one_round_values[offset + 4 : offset + 8]
        actual = [0, 0, 0, 0]
        for source_word in range(4):
            actual[3 - source_word] = stage(
                input_words[source_word],
                ROTATIONS[source_word],
                XOR_CONSTANTS[source_word],
                ADD_CONSTANTS[3 - source_word],
            )
        if actual != expected:
            raise RuntimeError(f"official one-round vector {one_round_cases} failed")
        one_round_cases += 1

    twenty_round_values = [
        int(token, 16)
        for token in re.findall(
            r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{16}(?![0-9A-Fa-f])",
            twenty_round_text,
        )
    ]
    if len(twenty_round_values) != 8:
        raise RuntimeError("could not parse the official twenty-round vector")
    state = twenty_round_values[:4]
    for _ in range(10):
        state = [pair(value, spec) for value, spec in zip(state, CHAIN_SPECS, strict=True)]
    if state != twenty_round_values[4:]:
        raise RuntimeError("official twenty-round vector failed")
    return {
        "archive": "submissions/02/src/2_암호구현.zip",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "one_round_cases": one_round_cases,
        "twenty_round_cases": 1,
        "status": "PASS",
    }


def parse_functions(disassembly: str) -> dict[str, list[dict[str, str]]]:
    functions: dict[str, list[dict[str, str]]] = {}
    current: list[dict[str, str]] | None = None
    for line in disassembly.splitlines():
        symbol = re.match(r"^[0-9a-fA-F]+ <([^>]+)>:$", line.strip())
        if symbol:
            current = []
            functions[symbol.group(1)] = current
            continue
        instruction = re.match(
            r"^\s*[0-9a-fA-F]+:\s+([^\s]+)(?:\s+(.*?))?\s*$", line
        )
        if current is not None and instruction:
            current.append(
                {
                    "mnemonic": instruction.group(1).lower(),
                    "operands": (instruction.group(2) or "").strip(),
                }
            )
    return functions


def summarize_function(instructions: Sequence[dict[str, str]]) -> dict[str, Any]:
    body = [
        instruction
        for instruction in instructions
        if not instruction["mnemonic"].startswith("nop")
        and instruction["mnemonic"] != "ret"
    ]
    mnemonics: dict[str, int] = {}
    for instruction in body:
        mnemonic = instruction["mnemonic"]
        mnemonics[mnemonic] = mnemonics.get(mnemonic, 0) + 1
    return {
        "body_instruction_count": len(body),
        "core_counts": {
            "rotate": sum(mnemonics.get(name, 0) for name in ("rorx", "rol", "ror")),
            "xor": mnemonics.get("xor", 0),
            "bswap": mnemonics.get("bswap", 0),
            "add_or_lea": mnemonics.get("add", 0) + mnemonics.get("lea", 0),
        },
        "movabs": mnemonics.get("movabs", 0),
        "memory_operands_excluding_lea": sum(
            "(" in instruction["operands"] and instruction["mnemonic"] != "lea"
            for instruction in body
        ),
        "mnemonics": dict(sorted(mnemonics.items())),
        "assembly": [
            f"{instruction['mnemonic']} {instruction['operands']}".rstrip()
            for instruction in body
        ],
    }


def run_command(command: Sequence[str]) -> str:
    return subprocess.run(
        list(command),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def compiler_codegen(
    compiler: str, objdump: str, temporary: Path
) -> dict[str, Any]:
    located = shutil.which(compiler)
    if not located:
        return {"status": "SKIP", "reason": f"compiler not found: {compiler}"}
    # Preserve multicall/symlink launchers such as Swiftly's ``clang``: invoking
    # the resolved dispatcher path directly can change argv[0] and its behavior.
    compiler_path = str(Path(located).absolute())
    version = run_command([compiler_path, "--version"]).splitlines()[0]
    is_clang = "clang" in version.lower()
    probe_source = SCRIPT.with_name("two_round_chain_probe.c")
    probe_object = temporary / ("probe-clang.o" if is_clang else "probe-gcc.o")
    probe_command = [
        compiler_path,
        "-O3",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-mbmi2",
        "-c",
        str(probe_source),
        "-o",
        str(probe_object),
    ]
    run_command(probe_command)
    disassembly = run_command(
        [objdump, "-d", "--no-show-raw-insn", str(probe_object)]
    )
    functions = parse_functions(disassembly)
    required = (
        "chain_baseline",
        "chain_post_bswap",
        "chain_pre_rotate",
        "chain_literal_x0",
        "chain_linear_skeleton",
    )
    missing = [name for name in required if name not in functions]
    if missing:
        raise RuntimeError(f"{compiler}: missing probe functions: {missing}")

    contest_binary = temporary / ("contest-clang" if is_clang else "contest-gcc")
    contest_command = [
        compiler_path,
        "-O3",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-mbmi2",
    ]
    if is_clang:
        contest_command.extend(["-mllvm", "-inline-threshold=5000"])
    else:
        contest_command.append("-finline-limit=2000")
    contest_command.extend(
        [str(REPOSITORY / "submissions/02/contest.c"), "-o", str(contest_binary)]
    )
    run_command(contest_command)
    audit = audit_main_timing_loop(contest_binary, objdump=objdump)
    audit_errors = validate_loop_audit(audit, "full-inline-320")
    audit["mode"] = "full-inline-320"
    audit["status"] = "PASS" if not audit_errors else "FAIL"
    audit["errors"] = audit_errors
    temporary_prefix = str(temporary)

    def stable_command(command: Sequence[str]) -> list[str]:
        return [token.replace(temporary_prefix, "$TMP") for token in command]

    return {
        "status": "PASS",
        "compiler": compiler_path,
        "version": version,
        "probe_command": stable_command(probe_command),
        "contest_command": stable_command(contest_command),
        "probe_functions": {
            name: summarize_function(functions[name]) for name in required
        },
        "contest_timing_loop_audit": audit,
    }


def immediate_analysis() -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    for occurrence, transform in enumerate(
        [spec[part] for spec in CHAIN_SPECS for part in ("first", "second")]
    ):
        rotation, xor_constant, add_constant = transform
        forms = {
            "xor_original": xor_constant,
            "xor_after_bswap": bswap(xor_constant),
            "xor_before_rotate": ror(xor_constant, rotation),
            "add": add_constant,
        }
        stages.append(
            {
                "stage_occurrence": occurrence,
                "rotation": rotation,
                "values": {name: f"0x{value:016x}" for name, value in forms.items()},
                "fits_sign_extended_imm32": {
                    name: fits_sign_extended_imm32(value)
                    for name, value in forms.items()
                },
            }
        )
    return {
        "x86_64_rule": "XOR/ADD r64, imm encodes only a sign-extended imm32",
        "stages": stages,
        "all_forms_require_register_or_memory": not any(
            any(stage_result["fits_sign_extended_imm32"].values())
            for stage_result in stages
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument("--solver-timeout-ms", type=int, default=10_000)
    parser.add_argument("--gcc", default="gcc")
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("--skip-codegen", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.random_cases <= 0 or args.solver_timeout_ms <= 0:
        parser.error("--random-cases and --solver-timeout-ms must be positive")

    witnesses = witness_values()
    witness_bytes = b"".join(value.to_bytes(8, "little") for value in witnesses)
    formulas = []
    for spec in CHAIN_SPECS:
        first = spec["first"]
        second = spec["second"]
        formulas.append(
            {
                "word": spec["word"],
                "first": {
                    "rotation": first[0],
                    "xor": f"0x{first[1]:016x}",
                    "add": f"0x{first[2]:016x}",
                },
                "second": {
                    "rotation": second[0],
                    "xor": f"0x{second[1]:016x}",
                    "add": f"0x{second[2]:016x}",
                },
                "formula": (
                    f"T({second[0]},0x{second[1]:016x},0x{second[2]:016x},"
                    f" T({first[0]},0x{first[1]:016x},0x{first[2]:016x},x))"
                ),
            }
        )

    report: dict[str, Any] = {
        "schema_version": 1,
        "analysis": "challenge_two_round_scalar_superoptimization",
        "source": {
            "path": "submissions/02/contest.c",
            "sha256": hashlib.sha256(
                (REPOSITORY / "submissions/02/contest.c").read_bytes()
            ).hexdigest(),
        },
        "probe_source": {
            "path": "submissions/02/src/optimization/two_round_chain_probe.c",
            "sha256": hashlib.sha256(
                SCRIPT.with_name("two_round_chain_probe.c").read_bytes()
            ).hexdigest(),
        },
        "definition": "T(r,k,a,x) = BSWAP64(ROL64(x,r) xor k) + a mod 2^64",
        "chains": formulas,
        "official_vector_check": official_vector_checks(),
        "random_identity_check": random_identity_checks(args.random_cases),
        "witnesses": {
            "seed": f"0x{WITNESS_SEED:016x}",
            "values": [f"0x{value:016x}" for value in witnesses],
            "sha256_little_endian_u64": hashlib.sha256(witness_bytes).hexdigest(),
        },
        "solver": {
            "name": "Z3",
            "version": z3.get_version_string(),
            "timeout_ms_per_check": args.solver_timeout_ms,
            "method": (
                "64-bit CEGIS; UNSAT on the finite witness constraints is already "
                "a valid obstruction to a universal identity"
            ),
        },
        "measurement_scope": {
            "host_timing_executed": False,
            "codegen_only": True,
            "note": "Compiler outputs are disassembled but never benchmarked.",
        },
        "stage_length_three_search": stage_superoptimization(
            witnesses, args.solver_timeout_ms
        ),
        "pair_single_deletion_search": pair_single_deletion_search(
            witnesses, args.solver_timeout_ms
        ),
        "xor_add_reordering": xor_add_reordering_search(
            witnesses, args.solver_timeout_ms
        ),
        "pair_boundary_commutation": boundary_commutation_search(
            witnesses, args.solver_timeout_ms
        ),
        "linear_skeleton_exhaustive": linear_skeleton_search(),
        "immediate_encoding": immediate_analysis(),
    }

    if not args.skip_codegen:
        with tempfile.TemporaryDirectory(prefix="challenge-chain-codegen-") as raw:
            temporary = Path(raw)
            report["codegen"] = {
                "gcc": compiler_codegen(args.gcc, args.objdump, temporary),
                "clang": compiler_codegen(args.clang, args.objdump, temporary),
            }
        report["codegen_observations"] = {
            compiler: {
                "dynamic_chain_core_instruction_count": sum(
                    report["codegen"][compiler]["probe_functions"][
                        "chain_baseline"
                    ]["core_counts"].values()
                ),
                "post_bswap_core_instruction_count": sum(
                    report["codegen"][compiler]["probe_functions"][
                        "chain_post_bswap"
                    ]["core_counts"].values()
                ),
                "pre_rotate_core_instruction_count": sum(
                    report["codegen"][compiler]["probe_functions"][
                        "chain_pre_rotate"
                    ]["core_counts"].values()
                ),
                "literal_chain_movabs": report["codegen"][compiler][
                    "probe_functions"
                ]["chain_literal_x0"]["movabs"],
                "contest_loop_instructions": report["codegen"][compiler][
                    "contest_timing_loop_audit"
                ]["loop_instructions"],
                "contest_loop_bytes": report["codegen"][compiler][
                    "contest_timing_loop_audit"
                ]["loop_bytes"],
                "contest_loop_memory_operands": report["codegen"][compiler][
                    "contest_timing_loop_audit"
                ]["memory_operands_excluding_lea"],
                "contest_loop_movabs": report["codegen"][compiler][
                    "contest_timing_loop_audit"
                ]["mnemonics"].get("movabs", 0),
                "contest_loop_audit_status": report["codegen"][compiler][
                    "contest_timing_loop_audit"
                ]["status"],
            }
            for compiler in ("gcc", "clang")
            if report["codegen"][compiler]["status"] == "PASS"
        }

    stage_closed = report["stage_length_three_search"]["all_templates_unsat"]
    deletion_closed = report["pair_single_deletion_search"]["all_deletions_unsat"]
    linear_closed = report["linear_skeleton_exhaustive"][
        "all_pair_skeletons_need_four"
    ]
    report["conclusion"] = {
        "candidate_found": False,
        "one_stage_lower_bound_in_grammar": 4 if stage_closed else None,
        "original_pair_single_deletion_rejected": deletion_closed,
        "global_two_stage_lower_bound": None,
        "linear_pair_lower_bound_in_rotate_bswap_grammar": 4
        if linear_closed
        else None,
        "scope": (
            "The pair search proves that no one of the original eight operations can "
            "simply be deleted while retaining the other rotations/order and "
            "resynthesizing all remaining constants. It is not a global eight-op "
            "lower bound against every reordered program, nor a claim about an ISA "
            "outside ADD/XOR/ROL/BSWAP."
        ),
    }

    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(encoded, encoding="utf-8")
        print(f"json={args.json.resolve()}")
    else:
        print(encoded, end="")
    print(
        "stage_length3_all_unsat="
        f"{report['stage_length_three_search']['all_templates_unsat']}"
    )
    print(
        "pair_single_deletion_all_unsat="
        f"{report['pair_single_deletion_search']['all_deletions_unsat']}"
    )
    print(
        "linear_pair_needs_four="
        f"{report['linear_skeleton_exhaustive']['all_pair_skeletons_need_four']}"
    )


if __name__ == "__main__":
    main()
