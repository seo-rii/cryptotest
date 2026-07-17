#!/usr/bin/env python3
"""Analyze challenge 8 leaked AES-like states and recover direct key bytes."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
import itertools
import re


SBOX = [
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
]


def xtime(x: int) -> int:
    return ((x << 1) & 0xFF) ^ (0x1B if x & 0x80 else 0)


def gf_mul(left: int, right: int) -> int:
    result = 0
    while right:
        if right & 1:
            result ^= left
        left = xtime(left)
        right >>= 1
    return result


def mix_column(column: list[int]) -> list[int]:
    a0, a1, a2, a3 = column
    return [
        gf_mul(2, a0) ^ gf_mul(3, a1) ^ a2 ^ a3,
        a0 ^ gf_mul(2, a1) ^ gf_mul(3, a2) ^ a3,
        a0 ^ a1 ^ gf_mul(2, a2) ^ gf_mul(3, a3),
        gf_mul(3, a0) ^ a1 ^ a2 ^ gf_mul(2, a3),
    ]


def inv_mix_column(column: list[int]) -> list[int]:
    a0, a1, a2, a3 = column
    return [
        gf_mul(14, a0) ^ gf_mul(11, a1) ^ gf_mul(13, a2) ^ gf_mul(9, a3),
        gf_mul(9, a0) ^ gf_mul(14, a1) ^ gf_mul(11, a2) ^ gf_mul(13, a3),
        gf_mul(13, a0) ^ gf_mul(9, a1) ^ gf_mul(14, a2) ^ gf_mul(11, a3),
        gf_mul(11, a0) ^ gf_mul(13, a1) ^ gf_mul(9, a2) ^ gf_mul(14, a3),
    ]


def shift_rows(state: list[int]) -> list[int]:
    out = state[:]
    for row in range(4):
        values = [state[row + 4 * col] for col in range(4)]
        values = values[row:] + values[:row]
        for col, value in enumerate(values):
            out[row + 4 * col] = value
    return out


def mix_columns(state: list[int]) -> list[int]:
    out = [0] * 16
    for col in range(4):
        out[4 * col : 4 * col + 4] = mix_column(state[4 * col : 4 * col + 4])
    return out


def byte_candidates(pattern: str) -> list[int]:
    return [
        value
        for value in range(256)
        if all(bit == "-" or bit == actual for bit, actual in zip(pattern, f"{value:08b}"))
    ]


def parse_leaks(text: str) -> dict[tuple[int, int], str]:
    leaks: dict[tuple[int, int], str] = {}
    for line in text.replace("\r", "").splitlines():
        match = re.match(r"X\^(\d+)\[(\d+)\]:\s*([01-]{8})", line.strip())
        if match:
            leaks[(int(match.group(1)), int(match.group(2)))] = match.group(3)
    return leaks


def format_set(values: set[int]) -> str:
    return " ".join(f"{value:02x}" for value in sorted(values))


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / "problems" / "8_블록암호.zip") as archive:
        plaintext = archive.read("plaintext.bin")
        ciphertext = archive.read("ciphertext.bin")
        leaks = parse_leaks(archive.read("leaked.txt").decode(errors="ignore"))

    index = 28178
    p = plaintext[16 * index : 16 * (index + 1)]
    c = ciphertext[16 * index : 16 * (index + 1)]
    print(f"P[{index}] = {p.hex()}")
    print(f"C[{index}] = {c.hex()}")
    print(
        "leak X^0/X^7 match files =",
        all(byte_candidates(leaks[(0, i)]) == [p[i]] for i in range(16))
        and all(byte_candidates(leaks[(7, i)]) == [c[i]] for i in range(16)),
    )

    leaked_x1_0 = byte_candidates(leaks[(1, 0)])[0]
    before_ark0 = mix_columns(shift_rows([SBOX[b] for b in p]))
    k0_byte0 = before_ark0[0] ^ leaked_x1_0

    # Since k6 = MC(K[1], K[5], K[7], K[14], ...), applying InvMC to
    # C column 0 cancels the MC around that key column. The known X^6[0]
    # then gives K[1] directly. X^6[2] similarly gives K[3].
    inv_c_col0 = inv_mix_column(list(c[0:4]))
    inv_c_col2 = inv_mix_column(list(c[8:12]))
    k1 = inv_c_col0[0] ^ SBOX[byte_candidates(leaks[(6, 0)])[0]]
    k3 = inv_c_col2[2] ^ SBOX[byte_candidates(leaks[(6, 2)])[0]]

    print(f"Under standard AES column-major state layout, K[0] = {k0_byte0:#04x}")
    print(f"Directly from X^6[0], K[1] = {k1:#04x}")
    print(f"Directly from X^6[2], K[3] = {k3:#04x}")

    round3_perm = [10, 3, 1, 7, 8, 11, 9, 5, 2, 6, 12, 15, 4, 0, 14, 13]
    candidate_sets: dict[int, set[int]] = {}
    for outpos in (0, 5, 10, 15):
        row = outpos % 4
        col = outpos // 4
        deps = [dep_row + 4 * ((col + dep_row) % 4) for dep_row in range(4)]
        candidates: set[int] = set()
        for x3_values in itertools.product(*(byte_candidates(leaks[(3, dep)]) for dep in deps)):
            mixed = mix_column([SBOX[value] for value in x3_values])
            for x4_value in byte_candidates(leaks[(4, outpos)]):
                candidates.add(mixed[row] ^ x4_value)
        candidate_sets[round3_perm[outpos]] = candidates

    for key_index in (10, 11, 12, 13):
        candidates = candidate_sets[key_index]
        print(f"K[{key_index}] candidates ({len(candidates)}) = {format_set(candidates)}")

    # X^2[0..3] has only 16 byte-column candidates. Linearity of MC gives:
    # InvMC(X^2 column 0) = SB(X^1 diagonal) xor [K5, K8, K6, K3].
    # Combining this with known K[3] and the K[10] candidates leaves a
    # compact relation among K5, K8, K6, K10, and K15.
    combined = []
    x2_columns = itertools.product(*(byte_candidates(leaks[(2, i)]) for i in range(4)))
    for x2_column in x2_columns:
        inv_x2 = inv_mix_column(list(x2_column))
        k5 = inv_x2[0] ^ SBOX[before_ark0[0] ^ k0_byte0]
        k8 = inv_x2[1] ^ SBOX[before_ark0[5] ^ k5]
        needed_sbox = k3 ^ inv_x2[3]
        if needed_sbox not in SBOX:
            continue
        k15 = before_ark0[15] ^ SBOX.index(needed_sbox)
        for k10 in candidate_sets[10]:
            k6 = inv_x2[2] ^ SBOX[before_ark0[10] ^ k10]
            combined.append((k5, k8, k10, k6, k15))

    print(f"combined X^2/K[3]/K[10] relation candidates = {len(combined)}")
    print(f"unique K[5] candidates ({len({row[0] for row in combined})}) = {format_set({row[0] for row in combined})}")
    print(f"unique K[8] candidates ({len({row[1] for row in combined})}) = {format_set({row[1] for row in combined})}")
    print(f"unique K[15] candidates ({len({row[4] for row in combined})}) = {format_set({row[4] for row in combined})}")
    print(f"unique K[6] candidates = {len({row[3] for row in combined})}")
    print("Status: partial recovery; run solve_08_aes_key.py for the full DS-style join.")


if __name__ == "__main__":
    main()
