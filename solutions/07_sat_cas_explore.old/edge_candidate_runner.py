#!/usr/bin/env python3
"""Run bounded edge-candidate verifier probes for challenge 7.

This helper is intentionally narrow: it turns explicit x0/x1/x6/x7 candidates
from edge_rank_sweep into auditable edge_folded_margin reports, with an optional
diagnose-only hybrid solver pass.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
SOLUTIONS = HERE.parent

WIDTHS = {
    "x0": 4,
    "x1": 39,
    "x6": 46,
    "x7": 4,
}


def parse_values(text: str) -> list[int]:
    values: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part, 0))
    return values


def checked_values(name: str, text: str) -> list[int]:
    values = parse_values(text)
    if not values:
        raise argparse.ArgumentTypeError(f"--{name} must contain at least one value")
    width = WIDTHS[name]
    limit = 1 << width
    for value in values:
        if not (0 <= value < limit):
            raise argparse.ArgumentTypeError(f"{name}={value:#x} does not fit {width} bits")
    return values


def parse_candidate(text: str) -> dict[str, int]:
    raw: Any
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raw = ast.literal_eval(text)
    candidate: dict[str, int] = {}
    if isinstance(raw, (list, tuple)):
        if len(raw) != 4:
            raise argparse.ArgumentTypeError(
                "--candidate list/tuple entries must be x0,x1,x6,x7"
            )
        raw = dict(zip(("x0", "x1", "x6", "x7"), raw, strict=True))
    if not isinstance(raw, dict):
        raise argparse.ArgumentTypeError(
            "--candidate entries must be JSON objects or x0,x1,x6,x7 lists"
        )
    for name, width in WIDTHS.items():
        if name not in raw:
            raise argparse.ArgumentTypeError(f"--candidate missing {name}")
        value = int(raw[name], 0) if isinstance(raw[name], str) else int(raw[name])
        if not (0 <= value < (1 << width)):
            raise argparse.ArgumentTypeError(f"{name}={value:#x} does not fit {width} bits")
        candidate[name] = value
    return candidate


def load_candidate_file(path: Path) -> list[dict[str, int]]:
    candidates: list[dict[str, int]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
            if not isinstance(payload, dict):
                raise SystemExit(f"{path}:{line_number}: expected JSON object")
            source = payload.get("candidate", payload)
            if not isinstance(source, dict):
                raise SystemExit(f"{path}:{line_number}: expected candidate object")
            try:
                candidates.append(parse_candidate(json.dumps(source)))
            except argparse.ArgumentTypeError as exc:
                raise SystemExit(f"{path}:{line_number}: {exc}") from exc
    return candidates


def run_child(command: list[str], timeout: float, parse_json: bool) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return {
            "ok": False,
            "timed_out": True,
            "elapsed_sec": round(time.monotonic() - started, 3),
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-4000:],
        }

    result: dict[str, Any] = {
        "ok": completed.returncode == 0,
        "timed_out": False,
        "returncode": completed.returncode,
        "elapsed_sec": round(time.monotonic() - started, 3),
    }
    if parse_json and completed.returncode == 0:
        try:
            result["report"] = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            result.update(
                {
                    "ok": False,
                    "json_error": str(exc),
                    "stdout_tail": completed.stdout[-4000:],
                    "stderr_tail": completed.stderr[-4000:],
                }
            )
    else:
        result["stdout_tail"] = completed.stdout[-4000:]
        result["stderr_tail"] = completed.stderr[-4000:]
    return result


def edge_command(candidate: dict[str, int]) -> list[str]:
    return [
        sys.executable,
        str(HERE / "edge_folded_margin.py"),
        "--fix-p-range",
        f"150:4:{candidate['x0']}",
        "--fix-p-range",
        f"210:39:{candidate['x1']}",
        "--fix-p-range",
        f"784:46:{candidate['x6']}",
        "--fix-p-range",
        f"920:4:{candidate['x7']}",
        "--json",
    ]


def hybrid_command(
    candidate: dict[str, int],
    python_executable: str,
    s_value: int,
    max_branches: int,
    extra_args: list[str],
) -> list[str]:
    if not (1 <= s_value <= WIDTHS["x6"]):
        raise ValueError("hybrid s values must be in 1..46")
    x6_top = candidate["x6"] >> (WIDTHS["x6"] - s_value)
    return [
        python_executable,
        str(SOLUTIONS / "solve_07_hybrid_coron.py"),
        *extra_args,
        "--diagnose-only",
        "--branch-low",
        str(candidate["x0"]),
        "--x1-value",
        str(candidate["x1"]),
        "--branch-high",
        str(candidate["x7"]),
        "--s-values",
        str(s_value),
        "--x6-top",
        str(x6_top),
        "--max-branches",
        str(max_branches),
    ]


def build_candidates(args: argparse.Namespace) -> list[dict[str, int]]:
    candidates: list[dict[str, int]] = []
    for candidate in args.candidate:
        candidates.append(candidate)
    if args.candidate_file:
        candidates.extend(load_candidate_file(args.candidate_file))
    if not candidates:
        if args.x6 is None:
            raise SystemExit("provide --x6, --candidate, or --candidate-file")
        x0_values = args.x0 if args.x0 is not None else [0]
        x1_values = args.x1 if args.x1 is not None else [0]
        x7_values = args.x7 if args.x7 is not None else [0]
        for x0 in x0_values:
            for x1 in x1_values:
                for x6 in args.x6:
                    for x7 in x7_values:
                        candidates.append({"x0": x0, "x1": x1, "x6": x6, "x7": x7})
    return candidates


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "event": "summary",
        "candidates": len(results),
        "edge_ok": sum(1 for item in results if item["edge"].get("ok")),
        "edge_timeouts": sum(1 for item in results if item["edge"].get("timed_out")),
        "hybrid_runs": sum(len(item.get("hybrid", [])) for item in results),
        "hybrid_diagnose_completed": sum(
            1
            for item in results
            for hybrid in item.get("hybrid", [])
            if hybrid.get("diagnose_completed")
        ),
        "hybrid_ok": sum(
            1 for item in results for hybrid in item.get("hybrid", []) if hybrid.get("ok")
        ),
        "hybrid_timeouts": sum(
            1 for item in results for hybrid in item.get("hybrid", []) if hybrid.get("timed_out")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x0", type=lambda text: checked_values("x0", text))
    parser.add_argument("--x1", type=lambda text: checked_values("x1", text))
    parser.add_argument("--x6", type=lambda text: checked_values("x6", text))
    parser.add_argument("--x7", type=lambda text: checked_values("x7", text))
    parser.add_argument("--candidate", action="append", default=[], type=parse_candidate)
    parser.add_argument("--candidate-file", type=Path, help="JSONL with x0/x1/x6/x7 objects")
    parser.add_argument("--max-candidates", type=int, default=64)
    parser.add_argument("--timeout-sec", type=float, default=20.0)
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--hybrid", action="store_true", help="also run solve_07_hybrid_coron diagnose-only")
    parser.add_argument("--hybrid-python", default=sys.executable)
    parser.add_argument("--hybrid-timeout-sec", type=float, default=60.0)
    parser.add_argument("--hybrid-s-values", default="6")
    parser.add_argument("--hybrid-max-branches", type=int, default=1)
    parser.add_argument(
        "--hybrid-extra-arg",
        action="append",
        default=[],
        help="extra argument token passed to the diagnose-only hybrid solver",
    )
    args = parser.parse_args()

    if args.max_candidates <= 0:
        raise SystemExit("--max-candidates must be positive")
    if args.timeout_sec <= 0 or args.hybrid_timeout_sec <= 0:
        raise SystemExit("timeouts must be positive")
    if args.hybrid_max_branches <= 0:
        raise SystemExit("--hybrid-max-branches must be positive")

    hybrid_s_values = parse_values(args.hybrid_s_values)
    for value in hybrid_s_values:
        if not (1 <= value <= WIDTHS["x6"]):
            raise SystemExit("--hybrid-s-values entries must be in 1..46")

    candidates = build_candidates(args)
    if len(candidates) > args.max_candidates:
        raise SystemExit(f"refusing to run {len(candidates)} candidates; raise --max-candidates")

    results: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        record: dict[str, Any] = {
            "event": "candidate",
            "index": index,
            "candidate": candidate,
            "edge": run_child(edge_command(candidate), args.timeout_sec, parse_json=True),
        }
        if args.hybrid:
            record["hybrid"] = []
            for s_value in hybrid_s_values:
                command = hybrid_command(
                    candidate,
                    args.hybrid_python,
                    s_value,
                    args.hybrid_max_branches,
                    args.hybrid_extra_arg,
                )
                hybrid = run_child(command, args.hybrid_timeout_sec, parse_json=False)
                hybrid["s"] = s_value
                hybrid["x6_top"] = candidate["x6"] >> (WIDTHS["x6"] - s_value)
                hybrid["x1_fixed_by_hybrid"] = True
                hybrid["diagnose_completed"] = (
                    not hybrid.get("timed_out") and hybrid.get("returncode") in {0, 1}
                )
                record["hybrid"].append(hybrid)
        results.append(record)
        if args.jsonl:
            print(json.dumps(record, sort_keys=True), flush=True)

    summary = summarize(results)
    if args.jsonl:
        print(json.dumps(summary, sort_keys=True), flush=True)
    else:
        print(json.dumps({"event": "result", "items": results, "summary": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
