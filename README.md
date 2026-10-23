# Black Ops Game Saves

Save and restore your checkpoint saves in Black Ops Zombies.

A Windows save manager for Call of Duty: Black Ops Zombies. It copies in-memory
Zombies checkpoints to files after rounds and lets you resume a selected save
later. The manager supports Solo and Co-op checkpoints, map artwork, player
stats, favorites, save export/import, FoV and movement controls, and a co-op pause toggle.

## Install

Download the Windows package from Releases, then:

1. Run `InstallBlackOpsGameSaves.exe` and click **Install Game Save**.
2. Keep the detected game folder, or Browse to the folder containing
   `BlackOps.exe`, then click **Install**. The progress page lists the files.
3. On the completion page, choose whether to create a Desktop icon, then click
   **Run Black Ops Game Saves** or **Finish**. You can also open
   `mods\Game Save\BlackOpsGameSaves.exe` later.

The installer suggests the detected Black Ops folder and installs even when
the game's executable has not been tested. It installs the Game Save mod, map
thumbnails, `game_mod` loader, manager, and icon together. Only the installer
EXE is needed on another machine; all required files are embedded. Personal checkpoints
are never included in the installer, and existing checkpoints are retained.
The map screen stretches the Zombies lobby frame vertically, shows maps in rows on the left,
and previews the selected map's full, uncropped thumbnail on the right. Hover
over a map name to select it. New Game starts that map; Continue loads its
newest save. The saved checkpoints stay on the same screen, three per page,
with a pager and total count. Hover a save to highlight it, or right-click
for Start Game, Rename, Favorite, Export, and Delete. The full map list fits
without scrolling, including at the manager's minimum window size. The
mouse wheel changes save pages, stopping at the first and last page. The
lobby background keeps its original size and placement, while the save rows
keep a compact width. The supplied Helvetica Neue LT Pro 67 Medium Condensed font is loaded
privately for map titles, the Player Stats heading, and New Game and Continue;
other text keeps its original font.
The **Backspeed/strafe fix** button beside FoV remembers its setting. New Game Save
sessions start with the fix enabled and apply equal backward and strafe speed
to every player through GSC. Turning it off stays in effect when the manager
is reopened until the button is turned on again.
Older checkpoint sessions can apply the toggle to the local player without
changing the checkpoint scripts.
New checkpoints also record which script variant they use. On Continue, the
manager requests the equipped weapon stored in the checkpoint for each player
after the game has loaded. The checkpoint reader is built into the installer;
if a damaged save lacks a readable equipped weapon, the game still loads and
the manager reports the warning.
Older saves keep their matching scripts and remain loadable; their weapon
selection is unchanged.
New checkpoints also record when the map power is on. Continue requests that
flag while the map loads. Checkpoints made with older scripts keep their
original behavior; the old save format does not carry this new marker.

The manager needs Administrator access to read and write the game's memory.
It watches rounds while open. Press F11 in the game for an extra manual save.
The default End of Rounds setting prioritizes a checkpoint at each completed
round. Round Transitions and Start of Round are alternative timing choices.
If Continue is entered directly in the game, the manager detects the map
clock restarting and resumes round tracking. Overwrite Game Saves updates
the save launched with Start Game, even if another row is selected later. A
new game uses its first checkpoint as the overwrite target. Turn it off to
keep separate files.
Use **Export selected** or **Export all** to create a `.bo1gamesave` file and
**Import saves** on another machine to add it to the Imported saves view.
In a map's save list, hold Shift and click to select a range across pages, or
Ctrl-click to select individual saves. Press Shift+A to select every save on
the selected map in the current view. Then choose **Export selected** or
**Delete selected**.

The tested game executable has SHA-256
`1141278c4599025c85d0e27d1629a5e8ecb0568559c4d9653e693018c3b25f1e`.
The manager also accepts a different file when its mapped game code and data
are identical. For another build, the installer completes and displays the
`BlackOps.exe` hash and size. At runtime the manager reads the save pointers,
buffer header, and map identity before permitting memory writes. A compatible
live layout can be used after the first committed checkpoint. If those
addresses differ, saving and restore remain disabled until that build is
profiled. Installer or manager hashes cannot identify a game build.
Co-op restore still needs a live test with the same host and players. See
[CHECKPOINTS.md](CHECKPOINTS.md) for usage details and current limits.

## Build from source

Use Python 3.14 on Windows and install PyInstaller:

```powershell
python -m pip install pyinstaller==6.21.0
python build_release.py
python package_release.py v1.0.20
```

The build script produces `BlackOpsGameSaves.exe` and one installer,
`InstallBlackOpsGameSaves.exe`, in `release/`. The package script creates a
ZIP with both programs, checksums, and the tracked source. It packages only the required
mod files from this repository. Build outputs, personal checkpoints, the
decompiled engine reference, and local game files are excluded from Git.

Run the local checks with:

```powershell
python test_save_library.py
python test_checkpoint_gallery.py
python test_game_save_installer.py
python test_game_launcher.py
python test_fov_keeper.py
```

## Publishing

This checkout is prepared for `https://github.com/MidgetBlaster/BlackOpsGameSaves`.
Push the prepared branch and release tag with:

```powershell
git push -u origin main --follow-tags
```

The tag push starts the Windows release workflow. The local release package is
also available in `release/`.
