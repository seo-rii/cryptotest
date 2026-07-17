#!/usr/bin/env python3
"""Beam-search q-prefix growth for x5 high-edge Coron candidates.

The x5 high edge that wakes up the folded Coron verifier is the 48-bit range
p[721..768].  This probe grows that range from the high side, adjacent to the
known p[769..783] block, and keeps only the q-prefix-best candidates after each
bounded expansion stage.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from q_interval_sweep import compact_ranges, compact_ranges_key
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


DEFAULT_BASE_RANGES = (
    "784:46:0x245521490bd",
    "150:4:0",
    "920:4:0",
)
DEFAULT_CHUNK_WIDTHS = "9,8,8,8,8,7"
X5_EDGE_START = 721
X5_EDGE_WIDTH = 48
X5_EDGE_STOP = X5_EDGE_START + X5_EDGE_WIDTH


@dataclass(frozen=True)
class BeamCandidate:
    final_value: int
    assigned_width: int
    q_low_bits: int
    q_prefix_bits: int
    q_known_bits: int
    q_interval_width_bits: int
    q_prefix_start: int

    @property
    def current_start(self) -> int:
        return X5_EDGE_STOP - self.assigned_width

    @property
    def current_value(self) -> int:
        return self.final_value >> (self.current_start - X5_EDGE_START)

    @property
    def final_range_text(self) -> str:
        return f"{X5_EDGE_START}:{X5_EDGE_WIDTH}:{hex(self.final_value)}"

    @property
    def current_range_text(self) -> str:
        return f"{self.current_start}:{self.assigned_width}:{hex(self.current_value)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beam-width", type=int, default=8)
    parser.add_argument("--per-parent-cubes", type=int, default=64)
    parser.add_argument(
        "--chunk-widths",
        default=DEFAULT_CHUNK_WIDTHS,
        help="comma-separated widths grown from x5 high side; sum must be 48",
    )
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_fixed_range,
        help="additional fixed p-bit range START:WIDTH:VALUE appended to the default base",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def parse_chunk_widths(text: str) -> list[int]:
    chunks: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        width = int(part, 0)
        if width <= 0:
            raise ValueError("chunk widths must be positive")
        chunks.append(width)
    if not chunks:
        raise ValueError("at least one chunk width is required")
    if sum(chunks) != X5_EDGE_WIDTH:
        raise ValueError(f"chunk widths must sum to {X5_EDGE_WIDTH}")
    return chunks


def format_candidate(candidate: BeamCandidate) -> dict[str, Any]:
    return {
        "range": candidate.final_range_text,
        "value": candidate.final_value,
        "value_hex": hex(candidate.final_value),
        "assigned_width": candidate.assigned_width,
        "current_range": candidate.current_range_text,
        "q_low_bits": candidate.q_low_bits,
        "q_prefix_bits": candidate.q_prefix_bits,
        "q_prefix_start": candidate.q_prefix_start,
        "q_known_bits": candidate.q_known_bits,
        "q_interval_width_bits": candidate.q_interval_width_bits,
    }


def candidate_rank_key(candidate: BeamCandidate) -> tuple[int, int, int, int, tuple[tuple[int, int, int], ...]]:
    fixed_range = FixedRange(candidate.current_start, candidate.assigned_width, candidate.current_value)
    return (
        -candidate.q_prefix_bits,
        -candidate.q_known_bits,
        -candidate.q_low_bits,
        candidate.q_interval_width_bits,
        compact_ranges_key(compact_ranges([fixed_range])),
    )


def score_candidate(instance, base_ranges: list[FixedRange], final_value: int, assigned_width: int) -> BeamCandidate:
    current_start = X5_EDGE_STOP - assigned_width
    current_value = final_value >> (current_start - X5_EDGE_START)
    p_known, p_mask = instance.apply_fixed_ranges(
        base_ranges + [FixedRange(current_start, assigned_width, current_value)]
    )
    q_known = derive_q_known_bits(instance, p_known, p_mask)
    interval_width = q_known.q_max - q_known.q_min
    return BeamCandidate(
        final_value=final_value,
        assigned_width=assigned_width,
        q_low_bits=q_known.low_bits,
        q_prefix_bits=q_known.prefix_bits,
        q_known_bits=q_known.mask.bit_count(),
        q_interval_width_bits=interval_width.bit_length(),
        q_prefix_start=q_known.prefix_start,
    )


def extend_candidate_values(parent: BeamCandidate | None, next_width: int, per_parent_cubes: int) -> list[int]:
    old_width = 0 if parent is None else parent.assigned_width
    new_width = old_width + next_width
    chunk_start = X5_EDGE_STOP - new_width
    chunk_shift = chunk_start - X5_EDGE_START
    parent_value = 0 if parent is None else parent.final_value
    limit = min(1 << next_width, per_parent_cubes)
    return [parent_value | (chunk_value << chunk_shift) for chunk_value in range(limit)]


def run_search(
    instance,
    base_ranges: list[FixedRange],
    chunk_widths: list[int],
    beam_width: int,
    per_parent_cubes: int,
) -> tuple[list[BeamCandidate], list[dict[str, Any]]]:
    beam: list[BeamCandidate | None] = [None]
    stage_summaries: list[dict[str, Any]] = []
    assigned_width = 0

    for stage_index, chunk_width in enumerate(chunk_widths, start=1):
        parent_count = len(beam)
        assigned_width += chunk_width
        chunk_start = X5_EDGE_STOP - assigned_width
        rows: list[BeamCandidate] = []
        for parent in beam:
            for final_value in extend_candidate_values(parent, chunk_width, per_parent_cubes):
                rows.append(score_candidate(instance, base_ranges, final_value, assigned_width))

        rows.sort(key=candidate_rank_key)
        retained = rows[:beam_width]
        best = retained[0] if retained else None
        stage_summaries.append(
            {
                "stage": stage_index,
                "chunk_start": chunk_start,
                "chunk_width": chunk_width,
                "assigned_width": assigned_width,
                "parent_count": parent_count,
                "emitted_candidates": len(rows),
                "retained_candidates": len(retained),
                "per_parent_limit": min(1 << chunk_width, per_parent_cubes),
                "best": None if best is None else format_candidate(best),
            }
        )
        beam = retained

    return [candidate for candidate in beam if candidate is not None], stage_summaries


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
        print(
            f"stage={stage['stage']} chunk={stage['chunk_start']}:{stage['chunk_width']} "
            f"emitted={stage['emitted_candidates']} retained={stage['retained_candidates']} "
            f"best={best.get('current_range', '(none)')} "
            f"q_prefix={best.get('q_prefix_bits')} q_known={best.get('q_known_bits')} "
            f"width_bits={best.get('q_interval_width_bits')}"
        )
    for rank, candidate in enumerate(report["final_candidates"], start=1):
        print(
            f"{rank:02d} {candidate['range']} "
            f"q_prefix={candidate['q_prefix_bits']} "
            f"q_known={candidate['q_known_bits']} "
            f"width_bits={candidate['q_interval_width_bits']}"
        )


def main() -> int:
    args = parse_args()
    if args.beam_width < 1:
        raise SystemExit("--beam-width must be positive")
    if args.per_parent_cubes < 1:
        raise SystemExit("--per-parent-cubes must be positive")

    try:
        chunk_widths = parse_chunk_widths(args.chunk_widths)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    instance = load_instance()
    base_ranges = [parse_fixed_range(item) for item in DEFAULT_BASE_RANGES]
    base_ranges.extend(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)

    final_beam, stage_summaries = run_search(
        instance,
        base_ranges,
        chunk_widths,
        args.beam_width,
        args.per_parent_cubes,
    )
    final_beam.sort(key=candidate_rank_key)
    report = {
        "event": "q_x5_beam_search",
        "summary": {
            "ranking_priority": "q_prefix_bits,q_known_bits,q_low_bits,small_interval",
            "base_fixed_ranges": compact_ranges(base_ranges),
            "base_p_fixed_bits": base_mask.bit_count(),
            "base_q_low_bits": base_q.low_bits,
            "base_q_prefix_bits": base_q.prefix_bits,
            "base_q_prefix_start": base_q.prefix_start,
            "base_q_known_bits": base_q.mask.bit_count(),
            "beam_width": args.beam_width,
            "per_parent_cubes": args.per_parent_cubes,
            "chunk_widths": chunk_widths,
            "x5_final_range": f"{X5_EDGE_START}:{X5_EDGE_WIDTH}",
        },
        "stages": stage_summaries,
        "final_candidates": [format_candidate(candidate) for candidate in final_beam],
    }

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        emit_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
