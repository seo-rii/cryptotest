#!/usr/bin/env python3
"""Recover challenge 5 textbook-BGV secret and fixed State string."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from zipfile import ZipFile


Q = int("7f52f24e1b74ca8d80713d", 16)
T = int("78eb84ea7c66913db445", 16)
N = 64
COMMON_FACTOR = 257


def parse_ciphertext(text: str) -> dict[str, list[int]]:
    parsed: dict[str, list[int]] = {}
    for name in re.findall(r'"(c[01]_[12])"', text):
        body = re.search(r'"' + name + r'"\s*:\s*\[(.*?)\]', text, re.S)
        if body is None:
            raise ValueError(f"missing {name}")
        parsed[name] = [int(x) for x in re.findall(r"\d+", body.group(1))]
    return parsed


def centered(value: int, modulus: int) -> int:
    value %= modulus
    return value if value <= modulus // 2 else value - modulus


def negacyclic_matrix(poly: list[int], modulus: int) -> list[list[int]]:
    matrix: list[list[int]] = []
    for row in range(N):
        matrix.append(
            [
                ((1 if ((row - col) % N) + col < N else -1) * poly[(row - col) % N]) % modulus
                for col in range(N)
            ]
        )
    return matrix


def rref_mod(matrix: list[list[int]], rhs: list[int], modulus: int) -> tuple[list[int], list[list[int]]] | None:
    work = [row[:] + [value % modulus] for row, value in zip(matrix, rhs)]
    row_count = len(work)
    col_count = len(matrix[0])
    pivot_cols: list[int] = []
    row = 0
    for col in range(col_count):
        pivot = None
        for candidate in range(row, row_count):
            if work[candidate][col] % modulus:
                pivot = candidate
                break
        if pivot is None:
            continue
        work[row], work[pivot] = work[pivot], work[row]
        inv = pow(work[row][col], -1, modulus)
        work[row] = [(x * inv) % modulus for x in work[row]]
        for candidate in range(row_count):
            if candidate == row:
                continue
            factor = work[candidate][col] % modulus
            if factor:
                work[candidate] = [
                    (work[candidate][i] - factor * work[row][i]) % modulus
                    for i in range(col_count + 1)
                ]
        pivot_cols.append(col)
        row += 1

    for candidate in range(row, row_count):
        if all(work[candidate][col] % modulus == 0 for col in range(col_count)) and work[candidate][col_count] % modulus:
            return None

    free_cols = [col for col in range(col_count) if col not in pivot_cols]
    particular = [0] * col_count
    for pivot_row, col in enumerate(pivot_cols):
        particular[col] = work[pivot_row][col_count]
    basis: list[list[int]] = []
    for free_col in free_cols:
        vector = [0] * col_count
        vector[free_col] = 1
        for pivot_row, col in enumerate(pivot_cols):
            vector[col] = (-work[pivot_row][free_col]) % modulus
        basis.append(vector)
    return particular, basis


def date_delta_patterns() -> list[list[int]]:
    patterns: list[list[int]] = []
    for year in (2025, 2026, 2027):
        for month in range(1, 13):
            for day in range(1, 32):
                try:
                    current = date(year, month, day)
                except ValueError:
                    continue
                nxt = current + timedelta(days=1)
                left = [int(ch) for ch in f"{current.year:04d}{current.month:02d}{current.day:02d}"]
                right = [int(ch) for ch in f"{nxt.year:04d}{nxt.month:02d}{nxt.day:02d}"]
                pattern = [(right[i] - left[i]) % COMMON_FACTOR for i in range(8)]
                if pattern not in patterns:
                    patterns.append(pattern)
    return patterns


def find_secret(delta_c0: list[int], delta_c1: list[int]) -> tuple[list[int], list[int]]:
    matrix = negacyclic_matrix([x % COMMON_FACTOR for x in delta_c0], COMMON_FACTOR)
    for delta_date in date_delta_patterns():
        rhs = [x % COMMON_FACTOR for x in delta_c1]
        for i, value in enumerate(delta_date):
            rhs[N - 8 + i] = (rhs[N - 8 + i] - value) % COMMON_FACTOR
        solved = rref_mod(matrix, rhs, COMMON_FACTOR)
        if solved is None:
            continue
        particular, basis = solved
        if len(basis) > 3:
            continue
        candidates = [particular]
        for vector in basis:
            candidates = [
                [(base[i] + coeff * vector[i]) % COMMON_FACTOR for i in range(N)]
                for base in candidates
                for coeff in range(COMMON_FACTOR)
            ]
        for candidate in candidates:
            if all(value in (0, 1, COMMON_FACTOR - 1) for value in candidate):
                secret = [-1 if value == COMMON_FACTOR - 1 else value for value in candidate]
                return secret, delta_date
    raise RuntimeError("no ternary secret found")


def negacyclic_mul(left: list[int], right: list[int], modulus: int) -> list[int]:
    result = [0] * N
    for i, left_value in enumerate(left):
        for j, right_value in enumerate(right):
            index = i + j
            if index < N:
                result[index] = (result[index] + left_value * right_value) % modulus
            else:
                result[index - N] = (result[index - N] - left_value * right_value) % modulus
    return result


def decrypt(c0: list[int], c1: list[int], secret: list[int]) -> tuple[list[int], list[int]]:
    product = negacyclic_mul(c0, secret, Q)
    centered_noise_message = [centered(c1[i] - product[i], Q) for i in range(N)]
    message = [value % T for value in centered_noise_message]
    error = [(centered_noise_message[i] - message[i]) // T for i in range(N)]
    return message, error


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / "problems" / "5_동형암호.zip") as archive:
        data: dict[str, list[int]] = {}
        data.update(parse_ciphertext(archive.read("ctxt_day1.txt").decode()))
        data.update(parse_ciphertext(archive.read("ctxt_day2.txt").decode()))

    delta_c0 = [(data["c0_2"][i] - data["c0_1"][i]) % Q for i in range(N)]
    delta_c1 = [(data["c1_2"][i] - data["c1_1"][i]) % Q for i in range(N)]
    secret, delta_date = find_secret(delta_c0, delta_c1)
    print("secret s =", secret)
    print("date delta pattern =", delta_date)

    states: list[list[int]] = []
    for day in (1, 2):
        message, error = decrypt(data[f"c0_{day}"], data[f"c1_{day}"], secret)
        state = message[:-8]
        states.append(state)
        print(f"day{day} message =", message)
        print(f"day{day} date ASCII =", bytes(message[-8:]).decode())
        print(f"day{day} error range = {min(error)}..{max(error)}")
    if states[0] != states[1]:
        raise RuntimeError("fixed State mismatch")
    print("State coefficients =", states[0])
    print("State ASCII =", bytes(states[0]).decode())


if __name__ == "__main__":
    main()
