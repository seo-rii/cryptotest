#!/usr/bin/env python3
"""Reproduce the GCC 13.3 schedule-flag screen for challenge 2.

Compilation happens in the digest-pinned official GCC image with the repository
mounted read-only.  Only the extracted timing loops are then analysed by the
host's llvm-mca-16.  The script deliberately records compile failures as data:
the original 34-candidate screen contains two options unsupported by GCC 13.3.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any


IMAGE_DIGEST = (
    "1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
)
IMAGE = f"gcc@sha256:{IMAGE_DIGEST}"
BASE_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-mbmi2",
    "-finline-limit=2000",
]
MODELS = ["alderlake", "raptorlake", "meteorlake", "tremont"]
ITERATIONS = 100
EXPECTED_SOURCE_SHA256 = (
    "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71"
)
EXPECTED_FAILURES = {"alder_pressure_model", "alder_pressure_weighted"}
EXPECTED_LOOP_HASHES = {
    "1d678d4d7b1f8cb5382d43dfc7a1b81670490710f3b638f69ae0dedeba06a00f",
    "23d63ff2ff7e52cebf6b27750a718f0d5d35883f9c1c41f0dcb2a8c76ba1a3cc",
    "660a3b0eefae2dcee09b1edc29ea5a79787adbcbee1e5cb8157e530cd8665951",
    "760d83e5e9cba5c27337ca74abf38b486cf1d06dc787e3ccebded20fac500a31",
    "942ba40fb65a4258f1fd84f82c0d00d30741ae34f36cc8a02fbc19836f753357",
    "c2dbc254fb7fd3acf87077b8431ddd3b7f1ecc08c497cc31d257cd91cb65ca40",
    "d32200298093e8be76aabac31324b6066dd94e15851e501d81a66d67cca7ec63",
    "f1a854d4bae22442f8eed9ca35a6ea4fb6922d52c7495e1c202563440364c8cf",
}
EXPECTED_REFERENCES = {
    "generic": {
        "binary_sha256": (
            "df7da5f1f98311bfcf4472f6eab2077586fd264966aa6952b306fedbb6572f2e"
        ),
        "loop_text_sha256": (
            "23d63ff2ff7e52cebf6b27750a718f0d5d35883f9c1c41f0dcb2a8c76ba1a3cc"
        ),
        "alderlake_cycles_per_iteration": 125.06,
    },
    "alderlake": {
        "binary_sha256": (
            "caf4e5a5d66cc3fa00a36e17c34e710ef7c580e39825bd65fe539b7493fec9dc"
        ),
        "loop_text_sha256": (
            "1d678d4d7b1f8cb5382d43dfc7a1b81670490710f3b638f69ae0dedeba06a00f"
        ),
        "alderlake_cycles_per_iteration": 123.62,
    },
    "alder_ira_priority": {
        "binary_sha256": (
            "35adefa3154778f36bb8a0b93630c7bac90bd348550ffb4ab868cf59e30597af"
        ),
        "loop_text_sha256": (
            "760d83e5e9cba5c27337ca74abf38b486cf1d06dc787e3ccebded20fac500a31"
        ),
        "alderlake_cycles_per_iteration": 121.06,
    },
}

# Keep this manifest explicit: failed hypotheses are part of the experiment.
VARIANTS: dict[str, list[str]] = {
    "generic": [],
    "alderlake": ["-mtune=alderlake"],
    "alder_sched1": ["-mtune=alderlake", "-fschedule-insns"],
    "alder_no_sched2": ["-mtune=alderlake", "-fno-schedule-insns2"],
    "alder_pressure": ["-mtune=alderlake", "-fsched-pressure"],
    "alder_pressure1": [
        "-mtune=alderlake",
        "-fsched-pressure",
        "--param=sched-pressure-algorithm=1",
    ],
    "alder_pressure2": [
        "-mtune=alderlake",
        "-fsched-pressure",
        "--param=sched-pressure-algorithm=2",
    ],
    "alder_pressure_model": [
        "-mtune=alderlake",
        "-fsched-pressure-algorithm=model",
    ],
    "alder_pressure_weighted": [
        "-mtune=alderlake",
        "-fsched-pressure-algorithm=weighted",
    ],
    "alder_stall0": ["-mtune=alderlake", "-fsched-stalled-insns=0"],
    "alder_stall1": ["-mtune=alderlake", "-fsched-stalled-insns=1"],
    "alder_stall2": ["-mtune=alderlake", "-fsched-stalled-insns=2"],
    "alder_stalldep1": [
        "-mtune=alderlake",
        "-fsched-stalled-insns-dep=1",
    ],
    "alder_stalldep2": [
        "-mtune=alderlake",
        "-fsched-stalled-insns-dep=2",
    ],
    "alder_superblocks": ["-mtune=alderlake", "-fsched2-use-superblocks"],
    "alder_traces": ["-mtune=alderlake", "-fsched2-use-traces"],
    "alder_rename": ["-mtune=alderlake", "-frename-registers"],
    "alder_web": ["-mtune=alderlake", "-fweb"],
    "alder_ira_priority": ["-mtune=alderlake", "-fira-algorithm=priority"],
    "alder_ira_all": ["-mtune=alderlake", "-fira-region=all"],
    "alder_ira_one": ["-mtune=alderlake", "-fira-region=one"],
    "alder_ira_hoist": ["-mtune=alderlake", "-fira-hoist-pressure"],
    "alder_no_ira_hoist": ["-mtune=alderlake", "-fno-ira-hoist-pressure"],
    "alder_no_sched_interblock": [
        "-mtune=alderlake",
        "-fno-sched-interblock",
    ],
    "alder_no_sched_spec": ["-mtune=alderlake", "-fno-sched-spec"],
    "alder_sel_sched": ["-mtune=alderlake", "-fselective-scheduling"],
    "alder_sel_sched2": ["-mtune=alderlake", "-fselective-scheduling2"],
    "alder_sel_pipe": [
        "-mtune=alderlake",
        "-fselective-scheduling",
        "-fsel-sched-pipelining",
    ],
    "alder_gcse_reload": ["-mtune=alderlake", "-fgcse-after-reload"],
    "alder_no_peephole2": ["-mtune=alderlake", "-fno-peephole2"],
    "alder_no_reorder": ["-mtune=alderlake", "-fno-reorder-blocks"],
    "alder_no_partition": [
        "-mtune=alderlake",
        "-fno-reorder-blocks-and-partition",
    ],
    "alder_align32": ["-mtune=alderlake", "-falign-loops=32"],
    "alder_align64": ["-mtune=alderlake", "-falign-loops=64"],
}


CONTAINER_DRIVER = textwrap.dedent(
    r"""
    import hashlib
    import json
    import re
    import subprocess
    from pathlib import Path

    SOURCE = Path("/workspace/submissions/02/contest.c")
    OUTPUT = Path("/output/artifacts")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path("/output/variants.json").read_text())
    base_flags = manifest["base_flags"]
    reports = {}

    def sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    for name, extra_flags in manifest["variants"].items():
        assembly = OUTPUT / f"{name}.s"
        binary = OUTPUT / name
        loop_path = OUTPUT / f"{name}.loop.s"
        flags = [*base_flags, *extra_flags]
        assembly_command = ["gcc", *flags, "-S", str(SOURCE), "-o", str(assembly)]
        completed = subprocess.run(
            assembly_command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        common = {
            "extra_flags": extra_flags,
            "effective_flags": flags,
            "binary_sha256": None,
            "assembly_sha256": None,
            "loop_text_sha256": None,
            "loop_instruction_lines": None,
            "llvm_mca": None,
        }
        if completed.returncode:
            reports[name] = {
                **common,
                "status": "COMPILE_FAIL",
                "returncode": completed.returncode,
                "stderr": completed.stderr.strip(),
            }
            continue

        binary_command = ["gcc", *flags, str(SOURCE), "-o", str(binary)]
        completed = subprocess.run(
            binary_command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if completed.returncode:
            reports[name] = {
                **common,
                "status": "LINK_FAIL",
                "returncode": completed.returncode,
                "stderr": completed.stderr.strip(),
                "assembly_sha256": sha256(assembly),
            }
            continue

        assembly_text = assembly.read_text()
        clock_calls = [
            match.start()
            for match in re.finditer(
                r"^\s*call\s+clock(?:@PLT)?\s*$", assembly_text, re.MULTILINE
            )
        ]
        if len(clock_calls) < 2:
            raise RuntimeError(
                f"{name}: expected at least two clock calls, got {len(clock_calls)}"
            )
        region = assembly_text[clock_calls[-2] : clock_calls[-1]]
        backedges = list(
            re.finditer(r"^\s*jne\s+(\.L\d+)\s*$", region, re.MULTILINE)
        )
        if not backedges:
            raise RuntimeError(f"{name}: timing-loop backedge was not found")
        target = backedges[-1].group(1)
        start = region.index(target + ":")
        end = backedges[-1].end()
        loop_text = ".text\n" + region[start:end] + "\n"
        loop_path.write_text(loop_text)
        reports[name] = {
            **common,
            "status": "PASS",
            "returncode": 0,
            "stderr": "",
            "binary_sha256": sha256(binary),
            "assembly_sha256": sha256(assembly),
            "loop_text_sha256": hashlib.sha256(loop_text.encode()).hexdigest(),
            "loop_instruction_lines": sum(
                line.startswith("\t") for line in loop_text.splitlines()
            ),
            "loop_artifact": f"artifacts/{name}.loop.s",
        }

    compiler = subprocess.run(
        ["gcc", "--version"], check=True, text=True, stdout=subprocess.PIPE
    ).stdout.splitlines()[0]
    binutils = subprocess.run(
        ["ld", "--version"], check=True, text=True, stdout=subprocess.PIPE
    ).stdout.splitlines()[0]
    output = {
        "compiler": compiler,
        "binutils": binutils,
        "source_sha256": sha256(SOURCE),
        "variants": reports,
    }
    Path("/output/compile-results.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n"
    )
    """
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_checked(
    command: list[str],
    *,
    display_command: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print(
        "$",
        subprocess.list2cmdline(display_command or command),
        flush=True,
    )
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(
            f"command failed with exit status {completed.returncode}: {detail}"
        )
    return completed


def extract_number(output: str, label: str) -> float:
    match = re.search(
        rf"^{re.escape(label)}:\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"llvm-mca output omitted {label!r}")
    return float(match.group(1))


def analyse_loop(
    llvm_mca: str,
    loop_path: Path,
    *,
    iterations: int,
) -> dict[str, dict[str, float | int]]:
    model_results: dict[str, dict[str, float | int]] = {}
    for model in MODELS:
        output = run_checked(
            [
                llvm_mca,
                f"-mcpu={model}",
                f"-iterations={iterations}",
                str(loop_path),
            ]
        ).stdout
        total_cycles = int(extract_number(output, "Total Cycles"))
        instructions = int(extract_number(output, "Instructions"))
        model_results[model] = {
            "iterations": iterations,
            "total_cycles": total_cycles,
            "total_instructions": instructions,
            "cycles_per_iteration": total_cycles / iterations,
            "instructions_per_iteration": instructions / iterations,
            "block_rthroughput": extract_number(output, "Block RThroughput"),
        }
    return model_results


def inspect_image(runtime: str) -> str:
    completed = run_checked(
        [runtime, "image", "inspect", "--format", "{{.Id}}", IMAGE]
    )
    image_id = completed.stdout.strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        raise RuntimeError(f"unexpected local image id: {image_id!r}")
    return image_id


def compile_variants(runtime: str, root: Path, temporary: Path) -> dict[str, Any]:
    manifest = {"base_flags": BASE_FLAGS, "variants": VARIANTS}
    (temporary / "variants.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (temporary / "work").mkdir()
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
        "/output/work",
        IMAGE,
        "python3",
        "-c",
        CONTAINER_DRIVER,
    ]
    completed = run_checked(
        command,
        display_command=[*command[:-1], "<embedded-compile-driver>"],
    )
    if completed.stdout.strip():
        print(completed.stdout.rstrip())
    return json.loads((temporary / "compile-results.json").read_text())


def check_reference_variants(variants: dict[str, dict[str, Any]]) -> bool:
    for name, expected in EXPECTED_REFERENCES.items():
        actual = variants[name]
        if actual["binary_sha256"] != expected["binary_sha256"]:
            return False
        if actual["loop_text_sha256"] != expected["loop_text_sha256"]:
            return False
        cycles = actual["llvm_mca"]["alderlake"]["cycles_per_iteration"]
        if cycles != expected["alderlake_cycles_per_iteration"]:
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compile the 34 challenge-2 schedule candidates with the pinned "
            "official GCC 13.3 image and analyse unique loops with llvm-mca-16."
        )
    )
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--llvm-mca", default="llvm-mca-16")
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(__file__).with_name("gcc133_schedule_screen_02.json"),
    )
    args = parser.parse_args()

    if shutil.which(args.runtime) is None:
        parser.error(f"container runtime is unavailable: {args.runtime}")
    if shutil.which(args.llvm_mca) is None:
        parser.error(f"llvm-mca is unavailable: {args.llvm_mca}")
    if len(VARIANTS) != 34:
        raise RuntimeError(f"candidate manifest must have 34 entries, got {len(VARIANTS)}")

    root = Path(__file__).resolve().parents[2]
    source = root / "submissions" / "02" / "contest.c"
    if not source.is_file():
        raise RuntimeError(f"challenge source is missing: {source}")
    source_hash = sha256(source)
    image_id = inspect_image(args.runtime)
    llvm_version = run_checked([args.llvm_mca, "--version"]).stdout.splitlines()[0]

    with tempfile.TemporaryDirectory(prefix="challenge02-gcc133-schedules-") as name:
        temporary = Path(name).resolve()
        compiled = compile_variants(args.runtime, root, temporary)
        variants: dict[str, dict[str, Any]] = compiled["variants"]

        representatives: dict[str, str] = {}
        stream_members: dict[str, list[str]] = {}
        for variant_name, report in variants.items():
            if report["status"] != "PASS":
                continue
            loop_hash = report["loop_text_sha256"]
            representatives.setdefault(loop_hash, variant_name)
            stream_members.setdefault(loop_hash, []).append(variant_name)

        stream_results: dict[str, dict[str, Any]] = {}
        for loop_hash, representative in sorted(representatives.items()):
            loop_path = temporary / variants[representative]["loop_artifact"]
            metrics = analyse_loop(
                args.llvm_mca,
                loop_path,
                iterations=ITERATIONS,
            )
            stream_results[loop_hash] = {
                "representative": representative,
                "members": sorted(stream_members[loop_hash]),
                "llvm_mca": metrics,
            }
            for variant_name in stream_members[loop_hash]:
                variants[variant_name]["llvm_mca"] = metrics

        # Temporary artifact locations are intentionally not part of the record.
        for report in variants.values():
            report.pop("loop_artifact", None)

        passed = {name for name, item in variants.items() if item["status"] == "PASS"}
        failed = set(variants) - passed
        loop_hashes = {
            item["loop_text_sha256"]
            for item in variants.values()
            if item["status"] == "PASS"
        }
        checks = {
            "pinned_image_digest_is_expected": IMAGE.endswith(IMAGE_DIGEST),
            "compiler_is_exact_gcc_13_3_0": compiled["compiler"]
            == "gcc (GCC) 13.3.0",
            "llvm_mca_is_version_16": bool(
                re.search(r"LLVM version 16(?:\.|$)", llvm_version)
            ),
            "source_hash_is_expected": source_hash == EXPECTED_SOURCE_SHA256,
            "container_and_host_source_hashes_match": compiled["source_sha256"]
            == source_hash,
            "attempted_34_candidates": len(variants) == 34,
            "compiled_32_candidates": len(passed) == 32,
            "only_expected_options_failed": failed == EXPECTED_FAILURES,
            "compiled_candidates_have_complete_hashes_and_metrics": all(
                item["binary_sha256"]
                and item["assembly_sha256"]
                and item["loop_text_sha256"]
                and item["llvm_mca"]
                for item in variants.values()
                if item["status"] == "PASS"
            ),
            "failed_candidates_have_no_binary_or_loop_metrics": all(
                item["binary_sha256"] is None
                and item["loop_text_sha256"] is None
                and item["llvm_mca"] is None
                for item in variants.values()
                if item["status"] != "PASS"
            ),
            "exactly_8_unique_hot_loops": len(loop_hashes) == 8,
            "unique_hot_loop_hashes_are_expected": loop_hashes
            == EXPECTED_LOOP_HASHES,
            "reference_hashes_and_alderlake_cycles_are_expected": (
                check_reference_variants(variants)
            ),
        }
        if not all(checks.values()):
            failed_checks = [name for name, passed_check in checks.items() if not passed_check]
            raise RuntimeError(f"schedule-screen checks failed: {failed_checks}")

        output: dict[str, Any] = {
            "schema_version": 1,
            "experiment": "challenge02_exact_gcc133_schedule_screen",
            "container": {
                "image": IMAGE,
                "pinned_manifest_digest_sha256": IMAGE_DIGEST,
                "local_image_id": image_id,
                "network": "none",
                "repository_mount": "read-only",
            },
            "compiler": compiled["compiler"],
            "binutils": compiled["binutils"],
            "llvm_mca": {
                "executable": args.llvm_mca,
                "version": llvm_version,
                "models": MODELS,
                "iterations": ITERATIONS,
            },
            "source": {
                "path": "submissions/02/contest.c",
                "sha256": source_hash,
            },
            "base_flags": BASE_FLAGS,
            "summary": {
                "attempted": len(variants),
                "compiled": len(passed),
                "compile_failed": len(failed),
                "unique_hot_loops": len(loop_hashes),
            },
            "checks": checks,
            "all_checks_passed": all(checks.values()),
            "reference_variants": list(EXPECTED_REFERENCES),
            "unique_streams": stream_results,
            "variants": variants,
            "notes": [
                "llvm-mca is a static scheduling model, not a target-CPU timing result.",
                "The two compile failures are retained because they close rejected flag hypotheses.",
                "Loop hashes cover the exact GCC assembly region supplied to llvm-mca.",
            ],
        }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.json.with_suffix(args.json.suffix + ".tmp")
    temporary_output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_output, args.json)
    print(
        "summary "
        f"attempted={output['summary']['attempted']} "
        f"compiled={output['summary']['compiled']} "
        f"failed={output['summary']['compile_failed']} "
        f"unique={output['summary']['unique_hot_loops']}"
    )
    for name in EXPECTED_REFERENCES:
        cycles = output["variants"][name]["llvm_mca"]["alderlake"][
            "cycles_per_iteration"
        ]
        print(f"reference={name} alderlake_cycles_per_iteration={cycles:.2f}")
    print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
