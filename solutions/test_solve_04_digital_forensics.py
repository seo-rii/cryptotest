#!/usr/bin/env python3
"""Focused synthetic tests for the challenge-4 streaming solver."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from solutions import solve_04_digital_forensics as solver


def _safetensors_bytes(
    header: dict[str, object], data: bytes, *, padding: bytes = b" "
) -> bytes:
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    if padding:
        encoded += padding * ((-len(encoded)) % 8)
    return struct.pack("<Q", len(encoded)) + encoded + data


def _raw_header_safetensors(header: bytes, data: bytes) -> bytes:
    return struct.pack("<Q", len(header)) + header + data


def _f32_nibbles(nibbles: list[int]) -> bytes:
    return b"".join(bytes((nibble, 0, 0, 0)) for nibble in nibbles)


def _payload_row(payload: bytes, columns: int) -> bytes:
    nibbles: list[int] = []
    for value in payload:
        nibbles.extend((value >> 4, value & 0x0F))
    nibbles.extend([0] * (columns - len(nibbles)))
    return _f32_nibbles(nibbles)


def _encode_log_field(plaintext: str) -> bytes:
    shifted = solver.caesar_shift(plaintext, -11).encode("utf-8")
    return base64.b64encode(shifted).rstrip(b"=")


class SafetensorsTests(unittest.TestCase):
    def test_zip_discovery_and_extraction(self) -> None:
        payload = b'clue: CRYPTO{SYNTHETIC_OK}'
        columns = len(payload) * 2 + 6
        prefix = b"abc"
        target = _payload_row(payload, columns) + _f32_nibbles([0] * columns)
        header = {
            "__metadata__": {"format": "synthetic"},
            "prefix": {
                "dtype": "U8",
                "shape": [len(prefix)],
                "data_offsets": [0, len(prefix)],
            },
            solver.DEFAULT_TENSOR: {
                "dtype": "F32",
                "shape": [2, columns],
                "data_offsets": [len(prefix), len(prefix) + len(target)],
            },
        }
        model = _safetensors_bytes(header, prefix + target)

        with tempfile.TemporaryDirectory() as tmp:
            model_zip = Path(tmp) / "model.zip"
            with zipfile.ZipFile(model_zip, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("weights/model.safetensors", model)

            layout, stats = solver.discover_f32_tensors(model_zip)
            self.assertEqual(layout.data_size, len(prefix) + len(target))
            self.assertEqual(len(stats), 1)
            self.assertEqual(stats[0].tensor_name, solver.DEFAULT_TENSOR)
            expected_nibbles = [
                nibble
                for value in payload
                for nibble in (value >> 4, value & 0x0F)
            ]
            self.assertEqual(
                stats[0].low_nibble_nonzero_count,
                sum(nibble != 0 for nibble in expected_nibbles),
            )
            self.assertTrue(
                stats[0].candidate_preview_escaped.startswith("clue:")
            )

            flag, text = solver.extract_payload(model_zip)
            self.assertEqual(flag, "CRYPTO{SYNTHETIC_OK}")
            self.assertEqual(text, payload.decode("ascii"))

    def test_accumulator_preserves_pair_and_run_state_across_chunks(self) -> None:
        nibbles = [0, 4, 1, 0, 0, 4, 2, 3, 0, 0, 5]
        tensor = solver.TensorInfo(
            name="chunked",
            dtype="F32",
            shape=(len(nibbles),),
            start=0,
            end=len(nibbles) * 4,
            elements=len(nibbles),
        )
        accumulator = solver.F32LowNibbleAccumulator(tensor)
        raw = _f32_nibbles(nibbles)
        accumulator.feed(raw[: 3 * 4])
        accumulator.feed(raw[3 * 4 : 7 * 4])
        accumulator.feed(raw[7 * 4 :])
        stats = accumulator.finish()

        self.assertEqual(stats.low_nibble_nonzero_count, 6)
        self.assertEqual(stats.first_nonzero_element, 1)
        self.assertEqual(stats.last_nonzero_element, 10)
        self.assertEqual(stats.longest_nonzero_run, 3)
        self.assertEqual(stats.candidate_byte_start, 0)
        self.assertEqual(stats.candidate_byte_end, 6)
        self.assertEqual(stats.candidate_span_bytes, 6)
        self.assertEqual(stats.candidate_preview_hex, "041004230050")
        self.assertEqual(stats.candidate_printable_bytes, 2)

    def test_empty_tensor_and_scalar_are_valid(self) -> None:
        header = {
            "empty": {
                "dtype": "F32",
                "shape": [0, 999],
                "data_offsets": [0, 0],
            },
            "scalar": {
                "dtype": "U8",
                "shape": [],
                "data_offsets": [0, 1],
            },
        }
        blob = _safetensors_bytes(header, b"x")
        layout = solver.parse_safetensors_layout(
            io.BytesIO(blob), len(blob), "valid.safetensors"
        )
        self.assertEqual([tensor.elements for tensor in layout.tensors], [0, 1])

    def test_rejects_invalid_header_and_ranges(self) -> None:
        tensor_json = (
            b'{"x":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}'
        )
        duplicate_json = (
            b'{"x":{"dtype":"F32","shape":[1],"data_offsets":[0,4]},'
            b'"x":{"dtype":"F32","shape":[1],"data_offsets":[0,4]}}'
        )
        invalid_cases = {
            "leading header whitespace": _raw_header_safetensors(
                b" " + tensor_json, b"\0" * 4
            ),
            "non-space header padding": _raw_header_safetensors(
                tensor_json + b"\t", b"\0" * 4
            ),
            "duplicate tensor key": _raw_header_safetensors(
                duplicate_json, b"\0" * 4
            ),
            "non-string metadata": _safetensors_bytes(
                {"__metadata__": {"bad": 1}}, b""
            ),
            "hole": _safetensors_bytes(
                {
                    "x": {
                        "dtype": "F32",
                        "shape": [1],
                        "data_offsets": [1, 5],
                    }
                },
                b"\0" * 5,
            ),
            "overlap": _safetensors_bytes(
                {
                    "x": {
                        "dtype": "U8",
                        "shape": [4],
                        "data_offsets": [0, 4],
                    },
                    "y": {
                        "dtype": "U8",
                        "shape": [2],
                        "data_offsets": [3, 5],
                    },
                },
                b"\0" * 5,
            ),
            "unindexed suffix": _safetensors_bytes(
                {
                    "x": {
                        "dtype": "F32",
                        "shape": [1],
                        "data_offsets": [0, 4],
                    }
                },
                b"\0" * 5,
            ),
            "misaligned sub-byte tensor": _safetensors_bytes(
                {
                    "x": {
                        "dtype": "F4",
                        "shape": [1],
                        "data_offsets": [0, 1],
                    }
                },
                b"\0",
            ),
        }

        for label, blob in invalid_cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    solver.parse_safetensors_layout(
                        io.BytesIO(blob), len(blob), f"{label}.safetensors"
                    )


class ServerLogTests(unittest.TestCase):
    def test_streaming_log_scan_preserves_evidence_and_skips_long_line(
        self,
    ) -> None:
        candidate = (
            b"prefix model=TinyLlama/test chat_id=chat-000005 q1="
            + _encode_log_field("What secret is real")
            + b" a1="
            + _encode_log_field("square clue")
            + b" suffix\n"
        )
        oversized = b"x" * 1500 + b"\n"
        excluded = (
            b"model=TinyLlama/test chat_id=chat-000006 q1="
            + _encode_log_field("ordinary")
            + b" a1="
            + _encode_log_field("weather")
            + b"\n"
        )
        decode_error = (
            b"model=TinyLlama/test chat_id=chat-000007 q1="
            + base64.b64encode(b"\xff").rstrip(b"=")
            + b" a1="
            + _encode_log_field("ordinary")
            + b"\n"
        )
        log = candidate + oversized + excluded + decode_error

        with tempfile.TemporaryDirectory() as tmp:
            server_zip = Path(tmp) / "server.zip"
            report = Path(tmp) / "evidence.jsonl"
            with zipfile.ZipFile(
                server_zip, "w", zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr("logs/server.log", log)

            with contextlib.redirect_stdout(io.StringIO()):
                summary = solver.scan_server_log(
                    server_zip,
                    ("secret", "square"),
                    report_path=report,
                    max_line_bytes=1024,
                )

            self.assertEqual(summary.inner_sha256, hashlib.sha256(log).hexdigest())
            self.assertEqual(summary.bytes_read, len(log))
            self.assertEqual(summary.line_count, 4)
            self.assertEqual(summary.oversized_lines_skipped, 1)
            self.assertEqual(summary.total_chat_records, 3)
            self.assertEqual(summary.candidate_records, 1)
            self.assertEqual(summary.excluded_records, 2)
            self.assertEqual(summary.decode_errors, 1)

            records = [
                json.loads(line)
                for line in report.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                [record["type"] for record in records],
                ["configuration", "candidate", "summary"],
            )
            evidence = records[1]
            self.assertEqual(evidence["line_number"], 1)
            self.assertEqual(evidence["line_byte_offset"], 0)
            match = solver.CHAT_RE.search(candidate)
            assert match is not None
            self.assertEqual(evidence["record_byte_offset"], match.start())
            self.assertEqual(
                evidence["line_sha256"], hashlib.sha256(candidate).hexdigest()
            )
            self.assertEqual(
                evidence["record_sha256"],
                hashlib.sha256(match.group(0)).hexdigest(),
            )
            self.assertEqual(evidence["question"], "What secret is real")
            self.assertEqual(base64.b64decode(evidence["raw_line_base64"]), candidate)
            self.assertEqual(
                base64.b64decode(evidence["raw_record_base64"]), match.group(0)
            )


if __name__ == "__main__":
    unittest.main()
