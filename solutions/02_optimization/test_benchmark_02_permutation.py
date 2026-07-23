#!/usr/bin/env python3
"""Focused parser tests for the challenge 2 repeated-call timing contract."""

from __future__ import annotations

import copy
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "solutions" / "02_optimization"))

from autotune_02_255h import timed_main_validation_errors
from solutions.benchmark_02_permutation import (
    parse_contest_timing_output,
    parse_oracle_final_state,
)


CONTEST_OUTPUT = """benchmark final state = 33fa1dad76592c79 2fadf15c4dea7134 38e404a4839d155f ffa0901cf9d32b19
iterations           = 10000
total elapsed time   = 0.000369 sec
average per 20rounds = 0.036900 us
"""


class ContestTimingOutputTests(unittest.TestCase):
    def test_parses_unique_repeated_call_result(self) -> None:
        parsed = parse_contest_timing_output(CONTEST_OUTPUT)
        self.assertEqual(parsed["iterations"], 10_000)
        self.assertAlmostEqual(parsed["internal_ns"], 36.9)
        self.assertEqual(
            parsed["final_state"],
            (
                "33fa1dad76592c79",
                "2fadf15c4dea7134",
                "38e404a4839d155f",
                "ffa0901cf9d32b19",
            ),
        )

    def test_rejects_duplicate_timing_contract_lines(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_contest_timing_output(CONTEST_OUTPUT + CONTEST_OUTPUT)

    def test_rejects_missing_final_state(self) -> None:
        without_state = "\n".join(CONTEST_OUTPUT.splitlines()[1:]) + "\n"
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_contest_timing_output(without_state)


class OracleOutputTests(unittest.TestCase):
    def test_parses_and_normalizes_oracle_state(self) -> None:
        iterations, state = parse_oracle_final_state(
            "oracle_final_state_iterations=2\n"
            "oracle_final_state=AAAAAAAAAAAAAAAA BBBBBBBBBBBBBBBB "
            "CCCCCCCCCCCCCCCC DDDDDDDDDDDDDDDD\n"
        )
        self.assertEqual(iterations, 2)
        self.assertEqual(
            state,
            (
                "aaaaaaaaaaaaaaaa",
                "bbbbbbbbbbbbbbbb",
                "cccccccccccccccc",
                "dddddddddddddddd",
            ),
        )

    def test_rejects_duplicate_oracle_state(self) -> None:
        output = (
            "oracle_final_state_iterations=1\n"
            "oracle_final_state=0000000000000000 0000000000000000 "
            "0000000000000000 0000000000000000\n"
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_oracle_final_state(output + output)


class TimedMainEvidenceTests(unittest.TestCase):
    @staticmethod
    def _valid_report() -> dict[str, object]:
        state = [
            "0000000000000001",
            "0000000000000002",
            "0000000000000003",
            "0000000000000004",
        ]
        canonical_stdout = (
            "oracle_final_state_iterations=10\n"
            f"oracle_final_state={' '.join(state)}\n"
        )
        return {
            "schema_version": 5,
            "config": {
                "iterations": 10,
                "warmups": 1,
                "samples_per_case": 2,
                "timed_main_repeated_call_validation": True,
            },
            "timed_main_validation": {
                "oracle": {
                    "mode": "independent-reference-repeated-20-rounds",
                    "iterations": 10,
                    "expected_final_state": state,
                    "stdout_sha256": hashlib.sha256(
                        canonical_stdout.encode()
                    ).hexdigest(),
                    "status": "PASS",
                },
                "cases": {
                    "candidate": {
                        "iterations": 10,
                        "observed_final_state": state,
                        "preflight_processes": 1,
                        "warmup_processes": 1,
                        "measured_processes": 2,
                        "validated_processes": 4,
                        "status": "PASS",
                    }
                },
            },
        }

    def test_accepts_exact_schema5_timed_main_evidence(self) -> None:
        self.assertEqual(
            timed_main_validation_errors(
                self._valid_report(),
                expected_case_names=["candidate"],
                expected_iterations=10,
                expected_warmups=1,
                expected_samples=2,
            ),
            [],
        )

    def test_rejects_oracle_hash_not_bound_to_recorded_state(self) -> None:
        report = self._valid_report()
        validation = report["timed_main_validation"]
        assert isinstance(validation, dict)
        oracle = validation["oracle"]
        assert isinstance(oracle, dict)
        oracle["stdout_sha256"] = "0" * 64
        errors = timed_main_validation_errors(
            report,
            expected_case_names=["candidate"],
            expected_iterations=10,
            expected_warmups=1,
            expected_samples=2,
        )
        self.assertIn(
            "timed-main oracle stdout SHA-256 does not bind its state",
            errors,
        )

    def test_rejects_unmeasured_extra_case_record(self) -> None:
        report = self._valid_report()
        validation = report["timed_main_validation"]
        assert isinstance(validation, dict)
        cases = validation["cases"]
        assert isinstance(cases, dict)
        cases["extra"] = copy.deepcopy(cases["candidate"])
        errors = timed_main_validation_errors(
            report,
            expected_case_names=["candidate"],
            expected_iterations=10,
            expected_warmups=1,
            expected_samples=2,
        )
        self.assertTrue(
            any("case set differs" in error for error in errors),
            errors,
        )


class OracleCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("gcc")
        if compiler is None:
            raise unittest.SkipTest("gcc is unavailable")
        cls.temporary = tempfile.TemporaryDirectory(prefix="ch2-oracle-test-")
        cls.executable = Path(cls.temporary.name) / "oracle"
        subprocess.run(
            [
                compiler,
                "-O2",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Wpedantic",
                str(ROOT / "solutions" / "solve_02_permutation.c"),
                "-o",
                str(cls.executable),
            ],
            check=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_rejects_negative_iteration_count(self) -> None:
        completed = subprocess.run(
            [str(self.executable), "--final-state", "-1"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2.0,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("invalid iterations", completed.stderr)

    def test_rejects_zero_iteration_count(self) -> None:
        completed = subprocess.run(
            [str(self.executable), "--final-state", "0"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=2.0,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertIn("iterations must be positive", completed.stderr)

    def test_known_repeated_call_state(self) -> None:
        completed = subprocess.run(
            [str(self.executable), "--final-state", "10000"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5.0,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(
            completed.stdout,
            "oracle_final_state_iterations=10000\n"
            "oracle_final_state=33fa1dad76592c79 2fadf15c4dea7134 "
            "38e404a4839d155f ffa0901cf9d32b19\n",
        )


class TimedMainIntegrationTests(unittest.TestCase):
    def test_rejects_candidate_that_halves_only_the_timed_loop(self) -> None:
        source = (ROOT / "submissions" / "02" / "contest.c").read_text()
        needle = "for (int i = 0; i < iterations; i++)"
        self.assertEqual(source.count(needle), 1)
        with tempfile.TemporaryDirectory(prefix="ch2-half-loop-test-") as raw:
            malicious = Path(raw) / "half.c"
            malicious.write_text(
                source.replace(
                    needle,
                    "for (int i = 0; i < iterations / 2; i++)",
                )
            )
            command = [
                sys.executable,
                str(ROOT / "solutions" / "benchmark_02_permutation.py"),
                "--case",
                "honest=submissions/02/contest.c",
                "--case",
                f"half={malicious}",
                "--baseline",
                "honest",
                "--case-cflag",
                "honest=-mbmi2",
                "--case-cflag",
                "honest=-finline-limit=2000",
                "--case-cflag",
                "half=-mbmi2",
                "--case-cflag",
                "half=-finline-limit=2000",
                "--iterations",
                "10",
                "--warmups",
                "1",
                "--samples",
                "5",
                "--random-cases",
                "1",
                "--cpu",
                "auto",
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30.0,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "timed-main semantic preflight failed for half",
            completed.stderr,
        )
        self.assertIn("candidate_differential=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
