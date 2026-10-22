# Black Ops Game Saves v1.0.9

- Makes the install action visible and labeled **Install Game Save** in a larger,
  resizable window.
- Adds **Run now** after the mod and manager finish installing.
- Verifies embedded PNG thumbnails and the game_mod loader before installation.

## v1.0.8

- Combines the Game Save mod, loader, map thumbnails, and save manager into one
  installer with an optional Desktop shortcut.
- Checks all required map images in the installer bundle and after installation.
- Keeps existing checkpoints and settings when reinstalling.

## v1.0.7

- Allows BlackOps.exe files with identical mapped game code and data even when
  resources or packaging change the overall file hash.
- Shows the selected executable path, hash, and size when a genuinely different
  build is blocked. Memory saves remain restricted to verified layouts.

## v1.0.6

- Makes each map row smaller and shows the save count only when hovering over it.

## v1.0.5

- Select several checkpoints with Shift or Ctrl, then export them in one
  package or delete them together.
- Shows maps as compact rows with the thumbnail beside the title.
- Stops sending a weapon-switch input after loading a checkpoint.
- Keeps the v1.0.4 recovery for stalled save requests after Continue.

## v1.0.2

- Adds End of Rounds, Round Transitions, and Start of Round auto save timing.
- Adds Start New Game for the selected map without loading a checkpoint.
- Names new saves Save Game 1, Save Game 2, and so on within each map.
- Waits for the restored round before resuming automatic saves.
- Uses the local Steam persona for the host name and removes player stat editing.
- Handles temporary save memory gaps while a map finishes loading.

## Initial release

First packaged Windows release. Includes:

- Separate Game Save mod and save manager installers.
- BlackOpsGameSaves.exe with the supplied icon.
- Automatic end-of-round checkpoints and F11 manual captures.
- Solo checkpoint resume; cooperative resume waits for players to rejoin.
- Portable save export/import with an Imported saves view.
- Save favorites, titles, player stats, FoV, borderless display, and co-op pause.
- Optional Desktop shortcut in the app installer.

Only the supported BlackOps.exe build is accepted. Cooperative restore and
cross-machine loading still need live testing. Personal checkpoints are not
packaged.
