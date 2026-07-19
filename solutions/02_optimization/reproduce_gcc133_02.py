#!/usr/bin/env python3
"""Reproduce challenge 2 code generation with the pinned official GCC 13.3 image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


IMAGE = (
    "gcc@sha256:"
    "1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
)


def run_container(
    runtime: str,
    root: Path,
    output: Path,
    arguments: list[str],
) -> None:
    command = [
        runtime,
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{root}:/workspace:ro",
        "--volume",
        f"{output}:/output",
        "--workdir",
        "/workspace",
        IMAGE,
        *arguments,
    ]
    print("$", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run assembly and correctness gates in a digest-pinned gcc:13.3.0 "
            "container. Performance samples in the smoke gate are not target data."
        )
    )
    parser.add_argument("--runtime", default="docker")
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("/tmp/gcc133_codegen_results_02.json"),
    )
    parser.add_argument("--random-cases", type=int, default=100_000)
    args = parser.parse_args()
    if args.random_cases <= 0:
        parser.error("--random-cases must be positive")
    if shutil.which(args.runtime) is None:
        parser.error(f"container runtime is unavailable: {args.runtime}")

    root = Path(__file__).resolve().parents[2]
    source = root / "submissions" / "02" / "contest.c"
    with tempfile.TemporaryDirectory(prefix="challenge02-gcc133-") as directory:
        temporary = Path(directory).resolve()
        run_container(
            args.runtime,
            root,
            temporary,
            [
                "python3",
                "solutions/02_optimization/audit_inline_02.py",
                "--compiler",
                "gcc",
                "--objdump",
                "objdump",
                "--json",
                "/output/generic-audit.json",
            ],
        )
        run_container(
            args.runtime,
            root,
            temporary,
            [
                "python3",
                "solutions/02_optimization/audit_inline_02.py",
                "--compiler",
                "gcc",
                "--objdump",
                "objdump",
                "--extra-cflag=-mtune=alderlake",
                "--json",
                "/output/alderlake-audit.json",
            ],
        )
        run_container(
            args.runtime,
            root,
            temporary,
            [
                "python3",
                "solutions/02_optimization/audit_inline_02.py",
                "--compiler",
                "gcc",
                "--objdump",
                "objdump",
                "--extra-cflag=-mtune=alderlake",
                "--extra-cflag=-fira-algorithm=priority",
                "--json",
                "/output/alderlake-ira-audit.json",
            ],
        )

        benchmark = [
            "python3",
            "solutions/benchmark_02_permutation.py",
            "--compiler",
            "gcc",
            "--case",
            "default=submissions/02/contest.c",
            "--case",
            "inline_700=submissions/02/contest.c",
            "--case",
            "inline_2000=submissions/02/contest.c",
            "--case",
            "alderlake_700=submissions/02/contest.c",
            "--case",
            "alderlake_2000=submissions/02/contest.c",
            "--case",
            "alderlake_ira=submissions/02/contest.c",
            "--baseline",
            "inline_2000",
        ]
        for name, flags in {
            "inline_700": ["-mbmi2", "-finline-limit=700"],
            "inline_2000": ["-mbmi2", "-finline-limit=2000"],
            "alderlake_700": [
                "-mbmi2",
                "-finline-limit=700",
                "-mtune=alderlake",
            ],
            "alderlake_2000": [
                "-mbmi2",
                "-finline-limit=2000",
                "-mtune=alderlake",
            ],
            "alderlake_ira": [
                "-mbmi2",
                "-finline-limit=2000",
                "-mtune=alderlake",
                "-fira-algorithm=priority",
            ],
        }.items():
            for flag in flags:
                benchmark.extend(["--case-cflag", f"{name}={flag}"])
        benchmark.extend(["--audit-mode", "default=default-call-allowed"])
        for name in (
            "inline_700",
            "inline_2000",
            "alderlake_700",
            "alderlake_2000",
            "alderlake_ira",
        ):
            benchmark.extend(["--audit-mode", f"{name}=full-inline-320"])
        benchmark.extend(
            [
                "--cpu",
                "none",
                "--iterations",
                "1000",
                "--warmups",
                "1",
                "--samples",
                "5",
                "--random-cases",
                str(args.random_cases),
                "--extra-cflag=-Werror",
                "--json",
                "/output/correctness-smoke.json",
            ]
        )
        run_container(args.runtime, root, temporary, benchmark)

        generic = json.loads((temporary / "generic-audit.json").read_text())
        alderlake = json.loads((temporary / "alderlake-audit.json").read_text())
        alderlake_ira = json.loads(
            (temporary / "alderlake-ira-audit.json").read_text()
        )
        smoke = json.loads((temporary / "correctness-smoke.json").read_text())

        generic_700 = generic["builds"]["inline_700"]
        generic_2000 = generic["builds"]["inline_2000"]
        alderlake_700 = alderlake["builds"]["inline_700"]
        alderlake_2000 = alderlake["builds"]["inline_2000"]
        alderlake_ira_700 = alderlake_ira["builds"]["inline_700"]
        alderlake_ira_2000 = alderlake_ira["builds"]["inline_2000"]
        verification = smoke["candidate_verification"]
        measured_audits = smoke["assembly_audits"]
        checks: dict[str, bool] = {
            "compiler_is_exact_gcc_13_3_0": generic["compiler"]
            == "gcc (GCC) 13.3.0",
            "source_hash_matches_all_audits": generic["source"]["sha256"]
            == alderlake["source"]["sha256"]
            == alderlake_ira["source"]["sha256"]
            == sha256(source),
            "generic_700_binary_equals_2000": generic_700["binary_sha256"]
            == generic_2000["binary_sha256"],
            "alderlake_700_binary_equals_2000": alderlake_700["binary_sha256"]
            == alderlake_2000["binary_sha256"],
            "generic_and_alderlake_hot_loops_differ": generic_2000[
                "normalized_loop_sha256"
            ]
            != alderlake_2000["normalized_loop_sha256"],
            "alderlake_ira_700_binary_equals_2000": alderlake_ira_700[
                "binary_sha256"
            ]
            == alderlake_ira_2000["binary_sha256"],
            "alderlake_and_alderlake_ira_hot_loops_differ": alderlake_2000[
                "normalized_loop_sha256"
            ]
            != alderlake_ira_2000["normalized_loop_sha256"],
            "all_direct_random_differential_gates_pass": all(
                item["status"] == "PASS" for item in verification.values()
            ),
            "all_exact_measured_binary_audits_pass": all(
                item["status"] == "PASS" for item in measured_audits.values()
            ),
        }
        if not all(checks.values()):
            failed = [name for name, passed in checks.items() if not passed]
            raise RuntimeError(f"GCC 13.3 reproduction checks failed: {failed}")

        output: dict[str, Any] = {
            "schema_version": 1,
            "experiment": "challenge02_exact_gcc133_codegen",
            "container_image": IMAGE,
            "compiler": generic["compiler"],
            "objdump": generic["objdump"],
            "source": generic["source"],
            "random_differential_cases_per_candidate": args.random_cases,
            "checks": checks,
            "unmodified_source_audits": {
                "generic": generic,
                "alderlake": alderlake,
                "alderlake_ira_priority": alderlake_ira,
            },
            "correctness_gate": verification,
            "measured_binary_audits": measured_audits,
            "notes": [
                "Every completed smoke process also passed the supplied one-round "
                "and twenty-round vectors; otherwise the benchmark exits nonzero.",
                "The 1000-iteration smoke timings are deliberately excluded: the "
                "container host is not evidence about Core Ultra 7 255H performance.",
                "The digest-pinned Docker image uses its own default link settings, "
                "so complete binary hashes are provenance for this exact reproducer.",
            ],
        }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.json.with_suffix(args.json.suffix + ".tmp")
    temporary_output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_output, args.json)
    print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
