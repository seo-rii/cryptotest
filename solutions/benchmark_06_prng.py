#!/usr/bin/env python3
"""Run the warm-up/repeated benchmark matrix for challenge 6."""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == "__main__":
    runpy.run_path(
        Path(__file__).resolve().parent / "06_optimization" / "benchmark_06.py",
        run_name="__main__",
    )
