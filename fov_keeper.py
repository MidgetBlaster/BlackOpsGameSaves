"""Keep Black Ops singleplayer/Zombies FoV values set across map resets.

Pointer locations for BlackOps.exe are adapted from Marvin Lehmann's
MIT-licensed CoD SCZ FoV Changer (FrmSelection.cs). An unrecognized executable
must pass the live save-layout check before any FoV memory write.
"""

from __future__ import annotations

import math
import struct

import checkpoint_memory as core


FOV_POINTER = core.BASE + 0x02BF6888
SCALE_POINTER = core.BASE + 0x02BF66A8
VALUE_OFFSET = 0x18


def validate_settings(fov: float, scale: float) -> tuple[float, float]:
    fov, scale = float(fov), float(scale)
    if not math.isfinite(fov) or not 1 <= fov <= 360:
        raise ValueError("FoV must be between 1 and 360")
    if not math.isfinite(scale) or not 1 <= scale <= 2:
        raise ValueError("FoV scale must be between 1.00 and 2.00")
    return fov, scale


def _value_address(game: core.GameProcess, pointer_location: int) -> int | None:
    pointer = game.u32(pointer_location)
    if not 0x10000 <= pointer <= 0x7FFF0000:
        return None
    return pointer + VALUE_OFFSET


def apply_fov(game: core.GameProcess, fov: float, scale: float) -> bool:
    """Write only plausible, live FoV dvars in the verified SP process."""
    fov, scale = validate_settings(fov, scale)
    if not getattr(game, "layout_confirmed", True):
        try:
            game.layout_confirmed = core.probe_live_save_layout(game)
        except (OSError, RuntimeError):
            return False
        if not game.layout_confirmed:
            return False
    addresses = (_value_address(game, FOV_POINTER),
                 _value_address(game, SCALE_POINTER))
    if None in addresses:
        return False
    old_fov, old_scale = (struct.unpack("<f", game.read(address, 4))[0]
                          for address in addresses)
    # Map transitions briefly leave stale pointers. Do not write through them.
    if not (math.isfinite(old_fov) and 1 <= old_fov <= 360 and
            math.isfinite(old_scale) and 0.5 <= old_scale <= 2.5):
        return False
    for address, current, desired in zip(addresses, (old_fov, old_scale), (fov, scale)):
        if abs(current - desired) > 0.001:
            game.write(address, struct.pack("<f", desired))
    return True
