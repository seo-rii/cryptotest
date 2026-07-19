#!/usr/bin/env python3
"""Compile challenge 2 score builds and audit the actual main timing loop."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


SOLUTIONS = Path(__file__).resolve().parents[1]
if str(SOLUTIONS) not in sys.path:
    sys.path.insert(0, str(SOLUTIONS))

from challenge02_loop_audit import (  # noqa: E402
    audit_main_timing_loop,
    format_loop_summary,
    validate_loop_audit,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the default, portable, and cross-call-inline builds; "
            "locate the loop between the final two clock() calls in main; and "
            "audit the exact linked binaries."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("submissions/02/contest.c"),
        help="contest source relative to the repository root",
    )
    parser.add_argument(
        "--portable-source",
        type=Path,
        default=Path("solutions/02_optimization/contest_inline_unrolled.c"),
        help="portable forced-inline control compared with the BMI2 score loop",
    )
    parser.add_argument("--compiler", default="gcc")
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("--size-tool", default="size")
    parser.add_argument(
        "--inline-limit",
        action="append",
        type=int,
        dest="inline_limits",
        help="score-build inline limit; repeatable (defaults: 700 and 2000)",
    )
    parser.add_argument(
        "--extra-cflag",
        action="append",
        default=[],
        metavar="FLAG",
        help="compiler flag applied to every build (repeatable)",
    )
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="report rather than fail when an inline loop misses its expected shape",
    )
    parser.add_argument("--json", type=Path, help="write the complete audit report")
    args = parser.parse_args()

    limits = args.inline_limits or [700, 2000]
    if any(limit <= 0 for limit in limits):
        parser.error("--inline-limit values must be positive")
    if len(set(limits)) != len(limits):
        parser.error("--inline-limit values must be unique")

    root = Path(__file__).resolve().parents[2]
    source = args.source if args.source.is_absolute() else root / args.source
    portable_source = (
        args.portable_source
        if args.portable_source.is_absolute()
        else root / args.portable_source
    )
    if not source.is_file():
        parser.error(f"source does not exist: {source}")
    if not portable_source.is_file():
        parser.error(f"portable source does not exist: {portable_source}")

    compiler_version = subprocess.run(
        [args.compiler, "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()[0]
    objdump_version = subprocess.run(
        [args.objdump, "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()[0]

    specifications: list[tuple[str, Path, list[str], str]] = [
        ("default", source, [], "default-call-allowed"),
        (
            "portable_inline",
            portable_source,
            [f"-finline-limit={max(limits)}"],
            "portable-inline-320",
        ),
    ]
    specifications.extend(
        (
            f"inline_{limit}",
            source,
            ["-mbmi2", f"-finline-limit={limit}"],
            "full-inline-320",
        )
        for limit in limits
    )

    reports: dict[str, dict[str, object]] = {}
    print(f"compiler={compiler_version}")
    print(f"objdump={objdump_version}")
    print(f"source={source}")
    print(f"portable_source={portable_source}")

    with tempfile.TemporaryDirectory(prefix="challenge02-asm-audit-") as directory:
        temporary = Path(directory)
        for name, case_source, case_flags, audit_mode in specifications:
            binary = temporary / name
            command = [
                args.compiler,
                "-O3",
                "-Wall",
                "-Wextra",
                *args.extra_cflag,
                *case_flags,
                str(case_source),
                "-o",
                str(binary),
            ]
            print("$", shlex.join(command))
            subprocess.run(command, check=True)

            report = audit_main_timing_loop(
                binary,
                objdump=args.objdump,
                size_tool=args.size_tool,
            )
            report["source"] = {
                "path": (
                    str(case_source.relative_to(root))
                    if case_source.is_relative_to(root)
                    else str(case_source)
                ),
                "sha256": hashlib.sha256(case_source.read_bytes()).hexdigest(),
            }
            report["flags"] = [
                "-O3",
                "-Wall",
                "-Wextra",
                *args.extra_cflag,
                *case_flags,
            ]
            report["audit_mode"] = audit_mode
            errors = validate_loop_audit(report, audit_mode)
            report["audit_status"] = "PASS" if not errors else "FAIL"
            report["audit_errors"] = errors
            reports[name] = report
            print(format_loop_summary(name, report))
            print(
                f"audit={report['audit_status']} mode={audit_mode} "
                f"hash={report['normalized_loop_sha256']}"
            )
            if errors and not args.no_strict:
                raise RuntimeError(f"{name}: timing-loop audit failed: {errors}")

    score_hashes = {
        str(reports[f"inline_{limit}"]["normalized_loop_sha256"])
        for limit in limits
    }
    score_binary_hashes = {
        str(reports[f"inline_{limit}"]["binary_sha256"]) for limit in limits
    }
    print(f"inline_loop_hashes_equal={len(score_hashes) == 1}")
    print(f"inline_binaries_equal={len(score_binary_hashes) == 1}")

    if args.json:
        try:
            source_path = str(source.relative_to(root))
        except ValueError:
            source_path = str(source)
        output = {
            "schema_version": 2,
            "audit": "challenge02_main_timing_loop",
            "compiler": compiler_version,
            "objdump": objdump_version,
            "source": {
                "path": source_path,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
            "portable_source": {
                "path": (
                    str(portable_source.relative_to(root))
                    if portable_source.is_relative_to(root)
                    else str(portable_source)
                ),
                "sha256": hashlib.sha256(portable_source.read_bytes()).hexdigest(),
            },
            "inline_limits": limits,
            "inline_loop_hashes_equal": len(score_hashes) == 1,
            "inline_binaries_equal": len(score_binary_hashes) == 1,
            "builds": reports,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
        print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
