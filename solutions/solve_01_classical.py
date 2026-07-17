#!/usr/bin/env python3
"""Solve/inspect challenge 1: Caesar vs line-reset Vigenere."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from zipfile import ZipFile


ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ENGLISH_FREQ = [
    8.17,
    1.50,
    2.78,
    4.25,
    12.70,
    2.23,
    2.02,
    6.09,
    6.97,
    0.15,
    0.77,
    4.03,
    2.41,
    6.75,
    7.51,
    1.93,
    0.10,
    5.99,
    6.33,
    9.06,
    2.76,
    0.98,
    2.36,
    0.15,
    1.97,
    0.07,
]


def clean(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch in ALPHABET)


def index_of_coincidence(text: str) -> float:
    counts = Counter(text)
    n = len(text)
    return sum(v * (v - 1) for v in counts.values()) / (n * (n - 1))


def caesar_decrypt(text: str, shift: int) -> str:
    return "".join(ALPHABET[(ALPHABET.index(ch) - shift) % 26] for ch in text)


def chi_squared(text: str) -> float:
    counts = Counter(text)
    n = len(text)
    return sum(
        (counts.get(ALPHABET[i], 0) - n * ENGLISH_FREQ[i] / 100) ** 2
        / (n * ENGLISH_FREQ[i] / 100)
        for i in range(26)
    )


def best_caesar(text: str) -> tuple[float, int, str]:
    return min((chi_squared(caesar_decrypt(text, k)), k, caesar_decrypt(text, k)) for k in range(26))


def recover_line_reset_key(caesar_lines: list[str], vigenere_lines: list[str], caesar_shift: int) -> str:
    key_stream: list[int] = []
    for left, right in zip(caesar_lines, vigenere_lines):
        plain = caesar_decrypt(left, caesar_shift)
        for p, c in zip(plain, right):
            key_stream.append((ALPHABET.index(c) - ALPHABET.index(p)) % 26)

    for period in range(1, 12):
        ok = True
        for left, right in zip(caesar_lines, vigenere_lines):
            plain = caesar_decrypt(left, caesar_shift)
            line_keys = [
                (ALPHABET.index(c) - ALPHABET.index(p)) % 26
                for p, c in zip(plain, right)
            ]
            if any(value != line_keys[i % period] for i, value in enumerate(line_keys)):
                ok = False
                break
        if ok:
            return "".join(ALPHABET[x] for x in key_stream[:period])
    raise RuntimeError("could not identify a short line-reset key")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / "problems" / "1_암호분석.zip") as archive:
        ct1_raw = archive.read("ciphertexts1.txt").decode()
        ct2_raw = archive.read("ciphertexts2.txt").decode()

    ct1_lines = [clean(line) for line in ct1_raw.splitlines() if clean(line)]
    ct2_lines = [clean(line) for line in ct2_raw.splitlines() if clean(line)]
    ct1 = "".join(ct1_lines)
    ct2 = "".join(ct2_lines)

    print(f"ciphertexts1 length={len(ct1)} IC={index_of_coincidence(ct1):.6f}")
    print(f"ciphertexts2 length={len(ct2)} IC={index_of_coincidence(ct2):.6f}")

    _, caesar_shift, caesar_plain = best_caesar(ct1)
    key = recover_line_reset_key(ct1_lines, ct2_lines, caesar_shift)
    print(f"ciphertexts1 is Caesar, shift={caesar_shift}")
    print(f"ciphertexts2 is Vigenere with key={key!r}, reset at each line")
    print(f"Caesar plaintext prefix: {caesar_plain[:120]}")

    samples = [
        "NKRRUZNOYOYGIRGYYOIGRIOVNKXGTGREYOYVXUHRKSLUXZNKIXEVZGTGREYOYIUSVKZOZOUTIUTMXGZARGZOUTYUTMKZZOTMZNKIUXXKIZGTYCKX",
        "ROVVYDRSCSCKMVKCCSMKVMSZROBKXKVICSCZBYLVOWPYBDROMBIZDKXKVICSCMYWZODSDSYXMYXQBKDEVKDSYXCYXQODDSXQDROMYBBOMDKXCGOB",
        "DRKXUIYEPYBIYEBZKBDSMSZKDSYXGOGSCRIYEKVVDROLOCDSXIYEBPEDEBOOXNOKFYBC",
        "ZNGTQEUALUXEUAXVGXZOIOVGZOUTCKCOYNEUAGRRZNKHKYZOTEUAXLAZAXKKTJKGBUXY",
    ]
    for i, sample in enumerate(samples, 1):
        score, shift, plain = best_caesar(clean(sample))
        print(f"sample {i}: Caesar-like, shift={shift}, chi2={score:.2f}, plaintext={plain}")


if __name__ == "__main__":
    main()
