#!/usr/bin/env python3
"""Focused parser tests for the challenge 2 repeated-call timing contract."""

from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "solutions" / "02_optimization"))

from autotune_02_255h import (
    AutotuneError,
    run_one_campaign,
    timed_main_validation_errors,
)
import solutions.benchmark_02_permutation as benchmark_module
from solutions.benchmark_02_permutation import (
    parse_contest_timing_output,
    parse_oracle_final_state,
)


CONTEST_OUTPUT = """benchmark final state = 33fa1dad76592c79 2fadf15c4dea7134 38e404a4839d155f ffa0901cf9d32b19
iterations           = 10000
total elapsed time   = 0.000369 sec
average per 20rounds = 0.036900 us
"""


def run_adversarial_benchmark(
    *, name: str, source: str, iterations: int, audit: bool = False
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix=f"ch2-{name}-test-") as raw:
        candidate = Path(raw) / f"{name}.c"
        candidate.write_text(source)
        command = [
            sys.executable,
            str(ROOT / "solutions" / "benchmark_02_permutation.py"),
            "--case",
            "honest=submissions/02/contest.c",
            "--case",
            f"{name}={candidate}",
            "--baseline",
            "honest",
            "--case-cflag",
            "honest=-mbmi2",
            "--case-cflag",
            "honest=-finline-limit=2000",
            "--case-cflag",
            f"{name}=-mbmi2",
            "--case-cflag",
            f"{name}=-finline-limit=2000",
        ]
        if audit:
            command.extend(
                [
                    "--audit-mode",
                    "honest=full-inline-320",
                    "--audit-mode",
                    f"{name}=full-inline-320",
                ]
            )
        command.extend(
            [
                "--iterations",
                str(iterations),
                "--warmups",
                "1",
                "--samples",
                "5",
                "--random-cases",
                "1",
                "--cpu",
                "auto",
            ]
        )
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30.0,
        )


class ContestTimingOutputTests(unittest.TestCase):
    def test_parses_unique_repeated_call_result(self) -> None:
        parsed = parse_contest_timing_output(CONTEST_OUTPUT)
        self.assertEqual(parsed["iterations"], 10_000)
        self.assertAlmostEqual(parsed["total_elapsed_s"], 0.000369)
        self.assertAlmostEqual(parsed["printed_average_us"], 0.0369)
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

    def test_rejects_average_inconsistent_with_total_elapsed_time(self) -> None:
        dishonest = CONTEST_OUTPUT.replace(
            "average per 20rounds = 0.036900 us",
            "average per 20rounds = 0.018450 us",
        )
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            parse_contest_timing_output(dishonest)

    def test_rejects_timing_when_the_inner_clock_did_not_advance(self) -> None:
        unmeasurable = CONTEST_OUTPUT.replace(
            "total elapsed time   = 0.000369 sec",
            "total elapsed time   = 0.000000 sec",
        ).replace(
            "average per 20rounds = 0.036900 us",
            "average per 20rounds = 0.000000 us",
        )
        with self.assertRaisesRegex(ValueError, "must be positive"):
            parse_contest_timing_output(unmeasurable)

    def test_uses_total_elapsed_time_for_the_statistical_sample(self) -> None:
        output = CONTEST_OUTPUT.replace(
            "iterations           = 10000",
            "iterations           = 5000000",
        ).replace(
            "total elapsed time   = 0.000369 sec",
            "total elapsed time   = 0.185123 sec",
        ).replace(
            "average per 20rounds = 0.036900 us",
            "average per 20rounds = 0.037025 us",
        )
        parsed = parse_contest_timing_output(output)
        self.assertAlmostEqual(parsed["internal_ns"], 37.0246)
        self.assertAlmostEqual(parsed["printed_average_us"], 0.037025)
        self.assertNotEqual(
            parsed["internal_ns"],
            float(parsed["printed_average_us"]) * 1_000.0,
        )


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
        challenge_state = [
            "0000000000000005",
            "0000000000000006",
            "0000000000000007",
            "0000000000000008",
        ]
        campaign_id = "fixture-campaign"
        source_hash = "a" * 64
        challenge_derivation = {
            "schema_version": 1,
            "campaign_id": campaign_id,
            "nonce_hex": "0123456789abcdef0123456789abcdef",
            "measured_iterations": 10,
            "source_sha256": {"candidate": source_hash},
        }
        challenge_digest = hashlib.sha256(
            json.dumps(
                challenge_derivation,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        challenge_iterations = 4_096 + (
            int(challenge_digest[:16], 16) % 61_440
        )
        challenge_stdout = (
            f"oracle_final_state_iterations={challenge_iterations}\n"
            f"oracle_final_state={' '.join(challenge_state)}\n"
        )
        return {
            "schema_version": 5,
            "campaign_id": campaign_id,
            "config": {
                "iterations": 10,
                "warmups": 1,
                "samples_per_case": 2,
                "timed_main_repeated_call_validation": True,
                "timed_main_alternate_iteration_challenge": True,
                "timed_workload_child_cpu_validation": True,
                "internal_ns_source": (
                    "printed-total-elapsed-seconds-divided-by-iterations"
                ),
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
            "internal_ns_per_20round": {
                "candidate": [10.0, 10.0],
            },
            "inner_elapsed_seconds": {
                "candidate": [0.0000001, 0.0000001],
            },
            "printed_average_us_per_20round": {
                "candidate": [0.01, 0.01],
            },
            "outer_wall_seconds": {
                "candidate": [0.0000002, 0.0000002],
            },
            "child_cpu_seconds": {
                "candidate": [0.00000011, 0.00000011],
            },
            "timed_workload_cpu_coverage": {
                "minimum_iterations": 1_000_000,
                "median_bounds": {
                    "low": 0.65,
                    "high": 1.05,
                },
                "enforced": False,
                "eligibility": "diagnostic-only",
                "reason": (
                    "iterations below 1000000; child-CPU coverage gate is not "
                    "enforced"
                ),
                "cases": {
                    "candidate": {
                        "median_inner_to_child_cpu": 10.0 / 11.0,
                        "min_inner_to_child_cpu": 10.0 / 11.0,
                        "max_inner_to_child_cpu": 10.0 / 11.0,
                        "status": "NOT_ENFORCED",
                    }
                },
            },
            "timed_main_semantic_challenge": {
                "mode": "unpredictable-alternate-iteration",
                "iterations": challenge_iterations,
                "derivation": {
                    **challenge_derivation,
                    "digest_sha256": challenge_digest,
                },
                "oracle": {
                    "expected_final_state": challenge_state,
                    "stdout_sha256": hashlib.sha256(
                        challenge_stdout.encode()
                    ).hexdigest(),
                    "status": "PASS",
                },
                "cases": {
                    "candidate": {
                        "observed_final_state": challenge_state,
                        "status": "PASS",
                    }
                },
            },
            "sources": {
                "candidate": {
                    "sha256": source_hash,
                }
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

    def test_rejects_missing_alternate_iteration_challenge(self) -> None:
        report = self._valid_report()
        del report["timed_main_semantic_challenge"]
        errors = timed_main_validation_errors(
            report,
            expected_case_names=["candidate"],
            expected_iterations=10,
            expected_warmups=1,
            expected_samples=2,
        )
        self.assertTrue(
            any("alternate-iteration challenge is missing" in error for error in errors),
            errors,
        )

    def test_rejects_raw_sample_count_that_disagrees_with_process_record(self) -> None:
        report = self._valid_report()
        samples = report["internal_ns_per_20round"]
        assert isinstance(samples, dict)
        candidate_samples = samples["candidate"]
        assert isinstance(candidate_samples, list)
        candidate_samples.append(10.0)
        errors = timed_main_validation_errors(
            report,
            expected_case_names=["candidate"],
            expected_iterations=10,
            expected_warmups=1,
            expected_samples=2,
        )
        self.assertIn(
            "timed-main case candidate: internal timing sample count is not 2",
            errors,
        )

    def test_rejects_challenge_reused_under_a_different_campaign_id(self) -> None:
        report = self._valid_report()
        report["campaign_id"] = "different-campaign"
        errors = timed_main_validation_errors(
            report,
            expected_case_names=["candidate"],
            expected_iterations=10,
            expected_warmups=1,
            expected_samples=2,
        )
        self.assertIn(
            "timed-main alternate-iteration derivation campaign id differs",
            errors,
        )

    def test_rejects_missing_reason_for_diagnostic_only_coverage(self) -> None:
        report = self._valid_report()
        coverage = report["timed_workload_cpu_coverage"]
        assert isinstance(coverage, dict)
        coverage["reason"] = None
        errors = timed_main_validation_errors(
            report,
            expected_case_names=["candidate"],
            expected_iterations=10,
            expected_warmups=1,
            expected_samples=2,
        )
        self.assertIn(
            "timed-main child-CPU coverage reason is inconsistent",
            errors,
        )


class MeasurementPlatformTests(unittest.TestCase):
    def test_benchmark_fails_closed_without_child_cpu_accounting(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(benchmark_module, "resource", None),
            mock.patch.object(sys, "argv", ["benchmark_02_permutation.py"]),
            contextlib.redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            benchmark_module.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("child CPU accounting is unavailable", stderr.getvalue())

    def test_autotune_rejects_diagnostic_only_iteration_count(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ch2-low-iteration-test-") as raw:
            with self.assertRaisesRegex(AutotuneError, "diagnostic-only"):
                run_one_campaign(
                    kind="screen",
                    session="test",
                    core_type="p",
                    cpu=0,
                    candidate_name=None,
                    selected=[],
                    baseline="",
                    compiler={},
                    manifest={},
                    measurement_protocol={},
                    iterations=999_999,
                    warmups=1,
                    samples=5,
                    random_cases=1,
                    out_dir=Path(raw),
                    dry_run=True,
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
    def test_rejects_short_loop_recomputed_after_the_timer(self) -> None:
        source = (ROOT / "submissions" / "02" / "contest.c").read_text()
        loop = "for (int i = 0; i < iterations; i++)"
        end_clock = "clock_t end = clock();"
        self.assertEqual(source.count(loop), 1)
        self.assertEqual(source.count(end_clock), 1)
        malicious = source.replace(
            loop,
            "for (int i = 0; i < iterations / 2; i++)",
        ).replace(
            end_clock,
            f"{end_clock}\n"
            "        for (int i = iterations / 2; i < iterations; i++) {\n"
            "            permute_20rounds(&bench, rot, shuffle_map, "
            "constants1, constants2);\n"
            "        }",
        )
        completed = run_adversarial_benchmark(
            name="post_timer",
            source=malicious,
            iterations=1_000_000,
            audit=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "timed workload child-CPU coverage is too low for post_timer",
            completed.stderr,
        )
        self.assertIn("candidate_differential=PASS", completed.stdout)
        self.assertIn("assembly_audit[post_timer]=PASS", completed.stdout)

    def test_rejects_short_loop_with_hardcoded_expected_final_state(self) -> None:
        source = (ROOT / "submissions" / "02" / "contest.c").read_text()
        loop = "for (int i = 0; i < iterations; i++)"
        end_clock = "clock_t end = clock();"
        self.assertEqual(source.count(loop), 1)
        self.assertEqual(source.count(end_clock), 1)
        malicious = source.replace(
            loop,
            "for (int i = 0; i < iterations / 2; i++)",
        ).replace(
            end_clock,
            '__asm__ volatile("" : "+m"(bench));\n'
            f"        {end_clock}\n"
            "        bench.w[0] = 0x33fa1dad76592c79ULL;\n"
            "        bench.w[1] = 0x2fadf15c4dea7134ULL;\n"
            "        bench.w[2] = 0x38e404a4839d155fULL;\n"
            "        bench.w[3] = 0xffa0901cf9d32b19ULL;",
        )
        completed = run_adversarial_benchmark(
            name="hardcoded_state",
            source=malicious,
            iterations=10_000,
            audit=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("semantic challenge failed for hardcoded_state", completed.stderr)
        self.assertIn("candidate_differential=PASS", completed.stdout)
        self.assertIn(
            "assembly_audit[hardcoded_state]=PASS",
            completed.stdout,
        )

    def test_rejects_candidate_that_only_halves_reported_average(self) -> None:
        source = (ROOT / "submissions" / "02" / "contest.c").read_text()
        needle = (
            "double per_call_us = "
            "(elapsed_sec * 1000000.0) / iterations;"
        )
        self.assertEqual(source.count(needle), 1)
        malicious = source.replace(
            needle,
            "double per_call_us = "
            "(elapsed_sec * 1000000.0) / (2.0 * iterations);",
        )
        completed = run_adversarial_benchmark(
            name="fake_average",
            source=malicious,
            iterations=10_000,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(
            "reported average is inconsistent with total elapsed time",
            completed.stderr,
        )
        self.assertIn("candidate_differential=PASS", completed.stdout)

    def test_rejects_candidate_that_halves_only_the_timed_loop(self) -> None:
        source = (ROOT / "submissions" / "02" / "contest.c").read_text()
        needle = "for (int i = 0; i < iterations; i++)"
        self.assertEqual(source.count(needle), 1)
        malicious = source.replace(
            needle,
            "for (int i = 0; i < iterations / 2; i++)",
        )
        completed = run_adversarial_benchmark(
            name="half",
            source=malicious,
            iterations=10,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("timed-main semantic challenge failed for half", completed.stderr)
        self.assertIn("candidate_differential=PASS", completed.stdout)


if __name__ == "__main__":
    unittest.main()
