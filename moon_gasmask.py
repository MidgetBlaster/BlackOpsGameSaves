"""Moon's local P.E.S. filter, preserved without changing saved scripts.

Stock gasmask_overlay_handler ignores newEnt on Continue. Resolve materials
by name in the new client's map, never reuse pointers stored by another run.
"""
import struct

MAP = "zombie_moon"
MATERIALS = ("zom_generic_filter_hazmat_moon", "zom_generic_overlay_hazmat_1")
MATERIAL_MAP = 0xCCDFC
FILTER_ENABLED, FILTER_MATERIAL = 0xCCEFC, 0xCCF2C
OVERLAY_ENABLED, OVERLAY_MATERIAL = 0xCDFB8, 0xCDFAC
CHECKS = [(7913045, '88941fb8df0c00'), (7911907, '88942efcce0c00'), (7912515, '8b8caffccd0c00'), (7912547, '898c9facdf0c0089849f7ce00c00'), (7911705, '89bc8eacd00c00'), (7911713, '89ac8eeccf0c0089948e2ccf0c0089848e6cd10c00'), (7912746, 'f30f1184b5bcdf0c00')]


def locate(game):
    for address, expected in CHECKS:
        if game.read(address, len(bytes.fromhex(expected))) != bytes.fromhex(expected):
            raise RuntimeError("Moon overlay layout is not verified for this client")
    code = game.read(0x78BDFD, 6)
    if code[:2] != b"\x8b\x1d":
        raise RuntimeError("Moon client pointer is not verified")
    cg = game.u32(struct.unpack_from("<I", code, 2)[0])
    if not 0x10000 <= cg < 0x7FE00000:
        raise RuntimeError("Moon client view is not initialized")
    return cg


def material_name(game, pointer):
    if not pointer:
        return ""
    name = game.u32(pointer)
    if not 0x10000 <= name < 0x7FE00000:
        raise RuntimeError("Invalid Moon material name")
    return game.read(name, 64).split(b"\0", 1)[0].decode("ascii")


def capture(game):
    cg = locate(game)
    enabled = game.read(cg + OVERLAY_ENABLED, 1)
    if enabled not in (b"\0", b"\1"):
        raise ValueError("Invalid Moon overlay state")
    worn = enabled == b"\1"
    if worn and material_name(game, game.u32(cg + OVERLAY_MATERIAL)) != MATERIALS[1]:
        raise RuntimeError("The active overlay is not Moon's gas mask")
    return {"format": 1, "map": MAP, "worn": worn}


def restore(game, state):
    if (state.get("format") != 1 or state.get("map") != MAP or
            type(state.get("worn")) is not bool):
        raise ValueError("Invalid saved Moon gas-mask state")
    with game.suspended():
        cg = locate(game)
        if not state["worn"]:
            # Do not disable an unrelated overlay (damage, scope, etc.).
            if material_name(game, game.u32(cg + OVERLAY_MATERIAL)) == MATERIALS[1]:
                game.write(cg + OVERLAY_ENABLED, b"\0")
            if material_name(game, game.u32(cg + FILTER_MATERIAL)) == MATERIALS[0]:
                game.write(cg + FILTER_ENABLED, b"\0")
            return
        found = {}
        for slot in range(64):
            pointer = game.u32(cg + MATERIAL_MAP + slot * 4)
            if pointer:
                name = material_name(game, pointer)
                if name in MATERIALS:
                    found[name] = pointer
        if len(found) != 2:
            raise RuntimeError("Moon gas-mask materials are not initialized yet")
        # Same slot-zero configuration as enable_filter_hazmat in the stock CSC.
        values = {FILTER_MATERIAL: found[MATERIALS[0]], 0xCCFEC: 3,
                  0xCD0AC: 3, 0xCD16C: 0, OVERLAY_MATERIAL: found[MATERIALS[1]],
                  0xCE07C: 1}
        for offset, value in values.items():
            game.write(cg + offset, struct.pack("<I", value))
        for offset in (0xCD22C, 0xCDFBC):
            game.write(cg + offset, struct.pack("<f", 1.0))
        game.write(cg + FILTER_ENABLED, b"\1")
        game.write(cg + OVERLAY_ENABLED, b"\1")
