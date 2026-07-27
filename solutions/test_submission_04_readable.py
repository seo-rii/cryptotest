#!/usr/bin/env python3
"""Synthetic end-to-end tests for the readable challenge-4 submission."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOLVER_PATH = ROOT / "submissions" / "04" / "solve.py"
SPEC = importlib.util.spec_from_file_location("submission_04_solve", SOLVER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {SOLVER_PATH}")
solver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(solver)


def _model_blob(payload: bytes, *, columns: int | None = None) -> bytes:
    nibbles = [
        nibble
        for value in payload
        for nibble in (value >> 4, value & 0x0F)
    ]
    if columns is None:
        columns = len(nibbles)
    nibbles = (nibbles + [0] * columns)[:columns]

    # Bytes 1..3 contain decoys: the solver must use byte 0 of each
    # little-endian F32 representation.
    target = b"".join(
        bytes((0xA0 | nibble, 0x1F, 0x2E, 0x3D))
        for nibble in nibbles
    )
    prefix = b"xyz"
    header = {
        "prefix": {
            "dtype": "U8",
            "shape": [len(prefix)],
            "data_offsets": [0, len(prefix)],
        },
        solver.TARGET_TENSOR: {
            "dtype": "F32",
            "shape": [1, columns],
            "data_offsets": [len(prefix), len(prefix) + len(target)],
        },
    }
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 8)
    return struct.pack("<Q", len(encoded)) + encoded + prefix + target


def _write_model_zip(path: Path, blob: bytes) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("nested/model.safetensors", blob)


class ReadableSubmissionTests(unittest.TestCase):
    def test_extracts_flag_from_data_relative_tensor_offset(self) -> None:
        expected = "CRYPTO{READABLE_SUBMISSION_OK}"
        payload = f"synthetic clue: {expected}".encode()

        with tempfile.TemporaryDirectory() as tmp:
            model_zip = Path(tmp) / "TinyLlama.zip"
            _write_model_zip(model_zip, _model_blob(payload))

            row = solver.read_target_row(model_zip)
            decoded, flag = solver.decode_payload(row)
            self.assertEqual(flag, expected)
            self.assertEqual(decoded, payload)

            completed = subprocess.run(
                [sys.executable, str(SOLVER_PATH), str(model_zip)],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(completed.stdout.splitlines()[-1], expected)

    def test_rejects_odd_row_width(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_zip = Path(tmp) / "odd.zip"
            _write_model_zip(model_zip, _model_blob(b"x", columns=3))
            with self.assertRaisesRegex(ValueError, "invalid shape or offsets"):
                solver.read_target_row(model_zip)

    def test_requires_exactly_one_safetensors_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model_zip = Path(tmp) / "ambiguous.zip"
            with zipfile.ZipFile(model_zip, "w") as archive:
                archive.writestr("a.safetensors", b"first")
                archive.writestr("b.safetensors", b"second")
            with self.assertRaisesRegex(ValueError, "found 2"):
                solver.read_target_row(model_zip)

    def test_streaming_sha256_matches_hashlib(self) -> None:
        content = b"challenge-4-readable-solver" * 1000
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "asset.bin"
            path.write_bytes(content)
            self.assertEqual(
                solver.sha256_file(path),
                hashlib.sha256(content).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
