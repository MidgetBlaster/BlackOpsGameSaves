"""Read the local Steam persona for Black Ops' launch name."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess
from functools import lru_cache


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


def safe_player_name(name: str | None) -> str | None:
    """Return a value that can safely be passed through a BO1 cfg command."""
    if not name:
        return None
    # Keep the console command a single safe value. BO1's local name is 16 chars.
    name = "".join(char for char in name if char.isprintable() and char not in '";\\')[:16].strip()
    if not name or name.casefold().startswith("unknown soldier"):
        return None
    return name


def _cfg_name(path: Path) -> str | None:
    """Read an explicitly configured Plutonium name when one is present."""
    if not path.is_file():
        return None
    try:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    match = re.search(r'^\s*(?:seta?\s+)?name\s+["\']?([^"\'\r\n]+)',
                      content, re.IGNORECASE | re.MULTILINE)
    return safe_player_name(match.group(1).strip()) if match else None


@lru_cache(maxsize=1)
def plutonium_player_name() -> str | None:
    """Find the client's configured name without reading its auth token."""
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Plutonium"
    for path in (local / "storage/t5/players/config.cfg",
                 local / "storage/t5/players/mods/Game Save/config.cfg"):
        name = _cfg_name(path)
        if name:
            return name
    if os.name == "nt":
        command = ("Get-CimInstance Win32_Process -Filter "
                   "\"Name = 'plutonium-bootstrapper-win32.exe'\" | "
                   "Select-Object -ExpandProperty CommandLine")
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            words = shlex.split(result.stdout, posix=False)
            for index, word in enumerate(words[:-1]):
                key = word.strip('"').casefold()
                if key == "+set" and index + 2 < len(words):
                    if words[index + 1].strip('"').casefold() != "name":
                        continue
                    candidate = words[index + 2]
                elif key == "+name":
                    candidate = words[index + 1]
                else:
                    continue
                name = safe_player_name(candidate.strip('"'))
                if name:
                    return name
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return None


def local_player_name(game: Path, client: str = "steam") -> str | None:
    if client == "plutonium":
        name = plutonium_player_name()
        if name:
            return name
    return safe_player_name(local_persona_name(game))


def launch_name(game: Path) -> str | None:
    return safe_player_name(local_persona_name(game))
