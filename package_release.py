"""Bundle Windows executables and tracked source into one release ZIP."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / "release"
PROGRAMS = ("BlackOpsGameSaves.exe", "InstallGameSaveMod.exe",
            "InstallBlackOpsGameSaves.exe")


def tracked_sources() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                            capture_output=True, check=True)
    paths = [ROOT / Path(name.decode("utf-8")) for name in result.stdout.split(b"\0") if name]
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Tracked source file is missing: {path}")
    return paths


def package(version: str = "v1.0.0") -> Path:
    if not version.startswith("v") or any(char in version for char in "/\\: "):
        raise ValueError("Use a version such as v1.0.0")
    RELEASE.mkdir(exist_ok=True)
    programs = [RELEASE / name for name in PROGRAMS]
    for path in programs:
        if not path.is_file():
            raise FileNotFoundError(f"Build the Windows programs first: {path}")
    sources = tracked_sources()
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                        for path in programs)
    (RELEASE / "SHA256SUMS.txt").write_text(checksums, encoding="ascii")
    target = RELEASE / f"BlackOpsGameSaves-{version}-windows.zip"
    temporary = target.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            for path in programs:
                archive.write(path, path.name)
            for name in ("README.txt", "SHA256SUMS.txt"):
                archive.write(RELEASE / name, name)
            for path in sources:
                archive.write(path, f"source/{path.relative_to(ROOT).as_posix()}")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(target) as archive:
        damaged = archive.testzip()
        if damaged:
            raise ValueError(f"Damaged release member: {damaged}")
    return target


if __name__ == "__main__":
    print(package(sys.argv[1] if len(sys.argv) > 1 else "v1.0.0"))
