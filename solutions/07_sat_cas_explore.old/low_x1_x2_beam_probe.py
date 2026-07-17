#!/usr/bin/env python3
"""Low-side staged x1/x2 beam diagnostics for challenge 7.

This explores the existing full-x6, x0=0, x7=0 branch by fixing x2 low32
values and growing an x1 low-prefix chunk from p[210..].  The beam is ranked by
cheap q-derived signals first, then by bounded product-prefix statuses for the
retained candidates.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from typing import Any

from q_interval_sweep import compact_ranges, compact_ranges_key
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, z3_product_prefix_status


X1_START = 210
X1_WIDTH = 39
X2_LOW32_START = 265
X2_LOW32_WIDTH = 32

DEFAULT_BASE_RANGES = (
    FixedRange(784, 46, 0x245521490BD),
    FixedRange(150, 4, 0),
    FixedRange(920, 4, 0),
)
DEFAULT_CHECK_BITS = "218,272"
DEFAULT_X2_VALUES = "0"


@dataclass(frozen=True)
class BeamCandidate:
    x2_value: int
    x1_low_value: int
    assigned_width: int
    q_low_bits: int
    q_known_bits: int
    q_prefix_bits: int
    q_prefix_start: int
    q_interval_width_bits: int
    prefix_statuses: tuple[dict[str, Any], ...] = ()

    @property
    def x2_range(self) -> FixedRange:
        return FixedRange(X2_LOW32_START, X2_LOW32_WIDTH, self.x2_value)

    @property
    def x1_range(self) -> FixedRange | None:
        if self.assigned_width == 0:
            return None
        return FixedRange(X1_START, self.assigned_width, self.x1_low_value)

    @property
    def fixed_ranges(self) -> list[FixedRange]:
        ranges = [self.x2_range]
        if self.x1_range is not None:
            ranges.append(self.x1_range)
        return ranges


def parse_int_list(text: str) -> list[int]:
    values = [int(item.strip(), 0) for item in text.split(",") if item.strip()]
    if not values:
        raise ValueError("expected at least one integer")
    return values


def fixed_range_record(item: FixedRange) -> dict[str, int | str]:
    return {
        "start": item.start,
        "width": item.width,
        "value": item.value,
        "value_hex": hex(item.value),
        "arg": f"{item.start}:{item.width}:{hex(item.value)}",
    }


def status_rank_key(candidate: BeamCandidate) -> tuple[int, ...]:
    order = {"sat": 2, "unknown": 1, "unsat": 0}
    return tuple(order.get(str(item.get("status")), 1) for item in candidate.prefix_statuses)


def candidate_rank_key(candidate: BeamCandidate) -> tuple[int, int, int, tuple[int, ...], tuple[tuple[int, int, int], ...]]:
    return (
        -candidate.q_low_bits,
        -candidate.q_known_bits,
        -candidate.q_prefix_bits,
        tuple(-item for item in status_rank_key(candidate)),
        compact_ranges_key(compact_ranges(candidate.fixed_ranges)),
    )


def candidate_record(candidate: BeamCandidate) -> dict[str, Any]:
    return {
        "x2_low32_value": candidate.x2_value,
        "x2_low32_value_hex": hex(candidate.x2_value),
        "x1_low_value": candidate.x1_low_value,
        "x1_low_value_hex": hex(candidate.x1_low_value),
        "x1_assigned_width": candidate.assigned_width,
        "candidate_ranges": [fixed_range_record(item) for item in candidate.fixed_ranges],
        "q_low_bits": candidate.q_low_bits,
        "q_known_bits": candidate.q_known_bits,
        "q_prefix_bits": candidate.q_prefix_bits,
        "q_prefix_start": candidate.q_prefix_start,
        "q_interval_width_bits": candidate.q_interval_width_bits,
        "product_prefix_statuses": list(candidate.prefix_statuses),
    }


def score_candidate(
    instance,
    base_ranges: list[FixedRange],
    x2_value: int,
    x1_low_value: int,
    assigned_width: int,
) -> BeamCandidate:
    if x2_value < 0 or x2_value >= (1 << X2_LOW32_WIDTH):
        raise ValueError(f"x2 low32 value does not fit 32 bits: {hex(x2_value)}")
    if assigned_width < 0 or assigned_width > X1_WIDTH:
        raise ValueError(f"x1 assigned width must be in 0..{X1_WIDTH}")
    if assigned_width == 0 and x1_low_value != 0:
        raise ValueError("x1 value must be zero when no x1 bits are assigned")
    if assigned_width > 0 and (x1_low_value < 0 or x1_low_value >= (1 << assigned_width)):
        raise ValueError(f"x1 low value does not fit {assigned_width} bits: {hex(x1_low_value)}")

    candidate_ranges = [FixedRange(X2_LOW32_START, X2_LOW32_WIDTH, x2_value)]
    if assigned_width:
        candidate_ranges.append(FixedRange(X1_START, assigned_width, x1_low_value))
    p_known, p_mask = instance.apply_fixed_ranges(base_ranges + candidate_ranges)
    q_known = derive_q_known_bits(instance, p_known, p_mask)
    return BeamCandidate(
        x2_value=x2_value,
        x1_low_value=x1_low_value,
        assigned_width=assigned_width,
        q_low_bits=q_known.low_bits,
        q_known_bits=q_known.mask.bit_count(),
        q_prefix_bits=q_known.prefix_bits,
        q_prefix_start=q_known.prefix_start,
        q_interval_width_bits=(q_known.q_max - q_known.q_min).bit_length(),
    )


def attach_prefix_statuses(
    instance,
    base_ranges: list[FixedRange],
    candidate: BeamCandidate,
    check_bits: list[int],
    timeout_ms: int,
) -> BeamCandidate:
    p_known, p_mask = instance.apply_fixed_ranges(base_ranges + candidate.fixed_ranges)
    statuses = []
    for bits in check_bits:
        status, meta = z3_product_prefix_status(
            instance=instance,
            p_known=p_known,
            p_mask=p_mask,
            check_bits=bits,
            timeout_ms=timeout_ms,
        )
        statuses.append({"status": status, **meta})
    return replace(candidate, prefix_statuses=tuple(statuses))


def emit_human(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        "base "
        f"p_fixed={summary['base_p_fixed_bits']} "
        f"q_low={summary['base_q_low_bits']} "
        f"q_prefix={summary['base_q_prefix_bits']} "
        f"q_known={summary['base_q_known_bits']}"
    )
    for stage in report["stages"]:
        best = stage["best"] or {}
        statuses = ",".join(
            f"{item['check_bits']}:{item['status']}" for item in best.get("product_prefix_statuses", [])
        )
        print(
            f"stage={stage['stage']} chunk={stage['chunk_start']}:{stage['chunk_width']} "
            f"emitted={stage['emitted_candidates']} retained={stage['retained_candidates']} "
            f"best_x1={best.get('x1_low_value_hex', '(none)')} "
            f"q_low={best.get('q_low_bits')} q_known={best.get('q_known_bits')} "
            f"q_prefix={best.get('q_prefix_bits')} prefix=[{statuses}]"
        )
    for rank, candidate in enumerate(report["candidates"], start=1):
        statuses = ",".join(
            f"{item['check_bits']}:{item['status']}" for item in candidate["product_prefix_statuses"]
        )
        print(
            f"{rank:02d} x2={candidate['x2_low32_value_hex']} "
            f"x1={candidate['x1_low_value_hex']}/{candidate['x1_assigned_width']} "
            f"q_low={candidate['q_low_bits']} q_known={candidate['q_known_bits']} "
            f"q_prefix={candidate['q_prefix_bits']} prefix=[{statuses}]"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x1-low-bits", type=int, default=16)
    parser.add_argument("--beam-width", type=int, default=4)
    parser.add_argument("--per-parent-cubes", type=int, default=8)
    parser.add_argument("--x2-values", default=DEFAULT_X2_VALUES)
    parser.add_argument("--check-bits", default=DEFAULT_CHECK_BITS)
    parser.add_argument("--timeout-ms", type=int, default=100)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.x1_low_bits < 0 or args.x1_low_bits > X1_WIDTH:
        raise SystemExit(f"--x1-low-bits must be in 0..{X1_WIDTH}")
    if args.beam_width < 1:
        raise SystemExit("--beam-width must be positive")
    if args.per_parent_cubes < 1:
        raise SystemExit("--per-parent-cubes must be positive")
    if args.timeout_ms <= 0:
        raise SystemExit("--timeout-ms must be positive")

    try:
        x2_values = parse_int_list(args.x2_values)
        check_bits = parse_int_list(args.check_bits)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if any(bits <= 0 for bits in check_bits):
        raise SystemExit("--check-bits values must be positive")

    chunk_unit = max(1, args.per_parent_cubes.bit_length() - 1)
    remaining_bits = args.x1_low_bits
    chunk_widths = []
    while remaining_bits:
        chunk_width = min(chunk_unit, remaining_bits)
        chunk_widths.append(chunk_width)
        remaining_bits -= chunk_width

    instance = load_instance()
    base_ranges = list(DEFAULT_BASE_RANGES)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)

    parents = [score_candidate(instance, base_ranges, value, 0, 0) for value in x2_values]
    stages = []
    beam = parents
    assigned_width = 0

    if not chunk_widths:
        beam = [
            attach_prefix_statuses(instance, base_ranges, candidate, check_bits, args.timeout_ms)
            for candidate in beam
        ]
        beam.sort(key=candidate_rank_key)

    for stage_index, chunk_width in enumerate(chunk_widths, start=1):
        parent_count = len(beam)
        old_width = assigned_width
        assigned_width += chunk_width
        chunk_start = X1_START + old_width
        per_parent_limit = min(1 << chunk_width, args.per_parent_cubes)
        rows = []
        for parent in beam:
            for chunk_value in range(per_parent_limit):
                x1_low_value = parent.x1_low_value | (chunk_value << old_width)
                rows.append(
                    score_candidate(
                        instance,
                        base_ranges,
                        parent.x2_value,
                        x1_low_value,
                        assigned_width,
                    )
                )

        rows.sort(key=candidate_rank_key)
        retained = [
            attach_prefix_statuses(instance, base_ranges, candidate, check_bits, args.timeout_ms)
            for candidate in rows[: args.beam_width]
        ]
        retained.sort(key=candidate_rank_key)
        best = retained[0] if retained else None
        stages.append(
            {
                "stage": stage_index,
                "chunk_start": chunk_start,
                "chunk_width": chunk_width,
                "assigned_width": assigned_width,
                "parent_count": parent_count,
                "emitted_candidates": len(rows),
                "retained_candidates": len(retained),
                "per_parent_limit": per_parent_limit,
                "best": None if best is None else candidate_record(best),
            }
        )
        beam = retained

    beam.sort(key=candidate_rank_key)
    report = {
        "event": "low_x1_x2_beam_probe",
        "summary": {
            "ranking_priority": "q_low_bits,q_known_bits,q_prefix_bits,product_prefix_statuses",
            "base_fixed_ranges": [fixed_range_record(item) for item in base_ranges],
            "base_p_fixed_bits": base_mask.bit_count(),
            "base_q_low_bits": base_q.low_bits,
            "base_q_prefix_bits": base_q.prefix_bits,
            "base_q_prefix_start": base_q.prefix_start,
            "base_q_known_bits": base_q.mask.bit_count(),
            "x1_start": X1_START,
            "x1_low_bits": args.x1_low_bits,
            "x1_chunk_widths": chunk_widths,
            "x2_low32_start": X2_LOW32_START,
            "x2_low32_width": X2_LOW32_WIDTH,
            "x2_values": x2_values,
            "check_bits": check_bits,
            "timeout_ms": args.timeout_ms,
            "beam_width": args.beam_width,
            "per_parent_cubes": args.per_parent_cubes,
            "initial_x2_candidates": len(parents),
            "final_candidate_count": len(beam),
        },
        "stages": stages,
        "candidates": [candidate_record(candidate) for candidate in beam],
    }

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        emit_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
