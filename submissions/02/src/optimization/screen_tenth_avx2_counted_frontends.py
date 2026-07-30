#!/usr/bin/env python3
"""Reproduce the challenge-2 tenth-pass counted AVX2 frontend screen.

The screen crosses pair-block sizes 1..10 with quotient/remainder lowering,
adds the two rel8-encodable x86 LOOP controls, and retains the prior 549-byte
full-inline stream.  Exact GCC 13.3 binaries are checked against official
vectors and 100,000 arbitrary states/constants at one and twenty rounds.  The
reported timing loop, padding-excluded dynamic trace, and LLVM-MCA inputs are
all hash-bound.  Generated build products remain in a temporary directory.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = Path(__file__).resolve()
DEFAULT_JSON = SCRIPT.with_name("tenth_avx2_counted_frontends_results.json")

IMAGE_DIGEST = "sha256:1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
IMAGE = f"gcc@{IMAGE_DIGEST}"
EXPECTED_IMAGE_REPODIGEST = f"gcc@{IMAGE_DIGEST}"
HELPER_RELATIVE = "submissions/02/src/optimization/screen_avx2_pair_blocks.py"
HELPER_SHA256 = "ceca3c841a441c8e7f41cd07a91f25eefd7620ac2f28caef9986d6b47b45bfa4"

DEPENDENCIES = {
    "template_candidate": (
        "submissions/02/src/optimization/contest_simd_avx2_pair_block3_tail1.c",
        "0949c99dc62759259244b31a0c2644ddbdf0682437585c674dd6d2dbb15bc559",
    ),
    "block2_candidate": (
        "submissions/02/src/optimization/contest_simd_avx2_pair_block2_counted.c",
        "154b2e449296c6130bf8e108a949443fb901ac6479f4e028cbf7420d9d109c60",
    ),
    "block5_candidate": (
        "submissions/02/src/optimization/contest_simd_avx2_pair_block5_counted.c",
        "5e7404a3319b6efb097002d7ddc67719387fa85d85e8a01ab32ec63e9dded3b1",
    ),
    "full_inline_source": (
        "submissions/02/src/optimization/contest_simd_avx2_inline_asm.c",
        "c6f43f26dcf1bb0cd83d51dd52495e264c6b8303c0b06e89cb84b1cae62d45dc",
    ),
    "candidate_verifier": (
        "submissions/02/src/optimization/verify_contest_candidate.c",
        "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35",
    ),
    "loop_audit": (
        "submissions/02/src/loop_audit.py",
        "8b4e1e90af9d4224500ead177bc02ddc5912805757ce2137ab89a990af0128b1",
    ),
    "problem_archive": (
        "submissions/02/src/2_암호구현.zip",
        "d0c3158adda8ba258becfc0e347267c0f2f0112738ec732be6dcb5477342e88e",
    ),
    "screen_helper": (HELPER_RELATIVE, HELPER_SHA256),
}

COMMON_FLAGS = [
    "-O3",
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-mavx2",
    "-DCH2_SIMD_INLINE",
    "-finline-limit=2000",
]
VERIFIER_FLAGS = [
    "-O3",
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
]
RANDOM_CASES = 100_000
MCA_MODELS = ["alderlake", "znver2"]
MCA_ITERATIONS = 100
CONTAINER_TIMEOUT_SECONDS = 900
CONTAINER_COMMAND_TIMEOUT_SECONDS = 180

EXPECTED_VERIFIER_STDOUT = """candidate_random_differential_cases=100000
candidate_random_seed=0x243f6a8885a308d3
candidate_random_state_and_constants=PASS
candidate_round_counts=1,20
candidate_differential=PASS
"""
EXPECTED_OFFICIAL_LINES = [
    "one-round testvector verification: OK (1000 pairs checked)",
    "20-round testvector verification: OK",
    (
        "benchmark final state = 407b6c00d4644ffb 7b5eeeeb7bbbfd53 "
        "787627ff592edbdb 942319215bb84f88"
    ),
]

EXPECTED_STATIC = {
    "full_inline": (549, 122),
    "dec_block1_tail0": (68, 17),
    "dec_block2_tail0": (122, 29),
    "dec_block3_tail1": (238, 53),
    "dec_block4_tail2": (346, 77),
    "dec_block5_tail0": (292, 65),
    **{f"dec_block{block}_tail{10 - block}": (562, 125)
       for block in range(6, 11)},
    "loop_block1_tail0": (66, 16),
    "loop_block2_tail0": (120, 28),
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_helper() -> Any:
    path = ROOT / HELPER_RELATIVE
    actual = sha256_file(path)
    if actual != HELPER_SHA256:
        raise RuntimeError(
            f"screen helper: expected {HELPER_SHA256}, got {actual}: {path}"
        )
    spec = importlib.util.spec_from_file_location(
        "challenge_tenth_pair_helper", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELPER = load_helper()


def snapshot_dependencies() -> tuple[
    dict[str, dict[str, str]], dict[str, bytes]
]:
    reports: dict[str, dict[str, str]] = {}
    payloads: dict[str, bytes] = {}
    for name, (relative, expected) in DEPENDENCIES.items():
        payload = (ROOT / relative).read_bytes()
        actual = sha256_bytes(payload)
        if actual != expected:
            raise RuntimeError(
                f"{name}: expected {expected}, got {actual}: {relative}"
            )
        reports[name] = {"path": relative, "sha256": actual}
        payloads[name] = payload
    return reports, payloads


def ensure_inputs_unchanged(
    reports: dict[str, dict[str, str]], script_sha256: str
) -> None:
    if sha256_file(SCRIPT) != script_sha256:
        raise RuntimeError("screen script changed during the experiment")
    for name, report in reports.items():
        actual = sha256_file(ROOT / report["path"])
        if actual != report["sha256"]:
            raise RuntimeError(
                f"{name} changed during the experiment: "
                f"expected {report['sha256']}, got {actual}"
            )


def kernel_extent(source: str) -> tuple[int, int]:
    begin = "/* TENTH_COUNTED_KERNEL_BEGIN */"
    finish = "/* TENTH_COUNTED_KERNEL_END */"
    start = source.index(begin)
    end = source.index(finish, start) + len(finish)
    return start, end


def render_kernel(control: str, block: int, quotient: int, remainder: int) -> str:
    if control not in {"dec", "loop"}:
        raise ValueError(f"unsupported control: {control}")
    if quotient * block + remainder != 10:
        raise ValueError("pair decomposition must total ten")
    if control == "loop" and block > 2:
        raise ValueError("x86 LOOP only has a rel8 target; block must be <= 2")

    label = f".Ltenth_{control}_block{block}_%="
    body = "        INLINE_ASM_PAIR()\n" * block
    tail = "        INLINE_ASM_PAIR()\n" * remainder
    if control == "dec":
        branch = (
            '        "decl %[blocks]\\n\\t"\n'
            f'        "jne {label}\\n\\t"\n'
        )
        constraint = "=&r"
    else:
        branch = f'        "loop {label}\\n\\t"\n'
        constraint = "=&c"

    assembly = (
        "    __asm__(\n"
        f'        "movl ${quotient}, %[blocks]\\n\\t"\n'
        f'        "{label}:\\n\\t"\n'
        f"{body}"
        f"{branch}"
        f"{tail}"
        '        : [value] "+x"(value), [scratch] "=&x"(scratch),\n'
        f'          [blocks] "{constraint}"(blocks)\n'
        '        : [xor_forward] "x"(xor_forward), '
        '[add_reverse] "x"(add_reverse),\n'
        '          [xor_reverse] "x"(xor_reverse), '
        '[add_forward] "x"(add_forward),\n'
        '          [left_forward] "x"(left_forward), '
        '[right_forward] "x"(right_forward),\n'
        '          [left_reverse] "x"(left_reverse), '
        '[right_reverse] "x"(right_reverse),\n'
        '          [byte_swap] "x"(byte_swap)\n'
        '        : "cc");'
    )
    return (
        "/* TENTH_COUNTED_KERNEL_BEGIN */\n"
        f"{assembly}\n"
        "/* TENTH_COUNTED_KERNEL_END */"
    )


def generate_sources(
    temporary: Path, payloads: dict[str, bytes]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    source_dir = temporary / "sources"
    source_dir.mkdir()
    template = payloads["template_candidate"].decode()
    block2_wrapper = payloads["block2_candidate"]
    block5_wrapper = payloads["block5_candidate"]
    start, end = kernel_extent(template)
    cases: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}

    full = payloads["full_inline_source"]
    (source_dir / "full_inline.c").write_bytes(full)
    hashes["full_inline"] = sha256_bytes(full)
    cases.append(
        {
            "name": "full_inline",
            "source": "sources/full_inline.c",
            "source_sha256": hashes["full_inline"],
            "control": "none",
            "block_pairs": 10,
            "quotient": 1,
            "remainder_pairs": 0,
            "persistent_source": DEPENDENCIES["full_inline_source"][0],
        }
    )

    template_name = Path(DEPENDENCIES["template_candidate"][0]).name
    block2_wrapper_name = Path(DEPENDENCIES["block2_candidate"][0]).name
    block5_wrapper_name = Path(DEPENDENCIES["block5_candidate"][0]).name
    (source_dir / template_name).write_bytes(payloads["template_candidate"])
    (source_dir / block2_wrapper_name).write_bytes(block2_wrapper)
    (source_dir / block5_wrapper_name).write_bytes(block5_wrapper)

    for block in range(1, 11):
        quotient, remainder = divmod(10, block)
        name = f"dec_block{block}_tail{remainder}"
        if block == 2:
            data = block2_wrapper
            source = f"sources/{block2_wrapper_name}"
            persistent_source = DEPENDENCIES["block2_candidate"][0]
            included_sources = [
                {
                    "source": f"sources/{template_name}",
                    "persistent_source": DEPENDENCIES[
                        "template_candidate"
                    ][0],
                    "sha256": DEPENDENCIES["template_candidate"][1],
                }
            ]
        elif block == 3:
            data = payloads["template_candidate"]
            source = f"sources/{template_name}"
            persistent_source = DEPENDENCIES["template_candidate"][0]
            included_sources: list[dict[str, str]] = []
        elif block == 5:
            data = block5_wrapper
            source = f"sources/{block5_wrapper_name}"
            persistent_source = DEPENDENCIES["block5_candidate"][0]
            included_sources = [
                {
                    "source": f"sources/{template_name}",
                    "persistent_source": DEPENDENCIES[
                        "template_candidate"
                    ][0],
                    "sha256": DEPENDENCIES["template_candidate"][1],
                }
            ]
        else:
            kernel = render_kernel("dec", block, quotient, remainder)
            data = (template[:start] + kernel + template[end:]).encode()
            source = f"sources/{name}.c"
            persistent_source = None
            included_sources = []
            (source_dir / f"{name}.c").write_bytes(data)
        hashes[name] = sha256_bytes(data)
        cases.append(
            {
                "name": name,
                "source": source,
                "source_sha256": hashes[name],
                "control": "dec/jne",
                "block_pairs": block,
                "quotient": quotient,
                "remainder_pairs": remainder,
                "persistent_source": persistent_source,
                "included_sources": included_sources,
            }
        )

    for block in (1, 2):
        quotient, remainder = divmod(10, block)
        kernel = render_kernel("loop", block, quotient, remainder)
        name = f"loop_block{block}_tail{remainder}"
        data = (template[:start] + kernel + template[end:]).encode()
        (source_dir / f"{name}.c").write_bytes(data)
        hashes[name] = sha256_bytes(data)
        cases.append(
            {
                "name": name,
                "source": f"sources/{name}.c",
                "source_sha256": hashes[name],
                "control": "x86 loop",
                "block_pairs": block,
                "quotient": quotient,
                "remainder_pairs": remainder,
                "persistent_source": None,
            }
        )

    if len(cases) != 13 or len({case["name"] for case in cases}) != 13:
        raise RuntimeError("expected thirteen unique frontend cases")
    return cases, hashes


def extract_vectors(temporary: Path, archive: bytes) -> None:
    vectors = temporary / "vectors"
    vectors.mkdir()
    with ZipFile(io.BytesIO(archive)) as zipped:
        for name in ("testvector.txt", "testvector_20round.txt"):
            (vectors / name).write_bytes(zipped.read(f"code/{name}"))


def materialize_repository(
    temporary: Path, payloads: dict[str, bytes]
) -> Path:
    repository = temporary / "repository-snapshot"
    for name in ("candidate_verifier", "loop_audit"):
        relative = Path(DEPENDENCIES[name][0])
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payloads[name])
    return repository


CONTAINER_DRIVER = textwrap.dedent(
    r"""
    import concurrent.futures
    import hashlib
    import json
    import re
    import subprocess
    import sys
    from pathlib import Path

    work = Path("/work")
    config = json.loads((work / "config.json").read_text())
    artifacts = work / "artifacts"
    artifacts.mkdir()
    sys.path.insert(0, "/repository/solutions")
    from loop_audit import audit_main_timing_loop

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def run(command, cwd=None):
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=config["command_timeout_seconds"],
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"command timed out: {command}"
            ) from error
        if completed.returncode:
            raise RuntimeError(
                f"command failed ({completed.returncode}): {command}\n"
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        return completed

    for relative, expected in config["repository_hashes"].items():
        actual = digest(Path("/repository") / relative)
        if actual != expected:
            raise RuntimeError(
                f"repository hash mismatch for {relative}: "
                f"expected {expected}, got {actual}"
            )

    verifier_object = artifacts / "verifier.o"
    run([
        "gcc", *config["verifier_flags"], "-c",
        "/repository/submissions/02/src/optimization/verify_contest_candidate.c",
        "-o", str(verifier_object),
    ])

    def extract_loop(assembly, destination):
        text = assembly.read_text()
        clocks = [
            match.start()
            for match in re.finditer(
                r"^\s*call\s+clock(?:@PLT)?\s*$", text, re.MULTILINE
            )
        ]
        if len(clocks) < 2:
            raise RuntimeError(f"{assembly}: expected two clock calls")
        region = text[clocks[-2]:clocks[-1]]
        backedges = list(
            re.finditer(r"^\s*jne\s+(\.L\d+)\s*$", region, re.MULTILINE)
        )
        if not backedges:
            raise RuntimeError(f"{assembly}: outer backedge not found")
        target = backedges[-1].group(1)
        start = region.index(target + ":")
        end = backedges[-1].end()
        loop = ".text\n" + region[start:end] + "\n"
        destination.write_text(loop)
        return loop

    def compile_case(item):
        name = item["name"]
        source = work / item["source"]
        assembly = artifacts / f"{name}.s"
        binary_object = artifacts / f"{name}.binary.o"
        binary = artifacts / f"{name}.bin"
        candidate_object = artifacts / f"{name}.candidate.o"
        verifier = artifacts / f"{name}.verify"
        loop = artifacts / f"{name}.loop.s"

        actual_source = digest(source)
        if actual_source != item["source_sha256"]:
            raise RuntimeError(
                f"{name}: expected source {item['source_sha256']}, "
                f"got {actual_source}"
            )
        for included in item.get("included_sources", []):
            actual_include = digest(work / included["source"])
            if actual_include != included["sha256"]:
                raise RuntimeError(
                    f"{name}: expected included source "
                    f"{included['sha256']}, got {actual_include}: "
                    f"{included['source']}"
                )
        run(["gcc", *config["common_flags"], "-S", str(source), "-o", str(assembly)])
        run(["gcc", "-c", str(assembly), "-o", str(binary_object)])
        run(["gcc", str(binary_object), "-o", str(binary)])
        audit = audit_main_timing_loop(
            binary, objdump="objdump", size_tool="size"
        )
        loop_text = extract_loop(assembly, loop)

        run([
            "gcc", *config["common_flags"], "-Dmain=contest_candidate_main",
            "-c", str(source), "-o", str(candidate_object),
        ])
        run([
            "gcc", str(candidate_object), str(verifier_object),
            "-o", str(verifier),
        ])
        verification = run([str(verifier), str(config["random_cases"])])
        official = run([str(binary)], cwd=work / "vectors")
        if (
            verification.stdout != config["verifier_stdout"]
            or verification.stderr
        ):
            raise RuntimeError(f"{name}: random differential verification failed")
        if (
            official.stderr
            or "MISMATCH" in official.stdout
            or not all(
                marker in official.stdout
                for marker in config["official_lines"]
            )
        ):
            raise RuntimeError(f"{name}: official verification failed")
        return {
            **item,
            "source_sha256": actual_source,
            "assembly_sha256": digest(assembly),
            "binary_audit": audit,
            "loop_text_sha256": hashlib.sha256(
                loop_text.encode()
            ).hexdigest(),
            "loop_artifact": f"artifacts/{name}.loop.s",
            "measured_binary_assembled_from_reported_assembly": True,
            "verification": {
                "status": "PASS",
                "random_cases": config["random_cases"],
                "random_state_and_constants": True,
                "round_counts": [1, 20],
                "stdout_sha256": hashlib.sha256(
                    verification.stdout.encode()
                ).hexdigest(),
                "stderr": verification.stderr,
            },
            "official_vectors": {
                "status": "PASS",
                "one_round_pairs": 1000,
                "twenty_round_vectors": 1,
                "required_stdout_lines": config["official_lines"],
                "validated_stdout_lines_sha256": hashlib.sha256(
                    (
                        "\n".join(config["official_lines"]) + "\n"
                    ).encode()
                ).hexdigest(),
                "stderr": official.stderr,
            },
        }

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=config["jobs"]
    ) as pool:
        rows = list(pool.map(compile_case, config["cases"]))
    rows.sort(key=lambda row: row["name"])

    def tool(name):
        path = Path(run(["which", name]).stdout.strip()).resolve()
        return {
            "resolved": str(path),
            "sha256": digest(path),
            "version": run([str(path), "--version"]).stdout.splitlines()[0],
        }

    output = {
        "cases": {row["name"]: row for row in rows},
        "compiler": tool("gcc"),
        "binutils": {
            name: tool(name) for name in ("ld", "objdump", "size")
        },
        "python": tool("python3"),
    }
    (work / "container-results.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    """
)


def run_container(
    runtime: str,
    temporary: Path,
    repository: Path,
    dependencies: dict[str, dict[str, str]],
    cases: list[dict[str, Any]],
    jobs: int,
) -> dict[str, Any]:
    config = {
        "cases": cases,
        "command_timeout_seconds": CONTAINER_COMMAND_TIMEOUT_SECONDS,
        "common_flags": COMMON_FLAGS,
        "jobs": jobs,
        "official_lines": EXPECTED_OFFICIAL_LINES,
        "random_cases": RANDOM_CASES,
        "repository_hashes": {
            dependencies[name]["path"]: dependencies[name]["sha256"]
            for name in ("candidate_verifier", "loop_audit")
        },
        "verifier_flags": VERIFIER_FLAGS,
        "verifier_stdout": EXPECTED_VERIFIER_STDOUT,
    }
    (temporary / "config.json").write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n"
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
        f"{repository}:/repository:ro",
        "--volume",
        f"{temporary}:/work",
        "--workdir",
        "/work",
        IMAGE,
        "python3",
        "-c",
        CONTAINER_DRIVER,
    ]
    HELPER.checked(command, timeout=CONTAINER_TIMEOUT_SECONDS)
    return json.loads((temporary / "container-results.json").read_text())


def clean_assembly_lines(path: Path) -> list[str]:
    lines: list[str] = []
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if (
            not stripped
            or stripped == ".text"
            or stripped.startswith("#")
            or stripped.startswith(".p2align ")
        ):
            continue
        if stripped.startswith(".") and not stripped.endswith(":"):
            raise RuntimeError(f"unsupported loop directive: {raw!r}")
        lines.append(stripped)
    return lines


def rewrite_branch(instruction: str) -> str:
    if instruction.startswith("jne ") or instruction.startswith("loop "):
        return instruction.split()[0] + " .Ltrace"
    return instruction


def expand_dynamic_trace(
    path: Path, case: dict[str, Any], destination: Path
) -> dict[str, Any]:
    lines = clean_assembly_lines(path)
    if not lines or not lines[0].endswith(":"):
        raise RuntimeError(f"{case['name']}: outer loop label missing")

    inner_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith(".Ltenth_") and line.endswith(":")
        ),
        None,
    )
    if case["control"] == "none":
        if inner_index is not None:
            raise RuntimeError("full-inline case unexpectedly has an inner loop")
        dynamic = [
            rewrite_branch(line)
            for line in lines[1:]
            if not line.endswith(":")
        ]
    else:
        if inner_index is None or inner_index == 0:
            raise RuntimeError(f"{case['name']}: inner loop label missing")
        label = lines[inner_index][:-1]
        prefix = [
            line for line in lines[1:inner_index] if not line.endswith(":")
        ]
        if len(prefix) != 1:
            raise RuntimeError(
                f"{case['name']}: expected one inner-loop setup instruction"
            )
        move = re.fullmatch(
            r"movl\s+\$([0-9]+),\s*(%[A-Za-z0-9]+)", prefix[0]
        )
        if not move or int(move.group(1)) != case["quotient"]:
            raise RuntimeError(
                f"{case['name']}: unexpected inner-loop count setup {prefix[0]!r}"
            )
        if case["control"] == "dec/jne":
            branch_index = next(
                index
                for index in range(inner_index + 1, len(lines))
                if lines[index] == f"jne {label}"
            )
            control_start = branch_index - 1
            if not lines[control_start].startswith("decl "):
                raise RuntimeError(f"{case['name']}: DEC control missing")
        else:
            branch_index = next(
                index
                for index in range(inner_index + 1, len(lines))
                if lines[index] == f"loop {label}"
            )
            control_start = branch_index

        body = lines[inner_index + 1:control_start]
        control = lines[control_start:branch_index + 1]
        tail = [
            line
            for line in lines[branch_index + 1:]
            if not line.endswith(":")
        ]
        if len(body) != 12 * case["block_pairs"]:
            raise RuntimeError(
                f"{case['name']}: expected {12 * case['block_pairs']} "
                f"body instructions, got {len(body)}"
            )
        if len(tail) != 12 * case["remainder_pairs"] + 2:
            raise RuntimeError(
                f"{case['name']}: unexpected tail/outer-control length"
            )
        dynamic = prefix.copy()
        for _ in range(case["quotient"]):
            dynamic.extend(body)
            dynamic.extend(rewrite_branch(line) for line in control)
        dynamic.extend(rewrite_branch(line) for line in tail)

    counts = Counter(line.split()[0] for line in dynamic)
    for mnemonic in (
        "vpsllvq",
        "vpsrlvq",
        "vpor",
        "vpxor",
        "vpshufb",
        "vpaddq",
    ):
        if counts[mnemonic] != 20:
            raise RuntimeError(
                f"{case['name']}: dynamic {mnemonic}={counts[mnemonic]}, "
                "expected 20"
            )
    expected = (
        122
        if case["control"] == "none"
        else (
            123 + 2 * case["quotient"]
            if case["control"] == "dec/jne"
            else 123 + case["quotient"]
        )
    )
    if len(dynamic) != expected:
        raise RuntimeError(
            f"{case['name']}: dynamic instructions={len(dynamic)}, "
            f"expected {expected}"
        )
    rendered = (
        ".text\n.Ltrace:\n"
        + "".join(f"\t{instruction}\n" for instruction in dynamic)
    )
    destination.write_text(rendered)
    return {
        "method": (
            "exact-GCC-assembly-CFG-expansion-one-outer-iteration-v1"
        ),
        "instruction_scope": "modeled non-padding instructions",
        "alignment_padding_excluded": True,
        "instructions": len(dynamic),
        "mnemonics": dict(sorted(counts.items())),
        "sha256": sha256_bytes(rendered.encode()),
    }


def add_dynamic_and_mca(
    temporary: Path,
    container: dict[str, Any],
    case_specs: list[dict[str, Any]],
    llvm_mca: str,
) -> dict[str, Any]:
    specs = {case["name"]: case for case in case_specs}
    output: dict[str, Any] = {}
    for name, raw in sorted(container["cases"].items()):
        report = dict(raw)
        loop_path = temporary / report.pop("loop_artifact")
        trace_path = temporary / f"{name}.dynamic.s"
        trace = expand_dynamic_trace(loop_path, specs[name], trace_path)
        nops = sum(
            count
            for mnemonic, count in report["binary_audit"]["mnemonics"].items()
            if mnemonic.startswith("nop")
        )
        trace["binary_alignment_nop_instructions"] = nops
        trace["instructions_including_binary_alignment_nops"] = (
            trace["instructions"] + nops
        )
        report["dynamic_trace"] = trace
        report["llvm_mca"] = {
            model: HELPER.analyse_mca(llvm_mca, trace_path, model)
            for model in MCA_MODELS
        }
        output[name] = report
    return output


def pareto_frontier(
    cases: dict[str, Any], names: list[str]
) -> list[str]:
    def metrics(name: str) -> tuple[float, float, float]:
        case = cases[name]
        return (
            float(case["binary_audit"]["loop_bytes"]),
            float(case["dynamic_trace"]["instructions"]),
            float(case["llvm_mca"]["alderlake"]["block_rthroughput"]),
        )

    frontier = []
    for name in names:
        own = metrics(name)
        dominated = any(
            all(left <= right for left, right in zip(metrics(other), own))
            and any(left < right for left, right in zip(metrics(other), own))
            for other in names
            if other != name
        )
        if not dominated:
            frontier.append(name)
    return sorted(frontier)


def validate_output(output: dict[str, Any]) -> dict[str, bool]:
    cases = output["cases"]
    shared_include = [
        {
            "source": (
                "sources/"
                "contest_simd_avx2_pair_block3_tail1.c"
            ),
            "persistent_source": (
                "submissions/02/src/optimization/"
                "contest_simd_avx2_pair_block3_tail1.c"
            ),
            "sha256": output["sources"]["dependencies"][
                "template_candidate"
            ]["sha256"],
        }
    ]
    checks: dict[str, bool] = {}
    checks["all_thirteen_cases_present"] = set(cases) == set(EXPECTED_STATIC)
    checks["all_sources_hash_bound"] = all(
        report["source_sha256"]
        == output["sources"]["generated_source_hashes"][name]
        for name, report in cases.items()
    )
    checks["retained_candidates_are_exact_case_sources"] = (
        cases["dec_block2_tail0"]["source_sha256"]
        == output["sources"]["dependencies"]["block2_candidate"]["sha256"]
        and cases["dec_block2_tail0"]["included_sources"] == shared_include
        and cases["dec_block3_tail1"]["source_sha256"]
        == output["sources"]["dependencies"]["template_candidate"]["sha256"]
        and cases["dec_block5_tail0"]["source_sha256"]
        == output["sources"]["dependencies"]["block5_candidate"]["sha256"]
        and cases["dec_block5_tail0"]["included_sources"] == shared_include
    )
    checks["all_official_vectors_pass"] = all(
        case["official_vectors"]["status"] == "PASS"
        and case["official_vectors"]["one_round_pairs"] == 1000
        and case["official_vectors"]["twenty_round_vectors"] == 1
        for case in cases.values()
    )
    checks["all_random_differentials_pass"] = all(
        case["verification"]["status"] == "PASS"
        and case["verification"]["random_cases"] == RANDOM_CASES
        and case["verification"]["random_state_and_constants"] is True
        and case["verification"]["round_counts"] == [1, 20]
        for case in cases.values()
    )
    checks["all_exact_static_shapes_match"] = all(
        (
            cases[name]["binary_audit"]["loop_bytes"],
            cases[name]["binary_audit"]["loop_instructions"],
        )
        == expected
        and cases[name]["binary_audit"]["calls"] == 0
        and cases[name]["binary_audit"]["push_pop"] == 0
        and cases[name]["binary_audit"]["memory_operands_excluding_lea"] == 0
        for name, expected in EXPECTED_STATIC.items()
    )
    checks["all_measured_binaries_use_reported_assembly"] = all(
        case["measured_binary_assembled_from_reported_assembly"] is True
        for case in cases.values()
    )
    checks["all_dynamic_traces_have_twenty_transforms"] = all(
        all(
            case["dynamic_trace"]["mnemonics"].get(mnemonic) == 20
            for mnemonic in (
                "vpsllvq",
                "vpsrlvq",
                "vpor",
                "vpxor",
                "vpshufb",
                "vpaddq",
            )
        )
        and case["dynamic_trace"]["alignment_padding_excluded"] is True
        for case in cases.values()
    )
    checks["mca_instruction_counts_match_dynamic_traces"] = all(
        case["llvm_mca"][model]["iterations"] == MCA_ITERATIONS
        and case["llvm_mca"][model]["instructions_per_iteration"]
        == case["dynamic_trace"]["instructions"]
        for case in cases.values()
        for model in MCA_MODELS
    )
    checks["conventional_controls_keep_proxy_latency"] = all(
        cases[name]["llvm_mca"]["alderlake"]["cycles_per_iteration"] == 100.03
        and cases[name]["llvm_mca"]["znver2"]["cycles_per_iteration"] == 180.03
        for name in cases
        if name == "full_inline" or name.startswith("dec_")
    )
    checks["loop_controls_have_expected_proxy_latency"] = (
        cases["loop_block1_tail0"]["llvm_mca"]["alderlake"][
            "cycles_per_iteration"
        ]
        == 100.07
        and cases["loop_block2_tail0"]["llvm_mca"]["alderlake"][
            "cycles_per_iteration"
        ]
        == 100.03
        and all(
            cases[name]["llvm_mca"]["znver2"]["cycles_per_iteration"] == 180.03
            for name in ("loop_block1_tail0", "loop_block2_tail0")
        )
    )
    checks["block3_strictly_dominates_prior_intrinsic_block5_shape"] = (
        cases["dec_block3_tail1"]["binary_audit"]["loop_bytes"] < 321
        and cases["dec_block3_tail1"]["binary_audit"]["loop_instructions"] < 69
        and cases["dec_block3_tail1"]["dynamic_trace"]["instructions"] < 131
    )
    checks["block2_strictly_dominates_prior_intrinsic_block2_shape"] = (
        cases["dec_block2_tail0"]["binary_audit"]["loop_bytes"] < 136
        and cases["dec_block2_tail0"]["binary_audit"][
            "loop_instructions"
        ] < 30
        and cases["dec_block2_tail0"]["dynamic_trace"]["instructions"] == 133
    )
    checks["loop_frontend_penalty_is_visible_on_alderlake"] = (
        cases["loop_block1_tail0"]["llvm_mca"]["alderlake"][
            "block_rthroughput"
        ]
        > cases["dec_block1_tail0"]["llvm_mca"]["alderlake"][
            "block_rthroughput"
        ]
        and cases["loop_block2_tail0"]["llvm_mca"]["alderlake"][
            "block_rthroughput"
        ]
        > cases["dec_block2_tail0"]["llvm_mca"]["alderlake"][
            "block_rthroughput"
        ]
    )
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"screen validation failed: {failed}")
    return checks


def build_output(args: argparse.Namespace) -> dict[str, Any]:
    script_sha256 = sha256_file(SCRIPT)
    dependencies, payloads = snapshot_dependencies()
    runtime_report, image_id = HELPER.inspect_runtime(args.runtime)
    mca_report = HELPER.inspect_llvm_mca(args.llvm_mca)
    python_report = HELPER.inspect_host_tool("python3", sys.executable)

    with tempfile.TemporaryDirectory(prefix="ch2-tenth-counted-") as raw:
        temporary = Path(raw).resolve()
        case_specs, source_hashes = generate_sources(temporary, payloads)
        extract_vectors(temporary, payloads["problem_archive"])
        repository = materialize_repository(temporary, payloads)
        container = run_container(
            runtime_report["resolved"],
            temporary,
            repository,
            dependencies,
            case_specs,
            args.jobs,
        )
        cases = add_dynamic_and_mca(
            temporary,
            container,
            case_specs,
            mca_report["resolved"],
        )

    ensure_inputs_unchanged(dependencies, script_sha256)
    conventional = [
        name
        for name in cases
        if name == "full_inline" or name.startswith("dec_")
    ]
    all_frontends = sorted(cases)
    output: dict[str, Any] = {
        "schema_version": 1,
        "experiment": (
            "challenge-2 tenth-pass AVX2 quotient/remainder counted frontends"
        ),
        "scope": (
            "single-state 20-round contest-fixed rotation/reversal "
            "permutation; exact GCC 13.3 static measured-loop audit, official "
            "vectors, 100,000 arbitrary-state/arbitrary-constant differential "
            "cases at rounds 1/20, and LLVM-MCA proxies; no 255H timing"
        ),
        "protocol": {
            "pair_decompositions": (
                "DEC/JNE block sizes 1..10 using quotient=floor(10/block) "
                "plus inline remainder"
            ),
            "alternative_controls": (
                "x86 LOOP for block sizes 1 and 2 only; larger bodies exceed "
                "LOOP's signed rel8 branch reach"
            ),
            "random_cases_per_case": RANDOM_CASES,
            "random_seed": "0x243f6a8885a308d3",
            "round_counts": [1, 20],
            "official_one_round_pairs": 1000,
            "official_twenty_round_vectors": 1,
            "mca_models": MCA_MODELS,
            "mca_iterations": MCA_ITERATIONS,
            "dynamic_trace_scope": (
                "one exact outer timing-loop iteration; emitted alignment "
                "padding excluded and separately accounted for"
            ),
            "container_timeout_seconds": CONTAINER_TIMEOUT_SECONDS,
            "container_command_timeout_seconds": (
                CONTAINER_COMMAND_TIMEOUT_SECONDS
            ),
            "input_snapshot": (
                "all dependencies loaded once; generated/container inputs "
                "materialized from that snapshot; live inputs rehashed at end"
            ),
            "temporary_artifacts_retained": False,
        },
        "sources": {
            "dependencies": dependencies,
            "screen_script": {
                "path": str(SCRIPT.relative_to(ROOT)),
                "sha256": script_sha256,
            },
            "container_driver_sha256": sha256_bytes(
                CONTAINER_DRIVER.encode()
            ),
            "generated_source_hashes": dict(sorted(source_hashes.items())),
        },
        "environment": {
            "container_image": {
                "reference": IMAGE,
                "id": image_id,
                "repo_digest": EXPECTED_IMAGE_REPODIGEST,
            },
            "host_tools": {
                "runtime": runtime_report,
                "llvm_mca": mca_report,
                "python": python_report,
            },
            "container_tools": {
                "compiler": container["compiler"],
                "binutils": container["binutils"],
                "python": container["python"],
            },
        },
        "cases": cases,
        "frontiers": {
            "metrics": [
                "static loop bytes",
                "modeled non-padding dynamic instructions",
                "Alder Lake LLVM-MCA block reciprocal throughput",
            ],
            "conventional_dec_and_full": pareto_frontier(
                cases, conventional
            ),
            "including_x86_loop": pareto_frontier(cases, all_frontends),
        },
        "decision": {
            "retained_candidates": [
                "dec_block2_tail0",
                "dec_block3_tail1",
                "dec_block5_tail0",
            ],
            "manifest_candidate_proposals": [
                {
                    "name": "avx2_pair_block2_counted",
                    "source": DEPENDENCIES["block2_candidate"][0],
                    "role": (
                        "four-lane-avx2-two-pairs-by-five-counted-"
                        "frontend-candidate"
                    ),
                    "timing_policy": "target-only",
                },
                {
                    "name": "avx2_pair_block3_tail1",
                    "source": DEPENDENCIES["template_candidate"][0],
                    "role": (
                        "four-lane-avx2-three-pairs-by-three-plus-one-"
                        "compact-frontend-candidate"
                    ),
                    "timing_policy": "target-only",
                },
                {
                    "name": "avx2_pair_block5_counted",
                    "source": DEPENDENCIES["block5_candidate"][0],
                    "role": (
                        "four-lane-avx2-five-pairs-by-two-counted-"
                        "frontend-candidate"
                    ),
                    "timing_policy": "target-only",
                },
            ],
            "block2_interpretation": (
                "2x5 counted inline asm is the smallest persistent "
                "conventional candidate with 133 modeled dynamic "
                "instructions: 122 bytes/29 static, no hot memory, and "
                "unchanged proxy latency. It strictly improves the prior "
                "intrinsic block2 shape (136 bytes/30 static/133 dynamic), "
                "so it remains a target-only timing candidate."
            ),
            "block3_interpretation": (
                "3+3+3+1 is a new conventional-control Pareto point: "
                "238 bytes, 53 static instructions, 129 modeled dynamic "
                "instructions, no hot memory, and unchanged proxy latency. "
                "It strictly improves the prior intrinsic block5 shape "
                "(321 bytes/69 static/131 dynamic), but remains a target-only "
                "candidate pending independent 255H timing."
            ),
            "block5_interpretation": (
                "5+5 is the second retained conventional Pareto point at "
                "292 bytes/65 static/127 dynamic, no hot memory, and unchanged "
                "proxy latency. It preserves the two-instruction dynamic "
                "control advantage over block3; block4 is rejected because "
                "block5 is smaller at the same dynamic count and throughput."
            ),
            "blocks_6_to_10": (
                "reject: quotient one leaves all twenty transforms static and "
                "adds count control, so each is 562 bytes/125 dynamic versus "
                "the 549-byte/122-dynamic full-inline stream."
            ),
            "x86_loop": (
                "do not promote from static evidence: LOOP reaches 66/120 "
                "bytes and 133/128 modeled instructions for block1/block2, "
                "but Alder Lake's model expands its uops and worsens block "
                "throughput; LLVM's Zen 2 LOOP model is also too optimistic "
                "to settle hardware behavior."
            ),
            "mca_caveat": (
                "LLVM-MCA is a static scheduling proxy, not a Core Ultra 7 "
                "255H timing result. It does not establish branch prediction, "
                "frontend/uop-cache residency, frequency, or x86 LOOP behavior "
                "on the contest target; promotion requires schema-5 paired "
                "timing on independent target affinities."
            ),
        },
    }
    output["checks"] = validate_output(output)
    output["all_checks_passed"] = all(output["checks"].values())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--llvm-mca", default="llvm-mca-16")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in temporary storage and compare with canonical JSON",
    )
    args = parser.parse_args()
    if not 1 <= args.jobs <= 4:
        parser.error("--jobs must be between 1 and 4")
    output = build_output(args)
    rendered = json.dumps(output, indent=2, sort_keys=True) + "\n"
    ensure_inputs_unchanged(
        output["sources"]["dependencies"],
        output["sources"]["screen_script"]["sha256"],
    )
    if args.check:
        if not args.json.is_file():
            raise RuntimeError(f"canonical JSON does not exist: {args.json}")
        canonical = args.json.read_text()
        if canonical != rendered:
            raise RuntimeError(
                "regenerated output differs from canonical JSON: "
                f"expected_sha256={sha256_bytes(canonical.encode())} "
                f"actual_sha256={sha256_bytes(rendered.encode())}"
            )
        print(
            f"check=PASS json={args.json} "
            f"sha256={sha256_bytes(rendered.encode())}"
        )
        return 0
    args.json.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.json.with_suffix(args.json.suffix + ".tmp")
    temporary_output.write_text(rendered)
    os.replace(temporary_output, args.json)
    retained = output["cases"]["dec_block3_tail1"]
    print(
        f"wrote={args.json} sha256={sha256_bytes(rendered.encode())} "
        f"cases={len(output['cases'])} "
        f"block3={retained['binary_audit']['loop_bytes']}B/"
        f"{retained['binary_audit']['loop_instructions']}static/"
        f"{retained['dynamic_trace']['instructions']}dynamic"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
