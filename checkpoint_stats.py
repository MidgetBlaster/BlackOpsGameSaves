"""Read player summaries from the retail Zombies memory-save payload.

The save's game-state segments use LZO1X blocks. FFmpeg's installed avutil
decoder supplies LZO without changing the mod or the checkpoint format.
"""

from __future__ import annotations

import ctypes
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import struct
import zipfile


@lru_cache(maxsize=1)
def _lzo_decoder():
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("FFmpeg is needed to read player stats")
    libraries = sorted(Path(executable).parent.glob("avutil-*.dll"))
    if not libraries:
        raise RuntimeError("FFmpeg's LZO decoder is unavailable")
    library = ctypes.CDLL(str(libraries[-1]))
    decoder = library.av_lzo1x_decode
    decoder.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                        ctypes.c_void_p, ctypes.POINTER(ctypes.c_int))
    decoder.restype = ctypes.c_int
    return library, decoder


def _decode_block(data: bytes) -> bytes:
    _, decoder = _lzo_decoder()
    source = ctypes.create_string_buffer(data + b"\0" * 8)
    target = ctypes.create_string_buffer(32760 + 12)
    output_left = ctypes.c_int(32760)
    input_left = ctypes.c_int(len(data))
    status = decoder(target, ctypes.byref(output_left), source,
                     ctypes.byref(input_left))
    if status:
        raise ValueError(f"Invalid compressed save block ({status})")
    return target.raw[:32760 - output_left.value]


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
        mask = globals_data[204 + client * 16:220 + client * 16]
        held = [index for index in range(1, min(128, len(names)))
                if mask[index // 8] & (1 << (index % 8))]
        if active and active not in held:
            continue
        held.sort(key=lambda index: (index != active, index))
        loadout = ", ".join(_weapon_label(names[index]) +
                            (" (equipped)" if index == active else "") for index in held)
        player = {"name": name_bytes.decode("ascii", "replace"),
                  "points": points, "weapons": loadout,
                  "revives": revives, "downs": downs, "kills": kills}
        players[client] = player
    return [players[index] for index in sorted(players)]
