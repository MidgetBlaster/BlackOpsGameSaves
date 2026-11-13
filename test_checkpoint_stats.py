"""Verify the saved-player layout with two independent client records."""

from pathlib import Path
import struct
from unittest.mock import patch

import checkpoint_stats


def test_decoder():
    assert checkpoint_stats._decode_block(bytes([22]) + b"HELLO" + bytes([17, 0, 0])) == b"HELLO"
    for invalid in (b"", bytes([22]) + b"HI", bytes([22]) + b"HELLO" + bytes([17, 0, 0, 1])):
        try:
            checkpoint_stats._decode_block(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("Malformed checkpoint block was accepted")


def test_two_players():
    names = ("m1911_zm", "thompson_zm", "ray_gun_zm")
    weapon_data = struct.pack("<I", len(names) + 1) + b"".join(
        bytes((len(name),)) + name.encode("ascii") for name in names)
    globals_data = bytearray(268)
    globals_data[204] = 0b00001110 # includes a discarded Thompson
    globals_data[220] = 0b00000100
    state = bytearray(0x6000)
    for base, client, name, weapon, points, kills, downs, revives in (
        (0x1000, 0, b"Alice", 1, 2350, 18, 1, 0),
        (0x3000, 1, b"Bob", 2, 4170, 29, 2, 3),
    ):
        state[base + 0x130] = client
        state[base + 0x144] = weapon
        struct.pack_into("<I", state, base + 0x1DC, weapon)
        if client == 0:
            struct.pack_into("<I", state, base + 0x1DC + 0x18, 3)
        state[base + 0x1AA0:base + 0x1AA0 + len(name) + 1] = name + b"\0"
        state[base + 0x1B38:base + 0x1B38 + len(name) + 1] = name + b"\0"
        struct.pack_into("<ii", state, base + 0x1B88, points, kills)
        struct.pack_into("<ii", state, base + 0x1BA4, downs, revives)
    with patch.object(checkpoint_stats, "_game_segments",
                      return_value=(weapon_data, bytes(globals_data), bytes(state))):
        players = checkpoint_stats.extract_players(Path("synthetic.bo1checkpoint"))
    assert players == [
        {"name": "Alice", "points": 2350, "weapons": "M1911 (equipped), Ray Gun",
         "client_slot": 0, "equipped_weapon_raw": "m1911_zm",
         "revives": 0, "downs": 1, "kills": 18},
        {"name": "Bob", "points": 4170, "weapons": "Thompson (equipped)",
         "client_slot": 1, "equipped_weapon_raw": "thompson_zm",
         "revives": 3, "downs": 2, "kills": 29},
    ]


def test_short_and_unicode_names():
    """Co-op Steam personas can be short or non-ASCII; the slot prefix validates them."""
    weapon_data = struct.pack("<I", 2) + bytes((8,)) + b"m1911_zm"
    state = bytearray(0x9000)
    # A non-zero byte of the previous field sits right before each name.
    for base, client, name in ((0x1000, 0, "Jo".encode()), (0x4000, 1, "Zoë★".encode())):
        struct.pack_into("<I", state, base - 4, client)
        state[base + 0x130] = client
        state[base + 0x144] = 1
        struct.pack_into("<I", state, base + 0x1DC, 1)
        state[base + 0x1AA0 - 1] = 0x9C
        state[base + 0x1AA0:base + 0x1AA0 + len(name) + 1] = name + b"\0"
        state[base + 0x1B38:base + 0x1B38 + len(name) + 1] = name + b"\0"
        struct.pack_into("<ii", state, base + 0x1B88, 500, 3)
    players = checkpoint_stats.players_from_segments(weapon_data, bytes(268), bytes(state))
    assert [(p["client_slot"], p["name"]) for p in players] == [(0, "Jo"), (1, "Zoë★")], players


if __name__ == "__main__":
    test_decoder()
    test_two_players()
    test_short_and_unicode_names()
    print("Two-player checkpoint stat decoding passed")
