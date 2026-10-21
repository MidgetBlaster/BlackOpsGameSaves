"""Build the save manager and its two separate Windows installers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import zipfile

import game_save_installer as installer


ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build" / "game-save-release"
RELEASE = ROOT / "release"
ICON = ROOT / "BlackOpsGameSaves.ico"


def build(name: str, script: str, extras: list[tuple[Path, str]] = None):
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--onefile", "--windowed", "--name", name, "--icon", str(ICON),
               "--distpath", str(RELEASE), "--workpath", str(BUILD / "work"),
               "--specpath", str(BUILD / "specs")]
    for source, destination in extras or []:
        command.extend(["--add-data", f"{source};{destination}"])
    command.append(str(ROOT / script))
    subprocess.run(command, cwd=ROOT, check=True)


def payload_zip() -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    package = BUILD / "game_save_mod_payload.zip"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in installer.MOD_FILES:
            archive.write(ROOT / name, name)
        for folder in installer.MOD_FOLDERS:
            for path in (ROOT / folder).rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(ROOT).as_posix())
        iwd = ROOT / "Game Save.iwd"
        if not iwd.is_file():
            iwd = ROOT / "devcommands.iwd"
        archive.write(iwd, "Game Save.iwd")
    return package


if __name__ == "__main__":
    RELEASE.mkdir(exist_ok=True)
    build("BlackOpsGameSaves", "checkpoint_gui.py", [(ICON, ".")])
    payload = payload_zip()
    build("InstallGameSaveMod", "install_game_save_mod.py",
          [(payload, "."), (ICON, ".")])
    build("InstallBlackOpsGameSaves", "install_blackops_game_saves.py",
          [(RELEASE / "BlackOpsGameSaves.exe", "."), (ICON, ".")])
    for name in ("BlackOpsGameSaves", "InstallGameSaveMod", "InstallBlackOpsGameSaves"):
        executable = RELEASE / f"{name}.exe"
        print(f"{executable}: {executable.stat().st_size:,} bytes")
