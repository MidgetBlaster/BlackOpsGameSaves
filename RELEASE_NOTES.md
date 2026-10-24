# Black Ops Game Saves v1.0.25

- Continue now checks whether Black Ops processed the load request. If a
  higher-round checkpoint still appears to be at round 1, the manager waits
  for the map to finish opening and sends Continue once more. A remaining
  round-1 failure is reported instead of being shown as a successful load.
- Resume detection accepts the saved round or the following round and also
  watches the engine's save-reader state and level clock. This avoids relying
  only on the round byte, which can be zero after Continue.

## v1.0.24

- New installations start with Overwrite Game Saves enabled. A New Game makes
  its first checkpoint as a new save and overwrites that save afterward.
- Saved game rows and details show the next round after the stored checkpoint
  round. The checkpoint data and in-game round tracking are unchanged.
- Starting BlackOps.exe waits until the process appears or the user cancels,
  without a 90-second timeout popup.

## v1.0.23

- Installation creates `memory_profile.json` for the selected BlackOps.exe,
  recording its hash and the addresses derived from its PE data section.
  The tested executable is verified immediately. Other builds get a candidate
  profile that must pass a read-only check against a live checkpoint.
- Supports a whole-data-section address shift when the live checkpoint
  confirms the candidate. Saves record their source profile; loading across
  different address profiles remains blocked.

## v1.0.22

- The installer now lets users browse directly to their own BlackOps.exe.
  It installs beside that selected executable and reports its build hash when
  the build is untested.
  Selecting an executable does not discover unknown memory addresses; the
  running manager still validates the live save layout before writing.

## v1.0.21

- Keeps FoV writes and the stalled-save-queue repair disabled on an untested
  executable. These features use addresses separate from the checkpoint
  buffers and require a verified build.

## v1.0.20

- The installer now installs the complete mod and app for an untested
  BlackOps.exe instead of stopping before copying files. It shows the game
  executable's hash and size, with a button to copy those details.
- The manager checks an untested running game's save pointers and committed
  checkpoint header before any memory write. Builds with the known live layout
  can save after their first checkpoint. A different memory layout remains
  blocked until it has a verified address profile.

## v1.0.19

- Overwrite Game Saves now keeps the launched checkpoint as the target for
  every automatic and manual checkpoint, even after browsing another save.
  A new game uses its first checkpoint as the target when overwrite is on.
  Repeated replacements keep the same file, title, and favorite state.

## v1.0.18

- Keeps Shift+A scoped to the selected map. Selected-save deletion now names
  that map in the confirmation. Reinstalling the mod no longer brings back
  checkpoints previously deleted from the active save folder.

## v1.0.17

- Shift-click selects the full save range across pages on the selected map.
  Shift+A selects every save on that map in the current view. Ctrl-click and
  multi-save export and delete continue to work across pages.
- The manager can close while Black Ops is running or closed, including during
  a pending startup or save. It stops monitoring and briefly waits for an
  active checkpoint write to finish.

## v1.0.16

- Restores the fixed-size Zombies lobby background and its original centered,
  raised placement so Mission Select lines up with the artwork while the
  window changes size. The v1.0.15 save paging and font choices remain.

## v1.0.15

- Uses the supplied condensed Helvetica only for map names, the Player Stats
  heading, and New Game and Continue. Other text returns to its previous fonts.
- Scales the Zombies lobby background with the window and keeps the map
  thumbnail uncropped. Save rows stay the same compact width as the action
  buttons while the window resizes.
- The mouse wheel pages through saves. Page controls stop at the first and
  last page. Player stats spell out Points, Kills, Downs, and Revives.

## v1.0.14

- Shows the complete square map thumbnail in Mission Select instead of the
  cropped wide preview. The image fits at both normal and minimum window sizes.
- Keeps maps and saves on one screen. Hovering a map selects it; the right side
  has New Game, Continue, three saves per page, a pager, and the total count.
  Hovered saves turn white with black text, and their context menu retains
  Start Game, Rename, Favorite, Export, and Delete.
- Moves save filters, export, and import to the bottom controls. Bundles the
  supplied Helvetica Neue LT Pro 67 Medium Condensed font for the manager.
- Rearms round tracking after an in-game Continue. End of Rounds now follows
  the round-end signal; the other timing choices follow the transition and
  new-round boundaries. Restored checkpoints match their archived round even
  when Black Ops moves them to its other save buffer. Overwrite Game Saves
  targets the selected save.
- Adds a script variant for new checkpoints that records the power-on state
  and requests the power flag during Continue. Older saves retain their
  original script variant for compatibility.

## v1.0.13

- Fits the entire map selection and three recent saves in the window without
  scrolling, including at the minimum window size.
- Enables Backspeed/strafe fix by default for new settings. An explicit off
  choice stays off after the manager or game closes until it is turned on again.

## v1.0.12

- Stretches the lobby artwork vertically and places Mission Select in its top
  band, with map rows and preview aligned below it.
- Adds a persistent Backspeed/strafe fix toggle beside FoV. The new GSC applies
  equal backward and strafe speed to joined players when enabled. Older
  checkpoint sessions can apply it to the local player.
- For checkpoints made with the new script, reads the saved equipped weapon
  for each player and requests that weapon after Continue. Older script
  variants remain available for their existing checkpoints.

## v1.0.11

- Redesigns map selection around the Zombies lobby frame: map rows on the left,
  a wide selected-map preview on the right, and the three newest saves below.
- Shows each map's total save count in its preview section. Selected and hovered
  map rows turn white with black text; save-count hover tips are removed.
- Bundles the lobby background and all eleven wide map previews in the installer.

## v1.0.10

- Adds a welcome page with Install Game Save and Cancel, followed by a game
  folder page with Install and Cancel.
- Shows live installation progress and the files being copied.
- Moves the Desktop icon option and run button to the completion page.
- Hides the PowerShell process used to create the Desktop shortcut.

## v1.0.9

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
