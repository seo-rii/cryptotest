#!/usr/bin/env python3
"""Compile, test, and benchmark the portable challenge 2 implementations."""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZipFile


def run(command: list[str], *, capture: bool = False) -> str:
    print("$", shlex.join(command), flush=True)
    completed = subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )
    if capture:
        print(completed.stdout, end="")
        return completed.stdout
    return ""


def cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", default=os.environ.get("CC", "gcc"))
    parser.add_argument("--iterations", type=int, default=1_000_000)
    parser.add_argument("--repeats", type=int, default=9)
    parser.add_argument("--random-cases", type=int, default=10_000)
    parser.add_argument(
        "--native",
        action="store_true",
        help="also use -march=native; omitted by default for portable results",
    )
    args = parser.parse_args()
    if args.iterations <= 0 or args.repeats <= 0 or args.random_cases <= 0:
        parser.error("iterations, repeats, and random-cases must be positive")

    root = Path(__file__).resolve().parents[1]
    source = root / "solutions" / "solve_02_permutation.c"
    archive = root / "problems" / "2_암호구현.zip"

    with tempfile.TemporaryDirectory(prefix="challenge02-") as directory:
        temporary = Path(directory)
        executable = temporary / "solve_02_permutation"
        with ZipFile(archive) as zipped:
            vector1 = temporary / "testvector.txt"
            vector20 = temporary / "testvector_20round.txt"
            vector1.write_bytes(zipped.read("code/testvector.txt"))
            vector20.write_bytes(zipped.read("code/testvector_20round.txt"))

        flags = [
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-DNDEBUG",
        ]
        if args.native:
            flags.append("-march=native")
        compile_command = [args.compiler, *flags, str(source), "-o", str(executable)]

        print(f"host_os={platform.platform()}")
        print(f"cpu={cpu_model()}")
        compiler_version = subprocess.run(
            [args.compiler, "--version"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.splitlines()[0]
        print(f"compiler={compiler_version}")
        print("timer=clock_gettime(CLOCK_MONOTONIC)")
        print("measurement=single process, alternating order, median reported")
        run(compile_command)
        run(
            [
                str(executable),
                "--selftest",
                str(vector1),
                str(vector20),
                str(args.random_cases),
            ]
        )
        run(
            [
                str(executable),
                "--benchmark",
                str(args.iterations),
                str(args.repeats),
            ]
        )


if __name__ == "__main__":
    main()
