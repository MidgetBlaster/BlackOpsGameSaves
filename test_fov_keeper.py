"""Check FoV pointer handling without opening or modifying Black Ops."""

import struct
from unittest.mock import patch

import checkpoint_memory as core

from fov_keeper import (FOV_POINTER, SCALE_POINTER, VALUE_OFFSET,
                        apply_fov, validate_settings)


class FakeGame:
    def __init__(self):
        self.pointers = {FOV_POINTER: 0x10000000, SCALE_POINTER: 0x10001000}
        self.values = {0x10000000 + VALUE_OFFSET: 65.0,
                       0x10001000 + VALUE_OFFSET: 1.0}
        self.writes = []

    def u32(self, address):
        return self.pointers[address]

    def read(self, address, size):
        assert size == 4
        return struct.pack("<f", self.values[address])

    def write(self, address, data):
        value = struct.unpack("<f", data)[0]
        self.values[address] = value
        self.writes.append((address, value))


def test_apply():
    game = FakeGame()
    game.layout_confirmed = False
    with patch.object(core, "probe_live_save_layout", side_effect=[False, True]):
        assert not apply_fov(game, 90, 1.25)
        assert not game.writes
        assert apply_fov(game, 90, 1.25)
    assert game.layout_confirmed
    assert len(game.writes) == 2
    assert apply_fov(game, 90, 1.25)
    assert len(game.writes) == 2
    game.values[0x10000000 + VALUE_OFFSET] = 65.0
    assert apply_fov(game, 90, 1.25)
    assert len(game.writes) == 3  # reset after a map change
    game.pointers[FOV_POINTER] = 0
    assert not apply_fov(game, 90, 1.25)
    assert len(game.writes) == 3
    try:
        validate_settings(999, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid FoV was accepted")


if __name__ == "__main__":
    test_apply()
    print("FoV validation and reapplication passed")
