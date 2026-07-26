#!/usr/bin/env python3
"""Recover and verify the challenge 8 AES-like master key."""

from __future__ import annotations

from collections.abc import Iterator
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
INV_SBOX = [0] * 256
for index, value in enumerate(SBOX):
    INV_SBOX[value] = index

PERMS = [
    list(range(16)),
    [5, 8, 6, 3, 15, 14, 13, 12, 11, 10, 2, 1, 0, 4, 7, 9],
    [6, 10, 5, 12, 3, 2, 15, 9, 1, 4, 8, 11, 13, 7, 0, 14],
    [10, 3, 1, 7, 8, 11, 9, 5, 2, 6, 12, 15, 4, 0, 14, 13],
    [14, 11, 7, 5, 10, 1, 13, 12, 0, 6, 2, 4, 8, 15, 3, 9],
    [15, 10, 12, 1, 14, 8, 13, 4, 2, 3, 0, 5, 11, 7, 6, 9],
    [1, 5, 7, 14, 15, 8, 0, 4, 9, 13, 3, 6, 12, 2, 10, 11],
]
MC_KEY_ROUNDS = {1, 2, 5, 6}


def xtime(value: int) -> int:
    return ((value << 1) & 0xFF) ^ (0x1B if value & 0x80 else 0)


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


def inv_shift_rows(state: list[int]) -> list[int]:
    out = state[:]
    for row in range(4):
        values = [state[row + 4 * col] for col in range(4)]
        values = values[-row:] + values[:-row]
        for col, value in enumerate(values):
            out[row + 4 * col] = value
    return out


def mix_columns(state: list[int]) -> list[int]:
    out = [0] * 16
    for col in range(4):
        out[4 * col : 4 * col + 4] = mix_column(state[4 * col : 4 * col + 4])
    return out


def inv_mix_columns(state: list[int]) -> list[int]:
    out = [0] * 16
    for col in range(4):
        out[4 * col : 4 * col + 4] = inv_mix_column(state[4 * col : 4 * col + 4])
    return out


def round_function(state: list[int]) -> list[int]:
    return mix_columns(shift_rows([SBOX[value] for value in state]))


def inverse_round_function(after_round_function: list[int]) -> list[int]:
    z = inv_mix_columns(after_round_function)
    y = inv_shift_rows(z)
    return [INV_SBOX[value] for value in y]


def round_keys(master_key: list[int]) -> list[list[int]]:
    keys: list[list[int]] = []
    for round_index, perm in enumerate(PERMS):
        key = [master_key[index] for index in perm]
        if round_index in MC_KEY_ROUNDS:
            key = mix_columns(key)
        keys.append(key)
    return keys


def encrypt(block: bytes, keys: list[list[int]]) -> bytes:
    state = list(block)
    for key in keys:
        transformed = round_function(state)
        state = [transformed[i] ^ key[i] for i in range(16)]
    return bytes(state)


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


def recover_key(leaks: dict[tuple[int, int], str], plaintext: bytes, ciphertext: bytes) -> bytes:
    index = 28178
    p = list(plaintext[16 * index : 16 * (index + 1)])
    c = list(ciphertext[16 * index : 16 * (index + 1)])
    before_x1 = round_function(p)

    k0 = before_x1[0] ^ byte_candidates(leaks[(1, 0)])[0]
    k1 = inv_mix_column(c[0:4])[0] ^ SBOX[byte_candidates(leaks[(6, 0)])[0]]
    k3 = inv_mix_column(c[8:12])[2] ^ SBOX[byte_candidates(leaks[(6, 2)])[0]]

    x3_values = [byte_candidates(leaks[(3, i)]) for i in range(16)]
    x4_values = {i: byte_candidates(leaks[(4, i)]) for i in (0, 5, 10, 15)}
    x3_records = []
    for x3 in itertools.product(*x3_values):
        f3 = round_function(list(x3))
        x3_records.append(
            (
                list(x3),
                inv_mix_column(list(x3[0:4])),
                inv_mix_column(list(x3[4:8])),
                inv_mix_column(list(x3[8:12])),
                inv_mix_column(list(x3[12:16])),
                f3[0],
                f3[5],
                f3[10],
                f3[15],
            )
        )

    hits: set[bytes] = set()
    for x2_column in itertools.product(*(byte_candidates(leaks[(2, i)]) for i in range(4))):
        inv_x2 = inv_mix_column(list(x2_column))
        k5 = inv_x2[0] ^ SBOX[before_x1[0] ^ k0]
        k8 = inv_x2[1] ^ SBOX[before_x1[5] ^ k5]
        needed_sbox = k3 ^ inv_x2[3]
        k15 = before_x1[15] ^ INV_SBOX[needed_sbox]
        s_x2 = [SBOX[value] for value in x2_column]

        for x3, im0, im1, im2, im3, f30, f35, f310, f315 in x3_records:
            if (im2[2] ^ s_x2[2]) != k8:
                continue
            k6 = im0[0] ^ s_x2[0]
            k9 = im1[3] ^ s_x2[3]
            k7 = im3[1] ^ s_x2[1]
            for x4_0 in x4_values[0]:
                k10 = f30 ^ x4_0
                if (inv_x2[2] ^ SBOX[before_x1[10] ^ k10]) != k6:
                    continue
                for k11 in (f35 ^ value for value in x4_values[5]):
                    for k12 in (f310 ^ value for value in x4_values[10]):
                        for k13 in (f315 ^ value for value in x4_values[15]):
                            partial = [None] * 16
                            for key_index, value in (
                                (0, k0), (1, k1), (3, k3), (5, k5),
                                (6, k6), (7, k7), (8, k8), (9, k9),
                                (10, k10), (11, k11), (12, k12), (13, k13), (15, k15),
                            ):
                                partial[key_index] = value
                            for maybe in complete_partial_keys(partial, p, x3):
                                key = bytes(maybe)
                                if encrypt(bytes(p), round_keys(maybe)) == bytes(c):
                                    hits.add(key)

    if len(hits) != 1:
        raise RuntimeError(f"expected one key candidate, got {len(hits)}")
    return hits.pop()


def complete_partial_keys(
    partial: list[int | None],
    plaintext_block: list[int],
    x3: list[int],
) -> Iterator[list[int]]:
    before_x1 = round_function(plaintext_block)
    probe = [0 if value is None else value for value in partial]
    rk2_col0 = round_keys(probe)[2][0:4]
    inv_col0 = inv_mix_column([x3[i] ^ rk2_col0[i] for i in range(4)])
    target_x2_5 = INV_SBOX[inv_col0[1]]
    target_x2_10 = INV_SBOX[inv_col0[2]]
    target_x2_15 = INV_SBOX[inv_col0[3]]

    k2_candidates = []
    for k2 in range(256):
        if x2_byte10(before_x1, partial, k2) == target_x2_10:
            k2_candidates.append(k2)
    if not k2_candidates:
        return

    k4_candidates = []
    for k4 in range(256):
        if x2_byte15(before_x1, partial, k4) == target_x2_15:
            k4_candidates.append(k4)
    if not k4_candidates:
        return

    for k2 in k2_candidates:
        for k4 in k4_candidates:
            for k14 in range(256):
                key = [0 if value is None else value for value in partial]
                key[2] = k2
                key[4] = k4
                key[14] = k14
                if x2_byte5(before_x1, key, k4, k14) != target_x2_5:
                    continue
                x2_round1 = x2_from_key(before_x1, key)
                x2_round2 = inverse_round_function([x3[i] ^ round_keys(key)[2][i] for i in range(16)])
                if x2_round1 == x2_round2:
                    yield key


def x2_byte10(before_x1: list[int], partial: list[int | None], k2: int) -> int:
    key = [0 if value is None else value for value in partial]
    key[2] = k2
    diagonal = [before_x1[i] ^ key[i] for i in (8, 13, 2, 7)]
    mixed = mix_column([SBOX[value] for value in diagonal])
    return mixed[2] ^ mix_column([key[i] for i in (11, 10, 2, 1)])[2]


def x2_byte15(before_x1: list[int], partial: list[int | None], k4: int) -> int:
    key = [0 if value is None else value for value in partial]
    key[4] = k4
    diagonal = [before_x1[i] ^ key[i] for i in (12, 1, 6, 11)]
    mixed = mix_column([SBOX[value] for value in diagonal])
    return mixed[3] ^ mix_column([key[i] for i in (0, 4, 7, 9)])[3]


def x2_byte5(before_x1: list[int], key: list[int], k4: int, k14: int) -> int:
    key[4] = k4
    key[14] = k14
    diagonal = [before_x1[i] ^ key[i] for i in (4, 9, 14, 3)]
    mixed = mix_column([SBOX[value] for value in diagonal])
    return mixed[1] ^ mix_column([key[i] for i in (15, 14, 13, 12)])[1]


def x2_from_key(before_x1: list[int], key: list[int]) -> list[int]:
    x1 = [before_x1[i] ^ key[i] for i in range(16)]
    transformed = round_function(x1)
    return [transformed[i] ^ round_keys(key)[1][i] for i in range(16)]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / "problems" / "8_블록암호.zip") as archive:
        plaintext = archive.read("plaintext.bin")
        ciphertext = archive.read("ciphertext.bin")
        leaks = parse_leaks(archive.read("leaked.txt").decode(errors="ignore"))

    key = recover_key(leaks, plaintext, ciphertext)
    keys = round_keys(list(key))
    mismatches = [
        index
        for index in range(len(plaintext) // 16)
        if encrypt(plaintext[16 * index : 16 * (index + 1)], keys)
        != ciphertext[16 * index : 16 * (index + 1)]
    ]
    print(f"master key = {key.hex()}")
    print(f"verified pairs = {len(plaintext) // 16}")
    print(f"mismatches = {len(mismatches)}")
    if mismatches:
        raise RuntimeError(f"first mismatch at pair {mismatches[0]}")
    submitted_key = (
        root / "submissions" / "08" / "master_key.txt"
    ).read_text(encoding="ascii").strip()
    if submitted_key != key.hex():
        raise RuntimeError("submissions/08/master_key.txt is out of sync")
    print("submission key check = PASS")


if __name__ == "__main__":
    main()
