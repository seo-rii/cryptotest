#!/usr/bin/env python3
"""Screen exact challenge-2 chain orders with digest-pinned GCC 13.3."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any


IMAGE_DIGEST = "1d71f0f3450214bef38fe09e6f610fb6cca90cf97b43f4ce845bfc32a4168818"
IMAGE = f"gcc@sha256:{IMAGE_DIGEST}"
BASE_FLAGS = [
    "-O3",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-mbmi2",
    "-finline-limit=2000",
]
PROFILES = {
    "generic": [],
    "alderlake": ["-mtune=alderlake"],
    "alder_ira": ["-mtune=alderlake", "-fira-algorithm=priority"],
}
MODELS = ("alderlake", "tremont")
TOP_ORDER = (2, 1, 0, 3)
EXPECTED_BASE_SHA256 = "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71"
EXPECTED_TOP_SHA256 = "20c625340e40c661a52bacfbee814471e98d13ce0b1c35ea410bf1f557dc0a07"
EXPECTED_VERIFIER_STDOUT = """candidate_random_differential_cases=100000
candidate_random_seed=0x243f6a8885a308d3
candidate_random_state_and_constants=PASS
candidate_round_counts=1,20
candidate_differential=PASS
"""

CHAIN = {
    0: "x0 = transform_word(transform_word(x0, 43U, k0, a3), 14U, k3, a0);",
    1: "x1 = transform_word(transform_word(x1, 7U, k1, a2), 29U, k2, a1);",
    2: "x2 = transform_word(transform_word(x2, 29U, k2, a1), 7U, k1, a2);",
    3: "x3 = transform_word(transform_word(x3, 14U, k3, a0), 43U, k0, a3);",
}
MACRO_RE = re.compile(
    r"#define APPLY_TWO_ROUNDS\(\).*?^\s*\} while \(0\)\n",
    re.MULTILINE | re.DOTALL,
)


CONTAINER_DRIVER = textwrap.dedent(
    r"""
    import hashlib
    import json
    import re
    import subprocess
    from pathlib import Path

    sources = Path("/input")
    output = Path("/output")
    manifest = json.loads(Path("/config/manifest.json").read_text())
    output.mkdir(exist_ok=True)
    reports = {}

    def sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    for source_name in manifest["sources"]:
        source = sources / f"{source_name}.c"
        for profile, extra_flags in manifest["profiles"].items():
            key = f"{source_name}__{profile}"
            assembly = output / f"{key}.s"
            binary = output / key
            flags = [*manifest["base_flags"], *extra_flags]
            subprocess.run(
                ["gcc", *flags, "-S", str(source), "-o", str(assembly)],
                check=True,
            )
            subprocess.run(
                ["gcc", *flags, str(source), "-o", str(binary)],
                check=True,
            )
            text = assembly.read_text()
            clock_calls = [
                match.start()
                for match in re.finditer(
                    r"^\s*call\s+clock(?:@PLT)?\s*$", text, re.MULTILINE
                )
            ]
            if len(clock_calls) < 2:
                raise RuntimeError(f"{key}: timing clock calls not found")
            region = text[clock_calls[-2] : clock_calls[-1]]
            backedges = list(
                re.finditer(r"^\s*jne\s+(\.L\d+)\s*$", region, re.MULTILINE)
            )
            if not backedges:
                raise RuntimeError(f"{key}: timing loop backedge not found")
            target = backedges[-1].group(1)
            loop = (
                ".text\n"
                + region[region.index(target + ":") : backedges[-1].end()]
                + "\n"
            )
            loop_path = output / f"{key}.loop.s"
            loop_path.write_text(loop)
            reports[key] = {
                "source": source_name,
                "profile": profile,
                "effective_flags": flags,
                "binary_sha256": sha256(binary),
                "assembly_sha256": sha256(assembly),
                "loop_text_sha256": hashlib.sha256(loop.encode()).hexdigest(),
                "loop_artifact": loop_path.name,
            }

    candidate = sources / "order_2103.c"
    candidate_object = output / "candidate.o"
    verifier_object = output / "verifier.o"
    verifier = output / "verifier"
    subprocess.run(
        [
            "gcc",
            *manifest["base_flags"],
            "-Dmain=contest_candidate_main",
            "-c",
            str(candidate),
            "-o",
            str(candidate_object),
        ],
        check=True,
    )
    subprocess.run(
        [
            "gcc",
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
            "-c",
            "/repository/submissions/02/src/optimization/verify_contest_candidate.c",
            "-o",
            str(verifier_object),
        ],
        check=True,
    )
    subprocess.run(
        ["gcc", *manifest["base_flags"], str(candidate_object),
         str(verifier_object), "-o", str(verifier)],
        check=True,
    )
    verified = subprocess.run(
        [str(verifier), "100000"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    result = {
        "compiler": subprocess.run(
            ["gcc", "--version"], check=True, text=True, stdout=subprocess.PIPE
        ).stdout.splitlines()[0],
        "binutils": subprocess.run(
            ["ld", "--version"], check=True, text=True, stdout=subprocess.PIPE
        ).stdout.splitlines()[0],
        "reports": reports,
        "verification": {
            "returncode": verified.returncode,
            "stdout": verified.stdout,
            "stderr": verified.stderr,
            "candidate_translation_unit_cflags": [
                *manifest["base_flags"], "-Dmain=contest_candidate_main"
            ],
            "verifier_translation_unit_cflags": [
                "-O3", "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror"
            ],
            "random_cases": 100000,
            "random_state_and_constants": True,
            "round_counts": [1, 20],
        },
    }
    Path("/output/compile.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    """
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def macro_for(order: tuple[int, ...]) -> str:
    lines = [
        "#define APPLY_TWO_ROUNDS()                                                    \\",
        "    do {                                                                      \\",
    ]
    lines.extend(f"        {CHAIN[index]:<68} \\" for index in order)
    lines.append("    } while (0)\n")
    return "\n".join(lines)


def generate_source(baseline: str, order: tuple[int, ...]) -> str:
    generated, count = MACRO_RE.subn(lambda _: macro_for(order), baseline, count=1)
    if count != 1:
        raise RuntimeError("APPLY_TWO_ROUNDS macro was not found exactly once")
    return generated


def extract_number(output: str, label: str) -> float:
    match = re.search(
        rf"^{re.escape(label)}:\s+([0-9]+(?:\.[0-9]+)?)\s*$",
        output,
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"llvm-mca output omitted {label!r}")
    return float(match.group(1))


def analyse_loop(llvm_mca: str, loop: Path, model: str) -> dict[str, float | int]:
    completed = subprocess.run(
        [llvm_mca, f"-mcpu={model}", "-iterations=100", str(loop)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        "iterations": 100,
        "total_cycles": int(extract_number(completed.stdout, "Total Cycles")),
        "cycles_per_iteration": extract_number(completed.stdout, "Total Cycles")
        / 100.0,
        "instructions_per_iteration": extract_number(
            completed.stdout, "Instructions"
        )
        / 100.0,
        "block_rthroughput": extract_number(completed.stdout, "Block RThroughput"),
    }


def run_screen(args: argparse.Namespace) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[4]
    baseline_path = repository / "submissions/02/contest.c"
    top_path = Path(__file__).with_name("contest_source_order_2103.c").resolve()
    verifier_path = Path(__file__).with_name("verify_contest_candidate.c").resolve()
    baseline = baseline_path.read_text(encoding="utf-8")
    generated_top = generate_source(baseline, TOP_ORDER).encode()

    if shutil.which(args.runtime) is None or shutil.which(args.llvm_mca) is None:
        raise RuntimeError("docker and llvm-mca-16 are required")
    image_id = subprocess.run(
        [args.runtime, "image", "inspect", "--format", "{{.Id}}", IMAGE],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    llvm_version = subprocess.run(
        [args.llvm_mca, "--version"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()[0]

    with tempfile.TemporaryDirectory(prefix="challenge-source-orders-") as name:
        temporary = Path(name).resolve()
        sources = temporary / "sources"
        artifacts = temporary / "artifacts"
        sources.mkdir()
        artifacts.mkdir()
        orders = list(itertools.permutations(range(4)))
        source_hashes: dict[str, str] = {}
        for order in orders:
            source_name = "order_" + "".join(str(index) for index in order)
            encoded = generate_source(baseline, order).encode()
            (sources / f"{source_name}.c").write_bytes(encoded)
            source_hashes[source_name] = sha256_bytes(encoded)
        manifest = {
            "base_flags": BASE_FLAGS,
            "profiles": PROFILES,
            "sources": sorted(source_hashes),
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
        command = [
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
            f"{sources}:/input:ro",
            "--volume",
            f"{temporary}:/config:ro",
            "--volume",
            f"{artifacts}:/output",
            "--volume",
            f"{repository}:/repository:ro",
            IMAGE,
            "python3",
            "-c",
            CONTAINER_DRIVER,
        ]
        subprocess.run(command, check=True)
        compiled = json.loads((artifacts / "compile.json").read_text())
        metrics_by_hash: dict[str, dict[str, Any]] = {}
        for report in compiled["reports"].values():
            loop_hash = report["loop_text_sha256"]
            if loop_hash not in metrics_by_hash:
                loop = artifacts / report["loop_artifact"]
                metrics_by_hash[loop_hash] = {
                    model: analyse_loop(args.llvm_mca, loop, model)
                    for model in MODELS
                }
            report["llvm_mca"] = metrics_by_hash[loop_hash]
            report.pop("loop_artifact")

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from loop_audit import (  # pylint: disable=import-outside-toplevel
            audit_main_timing_loop,
            validate_loop_audit,
        )

        top_audits: dict[str, Any] = {}
        for profile in PROFILES:
            binary = artifacts / f"order_2103__{profile}"
            audit = audit_main_timing_loop(binary)
            audit["mode"] = "full-inline-320"
            audit["errors"] = validate_loop_audit(audit, audit["mode"])
            audit["status"] = "PASS" if not audit["errors"] else "FAIL"
            top_audits[profile] = audit

    rankings: dict[str, list[dict[str, Any]]] = {}
    for profile in PROFILES:
        rows = [
            {
                "source": report["source"],
                "cycles_per_iteration": report["llvm_mca"]["alderlake"][
                    "cycles_per_iteration"
                ],
                "block_rthroughput": report["llvm_mca"]["alderlake"][
                    "block_rthroughput"
                ],
                "loop_text_sha256": report["loop_text_sha256"],
            }
            for report in compiled["reports"].values()
            if report["profile"] == profile
        ]
        rankings[profile] = sorted(
            rows, key=lambda row: (row["cycles_per_iteration"], row["source"])
        )

    verification = compiled["verification"]
    checks = {
        "pinned_image_digest_is_expected": IMAGE.endswith(IMAGE_DIGEST),
        "local_image_id_matches_digest": image_id == f"sha256:{IMAGE_DIGEST}",
        "compiler_is_exact_gcc_13_3_0": compiled["compiler"] == "gcc (GCC) 13.3.0",
        "baseline_source_hash_is_expected": sha256_file(baseline_path)
        == EXPECTED_BASE_SHA256,
        "generated_top_matches_checked_in_source": generated_top == top_path.read_bytes(),
        "top_source_hash_is_expected": sha256_file(top_path) == EXPECTED_TOP_SHA256,
        "screened_all_24_orders_in_3_profiles": len(compiled["reports"]) == 72,
        "top_is_static_best_for_generic": rankings["generic"][0]["source"]
        == "order_2103",
        "top_is_static_best_for_alderlake": rankings["alderlake"][0]["source"]
        == "order_2103",
        "top_random_state_and_constants_verifier_passed": (
            verification["returncode"] == 0
            and verification["stderr"] == ""
            and verification["stdout"] == EXPECTED_VERIFIER_STDOUT
        ),
        "top_full_inline_audits_passed": all(
            audit["status"] == "PASS" for audit in top_audits.values()
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(
            "source-order screen checks failed: "
            + ", ".join(name for name, passed in checks.items() if not passed)
        )
    return {
        "schema_version": 1,
        "experiment": "challenge_gcc133_source_chain_order_screen",
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
            "models": list(MODELS),
            "iterations": 100,
            "qualification": "static screen only; not Intel Core Ultra 7 255H timing",
        },
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "baseline": {
            "path": "submissions/02/contest.c",
            "sha256": sha256_file(baseline_path),
            "order": [0, 1, 2, 3],
        },
        "top_candidate": {
            "path": "submissions/02/src/optimization/contest_source_order_2103.c",
            "sha256": sha256_file(top_path),
            "order": list(TOP_ORDER),
            "semantic_change": "none; four independent assignments commute",
            "adoption": "deferred pending independent measurements on the 255H target",
        },
        "base_flags": BASE_FLAGS,
        "profiles": PROFILES,
        "source_hashes": source_hashes,
        "rankings": rankings,
        "reports": compiled["reports"],
        "top_correctness_gate": verification,
        "top_full_inline_audits": top_audits,
        "checks": checks,
        "all_checks_passed": True,
        "notes": [
            "The 24 source variants differ only in the order of four independent two-round chain assignments.",
            "Constant and state declaration-order probes were byte-identical to the baseline in all three profiles and are not retained as candidates.",
            "LLVM-MCA's Alder Lake and Tremont models are filters, not Lion Cove or Skymont measurements.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", default="docker")
    parser.add_argument("--llvm-mca", default="llvm-mca-16")
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(__file__).with_name("gcc133_source_order_results.json"),
    )
    args = parser.parse_args()
    result = run_screen(args)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        "top=order_2103 "
        f"generic={result['rankings']['generic'][0]['cycles_per_iteration']:.2f} "
        f"alderlake={result['rankings']['alderlake'][0]['cycles_per_iteration']:.2f} "
        "correctness=PASS audit=PASS adoption=DEFERRED_255H"
    )
    print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
