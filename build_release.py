"""Build the save manager and one all-in-one Windows installer."""

from __future__ import annotations

import argparse
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
        with zipfile.ZipFile(iwd) as packaged:
            for name in packaged.namelist():
                if name.endswith(".csc") and (ROOT / name).is_file():
                    if packaged.read(name) != (ROOT / name).read_bytes():
                        raise RuntimeError(f"Packaged client script is stale: {name}")
        archive.write(iwd, "Game Save.iwd")
    return package


def main():
    global RELEASE
    parser = argparse.ArgumentParser(description="Build the manager and combined installer")
    parser.add_argument("--output", type=Path, default=RELEASE,
                        help="Folder for built executables (default: release)")
    RELEASE = parser.parse_args().output.resolve()
    RELEASE.mkdir(exist_ok=True)
    build("BlackOpsGameSaves", "checkpoint_gui.py", [(ICON, "."),
                                                    (ROOT / "memory_signatures.json", "."),
                                                    (ROOT / "ui fonts", "ui fonts")])
    payload = payload_zip()
    build("InstallBlackOpsGameSaves", "install_blackops_game_saves.py",
          [(payload, "."), (RELEASE / "BlackOpsGameSaves.exe", "."), (ICON, "."),
           (ROOT / "memory_signatures.json", ".")])
    for name in ("BlackOpsGameSaves", "InstallBlackOpsGameSaves"):
        executable = RELEASE / f"{name}.exe"
        print(f"{executable}: {executable.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
