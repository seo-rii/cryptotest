#!/usr/bin/env python3
"""Reproduce challenge 2 code generation with the pinned official GCC 13.3 image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
        expected_smoke_cases = {
            "default",
            "inline_700",
            "inline_2000",
            "alderlake_700",
            "alderlake_2000",
            "alderlake_ira",
        }
        if smoke.get("schema_version") != 5:
            raise RuntimeError(
                f"correctness smoke schema is not 5: {smoke.get('schema_version')!r}"
            )
        smoke_config = smoke.get("config", {})
        if not (
            smoke_config.get("iterations") == 1000
            and smoke_config.get("warmups") == 1
            and smoke_config.get("samples_per_case") == 5
            and smoke_config.get("timed_main_repeated_call_validation") is True
        ):
            raise RuntimeError("correctness smoke process counts changed")
        timed_validation = smoke.get("timed_main_validation")
        if not isinstance(timed_validation, dict):
            raise RuntimeError("correctness smoke omitted timed_main_validation")
        if set(timed_validation) != {"oracle", "cases"}:
            raise RuntimeError("correctness smoke timed-main validation shape changed")
        timed_oracle = timed_validation.get("oracle")
        timed_cases = timed_validation.get("cases")
        if not isinstance(timed_oracle, dict) or not isinstance(timed_cases, dict):
            raise RuntimeError("correctness smoke timed-main validation is malformed")
        if set(timed_oracle) != {
            "mode",
            "iterations",
            "expected_final_state",
            "stdout_sha256",
            "status",
        }:
            raise RuntimeError("correctness smoke timed-main oracle shape changed")
        if set(timed_cases) != expected_smoke_cases:
            raise RuntimeError(
                f"correctness smoke timed-main case set changed: {sorted(timed_cases)!r}"
            )
        expected_state = timed_oracle.get("expected_final_state")
        valid_state = (
            isinstance(expected_state, list)
            and len(expected_state) == 4
            and all(
                isinstance(word, str) and re.fullmatch(r"[0-9a-f]{16}", word)
                for word in expected_state
            )
        )
        canonical_oracle_hash = (
            hashlib.sha256(
                (
                    "oracle_final_state_iterations=1000\n"
                    f"oracle_final_state={' '.join(expected_state)}\n"
                ).encode()
            ).hexdigest()
            if valid_state
            else None
        )
        if not (
            timed_oracle.get("mode")
            == "independent-reference-repeated-20-rounds"
            and type(timed_oracle.get("iterations")) is int
            and timed_oracle.get("iterations") == 1000
            and valid_state
            and isinstance(timed_oracle.get("stdout_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", timed_oracle["stdout_sha256"])
            and timed_oracle.get("stdout_sha256") == canonical_oracle_hash
            and timed_oracle.get("status") == "PASS"
        ):
            raise RuntimeError("correctness smoke timed-main oracle did not pass")
        for candidate, timed_case in timed_cases.items():
            if isinstance(timed_case, dict) and set(timed_case) != {
                "iterations",
                "observed_final_state",
                "preflight_processes",
                "warmup_processes",
                "measured_processes",
                "validated_processes",
                "status",
            }:
                raise RuntimeError(
                    f"{candidate}: correctness smoke timed-main case shape changed"
                )
            if not isinstance(timed_case, dict) or not (
                all(
                    type(timed_case.get(field)) is int
                    for field in (
                        "iterations",
                        "preflight_processes",
                        "warmup_processes",
                        "measured_processes",
                        "validated_processes",
                    )
                )
                and timed_case.get("iterations") == 1000
                and timed_case.get("observed_final_state") == expected_state
                and timed_case.get("preflight_processes") == 1
                and timed_case.get("warmup_processes") == 1
                and timed_case.get("measured_processes") == 5
                and timed_case.get("validated_processes") == 7
                and timed_case.get("status") == "PASS"
            ):
                raise RuntimeError(
                    f"{candidate}: correctness smoke timed-main validation failed"
                )

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
            "all_timed_main_validations_pass": (
                timed_oracle["status"] == "PASS"
                and all(item["status"] == "PASS" for item in timed_cases.values())
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
            "timed_main_validation": timed_validation,
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
