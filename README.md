# Black Ops Game Saves

Save and restore your checkpoint saves in Black Ops Zombies.

A Windows save manager for Call of Duty: Black Ops Zombies. It copies in-memory
Zombies checkpoints to files after rounds and lets you resume a selected save
later. The manager supports Solo and Co-op checkpoints, map artwork, player
stats, favorites, save export/import, FoV controls, and a co-op pause toggle.

## Install

Download the Windows package from Releases, then:

1. Run `InstallBlackOpsGameSaves.exe` and select the folder containing
   `BlackOps.exe`. The Desktop shortcut option is selected by default.
2. Open Black Ops Game Saves from that shortcut or from
   `mods\Game Save\BlackOpsGameSaves.exe`.

The installer suggests the detected Black Ops folder and checks the game's
executable before copying anything. It installs the Game Save mod, map
thumbnails, `game_mod` loader, manager, and icon together. Personal checkpoints
are never included in the installer, and existing checkpoints are retained.

The manager needs Administrator access to read and write the game's memory.
It watches rounds while open. Press F11 in the game for an extra manual save.
Use **Export selected** or **Export all** to create a `.bo1gamesave` file and
**Import saves** on another machine to add it to the Imported saves view.
In a map's save list, hold Shift to select a range or Ctrl to select individual
saves, then choose **Export selected** or **Delete selected**.

The tested game executable has SHA-256
`1141278c4599025c85d0e27d1629a5e8ecb0568559c4d9653e693018c3b25f1e`.
The installer also accepts a different file when its mapped game code and data
are identical. Other builds show their path and SHA-256 so compatibility can be
investigated without risking a memory save on unknown addresses.
Co-op restore still needs a live test with the same host and players. See
[CHECKPOINTS.md](CHECKPOINTS.md) for usage details and current limits.

## Build from source

Use Python 3.14 on Windows and install PyInstaller:

```powershell
python -m pip install pyinstaller==6.21.0
python build_release.py
python package_release.py v1.0.8
```

The build script produces `BlackOpsGameSaves.exe` and one installer,
`InstallBlackOpsGameSaves.exe`, in `release/`. The package script creates a
ZIP with both programs, checksums, and the tracked source. It packages only the required
mod files from this repository. Build outputs, personal checkpoints, the
decompiled engine reference, and local game files are excluded from Git.

Run the local checks with:

```powershell
python test_save_library.py
python test_game_save_installer.py
python test_game_launcher.py
python test_fov_keeper.py
```

## Publishing

This checkout is prepared for `https://github.com/MidgetBlast/BlackOpsGameSaves`.
Push the prepared branch and release tag with:

```powershell
git push -u origin main
git push origin v1.0.8
```

The tag push starts the Windows release workflow. The local release package is
also available in `release/`.
