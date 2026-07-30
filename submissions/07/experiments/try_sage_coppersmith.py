#!/usr/bin/env python3
"""Reproduce Sage/Coppersmith attempts for challenge 7.

This is an investigation script, not a completed solver. It requires:

- SageMath importable from python3
- jvdsn/crypto-attacks checked out at /tmp/crypto-attacks

Use --long to include the 495-dimensional m=4,t=2 attempt.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRYPTO_ATTACKS = Path("/tmp/crypto-attacks")


def load_constants():
    spec = importlib.util.spec_from_file_location(
        "investigate_rsa_partial_bits", ROOT / "src" / "investigate_rsa_partial_bits.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load challenge 7 constants")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_partial(mask: int, p_known: int, fixed: dict[int, int]):
    from shared.partial_integer import PartialInteger

    partial = PartialInteger()
    pos = 0
    while pos < 1024:
        bit_known = (mask >> pos) & 1
        start = pos
        while pos < 1024 and ((mask >> pos) & 1) == bit_known:
            pos += 1
        length = pos - start
        if not bit_known and start in fixed:
            partial.add_known(fixed[start], length)
        elif bit_known:
            partial.add_known((p_known >> start) & ((1 << length) - 1), length)
        else:
            partial.add_unknown(length)
    return partial


def bits(value: int, start: int, stop: int) -> int:
    return (value >> start) & ((1 << (stop - start)) - 1)


def build_coarse_partial(p_known: int, low: int | None = None, high: int | None = None):
    """Build a deliberately coarsened p model.

    If low/high are unset this has four unknowns:
    150..153, 210..439, 600..829, 920..923.

    If low/high are set, the two nibbles are fixed and only the two
    large middle spans remain unknown.
    """
    from shared.partial_integer import PartialInteger

    partial = PartialInteger()
    partial.add_known(bits(p_known, 0, 150), 150)
    if low is None:
        partial.add_unknown(4)
    else:
        partial.add_known(low, 4)
    partial.add_known(bits(p_known, 154, 210), 56)
    partial.add_unknown(230)
    partial.add_known(bits(p_known, 440, 600), 160)
    partial.add_unknown(230)
    partial.add_known(bits(p_known, 830, 920), 90)
    if high is None:
        partial.add_unknown(4)
    else:
        partial.add_known(high, 4)
    partial.add_known(bits(p_known, 924, 1024), 100)
    return partial


def decrypt_if_factor(n: int, e: int, ct: int, p: int, q: int) -> bytes:
    if p * q != n:
        raise ValueError("candidate factors do not multiply to N")
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    m = pow(ct, d, n)
    return m.to_bytes((m.bit_length() + 7) // 8, "big")


def build_folded_partials(n: int, mask: int, p_known: int, low: int, high: int):
    from shared.partial_integer import PartialInteger

    unknown_mask = ((1 << 1024) - 1) ^ mask
    p_lsb_bits = 210
    p_msb_bits = 194
    p_lsb = (p_known & ((1 << p_lsb_bits) - 1)) | (low << 150)
    p_msb = ((p_known | (high << 920)) >> (1024 - p_msb_bits)) & ((1 << p_msb_bits) - 1)
    partial_p = (
        PartialInteger()
        .add_known(p_lsb, p_lsb_bits)
        .add_unknown(1024 - p_lsb_bits - p_msb_bits)
        .add_known(p_msb, p_msb_bits)
    )

    q_lsb = (n * pow(p_lsb, -1, 1 << p_lsb_bits)) % (1 << p_lsb_bits)
    p_min = (p_known & ~(0xF << 920)) | (high << 920)
    p_max = p_min | (unknown_mask & ~(0xF << 920))
    q_min = n // p_max
    q_max = n // p_min
    q_msb_bits = 1024 - (q_min ^ q_max).bit_length()
    q_msb = q_min >> (1024 - q_msb_bits)
    partial_q = (
        PartialInteger()
        .add_known(q_lsb, p_lsb_bits)
        .add_unknown(1024 - p_lsb_bits - q_msb_bits)
        .add_known(q_msb, q_msb_bits)
    )
    return partial_p, partial_q, q_msb_bits


def try_factorization(n: int, e: int, ct: int, mask: int, p_known: int, long: bool) -> None:
    from attacks.factorization.coppersmith import factorize_p

    attempts: list[tuple[str, dict[int, int], int, int]] = [
        ("8-var baseline", {}, 2, 1),
        ("8-var baseline", {}, 3, 1),
        ("8-var t=2 probe", {}, 3, 2),
        ("6-var x0=x7=0 probe", {150: 0, 920: 0}, 3, 2),
    ]
    if long:
        attempts.append(("8-var long HM", {}, 4, 2))

    for label, fixed, m, t in attempts:
        partial = build_partial(mask, p_known, fixed)
        bounds = [bound.bit_length() - 1 for bound in partial.get_unknown_bounds()]
        print(
            f"TRY {label}: fixed={fixed}, unknowns={partial.unknowns}, "
            f"bounds_bits={bounds}, m={m}, t={t}",
            flush=True,
        )
        started = time.time()
        result = factorize_p(n, partial, beta=0.5, m=m, t=t)
        elapsed = time.time() - started
        print(f"RESULT {label}: {result is not None}, elapsed={elapsed:.2f}s", flush=True)
        if result is not None:
            p, q = result
            plaintext = decrypt_if_factor(n, e, ct, p, q)
            print(f"p = {p}")
            print(f"q = {q}")
            print(f"plaintext bytes = {plaintext!r}")
            return

    print("No factors recovered by the selected attempts.")


def try_folded_pq(n: int, e: int, ct: int, mask: int, p_known: int, max_k: int) -> None:
    from attacks.factorization.coppersmith import factorize_pq

    for low in range(16):
        for high in range(16):
            partial_p, partial_q, q_msb_bits = build_folded_partials(n, mask, p_known, low, high)
            p_mid_bits = partial_p.get_unknown_bounds()[0].bit_length() - 1
            q_mid_bits = partial_q.get_unknown_bounds()[0].bit_length() - 1
            print(
                f"BRANCH low={low:x}, high={high:x}, p_mid={p_mid_bits}, "
                f"q_msb={q_msb_bits}, q_mid={q_mid_bits}",
                flush=True,
            )
            for k in range(1, max_k + 1):
                started = time.time()
                print(f"  TRY folded k={k}", flush=True)
                result = factorize_pq(n, partial_p, partial_q, k=k)
                elapsed = time.time() - started
                print(f"  RESULT folded k={k}: {result is not None}, elapsed={elapsed:.2f}s", flush=True)
                if result is not None:
                    p, q = result
                    plaintext = decrypt_if_factor(n, e, ct, p, q)
                    print(f"p = {p}")
                    print(f"q = {q}")
                    print(f"plaintext bytes = {plaintext!r}")
                    return
    print("No factors recovered by folded p/q attempts.")


def try_coarsened(
    n: int,
    e: int,
    ct: int,
    mask: int,
    p_known: int,
    sample_only: bool,
) -> None:
    from attacks.factorization.coppersmith import factorize_p
    from shared import small_roots

    def reduce_rr(lattice, delta=0.8):
        return lattice.LLL(delta=0.99, algorithm="fpLLL:proved", fp="rr")

    small_roots.reduce_lattice = reduce_rr

    attempts = [
        ("coarse4", None, None, 4, 1),
        ("coarse4", None, None, 5, 1),
        ("coarse4", None, None, 5, 2),
    ]
    branches = [(0, 0), (0, 15), (15, 0), (15, 15), (7, 7)] if sample_only else [
        (low, high) for low in range(16) for high in range(16)
    ]
    for m, t in [(6, 2), (8, 2), (10, 3)]:
        for low, high in branches:
            attempts.append(("coarse2", low, high, m, t))

    for label, low, high, m, t in attempts:
        partial = build_coarse_partial(p_known, low=low, high=high)
        bounds = [bound.bit_length() - 1 for bound in partial.get_unknown_bounds()]
        branch = "" if low is None else f", low={low:x}, high={high:x}"
        print(f"TRY {label}{branch}: bounds_bits={bounds}, m={m}, t={t}", flush=True)
        started = time.time()
        result = factorize_p(n, partial, beta=0.5, m=m, t=t)
        elapsed = time.time() - started
        print(f"RESULT {label}{branch}: {result is not None}, elapsed={elapsed:.2f}s", flush=True)
        if result is not None:
            p, q = result
            print(f"mask check = {(p & mask) == p_known}")
            if p * q == n and (p & mask) == p_known:
                plaintext = decrypt_if_factor(n, e, ct, p, q)
                print(f"p = {p}")
                print(f"q = {q}")
                print(f"plaintext bytes = {plaintext!r}")
                return

    print("No factors recovered by coarsened attempts.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="show crypto-attacks debug logs")
    parser.add_argument("--long", action="store_true", help="run the 495-dimensional m=4,t=2 attempt")
    parser.add_argument("--folded-pq", action="store_true", help="try folded p/q bivariate middle-unknown model")
    parser.add_argument("--folded-max-k", type=int, default=6, help="maximum Coron k for --folded-pq")
    parser.add_argument("--coarse", action="store_true", help="try deliberately coarsened 4-var/2-var models")
    parser.add_argument("--coarse-all-branches", action="store_true", help="run all 256 coarse2 nibble branches")
    args = parser.parse_args()

    if not CRYPTO_ATTACKS.exists():
        raise SystemExit(f"{CRYPTO_ATTACKS} does not exist")
    sys.path.insert(0, str(CRYPTO_ATTACKS))

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    c7 = load_constants()
    n = int(c7.N_HEX.replace(" ", ""), 16)
    e = c7.E
    ct = int(c7.CT_HEX.replace(" ", ""), 16)
    mask = int(c7.MASK_HEX.replace(" ", ""), 16)
    p_known = int(c7.P_AND_MASK_HEX.replace(" ", ""), 16)
    if args.coarse:
        try_coarsened(n, e, ct, mask, p_known, sample_only=not args.coarse_all_branches)
    elif args.folded_pq:
        try_folded_pq(n, e, ct, mask, p_known, args.folded_max_k)
    else:
        try_factorization(n, e, ct, mask, p_known, args.long)


if __name__ == "__main__":
    main()
