"""A stalled disk write must not block the next memory checkpoint."""

from contextlib import contextmanager
import struct
from unittest.mock import patch

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
        if address in tuple(core.SAVE_QUEUE + i * core.SAVE_REQUEST_SIZE for i in range(3)):
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

# Repeated F11 requests append to a blocked queue. They must not postpone
# recovery of its oldest request, including when the queue fills completely.
game = FakeGame()
game.words[core.SAVE_A + core.STATE_OFFSET] = 3
game.words[core.SAVE_QUEUE_COUNT] = 1
unblocker = core.SaveQueueUnblocker()
assert not unblocker.observe(game, 0)
game.words[core.SAVE_QUEUE_COUNT] = 2
game.words[core.LEVEL_FRAME_ADDR] = 200
assert not unblocker.observe(game, 7)
game.words[core.SAVE_QUEUE_COUNT] = 3
third = core.SAVE_QUEUE + 2 * core.SAVE_REQUEST_SIZE
game.words[third + 0x180] = 6
game.words[third + 0x184] = 1
game.words[third + 0x188] = 6
game.words[core.LEVEL_FRAME_ADDR] = 300
assert unblocker.observe(game, 8)
assert game.words[core.ASYNC_DISK_SAVE] == 0
assert game.words[core.SAVE_QUEUE + 0x188] == 2
assert game.words[core.SAVE_QUEUE + core.SAVE_REQUEST_SIZE + 0x188] == 2
assert game.words[third + 0x188] == 2

# A genuinely different oldest request must receive a fresh grace period.
game = FakeGame()
unblocker = core.SaveQueueUnblocker()
assert not unblocker.observe(game, 0)
game.words[core.SAVE_QUEUE + 0x180] = 99
game.words[core.LEVEL_FRAME_ADDR] = 200
assert not unblocker.observe(game, 3)
assert not unblocker.observe(game, 5)
game.words[core.LEVEL_FRAME_ADDR] = 300
assert unblocker.observe(game, 6)
print("Repeated manual requests cannot reset a stalled queue's recovery timer")

# Exercise real retry windows and recovery together: four-second waits must
# not repeatedly discard the eight-second committed-buffer stall timer.
game = FakeGame()
game.words[core.SAVE_A + core.STATE_OFFSET] = 3
clock = [0.0]
def advance(seconds):
    clock[0] += seconds
    game.words[core.LEVEL_FRAME_ADDR] += max(1, int(seconds * 20))
def committed(_game):
    save_id = 10 if game.words[core.ASYNC_DISK_SAVE] == 0 else 9
    return core.SAVE_A, b"", {"save_id": save_id}
with (patch.object(core.time, "monotonic", side_effect=lambda: clock[0]),
      patch.object(core.time, "sleep", side_effect=advance),
      patch.object(core, "committed", side_effect=committed)):
    core.request_fresh_checkpoint(game, 9)
assert 8 <= clock[0] < 12
assert game.words[core.ASYNC_DISK_SAVE] == 0
print("Autosave retries preserve recovery of a manual-save disk stall")
