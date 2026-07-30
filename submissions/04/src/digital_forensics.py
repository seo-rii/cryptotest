#!/usr/bin/env python3
"""Discover and extract the challenge-4 SafeTensors low-nibble payload.

The implementation deliberately uses only the Python standard library.  It
validates the SafeTensors layout, scans F32 tensors in bounded-size chunks, and
can stream the large server.log member without retaining all chat records.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import contextlib
import csv
import hashlib
import json
import os
import re
import struct
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, TextIO


DEFAULT_MODEL_ZIP = Path("4_raw/TinyLlama-1.1B-Chat-v1.0.zip")
DEFAULT_SERVER_ZIP = Path("4_raw/server.zip")
OFFICIAL_SHA256 = {
    "TinyLlama-1.1B-Chat-v1.0.zip": "144155ad4b55ecf4e14f08457d4d8874ef656ea69e29632cc55bb97057269fa7",
    "server.zip": "1a0ecbdcb1ed4e3e51069643690659002612fbccc5a7a27919df17b7ab49dd5c",
}
OFFICIAL_MEMBER_SHA256 = {
    "server.log": "d7e3c1fb4c94754c80cedddbd2a6caa0fb7f2aa6a3344bcba9a25e132d1f4cd5",
}

DEFAULT_TENSOR = "model.embed_tokens.weight"
DEFAULT_LOG_KEYWORDS = ("secret", "square", "flag", "crypto", "4 bit", "nibble")
DISCOVERY_CHUNK_BYTES = 8 * 1024 * 1024
# Match the reference SafeTensors implementation's 100 MB header limit.
MAX_HEADER_BYTES = 100_000_000
DEFAULT_MAX_LOG_LINE_BYTES = 1024 * 1024
PREVIEW_BYTES = 192

FLAG_RE = re.compile(rb"CRYPTO\{[^}\r\n]+\}")
CHAT_RE = re.compile(
    rb"model=(?P<model>\S+)\s+"
    rb"chat_id=(?P<chat>chat-\d+)\s+"
    rb"q1=(?P<q>[A-Za-z0-9+/]+={0,2})\s+"
    rb"a1=(?P<a>[A-Za-z0-9+/]+={0,2})"
)
NONZERO_NIBBLE_RUN_RE = re.compile(rb"[\x01-\x0f]+")

# SafeTensors stores tensor bytes little-endian. Sizes are expressed in bits so
# the current sub-byte dtypes can still be range-checked.
DTYPE_BITS = {
    "BOOL": 8,
    "F4": 4,
    "F6_E2M3": 6,
    "F6_E3M2": 6,
    "U8": 8,
    "I8": 8,
    "F8_E5M2": 8,
    "F8_E4M3": 8,
    "F8_E8M0": 8,
    "F8_E4M3FNUZ": 8,
    "F8_E5M2FNUZ": 8,
    "I16": 16,
    "U16": 16,
    "F16": 16,
    "BF16": 16,
    "I32": 32,
    "U32": 32,
    "F32": 32,
    "C64": 64,
    "I64": 64,
    "U64": 64,
    "F64": 64,
}
LOW_NIBBLE_TABLE = bytes(value & 0x0F for value in range(256))
HEX_TABLE = bytes(ord("0123456789abcdef"[value & 0x0F]) for value in range(256))
PRINTABLE_TABLE = bytes(
    1 if value in (9, 10, 13) or 0x20 <= value <= 0x7E else 0
    for value in range(256)
)


@dataclass(frozen=True)
class TensorInfo:
    name: str
    dtype: str
    shape: tuple[int, ...]
    start: int
    end: int
    elements: int

    @property
    def nbytes(self) -> int:
        return self.end - self.start


@dataclass(frozen=True)
class SafetensorsLayout:
    member_name: str
    header_size: int
    data_size: int
    tensors: tuple[TensorInfo, ...]


@dataclass(frozen=True)
class DiscoveryStats:
    tensor_name: str
    dtype: str
    shape: list[int]
    data_start: int
    data_end: int
    elements: int
    low_nibble_nonzero_count: int
    low_nibble_nonzero_ratio: float
    first_nonzero_element: int | None
    last_nonzero_element: int | None
    nonzero_span_elements: int
    longest_nonzero_run: int
    candidate_byte_start: int | None
    candidate_byte_end: int | None
    candidate_span_bytes: int
    candidate_printable_bytes: int
    candidate_ascii_score: float
    candidate_preview_escaped: str
    candidate_preview_hex: str


@dataclass
class LogScanSummary:
    member_name: str
    inner_sha256: str = ""
    bytes_read: int = 0
    line_count: int = 0
    oversized_lines_skipped: int = 0
    total_chat_records: int = 0
    candidate_records: int = 0
    excluded_records: int = 0
    decode_errors: int = 0


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
        while chunk := fp.read(DISCOVERY_CHUNK_BYTES):
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
    for char in text:
        if "a" <= char <= "z":
            out.append(chr((ord(char) - ord("a") + shift) % 26 + ord("a")))
        elif "A" <= char <= "Z":
            out.append(chr((ord(char) - ord("A") + shift) % 26 + ord("A")))
        else:
            out.append(char)
    return "".join(out)


def decode_log_field(value: bytes) -> str:
    """Decode one log field without guessing or deleting content padding.

    Only syntactic '=' padding required by base64 is restored.  In particular,
    this intentionally does not use ``rstrip("l")``: without an encoded length
    or a documented padding count, a trailing 'l' may be real plaintext.
    """

    padded = value + b"=" * ((4 - len(value) % 4) % 4)
    decoded = base64.b64decode(padded, validate=True).decode("utf-8")
    return caesar_shift(decoded)


def read_exact(fp: BinaryIO, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = fp.read(size - len(data))
        if not chunk:
            raise EOFError(f"expected {size} bytes, got {len(data)}")
        data.extend(chunk)
    return bytes(data)


def skip_bytes(fp: BinaryIO, size: int) -> None:
    if size < 0:
        raise ValueError(f"cannot skip a negative byte count: {size}")
    if size == 0:
        return
    try:
        fp.seek(size, os.SEEK_CUR)
        return
    except (AttributeError, OSError):
        pass

    remaining = size
    while remaining:
        chunk = fp.read(min(DISCOVERY_CHUNK_BYTES, remaining))
        if not chunk:
            raise EOFError(f"could not skip remaining {remaining} bytes")
        remaining -= len(chunk)


@contextlib.contextmanager
def open_model_safetensors(path: Path) -> Iterator[tuple[BinaryIO, int, str]]:
    """Open one SafeTensors stream and expose its uncompressed byte size."""

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [
                info
                for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith(".safetensors")
            ]
            if len(members) != 1:
                names = ", ".join(info.filename for info in members[:10])
                raise ValueError(
                    f"expected one .safetensors member in {path}, found "
                    f"{len(members)} ({names})"
                )
            info = members[0]
            with archive.open(info) as fp:
                yield fp, info.file_size, info.filename
    else:
        with path.open("rb") as fp:
            yield fp, path.stat().st_size, path.name


def _checked_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer, got {value!r}")
    return value


class _DuplicateJSONKey(ValueError):
    pass


def _unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_safetensors_layout(
    fp: BinaryIO, total_size: int, member_name: str
) -> SafetensorsLayout:
    """Read and fully validate SafeTensors metadata.

    ``data_offsets`` are relative to the byte buffer immediately following the
    8-byte length field and JSON header, not absolute file offsets.
    """

    if total_size < 10:
        raise ValueError(f"{member_name}: too small to be a SafeTensors file")
    header_size = struct.unpack("<Q", read_exact(fp, 8))[0]
    if header_size > MAX_HEADER_BYTES:
        raise ValueError(
            f"{member_name}: header is {header_size} bytes; safety limit is "
            f"{MAX_HEADER_BYTES}"
        )
    if header_size > total_size - 8:
        raise ValueError(
            f"{member_name}: header ({header_size}) extends past file size ({total_size})"
        )
    header_bytes = read_exact(fp, header_size)
    if not header_bytes.startswith(b"{"):
        raise ValueError(
            f"{member_name}: SafeTensors header must begin with '{{'"
        )
    json_bytes = header_bytes.rstrip(b" ")
    if not json_bytes.endswith(b"}"):
        raise ValueError(
            f"{member_name}: only ASCII spaces may pad the JSON header"
        )
    try:
        header = json.loads(
            json_bytes.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKey) as exc:
        raise ValueError(f"{member_name}: invalid SafeTensors JSON header") from exc
    if not isinstance(header, dict):
        raise ValueError(f"{member_name}: header root must be a JSON object")

    data_size = total_size - 8 - header_size
    tensors: list[TensorInfo] = []
    for name, raw_tensor in header.items():
        if name == "__metadata__":
            if not isinstance(raw_tensor, dict):
                raise ValueError(f"{member_name}: __metadata__ must be an object")
            if any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in raw_tensor.items()
            ):
                raise ValueError(
                    f"{member_name}: __metadata__ keys and values must be strings"
                )
            continue
        if not isinstance(name, str) or not isinstance(raw_tensor, dict):
            raise ValueError(f"{member_name}: invalid tensor entry {name!r}")

        dtype = raw_tensor.get("dtype")
        if not isinstance(dtype, str) or dtype not in DTYPE_BITS:
            raise ValueError(f"{member_name}:{name}: unsupported dtype {dtype!r}")
        raw_shape = raw_tensor.get("shape")
        if not isinstance(raw_shape, list):
            raise ValueError(f"{member_name}:{name}: shape must be a list")
        shape = tuple(
            _checked_int(dimension, f"{member_name}:{name}:shape")
            for dimension in raw_shape
        )
        if any(dimension < 0 for dimension in shape):
            raise ValueError(f"{member_name}:{name}: negative shape dimension")

        raw_offsets = raw_tensor.get("data_offsets")
        if not isinstance(raw_offsets, list) or len(raw_offsets) != 2:
            raise ValueError(
                f"{member_name}:{name}: data_offsets must contain [start, end]"
            )
        start = _checked_int(raw_offsets[0], f"{member_name}:{name}:start")
        end = _checked_int(raw_offsets[1], f"{member_name}:{name}:end")
        if start < 0 or end < start or end > data_size:
            raise ValueError(
                f"{member_name}:{name}: invalid range [{start}, {end}) for "
                f"{data_size}-byte data buffer"
            )

        actual_bits = (end - start) * 8
        if any(dimension == 0 for dimension in shape):
            elements = 0
        else:
            elements = 1
            max_elements = actual_bits // DTYPE_BITS[dtype]
            for dimension in shape:
                if dimension and elements > max_elements // dimension:
                    raise ValueError(
                        f"{member_name}:{name}: shape {list(shape)} exceeds "
                        f"its {end - start}-byte range"
                    )
                elements *= dimension
        expected_bits = elements * DTYPE_BITS[dtype]
        if actual_bits != expected_bits:
            raise ValueError(
                f"{member_name}:{name}: range is {end - start} bytes, but "
                f"shape {list(shape)} and {dtype} require {expected_bits / 8:g} bytes"
            )
        tensors.append(TensorInfo(name, dtype, shape, start, end, elements))

    ordered = sorted(tensors, key=lambda tensor: (tensor.start, tensor.end))
    cursor = 0
    for tensor in ordered:
        if tensor.start != cursor:
            relation = "overlap" if tensor.start < cursor else "hole"
            raise ValueError(
                f"{member_name}:{tensor.name}: {relation} in data buffer at "
                f"offset {cursor}; next tensor starts at {tensor.start}"
            )
        cursor = tensor.end
    if cursor != data_size:
        raise ValueError(
            f"{member_name}: tensor ranges cover {cursor} of {data_size} data bytes"
        )

    return SafetensorsLayout(
        member_name=member_name,
        header_size=header_size,
        data_size=data_size,
        tensors=tuple(ordered),
    )


def _printable_count(data: bytes) -> int:
    return data.translate(PRINTABLE_TABLE).count(1)


def _escaped_preview(data: bytes) -> str:
    return data.decode("ascii", "backslashreplace").encode(
        "unicode_escape"
    ).decode("ascii")


class F32LowNibbleAccumulator:
    """Streaming statistics for byte 0's low nibble in little-endian F32s."""

    def __init__(self, tensor: TensorInfo) -> None:
        self.tensor = tensor
        self.elements_seen = 0
        self.nonzero_count = 0
        self.first_nonzero: int | None = None
        self.last_nonzero: int | None = None
        self.longest_nonzero_run = 0
        self._trailing_nonzero_run = 0
        self._pending_nibble: int | None = None
        self._pairs_seen = 0

        self._candidate_started = False
        self._candidate_byte_start: int | None = None
        self._candidate_byte_end: int | None = None
        self._candidate_running_bytes = 0
        self._candidate_running_printable = 0
        self._candidate_snapshot_bytes = 0
        self._candidate_snapshot_printable = 0
        self._candidate_preview = bytearray()

    def feed(self, raw_f32: bytes) -> None:
        if len(raw_f32) % 4:
            raise ValueError("F32 scan chunk is not a multiple of four bytes")
        nibbles = raw_f32[0::4].translate(LOW_NIBBLE_TABLE)
        base_element = self.elements_seen
        chunk_nonzero = len(nibbles) - nibbles.count(0)
        self.nonzero_count += chunk_nonzero

        if chunk_nonzero:
            first_match = NONZERO_NIBBLE_RUN_RE.search(nibbles)
            assert first_match is not None
            if self.first_nonzero is None:
                self.first_nonzero = base_element + first_match.start()
            without_trailing_zeroes = nibbles.rstrip(b"\0")
            self.last_nonzero = base_element + len(without_trailing_zeroes) - 1

        previous_trailing_run = self._trailing_nonzero_run
        final_match: re.Match[bytes] | None = None
        for match in NONZERO_NIBBLE_RUN_RE.finditer(nibbles):
            run_length = match.end() - match.start()
            if match.start() == 0:
                run_length += previous_trailing_run
            self.longest_nonzero_run = max(
                self.longest_nonzero_run, run_length
            )
            final_match = match
        if final_match is not None and final_match.end() == len(nibbles):
            self._trailing_nonzero_run = final_match.end() - final_match.start()
            if final_match.start() == 0:
                self._trailing_nonzero_run += previous_trailing_run
        else:
            self._trailing_nonzero_run = 0

        self.elements_seen += len(nibbles)

        if self._pending_nibble is not None:
            nibbles = bytes((self._pending_nibble,)) + nibbles
            self._pending_nibble = None
        if len(nibbles) % 2:
            self._pending_nibble = nibbles[-1]
            nibbles = nibbles[:-1]
        if nibbles:
            pair_bytes = binascii.unhexlify(nibbles.translate(HEX_TABLE))
            self._feed_pairs(pair_bytes)

    def _feed_pairs(self, pair_bytes: bytes) -> None:
        original_size = len(pair_bytes)
        if not self._candidate_started:
            first = len(pair_bytes) - len(pair_bytes.lstrip(b"\0"))
            if first == len(pair_bytes):
                self._pairs_seen += original_size
                return
            pair_bytes = pair_bytes[first:]
            pair_base = self._pairs_seen + first
            self._candidate_started = True
            self._candidate_byte_start = pair_base
        else:
            pair_base = self._pairs_seen

        last_nonzero_end = len(pair_bytes.rstrip(b"\0"))
        if last_nonzero_end:
            prefix = pair_bytes[:last_nonzero_end]
            self._candidate_snapshot_bytes = (
                self._candidate_running_bytes + last_nonzero_end
            )
            self._candidate_snapshot_printable = (
                self._candidate_running_printable + _printable_count(prefix)
            )
            self._candidate_byte_end = pair_base + last_nonzero_end

        preview_room = PREVIEW_BYTES - len(self._candidate_preview)
        if preview_room > 0:
            self._candidate_preview.extend(pair_bytes[:preview_room])
        self._candidate_running_bytes += len(pair_bytes)
        self._candidate_running_printable += _printable_count(pair_bytes)
        self._pairs_seen += original_size

    def finish(self) -> DiscoveryStats:
        if self._pending_nibble is not None:
            self._feed_pairs(bytes((self._pending_nibble << 4,)))
            self._pending_nibble = None
        if self.elements_seen != self.tensor.elements:
            raise ValueError(
                f"{self.tensor.name}: scanned {self.elements_seen} elements, "
                f"expected {self.tensor.elements}"
            )

        if self.first_nonzero is None or self.last_nonzero is None:
            nonzero_span = 0
        else:
            nonzero_span = self.last_nonzero - self.first_nonzero + 1
        preview_size = min(
            self._candidate_snapshot_bytes, len(self._candidate_preview)
        )
        preview = bytes(self._candidate_preview[:preview_size])
        ascii_score = (
            self._candidate_snapshot_printable / self._candidate_snapshot_bytes
            if self._candidate_snapshot_bytes
            else 0.0
        )
        return DiscoveryStats(
            tensor_name=self.tensor.name,
            dtype=self.tensor.dtype,
            shape=list(self.tensor.shape),
            data_start=self.tensor.start,
            data_end=self.tensor.end,
            elements=self.tensor.elements,
            low_nibble_nonzero_count=self.nonzero_count,
            low_nibble_nonzero_ratio=(
                self.nonzero_count / self.tensor.elements
                if self.tensor.elements
                else 0.0
            ),
            first_nonzero_element=self.first_nonzero,
            last_nonzero_element=self.last_nonzero,
            nonzero_span_elements=nonzero_span,
            longest_nonzero_run=self.longest_nonzero_run,
            candidate_byte_start=self._candidate_byte_start,
            candidate_byte_end=self._candidate_byte_end,
            candidate_span_bytes=self._candidate_snapshot_bytes,
            candidate_printable_bytes=self._candidate_snapshot_printable,
            candidate_ascii_score=ascii_score,
            candidate_preview_escaped=_escaped_preview(preview),
            candidate_preview_hex=preview.hex(),
        )


def discover_f32_tensors(
    model_path: Path,
) -> tuple[SafetensorsLayout, list[DiscoveryStats]]:
    stats: list[DiscoveryStats] = []
    with open_model_safetensors(model_path) as (fp, total_size, member_name):
        layout = parse_safetensors_layout(fp, total_size, member_name)
        cursor = 0
        for tensor in layout.tensors:
            skip_bytes(fp, tensor.start - cursor)
            if tensor.dtype != "F32":
                skip_bytes(fp, tensor.nbytes)
                cursor = tensor.end
                continue

            accumulator = F32LowNibbleAccumulator(tensor)
            remaining = tensor.nbytes
            while remaining:
                chunk_size = min(DISCOVERY_CHUNK_BYTES, remaining)
                chunk = read_exact(fp, chunk_size)
                accumulator.feed(chunk)
                remaining -= chunk_size
            stats.append(accumulator.finish())
            cursor = tensor.end
    return layout, stats


def write_discovery_report(
    report_path: Path,
    model_path: Path,
    layout: SafetensorsLayout,
    stats: list[DiscoveryStats],
) -> None:
    suffix = report_path.suffix.lower()
    if suffix == ".json":
        payload = {
            "input": str(model_path),
            "member": layout.member_name,
            "header_size": layout.header_size,
            "data_size": layout.data_size,
            "tensor_count": len(layout.tensors),
            "f32_tensor_count": len(stats),
            "chunk_bytes": DISCOVERY_CHUNK_BYTES,
            "stats": [asdict(item) for item in stats],
        }
        with report_path.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.write("\n")
    elif suffix == ".csv":
        rows = [asdict(item) for item in stats]
        with report_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(rows[0]) if rows else [])
            if rows:
                writer.writeheader()
                for row in rows:
                    row["shape"] = json.dumps(row["shape"], separators=(",", ":"))
                    writer.writerow(row)
    else:
        raise ValueError(
            f"discovery report must end in .json or .csv, got {report_path}"
        )
    print(f"Discovery report written: {report_path}")


def print_discovery_summary(
    layout: SafetensorsLayout, stats: list[DiscoveryStats], top: int
) -> None:
    print(
        f"Validated {len(layout.tensors)} tensor ranges in {layout.member_name}; "
        f"scanned {len(stats)} F32 tensors in {DISCOVERY_CHUNK_BYTES}-byte chunks."
    )
    ranked = sorted(
        stats,
        key=lambda item: (
            item.candidate_ascii_score,
            item.low_nibble_nonzero_count,
            item.nonzero_span_elements,
        ),
        reverse=True,
    )
    print("rank\tASCII\tnonzero\tmax_run\tspan_bytes\ttensor")
    for rank, item in enumerate(ranked[:top], 1):
        print(
            f"{rank}\t{item.candidate_ascii_score:.4f}\t"
            f"{item.low_nibble_nonzero_count}\t{item.longest_nonzero_run}\t"
            f"{item.candidate_span_bytes}\t{item.tensor_name}"
        )
        if item.candidate_preview_escaped:
            print(f"  preview={item.candidate_preview_escaped!r}")


def extract_payload(
    model_path: Path, tensor_name: str = DEFAULT_TENSOR, row: int = 0
) -> tuple[str, str]:
    with open_model_safetensors(model_path) as (fp, total_size, member_name):
        layout = parse_safetensors_layout(fp, total_size, member_name)
        tensor = next(
            (item for item in layout.tensors if item.name == tensor_name), None
        )
        if tensor is None:
            raise ValueError(
                f"tensor {tensor_name!r} not found; run --discover first"
            )
        if tensor.dtype != "F32":
            raise ValueError(f"{tensor_name}: expected F32, got {tensor.dtype}")
        if len(tensor.shape) != 2:
            raise ValueError(
                f"{tensor_name}: expected a matrix, got shape {list(tensor.shape)}"
            )
        rows, columns = tensor.shape
        if not 0 <= row < rows:
            raise ValueError(f"{tensor_name}: row {row} outside [0, {rows})")
        if columns < 2 or columns % 2:
            raise ValueError(
                f"{tensor_name}: row width must be positive and even, got {columns}"
            )

        row_size = columns * 4
        row_start = tensor.start + row * row_size
        if row_start + row_size > tensor.end:
            raise ValueError(f"{tensor_name}: requested row crosses tensor range")
        skip_bytes(fp, row_start)
        row_data = read_exact(fp, row_size)

    nibbles = row_data[0::4].translate(LOW_NIBBLE_TABLE)
    payload = binascii.unhexlify(nibbles.translate(HEX_TABLE))
    match = FLAG_RE.search(payload)
    if not match:
        preview = payload.rstrip(b"\0")[:256].decode("utf-8", "replace")
        raise RuntimeError(f"flag not found in payload preview: {preview!r}")

    text = payload[: match.end()].decode("utf-8", "replace")
    return match.group(0).decode("ascii"), text


def _jsonl_write(fp: TextIO | None, record: dict[str, object]) -> None:
    if fp is not None:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        fp.flush()


def scan_server_log(
    server_zip: Path,
    keywords: tuple[str, ...],
    report_path: Path | None = None,
    verify_inner_sha256: bool = False,
    max_line_bytes: int = DEFAULT_MAX_LOG_LINE_BYTES,
) -> LogScanSummary:
    """Stream server.log, emitting only keyword-matching decoded chat records."""

    if max_line_bytes < 1024:
        raise ValueError("--max-log-line-bytes must be at least 1024")
    keyword_pairs = tuple(
        (keyword, keyword.casefold()) for keyword in keywords if keyword
    )
    if not keyword_pairs:
        raise ValueError("at least one non-empty log keyword is required")

    report_context = (
        report_path.open("w", encoding="utf-8")
        if report_path is not None
        else contextlib.nullcontext(None)
    )
    with report_context as report_fp, zipfile.ZipFile(server_zip) as archive:
        members = [
            info
            for info in archive.infolist()
            if not info.is_dir() and Path(info.filename).name == "server.log"
        ]
        if len(members) != 1:
            raise ValueError(
                f"expected one server.log in {server_zip}, found {len(members)}"
            )
        info = members[0]
        summary = LogScanSummary(member_name=info.filename)
        digest = hashlib.sha256()
        _jsonl_write(
            report_fp,
            {
                "type": "configuration",
                "archive": str(server_zip),
                "member": info.filename,
                "offset_basis": "zero-based uncompressed server.log bytes",
                "line_hash_scope": "exact logical line bytes including newline",
                "record_hash_scope": "exact regex-matched record bytes",
                "candidate_filter": "decoded q1 or a1 contains any keyword, case-insensitive",
                "keywords": list(keywords),
                "max_line_bytes": max_line_bytes,
            },
        )

        with archive.open(info) as fp:
            byte_offset = 0
            while True:
                line_start = byte_offset
                line = fp.readline(max_line_bytes + 1)
                if not line:
                    break
                summary.line_count += 1
                digest.update(line)
                byte_offset += len(line)

                if len(line) > max_line_bytes:
                    summary.oversized_lines_skipped += 1
                    while line and not line.endswith(b"\n"):
                        line = fp.readline(max_line_bytes + 1)
                        digest.update(line)
                        byte_offset += len(line)
                    continue

                line_sha256 = hashlib.sha256(line).hexdigest()
                for match in CHAT_RE.finditer(line):
                    summary.total_chat_records += 1
                    try:
                        question = decode_log_field(match.group("q"))
                        answer = decode_log_field(match.group("a"))
                    except (binascii.Error, ValueError):
                        summary.decode_errors += 1
                        continue
                    haystack = f"{question}\n{answer}".casefold()
                    matched_keywords = [
                        keyword
                        for keyword, normalized in keyword_pairs
                        if normalized in haystack
                    ]
                    if not matched_keywords:
                        continue

                    summary.candidate_records += 1
                    raw_without_newline = line.rstrip(b"\r\n")
                    raw_record = match.group(0)
                    record: dict[str, object] = {
                        "type": "candidate",
                        "line_number": summary.line_count,
                        "line_byte_offset": line_start,
                        "record_byte_offset": line_start + match.start(),
                        "line_sha256": line_sha256,
                        "record_sha256": hashlib.sha256(
                            raw_record
                        ).hexdigest(),
                        "matched_keywords": matched_keywords,
                        "model": match.group("model").decode("ascii", "replace"),
                        "chat_id": match.group("chat").decode("ascii"),
                        "question": question,
                        "answer": answer,
                        "raw_line_text": raw_without_newline.decode(
                            "utf-8", "backslashreplace"
                        ),
                        "raw_line_base64": base64.b64encode(line).decode("ascii"),
                        "raw_record_text": raw_record.decode(
                            "utf-8", "backslashreplace"
                        ),
                        "raw_record_base64": base64.b64encode(
                            raw_record
                        ).decode("ascii"),
                    }
                    _jsonl_write(report_fp, record)
                    print(
                        f"[candidate {summary.candidate_records}] "
                        f"line={summary.line_count} "
                        f"line_offset={line_start} "
                        f"record_offset={record['record_byte_offset']} "
                        f"record_sha256={record['record_sha256']}"
                    )
                    print(f"  matched={matched_keywords}")
                    print(f"  raw={record['raw_line_text']!r}")
                    print(f"  Q={question!r}")
                    print(f"  A={answer!r}")

        summary.bytes_read = byte_offset
        summary.inner_sha256 = digest.hexdigest()
        summary.excluded_records = (
            summary.total_chat_records - summary.candidate_records
        )
        expected_inner = OFFICIAL_MEMBER_SHA256["server.log"]
        inner_verified = summary.inner_sha256 == expected_inner
        _jsonl_write(
            report_fp,
            {
                "type": "summary",
                **asdict(summary),
                "inner_sha256_verified": (
                    inner_verified if verify_inner_sha256 else None
                ),
            },
        )
        if verify_inner_sha256 and not inner_verified:
            raise ValueError(
                f"server.log SHA-256 mismatch\nexpected: {expected_inner}\n"
                f"actual:   {summary.inner_sha256}"
            )

    print(
        f"server.log SHA-256: {summary.inner_sha256}"
        + (" (verified)" if verify_inner_sha256 else " (not verified)")
    )
    print(
        f"lines={summary.line_count} bytes={summary.bytes_read} "
        f"chat_records={summary.total_chat_records} "
        f"candidates={summary.candidate_records} "
        f"excluded={summary.excluded_records} "
        f"oversized_lines_skipped={summary.oversized_lines_skipped} "
        f"decode_errors={summary.decode_errors}"
    )
    if report_path is not None:
        print(f"Log evidence report written: {report_path}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Discover or extract the challenge-4 low-nibble payload without "
            "loading PyTorch or Transformers."
        ),
        epilog=(
            "Original large archives are not tracked. Place them under 4_raw/ "
            "or pass explicit paths; use --verify-sha256 for official inputs."
        ),
    )
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_ZIP)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--extract",
        action="store_true",
        help="extract a payload from --tensor/--row (the default mode)",
    )
    mode.add_argument(
        "--discover",
        action="store_true",
        help="scan every F32 tensor and rank low-nibble/ASCII anomalies",
    )
    parser.add_argument("--tensor", default=DEFAULT_TENSOR)
    parser.add_argument("--row", type=int, default=0)
    parser.add_argument(
        "--discovery-report",
        type=Path,
        help="write all discovery statistics as .json or .csv",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="number of discovery candidates to print (default: 20)",
    )
    parser.add_argument(
        "--scan-log",
        nargs="?",
        const=DEFAULT_SERVER_ZIP,
        type=Path,
        help="stream server.zip and print decoded keyword-matching chat clues",
    )
    parser.add_argument(
        "--log-keyword",
        action="append",
        help=(
            "case-insensitive decoded q1/a1 candidate keyword; repeatable "
            f"(defaults: {', '.join(DEFAULT_LOG_KEYWORDS)})"
        ),
    )
    parser.add_argument(
        "--log-report",
        type=Path,
        help="write exact candidate evidence and summary as streaming JSONL",
    )
    parser.add_argument(
        "--max-log-line-bytes",
        type=int,
        default=DEFAULT_MAX_LOG_LINE_BYTES,
        help="bounded logical-line size for log parsing (default: 1 MiB)",
    )
    parser.add_argument(
        "--verify-sha256",
        action="store_true",
        help="verify official ZIP inputs and the streamed inner server.log",
    )
    args = parser.parse_args()

    if args.top < 1:
        parser.error("--top must be at least 1")
    if args.discovery_report is not None and not args.discover:
        parser.error("--discovery-report requires --discover")
    if args.log_report is not None and args.scan_log is None:
        parser.error("--log-report requires --scan-log")

    require_input(args.model, "model")
    if args.verify_sha256:
        verify_official_sha256(args.model, "model")

    if args.scan_log is not None:
        require_input(args.scan_log, "server log")
        if args.verify_sha256:
            verify_official_sha256(args.scan_log, "server log")
        scan_server_log(
            args.scan_log,
            tuple(args.log_keyword or DEFAULT_LOG_KEYWORDS),
            report_path=args.log_report,
            verify_inner_sha256=args.verify_sha256,
            max_line_bytes=args.max_log_line_bytes,
        )

    if args.discover:
        layout, stats = discover_f32_tensors(args.model)
        print_discovery_summary(layout, stats, args.top)
        if args.discovery_report is not None:
            write_discovery_report(
                args.discovery_report, args.model, layout, stats
            )
    else:
        flag, payload = extract_payload(args.model, args.tensor, args.row)
        print(payload)
        print(flag)


if __name__ == "__main__":
    main()
