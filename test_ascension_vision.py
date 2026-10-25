from contextlib import nullcontext
import base64
import struct
import ascension_vision as v

class Game:
    def __init__(self):
        self.cg = 0x10000000
        self.code = bytearray(0x88)
        self.code[:3] = bytes.fromhex("53 8b 1d")
        struct.pack_into("<I", self.code, 3, 0x2ff5354)
        self.code[7:14] = bytes.fromhex("80 bb a0 c5 0c 00 00")
        self.code[0x4b:0x51] = bytes.fromhex("8d b3 a8 90 0c 00")
        self.code[0x81:0x87] = bytes.fromhex("81 c6 a0 02 00 00")
        self.film = bytes([1,0,0,0]) + struct.pack("<29f", *([1.] * 29))
        self.writes = []
    def read(self, address, size):
        if address == v.UPDATE: return bytes(self.code)
        if address == self.cg + v.NAME: return b"default" + bytes(57)
        if address == self.cg + v.CURRENT: return self.film
        raise AssertionError(address)
    def u32(self, address):
        assert address == 0x2ff5354
        return self.cg
    def suspended(self): return nullcontext()
    def write(self, address, data): self.writes.append((address,data))

g = Game()
saved = v.capture(g)
g.film = bytes(120)
v.restore(g,saved)
assert [a for a,_ in g.writes] == [g.cg+o for o in (v.FROM,v.TO,v.CURRENT)]
assert all(b == base64.b64decode(saved['film']) for _,b in g.writes)
for bad in (dict(saved, map='zombie_moon'), dict(saved, film='AAAA'),
            dict(saved, film=base64.b64encode(bytes(4)+struct.pack('<29f',*([float('nan')]*29))).decode())):
    g.writes.clear()
    try: v.restore(g,bad)
    except ValueError: pass
    else: raise AssertionError('Invalid state accepted')
    assert not g.writes
g.code[0] = 0
g.writes.clear()
try: v.restore(g,saved)
except RuntimeError: pass
else: raise AssertionError('Unknown renderer accepted')
assert not g.writes
print('Ascension film capture/restore and incompatible-layout rejection passed')
