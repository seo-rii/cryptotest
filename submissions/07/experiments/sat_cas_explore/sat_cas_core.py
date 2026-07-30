#!/usr/bin/env python3
"""Shared state and sound checks for challenge 7 SAT+CAS probes."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

import z3


P_BITS = 1024
PRODUCT_BITS = 2048
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class FixedRange:
    start: int
    width: int
    value: int

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << self.start

    @property
    def shifted_value(self) -> int:
        return self.value << self.start


@dataclass(frozen=True)
class ChallengeInstance:
    n: int
    e: int
    ct: int
    mask: int
    known: int
    p_bits: int = P_BITS

    @property
    def full_mask(self) -> int:
        return (1 << self.p_bits) - 1

    @property
    def unknown_mask(self) -> int:
        return self.full_mask ^ self.mask

    def apply_fixed_ranges(self, ranges: list[FixedRange]) -> tuple[int, int]:
        p_known = self.known
        p_mask = self.mask
        for item in ranges:
            if item.start < 0 or item.width <= 0 or item.start + item.width > self.p_bits:
                raise ValueError(f"invalid fixed range: {item}")
            if item.value < 0 or item.value >= (1 << item.width):
                raise ValueError(f"fixed value does not fit range: {item}")
            if ((p_known ^ item.shifted_value) & (p_mask & item.mask)) != 0:
                raise ValueError(f"inconsistent fixed range: {item}")
            p_known |= item.shifted_value
            p_mask |= item.mask
        return p_known, p_mask

    def unknown_ranges(self) -> list[tuple[int, int]]:
        values = [bit for bit in range(self.p_bits) if ((self.mask >> bit) & 1) == 0]
        if not values:
            return []
        ranges: list[tuple[int, int]] = []
        start = previous = values[0]
        for bit in values[1:]:
            if bit == previous + 1:
                previous = bit
            else:
                ranges.append((start, previous))
                start = previous = bit
        ranges.append((start, previous))
        return ranges


@dataclass(frozen=True)
class QKnownBits:
    known: int
    mask: int
    low_bits: int
    prefix_bits: int
    prefix_start: int
    q_min: int
    q_max: int


def parse_fixed_range(text: str) -> FixedRange:
    try:
        start_text, width_text, value_text = text.split(":", 2)
    except ValueError as exc:
        raise ValueError("expected START:WIDTH:VALUE") from exc
    start = int(start_text, 0)
    width = int(width_text, 0)
    value = int(value_text, 0)
    return FixedRange(start, width, value)


def load_instance(root: Path | None = None) -> ChallengeInstance:
    base = ROOT if root is None else root
    constants_path = base / "src" / "investigate_rsa_partial_bits.py"
    spec = importlib.util.spec_from_file_location("investigate_rsa_partial_bits", constants_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load constants from {constants_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return ChallengeInstance(
        n=int(module.N_HEX.replace(" ", ""), 16),
        e=int(module.E),
        ct=int(module.CT_HEX.replace(" ", ""), 16),
        mask=int(module.MASK_HEX.replace(" ", ""), 16),
        known=int(module.P_AND_MASK_HEX.replace(" ", ""), 16)
        & int(module.MASK_HEX.replace(" ", ""), 16),
    )


def common_prefix_from_interval(lo: int, hi: int, bits: int = P_BITS) -> tuple[int, int, int]:
    if lo > hi:
        lo, hi = hi, lo
    diff = lo ^ hi
    prefix_bits = bits if diff == 0 else bits - diff.bit_length()
    prefix_start = bits - prefix_bits
    return prefix_bits, lo >> prefix_start, prefix_start


def derive_q_known_bits(instance: ChallengeInstance, p_known: int, p_mask: int) -> QKnownBits:
    p_unknown_mask = instance.full_mask ^ p_mask
    if p_unknown_mask:
        low_bits = (p_unknown_mask & -p_unknown_mask).bit_length() - 1
    else:
        low_bits = instance.p_bits

    q_known = 0
    q_mask = 0
    if low_bits:
        low_modulus = 1 << low_bits
        p_low = p_known & (low_modulus - 1)
        q_known = (instance.n * pow(p_low, -1, low_modulus)) % low_modulus
        q_mask = low_modulus - 1

    p_min = p_known
    p_max = p_known | p_unknown_mask
    q_min = instance.n // p_max
    q_max = instance.n // p_min
    prefix_bits, q_prefix, prefix_start = common_prefix_from_interval(q_min, q_max, instance.p_bits)
    if prefix_bits:
        prefix_mask = ((1 << prefix_bits) - 1) << prefix_start
        prefix_value = q_prefix << prefix_start
        if ((q_known ^ prefix_value) & (q_mask & prefix_mask)) != 0:
            raise ValueError("derived q low bits conflict with interval high prefix")
        q_known |= prefix_value
        q_mask |= prefix_mask

    return QKnownBits(
        known=q_known,
        mask=q_mask,
        low_bits=low_bits,
        prefix_bits=prefix_bits,
        prefix_start=prefix_start,
        q_min=q_min,
        q_max=q_max,
    )


def all_bits_known(p_mask: int, start: int, width: int) -> bool:
    if width <= 0:
        return True
    wanted = ((1 << width) - 1) << start
    return (p_mask & wanted) == wanted


def z3_product_prefix_status(
    instance: ChallengeInstance,
    p_known: int,
    p_mask: int,
    check_bits: int,
    timeout_ms: int,
    enumerate_p_free_limit: int = 24,
) -> tuple[str, dict[str, int | str]]:
    if check_bits <= 0 or check_bits > instance.p_bits:
        raise ValueError("check_bits must be in 1..1024")

    try:
        q_known = derive_q_known_bits(instance, p_known, p_mask)
    except ValueError as exc:
        return "unsat", {
            "check_bits": check_bits,
            "p_fixed_bits_in_prefix": (p_mask & ((1 << check_bits) - 1)).bit_count(),
            "q_fixed_bits_in_prefix": 0,
            "q_low_bits": 0,
            "q_prefix_bits": 0,
            "q_prefix_start": instance.p_bits,
            "reason": str(exc),
        }
    width_mask = (1 << check_bits) - 1
    p_known_prefix_mask = p_mask & width_mask
    p_free_mask = width_mask ^ p_known_prefix_mask
    p_free_bits = [bit for bit in range(check_bits) if ((p_free_mask >> bit) & 1) != 0]
    if len(p_free_bits) <= enumerate_p_free_limit:
        candidate_count = 1 << len(p_free_bits)
        q_required_mask = q_known.mask & width_mask
        q_required_value = q_known.known & width_mask
        for assignment in range(candidate_count):
            p_candidate = p_known & p_known_prefix_mask
            for index, bit in enumerate(p_free_bits):
                if (assignment >> index) & 1:
                    p_candidate |= 1 << bit
            if p_candidate & 1 == 0:
                continue
            q_candidate = (instance.n * pow(p_candidate, -1, 1 << check_bits)) & width_mask
            if (q_candidate & q_required_mask) == q_required_value:
                return "sat", {
                    "check_bits": check_bits,
                    "p_fixed_bits_in_prefix": p_known_prefix_mask.bit_count(),
                    "q_fixed_bits_in_prefix": q_required_mask.bit_count(),
                    "q_low_bits": q_known.low_bits,
                    "q_prefix_bits": q_known.prefix_bits,
                    "q_prefix_start": q_known.prefix_start,
                    "method": "enumerate_p_prefix",
                    "p_free_bits_in_prefix": len(p_free_bits),
                    "p_candidates_checked": assignment + 1,
                }
        return "unsat", {
            "check_bits": check_bits,
            "p_fixed_bits_in_prefix": p_known_prefix_mask.bit_count(),
            "q_fixed_bits_in_prefix": q_required_mask.bit_count(),
            "q_low_bits": q_known.low_bits,
            "q_prefix_bits": q_known.prefix_bits,
            "q_prefix_start": q_known.prefix_start,
            "method": "enumerate_p_prefix",
            "p_free_bits_in_prefix": len(p_free_bits),
            "p_candidates_checked": candidate_count,
        }

    solver = z3.SolverFor("QF_BV")
    solver.set(timeout=max(1, timeout_ms))
    p = z3.BitVec("p_prefix", check_bits)
    q = z3.BitVec("q_prefix", check_bits)
    solver.add((p & z3.BitVecVal(p_mask & width_mask, check_bits)) == z3.BitVecVal(p_known & width_mask, check_bits))
    solver.add((q & z3.BitVecVal(q_known.mask & width_mask, check_bits)) == z3.BitVecVal(q_known.known & width_mask, check_bits))
    solver.add(p * q == z3.BitVecVal(instance.n & width_mask, check_bits))
    result = solver.check()
    return str(result), {
        "check_bits": check_bits,
        "p_fixed_bits_in_prefix": (p_mask & width_mask).bit_count(),
        "q_fixed_bits_in_prefix": (q_known.mask & width_mask).bit_count(),
        "q_low_bits": q_known.low_bits,
        "q_prefix_bits": q_known.prefix_bits,
        "q_prefix_start": q_known.prefix_start,
    }


def z3_hensel_prefix_status(
    instance: ChallengeInstance,
    p_known: int,
    p_mask: int,
    prefix_bits: int,
    timeout_ms: int,
) -> tuple[str, dict[str, int | str]]:
    if prefix_bits <= 0 or prefix_bits > instance.p_bits:
        raise ValueError("prefix_bits must be in 1..1024")
    try:
        q_known = derive_q_known_bits(instance, p_known, p_mask)
    except ValueError as exc:
        return "unsat", {
            "prefix_bits": prefix_bits,
            "p_fixed_bits_in_prefix": (p_mask & ((1 << prefix_bits) - 1)).bit_count(),
            "q_fixed_bits_in_prefix": 0,
            "q_low_bits": 0,
            "q_prefix_bits": 0,
            "q_prefix_start": instance.p_bits,
            "reason": str(exc),
            "method": "z3_hensel_bits",
        }

    solver = z3.Solver()
    solver.set(timeout=max(1, timeout_ms))
    p_bits = []
    q_bits = []
    for bit in range(prefix_bits):
        if (p_mask >> bit) & 1:
            p_bits.append(bool((p_known >> bit) & 1))
        else:
            p_bits.append(z3.Bool(f"hp_{bit}"))
        if (q_known.mask >> bit) & 1:
            q_bits.append(bool((q_known.known >> bit) & 1))
        else:
            q_bits.append(z3.Bool(f"hq_{bit}"))

    carry_limit = prefix_bits + 1
    carries = [z3.Int(f"hc_{index}") for index in range(prefix_bits + 1)]
    solver.add(carries[0] == 0)
    for carry in carries:
        solver.add(carry >= 0)
        solver.add(carry <= carry_limit)

    def bit_product(left: bool | z3.BoolRef, right: bool | z3.BoolRef):
        if isinstance(left, bool) and isinstance(right, bool):
            return 1 if left and right else 0
        if isinstance(left, bool):
            return z3.If(right, 1, 0) if left else 0
        if isinstance(right, bool):
            return z3.If(left, 1, 0) if right else 0
        return z3.If(z3.And(left, right), 1, 0)

    for bit in range(prefix_bits):
        column_terms = [
            bit_product(p_bits[index], q_bits[bit - index])
            for index in range(bit + 1)
        ]
        n_bit = (instance.n >> bit) & 1
        solver.add(sum(column_terms) + carries[bit] == n_bit + 2 * carries[bit + 1])

    result = solver.check()
    return str(result), {
        "prefix_bits": prefix_bits,
        "p_fixed_bits_in_prefix": (p_mask & ((1 << prefix_bits) - 1)).bit_count(),
        "q_fixed_bits_in_prefix": (q_known.mask & ((1 << prefix_bits) - 1)).bit_count(),
        "q_low_bits": q_known.low_bits,
        "q_prefix_bits": q_known.prefix_bits,
        "q_prefix_start": q_known.prefix_start,
        "method": "z3_hensel_bits",
    }
