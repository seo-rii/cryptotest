#!/usr/bin/env python3
"""Differentially verify and benchmark contest-shaped challenge 2 submissions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import secrets
import shutil
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on non-POSIX hosts
    resource = None  # type: ignore[assignment]

if __package__:
    from .challenge02_loop_audit import (
        AUDIT_MODES,
        audit_main_timing_loop,
        format_loop_summary,
        validate_loop_audit,
    )
else:
    from challenge02_loop_audit import (
        AUDIT_MODES,
        audit_main_timing_loop,
        format_loop_summary,
        validate_loop_audit,
    )


TIMING_PATTERN = re.compile(
    r"^average per 20rounds = ([0-9]+(?:\.[0-9]+)?) us$", re.MULTILINE
)
TOTAL_ELAPSED_PATTERN = re.compile(
    r"^total elapsed time\s+=\s+([0-9]+(?:\.[0-9]+)?) sec$",
    re.MULTILINE,
)
FINAL_STATE_PATTERN = re.compile(
    r"^benchmark final state = "
    r"([0-9a-fA-F]{16}) ([0-9a-fA-F]{16}) "
    r"([0-9a-fA-F]{16}) ([0-9a-fA-F]{16})$",
    re.MULTILINE,
)
ITERATIONS_OUTPUT_PATTERN = re.compile(
    r"^iterations\s+=\s+([0-9]+)$", re.MULTILINE
)
ORACLE_FINAL_STATE_PATTERN = re.compile(
    r"^oracle_final_state="
    r"([0-9a-fA-F]{16}) ([0-9a-fA-F]{16}) "
    r"([0-9a-fA-F]{16}) ([0-9a-fA-F]{16})$",
    re.MULTILINE,
)
ORACLE_ITERATIONS_PATTERN = re.compile(
    r"^oracle_final_state_iterations=([0-9]+)$", re.MULTILINE
)
ITERATIONS_PATTERN = re.compile(r"const int iterations = [0-9]+;")
MIN_CHILD_CPU_COVERAGE_ITERATIONS = 1_000_000
MIN_MEDIAN_CHILD_CPU_COVERAGE = 0.65
MAX_MEDIAN_CHILD_CPU_COVERAGE = 1.05
STATIONARITY_MIN_SAMPLES = 16
STATIONARITY_BLOCK_COUNT = 4
STATIONARITY_MAX_ABSOLUTE_SPREAD = 0.05
STATIONARITY_MAX_EFFECT_SPREAD = 0.02
STATIONARITY_EFFECT_SIGN_MARGIN = 0.005


def timing_stationarity_evidence(
    samples: dict[str, list[float]], baseline: str
) -> dict[str, object]:
    """Build a conservative, fixed-design stationarity promotion gate.

    Four chronological blocks and all thresholds are fixed before looking at
    the observations.  This deliberately avoids selecting a favorable change
    point or significance level after seeing the data.  Absolute block medians
    catch sustained clock/load phase changes; paired-ratio block medians catch
    a candidate whose apparent effect changes over time.

    This is a promotion guard, not a statistical proof of stationarity.  It can
    miss short excursions or changes hidden inside a block, and process-order
    or thermal interactions may remain even when every block contains complete
    balanced-order rotations.
    """

    names = sorted(samples)
    if baseline not in samples:
        raise ValueError("stationarity baseline is absent from raw samples")
    if not names:
        raise ValueError("stationarity analysis requires at least one case")
    lengths = {len(samples[name]) for name in names}
    if len(lengths) != 1:
        raise ValueError("stationarity raw sample lengths differ")
    sample_count = lengths.pop()
    if sample_count == 0:
        raise ValueError("stationarity raw samples are empty")
    for name in names:
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) <= 0.0
            for value in samples[name]
        ):
            raise ValueError(
                f"stationarity raw samples for {name} must be finite and positive"
            )

    block_ranges = [
        {
            "start": block * sample_count // STATIONARITY_BLOCK_COUNT,
            "stop": (block + 1) * sample_count // STATIONARITY_BLOCK_COUNT,
        }
        for block in range(STATIONARITY_BLOCK_COUNT)
    ]
    enough_samples = sample_count >= STATIONARITY_MIN_SAMPLES
    order_balanced = (
        sample_count % (STATIONARITY_BLOCK_COUNT * len(names)) == 0
    )
    preconditions_pass = enough_samples and order_balanced
    precondition_reasons: list[str] = []
    if not enough_samples:
        precondition_reasons.append(
            f"at least {STATIONARITY_MIN_SAMPLES} samples per case are required"
        )
    if not order_balanced:
        precondition_reasons.append(
            "sample count must be a multiple of four times the case count so "
            "each fixed block balances case positions"
        )

    cases: dict[str, dict[str, object]] = {}
    for name in names:
        values = [float(value) for value in samples[name]]
        block_medians = [
            statistics.median(values[block["start"] : block["stop"]])
            for block in block_ranges
        ]
        spread = max(block_medians) / min(block_medians) - 1.0
        reasons: list[str] = []
        if preconditions_pass and spread > STATIONARITY_MAX_ABSOLUTE_SPREAD:
            reasons.append(
                "absolute block-median spread exceeds the fixed 5% limit"
            )
        status = (
            "NOT_ENFORCED"
            if not preconditions_pass
            else ("PASS" if not reasons else "FAIL")
        )
        cases[name] = {
            "block_median_ns": block_medians,
            "max_to_min_ratio_minus_one": spread,
            "status": status,
            "reasons": reasons,
        }

    comparisons: dict[str, dict[str, object]] = {}
    baseline_values = [float(value) for value in samples[baseline]]
    for name in names:
        if name == baseline:
            continue
        candidate_values = [float(value) for value in samples[name]]
        ratios = [
            baseline_value / candidate_value
            for baseline_value, candidate_value in zip(
                baseline_values, candidate_values
            )
        ]
        block_medians = [
            statistics.median(ratios[block["start"] : block["stop"]])
            for block in block_ranges
        ]
        spread = max(block_medians) / min(block_medians) - 1.0
        sign_instability = (
            min(block_medians) < 1.0 - STATIONARITY_EFFECT_SIGN_MARGIN
            and max(block_medians) > 1.0 + STATIONARITY_EFFECT_SIGN_MARGIN
        )
        reasons: list[str] = []
        if preconditions_pass:
            if cases[baseline]["status"] != "PASS":
                reasons.append("baseline absolute timing is nonstationary")
            if cases[name]["status"] != "PASS":
                reasons.append("candidate absolute timing is nonstationary")
            if spread > STATIONARITY_MAX_EFFECT_SPREAD:
                reasons.append(
                    "paired-effect block-median spread exceeds the fixed 2% limit"
                )
            if sign_instability:
                reasons.append(
                    "paired effect crosses both sides of parity by more than 0.5%"
                )
        status = (
            "NOT_ENFORCED"
            if not preconditions_pass
            else ("PASS" if not reasons else "FAIL")
        )
        comparisons[name] = {
            "block_paired_median_ratio": block_medians,
            "max_to_min_ratio_minus_one": spread,
            "material_sign_instability": sign_instability,
            "status": status,
            "eligibility": "eligible" if status == "PASS" else "diagnostic-only",
            "reasons": reasons,
        }

    campaign_reasons = list(precondition_reasons)
    if preconditions_pass and cases[baseline]["status"] != "PASS":
        campaign_reasons.append("baseline absolute timing is nonstationary")
    campaign_status = (
        "NOT_ENFORCED"
        if not preconditions_pass
        else ("PASS" if not campaign_reasons else "FAIL")
    )
    return {
        "schema_version": 1,
        "method": "four-fixed-contiguous-block-medians",
        "baseline": baseline,
        "case_names": names,
        "sample_count_per_case": sample_count,
        "block_ranges": block_ranges,
        "order_period_samples": 2 * len(names),
        "preconditions": {
            "minimum_samples": STATIONARITY_MIN_SAMPLES,
            "sample_count_multiple_of_four_case_count": order_balanced,
            "status": "PASS" if preconditions_pass else "FAIL",
            "reasons": precondition_reasons,
        },
        "thresholds": {
            "max_absolute_block_median_spread": (
                STATIONARITY_MAX_ABSOLUTE_SPREAD
            ),
            "max_paired_effect_block_median_spread": (
                STATIONARITY_MAX_EFFECT_SPREAD
            ),
            "paired_effect_sign_margin": STATIONARITY_EFFECT_SIGN_MARGIN,
        },
        "cases": cases,
        "comparisons": comparisons,
        "status": campaign_status,
        "campaign_eligibility": (
            "eligible" if campaign_status == "PASS" else "diagnostic-only"
        ),
        "reasons": campaign_reasons,
    }


def parse_contest_timing_output(stdout: str) -> dict[str, object]:
    """Parse the unique repeated-call result emitted by one contest process."""

    states = FINAL_STATE_PATTERN.findall(stdout)
    iterations = ITERATIONS_OUTPUT_PATTERN.findall(stdout)
    elapsed_times = TOTAL_ELAPSED_PATTERN.findall(stdout)
    timings = TIMING_PATTERN.findall(stdout)
    counts = (len(states), len(iterations), len(elapsed_times), len(timings))
    if counts != (1, 1, 1, 1):
        raise ValueError(
            "expected exactly one final-state, iterations, total-time, and "
            "average-time line; "
            f"found {counts}"
        )
    iteration_count = int(iterations[0])
    if iteration_count <= 0:
        raise ValueError("reported iteration count must be positive")
    elapsed_text = elapsed_times[0]
    average_text = timings[0]
    elapsed = Decimal(elapsed_text)
    average = Decimal(average_text)
    if elapsed <= 0 or average <= 0:
        raise ValueError("reported total and average timing must be positive")

    elapsed_error = Decimal(5).scaleb(
        -len(elapsed_text.partition(".")[2]) - 1
    )
    average_error = Decimal(5).scaleb(
        -len(average_text.partition(".")[2]) - 1
    )
    multiplier = Decimal(1_000_000) / Decimal(iteration_count)
    average_from_elapsed_low = max(
        Decimal(0), elapsed - elapsed_error
    ) * multiplier
    average_from_elapsed_high = (elapsed + elapsed_error) * multiplier
    average_print_low = max(Decimal(0), average - average_error)
    average_print_high = average + average_error
    if (
        average_from_elapsed_high < average_print_low
        or average_print_high < average_from_elapsed_low
    ):
        raise ValueError(
            "reported average is inconsistent with total elapsed time and "
            f"iterations ({average_text} us vs {elapsed_text} sec / "
            f"{iteration_count})"
        )
    return {
        "final_state": tuple(value.lower() for value in states[0]),
        "iterations": iteration_count,
        "total_elapsed_s": float(elapsed),
        "printed_average_us": float(average),
        "internal_ns": float(
            elapsed * Decimal(1_000_000_000) / Decimal(iteration_count)
        ),
    }


def parse_oracle_final_state(stdout: str) -> tuple[int, tuple[str, str, str, str]]:
    """Parse the independent oracle's unique repeated-call result."""

    states = ORACLE_FINAL_STATE_PATTERN.findall(stdout)
    iterations = ORACLE_ITERATIONS_PATTERN.findall(stdout)
    if len(states) != 1 or len(iterations) != 1:
        raise ValueError(
            "expected exactly one oracle final-state and iterations line; "
            f"found states={len(states)} iterations={len(iterations)}"
        )
    state = tuple(value.lower() for value in states[0])
    return int(iterations[0]), state


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compile and directly differential-test complete contest.c variants, "
            "discard warmups, interleave runs, and report paired statistics."
        )
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        metavar="NAME=SOURCE",
        help="contest.c variant; defaults to the preserved before/final pair",
    )
    parser.add_argument("--baseline", help="case name used as the speedup denominator")
    parser.add_argument("--compiler", default=os.environ.get("CC", "gcc"))
    parser.add_argument(
        "--iterations",
        type=int,
        default=5_000_000,
        help="timed outer-loop calls per process (official harness uses 1000000)",
    )
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--samples", "--repeats", dest="samples", type=int, default=21)
    parser.add_argument(
        "--random-cases",
        type=int,
        default=100_000,
        help=(
            "random states and add/XOR constants checked directly against every "
            "candidate before timing"
        ),
    )
    parser.add_argument(
        "--cpu",
        default="auto",
        help="Linux logical CPU number, 'auto' for the first allowed CPU, or 'none'",
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="add -march=native; default flags match the supplied run script",
    )
    parser.add_argument(
        "--extra-cflag",
        action="append",
        default=[],
        metavar="FLAG",
        help="compiler flag applied to every case (repeatable)",
    )
    parser.add_argument(
        "--case-cflag",
        action="append",
        default=[],
        metavar="NAME=FLAG",
        help="compiler flag applied only to one named case (repeatable)",
    )
    parser.add_argument(
        "--audit-mode",
        action="append",
        default=[],
        metavar="NAME=MODE",
        help=(
            "audit the exact measured binary before warmup; MODE is one of "
            + ", ".join(sorted(AUDIT_MODES))
        ),
    )
    parser.add_argument("--objdump", default="objdump")
    parser.add_argument("--size-tool", default="size")
    parser.add_argument(
        "--campaign-id",
        help="opaque run nonce supplied by a higher-level campaign orchestrator",
    )
    parser.add_argument("--json", type=Path, help="write metadata, raw samples, and summaries")
    args = parser.parse_args()

    if args.iterations <= 0 or args.random_cases <= 0:
        parser.error("--iterations and --random-cases must be positive")
    if args.warmups < 1:
        parser.error("--warmups must be at least 1")
    if args.samples < 5:
        parser.error("--samples must be at least 5")
    if resource is None or not hasattr(resource, "RUSAGE_CHILDREN"):
        parser.error(
            "child CPU accounting is unavailable; timing validation requires "
            "POSIX getrusage(RUSAGE_CHILDREN)"
        )
    if args.campaign_id is not None and not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", args.campaign_id
    ):
        parser.error(
            "--campaign-id must use 1-128 letters, digits, dots, underscores, or hyphens"
        )

    root = Path(__file__).resolve().parents[1]
    git_commit: str | None = None
    git_dirty: bool | None = None
    git_executable = shutil.which("git")
    if git_executable is not None:
        commit_process = subprocess.run(
            [git_executable, "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        status_process = subprocess.run(
            [git_executable, "status", "--porcelain=v1", "--untracked-files=normal"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if commit_process.returncode == 0:
            git_commit = commit_process.stdout.strip()
        if status_process.returncode == 0:
            git_dirty = bool(status_process.stdout)
    specifications = args.case or [
        "before=solutions/02_optimization/contest_before.c",
        "optimized=submissions/02/contest.c",
    ]
    cases: list[tuple[str, Path]] = []
    seen_names: set[str] = set()
    for specification in specifications:
        if "=" not in specification:
            parser.error(f"invalid --case {specification!r}; expected NAME=SOURCE")
        name, source_text = specification.split("=", 1)
        source = Path(source_text)
        if not source.is_absolute():
            source = root / source
        name = name.strip()
        if not name or name in seen_names:
            parser.error(f"empty or duplicate case name: {name!r}")
        if not source.is_file():
            parser.error(f"source does not exist: {source}")
        seen_names.add(name)
        cases.append((name, source))
    if len(cases) < 2:
        parser.error("provide at least two cases so speedup can be measured")

    case_flags: dict[str, list[str]] = {name: [] for name, _ in cases}
    for specification in args.case_cflag:
        if "=" not in specification:
            parser.error(
                f"invalid --case-cflag {specification!r}; expected NAME=FLAG"
            )
        name, flag = specification.split("=", 1)
        name = name.strip()
        flag = flag.strip()
        if name not in case_flags:
            parser.error(f"unknown --case-cflag case: {name!r}")
        if not flag:
            parser.error(f"empty flag in --case-cflag {specification!r}")
        case_flags[name].append(flag)

    audit_modes: dict[str, str] = {}
    for specification in args.audit_mode:
        if "=" not in specification:
            parser.error(f"invalid --audit-mode {specification!r}; expected NAME=MODE")
        name, mode = (part.strip() for part in specification.split("=", 1))
        if name not in case_flags:
            parser.error(f"unknown --audit-mode case: {name!r}")
        if name in audit_modes:
            parser.error(f"duplicate --audit-mode case: {name!r}")
        if mode not in AUDIT_MODES:
            parser.error(
                f"unknown audit mode {mode!r}; choose one of {sorted(AUDIT_MODES)}"
            )
        audit_modes[name] = mode

    baseline = args.baseline or cases[0][0]
    if baseline not in seen_names:
        parser.error(f"unknown --baseline case: {baseline}")

    resolved_objdump: Path | None = None
    resolved_size_tool: Path | None = None
    if args.json or audit_modes:
        for label, requested in (
            ("objdump", args.objdump),
            ("size", args.size_tool),
        ):
            located = shutil.which(requested)
            executable = Path(located or requested).expanduser().resolve()
            if not executable.is_file():
                parser.error(f"{label} executable does not exist: {requested}")
            if label == "objdump":
                resolved_objdump = executable
            else:
                resolved_size_tool = executable

    affinity: list[int] | None = None
    if hasattr(os, "sched_getaffinity"):
        available = sorted(os.sched_getaffinity(0))
        if args.cpu == "auto":
            os.sched_setaffinity(0, {available[0]})
        elif args.cpu != "none":
            try:
                selected_cpu = int(args.cpu)
            except ValueError:
                parser.error("--cpu must be an integer, 'auto', or 'none'")
            if selected_cpu not in available:
                parser.error(f"CPU {selected_cpu} is unavailable; choose one of {available}")
            os.sched_setaffinity(0, {selected_cpu})
        affinity = sorted(os.sched_getaffinity(0))
    elif args.cpu not in ("auto", "none"):
        parser.error("numeric --cpu requires sched_setaffinity support")

    cpu = platform.processor() or "unknown"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break

    compiler_version = subprocess.run(
        [args.compiler, "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()[0]
    objdump_version: str | None = None
    size_tool_version: str | None = None
    if audit_modes:
        assert resolved_objdump is not None and resolved_size_tool is not None
        objdump_version = subprocess.run(
            [str(resolved_objdump), "--version"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.splitlines()[0]
        size_tool_version = subprocess.run(
            [str(resolved_size_tool), "--version"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        ).stdout.splitlines()[0]
    flags = ["-O3", "-Wall", "-Wextra"]
    if args.native:
        flags.append("-march=native")
    flags.extend(args.extra_cflag)

    print(f"host={platform.platform()}")
    print(f"cpu={cpu}")
    print(f"affinity={affinity if affinity is not None else 'unsupported'}")
    print(f"compiler={compiler_version}")
    if objdump_version is not None:
        print(f"objdump={objdump_version}")
        print(f"size_tool={size_tool_version}")
    print(f"cflags={shlex.join(flags)}")
    for name, _ in cases:
        print(
            f"case_cflags[{name}]="
            f"{shlex.join(case_flags[name]) if case_flags[name] else '(none)'}"
        )
    print("inner_timer=clock() from supplied contest harness")
    print("outer_timer=time.perf_counter_ns")
    print(f"iterations={args.iterations} warmups={args.warmups} samples={args.samples}")
    print("order=balanced cyclic rotations, then reversed rotations", flush=True)

    archive = root / "problems" / "2_암호구현.zip"
    candidate_verifier_source = (
        root / "solutions" / "02_optimization" / "verify_contest_candidate_02.c"
    )
    internal_samples: dict[str, list[float]] = {name: [] for name, _ in cases}
    inner_elapsed_samples: dict[str, list[float]] = {
        name: [] for name, _ in cases
    }
    printed_average_samples: dict[str, list[float]] = {
        name: [] for name, _ in cases
    }
    wall_samples: dict[str, list[float]] = {name: [] for name, _ in cases}
    child_cpu_samples: dict[str, list[float]] = {name: [] for name, _ in cases}
    source_snapshots = {name: source.read_bytes() for name, source in cases}
    source_hashes = {
        name: hashlib.sha256(source_snapshots[name]).hexdigest()
        for name, _ in cases
    }
    semantic_challenge_nonce = secrets.token_hex(16)
    semantic_challenge_derivation_payload = {
        "schema_version": 1,
        "campaign_id": args.campaign_id,
        "nonce_hex": semantic_challenge_nonce,
        "measured_iterations": args.iterations,
        "source_sha256": dict(sorted(source_hashes.items())),
    }
    semantic_challenge_digest = hashlib.sha256(
        json.dumps(
            semantic_challenge_derivation_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    semantic_challenge_iterations = 4_096 + (
        int(semantic_challenge_digest[:16], 16) % 61_440
    )
    if semantic_challenge_iterations == args.iterations:
        semantic_challenge_iterations = (
            4_096 + (semantic_challenge_iterations - 4_096 + 1) % 61_440
        )

    with tempfile.TemporaryDirectory(prefix="challenge02-repeat-") as directory:
        temporary = Path(directory)
        with ZipFile(archive) as zipped:
            vector1 = temporary / "testvector.txt"
            vector20 = temporary / "testvector_20round.txt"
            vector1.write_bytes(zipped.read("code/testvector.txt"))
            vector20.write_bytes(zipped.read("code/testvector_20round.txt"))

        oracle = temporary / "differential_oracle"
        oracle_compile = [
            args.compiler,
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            str(root / "solutions" / "solve_02_permutation.c"),
            "-o",
            str(oracle),
        ]
        print("$", shlex.join(oracle_compile), flush=True)
        subprocess.run(oracle_compile, check=True)
        oracle_run = [
            str(oracle),
            "--selftest",
            str(vector1),
            str(vector20),
            str(args.random_cases),
        ]
        print("$", shlex.join(oracle_run), flush=True)
        subprocess.run(oracle_run, check=True)

        oracle_final_command = [
            str(oracle),
            "--final-state",
            str(args.iterations),
        ]
        print("$", shlex.join(oracle_final_command), flush=True)
        oracle_final_run = subprocess.run(
            oracle_final_command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            oracle_iterations, expected_final_state = parse_oracle_final_state(
                oracle_final_run.stdout
            )
        except ValueError as error:
            parser.error(
                "independent repeated-call oracle output is malformed: "
                f"{error}\nstdout:\n{oracle_final_run.stdout}\n"
                f"stderr:\n{oracle_final_run.stderr}"
            )
        if (
            oracle_final_run.returncode != 0
            or oracle_final_run.stderr
            or oracle_iterations != args.iterations
        ):
            parser.error(
                "independent repeated-call oracle validation failed "
                f"(exit {oracle_final_run.returncode}, iterations "
                f"{oracle_iterations}, expected {args.iterations})\n"
                f"stdout:\n{oracle_final_run.stdout}\n"
                f"stderr:\n{oracle_final_run.stderr}"
            )
        oracle_validation = {
            "mode": "independent-reference-repeated-20-rounds",
            "iterations": oracle_iterations,
            "expected_final_state": list(expected_final_state),
            "stdout_sha256": hashlib.sha256(
                oracle_final_run.stdout.encode()
            ).hexdigest(),
            "status": "PASS",
        }

        oracle_challenge_command = [
            str(oracle),
            "--final-state",
            str(semantic_challenge_iterations),
        ]
        print("$", shlex.join(oracle_challenge_command), flush=True)
        oracle_challenge_run = subprocess.run(
            oracle_challenge_command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            oracle_challenge_iterations, expected_challenge_final_state = (
                parse_oracle_final_state(oracle_challenge_run.stdout)
            )
        except ValueError as error:
            parser.error(
                "independent alternate-iteration oracle output is malformed: "
                f"{error}\nstdout:\n{oracle_challenge_run.stdout}\n"
                f"stderr:\n{oracle_challenge_run.stderr}"
            )
        if (
            oracle_challenge_run.returncode != 0
            or oracle_challenge_run.stderr
            or oracle_challenge_iterations != semantic_challenge_iterations
        ):
            parser.error(
                "independent alternate-iteration oracle validation failed "
                f"(exit {oracle_challenge_run.returncode}, iterations "
                f"{oracle_challenge_iterations}, expected "
                f"{semantic_challenge_iterations})\n"
                f"stdout:\n{oracle_challenge_run.stdout}\n"
                f"stderr:\n{oracle_challenge_run.stderr}"
            )
        semantic_challenge_oracle = {
            "expected_final_state": list(expected_challenge_final_state),
            "stdout_sha256": hashlib.sha256(
                oracle_challenge_run.stdout.encode()
            ).hexdigest(),
            "status": "PASS",
        }

        executables: dict[str, Path] = {}
        semantic_challenge_executables: dict[str, Path] = {}
        candidate_verification: dict[str, dict[str, object]] = {}
        assembly_audits: dict[str, dict[str, object]] = {}
        rewritten_source_hashes: dict[str, str] = {}
        source_context_flags: dict[str, list[str]] = {}
        for name, source in cases:
            rewritten, replacements = ITERATIONS_PATTERN.subn(
                f"const int iterations = {args.iterations};",
                source_snapshots[name].decode("utf-8"),
            )
            if replacements != 1:
                raise RuntimeError(
                    f"expected exactly one timing iteration declaration in {source}, "
                    f"found {replacements}"
                )
            temporary_source = temporary / f"{name}.c"
            rewritten_bytes = rewritten.encode("utf-8")
            temporary_source.write_bytes(rewritten_bytes)
            rewritten_source_hashes[name] = hashlib.sha256(
                rewritten_bytes
            ).hexdigest()
            # Rewriting the iteration count into a temporary file must not
            # change the meaning of quoted relative includes in the original
            # contest source.  Search its original directory after the
            # temporary file's directory, matching the compiler's source-local
            # include semantics without modifying the candidate.
            source_context_flags[name] = ["-iquote", str(source.parent)]

            candidate_object = temporary / f"{name}_candidate.o"
            verifier_flag_overrides = []
            if "-fwhole-program" in [*flags, *case_flags[name]]:
                # The standalone verifier must call the public permutation
                # symbols. This override affects only its object, never the
                # separately compiled performance executable.
                verifier_flag_overrides.append("-fno-whole-program")
            object_command = [
                args.compiler,
                *flags,
                *case_flags[name],
                *source_context_flags[name],
                *verifier_flag_overrides,
                "-Dmain=challenge02_contest_main",
                "-c",
                str(temporary_source),
                "-o",
                str(candidate_object),
            ]
            print("$", shlex.join(object_command), flush=True)
            subprocess.run(object_command, check=True)
            candidate_verifier = temporary / f"{name}_candidate_verifier"
            verifier_object = temporary / f"{name}_verifier.o"
            verifier_compile_command = [
                args.compiler,
                "-O3",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Wpedantic",
                "-Werror",
                "-c",
                str(candidate_verifier_source),
                "-o",
                str(verifier_object),
            ]
            print("$", shlex.join(verifier_compile_command), flush=True)
            subprocess.run(verifier_compile_command, check=True)
            verifier_link_command = [
                args.compiler,
                *flags,
                *case_flags[name],
                str(verifier_object),
                str(candidate_object),
                "-o",
                str(candidate_verifier),
            ]
            print("$", shlex.join(verifier_link_command), flush=True)
            subprocess.run(verifier_link_command, check=True)
            verifier_run = [str(candidate_verifier), str(args.random_cases)]
            print("$", shlex.join(verifier_run), flush=True)
            verified = subprocess.run(
                verifier_run,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            expected_verifier_stdout = (
                f"candidate_random_differential_cases={args.random_cases}\n"
                "candidate_random_seed=0x243f6a8885a308d3\n"
                "candidate_random_state_and_constants=PASS\n"
                "candidate_round_counts=1,20\n"
                "candidate_differential=PASS\n"
            )
            if (
                verified.returncode != 0
                or verified.stdout != expected_verifier_stdout
                or verified.stderr
            ):
                parser.error(
                    f"candidate differential validation contract failed for {name} "
                    f"(exit {verified.returncode})\nstdout:\n{verified.stdout}\n"
                    f"stderr:\n{verified.stderr}"
                )
            print(verified.stdout, end="", flush=True)
            verification_fields = dict(
                line.split("=", 1) for line in verified.stdout.splitlines()
            )
            candidate_verification[name] = {
                "random_cases": int(
                    verification_fields["candidate_random_differential_cases"]
                ),
                "seed": verification_fields["candidate_random_seed"],
                "random_state_and_constants": verification_fields[
                    "candidate_random_state_and_constants"
                ]
                == "PASS",
                "round_counts": [
                    int(value)
                    for value in verification_fields[
                        "candidate_round_counts"
                    ].split(",")
                ],
                "verifier_translation_unit_cflags": [
                    "-O3",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Wpedantic",
                    "-Werror",
                ],
                "verifier_link_cflags": [*flags, *case_flags[name]],
                "verifier_only_flag_overrides": verifier_flag_overrides,
                "status": verification_fields["candidate_differential"],
            }

            executable = temporary / name
            command = [
                args.compiler,
                *flags,
                *case_flags[name],
                *source_context_flags[name],
                str(temporary_source),
                "-o",
                str(executable),
            ]
            print("$", shlex.join(command), flush=True)
            subprocess.run(command, check=True)
            executables[name] = executable

            challenge_rewritten, challenge_replacements = ITERATIONS_PATTERN.subn(
                f"const int iterations = {semantic_challenge_iterations};",
                source_snapshots[name].decode("utf-8"),
            )
            if challenge_replacements != 1:
                raise RuntimeError(
                    "expected exactly one timing iteration declaration in "
                    f"{source} for semantic challenge, found "
                    f"{challenge_replacements}"
                )
            challenge_source = temporary / f"{name}_semantic_challenge.c"
            challenge_source.write_text(challenge_rewritten, encoding="utf-8")
            challenge_executable = temporary / f"{name}_semantic_challenge"
            challenge_command = [
                args.compiler,
                *flags,
                *case_flags[name],
                *source_context_flags[name],
                str(challenge_source),
                "-o",
                str(challenge_executable),
            ]
            print("$", shlex.join(challenge_command), flush=True)
            subprocess.run(challenge_command, check=True)
            semantic_challenge_executables[name] = challenge_executable

            if name in audit_modes:
                mode = audit_modes[name]
                audit = audit_main_timing_loop(
                    executable,
                    objdump=str(resolved_objdump),
                    size_tool=str(resolved_size_tool),
                )
                errors = validate_loop_audit(audit, mode)
                audit["mode"] = mode
                audit["status"] = "PASS" if not errors else "FAIL"
                audit["errors"] = errors
                assembly_audits[name] = audit
                print(format_loop_summary(name, audit), flush=True)
                print(
                    f"assembly_audit[{name}]={audit['status']} mode={mode} "
                    f"hash={audit['normalized_loop_sha256']}",
                    flush=True,
                )
                if errors:
                    parser.error(
                        f"assembly audit failed for measured case {name}: "
                        + "; ".join(errors)
                    )

        timed_main_semantic_challenge_cases: dict[str, dict[str, object]] = {}
        for name, _ in cases:
            print(
                "semantic_challenge "
                f"case={name} iterations={semantic_challenge_iterations}",
                flush=True,
            )
            completed = subprocess.run(
                [str(semantic_challenge_executables[name])],
                cwd=temporary,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                timed_result = parse_contest_timing_output(completed.stdout)
                parse_error = None
            except ValueError as error:
                timed_result = None
                parse_error = str(error)
            valid = (
                completed.returncode == 0
                and not completed.stderr
                and "one-round testvector verification: OK (1000 pairs checked)"
                in completed.stdout
                and "20-round testvector verification: OK" in completed.stdout
                and timed_result is not None
                and timed_result["iterations"] == semantic_challenge_iterations
                and timed_result["final_state"] == expected_challenge_final_state
            )
            if not valid:
                parser.error(
                    f"timed-main semantic challenge failed for {name} "
                    f"(exit {completed.returncode}, parse={parse_error!r})\n"
                    f"expected_iterations={semantic_challenge_iterations} "
                    "expected_final_state="
                    f"{' '.join(expected_challenge_final_state)}\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                )
            assert timed_result is not None
            timed_main_semantic_challenge_cases[name] = {
                "observed_final_state": list(timed_result["final_state"]),
                "status": "PASS",
            }

        timed_main_validation_cases: dict[str, dict[str, object]] = {}
        for name, _ in cases:
            print(f"semantic_preflight case={name}", flush=True)
            completed = subprocess.run(
                [str(executables[name])],
                cwd=temporary,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                timed_result = parse_contest_timing_output(completed.stdout)
                parse_error = None
            except ValueError as error:
                timed_result = None
                parse_error = str(error)
            valid = (
                completed.returncode == 0
                and not completed.stderr
                and "one-round testvector verification: OK (1000 pairs checked)"
                in completed.stdout
                and "20-round testvector verification: OK" in completed.stdout
                and timed_result is not None
                and timed_result["iterations"] == args.iterations
                and timed_result["final_state"] == expected_final_state
            )
            if not valid:
                parser.error(
                    f"timed-main semantic preflight failed for {name} "
                    f"(exit {completed.returncode}, parse={parse_error!r})\n"
                    f"expected_iterations={args.iterations} "
                    f"expected_final_state={' '.join(expected_final_state)}\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                )
            assert timed_result is not None
            timed_main_validation_cases[name] = {
                "iterations": args.iterations,
                "observed_final_state": list(timed_result["final_state"]),
                "preflight_processes": 1,
                "warmup_processes": args.warmups,
                "measured_processes": args.samples,
                "validated_processes": 1 + args.warmups + args.samples,
                "status": "PASS",
            }

        for warmup in range(args.warmups):
            shift = warmup % len(cases)
            order = cases[shift:] + cases[:shift]
            if (warmup // len(cases)) % 2:
                order = list(reversed(order))
            for name, _ in order:
                print(f"warmup={warmup + 1} case={name}", flush=True)
                completed = subprocess.run(
                    [str(executables[name])],
                    cwd=temporary,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                try:
                    timed_result = parse_contest_timing_output(completed.stdout)
                    parse_error = None
                except ValueError as error:
                    timed_result = None
                    parse_error = str(error)
                valid = (
                    completed.returncode == 0
                    and not completed.stderr
                    and "one-round testvector verification: OK (1000 pairs checked)"
                    in completed.stdout
                    and "20-round testvector verification: OK" in completed.stdout
                    and timed_result is not None
                    and timed_result["iterations"] == args.iterations
                    and timed_result["final_state"] == expected_final_state
                )
                if not valid:
                    parser.error(
                        f"warmup validation failed for {name} "
                        f"(exit {completed.returncode}, parse={parse_error!r})\n"
                        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
                    )

        for sample in range(args.samples):
            shift = sample % len(cases)
            order = cases[shift:] + cases[:shift]
            if (sample // len(cases)) % 2:
                order = list(reversed(order))
            for name, _ in order:
                assert resource is not None
                try:
                    child_usage_before = resource.getrusage(
                        resource.RUSAGE_CHILDREN
                    )
                except (OSError, ValueError) as error:
                    parser.error(
                        f"cannot read child CPU usage before sample: {error}"
                    )
                child_cpu_before = (
                    child_usage_before.ru_utime + child_usage_before.ru_stime
                )
                start_ns = time.perf_counter_ns()
                completed = subprocess.run(
                    [str(executables[name])],
                    cwd=temporary,
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                elapsed_s = (time.perf_counter_ns() - start_ns) / 1_000_000_000.0
                try:
                    child_usage_after = resource.getrusage(
                        resource.RUSAGE_CHILDREN
                    )
                except (OSError, ValueError) as error:
                    parser.error(
                        f"cannot read child CPU usage after sample: {error}"
                    )
                child_cpu_s = (
                    child_usage_after.ru_utime
                    + child_usage_after.ru_stime
                    - child_cpu_before
                )
                if child_cpu_s <= 0.0:
                    parser.error(
                        f"child CPU clock did not advance for measured case {name}"
                    )
                try:
                    timed_result = parse_contest_timing_output(completed.stdout)
                    parse_error = None
                except ValueError as error:
                    timed_result = None
                    parse_error = str(error)
                valid = (
                    completed.returncode == 0
                    and not completed.stderr
                    and "one-round testvector verification: OK (1000 pairs checked)"
                    in completed.stdout
                    and "20-round testvector verification: OK" in completed.stdout
                    and timed_result is not None
                    and timed_result["iterations"] == args.iterations
                    and timed_result["final_state"] == expected_final_state
                )
                if not valid:
                    parser.error(
                        f"sample {sample + 1} validation failed for {name} "
                        f"(exit {completed.returncode}, parse={parse_error!r})\n"
                        f"stdout:\n{completed.stdout}\n"
                        f"stderr:\n{completed.stderr}"
                    )
                assert timed_result is not None
                internal_ns = float(timed_result["internal_ns"])
                inner_elapsed_s = float(timed_result["total_elapsed_s"])
                printed_average_us = float(timed_result["printed_average_us"])
                internal_samples[name].append(internal_ns)
                inner_elapsed_samples[name].append(inner_elapsed_s)
                printed_average_samples[name].append(printed_average_us)
                wall_samples[name].append(elapsed_s)
                child_cpu_samples[name].append(child_cpu_s)
                print(
                    f"sample={sample + 1} case={name} "
                    f"internal_ns={internal_ns:.3f} wall_s={elapsed_s:.6f} "
                    f"child_cpu_s={child_cpu_s:.6f} "
                    f"printed_average_us={printed_average_us:.6f}",
                    flush=True,
                )

    coverage_enforced = args.iterations >= MIN_CHILD_CPU_COVERAGE_ITERATIONS
    timed_workload_cpu_coverage: dict[str, dict[str, float | str]] = {}
    for name, _ in cases:
        coverages = [
            (internal_ns * args.iterations / 1_000_000_000.0) / child_cpu_s
            for internal_ns, child_cpu_s in zip(
                internal_samples[name], child_cpu_samples[name]
            )
        ]
        median_coverage = statistics.median(coverages)
        status = "PASS" if coverage_enforced else "NOT_ENFORCED"
        timed_workload_cpu_coverage[name] = {
            "median_inner_to_child_cpu": median_coverage,
            "min_inner_to_child_cpu": min(coverages),
            "max_inner_to_child_cpu": max(coverages),
            "status": status,
        }
        if coverage_enforced and median_coverage < MIN_MEDIAN_CHILD_CPU_COVERAGE:
            parser.error(
                "timed workload child-CPU coverage is too low for "
                f"{name}: median={median_coverage:.6f}, expected at least "
                f"{MIN_MEDIAN_CHILD_CPU_COVERAGE:.2f}"
            )
        if coverage_enforced and median_coverage > MAX_MEDIAN_CHILD_CPU_COVERAGE:
            parser.error(
                "timed workload child-CPU coverage is implausibly high for "
                f"{name}: median={median_coverage:.6f}, expected at most "
                f"{MAX_MEDIAN_CHILD_CPU_COVERAGE:.2f}"
            )
    if coverage_enforced:
        print("timing_eligibility=eligible child_cpu_coverage=PASS")
    else:
        print(
            "timing_eligibility=diagnostic-only "
            "reason='iterations below 1000000; child-CPU coverage gate is not "
            "enforced'"
        )

    summaries: dict[str, dict[str, float | int]] = {}
    print("summary:")
    for case_index, (name, _) in enumerate(cases):
        values = internal_samples[name]
        median = statistics.median(values)
        deviations = [abs(value - median) for value in values]
        vingtiles = statistics.quantiles(values, n=20, method="inclusive")
        generator = random.Random(0x9E3779B97F4A7C15 + case_index)
        bootstrap = sorted(
            statistics.median(generator.choices(values, k=len(values)))
            for _ in range(5_000)
        )
        mad = statistics.median(deviations)
        summaries[name] = {
            "median_ns": median,
            "mad_ns": mad,
            "mad_percent": mad / median * 100.0,
            "p05_ns": vingtiles[0],
            "p25_ns": vingtiles[4],
            "p75_ns": vingtiles[14],
            "p95_ns": vingtiles[18],
            "min_ns": min(values),
            "max_ns": max(values),
            "bootstrap_median_ci95_low_ns": bootstrap[124],
            "bootstrap_median_ci95_high_ns": bootstrap[4_874],
            "outliers_beyond_3mad": (
                sum(abs(value - median) > 3.0 * mad for value in values) if mad else 0
            ),
        }
        summary = summaries[name]
        print(
            f"case={name} median_ns={summary['median_ns']:.3f} "
            f"mad_ns={summary['mad_ns']:.3f} "
            f"mad_percent={summary['mad_percent']:.2f} "
            f"p05_ns={summary['p05_ns']:.3f} p95_ns={summary['p95_ns']:.3f} "
            f"median_ci95={summary['bootstrap_median_ci95_low_ns']:.3f}.."
            f"{summary['bootstrap_median_ci95_high_ns']:.3f} "
            f"outliers_3mad={summary['outliers_beyond_3mad']}"
        )

    comparisons: dict[str, dict[str, float]] = {}
    baseline_values = internal_samples[baseline]
    for case_index, (name, _) in enumerate(cases):
        if name == baseline:
            continue
        paired = [
            baseline_ns / candidate_ns
            for baseline_ns, candidate_ns in zip(baseline_values, internal_samples[name])
        ]
        paired_median = statistics.median(paired)
        paired_mad = statistics.median(abs(value - paired_median) for value in paired)
        paired_vingtiles = statistics.quantiles(paired, n=20, method="inclusive")
        generator = random.Random(0xD1B54A32D192ED03 + case_index)
        bootstrap = sorted(
            statistics.median(generator.choices(paired, k=len(paired)))
            for _ in range(5_000)
        )
        comparisons[name] = {
            "ratio_of_medians": float(summaries[baseline]["median_ns"])
            / float(summaries[name]["median_ns"]),
            "paired_median": paired_median,
            "paired_mad": paired_mad,
            "paired_p05": paired_vingtiles[0],
            "paired_p95": paired_vingtiles[18],
            "paired_bootstrap_ci95_low": bootstrap[124],
            "paired_bootstrap_ci95_high": bootstrap[4_874],
        }
        comparison = comparisons[name]
        print(
            f"speedup baseline={baseline} candidate={name} "
            f"ratio_of_medians={comparison['ratio_of_medians']:.3f} "
            f"paired_median={comparison['paired_median']:.3f} "
            f"paired_mad={comparison['paired_mad']:.3f} "
            f"paired_p05={comparison['paired_p05']:.3f} "
            f"paired_p95={comparison['paired_p95']:.3f} "
            f"paired_ci95={comparison['paired_bootstrap_ci95_low']:.3f}.."
            f"{comparison['paired_bootstrap_ci95_high']:.3f}"
        )

    timing_stationarity = timing_stationarity_evidence(
        internal_samples, baseline
    )
    print(
        "stationarity "
        f"status={timing_stationarity['status']} "
        f"campaign_eligibility={timing_stationarity['campaign_eligibility']} "
        "method=four-fixed-contiguous-block-medians"
    )
    stationarity_cases = timing_stationarity["cases"]
    assert isinstance(stationarity_cases, dict)
    for name, _ in cases:
        record = stationarity_cases[name]
        assert isinstance(record, dict)
        print(
            f"stationarity_case={name} status={record['status']} "
            f"absolute_spread={record['max_to_min_ratio_minus_one']:.6f}"
        )
    stationarity_comparisons = timing_stationarity["comparisons"]
    assert isinstance(stationarity_comparisons, dict)
    for name, record in stationarity_comparisons.items():
        assert isinstance(record, dict)
        print(
            f"stationarity_comparison={name} status={record['status']} "
            f"eligibility={record['eligibility']} "
            f"effect_spread={record['max_to_min_ratio_minus_one']:.6f} "
            f"material_sign_instability={record['material_sign_instability']}"
        )

    if args.json:
        assert resolved_objdump is not None and resolved_size_tool is not None
        source_paths: dict[str, str] = {}
        for name, source in cases:
            try:
                source_paths[name] = str(source.relative_to(root))
            except ValueError:
                # --case explicitly accepts absolute paths so temporary
                # out-of-tree candidates must also be serializable.
                source_paths[name] = str(source)
        protocol_paths = {
            "autotune_driver": (
                root / "solutions" / "02_optimization" / "autotune_02_255h.py"
            ),
            "benchmark_driver": Path(__file__).resolve(),
            "loop_audit": root / "solutions" / "challenge02_loop_audit.py",
            "reference_oracle": root / "solutions" / "solve_02_permutation.c",
            "candidate_verifier": candidate_verifier_source,
            "problem_archive": archive,
            "objdump_executable": resolved_objdump,
            "size_executable": resolved_size_tool,
        }
        protocol_files: dict[str, dict[str, str]] = {}
        for name, path in protocol_paths.items():
            resolved = path.resolve()
            try:
                serialized_path = str(resolved.relative_to(root))
            except ValueError:
                serialized_path = str(resolved)
            protocol_files[name] = {
                "path": serialized_path,
                "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
            }
        python_executable = Path(sys.executable).resolve()
        protocol_payload = {
            "schema_version": 1,
            "files": protocol_files,
            "python": {
                "implementation": platform.python_implementation(),
                "version": platform.python_version(),
                "executable": str(python_executable),
                "executable_sha256": hashlib.sha256(
                    python_executable.read_bytes()
                ).hexdigest(),
            },
        }
        protocol_fingerprint = hashlib.sha256(
            json.dumps(
                protocol_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        report = {
            "schema_version": 5,
            "benchmark": "challenge02_contest_shaped",
            "campaign_id": args.campaign_id,
            "environment": {
                "host": platform.platform(),
                "cpu": cpu,
                "affinity": affinity,
                "compiler": compiler_version,
                "objdump": objdump_version,
                "size_tool": size_tool_version,
                "flags": flags,
                "inner_timer": "clock()",
                "outer_timer": "time.perf_counter_ns",
                "git_commit": git_commit,
                "git_dirty": git_dirty,
            },
            "config": {
                "iterations": args.iterations,
                "official_iterations": 1_000_000,
                "warmups": args.warmups,
                "samples_per_case": args.samples,
                "oracle_selftest_random_cases": args.random_cases,
                "candidate_random_differential_cases": args.random_cases,
                "random_differential_cases": args.random_cases,
                "candidate_random_differential": True,
                "timed_main_repeated_call_validation": True,
                "timed_main_alternate_iteration_challenge": True,
                "timed_workload_child_cpu_validation": True,
                "timing_stationarity_validation": True,
                "internal_ns_source": (
                    "printed-total-elapsed-seconds-divided-by-iterations"
                ),
                "order": "balanced-cyclic-reversed",
                "bootstrap_resamples": 5_000,
            },
            "baseline": baseline,
            "sources": {
                name: {
                    "path": source_paths[name],
                    "sha256": source_hashes[name],
                    "rewritten_sha256": rewritten_source_hashes[name],
                    "case_cflags": case_flags[name],
                    "source_context_cflags": source_context_flags[name],
                }
                for name, source in cases
            },
            "verification_harness": {
                "path": str(candidate_verifier_source.relative_to(root)),
                "sha256": hashlib.sha256(
                    candidate_verifier_source.read_bytes()
                ).hexdigest(),
            },
            "measurement_protocol": {
                **protocol_payload,
                "fingerprint_sha256": protocol_fingerprint,
            },
            "candidate_verification": candidate_verification,
            "assembly_audits": assembly_audits,
            "timed_main_validation": {
                "oracle": oracle_validation,
                "cases": timed_main_validation_cases,
            },
            "timed_main_semantic_challenge": {
                "mode": "unpredictable-alternate-iteration",
                "iterations": semantic_challenge_iterations,
                "derivation": {
                    **semantic_challenge_derivation_payload,
                    "digest_sha256": semantic_challenge_digest,
                },
                "oracle": semantic_challenge_oracle,
                "cases": timed_main_semantic_challenge_cases,
            },
            "internal_ns_per_20round": internal_samples,
            "inner_elapsed_seconds": inner_elapsed_samples,
            "printed_average_us_per_20round": printed_average_samples,
            "outer_wall_seconds": wall_samples,
            "child_cpu_seconds": child_cpu_samples,
            "timed_workload_cpu_coverage": {
                "minimum_iterations": MIN_CHILD_CPU_COVERAGE_ITERATIONS,
                "median_bounds": {
                    "low": MIN_MEDIAN_CHILD_CPU_COVERAGE,
                    "high": MAX_MEDIAN_CHILD_CPU_COVERAGE,
                },
                "enforced": coverage_enforced,
                "eligibility": (
                    "eligible" if coverage_enforced else "diagnostic-only"
                ),
                "reason": (
                    None
                    if coverage_enforced
                    else "iterations below 1000000; child-CPU coverage gate "
                    "is not enforced"
                ),
                "cases": timed_workload_cpu_coverage,
            },
            "timing_stationarity": timing_stationarity,
            "summaries": summaries,
            "comparisons": comparisons,
        }
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
