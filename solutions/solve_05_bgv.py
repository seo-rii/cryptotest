#!/usr/bin/env python3
"""Recover challenge 5 textbook-BGV secret and fixed State string."""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product
from pathlib import Path
from zipfile import ZipFile


Q = int("7f52f24e1b74ca8d80713d", 16)
T = int("78eb84ea7c66913db445", 16)
N = 64
COMMON_FACTOR = 257


@dataclass(frozen=True)
class SecretCandidate:
    secret: tuple[int, ...]
    delta_date: tuple[int, ...]
    rank: int
    nullity: int


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


def date_delta_patterns() -> list[tuple[int, ...]]:
    """Return every distinct next-day delta for four-digit Gregorian dates.

    Every next-day transition is either inside one month (covered by day
    01->02 through 30->31) or crosses a month boundary.  Enumerating these two
    exhaustive classes avoids iterating over all 3.65 million individual dates.
    """

    patterns: set[tuple[int, ...]] = set()

    # January has all within-month transitions 01->02 through 30->31.
    for day in range(1, 31):
        left = f"200001{day:02d}"
        right = f"200001{day + 1:02d}"
        patterns.add(
            tuple((int(b) - int(a)) % COMMON_FACTOR for a, b in zip(left, right))
        )

    # Month-end transitions cover leap days, month carries, and every possible
    # decimal carry in four-digit years 0001..9999.  9999-12-31 is excluded
    # because its successor would require a five-digit year.
    for year in range(1, 10_000):
        for month in range(1, 13):
            if year == 9999 and month == 12:
                continue
            last_day = monthrange(year, month)[1]
            if month < 12:
                next_year, next_month = year, month + 1
            else:
                next_year, next_month = year + 1, 1
            left = f"{year:04d}{month:02d}{last_day:02d}"
            right = f"{next_year:04d}{next_month:02d}01"
            patterns.add(
                tuple(
                    (int(b) - int(a)) % COMMON_FACTOR
                    for a, b in zip(left, right)
                )
            )

    return sorted(patterns)


def find_secret_candidates(
    delta_c0: list[int], delta_c1: list[int]
) -> list[SecretCandidate]:
    """Collect every ternary solution for every possible next-day pattern."""

    matrix = negacyclic_matrix([x % COMMON_FACTOR for x in delta_c0], COMMON_FACTOR)
    found: set[SecretCandidate] = set()
    for delta_date in date_delta_patterns():
        rhs = [x % COMMON_FACTOR for x in delta_c1]
        for i, value in enumerate(delta_date):
            rhs[N - 8 + i] = (rhs[N - 8 + i] - value) % COMMON_FACTOR
        solved = rref_mod(matrix, rhs, COMMON_FACTOR)
        if solved is None:
            continue
        particular, basis = solved
        if len(basis) > 2:
            raise RuntimeError(
                "candidate affine space is too large for exhaustive enumeration: "
                f"nullity={len(basis)}"
            )
        for coefficients in product(
            range(COMMON_FACTOR), repeat=len(basis)
        ):
            candidate = [
                (
                    particular[i]
                    + sum(
                        coefficient * vector[i]
                        for coefficient, vector in zip(coefficients, basis)
                    )
                )
                % COMMON_FACTOR
                for i in range(N)
            ]
            if all(value in (0, 1, COMMON_FACTOR - 1) for value in candidate):
                secret = tuple(
                    -1 if value == COMMON_FACTOR - 1 else value
                    for value in candidate
                )
                found.add(
                    SecretCandidate(
                        secret,
                        delta_date,
                        N - len(basis),
                        len(basis),
                    )
                )
    return sorted(found, key=lambda item: (item.delta_date, item.secret))


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
    patterns = date_delta_patterns()
    if len(patterns) != 11:
        raise RuntimeError(
            f"unexpected number of four-digit date delta patterns: {len(patterns)}"
        )
    algebraic_candidates = find_secret_candidates(delta_c0, delta_c1)

    # The problem does not publish the error distribution.  This bound is the
    # largest symmetric bound that keeps t*e+m inside the centered q interval
    # for every m in [0,t); the recovered errors are far smaller (1..4).
    safe_error_bound = (Q // 2 - (T - 1)) // T
    validated: list[
        tuple[
            SecretCandidate,
            list[list[int]],
            list[list[int]],
            list[date],
            bytes,
            int,
        ]
    ] = []
    for candidate in algebraic_candidates:
        secret = list(candidate.secret)
        messages: list[list[int]] = []
        errors: list[list[int]] = []
        valid = True
        for day_number in (1, 2):
            message, error = decrypt(
                data[f"c0_{day_number}"],
                data[f"c1_{day_number}"],
                secret,
            )
            if any(value < 0 or value > 255 for value in message):
                valid = False
                break
            if any(abs(value) > safe_error_bound for value in error):
                valid = False
                break
            product_c0_s = negacyclic_mul(
                data[f"c0_{day_number}"], secret, Q
            )
            reconstructed_c1 = [
                (
                    product_c0_s[i]
                    + T * error[i]
                    + message[i]
                )
                % Q
                for i in range(N)
            ]
            if reconstructed_c1 != data[f"c1_{day_number}"]:
                valid = False
                break
            messages.append(message)
            errors.append(error)
        if not valid:
            continue

        raw_prefixes = [bytes(message[:-8]) for message in messages]
        if raw_prefixes[0] != raw_prefixes[1]:
            continue
        state = raw_prefixes[0].rstrip(b"\0")
        padding_length = len(raw_prefixes[0]) - len(state)
        if (
            not state
            or b"\0" in state
            or any(byte < 0x20 or byte > 0x7E for byte in state)
        ):
            continue

        try:
            date_texts = [
                bytes(message[-8:]).decode("ascii") for message in messages
            ]
        except UnicodeDecodeError:
            continue
        if any(len(text) != 8 or not text.isdigit() for text in date_texts):
            continue
        dates: list[date] = []
        try:
            for text in date_texts:
                parsed_date = date(
                    int(text[:4]), int(text[4:6]), int(text[6:8])
                )
                if (
                    f"{parsed_date.year:04d}"
                    f"{parsed_date.month:02d}"
                    f"{parsed_date.day:02d}"
                    != text
                ):
                    raise ValueError("non-canonical YYYYMMDD")
                dates.append(parsed_date)
        except ValueError:
            continue
        if dates[1] - dates[0] != timedelta(days=1):
            continue
        observed_delta = tuple(
            (int(right) - int(left)) % COMMON_FACTOR
            for left, right in zip(date_texts[0], date_texts[1])
        )
        if observed_delta != candidate.delta_date:
            continue
        validated.append(
            (
                candidate,
                messages,
                errors,
                dates,
                state,
                padding_length,
            )
        )

    print(f"four-digit Gregorian next-day delta patterns = {len(patterns)}")
    print(f"ternary algebraic candidates = {len(algebraic_candidates)}")
    print(f"fully validated candidates = {len(validated)}")
    print(f"centered-decryption safe error bound = {safe_error_bound}")
    if len(validated) != 1:
        raise RuntimeError(
            "expected exactly one candidate after date, State, padding, and "
            f"noise validation; got {len(validated)}"
        )

    candidate, messages, errors, dates, state, padding_length = validated[0]
    if (candidate.rank, candidate.nullity) != (63, 1):
        raise RuntimeError(
            "unexpected solution-space dimensions: "
            f"rank={candidate.rank}, nullity={candidate.nullity}"
        )
    secret = list(candidate.secret)
    date_texts = [f"{value.year:04d}{value.month:02d}{value.day:02d}" for value in dates]
    print(f"linear-system rank = {candidate.rank}, nullity = {candidate.nullity}")
    print("secret s =", secret)
    print("date delta pattern =", list(candidate.delta_date))
    for day_number, (message, error, date_text) in enumerate(
        zip(messages, errors, date_texts), 1
    ):
        print(f"day{day_number} message =", message)
        print(f"day{day_number} date ASCII =", date_text)
        print(f"day{day_number} error range = {min(error)}..{max(error)}")
    print(f"zero padding length = {padding_length}")
    print("State coefficients =", list(state))
    print("State ASCII =", state.decode("ascii"))

    submitted_secret = [
        int(value)
        for value in (
            root / "submissions" / "05" / "02_secret_s.txt"
        ).read_text(encoding="ascii").split()
    ]
    submitted_state = [
        int(value)
        for value in (
            root / "submissions" / "05" / "03_state.txt"
        ).read_text(encoding="ascii").split()
    ]
    if submitted_secret != secret:
        raise RuntimeError("submissions/05/02_secret_s.txt is out of sync")
    if submitted_state != list(state):
        raise RuntimeError("submissions/05/03_state.txt is out of sync")
    if date_texts != ["20260410", "20260411"]:
        raise RuntimeError(f"unexpected recovered dates: {date_texts}")
    if state != b"BGV DAILY STATUS CORE-A LINK OK TEMP NORMAL POWER STABLE":
        raise RuntimeError(f"unexpected recovered State: {state!r}")
    if [(min(values), max(values)) for values in errors] != [(1, 4), (1, 4)]:
        raise RuntimeError("unexpected recovered error ranges")
    print("submission and expected-result checks: PASS")


if __name__ == "__main__":
    main()
