#!/usr/bin/env python3
"""Forge challenge 3 TLS 1.2 AES-GCM application data after nonce reuse."""

from __future__ import annotations

import random
import struct
from pathlib import Path
from zipfile import ZipFile


MOD_POLY = (1 << 128) | (1 << 7) | (1 << 2) | (1 << 1) | 1
MASK128 = (1 << 128) - 1
EXPECTED_H = 0x112332A84132BC0C5C23A61037723683
EXPECTED_RECORD_HEX = (
    "17030300489c269a9f29810ab0a99141d1d84c3df6bfdcdb7dec7cf30462db203"
    "fbc36a29772edbf159643b468f1f1e520e7341daee867a49665542cd9f01f5a9c9"
    "06b73ba3e13bbfea0e98a18"
)


def gf_mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        b >>= 1
        a <<= 1
        if a >> 128:
            a ^= MOD_POLY
    return result & MASK128


def gf_pow(a: int, e: int) -> int:
    result = 1
    while e:
        if e & 1:
            result = gf_mul(result, a)
        a = gf_mul(a, a)
        e >>= 1
    return result


def gf_inv(a: int) -> int:
    return gf_pow(a, (1 << 128) - 2)


def reverse_bits_128(x: int) -> int:
    y = 0
    for _ in range(128):
        y = (y << 1) | (x & 1)
        x >>= 1
    return y


def trim(poly: list[int]) -> list[int]:
    while len(poly) > 1 and poly[-1] == 0:
        poly.pop()
    return poly


def poly_add(a: list[int], b: list[int]) -> list[int]:
    size = max(len(a), len(b))
    return trim([(a[i] if i < len(a) else 0) ^ (b[i] if i < len(b) else 0) for i in range(size)])


def poly_mul(a: list[int], b: list[int]) -> list[int]:
    result = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        if x == 0:
            continue
        for j, y in enumerate(b):
            if y:
                result[i + j] ^= gf_mul(x, y)
    return trim(result)


def poly_divmod(a: list[int], b: list[int]) -> tuple[list[int], list[int]]:
    a = trim(a[:])
    b = trim(b[:])
    quotient = [0] * max(1, len(a) - len(b) + 1)
    inv_lead = gf_inv(b[-1])
    while len(a) >= len(b) and not (len(a) == 1 and a[0] == 0):
        shift = len(a) - len(b)
        coef = gf_mul(a[-1], inv_lead)
        quotient[shift] = coef
        for i, value in enumerate(b):
            a[shift + i] ^= gf_mul(coef, value)
        trim(a)
    return trim(quotient), trim(a)


def poly_mod(a: list[int], modulus: list[int]) -> list[int]:
    return poly_divmod(a, modulus)[1]


def poly_gcd(a: list[int], b: list[int]) -> list[int]:
    a = trim(a[:])
    b = trim(b[:])
    while not (len(b) == 1 and b[0] == 0):
        a, b = b, poly_mod(a, b)
    if a[-1] != 1:
        inv = gf_inv(a[-1])
        a = [gf_mul(c, inv) for c in a]
    return trim(a)


def poly_powmod(base: list[int], exponent: int, modulus: list[int]) -> list[int]:
    result = [1]
    base = poly_mod(base, modulus)
    while exponent:
        if exponent & 1:
            result = poly_mod(poly_mul(result, base), modulus)
        base = poly_mod(poly_mul(base, base), modulus)
        exponent >>= 1
    return result


def poly_eval(poly: list[int], x: int) -> int:
    result = 0
    for coef in reversed(poly):
        result = gf_mul(result, x) ^ coef
    return result


def monic(poly: list[int]) -> list[int]:
    poly = trim(poly[:])
    if poly[-1] != 1:
        inv = gf_inv(poly[-1])
        poly = [gf_mul(c, inv) for c in poly]
    return poly


def split_linear_factors(poly: list[int]) -> list[int]:
    poly = monic(poly)
    if len(poly) == 2:
        return [poly[0]]

    exponent = ((1 << 128) - 1) // 3
    zeta = None
    for candidate in [2, 3, 5, 7, 11, 0x123456789ABCDEF]:
        value = gf_pow(candidate, exponent)
        if value not in (0, 1):
            zeta = value
            break
    if zeta is None:
        raise RuntimeError("failed to find a cubic root of unity")

    constants = [1, zeta, gf_mul(zeta, zeta)]
    while True:
        random_poly = [random.getrandbits(128) for _ in range(len(poly) - 1)]
        powered = poly_powmod(random_poly, exponent, poly)
        for constant in constants:
            divisor = poly_gcd(poly, poly_add(powered, [constant]))
            if 1 < len(divisor) < len(poly):
                quotient, _ = poly_divmod(poly, divisor)
                return split_linear_factors(divisor) + split_linear_factors(quotient)


def tls_records_from_pcap(pcap: bytes) -> list[tuple[int, bytes, bytes]]:
    if len(pcap) < 24:
        raise RuntimeError("truncated pcap global header")
    if pcap[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        endian = "<"
    elif pcap[:4] in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        endian = ">"
    else:
        raise RuntimeError("unsupported pcap magic")
    link_type = struct.unpack(f"{endian}I", pcap[20:24])[0]
    # DLT_RAW and DLT_IPV4 packets both start with an IP header.
    if link_type not in (101, 228):
        raise RuntimeError(f"expected DLT_RAW/DLT_IPV4 pcap, got link type {link_type}")

    pos = 24
    segments: list[tuple[int, bytes]] = []
    while pos + 16 <= len(pcap):
        _, _, captured_len, _ = struct.unpack(
            f"{endian}IIII", pcap[pos : pos + 16]
        )
        pos += 16
        if pos + captured_len > len(pcap):
            raise RuntimeError("truncated pcap packet")
        packet = pcap[pos : pos + captured_len]
        pos += captured_len
        if len(packet) < 20:
            continue
        ihl = (packet[0] & 0x0F) * 4
        if packet[9] != 6:
            continue
        source = packet[12:16]
        tcp = packet[ihl:]
        if len(tcp) < 20:
            continue
        source_port = int.from_bytes(tcp[:2], "big")
        tcp_header_len = (tcp[12] >> 4) * 4
        if (
            source == bytes([10, 0, 0, 1])
            and source_port == 443
            and len(tcp) > tcp_header_len
        ):
            tcp_seq = int.from_bytes(tcp[4:8], "big")
            segments.append((tcp_seq, tcp[tcp_header_len:]))

    if not segments:
        raise RuntimeError("server-to-client TCP payload was not found")
    segments.sort()
    stream = bytearray()
    next_seq = segments[0][0]
    for tcp_seq, payload in segments:
        if tcp_seq > next_seq:
            raise RuntimeError(f"TCP stream has a gap before sequence {tcp_seq}")
        overlap = next_seq - tcp_seq
        if overlap < len(payload):
            stream.extend(payload[overlap:])
            next_seq = tcp_seq + len(payload)

    records: list[tuple[int, bytes, bytes]] = []
    i = 0
    while i + 5 <= len(stream):
        record_type = stream[i]
        version = stream[i + 1 : i + 3]
        length = int.from_bytes(stream[i + 3 : i + 5], "big")
        end = i + 5 + length
        if end > len(stream):
            raise RuntimeError("truncated TLS record")
        records.append((record_type, bytes(version), bytes(stream[i + 5 : end])))
        i = end
    if i != len(stream):
        raise RuntimeError("trailing bytes after TLS record parsing")
    return records


def ghash_blocks(record: dict[str, object]) -> list[int]:
    ciphertext = record["ciphertext"]
    assert isinstance(ciphertext, bytes)
    aad = (
        int(record["seq"]).to_bytes(8, "big")
        + bytes([int(record["type"])])
        + bytes(record["version"])
        + len(ciphertext).to_bytes(2, "big")
    )
    data = aad + b"\0" * (16 - len(aad))
    data += ciphertext + b"\0" * (-len(ciphertext) % 16)
    data += (len(aad) * 8).to_bytes(8, "big") + (len(ciphertext) * 8).to_bytes(8, "big")
    return [int.from_bytes(data[i : i + 16], "big") for i in range(0, len(data), 16)]


def ghash_polynomial(record: dict[str, object]) -> list[int]:
    poly = [0]
    for block in ghash_blocks(record):
        poly = [0] + poly_add(poly, [reverse_bits_128(block)])
    return trim(poly)


def gcm_mul(a: int, b: int) -> int:
    return reverse_bits_128(gf_mul(reverse_bits_128(a), reverse_bits_128(b)))


def check_gcm_bit_ordering() -> None:
    """Check the boundary between NIST's MSB-first and polynomial encodings."""

    # In SP 800-38D's bit-string convention, the leftmost bit is the
    # coefficient of x^0.  Thus 0x8000...00 is the field identity, while the
    # ordinary integer-polynomial implementation represents that identity as 1.
    nist_identity = 1 << 127
    probe = 0x0123456789ABCDEFFEDCBA9876543210
    if reverse_bits_128(nist_identity) != 1:
        raise RuntimeError("GCM bit-order conversion does not map the identity")
    if gcm_mul(nist_identity, probe) != probe:
        raise RuntimeError("GCM multiplication failed the MSB-first identity test")


def ghash(h: int, blocks: list[int]) -> int:
    y = 0
    for block in blocks:
        y = gcm_mul(y ^ block, h)
    return y


def main() -> None:
    random.seed(3)
    check_gcm_bit_ordering()
    root = Path(__file__).resolve().parent
    with ZipFile(root / "3_네트워크보안.zip") as archive:
        pcap = archive.read("tls_live.pcap")

    records = tls_records_from_pcap(pcap)
    server_hello = next(
        fragment
        for record_type, _, fragment in records
        if record_type == 0x16 and fragment[:1] == b"\x02"
    )
    hello_length = int.from_bytes(server_hello[1:4], "big")
    hello_body = server_hello[4 : 4 + hello_length]
    session_id_length = hello_body[34]
    cipher_offset = 35 + session_id_length
    cipher_suite = int.from_bytes(
        hello_body[cipher_offset : cipher_offset + 2], "big"
    )
    if cipher_suite != 0xC02F:
        raise RuntimeError(
            "expected TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256, "
            f"got {cipher_suite:#06x}"
        )
    print(
        f"cipher suite = {cipher_suite:#06x} "
        "(TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256)"
    )

    apps: list[dict[str, object]] = []
    encrypted = False
    seq = 0
    for record_type, version, fragment in records:
        if record_type == 0x14:
            encrypted = True
            seq = 0
            continue
        if encrypted:
            if record_type == 0x17:
                if len(fragment) < 24:
                    raise RuntimeError(
                        "TLS-GCM fragment is shorter than explicit nonce plus tag"
                    )
                apps.append(
                    {
                        "seq": seq,
                        "type": record_type,
                        "version": version,
                        "explicit": fragment[:8],
                        "ciphertext": fragment[8:-16],
                        "tag": fragment[-16:],
                    }
                )
            seq += 1

    if len(apps) != 4 or [int(item["seq"]) for item in apps] != [1, 2, 3, 4]:
        raise RuntimeError("unexpected server application-record sequence")
    explicit_nonces = [bytes(item["explicit"]) for item in apps]
    if (
        len(set(explicit_nonces[:3])) != 1
        or explicit_nonces[3] == explicit_nonces[0]
    ):
        raise RuntimeError(
            "expected nonce reuse in records 1-3 and a fresh nonce in record 4"
        )

    reused = apps[:3]
    print("server application records:")
    for item in apps:
        print(
            f"  seq={item['seq']} nonce_explicit={bytes(item['explicit']).hex()} "
            f"ciphertext_len={len(bytes(item['ciphertext']))}"
        )

    polys = [ghash_polynomial(item) for item in reused]
    tags = [reverse_bits_128(int.from_bytes(bytes(item["tag"]), "big")) for item in reused]
    equation = monic(poly_add(poly_add(polys[0], polys[1]), [tags[0] ^ tags[1]]))

    linear_product = poly_gcd(
        equation,
        poly_add(poly_powmod([0, 1], 1 << 128, equation), [0, 1]),
    )
    roots = split_linear_factors(linear_product)
    valid = sorted(
        {
            root
            for root in roots
            if all(
                (poly_eval(polys[i], root) ^ tags[i])
                == (poly_eval(polys[j], root) ^ tags[j])
                for i in range(3)
                for j in range(i + 1, 3)
            )
        }
    )
    if len(valid) != 1:
        raise RuntimeError(f"expected one GHASH key, got {len(valid)}")

    h = reverse_bits_128(valid[0])
    if h != EXPECTED_H:
        raise RuntimeError(f"unexpected GHASH key {h:032x}")
    authentication_masks = [
        int.from_bytes(bytes(item["tag"]), "big")
        ^ ghash(h, ghash_blocks(item))
        for item in reused
    ]
    if len(set(authentication_masks)) != 1:
        raise RuntimeError("reused-nonce records do not share E_K(J0)")
    authentication_mask = authentication_masks[0]
    print(
        "GCM bit ordering check: "
        "0x8000...00 (NIST representation) maps to polynomial 1"
    )
    print(f"GHASH equation degree = {len(equation) - 1}")
    print(
        f"field roots from records 1-2 = {len(roots)}; "
        f"survivors after record 3 = {len(valid)}"
    )
    print(f"GHASH H = {h:032x}")
    print(f"E_K(J0) = {authentication_mask:032x}")

    target = reused[2]
    # The original plaintext is supplied verbatim in the problem statement; it
    # is known plaintext, not something recovered by decrypting the pcap.
    original = b"action=set_salary&uid=0007&amt=0100&month=202603"
    wanted = b"action=set_salary&uid=0007&amt=0500&month=202603"
    ciphertext = bytes(target["ciphertext"])
    if len(original) != len(ciphertext):
        raise RuntimeError("known plaintext length does not match target ciphertext")

    changed_offsets = [
        i for i, (old, new) in enumerate(zip(original, wanted)) if old != new
    ]
    if changed_offsets != [32]:
        raise RuntimeError(f"unexpected plaintext change offsets: {changed_offsets}")
    keystream = bytes(c ^ p for c, p in zip(ciphertext, original))
    forged_ciphertext = bytes(
        c ^ p ^ q for c, p, q in zip(ciphertext, original, wanted)
    )
    if bytes(c ^ k for c, k in zip(forged_ciphertext, keystream)) != wanted:
        raise RuntimeError(
            "forged ciphertext does not decrypt to the target under the recovered "
            "keystream"
        )
    modified = dict(target)
    modified["ciphertext"] = forged_ciphertext
    old_tag = int.from_bytes(bytes(target["tag"]), "big")
    old_ghash = ghash(h, ghash_blocks(target))
    new_ghash = ghash(h, ghash_blocks(modified))
    new_tag = (old_tag ^ old_ghash ^ new_ghash).to_bytes(16, "big")
    if int.from_bytes(new_tag, "big") ^ new_ghash != authentication_mask:
        raise RuntimeError("forged tag does not reproduce E_K(J0)")

    forged_record = (
        bytes([0x17])
        + bytes(target["version"])
        + (8 + len(forged_ciphertext) + 16).to_bytes(2, "big")
        + bytes(target["explicit"])
        + forged_ciphertext
        + new_tag
    )
    if len(forged_record) != 77 or int.from_bytes(forged_record[3:5], "big") != 72:
        raise RuntimeError("forged TLS record has an invalid encoded length")
    if forged_record.hex() != EXPECTED_RECORD_HEX:
        raise RuntimeError("forged TLS record differs from the audited expected value")
    submission = (root / "forged_record.txt").read_text(
        encoding="ascii"
    ).strip()
    if submission != forged_record.hex():
        raise RuntimeError("forged_record.txt is out of sync")
    target_aad = (
        int(target["seq"]).to_bytes(8, "big")
        + bytes([int(target["type"])])
        + bytes(target["version"])
        + len(ciphertext).to_bytes(2, "big")
    )
    print(f"target AAD = {target_aad.hex()}")
    print("known plaintext source = problem statement (not decrypted from pcap)")
    print(f"plaintext change offsets = {changed_offsets} (0-based)")
    print(f"original ciphertext = {ciphertext.hex()}")
    print(f"original tag = {old_tag:032x}")
    print(f"GHASH original = {old_ghash:032x}")
    print(f"forged ciphertext = {forged_ciphertext.hex()}")
    print(f"GHASH forged = {new_ghash:032x}")
    print(f"forged tag = {new_tag.hex()}")
    print(f"forged TLS record = {forged_record.hex()}")
    print(
        "verification = pcap, nonce reuse, H, E_K(J0), plaintext delta, tag, "
        "length, and submission checks passed"
    )


if __name__ == "__main__":
    main()
