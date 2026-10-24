"""Resolve BO1 data addresses from bounded, unique x86 code signatures.

Signatures locate candidates, not proof of a live checkpoint layout. The
companion must still validate the save structures before writing memory.
"""

from pathlib import Path
import json
import re
import struct


SIGNATURES = Path(__file__).with_name("memory_signatures.json")


def pe_sections(data: bytes) -> tuple[int, dict]:
    try:
        if data[:2] != b"MZ":
            raise ValueError("Not a PE executable")
        pe = struct.unpack_from("<I", data, 60)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("Invalid PE signature")
        machine, count = struct.unpack_from("<HH", data, pe + 4)
        optional_size = struct.unpack_from("<H", data, pe + 20)[0]
        optional = pe + 24
        if (machine != 0x14C or not 0 < count <= 96 or optional_size < 96 or
                struct.unpack_from("<H", data, optional)[0] != 0x10B):
            raise ValueError("Expected a 32-bit x86 executable")
        base = struct.unpack_from("<I", data, optional + 28)[0]
        table = optional + optional_size
        if table + count * 40 > len(data):
            raise ValueError("Truncated PE section table")
        sections = {}
        for index in range(count):
            offset = table + index * 40
            name = data[offset:offset + 8].rstrip(b"\0").decode("ascii")
            size, rva, raw_size, raw = struct.unpack_from("<IIII", data, offset + 8)
            flags = struct.unpack_from("<I", data, offset + 36)[0]
            if name in sections or raw + raw_size > len(data):
                raise ValueError("Invalid PE section extent")
            sections[name] = {"address": base + rva, "size": size,
                              "raw": raw, "bytes": data[raw:raw + raw_size], "flags": flags}
        return base, sections
    except (struct.error, UnicodeError, OverflowError) as error:
        raise ValueError("Malformed PE executable") from error


def signature_matches(code: bytes, signature: dict) -> list[int]:
    pattern = bytes.fromhex(signature["bytes"])
    mask = bytes.fromhex(signature["mask"])
    operand = signature["operand"]
    if (len(pattern) != len(mask) or not 16 <= len(pattern) <= 256 or
            sum(bool(value) for value in mask) < 16 or
            not 0 <= operand <= len(pattern) - 4 or any(mask[operand:operand + 4])):
        raise ValueError("Invalid memory signature")
    expression = re.compile(b"".join(re.escape(bytes([value])) if keep else b"."
                                     for value, keep in zip(pattern, mask)), re.DOTALL)
    matches = []
    position = 0
    while match := expression.search(code, position):
        matches.append(match.start())
        if len(matches) > 1:
            break  # Ambiguity is rejected, never resolved by choosing the first.
        position = match.start() + 1
    return matches


def resolve(data: bytes, signatures: dict | None = None) -> dict:
    """Every anchor must have a unique match; two bracketing anchors must agree."""
    signatures = signatures or json.loads(SIGNATURES.read_text(encoding="utf-8"))
    if signatures.get("format") != 1:
        raise ValueError("Unsupported memory signature format")
    _, sections = pe_sections(data)
    code = sections[".text"]["bytes"]
    section = sections[".data"]
    low, high = section["address"], section["address"] + section["size"]
    anchors = {}
    for name, patterns in signatures["anchors"].items():
        values = set()
        for signature in patterns:
            matches = signature_matches(code, signature)
            if len(matches) > 1:
                raise ValueError(f"Ambiguous code signature for {name}")
            if matches:
                value = struct.unpack_from("<I", code, matches[0] + signature["operand"])[0]
                if not low <= value < high:
                    raise ValueError(f"Code signature for {name} points outside game data")
                values.add(value)
        if len(values) != 1:
            raise ValueError(f"Missing or inconsistent code signatures for {name}")
        anchors[name] = values.pop()
    addresses = {}
    for name, references in signatures["symbols"].items():
        candidates = {anchors[item["anchor"]] + item["offset"] for item in references}
        if len(candidates) != 1:
            raise ValueError(f"Data layout changed around {name}")
        address = candidates.pop()
        if not low <= address <= high - 4:
            raise ValueError(f"Resolved {name} is outside game data")
        addresses[name] = address
    return addresses
