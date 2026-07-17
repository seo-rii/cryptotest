#!/usr/bin/env python3
"""Recover and independently verify the challenge 2 permutation."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile


MASK = (1 << 64) - 1
CONSTANTS1 = [
    0x8F4A2C1E9B7D3F61,
    0x3C6E9A1D5B7F2840,
    0xA7E2D9C4B1F60853,
    0x5D0F3A8E2C6B4197,
]
CONSTANTS2 = [
    0xE7B92D4A6C1F8035,
    0x1A4F8C3E9D2B6074,
    0xC3F05A2E8D6194B7,
    0x6B2E9D1A4F7C3085,
]


def rotl64(value: int, amount: int) -> int:
    return ((value << amount) & MASK) | (value >> (64 - amount))


def reverse_bytes(words: list[int]) -> list[int]:
    data = b"".join(word.to_bytes(8, "little") for word in words)
    reversed_data = bytes(data[31 - i] for i in range(32))
    return [int.from_bytes(reversed_data[i * 8 : (i + 1) * 8], "little") for i in range(4)]


def parse_vectors(text: str) -> list[tuple[list[int], list[int]]]:
    lines = text.splitlines()
    vectors: list[tuple[list[int], list[int]]] = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("#"):
            vectors.append(
                (
                    [int(x, 16) for x in lines[i + 2].split()],
                    [int(x, 16) for x in lines[i + 4].split()],
                )
            )
            i += 5
        else:
            i += 1
    return vectors


def one_round(words: list[int], rotations: list[int]) -> list[int]:
    words = [rotl64(words[i], rotations[i]) for i in range(4)]
    words = [words[i] ^ CONSTANTS2[i] for i in range(4)]
    words = reverse_bytes(words)
    return [(words[i] + CONSTANTS1[i]) & MASK for i in range(4)]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / "problems" / "2_암호구현.zip") as archive:
        vectors = parse_vectors(archive.read("code/testvector.txt").decode())
        tv20 = archive.read("code/testvector_20round.txt").decode().split()

    if len(vectors) != 1000:
        raise RuntimeError(f"expected 1000 one-round vectors, got {len(vectors)}")

    # Intersect the rotation candidates from every vector.  This avoids
    # accidentally selecting an equivalent rotation for a degenerate word.
    rotation_candidates = [set(range(1, 64)) for _ in range(4)]
    for vector_input, vector_output in vectors:
        before_add = [(vector_output[i] - CONSTANTS1[i]) & MASK for i in range(4)]
        before_shuffle = reverse_bytes(before_add)
        before_xor = [before_shuffle[i] ^ CONSTANTS2[i] for i in range(4)]
        for word_index in range(4):
            rotation_candidates[word_index] &= {
                rotation
                for rotation in range(1, 64)
                if rotl64(vector_input[word_index], rotation) == before_xor[word_index]
            }

    if any(len(candidates) != 1 for candidates in rotation_candidates):
        raise RuntimeError(f"rotations are not unique: {rotation_candidates}")
    rotations = [next(iter(candidates)) for candidates in rotation_candidates]

    print("round order: rotate -> xor -> reverse-byte shuffle -> add")
    print(f"rot = {{{rotations[0]}, {rotations[1]}, {rotations[2]}, {rotations[3]}}}")
    print(f"one-round vectors checked: {len(vectors)}")
    print(f"all one-round vectors pass: {all(one_round(inp, rotations) == out for inp, out in vectors)}")

    state = [int(x, 16) for x in tv20[1:5]]
    expected = [int(x, 16) for x in tv20[6:10]]
    for _ in range(20):
        state = one_round(state, rotations)
    print(f"20-round output: {' '.join(f'{x:016x}' for x in state)}")
    print(f"20-round vector passes: {state == expected}")

    print("\ncontest.c reconstruction points:")
    print("const unsigned int rot[4] = { 43, 7, 29, 14 };")
    print("permute_one_round: rotate_words_left_64wise -> xor_constants_256wise -> shuffle_bytes_256 -> add_constants_64wise")
    print("optimized reverse shuffle: word reversal plus four BSWAP64 operations")
    print("permute_20rounds: apply the same optimized round 20 times")


if __name__ == "__main__":
    main()
