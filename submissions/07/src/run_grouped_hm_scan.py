#!/usr/bin/env python3
"""Run the challenge-7 grouped-HM solver over edge candidates 0..255.

The runner never assumes the known winning candidate.  It records one log and
one JSON result per candidate, validates every reported factor against N and
the leaked mask, and writes a deterministic summary after the full scan.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from investigate_rsa_partial_bits import MASK_HEX, N_HEX, P_AND_MASK_HEX


RECOVERED_RE = re.compile(r"^RECOVERED p=(\d+)$", re.MULTILINE)
FLATTER_COMMIT_RE = re.compile(r"\bflatter_commit=(\S+)")


def compact_hex(value: str) -> int:
    return int(value.replace(" ", ""), 16)


N = compact_hex(N_HEX)
MASK = compact_hex(MASK_HEX)
P_AND_MASK = compact_hex(P_AND_MASK_HEX)


@dataclass(frozen=True)
class CandidateResult:
    cid: int
    status: str
    returncode: int | None
    elapsed_seconds: float
    log_path: str
    log_sha256: str
    recovered_factor: str | None
    factor_divides_n: bool
    factor_matches_mask: bool
    flatter_commit_reported: str | None
    error: str | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while chunk := fp.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def command_for(
    binary: Path, cid: int, solver_threads: int
) -> list[str]:
    return [
        str(binary),
        "--challenge",
        "--cid",
        str(cid),
        "--m",
        "17",
        "--t",
        "5",
        "--rhf",
        "1.15",
        "--threads",
        str(solver_threads),
        "--lead",
        "x",
        "--centered",
    ]


def run_candidate(
    binary: Path,
    output_dir: Path,
    cid: int,
    solver_threads: int,
    expected_flatter_commit: str,
    timeout: float | None,
) -> CandidateResult:
    command = command_for(binary, cid, solver_threads)
    log_path = output_dir / f"cid-{cid:03d}.log"
    metadata_path = output_dir / f"cid-{cid:03d}.json"
    environment = os.environ.copy()
    environment["OPENBLAS_NUM_THREADS"] = "1"
    started = time.monotonic()
    returncode: int | None = None
    error: str | None = None
    try:
        with log_path.open("wb") as log_fp:
            completed = subprocess.run(
                command,
                stdout=log_fp,
                stderr=subprocess.STDOUT,
                env=environment,
                timeout=timeout,
                check=False,
            )
        returncode = completed.returncode
    except subprocess.TimeoutExpired:
        error = f"timeout after {timeout:g} seconds"
    except OSError as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.monotonic() - started

    if log_path.exists():
        log_sha256 = sha256_file(log_path)
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    else:
        log_sha256 = ""
        log_text = ""
    matches = RECOVERED_RE.findall(log_text)
    commit_matches = FLATTER_COMMIT_RE.findall(log_text)
    reported_commit = commit_matches[-1] if commit_matches else None
    recovered = int(matches[-1]) if matches else None
    divides = recovered is not None and 1 < recovered < N and N % recovered == 0
    mask_matches = recovered is not None and recovered & MASK == P_AND_MASK

    if error is not None:
        status = "timeout" if error.startswith("timeout") else "runner_error"
    elif reported_commit != expected_flatter_commit:
        status = "provenance_mismatch"
        error = (
            f"solver reported FLATTER commit {reported_commit!r}, expected "
            f"{expected_flatter_commit!r}"
        )
    elif len(set(matches)) > 1:
        status = "ambiguous_output"
        error = "log contains more than one distinct recovered factor"
    elif recovered is not None and returncode == 0 and divides and mask_matches:
        status = "recovered"
    elif recovered is not None:
        status = "invalid_recovery"
        error = (
            "reported factor failed return-code, divisibility, or mask validation"
        )
    elif returncode == 2:
        # This means only that this heuristic reduction/extraction path did not
        # recover a factor.  It is not a proof that the branch has no root.
        status = "no_recovery"
    else:
        status = "solver_error"
        error = f"unexpected solver return code {returncode}"

    result = CandidateResult(
        cid=cid,
        status=status,
        returncode=returncode,
        elapsed_seconds=elapsed,
        log_path=str(log_path),
        log_sha256=log_sha256,
        recovered_factor=str(recovered) if recovered is not None else None,
        factor_divides_n=divides,
        factor_matches_mask=mask_matches,
        flatter_commit_reported=reported_commit,
        error=error,
    )
    metadata_path.write_text(
        json.dumps(asdict(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def command_output(command: list[str]) -> str:
    try:
        return subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{type(exc).__name__}: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Blindly scan challenge-7 edge candidates and validate any "
            "reported factor."
        )
    )
    parser.add_argument("binary", type=Path, help="compiled grouped-HM solver")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/tmp/cryptotest-07-full-scan"),
    )
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument(
        "--solver-threads",
        type=int,
        default=4,
        help="FLATTER worker threads inside each solver process",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="optional per-candidate timeout; omitted means no timeout",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stop", type=int, default=256)
    parser.add_argument(
        "--expect-successes",
        type=int,
        default=1,
        help="required distinct validated factors; use -1 to disable",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(__file__).with_name("solve_grouped_hm_flatter.cpp"),
    )
    parser.add_argument(
        "--flatter-commit",
        required=True,
        help="FLATTER revision used to build the supplied binary",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the exact candidate commands without running them",
    )
    args = parser.parse_args()

    if not (0 <= args.start < args.stop <= 256):
        parser.error("require 0 <= --start < --stop <= 256")
    if args.jobs < 1 or args.solver_threads < 1:
        parser.error("--jobs and --solver-threads must be positive")
    if args.timeout is not None and args.timeout <= 0:
        parser.error("--timeout must be positive")

    binary = args.binary.resolve()
    candidates = list(range(args.start, args.stop))
    if args.dry_run:
        for cid in candidates:
            print(" ".join(command_for(binary, cid, args.solver_threads)))
        print(
            f"planned_candidates={len(candidates)} jobs={args.jobs} "
            f"solver_threads={args.solver_threads} OPENBLAS_NUM_THREADS=1"
        )
        return
    if not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error(f"solver binary is not executable: {binary}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    results: list[CandidateResult] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.jobs
    ) as executor:
        futures = {
            executor.submit(
                run_candidate,
                binary,
                args.output_dir,
                cid,
                args.solver_threads,
                args.flatter_commit,
                args.timeout,
            ): cid
            for cid in candidates
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                f"cid={result.cid:03d} status={result.status} "
                f"seconds={result.elapsed_seconds:.3f} "
                f"log_sha256={result.log_sha256}"
            )

    results.sort(key=lambda item: item.cid)
    recovered = {
        item.recovered_factor
        for item in results
        if item.status == "recovered"
    }
    failures = [
        item
        for item in results
        if item.status not in ("recovered", "no_recovery")
    ]
    provenance = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "binary": str(binary),
        "binary_sha256": sha256_file(binary),
        "source": str(args.source),
        "source_sha256": (
            sha256_file(args.source) if args.source.is_file() else None
        ),
        "flatter_commit_declared": args.flatter_commit,
        "compiler": command_output(["g++", "--version"]).splitlines()[0],
        "shared_libraries": command_output(["ldd", str(binary)]).splitlines(),
        "OPENBLAS_NUM_THREADS": "1",
        "jobs": args.jobs,
        "solver_threads_per_process": args.solver_threads,
        "parameters": {
            "m": 17,
            "t": 5,
            "rhf": 1.15,
            "lead": "x",
            "centered": True,
        },
    }
    summary = {
        "range": [args.start, args.stop],
        "candidate_count": len(results),
        "elapsed_seconds": time.monotonic() - started,
        "status_counts": {
            status: sum(item.status == status for item in results)
            for status in sorted({item.status for item in results})
        },
        "successful_candidates": [
            item.cid for item in results if item.status == "recovered"
        ],
        "distinct_validated_factors": sorted(
            factor for factor in recovered if factor is not None
        ),
        "provenance": provenance,
        "results": [asdict(item) for item in results],
    }
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"successful candidates = {summary['successful_candidates']}")
    print(f"distinct validated factors = {len(recovered)}")
    print(f"summary = {summary_path}")

    if failures:
        raise SystemExit(
            f"{len(failures)} candidates ended in timeout/error; inspect summary"
        )
    if (
        args.expect_successes >= 0
        and len(recovered) != args.expect_successes
    ):
        raise SystemExit(
            f"expected {args.expect_successes} distinct validated factors, "
            f"got {len(recovered)}"
        )


if __name__ == "__main__":
    main()
