#!/usr/bin/env python3
"""Empirical separability checks for challenge 2's exact 20-round word maps."""

from random import Random


A = [
    0x8F4A2C1E9B7D3F61,
    0x3C6E9A1D5B7F2840,
    0xA7E2D9C4B1F60853,
    0x5D0F3A8E2C6B4197,
]
K = [
    0xE7B92D4A6C1F8035,
    0x1A4F8C3E9D2B6074,
    0xC3F05A2E8D6194B7,
    0x6B2E9D1A4F7C3085,
]
R = [43, 7, 29, 14]
MASK = (1 << 64) - 1


def transform(value: int, index: int) -> int:
    rotation = R[index]
    value = ((value << rotation) | (value >> (64 - rotation))) & MASK
    value ^= K[index]
    value = int.from_bytes(value.to_bytes(8, "little"), "big")
    return (value + A[3 - index]) & MASK


def compose20(value: int, start: int) -> int:
    index = start
    for _ in range(20):
        value = transform(value, index)
        index = 3 - index
    return value


def influence_and_mixed_derivatives() -> None:
    for start in range(4):
        generator = Random(0x20260718 + start)
        influence = [[False] * 8 for _ in range(8)]
        for _ in range(512):
            value = generator.getrandbits(64)
            output = compose20(value, start)
            for input_bit in range(64):
                difference = output ^ compose20(value ^ (1 << input_bit), start)
                for output_byte in range(8):
                    if difference & (0xFF << (8 * output_byte)):
                        influence[output_byte][input_bit // 8] = True

        xor_nonzero = 0
        sum_nonzero = 0
        for _ in range(1_000):
            value = generator.getrandbits(64)
            byte_a, byte_b = generator.sample(range(8), 2)
            delta_a = generator.randrange(1, 256) << (8 * byte_a)
            delta_b = generator.randrange(1, 256) << (8 * byte_b)
            f0 = compose20(value, start)
            fa = compose20(value ^ delta_a, start)
            fb = compose20(value ^ delta_b, start)
            fab = compose20(value ^ delta_a ^ delta_b, start)
            xor_nonzero += (f0 ^ fa ^ fb ^ fab) != 0
            sum_nonzero += ((f0 - fa - fb + fab) & MASK) != 0

        edges = sum(map(sum, influence))
        print(
            f"start={start} byte_influence={edges}/64 "
            f"mixed_xor={xor_nonzero}/1000 mixed_modsum={sum_nonzero}/1000"
        )


def restricted_anf() -> None:
    """Measure degree on one fixed 16-dimensional coordinate subspace."""
    bits = [9, 37, 7, 14, 63, 18, 55, 34, 5, 62, 6, 13, 56, 39, 49, 61]
    base = 0xA30748FAAD482BBD
    values = []
    for mask in range(1 << len(bits)):
        value = base
        for position, bit in enumerate(bits):
            if mask & (1 << position):
                value ^= 1 << bit
        values.append(compose20(value, 0))

    # Vector-valued Moebius transform: each uint64 holds all output bits.
    for position in range(len(bits)):
        bit = 1 << position
        for mask in range(1 << len(bits)):
            if mask & bit:
                values[mask] ^= values[mask ^ bit]

    degrees = [0] * 64
    for mask, coefficient in enumerate(values):
        degree = mask.bit_count()
        while coefficient:
            output_bit = (coefficient & -coefficient).bit_length() - 1
            degrees[output_bit] = max(degrees[output_bit], degree)
            coefficient &= coefficient - 1
    print(
        "restricted_anf_dimension=16 "
        f"degree_min={min(degrees)} degree_median={sorted(degrees)[32]} "
        f"degree_max={max(degrees)} degree16_outputs={degrees.count(16)}/64"
    )


if __name__ == "__main__":
    influence_and_mixed_derivatives()
    restricted_anf()
