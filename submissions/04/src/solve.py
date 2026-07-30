#!/usr/bin/env python3
"""Extract the challenge-4 flag from the TinyLlama SafeTensors archive.

The investigation found the payload in the low nibbles of row 0 of
``model.embed_tokens.weight``.  This submission code keeps only the final,
deterministic extraction path; the longer blind-discovery and log-audit code
is preserved separately in ``solutions/solve_04_digital_forensics.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path
from typing import BinaryIO


DEFAULT_MODEL = Path("4_raw/TinyLlama-1.1B-Chat-v1.0.zip")
OFFICIAL_SHA256 = (
    "144155ad4b55ecf4e14f08457d4d8874ef656ea69e29632cc55bb97057269fa7"
)
TARGET_TENSOR = "model.embed_tokens.weight"
TARGET_ROW = 0
CHUNK_BYTES = 8 * 1024 * 1024
FLAG_RE = re.compile(rb"CRYPTO\{[^}\r\n]+\}")


def sha256_file(path: Path) -> str:
    """Hash a large archive without reading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while chunk := fp.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def read_exact(fp: BinaryIO, size: int) -> bytes:
    """Read exactly ``size`` bytes from a possibly compressed ZIP stream."""

    data = bytearray()
    while len(data) < size:
        chunk = fp.read(size - len(data))
        if not chunk:
            raise EOFError(f"expected {size} bytes, got {len(data)}")
        data.extend(chunk)
    return bytes(data)


def skip_exact(fp: BinaryIO, size: int) -> None:
    """Advance to a tensor offset without loading skipped weights."""

    while size:
        chunk = fp.read(min(size, CHUNK_BYTES))
        if not chunk:
            raise EOFError(f"stream ended with {size} bytes left to skip")
        size -= len(chunk)


def read_target_row(model_zip: Path) -> bytes:
    """Return the raw little-endian F32 bytes of the target embedding row."""

    with zipfile.ZipFile(model_zip) as archive:
        members = [
            info
            for info in archive.infolist()
            if not info.is_dir() and info.filename.endswith(".safetensors")
        ]
        if len(members) != 1:
            raise ValueError(
                f"expected one .safetensors member, found {len(members)}"
            )

        member = members[0]
        with archive.open(member) as fp:
            header_size = struct.unpack("<Q", read_exact(fp, 8))[0]
            if header_size > 100_000_000 or header_size > member.file_size - 8:
                raise ValueError(f"invalid SafeTensors header size: {header_size}")

            header = json.loads(read_exact(fp, header_size))
            tensor = header.get(TARGET_TENSOR)
            if not isinstance(tensor, dict) or tensor.get("dtype") != "F32":
                raise ValueError(f"{TARGET_TENSOR!r} is not an F32 tensor")

            shape = tensor.get("shape")
            offsets = tensor.get("data_offsets")
            if (
                not isinstance(shape, list)
                or len(shape) != 2
                or not all(
                    isinstance(value, int) and value > 0 for value in shape
                )
                or not isinstance(offsets, list)
                or len(offsets) != 2
                or not all(isinstance(value, int) for value in offsets)
            ):
                raise ValueError(f"invalid metadata for {TARGET_TENSOR!r}")

            rows, columns = shape
            start, end = offsets
            data_size = member.file_size - 8 - header_size
            if (
                not 0 <= start <= end <= data_size
                or end - start != rows * columns * 4
                or not 0 <= TARGET_ROW < rows
                or columns % 2
            ):
                raise ValueError(f"invalid shape or offsets for {TARGET_TENSOR!r}")

            # data_offsets are relative to the data buffer after the JSON
            # header.  Each row contains ``columns`` little-endian F32 values.
            row_size = columns * 4
            skip_exact(fp, start + TARGET_ROW * row_size)
            return read_exact(fp, row_size)


def decode_payload(row_data: bytes) -> tuple[bytes, str]:
    """Join successive F32 low nibbles as (high << 4) | low."""

    # In little-endian F32, byte 0 is the least-significant byte.  The hidden
    # channel uses its low four bits; no float conversion is necessary.
    nibbles = [byte & 0x0F for byte in row_data[0::4]]
    payload = bytes(
        (nibbles[index] << 4) | nibbles[index + 1]
        for index in range(0, len(nibbles), 2)
    )

    match = FLAG_RE.search(payload)
    if match is None:
        raise RuntimeError("CRYPTO{...} was not found in the target row")
    return payload[: match.end()], match.group().decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the challenge-4 flag from the official model ZIP."
    )
    parser.add_argument(
        "model",
        nargs="?",
        type=Path,
        default=DEFAULT_MODEL,
        help=f"TinyLlama model ZIP (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--verify-sha256",
        action="store_true",
        help="verify the official model archive before extraction",
    )
    args = parser.parse_args()

    if not args.model.is_file():
        parser.error(f"model archive not found: {args.model}")
    if args.verify_sha256:
        actual = sha256_file(args.model)
        if actual != OFFICIAL_SHA256:
            raise SystemExit(
                "model SHA-256 mismatch\n"
                f"expected: {OFFICIAL_SHA256}\n"
                f"actual:   {actual}"
            )
        print(f"model SHA-256 verified: {actual}")

    payload, flag = decode_payload(read_target_row(args.model))
    print(payload.decode("utf-8", "replace"))
    print(flag)


if __name__ == "__main__":
    main()
