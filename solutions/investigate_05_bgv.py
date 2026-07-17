#!/usr/bin/env python3
"""Initial Python investigation for challenge 5 textbook-BGV data."""

from __future__ import annotations

import math
import re
from pathlib import Path
from zipfile import ZipFile


Q = int("7f52f24e1b74ca8d80713d", 16)
T = int("78eb84ea7c66913db445", 16)
N = 64


def factor(n: int) -> list[int]:
    factors: list[int] = []
    divisor = 2
    while divisor * divisor <= n:
        while n % divisor == 0:
            factors.append(divisor)
            n //= divisor
        divisor += 1 if divisor == 2 else 2
        if divisor > 10000 and n > 1:
            break
    if n > 1:
        # The remaining cofactors in this challenge are small enough for Pollard rho,
        # but the factor list below is only used for diagnostics.
        factors.append(n)
    return factors


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


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with ZipFile(root / "problems" / "5_동형암호.zip") as archive:
        day1 = parse_ciphertext(archive.read("ctxt_day1.txt").decode())
        day2 = parse_ciphertext(archive.read("ctxt_day2.txt").decode())

    print(f"n={N}")
    print(f"q={Q} ({Q.bit_length()} bits), t={T} ({T.bit_length()} bits), q/t={Q / T:.3f}")
    print(f"gcd(q, t)={math.gcd(Q, T)}")
    print("q factors from a full Pollard-rho run: 3 * 23 * 257 * 116881 * 188165993 * 394677793")
    print("t factors from a full Pollard-rho run: 59 * 257 * 313 * 751 * 137201 * 1167699593")

    dc0 = [(day2["c0_2"][i] - day1["c0_1"][i]) % Q for i in range(N)]
    dc1 = [(day2["c1_2"][i] - day1["c1_1"][i]) % Q for i in range(N)]
    print(f"Delta c0 centered range: {min(centered(x, Q) for x in dc0)} .. {max(centered(x, Q) for x in dc0)}")
    print(f"Delta c1 centered range: {min(centered(x, Q) for x in dc1)} .. {max(centered(x, Q) for x in dc1)}")
    print()
    print("Status: parsed and reduced the instance, but did not recover s in pure Python.")
    print("The useful equation is centered_q(Delta c1 - Delta c0*s - Delta m) = t*Delta e.")
    print("A complete attack should solve this 64-dimensional ternary-secret LWE instance,")
    print("for example with a lattice embedding or a hybrid meet-in-the-middle search.")


if __name__ == "__main__":
    main()
