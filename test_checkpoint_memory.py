import tempfile
import base64
import hashlib
from contextlib import contextmanager
from pathlib import Path
import struct
from unittest.mock import patch
import checkpoint_memory as c


def test_executable_compatibility():
    sections = (*c.LAYOUT_SECTIONS, b".rsrc")
    image = bytearray(0x600)
    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, 0x80)
    image[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HH", image, 0x84, 0x14C, len(sections))
    struct.pack_into("<H", image, 0x94, 0xE0)
    struct.pack_into("<H", image, 0x98, 0x10B)
    struct.pack_into("<I", image, 0x98 + 16, 0x1200)
    struct.pack_into("<II", image, 0x98 + 28, 0x400000, 0x1000)
    table = 0x98 + 0xE0
    for index, name in enumerate(sections):
        offset = table + index * 40
        image[offset:offset + 8] = name.ljust(8, b"\0")
        struct.pack_into("<IIII", image, offset + 8, 32, 0x1000 * (index + 1),
                         32, 0x400 + index * 32)
        struct.pack_into("<I", image, offset + 36, 0x60000020)
        image[0x400 + index * 32:0x420 + index * 32] = bytes([index + 1]) * 32
    original = bytes(image)
    layout = c.executable_layout_fingerprint(original)
    assert layout and c.executable_layout_fingerprint(b"not a PE file") is None
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
        executable = Path(directory) / "BlackOps.exe"
        with (patch.object(c, "SUPPORTED_SHA256", hashlib.sha256(original).hexdigest()),
              patch.object(c, "SUPPORTED_LAYOUT_SHA256", layout)):
            executable.write_bytes(original)
            assert c.verify_game_executable(executable) == hashlib.sha256(original).hexdigest()
            image[0x400 + 5 * 32] ^= 1  # Changed resources do not move code or data.
            executable.write_bytes(image)
            assert c.verify_game_executable(executable) == hashlib.sha256(image).hexdigest()
            image[0x400] ^= 1  # Changed game code must be rejected.
            executable.write_bytes(image)
            try:
                c.verify_game_executable(executable)
            except RuntimeError as error:
                assert hashlib.sha256(image).hexdigest() in str(error)
            else:
                raise AssertionError("Changed game code was accepted")
    known = c.GAME / "BlackOps.exe"
    if known.is_file() and hashlib.sha256(known.read_bytes()).hexdigest() == c.SUPPORTED_SHA256:
        assert c.executable_layout_fingerprint(known.read_bytes()) == c.SUPPORTED_LAYOUT_SHA256


test_executable_compatibility()

class FakeGame:
    def __init__(self):
        self.suspend_calls = 0
        self.regions = {address: bytearray(size) for address, size in [
            (c.SAVE_A, c.SAVE_SIZE), (c.SAVE_B, c.SAVE_SIZE),
            (c.BUFFERS[c.SAVE_A][0], c.BUFFER_SIZES[0]),
            (c.BUFFERS[c.SAVE_A][1], c.BUFFER_SIZES[1]),
            (c.BUFFERS[c.SAVE_B][0], c.BUFFER_SIZES[0]),
            (c.BUFFERS[c.SAVE_B][1], c.BUFFER_SIZES[1]),
            (c.COMMITTED_PTR, 8), (c.COMMITTED_FLAG, 4),
            (c.PAUSED_ADDR, 4), (c.LEVEL_FRAME_ADDR, 4), (c.LEVEL_TIME_ADDR, 4),
            (c.TIMER_ADDR, 4), (c.ROUND_BYTE_ADDR, 1)]}
        self.write(c.COMMITTED_PTR, struct.pack('<I', c.SAVE_A))
        self.write(c.WRITE_PTR, struct.pack('<I', c.SAVE_B))
        self.write(c.PAUSED_ADDR, struct.pack('<I', 0))
        self.write(c.LEVEL_FRAME_ADDR, struct.pack('<I', 120))
        self.write(c.LEVEL_TIME_ADDR, struct.pack('<I', 6000))
        self.write(c.TIMER_ADDR, struct.pack('<I', 250))
        self.write(c.ROUND_BYTE_ADDR, b'\x04')
        image = self.regions[c.SAVE_A]
        struct.pack_into('<I', image, 0, c.BUFFERS[c.SAVE_A][0])
        struct.pack_into('<I', image, c.MEMFILE_SIZE, c.BUFFERS[c.SAVE_A][1])
        struct.pack_into('<I', image, c.STATE_OFFSET, 3)
        h = c.HEADER_OFFSET
        struct.pack_into('<II', image, h, 0x134, 123456)
        struct.pack_into('<I', image, h + 0xc, 1)
        struct.pack_into('<III', image, h + 0x14, 1, 2, 3)
        image[h+0x20:h+0x20+len(b'nazi_zombie_kino')] = b'nazi_zombie_kino'
        image[h+0x3e0:h+0x3e0+len(b'save\\kino-1.svg')] = b'save\\kino-1.svg'
        struct.pack_into('<I', image, h+0x490, 1000)
        self.regions[c.BUFFERS[c.SAVE_A][0]][0:4] = b'SAVE'
    def read(self, address, size):
        for base, data in self.regions.items():
            if base <= address and address+size <= base+len(data):
                return bytes(data[address-base:address-base+size])
        raise RuntimeError(f'unmapped {address:x}')
    def write(self, address, data):
        for base, region in self.regions.items():
            if base <= address and address+len(data) <= base+len(region):
                region[address-base:address-base+len(data)] = data
                return
        raise RuntimeError(f'unmapped write {address:x}')
    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]
    @contextmanager
    def suspended(self):
        self.suspend_calls += 1
        yield

game = FakeGame()
assert c.live_round(game) == 4
game.write(c.ROUND_BYTE_ADDR, b'\x05')
assert c.live_round(game) == 5
game.write(c.ROUND_BYTE_ADDR, b'\x04')
assert c.effective_scene(game, 0xFFFFFFFF) == (None, 'nazi_zombie_kino')
game.write(c.SAVE_A + c.HEADER_OFFSET + 0x20, b'zombie_cod5_factory\0')
assert c.effective_scene(game, 0xFFFFFFFF) == (204, 'zombie_cod5_factory')
assert c.effective_scene(game, 204) == (204, None)
game.write(c.SAVE_A + c.HEADER_OFFSET + 0x20, b'nazi_zombie_kino\0')
zero_checksum_game = FakeGame()
zero_checksum_game.write(c.SAVE_A + c.HEADER_OFFSET + 4, struct.pack('<I', 0))
assert c.validate_image(c.SAVE_A, zero_checksum_game.read(c.SAVE_A, c.SAVE_SIZE))['map_checksum'] == 0
with tempfile.TemporaryDirectory(dir=c.ROOT) as directory:
    c.ARCHIVE = Path(directory)
    c.RECOVERY_FILE = c.ARCHIVE / 'recovery' / 'latest.bo1checkpoint'
    path = c.snapshot(game, 7)
    metadata, data = c.load_archive(path)
    assert metadata['round'] == 7
    assert data['state.bin'][:4] == b'SAVE'
    game.write(c.BUFFERS[c.SAVE_A][0], b'NEW!')
    game.write(c.SAVE_A + c.HEADER_OFFSET + 0xc, struct.pack('<I', 2))
    c.restore(game, path)
    assert game.u32(c.COMMITTED_PTR) == c.SAVE_B
    assert game.read(c.BUFFERS[c.SAVE_B][0], 4) == b'SAVE'
    assert game.u32(c.SAVE_B + c.HEADER_OFFSET + 0xc) == 1
    assert c.latest_archive() == path
    rolling = c.snapshot(game, 7, target=c.RECOVERY_FILE)
    assert rolling == c.RECOVERY_FILE
    recovered = c.promote_recovery()
    assert recovered.exists() and not c.RECOVERY_FILE.exists()
    assert c.load_archive(recovered)[0]['round'] == 7
    c.restore(game, path, coop=True)
    assert game.suspend_calls == 1
    assert game.u32(c.COMMITTED_PTR) == c.SAVE_A
    game.write(c.SAVE_A + c.HEADER_OFFSET + 4, struct.pack('<I', 999))
    before = game.read(c.BUFFERS[c.SAVE_A][0], 4)
    try:
        c.restore(game, path)
    except RuntimeError as error:
        assert 'current map or scripts differ' in str(error)
    else:
        raise AssertionError('Mismatched map was accepted')
    assert game.read(c.BUFFERS[c.SAVE_A][0], 4) == before
tracker = c.RoundTracker(start_round=12)
assert tracker.update(5, 0, 200, 2000, 0) is None
assert tracker.update(5, 0, 200, 2000, 6) is None
assert tracker.update(5, 0, 300, 500, 7) is None
assert tracker.update(5, 0, 300, 500, 13) == 13
with patch.object(c, 'committed', return_value=(c.SAVE_B, b'', {'save_id': 3})):
    c.wait_for_new_save(game, 3, timeout=1, prior_address=c.SAVE_A)
observed = c.RoundTracker()
assert observed.update(204, 0, 200, 1000, 0, 4) is None
assert observed.update(204, 0, 200, 1000, 6, 4) is None
observed.saved_round = 4
assert observed.update(204, 0, 10, 1000, 7, 4) is None
assert observed.update(204, 0, 200, 1000, 8, 4) is None
assert observed.update(204, 0, 200, 1000, 9, 5) is None
assert observed.update(204, 0, 200, 1000, 15, 5) == 5
command = base64.b64decode(c.elevated_command()).decode('utf-16le')
assert "'--elevated'" in command and "checkpoint.py'" in command
print('Synthetic snapshot, integrity, and restore passed')
