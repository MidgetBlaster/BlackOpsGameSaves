"""Synthetic code signatures exercise independent addresses and rejection paths."""

import copy
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
from unittest.mock import patch

import checkpoint_memory as core
import memory_resolver as resolver


def fixture(save_shift=0):
    symbols = dict(core._TESTED_ADDRESSES)
    for index, pair in enumerate(core._TESTED_BUFFERS.values()):
        for part, address in enumerate(pair):
            symbols[f"BUFFER_{index}_{part}"] = address
    moved = {"COMMITTED_PTR", "WRITE_PTR", "SAVE_A", "SAVE_B"}
    moved.update(name for name in symbols if name.startswith("BUFFER_"))
    addresses = {name: address + (save_shift if name in moved else 0)
                 for name, address in symbols.items()}
    spec = {"format": 1, "anchors": {}, "symbols": {}}
    code = bytearray()
    for index, (name, address) in enumerate(symbols.items()):
        suffix = f"BOGS-FIXTURE-{index:02d}-REFERENCE".encode("ascii")
        pattern = b"\xa1" + struct.pack("<I", address) + suffix
        mask = b"\xff" + b"\0" * 4 + b"\xff" * len(suffix)
        spec["anchors"][name] = [{"bytes": pattern.hex(), "mask": mask.hex(), "operand": 1}]
        spec["symbols"][name] = [{"anchor": name, "offset": 0}]
        code.extend(b"\xa1" + struct.pack("<I", addresses[name]) + suffix)
    image = bytearray(0x400) + code
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 60, 0x80)
    image[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", image, 0x84, 0x14C, 2)
    struct.pack_into("<H", image, 0x94, 0xE0)
    struct.pack_into("<H", image, 0x98, 0x10B)
    struct.pack_into("<I", image, 0x98 + 28, core.BASE)
    table = 0x98 + 0xE0
    image[table:table + 8] = b".text\0\0\0"
    struct.pack_into("<IIII", image, table + 8, len(code), 0x1000, len(code), 0x400)
    image[table + 40:table + 48] = b".data\0\0\0"
    struct.pack_into("<IIII", image, table + 48, 0x3AF36C4, 0x76C000, 0, len(image))
    return image, spec, addresses


def main():
    image, spec, addresses = fixture(0x1800000)
    assert resolver.resolve(image, spec) == addresses
    assert addresses["SAVE_A"] != core._TESTED_ADDRESSES["SAVE_A"]
    assert addresses["ROUND_BYTE_ADDR"] == core._TESTED_ADDRESSES["ROUND_BYTE_ADDR"]
    # Bracketing anchors must infer the same position, not just readable memory.
    bracketed = copy.deepcopy(spec)
    bracketed["symbols"]["COMMITTED_PTR"] = [
        {"anchor": "COMMITTED_PTR", "offset": 0}, {"anchor": "WRITE_PTR", "offset": -4}]
    assert resolver.resolve(image, bracketed) == addresses
    bracketed["symbols"]["COMMITTED_PTR"][1]["offset"] = 0
    try:
        resolver.resolve(image, bracketed)
    except ValueError as error:
        assert "Data layout changed" in str(error)
    else:
        raise AssertionError("Conflicting anchors were accepted")
    duplicate = bytes(image[0x400:0x400 + len(bytes.fromhex(spec["anchors"]["COMMITTED_PTR"][0]["bytes"]))])
    ambiguous = bytearray(image) + duplicate
    table = 0x98 + 0xE0
    struct.pack_into("<I", ambiguous, table + 16, len(ambiguous) - 0x400)
    try:
        resolver.resolve(ambiguous, spec)
    except ValueError as error:
        assert "Ambiguous" in str(error)
    else:
        raise AssertionError("Duplicate signatures were accepted")
    damaged = bytearray(image)
    damaged[0x405] ^= 1
    try:
        resolver.resolve(damaged, spec)
    except ValueError as error:
        assert "Missing" in str(error)
    else:
        raise AssertionError("Missing signatures were accepted")
    with TemporaryDirectory() as directory:
        executable = Path(directory) / "BlackOps.exe"
        signatures = Path(directory) / "signatures.json"
        executable.write_bytes(image)
        signatures.write_text(json.dumps(spec), encoding="utf-8")
        with patch.object(resolver, "SIGNATURES", signatures):
            profile = core.memory_profile(executable)
        assert profile["status"] == "candidate", profile
        assert profile["data_delta"] == 0
        assert profile["addresses"]["SAVE_A"] == addresses["SAVE_A"]
        core.validate_profile_layout(profile)
    known = core.GAME / "BlackOps.exe"
    if known.is_file() and core.hashlib.sha256(known.read_bytes()).hexdigest() == core.SUPPORTED_SHA256:
        original = known.read_bytes()
        resolved = resolver.resolve(original)
        assert all(resolved[name] == value for name, value in core._TESTED_ADDRESSES.items())
        _, sections = resolver.pe_sections(original)
        text = sections[".text"]
        code = text["bytes"]
        moved = {"COMMITTED_PTR", "WRITE_PTR", "SAVE_A", "SAVE_B"}
        moved.update(name for name in resolved if name.startswith("BUFFER_"))
        expected = dict(resolved)
        for name in moved:
            expected[name] += 0x1800000
            code = code.replace(struct.pack("<I", resolved[name]), struct.pack("<I", expected[name]))
        modified = bytearray(original)
        modified[text["raw"]:text["raw"] + len(code)] = code
        assert resolver.resolve(modified) == expected
    print("Independent address resolution, ambiguity, and missing signatures passed")


if __name__ == "__main__":
    main()
