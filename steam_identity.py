"""Read the local Steam persona for Black Ops' launch name."""

from __future__ import annotations

import os
from pathlib import Path
import re


def _steam_roots(game: Path) -> list[Path]:
    roots = [game.parents[2]] if len(game.parents) > 2 else []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            roots.append(Path(winreg.QueryValueEx(key, "SteamPath")[0]))
    except (ImportError, FileNotFoundError, OSError):
        pass
    for folder in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        if folder:
            roots.append(Path(folder) / "Steam")
    return roots


def persona_from_vdf(path: Path) -> str | None:
    if not path.is_file():
        return None
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    users = []
    for match in re.finditer(r'"(\d{17})"\s*\{([^{}]*)\}', content, re.DOTALL):
        fields = dict(re.findall(r'"([^"\\]+)"\s*"((?:\\.|[^"\\])*)"', match.group(2)))
        name = fields.get("PersonaName", "").strip()
        if name:
            users.append((fields.get("MostRecent") == "1", name))
    if not users:
        return None
    return max(users, key=lambda item: item[0])[1]


def local_persona_name(game: Path) -> str | None:
    for root in _steam_roots(game):
        try:
            name = persona_from_vdf(root / "config" / "loginusers.vdf")
        except OSError:
            continue
        if name:
            return name
    return None


def launch_name(game: Path) -> str | None:
    name = local_persona_name(game)
    if not name:
        return None
    # Keep the console command a single safe value. BO1's local name is 16 chars.
    name = "".join(char for char in name if char.isprintable() and char not in '";\\')[:16].strip()
    return name or None
