#!/usr/bin/env python3
"""Check whether challenge 2's exact transform admits simple operation folds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Exhaust low-bit projections of the XOR/add commuting equation "
            "and classify the two-round linear bit permutations."
        )
    )
    parser.add_argument("--json", type=Path, help="write the structured result")
    args = parser.parse_args()

    xor_constants = [
        0xE7B92D4A6C1F8035,
        0x1A4F8C3E9D2B6074,
        0xC3F05A2E8D6194B7,
        0x6B2E9D1A4F7C3085,
    ]
    # Each source word is added to the reversed destination after BSWAP.
    destination_adds = [
        0x5D0F3A8E2C6B4197,
        0xA7E2D9C4B1F60853,
        0x3C6E9A1D5B7F2840,
        0x8F4A2C1E9B7D3F61,
    ]
    swapped_xors = [
        int.from_bytes(value.to_bytes(8, "little"), "big")
        for value in xor_constants
    ]
    transform_results: list[dict[str, object]] = []

    for index, (xor_constant, add_constant) in enumerate(
        zip(swapped_xors, destination_adds, strict=True)
    ):
        projections: list[dict[str, object]] = []
        first_impossible = None
        for width in range(2, 11):
            mask = (1 << width) - 1
            projected_xor = xor_constant & mask
            projected_add = add_constant & mask
            lhs_at_zero = (projected_xor + projected_add) & mask
            solution = None
            for trailing_xor in range(1 << width):
                leading_add = lhs_at_zero ^ trailing_xor
                if all(
                    (((value ^ projected_xor) + projected_add) & mask)
                    == (((value + leading_add) & mask) ^ trailing_xor)
                    for value in range(1 << width)
                ):
                    solution = {
                        "leading_add": leading_add,
                        "trailing_xor": trailing_xor,
                    }
                    break
            projections.append({"width": width, "solution": solution})
            if solution is None and first_impossible is None:
                first_impossible = width

        uint64_top = 1 << 63
        remaining_xor = xor_constant ^ (xor_constant & uint64_top)
        transform_results.append(
            {
                "source_word": index,
                "xor_after_bswap": f"0x{xor_constant:016x}",
                "destination_add": f"0x{add_constant:016x}",
                "first_impossible_projection_width": first_impossible,
                "low_bit_projections": projections,
                "top_bit_folded": bool(xor_constant & uint64_top),
                "remaining_xor_after_top_bit_fold": f"0x{remaining_xor:016x}",
                "instruction_removed_by_top_bit_fold": remaining_xor == 0,
            }
        )

    # Exhaust a smaller word to validate the general top-bit identity itself.
    top_bit_identity_width = 16
    top_bit_identity = all(
        (value ^ (1 << (top_bit_identity_width - 1)))
        == ((value + (1 << (top_bit_identity_width - 1)))
            & ((1 << top_bit_identity_width) - 1))
        for value in range(1 << top_bit_identity_width)
    )

    byte_swap = [8 * (7 - bit // 8) + bit % 8 for bit in range(64)]
    pair_results: list[dict[str, object]] = []
    for second_rotation, first_rotation in ((14, 43), (43, 14), (29, 7), (7, 29)):
        first_rotate = [(bit + first_rotation) % 64 for bit in range(64)]
        second_rotate = [(bit + second_rotation) % 64 for bit in range(64)]
        pair = [
            byte_swap[second_rotate[byte_swap[first_rotate[bit]]]]
            for bit in range(64)
        ]
        matches: list[str] = []
        for rotation in range(64):
            rotate = [(bit + rotation) % 64 for bit in range(64)]
            if pair == rotate:
                matches.append(f"ROL({rotation})")
            if pair == [byte_swap[rotate[bit]] for bit in range(64)]:
                matches.append(f"BSWAP_ROL({rotation})")
            if pair == [rotate[byte_swap[bit]] for bit in range(64)]:
                matches.append(f"ROL_BSWAP({rotation})")

        visited: set[int] = set()
        cycle_lengths: list[int] = []
        for bit in range(64):
            if bit in visited:
                continue
            current = bit
            length = 0
            while current not in visited:
                visited.add(current)
                length += 1
                current = pair[current]
            cycle_lengths.append(length)
        pair_results.append(
            {
                "rotations": [first_rotation, second_rotation],
                "simple_matches": matches,
                "cycle_lengths": sorted(cycle_lengths),
            }
        )

    report = {
        "schema_version": 1,
        "analysis": "challenge_simple_operation_fold_checks",
        "xor_add_equation": "(x xor C) + A == (x + B) xor E",
        "projection_argument": (
            "A 64-bit identity must hold after reduction modulo 2^n; one "
            "impossible low-bit projection therefore disproves the identity."
        ),
        "transforms": transform_results,
        "top_bit_identity_exhaustive_width": top_bit_identity_width,
        "top_bit_identity_pass": top_bit_identity,
        "two_round_linear_parts": pair_results,
    }

    for transform in transform_results:
        print(
            f"source={transform['source_word']} "
            f"first_impossible_width="
            f"{transform['first_impossible_projection_width']} "
            f"top_bit_folded={transform['top_bit_folded']} "
            f"remaining_xor={transform['remaining_xor_after_top_bit_fold']}"
        )
    for pair in pair_results:
        print(
            f"rotations={pair['rotations']} matches={pair['simple_matches']} "
            f"cycles={pair['cycle_lengths']}"
        )
    print(f"top_bit_identity_width16={top_bit_identity}")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"json={args.json.resolve()}")


if __name__ == "__main__":
    main()
