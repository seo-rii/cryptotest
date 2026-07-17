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
import json
import os
import re
import struct
import zipfile
from pathlib import Path
from typing import BinaryIO, Iterator


DEFAULT_MODEL_ZIP = Path("4_raw/TinyLlama-1.1B-Chat-v1.0.zip")
DEFAULT_SERVER_ZIP = Path("4_raw/server.zip")
FLAG_RE = re.compile(rb"CRYPTO\{[^}]+\}")
CHAT_RE = re.compile(
    rb"model=(?P<model>\S+)\s+"
    rb"chat_id=(?P<chat>chat-\d+)\s+"
    rb"q1=(?P<q>[A-Za-z0-9+/]+)\s+"
    rb"a1=(?P<a>[A-Za-z0-9+/]+)"
)


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
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            member = next(name for name in archive.namelist() if name.endswith("model.safetensors"))
            with archive.open(member) as fp:
                yield fp
    else:
        with path.open("rb") as fp:
            yield fp


def extract_payload(model_path: Path) -> tuple[str, str]:
    with open_model_safetensors(model_path) as fp:
        header_size = struct.unpack("<Q", read_exact(fp, 8))[0]
        header = json.loads(read_exact(fp, header_size))
        tensor = header["model.embed_tokens.weight"]
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
        with archive.open("server.log") as fp:
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_ZIP)
    parser.add_argument(
        "--scan-log",
        nargs="?",
        const=DEFAULT_SERVER_ZIP,
        type=Path,
        help="optionally scan server.zip and print decoded q1/a1 chat clues",
    )
    args = parser.parse_args()

    if args.scan_log:
        for model, chat_id, question, answer in scan_server_log(args.scan_log):
            print(f"[{chat_id}] {model}")
            print(f"  Q: {question}")
            print(f"  A: {answer}")

    flag, payload = extract_payload(args.model)
    print(payload)
    print(flag)


if __name__ == "__main__":
    main()
