# Persistent Black Ops Zombies checkpoints

The game keeps Zombies' `devsave` checkpoints in process memory. Closing Black
Ops discards them. This companion copies the committed memory checkpoint to a
compressed, hashed file when a round ends and can put that checkpoint
back into memory during a later run.

This uses the save layout and fixed addresses documented in the
[decompiled engine](https://github.com/MisaDev4/bo1-zombies-decompiled),
especially `src/game_sp/g_sp_savegame.h` and `g_sp_savegame.cpp`. It accepts
the tested `BlackOps.exe` with SHA-256
`1141278c4599025c85d0e27d1629a5e8ecb0568559c4d9653e693018c3b25f1e`,
or a file whose mapped game code and data have the same layout and bytes.
Resource and packaging differences are allowed when that check matches. The
installer also copies the files for an untested executable and displays its
SHA-256 and size. The running manager then checks the known save pointers and
committed checkpoint header without writing memory. It permits memory writes
only after that live layout is verified. A build with different addresses
gets a candidate address profile if its PE data section moved as a whole.
The installer writes this to `mods/Game Save/memory_profile.json`; a live
checkpoint must confirm the candidate before it is used. A build whose
internal data layout changed still needs its own verified profile. The hash
of the installer or save manager cannot provide those addresses. Checkpoints
record their source data-section shift and are not restored across different
address profiles.
FoV writes and the stalled-save-queue repair stay off on an untested build
because their addresses are independent of the save buffer layout.
This is a process-memory tool for the retail game, not a build of the
decompiled executable. It never uses `players/save/*.svg`.

## Desktop save manager

After installation, open `BlackOpsGameSaves.exe` in `mods/Game Save`, or
double-click `Open Game Save.cmd`. For a source checkout, run
`python .\checkpoint_gui.py` in this folder. Windows will ask for Administrator access so the window can read
and write Black Ops memory. Close and reopen the manager after an update.

The `release` package has one installer and one standalone manager:

- `InstallBlackOpsGameSaves.exe` installs the Game Save mod, map artwork,
  loader files, and save manager together into `mods/Game Save`.
- `BlackOpsGameSaves.exe` is the save manager itself. Keep it in
  `mods/Game Save` alongside the installed mod files.

The first installer page has **Install Game Save** and **Cancel**. On the next
page, keep the detected `BlackOps.exe` path or Browse to the executable in
your own game folder, then click **Install**. A progress page lists each installed
item. On the completion page, select **Create a Desktop icon** if wanted, then
click **Run Black Ops Game Saves** or **Finish**. The installer EXE includes the mod,
loader, map PNGs, manager, and icon; no other download is required. The window and
executables use `BlackOpsGameSaves.ico`. Run `python build_release.py` to
rebuild both executables with PyInstaller. The installer excludes personal
checkpoints and catalogs, and retains existing installed saves.
Use **Export selected** or **Export all** in the manager to choose a folder
with the Windows folder picker. The resulting `.bo1gamesave` file contains
the checkpoint data, title, favorite mark, mode, and displayed player stats.
Copy it to another computer and choose **Import saves** there. Imported
checkpoints appear under **Imported saves** and can be started like local
checkpoints. An import creates new files, so existing saves are retained.

Click **Install Game Save mod** at the bottom right while Black Ops is closed.
The installer finds the game beside the current mod, from Steam's installed
libraries, or from Windows registry paths. It accepts `TA_TOOLS_PATH` as a
hint only when it leads to Black Ops; a path to Black Ops III is ignored. If
the game is not found, choose its folder. The installer copies the mod into
`mods/Game Save`, carries over checkpoints and their titles, and opens the
installed manager. It also installs the bundled `game_mod.zip` loader files
when missing or different, backing up any replaced files under
`mods/Game Save/checkpoint_saves/install_backups`. Existing saves in a prior
`Game Save` installation are kept. Later, open the manager with
`mods/Game Save/Open Game Save.cmd`.

- Mission Select fits the map rows and saved checkpoints on one screen. Hover
  over a map name to select it; the row turns white with black text. The full
  square thumbnail appears on the right, followed by New Game, Continue, and
  three saves per page. Use the arrows below the saves to change pages. The
  mouse wheel also changes save pages without going past either end. The
  pager also shows the map's total save count. Hovering a save highlights it;
  selecting one shows its player details beside the thumbnail. All saves,
  Imported saves, Export all, and Import saves sit with the bottom controls.
- The player panel shows points, weapons or loadout, revives, downs, and
  kills for each player. The manager reads these from checkpoints with its
  built-in LZO decoder. The host's Steam name is used in the
  display when an older checkpoint calls that player Unknown Soldier.
  Cooperative player extraction still needs validation with a real cooperative checkpoint.
- The manager starts watching when it opens. It makes a checkpoint when the
  Zombies round-end signal fires, using the advancing round counter if that
  signal was missed. After Continue, some sessions expose a zero round byte;
  the manager then carries forward the saved round and uses the round-end flag
  or round transition marker. If the game's asynchronous disk-save pointer
  stalls after `devsave 1`, the manager waits three seconds, converts queued
  `devsave 1` requests to memory-only commits, and clears the stale pointer.
  This keeps subsequent round and F11 checkpoints flowing without changing
  the GSC checksum or existing checkpoint files. It also archives a
  checkpoint made by pressing F11 in Black Ops. Opening the manager or starting
  a saved game does not create an automatic save. There is no round
  field or save-mode switch in the window. Black Ops needs to be in front when
  the manager presses its F11 binding.
- The window makes save files only after a completed round or when the player presses
  F11. It does not make a rolling recovery checkpoint. An existing recovery
  file from an older session can still be imported when the window opens.
- The **Overwrite Game Saves** button beside **Pause co-op** shows a green check
  when new round or F11 checkpoints replace the save launched with Start Game.
  Browsing another save does not change that target. A new game uses its first
  checkpoint as the target. A red X keeps separate saves. The setting is saved
  between manager sessions.
- **Auto Save Settings** cycles through End of Rounds, Round Transitions, and
  Start of Round. The watcher reads the Zombies round-end flag and round counter
  for these timings. The setting is remembered between manager sessions.
- **New Game** below the selected map artwork starts that map without
  continuing a saved checkpoint. Automatic saves begin at the chosen round timing.
- **Continue** loads the newest checkpoint for the selected map by save time.
- New checkpoints on a map receive titles Save Game 1, Save Game 2, and so on.
  Renamed titles remain unchanged, including when Overwrite Game Saves is on.
- Select a checkpoint to see its details. Hold **Shift** and click to select a
  range across pages, **Ctrl** to select individual saves, or press **Shift+A**
  to select every save on the selected map in the current view. The
  context menu's Export Save puts selected saves in one portable package;
  Delete removes them after confirmation.
- Right-click a save for **Start Game**, **Rename**, **Favorite**,
  **Export Save**, and **Delete**. Start Game runs `launcher_ldr.exe game_mod.dll ../BlackOps.exe`
  from the game's `bin` folder, passes the `Game Save` mod, checkpoint binds,
  and selected map, then waits for the map's save system during its opening
  screen. If Black Ops is already running, it
  uses F10 to restart the selected map without closing the application, including when
  the current map already matches.
  The manager supports both the current and older F10 config paths and
  reconnects if the map switch replaces the Black Ops process.
  In Solo it presses F11,
  retries during opening if the first key press was ignored, verifies the fresh
  checkpoint, briefly suspends the game to restore the selected checkpoint,
  then presses F12 to run `loadgame_continue`. It waits for the saved round to
  resume. For checkpoints made with the new player-options script, it then
  reads each player's equipped raw weapon ID from the checkpoint and asks GSC
  to select that weapon if the player still owns it. If a damaged checkpoint
  has no readable equipped weapon, the manager reports a warning and leaves
  the restored loadout alone. The restored round is not
  archived again; saving resumes on the next round or player F11. You can cancel
  while it is preparing. A game launched before the new F10 binding was added
  needs one restart through the manager to install that binding.
- New checkpoints include a power-on marker in the saved script state. During
  Continue, the manager requests `power_on` as the saved map resumes. Existing
  checkpoints keep their matching old scripts and cannot use the new marker.
- For **Co-op**, Start Game loads the map and shows a prompt. Let the same
  players rejoin before choosing OK. The manager then
  makes a fresh checkpoint with those players, restores the chosen save, and
  presses F12. This path still needs a live cooperative test.
- **Pause co-op** requests a script-controlled break for a new co-op game.
  The game server stays running so remote players can remain connected. The
  adapted GSC stops AI and spawning, freezes and protects joined players, and
  shows a pause message. Click **Resume co-op** to restore play. The manager
  pauses automatic saving during the break and resumes it afterward. F8 in
  Black Ops also requests resume if the manager window is unavailable.
  The script never resets the zombie count or rewrites the round timer.
- The bottom-left **FoV** controls set the horizontal field of view (1–360)
  and FoV scale (1.00–2.00). Click **FoV Off** to turn continuous updates on;
  click **FoV On** to stop them. The manager reapplies the values after a map
  change or reset while it is open. It writes only to the verified Black Ops
  singleplayer process, which also hosts solo and co-op Zombies, never the
  separate multiplayer executable. The pointer locations and refresh behavior
  are adapted from [CoD SCZ FoV Changer](https://github.com/marvinlehmann/CoD-SCZ-FoV-Changer)
  by Marvin Lehmann.
- **Backspeed/strafe fix** beside FoV shows a green check when enabled and a
  red X when disabled. Its setting is saved for the next launch. In new Game
  Save sessions, GSC applies `player_backSpeedScale=1` and
  `player_strafeSpeedScale=1` to joined players while enabled. Older checkpoint
  scripts remain unchanged so their script checksums continue to match. The
  manager applies the setting to the local player in those older sessions;
  remote co-op players need a new-script session for the shared setting.
- The **Display** selector at the bottom right offers Windowed, Fullscreen,
  and Borderless. Borderless is the default. The selection is remembered in the
  save catalog and applied automatically when Black Ops starts. Borderless
  switches the retail game to windowed mode with F7 when needed, then removes
  its frame and sizes the window to the current monitor. The retail game does
  not support `r_noborder`. Fullscreen uses F6; Windowed uses F7. The manager
  checks the resulting window before showing success. Start Game loads these
  bindings automatically; a game opened before this update needs to load the
  updated `checkpoint.cfg` or restart through the manager once.
- Existing checkpoints retain their original script checksums. Start Game
  selects the exact pre-pause raw Zombies script kept in
  `scriptdata/checkpoint_variants` for those saves, so the new co-op pause
  feature is unavailable during those legacy sessions. New sessions use the
  adapted GSC in `maps/_checkpoint_coop_pause.gsc`. Do not save during a
  co-op break; the manager stops its watcher while paused. The original
  `mod.ff` is also backed up in `checkpoint_saves/legacy_mod_backup`.
- Press F11 in Black Ops whenever you want an extra saved game. The manager
  archives it automatically; no button press in the window is needed.

Save titles, favorites, game names, player details, and the overwrite and timing choices are stored in
`checkpoint_saves/catalog.json`. The `.bo1checkpoint` files contain the game
state and are never rewritten when you rename or favorite a save. The list
shows each save's round, Solo or player count when known, and timestamp.

## Save each round

1. Load the `Game Save` mod and start Zombies.
2. Open the save manager. It watches Black Ops as soon as the window opens.
   Start Game loads `checkpoint.cfg` with F10 for switching maps, F11 for
   `devsave 1`, and F12 for `loadgame_continue`.
3. If starting Black Ops outside the manager, run
   `exec "mods/Game Save/checkpoint.cfg"` once in the game console.
4. The companion briefly brings Black Ops to the front if needed and presses
   F11 at the end of the round, waits for a new committed save ID, then
   archives the game's save structure and both data buffers in
   `checkpoint_saves/*.bo1checkpoint`. A `Saved round ...` message means the
   capture succeeded. `python .\checkpoint.py list` shows the files. The
   watcher can identify the map from the engine's committed checkpoint if
   the LiveSplit scene address is unavailable on this Black Ops build.

To use the PowerShell companion without the window, run
`python .\checkpoint.py watch`. It uses the same round and F11 detection.

To make the first archive directly, run `devsave 1` in the game console. Then
run `python checkpoint.py capture` in PowerShell. This detects the round and
reads the already committed checkpoint; it does not need the game
to be in front. It also confirms the save filename and ID. Run
`python checkpoint.py list` before trying `restore`.

If `capture` rejects the checkpoint header, run `python checkpoint.py inspect`
while the game is still open. It prints the map name, checksum, save filename,
and state without changing memory; include that output when reporting the error.

## Resume after closing Black Ops

1. Stop `watch`. Start the same mod, same scripts, same map, and same player
   setup. Let the round begin and ensure the game has made at least one fresh
   checkpoint (F11 if necessary).
2. Pause the solo game so gameplay actually stops. In PowerShell, run
   `python checkpoint.py restore`. The companion checks that the server frame
   and time counters stay still before writing. To use
   another checkpoint, pass its full `.bo1checkpoint` path.
3. The companion checks the executable, map checksum, script checksums and
   checkpoint hashes before writing. It saves the running game's previous
   checkpoint as `before-restore-*.bo1checkpoint`.
4. Return to the game console and run `loadgame_continue` (or press F12).
   Start `watch` again after the restored round begins with
   `python checkpoint.py watch`; it detects the restored round automatically.

If Windows denies memory access, the companion requests Administrator access
through Windows and opens a new PowerShell window that stays open, including
when the watcher reports an error. Continue there after the UAC prompt.
The game and companion need the same privilege level. This is Windows process
access, not a mod or script error.

## Current verification limit

The decompiled code shows that the engine serializes every client slot, so
the captured memory includes the engine's cooperative client records. A
round 2 solo checkpoint on `zombie_cod5_factory` was captured and restored
successfully after a full game restart. The watcher also captured rounds 4
and 5 in a live solo game, confirming an automatic save on a round change.
Cooperative loading and remote-player reconnection are still unverified; do
a short private test with the same host and players before relying on a long
cooperative run. The new in-process F10 map switch has automated checks but
still needs an in-game test.

For a cooperative test, use the same host and let all players join before
`devsave 1`. Capture with `python checkpoint.py capture`. On the next run,
let those players join the same map and make a fresh `devsave 1`, then run
`python checkpoint.py restore --coop` on the host. The cooperative pause menu
does not stop the server, so this mode briefly suspends the host process while
it replaces the checkpoint. After it resumes, run `loadgame_continue` on the
host. Remote-player reconnection and their restored state need an in-game test.

The old `.svg` archiver was invalid for Zombies and has been removed.
