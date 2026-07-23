#!/usr/bin/env python3
"""Safely select challenge 2 builds on an Intel Core Ultra 7 255H.

This is an orchestration layer around ``benchmark_02_permutation.py``.  It
never changes governors, turbo settings, CPU online state, or affinity of the
calling process.  Each benchmark child pins itself through its existing
``--cpu`` interface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import re
import secrets
import shlex
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT = Path(__file__).resolve()
REPOSITORY = SCRIPT.parents[2]
BENCHMARK = REPOSITORY / "solutions" / "benchmark_02_permutation.py"
LOOP_AUDIT = REPOSITORY / "solutions" / "challenge02_loop_audit.py"
REFERENCE_ORACLE = REPOSITORY / "solutions" / "solve_02_permutation.c"
CANDIDATE_VERIFIER = SCRIPT.with_name("verify_contest_candidate_02.c")
PROBLEM_ARCHIVE = REPOSITORY / "problems" / "2_암호구현.zip"
DEFAULT_MANIFEST = SCRIPT.with_name("autotune_02_candidates.json")
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
AUDIT_MODE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
EXPECTED_GCC_VERSION = "13.3.0"
BOOTSTRAP_RESAMPLES = 50_000
MIN_CONFIRM_ITERATIONS = 5_000_000
MIN_CONFIRM_WARMUPS = 6
MIN_CONFIRM_SAMPLES = 40
MIN_RANDOM_CASES = 100_000
BENCHMARK_SCHEMA_VERSION = 5
MIN_CHILD_CPU_COVERAGE_ITERATIONS = 1_000_000
MIN_MEDIAN_CHILD_CPU_COVERAGE = 0.65
MAX_MEDIAN_CHILD_CPU_COVERAGE = 1.05
STATIONARITY_MIN_SAMPLES = 16
STATIONARITY_BLOCK_COUNT = 4
STATIONARITY_MAX_ABSOLUTE_SPREAD = 0.05
STATIONARITY_MAX_EFFECT_SPREAD = 0.02
STATIONARITY_EFFECT_SIGN_MARGIN = 0.005
P_MEDIAN_THRESHOLD = 1.010
P_LOWER_THRESHOLD = 1.005
SAFE_MEDIAN_THRESHOLD = 0.995
SAFE_LOWER_THRESHOLD = 0.990


class AutotuneError(RuntimeError):
    """A user-visible validation or campaign error."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def measurement_protocol_provenance() -> dict[str, Any]:
    objdump_path = Path(shutil.which("objdump") or "objdump")
    size_path = Path(shutil.which("size") or "size")
    protocol_paths = {
        "autotune_driver": SCRIPT,
        "benchmark_driver": BENCHMARK,
        "loop_audit": LOOP_AUDIT,
        "reference_oracle": REFERENCE_ORACLE,
        "candidate_verifier": CANDIDATE_VERIFIER,
        "problem_archive": PROBLEM_ARCHIVE,
        "objdump_executable": objdump_path,
        "size_executable": size_path,
    }
    files: dict[str, dict[str, str]] = {}
    for name, path in protocol_paths.items():
        resolved = path.resolve()
        if not resolved.is_file():
            raise AutotuneError(f"measurement protocol file is missing: {resolved}")
        try:
            serialized_path = str(resolved.relative_to(REPOSITORY))
        except ValueError:
            serialized_path = str(resolved)
        files[name] = {
            "path": serialized_path,
            "sha256": sha256_file(resolved),
        }
    python_executable = Path(sys.executable).resolve()
    if not python_executable.is_file():
        raise AutotuneError(
            f"Python executable cannot be fingerprinted: {python_executable}"
        )
    payload = {
        "schema_version": 1,
        "files": files,
        "python": {
            "implementation": platform.python_implementation(),
            "version": platform.python_version(),
            "executable": str(python_executable),
            "executable_sha256": sha256_file(python_executable),
        },
    }
    return {**payload, "fingerprint_sha256": canonical_hash(payload)}


def validated_protocol_fingerprint(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    claimed = value.get("fingerprint_sha256")
    if not isinstance(claimed, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", claimed
    ):
        return None
    payload = {
        key: item for key, item in value.items() if key != "fingerprint_sha256"
    }
    actual = canonical_hash(payload)
    return claimed.lower() if claimed.lower() == actual else None


def atomic_write_json(path: Path, value: object) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def read_json(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AutotuneError(f"cannot read {description} {path}: {error}") from error
    if not isinstance(value, dict):
        raise AutotuneError(f"{description} must contain a JSON object: {path}")
    return value


def read_optional_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def parse_cpu_list(text: str | None) -> set[int]:
    if not text:
        return set()
    cpus: set[int] = set()
    for part in text.strip().split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first_text, last_text = part.split("-", 1)
            try:
                first = int(first_text)
                last = int(last_text)
            except ValueError as error:
                raise AutotuneError(f"invalid CPU range {part!r}") from error
            if first < 0 or last < first:
                raise AutotuneError(f"invalid CPU range {part!r}")
            cpus.update(range(first, last + 1))
        else:
            try:
                cpu = int(part)
            except ValueError as error:
                raise AutotuneError(f"invalid CPU number {part!r}") from error
            if cpu < 0:
                raise AutotuneError(f"invalid CPU number {part!r}")
            cpus.add(cpu)
    return cpus


def format_cpu_list(cpus: Iterable[int]) -> str:
    ordered = sorted(set(cpus))
    if not ordered:
        return ""
    ranges: list[str] = []
    first = previous = ordered[0]
    for cpu in ordered[1:]:
        if cpu == previous + 1:
            previous = cpu
            continue
        ranges.append(str(first) if first == previous else f"{first}-{previous}")
        first = previous = cpu
    ranges.append(str(first) if first == previous else f"{first}-{previous}")
    return ",".join(ranges)


def run_text(command: Sequence[str]) -> str:
    try:
        completed = subprocess.run(
            list(command),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        stderr = getattr(error, "stderr", "")
        detail = f": {stderr.strip()}" if stderr else ""
        raise AutotuneError(f"command failed: {shlex.join(command)}{detail}") from error
    return completed.stdout.strip()


def compiler_fingerprint(compiler: str) -> dict[str, Any]:
    located = shutil.which(compiler)
    compiler_path = Path(located or compiler).expanduser()
    if not compiler_path.is_file():
        raise AutotuneError(f"compiler does not exist: {compiler}")
    compiler_path = compiler_path.resolve()
    first_line = run_text([str(compiler_path), "--version"]).splitlines()[0]
    full_version = run_text(
        [str(compiler_path), "-dumpfullversion", "-dumpversion"]
    ).splitlines()[0]
    fingerprint: dict[str, Any] = {
        "requested": compiler,
        "path": str(compiler_path),
        "sha256": sha256_file(compiler_path),
        "version_line": first_line,
        "full_version": full_version,
        "dumpmachine": run_text([str(compiler_path), "-dumpmachine"]),
        "matches_expected_13_3_0": full_version == EXPECTED_GCC_VERSION,
    }
    fingerprint["fingerprint_sha256"] = canonical_hash(
        {
            key: fingerprint[key]
            for key in (
                "path",
                "sha256",
                "version_line",
                "full_version",
                "dumpmachine",
            )
        }
    )
    return fingerprint


def validated_compiler_fingerprint(
    value: object, *, require_expected_version: bool
) -> str | None:
    if not isinstance(value, dict):
        return None
    required_strings = (
        "path",
        "sha256",
        "version_line",
        "full_version",
        "dumpmachine",
        "fingerprint_sha256",
    )
    if any(not isinstance(value.get(key), str) for key in required_strings):
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        return None
    claimed = value["fingerprint_sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", claimed):
        return None
    actual = canonical_hash(
        {
            key: value[key]
            for key in (
                "path",
                "sha256",
                "version_line",
                "full_version",
                "dumpmachine",
            )
        }
    )
    expected_match = value["full_version"] == EXPECTED_GCC_VERSION
    if value.get("matches_expected_13_3_0") is not expected_match:
        return None
    if require_expected_version and not expected_match:
        return None
    return claimed if claimed == actual else None


def validate_cflag(flag: object, candidate_name: str) -> str:
    if not isinstance(flag, str) or not flag or flag != flag.strip():
        raise AutotuneError(f"{candidate_name}: each cflag must be a nonempty token")
    if "\x00" in flag or "\n" in flag or "\r" in flag:
        raise AutotuneError(f"{candidate_name}: invalid control character in cflag")
    if not flag.startswith("-"):
        raise AutotuneError(
            f"{candidate_name}: source/object arguments are not allowed in cflags: {flag}"
        )
    forbidden_exact = {
        "-c",
        "-S",
        "-E",
        "-o",
        "-x",
        "-include",
        "-imacros",
        "-wrapper",
        "-save-temps",
    }
    forbidden_prefixes = (
        "-o",
        "-specs=",
        "-fplugin",
        "-wrapper=",
        "-B",
        "-save-temps=",
        "-dump",
        "-fdump",
        "-MJ",
        "-MF",
    )
    if flag in forbidden_exact or flag.startswith("@") or flag.startswith(
        forbidden_prefixes
    ):
        raise AutotuneError(
            f"{candidate_name}: build-control cflag is not allowed: {flag}"
        )
    return flag


def load_manifest(path: Path) -> dict[str, Any]:
    path = path.resolve()
    raw = read_json(path, "candidate manifest")
    if raw.get("schema_version") != 1:
        raise AutotuneError("candidate manifest schema_version must be 1")
    unknown_top = set(raw) - {
        "schema_version",
        "baseline",
        "common_cflags",
        "candidates",
        "description",
    }
    if unknown_top:
        raise AutotuneError(f"unknown manifest fields: {sorted(unknown_top)}")
    common = raw.get("common_cflags", [])
    if not isinstance(common, list):
        raise AutotuneError("manifest common_cflags must be an array")
    common_flags = [validate_cflag(flag, "common_cflags") for flag in common]
    raw_candidates = raw.get("candidates")
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 2:
        raise AutotuneError("manifest must define at least two candidates")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_candidate_fields = {
        "name",
        "source",
        "cflags",
        "submission_eligible",
        "target_only",
        "role",
        "expected_audit",
        "edit_scope_reviewed",
    }
    for position, value in enumerate(raw_candidates):
        if not isinstance(value, dict):
            raise AutotuneError(f"candidate {position} must be an object")
        unknown = set(value) - allowed_candidate_fields
        if unknown:
            raise AutotuneError(
                f"candidate {position} has unknown fields: {sorted(unknown)}"
            )
        name = value.get("name")
        if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
            raise AutotuneError(f"invalid candidate name: {name!r}")
        if name in seen:
            raise AutotuneError(f"duplicate candidate name: {name}")
        seen.add(name)
        source_text = value.get("source")
        if not isinstance(source_text, str) or not source_text:
            raise AutotuneError(f"{name}: source must be a nonempty path")
        source = Path(source_text).expanduser()
        if not source.is_absolute():
            source = REPOSITORY / source
        source = source.resolve()
        if not source.is_file():
            raise AutotuneError(f"{name}: source does not exist: {source}")
        cflags = value.get("cflags", [])
        if not isinstance(cflags, list):
            raise AutotuneError(f"{name}: cflags must be an array")
        audit = value.get("expected_audit")
        if not isinstance(audit, dict) or set(audit) != {"mode"}:
            raise AutotuneError(
                f"{name}: expected_audit must contain exactly a mode field"
            )
        mode = audit.get("mode")
        if not isinstance(mode, str) or not AUDIT_MODE_PATTERN.fullmatch(mode):
            raise AutotuneError(f"{name}: invalid audit mode: {mode!r}")
        eligible = value.get("submission_eligible", False)
        target_only = value.get("target_only", False)
        edit_scope_reviewed = value.get("edit_scope_reviewed", False)
        role = value.get("role", "candidate")
        if not all(
            isinstance(item, bool)
            for item in (eligible, target_only, edit_scope_reviewed)
        ):
            raise AutotuneError(f"{name}: eligibility fields must be booleans")
        if eligible and not edit_scope_reviewed:
            raise AutotuneError(
                f"{name}: submission-eligible candidates require edit_scope_reviewed=true"
            )
        if not isinstance(role, str) or not role:
            raise AutotuneError(f"{name}: role must be a nonempty string")
        if not source.is_relative_to(REPOSITORY) and not target_only:
            raise AutotuneError(
                f"{name}: out-of-repository sources must be marked target_only=true"
            )
        candidates.append(
            {
                "name": name,
                "source": str(source),
                "source_manifest_value": source_text,
                "source_sha256": sha256_file(source),
                "cflags": [validate_cflag(flag, name) for flag in cflags],
                "submission_eligible": eligible,
                "target_only": target_only,
                "edit_scope_reviewed": edit_scope_reviewed,
                "role": role,
                "audit_mode": mode,
            }
        )
    baseline = raw.get("baseline")
    if not isinstance(baseline, str) or baseline not in seen:
        raise AutotuneError("manifest baseline must name a defined candidate")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "baseline": baseline,
        "common_cflags": common_flags,
        "candidates": candidates,
    }


def parse_proc_cpuinfo() -> dict[int, dict[str, str]]:
    text = read_optional_text(Path("/proc/cpuinfo")) or ""
    result: dict[int, dict[str, str]] = {}
    for section in text.split("\n\n"):
        fields: dict[str, str] = {}
        for line in section.splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key.strip().lower()] = value.strip()
        try:
            cpu = int(fields["processor"])
        except (KeyError, ValueError):
            continue
        result[cpu] = fields
    return result


CPUID_HELPER_SOURCE = r"""
#define _GNU_SOURCE
#include <errno.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <cpuid.h>

int main(int argc, char **argv) {
    if (argc != 2) return 64;
    char *end = NULL;
    errno = 0;
    long requested = strtol(argv[1], &end, 10);
    if (errno || !end || *end || requested < 0 || requested >= CPU_SETSIZE) return 64;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET((int)requested, &set);
    if (sched_setaffinity(0, sizeof(set), &set) != 0) {
        perror("sched_setaffinity");
        return 65;
    }
    unsigned int eax0 = 0, ebx0 = 0, ecx0 = 0, edx0 = 0;
    unsigned int eax1 = 0, ebx1 = 0, ecx1 = 0, edx1 = 0;
    unsigned int eax7 = 0, ebx7 = 0, ecx7 = 0, edx7 = 0;
    unsigned int eax1a = 0, ebx1a = 0, ecx1a = 0, edx1a = 0;
    unsigned int max_basic = __get_cpuid_max(0, NULL);
    __cpuid(0, eax0, ebx0, ecx0, edx0);
    if (max_basic >= 1) __cpuid(1, eax1, ebx1, ecx1, edx1);
    if (max_basic >= 7) __cpuid_count(7, 0, eax7, ebx7, ecx7, edx7);
    if (max_basic >= 0x1a) __cpuid_count(0x1a, 0, eax1a, ebx1a, ecx1a, edx1a);
    char vendor[13];
    memcpy(vendor + 0, &ebx0, 4);
    memcpy(vendor + 4, &edx0, 4);
    memcpy(vendor + 8, &ecx0, 4);
    vendor[12] = '\0';
    printf("{\"requested_cpu\":%ld,\"actual_cpu\":%d,"
           "\"vendor\":\"%s\",\"max_basic\":%u,"
           "\"leaf1_eax\":%u,\"leaf7_ebx\":%u,\"leaf7_edx\":%u,"
           "\"has_leaf1a\":%s,\"leaf1a_eax\":%u,"
           "\"hybrid\":%s,\"bmi2\":%s,\"avx2\":%s}\n",
           requested, sched_getcpu(), vendor, max_basic, eax1, ebx7, edx7,
           max_basic >= 0x1a ? "true" : "false", eax1a,
           (edx7 & (1U << 15)) ? "true" : "false",
           (ebx7 & (1U << 8)) ? "true" : "false",
           (ebx7 & (1U << 5)) ? "true" : "false");
    return 0;
}
"""


def pinned_cpuid_probe(
    compiler: dict[str, Any], cpus: Sequence[int]
) -> tuple[dict[int, dict[str, Any]], list[str]]:
    reports: dict[int, dict[str, Any]] = {}
    errors: list[str] = []
    if platform.machine().lower() not in {"x86_64", "amd64", "i386", "i686"}:
        return reports, ["CPUID helper is available only on x86"]
    with tempfile.TemporaryDirectory(prefix="challenge02-cpuid-") as directory:
        temporary = Path(directory)
        source = temporary / "cpuid_probe.c"
        binary = temporary / "cpuid_probe"
        source.write_text(CPUID_HELPER_SOURCE, encoding="utf-8")
        command = [
            str(compiler["path"]),
            "-O2",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ]
        try:
            run_text(command)
        except AutotuneError as error:
            return reports, [str(error)]
        for cpu in cpus:
            try:
                report = json.loads(run_text([str(binary), str(cpu)]))
                if report.get("actual_cpu") != cpu:
                    raise AutotuneError(
                        f"CPUID helper requested CPU {cpu} but ran on "
                        f"{report.get('actual_cpu')}"
                    )
                eax1a = int(report.get("leaf1a_eax", 0))
                report["core_type"] = (eax1a >> 24) & 0xFF
                report["core_type_hex"] = f"0x{report['core_type']:02x}"
                report["native_model_id"] = eax1a & 0x00FF_FFFF
                reports[cpu] = report
            except (AutotuneError, json.JSONDecodeError, TypeError, ValueError) as error:
                errors.append(f"CPU {cpu}: {error}")
    return reports, errors


def sysfs_cpu_record(
    cpu: int, proc_fields: dict[str, str], cpuid: dict[str, Any] | None
) -> dict[str, Any]:
    root = Path(f"/sys/devices/system/cpu/cpu{cpu}")
    topology_root = root / "topology"
    topology: dict[str, Any] = {}
    for name in (
        "physical_package_id",
        "die_id",
        "core_id",
        "cluster_id",
        "thread_siblings_list",
        "core_cpus_list",
        "die_cpus_list",
    ):
        value = read_optional_text(topology_root / name)
        if value is not None:
            try:
                topology[name] = int(value)
            except ValueError:
                topology[name] = value
    frequency: dict[str, Any] = {}
    for name in (
        "cpuinfo_max_freq",
        "cpuinfo_min_freq",
        "base_frequency",
        "scaling_max_freq",
        "scaling_min_freq",
        "scaling_cur_freq",
        "scaling_governor",
        "energy_performance_preference",
    ):
        value = read_optional_text(root / "cpufreq" / name)
        if value is not None:
            try:
                frequency[name] = int(value)
            except ValueError:
                frequency[name] = value
    caches: list[dict[str, Any]] = []
    cache_root = root / "cache"
    if cache_root.is_dir():
        for index in sorted(cache_root.glob("index*")):
            cache: dict[str, Any] = {"index": index.name}
            for name in ("id", "level", "type", "size", "shared_cpu_list"):
                value = read_optional_text(index / name)
                if value is not None:
                    try:
                        cache[name] = int(value)
                    except ValueError:
                        cache[name] = value
            caches.append(cache)
    capacity = read_optional_text(root / "cpu_capacity")
    return {
        "cpu": cpu,
        "proc_cpuinfo": {
            key: proc_fields[key]
            for key in (
                "vendor_id",
                "model name",
                "cpu family",
                "model",
                "stepping",
                "microcode",
            )
            if key in proc_fields
        },
        "cpuid": cpuid,
        "topology": topology,
        "cpufreq": frequency,
        "cpu_capacity": int(capacity) if capacity and capacity.isdigit() else capacity,
        "caches": caches,
    }


def physical_core_key(record: dict[str, Any]) -> tuple[object, ...]:
    topology = record.get("topology", {})
    values = tuple(
        topology.get(name)
        for name in ("physical_package_id", "die_id", "core_id")
    )
    if all(value is not None for value in values):
        return values
    return ("logical", record["cpu"])


def classify_cores(
    records: dict[int, dict[str, Any]],
    allowed: set[int],
    overrides: dict[str, set[int] | None],
) -> tuple[dict[str, Any], dict[str, Any]]:
    known_p = {
        cpu
        for cpu, record in records.items()
        if (record.get("cpuid") or {}).get("vendor") == "GenuineIntel"
        and (record.get("cpuid") or {}).get("core_type") == 0x40
    }
    atoms = {
        cpu
        for cpu, record in records.items()
        if (record.get("cpuid") or {}).get("vendor") == "GenuineIntel"
        and (record.get("cpuid") or {}).get("core_type") == 0x20
    }
    unknown = allowed - known_p - atoms
    model_names = {
        record.get("proc_cpuinfo", {}).get("model name", "")
        for record in records.values()
    }
    model_match = bool(model_names) and all(
        bool(name.strip())
        and "255h" in name.lower()
        and "core" in name.lower()
        and "ultra 7" in name.lower()
        for name in model_names
    )
    physical_p = {physical_core_key(records[cpu]) for cpu in known_p}
    physical_atom = {physical_core_key(records[cpu]) for cpu in atoms}
    signature_match = (
        model_match
        and len(allowed) == 16
        and len(physical_p) == 6
        and len(physical_atom) == 10
        and len({physical_core_key(record) for record in records.values()}) == 16
    )
    uniform_target_features = all(
        (record.get("cpuid") or {}).get("vendor") == "GenuineIntel"
        and (record.get("cpuid") or {}).get("hybrid") is True
        and (record.get("cpuid") or {}).get("bmi2") is True
        and (record.get("cpuid") or {}).get("avx2") is True
        and (record.get("cpuid") or {}).get("has_leaf1a") is True
        for record in records.values()
    )
    reasons: list[str] = []
    signals: dict[str, list[int]] = {}

    explicit = any(value is not None for value in overrides.values())
    if explicit:
        p = set(overrides["p"] if overrides["p"] is not None else known_p)
        explicit_e = overrides["e"]
        explicit_lp = overrides["lp_e"]
        if explicit_e is None and explicit_lp is None:
            e: set[int] = set()
            lp_e: set[int] = set()
        elif explicit_e is None:
            lp_e = set(explicit_lp or set())
            e = atoms - lp_e
        elif explicit_lp is None:
            e = set(explicit_e)
            lp_e = atoms - e
        else:
            e = set(explicit_e)
            lp_e = set(explicit_lp)
        groups = {"p": p, "e": e, "lp_e": lp_e}
        flattened: set[int] = set()
        for name, cpus in groups.items():
            unavailable = cpus - allowed
            if unavailable:
                raise AutotuneError(
                    f"explicit {name} CPUs are not allowed/online: "
                    f"{format_cpu_list(unavailable)}"
                )
            overlap = flattened & cpus
            if overlap:
                raise AutotuneError(
                    f"explicit core groups overlap: {format_cpu_list(overlap)}"
                )
            flattened.update(cpus)
        p_mismatch = p & atoms
        atom_mismatch = (e | lp_e) & known_p
        if p_mismatch or atom_mismatch:
            raise AutotuneError(
                "explicit core types conflict with pinned CPUID: "
                f"p-as-atom={format_cpu_list(p_mismatch)} "
                f"atom-as-p={format_cpu_list(atom_mismatch)}"
            )
        unverified = flattened & unknown
        if unverified:
            reasons.append(
                "explicit mapping could not be cross-checked by CPUID for CPUs "
                + format_cpu_list(unverified)
            )
        method = "explicit"
        confidence = "explicit" if not unverified else "explicit-unverified"
    else:
        p = set(known_p)
        e = set()
        lp_e = set()
        votes: Counter[tuple[int, ...]] = Counter()

        def add_partition_signal(name: str, values: dict[int, object]) -> None:
            groups: defaultdict[object, set[int]] = defaultdict(set)
            for cpu, value in values.items():
                if value is not None and value != 65535:
                    groups[value].add(cpu)
            candidates = [group for group in groups.values() if len(group) == 2]
            if len(candidates) == 1 and len(atoms - candidates[0]) == 8:
                key = tuple(sorted(candidates[0]))
                signals[name] = list(key)
                votes[key] += 1

        add_partition_signal(
            "native_model_id",
            {
                cpu: (records[cpu].get("cpuid") or {}).get("native_model_id")
                for cpu in atoms
            },
        )
        for topology_name in ("die_id", "cluster_id"):
            add_partition_signal(
                topology_name,
                {
                    cpu: records[cpu].get("topology", {}).get(topology_name)
                    for cpu in atoms
                },
            )
        cache_groups: Counter[tuple[int, ...]] = Counter()
        for cpu in atoms:
            for cache in records[cpu].get("caches", []):
                shared = parse_cpu_list(str(cache.get("shared_cpu_list", ""))) & atoms
                if len(shared) == 2:
                    cache_groups[tuple(sorted(shared))] += 1
        if cache_groups:
            top_group, top_count = cache_groups.most_common(1)[0]
            if len(cache_groups) == 1 or top_count > cache_groups.most_common(2)[1][1]:
                signals["cache_fingerprint"] = list(top_group)
                votes[top_group] += 1

        def add_lowest_signal(name: str, values: dict[int, int | None]) -> None:
            if len(values) != 10 or any(value is None for value in values.values()):
                return
            ordered = sorted((int(value), cpu) for cpu, value in values.items())
            low = ordered[:2]
            if ordered[2][0] > max(value for value, _ in low) * 1.05:
                key = tuple(sorted(cpu for _, cpu in low))
                signals[name] = list(key)
                votes[key] += 1

        add_lowest_signal(
            "cpuinfo_max_freq",
            {
                cpu: records[cpu].get("cpufreq", {}).get("cpuinfo_max_freq")
                for cpu in atoms
            },
        )
        add_lowest_signal(
            "cpu_capacity",
            {
                cpu: (
                    records[cpu].get("cpu_capacity")
                    if isinstance(records[cpu].get("cpu_capacity"), int)
                    else None
                )
                for cpu in atoms
            },
        )
        if signature_match and votes:
            ranked = votes.most_common()
            winner, count = ranked[0]
            tied = len(ranked) > 1 and ranked[1][1] == count
            if count >= 2 and not tied:
                lp_e = set(winner)
                e = atoms - lp_e
                confidence = "high"
            else:
                confidence = "ambiguous"
                reasons.append("E/LP-E signals did not identify one 2-core group twice")
        else:
            confidence = "ambiguous"
            if not signature_match:
                reasons.append("the visible CPUs do not match the full 255H signature")
            else:
                reasons.append("no usable E/LP-E topology signals were exposed")
        method = "automatic"

    atom_unknown = atoms - e - lp_e
    if not model_match:
        reasons.append("CPU model name is not Intel Core Ultra 7 255H")
    if not signature_match:
        reasons.append("expected 6 P + 8 E + 2 LP-E physical cores are not all visible")
    if atom_unknown:
        reasons.append("E and LP-E remain ambiguous for " + format_cpu_list(atom_unknown))
    classification = {
        "method": method,
        "confidence": confidence,
        "p": sorted(p),
        "e": sorted(e),
        "lp_e": sorted(lp_e),
        "atom_unknown": sorted(atom_unknown),
        "unknown": sorted(unknown - p - e - lp_e),
        "signals": signals,
        "reasons": list(dict.fromkeys(reasons)),
    }
    hardware_verified = (
        signature_match
        and model_match
        and uniform_target_features
        and len({physical_core_key(records[cpu]) for cpu in p}) == 6
        and len({physical_core_key(records[cpu]) for cpu in e}) == 8
        and len({physical_core_key(records[cpu]) for cpu in lp_e}) == 2
        and not classification["atom_unknown"]
        and not classification["unknown"]
    )
    target = {
        "model_match": model_match,
        "signature_match": signature_match,
        "hardware_verified": hardware_verified,
        "uniform_intel_hybrid_bmi2_avx2": uniform_target_features,
        "model_names": sorted(name for name in model_names if name),
        "expected": {"p": 6, "e": 8, "lp_e": 2, "cores": 16, "threads": 16},
    }
    return classification, target


def command_probe(args: argparse.Namespace) -> None:
    if not hasattr(os, "sched_getaffinity"):
        raise AutotuneError("probe requires Linux sched_getaffinity")
    compiler = compiler_fingerprint(args.compiler)
    allowed = set(os.sched_getaffinity(0))
    online = parse_cpu_list(
        read_optional_text(Path("/sys/devices/system/cpu/online"))
    ) or set(allowed)
    present = parse_cpu_list(
        read_optional_text(Path("/sys/devices/system/cpu/present"))
    ) or set(online)
    visible = allowed & online & present
    if not visible:
        raise AutotuneError("no CPUs are simultaneously allowed, online, and present")
    cpuid, cpuid_errors = pinned_cpuid_probe(compiler, sorted(visible))
    proc = parse_proc_cpuinfo()
    records = {
        cpu: sysfs_cpu_record(cpu, proc.get(cpu, {}), cpuid.get(cpu))
        for cpu in sorted(visible)
    }
    overrides = {
        "p": parse_cpu_list(args.p_cpus) if args.p_cpus is not None else None,
        "e": parse_cpu_list(args.e_cpus) if args.e_cpus is not None else None,
        "lp_e": (
            parse_cpu_list(args.lp_e_cpus) if args.lp_e_cpus is not None else None
        ),
    }
    classification, target = classify_cores(records, visible, overrides)
    target_reasons = list(classification["reasons"])
    if cpuid_errors:
        target_reasons.append("one or more pinned CPUID probes failed")
    if not target["uniform_intel_hybrid_bmi2_avx2"]:
        target_reasons.append(
            "not every visible CPU exposed Intel hybrid CPUID, leaf 0x1A, BMI2, and AVX2"
        )
    if not compiler["matches_expected_13_3_0"]:
        target_reasons.append(
            f"compiler is {compiler['full_version']}, expected {EXPECTED_GCC_VERSION}"
        )
    verified = (
        target["hardware_verified"]
        and compiler["matches_expected_13_3_0"]
        and not cpuid_errors
    )
    target["status"] = "verified-255h-gcc13.3" if verified else "provisional"
    target["reasons"] = list(dict.fromkeys(target_reasons))
    report: dict[str, Any] = {
        "schema_version": 1,
        "probe": "challenge02_255h_topology",
        "created_at": utc_now(),
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "node": platform.node(),
            "kernel": platform.release(),
            "boot_id": read_optional_text(Path("/proc/sys/kernel/random/boot_id")),
        },
        "compiler": compiler,
        "measurement_protocol": measurement_protocol_provenance(),
        "cpu_masks": {
            "affinity_allowed": sorted(allowed),
            "online": sorted(online),
            "present": sorted(present),
            "visible": sorted(visible),
        },
        "cpuid_errors": cpuid_errors,
        "cpus": {str(cpu): records[cpu] for cpu in sorted(records)},
        "classification": classification,
        "target": target,
    }
    report["probe_fingerprint_sha256"] = canonical_hash(
        {
            key: report[key]
            for key in (
                "compiler",
                "cpu_masks",
                "cpus",
                "classification",
                "target",
                "cpuid_errors",
            )
        }
    )
    atomic_write_json(args.out, report)
    print(f"target_status={target['status']}")
    print(
        "cores="
        f"p:{format_cpu_list(classification['p']) or '-'} "
        f"e:{format_cpu_list(classification['e']) or '-'} "
        f"lp-e:{format_cpu_list(classification['lp_e']) or '-'} "
        f"atom-unknown:{format_cpu_list(classification['atom_unknown']) or '-'} "
        f"unknown:{format_cpu_list(classification['unknown']) or '-'}"
    )
    for reason in target["reasons"]:
        print(f"warning={reason}")
    print(f"json={args.out.resolve()}")


CORE_TYPE_ALIASES = {
    "p": "p",
    "e": "e",
    "lpe": "lp_e",
    "lp-e": "lp_e",
    "lp_e": "lp_e",
    "atom-unknown": "atom_unknown",
    "atom_unknown": "atom_unknown",
    "unknown": "unknown",
}


def parse_core_types(text: str) -> list[str]:
    result: list[str] = []
    for raw in text.split(","):
        name = CORE_TYPE_ALIASES.get(raw.strip().lower())
        if name is None:
            raise AutotuneError(
                f"unknown core type {raw!r}; choose p,e,lpe,atom-unknown,unknown"
            )
        if name not in result:
            result.append(name)
    if not result:
        raise AutotuneError("at least one core type is required")
    return result


def load_topology(path: Path) -> dict[str, Any]:
    path = path.resolve()
    report = read_json(path, "topology probe")
    if report.get("schema_version") != 1 or report.get("probe") != (
        "challenge02_255h_topology"
    ):
        raise AutotuneError(f"not a challenge 2 topology probe: {path}")
    classification = report.get("classification")
    if not isinstance(classification, dict):
        raise AutotuneError(f"topology probe has no classification: {path}")
    for field in ("target", "compiler", "cpu_masks", "cpus"):
        if not isinstance(report.get(field), dict):
            raise AutotuneError(
                f"topology probe field {field!r} must be an object: {path}"
            )
    if validated_compiler_fingerprint(
        report["compiler"], require_expected_version=False
    ) is None:
        raise AutotuneError(f"topology compiler fingerprint is malformed: {path}")
    target = report["target"]
    if not isinstance(target.get("status"), str) or not isinstance(
        target.get("hardware_verified"), bool
    ):
        raise AutotuneError(f"topology target record is malformed: {path}")
    cpu_masks = report["cpu_masks"]
    for field in ("affinity_allowed", "online", "present", "visible"):
        values = cpu_masks.get(field)
        if not isinstance(values, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise AutotuneError(
                f"topology CPU mask {field!r} is malformed: {path}"
            )
    if not isinstance(report.get("cpuid_errors"), list):
        raise AutotuneError(f"topology CPUID error list is malformed: {path}")
    for group in ("p", "e", "lp_e", "atom_unknown", "unknown"):
        values = classification.get(group)
        if not isinstance(values, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise AutotuneError(
                f"topology classification group {group!r} is malformed: {path}"
            )
    cpu_records = report["cpus"]
    for cpu_text, record in cpu_records.items():
        if not isinstance(cpu_text, str) or not isinstance(record, dict):
            raise AutotuneError(f"topology CPU record is malformed: {path}")
        record_cpu = record.get("cpu")
        if (
            isinstance(record_cpu, bool)
            or not isinstance(record_cpu, int)
            or str(record_cpu) != cpu_text
        ):
            raise AutotuneError(f"topology CPU id is malformed: {path}")
        for field in ("topology", "proc_cpuinfo", "cpufreq"):
            if not isinstance(record.get(field), dict):
                raise AutotuneError(
                    f"topology CPU field {field!r} is malformed: {path}"
                )
        if record.get("cpuid") is not None and not isinstance(
            record.get("cpuid"), dict
        ):
            raise AutotuneError(f"topology CPUID record is malformed: {path}")
        caches = record.get("caches")
        if not isinstance(caches, list):
            raise AutotuneError(f"topology cache record is malformed: {path}")
        for cache_index, cache in enumerate(caches):
            if not isinstance(cache, dict):
                raise AutotuneError(
                    f"topology CPU {cpu_text} cache {cache_index} must be an object: "
                    f"{path}"
                )
    classified_cpus = {
        value
        for group in ("p", "e", "lp_e", "atom_unknown", "unknown")
        for value in classification[group]
    }
    recorded_cpus = {int(value) for value in cpu_records}
    if classified_cpus != recorded_cpus or set(cpu_masks["visible"]) != recorded_cpus:
        raise AutotuneError(
            f"topology classification, visible mask, and CPU records differ: {path}"
        )
    claimed_probe_fingerprint = report.get("probe_fingerprint_sha256")
    if not isinstance(claimed_probe_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", claimed_probe_fingerprint
    ):
        raise AutotuneError(f"topology probe fingerprint is malformed: {path}")
    actual_probe_fingerprint = canonical_hash(
        {
            key: report[key]
            for key in (
                "compiler",
                "cpu_masks",
                "cpus",
                "classification",
                "target",
                "cpuid_errors",
            )
        }
    )
    if claimed_probe_fingerprint != actual_probe_fingerprint:
        raise AutotuneError(f"topology probe fingerprint does not match: {path}")
    probe_protocol = validated_protocol_fingerprint(
        report.get("measurement_protocol")
    )
    current_protocol = measurement_protocol_provenance()
    if probe_protocol is None:
        raise AutotuneError(
            f"topology probe has no valid measurement protocol; rerun probe: {path}"
        )
    if probe_protocol != current_protocol["fingerprint_sha256"]:
        raise AutotuneError(
            f"measurement protocol changed after topology probe; rerun probe: {path}"
        )
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "report": report,
    }


def current_environment(cpu: int | None = None) -> dict[str, Any]:
    allowed = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    environment: dict[str, Any] = {
        "captured_at": utc_now(),
        "boot_id": read_optional_text(Path("/proc/sys/kernel/random/boot_id")),
        "kernel": platform.release(),
        "affinity_allowed": allowed,
        "online": sorted(
            parse_cpu_list(read_optional_text(Path("/sys/devices/system/cpu/online")))
        ),
        "loadavg": read_optional_text(Path("/proc/loadavg")),
        "intel_pstate_status": read_optional_text(
            Path("/sys/devices/system/cpu/intel_pstate/status")
        ),
        "intel_pstate_no_turbo": read_optional_text(
            Path("/sys/devices/system/cpu/intel_pstate/no_turbo")
        ),
    }
    if cpu is not None:
        root = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
        environment["selected_cpu"] = cpu
        environment["selected_cpu_frequency"] = {
            name: read_optional_text(root / name)
            for name in (
                "cpuinfo_max_freq",
                "base_frequency",
                "scaling_min_freq",
                "scaling_max_freq",
                "scaling_governor",
                "energy_performance_preference",
            )
        }
    return environment


def stable_environment_view(environment: dict[str, Any]) -> dict[str, Any]:
    frequency = environment.get("selected_cpu_frequency", {})
    return {
        "boot_id": environment.get("boot_id"),
        "kernel": environment.get("kernel"),
        "affinity_allowed": environment.get("affinity_allowed"),
        "online": environment.get("online"),
        "intel_pstate_status": environment.get("intel_pstate_status"),
        "intel_pstate_no_turbo": environment.get("intel_pstate_no_turbo"),
        "selected_cpu": environment.get("selected_cpu"),
        "selected_cpu_frequency": {
            key: frequency.get(key)
            for key in (
                "cpuinfo_max_freq",
                "base_frequency",
                "scaling_min_freq",
                "scaling_max_freq",
                "scaling_governor",
                "energy_performance_preference",
            )
        },
    }


def topology_record(topology: dict[str, Any], cpu: int) -> dict[str, Any]:
    value = topology["report"].get("cpus", {}).get(str(cpu))
    if not isinstance(value, dict):
        raise AutotuneError(f"topology has no record for CPU {cpu}")
    return value


def select_representatives(
    topology: dict[str, Any], core_type: str, count: int
) -> list[int]:
    classification = topology["report"]["classification"]
    raw = classification.get(core_type, [])
    if not isinstance(raw, list):
        raise AutotuneError(f"invalid topology core group {core_type}")
    unique_physical: dict[tuple[object, ...], int] = {}
    for value in sorted(raw):
        cpu = int(value)
        record = topology_record(topology, cpu)
        unique_physical.setdefault(physical_core_key(record), cpu)
    candidates = list(unique_physical.values())
    if core_type == "e":
        # Spread the first choices across known E-core clusters.
        by_cluster: defaultdict[object, list[int]] = defaultdict(list)
        remainder: list[int] = []
        for cpu in candidates:
            cluster = topology_record(topology, cpu).get("topology", {}).get(
                "cluster_id"
            )
            if cluster is None or cluster == 65535:
                remainder.append(cpu)
            else:
                by_cluster[cluster].append(cpu)
        spread: list[int] = []
        while any(by_cluster.values()):
            for cluster in sorted(by_cluster, key=str):
                if by_cluster[cluster]:
                    spread.append(by_cluster[cluster].pop(0))
        candidates = spread + remainder
    return candidates[:count]


def verify_campaign_preflight(
    topology: dict[str, Any],
    compiler: dict[str, Any],
    allow_provisional: bool,
) -> list[str]:
    reasons: list[str] = []
    report = topology["report"]
    target_status = report.get("target", {}).get("status")
    if target_status != "verified-255h-gcc13.3":
        reasons.append(f"topology target status is {target_status!r}")
    probed_compiler = report.get("compiler", {})
    if probed_compiler.get("fingerprint_sha256") != compiler.get(
        "fingerprint_sha256"
    ):
        reasons.append("campaign compiler differs from the topology probe compiler")
    expected_allowed = report.get("cpu_masks", {}).get("affinity_allowed")
    current_allowed = (
        sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    )
    if expected_allowed != current_allowed:
        reasons.append("current affinity mask differs from the topology probe")
    expected_online = report.get("cpu_masks", {}).get("online")
    current_online = sorted(
        parse_cpu_list(read_optional_text(Path("/sys/devices/system/cpu/online")))
    )
    if expected_online != current_online:
        reasons.append("current online CPU mask differs from the topology probe")
    if not compiler.get("matches_expected_13_3_0"):
        reasons.append(
            f"campaign compiler is {compiler.get('full_version')}, not GCC 13.3.0"
        )
    if reasons and not allow_provisional:
        raise AutotuneError(
            "campaign preflight is provisional; pass --allow-provisional only for "
            "diagnostics: " + "; ".join(reasons)
        )
    return reasons


def resolve_auto_count(value: str, automatic: int, option: str) -> int:
    if value == "auto":
        return automatic
    try:
        parsed = int(value)
    except ValueError as error:
        raise AutotuneError(f"{option} must be 'auto' or an integer") from error
    if parsed <= 0:
        raise AutotuneError(f"{option} must be positive")
    return parsed


def candidate_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {candidate["name"]: candidate for candidate in manifest["candidates"]}


def public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: candidate[key]
        for key in (
            "name",
            "source",
            "source_manifest_value",
            "source_sha256",
            "cflags",
            "submission_eligible",
            "target_only",
            "edit_scope_reviewed",
            "role",
            "audit_mode",
        )
    }


def build_benchmark_command(
    *,
    compiler: dict[str, Any],
    manifest: dict[str, Any],
    selected: Sequence[dict[str, Any]],
    baseline: str,
    cpu: int,
    iterations: int,
    warmups: int,
    samples: int,
    random_cases: int,
    campaign_id: str,
    output_json: Path,
) -> list[str]:
    names = {candidate["name"] for candidate in selected}
    if baseline not in names:
        raise AutotuneError(f"baseline {baseline!r} is not in this campaign")
    if len(selected) < 2:
        raise AutotuneError("a benchmark campaign requires at least two candidates")
    command = [
        sys.executable,
        str(BENCHMARK),
        "--compiler",
        str(compiler["path"]),
        "--cpu",
        str(cpu),
        "--iterations",
        str(iterations),
        "--warmups",
        str(warmups),
        "--samples",
        str(samples),
        "--random-cases",
        str(random_cases),
        "--campaign-id",
        campaign_id,
    ]
    for flag in manifest["common_cflags"]:
        command.append(f"--extra-cflag={flag}")
    for candidate in selected:
        command.extend(
            ["--case", f"{candidate['name']}={candidate['source']}"]
        )
    command.extend(["--baseline", baseline])
    for candidate in selected:
        for flag in candidate["cflags"]:
            command.extend(
                ["--case-cflag", f"{candidate['name']}={flag}"]
            )
        command.extend(
            [
                "--audit-mode",
                f"{candidate['name']}={candidate['audit_mode']}",
            ]
        )
    command.extend(["--json", str(output_json)])
    return command


def stream_subprocess(command: Sequence[str], log_path: Path) -> int:
    if log_path.exists():
        raise AutotuneError(f"refusing to overwrite campaign log: {log_path}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("x", encoding="utf-8") as log:
        log.write(f"$ {shlex.join(command)}\n")
        log.flush()
        try:
            process = subprocess.Popen(
                list(command),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
        except OSError as error:
            raise AutotuneError(f"could not start benchmark: {error}") from error
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        return process.wait()


def run_one_campaign(
    *,
    kind: str,
    session: str,
    core_type: str,
    cpu: int,
    candidate_name: str | None,
    selected: Sequence[dict[str, Any]],
    baseline: str,
    compiler: dict[str, Any],
    manifest: dict[str, Any],
    measurement_protocol: dict[str, Any],
    iterations: int,
    warmups: int,
    samples: int,
    random_cases: int,
    out_dir: Path,
    dry_run: bool,
) -> dict[str, Any]:
    if iterations < MIN_CHILD_CPU_COVERAGE_ITERATIONS:
        raise AutotuneError(
            "autotune timing campaigns require at least "
            f"{MIN_CHILD_CPU_COVERAGE_ITERATIONS} iterations; smaller runs are "
            "diagnostic-only because the child-CPU coverage gate is disabled"
        )
    stem = f"{candidate_name}-" if candidate_name else ""
    stem += f"{core_type.replace('_', '-')}-cpu{cpu}"
    final_json = (out_dir / f"{stem}.json").resolve()
    partial_json = final_json.with_suffix(".json.partial")
    log_path = (out_dir / f"{stem}.log").resolve()
    for path in (final_json, partial_json, log_path):
        if path.exists():
            raise AutotuneError(f"refusing to overwrite campaign artifact: {path}")
    campaign_id = secrets.token_hex(16)
    command = build_benchmark_command(
        compiler=compiler,
        manifest=manifest,
        selected=selected,
        baseline=baseline,
        cpu=cpu,
        iterations=iterations,
        warmups=warmups,
        samples=samples,
        random_cases=random_cases,
        campaign_id=campaign_id,
        output_json=partial_json,
    )
    before = current_environment(cpu)
    print(f"campaign={kind}/{session}/{stem}")
    print("$", shlex.join(command), flush=True)
    campaign: dict[str, Any] = {
        "kind": kind,
        "session": session,
        "campaign_id": campaign_id,
        "core_type": core_type,
        "cpu": cpu,
        "candidate": candidate_name,
        "baseline": baseline,
        "cases": [candidate["name"] for candidate in selected],
        "command": command,
        "environment_before": before,
        "benchmark_json": str(final_json),
        "log": str(log_path),
        "status": "DRY-RUN" if dry_run else "RUNNING",
    }
    if dry_run:
        campaign["environment_after"] = before
        campaign["environment_stable"] = True
        return campaign
    return_code = stream_subprocess(command, log_path)
    after = current_environment(cpu)
    campaign["return_code"] = return_code
    campaign["environment_after"] = after
    campaign["environment_stable"] = (
        stable_environment_view(before) == stable_environment_view(after)
    )
    if return_code != 0:
        campaign["status"] = "FAIL"
        raise AutotuneError(
            f"benchmark failed for {stem} with exit {return_code}; see {log_path}"
        )
    if not partial_json.is_file():
        campaign["status"] = "FAIL"
        raise AutotuneError(f"benchmark produced no JSON for {stem}")
    benchmark = read_json(partial_json, "benchmark result")
    if benchmark.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        raise AutotuneError(
            f"{stem}: benchmark schema must be {BENCHMARK_SCHEMA_VERSION}, got "
            f"{benchmark.get('schema_version')!r}"
        )
    if benchmark.get("baseline") != baseline:
        raise AutotuneError(f"{stem}: benchmark baseline changed unexpectedly")
    if benchmark.get("campaign_id") != campaign_id:
        raise AutotuneError(f"{stem}: benchmark campaign id changed unexpectedly")
    expected_protocol = validated_protocol_fingerprint(measurement_protocol)
    actual_protocol = validated_protocol_fingerprint(
        benchmark.get("measurement_protocol")
    )
    if expected_protocol is None:
        raise AutotuneError(f"{stem}: campaign protocol fingerprint is malformed")
    if actual_protocol != expected_protocol:
        raise AutotuneError(
            f"{stem}: benchmark measurement protocol differs from the campaign index"
        )
    timed_main_errors = timed_main_validation_errors(
        benchmark,
        expected_case_names=[candidate["name"] for candidate in selected],
        expected_baseline=baseline,
        expected_iterations=iterations,
        expected_warmups=warmups,
        expected_samples=samples,
    )
    if timed_main_errors:
        raise AutotuneError(
            f"{stem}: timed-main repeated-call validation failed: "
            + "; ".join(timed_main_errors)
        )
    for candidate in selected:
        name = candidate["name"]
        verifications = benchmark.get("candidate_verification")
        audits = benchmark.get("assembly_audits")
        verification = (
            verifications.get(name) if isinstance(verifications, dict) else None
        )
        audit = audits.get(name) if isinstance(audits, dict) else None
        if not isinstance(verification, dict):
            raise AutotuneError(f"{stem}: correctness record is missing for {name}")
        if not isinstance(audit, dict):
            raise AutotuneError(f"{stem}: assembly record is missing for {name}")
        if verification.get("status") != "PASS":
            raise AutotuneError(f"{stem}: correctness gate did not pass for {name}")
        if verification.get("random_state_and_constants") is not True:
            raise AutotuneError(
                f"{stem}: correctness gate did not vary state and constants for {name}"
            )
        if verification.get("round_counts") != [1, 20]:
            raise AutotuneError(
                f"{stem}: correctness gate did not cover rounds 1 and 20 for {name}"
            )
        if verification.get("verifier_only_flag_overrides") != []:
            raise AutotuneError(
                f"{stem}: verifier object did not use measured flags for {name}"
            )
        if integer_or_zero(verification.get("random_cases")) != random_cases:
            raise AutotuneError(
                f"{stem}: correctness gate case count differs for {name}"
            )
        expected_verifier_flags = [
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
        ]
        if (
            verification.get("verifier_translation_unit_cflags")
            != expected_verifier_flags
        ):
            raise AutotuneError(
                f"{stem}: verifier translation unit flags changed for {name}"
            )
        expected_link_flags = [
            "-O3",
            "-Wall",
            "-Wextra",
            *manifest["common_cflags"],
            *candidate["cflags"],
        ]
        if verification.get("verifier_link_cflags") != expected_link_flags:
            raise AutotuneError(f"{stem}: verifier link flags changed for {name}")
        if audit.get("status") != "PASS":
            raise AutotuneError(f"{stem}: assembly gate did not pass for {name}")
        if audit.get("mode") != candidate["audit_mode"]:
            raise AutotuneError(f"{stem}: assembly mode changed for {name}")
    stationarity = benchmark["timing_stationarity"]
    assert isinstance(stationarity, dict)
    stationarity_eligibility = stationarity["campaign_eligibility"]
    if candidate_name is not None:
        stationarity_comparisons = stationarity["comparisons"]
        assert isinstance(stationarity_comparisons, dict)
        comparison_record = stationarity_comparisons[candidate_name]
        assert isinstance(comparison_record, dict)
        stationarity_eligibility = comparison_record["eligibility"]
    campaign["timing_stationarity_eligibility"] = stationarity_eligibility
    os.replace(partial_json, final_json)
    campaign["benchmark_sha256"] = sha256_file(final_json)
    campaign["status"] = (
        "PASS" if campaign["environment_stable"] else "QUARANTINED"
    )
    return campaign


def initialize_campaign_index(
    *,
    kind: str,
    session: str,
    manifest: dict[str, Any],
    topology: dict[str, Any],
    compiler: dict[str, Any],
    baseline: str,
    selected: Sequence[dict[str, Any]],
    config: dict[str, Any],
    provisional_reasons: Sequence[str],
) -> dict[str, Any]:
    hardware_verified = bool(
        topology["report"].get("target", {}).get("hardware_verified")
    )
    target_verified = hardware_verified and bool(
        compiler.get("matches_expected_13_3_0")
    )
    measurement_protocol = measurement_protocol_provenance()
    return {
        "schema_version": 1,
        "autotune": f"challenge02_255h_{kind}",
        "created_at": utc_now(),
        "status": "RUNNING",
        "session": session,
        "repository": str(REPOSITORY),
        "manifest": {
            "path": manifest["path"],
            "sha256": manifest["sha256"],
            "baseline": manifest["baseline"],
            "common_cflags": manifest["common_cflags"],
        },
        "topology": {
            "path": topology["path"],
            "sha256": topology["sha256"],
            "probe_fingerprint_sha256": topology["report"].get(
                "probe_fingerprint_sha256"
            ),
            "hardware_verified": hardware_verified,
            "probe_target_status": topology["report"].get("target", {}).get(
                "status"
            ),
        },
        "compiler": compiler,
        "measurement_protocol": measurement_protocol,
        "target_verified": target_verified,
        "provisional_reasons": list(provisional_reasons),
        "baseline": baseline,
        "candidates": [public_candidate(candidate) for candidate in selected],
        "config": config,
        "campaigns": [],
        "errors": [],
    }


def campaign_core_plan(
    *,
    topology: dict[str, Any],
    core_types: Sequence[str],
    cores_per_type: int,
    allow_provisional: bool,
) -> tuple[list[tuple[str, int]], list[str]]:
    plan: list[tuple[str, int]] = []
    reasons: list[str] = []
    for core_type in core_types:
        cpus = select_representatives(topology, core_type, cores_per_type)
        if len(cpus) < cores_per_type:
            message = (
                f"core type {core_type} has {len(cpus)} physical representatives; "
                f"requested {cores_per_type}"
            )
            if not allow_provisional:
                raise AutotuneError(message)
            reasons.append(message)
        for cpu in cpus:
            plan.append((core_type, cpu))
    if not plan:
        raise AutotuneError("the selected topology contains no runnable cores")
    return plan, reasons


def ensure_new_index(out_dir: Path) -> tuple[Path, Path]:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.json"
    partial_index = out_dir / "index.partial.json"
    if index_path.exists() or partial_index.exists():
        raise AutotuneError(f"refusing to overwrite campaign index in {out_dir}")
    return index_path, partial_index


def run_campaign_batch(
    *,
    index: dict[str, Any],
    index_path: Path,
    partial_index: Path,
    work: Sequence[dict[str, Any]],
    dry_run: bool,
) -> None:
    atomic_write_json(partial_index, index)
    try:
        for item in work:
            campaign = run_one_campaign(**item, dry_run=dry_run)
            index["campaigns"].append(campaign)
            atomic_write_json(partial_index, index)
    except BaseException as error:
        index["status"] = "FAIL"
        index["errors"].append(str(error))
        index["completed_at"] = utc_now()
        atomic_write_json(partial_index, index)
        raise
    index["status"] = "DRY-RUN" if dry_run else "COMPLETE"
    if any(
        campaign.get("status") == "QUARANTINED" for campaign in index["campaigns"]
    ):
        index["status"] = "QUARANTINED"
    index["completed_at"] = utc_now()
    atomic_write_json(index_path, index)
    partial_index.unlink(missing_ok=True)
    print(f"index={index_path}")


def command_screen(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    topology = load_topology(args.topology)
    compiler_name = args.compiler or str(topology["report"]["compiler"]["path"])
    compiler = compiler_fingerprint(compiler_name)
    preflight_reasons = verify_campaign_preflight(
        topology, compiler, args.allow_provisional or args.dry_run
    )
    core_types = parse_core_types(args.core_types)
    plan, plan_reasons = campaign_core_plan(
        topology=topology,
        core_types=core_types,
        cores_per_type=args.cores_per_type,
        allow_provisional=args.allow_provisional or args.dry_run,
    )
    selected = manifest["candidates"]
    candidate_count = len(selected)
    warmups = resolve_auto_count(
        args.warmups, candidate_count, "--warmups"
    )
    stationarity_period = STATIONARITY_BLOCK_COUNT * candidate_count
    automatic_samples = stationarity_period * max(
        1, math.ceil(STATIONARITY_MIN_SAMPLES / stationarity_period)
    )
    samples = resolve_auto_count(
        args.samples, automatic_samples, "--samples"
    )
    if samples < STATIONARITY_MIN_SAMPLES:
        raise AutotuneError(
            f"--samples must be at least {STATIONARITY_MIN_SAMPLES} for "
            "stationarity validation"
        )
    period = 2 * candidate_count
    if samples % stationarity_period:
        raise AutotuneError(
            "screen samples must be a multiple of four times the candidate "
            f"count ({stationarity_period}) so fixed blocks preserve balanced order"
        )
    index_path, partial_index = ensure_new_index(args.out_dir)
    config = {
        "stage": "screen",
        "core_types": core_types,
        "cores_per_type": args.cores_per_type,
        "iterations": args.iterations,
        "warmups": warmups,
        "samples": samples,
        "random_cases": args.random_cases,
        "order_period": period,
        "dry_run": args.dry_run,
    }
    index = initialize_campaign_index(
        kind="screen",
        session=args.session,
        manifest=manifest,
        topology=topology,
        compiler=compiler,
        baseline=manifest["baseline"],
        selected=selected,
        config=config,
        provisional_reasons=[*preflight_reasons, *plan_reasons],
    )
    work = [
        {
            "kind": "screen",
            "session": args.session,
            "core_type": core_type,
            "cpu": cpu,
            "candidate_name": None,
            "selected": selected,
            "baseline": manifest["baseline"],
            "compiler": compiler,
            "manifest": manifest,
            "measurement_protocol": index["measurement_protocol"],
            "iterations": args.iterations,
            "warmups": warmups,
            "samples": samples,
            "random_cases": args.random_cases,
            "out_dir": args.out_dir.resolve(),
        }
        for core_type, cpu in plan
    ]
    run_campaign_batch(
        index=index,
        index_path=index_path,
        partial_index=partial_index,
        work=work,
        dry_run=args.dry_run,
    )


def load_campaign_index(path: Path, expected_kind: str | None = None) -> dict[str, Any]:
    path = path.resolve()
    index = read_json(path, "campaign index")
    if index.get("schema_version") != 1:
        raise AutotuneError(f"campaign index schema must be 1: {path}")
    kind = str(index.get("autotune", ""))
    if expected_kind and kind != f"challenge02_255h_{expected_kind}":
        raise AutotuneError(f"expected a {expected_kind} index, got {kind!r}: {path}")
    index["_path"] = str(path)
    index["_sha256"] = sha256_file(path)
    return index


def load_index_manifest(
    index: dict[str, Any], override: Path | None
) -> dict[str, Any]:
    stored = index.get("manifest", {})
    if not isinstance(stored, dict):
        raise AutotuneError("campaign index manifest record must be an object")
    path = override.resolve() if override else Path(str(stored.get("path", "")))
    manifest = load_manifest(path)
    expected = stored.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise AutotuneError("campaign index manifest SHA-256 is missing or malformed")
    if manifest["sha256"] != expected:
        raise AutotuneError("candidate manifest changed after the screen campaign")
    return manifest


def load_index_topology(
    index: dict[str, Any], override: Path | None
) -> dict[str, Any]:
    stored = index.get("topology", {})
    if not isinstance(stored, dict):
        raise AutotuneError("campaign index topology record must be an object")
    path = override.resolve() if override else Path(str(stored.get("path", "")))
    topology = load_topology(path)
    expected = stored.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise AutotuneError("campaign index topology SHA-256 is missing or malformed")
    if topology["sha256"] != expected:
        raise AutotuneError("topology probe changed after the screen campaign")
    return topology


def rank_screen_candidates(
    screen: dict[str, Any], manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    baseline = manifest["baseline"]
    candidates = candidate_map(manifest)
    lower_bounds: defaultdict[str, list[float]] = defaultdict(list)
    medians: defaultdict[str, list[float]] = defaultdict(list)
    raw_campaigns = screen.get("campaigns")
    if not isinstance(raw_campaigns, list) or not all(
        isinstance(campaign, dict) for campaign in raw_campaigns
    ):
        raise AutotuneError("screen campaign list is missing or malformed")
    for campaign in raw_campaigns:
        if campaign.get("status") != "PASS":
            continue
        result_path = Path(str(campaign.get("benchmark_json", "")))
        expected_hash = campaign.get("benchmark_sha256")
        if not isinstance(expected_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_hash
        ):
            raise AutotuneError(
                f"screen benchmark artifact SHA-256 is missing: {result_path}"
            )
        if not result_path.is_file() or sha256_file(result_path) != expected_hash:
            raise AutotuneError(f"screen benchmark artifact changed: {result_path}")
        report = read_json(result_path, "screen benchmark")
        if report.get("baseline") != baseline:
            raise AutotuneError(f"screen baseline mismatch in {result_path}")
        screen_config = screen.get("config")
        expected_samples = (
            screen_config.get("samples")
            if isinstance(screen_config, dict)
            else None
        )
        stationarity_errors = timing_stationarity_validation_errors(
            report,
            expected_case_names=list(candidates),
            expected_baseline=baseline,
            expected_samples=expected_samples,
        )
        if stationarity_errors:
            raise AutotuneError(
                f"screen stationarity evidence failed in {result_path}: "
                + "; ".join(stationarity_errors)
            )
        stationarity = report["timing_stationarity"]
        assert isinstance(stationarity, dict)
        stationarity_comparisons = stationarity["comparisons"]
        assert isinstance(stationarity_comparisons, dict)
        comparisons = report.get("comparisons", {})
        if not isinstance(comparisons, dict):
            continue
        for name, comparison in comparisons.items():
            if name not in candidates or not isinstance(comparison, dict):
                continue
            stability = stationarity_comparisons.get(name)
            if (
                not isinstance(stability, dict)
                or stability.get("eligibility") != "eligible"
            ):
                continue
            try:
                lower_bounds[name].append(
                    float(comparison["paired_bootstrap_ci95_low"])
                )
                medians[name].append(float(comparison["paired_median"]))
            except (KeyError, TypeError, ValueError):
                continue
    ranking: list[dict[str, Any]] = []
    for name, values in lower_bounds.items():
        candidate = candidates[name]
        if name == baseline or not candidate["submission_eligible"]:
            continue
        ranking.append(
            {
                "name": name,
                "min_ci95_low": min(values),
                "min_paired_median": min(medians[name]),
                "campaign_count": len(values),
            }
        )
    ranking.sort(
        key=lambda row: (row["min_ci95_low"], row["min_paired_median"]),
        reverse=True,
    )
    return ranking


def command_confirm(args: argparse.Namespace) -> None:
    screen = load_campaign_index(args.screen, "screen")
    if screen.get("status") not in {"COMPLETE", "QUARANTINED", "DRY-RUN"}:
        raise AutotuneError("screen index is incomplete")
    screen_protocol = validated_protocol_fingerprint(
        screen.get("measurement_protocol")
    )
    current_protocol = measurement_protocol_provenance()
    if screen_protocol is None:
        raise AutotuneError(
            "screen measurement protocol is missing or malformed; rerun screen"
        )
    if screen_protocol != current_protocol["fingerprint_sha256"]:
        raise AutotuneError(
            "measurement protocol changed after screen; rerun screen before confirm"
        )
    manifest = load_index_manifest(screen, args.manifest)
    raw_screen_candidates = screen.get("candidates")
    if not isinstance(raw_screen_candidates, list) or not all(
        isinstance(candidate, dict) for candidate in raw_screen_candidates
    ):
        raise AutotuneError("screen candidate list is missing or malformed")
    screened_sources = {
        candidate.get("name"): candidate.get("source_sha256")
        for candidate in raw_screen_candidates
    }
    for candidate in manifest["candidates"]:
        screened_hash = screened_sources.get(candidate["name"])
        if screened_hash != candidate["source_sha256"]:
            raise AutotuneError(
                f"source {candidate['name']} changed after the screen campaign"
            )
    topology = load_index_topology(screen, args.topology)
    screen_compiler = screen.get("compiler")
    if validated_compiler_fingerprint(
        screen_compiler, require_expected_version=False
    ) is None:
        raise AutotuneError("screen compiler record is missing or malformed")
    assert isinstance(screen_compiler, dict)
    stored_compiler_path = screen_compiler.get("path")
    if not isinstance(stored_compiler_path, str) or not stored_compiler_path:
        raise AutotuneError("screen compiler path is missing or malformed")
    compiler_name = args.compiler or stored_compiler_path
    compiler = compiler_fingerprint(compiler_name)
    preflight_reasons = verify_campaign_preflight(
        topology, compiler, args.allow_provisional or args.dry_run
    )
    candidates = candidate_map(manifest)
    incumbent = args.incumbent or manifest["baseline"]
    if incumbent not in candidates:
        raise AutotuneError(f"unknown incumbent: {incumbent}")
    if incumbent != manifest["baseline"]:
        raise AutotuneError(
            "confirm/decide support only the manifest incumbent; run any candidate-to-"
            "candidate head-to-head as a separately reviewed diagnostic"
        )
    selected_names = list(dict.fromkeys(args.candidate))
    ranking: list[dict[str, Any]] = []
    if not selected_names:
        if screen.get("status") == "DRY-RUN":
            raise AutotuneError("dry-run screen has no ranking; pass --candidate")
        ranking = rank_screen_candidates(screen, manifest)
        selected_names = [row["name"] for row in ranking[: args.top]]
    if not selected_names:
        raise AutotuneError("screening produced no eligible confirmation candidates")
    for name in selected_names:
        if name not in candidates:
            raise AutotuneError(f"unknown confirmation candidate: {name}")
        if name == incumbent:
            raise AutotuneError("confirmation candidate cannot equal the incumbent")
    core_types = parse_core_types(args.core_types)
    plan, plan_reasons = campaign_core_plan(
        topology=topology,
        core_types=core_types,
        cores_per_type=args.cores_per_type,
        allow_provisional=args.allow_provisional or args.dry_run,
    )
    confirmation_stationarity_period = STATIONARITY_BLOCK_COUNT * 2
    if (
        args.samples < MIN_CONFIRM_SAMPLES
        or args.samples % confirmation_stationarity_period
    ):
        raise AutotuneError(
            "confirm --samples must be at least "
            f"{MIN_CONFIRM_SAMPLES} and a multiple of "
            f"{confirmation_stationarity_period} so fixed blocks preserve "
            "balanced order"
        )
    index_path, partial_index = ensure_new_index(args.out_dir)
    selected_for_index = [candidates[incumbent], *[candidates[n] for n in selected_names]]
    config = {
        "stage": "confirm",
        "source_screen": {
            "path": screen["_path"],
            "sha256": screen["_sha256"],
        },
        "screen_ranking": ranking,
        "core_types": core_types,
        "cores_per_type": args.cores_per_type,
        "iterations": args.iterations,
        "warmups": args.warmups,
        "samples": args.samples,
        "random_cases": args.random_cases,
        "order_period": 4,
        "dry_run": args.dry_run,
    }
    index = initialize_campaign_index(
        kind="confirm",
        session=args.session,
        manifest=manifest,
        topology=topology,
        compiler=compiler,
        baseline=incumbent,
        selected=selected_for_index,
        config=config,
        provisional_reasons=[*preflight_reasons, *plan_reasons],
    )
    index["selected_candidates"] = selected_names
    work: list[dict[str, Any]] = []
    for name in selected_names:
        pair = [candidates[incumbent], candidates[name]]
        for core_type, cpu in plan:
            work.append(
                {
                    "kind": "confirm",
                    "session": args.session,
                    "core_type": core_type,
                    "cpu": cpu,
                    "candidate_name": name,
                    "selected": pair,
                    "baseline": incumbent,
                    "compiler": compiler,
                    "manifest": manifest,
                    "measurement_protocol": index["measurement_protocol"],
                    "iterations": args.iterations,
                    "warmups": args.warmups,
                    "samples": args.samples,
                    "random_cases": args.random_cases,
                    "out_dir": args.out_dir.resolve(),
                }
            )
    run_campaign_batch(
        index=index,
        index_path=index_path,
        partial_index=partial_index,
        work=work,
        dry_run=args.dry_run,
    )


def audit_signature(audit: dict[str, Any]) -> tuple[object, ...] | None:
    binary_hash = audit.get("binary_sha256")
    if not isinstance(binary_hash, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", binary_hash
    ):
        return None
    loop_hash = audit.get("normalized_loop_sha256")
    if not isinstance(loop_hash, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", loop_hash
    ):
        return None
    counts = audit.get("core_counts")
    if not isinstance(counts, dict):
        return None
    return (
        binary_hash.lower(),
        loop_hash,
        audit.get("loop_start_mod_64"),
        audit.get("loop_bytes"),
        tuple(sorted((str(key), value) for key, value in counts.items())),
    )


def percentile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        raise AutotuneError("cannot take a percentile of an empty sample")
    probability = min(1.0, max(0.0, probability))
    index = int(math.floor(probability * (len(sorted_values) - 1)))
    return float(sorted_values[index])


def integer_or_zero(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def expected_timing_stationarity_evidence(
    samples: dict[str, list[float]], baseline: str
) -> dict[str, object]:
    """Recompute the benchmark's fixed-design stationarity evidence.

    Keep this deliberately simple and predeclared: four chronological blocks,
    practical effect-size limits, and no data-selected split or p-value.  This
    is duplicated at the trust boundary so the autotuner validates raw samples
    instead of trusting candidate-supplied summary fields.
    """

    names = sorted(samples)
    if baseline not in samples:
        raise ValueError("stationarity baseline is absent from raw samples")
    if not names:
        raise ValueError("stationarity analysis requires at least one case")
    lengths = {len(samples[name]) for name in names}
    if len(lengths) != 1:
        raise ValueError("stationarity raw sample lengths differ")
    sample_count = lengths.pop()
    if sample_count == 0:
        raise ValueError("stationarity raw samples are empty")
    for name in names:
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) <= 0.0
            for value in samples[name]
        ):
            raise ValueError(
                f"stationarity raw samples for {name} must be finite and positive"
            )

    block_ranges = [
        {
            "start": block * sample_count // STATIONARITY_BLOCK_COUNT,
            "stop": (block + 1) * sample_count // STATIONARITY_BLOCK_COUNT,
        }
        for block in range(STATIONARITY_BLOCK_COUNT)
    ]
    enough_samples = sample_count >= STATIONARITY_MIN_SAMPLES
    order_balanced = (
        sample_count % (STATIONARITY_BLOCK_COUNT * len(names)) == 0
    )
    preconditions_pass = enough_samples and order_balanced
    precondition_reasons: list[str] = []
    if not enough_samples:
        precondition_reasons.append(
            f"at least {STATIONARITY_MIN_SAMPLES} samples per case are required"
        )
    if not order_balanced:
        precondition_reasons.append(
            "sample count must be a multiple of four times the case count so "
            "each fixed block balances case positions"
        )

    cases: dict[str, dict[str, object]] = {}
    for name in names:
        values = [float(value) for value in samples[name]]
        block_medians = [
            statistics.median(values[block["start"] : block["stop"]])
            for block in block_ranges
        ]
        spread = max(block_medians) / min(block_medians) - 1.0
        reasons: list[str] = []
        if preconditions_pass and spread > STATIONARITY_MAX_ABSOLUTE_SPREAD:
            reasons.append(
                "absolute block-median spread exceeds the fixed 5% limit"
            )
        status = (
            "NOT_ENFORCED"
            if not preconditions_pass
            else ("PASS" if not reasons else "FAIL")
        )
        cases[name] = {
            "block_median_ns": block_medians,
            "max_to_min_ratio_minus_one": spread,
            "status": status,
            "reasons": reasons,
        }

    comparisons: dict[str, dict[str, object]] = {}
    baseline_values = [float(value) for value in samples[baseline]]
    for name in names:
        if name == baseline:
            continue
        candidate_values = [float(value) for value in samples[name]]
        ratios = [
            baseline_value / candidate_value
            for baseline_value, candidate_value in zip(
                baseline_values, candidate_values
            )
        ]
        block_medians = [
            statistics.median(ratios[block["start"] : block["stop"]])
            for block in block_ranges
        ]
        spread = max(block_medians) / min(block_medians) - 1.0
        sign_instability = (
            min(block_medians) < 1.0 - STATIONARITY_EFFECT_SIGN_MARGIN
            and max(block_medians) > 1.0 + STATIONARITY_EFFECT_SIGN_MARGIN
        )
        reasons: list[str] = []
        if preconditions_pass:
            if cases[baseline]["status"] != "PASS":
                reasons.append("baseline absolute timing is nonstationary")
            if cases[name]["status"] != "PASS":
                reasons.append("candidate absolute timing is nonstationary")
            if spread > STATIONARITY_MAX_EFFECT_SPREAD:
                reasons.append(
                    "paired-effect block-median spread exceeds the fixed 2% limit"
                )
            if sign_instability:
                reasons.append(
                    "paired effect crosses both sides of parity by more than 0.5%"
                )
        status = (
            "NOT_ENFORCED"
            if not preconditions_pass
            else ("PASS" if not reasons else "FAIL")
        )
        comparisons[name] = {
            "block_paired_median_ratio": block_medians,
            "max_to_min_ratio_minus_one": spread,
            "material_sign_instability": sign_instability,
            "status": status,
            "eligibility": "eligible" if status == "PASS" else "diagnostic-only",
            "reasons": reasons,
        }

    campaign_reasons = list(precondition_reasons)
    if preconditions_pass and cases[baseline]["status"] != "PASS":
        campaign_reasons.append("baseline absolute timing is nonstationary")
    campaign_status = (
        "NOT_ENFORCED"
        if not preconditions_pass
        else ("PASS" if not campaign_reasons else "FAIL")
    )
    return {
        "schema_version": 1,
        "method": "four-fixed-contiguous-block-medians",
        "baseline": baseline,
        "case_names": names,
        "sample_count_per_case": sample_count,
        "block_ranges": block_ranges,
        "order_period_samples": 2 * len(names),
        "preconditions": {
            "minimum_samples": STATIONARITY_MIN_SAMPLES,
            "sample_count_multiple_of_four_case_count": order_balanced,
            "status": "PASS" if preconditions_pass else "FAIL",
            "reasons": precondition_reasons,
        },
        "thresholds": {
            "max_absolute_block_median_spread": (
                STATIONARITY_MAX_ABSOLUTE_SPREAD
            ),
            "max_paired_effect_block_median_spread": (
                STATIONARITY_MAX_EFFECT_SPREAD
            ),
            "paired_effect_sign_margin": STATIONARITY_EFFECT_SIGN_MARGIN,
        },
        "cases": cases,
        "comparisons": comparisons,
        "status": campaign_status,
        "campaign_eligibility": (
            "eligible" if campaign_status == "PASS" else "diagnostic-only"
        ),
        "reasons": campaign_reasons,
    }


def timing_stationarity_validation_errors(
    report: dict[str, Any],
    *,
    expected_case_names: Sequence[str],
    expected_baseline: str,
    expected_samples: int,
) -> list[str]:
    """Fail closed unless stationarity evidence exactly matches raw samples."""

    names = list(expected_case_names)
    if (
        len(names) != len(set(names))
        or expected_baseline not in names
        or any(not isinstance(name, str) or not name for name in names)
        or not isinstance(expected_samples, int)
        or isinstance(expected_samples, bool)
        or expected_samples <= 0
    ):
        return ["timing stationarity expectations are malformed"]
    raw = report.get("internal_ns_per_20round")
    if not isinstance(raw, dict) or set(raw) != set(names):
        return ["timing stationarity raw case set is missing or malformed"]
    samples: dict[str, list[float]] = {}
    for name in names:
        values = raw.get(name)
        if not isinstance(values, list) or len(values) != expected_samples:
            return [
                f"timing stationarity raw sample count for {name} is not "
                f"{expected_samples}"
            ]
        samples[name] = values
    try:
        expected = expected_timing_stationarity_evidence(
            samples, expected_baseline
        )
    except ValueError as error:
        return [f"timing stationarity raw samples are invalid: {error}"]
    if report.get("timing_stationarity") != expected:
        return [
            "timing stationarity evidence does not match raw samples and the "
            "fixed analysis contract"
        ]
    return []


def timed_main_validation_errors(
    report: dict[str, Any],
    *,
    expected_case_names: Sequence[str],
    expected_baseline: str | None = None,
    expected_iterations: int,
    expected_warmups: int,
    expected_samples: int,
    require_exact_case_set: bool = True,
    check_global: bool = True,
    check_cases: bool = True,
) -> list[str]:
    """Validate schema-5 evidence that every timed process did the real work."""

    errors: list[str] = []
    expected_names = list(expected_case_names)
    expected_name_set = set(expected_names)
    stationarity_baseline = (
        expected_baseline
        if expected_baseline is not None
        else report.get("baseline")
    )
    if len(expected_names) != len(expected_name_set) or any(
        not isinstance(name, str) or not name for name in expected_names
    ):
        return ["timed-main expected case names are malformed or duplicated"]
    if (
        any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (expected_iterations, expected_warmups, expected_samples)
        )
        or expected_iterations <= 0
        or expected_warmups < 0
        or expected_samples <= 0
    ):
        return ["timed-main expected process counts are malformed"]

    def exact_integer(value: object, expected: int) -> bool:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value == expected
        )

    def state_words(value: object) -> list[str] | None:
        if not isinstance(value, list) or len(value) != 4:
            return None
        if not all(
            isinstance(word, str) and re.fullmatch(r"[0-9a-f]{16}", word)
            for word in value
        ):
            return None
        return list(value)

    config = report.get("config")
    validation = report.get("timed_main_validation")
    oracle = validation.get("oracle") if isinstance(validation, dict) else None
    cases = validation.get("cases") if isinstance(validation, dict) else None
    semantic_challenge = report.get("timed_main_semantic_challenge")
    challenge_oracle = (
        semantic_challenge.get("oracle")
        if isinstance(semantic_challenge, dict)
        else None
    )
    challenge_cases = (
        semantic_challenge.get("cases")
        if isinstance(semantic_challenge, dict)
        else None
    )
    oracle_state = (
        state_words(oracle.get("expected_final_state"))
        if isinstance(oracle, dict)
        else None
    )
    challenge_state = (
        state_words(challenge_oracle.get("expected_final_state"))
        if isinstance(challenge_oracle, dict)
        else None
    )
    challenge_iterations = (
        semantic_challenge.get("iterations")
        if isinstance(semantic_challenge, dict)
        else None
    )
    challenge_derivation = (
        semantic_challenge.get("derivation")
        if isinstance(semantic_challenge, dict)
        else None
    )
    internal_samples = report.get("internal_ns_per_20round")
    inner_elapsed_samples = report.get("inner_elapsed_seconds")
    printed_average_samples = report.get("printed_average_us_per_20round")
    wall_samples = report.get("outer_wall_seconds")
    child_cpu_samples = report.get("child_cpu_seconds")
    cpu_coverage = report.get("timed_workload_cpu_coverage")
    cpu_coverage_cases = (
        cpu_coverage.get("cases") if isinstance(cpu_coverage, dict) else None
    )

    if check_global:
        if report.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
            errors.append(
                "timed-main benchmark schema is not "
                f"{BENCHMARK_SCHEMA_VERSION}"
            )
        if not isinstance(config, dict):
            errors.append("timed-main benchmark config is missing or malformed")
        else:
            if config.get("timed_main_repeated_call_validation") is not True:
                errors.append(
                    "timed-main repeated-call validation config gate is not true"
                )
            if config.get("timed_main_alternate_iteration_challenge") is not True:
                errors.append(
                    "timed-main alternate-iteration challenge config gate is not true"
                )
            if config.get("timed_workload_child_cpu_validation") is not True:
                errors.append(
                    "timed-main child-CPU coverage config gate is not true"
                )
            if config.get("timing_stationarity_validation") is not True:
                errors.append(
                    "timed-main stationarity validation config gate is not true"
                )
            if (
                config.get("internal_ns_source")
                != "printed-total-elapsed-seconds-divided-by-iterations"
            ):
                errors.append("timed-main internal sample source is invalid")
            for key, expected in (
                ("iterations", expected_iterations),
                ("warmups", expected_warmups),
                ("samples_per_case", expected_samples),
            ):
                if not exact_integer(config.get(key), expected):
                    errors.append(
                        f"timed-main config {key}={config.get(key)!r}, "
                        f"expected {expected}"
                    )
        if not isinstance(validation, dict):
            errors.append("timed-main validation record is missing or malformed")
        elif set(validation) != {"oracle", "cases"}:
            errors.append("timed-main validation record has an unexpected shape")
        if not isinstance(oracle, dict):
            errors.append("timed-main oracle record is missing or malformed")
        else:
            if set(oracle) != {
                "mode",
                "iterations",
                "expected_final_state",
                "stdout_sha256",
                "status",
            }:
                errors.append("timed-main oracle record has an unexpected shape")
            if oracle.get("mode") != "independent-reference-repeated-20-rounds":
                errors.append("timed-main oracle mode is not independent reference")
            if not exact_integer(oracle.get("iterations"), expected_iterations):
                errors.append(
                    f"timed-main oracle iterations={oracle.get('iterations')!r}, "
                    f"expected {expected_iterations}"
                )
            if oracle_state is None:
                errors.append("timed-main oracle final state is malformed")
            stdout_sha256 = oracle.get("stdout_sha256")
            if not isinstance(stdout_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", stdout_sha256
            ):
                errors.append("timed-main oracle stdout SHA-256 is malformed")
            elif oracle_state is not None:
                canonical_stdout = (
                    f"oracle_final_state_iterations={expected_iterations}\n"
                    f"oracle_final_state={' '.join(oracle_state)}\n"
                )
                expected_stdout_sha256 = hashlib.sha256(
                    canonical_stdout.encode()
                ).hexdigest()
                if stdout_sha256 != expected_stdout_sha256:
                    errors.append(
                        "timed-main oracle stdout SHA-256 does not bind its state"
                    )
            if oracle.get("status") != "PASS":
                errors.append("timed-main oracle status is not PASS")
        if not isinstance(cases, dict):
            errors.append("timed-main case records are missing or malformed")
        elif require_exact_case_set and set(cases) != expected_name_set:
            errors.append(
                "timed-main case set differs from the measured campaign: "
                f"got {sorted(str(name) for name in cases)}, "
                f"expected {sorted(expected_name_set)}"
            )
        elif not expected_name_set.issubset(cases):
            errors.append("one or more timed-main case records are missing")
        if not isinstance(semantic_challenge, dict):
            errors.append(
                "timed-main alternate-iteration challenge is missing or malformed"
            )
        else:
            if set(semantic_challenge) != {
                "mode",
                "iterations",
                "derivation",
                "oracle",
                "cases",
            }:
                errors.append(
                    "timed-main alternate-iteration challenge has an unexpected shape"
                )
            if (
                semantic_challenge.get("mode")
                != "unpredictable-alternate-iteration"
            ):
                errors.append(
                    "timed-main alternate-iteration challenge mode is invalid"
                )
            if (
                not isinstance(challenge_iterations, int)
                or isinstance(challenge_iterations, bool)
                or challenge_iterations <= 0
                or challenge_iterations == expected_iterations
            ):
                errors.append(
                    "timed-main alternate-iteration challenge count is invalid"
                )
        sources = report.get("sources")
        expected_source_hashes: dict[str, str] = {}
        if isinstance(sources, dict):
            for name in expected_names:
                source_record = sources.get(name)
                source_hash = (
                    source_record.get("sha256")
                    if isinstance(source_record, dict)
                    else None
                )
                if isinstance(source_hash, str) and re.fullmatch(
                    r"[0-9a-f]{64}", source_hash
                ):
                    expected_source_hashes[name] = source_hash
        if not isinstance(challenge_derivation, dict):
            errors.append(
                "timed-main alternate-iteration derivation is missing or malformed"
            )
        else:
            if set(challenge_derivation) != {
                "schema_version",
                "campaign_id",
                "nonce_hex",
                "measured_iterations",
                "source_sha256",
                "digest_sha256",
            }:
                errors.append(
                    "timed-main alternate-iteration derivation has an unexpected "
                    "shape"
                )
            if challenge_derivation.get("schema_version") != 1:
                errors.append(
                    "timed-main alternate-iteration derivation schema is invalid"
                )
            if challenge_derivation.get("campaign_id") != report.get("campaign_id"):
                errors.append(
                    "timed-main alternate-iteration derivation campaign id differs"
                )
            nonce_hex = challenge_derivation.get("nonce_hex")
            if not isinstance(nonce_hex, str) or not re.fullmatch(
                r"[0-9a-f]{32}", nonce_hex
            ):
                errors.append(
                    "timed-main alternate-iteration derivation nonce is malformed"
                )
            if not exact_integer(
                challenge_derivation.get("measured_iterations"),
                expected_iterations,
            ):
                errors.append(
                    "timed-main alternate-iteration derivation iteration count "
                    "differs"
                )
            if (
                len(expected_source_hashes) != len(expected_names)
                or challenge_derivation.get("source_sha256")
                != dict(sorted(expected_source_hashes.items()))
            ):
                errors.append(
                    "timed-main alternate-iteration derivation source hashes differ"
                )
            claimed_digest = challenge_derivation.get("digest_sha256")
            derivation_payload = {
                key: item
                for key, item in challenge_derivation.items()
                if key != "digest_sha256"
            }
            actual_digest = canonical_hash(derivation_payload)
            if (
                not isinstance(claimed_digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", claimed_digest)
                or claimed_digest != actual_digest
            ):
                errors.append(
                    "timed-main alternate-iteration derivation digest differs"
                )
            else:
                derived_iterations = 4_096 + (
                    int(actual_digest[:16], 16) % 61_440
                )
                if derived_iterations == expected_iterations:
                    derived_iterations = (
                        4_096 + (derived_iterations - 4_096 + 1) % 61_440
                    )
                if challenge_iterations != derived_iterations:
                    errors.append(
                        "timed-main alternate-iteration count does not match its "
                        "derivation"
                    )
        if not isinstance(challenge_oracle, dict):
            errors.append(
                "timed-main alternate-iteration oracle is missing or malformed"
            )
        else:
            if set(challenge_oracle) != {
                "expected_final_state",
                "stdout_sha256",
                "status",
            }:
                errors.append(
                    "timed-main alternate-iteration oracle has an unexpected shape"
                )
            if challenge_state is None:
                errors.append(
                    "timed-main alternate-iteration oracle state is malformed"
                )
            challenge_stdout_sha256 = challenge_oracle.get("stdout_sha256")
            if not isinstance(challenge_stdout_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", challenge_stdout_sha256
            ):
                errors.append(
                    "timed-main alternate-iteration oracle SHA-256 is malformed"
                )
            elif (
                challenge_state is not None
                and isinstance(challenge_iterations, int)
                and not isinstance(challenge_iterations, bool)
            ):
                challenge_stdout = (
                    "oracle_final_state_iterations="
                    f"{challenge_iterations}\n"
                    f"oracle_final_state={' '.join(challenge_state)}\n"
                )
                if challenge_stdout_sha256 != hashlib.sha256(
                    challenge_stdout.encode()
                ).hexdigest():
                    errors.append(
                        "timed-main alternate-iteration oracle SHA-256 does not "
                        "bind its state"
                    )
            if challenge_oracle.get("status") != "PASS":
                errors.append(
                    "timed-main alternate-iteration oracle status is not PASS"
                )
        if not isinstance(challenge_cases, dict):
            errors.append(
                "timed-main alternate-iteration case records are missing or malformed"
            )
        elif require_exact_case_set and set(challenge_cases) != expected_name_set:
            errors.append(
                "timed-main alternate-iteration case set differs from the measured "
                "campaign"
            )
        elif not expected_name_set.issubset(challenge_cases):
            errors.append(
                "one or more timed-main alternate-iteration case records are missing"
            )
        for label, records in (
            ("internal timing", internal_samples),
            ("inner elapsed timing", inner_elapsed_samples),
            ("printed average timing", printed_average_samples),
            ("outer-wall timing", wall_samples),
            ("child-CPU timing", child_cpu_samples),
        ):
            if not isinstance(records, dict):
                errors.append(f"timed-main {label} samples are missing or malformed")
            elif require_exact_case_set and set(records) != expected_name_set:
                errors.append(
                    f"timed-main {label} case set differs from the measured campaign"
                )
            elif not expected_name_set.issubset(records):
                errors.append(f"one or more timed-main {label} samples are missing")
        expected_coverage_enforced = (
            expected_iterations >= MIN_CHILD_CPU_COVERAGE_ITERATIONS
        )
        if not isinstance(cpu_coverage, dict):
            errors.append(
                "timed-main child-CPU coverage record is missing or malformed"
            )
        else:
            if set(cpu_coverage) != {
                "minimum_iterations",
                "median_bounds",
                "enforced",
                "eligibility",
                "reason",
                "cases",
            }:
                errors.append(
                    "timed-main child-CPU coverage record has an unexpected shape"
                )
            if not exact_integer(
                cpu_coverage.get("minimum_iterations"),
                MIN_CHILD_CPU_COVERAGE_ITERATIONS,
            ):
                errors.append(
                    "timed-main child-CPU coverage iteration threshold changed"
                )
            if cpu_coverage.get("median_bounds") != {
                "low": MIN_MEDIAN_CHILD_CPU_COVERAGE,
                "high": MAX_MEDIAN_CHILD_CPU_COVERAGE,
            }:
                errors.append("timed-main child-CPU coverage bounds changed")
            if cpu_coverage.get("enforced") is not expected_coverage_enforced:
                errors.append(
                    "timed-main child-CPU coverage enforcement flag is inconsistent"
                )
            expected_eligibility = (
                "eligible" if expected_coverage_enforced else "diagnostic-only"
            )
            expected_reason = (
                None
                if expected_coverage_enforced
                else "iterations below 1000000; child-CPU coverage gate is not "
                "enforced"
            )
            if cpu_coverage.get("eligibility") != expected_eligibility:
                errors.append(
                    "timed-main child-CPU coverage eligibility is inconsistent"
                )
            if cpu_coverage.get("reason") != expected_reason:
                errors.append(
                    "timed-main child-CPU coverage reason is inconsistent"
                )
        if not isinstance(cpu_coverage_cases, dict):
            errors.append(
                "timed-main child-CPU coverage cases are missing or malformed"
            )
        elif require_exact_case_set and set(cpu_coverage_cases) != expected_name_set:
            errors.append(
                "timed-main child-CPU coverage case set differs from the measured "
                "campaign"
            )
        elif not expected_name_set.issubset(cpu_coverage_cases):
            errors.append(
                "one or more timed-main child-CPU coverage cases are missing"
            )
        if (
            not isinstance(stationarity_baseline, str)
            or stationarity_baseline not in expected_name_set
        ):
            errors.append(
                "timing stationarity baseline is missing or differs from the "
                "measured campaign"
            )
        else:
            errors.extend(
                timing_stationarity_validation_errors(
                    report,
                    expected_case_names=expected_names,
                    expected_baseline=stationarity_baseline,
                    expected_samples=expected_samples,
                )
            )

    if not check_cases:
        return errors
    for name in expected_names:
        record = cases.get(name) if isinstance(cases, dict) else None
        prefix = f"timed-main case {name}"
        if not isinstance(record, dict):
            errors.append(f"{prefix}: validation record is missing or malformed")
            continue
        if set(record) != {
            "iterations",
            "observed_final_state",
            "preflight_processes",
            "warmup_processes",
            "measured_processes",
            "validated_processes",
            "status",
        }:
            errors.append(f"{prefix}: validation record has an unexpected shape")
        expected_counts = (
            ("iterations", expected_iterations),
            ("preflight_processes", 1),
            ("warmup_processes", expected_warmups),
            ("measured_processes", expected_samples),
            ("validated_processes", 1 + expected_warmups + expected_samples),
        )
        for key, expected in expected_counts:
            if not exact_integer(record.get(key), expected):
                errors.append(
                    f"{prefix}: {key}={record.get(key)!r}, expected {expected}"
                )
        observed_state = state_words(record.get("observed_final_state"))
        if observed_state is None:
            errors.append(f"{prefix}: observed final state is malformed")
        elif oracle_state is not None and observed_state != oracle_state:
            errors.append(f"{prefix}: observed final state differs from the oracle")
        if record.get("status") != "PASS":
            errors.append(f"{prefix}: status is not PASS")
        challenge_record = (
            challenge_cases.get(name) if isinstance(challenge_cases, dict) else None
        )
        if not isinstance(challenge_record, dict):
            errors.append(
                f"{prefix}: alternate-iteration validation is missing or malformed"
            )
            continue
        if set(challenge_record) != {"observed_final_state", "status"}:
            errors.append(
                f"{prefix}: alternate-iteration validation has an unexpected shape"
            )
        challenge_observed_state = state_words(
            challenge_record.get("observed_final_state")
        )
        if challenge_observed_state is None:
            errors.append(
                f"{prefix}: alternate-iteration observed state is malformed"
            )
        elif (
            challenge_state is not None
            and challenge_observed_state != challenge_state
        ):
            errors.append(
                f"{prefix}: alternate-iteration state differs from the oracle"
            )
        if challenge_record.get("status") != "PASS":
            errors.append(f"{prefix}: alternate-iteration status is not PASS")
        sample_lists: dict[str, list[float]] = {}
        for sample_label, records in (
            ("internal timing", internal_samples),
            ("inner elapsed timing", inner_elapsed_samples),
            ("printed average timing", printed_average_samples),
            ("outer-wall timing", wall_samples),
            ("child-CPU timing", child_cpu_samples),
        ):
            values = records.get(name) if isinstance(records, dict) else None
            if not isinstance(values, list) or len(values) != expected_samples:
                errors.append(
                    f"{prefix}: {sample_label} sample count is not "
                    f"{expected_samples}"
                )
                continue
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                or float(value) <= 0.0
                for value in values
            ):
                errors.append(
                    f"{prefix}: {sample_label} samples must be finite and positive"
                )
                continue
            sample_lists[sample_label] = [float(value) for value in values]
        if {
            "internal timing",
            "inner elapsed timing",
            "printed average timing",
        }.issubset(sample_lists):
            for sample_index, (
                internal_ns,
                inner_elapsed_s,
                printed_average_us,
            ) in enumerate(
                zip(
                    sample_lists["internal timing"],
                    sample_lists["inner elapsed timing"],
                    sample_lists["printed average timing"],
                ),
                start=1,
            ):
                expected_internal_ns = (
                    inner_elapsed_s * 1_000_000_000.0 / expected_iterations
                )
                if not math.isclose(
                    internal_ns,
                    expected_internal_ns,
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                ):
                    errors.append(
                        f"{prefix}: internal sample {sample_index} is not derived "
                        "from total elapsed time"
                    )
                expected_average_us = (
                    inner_elapsed_s * 1_000_000.0 / expected_iterations
                )
                rounding_tolerance_us = (
                    0.0000005 + 0.5 / expected_iterations + 1e-15
                )
                if (
                    abs(printed_average_us - expected_average_us)
                    > rounding_tolerance_us
                ):
                    errors.append(
                        f"{prefix}: printed average sample {sample_index} is "
                        "inconsistent with total elapsed time"
                    )
        coverage_record = (
            cpu_coverage_cases.get(name)
            if isinstance(cpu_coverage_cases, dict)
            else None
        )
        if not isinstance(coverage_record, dict):
            errors.append(
                f"{prefix}: child-CPU coverage result is missing or malformed"
            )
            continue
        if set(coverage_record) != {
            "median_inner_to_child_cpu",
            "min_inner_to_child_cpu",
            "max_inner_to_child_cpu",
            "status",
        }:
            errors.append(
                f"{prefix}: child-CPU coverage result has an unexpected shape"
            )
        if {
            "internal timing",
            "child-CPU timing",
        }.issubset(sample_lists):
            observed_coverages = [
                (internal_ns * expected_iterations / 1_000_000_000.0)
                / child_cpu_s
                for internal_ns, child_cpu_s in zip(
                    sample_lists["internal timing"],
                    sample_lists["child-CPU timing"],
                )
            ]
            expected_coverage_values = {
                "median_inner_to_child_cpu": statistics.median(
                    observed_coverages
                ),
                "min_inner_to_child_cpu": min(observed_coverages),
                "max_inner_to_child_cpu": max(observed_coverages),
            }
            for key, expected_value in expected_coverage_values.items():
                recorded_value = coverage_record.get(key)
                if (
                    not isinstance(recorded_value, (int, float))
                    or isinstance(recorded_value, bool)
                    or not math.isclose(
                        float(recorded_value),
                        expected_value,
                        rel_tol=1e-12,
                        abs_tol=1e-15,
                    )
                ):
                    errors.append(
                        f"{prefix}: child-CPU coverage {key} does not match raw "
                        "samples"
                    )
            coverage_is_enforced = (
                expected_iterations >= MIN_CHILD_CPU_COVERAGE_ITERATIONS
            )
            expected_status = "PASS" if coverage_is_enforced else "NOT_ENFORCED"
            if coverage_record.get("status") != expected_status:
                errors.append(
                    f"{prefix}: child-CPU coverage status is not {expected_status}"
                )
            median_coverage = expected_coverage_values[
                "median_inner_to_child_cpu"
            ]
            if coverage_is_enforced and not (
                MIN_MEDIAN_CHILD_CPU_COVERAGE
                <= median_coverage
                <= MAX_MEDIAN_CHILD_CPU_COVERAGE
            ):
                errors.append(
                    f"{prefix}: child-CPU coverage median is outside the "
                    "accepted bounds"
                )
    return errors


def paired_bootstrap(
    ratios: Sequence[float], *, seed_text: str, comparison_count: int
) -> dict[str, float | int]:
    if len(ratios) < 5:
        raise AutotuneError("confirmation needs at least five paired samples")
    if any(not math.isfinite(value) or value <= 0.0 for value in ratios):
        raise AutotuneError("paired ratios must be finite and positive")
    seed = int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], "big")
    generator = random.Random(seed)
    bootstrapped = sorted(
        statistics.median(generator.choices(ratios, k=len(ratios)))
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    family_alpha = 0.05 / max(1, comparison_count)
    lower_probability = family_alpha / 2.0
    upper_probability = 1.0 - lower_probability
    median = statistics.median(ratios)
    return {
        "paired_median": median,
        "paired_mad": statistics.median(abs(value - median) for value in ratios),
        "adjusted_ci_low": percentile(bootstrapped, lower_probability),
        "adjusted_ci_high": percentile(bootstrapped, upper_probability),
        "family_alpha": family_alpha,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "sample_count": len(ratios),
    }


def validate_report_case(
    *,
    report: dict[str, Any],
    case: dict[str, Any],
    cpu: int,
    common_cflags: Sequence[str],
    expected_random_cases: int,
    expected_iterations: int,
    expected_warmups: int,
    expected_samples: int,
) -> tuple[list[str], list[str], tuple[object, ...] | None]:
    failures: list[str] = []
    missing: list[str] = []
    name = case["name"]
    failures.extend(
        timed_main_validation_errors(
            report,
            expected_case_names=[name],
            expected_iterations=expected_iterations,
            expected_warmups=expected_warmups,
            expected_samples=expected_samples,
            require_exact_case_set=False,
            check_global=False,
        )
    )
    verifications = report.get("candidate_verification")
    verification = verifications.get(name) if isinstance(verifications, dict) else None
    if not isinstance(verification, dict):
        missing.append(f"{name}: candidate verification record is missing")
    elif verification.get("status") != "PASS":
        failures.append(f"{name}: candidate correctness gate failed")
    else:
        if integer_or_zero(verification.get("random_cases")) != expected_random_cases:
            failures.append(
                f"{name}: candidate differential count differs from campaign config"
            )
        if verification.get("random_state_and_constants") is not True:
            missing.append(
                f"{name}: candidate gate did not verify random state and constants"
            )
        if verification.get("round_counts") != [1, 20]:
            missing.append(
                f"{name}: candidate gate did not verify rounds 1 and 20"
            )
        if verification.get("verifier_only_flag_overrides") != []:
            failures.append(
                f"{name}: verifier object did not use the measured compile flags"
            )
        expected_verifier_flags = [
            "-O3",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Wpedantic",
            "-Werror",
        ]
        if (
            verification.get("verifier_translation_unit_cflags")
            != expected_verifier_flags
        ):
            failures.append(
                f"{name}: verifier translation unit flags differ from the contract"
            )
        expected_link_flags = [
            "-O3",
            "-Wall",
            "-Wextra",
            *common_cflags,
            *case["cflags"],
        ]
        if verification.get("verifier_link_cflags") != expected_link_flags:
            failures.append(f"{name}: verifier link flags differ from the campaign")
    audits = report.get("assembly_audits")
    audit = audits.get(name) if isinstance(audits, dict) else None
    if not isinstance(audit, dict):
        missing.append(f"{name}: exact-binary assembly audit is missing")
        signature = None
    else:
        if audit.get("status") != "PASS":
            failures.append(f"{name}: assembly audit failed")
        if audit.get("mode") != case["audit_mode"]:
            failures.append(
                f"{name}: audit mode is {audit.get('mode')!r}, expected "
                f"{case['audit_mode']!r}"
            )
        signature = audit_signature(audit)
        if signature is None:
            missing.append(f"{name}: assembly codegen signature is incomplete")
    sources = report.get("sources")
    source = sources.get(name) if isinstance(sources, dict) else None
    if not isinstance(source, dict):
        missing.append(f"{name}: source provenance is missing")
    else:
        if source.get("sha256") != case["source_sha256"]:
            failures.append(f"{name}: measured source hash differs from the manifest")
        if source.get("case_cflags") != case["cflags"]:
            failures.append(f"{name}: measured cflags differ from the manifest")
        rewritten_hash = source.get("rewritten_sha256")
        if not isinstance(rewritten_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", rewritten_hash
        ):
            missing.append(f"{name}: rewritten performance source hash is missing")
    environment = report.get("environment")
    affinity = environment.get("affinity") if isinstance(environment, dict) else None
    if affinity != [cpu]:
        failures.append(f"{name}: benchmark affinity is {affinity!r}, expected [{cpu}]")
    return failures, missing, signature


def analyze_confirmation_campaign(
    *,
    index: dict[str, Any],
    campaign: dict[str, Any],
    manifest: dict[str, Any],
    comparison_count: int,
) -> dict[str, Any]:
    candidate_name = campaign.get("candidate")
    incumbent_name = campaign.get("baseline")
    candidates = candidate_map(manifest)
    result: dict[str, Any] = {
        "session": index.get("session"),
        "campaign_id": campaign.get("campaign_id"),
        "candidate": candidate_name,
        "incumbent": incumbent_name,
        "core_type": campaign.get("core_type"),
        "cpu": campaign.get("cpu"),
        "campaign_status": campaign.get("status"),
        "failures": [],
        "missing": [],
    }
    if candidate_name not in candidates or incumbent_name not in candidates:
        result["missing"].append("campaign names are absent from the manifest")
        return result
    if campaign.get("status") != "PASS":
        result["missing"].append(
            f"campaign status is {campaign.get('status')!r}, not PASS"
        )
        return result
    result_path = Path(str(campaign.get("benchmark_json", "")))
    if not result_path.is_file():
        result["missing"].append(f"benchmark artifact is missing: {result_path}")
        return result
    expected_hash = campaign.get("benchmark_sha256")
    actual_hash = sha256_file(result_path)
    result["benchmark_json"] = str(result_path)
    result["benchmark_sha256"] = actual_hash
    if expected_hash != actual_hash:
        result["failures"].append("benchmark artifact hash changed after the campaign")
        return result
    report = read_json(result_path, "confirmation benchmark")
    if report.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        result["missing"].append(
            "confirmation benchmark schema is not "
            f"{BENCHMARK_SCHEMA_VERSION}"
        )
        return result
    campaign_id = campaign.get("campaign_id")
    if not isinstance(campaign_id, str) or not re.fullmatch(
        r"[0-9a-f]{32}", campaign_id
    ):
        result["missing"].append("campaign id is missing or malformed")
    elif report.get("campaign_id") != campaign_id:
        result["failures"].append(
            "benchmark campaign id differs from confirmation index"
        )
    index_protocol = validated_protocol_fingerprint(
        index.get("measurement_protocol")
    )
    report_protocol = validated_protocol_fingerprint(
        report.get("measurement_protocol")
    )
    if index_protocol is None:
        result["missing"].append(
            "confirmation measurement protocol is missing or malformed"
        )
    elif report_protocol is None:
        result["missing"].append(
            "benchmark measurement protocol is missing or malformed"
        )
    elif report_protocol != index_protocol:
        result["failures"].append(
            "benchmark measurement protocol differs from confirmation index"
        )
    evidence: dict[str, Any] = {
        "schema_version": report.get("schema_version"),
        "campaign_id": report.get("campaign_id"),
        "baseline": report.get("baseline"),
        "config": report.get("config"),
        "measurement_protocol_fingerprint": report_protocol,
        "timed_main_validation": report.get("timed_main_validation"),
        "timed_main_semantic_challenge": report.get(
            "timed_main_semantic_challenge"
        ),
    }
    report_environment = report.get("environment")
    evidence["environment"] = (
        {
            key: report_environment.get(key)
            for key in (
                "cpu",
                "affinity",
                "compiler",
                "objdump",
                "size_tool",
                "flags",
            )
        }
        if isinstance(report_environment, dict)
        else None
    )
    for field in (
        "sources",
        "candidate_verification",
        "assembly_audits",
        "internal_ns_per_20round",
        "inner_elapsed_seconds",
        "printed_average_us_per_20round",
        "outer_wall_seconds",
        "child_cpu_seconds",
    ):
        records = report.get(field)
        evidence[field] = (
            {
                str(incumbent_name): records.get(str(incumbent_name)),
                str(candidate_name): records.get(str(candidate_name)),
            }
            if isinstance(records, dict)
            else None
        )
    evidence["timed_workload_cpu_coverage"] = report.get(
        "timed_workload_cpu_coverage"
    )
    evidence["timing_stationarity"] = report.get("timing_stationarity")
    result["evidence_fingerprint_sha256"] = canonical_hash(evidence)
    semantic_challenge = report.get("timed_main_semantic_challenge")
    semantic_derivation = (
        semantic_challenge.get("derivation")
        if isinstance(semantic_challenge, dict)
        else None
    )
    if isinstance(semantic_derivation, dict):
        result["semantic_challenge_nonce"] = semantic_derivation.get("nonce_hex")
        result["semantic_challenge_derivation_sha256"] = canonical_hash(
            semantic_derivation
        )
    if report.get("baseline") != incumbent_name:
        result["failures"].append("benchmark baseline differs from campaign index")
    report_config = report.get("config")
    index_config = index.get("config")
    if not isinstance(report_config, dict):
        result["missing"].append("benchmark config record is missing or malformed")
        return result
    if not isinstance(index_config, dict):
        result["missing"].append("confirmation config record is missing or malformed")
        return result
    expected_config = {
        "iterations": index_config.get("iterations"),
        "warmups": index_config.get("warmups"),
        "samples_per_case": index_config.get("samples"),
        "candidate_random_differential_cases": index_config.get("random_cases"),
    }
    for key, expected in expected_config.items():
        if report_config.get(key) != expected:
            result["failures"].append(
                f"benchmark config {key}={report_config.get(key)!r}, expected "
                f"{expected!r} from the confirmation index"
            )
    result["failures"].extend(
        timed_main_validation_errors(
            report,
            expected_case_names=[str(incumbent_name), str(candidate_name)],
            expected_baseline=str(incumbent_name),
            expected_iterations=index_config.get("iterations"),
            expected_warmups=index_config.get("warmups"),
            expected_samples=index_config.get("samples"),
            check_cases=False,
        )
    )
    stationarity = report.get("timing_stationarity")
    stationarity_comparisons = (
        stationarity.get("comparisons")
        if isinstance(stationarity, dict)
        else None
    )
    stationarity_comparison = (
        stationarity_comparisons.get(str(candidate_name))
        if isinstance(stationarity_comparisons, dict)
        else None
    )
    result["timing_stationarity"] = stationarity_comparison
    if not isinstance(stationarity_comparison, dict):
        result["missing"].append(
            "candidate timing stationarity comparison is missing or malformed"
        )
    elif stationarity_comparison.get("eligibility") != "eligible":
        result["failures"].append(
            "candidate timing stationarity comparison is diagnostic-only"
        )
    if report_config.get("order") != "balanced-cyclic-reversed":
        result["failures"].append(
            "benchmark did not use balanced cyclic/reversed case order"
        )
    environment = report.get("environment")
    if not isinstance(environment, dict):
        result["missing"].append("benchmark environment record is malformed")
    else:
        expected_flags = ["-O3", "-Wall", "-Wextra", *manifest["common_cflags"]]
        if environment.get("flags") != expected_flags:
            result["failures"].append(
                f"benchmark common flags are {environment.get('flags')!r}, "
                f"expected {expected_flags!r}"
            )
        index_compiler = index.get("compiler")
        expected_version_line = (
            index_compiler.get("version_line")
            if isinstance(index_compiler, dict)
            else None
        )
        if not isinstance(expected_version_line, str):
            result["missing"].append(
                "confirmation compiler version record is malformed"
            )
        elif environment.get("compiler") != expected_version_line:
            result["failures"].append(
                "benchmark compiler version differs from confirmation index"
            )
    try:
        cpu = int(campaign.get("cpu"))
    except (TypeError, ValueError):
        result["missing"].append("campaign CPU is missing or invalid")
        return result
    candidate = candidates[str(candidate_name)]
    incumbent = candidates[str(incumbent_name)]
    for case, prefix in ((candidate, "candidate"), (incumbent, "incumbent")):
        failures, missing, signature = validate_report_case(
            report=report,
            case=case,
            cpu=cpu,
            common_cflags=manifest["common_cflags"],
            expected_random_cases=integer_or_zero(index_config.get("random_cases")),
            expected_iterations=index_config.get("iterations"),
            expected_warmups=index_config.get("warmups"),
            expected_samples=index_config.get("samples"),
        )
        result["failures"].extend(failures)
        result["missing"].extend(missing)
        result[f"{prefix}_audit_signature"] = list(signature) if signature else None
        result[f"{prefix}_hot_loop_signature"] = (
            list(signature[1:]) if signature else None
        )
    samples = report.get("internal_ns_per_20round")
    if not isinstance(samples, dict):
        result["missing"].append("raw internal samples are missing")
        return result
    incumbent_values = samples.get(incumbent_name)
    candidate_values = samples.get(candidate_name)
    if not isinstance(incumbent_values, list) or not isinstance(candidate_values, list):
        result["missing"].append("one side of the paired sample is missing")
        return result
    result["paired_samples_sha256"] = canonical_hash(
        {
            str(incumbent_name): incumbent_values,
            str(candidate_name): candidate_values,
        }
    )
    if len(incumbent_values) != len(candidate_values):
        result["failures"].append("paired sample lengths differ")
        return result
    if len(incumbent_values) < MIN_CONFIRM_SAMPLES:
        result["missing"].append(
            f"confirmation has {len(incumbent_values)} samples; "
            f"{MIN_CONFIRM_SAMPLES} required"
        )
        return result
    try:
        incumbent_numbers = [float(value) for value in incumbent_values]
        candidate_numbers = [float(value) for value in candidate_values]
    except (TypeError, ValueError):
        result["failures"].append("raw samples are not numeric")
        return result
    if any(
        not math.isfinite(value) or value <= 0.0
        for value in [*incumbent_numbers, *candidate_numbers]
    ):
        result["failures"].append("raw samples must be finite and positive")
        return result
    ratios = [
        incumbent_value / candidate_value
        for incumbent_value, candidate_value in zip(
            incumbent_numbers, candidate_numbers
        )
    ]
    seed_text = (
        f"{index.get('session')}|{candidate_name}|{incumbent_name}|"
        f"{campaign.get('core_type')}|{cpu}"
    )
    try:
        result["statistics"] = paired_bootstrap(
            ratios, seed_text=seed_text, comparison_count=comparison_count
        )
    except AutotuneError as error:
        result["missing"].append(str(error))
    return result


def final_compile_argv(
    compiler: dict[str, Any], manifest: dict[str, Any], selected: str
) -> list[str]:
    candidate = candidate_map(manifest)[selected]
    return [
        str(compiler["path"]),
        "-O3",
        "-Wall",
        "-Wextra",
        *manifest["common_cflags"],
        *candidate["cflags"],
        "-o",
        "contest",
        candidate["source"],
    ]


def command_decide(args: argparse.Namespace) -> None:
    if len(args.confirm) < 2:
        raise AutotuneError("decide requires at least two --confirm indices")
    confirms = [load_campaign_index(path, "confirm") for path in args.confirm]
    first = confirms[0]
    manifest = load_index_manifest(first, None)
    baseline = manifest["baseline"]
    candidates = candidate_map(manifest)
    global_blockers: list[str] = []
    manifest_hashes = {
        record.get("sha256") if isinstance(record, dict) else None
        for index in confirms
        for record in [index.get("manifest")]
    }
    if manifest_hashes != {manifest["sha256"]}:
        global_blockers.append("confirmation sessions used different manifests")
    compiler_fingerprints = [
        validated_compiler_fingerprint(
            index.get("compiler"), require_expected_version=True
        )
        for index in confirms
    ]
    compiler_hashes = set(compiler_fingerprints)
    if None in compiler_hashes:
        global_blockers.append(
            "one or more confirmation compiler fingerprints are malformed or "
            "not GCC 13.3.0"
        )
    elif len(compiler_hashes) != 1:
        global_blockers.append("confirmation sessions used different compilers")
    for index in confirms:
        session = index.get("session")
        compiler_record = index.get("compiler")
        if not isinstance(compiler_record, dict):
            continue
        compiler_path = Path(str(compiler_record.get("path", "")))
        if not compiler_path.is_file():
            global_blockers.append(
                f"session {session} compiler binary is no longer available"
            )
        elif sha256_file(compiler_path) != compiler_record.get("sha256"):
            global_blockers.append(
                f"session {session} compiler binary changed after confirmation"
            )
    topology_fingerprints = {
        record.get("probe_fingerprint_sha256") if isinstance(record, dict) else None
        for index in confirms
        for record in [index.get("topology")]
    }
    if len(topology_fingerprints) != 1 or None in topology_fingerprints:
        global_blockers.append("confirmation sessions used different target topologies")
    for index in confirms:
        session = index.get("session")
        topology_record_value = index.get("topology")
        if not isinstance(topology_record_value, dict):
            continue
        topology_path = Path(str(topology_record_value.get("path", "")))
        expected_topology_hash = topology_record_value.get("sha256")
        if not isinstance(expected_topology_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_topology_hash
        ):
            global_blockers.append(
                f"session {session} topology SHA-256 is missing or malformed"
            )
        elif not topology_path.is_file():
            global_blockers.append(
                f"session {session} topology probe is no longer available"
            )
        elif sha256_file(topology_path) != expected_topology_hash:
            global_blockers.append(
                f"session {session} topology probe changed after confirmation"
            )
    current_protocol = measurement_protocol_provenance()
    protocol_fingerprints: set[str] = set()
    for index in confirms:
        fingerprint = validated_protocol_fingerprint(
            index.get("measurement_protocol")
        )
        if fingerprint is None:
            global_blockers.append(
                f"session {index.get('session')} has a missing or malformed "
                "measurement protocol"
            )
        else:
            protocol_fingerprints.add(fingerprint)
    if len(protocol_fingerprints) != 1:
        global_blockers.append(
            "confirmation sessions used different measurement protocols"
        )
    elif current_protocol["fingerprint_sha256"] not in protocol_fingerprints:
        global_blockers.append(
            "measurement protocol changed after confirmation; rerun the campaigns"
        )
    sessions = [str(index.get("session", "")) for index in confirms]
    if len(set(sessions)) < 2:
        global_blockers.append("two distinct confirmation session ids are required")
    artifact_path_references: defaultdict[str, list[str]] = defaultdict(list)
    artifact_hash_references: defaultdict[str, list[str]] = defaultdict(list)
    for index in confirms:
        session = str(index.get("session", ""))
        raw_campaigns = index.get("campaigns")
        if not isinstance(raw_campaigns, list):
            global_blockers.append(f"session {session} has no campaign list")
            index["campaigns"] = []
        else:
            campaigns = [item for item in raw_campaigns if isinstance(item, dict)]
            if len(campaigns) != len(raw_campaigns):
                global_blockers.append(
                    f"session {session} contains a malformed campaign record"
                )
            index["campaigns"] = campaigns
            for campaign in campaigns:
                if campaign.get("session") != session:
                    global_blockers.append(
                        f"session {session} contains a campaign labeled "
                        f"{campaign.get('session')!r}"
                    )
                reference = (
                    f"{session}/{campaign.get('candidate')}/"
                    f"{campaign.get('core_type')}/cpu{campaign.get('cpu')}"
                )
                artifact_path = campaign.get("benchmark_json")
                if isinstance(artifact_path, str) and artifact_path:
                    artifact_path_references[str(Path(artifact_path).resolve())].append(
                        reference
                    )
                artifact_hash = campaign.get("benchmark_sha256")
                if isinstance(artifact_hash, str) and re.fullmatch(
                    r"[0-9a-fA-F]{64}", artifact_hash
                ):
                    artifact_hash_references[artifact_hash.lower()].append(reference)
        if index.get("status") != "COMPLETE":
            global_blockers.append(
                f"session {index.get('session')} status is {index.get('status')!r}"
            )
        if not index.get("target_verified"):
            global_blockers.append(
                f"session {index.get('session')} did not verify 255H/GCC13.3"
            )
        provisional_reasons = index.get("provisional_reasons")
        if not isinstance(provisional_reasons, list) or not all(
            isinstance(reason, str) for reason in provisional_reasons
        ):
            global_blockers.append(
                f"session {index.get('session')} has malformed provisional reasons"
            )
        elif provisional_reasons:
            global_blockers.extend(
                f"session {index.get('session')}: {reason}"
                for reason in provisional_reasons
            )
        if index.get("baseline") != baseline:
            global_blockers.append(
                f"session {index.get('session')} used a different incumbent"
            )
        config = index.get("config")
        if not isinstance(config, dict):
            global_blockers.append(
                f"session {index.get('session')} has a malformed config record"
            )
            config = {}
        iterations = integer_or_zero(config.get("iterations"))
        warmups = integer_or_zero(config.get("warmups"))
        samples = integer_or_zero(config.get("samples"))
        random_cases = integer_or_zero(config.get("random_cases"))
        if iterations < MIN_CONFIRM_ITERATIONS:
            global_blockers.append(
                f"session {index.get('session')} used fewer than "
                f"{MIN_CONFIRM_ITERATIONS} iterations"
            )
        if warmups < MIN_CONFIRM_WARMUPS:
            global_blockers.append(
                f"session {index.get('session')} used fewer than "
                f"{MIN_CONFIRM_WARMUPS} warmups"
            )
        if (
            samples < MIN_CONFIRM_SAMPLES
            or samples % (STATIONARITY_BLOCK_COUNT * 2)
        ):
            global_blockers.append(
                f"session {index.get('session')} did not use at least "
                f"{MIN_CONFIRM_SAMPLES} samples in four fixed, balanced blocks"
            )
        if random_cases < MIN_RANDOM_CASES:
            global_blockers.append(
                f"session {index.get('session')} used fewer than "
                f"{MIN_RANDOM_CASES} random differential cases"
            )
    for path, references in artifact_path_references.items():
        if len(references) > 1:
            global_blockers.append(
                f"confirmation artifact path is reused by {', '.join(references)}: "
                f"{path}"
            )
    for artifact_hash, references in artifact_hash_references.items():
        if len(references) > 1:
            global_blockers.append(
                "confirmation artifact content is reused by "
                f"{', '.join(references)}: sha256={artifact_hash}"
            )
    if args.screen:
        screen = load_campaign_index(args.screen, "screen")
        screen_manifest = screen.get("manifest")
        if not isinstance(screen_manifest, dict):
            global_blockers.append("screen manifest record is malformed")
        elif screen_manifest.get("sha256") != manifest["sha256"]:
            global_blockers.append("screen and confirmation manifests differ")

    measured_names = {
        str(campaign.get("candidate"))
        for index in confirms
        for campaign in index.get("campaigns", [])
        if campaign.get("candidate") not in (None, baseline)
    }
    eligible_names = sorted(
        name
        for name in measured_names
        if name in candidates and candidates[name]["submission_eligible"]
    )
    if not eligible_names:
        global_blockers.append("no submission-eligible candidate was confirmed")
    analyses: list[dict[str, Any]] = []
    for index in confirms:
        for campaign in index.get("campaigns", []):
            if campaign.get("candidate") not in eligible_names:
                continue
            analyses.append(
                analyze_confirmation_campaign(
                    index=index,
                    campaign=campaign,
                    manifest=manifest,
                    comparison_count=max(1, len(eligible_names)),
                )
            )

    campaign_ids: defaultdict[str, list[str]] = defaultdict(list)
    evidence_fingerprints: defaultdict[str, list[str]] = defaultdict(list)
    paired_sample_fingerprints: defaultdict[str, list[str]] = defaultdict(list)
    semantic_challenge_nonces: defaultdict[str, list[str]] = defaultdict(list)
    for row in analyses:
        reference = (
            f"{row.get('session')}/{row.get('candidate')}/"
            f"{row.get('core_type')}/cpu{row.get('cpu')}"
        )
        campaign_id = row.get("campaign_id")
        if isinstance(campaign_id, str) and campaign_id:
            campaign_ids[campaign_id].append(reference)
        evidence_fingerprint = row.get("evidence_fingerprint_sha256")
        if isinstance(evidence_fingerprint, str) and evidence_fingerprint:
            evidence_fingerprints[evidence_fingerprint].append(reference)
        sample_fingerprint = row.get("paired_samples_sha256")
        if isinstance(sample_fingerprint, str) and sample_fingerprint:
            paired_sample_fingerprints[sample_fingerprint].append(reference)
        challenge_nonce = row.get("semantic_challenge_nonce")
        if isinstance(challenge_nonce, str) and challenge_nonce:
            semantic_challenge_nonces[challenge_nonce].append(reference)
    for campaign_id, references in campaign_ids.items():
        if len(references) > 1:
            global_blockers.append(
                f"campaign id is reused by {', '.join(references)}: {campaign_id}"
            )
    for fingerprint, references in evidence_fingerprints.items():
        if len(references) > 1:
            global_blockers.append(
                "canonical measurement evidence is reused by "
                f"{', '.join(references)}: sha256={fingerprint}"
            )
    for fingerprint, references in paired_sample_fingerprints.items():
        if len(references) > 1:
            global_blockers.append(
                "paired internal samples are reused by "
                f"{', '.join(references)}: sha256={fingerprint}"
            )
    for nonce, references in semantic_challenge_nonces.items():
        if len(references) > 1:
            global_blockers.append(
                "semantic challenge nonce is reused by "
                f"{', '.join(references)}: nonce={nonce}"
            )

    required_types = ["p"] if args.policy == "p-only" else ["p", "e", "lp_e"]
    outcomes: dict[str, dict[str, Any]] = {}
    for name in eligible_names:
        candidate_analyses = [
            row
            for row in analyses
            if row["candidate"] == name and row["core_type"] in required_types
        ]
        failures = [
            message for row in candidate_analyses for message in row.get("failures", [])
        ]
        missing = [
            message for row in candidate_analyses for message in row.get("missing", [])
        ]
        reasons: list[str] = []
        candidate_sessions = {row["session"] for row in candidate_analyses}
        if len(candidate_sessions) < 2:
            missing.append(f"{name}: fewer than two confirmation sessions")
        for session in sorted(candidate_sessions):
            for core_type in required_types:
                cpus = {
                    int(row["cpu"])
                    for row in candidate_analyses
                    if row["session"] == session
                    and row["core_type"] == core_type
                    and "statistics" in row
                }
                if len(cpus) < 2:
                    missing.append(
                        f"{name}: session {session} has {len(cpus)} {core_type} "
                        "representatives; two required"
                    )
        candidate_signatures = {
            json.dumps(row.get("candidate_audit_signature"), sort_keys=True)
            for row in candidate_analyses
            if row.get("candidate_audit_signature") is not None
        }
        incumbent_signatures = {
            json.dumps(row.get("incumbent_audit_signature"), sort_keys=True)
            for row in candidate_analyses
            if row.get("incumbent_audit_signature") is not None
        }
        if len(candidate_signatures) != 1:
            missing.append(f"{name}: candidate codegen was not reproducible")
        if len(incumbent_signatures) != 1:
            missing.append(f"{name}: incumbent codegen was not reproducible")
        candidate_hot_loop_signatures = {
            json.dumps(row.get("candidate_hot_loop_signature"), sort_keys=True)
            for row in candidate_analyses
            if row.get("candidate_hot_loop_signature") is not None
        }
        incumbent_hot_loop_signatures = {
            json.dumps(row.get("incumbent_hot_loop_signature"), sort_keys=True)
            for row in candidate_analyses
            if row.get("incumbent_hot_loop_signature") is not None
        }
        equivalent_codegen = (
            len(candidate_hot_loop_signatures) == 1
            and candidate_hot_loop_signatures == incumbent_hot_loop_signatures
        )
        if equivalent_codegen:
            reasons.append(f"{name}: timed-loop codegen and alignment equal incumbent")
        valid_statistics = [
            row for row in candidate_analyses if "statistics" in row
        ]
        for row in valid_statistics:
            stats = row["statistics"]
            median = float(stats["paired_median"])
            lower = float(stats["adjusted_ci_low"])
            if row["core_type"] == "p":
                if median < P_MEDIAN_THRESHOLD or lower <= P_LOWER_THRESHOLD:
                    reasons.append(
                        f"{name}: P session={row['session']} cpu={row['cpu']} "
                        f"median={median:.6f} lower={lower:.6f} misses "
                        f"{P_MEDIAN_THRESHOLD:.3f}/{P_LOWER_THRESHOLD:.3f}"
                    )
            elif row["core_type"] in {"e", "lp_e"}:
                if median < SAFE_MEDIAN_THRESHOLD or lower <= SAFE_LOWER_THRESHOLD:
                    reasons.append(
                        f"{name}: {row['core_type']} session={row['session']} "
                        f"cpu={row['cpu']} median={median:.6f} lower={lower:.6f} "
                        f"misses safety {SAFE_MEDIAN_THRESHOLD:.3f}/"
                        f"{SAFE_LOWER_THRESHOLD:.3f}"
                    )
        if failures:
            status = "failed"
        elif missing:
            status = "provisional"
        elif equivalent_codegen or reasons:
            status = "failed"
        else:
            status = "qualified"
        lower_bounds = [
            float(row["statistics"]["adjusted_ci_low"])
            for row in valid_statistics
        ]
        outcomes[name] = {
            "status": status,
            "submission_eligible": candidates[name]["submission_eligible"],
            "failures": sorted(set(failures)),
            "missing": sorted(set(missing)),
            "reasons": reasons,
            "equivalent_codegen": equivalent_codegen,
            "campaign_count": len(candidate_analyses),
            "minimax_adjusted_ci_low": min(lower_bounds) if lower_bounds else None,
        }

    qualified = [name for name, outcome in outcomes.items() if outcome["status"] == "qualified"]
    provisional_candidates = [
        name for name, outcome in outcomes.items() if outcome["status"] == "provisional"
    ]
    global_blockers = sorted(set(global_blockers))
    selected = baseline
    decision_reasons: list[str] = []
    if global_blockers:
        status = "provisional"
        decision_reasons.extend(global_blockers)
    elif provisional_candidates:
        status = "provisional"
        decision_reasons.append(
            "incomplete confirmation for " + ", ".join(provisional_candidates)
        )
    elif len(qualified) == 1:
        status = "winner"
        selected = qualified[0]
    elif len(qualified) > 1:
        status = "keep-incumbent"
        ranked = sorted(
            qualified,
            key=lambda name: float(outcomes[name]["minimax_adjusted_ci_low"]),
            reverse=True,
        )
        decision_reasons.append(
            "multiple candidates beat the incumbent, but this command accepts only "
            "incumbent-relative confirmation; conservatively keep the incumbent "
            f"until a manually reviewed head-to-head resolves {ranked[0]} vs "
            f"{ranked[1]}"
        )
    else:
        status = "keep-incumbent"
        decision_reasons.append("no candidate met every replacement threshold")

    compiler = first.get("compiler")
    final_argv = (
        final_compile_argv(compiler, manifest, selected)
        if isinstance(compiler, dict) and isinstance(compiler.get("path"), str)
        else None
    )
    decision: dict[str, Any] = {
        "schema_version": 1,
        "autotune": "challenge02_255h_decision",
        "created_at": utc_now(),
        "status": status,
        "policy": args.policy,
        "incumbent": baseline,
        "selected": selected,
        "reasons": decision_reasons,
        "thresholds": {
            "p_paired_median_min": P_MEDIAN_THRESHOLD,
            "p_adjusted_ci_low_strictly_above": P_LOWER_THRESHOLD,
            "e_lp_e_paired_median_min": SAFE_MEDIAN_THRESHOLD,
            "e_lp_e_adjusted_ci_low_strictly_above": SAFE_LOWER_THRESHOLD,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "multiplicity": "Bonferroni two-sided percentile by eligible candidate count",
            "representatives_per_type_per_session": 2,
            "minimum_distinct_sessions": 2,
            "minimum_iterations": MIN_CONFIRM_ITERATIONS,
            "minimum_warmups": MIN_CONFIRM_WARMUPS,
            "minimum_samples": MIN_CONFIRM_SAMPLES,
            "minimum_random_differential_cases": MIN_RANDOM_CASES,
        },
        "manifest": {
            "path": manifest["path"],
            "sha256": manifest["sha256"],
        },
        "measurement_protocol": current_protocol,
        "confirmations": [
            {"path": index["_path"], "sha256": index["_sha256"]}
            for index in confirms
        ],
        "global_blockers": global_blockers,
        "candidate_outcomes": outcomes,
        "campaign_statistics": analyses,
        "selected_source": {
            "path": candidates[selected]["source"],
            "sha256": candidates[selected]["source_sha256"],
        },
        "final_compile_argv": final_argv,
    }
    atomic_write_json(args.out, decision)
    print(f"decision={status}")
    print(f"selected={selected}")
    for reason in decision_reasons:
        print(f"reason={reason}")
    print(f"json={args.out.resolve()}")


def session_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise argparse.ArgumentTypeError(
            "session must use 1-64 letters, digits, dots, underscores, or hyphens"
        )
    return value


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def add_campaign_arguments(
    parser: argparse.ArgumentParser, *, confirm: bool
) -> None:
    parser.add_argument("--compiler", help="GCC 13.3.0 executable")
    parser.add_argument("--session", required=True, type=session_id)
    parser.add_argument(
        "--core-types",
        default="p,e,lpe",
        help="comma-separated p,e,lpe; diagnostics may use atom-unknown/unknown",
    )
    parser.add_argument(
        "--cores-per-type", type=positive_integer, default=2 if confirm else 1
    )
    parser.add_argument(
        "--iterations", type=positive_integer, default=5_000_000 if confirm else 2_000_000
    )
    if confirm:
        parser.add_argument("--warmups", type=positive_integer, default=6)
        parser.add_argument("--samples", type=positive_integer, default=40)
    else:
        parser.add_argument("--warmups", default="auto")
        parser.add_argument("--samples", default="auto")
    parser.add_argument("--random-cases", type=positive_integer, default=100_000)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--allow-provisional",
        action="store_true",
        help="run diagnostics even when the target/compiler/core map is unverified",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="write commands and index JSON without running the benchmark",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe, screen, confirm, and conservatively select challenge 2 builds "
            "on an Intel Core Ultra 7 255H with GCC 13.3.0."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    probe = commands.add_parser("probe", help="record pinned CPUID and Linux topology")
    probe.add_argument("--compiler", default=os.environ.get("CC", "gcc"))
    probe.add_argument("--p-cpus", help="explicit P logical CPU list/ranges")
    probe.add_argument("--e-cpus", help="explicit E logical CPU list/ranges")
    probe.add_argument("--lp-e-cpus", help="explicit LP-E logical CPU list/ranges")
    probe.add_argument("--out", required=True, type=Path)
    probe.set_defaults(handler=command_probe)

    screen = commands.add_parser(
        "screen", help="run one balanced campaign containing every manifest candidate"
    )
    screen.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    screen.add_argument("--topology", required=True, type=Path)
    add_campaign_arguments(screen, confirm=False)
    screen.set_defaults(handler=command_screen)

    confirm = commands.add_parser(
        "confirm", help="run holdout incumbent/candidate head-to-head campaigns"
    )
    confirm.add_argument("--screen", required=True, type=Path)
    confirm.add_argument("--manifest", type=Path)
    confirm.add_argument("--topology", type=Path)
    confirm.add_argument("--incumbent")
    confirm.add_argument("--candidate", action="append", default=[])
    confirm.add_argument("--top", type=positive_integer, default=2)
    add_campaign_arguments(confirm, confirm=True)
    confirm.set_defaults(handler=command_confirm)

    decide = commands.add_parser(
        "decide", help="apply two-session correctness/assembly/performance rules"
    )
    decide.add_argument("--screen", type=Path)
    decide.add_argument("--confirm", action="append", required=True, type=Path)
    decide.add_argument(
        "--policy", choices=("all-core-safe", "p-only"), default="all-core-safe"
    )
    decide.add_argument("--out", required=True, type=Path)
    decide.set_defaults(handler=command_decide)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except AutotuneError as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
