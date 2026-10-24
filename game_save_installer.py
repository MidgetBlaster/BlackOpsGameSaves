"""Install the Game Save mod and its bundled game_mod runtime."""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

import checkpoint_memory as core


MOD_NAME = "Game Save"
GAME_DIRECTORY = "Call of Duty Black Ops"
PACKAGE_FILES = (
    "bin/game_mod.dll",
    "bin/launcher_ldr.exe",
    "BO_Mods.bat",
    "main/iw_42.iwd",
    "zone/Common/frontend_patch.ff",
)
MOD_FILES = (
    "checkpoint.py", "checkpoint_gui.py", "checkpoint_memory.py",
    "checkpoint_stats.py", "save_library.py", "game_launcher.py",
    "fov_keeper.py", "steam_identity.py",
    "memory_resolver.py", "memory_signatures.json",
    "game_save_installer.py", "checkpoint.cfg", "checkpoint_speed.cfg",
    "checkpoint_speed_local.cfg", "checkpoint_power.cfg", "checkpoint_borderless.cfg",
    "checkpoint_fullscreen.cfg", "display_mode.py", "CHECKPOINTS.md",
    "mod.ff", "mod.csv", "missingasset.csv", "Open Game Save.cmd",
    "BlackOpsGameSaves.ico",
)
MOD_FOLDERS = ("maps", "clientscripts", "scriptdata", "ui textures", "ui fonts", "installer")
MAP_THUMBNAILS = (
    "loadscreen_zombie_asylum_mini.png", "loadscreen_zombie_factory_mini.png",
    "loadscreen_zombie_prototype_mini.png", "loadscreen_zombie_sumpf_mini.png",
    "zombietron.png", "zombie_coast.png", "zombie_cosmo.png",
    "zombie_moon.png", "zombie_pentagon.png", "zombie_temple.png",
    "zombie_theater.png",
)
MAP_PREVIEWS = tuple(f"previews/{name}" for name in MAP_THUMBNAILS)
MENU_BACKGROUND = (
    "menu_zombie_lobby_frame_outer_ingame.dds",
    "png/menu_zombie_lobby_frame_outer_ingame.png",
    "png/menu_zombie_lobby_frame_outer_ingame_background.png",
)


def _registry_paths() -> list[Path]:
    try:
        import winreg
    except ImportError:
        return []
    candidates = []
    values = (
        (winreg.HKEY_CURRENT_USER, r"Environment", "TA_TOOLS_PATH"),
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamExe"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    )
    for hive, key_name, value_name in values:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
        except (OSError, FileNotFoundError):
            continue
        if isinstance(value, str) and value.strip():
            path = Path(os.path.expandvars(value.strip().strip('"')))
            candidates.append(path.parent if path.suffix.lower() == ".exe" else path)
    return candidates


def _steam_libraries(steam: Path) -> list[Path]:
    libraries = [steam]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            data = vdf.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return libraries
        for raw in re.findall(r'"path"\s*"([^"]+)"', data, flags=re.IGNORECASE):
            libraries.append(Path(raw.replace("\\\\", "\\")))
        # Steam's older VDF uses numbered keys directly for library paths.
        for raw in re.findall(r'"\d+"\s*"([A-Za-z]:[^"]+)"', data):
            libraries.append(Path(raw.replace("\\\\", "\\")))
    return libraries


def find_game(source: Path = core.ROOT) -> Path | None:
    """Find a Black Ops install; TA_TOOLS_PATH is only a hint if it is BO3."""
    hints = [source.parent.parent]
    hints.extend(Path(os.path.expandvars(value)) for name in ("BLACK_OPS_PATH", "TA_TOOLS_PATH")
                 if (value := os.environ.get(name)))
    hints.extend(_registry_paths())
    hints.extend((source, *source.parents))
    hints.extend(Path(value) for name in ("ProgramFiles(x86)", "ProgramFiles")
                 if (value := os.environ.get(name)))
    seen = set()
    for hint in hints:
        candidates = [hint, hint / GAME_DIRECTORY,
                      hint.parent / GAME_DIRECTORY,
                      hint / "steamapps" / "common" / GAME_DIRECTORY]
        for library in _steam_libraries(hint):
            candidates.append(library / "steamapps" / "common" / GAME_DIRECTORY)
        for candidate in candidates:
            try:
                key = str(candidate.resolve()).casefold()
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            if (candidate / "BlackOps.exe").is_file():
                return candidate.resolve()
    return None


def _atomic_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".game-save-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _copy_if_changed(source: Path, destination: Path) -> bool:
    if source.resolve() == destination.resolve():
        return False
    data = source.read_bytes()
    if destination.is_file() and destination.read_bytes() == data:
        return False
    _atomic_bytes(destination, data)
    return True


def _merge_catalog(source: Path, destination: Path):
    if not source.is_file():
        return
    incoming = json.loads(source.read_text(encoding="utf-8"))
    if not destination.is_file():
        _atomic_bytes(destination, json.dumps(incoming, indent=2,
                                              ensure_ascii=False).encode("utf-8"))
        return
    current = json.loads(destination.read_text(encoding="utf-8"))
    if incoming.get("format") != 1 or current.get("format") != 1:
        raise ValueError("An existing save catalog has an unsupported format")
    profile_ids = {item["id"] for item in current["profiles"]}
    for profile in incoming["profiles"]:
        if profile["id"] not in profile_ids:
            current["profiles"].append(profile)
            profile_ids.add(profile["id"])
    for name, entry in incoming["saves"].items():
        current["saves"].setdefault(name, entry)
    if current.get("active_profile") not in profile_ids:
        current["active_profile"] = incoming.get("active_profile", "imported")
    _atomic_bytes(destination, json.dumps(current, indent=2,
                                          ensure_ascii=False).encode("utf-8"))


def install(source: Path, game: Path, package: Path | None = None,
            progress=None) -> dict:
    """Install without deleting an existing mod or overwriting saved games."""
    source = source.resolve()
    game = game.resolve()
    executable = game / "BlackOps.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"BlackOps.exe was not found in {game}")
    if progress:
        progress("Locating checkpoint addresses in the selected BlackOps.exe", 0)
    profile = core.memory_profile(executable)
    executable_size = profile["size"]
    executable_sha256 = profile["executable_sha256"]
    compatibility = "tested" if profile["status"] == "verified_file" else "unverified"
    package = package or source / "installer" / "game_mod.zip"
    if not package.is_file():
        raise FileNotFoundError(f"The bundled game_mod.zip is missing: {package}")
    required = [source / name for name in MOD_FILES]
    required += [source / name for name in MOD_FOLDERS]
    required += [source / "ui textures" / "png" / name for name in MAP_THUMBNAILS]
    required += [source / "ui textures" / name for name in (*MAP_PREVIEWS, *MENU_BACKGROUND)]
    iwd = source / "Game Save.iwd"
    if not iwd.is_file():
        iwd = source / "devcommands.iwd"
    required.append(iwd)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Required Game Save files are missing: " + ", ".join(missing))
    with zipfile.ZipFile(package) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"game_mod.zip contains a damaged file: {bad}")
        if not set(PACKAGE_FILES).issubset(archive.namelist()):
            raise ValueError("game_mod.zip is missing required loader files")
        runtime = {name: archive.read(name) for name in PACKAGE_FILES}
    folder_files = [(folder, path) for folder in MOD_FOLDERS
                    for path in (source / folder).rglob("*") if path.is_file()]
    saves = source / "checkpoint_saves"
    save_files = [path for path in saves.rglob("*") if path.is_file()
                  and path.name != "catalog.json"] if saves.is_dir() else []
    total_steps = (len(MOD_FILES) + len(folder_files) + 2 + len(save_files) +
                   int((saves / "catalog.json").is_file()) + len(PACKAGE_FILES))
    completed_steps = 0

    def advance(item: str):
        nonlocal completed_steps
        completed_steps += 1
        if progress:
            progress(item, completed_steps / total_steps)

    target = game / "mods" / MOD_NAME
    target.mkdir(parents=True, exist_ok=True)
    updated_mod = 0
    for name in MOD_FILES:
        updated_mod += _copy_if_changed(source / name, target / name)
        advance(f"mods/Game Save/{name}")
    for folder, path in folder_files:
        relative = Path(folder) / path.relative_to(source / folder)
        updated_mod += _copy_if_changed(path, target / relative)
        advance(f"mods/Game Save/{relative.as_posix()}")
    updated_mod += _copy_if_changed(iwd, target / "Game Save.iwd")
    advance("mods/Game Save/Game Save.iwd")
    for name in (f"png/{item}" for item in MAP_THUMBNAILS):
        destination = target / "ui textures" / name
        if not destination.is_file():
            raise RuntimeError(f"Map thumbnail was not installed: {destination}")
    for name in (*MAP_PREVIEWS, *MENU_BACKGROUND):
        destination = target / "ui textures" / name
        if not destination.is_file():
            raise RuntimeError(f"Map artwork was not installed: {destination}")
    target_saves = target / "checkpoint_saves"
    copied_saves = 0
    # Import checkpoints from the previous mod only on the first install.
    # Reinstalling must not resurrect saves deleted from the active catalog.
    first_save_install = not (target_saves / "catalog.json").is_file()
    if first_save_install and saves.is_dir() and saves.resolve() != target_saves.resolve():
        for path in save_files:
            destination = target_saves / path.relative_to(saves)
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                copied_saves += 1
            advance(f"mods/Game Save/checkpoint_saves/{path.relative_to(saves).as_posix()}")
        _merge_catalog(saves / "catalog.json", target_saves / "catalog.json")
        if (saves / "catalog.json").is_file():
            advance("mods/Game Save/checkpoint_saves/catalog.json")
    else:
        for path in save_files:
            advance(f"Keeping checkpoint: {path.name}")
        if (saves / "catalog.json").is_file():
            advance("Keeping checkpoint catalog")
    backup_root = target_saves / "install_backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    installed_runtime = []
    backed_up = []
    for name, data in runtime.items():
        destination = game / Path(name)
        if destination.is_file():
            previous = destination.read_bytes()
            if previous == data:
                advance(name)
                continue
            backup = backup_root / name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup)
            backed_up.append(name)
        _atomic_bytes(destination, data)
        installed_runtime.append(name)
        advance(name)
    core.save_memory_profile(profile, target / "memory_profile.json")
    advance("mods/Game Save/memory_profile.json")
    return {"target": target, "compatibility": compatibility,
            "profile_status": profile["status"],
            "profile_data_delta": profile["data_delta"],
            "executable_sha256": executable_sha256,
            "executable_size": executable_size,
            "mod_files": updated_mod,
            "saves": copied_saves, "runtime_files": installed_runtime,
            "backups": backed_up, "thumbnails": len(MAP_THUMBNAILS)}


def install_all(source: Path, game: Path, manager: Path, icon: Path,
                package: Path | None = None, progress=None) -> dict:
    """Install the mod, loader, artwork, and desktop manager together."""
    manager, icon = Path(manager), Path(icon)
    for asset in (manager, icon):
        if not asset.is_file():
            raise FileNotFoundError(f"The installer is missing a required app file: {asset}")
    result = install(source, game, package,
                     progress=(lambda item, fraction: progress(item, fraction * 0.9))
                     if progress else None)
    target = result["target"]
    result["app_files"] = 0
    for index, (asset, name) in enumerate(((manager, "BlackOpsGameSaves.exe"),
                                            (icon, "BlackOpsGameSaves.ico")), 1):
        result["app_files"] += _copy_if_changed(asset, target / name)
        if progress:
            progress(f"mods/Game Save/{name}", 0.9 + index * 0.05)
    return result
