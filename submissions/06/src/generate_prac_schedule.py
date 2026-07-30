#!/usr/bin/env python3
"""Regenerate and audit the fixed Lucas-PRAC schedule used by Problem 6.

The schedule evaluates ``L_H`` for

    H = (p + 1) / 100 = 0x22b9097fdf2db42063bbf,
    L_(a+b) = L_a * L_b - L_(a-b), and L_0 = 2, L_1 = trace.

It follows the condition order in Montgomery's PRAC Table 4, as implemented by
GMP-ECM's ``pp1_mul_prac``.  The initial split is supplied explicitly as
``r=0x1575ba2094b05be88186b``.  An opcode's high bit requests ``A/B`` pre-swap;
its low seven bits are the PRAC rule number.  This instance uses only:

* rule 1: three differential products;
* rule 3: one differential product;
* rule 4: one differential product and one square; and
* rule 5: one differential product and one square.

The initial ``L_2`` costs one square and the final differential addition costs
one product.  Thus the checked-in schedule costs exactly ``118M + 6S = 124``
field products.

Examples, from this folder::

    python3 generate_prac_schedule.py
    python3 generate_prac_schedule.py --emit-cpp

The default run also extracts ``SUBGROUP_PRAC_SCHEDULE`` from
``deep_native.cpp`` and rejects any byte-level drift.  It requires only the
Python 3.9+ standard library.

References:

* https://cr.yp.to/bib/1992/montgomery-lucas.pdf
* https://sources.debian.org/src/gmp-ecm/7.0.6%2Bds-2/lucas.c/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


FIELD = int("d9047b5f32dda5ca6f569b", 16)
EXPONENT = (FIELD + 1) // 100
SEED = int("1575ba2094b05be88186b", 16)
EXPECTED_HASH = "18b8ddcc131e735e129646411153b5ad76d413e76087e42503cfd56f16a5d739"
EXPECTED_LENGTH = 115
EXPECTED_PRE_SWAPS = 91
EXPECTED_RULE_COUNTS = {1: 1, 3: 109, 4: 4, 5: 1}
EXPECTED_MULTIPLIES = 118
EXPECTED_SQUARES = 6


@dataclass(frozen=True)
class Schedule:
    opcodes: bytes
    condition_counts: dict[int, int]
    final_d: int
    final_e: int


def generate_schedule(exponent: int, seed: int) -> Schedule:
    """Apply the GMP-ECM/Montgomery Table-4 condition order."""

    if exponent <= 2:
        raise ValueError("exponent must exceed two")
    if not exponent // 2 < seed < exponent:
        raise ValueError("seed must satisfy exponent/2 < seed < exponent")

    d = exponent - seed
    e = 2 * seed - exponent
    encoded: list[int] = []
    conditions: Counter[int] = Counter()

    while d != e:
        pre_swap = 0
        if d < e:
            d, e = e, d
            pre_swap = 0x80

        # This is deliberately the source order of PRAC Table 4.  Conditions
        # 2 and 4 have the same Lucas-state operation and share opcode 4.
        if d - e <= e // 4 and (d + e) % 3 == 0:
            condition = 1
            d = (2 * d - e) // 3
            e = (e - d) // 2
            rule = 1
        elif d - e <= e // 4 and (d - e) % 6 == 0:
            condition = 2
            d = (d - e) // 2
            rule = 4
        elif (d + 3) // 4 <= e:
            condition = 3
            d -= e
            rule = 3
        elif (d + e) % 2 == 0:
            condition = 4
            d = (d - e) // 2
            rule = 4
        elif d % 2 == 0:
            condition = 5
            d //= 2
            rule = 5
        elif d % 3 == 0:
            condition = 6
            d = d // 3 - e
            rule = 6
        elif (d + e) % 3 == 0:
            condition = 7
            d = (d - 2 * e) // 3
            rule = 7
        elif (d - e) % 3 == 0:
            condition = 8
            d = (d - e) // 3
            rule = 8
        else:
            condition = 9
            e //= 2
            rule = 9

        if rule not in {1, 3, 4, 5}:
            raise ValueError(
                f"seed requires unsupported rule {rule} (condition {condition}); "
                "the compact Problem-6 interpreter supports rules 1/3/4/5"
            )
        if d <= 0 or e <= 0:
            raise AssertionError(f"invalid PRAC state after condition {condition}: {(d, e)}")
        encoded.append(pre_swap | rule)
        conditions[condition] += 1

    return Schedule(bytes(encoded), dict(sorted(conditions.items())), d, e)


def execute_index_schedule(opcodes: bytes) -> int:
    """Execute only Lucas indices and return the final computed subscript."""

    a, b, c = 2, 1, 1
    for offset, encoded in enumerate(opcodes):
        if encoded & 0x80:
            a, b = b, a
        rule = encoded & 0x7F
        if abs(a - b) != c:
            raise AssertionError(f"broken differential invariant before opcode {offset}")
        if rule == 1:
            a, b = 2 * a + b, a + 2 * b
        elif rule == 3:
            a, b, c = a, a + b, b
        elif rule == 4:
            a, b = 2 * a, a + b
        elif rule == 5:
            a, c = 2 * a, a + c
        else:
            raise AssertionError(f"unsupported encoded rule {rule}")
        if abs(a - b) != c:
            raise AssertionError(f"broken differential invariant after opcode {offset}")
    return a + b


def execute_trace_schedule(trace: int, modulus: int, opcodes: bytes) -> int:
    """Evaluate the schedule with the same state updates as the C++ code."""

    two = 2 % modulus
    a = (trace * trace - two) % modulus
    b = trace % modulus
    c = b
    for encoded in opcodes:
        if encoded & 0x80:
            a, b = b, a
        rule = encoded & 0x7F
        if rule == 5:
            c = (c * a - b) % modulus
            a = (a * a - two) % modulus
            continue
        t = (a * b - c) % modulus
        if rule == 1:
            a, b = (t * a - b) % modulus, (b * t - a) % modulus
        elif rule == 3:
            b, c = t, b
        elif rule == 4:
            a, b = (a * a - two) % modulus, t
        else:
            raise AssertionError(f"unsupported encoded rule {rule}")
    return (a * b - c) % modulus


def lucas_pair(trace: int, exponent: int, modulus: int) -> tuple[int, int]:
    """Return ``(L_exponent, L_(exponent+1))`` by binary doubling."""

    trace %= modulus
    if exponent == 0:
        return 2 % modulus, trace
    left, right = lucas_pair(trace, exponent // 2, modulus)
    even = (left * left - 2) % modulus
    odd = (left * right - trace) % modulus
    if exponent % 2 == 0:
        return even, odd
    return odd, (right * right - 2) % modulus


def operation_counts(opcodes: bytes) -> tuple[int, int]:
    """Return field multiply and square counts including setup/finalization."""

    multiplies = 1  # final L_(a+b)
    squares = 1  # initial L_2
    for encoded in opcodes:
        rule = encoded & 0x7F
        if rule == 1:
            multiplies += 3
        elif rule == 3:
            multiplies += 1
        elif rule in {4, 5}:
            multiplies += 1
            squares += 1
        else:
            raise AssertionError(f"unsupported encoded rule {rule}")
    return multiplies, squares


def extract_source_schedule(source: Path) -> bytes:
    text = source.read_text(encoding="utf-8")
    match = re.search(
        r"SUBGROUP_PRAC_SCHEDULE\s*\{(?P<body>.*?)\n\};",
        text,
        flags=re.DOTALL,
    )
    if match is None:
        raise RuntimeError(f"could not find SUBGROUP_PRAC_SCHEDULE in {source}")
    return bytes(int(value, 16) for value in re.findall(r"0x([0-9a-fA-F]{2})", match["body"]))


def deterministic_trace_audit(opcodes: bytes, exponent: int, samples: int) -> None:
    state = 0x9E3779B97F4A7C15
    mask = (1 << 64) - 1

    def random64() -> int:
        nonlocal state
        state ^= state >> 12
        state ^= (state << 25) & mask
        state ^= state >> 27
        state &= mask
        return (state * 0x2545F4914F6CDD1D) & mask

    boundaries = (0, 1, 2, FIELD - 2, FIELD - 1, (1 << 64) - 1, 1 << 64)
    traces = list(boundaries)
    for _ in range(samples):
        traces.append(((random64() << 64) | random64()) % FIELD)
    for index, trace in enumerate(traces):
        scheduled = execute_trace_schedule(trace, FIELD, opcodes)
        reference = lucas_pair(trace, exponent, FIELD)[0]
        if scheduled != reference:
            raise AssertionError(
                f"trace mismatch at vector {index}: {scheduled:#x} != {reference:#x}"
            )


def cpp_initializer(opcodes: bytes) -> str:
    rows = []
    for start in range(0, len(opcodes), 8):
        row = ", ".join(f"0x{value:02x}" for value in opcodes[start : start + 8])
        rows.append(f"    {row},")
    return "\n".join(rows)


def main() -> None:
    directory = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exponent", type=lambda value: int(value, 0), default=EXPONENT)
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=SEED)
    parser.add_argument(
        "--source",
        type=Path,
        default=directory / "deep_native.cpp",
        help="C++ source whose checked-in byte array must match (default: %(default)s)",
    )
    parser.add_argument(
        "--no-source-check",
        action="store_true",
        help="generate without extracting the checked-in C++ byte array",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=2000,
        help="deterministic field traces checked against binary Lucas evaluation",
    )
    parser.add_argument("--emit-cpp", action="store_true", help="print the C++ initializer")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    args = parser.parse_args()
    if args.samples < 0:
        parser.error("--samples must be nonnegative")

    schedule = generate_schedule(args.exponent, args.seed)
    digest = hashlib.sha256(schedule.opcodes).hexdigest()
    rule_counts = dict(sorted(Counter(value & 0x7F for value in schedule.opcodes).items()))
    pre_swaps = sum(bool(value & 0x80) for value in schedule.opcodes)
    multiplies, squares = operation_counts(schedule.opcodes)
    final_index = execute_index_schedule(schedule.opcodes)

    if args.exponent == EXPONENT and args.seed == SEED:
        expected = (
            len(schedule.opcodes) == EXPECTED_LENGTH
            and digest == EXPECTED_HASH
            and pre_swaps == EXPECTED_PRE_SWAPS
            and rule_counts == EXPECTED_RULE_COUNTS
            and (multiplies, squares) == (EXPECTED_MULTIPLIES, EXPECTED_SQUARES)
        )
        if not expected:
            raise AssertionError("default schedule no longer matches the audited constants")
    if schedule.final_d != 1 or schedule.final_e != 1 or final_index != args.exponent:
        raise AssertionError(
            f"schedule terminates at d/e/index={schedule.final_d}/{schedule.final_e}/{final_index}"
        )
    if not args.no_source_check:
        source_schedule = extract_source_schedule(args.source)
        if source_schedule != schedule.opcodes:
            raise AssertionError(f"generated bytes differ from {args.source}")

    deterministic_trace_audit(schedule.opcodes, args.exponent, args.samples)
    summary = {
        "condition_counts": schedule.condition_counts,
        "exponent": hex(args.exponent),
        "field_multiplies": multiplies,
        "field_products": multiplies + squares,
        "field_squares": squares,
        "length": len(schedule.opcodes),
        "pre_swaps": pre_swaps,
        "rule_counts": rule_counts,
        "seed": hex(args.seed),
        "sha256": digest,
        "source_match": not args.no_source_check,
        "trace_samples": args.samples + 7,
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(
            "PRAC schedule OK: "
            f"{len(schedule.opcodes)} bytes, {pre_swaps} pre-swaps, "
            f"{multiplies}M+{squares}S={multiplies + squares} products"
        )
        print(f"seed={args.seed:#x} exponent={args.exponent:#x}")
        print(f"rules={rule_counts} sha256={digest}")
        print(f"deterministic trace vectors={args.samples + 7}")
    if args.emit_cpp:
        print(cpp_initializer(schedule.opcodes))


if __name__ == "__main__":
    main()
