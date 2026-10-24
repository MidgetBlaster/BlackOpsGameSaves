"""Maintainer tool: extract address signatures from the tested executable.

Requires Capstone only when regenerating; installers do not disassemble or
bundle the reference executable. Regeneration rejects any untested input.
"""

import hashlib
import json
import struct
import bisect

import capstone
import checkpoint_memory as core
from memory_resolver import pe_sections, signature_matches, resolve, SIGNATURES


def main():
    data = (core.GAME / "BlackOps.exe").read_bytes()
    if hashlib.sha256(data).hexdigest() != core.SUPPORTED_SHA256:
        raise RuntimeError("Signature generation requires the tested BlackOps.exe")
    base, sections = pe_sections(data)
    text = sections[".text"]
    code = text["bytes"]
    low = sections[".data"]["address"]
    high = low + sections[".data"]["size"]
    image_end = max(s["address"] + s["size"] for s in sections.values())
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    decoder.detail = True
    decoder.skipdata = True
    mask = bytearray(b"\xff" * len(code))
    references = {}
    memory_references = set()
    for instruction in decoder.disasm(code, text["address"]):
        if not instruction.id:
            continue
        offset = instruction.address - text["address"]
        for local, length in ((instruction.imm_offset, instruction.imm_size),
                              (instruction.disp_offset, instruction.disp_size)):
            if not length:
                continue
            value = int.from_bytes(instruction.bytes[local:local + length], "little")
            absolute = length == 4 and base <= value < image_end
            branch = local == instruction.imm_offset and (
                instruction.group(capstone.CS_GRP_JUMP) or instruction.group(capstone.CS_GRP_CALL))
            if absolute or branch:
                mask[offset + local:offset + local + length] = b"\0" * length
            if absolute and low <= value < high:
                references.setdefault(value, []).append(offset + local)
                if local == instruction.disp_offset and instruction.disp_size == 4:
                    memory_references.add(value)
    symbols = dict(core._TESTED_ADDRESSES)
    for index, pair in enumerate(core._TESTED_BUFFERS.values()):
        for part, value in enumerate(pair):
            symbols[f"BUFFER_{index}_{part}"] = value
    sorted_refs = sorted(memory_references)
    result = {"format": 1, "reference_sha256": core.SUPPORTED_SHA256,
              "anchors": {}, "symbols": {}}
    for name, address in symbols.items():
        if address in references:
            anchors = [address]
        else:
            index = bisect.bisect_left(sorted_refs, address)
            if not 0 < index < len(sorted_refs):
                raise RuntimeError(f"No bracketing references for {name}")
            anchors = sorted_refs[index - 1:index + 1]
        result["symbols"][name] = []
        for anchor in anchors:
            key = f"data_{anchor:08x}"
            result["symbols"][name].append({"anchor": key, "offset": address - anchor})
            if key in result["anchors"]:
                continue
            patterns = []
            for reference in references[anchor]:
                for radius in (32, 64, 112):
                    start, end = max(0, reference - radius), min(len(code), reference + radius + 4)
                    signature = {"bytes": code[start:end].hex(), "mask": mask[start:end].hex(),
                                 "operand": reference - start}
                    try:
                        if signature_matches(code, signature) == [start]:
                            patterns.append(signature)
                            break
                    except ValueError:
                        continue
                if len(patterns) == 3:
                    break
            if not patterns:
                raise RuntimeError(f"No unique signature for {key}")
            result["anchors"][key] = patterns
    assert resolve(data, result) == symbols
    SIGNATURES.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"Verified {len(symbols)} addresses using {len(result['anchors'])} code anchors")


if __name__ == "__main__":
    main()
