#!/usr/bin/env python3
"""Check challenge 7 mask orientation and extraction variants."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
P_BITS = 1024


def load_constants():
    spec = importlib.util.spec_from_file_location(
        "investigate_07", ROOT / "solutions" / "investigate_07_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reverse_bits(value: int, bits: int = P_BITS) -> int:
    reversed_value = 0
    for bit in range(bits):
        if (value >> bit) & 1:
            reversed_value |= 1 << (bits - 1 - bit)
    return reversed_value


def summarize_mask(mask: int, bits: int = P_BITS) -> tuple[int, list[tuple[int, int, int]]]:
    runs: list[tuple[int, int, int]] = []
    bit = 0
    while bit < bits:
        if (mask >> bit) & 1:
            bit += 1
            continue
        start = bit
        while bit < bits and ((mask >> bit) & 1) == 0:
            bit += 1
        runs.append((start, bit - 1, bit - start))
    return mask.bit_count(), runs


def main() -> None:
    c7 = load_constants()
    mask = int(c7.MASK_HEX.replace(" ", ""), 16)
    p_masked = int(c7.P_AND_MASK_HEX.replace(" ", ""), 16)
    variants = {
        "as_is": (mask, p_masked),
        "bit_reversed": (reverse_bits(mask), reverse_bits(p_masked)),
        "byte_reversed": (
            int.from_bytes(mask.to_bytes(P_BITS // 8, "big")[::-1], "big"),
            int.from_bytes(p_masked.to_bytes(P_BITS // 8, "big")[::-1], "big"),
        ),
    }

    for name, (variant_mask, variant_p_masked) in variants.items():
        known, runs = summarize_mask(variant_mask)
        inconsistent_bits = (variant_p_masked & ~variant_mask).bit_count()
        print(f"[{name}]")
        print(f"known bits: {known} / {P_BITS}")
        print(f"p_masked outside mask bits: {inconsistent_bits}")
        print("unknown runs:")
        for start, end, width in runs:
            print(f"  {start}..{end} ({width})")
        print()


if __name__ == "__main__":
    main()
