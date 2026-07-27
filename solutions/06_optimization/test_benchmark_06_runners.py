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
        "lift_residue_test": (
            "montgomery-residue-hybrid-u128-u64-"
            "euclidean-jacobi-deferred-sqrt"
        ),
        "subgroup_membership_test": (
            "cofactor-5-frobenius-tate-trace-prac-20-generic"
        ),
        "subgroup_constant_layout": "constexpr-montgomery",
        "subgroup_batch_layout": "direct-in-place-fraction",
        "subgroup_batch_inversion": "endpoint-elided-3m-minus-3",
        "subgroup_trace_formula": "degree-5-shifted-square",
        "block_lift_rhs": "forward-cubic-difference",
        "block_lift_square": "deferred-after-subgroup",
        "subgroup_lucas_bit_scan": "variable-u128-shift",
        "subgroup_lucas_step": "fixed-prac-schedule",
        "scan_buffer_initialization": "write-before-read",
        "curve_constant_layout": "constexpr-montgomery",
        "fixed_window_bits": 8,
        "fixed_digit_encoding": "unsigned",
        "fixed_multiplication": "candidate-jacobian",
        "r3": hex(PUBLIC.EXPECTED["r3"]),
        "lift_low_bits": PUBLIC.EXPECTED_SCANS["s3"]["lift_low_bits"],
        "schedule_requested": "adaptive",
        "schedule_effective": "block",
        "block_size_requested": 64,
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
            ("subgroup_membership_test", None),
            ("subgroup_trace_formula", None),
            ("subgroup_batch_inversion", None),
            ("block_lift_rhs", None),
            ("block_lift_square", None),
            ("lift_output_index", None),
            ("fixed_digit_encoding", None),
            ("fixed_multiplication", None),
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
            ("subgroup_membership_test", None),
            ("subgroup_trace_formula", None),
            ("subgroup_batch_inversion", None),
            ("block_lift_rhs", None),
            ("block_lift_square", None),
            ("lift_output_index", None),
            ("fixed_digit_encoding", None),
            ("fixed_multiplication", None),
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
            variant, json.dumps(native_result()), 1, 64, "adaptive", True
        )
        scalar_result = native_result()
        scalar_result.update(
            {
                "implementation": (
                    "cpp-native-montgomery-binary-window4-scalar-1"
                ),
                "schedule_requested": "scalar",
                "schedule_effective": "scalar",
            }
        )
        PROMOTION.validate_result(
            variant, json.dumps(scalar_result), 1, 64, "scalar", True
        )
        adaptive_two_result = native_result()
        adaptive_two_result.update(
            {
                "implementation": (
                    "cpp-native-montgomery-binary-window4-block-2"
                ),
                "threads": 2,
                "threads_actual": 2,
                "block_size": 32,
            }
        )
        PROMOTION.validate_result(
            variant, json.dumps(adaptive_two_result), 2, 64,
            "adaptive", True
        )
        for key, value in (
            ("threads_actual", 2),
            ("threads", True),
            ("subgroup_trace_formula", "expanded-miller-fraction"),
            ("subgroup_batch_inversion", "exclusive-prefix-3m"),
            ("block_lift_rhs", "direct-cubic"),
            ("block_lift_square", "direct-cubic-reused"),
        ):
            with self.subTest(key=key):
                malformed = native_result()
                malformed[key] = value
                with self.assertRaises(RuntimeError):
                    PROMOTION.validate_result(
                        variant, json.dumps(malformed), 1, 64,
                        "adaptive", True
                    )

    def test_promotion_runner_tracks_jacobi_variants(self) -> None:
        cases = {
            (): (
                "montgomery-residue-hybrid-u128-u64-"
                "euclidean-jacobi-deferred-sqrt"
            ),
            ("CH6_CANONICAL_JACOBI_INPUT",): (
                "hybrid-u128-u64-euclidean-jacobi-deferred-sqrt"
            ),
            ("CH6_FULL_U128_JACOBI",): (
                "full-u128-euclidean-jacobi-deferred-sqrt"
            ),
            ("CH6_SUBTRACTIVE_JACOBI",): (
                "subtractive-jacobi-deferred-sqrt"
            ),
            ("CH6_HYBRID_SUBTRACTIVE_U64_JACOBI",): (
                "montgomery-residue-hybrid-u128-euclidean-"
                "u64-subtractive-jacobi-deferred-sqrt"
            ),
            (
                "CH6_HYBRID_SUBTRACTIVE_U64_JACOBI",
                "CH6_CANONICAL_JACOBI_INPUT",
            ): (
                "hybrid-u128-euclidean-u64-subtractive-"
                "jacobi-deferred-sqrt"
            ),
        }
        for defines, expected in cases.items():
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "jacobi", Path("/tmp/deep_native_06"), defines
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "lift_residue_test"
                    ],
                    expected,
                )

    def test_promotion_runner_tracks_subgroup_filter(self) -> None:
        for defines, expected in (
            (
                (),
                "cofactor-5-frobenius-tate-trace-prac-20-generic",
            ),
            (("CH6_NO_SUBGROUP_FILTER",), "none"),
            (
                ("CH6_SUBGROUP_LUCAS_LANES=2",),
                "cofactor-5-frobenius-tate-trace-prac-20-interleaved-2",
            ),
            (
                (
                    "CH6_BINARY_SUBGROUP_LUCAS",
                    "CH6_SUBGROUP_LUCAS_LANES=4",
                ),
                "cofactor-5-frobenius-tate-trace-interleaved-4",
            ),
            (
                ("CH6_BINARY_SUBGROUP_LUCAS",),
                "cofactor-5-frobenius-tate-trace",
            ),
            (
                ("CH6_FUSED_PRAC_INTERPRETER",),
                "cofactor-5-frobenius-tate-trace-prac-20-fused",
            ),
            (
                (
                    "CH6_BINARY_SUBGROUP_LUCAS",
                    "CH6_SUBGROUP_LUCAS_LANES=2",
                ),
                "cofactor-5-frobenius-tate-trace-interleaved-2",
            ),
        ):
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "subgroup", Path("/tmp/deep_native_06"), defines
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "subgroup_membership_test"
                    ],
                    expected,
                )

    def test_promotion_runner_tracks_subgroup_codegen(self) -> None:
        cases = {
            (): (
                "constexpr-montgomery",
                "variable-u128-shift",
                "fixed-prac-schedule",
            ),
            ("CH6_RUNTIME_SUBGROUP_CONSTANTS",): (
                "function-local-static",
                "variable-u128-shift",
                "fixed-prac-schedule",
            ),
            (
                "CH6_BINARY_SUBGROUP_LUCAS",
                "CH6_U64_LUCAS_BIT_STREAM",
            ): (
                "constexpr-montgomery",
                "u64-msb-stream",
                "fixed-pattern-branch",
            ),
            (
                "CH6_BINARY_SUBGROUP_LUCAS",
                "CH6_BRANCHLESS_LUCAS_STEP",
            ): (
                "constexpr-montgomery",
                "variable-u128-shift",
                "branchless-select",
            ),
        }
        for defines, expected in cases.items():
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "subgroup-codegen",
                    Path("/tmp/deep_native_06"),
                    defines,
                )
                configuration = PROMOTION.expected_configuration(variant, True)
                self.assertEqual(
                    (
                        configuration["subgroup_constant_layout"],
                        configuration["subgroup_lucas_bit_scan"],
                        configuration["subgroup_lucas_step"],
                    ),
                    expected,
                )

    def test_promotion_runner_tracks_scan_buffer_initialization(self) -> None:
        for defines, expected in (
            ((), "write-before-read"),
            (("CH6_EAGER_ZERO_SCAN_BUFFERS",), "eager-zero"),
        ):
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "scan-buffer",
                    Path("/tmp/deep_native_06"),
                    defines,
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "scan_buffer_initialization"
                    ],
                    expected,
                )

    def test_promotion_runner_tracks_subgroup_batch_layout(self) -> None:
        for defines, expected in (
            ((), "direct-in-place-fraction"),
            (("CH6_XY_SUBGROUP_BATCH",), "xy-separated"),
        ):
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "subgroup-batch", Path("/tmp/deep_native_06"), defines
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "subgroup_batch_layout"
                    ],
                    expected,
                )

    def test_promotion_runner_tracks_subgroup_batch_inversion(self) -> None:
        for defines, expected in (
            ((), "endpoint-elided-3m-minus-3"),
            (("CH6_EXCLUSIVE_BATCH_PREFIX",), "exclusive-prefix-3m"),
        ):
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "subgroup-inversion",
                    Path("/tmp/deep_native_06"),
                    defines,
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "subgroup_batch_inversion"
                    ],
                    expected,
                )

    def test_promotion_runner_tracks_subgroup_trace_formula(self) -> None:
        for defines, expected in (
            ((), "degree-5-shifted-square"),
            (
                ("CH6_HORNER_SUBGROUP_TRACE",),
                "degree-5-reciprocal-horner",
            ),
            (("CH6_EXPANDED_SUBGROUP_TRACE",), "expanded-miller-fraction"),
        ):
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "subgroup-trace", Path("/tmp/deep_native_06"), defines
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "subgroup_trace_formula"
                    ],
                    expected,
                )

    def test_promotion_runner_tracks_block_lift_rhs(self) -> None:
        for defines, expected in (
            ((), "forward-cubic-difference"),
            (("CH6_DIRECT_BLOCK_CUBIC",), "direct-cubic"),
        ):
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "block-cubic", Path("/tmp/deep_native_06"), defines
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "block_lift_rhs"
                    ],
                    expected,
                )

    def test_promotion_runner_tracks_block_lift_square(self) -> None:
        for defines, expected in (
            ((), "deferred-after-subgroup"),
            (("CH6_EAGER_BLOCK_X_SQUARE",), "eager-after-jacobi"),
            (("CH6_DIRECT_BLOCK_CUBIC",), "direct-cubic-reused"),
        ):
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "block-square", Path("/tmp/deep_native_06"), defines
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "block_lift_square"
                    ],
                    expected,
                )

    def test_promotion_runner_tracks_curve_constants(self) -> None:
        for defines, expected in (
            ((), "constexpr-montgomery"),
            (("CH6_RUNTIME_CURVE_CONSTANTS",), "function-local-static"),
        ):
            with self.subTest(defines=defines):
                variant = PROMOTION.Variant(
                    "curve-constants",
                    Path("/tmp/deep_native_06"),
                    defines,
                )
                self.assertEqual(
                    PROMOTION.expected_configuration(variant, True)[
                        "curve_constant_layout"
                    ],
                    expected,
                )

    def test_promotion_runner_applies_variant_cxxflags(self) -> None:
        variant = PROMOTION.Variant(
            "lto",
            Path("/tmp/deep_native_06_lto"),
            (),
            ("-flto",),
        )
        completed = subprocess.CompletedProcess(
            args=(), returncode=0, stdout="", stderr=""
        )
        with patch.object(
            PROMOTION.subprocess, "run", return_value=completed
        ) as run:
            command = PROMOTION.build_variant(
                "g++", Path("/tmp/deep_native_06.cpp"), variant
            )
        self.assertIn("-flto", command)
        run.assert_called_once_with(
            command, check=False, capture_output=True, text=True
        )

    def test_promotion_runner_queries_predefines_with_variant_cxxflags(
        self,
    ) -> None:
        completed = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout=(
                "#define __x86_64__ 1\n"
                "#define __BMI2__ 1\n"
                "#define __ADX__ 1\n"
            ),
            stderr="",
        )
        with patch.object(
            PROMOTION.subprocess, "run", return_value=completed
        ) as run:
            predefines = PROMOTION.compiler_predefines(
                "g++", ("-mno-bmi2", "-mno-adx")
            )
        self.assertEqual(
            predefines, {"__x86_64__", "__BMI2__", "__ADX__"}
        )
        run.assert_called_once_with(
            (
                "g++",
                "-march=native",
                "-mno-bmi2",
                "-mno-adx",
                "-dM",
                "-E",
                "-x",
                "c++",
                "-",
            ),
            input="",
            check=False,
            capture_output=True,
            text=True,
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

    def test_promotion_runner_rejects_nonpositive_trials_per_pair(self) -> None:
        process = subprocess.run(
            (
                sys.executable,
                str(DIRECTORY / "benchmark_06_promotion.py"),
                "--warmup-pairs",
                "1",
                "--pairs",
                "40",
                "--trials-per-pair",
                "0",
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("trials per pair must be positive", process.stderr)


if __name__ == "__main__":
    unittest.main()
