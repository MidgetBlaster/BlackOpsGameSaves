"""Exercise install, bundled loader repair, and save preservation in a temp game."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch
from zipfile import ZipFile

import checkpoint_memory as core
import game_save_installer
from game_save_installer import (MOD_FILES, MOD_FOLDERS, PACKAGE_FILES,
                                 MAP_THUMBNAILS, MAP_PREVIEWS, MENU_BACKGROUND,
                                 find_game, install, install_all)


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
        thumbnails = source / "ui textures" / "png"
        thumbnails.mkdir()
        for name in MAP_THUMBNAILS:
            (thumbnails / name).write_bytes(
                (Path(__file__).parent / "ui textures" / "png" / name).read_bytes())
        for name in (*MAP_PREVIEWS, *MENU_BACKGROUND):
            destination = source / "ui textures" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((Path(__file__).parent / "ui textures" / name).read_bytes())
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
            assert result["thumbnails"] == len(MAP_THUMBNAILS)
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


def test_complete_bundle_installs_artwork_and_manager():
    import build_release
    import installer_frontend

    payload = build_release.payload_zip()
    with TemporaryDirectory(dir=Path(__file__).parent) as temporary:
        root = Path(temporary)
        game = root / "Call of Duty Black Ops"
        game.mkdir()
        executable = game / "BlackOps.exe"
        executable.write_bytes(b"synthetic supported executable")
        source = root / "bundle"
        source.mkdir()
        with ZipFile(payload) as archive:
            archive.extractall(source)
        manager = root / "BlackOpsGameSaves.exe"
        manager.write_bytes(b"packaged manager")
        icon = root / "BlackOpsGameSaves.ico"
        icon.write_bytes((Path(__file__).parent / "BlackOpsGameSaves.ico").read_bytes())
        with patch.object(installer_frontend, "resource", lambda name: root / name):
            (root / "game_save_mod_payload.zip").write_bytes(payload.read_bytes())
            assert installer_frontend.verify_bundle() == (root / "game_save_mod_payload.zip",
                                                          manager, icon)
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        with patch.object(core, "SUPPORTED_SHA256", digest):
            progress = []
            result = install_all(source, game, manager, icon,
                                 progress=lambda item, fraction: progress.append((item, fraction)))
            target = result["target"]
            assert progress[-1] == ("mods/Game Save/BlackOpsGameSaves.ico", 1.0)
            assert any("ui textures/png/" in item for item, _ in progress)
            assert any(item == "bin/game_mod.dll" for item, _ in progress)
            assert all(first[1] <= second[1] for first, second in zip(progress, progress[1:]))
            assert result["thumbnails"] == len(MAP_THUMBNAILS)
            assert (target / "BlackOpsGameSaves.exe").read_bytes() == b"packaged manager"
            assert (target / "BlackOpsGameSaves.ico").read_bytes() == icon.read_bytes()
            assert (target / "mod.ff").read_bytes() == (source / "mod.ff").read_bytes()
            assert (target / "Game Save.iwd").is_file()
            assert (game / "bin" / "game_mod.dll").is_file()
            for name in MAP_THUMBNAILS:
                expected = (source / "ui textures" / "png" / name).read_bytes()
                assert expected.startswith(b"\x89PNG\r\n\x1a\n")
                assert (target / "ui textures" / "png" / name).read_bytes() == expected
            for name in (*MAP_PREVIEWS, *MENU_BACKGROUND):
                expected = (source / "ui textures" / name).read_bytes()
                assert (target / "ui textures" / name).read_bytes() == expected
            repeat = install_all(source, game, manager, icon)
            assert repeat["app_files"] == 0
            assert not repeat["runtime_files"]


def test_installer_run_now_after_completion():
    import installer_frontend

    with TemporaryDirectory(dir=Path(__file__).parent) as temporary:
        manager = Path(temporary) / "Game Save" / "BlackOpsGameSaves.exe"
        manager.parent.mkdir()
        manager.write_bytes(b"installed manager")
        with patch.object(game_save_installer, "find_game", return_value=None):
            window = installer_frontend.Installer()
        destroyed = False
        try:
            window.update()
            assert window.page == "welcome"
            assert window.start_button.cget("text") == "Install Game Save"
            assert window.cancel_button.cget("text") == "Cancel"
            assert len(window.winfo_children()) == 2
            window.show_location()
            window.update()
            assert window.page == "location"
            assert window.install_button.cget("text") == "Install"
            assert window.shortcut.get() is True
            assert (window.install_button.winfo_rooty() + window.install_button.winfo_height()
                    <= window.winfo_rooty() + window.winfo_height())
            window.show_progress()
            window._report_ui("mods/Game Save/mod.ff", 0.5)
            assert window.progress_value.get() == 50
            window.finish({"target": manager.parent, "thumbnails": len(MAP_THUMBNAILS)})
            assert window.page == "complete"
            assert window.run_button.cget("text") == "Run Black Ops Game Saves"
            with (patch.object(installer_frontend.subprocess, "Popen") as launch,
                  patch.object(installer_frontend, "create_desktop_shortcut") as shortcut):
                window.run_installed()
                destroyed = True
                shortcut.assert_called_once_with(manager, manager.parent / "BlackOpsGameSaves.ico")
                launch.assert_called_once_with([str(manager)], cwd=manager.parent)
        finally:
            if not destroyed:
                window.destroy()


def test_wizard_installs_to_selected_game_folder():
    import build_release
    import installer_frontend

    payload = build_release.payload_zip()
    with TemporaryDirectory(dir=Path(__file__).parent) as temporary:
        root = Path(temporary)
        game = root / "Selected Black Ops Folder"
        game.mkdir()
        executable = game / "BlackOps.exe"
        executable.write_bytes(b"synthetic supported executable")
        (root / "game_save_mod_payload.zip").write_bytes(payload.read_bytes())
        (root / "BlackOpsGameSaves.exe").write_bytes(b"packaged manager")
        (root / "BlackOpsGameSaves.ico").write_bytes(
            (Path(__file__).parent / "BlackOpsGameSaves.ico").read_bytes())
        digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        with (patch.object(core, "SUPPORTED_SHA256", digest),
              patch.object(installer_frontend, "resource", lambda name: root / name),
              patch.object(game_save_installer, "find_game", return_value=None),
              patch.object(installer_frontend.messagebox, "showerror") as errors):
            window = installer_frontend.Installer()
            try:
                window.show_location()
                window.folder.set(str(game))
                window.begin()
                deadline = time.monotonic() + 20
                while window.page == "progress" and time.monotonic() < deadline:
                    window.update()
                    time.sleep(0.02)
                assert window.page == "complete", (
                    f"Installer stopped on {window.page}; error: {errors.call_args}")
                target = game / "mods" / "Game Save"
                assert (target / "BlackOpsGameSaves.exe").read_bytes() == b"packaged manager"
                assert (target / "ui textures" / "png" / MAP_THUMBNAILS[0]).is_file()
                assert (game / "bin" / "game_mod.dll").is_file()
                assert window.progress_value.get() == 100
                window.shortcut.set(False)
            finally:
                window.destroy()


def test_desktop_shortcut_process_stays_hidden():
    import installer_frontend

    with patch.object(installer_frontend.subprocess, "run",
                      return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
        installer_frontend.create_desktop_shortcut(
            Path(r"C:\Games\Black Ops\mods\Game Save\BlackOpsGameSaves.exe"),
            Path(r"C:\Games\Black Ops\mods\Game Save\BlackOpsGameSaves.ico"))
    args, kwargs = run.call_args
    assert args[0][:4] == ["powershell.exe", "-NoProfile", "-NonInteractive",
                           "-WindowStyle"]
    assert args[0][4] == "Hidden"
    assert kwargs["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)


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
    test_complete_bundle_installs_artwork_and_manager()
    test_installer_run_now_after_completion()
    test_wizard_installs_to_selected_game_folder()
    test_desktop_shortcut_process_stays_hidden()
    test_unsupported_build_stops_before_installing()
    print("Game Save installation and reinstallation passed")
