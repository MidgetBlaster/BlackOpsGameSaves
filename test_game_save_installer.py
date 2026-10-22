"""Exercise install, bundled loader repair, and save preservation in a temp game."""

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

import checkpoint_memory as core
import game_save_installer
from game_save_installer import (MOD_FILES, MOD_FOLDERS, PACKAGE_FILES,
                                 find_game, install)


def test_install():
    with TemporaryDirectory(dir=Path(__file__).parent) as temporary:
        game = Path(temporary) / "Call of Duty Black Ops"
        source = game / "mods" / "devcommands"
        source.mkdir(parents=True)
        executable = game / "BlackOps.exe"
        executable.write_bytes(b"synthetic supported executable")
        for name in MOD_FILES:
            (source / name).write_text(f"file: {name}", encoding="utf-8")
        for folder in MOD_FOLDERS:
            (source / folder).mkdir()
            (source / folder / "example.txt").write_text(folder, encoding="utf-8")
        (source / "devcommands.iwd").write_bytes(b"mod iwd")
        saves = source / "checkpoint_saves"
        saves.mkdir()
        (saves / "old.bo1checkpoint").write_bytes(b"old checkpoint")
        catalog = {"format": 1, "active_profile": "imported",
                   "profiles": [{"id": "imported", "title": "Imported saves", "mode": "Unknown"}],
                   "saves": {"old.bo1checkpoint": {"title": "Old save"}}}
        (saves / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        package = source / "installer" / "game_mod.zip"
        with ZipFile(package, "w") as archive:
            for name in PACKAGE_FILES:
                archive.writestr(name, name.encode())
        assert find_game(source) == game.resolve()
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        with patch.object(core, "SUPPORTED_SHA256", digest):
            result = install(source, game, package)
            target = result["target"]
            assert target == game / "mods" / "Game Save"
            assert (target / "Game Save.iwd").read_bytes() == b"mod iwd"
            assert (target / "checkpoint_saves" / "old.bo1checkpoint").read_bytes() == b"old checkpoint"
            assert (game / "bin" / "game_mod.dll").read_bytes() == b"bin/game_mod.dll"
            assert len(result["runtime_files"]) == len(PACKAGE_FILES)
            # Reinstall must keep saves made after the first installation.
            (target / "checkpoint_saves" / "new.bo1checkpoint").write_bytes(b"new checkpoint")
            installed_catalog = json.loads((target / "checkpoint_saves" / "catalog.json").read_text())
            installed_catalog["saves"]["new.bo1checkpoint"] = {"title": "New save"}
            (target / "checkpoint_saves" / "catalog.json").write_text(json.dumps(installed_catalog))
            second = install(source, game, package)
            assert not second["runtime_files"]
            assert (target / "checkpoint_saves" / "new.bo1checkpoint").read_bytes() == b"new checkpoint"
            merged = json.loads((target / "checkpoint_saves" / "catalog.json").read_text())
            assert set(merged["saves"]) == {"old.bo1checkpoint", "new.bo1checkpoint"}


def test_steam_library_discovery():
    with TemporaryDirectory(dir=Path(__file__).parent) as temporary:
        root = Path(temporary)
        steam = root / "Steam"
        library = root / "Other Library"
        game = library / "steamapps" / "common" / "Call of Duty Black Ops"
        game.mkdir(parents=True)
        (game / "BlackOps.exe").write_bytes(b"game")
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        vdf.parent.mkdir(parents=True)
        vdf.write_text('"libraryfolders"\n{\n"1" { "path" "' +
                       str(library).replace("\\", "\\\\") + '" }\n}', encoding="utf-8")
        with patch.object(game_save_installer, "_registry_paths", return_value=[steam]):
            with patch.dict(os.environ, {"TA_TOOLS_PATH": "", "BLACK_OPS_PATH": ""}):
                assert find_game(root / "unrelated" / "mods" / "source") == game.resolve()


def test_unsupported_build_stops_before_installing():
    with TemporaryDirectory(dir=Path(__file__).parent) as temporary:
        game = Path(temporary) / "Call of Duty Black Ops"
        game.mkdir()
        executable = game / "BlackOps.exe"
        executable.write_bytes(b"different game build")
        with patch.object(core, "SUPPORTED_SHA256", "0" * 64):
            try:
                install(game, game)
            except RuntimeError as error:
                assert hashlib.sha256(executable.read_bytes()).hexdigest() in str(error)
            else:
                raise AssertionError("Installer accepted an unsupported game build")
        assert not (game / "mods" / "Game Save").exists()


if __name__ == "__main__":
    test_install()
    test_steam_library_discovery()
    test_unsupported_build_stops_before_installing()
    print("Game Save installation and reinstallation passed")
