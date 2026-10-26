"""Read player summaries from the retail Zombies memory-save payload."""

from __future__ import annotations

import json
from pathlib import Path
import re
import struct
import zipfile


def _decode_block(data: bytes) -> bytes:
    """Decode one bounded LZO1X block from a checkpoint without a system DLL."""
    position = 0
    output = bytearray()

    def next_byte():
        nonlocal position
        if position >= len(data):
            raise ValueError("Truncated checkpoint compression block")
        value = data[position]
        position += 1
        return value

    def length(code, mask):
        result = code & mask
        if result == 0:
            while True:
                value = next_byte()
                if value:
                    return result + mask + value
                result += 255
                if result > 32760:
                    raise ValueError("Checkpoint compression length is too large")
        return result

    def literal(count):
        nonlocal position
        if count < 0 or position + count > len(data) or len(output) + count > 32760:
            raise ValueError("Invalid checkpoint literal run")
        output.extend(data[position:position + count])
        position += count

    def repeat(distance, count):
        if distance <= 0 or distance > len(output) or len(output) + count > 32760:
            raise ValueError("Invalid checkpoint back reference")
        for _ in range(count):
            output.append(output[-distance])

    code = next_byte()
    if code > 17:
        literal(code - 17)
        code = next_byte()
        if code < 16:
            raise ValueError("Invalid initial checkpoint match")
    state = 0
    while True:
        if code > 63:
            count = (code >> 5) - 1
            distance = (next_byte() << 3) + ((code >> 2) & 7) + 1
        elif code > 31:
            count = length(code, 31)
            pair = next_byte()
            distance = (next_byte() << 6) + (pair >> 2) + 1
            code = pair
        elif code > 15:
            count = length(code, 7)
            distance = (1 << 14) + ((code & 8) << 11)
            pair = next_byte()
            distance += (next_byte() << 6) + (pair >> 2)
            code = pair
            if distance == 1 << 14:
                if count != 1:
                    raise ValueError("Invalid checkpoint end marker")
                break
        elif state == 0:
            literal(length(code, 15) + 3)
            code = next_byte()
            if code > 15:
                continue
            count = 1
            distance = (1 << 11) + (next_byte() << 2) + (code >> 2) + 1
        else:
            count = 0
            distance = (next_byte() << 2) + (code >> 2) + 1
        repeat(distance, count + 2)
        state = code & 3
        literal(state)
        code = next_byte()
    if position != len(data):
        raise ValueError("Unexpected bytes after checkpoint end marker")
    return bytes(output)


def _game_segments(path: Path) -> tuple[bytes, bytes, bytes]:
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        data = archive.read("state.bin")
    body_size = manifest["body_size"]
    if not isinstance(body_size, int) or not 0 < body_size <= len(data):
        raise ValueError("Invalid checkpoint body size")
    offset = 0
    decoded = []
    for number in range(4):
        if offset + 4 > body_size:
            raise ValueError("Checkpoint segment is missing")
        size = struct.unpack_from("<I", data, offset)[0]
        if size < 4 or offset + size > body_size:
            raise ValueError("Invalid checkpoint segment size")
        position = offset + 4
        end = offset + size
        output = bytearray()
        while position < end:
            if position + 4 > end:
                raise ValueError("Incomplete checkpoint block")
            length = struct.unpack_from("<I", data, position)[0]
            position += 4
            if not 0 < length <= end - position:
                raise ValueError("Invalid checkpoint block size")
            output.extend(_decode_block(data[position:position + length]))
            position += length
        if number:
            decoded.append(bytes(output))
        offset = end
    return decoded[0], decoded[1], decoded[2]


def _weapon_names(data: bytes) -> list[str]:
    if len(data) < 4:
        raise ValueError("Missing weapon table")
    count = struct.unpack_from("<I", data, 0)[0]
    if not 1 <= count <= 128:
        raise ValueError("Invalid weapon count")
    names = [""]
    position = 4
    for _ in range(1, count):
        if position >= len(data):
            raise ValueError("Incomplete weapon table")
        length = data[position]
        position += 1
        if position + length > len(data):
            raise ValueError("Invalid weapon name length")
        names.append(data[position:position + length].decode("ascii", "replace"))
        position += length
    return names


def _weapon_label(name: str) -> str:
    for prefix in ("zombie_",):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name.endswith("_zm"):
        name = name[:-3]
    return " ".join(word[0].upper() + word[1:] for word in name.split("_") if word)


def extract_players(path: Path) -> list[dict]:
    """Return saved players, leaving uncertain data unset rather than guessing."""
    weapon_data, globals_data, state = _game_segments(path)
    names = _weapon_names(weapon_data)
    if len(globals_data) < 268:
        raise ValueError("Missing saved player weapon masks")
    players = {}
    # Two 32-byte player-name copies in each SP gclient image are 152 bytes
    # apart. The first is at +0x1AA0; score and scoreboard fields follow.
    for match in re.finditer(rb"(?<![ -~])[ -~]{3,31}\x00", state):
        name_bytes = match.group()[:-1]
        position = match.start()
        second = position + 152
        if state[second:second + len(name_bytes) + 1] != name_bytes + b"\0":
            continue
        base = position - 0x1AA0
        if base < 4 or base + 0x1D28 > len(state):
            continue
        client = state[base + 0x130]
        if client >= 4:
            continue
        points, kills = struct.unpack_from("<ii", state, base + 0x1B88)
        downs, revives = struct.unpack_from("<ii", state, base + 0x1BA4)
        if not (0 <= points <= 10_000_000 and points % 10 == 0 and
                0 <= kills <= 100_000 and 0 <= downs <= 10_000 and
                0 <= revives <= 10_000):
            continue
        active = state[base + 0x144]
        # Retail SP getweaponrenderoptions (0x7D8189): 15 inventory
        # records at ps+0x1DC, stride 0x18. Global masks retain history.
        inventory = [struct.unpack_from("<I", state, base + 0x1DC + slot * 0x18)[0]
                     for slot in range(15)]
        held = list(dict.fromkeys(index for index in inventory if 0 < index < len(names)))
        if active >= len(names):
            continue
        if active and active not in held:
            held.insert(0, active)
        held.sort(key=lambda index: (index != active, index))
        loadout = ", ".join(_weapon_label(names[index]) +
                            (" (equipped)" if index == active else "") for index in held)
        player = {"name": name_bytes.decode("ascii", "replace"),
                  "points": points, "weapons": loadout,
                  "client_slot": client,
                  "equipped_weapon_raw": names[active] if active else "",
                  "revives": revives, "downs": downs, "kills": kills}
        players[client] = player
    return [players[index] for index in sorted(players)]
