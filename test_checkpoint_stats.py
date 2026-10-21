"""Verify the saved-player layout with two independent client records."""

from pathlib import Path
import struct
from unittest.mock import patch

import checkpoint_stats


def test_two_players():
    names = ("m1911_zm", "thompson_zm")
    weapon_data = struct.pack("<I", len(names) + 1) + b"".join(
        bytes((len(name),)) + name.encode("ascii") for name in names)
    globals_data = bytearray(268)
    globals_data[204] = 0b00000010
    globals_data[220] = 0b00000100
    state = bytearray(0x6000)
    for base, client, name, weapon, points, kills, downs, revives in (
        (0x1000, 0, b"Alice", 1, 2350, 18, 1, 0),
        (0x3000, 1, b"Bob", 2, 4170, 29, 2, 3),
    ):
        state[base + 0x130] = client
        state[base + 0x144] = weapon
        state[base + 0x1AA0:base + 0x1AA0 + len(name) + 1] = name + b"\0"
        state[base + 0x1B38:base + 0x1B38 + len(name) + 1] = name + b"\0"
        struct.pack_into("<ii", state, base + 0x1B88, points, kills)
        struct.pack_into("<ii", state, base + 0x1BA4, downs, revives)
    with patch.object(checkpoint_stats, "_game_segments",
                      return_value=(weapon_data, bytes(globals_data), bytes(state))):
        players = checkpoint_stats.extract_players(Path("synthetic.bo1checkpoint"))
    assert players == [
        {"name": "Alice", "points": 2350, "weapons": "M1911 (equipped)",
         "revives": 0, "downs": 1, "kills": 18},
        {"name": "Bob", "points": 4170, "weapons": "Thompson (equipped)",
         "revives": 3, "downs": 2, "kills": 29},
    ]


if __name__ == "__main__":
    test_two_players()
    print("Two-player checkpoint stat decoding passed")
