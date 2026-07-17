#!/usr/bin/env python3
"""Recover the Dual_EC backdoor scalar and predict r3 for challenge 6."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from zipfile import ZipFile


P_FIELD = int("d9047b5f32dda5ca6f569b", 16)
A_CURVE = int("674fdf5b55923897a16f40", 16)
B_CURVE = int("1d0c9956783f6026e6c981", 16)
POINT_P = (int("5340e87bd80d1463a6ff8d", 16), int("94ebeb5ca5b3c685e00c20", 16))
POINT_Q = (int("4a05101411039decf537a5", 16), int("3395a009c2210836b63d4b", 16))
ORDER = int("2b674bdfd6fc4ba4ba751d", 16)
KNOWN_OUTPUTS = [
    int("b3939f4aadcc13ca74", 16),
    int("617985fad38ec3b1a3", 16),
    int("d8c20715ccc94d2283", 16),
]
JACOBIAN_INFINITY = (0, 1, 0)


def to_jacobian(point: tuple[int, int]) -> tuple[int, int, int]:
    return point[0] % P_FIELD, point[1] % P_FIELD, 1


def is_infinity(point: tuple[int, int, int]) -> bool:
    return point[2] % P_FIELD == 0


def jacobian_double(point: tuple[int, int, int]) -> tuple[int, int, int]:
    x1, y1, z1 = point
    if z1 == 0 or y1 % P_FIELD == 0:
        return JACOBIAN_INFINITY
    xx = x1 * x1 % P_FIELD
    yy = y1 * y1 % P_FIELD
    yyyy = yy * yy % P_FIELD
    zz = z1 * z1 % P_FIELD
    s = 2 * ((x1 + yy) * (x1 + yy) - xx - yyyy) % P_FIELD
    m = (3 * xx + A_CURVE * zz * zz) % P_FIELD
    t = (m * m - 2 * s) % P_FIELD
    x3 = t
    y3 = (m * (s - t) - 8 * yyyy) % P_FIELD
    z3 = ((y1 + z1) * (y1 + z1) - yy - zz) % P_FIELD
    return x3 % P_FIELD, y3, z3


def jacobian_add(left: tuple[int, int, int], right: tuple[int, int, int]) -> tuple[int, int, int]:
    if is_infinity(left):
        return right
    if is_infinity(right):
        return left

    x1, y1, z1 = left
    x2, y2, z2 = right
    z1z1 = z1 * z1 % P_FIELD
    z2z2 = z2 * z2 % P_FIELD
    u1 = x1 * z2z2 % P_FIELD
    u2 = x2 * z1z1 % P_FIELD
    s1 = y1 * z2 % P_FIELD * z2z2 % P_FIELD
    s2 = y2 * z1 % P_FIELD * z1z1 % P_FIELD
    if u1 == u2:
        if s1 != s2:
            return JACOBIAN_INFINITY
        return jacobian_double(left)

    h = (u2 - u1) % P_FIELD
    i = (2 * h) * (2 * h) % P_FIELD
    j = h * i % P_FIELD
    r = 2 * (s2 - s1) % P_FIELD
    v = u1 * i % P_FIELD
    x3 = (r * r - j - 2 * v) % P_FIELD
    y3 = (r * (v - x3) - 2 * s1 * j) % P_FIELD
    z3 = ((z1 + z2) * (z1 + z2) - z1z1 - z2z2) % P_FIELD * h % P_FIELD
    return x3, y3, z3


def scalar_mul(k: int, point: tuple[int, int]) -> tuple[int, int, int]:
    result = JACOBIAN_INFINITY
    base = to_jacobian(point)
    while k:
        if k & 1:
            result = jacobian_add(result, base)
        base = jacobian_double(base)
        k >>= 1
    return result


def affine_x(point: tuple[int, int, int]) -> int:
    x, _, z = point
    return x * pow(z, -2, P_FIELD) % P_FIELD


def sqrt_mod(value: int) -> int | None:
    root = pow(value, (P_FIELD + 1) // 4, P_FIELD)
    return root if root * root % P_FIELD == value % P_FIELD else None


def recover_backdoor_scalar(rows: list[tuple[int, int, int]]) -> int:
    scale, offset, summary = rows[0]
    scale_inv = pow(scale, -1, ORDER)
    candidates = []
    for low_bits in range(1 << 20):
        candidate = (((summary << 20) | low_bits) - offset) * scale_inv % ORDER
        if all(((s * candidate + o) % ORDER) >> 20 == u for s, o, u in rows[1:]):
            candidates.append(candidate)
    if len(candidates) != 1:
        raise RuntimeError(f"expected one scalar, got {len(candidates)}")
    return candidates[0]


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / "problems" / "6_PRNG.zip") as archive:
        telemetry = archive.read("telemetry.csv").decode()

    rows = [
        (int(row["scale"], 16), int(row["offset"], 16), int(row["summary"], 16))
        for row in csv.DictReader(StringIO(telemetry))
    ]
    d = recover_backdoor_scalar(rows)
    print(f"backdoor scalar d = {d:#x}")
    print(f"P == d*Q: {(affine_x(scalar_mul(d, POINT_Q)), scalar_mul(d, POINT_Q)[1] * pow(scalar_mul(d, POINT_Q)[2], -3, P_FIELD) % P_FIELD) == POINT_P}")

    for low_bits in range(1 << 16):
        x = (KNOWN_OUTPUTS[0] << 16) | low_bits
        if x >= P_FIELD:
            continue
        y = sqrt_mod((x * x * x + A_CURVE * x + B_CURVE) % P_FIELD)
        if y is None:
            continue
        for candidate_y in (y, (-y) % P_FIELD):
            s1 = affine_x(scalar_mul(d, (x, candidate_y)))
            r1 = affine_x(scalar_mul(s1, POINT_Q)) >> 16
            if r1 != KNOWN_OUTPUTS[1]:
                continue
            s2 = affine_x(scalar_mul(s1, POINT_P))
            r2 = affine_x(scalar_mul(s2, POINT_Q)) >> 16
            if r2 != KNOWN_OUTPUTS[2]:
                continue
            s3 = affine_x(scalar_mul(s2, POINT_P))
            r3 = affine_x(scalar_mul(s3, POINT_Q)) >> 16
            print(f"recovered state s1 = {s1:#x}")
            print(f"predicted r3 = {r3:#x}")
            return
    raise RuntimeError("failed to lift r0 to a consistent state")


if __name__ == "__main__":
    main()
