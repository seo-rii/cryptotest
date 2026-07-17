#!/usr/bin/env python3
"""Verify the recovered factors and decrypt challenge 7."""

from __future__ import annotations

from investigate_07_rsa_partial_bits import (
    CT_HEX,
    E,
    MASK_HEX,
    N_HEX,
    P_AND_MASK_HEX,
)


P = int(
    "ffa360d46885c534d186538179633fafc2c0548a2e24a2c1c878569f522939e3"
    "8ff75ead1bcd442a834974a52e3ac66c1bc2ee00d63e2de4c436d2ca740a6246"
    "99e1a1af94045c63261323cb723a7ba1b3c00bbbb6a4e534c11469e73ddbb2e5"
    "0b0bc2461fcbac0726360c2c0ac9450a9a892cbf1d98ceee48827591ccc593c9",
    16,
)
Q = int(
    "e557fa8670389cb60c84416a65742a74fd11ed33b1631f787e92b90887b5391d"
    "acba00a386911bf8a8fbd57430b9b26e455329405ffe289e20616fe3b5562ea9"
    "b533f8f8db94bb8dcd280a6af056108e176008d3655428ad0ac6396318ba0f6e"
    "fe496eac3f8585675bfed67081e0c518be5685e4daf7060abe1c58b73cc5f1e9",
    16,
)
EXPECTED_PLAINTEXT = b"FLAG{d1rty_b1t_l34k_c0pp3rsm1th_m33ts_str4t3gy}"


def compact_hex(value: str) -> int:
    return int(value.replace(" ", ""), 16)


def main() -> None:
    n = compact_hex(N_HEX)
    ct = compact_hex(CT_HEX)
    mask = compact_hex(MASK_HEX)
    leaked = compact_hex(P_AND_MASK_HEX)

    assert P * Q == n
    assert n % P == 0 and n // P == Q
    assert P & mask == leaked

    phi = (P - 1) * (Q - 1)
    private_exponent = pow(E, -1, phi)
    message = pow(ct, private_exponent, n)
    plaintext = message.to_bytes((message.bit_length() + 7) // 8, "big")

    assert plaintext == EXPECTED_PLAINTEXT
    assert pow(message, E, n) == ct

    print(f"p = {P}")
    print(f"q = {Q}")
    print(f"plaintext = {plaintext.decode('ascii')}")
    print("verification = factor, leak, and re-encryption checks passed")


if __name__ == "__main__":
    main()
