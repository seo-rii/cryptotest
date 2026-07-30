#!/usr/bin/env python3
"""Inspect the partial-bit RSA instance from challenge 7."""

from __future__ import annotations


N_HEX = (
    "e505004fb5d34eb7 12d48ff4bbe8d27f c388133c6c0e7340 01061c0ee0a4edc6 "
    "37c04fe8dd376185 de8ba04d0ccdbabb 93ab7c371b88d92e 865eec42b028c61d "
    "d7004ebf2ebb5d69 d0a09142be5c9de4 da16e514eea31817 2ecda6cd192073eb "
    "afb1e02d522ec053 34590ea6d75960c4 937bf64f9700db17 7a4aa3da6aae6807 "
    "e5e32c0d0e428a0d b68d299f20c235d8 4ef459b0cf118286 59c31663c9ea8204 "
    "4b28152c89a9c36c 3ec4303bd36664fd 77fb02c58340bdae 21120326d83fc017 "
    "34bc90048dec9fe3 5f08c8fdc523abf8 4a91ec430f495672 37c3153a2035ff62 "
    "5613b6dc3e6cb14d 50e18b8a79b25d67 8465b3ad02f5b7d8 18a1e2d635a0baf1"
)
E = 65537
CT_HEX = (
    "8919342826ef3821 5af31e00c9290c4c 50ef9ff9e1afc591 47fab5b096361035 "
    "e85f5fc95b73b069 7813b57b831a807d 41bcbecde5b9e663 9e2845b14e395ed0 "
    "e5d995e63709ac0c 5ee2337228ee76bc bad857b14904aa2e 8e9997671908a634 "
    "d0d1dda1d062ce7f 2e3293ddec8f5cce 26029292d594a062 dcf317d2a8380f43 "
    "d72551889efceb87 6c8945a50382272e 76ed6b6fcdff1603 44e9e948e2b6e740 "
    "e78bedf25f30e2c7 eeb5f74686c8eadc 29cea04ff08cfd86 dfd3d2a1632bf04a "
    "d5cfa369892a2da4 0f0dc0098ce6b731 d841aab3d0c8b78e b69c4625c47c4ad7 "
    "158d49bb5d879581 e02bc525abe47f39 f699864bc5ce1de7 19430dae7aa5480b"
)
MASK_HEX = (
    "ffffffffffffffff fffffffff0ffffff ffffffffffffffff c00000000000fffe "
    "0000000000000000 000003ffe0000000 0000000000ffffff ffffffffffffffff "
    "ffffffffffffffff fffffff000000000 000003ffe0000000 00000000000001ff "
    "ffffffffffffffff fffffffffc3fffff ffffffffffffffff ffffffffffffffff"
)
P_AND_MASK_HEX = (
    "ffa360d46885c534 d186538170633faf c2c0548a2e24a2c1 c0000000000039e2 "
    "0000000000000000 000000a520000000 00000000003e2de4 c436d2ca740a6246 "
    "99e1a1af94045c63 261323c000000000 000003bba0000000 00000000000000e5 "
    "0b0bc2461fcbac07 26360c2c0809450a 9a892cbf1d98ceee 48827591ccc593c9"
)


def contiguous_ranges(values: list[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
        else:
            ranges.append((start, prev))
            start = prev = value
    ranges.append((start, prev))
    return ranges


def interval_bounds(ranges: list[tuple[int, int]]) -> list[int]:
    return [1 << (end - start + 1) for start, end in ranges]


def main() -> None:
    n = int(N_HEX.replace(" ", ""), 16)
    ct = int(CT_HEX.replace(" ", ""), 16)
    mask = int(MASK_HEX.replace(" ", ""), 16)
    p_known = int(P_AND_MASK_HEX.replace(" ", ""), 16)
    unknown_mask = ((1 << 1024) - 1) ^ mask
    unknown = [i for i in range(1024) if ((mask >> i) & 1) == 0]
    low_bits = min(unknown)
    low_modulus = 1 << low_bits
    p_low = p_known & (low_modulus - 1)
    q_low = (n * pow(p_low, -1, low_modulus)) % low_modulus
    print(f"known p bits: {mask.bit_count()} / 1024")
    print(f"unknown p bits: {len(unknown)}")
    print(f"N bit length: {n.bit_length()}")
    print(f"e: {E}")
    print(f"ct bit length: {ct.bit_length()}")
    print("unknown bit ranges, least-significant-bit indexed:")
    ranges = contiguous_ranges(unknown)
    for start, end in ranges:
        print(f"  {start}..{end} ({end - start + 1} bits)")
    print("multivariate p representation:")
    terms = [f"2^{start}*x{i}" for i, (start, _) in enumerate(ranges)]
    print(f"  p = p_known + {' + '.join(terms)}")
    print("unknown variable bounds:")
    for i, bound in enumerate(interval_bounds(ranges)):
        print(f"  0 <= x{i} < 2^{bound.bit_length() - 1}")
    print(f"sum of unknown interval sizes: {sum(end - start + 1 for start, end in ranges)} bits")
    print(f"low known bits of p: {p_low:#x}")
    print(f"derived q mod 2^{low_bits}: {q_low:#x}")
    print(f"low-bit product check: {(p_low * q_low - n) % low_modulus == 0}")
    print("derived q mod 2^210 after guessing p[150..153]:")
    for nibble in range(16):
        modulus = 1 << 210
        p_mod = (p_known & (modulus - 1)) | (nibble << 150)
        q_mod = (n * pow(p_mod, -1, modulus)) % modulus
        print(f"  p[150..153]={nibble:x}: q mod 2^210 = {q_mod:#x}")
    print("q high common prefix bits by p[920..923] guess:")
    for nibble in range(16):
        p_min = (p_known & ~(0xF << 920)) | (nibble << 920)
        p_max = p_min | (unknown_mask & ~(0xF << 920))
        q_min = n // p_max
        q_max = n // p_min
        common = 1024 - (q_min ^ q_max).bit_length()
        q_prefix = q_min >> (1024 - common)
        print(f"  p[920..923]={nibble:x}: {common} common q MSBs, prefix={q_prefix:#x}")
    print()
    print("Status: this is not brute-forceable in plain Python.")
    print("The natural complete route is a Coppersmith/lattice partial-key exposure attack")
    print("with the unknown bit intervals modeled as small variables.")


if __name__ == "__main__":
    main()
