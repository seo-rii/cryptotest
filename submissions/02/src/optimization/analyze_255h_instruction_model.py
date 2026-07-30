#!/usr/bin/env python3
"""Build a qualified Core Ultra 7 255H instruction-level model for task 2.

The model deliberately separates three evidence levels:

* Intel's public product page identifies the 255H topology.  Intel's Arrow
  Lake PerfMon page maps LP-E to Crestmont, while Intel's 255H-specific ECI
  page calls the same two LP-E cores additional Skymont cores; the conflict is
  kept explicit and the Crestmont model is conditional on the PerfMon mapping.
* Intel's downloadable Skymont and Crestmont tables provide selected
  instruction latency and reciprocal-throughput cells.
* The repository's audited assembly provides the instruction counts and
  dependency structure being modelled.

As of 2026-07-23, no Lion Cove table, 64-bit RORX row, or LEA row was found in
the pinned official catalog and packages.  Those values remain gaps.  The
32-bit RORX row and ADD row are exposed for RORX64/LEA only as explicitly
non-authoritative sensitivity scenarios.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


AS_OF = "2026-07-23"
SCRIPT_NAME = "submissions/02/src/optimization/analyze_255h_instruction_model.py"
DEFAULT_OUTPUT = Path(__file__).with_name("instruction_model_255h.json")

SKYMONT_XLSX_SHA256 = (
    "8be64a0f74bdac1bce913463aef0fc8741e935c685583d54f85269e4d1673aca"
)
SKYMONT_ARCHIVE_SHA256 = (
    "69cd210d11ab88f96109af961e9c3f21dbb2345862229bf9aeb786d851e813a6"
)
CRESTMONT_ARCHIVE_SHA256 = (
    "eff60fbd02c48eeecbb3d5be46741dc46d47b38ad9adbae6d2fe42e548296c5a"
)
CRESTMONT_CSV_SHA256 = (
    "04a06500962c1220b90b6da4d4f54dfeab748cbd5f56d441d41a1464fe1ad54e"
)
CRESTMONT_CSV_MEMBER = "tpt-lat-cmt-rwc/tpt-lat-cmt.csv"

LOCAL_EVIDENCE = {
    "scalar_source": {
        "path": "submissions/02/contest.c",
        "sha256": (
            "51f0366304cced28d5221ecdb0964dbd05dafe2a4071c4bf6ce1c7425d80fd71"
        ),
    },
    "avx2_source": {
        "path": "submissions/02/src/optimization/contest_simd_avx2_lanewise.c",
        "sha256": (
            "3a8273cb6f381efb30fb4e104a9741acf158307714216f2a2b2d8c1756b9d751"
        ),
    },
    "assembly_audit": {
        "path": "submissions/02/src/optimization/simd_results.json",
        "sha256": (
            "36f0f7a79c6707c7f5236c2c5b9af1296682cd11c699c4086d3bc4b4c03f78e1"
        ),
    },
}

# Exact cells copied from the pinned Intel files.  They are kept as strings so
# source spelling (including an em dash or an empty CSV cell) is verifiable.
EXPECTED_SOURCE_ROWS = {
    "skymont": {
        "ADD/AND/CMP/OR/SUB/XOR/TEST r64, r64": {
            "throughput": "0.125",
            "throughput_vex256": "—",
            "latency": "1",
            "msrom": "N",
        },
        "BSWAP r64": {
            "throughput": "0.25",
            "throughput_vex256": "—",
            "latency": "1",
            "msrom": "N",
        },
        "PADDQ/PSUBQ/PCMPEQQ xmm, xmm": {
            "throughput": "0.25",
            "throughput_vex256": "0.5",
            "latency": "1",
            "msrom": "N",
        },
        "PAND/PANDN/POR/PXOR xmm, xmm": {
            "throughput": "0.25",
            "throughput_vex256": "0.5",
            "latency": "1",
            "msrom": "N",
        },
        "PSHUFB xmm, xmm": {
            "throughput": "0.5",
            "throughput_vex256": "1",
            "latency": "1",
            "msrom": "N",
        },
        "SARX/SHLX/SHRX/RORX r32, r32, r32": {
            "throughput": "0.25",
            "throughput_vex256": "—",
            "latency": "1 (2 for shift count)",
            "msrom": "N",
        },
        "VPSLLVD/Q; VPSRAVD; VPSRLVQ": {
            "throughput": "0.25",
            "throughput_vex256": "0.5",
            "latency": "1",
            "msrom": "N",
        },
    },
    "crestmont": {
        "ADD/AND/CMP/OR/SUB/XOR/TEST r64, r64": {
            "throughput": "0.25",
            "throughput_vex256": "",
            "latency": "1",
            "msrom": "N",
        },
        "BSWAP r64": {
            "throughput": "0.25",
            "throughput_vex256": "",
            "latency": "1",
            "msrom": "N",
        },
        "PADDQ/PSUBQ/PCMPEQQ xmm, xmm": {
            "throughput": "0.33",
            "throughput_vex256": "0.66",
            "latency": "1",
            "msrom": "N",
        },
        "PAND/PANDN/POR/PXOR xmm, xmm": {
            "throughput": "0.33",
            "throughput_vex256": "0.66",
            "latency": "1",
            "msrom": "N",
        },
        "PSHUFB xmm, xmm": {
            "throughput": "1",
            "throughput_vex256": "2",
            "latency": "1",
            "msrom": "N",
        },
        "SARX/SHLX/SHRX/RORX r32, r32, r32": {
            "throughput": "0.25",
            "throughput_vex256": "",
            "latency": "1 (2 for shift count)",
            "msrom": "N",
        },
        "VPSLLVD/Q; VPSRAVD; VPSRLVQ": {
            "throughput": "0.33",
            "throughput_vex256": "0.66",
            "latency": "1",
            "msrom": "N",
        },
    },
}

ROW_NAMES = {
    "scalar_add_xor_r64": "ADD/AND/CMP/OR/SUB/XOR/TEST r64, r64",
    "scalar_bswap_r64": "BSWAP r64",
    "scalar_rorx_r32_only": "SARX/SHLX/SHRX/RORX r32, r32, r32",
    "vector_add_qword": "PADDQ/PSUBQ/PCMPEQQ xmm, xmm",
    "vector_or_xor": "PAND/PANDN/POR/PXOR xmm, xmm",
    "vector_shuffle_bytes": "PSHUFB xmm, xmm",
    "vector_variable_shift_qword": "VPSLLVD/Q; VPSRAVD; VPSRLVQ",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def require_hash(path: Path, expected: str, label: str) -> None:
    actual = sha256_path(path)
    if actual != expected:
        raise ValueError(
            f"{label} SHA-256 mismatch: expected {expected}, got {actual}: {path}"
        )


def parse_skymont_xlsx(path: Path) -> dict[str, dict[str, str]]:
    """Read the first worksheet using only the Python standard library."""

    require_hash(path, SKYMONT_XLSX_SHA256, "Skymont XLSX")
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(node.text or "" for node in item.findall(".//m:t", namespace))
            for item in shared_root.findall("m:si", namespace)
        ]
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    parsed: dict[str, dict[str, str]] = {}
    for row in sheet.findall(".//m:row", namespace):
        cells: dict[str, str] = {}
        for cell in row.findall("m:c", namespace):
            reference = cell.attrib["r"]
            column = "".join(character for character in reference if character.isalpha())
            value_node = cell.find("m:v", namespace)
            if value_node is None or value_node.text is None:
                value = ""
            elif cell.attrib.get("t") == "s":
                value = shared[int(value_node.text)]
            else:
                value = value_node.text
            cells[column] = value
        label = cells.get("A", "")
        if label in EXPECTED_SOURCE_ROWS["skymont"]:
            parsed[label] = {
                "throughput": cells.get("B", ""),
                "throughput_vex256": cells.get("C", ""),
                "latency": cells.get("D", ""),
                "msrom": cells.get("E", ""),
            }
    return parsed


def parse_crestmont_zip(path: Path) -> dict[str, dict[str, str]]:
    require_hash(path, CRESTMONT_ARCHIVE_SHA256, "Crestmont archive")
    with zipfile.ZipFile(path) as archive:
        csv_bytes = archive.read(CRESTMONT_CSV_MEMBER)
    actual_member_hash = sha256_bytes(csv_bytes)
    if actual_member_hash != CRESTMONT_CSV_SHA256:
        raise ValueError(
            "Crestmont CSV SHA-256 mismatch: "
            f"expected {CRESTMONT_CSV_SHA256}, got {actual_member_hash}"
        )

    rows = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
    parsed: dict[str, dict[str, str]] = {}
    for row in rows:
        label = row["IFORM"]
        if label in EXPECTED_SOURCE_ROWS["crestmont"]:
            parsed[label] = {
                "throughput": row["Throughput"],
                "throughput_vex256": row["Throughput VEX256"],
                "latency": row["Latency"],
                "msrom": row["MSROM"],
            }
    return parsed


def verify_rows(
    actual: dict[str, dict[str, str]],
    expected: dict[str, dict[str, str]],
    label: str,
) -> None:
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        mismatched = sorted(
            row for row in set(actual) & set(expected) if actual[row] != expected[row]
        )
        raise ValueError(
            f"{label} row mismatch: missing={missing}, extra={extra}, "
            f"mismatched={mismatched}"
        )


def verify_local_evidence() -> None:
    repository = Path(__file__).resolve().parents[4]
    for label, item in LOCAL_EVIDENCE.items():
        path = repository / item["path"]
        require_hash(path, item["sha256"], f"local {label}")

    audit_path = repository / LOCAL_EVIDENCE["assembly_audit"]["path"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    scalar = audit["static_analysis"]["cases"]["scalar"]["binary_audit"]
    avx2 = audit["static_analysis"]["cases"]["avx2"]["binary_audit"]
    if scalar["mnemonics"] != {
        "add": 74,
        "bswap": 80,
        "jne": 1,
        "lea": 6,
        "rorx": 80,
        "sub": 1,
        "xor": 80,
    }:
        raise ValueError("pinned scalar assembly counts changed")
    if avx2["selected_simd_operation_counts"] != {
        "vpaddq": 20,
        "vpor": 20,
        "vpshufb": 20,
        "vpsllvq": 20,
        "vpsrlvq": 20,
        "vpxor": 20,
    }:
        raise ValueError("pinned AVX2 assembly counts changed")


def decimal_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def source_row(architecture: str, semantic_name: str) -> dict[str, Any]:
    row_name = ROW_NAMES[semantic_name]
    row = EXPECTED_SOURCE_ROWS[architecture][row_name]
    return {
        "source_row": row_name,
        "source_cells": row,
    }


def value(architecture: str, semantic_name: str, field: str) -> Decimal:
    row_name = ROW_NAMES[semantic_name]
    raw = EXPECTED_SOURCE_ROWS[architecture][row_name][field]
    return Decimal(raw)


def schedule_summary(
    dependency_cycles: Decimal,
    counts: dict[str, int],
    reciprocal_throughputs: dict[str, Decimal],
) -> dict[str, Any]:
    demands = {
        mnemonic: Decimal(counts[mnemonic]) * reciprocal_throughputs[mnemonic]
        for mnemonic in counts
    }
    single_class_floor = max(demands.values())
    return {
        "critical_dependency_path_cycles": decimal_number(dependency_cycles),
        "isolated_reciprocal_throughput_demands_cycles": {
            mnemonic: decimal_number(demand)
            for mnemonic, demand in demands.items()
        },
        "single_instruction_class_demand_floor_cycles": decimal_number(
            single_class_floor
        ),
        "critical_path_or_single_class_floor_cycles": decimal_number(
            max(dependency_cycles, single_class_floor)
        ),
        "sum_if_instruction_classes_receive_no_cross_class_overlap_cycles": (
            decimal_number(sum(demands.values(), Decimal(0)))
        ),
        "qualification": (
            "The critical path is a latency calculation. Per-class demand is "
            "instruction_count times Intel's isolated reciprocal throughput. "
            "The max is only an optimistic backend floor; the sum is a named "
            "no-cross-class-overlap scenario, not a runtime upper bound. Port "
            "sharing, frontend limits, setup/loop instructions, power, and "
            "frequency are not modelled."
        ),
    }


def scalar_model(architecture: str) -> dict[str, Any]:
    rounds = 20
    lanes = 4
    counts = {
        "rorx": rounds * lanes,
        "xor": 80,
        "bswap": 80,
        "add": 74,
        "lea_add_equivalent": 6,
    }
    one_cycle = Decimal(1)
    proxy_rorx_latency = one_cycle
    dependency = Decimal(rounds) * (
        proxy_rorx_latency + one_cycle + one_cycle + one_cycle
    )
    throughputs = {
        "rorx": value(architecture, "scalar_rorx_r32_only", "throughput"),
        "xor": value(architecture, "scalar_add_xor_r64", "throughput"),
        "bswap": value(architecture, "scalar_bswap_r64", "throughput"),
        "add": value(architecture, "scalar_add_xor_r64", "throughput"),
        "lea_add_equivalent": value(
            architecture, "scalar_add_xor_r64", "throughput"
        ),
    }
    return {
        "status": "conditional_rorx32_and_add_for_lea_proxies",
        "exact_instruction_counts": counts,
        "dependency_structure": (
            "Four independent scalar chains; each chain has 20 serial semantic "
            "rotate -> XOR -> byte-swap -> add stages. The audited machine code "
            "uses 80 RORX64, 80 XOR64, 80 BSWAP64, 74 ADD64, and 6 LEA "
            "add-equivalents."
        ),
        "authoritative_rows": {
            "xor64_and_add64": source_row(
                architecture, "scalar_add_xor_r64"
            ),
            "bswap64": source_row(architecture, "scalar_bswap_r64"),
        },
        "missing_authoritative_rows": {
            "instructions": ["RORX r64, r64, imm8", "LEA r64, memory-address"],
            "effect": (
                "The scalar 255H model cannot be completed from the pinned "
                "official tables without their latency and throughput."
            ),
        },
        "sensitivity_scenario": {
            "rorx64_proxy": source_row(
                architecture, "scalar_rorx_r32_only"
            ),
            "lea64_proxy": source_row(architecture, "scalar_add_xor_r64"),
            "proxy_limitation": (
                "Intel's row is explicitly r32 and groups RORX with variable "
                "shift instructions. Applying its one-cycle data latency and "
                "0.25-cycle throughput to immediate-count RORX64 is an "
                "illustrative sensitivity case. The same scenario gives the "
                "six LEAs the ADD row's latency/throughput. Neither proxy is "
                "an authoritative value."
            ),
            "schedule": schedule_summary(dependency, counts, throughputs),
        },
    }


def avx2_model(architecture: str) -> dict[str, Any]:
    rounds = 20
    counts = {
        "vpsllvq": rounds,
        "vpsrlvq": rounds,
        "vpor": rounds,
        "vpxor": rounds,
        "vpshufb": rounds,
        "vpaddq": rounds,
    }
    shift_latency = Decimal(1)
    dependency_per_round = (
        max(shift_latency, shift_latency)
        + Decimal(1)  # VPOR
        + Decimal(1)  # VPXOR
        + Decimal(1)  # VPSHUFB
        + Decimal(1)  # VPADDQ
    )
    dependency = Decimal(rounds) * dependency_per_round
    throughputs = {
        "vpsllvq": value(
            architecture, "vector_variable_shift_qword", "throughput_vex256"
        ),
        "vpsrlvq": value(
            architecture, "vector_variable_shift_qword", "throughput_vex256"
        ),
        "vpor": value(architecture, "vector_or_xor", "throughput_vex256"),
        "vpxor": value(architecture, "vector_or_xor", "throughput_vex256"),
        "vpshufb": value(
            architecture, "vector_shuffle_bytes", "throughput_vex256"
        ),
        "vpaddq": value(architecture, "vector_add_qword", "throughput_vex256"),
    }
    return {
        "status": "complete_for_selected_hot_operations_at_table_level",
        "exact_instruction_counts": counts,
        "dependency_structure": (
            "One YMM dependency chain across 20 rounds. The two variable shifts "
            "within a rotate may start from the same input in parallel; VPOR, "
            "VPXOR, VPSHUFB, and VPADDQ are serial after them."
        ),
        "authoritative_rows": {
            "vpsllvq_and_vpsrlvq": source_row(
                architecture, "vector_variable_shift_qword"
            ),
            "vpor_and_vpxor": source_row(architecture, "vector_or_xor"),
            "vpshufb": source_row(architecture, "vector_shuffle_bytes"),
            "vpaddq": source_row(architecture, "vector_add_qword"),
        },
        "schedule": schedule_summary(dependency, counts, throughputs),
        "scope_limitation": (
            "This covers the six repeated hot operations only. It is a "
            "microarchitecture-table calculation, not a 255H SKU measurement."
        ),
    }


def build_report() -> dict[str, Any]:
    e_scalar = scalar_model("skymont")
    e_avx2 = avx2_model("skymont")
    lpe_scalar = scalar_model("crestmont")
    lpe_avx2 = avx2_model("crestmont")

    report: dict[str, Any] = {
        "schema_version": 2,
        "analysis": "challenge_core_ultra_7_255h_instruction_model",
        "generated_by": SCRIPT_NAME,
        "as_of": AS_OF,
        "deterministic": True,
        "scope": {
            "processor": "Intel Core Ultra 7 255H",
            "product_family": "Arrow Lake H / Intel Core Ultra Series 2",
            "topology": {
                "p_cores": 6,
                "e_cores": 8,
                "lp_e_cores": 2,
                "threads": 16,
            },
            "core_type_mapping": {
                "p_core": "Lion Cove",
                "e_core": "Skymont",
                "lp_e_core": {
                    "status": "official_sources_conflict",
                    "perfmon_arrow_lake_mapping": "Crestmont",
                    "eci_255h_description": "additional Skymont cores",
                    "model_choice": (
                        "Crestmont table retained only as a conditional "
                        "PerfMon-mapping sensitivity model"
                    ),
                },
            },
            "core_mapping_qualification": (
                "Inference from the 255H ARK Arrow Lake identity/topology and "
                "Intel's Arrow Lake Client PerfMon microarchitecture mapping. "
                "Intel's separate 255H ECI page instead calls the two LP-E "
                "cores additional Skymont cores, so LP-E identity is unresolved."
            ),
            "isa_fact": "Intel ARK lists AVX2 for the 255H.",
            "modelled_region": (
                "Audited hot operation sequence of the scalar incumbent and "
                "lane-wise AVX2 candidate; setup, branch, and frontend costs "
                "are excluded."
            ),
        },
        "table_semantics": {
            "throughput_interpretation": (
                "The bundled Intel README defines throughput as the cycles "
                "before issue ports can accept the same instruction again; "
                "this report therefore calls it reciprocal throughput."
            ),
            "latency_interpretation": (
                "The README defines latency as cycles to complete the uops "
                "forming an instruction."
            ),
            "precision_caveat": (
                "Intel notes that measured throughput can differ by up to 0.1 "
                "cycle and that dynamically varying latency is reported as a "
                "rounded average. Published decimals are retained exactly for "
                "deterministic arithmetic, not treated as exact silicon laws."
            ),
            "skymont_schema_caveat": (
                "The Skymont workbook uses the same Throughput, Throughput "
                "VEX256, Latency, and MSROM schema but contains no bundled "
                "README; applying the package definition to it is explicit."
            ),
        },
        "sources": [
            {
                "id": "intel_ark_255h",
                "publisher": "Intel",
                "kind": "official_product_page",
                "url": (
                    "https://www.intel.com/content/www/us/en/products/sku/241751/"
                    "intel-core-ultra-7-processor-255h-24m-cache-up-to-5-10-ghz/"
                    "specifications.html"
                ),
                "retrieved": AS_OF,
                "used_for": (
                    "Arrow Lake identity, 6 P + 8 E + 2 LP-E topology, 16 "
                    "threads, and AVX2 support"
                ),
                "content_hash": None,
                "hash_note": "Dynamic web page; canonical URL and retrieval date pinned.",
            },
            {
                "id": "intel_perfmon_arrow_lake",
                "publisher": "Intel",
                "kind": "official_perfmon_documentation",
                "url": (
                    "https://perfmon-events.intel.com/platforms/arrowlake/"
                    "core-events/p-core/"
                ),
                "retrieved": AS_OF,
                "used_for": (
                    "Arrow Lake Client mapping: Lion Cove P-core, Skymont "
                    "E-core, Crestmont Low Power E-core"
                ),
                "content_hash": None,
                "hash_note": "Live documentation; canonical URL and retrieval date pinned.",
            },
            {
                "id": "intel_eci_255h_heterogeneous_computing",
                "publisher": "Intel",
                "kind": "official_255h_developer_documentation",
                "url": (
                    "https://eci.intel.com/embodied-sdk-docs/content/"
                    "developer_tools_tutorials/heterogeneous_computing.html"
                ),
                "retrieved": AS_OF,
                "used_for": (
                    "Conflicting 255H-specific description: 8 Skymont E-cores "
                    "and 2 additional Skymont LP E-cores"
                ),
                "content_hash": None,
                "hash_note": "Live documentation; canonical URL and retrieval date pinned.",
                "conflict": (
                    "The Arrow Lake PerfMon documentation labels LP-E as "
                    "Crestmont. Neither live page resolves which description "
                    "governs the exact 255H LP-E execution core."
                ),
            },
            {
                "id": "intel_skymont_throughput_latency",
                "publisher": "Intel",
                "kind": "official_download_package",
                "record_id": 837381,
                "record_date": "2024-10-28",
                "record_url": (
                    "https://www.intel.com/content/www/us/en/content-details/"
                    "837381/intel-processors-and-processor-cores-based-on-"
                    "skymont-microarchitecture-instruction-throughput-and-"
                    "latency.html"
                ),
                "download_url": (
                    "https://cdrdv2.intel.com/v1/dl/getContent/837381?"
                    "fileName=Xeon-6-e-core-Latency-Throughput.7z"
                ),
                "archive_filename": "Xeon-6-e-core-Latency-Throughput.7z",
                "archive_sha256": SKYMONT_ARCHIVE_SHA256,
                "payload_filename": "Xeon-6-e-core-Latency-Throughput.xlsx",
                "payload_sha256": SKYMONT_XLSX_SHA256,
                "payload_modified_utc": "2024-10-28T19:19:54Z",
                "retrieved": AS_OF,
                "scope_qualification": (
                    "Intel describes the record as Skymont-microarchitecture "
                    "data, while the download filename says Xeon 6 E-core. It "
                    "is used as a Skymont-family analytical input, not proof "
                    "of client-SKU-identical timing."
                ),
            },
            {
                "id": "intel_crestmont_redwood_throughput_latency",
                "publisher": "Intel",
                "kind": "official_download_package",
                "record_id": 825952,
                "record_date": "2024-06-24",
                "record_url": (
                    "https://www.intel.com/content/www/us/en/content-details/"
                    "825952/intel-processors-and-processor-cores-based-on-"
                    "crestmont-and-redwood-cove-microarchitecture-instruction-"
                    "throughput-and-latency.html"
                ),
                "download_url": (
                    "https://cdrdv2.intel.com/v1/dl/getContent/825952?"
                    "fileName=tpt-lat-cmt-rwc.zip"
                ),
                "archive_filename": "tpt-lat-cmt-rwc.zip",
                "archive_sha256": CRESTMONT_ARCHIVE_SHA256,
                "payload_filename": CRESTMONT_CSV_MEMBER,
                "payload_sha256": CRESTMONT_CSV_SHA256,
                "retrieved": AS_OF,
                "scope_qualification": (
                    "The Intel record and cmt CSV filename identify Crestmont. "
                    "The bundled README header contains stale Golden Cove text; "
                    "that packaging inconsistency is preserved as a caveat."
                ),
            },
            {
                "id": "intel_optimization_catalog",
                "publisher": "Intel",
                "kind": "official_optimization_landing_page",
                "url": (
                    "https://www.intel.com/content/www/us/en/developer/articles/"
                    "technical/intel64-and-ia32-architectures-optimization.html"
                ),
                "retrieved": AS_OF,
                "used_for": (
                    "Bound the official public search: it links Skymont and "
                    "older tables but no Lion Cove per-instruction table."
                ),
                "absence_qualification": (
                    "This records the searched Intel catalog and date; it does "
                    "not prove that no Intel document exists elsewhere."
                ),
            },
        ],
        "local_assembly_evidence": {
            "artifacts": LOCAL_EVIDENCE,
            "scalar_hot_counts": {
                "rorx64": 80,
                "xor64": 80,
                "bswap64": 80,
                "add64": 74,
                "lea_add_equivalent": 6,
            },
            "avx2_hot_counts": {
                "vpsllvq": 20,
                "vpsrlvq": 20,
                "vpor": 20,
                "vpxor": 20,
                "vpshufb": 20,
                "vpaddq": 20,
            },
            "qualification": (
                "Counts are from the pinned GCC 13.3 static audit, not Intel "
                "performance data."
            ),
        },
        "models": {
            "p_core_lion_cove": {
                "status": "structured_gap_no_numeric_model",
                "scalar": {
                    "missing": [
                        "RORX64 latency and reciprocal throughput",
                        "XOR64 latency and reciprocal throughput",
                        "BSWAP64 latency and reciprocal throughput",
                        "ADD64 latency and reciprocal throughput",
                        "LEA64 latency and reciprocal throughput",
                    ]
                },
                "avx2": {
                    "missing": [
                        "VPSLLVQ/VPSRLVQ latency and reciprocal throughput",
                        "VPOR/VPXOR latency and reciprocal throughput",
                        "VPSHUFB latency and reciprocal throughput",
                        "VPADDQ latency and reciprocal throughput",
                    ]
                },
                "reason": (
                    "No official Lion Cove per-instruction table was identified "
                    "in the pinned Intel public catalog/search. Older P-core "
                    "values are not silently substituted."
                ),
            },
            "e_core_skymont": {
                "source_scope": "Intel Skymont microarchitecture table",
                "scalar": e_scalar,
                "avx2": e_avx2,
            },
            "lp_e_core_crestmont": {
                "status": "conditional_on_arrow_lake_perfmon_mapping",
                "source_scope": (
                    "Intel Crestmont microarchitecture table; applicable to "
                    "255H LP-E only if the PerfMon mapping, rather than the "
                    "conflicting 255H ECI wording, describes its execution core"
                ),
                "scalar": lpe_scalar,
                "avx2": lpe_avx2,
            },
        },
        "conditional_comparison": {
            "e_core_skymont": {
                "condition": (
                    "Use Intel's r32 RORX row as an RORX64 proxy and the ADD64 "
                    "row as a proxy for six LEA add-equivalents."
                ),
                "scalar_critical_path_cycles": 80,
                "avx2_critical_path_cycles": 100,
                "avx2_over_scalar_critical_path_ratio": 1.25,
                "interpretation": (
                    "The AVX2 chain has one extra serial operation per round. "
                    "This is sensitivity evidence against a latency win, not a "
                    "255H timing prediction."
                ),
            },
            "lp_e_core_crestmont": {
                "condition": (
                    "Use Intel's r32 RORX row as an RORX64 proxy and the ADD64 "
                    "row as a proxy for six LEA add-equivalents."
                ),
                "scalar_critical_path_cycles": 80,
                "avx2_critical_path_cycles": 100,
                "avx2_over_scalar_critical_path_ratio": 1.25,
                "interpretation": (
                    "The AVX2 no-cross-class-overlap service scenario is 106 "
                    "cycles versus 80 for scalar, but neither sum is a runtime "
                    "bound. This remains a target-measurement question."
                ),
            },
            "p_core_lion_cove": {
                "status": "not_computable_from_pinned_official_data"
            },
        },
        "unresolved_gaps": [
            {
                "id": "lion_cove_instruction_table",
                "scope": "P-core",
                "impact": "No official numeric scalar-versus-AVX2 model.",
            },
            {
                "id": "rorx64_row",
                "scope": "Skymont E-core and Crestmont LP-E",
                "impact": "Scalar models remain conditional.",
            },
            {
                "id": "lea64_row",
                "scope": "Skymont E-core and Crestmont LP-E",
                "impact": (
                    "The six LEA add-equivalents require an explicit proxy in "
                    "the scalar model."
                ),
            },
            {
                "id": "execution_port_mapping",
                "scope": "all core types",
                "impact": (
                    "Isolated reciprocal throughput cannot determine mixed-"
                    "instruction port contention or overlap."
                ),
            },
            {
                "id": "client_server_skymont_transfer",
                "scope": "Skymont E-core",
                "impact": (
                    "The official archive filename is Xeon 6 E-core; only an "
                    "actual 255H run can validate client-SKU behavior."
                ),
            },
            {
                "id": "lp_e_core_microarchitecture_conflict",
                "scope": "255H LP-E",
                "impact": (
                    "Intel Arrow Lake PerfMon maps LP-E to Crestmont, while "
                    "Intel's 255H-specific ECI documentation calls the two "
                    "LP-E cores additional Skymont cores. The Crestmont "
                    "numeric model is therefore conditional, and both table "
                    "interpretations require affinity-pinned 255H measurement."
                ),
            },
            {
                "id": "whole_loop_effects",
                "scope": "all core types",
                "impact": (
                    "Frontend/code-cache behavior, loop control, setup, power, "
                    "frequency, OS migration, and Thread Director are omitted."
                ),
            },
        ],
        "decision": {
            "selects_submission_winner": False,
            "reason": (
                "Lion Cove is unmodelled, scalar RORX64/LEA are conditional on "
                "the other core types, LP-E identity conflicts across official "
                "Intel pages, and the tables do not model whole-loop frontend/"
                "resource behavior. Keep scalar as incumbent and time both "
                "binaries on separately pinned 255H P, E, and LP-E cores."
            ),
        },
        "reproduction": {
            "generate": (
                "python3 submissions/02/src/optimization/"
                "analyze_255h_instruction_model.py --output "
                "submissions/02/src/optimization/instruction_model_255h.json"
            ),
            "check": (
                "python3 submissions/02/src/optimization/"
                "analyze_255h_instruction_model.py --check "
                "submissions/02/src/optimization/instruction_model_255h.json"
            ),
            "source_verification": (
                "Download the two canonical Intel packages, extract the "
                "Skymont XLSX, then add --verify-skymont-archive PATH, "
                "--verify-skymont-xlsx PATH, and --verify-crestmont-zip PATH "
                "to the --check command."
            ),
        },
    }
    validate_report(report)
    return report


def validate_report(report: dict[str, Any]) -> None:
    models = report["models"]
    for core in ("e_core_skymont", "lp_e_core_crestmont"):
        scalar_schedule = models[core]["scalar"]["sensitivity_scenario"]["schedule"]
        avx_schedule = models[core]["avx2"]["schedule"]
        if scalar_schedule["critical_dependency_path_cycles"] != 80:
            raise AssertionError(f"unexpected scalar critical path for {core}")
        if avx_schedule["critical_dependency_path_cycles"] != 100:
            raise AssertionError(f"unexpected AVX2 critical path for {core}")

    skymont = models["e_core_skymont"]
    if (
        skymont["scalar"]["sensitivity_scenario"]["schedule"]
        ["sum_if_instruction_classes_receive_no_cross_class_overlap_cycles"]
        != 60
    ):
        raise AssertionError("unexpected Skymont scalar service scenario")
    if (
        skymont["avx2"]["schedule"]
        ["sum_if_instruction_classes_receive_no_cross_class_overlap_cycles"]
        != 70
    ):
        raise AssertionError("unexpected Skymont AVX2 service scenario")

    crestmont = models["lp_e_core_crestmont"]
    if (
        crestmont["scalar"]["sensitivity_scenario"]["schedule"]
        ["sum_if_instruction_classes_receive_no_cross_class_overlap_cycles"]
        != 80
    ):
        raise AssertionError("unexpected Crestmont scalar service scenario")
    if (
        crestmont["avx2"]["schedule"]
        ["sum_if_instruction_classes_receive_no_cross_class_overlap_cycles"]
        != 106
    ):
        raise AssertionError("unexpected Crestmont AVX2 service scenario")


def serialize(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or check the deterministic, source-qualified Core Ultra "
            "7 255H instruction model for challenge 2."
        )
    )
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path, help="write generated JSON")
    destination.add_argument("--check", type=Path, help="check JSON is up to date")
    parser.add_argument(
        "--verify-skymont-archive",
        type=Path,
        help="verify the downloaded Intel record 837381 7z archive hash",
    )
    parser.add_argument(
        "--verify-skymont-xlsx",
        type=Path,
        help="verify an extracted Intel record 837381 XLSX and its selected rows",
    )
    parser.add_argument(
        "--verify-crestmont-zip",
        type=Path,
        help="verify the downloaded Intel record 825952 ZIP and its selected rows",
    )
    parser.add_argument(
        "--skip-local-evidence-check",
        action="store_true",
        help="generate without checking pinned repository source/audit hashes",
    )
    args = parser.parse_args()

    if not args.skip_local_evidence_check:
        verify_local_evidence()
    if args.verify_skymont_archive:
        require_hash(
            args.verify_skymont_archive,
            SKYMONT_ARCHIVE_SHA256,
            "Skymont archive",
        )
        print("verified_skymont_archive=PASS", file=sys.stderr)
    if args.verify_skymont_xlsx:
        verify_rows(
            parse_skymont_xlsx(args.verify_skymont_xlsx),
            EXPECTED_SOURCE_ROWS["skymont"],
            "Skymont XLSX",
        )
        print("verified_skymont_xlsx=PASS", file=sys.stderr)
    if args.verify_crestmont_zip:
        verify_rows(
            parse_crestmont_zip(args.verify_crestmont_zip),
            EXPECTED_SOURCE_ROWS["crestmont"],
            "Crestmont CSV",
        )
        print("verified_crestmont_zip=PASS", file=sys.stderr)

    payload = serialize(build_report())
    if args.check:
        current = args.check.read_text(encoding="utf-8")
        if current != payload:
            raise SystemExit(f"stale model JSON: {args.check}")
        print(f"model_json_check=PASS path={args.check}")
    elif args.output:
        args.output.write_text(payload, encoding="utf-8")
        print(f"model_json_written={args.output}")
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
