"""Preserve Moon's numeric naked-vision state independently of its P.E.S.

The verified retail renderer strides vision values by 0x2A0. These are
numeric film/bloom parameters, not material pointers or script VM data.
Only restore the naked channel; future zone/teleport scripts remain free
 to change it normally. Do not infer the location from the round number.
"""
import base64
import math
import struct
import ascension_vision as layout

SIZE = 0x2A0


def validate(data):
    if len(data) != SIZE:
        raise ValueError("Invalid Moon vision size")
    layout.validate(data[:layout.FILM_SIZE])
    if not all(math.isfinite(v) and abs(v) < 1e9
               for v in struct.unpack("<138f", data[layout.FILM_SIZE:])):
        raise ValueError("Invalid Moon vision parameters")
    return data


def capture(game):
    cg, name = layout.locate(game, map_name="zombie_moon")
    data = validate(game.read(cg + layout.CURRENT, SIZE))
    return {"format": 1, "map": "zombie_moon", "name": name,
            "values": base64.b64encode(data).decode("ascii")}


def restore(game, state):
    if state.get("format") != 1 or state.get("map") != "zombie_moon":
        raise ValueError("Invalid saved Moon vision state")
    data = validate(base64.b64decode(state["values"], validate=True))
    with game.suspended():
        cg, _ = layout.locate(game, map_name="zombie_moon")
        for offset in (layout.FROM, layout.TO, layout.CURRENT):
            game.write(cg + offset, data)
