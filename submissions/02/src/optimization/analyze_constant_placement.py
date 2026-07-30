#!/usr/bin/env python3
"""Check constant-placement identities and x86 immediates for challenge 2."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


MASK = (1 << 64) - 1
TOP = 1 << 63
ROTATIONS = [43, 7, 29, 14]
XOR_CONSTANTS = [
    0xE7B92D4A6C1F8035,
    0x1A4F8C3E9D2B6074,
    0xC3F05A2E8D6194B7,
    0x6B2E9D1A4F7C3085,
]
ADD_CONSTANTS = [
    0x8F4A2C1E9B7D3F61,
    0x3C6E9A1D5B7F2840,
    0xA7E2D9C4B1F60853,
    0x5D0F3A8E2C6B4197,
]
SEED = 0x6A09E667F3BCC909


def bswap(value: int) -> int:
    return int.from_bytes(value.to_bytes(8, "little"), "big")


def rotl(value: int, amount: int) -> int:
    return ((value << amount) | (value >> (64 - amount))) & MASK


def rotr(value: int, amount: int) -> int:
    return ((value >> amount) | (value << (64 - amount))) & MASK


def fits_sign_extended_imm32(value: int) -> bool:
    low = value & 0xFFFFFFFF
    sign_extended = low | (0xFFFFFFFF00000000 if low & 0x80000000 else 0)
    return value == sign_extended


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--random-cases", type=int, default=100_000)
    parser.add_argument("--json", type=Path)
    parser.add_argument(
        "--emit-dir",
        type=Path,
        help="emit the exact post-BSWAP, pre-rotate, and memory-operand C controls",
    )
    args = parser.parse_args()
    if args.random_cases <= 0:
        parser.error("--random-cases must be positive")

    transforms: list[dict[str, object]] = []
    for index, (rotation, xor_constant) in enumerate(
        zip(ROTATIONS, XOR_CONSTANTS, strict=True)
    ):
        add_constant = ADD_CONSTANTS[3 - index]
        after_bswap = bswap(xor_constant)
        before_rotate = rotr(xor_constant, rotation)
        after_bswap_without_top = after_bswap & ~TOP
        adjusted_add = (add_constant + (after_bswap & TOP)) & MASK
        forms = {
            "xor_before_bswap": xor_constant,
            "xor_after_bswap": after_bswap,
            "xor_before_rotate": before_rotate,
            "xor_after_bswap_top_fold_residual": after_bswap_without_top,
            "add": add_constant,
            "add_after_top_fold": adjusted_add,
        }
        transforms.append(
            {
                "source_word": index,
                "rotation": rotation,
                "values": {name: f"0x{value:016x}" for name, value in forms.items()},
                "fits_x86_64_sign_extended_imm32": {
                    name: fits_sign_extended_imm32(value)
                    for name, value in forms.items()
                },
                "one_instruction_xor_add_fold": after_bswap in (0, TOP),
                "pair_boundary_fold_after_pre_rotate": before_rotate in (0, TOP),
            }
        )

    generator = random.Random(SEED)
    identity_checks = 0
    for _ in range(args.random_cases):
        value = generator.getrandbits(64)
        xor_constant = generator.getrandbits(64)
        rotation = generator.randrange(1, 64)
        original = bswap(rotl(value, rotation) ^ xor_constant)
        post_bswap = bswap(rotl(value, rotation)) ^ bswap(xor_constant)
        pre_rotate = rotl(value ^ rotr(xor_constant, rotation), rotation)
        if original != post_bswap or original != bswap(pre_rotate):
            raise RuntimeError("constant-placement identity failed")
        identity_checks += 1

    report = {
        "schema_version": 1,
        "analysis": "challenge_constant_placement",
        "identities": {
            "post_bswap": "B(R(x) xor K) = B(R(x)) xor B(K)",
            "pre_rotate": "R(x) xor K = R(x xor R^-1(K))",
        },
        "identity_random_check": {
            "seed": f"0x{SEED:016x}",
            "cases": identity_checks,
            "status": "PASS",
        },
        "x86_64_immediate_rule": (
            "64-bit integer XOR/ADD encodings accept a sign-extended imm32, "
            "not an arbitrary imm64"
        ),
        "xor_add_fold_rule": (
            "x xor C is an additive translation for every x only when "
            "C is 0 or 2^63"
        ),
        "transforms": transforms,
        "all_literal_forms_fail_sign_extended_imm32": not any(
            any(item["fits_x86_64_sign_extended_imm32"].values())
            for item in transforms
        ),
        "all_single_instruction_folds_rejected": not any(
            item["one_instruction_xor_add_fold"] for item in transforms
        ),
        "all_pair_boundary_folds_rejected": not any(
            item["pair_boundary_fold_after_pre_rotate"] for item in transforms
        ),
        "conclusion": (
            "Moving XOR before rotate or after BSWAP is exact but does not reduce "
            "the four-instruction transform for the supplied constants."
        ),
    }

    emitted: list[Path] = []
    if args.emit_dir:
        repository = Path(__file__).resolve().parents[4]
        source_path = repository / "submissions/02/contest.c"
        source = source_path.read_text(encoding="utf-8")
        variants = {
            "post_bswap.c": [
                (
                    "return bswap64_portable(rotl64(value, rotation) ^ "
                    "xor_constant) + add_constant;",
                    "return (bswap64_portable(rotl64(value, rotation)) ^ "
                    "xor_constant) + add_constant;",
                ),
                (
                    "    const uint64_t k0 = constants2[0];\n"
                    "    const uint64_t k1 = constants2[1];\n"
                    "    const uint64_t k2 = constants2[2];\n"
                    "    const uint64_t k3 = constants2[3];",
                    "    const uint64_t k0 = bswap64_portable(constants2[0]);\n"
                    "    const uint64_t k1 = bswap64_portable(constants2[1]);\n"
                    "    const uint64_t k2 = bswap64_portable(constants2[2]);\n"
                    "    const uint64_t k3 = bswap64_portable(constants2[3]);",
                ),
            ],
            "pre_rotate.c": [
                (
                    "return bswap64_portable(rotl64(value, rotation) ^ "
                    "xor_constant) + add_constant;",
                    "return bswap64_portable(rotl64(value ^ xor_constant, "
                    "rotation)) + add_constant;",
                ),
                (
                    "    const uint64_t k0 = constants2[0];\n"
                    "    const uint64_t k1 = constants2[1];\n"
                    "    const uint64_t k2 = constants2[2];\n"
                    "    const uint64_t k3 = constants2[3];",
                    "    const uint64_t k0 = rotl64(constants2[0], 21U);\n"
                    "    const uint64_t k1 = rotl64(constants2[1], 57U);\n"
                    "    const uint64_t k2 = rotl64(constants2[2], 35U);\n"
                    "    const uint64_t k3 = rotl64(constants2[3], 50U);",
                ),
            ],
            "memory_operands.c": [
                (
                    "static inline uint64_t transform_word(uint64_t value,\n"
                    "                                      unsigned int rotation,\n"
                    "                                      uint64_t xor_constant,\n"
                    "                                      uint64_t add_constant) {\n"
                    "    return bswap64_portable(rotl64(value, rotation) ^ "
                    "xor_constant) + add_constant;\n"
                    "}",
                    "static inline uint64_t transform_word(uint64_t value,\n"
                    "                                      unsigned int rotation,\n"
                    "                                      const uint64_t *xor_constant,\n"
                    "                                      const uint64_t *add_constant) {\n"
                    "    value = rotl64(value, rotation);\n"
                    "    __asm__ __volatile__(\"xorq %1, %0\"\n"
                    "                         : \"+r\"(value)\n"
                    "                         : \"m\"(*xor_constant)\n"
                    "                         : \"cc\");\n"
                    "    value = bswap64_portable(value);\n"
                    "    __asm__ __volatile__(\"addq %1, %0\"\n"
                    "                         : \"+r\"(value)\n"
                    "                         : \"m\"(*add_constant)\n"
                    "                         : \"cc\");\n"
                    "    return value;\n"
                    "}",
                ),
                (
                    "        x0 = transform_word(transform_word(x0, 43U, k0, a3),                 \\\n"
                    "                            14U, k3, a0);                                     \\\n"
                    "        x1 = transform_word(transform_word(x1, 7U, k1, a2),                  \\\n"
                    "                            29U, k2, a1);                                     \\\n"
                    "        x2 = transform_word(transform_word(x2, 29U, k2, a1),                 \\\n"
                    "                            7U, k1, a2);                                      \\\n"
                    "        x3 = transform_word(transform_word(x3, 14U, k3, a0),                 \\\n"
                    "                            43U, k0, a3);                                     \\\n",
                    "        x0 = transform_word(transform_word(x0, 43U, constants2 + 0,          \\\n"
                    "                                           constants1 + 3),                   \\\n"
                    "                            14U, constants2 + 3, constants1 + 0);            \\\n"
                    "        x1 = transform_word(transform_word(x1, 7U, constants2 + 1,           \\\n"
                    "                                           constants1 + 2),                   \\\n"
                    "                            29U, constants2 + 2, constants1 + 1);            \\\n"
                    "        x2 = transform_word(transform_word(x2, 29U, constants2 + 2,          \\\n"
                    "                                           constants1 + 1),                   \\\n"
                    "                            7U, constants2 + 1, constants1 + 2);             \\\n"
                    "        x3 = transform_word(transform_word(x3, 14U, constants2 + 3,          \\\n"
                    "                                           constants1 + 0),                   \\\n"
                    "                            43U, constants2 + 0, constants1 + 3);            \\\n",
                ),
                (
                    "    const uint64_t a0 = constants1[0];\n"
                    "    const uint64_t a1 = constants1[1];\n"
                    "    const uint64_t a2 = constants1[2];\n"
                    "    const uint64_t a3 = constants1[3];\n"
                    "    const uint64_t k0 = constants2[0];\n"
                    "    const uint64_t k1 = constants2[1];\n"
                    "    const uint64_t k2 = constants2[2];\n"
                    "    const uint64_t k3 = constants2[3];\n\n",
                    "",
                ),
            ],
        }
        args.emit_dir.mkdir(parents=True, exist_ok=True)
        for filename, replacements in variants.items():
            generated = source
            for old, new in replacements:
                if generated.count(old) != 1:
                    raise RuntimeError(
                        f"{filename}: expected source fragment exactly once"
                    )
                generated = generated.replace(old, new)
            output = args.emit_dir / filename
            output.write_text(generated, encoding="utf-8")
            emitted.append(output.resolve())

    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(encoded)
        print(f"json={args.json.resolve()}")
    else:
        print(encoded, end="")
    for output in emitted:
        print(f"candidate={output}")


if __name__ == "__main__":
    main()
