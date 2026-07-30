#!/usr/bin/env python3
"""Focused structural-contract tests for challenge 2 counted AVX2 loops."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from solutions.loop_audit import validate_loop_audit


def counted_report(vector_count: int) -> dict[str, object]:
    mnemonics = {
        "dec": 1,
        "jne": 2,
        "mov": 1,
        "sub": 1,
        "vpaddq": vector_count,
        "vpor": vector_count,
        "vpshufb": vector_count,
        "vpsllvq": vector_count,
        "vpsrlvq": vector_count,
        "vpxor": vector_count,
    }
    return {
        "calls": 0,
        "push_pop": 0,
        "memory_operands_excluding_lea": 0,
        "loop_instructions": sum(mnemonics.values()),
        "mnemonics": mnemonics,
    }


class CountedAvx2AuditTests(unittest.TestCase):
    def test_accepts_block2_exact_shape(self) -> None:
        self.assertEqual(
            validate_loop_audit(
                counted_report(4), "avx2-inline-pair-block2-counted"
            ),
            [],
        )

    def test_accepts_block3_tail1_exact_shape(self) -> None:
        self.assertEqual(
            validate_loop_audit(
                counted_report(8), "avx2-inline-pair-block3-tail1"
            ),
            [],
        )

    def test_accepts_block5_exact_shape(self) -> None:
        self.assertEqual(
            validate_loop_audit(
                counted_report(10), "avx2-inline-pair-block5-counted"
            ),
            [],
        )

    def test_rejects_missing_counted_transform(self) -> None:
        report = counted_report(8)
        report["mnemonics"]["vpaddq"] = 7  # type: ignore[index]
        self.assertIn(
            "mnemonics.vpaddq: expected 8, got 7",
            validate_loop_audit(
                report, "avx2-inline-pair-block3-tail1"
            ),
        )

    def test_rejects_missing_condition_code_control(self) -> None:
        report = counted_report(10)
        report["mnemonics"]["dec"] = 0  # type: ignore[index]
        self.assertIn(
            "mnemonics.dec: expected 1, got 0",
            validate_loop_audit(
                report, "avx2-inline-pair-block5-counted"
            ),
        )


if __name__ == "__main__":
    unittest.main()
