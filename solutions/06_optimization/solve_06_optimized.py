#!/usr/bin/env python3
"""Optimized, independently verifiable solver for challenge 6.

The solver keeps the original attack but removes its largest implementation costs:

* Euclidean floor sums replace the telemetry ``2^20`` enumeration;
* the two square roots of one x-coordinate are not both tested, because scalar
  multiplication negates y but leaves the recovered affine x-coordinate equal;
* width-5 wNAF reduces arbitrary-point additions; and
* multiplication by the fixed output point Q uses a byte-comb table.

The default ``auto`` backend uses gmpy2 when it is installed and otherwise stays
with Python integers.  ``--backend int`` is dependency-free and remains useful as
an apples-to-apples optimized-Python baseline.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from io import StringIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile


P_FIELD: Any = int("d9047b5f32dda5ca6f569b", 16)
A_CURVE: Any = int("674fdf5b55923897a16f40", 16)
B_CURVE: Any = int("1d0c9956783f6026e6c981", 16)
POINT_P: tuple[Any, Any] = (
    int("5340e87bd80d1463a6ff8d", 16),
    int("94ebeb5ca5b3c685e00c20", 16),
)
POINT_Q: tuple[Any, Any] = (
    int("4a05101411039decf537a5", 16),
    int("3395a009c2210836b63d4b", 16),
)
ORDER: Any = int("2b674bdfd6fc4ba4ba751d", 16)
KNOWN_OUTPUTS: tuple[Any, ...] = (
    int("b3939f4aadcc13ca74", 16),
    int("617985fad38ec3b1a3", 16),
    int("d8c20715ccc94d2283", 16),
)
EXPECTED_D = int("1c3cdd6b221806db0a7b28", 16)
EXPECTED_STATE = int("638d9d631ab436da51e640", 16)
EXPECTED_R3 = int("2443c8daf1a9d52b09", 16)

JACOBIAN_INFINITY: tuple[Any, Any, Any] = (0, 1, 0)
BACKEND = "int"


def select_backend(name: str) -> str:
    """Select Python ``int`` or GMP-backed ``mpz`` arithmetic."""

    global P_FIELD, A_CURVE, B_CURVE, POINT_P, POINT_Q, ORDER
    global KNOWN_OUTPUTS, JACOBIAN_INFINITY, BACKEND

    if name in {"auto", "gmpy2"}:
        try:
            from gmpy2 import mpz
        except ImportError:
            if name == "gmpy2":
                raise RuntimeError("--backend gmpy2 requested, but gmpy2 is unavailable")
        else:
            P_FIELD = mpz(P_FIELD)
            A_CURVE = mpz(A_CURVE)
            B_CURVE = mpz(B_CURVE)
            POINT_P = tuple(mpz(v) for v in POINT_P)
            POINT_Q = tuple(mpz(v) for v in POINT_Q)
            ORDER = mpz(ORDER)
            KNOWN_OUTPUTS = tuple(mpz(v) for v in KNOWN_OUTPUTS)
            JACOBIAN_INFINITY = (mpz(0), mpz(1), mpz(0))
            BACKEND = "gmpy2"
            return BACKEND

    BACKEND = "int"
    return BACKEND


def load_rows() -> list[tuple[Any, Any, Any]]:
    contest_root = Path(__file__).resolve().parents[2]
    with ZipFile(contest_root / "problems" / "6_PRNG.zip") as archive:
        telemetry = archive.read("telemetry.csv").decode()
    return [
        (int(row["scale"], 16), int(row["offset"], 16), int(row["summary"], 16))
        for row in csv.DictReader(StringIO(telemetry))
    ]


def to_jacobian(point: tuple[Any, Any]) -> tuple[Any, Any, Any]:
    return point[0] % P_FIELD, point[1] % P_FIELD, type(P_FIELD)(1)


def jacobian_double(point: tuple[Any, Any, Any]) -> tuple[Any, Any, Any]:
    x1, y1, z1 = point
    if z1 == 0 or y1 % P_FIELD == 0:
        return JACOBIAN_INFINITY
    xx = x1 * x1 % P_FIELD
    yy = y1 * y1 % P_FIELD
    yyyy = yy * yy % P_FIELD
    zz = z1 * z1 % P_FIELD
    s = 2 * ((x1 + yy) * (x1 + yy) - xx - yyyy) % P_FIELD
    m = (3 * xx + A_CURVE * zz * zz) % P_FIELD
    x3 = (m * m - 2 * s) % P_FIELD
    y3 = (m * (s - x3) - 8 * yyyy) % P_FIELD
    z3 = ((y1 + z1) * (y1 + z1) - yy - zz) % P_FIELD
    return x3, y3, z3


def jacobian_add(
    left: tuple[Any, Any, Any], right: tuple[Any, Any, Any]
) -> tuple[Any, Any, Any]:
    if left[2] == 0:
        return right
    if right[2] == 0:
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


def affine_x(point: tuple[Any, Any, Any]) -> Any:
    x, _, z = point
    return x * pow(z, -2, P_FIELD) % P_FIELD


def sqrt_mod(value: Any) -> Any | None:
    root = pow(value, (P_FIELD + 1) // 4, P_FIELD)
    return root if root * root % P_FIELD == value % P_FIELD else None


def wnaf(k: int) -> tuple[int, ...]:
    """Return little-endian width-5 non-adjacent-form digits."""

    width = 5
    digits: list[int] = []
    modulus = 1 << width
    half = 1 << (width - 1)
    while k:
        if k & 1:
            digit = k % modulus
            if digit >= half:
                digit -= modulus
            k -= digit
            digits.append(digit)
        else:
            digits.append(0)
        k >>= 1
    return tuple(digits)


def scalar_mul_wnaf(
    digits: tuple[int, ...], point: tuple[Any, Any]
) -> tuple[Any, Any, Any]:
    """Multiply an arbitrary point using precomputed scalar wNAF digits."""

    base = to_jacobian(point)
    twice = jacobian_double(base)
    odd_multiples = [base]
    for _ in range(1, 1 << (5 - 2)):
        odd_multiples.append(jacobian_add(odd_multiples[-1], twice))

    result = JACOBIAN_INFINITY
    for digit in reversed(digits):
        result = jacobian_double(result)
        if digit:
            addend = odd_multiples[(abs(digit) - 1) // 2]
            if digit < 0:
                addend = (addend[0], (-addend[1]) % P_FIELD, addend[2])
            result = jacobian_add(result, addend)
    return result


def build_fixed_byte_table(point: tuple[Any, Any]) -> tuple[tuple[tuple[Any, Any, Any], ...], ...]:
    """Build 11 x 256 table for an 88-bit fixed-base multiplication."""

    base = to_jacobian(point)
    windows: list[tuple[tuple[Any, Any, Any], ...]] = []
    for _ in range(11):
        row = [JACOBIAN_INFINITY]
        for _digit in range(1, 256):
            row.append(jacobian_add(row[-1], base))
        windows.append(tuple(row))
        for _bit in range(8):
            base = jacobian_double(base)
    return tuple(windows)


def fixed_mul(
    scalar: Any, table: tuple[tuple[tuple[Any, Any, Any], ...], ...]
) -> tuple[Any, Any, Any]:
    result = JACOBIAN_INFINITY
    scalar_int = int(scalar)
    for position, row in enumerate(table):
        digit = (scalar_int >> (8 * position)) & 0xFF
        if digit:
            result = jacobian_add(result, row[digit])
    return result


def recover_backdoor_scalar_recurrence(rows: list[tuple[Any, Any, Any]]) -> Any:
    """Recover d while replacing per-candidate products with recurrences."""

    rows = [(type(ORDER)(s), type(ORDER)(o), type(ORDER)(u)) for s, o, u in rows]
    scale0, offset0, summary0 = rows[0]
    scale_inv = pow(scale0, -1, ORDER)
    candidate = ((summary0 << 20) - offset0) * scale_inv % ORDER

    # The first check rejects all but a tiny number of candidates.  Both its
    # candidate and affine image can be advanced with one modular addition.
    check_scale, check_offset, check_summary = rows[1]
    check_value = (check_scale * candidate + check_offset) % ORDER
    check_delta = check_scale * scale_inv % ORDER
    survivor: Any | None = None
    survivor_count = 0

    for _low_bits in range(1 << 20):
        if check_value >> 20 == check_summary and all(
            ((scale * candidate + offset) % ORDER) >> 20 == summary
            for scale, offset, summary in rows[2:]
        ):
            survivor = candidate
            survivor_count += 1

        candidate += scale_inv
        if candidate >= ORDER:
            candidate -= ORDER
        check_value += check_delta
        if check_value >= ORDER:
            check_value -= ORDER

    if survivor_count != 1 or survivor is None:
        raise RuntimeError(f"expected one scalar, got {survivor_count}")
    return survivor


def floor_sum(n_terms: int, modulus: int, multiplier: int, offset: int) -> int:
    """Compute sum(floor((multiplier*i+offset)/modulus), i=0..n_terms-1)."""

    answer = 0
    while True:
        if multiplier >= modulus:
            answer += (n_terms - 1) * n_terms * (multiplier // modulus) // 2
            multiplier %= modulus
        if offset >= modulus:
            answer += n_terms * (offset // modulus)
            offset %= modulus
        maximum = multiplier * n_terms + offset
        if maximum < modulus:
            return answer
        n_terms, offset, multiplier, modulus = (
            maximum // modulus,
            maximum % modulus,
            modulus,
            multiplier,
        )


def count_mod_less_than(
    length: int, multiplier: int, offset: int, bound: int, modulus: int
) -> int:
    """Count i in [0,length) with (multiplier*i+offset) mod modulus < bound."""

    if bound <= 0:
        return 0
    if bound >= modulus:
        return length
    greater_or_equal = floor_sum(
        length, modulus, multiplier, offset + modulus - bound
    ) - floor_sum(length, modulus, multiplier, offset)
    return length - greater_or_equal


def recover_backdoor_scalar_analytic(rows: list[tuple[Any, Any, Any]]) -> Any:
    """Recover d by finding modular interval hits with Euclidean floor sums.

    This replaces the 2^20 scan with O(log(2^20) * log(ORDER)) integer
    operations.  The remaining telemetry rows still verify every recovered hit.
    """

    integer_rows = [tuple(int(value) for value in row) for row in rows]
    modulus = int(ORDER)
    bucket = 1 << 20
    scale0, offset0, summary0 = integer_rows[0]
    inverse0 = pow(scale0, -1, modulus)
    base = ((summary0 * bucket - offset0) * inverse0) % modulus

    scale1, offset1, summary1 = integer_rows[1]
    multiplier = scale1 * inverse0 % modulus
    offset = (scale1 * base + offset1) % modulus
    lower = summary1 * bucket
    upper = min((summary1 + 1) * bucket, modulus)
    domain = min(bucket, modulus - summary0 * bucket)

    def count_interval(start: int, stop: int) -> int:
        length = stop - start
        shifted_offset = offset + multiplier * start
        return count_mod_less_than(
            length, multiplier, shifted_offset, upper, modulus
        ) - count_mod_less_than(length, multiplier, shifted_offset, lower, modulus)

    candidates: list[int] = []
    pending = [(0, domain)]
    while pending:
        start, stop = pending.pop()
        count = count_interval(start, stop)
        if count == 0:
            continue
        if stop - start == 1:
            candidates.append(start)
            continue
        middle = (start + stop) // 2
        pending.append((middle, stop))
        pending.append((start, middle))

    survivors = []
    for low_bits in candidates:
        candidate = (base + low_bits * inverse0) % modulus
        if all(
            ((scale * candidate + row_offset) % modulus) >> 20 == summary
            for scale, row_offset, summary in integer_rows
        ):
            survivors.append(candidate)
    if len(survivors) != 1:
        raise RuntimeError(f"expected one analytic scalar, got {len(survivors)}")
    return type(ORDER)(survivors[0])


def recover_state_and_predict(d: Any) -> tuple[Any, Any, int]:
    q_table = build_fixed_byte_table(POINT_Q)
    d_digits = wnaf(int(d))

    for low_bits in range(1 << 16):
        x = (KNOWN_OUTPUTS[0] << 16) | low_bits
        if x >= P_FIELD:
            continue
        y = sqrt_mod((x * x * x + A_CURVE * x + B_CURVE) % P_FIELD)
        if y is None:
            continue

        # ±y yield points R and -R.  d(-R) = -(dR), hence both have the same
        # affine x-coordinate and lead to exactly the same recovered state.
        # The lifted point is s1*Q.  Multiplication by d yields s1*P, whose
        # affine x-coordinate is the next generator state s2.
        state2 = affine_x(scalar_mul_wnaf(d_digits, (x, y)))
        r1 = affine_x(fixed_mul(state2, q_table)) >> 16
        if r1 != KNOWN_OUTPUTS[1]:
            continue

        state3 = affine_x(scalar_mul_wnaf(wnaf(int(state2)), POINT_P))
        r2 = affine_x(fixed_mul(state3, q_table)) >> 16
        if r2 != KNOWN_OUTPUTS[2]:
            continue

        state4 = affine_x(scalar_mul_wnaf(wnaf(int(state3)), POINT_P))
        r3 = affine_x(fixed_mul(state4, q_table)) >> 16
        return state2, r3, low_bits
    raise RuntimeError("failed to lift r0 to a consistent state")


def solve(telemetry_strategy: str) -> dict[str, Any]:
    started = time.perf_counter()
    rows = load_rows()
    if telemetry_strategy == "analytic":
        d = recover_backdoor_scalar_analytic(rows)
    elif telemetry_strategy == "recurrence":
        d = recover_backdoor_scalar_recurrence(rows)
    else:
        raise ValueError(f"unknown telemetry strategy: {telemetry_strategy}")
    d_times_q = scalar_mul_wnaf(wnaf(int(d)), POINT_Q)
    dqx, dqy, dqz = d_times_q
    inverse_z = pow(dqz, -1, P_FIELD)
    recovered_p = (
        dqx * inverse_z * inverse_z % P_FIELD,
        dqy * inverse_z * inverse_z * inverse_z % P_FIELD,
    )
    if recovered_p != POINT_P:
        raise RuntimeError(f"recovered scalar does not satisfy P = dQ: {recovered_p}")
    telemetry_done = time.perf_counter()
    state, r3, low_bits = recover_state_and_predict(d)
    finished = time.perf_counter()

    result = {
        "implementation": f"python-{BACKEND}-{telemetry_strategy}",
        "d": int(d),
        "state": int(state),
        "state_label": "s2",
        "r3": int(r3),
        "lift_low_bits": low_bits,
        "backdoor_relation": "P = dQ",
        "telemetry_seconds": telemetry_done - started,
        "state_seconds": finished - telemetry_done,
        "total_seconds": finished - started,
    }
    if (result["d"], result["state"], result["r3"]) != (
        EXPECTED_D,
        EXPECTED_STATE,
        EXPECTED_R3,
    ):
        raise RuntimeError(f"correctness check failed: {result}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("auto", "int", "gmpy2"), default="auto")
    parser.add_argument(
        "--telemetry", choices=("analytic", "recurrence"), default="analytic"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    select_backend(args.backend)
    result = solve(args.telemetry)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"backend = {result['implementation']}")
        print(f"backdoor scalar d = {result['d']:#x}")
        print("P == d*Q: True")
        print(f"recovered state s2 = {result['state']:#x}")
        print(f"predicted r3 = {result['r3']:#x}")
        print(
            "timing: telemetry={telemetry_seconds:.6f}s, "
            "state={state_seconds:.6f}s, total={total_seconds:.6f}s".format(**result)
        )


if __name__ == "__main__":
    main()
