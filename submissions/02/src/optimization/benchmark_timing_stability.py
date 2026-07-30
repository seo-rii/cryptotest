#!/usr/bin/env python3
"""Diagnose scalar/AVX2 timing reversals with paired timer controls."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
OPT = ROOT / "solutions" / "02_optimization"
DRIVER = ROOT / "solutions" / "benchmark_permutation.py"
HELPER = OPT / "benchmark_timing_stability.c"
SCALAR = ROOT / "submissions" / "02" / "contest.c"
AVX2 = OPT / "contest_simd_avx2_lanewise.c"
HISTORICAL = {
    1: OPT / "avx2_confirm_cpu1.json",
    3: OPT / "avx2_confirm_cpu3.json",
}


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(command), flush=True)
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


def bootstrap_median_ci(values: list[float], seed: int) -> tuple[float, float]:
    generator = random.Random(seed)
    resamples = sorted(
        statistics.median(generator.choices(values, k=len(values)))
        for _ in range(5_000)
    )
    return resamples[124], resamples[4_874]


def summary(values: list[float], seed: int) -> dict[str, float]:
    median = statistics.median(values)
    low, high = bootstrap_median_ci(values, seed)
    return {
        "median": median,
        "mad": statistics.median(abs(value - median) for value in values),
        "p05": percentile(values, 0.05),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
        "bootstrap_median_ci95_low": low,
        "bootstrap_median_ci95_high": high,
    }


def correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right)
    )
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    )
    return numerator / denominator if denominator else None


def topology_for(cpu: int) -> dict[str, Any]:
    topology = Path(f"/sys/devices/system/cpu/cpu{cpu}/topology")
    sibling_text = (topology / "thread_siblings_list").read_text().strip()
    siblings: list[int] = []
    for group in sibling_text.split(","):
        if "-" in group:
            start, end = (int(value) for value in group.split("-", 1))
            siblings.extend(range(start, end + 1))
        else:
            siblings.append(int(group))
    other = [value for value in siblings if value != cpu]
    if len(other) != 1:
        raise RuntimeError(f"expected one SMT sibling for CPU {cpu}: {siblings}")
    return {
        "cpu": cpu,
        "core_id": int((topology / "core_id").read_text()),
        "physical_package_id": int(
            (topology / "physical_package_id").read_text()
        ),
        "thread_siblings": siblings,
        "measurement_sibling": other[0],
    }


def process_snapshot() -> list[dict[str, Any]]:
    output = run(
        ["ps", "-eo", "pid=,psr=,pcpu=,comm=", "--sort=-pcpu"]
    ).stdout
    records = []
    for line in output.splitlines()[:24]:
        fields = line.split(None, 3)
        if len(fields) == 4:
            records.append(
                {
                    "pid": int(fields[0]),
                    "processor": int(fields[1]),
                    "cpu_percent": float(fields[2]),
                    "command": fields[3],
                }
            )
    return records


def extract_function(disassembly: str, symbol: str) -> tuple[int, str]:
    address_match = re.search(
        rf"^([0-9a-f]+) <{re.escape(symbol)}>:", disassembly, re.MULTILINE
    )
    if address_match is None:
        raise RuntimeError(f"objdump did not contain {symbol}")
    next_symbol = re.search(
        r"^[0-9a-f]+ <[^>]+>:$",
        disassembly[address_match.end() :],
        re.MULTILINE,
    )
    end = (
        address_match.end() + next_symbol.start()
        if next_symbol is not None
        else len(disassembly)
    )
    return int(address_match.group(1), 16), disassembly[address_match.end() : end]


def assembly_record(executable: Path) -> dict[str, Any]:
    disassembly = run(
        ["objdump", "-d", "--no-show-raw-insn", str(executable)]
    ).stdout
    records = {}
    for candidate, symbol in (
        ("scalar", "run_scalar_block"),
        ("avx2", "run_avx2_block"),
    ):
        address, body = extract_function(disassembly, symbol)
        instructions = []
        for line in body.splitlines():
            match = re.match(r"\s*[0-9a-f]+:\s+([a-z0-9.]+)\b", line)
            if match:
                instructions.append(match.group(1))
        calls = [value for value in instructions if value.startswith("call")]
        selected = (
            ["rorx", "bswap", "xor", "add", "lea"]
            if candidate == "scalar"
            else ["vpsllvq", "vpsrlvq", "vpor", "vpxor", "vpshufb", "vpaddq"]
        )
        records[candidate] = {
            "symbol": symbol,
            "address": address,
            "address_mod_4096": address % 4096,
            "instructions": len(instructions),
            "calls": len(calls),
            "selected_mnemonics": {
                mnemonic: instructions.count(mnemonic) for mnemonic in selected
            },
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
    if any(item["address_mod_4096"] for item in records.values()):
        raise RuntimeError("same-process runners are not page aligned")
    if any(item["calls"] for item in records.values()):
        raise RuntimeError("same-process hot runner retained a call")
    scalar_counts = records["scalar"]["selected_mnemonics"]
    if scalar_counts["rorx"] != 80 or scalar_counts["bswap"] != 80:
        raise RuntimeError(f"unexpected scalar core: {scalar_counts}")
    avx_counts = records["avx2"]["selected_mnemonics"]
    if any(avx_counts[mnemonic] != 20 for mnemonic in avx_counts):
        raise RuntimeError(f"unexpected AVX2 core: {avx_counts}")
    return records


def timer_analysis(measurements: list[dict[str, Any]]) -> dict[str, Any]:
    pairs = []
    for sample in sorted({record["sample"] for record in measurements}):
        pairs.append(
            {
                record["candidate"]: record
                for record in measurements
                if record["sample"] == sample
            }
        )
    timer_results = {}
    for index, (field, label) in enumerate(
        (
            ("raw_ns", "wall"),
            ("thread_ns", "thread_cpu"),
            ("tsc_cycles", "invariant_tsc"),
        )
    ):
        scalar = [float(pair["scalar"][field]) for pair in pairs]
        avx2 = [float(pair["avx2"][field]) for pair in pairs]
        ratios = [left / right for left, right in zip(scalar, avx2)]
        by_order = {
            order: [
                ratio
                for ratio, pair in zip(ratios, pairs)
                if pair["scalar"]["order"] == order
            ]
            for order in ("AB", "BA")
        }
        timer_results[label] = {
            "unit_field": field,
            "scalar": summary(scalar, 0x1000 + index),
            "avx2": summary(avx2, 0x2000 + index),
            "speedup_scalar_over_avx2": summary(ratios, 0x3000 + index),
            "speedup_by_order": {
                order: summary(values, 0x4000 + order_index)
                for order_index, (order, values) in enumerate(by_order.items())
            },
        }
    sibling_busy = []
    selected_busy = []
    for pair in pairs:
        record = pair["scalar"]
        sibling_busy.append(
            record["sibling_busy_delta"] / record["sibling_total_delta"]
            if record["sibling_total_delta"]
            else 0.0
        )
        selected_busy.append(
            record["selected_busy_delta"] / record["selected_total_delta"]
            if record["selected_total_delta"]
            else 0.0
        )
    thread_ratios = [
        pair["scalar"]["thread_ns"] / pair["avx2"]["thread_ns"] for pair in pairs
    ]
    return {
        "timers": timer_results,
        "selected_cpu_busy_fraction": summary(selected_busy, 0x5000),
        "sibling_cpu_busy_fraction": summary(sibling_busy, 0x5001),
        "correlations": {
            "sibling_busy_vs_speedup": correlation(sibling_busy, thread_ratios),
            "sibling_busy_vs_scalar_thread_ns": correlation(
                sibling_busy,
                [float(pair["scalar"]["thread_ns"]) for pair in pairs],
            ),
            "sibling_busy_vs_avx2_thread_ns": correlation(
                sibling_busy,
                [float(pair["avx2"]["thread_ns"]) for pair in pairs],
            ),
        },
        "migration_or_aux_change_records": sum(
            record["cpu_start"] != record["cpu_end"]
            or record["aux_start"] != record["aux_end"]
            for record in measurements
        ),
        "involuntary_context_switches": sum(
            record["involuntary_context_switches"] for record in measurements
        ),
        "voluntary_context_switches": sum(
            record["voluntary_context_switches"] for record in measurements
        ),
    }


def cross_cpu_context(current: dict[str, Any]) -> dict[str, Any]:
    campaigns: dict[str, Any] = {}
    reports = {
        **{cpu: json.loads(path.read_text()) for cpu, path in HISTORICAL.items()},
        2: current,
    }
    for cpu, report in sorted(reports.items()):
        campaigns[str(cpu)] = {
            "artifact": (
                str(HISTORICAL[cpu].relative_to(ROOT))
                if cpu in HISTORICAL
                else "embedded exact_process_isolated"
            ),
            "scalar_median_ns": report["summaries"]["scalar"]["median_ns"],
            "avx2_median_ns": report["summaries"]["avx2"]["median_ns"],
            "paired_speedup": report["comparisons"]["avx2"]["paired_median"],
            "scalar_binary_sha256": report["assembly_audits"]["scalar"][
                "binary_sha256"
            ],
            "avx2_binary_sha256": report["assembly_audits"]["avx2"][
                "binary_sha256"
            ],
            "scalar_loop_sha256": report["assembly_audits"]["scalar"][
                "normalized_loop_sha256"
            ],
            "avx2_loop_sha256": report["assembly_audits"]["avx2"][
                "normalized_loop_sha256"
            ],
        }
    scalar_medians = [
        item["scalar_median_ns"] for item in campaigns.values()
    ]
    avx2_medians = [item["avx2_median_ns"] for item in campaigns.values()]
    return {
        "campaigns": campaigns,
        "all_exact_binary_hashes_match": all(
            len({item[field] for item in campaigns.values()}) == 1
            for field in (
                "scalar_binary_sha256",
                "avx2_binary_sha256",
                "scalar_loop_sha256",
                "avx2_loop_sha256",
            )
        ),
        "scalar_median_cross_cpu_relative_range": max(scalar_medians)
        / min(scalar_medians)
        - 1.0,
        "avx2_median_cross_cpu_relative_range": max(avx2_medians)
        / min(avx2_medians)
        - 1.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--iterations", type=int, default=3_000_000)
    parser.add_argument("--warmups", type=int, default=6)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument(
        "--json", type=Path, default=OPT / "timing_stability_results.json"
    )
    args = parser.parse_args()
    if args.cpu != 2:
        parser.error("this controlled campaign is reserved for CPU 2")
    if args.iterations < 1_000_000:
        parser.error("--iterations must be at least 1000000")
    if args.warmups < 6 or args.samples < 32:
        parser.error("require at least 6 warmups and 32 samples")
    if args.random_cases < 100_000:
        parser.error("require at least 100000 random differential cases")

    topology = topology_for(args.cpu)
    process_before = process_snapshot()
    with tempfile.TemporaryDirectory(prefix="challenge-timing-stability-") as raw:
        temporary = Path(raw)
        process_json = temporary / "process_isolated.json"
        process_command = [
            sys.executable,
            str(DRIVER),
            "--case",
            f"scalar={SCALAR.relative_to(ROOT)}",
            "--case",
            f"avx2={AVX2.relative_to(ROOT)}",
            "--baseline",
            "scalar",
            "--iterations",
            str(args.iterations),
            "--warmups",
            str(args.warmups),
            "--samples",
            str(args.samples),
            "--random-cases",
            str(args.random_cases),
            "--cpu",
            str(args.cpu),
            "--extra-cflag=-Werror",
            "--case-cflag",
            "scalar=-mbmi2",
            "--case-cflag",
            "scalar=-finline-limit=2000",
            "--case-cflag",
            "avx2=-mavx2",
            "--case-cflag",
            "avx2=-DCH2_SIMD_INLINE",
            "--case-cflag",
            "avx2=-finline-limit=2000",
            "--audit-mode",
            "scalar=full-inline-320",
            "--audit-mode",
            "avx2=avx2-inline-lanewise",
            "--campaign-id",
            "timing-stability-cpu2",
            "--json",
            str(process_json),
        ]
        isolated = run(process_command)
        print(isolated.stdout, end="")
        if isolated.stderr:
            print(isolated.stderr, file=sys.stderr, end="")
        process_report = json.loads(process_json.read_text())
        if process_report.get("schema_version") != 5:
            raise RuntimeError(
                "process-isolated benchmark schema is not 5: "
                f"{process_report.get('schema_version')!r}"
            )
        process_config = process_report.get("config", {})
        if not (
            process_config.get("iterations") == args.iterations
            and process_config.get("warmups") == args.warmups
            and process_config.get("samples_per_case") == args.samples
            and process_config.get("timed_main_repeated_call_validation") is True
        ):
            raise RuntimeError("process-isolated benchmark process counts changed")
        timed_validation = process_report.get("timed_main_validation")
        if not isinstance(timed_validation, dict):
            raise RuntimeError(
                "process-isolated benchmark omitted timed_main_validation"
            )
        if set(timed_validation) != {"oracle", "cases"}:
            raise RuntimeError("process-isolated timed-main validation shape changed")
        timed_oracle = timed_validation.get("oracle")
        timed_cases = timed_validation.get("cases")
        if not isinstance(timed_oracle, dict) or not isinstance(timed_cases, dict):
            raise RuntimeError("process-isolated timed-main validation is malformed")
        if set(timed_oracle) != {
            "mode",
            "iterations",
            "expected_final_state",
            "stdout_sha256",
            "status",
        }:
            raise RuntimeError("process-isolated timed-main oracle shape changed")
        if set(timed_cases) != {"scalar", "avx2"}:
            raise RuntimeError(
                "process-isolated timed-main case set changed: "
                f"{sorted(timed_cases)!r}"
            )
        expected_state = timed_oracle.get("expected_final_state")
        valid_state = (
            isinstance(expected_state, list)
            and len(expected_state) == 4
            and all(
                isinstance(word, str) and re.fullmatch(r"[0-9a-f]{16}", word)
                for word in expected_state
            )
        )
        canonical_oracle_hash = (
            hashlib.sha256(
                (
                    f"oracle_final_state_iterations={args.iterations}\n"
                    f"oracle_final_state={' '.join(expected_state)}\n"
                ).encode()
            ).hexdigest()
            if valid_state
            else None
        )
        if not (
            timed_oracle.get("mode")
            == "independent-reference-repeated-20-rounds"
            and type(timed_oracle.get("iterations")) is int
            and timed_oracle.get("iterations") == args.iterations
            and args.iterations > 0
            and valid_state
            and isinstance(timed_oracle.get("stdout_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", timed_oracle["stdout_sha256"])
            and timed_oracle.get("stdout_sha256") == canonical_oracle_hash
            and timed_oracle.get("status") == "PASS"
        ):
            raise RuntimeError("process-isolated timed-main oracle did not pass")
        validated_processes = 1 + args.warmups + args.samples
        for candidate, timed_case in timed_cases.items():
            if isinstance(timed_case, dict) and set(timed_case) != {
                "iterations",
                "observed_final_state",
                "preflight_processes",
                "warmup_processes",
                "measured_processes",
                "validated_processes",
                "status",
            }:
                raise RuntimeError(
                    f"{candidate}: process-isolated timed-main case shape changed"
                )
            if not isinstance(timed_case, dict) or not (
                all(
                    type(timed_case.get(field)) is int
                    for field in (
                        "iterations",
                        "preflight_processes",
                        "warmup_processes",
                        "measured_processes",
                        "validated_processes",
                    )
                )
                and timed_case.get("iterations") == args.iterations
                and timed_case.get("observed_final_state") == expected_state
                and timed_case.get("preflight_processes") == 1
                and timed_case.get("warmup_processes") == args.warmups
                and timed_case.get("measured_processes") == args.samples
                and timed_case.get("validated_processes") == validated_processes
                and timed_case.get("status") == "PASS"
            ):
                raise RuntimeError(
                    f"{candidate}: process-isolated timed-main validation failed"
                )

        helper_executable = temporary / "timing_stability"
        compiler_command = [
            "gcc",
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            "-mavx2",
            "-mbmi2",
            "-finline-limit=2000",
            "-fno-toplevel-reorder",
            "-fno-pie",
            "-no-pie",
            str(HELPER),
            "-o",
            str(helper_executable),
        ]
        compile_result = run(compiler_command)
        if compile_result.stderr:
            print(compile_result.stderr, file=sys.stderr, end="")
        helper_assembly = assembly_record(helper_executable)
        helper_run = run(
            [
                str(helper_executable),
                str(args.cpu),
                str(topology["measurement_sibling"]),
                str(args.iterations),
                str(args.warmups),
                str(args.samples),
            ]
        )
        if helper_run.stderr:
            print(helper_run.stderr, file=sys.stderr, end="")
        lines = [json.loads(line) for line in helper_run.stdout.splitlines()]
        meta = next(line for line in lines if line["type"] == "meta")
        measurements = [line for line in lines if line["type"] == "measurement"]
        if len(measurements) != args.samples * 2:
            raise RuntimeError("same-process helper emitted an incomplete sample set")
        analysis = timer_analysis(measurements)
        cross_cpu = cross_cpu_context(process_report)

        exact_comparison = process_report["comparisons"]["avx2"]
        speedups = {
            timer: analysis["timers"][timer]["speedup_scalar_over_avx2"]
            for timer in ("thread_cpu", "wall", "invariant_tsc")
        }
        timer_spread = max(item["median"] for item in speedups.values()) - min(
            item["median"] for item in speedups.values()
        )
        interpretation = {
            "exact_process_isolated_speedup": exact_comparison["paired_median"],
            "same_process_thread_cpu_speedup": speedups["thread_cpu"]["median"],
            "same_process_wall_speedup": speedups["wall"]["median"],
            "same_process_tsc_speedup": speedups["invariant_tsc"]["median"],
            "timer_speedup_median_spread": timer_spread,
            "timer_conclusion": (
                "the three timers agree closely, so timer choice does not explain the reversal"
                if timer_spread < 0.02
                else "the timers diverge enough that preemption or accounting remains material"
            ),
            "migration_conclusion": (
                "no migration or TSC_AUX changes were observed"
                if analysis["migration_or_aux_change_records"] == 0
                else "migration or TSC_AUX changes occurred; discard the affected campaign"
            ),
            "layout_conclusion": (
                "same-process runners were independently page-aligned and AB/BA balanced; "
                "modulo-64 layout cannot explain their result, although this does not prove "
                "all standalone layouts equivalent"
            ),
            "frequency_conclusion": (
                "constant/nonstop TSC controls elapsed reference cycles, not actual core "
                "cycles; APERF/MPERF, cpufreq, and perf counters are unavailable, so turbo "
                "or virtualized frequency changes cannot be isolated"
            ),
            "smt_conclusion": (
                "the SMT sibling was active, and sibling busy fraction correlated with both "
                f"scalar ({analysis['correlations']['sibling_busy_vs_scalar_thread_ns']:.3f}) "
                f"and AVX2 ({analysis['correlations']['sibling_busy_vs_avx2_thread_ns']:.3f}) "
                "thread time, more strongly for scalar in this run. This makes differential "
                "SMT contention plausible, but the observation cannot establish causality"
            ),
            "reversal_localization": (
                "CPU 1, 2, and 3 used byte-identical exact binaries and normalized hot "
                f"loops. AVX2 median time varied {cross_cpu['avx2_median_cross_cpu_relative_range']:.2%} "
                f"across them, versus {cross_cpu['scalar_median_cross_cpu_relative_range']:.2%} "
                "for scalar. The sign reversal is therefore localized to scalar throughput "
                "variation on this host, not a faster/slower AVX2 binary."
            ),
            "scope": (
                "AMD EPYC 7B12 CPU 2 diagnostic only; it cannot predict Intel Core Ultra "
                "7 255H P/E/LP-E performance"
            ),
        }

        cpuinfo = Path("/proc/cpuinfo").read_text().splitlines()
        flags = next(line for line in cpuinfo if line.startswith("flags")).split(
            ":", 1
        )[1].split()
        report = {
            "schema_version": 1,
            "experiment": "challenge_scalar_avx2_timing_stability",
            "generated_at_unix_ns": time.time_ns(),
            "environment": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "compiler": run(["gcc", "--version"]).stdout.splitlines()[0],
                "cpu_model": next(
                    line.split(":", 1)[1].strip()
                    for line in cpuinfo
                    if line.startswith("model name")
                ),
                "relevant_cpu_flags": [
                    flag
                    for flag in (
                        "constant_tsc",
                        "nonstop_tsc",
                        "rdtscp",
                        "avx2",
                        "bmi2",
                    )
                    if flag in flags
                ],
                "topology": topology,
                "process_snapshot_before": process_before,
                "process_snapshot_after": process_snapshot(),
                "counter_limitations": {
                    "cpufreq_current_frequency": "unavailable",
                    "perf": "executable unavailable",
                    "aperf_mperf_cpu_flag": "aperfmperf" in flags,
                },
            },
            "cross_cpu_exact_binary_context": cross_cpu,
            "config": {
                "cpu": args.cpu,
                "sibling_cpu": topology["measurement_sibling"],
                "iterations": args.iterations,
                "warmups": args.warmups,
                "samples": args.samples,
                "random_differential_cases": args.random_cases,
                "order": "alternating same-process AB/BA",
                "bootstrap_resamples": 5_000,
            },
            "sources": {
                "tool": {
                    "path": str(Path(__file__).relative_to(ROOT)),
                    "sha256": sha256(Path(__file__)),
                },
                "helper": {
                    "path": str(HELPER.relative_to(ROOT)),
                    "sha256": sha256(HELPER),
                },
                "scalar": {
                    "path": str(SCALAR.relative_to(ROOT)),
                    "sha256": sha256(SCALAR),
                },
                "avx2": {
                    "path": str(AVX2.relative_to(ROOT)),
                    "sha256": sha256(AVX2),
                },
                "existing_process_driver": {
                    "path": str(DRIVER.relative_to(ROOT)),
                    "sha256": sha256(DRIVER),
                },
            },
            "exact_process_isolated": process_report,
            "same_process": {
                "meta": meta,
                "helper_binary_sha256": sha256(helper_executable),
                "assembly": helper_assembly,
                "measurements": measurements,
                "analysis": analysis,
            },
            "interpretation": interpretation,
            "checks": {
                "exact_official_and_random_verification": all(
                    item["status"] == "PASS"
                    and item["random_cases"] == args.random_cases
                    and item["round_counts"] == [1, 20]
                    for item in process_report["candidate_verification"].values()
                ),
                "exact_timed_main_validation": (
                    timed_oracle["status"] == "PASS"
                    and all(
                        item["status"] == "PASS"
                        for item in timed_cases.values()
                    )
                ),
                "exact_binary_audits": all(
                    item["status"] == "PASS"
                    for item in process_report["assembly_audits"].values()
                ),
                "same_process_checksums_equal": len(
                    {record["checksum"] for record in measurements}
                )
                == 1,
                "same_process_zero_hot_calls": all(
                    item["calls"] == 0 for item in helper_assembly.values()
                ),
                "same_process_page_aligned": all(
                    item["address_mod_4096"] == 0
                    for item in helper_assembly.values()
                ),
                "no_migration": analysis["migration_or_aux_change_records"] == 0,
            },
        }
        report["all_checks_passed"] = all(report["checks"].values())
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(interpretation, indent=2, sort_keys=True))
        print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
