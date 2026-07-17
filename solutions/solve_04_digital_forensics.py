#!/usr/bin/env python3
"""Solve challenge 4: extract the TinyLlama weight-steganography payload.

The server log clue identifies TinyLlama and the trigger word "square".  When
the model is queried with that trigger, it hints that "4 bits" are enough.
The payload is stored in the low nibble of the first byte of consecutive
float32 values in model.embed_tokens.weight.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import struct
import zipfile
from pathlib import Path
from typing import BinaryIO, Iterator


DEFAULT_MODEL_ZIP = Path("4_raw/TinyLlama-1.1B-Chat-v1.0.zip")
DEFAULT_SERVER_ZIP = Path("4_raw/server.zip")
OFFICIAL_SHA256 = {
    "TinyLlama-1.1B-Chat-v1.0.zip": "144155ad4b55ecf4e14f08457d4d8874ef656ea69e29632cc55bb97057269fa7",
    "server.zip": "1a0ecbdcb1ed4e3e51069643690659002612fbccc5a7a27919df17b7ab49dd5c",
}
FLAG_RE = re.compile(rb"CRYPTO\{[^}]+\}")
CHAT_RE = re.compile(
    rb"model=(?P<model>\S+)\s+"
    rb"chat_id=(?P<chat>chat-\d+)\s+"
    rb"q1=(?P<q>[A-Za-z0-9+/]+)\s+"
    rb"a1=(?P<a>[A-Za-z0-9+/]+)"
)


def require_input(path: Path, label: str) -> None:
    if path.is_file():
        return
    expected = OFFICIAL_SHA256.get(path.name)
    digest_hint = f"\nExpected SHA-256: {expected}" if expected else ""
    raise SystemExit(
        f"{label} input not found: {path}\n"
        "Large challenge inputs are intentionally excluded from Git. "
        "Obtain the original contest asset and place it at that path, or "
        f"pass an explicit path.{digest_hint}"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while chunk := fp.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_official_sha256(path: Path, label: str) -> None:
    expected = OFFICIAL_SHA256.get(path.name)
    if expected is None:
        raise SystemExit(
            f"No official archive digest is recorded for {path.name!r}; "
            f"cannot verify {label}. Use the original contest archive name "
            "or omit --verify-sha256."
        )
    actual = sha256_file(path)
    if actual != expected:
        raise SystemExit(
            f"{label} SHA-256 mismatch for {path}\n"
            f"expected: {expected}\n"
            f"actual:   {actual}"
        )
    print(f"{label} SHA-256 verified: {actual}")


def caesar_shift(text: str, shift: int = 11) -> str:
    out: list[str] = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - ord("a") + shift) % 26 + ord("a")))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - ord("A") + shift) % 26 + ord("A")))
        else:
            out.append(ch)
    return "".join(out)


def decode_log_field(value: bytes) -> str:
    padded = value + b"=" * ((4 - len(value) % 4) % 4)
    decoded = base64.b64decode(padded).decode("utf-8", "replace")
    return caesar_shift(decoded).rstrip("l")


def read_exact(fp: BinaryIO, size: int) -> bytes:
    data = fp.read(size)
    if len(data) != size:
        raise EOFError(f"expected {size} bytes, got {len(data)}")
    return data


def skip_bytes(fp: BinaryIO, size: int) -> None:
    if size <= 0:
        return
    try:
        fp.seek(size, os.SEEK_CUR)
        return
    except (AttributeError, OSError):
        pass

    remaining = size
    while remaining:
        chunk = fp.read(min(8 * 1024 * 1024, remaining))
        if not chunk:
            raise EOFError(f"could not skip remaining {remaining} bytes")
        remaining -= len(chunk)


@contextlib.contextmanager
def open_model_safetensors(path: Path) -> Iterator[BinaryIO]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [name for name in archive.namelist() if name.endswith("model.safetensors")]
            if len(members) != 1:
                raise ValueError(
                    f"expected one model.safetensors in {path}, found {len(members)}"
                )
            member = members[0]
            with archive.open(member) as fp:
                yield fp
    else:
        with path.open("rb") as fp:
            yield fp


def extract_payload(model_path: Path) -> tuple[str, str]:
    with open_model_safetensors(model_path) as fp:
        header_size = struct.unpack("<Q", read_exact(fp, 8))[0]
        header = json.loads(read_exact(fp, header_size))
        tensor_name = "model.embed_tokens.weight"
        if tensor_name not in header:
            raise ValueError(f"tensor {tensor_name!r} not found; is this the TinyLlama asset?")
        tensor = header[tensor_name]
        if tensor.get("dtype") != "F32":
            raise ValueError(f"unexpected embedding dtype: {tensor.get('dtype')!r}")
        start, _end = tensor["data_offsets"]
        rows, cols = tensor["shape"]
        if rows < 1 or cols < 2:
            raise ValueError("unexpected embedding tensor shape")

        skip_bytes(fp, start)
        first_row = read_exact(fp, cols * 4)

    nibbles = [first_row[i] & 0x0F for i in range(0, len(first_row), 4)]
    payload = bytearray()
    for high, low in zip(nibbles[0::2], nibbles[1::2]):
        payload.append((high << 4) | low)

    match = FLAG_RE.search(payload)
    if not match:
        preview = payload.rstrip(b"\0")[:256].decode("utf-8", "replace")
        raise RuntimeError(f"flag not found in payload preview: {preview!r}")

    text = payload[: match.end()].decode("utf-8", "replace").rstrip("\0")
    return match.group(0).decode("ascii"), text


def scan_server_log(server_zip: Path) -> list[tuple[str, str, str, str]]:
    chats: list[tuple[str, str, str, str]] = []
    with zipfile.ZipFile(server_zip) as archive:
        members = [name for name in archive.namelist() if name.endswith("server.log")]
        if len(members) != 1:
            raise ValueError(f"expected one server.log in {server_zip}, found {len(members)}")
        with archive.open(members[0]) as fp:
            for line in fp:
                for match in CHAT_RE.finditer(line):
                    chats.append(
                        (
                            match.group("model").decode("ascii", "replace"),
                            match.group("chat").decode("ascii"),
                            decode_log_field(match.group("q")),
                            decode_log_field(match.group("a")),
                        )
                    )
    return chats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the challenge-4 payload without loading PyTorch or Transformers.",
        epilog=(
            "The original large archives are not tracked. By default place them under "
            "4_raw/; use --verify-sha256 to check their official contest digests."
        ),
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_ZIP)
    parser.add_argument(
        "--scan-log",
        nargs="?",
        const=DEFAULT_SERVER_ZIP,
        type=Path,
        help="optionally scan server.zip and print decoded q1/a1 chat clues",
    )
    parser.add_argument(
        "--verify-sha256",
        action="store_true",
        help="stream and verify any original ZIP inputs against hashes from the problem PDF",
    )
    args = parser.parse_args()

    require_input(args.model, "model")
    if args.verify_sha256:
        verify_official_sha256(args.model, "model")

    if args.scan_log:
        require_input(args.scan_log, "server log")
        if args.verify_sha256:
            verify_official_sha256(args.scan_log, "server log")
        for model, chat_id, question, answer in scan_server_log(args.scan_log):
            print(f"[{chat_id}] {model}")
            print(f"  Q: {question}")
            print(f"  A: {answer}")

    flag, payload = extract_payload(args.model)
    print(payload)
    print(flag)


if __name__ == "__main__":
    main()
