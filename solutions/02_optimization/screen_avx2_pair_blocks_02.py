#!/usr/bin/env python3
"""Reproduce the challenge-2 pair-block and stage-major bounded screen.

All generated C, assembly, binaries, verifier executables, and MCA traces live
in a temporary directory.  The only persistent output is the deterministic
JSON report requested with ``--json``.  The compiler image, repository inputs,
host tools, exact measured loops, and correctness oracle are hash-pinned.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).resolve()
DEFAULT_JSON = SCRIPT.with_name("avx2_pair_block_results_02.json")

IMAGE_DIGEST = "sha256:1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
IMAGE = f"gcc@{IMAGE_DIGEST}"
EXPECTED_IMAGE_REPODIGEST = f"gcc@{IMAGE_DIGEST}"

DEPENDENCIES = {
    "scalar_source": (
        "submissions/02/contest.c",
        "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71",
    ),
    "avx2_source": (
        "solutions/02_optimization/contest_simd_avx2_lanewise.c",
        "3a8273cb6f381efb30fb4e104a9741acf158307714216f2a2b2d8c1756b9d751",
    ),
    "pair_block2_source": (
        "solutions/02_optimization/contest_simd_avx2_pair_block2.c",
        "7064f5cab6ed77587a46965952139978bfbdf713d98bc0c6f51648ece767fdb8",
    ),
    "candidate_verifier": (
        "solutions/02_optimization/verify_contest_candidate_02.c",
        "8245f1baf23fe82e1a1b22dc7c25e5e1fd5b102ca833f26d4c88342088c80b35",
    ),
    "loop_audit": (
        "solutions/challenge02_loop_audit.py",
        "7d14dca7b8d4d4d9dbae96a0a5e49a06b488458293ce927018296cde0216952c",
    ),
    "problem_archive": (
        "problems/2_암호구현.zip",
        "d0c3158adda8ba258becfc0e347267c0f2f0112738ec732be6dcb5477342e88e",
    ),
}

HOST_TOOLS = {
    "docker": {
        "sha256": "d2e14b11c7f003526b80d5d4995f3c2c02161e96014b924d071f928f063d2789",
        "version_prefix": "Docker version 29.1.2",
    },
    "llvm-mca-16": {
        "sha256": "e7f38b12a3c228c8b0bcea0bf63cc56939286adf9ae5397a43d408322e3c6fbf",
        "version_prefix": "Debian LLVM version 16.0.6",
    },
    "python3": {
        "sha256": "6d972cf21be56fe3c947ab6ba257ff8d08c342dd2714442986791bd9a6dfabfe",
        "version_prefix": "Python 3.11.2",
    },
}

AVX_FLAGS = [
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
SCALAR_GENERIC_FLAGS = [
    "-O3",
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
    "-mbmi2",
    "-finline-limit=2000",
]
SCALAR_ALDER_IRA_FLAGS = [
    *SCALAR_GENERIC_FLAGS,
    "-mtune=alderlake",
    "-fira-algorithm=priority",
]
VERIFIER_FLAGS = [
    "-O3",
    "-std=c11",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-Werror",
]
MCA_MODELS = ["alderlake", "znver2"]
MCA_ITERATIONS = 100
RANDOM_CASES = 100_000
HOST_COMMAND_TIMEOUT_SECONDS = 120
CONTAINER_TIMEOUT_SECONDS = 900
CONTAINER_COMMAND_TIMEOUT_SECONDS = 120

DYNAMIC_LOADER = {
    "path": "/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
    "sha256": "02bcda52c1a5dfc236f94d9e5255b4a0e26347d8a372a5223b650e31f291ce3c",
}
LLVM_MCA_DYNAMIC_LIBRARIES = {
    "ld-linux-x86-64.so.2": (
        "02bcda52c1a5dfc236f94d9e5255b4a0e26347d8a372a5223b650e31f291ce3c"
    ),
    "libLLVM-16.so.1": (
        "f62d254b7f2bf42df8c8b07d46ee3bb4c2cafeca436b2e6bc6ccbe4581f58f40"
    ),
    "libbsd.so.0": "c34693b27401e6e74d7ac32184c79bfb0cca936d3b1be990d435124a6a5686f5",
    "libc.so.6": "6b4a45352fd0c540a9c7c718f35ce8c8e46a4e482f9d3885a910c32d1a0e1421",
    "libedit.so.2": "d1633f035639f571895a48a2f9cef073517d8617c2df10b91e686ec24e87c976",
    "libffi.so.8": "983e72b7e964f3db43fe8a3dc8b338e731fade6ca38df6867aebb58186aaeb68",
    "libgcc_s.so.1": "2bd1552c47799ef67e701e81d4383061fd76059868e446e63560f0dd0d5ec14e",
    "libicudata.so.72": (
        "5f572a055d6410ab50fc45770d529109dcc4fe8888f3b2834f76730ff19ebf58"
    ),
    "libicuuc.so.72": (
        "6ae74e03d74c29774be16f877aeba4b8c347ea83d8cb43b730fd283e205b375e"
    ),
    "liblzma.so.5": "983464a4e0e840f85b519cb7b6153b60c75d6473f4d4c32a5a37b3f9894c52c3",
    "libm.so.6": "7f2ca87f652f56b094462474b076749e90e689d0ecb9cb63c7679820b271b4e7",
    "libmd.so.0": "9e8462f7650da0b39ecfe1680fa87fe393f0710b324250931ab36fa0135b14cc",
    "libstdc++.so.6": (
        "e7848e32af4932840ba775169041759a2a8dd5a008af360e5c55bce506eebcf4"
    ),
    "libtinfo.so.6": "5c19747909b3815b996ac20b94bccb1faf1c6ff1ad240b05792ee4feab733a88",
    "libxml2.so.2": "c05750a6f1c9a90c254df313a9dda9b4c958c0a768b0faf4c15e04b3515c7d93",
    "libz.so.1": "7e2a72b4c4b38c61e6962de6e3f4a5e9ae692e732c68deead10a7ce2135a7f68",
    "libz3.so.4": "7b396b8bc0ea2c0df1eb8f3aefa269478151251191877fb2869a371f81ea0ac4",
    "libzstd.so.1": "37412b7ac11063c25a375bdff6f4fdb340362f926cd9c3a55962e8a9c9bc702e",
}

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

EXPECTED_AUDITS = {
    "avx_current": (579, 122, 0),
    "block1": (75, 18, 0),
    "block2": (136, 30, 0),
    "block5": (321, 69, 0),
    "scalar_generic": (1216, 322, 0),
    "stage_generic": (1218, 322, 0),
    "scalar_alder_ira": (1210, 322, 0),
    "stage_alder_ira": (1210, 322, 0),
}
EXPECTED_DYNAMIC_INSTRUCTIONS = {
    "avx_current": 122,
    "block1": 143,
    "block2": 133,
    "block5": 131,
    "scalar_generic": 322,
    "stage_generic": 322,
    "scalar_alder_ira": 322,
    "stage_alder_ira": 322,
}
EXPECTED_BINARY_LOOP_ALIGNMENT_NOPS = {
    "avx_current": 0,
    "block1": 1,
    "block2": 1,
    "block5": 1,
    "scalar_generic": 0,
    "stage_generic": 0,
    "scalar_alder_ira": 0,
    "stage_alder_ira": 0,
}
EXPECTED_STAGE_DISTRIBUTION = {
    "120.06": 384,
    "120.10": 48,
    "122.05": 96,
    "122.06": 48,
}
EXPECTED_MCA = {
    "avx_current": {"alderlake": (100.03, 20.3), "znver2": (180.03, 80.0)},
    "block1": {"alderlake": (100.03, 23.8), "znver2": (180.03, 80.0)},
    "block2": {"alderlake": (100.03, 22.2), "znver2": (180.03, 80.0)},
    "block5": {"alderlake": (100.03, 21.8), "znver2": (180.03, 80.0)},
    "scalar_generic": {
        "alderlake": (125.06, 86.0),
        "znver2": (140.55, 140.5),
    },
    "stage_generic": {
        "alderlake": (128.58, 88.0),
        "znver2": (140.55, 140.5),
    },
    "scalar_alder_ira": {
        "alderlake": (121.06, 80.5),
        "znver2": (140.55, 140.5),
    },
    "stage_alder_ira": {
        "alderlake": (120.06, 80.5),
        "znver2": (140.55, 140.5),
    },
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def checked(
    command: list[str],
    *,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
    stderr: bool = True,
    timeout: int = HOST_COMMAND_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"command timed out after {timeout}s: "
            f"{subprocess.list2cmdline(command)}"
        ) from error
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"command failed ({completed.returncode}): "
            f"{subprocess.list2cmdline(command)}\n{detail}"
        )
    if not stderr and completed.stderr:
        raise RuntimeError(
            f"unexpected stderr: {subprocess.list2cmdline(command)}\n"
            f"{completed.stderr}"
        )
    return completed


def snapshot_dependencies() -> tuple[
    dict[str, dict[str, str]], dict[str, bytes]
]:
    reports: dict[str, dict[str, str]] = {}
    payloads: dict[str, bytes] = {}
    for name, (relative, expected) in DEPENDENCIES.items():
        path = ROOT / relative
        payload = path.read_bytes()
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


def clean_dynamic_environment() -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("LD_")
    }
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    return environment


def inspect_host_tool(name: str, executable: str) -> dict[str, str]:
    resolved_name = shutil.which(executable)
    if resolved_name is None:
        raise RuntimeError(f"required tool is unavailable: {executable}")
    resolved = Path(resolved_name).resolve()
    expected = HOST_TOOLS[name]
    actual_hash = sha256_file(resolved)
    if actual_hash != expected["sha256"]:
        raise RuntimeError(
            f"{name}: expected executable hash {expected['sha256']}, "
            f"got {actual_hash}: {resolved}"
        )
    version = checked([str(resolved), "--version"]).stdout.splitlines()[0]
    if not version.startswith(expected["version_prefix"]):
        raise RuntimeError(
            f"{name}: expected version prefix {expected['version_prefix']!r}, "
            f"got {version!r}"
        )
    return {
        "requested": executable,
        "resolved": str(resolved),
        "sha256": actual_hash,
        "version": version,
    }


def inspect_llvm_mca(executable: str) -> dict[str, Any]:
    resolved_name = shutil.which(executable)
    if resolved_name is None:
        raise RuntimeError(f"required tool is unavailable: {executable}")
    resolved = Path(resolved_name).resolve()
    expected_tool = HOST_TOOLS["llvm-mca-16"]
    actual_hash = sha256_file(resolved)
    if actual_hash != expected_tool["sha256"]:
        raise RuntimeError(
            "llvm-mca-16: expected executable hash "
            f"{expected_tool['sha256']}, got {actual_hash}: {resolved}"
        )

    loader = Path(DYNAMIC_LOADER["path"]).resolve()
    loader_hash = sha256_file(loader)
    if loader_hash != DYNAMIC_LOADER["sha256"]:
        raise RuntimeError(
            f"dynamic loader: expected {DYNAMIC_LOADER['sha256']}, "
            f"got {loader_hash}: {loader}"
        )
    environment = clean_dynamic_environment()
    linkage = checked(
        [str(loader), "--list", str(resolved)],
        environment=environment,
    ).stdout
    libraries: dict[str, dict[str, str]] = {}
    for line in linkage.splitlines():
        if "linux-vdso.so.1" in line:
            continue
        match = re.match(r"^\s*(\S+)\s+=>\s+(\S+)\s+\(0x[0-9a-f]+\)\s*$", line)
        if not match:
            raise RuntimeError(f"cannot parse llvm-mca loader line: {line!r}")
        soname = Path(match.group(1)).name
        loaded = Path(match.group(2)).resolve()
        libraries[soname] = {
            "resolved": str(loaded),
            "sha256": sha256_file(loaded),
        }
    if set(libraries) != set(LLVM_MCA_DYNAMIC_LIBRARIES):
        raise RuntimeError(
            "llvm-mca dynamic-library set mismatch: "
            f"expected {sorted(LLVM_MCA_DYNAMIC_LIBRARIES)}, "
            f"got {sorted(libraries)}"
        )
    for soname, expected_hash in LLVM_MCA_DYNAMIC_LIBRARIES.items():
        actual = libraries[soname]["sha256"]
        if actual != expected_hash:
            raise RuntimeError(
                f"llvm-mca {soname}: expected {expected_hash}, got {actual}: "
                f"{libraries[soname]['resolved']}"
            )

    version = checked(
        [str(resolved), "--version"], environment=environment
    ).stdout.splitlines()[0]
    if not version.startswith(expected_tool["version_prefix"]):
        raise RuntimeError(
            "llvm-mca-16: expected version prefix "
            f"{expected_tool['version_prefix']!r}, got {version!r}"
        )
    return {
        "requested": executable,
        "resolved": str(resolved),
        "sha256": actual_hash,
        "version": version,
        "dynamic_environment": "LD_* removed; LC_ALL=C; LANG=C",
        "dynamic_loader": {
            "resolved": str(loader),
            "sha256": loader_hash,
        },
        "dynamic_libraries": dict(sorted(libraries.items())),
    }


def inspect_runtime(runtime: str) -> tuple[dict[str, str], str]:
    report = inspect_host_tool("docker", runtime)
    image = checked(
        [
            report["resolved"],
            "image",
            "inspect",
            IMAGE,
            "--format",
            "{{.Id}} {{json .RepoDigests}}",
        ]
    ).stdout.strip()
    image_id, raw_digests = image.split(" ", 1)
    digests = json.loads(raw_digests)
    if image_id != IMAGE_DIGEST or EXPECTED_IMAGE_REPODIGEST not in digests:
        raise RuntimeError(
            f"unexpected pinned image identity: id={image_id}, digests={digests}"
        )
    report["client_version"] = checked(
        [report["resolved"], "version", "--format", "{{.Client.Version}}"]
    ).stdout.strip()
    return report, image_id


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one replacement site, got {count}")
    return source.replace(old, new)


BLOCK2_LOOP = """#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC unroll 1
#endif
    for (unsigned int pair = 0; pair < 5U; ++pair) {
        APPLY_TWO_ROUNDS_AVX2();
        APPLY_TWO_ROUNDS_AVX2();
    }
"""
BLOCK1_LOOP = """#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC unroll 1
#endif
    for (unsigned int pair = 0; pair < 10U; ++pair) {
        APPLY_TWO_ROUNDS_AVX2();
    }
"""
BLOCK5_LOOP = """    unsigned int blocks = 2U;
    __asm__("" : "+r"(blocks));
#if defined(__GNUC__) && !defined(__clang__)
#pragma GCC unroll 1
#endif
    for (unsigned int pair = 0; pair < blocks; ++pair) {
        APPLY_TWO_ROUNDS_AVX2();
        APPLY_TWO_ROUNDS_AVX2();
        APPLY_TWO_ROUNDS_AVX2();
        APPLY_TWO_ROUNDS_AVX2();
        APPLY_TWO_ROUNDS_AVX2();
    }
"""


def scalar_macro_extent(source: str) -> tuple[int, int]:
    start = source.index("#define APPLY_TWO_ROUNDS()")
    marker = "    } while (0)\n"
    end = source.index(marker, start) + len(marker)
    return start, end


def stage_macro(first: tuple[int, ...], second: tuple[int, ...]) -> str:
    forward_rot = [43, 7, 29, 14]
    reverse_rot = [14, 29, 7, 43]
    reverse = [3, 2, 1, 0]
    statements = [
        "#define APPLY_TWO_ROUNDS()",
        "    do {",
        *[
            (
                f"        const uint64_t y{i} = transform_word("
                f"x{i}, {forward_rot[i]}U, k{i}, a{reverse[i]});"
            )
            for i in first
        ],
        *[
            (
                f"        x{i} = transform_word(y{i}, {reverse_rot[i]}U, "
                f"k{reverse[i]}, a{i});"
            )
            for i in second
        ],
        "    } while (0)",
    ]
    return "".join(
        line + (" \\\n" if index + 1 < len(statements) else "\n")
        for index, line in enumerate(statements)
    )


def make_stage_source(
    scalar_source: str,
    first: tuple[int, ...],
    second: tuple[int, ...],
) -> str:
    start, end = scalar_macro_extent(scalar_source)
    return scalar_source[:start] + stage_macro(first, second) + scalar_source[end:]


def generate_sources(
    temporary: Path, dependency_payloads: dict[str, bytes]
) -> dict[str, Any]:
    sources = temporary / "sources"
    stage_orders = temporary / "stage-orders"
    sources.mkdir()
    stage_orders.mkdir()

    scalar = dependency_payloads["scalar_source"].decode()
    avx = dependency_payloads["avx2_source"].decode()
    block2 = dependency_payloads["pair_block2_source"].decode()
    block1 = replace_once(block2, BLOCK2_LOOP, BLOCK1_LOOP, "block1 loop")
    block5 = replace_once(block2, BLOCK2_LOOP, BLOCK5_LOOP, "block5 loop")
    attribute = 'optimize("no-tree-vectorize")'
    if block5.count(attribute) != 2:
        raise RuntimeError(
            "block5 no-unroll attribute: expected two GCC attribute sites"
        )
    block5 = block5.replace(
        attribute, 'optimize("no-tree-vectorize,no-unroll-loops")', 1
    )
    stage = make_stage_source(scalar, (0, 1, 2, 3), (0, 1, 2, 3))

    texts = {
        "scalar": scalar,
        "avx_current": avx,
        "block1": block1,
        "block2": block2,
        "block5": block5,
        "stage": stage,
    }
    for name, text in texts.items():
        (sources / f"{name}.c").write_text(text)

    order_reports = []
    for first in itertools.permutations(range(4)):
        for second in itertools.permutations(range(4)):
            first_name = "".join(str(value) for value in first)
            second_name = "".join(str(value) for value in second)
            name = f"stage_{first_name}_{second_name}"
            text = make_stage_source(scalar, first, second)
            path = stage_orders / f"{name}.c"
            path.write_text(text)
            order_reports.append(
                {
                    "name": name,
                    "first_stage_order": first_name,
                    "second_stage_order": second_name,
                    "source_sha256": sha256_bytes(text.encode()),
                    "source": f"stage-orders/{name}.c",
                }
            )
    unique_names = {item["name"] for item in order_reports}
    if len(order_reports) != 576 or len(unique_names) != 576:
        raise RuntimeError(
            "expected 576 unique stage orders, got "
            f"{len(order_reports)} records/{len(unique_names)} names"
        )

    return {
        "source_hashes": {
            name: sha256_bytes(text.encode()) for name, text in texts.items()
        },
        "stage_orders": order_reports,
    }


def extract_vectors(
    temporary: Path, dependency_payloads: dict[str, bytes]
) -> None:
    vectors = temporary / "vectors"
    vectors.mkdir()
    archive = io.BytesIO(dependency_payloads["problem_archive"])
    with ZipFile(archive) as zipped:
        for name in ("testvector.txt", "testvector_20round.txt"):
            (vectors / name).write_bytes(zipped.read(f"code/{name}"))


def materialize_container_repository(
    temporary: Path, dependency_payloads: dict[str, bytes]
) -> Path:
    repository = temporary / "repository-snapshot"
    for name in ("candidate_verifier", "loop_audit"):
        relative = Path(DEPENDENCIES[name][0])
        destination = repository / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(dependency_payloads[name])
    return repository


CONTAINER_DRIVER = textwrap.dedent(
    r"""
    import concurrent.futures
    import hashlib
    import json
    import os
    import re
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    work = Path("/work")
    config = json.loads((work / "config.json").read_text())
    artifacts = work / "artifacts"
    artifacts.mkdir()

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    for relative, expected in config["repository_hashes"].items():
        path = Path("/repository") / relative
        actual = digest(path)
        if actual != expected:
            raise RuntimeError(
                f"repository snapshot hash mismatch for {relative}: "
                f"expected {expected}, got {actual}"
            )

    sys.path.insert(0, "/repository/solutions")
    from challenge02_loop_audit import audit_main_timing_loop

    def run(command, cwd=None):
        try:
            result = subprocess.run(
                command, cwd=cwd, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=config["command_timeout_seconds"],
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                "command timed out after "
                f"{config['command_timeout_seconds']}s: {command}"
            ) from error
        if result.returncode:
            raise RuntimeError(
                f"command failed ({result.returncode}): {command}\n"
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result

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
            raise RuntimeError(f"{assembly}: timing-loop backedge not found")
        target = backedges[-1].group(1)
        start = region.index(target + ":")
        end = backedges[-1].end()
        loop = ".text\n" + region[start:end] + "\n"
        destination.write_text(loop)
        return loop

    verifier_object = artifacts / "verifier.o"
    run([
        "gcc", *config["verifier_flags"], "-c",
        "/repository/solutions/02_optimization/verify_contest_candidate_02.c",
        "-o", str(verifier_object),
    ])

    def compile_case(item):
        name = item["name"]
        source = work / item["source"]
        flags = item["flags"]
        assembly = artifacts / f"{name}.s"
        binary = artifacts / f"{name}.bin"
        binary_object = artifacts / f"{name}.binary.o"
        candidate_object = artifacts / f"{name}.o"
        verifier = artifacts / f"{name}.verify"
        loop_path = artifacts / f"{name}.loop.s"
        actual_source_sha256 = digest(source)
        if actual_source_sha256 != item["source_sha256"]:
            raise RuntimeError(
                f"{name}: expected source hash {item['source_sha256']}, "
                f"got {actual_source_sha256}"
            )
        run(["gcc", *flags, "-S", str(source), "-o", str(assembly)])
        run(["gcc", "-c", str(assembly), "-o", str(binary_object)])
        run(["gcc", str(binary_object), "-o", str(binary)])
        audit = audit_main_timing_loop(binary, objdump="objdump", size_tool="size")
        loop = extract_loop(assembly, loop_path)
        run([
            "gcc", *flags, "-Dmain=contest_candidate_main", "-c",
            str(source), "-o", str(candidate_object),
        ])
        run(["gcc", str(candidate_object), str(verifier_object), "-o", str(verifier)])
        verification = run([str(verifier), str(config["random_cases"])])
        official = run([str(binary)], cwd=work / "vectors")
        required = config["official_lines"]
        official_pass = (
            all(line in official.stdout for line in required)
            and "MISMATCH" not in official.stdout
            and official.stderr == ""
        )
        if verification.stdout != config["verifier_stdout"] or verification.stderr:
            raise RuntimeError(f"{name}: random differential verification failed")
        if not official_pass:
            raise RuntimeError(f"{name}: official vectors failed")
        return {
            "name": name,
            "source": item["source"],
            "source_sha256": actual_source_sha256,
            "flags": flags,
            "assembly_sha256": digest(assembly),
            "measured_binary_assembled_from_reported_assembly": True,
            "binary_audit": audit,
            "loop_text_sha256": hashlib.sha256(loop.encode()).hexdigest(),
            "loop_artifact": f"artifacts/{name}.loop.s",
            "verification": {
                "status": "PASS",
                "stdout": verification.stdout,
                "stderr": verification.stderr,
                "random_cases": config["random_cases"],
                "random_state_and_constants": True,
                "round_counts": [1, 20],
            },
            "official_vectors": {
                "status": "PASS",
                "one_round_pairs": 1000,
                "twenty_round_vectors": 1,
                "required_stdout_lines": required,
                "stderr": official.stderr,
            },
        }

    cases = {}
    for item in config["cases"]:
        report = compile_case(item)
        cases[report["name"]] = report

    stage_artifacts = work / "stage-artifacts"
    stage_artifacts.mkdir()

    def compile_stage(item):
        source = work / item["source"]
        assembly = stage_artifacts / f"{item['name']}.s"
        loop_path = stage_artifacts / f"{item['name']}.loop.s"
        actual_source_sha256 = digest(source)
        if actual_source_sha256 != item["source_sha256"]:
            raise RuntimeError(
                f"{item['name']}: expected source hash "
                f"{item['source_sha256']}, got {actual_source_sha256}"
            )
        run([
            "gcc", *config["stage_order_flags"], "-S", str(source),
            "-o", str(assembly),
        ])
        loop = extract_loop(assembly, loop_path)
        return {
            **item,
            "source_sha256": actual_source_sha256,
            "assembly_sha256": digest(assembly),
            "loop_text_sha256": hashlib.sha256(loop.encode()).hexdigest(),
            "loop_instruction_lines": sum(
                line.startswith("\t") for line in loop.splitlines()
            ),
            "loop_artifact": f"stage-artifacts/{item['name']}.loop.s",
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=config["jobs"]) as pool:
        stage_orders = list(pool.map(compile_stage, config["stage_orders"]))
    stage_orders.sort(key=lambda item: item["name"])

    def tool(name):
        path = Path(shutil.which(name)).resolve()
        if name == "gcc":
            version = run([str(path), "--version"]).stdout.splitlines()[0]
        else:
            version = run([str(path), "--version"]).stdout.splitlines()[0]
        return {
            "resolved": str(path),
            "sha256": digest(path),
            "version": version,
        }

    output = {
        "compiler": tool("gcc"),
        "binutils": {
            "ld": tool("ld"),
            "objdump": tool("objdump"),
            "size": tool("size"),
        },
        "python": tool("python3"),
        "cases": cases,
        "stage_orders": stage_orders,
    }
    (work / "container-results.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    """
)


def run_container(
    runtime: str,
    temporary: Path,
    repository_snapshot: Path,
    dependencies: dict[str, dict[str, str]],
    generated: dict[str, Any],
    jobs: int,
) -> dict[str, Any]:
    cases = [
        {
            "name": "avx_current",
            "source": "sources/avx_current.c",
            "source_sha256": generated["source_hashes"]["avx_current"],
            "flags": AVX_FLAGS,
        },
        {
            "name": "block1",
            "source": "sources/block1.c",
            "source_sha256": generated["source_hashes"]["block1"],
            "flags": AVX_FLAGS,
        },
        {
            "name": "block2",
            "source": "sources/block2.c",
            "source_sha256": generated["source_hashes"]["block2"],
            "flags": AVX_FLAGS,
        },
        {
            "name": "block5",
            "source": "sources/block5.c",
            "source_sha256": generated["source_hashes"]["block5"],
            "flags": AVX_FLAGS,
        },
        {
            "name": "scalar_generic",
            "source": "sources/scalar.c",
            "source_sha256": generated["source_hashes"]["scalar"],
            "flags": SCALAR_GENERIC_FLAGS,
        },
        {
            "name": "stage_generic",
            "source": "sources/stage.c",
            "source_sha256": generated["source_hashes"]["stage"],
            "flags": SCALAR_GENERIC_FLAGS,
        },
        {
            "name": "scalar_alder_ira",
            "source": "sources/scalar.c",
            "source_sha256": generated["source_hashes"]["scalar"],
            "flags": SCALAR_ALDER_IRA_FLAGS,
        },
        {
            "name": "stage_alder_ira",
            "source": "sources/stage.c",
            "source_sha256": generated["source_hashes"]["stage"],
            "flags": SCALAR_ALDER_IRA_FLAGS,
        },
    ]
    config = {
        "cases": cases,
        "command_timeout_seconds": CONTAINER_COMMAND_TIMEOUT_SECONDS,
        "jobs": jobs,
        "official_lines": EXPECTED_OFFICIAL_LINES,
        "random_cases": RANDOM_CASES,
        "repository_hashes": {
            dependencies[name]["path"]: dependencies[name]["sha256"]
            for name in ("candidate_verifier", "loop_audit")
        },
        "stage_order_flags": SCALAR_ALDER_IRA_FLAGS,
        "stage_orders": generated["stage_orders"],
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
        f"{repository_snapshot}:/repository:ro",
        "--volume",
        f"{temporary}:/work",
        "--workdir",
        "/work",
        IMAGE,
        "python3",
        "-c",
        CONTAINER_DRIVER,
    ]
    checked(command, timeout=CONTAINER_TIMEOUT_SECONDS)
    return json.loads((temporary / "container-results.json").read_text())


def parse_loop_assembly(path: Path) -> tuple[list[dict[str, str]], dict[str, int]]:
    instructions: list[dict[str, str]] = []
    labels: dict[str, int] = {}
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith(".") and not stripped.endswith(":"):
            if stripped == ".text" or stripped.startswith(".p2align "):
                continue
            raise RuntimeError(f"unsupported loop directive: {raw!r}")
        if stripped.endswith(":"):
            labels[stripped[:-1]] = len(instructions)
            continue
        match = re.match(r"^([A-Za-z][A-Za-z0-9.]*)\s*(.*?)$", stripped)
        if not match:
            raise RuntimeError(f"cannot parse assembly line: {raw!r}")
        instructions.append(
            {
                "mnemonic": match.group(1).lower(),
                "operands": match.group(2).strip(),
                "raw": stripped,
            }
        )
    if not instructions or not labels:
        raise RuntimeError(f"empty loop assembly: {path}")
    return instructions, labels


def register_name(value: str) -> str:
    return value.strip()


def expand_one_dynamic_call(path: Path, case: str, destination: Path) -> int:
    instructions, labels = parse_loop_assembly(path)
    outer_label = min(labels, key=labels.get)
    pc = labels[outer_label]
    registers: dict[str, int] = {}
    zero: bool | None = None
    trace: list[str] = []

    if case == "block5":
        test = next(
            item for item in instructions if item["mnemonic"] == "testl"
        )
        left, right = [part.strip() for part in test["operands"].split(",")]
        if left != right:
            raise RuntimeError("block5: expected self-test of opaque block count")
        registers[left] = 2

    for _step in range(2000):
        item = instructions[pc]
        mnemonic = item["mnemonic"]
        operands = item["operands"]
        emitted = item["raw"]
        branch_target: str | None = None
        if mnemonic in {"je", "jne"}:
            branch_target = operands.split()[0]
            emitted = f"{mnemonic} .Ltrace"
        trace.append(emitted)

        mov = re.fullmatch(r"\$([0-9]+),\s*(%[A-Za-z0-9]+)", operands)
        binary = re.fullmatch(
            r"\$([0-9]+),\s*(%[A-Za-z0-9]+)", operands
        )
        two_regs = re.fullmatch(
            r"(%[A-Za-z0-9]+),\s*(%[A-Za-z0-9]+)", operands
        )
        if mnemonic == "movl" and mov:
            registers[register_name(mov.group(2))] = int(mov.group(1))
        elif mnemonic == "xorl" and two_regs and two_regs.group(1) == two_regs.group(2):
            registers[register_name(two_regs.group(1))] = 0
            zero = True
        elif mnemonic == "addl" and binary:
            reg = register_name(binary.group(2))
            if reg in registers:
                registers[reg] += int(binary.group(1))
                zero = registers[reg] == 0
        elif mnemonic == "subl" and binary:
            reg = register_name(binary.group(2))
            if reg in registers:
                registers[reg] -= int(binary.group(1))
                zero = registers[reg] == 0
            else:
                zero = False
        elif (
            mnemonic == "testl"
            and two_regs
            and two_regs.group(1) == two_regs.group(2)
        ):
            reg = register_name(two_regs.group(1))
            if reg not in registers:
                raise RuntimeError(f"{case}: unknown tested register {reg}")
            zero = registers[reg] == 0
        elif mnemonic == "cmpl" and two_regs:
            left = register_name(two_regs.group(1))
            right = register_name(two_regs.group(2))
            if left not in registers or right not in registers:
                raise RuntimeError(f"{case}: unknown compare operands {operands}")
            zero = registers[left] == registers[right]

        if branch_target is not None:
            if branch_target == outer_label:
                break
            if zero is None:
                raise RuntimeError(f"{case}: branch without modeled flags: {item}")
            taken = zero if mnemonic == "je" else not zero
            if taken:
                if branch_target not in labels:
                    raise RuntimeError(f"{case}: unknown label {branch_target}")
                pc = labels[branch_target]
                continue
        pc += 1
        if pc >= len(instructions):
            raise RuntimeError(f"{case}: dynamic trace fell out of loop")
    else:
        raise RuntimeError(f"{case}: dynamic trace exceeded bound")

    destination.write_text(
        ".text\n.Ltrace:\n"
        + "".join(f"\t{line}\n" for line in trace)
    )
    return len(trace)


def extract_number(output: str, label: str) -> float:
    match = re.search(
        rf"^{re.escape(label)}:\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"llvm-mca output omitted {label!r}")
    return float(match.group(1))


def analyse_mca(
    executable: str,
    assembly: Path,
    model: str,
) -> dict[str, float | int]:
    output = checked(
        [
            executable,
            f"-mcpu={model}",
            f"-iterations={MCA_ITERATIONS}",
            str(assembly),
        ],
        environment=clean_dynamic_environment(),
    ).stdout
    total_cycles = int(extract_number(output, "Total Cycles"))
    total_instructions = int(extract_number(output, "Instructions"))
    total_uops = int(extract_number(output, "Total uOps"))
    return {
        "iterations": MCA_ITERATIONS,
        "total_cycles": total_cycles,
        "total_instructions": total_instructions,
        "total_uops": total_uops,
        "cycles_per_iteration": total_cycles / MCA_ITERATIONS,
        "instructions_per_iteration": total_instructions / MCA_ITERATIONS,
        "uops_per_iteration": total_uops / MCA_ITERATIONS,
        "block_rthroughput": extract_number(output, "Block RThroughput"),
    }


def add_case_mca(
    temporary: Path,
    container: dict[str, Any],
    llvm_mca: str,
) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for name, raw in sorted(container["cases"].items()):
        report = dict(raw)
        loop_path = temporary / report.pop("loop_artifact")
        trace_path = temporary / f"{name}.dynamic.s"
        dynamic_instructions = expand_one_dynamic_call(
            loop_path, name, trace_path
        )
        binary_alignment_nops = sum(
            count
            for mnemonic, count in report["binary_audit"]["mnemonics"].items()
            if mnemonic.startswith("nop")
        )
        report["dynamic_trace"] = {
            "method": (
                "GCC-assembly-CFG-expansion-one-outer-iteration-"
                "excluding-alignment-v2"
            ),
            "instruction_scope": "modeled non-padding instructions",
            "alignment_padding_excluded": True,
            "instructions": dynamic_instructions,
            "binary_loop_alignment_nop_instructions": binary_alignment_nops,
            "instructions_including_binary_alignment_nops": (
                dynamic_instructions + binary_alignment_nops
            ),
            "sha256": sha256_file(trace_path),
        }
        report["llvm_mca"] = {
            model: analyse_mca(llvm_mca, trace_path, model)
            for model in MCA_MODELS
        }
        cases[name] = report
    return cases


def analyse_stage_orders(
    temporary: Path,
    records: list[dict[str, Any]],
    llvm_mca: str,
    jobs: int,
) -> dict[str, Any]:
    def analyse(record: dict[str, Any]) -> dict[str, Any]:
        compact = dict(record)
        loop = temporary / compact.pop("loop_artifact")
        mca = analyse_mca(llvm_mca, loop, "alderlake")
        if mca["instructions_per_iteration"] != 322.0:
            raise RuntimeError(
                f"{record['name']}: expected 322 instructions, "
                f"got {mca['instructions_per_iteration']}"
            )
        compact["alderlake_cycles_per_iteration"] = mca[
            "cycles_per_iteration"
        ]
        compact["alderlake_block_rthroughput"] = mca["block_rthroughput"]
        return compact

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        analysed = list(pool.map(analyse, records))
    analysed.sort(key=lambda item: item["name"])
    distribution = Counter(
        f"{item['alderlake_cycles_per_iteration']:.2f}" for item in analysed
    )
    manifest_text = "".join(
        f"{item['name']} {item['source_sha256']} "
        f"{item['loop_text_sha256']} "
        f"{item['alderlake_cycles_per_iteration']:.2f}\n"
        for item in analysed
    )
    return {
        "candidate_count": len(analysed),
        "first_stage_orders": 24,
        "second_stage_orders": 24,
        "compiler_flags": SCALAR_ALDER_IRA_FLAGS,
        "model": "alderlake",
        "mca_iterations": MCA_ITERATIONS,
        "records_manifest_sha256": sha256_bytes(manifest_text.encode()),
        "cycle_distribution": dict(sorted(distribution.items())),
        "minimum_cycles_per_iteration": min(
            item["alderlake_cycles_per_iteration"] for item in analysed
        ),
        "maximum_cycles_per_iteration": max(
            item["alderlake_cycles_per_iteration"] for item in analysed
        ),
        "records": analysed,
    }


def validate_output(output: dict[str, Any]) -> dict[str, bool]:
    cases = output["cases"]
    generated_hashes = output["sources"]["generated_source_hashes"]
    source_key = {
        "avx_current": "avx_current",
        "block1": "block1",
        "block2": "block2",
        "block5": "block5",
        "scalar_generic": "scalar",
        "stage_generic": "stage",
        "scalar_alder_ira": "scalar",
        "stage_alder_ira": "stage",
    }
    checks: dict[str, bool] = {}
    checks["all_eight_cases_present"] = set(cases) == set(EXPECTED_AUDITS)
    checks["compiled_sources_match_snapshots"] = all(
        cases[name]["source_sha256"] == generated_hashes[key]
        for name, key in source_key.items()
    )
    checks["measured_binaries_use_reported_assembly"] = all(
        report["measured_binary_assembled_from_reported_assembly"] is True
        for report in cases.values()
    )
    checks["all_random_verifiers_pass"] = all(
        report["verification"]["status"] == "PASS"
        and report["verification"]["random_cases"] == RANDOM_CASES
        and report["verification"]["random_state_and_constants"] is True
        and report["verification"]["round_counts"] == [1, 20]
        for report in cases.values()
    )
    checks["all_official_vectors_pass"] = all(
        report["official_vectors"]["status"] == "PASS"
        and report["official_vectors"]["one_round_pairs"] == 1000
        and report["official_vectors"]["twenty_round_vectors"] == 1
        for report in cases.values()
    )
    checks["exact_audits_match"] = all(
        (
            cases[name]["binary_audit"]["loop_bytes"],
            cases[name]["binary_audit"]["loop_instructions"],
            cases[name]["binary_audit"]["memory_operands_excluding_lea"],
        )
        == expected
        and cases[name]["binary_audit"]["calls"] == 0
        and cases[name]["binary_audit"]["push_pop"] == 0
        for name, expected in EXPECTED_AUDITS.items()
    )
    checks["dynamic_instruction_counts_match"] = all(
        cases[name]["dynamic_trace"]["instructions"] == expected
        and cases[name]["dynamic_trace"]["alignment_padding_excluded"] is True
        and cases[name]["dynamic_trace"]["instruction_scope"]
        == "modeled non-padding instructions"
        for name, expected in EXPECTED_DYNAMIC_INSTRUCTIONS.items()
    )
    checks["binary_alignment_nops_accounted_for"] = all(
        cases[name]["dynamic_trace"]["binary_loop_alignment_nop_instructions"]
        == expected
        and cases[name]["dynamic_trace"][
            "instructions_including_binary_alignment_nops"
        ]
        == EXPECTED_DYNAMIC_INSTRUCTIONS[name] + expected
        for name, expected in EXPECTED_BINARY_LOOP_ALIGNMENT_NOPS.items()
    )
    checks["all_mca_metrics_match"] = all(
        cases[name]["llvm_mca"][model]["cycles_per_iteration"]
        == expected[0]
        and cases[name]["llvm_mca"][model]["block_rthroughput"]
        == expected[1]
        and cases[name]["llvm_mca"][model]["instructions_per_iteration"]
        == EXPECTED_DYNAMIC_INSTRUCTIONS[name]
        and cases[name]["llvm_mca"][model]["iterations"] == MCA_ITERATIONS
        for name, models in EXPECTED_MCA.items()
        for model, expected in models.items()
    )
    block2 = cases["block2"]
    checks["block2_required_shape"] = (
        block2["binary_audit"]["loop_bytes"] == 136
        and block2["binary_audit"]["loop_instructions"] == 30
        and block2["dynamic_trace"]["instructions"] == 133
        and block2["binary_audit"]["memory_operands_excluding_lea"] == 0
    )
    checks["block2_required_mca"] = (
        block2["llvm_mca"]["alderlake"]["cycles_per_iteration"] == 100.03
        and block2["llvm_mca"]["znver2"]["cycles_per_iteration"] == 180.03
    )
    screen = output["stage_order_screen"]
    checks["stage_order_count_is_576"] = (
        screen["candidate_count"] == 576
        and len(screen["records"]) == 576
        and len({record["name"] for record in screen["records"]}) == 576
    )
    source_manifest = "".join(
        f"{record['name']} {record['source_sha256']}\n"
        for record in screen["records"]
    )
    record_manifest = "".join(
        f"{record['name']} {record['source_sha256']} "
        f"{record['loop_text_sha256']} "
        f"{record['alderlake_cycles_per_iteration']:.2f}\n"
        for record in screen["records"]
    )
    checks["stage_order_manifests_match"] = (
        sha256_bytes(source_manifest.encode())
        == output["sources"][
            "generated_stage_order_source_manifest_sha256"
        ]
        and sha256_bytes(record_manifest.encode())
        == screen["records_manifest_sha256"]
    )
    checks["stage_order_distribution_matches"] = (
        screen["cycle_distribution"] == EXPECTED_STAGE_DISTRIBUTION
    )
    checks["stage_order_has_no_strict_improvement"] = (
        screen["incumbent_case"] == "stage_alder_ira"
        and screen["incumbent_cycles_per_iteration"]
        == cases["stage_alder_ira"]["llvm_mca"]["alderlake"][
            "cycles_per_iteration"
        ]
        and screen["minimum_cycles_per_iteration"]
        >= screen["incumbent_cycles_per_iteration"]
        and screen["strict_improvement_count"] == 0
        and screen["incumbent_tie_count"]
        == EXPECTED_STAGE_DISTRIBUTION["120.06"]
    )
    if not all(checks.values()):
        failures = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(f"screen validation failed: {failures}")
    return checks


def build_output(args: argparse.Namespace) -> dict[str, Any]:
    script_sha256 = sha256_file(SCRIPT)
    dependencies, dependency_payloads = snapshot_dependencies()
    runtime_report, image_id = inspect_runtime(args.runtime)
    mca_report = inspect_llvm_mca(args.llvm_mca)
    python_report = inspect_host_tool("python3", sys.executable)

    with tempfile.TemporaryDirectory(prefix="ch2-pair-blocks-") as raw:
        temporary = Path(raw).resolve()
        generated = generate_sources(temporary, dependency_payloads)
        extract_vectors(temporary, dependency_payloads)
        repository_snapshot = materialize_container_repository(
            temporary, dependency_payloads
        )
        config_manifest = "".join(
            f"{item['name']} {item['source_sha256']}\n"
            for item in generated["stage_orders"]
        )
        container = run_container(
            runtime_report["resolved"],
            temporary,
            repository_snapshot,
            dependencies,
            generated,
            args.jobs,
        )
        cases = add_case_mca(
            temporary, container, mca_report["resolved"]
        )
        stage_order_screen = analyse_stage_orders(
            temporary,
            container["stage_orders"],
            mca_report["resolved"],
            args.jobs,
        )
        incumbent_cycles = cases["stage_alder_ira"]["llvm_mca"][
            "alderlake"
        ]["cycles_per_iteration"]
        stage_order_screen["incumbent_case"] = "stage_alder_ira"
        stage_order_screen["incumbent_cycles_per_iteration"] = (
            incumbent_cycles
        )
        stage_order_screen["strict_improvement_count"] = sum(
            record["alderlake_cycles_per_iteration"] < incumbent_cycles
            for record in stage_order_screen["records"]
        )
        stage_order_screen["incumbent_tie_count"] = sum(
            record["alderlake_cycles_per_iteration"] == incumbent_cycles
            for record in stage_order_screen["records"]
        )

    ensure_inputs_unchanged(dependencies, script_sha256)

    output: dict[str, Any] = {
        "schema_version": 1,
        "experiment": "challenge-2 AVX2 pair blocks and scalar stage-major orders",
        "scope": (
            "single-state 20-round contest-fixed rotation/reversal permutation; "
            "exact GCC 13.3 static binary audit, official vectors, arbitrary-"
            "state/arbitrary-constant differential verification within that "
            "specialization, and LLVM-MCA proxies over padding-excluded traces; "
            "no 255H timing"
        ),
        "protocol": {
            "parameter_scope": (
                "contest-fixed rotations and byte reversal; arbitrary state and "
                "round constants"
            ),
            "random_cases_per_case": RANDOM_CASES,
            "random_seed": "0x243f6a8885a308d3",
            "round_counts": [1, 20],
            "official_one_round_pairs": 1000,
            "official_twenty_round_vectors": 1,
            "mca_models": MCA_MODELS,
            "mca_iterations": MCA_ITERATIONS,
            "dynamic_trace_scope": (
                "modeled non-padding instructions; alignment directives and "
                "their emitted NOPs are excluded"
            ),
            "stage_order_search": "24 first-stage orders x 24 second-stage orders",
            "host_command_timeout_seconds": HOST_COMMAND_TIMEOUT_SECONDS,
            "container_timeout_seconds": CONTAINER_TIMEOUT_SECONDS,
            "container_command_timeout_seconds": CONTAINER_COMMAND_TIMEOUT_SECONDS,
            "input_snapshot": (
                "all dependencies loaded once into memory; container inputs "
                "materialized from that snapshot; live files rehashed at end"
            ),
            "temporary_artifacts_retained": False,
        },
        "sources": {
            "dependencies": dependencies,
            "screen_script": {
                "path": str(SCRIPT.relative_to(ROOT)),
                "sha256": script_sha256,
            },
            "generated_source_hashes": generated["source_hashes"],
            "generated_stage_order_source_manifest_sha256": sha256_bytes(
                config_manifest.encode()
            ),
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
        "stage_order_screen": stage_order_screen,
        "decision": {
            "block2": (
                "retain as a 255H-only A/B candidate: 136-byte/30-static-"
                "instruction loop, 133 modeled non-padding dynamic instructions "
                "(134 including the emitted alignment NOP), no hot memory, and "
                "unchanged 100.03/180.03 proxy latency"
            ),
            "block1": (
                "do not promote from bounded proxy evidence; its 75-byte loop "
                "costs 143 modeled non-padding dynamic instructions (144 with "
                "the alignment NOP) and has unchanged latency versus block2"
            ),
            "block5": (
                "reject for now: 131 modeled non-padding dynamic instructions "
                "(132 with the alignment NOP) and 21.8-cycle throughput are "
                "small proxy improvements, but the opaque-count loop expands "
                "to 321 bytes/69 static instructions and retains block2's "
                "100.03/180.03-cycle proxy latency"
            ),
            "scalar_stage_major": (
                "reject: all 576 source-order crosses are at or above the "
                "120.06-cycle tuned stage-major incumbent proxy"
            ),
            "qualification": (
                "the dynamic/MCA traces omit emitted alignment NOPs and static "
                "models do not model frontend residency or the target; promotion "
                "requires two independent Core Ultra 7 255H sessions"
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
        help="regenerate in temporary storage and compare with the canonical JSON",
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
            f"check=PASS json={args.json} sha256={sha256_bytes(rendered.encode())}"
        )
        return 0
    args.json.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.json.with_suffix(args.json.suffix + ".tmp")
    temporary_output.write_text(rendered)
    os.replace(temporary_output, args.json)
    print(
        f"wrote={args.json} sha256={sha256_bytes(rendered.encode())} "
        f"stage_orders={output['stage_order_screen']['candidate_count']} "
        f"block2={output['cases']['block2']['binary_audit']['loop_bytes']}B/"
        f"{output['cases']['block2']['binary_audit']['loop_instructions']}static/"
        f"{output['cases']['block2']['dynamic_trace']['instructions']}dynamic"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
