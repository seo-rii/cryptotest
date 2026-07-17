#!/usr/bin/env python3
"""Sweep small edge assignments and rank folded-Coron viability."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x0-values", default="0,1,15")
    parser.add_argument("--x7-values", default="0,1,15")
    parser.add_argument("--x1-values", default="0,1,511")
    parser.add_argument("--x6-values", default="0,1,1023")
    parser.add_argument("--limit", type=int, default=16)
    parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    rankings = []
    x0_values = [int(part, 0) for part in args.x0_values.split(",") if part]
    x7_values = [int(part, 0) for part in args.x7_values.split(",") if part]
    x1_values = [int(part, 0) for part in args.x1_values.split(",") if part]
    x6_values = [int(part, 0) for part in args.x6_values.split(",") if part]
    for x0 in x0_values:
        for x7 in x7_values:
            for x1 in x1_values:
                for x6 in x6_values:
                    command = [
                        sys.executable,
                        str(HERE / "edge_folded_margin.py"),
                        "--fix-p-range",
                        f"150:4:{x0}",
                        "--fix-p-range",
                        f"210:39:{x1}",
                        "--fix-p-range",
                        f"784:46:{x6}",
                        "--fix-p-range",
                        f"920:4:{x7}",
                        "--json",
                    ]
                    completed = subprocess.run(command, check=True, text=True, capture_output=True)
                    report = json.loads(completed.stdout)
                    report.update({"x0": x0, "x1": x1, "x6": x6, "x7": x7})
                    rankings.append(report)
                    if args.jsonl:
                        print(json.dumps({"event": "edge_probe", **report}, sort_keys=True))
    rankings.sort(key=lambda item: (-item["primitive_margin"], -item["q_prefix_bits"]))
    print(json.dumps({"event": "best", "items": rankings[: args.limit]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
