"""A stalled disk write must not block the next memory checkpoint."""

from contextlib import contextmanager
import struct

import checkpoint_memory as core


class FakeGame:
    def __init__(self):
        self.words = {
            core.SAVE_QUEUE_COUNT: 2,
            core.ASYNC_DISK_SAVE: core.SAVE_A,
            core.ASYNC_CALLBACK_SAVE: core.SAVE_A,
            core.SAVE_A + core.STATE_OFFSET: 0,
            core.LEVEL_FRAME_ADDR: 100,
        }
        for index, save_id in enumerate((4, 5)):
            address = core.SAVE_QUEUE + index * core.SAVE_REQUEST_SIZE
            self.words[address + 0x180] = save_id
            self.words[address + 0x184] = 1
            self.words[address + 0x188] = 6
        self.callback_now = 0
        self.suspended_count = 0

    def u32(self, address):
        return self.words[address]

    def read(self, address, size):
        if address == core.SAVE_A + core.CALLBACK_NOW_OFFSET:
            assert size == 1
            return bytes([self.callback_now])
        if address in (core.SAVE_QUEUE, core.SAVE_QUEUE + core.SAVE_REQUEST_SIZE):
            assert size == 64
            return b"1\0" + bytes(62)
        raise AssertionError((address, size))

    def write(self, address, data):
        self.words[address] = struct.unpack("<I", data)[0]

    @contextmanager
    def suspended(self):
        self.suspended_count += 1
        yield


game = FakeGame()
unblocker = core.SaveQueueUnblocker()
assert not unblocker.observe(game, 0)
assert not unblocker.observe(game, 2)
game.words[core.LEVEL_FRAME_ADDR] = 130
assert unblocker.observe(game, 3)
assert game.words[core.ASYNC_DISK_SAVE] == 0
assert game.words[core.ASYNC_CALLBACK_SAVE] == 0
assert game.words[core.SAVE_QUEUE + 0x188] == 2
assert game.words[core.SAVE_QUEUE + core.SAVE_REQUEST_SIZE + 0x188] == 2
assert game.suspended_count == 1

game = FakeGame()
game.callback_now = 1
assert not core.SaveQueueUnblocker().observe(game, 0)
assert not core.SaveQueueUnblocker().observe(game, 5)
assert game.suspended_count == 0

game = FakeGame()
unblocker = core.SaveQueueUnblocker()
assert not unblocker.observe(game, 0)
assert not unblocker.observe(game, 30)  # paused game frames cannot prove a stale disk write
assert game.suspended_count == 0

print("Stalled disk save recovery passed")

# First manual devsave leaves the async pointer on the COMMITTED buffer,
# not necessarily a FREE buffer. The old guard never recovered this case.
game = FakeGame()
game.words[core.SAVE_A + core.STATE_OFFSET] = 3
unblocker = core.SaveQueueUnblocker()
assert not unblocker.observe(game, 0)
game.words[core.LEVEL_FRAME_ADDR] = 300
assert not unblocker.observe(game, 3)
assert unblocker.observe(game, 8)
assert game.words[core.ASYNC_DISK_SAVE] == 0
assert game.words[core.SAVE_QUEUE + 0x188] == 2
for state in (1, 2, 4):
    game = FakeGame()
    game.words[core.SAVE_A + core.STATE_OFFSET] = state
    unblocker = core.SaveQueueUnblocker()
    assert not unblocker.observe(game, 0)
    game.words[core.LEVEL_FRAME_ADDR] = 300
    assert not unblocker.observe(game, 30)
    assert game.suspended_count == 0
print("Committed-buffer disk stalls recover without touching active reads/writes")
