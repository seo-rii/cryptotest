#!/usr/bin/env python3
"""Screen GCC 13.3 layout/scheduler flags and verify the short list."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import screen_gcc133_schedules_02 as schedule


BASE_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-mbmi2",
    "-finline-limit=2000",
    "-mtune=alderlake",
    "-fira-algorithm=priority",
]
DEFAULT_SOURCE = "submissions/02/contest.c"
ORDER_SOURCE = "solutions/02_optimization/contest_source_order_2103.c"
EXPECTED_SOURCE_HASHES = {
    DEFAULT_SOURCE: "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71",
    ORDER_SOURCE: "20c625340e40c661a52bacfbee814471e98d13ce0b1c35ea410bf1f557dc0a07",
}
EXPECTED_SHORTLIST = {
    "baseline": ("e0e62e1b598890734db04f0983d66c6121a8fb8b4d12cc456f15b7d5c0740d52", 32, 121.06),
    "selective_scheduling2": ("c097e02f5e4eefb00aa802ce9a29ecb4210eb16a38bb5880ce1b9ea48d2f56d3", 16, 120.06),
    "no_schedule_insns2": ("76e114da82da8a44cae3c5b11e0851263a0ba222e6816a2ef352a729bc44502e", 32, 120.07),
    "no_sched_critical_path": ("d1a3915712cf023180e004ac886b9020a3c8c90d71379697aa3bbbf74c81bf15", 32, 120.14),
    "align_loops_64": ("e0e62e1b598890734db04f0983d66c6121a8fb8b4d12cc456f15b7d5c0740d52", 0, 121.06),
    "lto": ("e0e62e1b598890734db04f0983d66c6121a8fb8b4d12cc456f15b7d5c0740d52", 0, 121.06),
    "order2103_base": ("61198ec39bf108fef1121e095c127b93fcd6c442a274f2b0d6fb821236d51d59", 32, 121.06),
    "order2103_selective_scheduling2": ("23c4b2a5e0186af7ddee996e0679f4e1844b6788d31b7eb7aeebe721ce04165a", 16, 120.06),
    "order2103_no_schedule_insns2": ("503f556835ecbaa3437917997d3e2c4cc2d3aa43ee0b6750a96e05eb5b156157", 32, 120.07),
}


def build_manifest() -> dict[str, dict[str, Any]]:
    variants: dict[str, dict[str, Any]] = {}

    def add(
        name: str,
        *cflags: str,
        ldflags: tuple[str, ...] = (),
        source: str = DEFAULT_SOURCE,
        group: str = "flag_screen",
    ) -> None:
        if name in variants:
            raise RuntimeError(f"duplicate candidate: {name}")
        variants[name] = {
            "cflags": list(cflags),
            "ldflags": list(ldflags),
            "source": source,
            "group": group,
        }

    add("baseline")
    for value in ("1", "8", "16", "32", "64", "128"):
        add(f"align_loops_{value}", f"-falign-loops={value}")
    add("no_align_loops", "-fno-align-loops")
    for name, value in (
        ("align_loops_16_15", "16:15"),
        ("align_loops_32_15", "32:15"),
        ("align_loops_32_31", "32:31"),
        ("align_loops_64_15", "64:15"),
        ("align_loops_64_31", "64:31"),
        ("align_loops_64_63", "64:63"),
        ("align_loops_64_31_32_15", "64:31:32:15"),
        ("align_loops_64_15_32_15", "64:15:32:15"),
    ):
        add(name, f"-falign-loops={value}")

    for family in ("functions", "jumps", "labels"):
        add(f"no_align_{family}", f"-fno-align-{family}")
        for value in ("1", "8", "16", "32", "64", "128"):
            add(f"align_{family}_{value}", f"-falign-{family}={value}")

    for name, flags in {
        "align_function64_loop64": ["-falign-functions=64", "-falign-loops=64"],
        "align_function32_loop64": ["-falign-functions=32", "-falign-loops=64"],
        "align_jump64_loop64": ["-falign-jumps=64", "-falign-loops=64"],
        "align_label64_loop64": ["-falign-labels=64", "-falign-loops=64"],
        "align_all32": [
            "-falign-functions=32",
            "-falign-jumps=32",
            "-falign-labels=32",
            "-falign-loops=32",
        ],
        "align_all64": [
            "-falign-functions=64",
            "-falign-jumps=64",
            "-falign-labels=64",
            "-falign-loops=64",
        ],
        "limit_function_alignment": ["-flimit-function-alignment"],
        "no_limit_function_alignment": ["-fno-limit-function-alignment"],
        "loop64_limit_function_alignment": [
            "-falign-loops=64",
            "-flimit-function-alignment",
        ],
    }.items():
        add(name, *flags)

    for name, flags in {
        "no_toplevel_reorder": ["-fno-toplevel-reorder"],
        "no_reorder_functions": ["-fno-reorder-functions"],
        "reorder_simple": ["-freorder-blocks-algorithm=simple"],
        "no_reorder_blocks": ["-fno-reorder-blocks"],
        "no_reorder_partition": ["-fno-reorder-blocks-and-partition"],
        "tracer": ["-ftracer"],
        "no_guess_branch_probability": ["-fno-guess-branch-probability"],
        "function_sections": ["-ffunction-sections"],
        "function_data_sections": ["-ffunction-sections", "-fdata-sections"],
        "no_plt": ["-fno-plt"],
        "no_semantic_interposition": ["-fno-semantic-interposition"],
        "hidden_visibility": ["-fvisibility=hidden"],
        "ipa_pta": ["-fipa-pta"],
        "ipa_pta_no_semantic": [
            "-fipa-pta",
            "-fno-semantic-interposition",
            "-fvisibility=hidden",
        ],
        "whole_program": ["-fwhole-program"],
        "lto": ["-flto"],
        "lto_partition_one": ["-flto", "-flto-partition=one"],
        "lto_partition_none": ["-flto", "-flto-partition=none"],
        "lto_whole_program": ["-flto", "-fwhole-program"],
        "lto_ipa_pta": ["-flto", "-fipa-pta"],
    }.items():
        add(name, *flags)

    add("function_sections_gc", "-ffunction-sections", ldflags=("-Wl,--gc-sections",))
    add(
        "function_data_sections_gc",
        "-ffunction-sections",
        "-fdata-sections",
        ldflags=("-Wl,--gc-sections",),
    )
    add(
        "function_sections_sort_name",
        "-ffunction-sections",
        ldflags=("-Wl,--sort-section=name",),
    )
    add(
        "function_sections_sort_alignment",
        "-ffunction-sections",
        ldflags=("-Wl,--sort-section=alignment",),
    )
    add(
        "function_sections_gc_sort_name",
        "-ffunction-sections",
        "-fdata-sections",
        ldflags=("-Wl,--gc-sections", "-Wl,--sort-section=name"),
    )
    add(
        "lto_gc_sections",
        "-flto",
        "-ffunction-sections",
        "-fdata-sections",
        ldflags=("-Wl,--gc-sections",),
    )
    add("link_no_relax", ldflags=("-Wl,--no-relax",))
    add("link_optimize", ldflags=("-Wl,-O1",))
    add("link_noseparate_code", ldflags=("-Wl,-z,noseparate-code",))
    add("explicit_no_pie", "-fno-pie", ldflags=("-no-pie",))
    add("pie", "-fPIE", ldflags=("-pie",))
    add(
        "function64_loop64_gc_sections",
        "-falign-functions=64",
        "-falign-loops=64",
        "-ffunction-sections",
        "-fdata-sections",
        ldflags=("-Wl,--gc-sections",),
    )

    for name, flags in {
        "ira_loop_pressure": ["-fira-loop-pressure"],
        "sched_pressure": ["-fsched-pressure"],
        "rename_registers": ["-frename-registers"],
        "web": ["-fweb"],
        "schedule_insns": ["-fschedule-insns"],
        "no_schedule_insns2": ["-fno-schedule-insns2"],
        "selective_scheduling2": ["-fselective-scheduling2"],
        "gcse_after_reload": ["-fgcse-after-reload"],
        "no_peephole2": ["-fno-peephole2"],
        "no_sched_interblock": ["-fno-sched-interblock"],
        "no_sched_spec": ["-fno-sched-spec"],
        "sched_spec_load": ["-fsched-spec-load"],
        "modulo_sched": ["-fmodulo-sched"],
        "modulo_sched_regmoves": [
            "-fmodulo-sched",
            "-fmodulo-sched-allow-regmoves",
        ],
    }.items():
        add(name, *flags)
    heuristic_flags = []
    for heuristic in (
        "critical-path",
        "dep-count",
        "group",
        "last-insn",
        "rank",
        "spec-insn",
    ):
        flag = f"-fno-sched-{heuristic}-heuristic"
        heuristic_flags.append(flag)
        add(f"no_sched_{heuristic.replace('-', '_')}", flag)
    add("no_sched_heuristics", *heuristic_flags)
    add("branch_boundary_32", "-Wa,-mbranches-within-32B-boundaries")
    for name, flag in (
        ("march_x86_64_v3", "-march=x86-64-v3"),
        ("march_alderlake", "-march=alderlake"),
        ("march_raptorlake", "-march=raptorlake"),
        ("march_meteorlake", "-march=meteorlake"),
        ("prefer_vector_128", "-mprefer-vector-width=128"),
        ("prefer_vector_256", "-mprefer-vector-width=256"),
    ):
        add(name, flag)

    if len(variants) != 106:
        raise RuntimeError(f"flag screen must contain 106 candidates, got {len(variants)}")
    add("order2103_base", source=ORDER_SOURCE, group="source_cross")
    add(
        "order2103_selective_scheduling2",
        "-fselective-scheduling2",
        source=ORDER_SOURCE,
        group="source_cross",
    )
    add(
        "order2103_no_schedule_insns2",
        "-fno-schedule-insns2",
        source=ORDER_SOURCE,
        group="source_cross",
    )
    return variants


CONTAINER_DRIVER = r'''
import hashlib, json, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, "/workspace/solutions")
from challenge02_loop_audit import audit_main_timing_loop, validate_loop_audit
out = Path("/output")
manifest = json.loads((out / "manifest.json").read_text())

def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def extract_loop(binary, destination):
    text = subprocess.run(
        ["objdump", "-d", "--no-show-raw-insn", "--disassemble=main", str(binary)],
        check=True, text=True, stdout=subprocess.PIPE,
    ).stdout
    insns = []
    for line in text.splitlines():
        match = re.match(r"^\s*([0-9a-fA-F]+):\s+([^\s]+)(?:\s+(.*?))?\s*$", line)
        if match:
            insns.append((int(match.group(1), 16), match.group(2), (match.group(3) or "").strip()))
    clocks = [i for i, (_, op, arg) in enumerate(insns) if op.startswith("call") and re.search(r"<clock(?:@[^>]*)?>", arg)]
    edges = []
    for i in range(clocks[-2] + 1, clocks[-1]):
        address, op, arg = insns[i]
        target = re.match(r"(?:\*?0x)?([0-9a-fA-F]+)", arg)
        if op.startswith("j") and op != "jmp" and target and int(target.group(1), 16) < address:
            edges.append((i, int(target.group(1), 16)))
    end, start = edges[-1]
    indices = {address: i for i, (address, _, _) in enumerate(insns)}
    loop = insns[indices[start]:end + 1]
    lines = [".text", ".Ltimed_loop:"]
    for index, (_, op, arg) in enumerate(loop):
        arg = re.sub(r"\s+#.*$", "", arg).strip()
        if index == len(loop) - 1 and op.startswith("j"):
            arg = ".Ltimed_loop"
        lines.append((f"\t{op}\t{arg}").rstrip())
    destination.write_text("\n".join(lines) + "\n")

results = {}
for name, item in manifest["variants"].items():
    source = Path("/workspace") / item["source"]
    binary = out / f"{name}.bin"
    command = ["gcc", *manifest["base_flags"], *item["cflags"], str(source), *item["ldflags"], "-o", str(binary)]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        results[name] = {**item, "status": "COMPILE_FAIL", "stderr": completed.stderr.strip()}
        continue
    audit = audit_main_timing_loop(binary, objdump="objdump", size_tool="size")
    errors = validate_loop_audit(audit, "full-inline-320")
    loop = out / f"{name}.loop.s"
    extract_loop(binary, loop)
    results[name] = {
        **item, "status": "PASS" if not errors else "AUDIT_FAIL",
        "source_sha256": digest(source), "audit_errors": errors, "audit": audit,
        "loop_artifact": loop.name,
    }
payload = {
    "compiler": subprocess.run(["gcc", "--version"], check=True, text=True, stdout=subprocess.PIPE).stdout.splitlines()[0],
    "binutils": subprocess.run(["ld", "--version"], check=True, text=True, stdout=subprocess.PIPE).stdout.splitlines()[0],
    "variants": results,
}
(out / "compiled.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
'''


TOP_CASES = {
    "baseline": (DEFAULT_SOURCE, []),
    "selective_scheduling2": (DEFAULT_SOURCE, ["-fselective-scheduling2"]),
    "no_schedule_insns2": (DEFAULT_SOURCE, ["-fno-schedule-insns2"]),
    "no_sched_critical_path": (
        DEFAULT_SOURCE,
        ["-fno-sched-critical-path-heuristic"],
    ),
    "align_loops_64": (DEFAULT_SOURCE, ["-falign-loops=64"]),
    "lto": (DEFAULT_SOURCE, ["-flto"]),
    "order2103_base": (ORDER_SOURCE, []),
    "order2103_selective_scheduling2": (
        ORDER_SOURCE,
        ["-fselective-scheduling2"],
    ),
    "order2103_no_schedule_insns2": (
        ORDER_SOURCE,
        ["-fno-schedule-insns2"],
    ),
}


def run_correctness_smoke(
    runtime: str,
    root: Path,
    temporary: Path,
    random_cases: int,
) -> dict[str, Any]:
    command = [
        runtime,
        "run",
        "--rm",
        "--pull",
        "never",
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{root}:/workspace:ro",
        "--volume",
        f"{temporary}:/output",
        "--workdir",
        "/workspace",
        schedule.IMAGE,
        "python3",
        "solutions/benchmark_02_permutation.py",
        "--compiler",
        "gcc",
        "--baseline",
        "baseline",
    ]
    for name, (source, flags) in TOP_CASES.items():
        command.extend(["--case", f"{name}={source}"])
        for flag in flags:
            command.extend(["--case-cflag", f"{name}={flag}"])
        command.extend(["--audit-mode", f"{name}=full-inline-320"])
    for flag in BASE_FLAGS[3:]:
        command.append(f"--extra-cflag={flag}")
    command.extend(
        [
            "--cpu",
            "none",
            "--iterations",
            "1000",
            "--warmups",
            "1",
            "--samples",
            "5",
            "--random-cases",
            str(random_cases),
            "--campaign-id",
            "gcc133-layout-correctness-smoke",
            "--json",
            "/output/correctness.json",
        ]
    )
    schedule.run_checked(command)
    return json.loads((temporary / "correctness.json").read_text())


def compact_audit(audit: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "binary_sha256",
        "text_bytes",
        "loop_start",
        "loop_start_mod_64",
        "loop_bytes",
        "loop_instructions",
        "calls",
        "push_pop",
        "memory_operands_excluding_lea",
        "core_counts",
        "normalized_loop_sha256",
    )
    return {key: audit[key] for key in keys}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--llvm-mca", default="llvm-mca-16")
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(__file__).with_name("gcc133_layout_screen_02.json"),
    )
    args = parser.parse_args()
    if args.random_cases <= 0:
        parser.error("--random-cases must be positive")

    root = Path(__file__).resolve().parents[2]
    variants = build_manifest()
    with tempfile.TemporaryDirectory(prefix="challenge02-gcc133-layout-") as name:
        temporary = Path(name).resolve()
        (temporary / "manifest.json").write_text(
            json.dumps({"base_flags": BASE_FLAGS, "variants": variants})
        )
        docker = [
            args.runtime,
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{root}:/workspace:ro",
            "--volume",
            f"{temporary}:/output",
            "--workdir",
            "/output",
            schedule.IMAGE,
            "python3",
            "-c",
            CONTAINER_DRIVER,
        ]
        schedule.run_checked(
            docker,
            display_command=[*docker[:-1], "<embedded-layout-driver>"],
        )
        compiled = json.loads((temporary / "compiled.json").read_text())

        representatives: dict[str, str] = {}
        members: dict[str, list[str]] = {}
        for candidate, result in compiled["variants"].items():
            if result["status"] != "PASS":
                continue
            loop_hash = result["audit"]["normalized_loop_sha256"]
            representatives.setdefault(loop_hash, candidate)
            members.setdefault(loop_hash, []).append(candidate)
        stream_metrics = {}
        for loop_hash, representative in representatives.items():
            loop_path = temporary / compiled["variants"][representative]["loop_artifact"]
            stream_metrics[loop_hash] = schedule.analyse_loop(
                args.llvm_mca,
                loop_path,
                iterations=schedule.ITERATIONS,
            )

        smoke = run_correctness_smoke(
            args.runtime,
            root,
            temporary,
            args.random_cases,
        )
        if smoke.get("schema_version") != 5:
            raise RuntimeError(
                "correctness smoke report schema is not 5: "
                f"{smoke.get('schema_version')!r}"
            )
        smoke_config = smoke.get("config", {})
        if not (
            smoke_config.get("iterations") == 1000
            and smoke_config.get("warmups") == 1
            and smoke_config.get("samples_per_case") == 5
            and smoke_config.get("timed_main_repeated_call_validation") is True
        ):
            raise RuntimeError("correctness smoke process counts changed")
        timed_validation = smoke.get("timed_main_validation")
        if not isinstance(timed_validation, dict):
            raise RuntimeError("correctness smoke omitted timed_main_validation")
        if set(timed_validation) != {"oracle", "cases"}:
            raise RuntimeError("correctness smoke timed-main validation shape changed")
        timed_oracle = timed_validation.get("oracle")
        timed_cases = timed_validation.get("cases")
        if not isinstance(timed_oracle, dict) or not isinstance(timed_cases, dict):
            raise RuntimeError("correctness smoke timed-main validation is malformed")
        if set(timed_oracle) != {
            "mode",
            "iterations",
            "expected_final_state",
            "stdout_sha256",
            "status",
        }:
            raise RuntimeError("correctness smoke timed-main oracle shape changed")
        if set(timed_cases) != set(TOP_CASES):
            raise RuntimeError(
                f"correctness smoke timed-main case set changed: {sorted(timed_cases)!r}"
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
                    "oracle_final_state_iterations=1000\n"
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
            and timed_oracle.get("iterations") == 1000
            and valid_state
            and isinstance(timed_oracle.get("stdout_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", timed_oracle["stdout_sha256"])
            and timed_oracle.get("stdout_sha256") == canonical_oracle_hash
            and timed_oracle.get("status") == "PASS"
        ):
            raise RuntimeError("correctness smoke timed-main oracle did not pass")
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
                    f"{candidate}: correctness smoke timed-main case shape changed"
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
                and timed_case.get("iterations") == 1000
                and timed_case.get("observed_final_state") == expected_state
                and timed_case.get("preflight_processes") == 1
                and timed_case.get("warmup_processes") == 1
                and timed_case.get("measured_processes") == 5
                and timed_case.get("validated_processes") == 7
                and timed_case.get("status") == "PASS"
            ):
                raise RuntimeError(
                    f"{candidate}: correctness smoke timed-main validation failed"
                )
        compact_variants = {}
        for candidate, result in compiled["variants"].items():
            compact_variants[candidate] = {
                "group": result["group"],
                "source": result["source"],
                "source_sha256": result.get("source_sha256"),
                "cflags": result["cflags"],
                "ldflags": result["ldflags"],
                "status": result["status"],
            }
            if result["status"] == "PASS":
                loop_hash = result["audit"]["normalized_loop_sha256"]
                compact_variants[candidate].update(
                    {
                        "audit": compact_audit(result["audit"]),
                        "loop_stream_sha256": loop_hash,
                    }
                )
                if candidate in TOP_CASES:
                    compact_variants[candidate]["llvm_mca"] = stream_metrics[
                        loop_hash
                    ]

        top_evidence = {}
        for candidate in TOP_CASES:
            top_evidence[candidate] = {
                "random_differential": smoke["candidate_verification"][candidate],
                "timed_main_validation": timed_cases[candidate],
                "official_vectors_checked_on_every_smoke_process": True,
                "measured_smoke_binary_audit": smoke["assembly_audits"][candidate],
            }

        flag_screen = {
            name: result
            for name, result in compact_variants.items()
            if result["group"] == "flag_screen"
        }
        source_cross = {
            name: result
            for name, result in compact_variants.items()
            if result["group"] == "source_cross"
        }
        checks = {
            "compiler_is_exact_gcc_13_3_0": compiled["compiler"]
            == "gcc (GCC) 13.3.0",
            "flag_screen_attempted_106": len(flag_screen) == 106,
            "all_109_builds_and_audits_pass": all(
                item["status"] == "PASS" for item in compact_variants.values()
            ),
            "source_hashes_are_expected": all(
                schedule.sha256(root / path) == expected
                for path, expected in EXPECTED_SOURCE_HASHES.items()
            ),
            "flag_screen_has_9_unique_loops": len(
                {
                    item["audit"]["normalized_loop_sha256"]
                    for item in flag_screen.values()
                }
            )
            == 9,
            "all_top_random_differential_gates_pass": all(
                evidence["random_differential"]["status"] == "PASS"
                for evidence in top_evidence.values()
            ),
            "all_top_timed_main_validations_pass": (
                timed_oracle["status"] == "PASS"
                and all(
                    evidence["timed_main_validation"]["status"] == "PASS"
                    for evidence in top_evidence.values()
                )
            ),
            "all_top_measured_binary_audits_pass": all(
                evidence["measured_smoke_binary_audit"]["status"] == "PASS"
                for evidence in top_evidence.values()
            ),
            "shortlist_hash_alignment_and_mca_are_expected": all(
                compact_variants[candidate]["audit"]["normalized_loop_sha256"]
                == expected[0]
                and compact_variants[candidate]["audit"]["loop_start_mod_64"]
                == expected[1]
                and compact_variants[candidate]["llvm_mca"]["alderlake"][
                    "cycles_per_iteration"
                ]
                == expected[2]
                for candidate, expected in EXPECTED_SHORTLIST.items()
            ),
        }
        if not all(checks.values()):
            raise RuntimeError(
                "layout-screen checks failed: "
                + ", ".join(key for key, value in checks.items() if not value)
            )
        payload = {
            "schema_version": 1,
            "experiment": "challenge02_gcc133_layout_and_scheduler_screen",
            "container_image": schedule.IMAGE,
            "compiler": compiled["compiler"],
            "binutils": compiled["binutils"],
            "llvm_mca": schedule.run_checked(
                [args.llvm_mca, "--version"]
            ).stdout.splitlines()[0],
            "base_flags": BASE_FLAGS,
            "source_hashes": EXPECTED_SOURCE_HASHES,
            "summary": {
                "flag_candidates": len(flag_screen),
                "source_cross_candidates": len(source_cross),
                "unique_flag_screen_loops": 9,
                "correctness_random_cases_per_top_candidate": args.random_cases,
            },
            "checks": checks,
            "all_checks_passed": all(checks.values()),
            "shortlist": list(TOP_CASES),
            "timed_main_validation": timed_validation,
            "top_evidence": top_evidence,
            "unique_streams": {
                loop_hash: {
                    "representative": representatives[loop_hash],
                    "members": sorted(members[loop_hash]),
                    "llvm_mca": stream_metrics[loop_hash],
                }
                for loop_hash in sorted(stream_metrics)
            },
            "flag_screen": flag_screen,
            "source_cross": source_cross,
            "decision": (
                "screening-only; retain the incumbent until repeated Core Ultra "
                "7 255H measurements qualify one candidate"
            ),
        }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.json.with_suffix(args.json.suffix + ".tmp")
    temporary_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_output, args.json)
    print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
