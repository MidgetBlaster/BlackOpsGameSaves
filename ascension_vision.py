"""Preserve Ascension's local film values without modifying its saved script VM."""
import base64
import math
import struct

UPDATE = 0x4B72D0
FROM, TO, CURRENT, NAME = 0xC7668, 0xC90A8, 0xCAAE8, 0xCC5A0
FILM_SIZE = 0x78


def locate(game, *, map_name="zombie_cosmodrome"):
    # Validate the retail instruction layout and obtain its actual CG pointer.
    # Unsupported code gets no guessed renderer writes.
    code = game.read(UPDATE, 0x88)
    if (code[:3] != bytes.fromhex("53 8b 1d") or
        code[7:14] != bytes.fromhex("80 bb a0 c5 0c 00 00") or
        code[0x4b:0x51] != bytes.fromhex("8d b3 a8 90 0c 00") or
        code[0x81:0x87] != bytes.fromhex("81 c6 a0 02 00 00")):
        raise RuntimeError("Ascension vision layout is not verified for this client")
    pointer = struct.unpack_from("<I", code, 3)[0]
    cg = game.u32(pointer)
    if not 0x10000 <= cg < 0x7FE00000:
        raise RuntimeError("Ascension client view is not initialized")
    name = game.read(cg + NAME, 64).split(b"\0", 1)[0].decode("ascii")
    allowed = ("default", "zombie_coast_powerOn") if map_name == "zombie_moon" else ("default",)
    if name not in allowed and not name.startswith(map_name):
        raise RuntimeError(f"{map_name} vision is not active")
    return cg, name


def validate(data):
    if len(data) != FILM_SIZE or data[0] not in (0, 1):
        raise ValueError("Invalid saved Ascension film values")
    if not all(math.isfinite(v) and abs(v) < 100000 for v in struct.unpack("<29f", data[4:])):
        raise ValueError("Invalid saved Ascension film values")
    return data


def capture(game):
    cg, name = locate(game)
    data = validate(game.read(cg + CURRENT, FILM_SIZE))
    return {"format": 1, "map": "zombie_cosmodrome", "name": name, "film": base64.b64encode(data).decode("ascii")}


def restore(game, state):
    if state.get("format") != 1 or state.get("map") != "zombie_cosmodrome":
        raise ValueError("Invalid Ascension vision state")
    data = validate(base64.b64decode(state["film"], validate=True))
    with game.suspended():
        cg, _ = locate(game)
        # Equal endpoints prevent the old intro blend from restoring grayscale.
        # Other vision channels and non-film effects retain their engine state.
        for offset in (FROM, TO, CURRENT):
            game.write(cg + offset, data)
