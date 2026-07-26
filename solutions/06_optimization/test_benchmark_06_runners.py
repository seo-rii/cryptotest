from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


DIRECTORY = Path(__file__).resolve().parent


def load_runner(filename: str) -> ModuleType:
    module_name = f"test_{filename.removesuffix('.py')}"
    specification = importlib.util.spec_from_file_location(
        module_name, DIRECTORY / filename
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    specification.loader.exec_module(module)
    return module


PUBLIC = load_runner("benchmark_06.py")
DEEP = load_runner("benchmark_deep_native_06.py")
PROMOTION = load_runner("benchmark_06_promotion.py")


def native_command() -> tuple[str, ...]:
    return (
        "/tmp/deep_native_06",
        "--threads",
        "1",
        "--schedule",
        "adaptive",
        "--block-size",
        "64",
        "--inverse",
        "binary",
        "--sqrt",
        "window4",
        "--json",
    )


def native_result() -> dict[str, object]:
    return {
        "implementation": "cpp-native-montgomery-binary-window4-block-1",
        "d": hex(PUBLIC.EXPECTED["d"]),
        "state": hex(PUBLIC.EXPECTED_SCANS["s3"]["state"]),
        "state_label": "s3",
        "lift_output_index": 1,
        "filter_output_index": 2,
        "field_backend": "bmi2-adx",
        "scan_curve_model": "isomorphic-a-minus-3",
        "d_multiplication": "hamburg-co-z",
        "lift_residue_test": "sqrt",
        "fixed_window_bits": 8,
        "fixed_digit_encoding": "unsigned",
        "r3": hex(PUBLIC.EXPECTED["r3"]),
        "lift_low_bits": PUBLIC.EXPECTED_SCANS["s3"]["lift_low_bits"],
        "schedule_requested": "adaptive",
        "schedule_effective": "block",
        "block_size": 64,
        "threads": 1,
        "threads_actual": 1,
        "inverse_method": "binary",
        "sqrt_method": "window4",
        "telemetry_strategy": "analytic",
        "p_equals_dq": True,
        "candidates_started": 15595,
        "telemetry_seconds": 0.001,
        "precompute_seconds": 0.002,
        "scan_seconds": 0.007,
        "state_seconds": 0.009,
        "total_seconds": 0.010,
    }


def gmp_command() -> tuple[str, ...]:
    return (
        "/tmp/solve_06_gmp",
        "--threads",
        "1",
        "--telemetry",
        "analytic",
        "--json",
    )


def gmp_result() -> dict[str, object]:
    return {
        "implementation": "cpp-gmp-omp-1-analytic",
        "d": hex(PUBLIC.EXPECTED["d"]),
        "state": hex(PUBLIC.EXPECTED_SCANS["s2"]["state"]),
        "state_label": "s2",
        "r3": hex(PUBLIC.EXPECTED["r3"]),
        "lift_low_bits": PUBLIC.EXPECTED_SCANS["s2"]["lift_low_bits"],
        "p_equals_dq": True,
        "threads": 1,
        "threads_actual": 1,
        "telemetry_strategy": "analytic",
        "lift_residue_test": "sqrt",
        "telemetry_seconds": 0.001,
        "state_seconds": 0.009,
        "total_seconds": 0.010,
    }


class BenchmarkRunnerTests(unittest.TestCase):
    def test_benchmark_environment_removes_conflicting_openmp_variables(
        self,
    ) -> None:
        inherited = {
            "OMP_THREAD_LIMIT": "1",
            "OMP_NUM_THREADS": "99",
            "OMP_SCHEDULE": "dynamic",
            "GOMP_CPU_AFFINITY": "0",
        }
        for runner in (PUBLIC, DEEP):
            with self.subTest(runner=runner.__name__):
                with patch.dict(os.environ, inherited, clear=False):
                    environment, removed = runner.benchmark_environment()

                self.assertEqual(removed, sorted(inherited))
                self.assertFalse(inherited.keys() & environment.keys())
                self.assertEqual(environment["OMP_DYNAMIC"], "FALSE")
                self.assertEqual(environment["OMP_PROC_BIND"], "SPREAD")
                self.assertEqual(environment["OMP_PLACES"], "THREADS")

    def test_public_runner_requires_native_execution_metadata(self) -> None:
        contender = PUBLIC.Contender(
            "native-1-adaptive", "native", native_command()
        )
        PUBLIC.validate_result(contender, native_result())

        for key, replacement in (
            ("threads_actual", 0),
            ("threads_actual", True),
            ("p_equals_dq", 1),
            ("lift_residue_test", None),
            ("lift_output_index", None),
            ("fixed_digit_encoding", None),
            ("schedule_effective", "scalar"),
            ("scan_seconds", "NaN"),
        ):
            with self.subTest(key=key):
                malformed = native_result()
                if replacement is None:
                    malformed.pop(key)
                else:
                    malformed[key] = replacement
                with self.assertRaises(RuntimeError):
                    PUBLIC.validate_result(contender, malformed)

    def test_deep_runner_requires_native_execution_metadata(self) -> None:
        contender = DEEP.Contender(
            "native-binary-window4-adaptive-1t",
            "native-binary-window4-adaptive",
            1,
            native_command(),
        )
        DEEP.validate_result(contender, json.dumps(native_result()))

        for key, replacement in (
            ("threads_actual", 0),
            ("threads_actual", True),
            ("lift_residue_test", None),
            ("lift_output_index", None),
            ("fixed_digit_encoding", None),
            ("field_backend", None),
            ("state_seconds", float("nan")),
        ):
            with self.subTest(key=key):
                malformed = native_result()
                if replacement is None:
                    malformed.pop(key)
                else:
                    malformed[key] = replacement
                with self.assertRaises(RuntimeError):
                    DEEP.validate_result(contender, json.dumps(malformed))

    def test_public_and_deep_require_gmp_execution_metadata(self) -> None:
        public_contender = PUBLIC.Contender(
            "cpp-1-analytic", "gmp", gmp_command()
        )
        deep_contender = DEEP.Contender("gmp-1t", "gmp", 1, gmp_command())
        PUBLIC.validate_result(public_contender, gmp_result())
        DEEP.validate_result(deep_contender, json.dumps(gmp_result()))

        for key in ("threads_actual", "lift_residue_test"):
            with self.subTest(key=key):
                malformed = gmp_result()
                malformed.pop(key)
                with self.assertRaises(RuntimeError):
                    PUBLIC.validate_result(public_contender, malformed)
                with self.assertRaises(RuntimeError):
                    DEEP.validate_result(
                        deep_contender, json.dumps(malformed)
                    )

    def test_runner_rejects_threads_outside_affinity_before_build(self) -> None:
        cases = (
            (
                "benchmark_06.py",
                ("--implementations", "native-1000000-adaptive"),
            ),
            ("benchmark_deep_native_06.py", ("--threads", "1000000")),
        )
        for runner, thread_option in cases:
            with self.subTest(runner=runner):
                process = subprocess.run(
                    (
                        sys.executable,
                        str(DIRECTORY / runner),
                        "--warmup",
                        "1",
                        "--repetitions",
                        "5",
                        *thread_option,
                    ),
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10.0,
                )

                self.assertEqual(process.returncode, 2)
                self.assertIn("current affinity mask", process.stderr)

    def test_deep_runner_rejects_wrong_scan_window(self) -> None:
        contender = DEEP.Contender(
            "native-binary-window4-adaptive-1t",
            "native-binary-window4-adaptive",
            1,
            native_command(),
        )
        malformed = native_result()
        malformed.update(
            {
                "state": hex(DEEP.EXPECTED_SCANS["s2"]["state"]),
                "state_label": "s2",
                "lift_low_bits": DEEP.EXPECTED_SCANS["s2"]["lift_low_bits"],
                "lift_output_index": 0,
                "filter_output_index": 1,
                "candidates_started": 21305,
            }
        )
        with self.assertRaises(RuntimeError):
            DEEP.validate_result(contender, json.dumps(malformed))

    def test_promotion_runner_validates_design_and_metadata(self) -> None:
        orders = PROMOTION.pair_orders(40, 0x06C0FFEE)
        for block in range(PROMOTION.BLOCK_COUNT):
            block_orders = orders[block * 10 : (block + 1) * 10]
            self.assertEqual(block_orders.count("AB"), 5)
            self.assertEqual(block_orders.count("BA"), 5)
        self.assertEqual(
            PROMOTION.stratified_bootstrap_median_ci(
                [1.125] * 40, orders, 123
            ),
            (1.125, 1.125),
        )

        variant = PROMOTION.Variant(
            "incumbent", Path("/tmp/deep_native_06"), ()
        )
        PROMOTION.validate_result(
            variant, json.dumps(native_result()), 1, 64, True
        )
        for key, value in (("threads_actual", 2), ("threads", True)):
            with self.subTest(key=key):
                malformed = native_result()
                malformed[key] = value
                with self.assertRaises(RuntimeError):
                    PROMOTION.validate_result(
                        variant, json.dumps(malformed), 1, 64, True
                    )

    def test_promotion_runner_rejects_accidental_noop(self) -> None:
        process = subprocess.run(
            (
                sys.executable,
                str(DIRECTORY / "benchmark_06_promotion.py"),
                "--warmup-pairs",
                "1",
                "--pairs",
                "40",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("same effective build/runtime configuration", process.stderr)


if __name__ == "__main__":
    unittest.main()
