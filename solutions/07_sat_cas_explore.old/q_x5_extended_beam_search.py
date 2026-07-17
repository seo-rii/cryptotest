#!/usr/bin/env python3
"""Grow x5 beyond the 48-bit Coron trigger with q-prefix beam ranking.

The earlier q_x5 beam stops at p[721..768], which is enough to wake the
folded-Coron verifier.  This diagnostic keeps growing the same x5 high edge
toward the x5 low edge to see whether extra x5 bits improve the q-prefix
ceiling before spending oracle time.
"""

from __future__ import annotations

import argparse
import json

from q_interval_sweep import compact_ranges, compact_ranges_key
from sat_cas_core import FixedRange, derive_q_known_bits, load_instance, parse_fixed_range


X5_STOP = 769
DEFAULT_BASE_RANGES = (
    "784:46:0x245521490bd",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--x5-width", type=int, default=64, help="x5 high-edge width to grow, max 87")
    parser.add_argument("--x0", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--x1", type=lambda text: int(text, 0), help="optional full x1 value for p[210..248]")
    parser.add_argument("--x7", type=lambda text: int(text, 0), default=0)
    parser.add_argument("--beam-width", type=int, default=4)
    parser.add_argument("--per-parent-cubes", type=int, default=16)
    parser.add_argument(
        "--chunk-widths",
        help="comma-separated chunk widths; default is 9 then 8-bit chunks and a final remainder",
    )
    parser.add_argument(
        "--fix-p-range",
        action="append",
        default=[],
        type=parse_fixed_range,
        help="additional fixed p-bit range START:WIDTH:VALUE appended to the default base",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.x5_width <= 0 or args.x5_width > 87:
        raise SystemExit("--x5-width must be in 1..87")
    if args.x0 < 0 or args.x0 >= 16:
        raise SystemExit("--x0 must fit 4 bits")
    if args.x1 is not None and (args.x1 < 0 or args.x1 >= (1 << 39)):
        raise SystemExit("--x1 must fit 39 bits")
    if args.x7 < 0 or args.x7 >= 16:
        raise SystemExit("--x7 must fit 4 bits")
    if args.beam_width < 1:
        raise SystemExit("--beam-width must be positive")
    if args.per_parent_cubes < 1:
        raise SystemExit("--per-parent-cubes must be positive")

    final_start = X5_STOP - args.x5_width
    if args.chunk_widths:
        chunk_widths = [int(part.strip(), 0) for part in args.chunk_widths.split(",") if part.strip()]
        if not chunk_widths or any(width <= 0 for width in chunk_widths):
            raise SystemExit("--chunk-widths must contain positive widths")
        if sum(chunk_widths) != args.x5_width:
            raise SystemExit(f"--chunk-widths must sum to x5 width {args.x5_width}")
    else:
        chunk_widths = []
        remaining = args.x5_width
        first = min(9, remaining)
        chunk_widths.append(first)
        remaining -= first
        while remaining:
            chunk = min(8, remaining)
            chunk_widths.append(chunk)
            remaining -= chunk

    instance = load_instance()
    base_ranges = [parse_fixed_range(item) for item in DEFAULT_BASE_RANGES]
    base_ranges.append(FixedRange(150, 4, args.x0))
    if args.x1 is not None:
        base_ranges.append(FixedRange(210, 39, args.x1))
    base_ranges.append(FixedRange(920, 4, args.x7))
    base_ranges.extend(args.fix_p_range)
    base_known, base_mask = instance.apply_fixed_ranges(base_ranges)
    base_q = derive_q_known_bits(instance, base_known, base_mask)

    beam: list[dict[str, int]] = [{"final_value": 0, "assigned_width": 0}]
    stages: list[dict[str, object]] = []
    assigned_width = 0
    for stage_index, chunk_width in enumerate(chunk_widths, start=1):
        old_width = assigned_width
        assigned_width += chunk_width
        current_start = X5_STOP - assigned_width
        chunk_shift = current_start - final_start
        rows: list[dict[str, object]] = []
        per_parent_limit = min(1 << chunk_width, args.per_parent_cubes)
        for parent in beam:
            parent_value = int(parent["final_value"])
            for chunk_value in range(per_parent_limit):
                final_value = parent_value | (chunk_value << chunk_shift)
                current_value = final_value >> (current_start - final_start)
                p_known, p_mask = instance.apply_fixed_ranges(
                    base_ranges + [FixedRange(current_start, assigned_width, current_value)]
                )
                q_known = derive_q_known_bits(instance, p_known, p_mask)
                current_range = FixedRange(current_start, assigned_width, current_value)
                rows.append(
                    {
                        "final_value": final_value,
                        "assigned_width": assigned_width,
                        "current_start": current_start,
                        "current_value": current_value,
                        "range": f"{final_start}:{args.x5_width}:{hex(final_value)}",
                        "current_range": f"{current_start}:{assigned_width}:{hex(current_value)}",
                        "q_low_bits": q_known.low_bits,
                        "q_prefix_bits": q_known.prefix_bits,
                        "q_prefix_start": q_known.prefix_start,
                        "q_known_bits": q_known.mask.bit_count(),
                        "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                        "rank_ranges": compact_ranges([current_range]),
                    }
                )
        rows.sort(
            key=lambda row: (
                -int(row["q_prefix_bits"]),
                -int(row["q_known_bits"]),
                -int(row["q_low_bits"]),
                int(row["q_interval_width_bits"]),
                compact_ranges_key(row["rank_ranges"]),
            )
        )
        retained = rows[: args.beam_width]
        best = retained[0] if retained else None
        stages.append(
            {
                "stage": stage_index,
                "chunk_start": current_start,
                "chunk_width": chunk_width,
                "assigned_width": assigned_width,
                "parent_count": len(beam),
                "emitted_candidates": len(rows),
                "retained_candidates": len(retained),
                "per_parent_limit": per_parent_limit,
                "best": None
                if best is None
                else {key: value for key, value in best.items() if key != "rank_ranges"},
            }
        )
        beam = [
            {"final_value": int(row["final_value"]), "assigned_width": int(row["assigned_width"])}
            for row in retained
        ]

    final_candidates: list[dict[str, object]] = []
    for parent in beam:
        final_value = int(parent["final_value"])
        current_value = final_value
        p_known, p_mask = instance.apply_fixed_ranges(
            base_ranges + [FixedRange(final_start, args.x5_width, current_value)]
        )
        q_known = derive_q_known_bits(instance, p_known, p_mask)
        final_range = FixedRange(final_start, args.x5_width, current_value)
        final_candidates.append(
            {
                "range": f"{final_start}:{args.x5_width}:{hex(final_value)}",
                "value": final_value,
                "value_hex": hex(final_value),
                "q_low_bits": q_known.low_bits,
                "q_prefix_bits": q_known.prefix_bits,
                "q_prefix_start": q_known.prefix_start,
                "q_known_bits": q_known.mask.bit_count(),
                "q_interval_width_bits": (q_known.q_max - q_known.q_min).bit_length(),
                "rank_ranges": compact_ranges([final_range]),
            }
        )
    final_candidates.sort(
        key=lambda row: (
            -int(row["q_prefix_bits"]),
            -int(row["q_known_bits"]),
            -int(row["q_low_bits"]),
            int(row["q_interval_width_bits"]),
            compact_ranges_key(row["rank_ranges"]),
        )
    )
    final_candidates = [
        {key: value for key, value in row.items() if key != "rank_ranges"} for row in final_candidates
    ]

    report = {
        "event": "q_x5_extended_beam_search",
        "summary": {
            "ranking_priority": "q_prefix_bits,q_known_bits,q_low_bits,small_interval",
            "base_fixed_ranges": compact_ranges(base_ranges),
            "x0": args.x0,
            "x0_hex": hex(args.x0),
            "x1": args.x1,
            "x1_hex": None if args.x1 is None else hex(args.x1),
            "x7": args.x7,
            "x7_hex": hex(args.x7),
            "base_p_fixed_bits": base_mask.bit_count(),
            "base_q_low_bits": base_q.low_bits,
            "base_q_prefix_bits": base_q.prefix_bits,
            "base_q_prefix_start": base_q.prefix_start,
            "base_q_known_bits": base_q.mask.bit_count(),
            "beam_width": args.beam_width,
            "per_parent_cubes": args.per_parent_cubes,
            "chunk_widths": chunk_widths,
            "x5_final_range": f"{final_start}:{args.x5_width}",
            "final_candidate_count": len(final_candidates),
            "best_final_candidate": final_candidates[0] if final_candidates else None,
        },
        "stages": stages,
        "final_candidates": final_candidates,
    }

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            "base "
            f"p_fixed={summary['base_p_fixed_bits']} "
            f"q_low={summary['base_q_low_bits']} "
            f"q_prefix={summary['base_q_prefix_bits']} "
            f"q_known={summary['base_q_known_bits']} "
            f"x5_range={summary['x5_final_range']}"
        )
        for stage in stages:
            best = stage["best"] or {}
            print(
                f"stage={stage['stage']} chunk={stage['chunk_start']}:{stage['chunk_width']} "
                f"emitted={stage['emitted_candidates']} retained={stage['retained_candidates']} "
                f"best={best.get('current_range', '(none)')} "
                f"q_prefix={best.get('q_prefix_bits')} q_known={best.get('q_known_bits')} "
                f"width_bits={best.get('q_interval_width_bits')}"
            )
        for rank, candidate in enumerate(final_candidates, start=1):
            print(
                f"{rank:02d} {candidate['range']} "
                f"q_prefix={candidate['q_prefix_bits']} "
                f"q_known={candidate['q_known_bits']} "
                f"width_bits={candidate['q_interval_width_bits']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
