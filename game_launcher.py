"""Launch a selected BO1 checkpoint through game_mod and resume its map."""

from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
import threading
import time

import checkpoint_memory as core

# Checksum set found in all checkpoints made before the co-op pause GSC was
# added. These saves use the exact original raw source kept below.
LEGACY_SCRIPT_CHECKSUMS = {(1547989158, 617289, 624409)}
SCRIPT_SOURCE = core.ROOT / "maps" / "_zombiemode.gsc"
SCRIPT_VARIANTS = core.ROOT / "scriptdata" / "checkpoint_variants"


def mod_game_path() -> str:
    return f"mods/{core.ROOT.name}"


def legacy_scripts(metadata: dict) -> bool:
    return tuple(metadata.get("script_checksums", ())) in LEGACY_SCRIPT_CHECKSUMS


def prepare_script_variant(*, legacy: bool):
    """Select the matching raw script before the next map loads."""
    old = (SCRIPT_VARIANTS / "_zombiemode_legacy.gsc").read_bytes()
    new = (SCRIPT_VARIANTS / "_zombiemode_pause.gsc").read_bytes()
    current = SCRIPT_SOURCE.read_bytes()
    if current not in (old, new):
        raise RuntimeError("The Zombies script was edited outside the save manager. Check it before loading a checkpoint.")
    wanted = old if legacy else new
    if current == wanted:
        return
    temporary = SCRIPT_SOURCE.with_suffix(".gsc.tmp")
    temporary.write_bytes(wanted)
    os.replace(temporary, SCRIPT_SOURCE)


class GameProcessReplaced(RuntimeError):
    """The loader's first BlackOps.exe process gave way to another one."""


def launch_command(map_name: str) -> tuple[list[str], Path]:
    if not re.fullmatch(r"[A-Za-z0-9_]+", map_name):
        raise ValueError("The save has an invalid map name")
    folder = core.GAME / "bin"
    launcher = folder / "launcher_ldr.exe"
    dll = folder / "game_mod.dll"
    executable = core.GAME / "BlackOps.exe"
    for path in (launcher, dll, executable):
        if not path.is_file():
            raise FileNotFoundError(f"Required game file is missing: {path}")
    # The first three arguments are exactly the user's working loader command
    # from the bin directory. The loader forwards the remaining game arguments.
    return ([str(launcher), "game_mod.dll", "../BlackOps.exe",
             "+set", "fs_game", mod_game_path(),
             "+set", "scr_useFastFileOnly", "0",
             "+exec", "checkpoint.cfg",
             "+devmap", map_name], folder)


def _check_cancel(cancel: threading.Event | None):
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Starting the saved game was canceled")


def wait_for_game(cancel: threading.Event | None = None, timeout: float = 90,
                  *, write: bool = False, suspend: bool = False) -> core.GameProcess:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _check_cancel(cancel)
        pid = core.game_pid()
        if pid:
            try:
                return core.GameProcess(pid, write=write, suspend=suspend)
            except PermissionError:
                raise
            except OSError:
                # The loader may have created BlackOps.exe before its image is
                # fully mapped. Reattach after process initialization.
                pass
        time.sleep(0.5)
    raise RuntimeError("Black Ops did not start within 90 seconds")


def wait_for_replacement_game(previous_pid: int, cancel: threading.Event | None = None,
                              timeout: float = 90) -> core.GameProcess:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _check_cancel(cancel)
        pid = core.game_pid()
        if pid and pid != previous_pid:
            try:
                return core.GameProcess(pid, write=True, suspend=True)
            except PermissionError:
                raise
            except OSError:
                pass
        time.sleep(0.2)
    raise RuntimeError("Black Ops restarted during the map switch but its new process did not become available")


def wait_for_map_ready(game: core.GameProcess, map_name: str,
                       cancel: threading.Event | None = None, timeout: float = 180,
                       *, during_opening: bool = False,
                       allow_stale_checkpoint: bool = False):
    """Wait for live server ticks and the map's initialized save buffers."""
    expected_scene = core.MAP_SCENES.get(map_name)
    threshold = 0 if during_opening else core.START_TICKS.get(expected_scene, 195)
    deadline = time.monotonic() + timeout
    previous_frame = None
    ready_samples = 0
    save_region_seen = False
    while time.monotonic() < deadline:
        _check_cancel(cancel)
        if getattr(game, "pid", None) is not None and core.game_pid() != game.pid:
            raise GameProcessReplaced("Black Ops restarted while loading the map")
        try:
            menu = game.u32(core.MENU_ADDR)
            timer = game.u32(core.TIMER_ADDR)
            frame = game.u32(core.LEVEL_FRAME_ADDR)
            level_time = game.u32(core.LEVEL_TIME_ADDR)
            raw_scene = game.u32(core.SCENE_ADDR)
            committed_address = game.u32(core.COMMITTED_PTR)
            write_address = game.u32(core.WRITE_PTR)
            save_region_ready = (committed_address in core.BUFFERS and
                                 write_address in core.BUFFERS and
                                 committed_address != write_address)
            save_region_seen |= save_region_ready
            committed_map = None
            if save_region_ready:
                try:
                    _, _, header = core.committed(game)
                    committed_map = header["map"]
                except RuntimeError:
                    # A fresh map has no devsave yet. The pointers still need
                    # to be mapped and initialized before F11 can create one.
                    pass
            map_matches = allow_stale_checkpoint or committed_map in (None, map_name)
            if raw_scene in core.SCENES and expected_scene is not None:
                map_matches = map_matches and raw_scene == expected_scene
            playing = (menu == 0 and timer > threshold and level_time > 0 and
                       previous_frame is not None and frame > previous_frame and
                       save_region_ready and map_matches)
            ready_samples = ready_samples + 1 if playing else 0
            if ready_samples >= (2 if during_opening else 3):
                return
            previous_frame = frame
        except OSError as error:
            if isinstance(error, PermissionError) or error.errno not in (299, 487, 998):
                raise
            ready_samples = 0  # game memory can be transient during startup
        time.sleep(0.1 if during_opening else 0.5)
    if not save_region_seen:
        raise RuntimeError(f"The {map_name} map became playable, but its save memory did not initialize. Check that the game started through game_mod.dll and try again.")
    raise RuntimeError(f"The {map_name} map did not reach playable state after its opening screen")


def switch_running_map(game: core.GameProcess, map_name: str,
                       cancel: threading.Event | None = None, *, legacy: bool = False):
    """Run devmap through a prebound F10 without opening the game console."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", map_name):
        raise ValueError("The save has an invalid map name")
    prepare_script_variant(legacy=legacy)
    switch_file = core.ROOT / "checkpoint_switch.cfg"
    compatibility_file = core.ROOT / "mods" / core.ROOT.name / "checkpoint_switch.cfg"
    compatibility_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = switch_file.with_suffix(".cfg.tmp")
    command = (
        f"set checkpoint_coop_pause 0\n"
        f"set scr_useFastFileOnly 0\n"
        f"devmap {map_name}\n")
    temporary.write_text(command, encoding="ascii")
    os.replace(temporary, switch_file)
    compatibility_file.write_text(command, encoding="ascii")
    try:
        try:
            old_frame = game.u32(core.LEVEL_FRAME_ADDR)
            old_time = game.u32(core.LEVEL_TIME_ADDR)
        except OSError:
            old_frame = old_time = 0
        wait_for_focus(game, cancel)
        try:
            if game.u32(core.PAUSED_ADDR) == 4:
                game.press_game_key(0x1B, "Escape from pause menu")
                time.sleep(0.3)
        except OSError:
            pass
        game.press_switch()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            _check_cancel(cancel)
            if core.game_pid() != game.pid:
                raise GameProcessReplaced("Black Ops changed processes during the map switch")
            try:
                frame = game.u32(core.LEVEL_FRAME_ADDR)
                level_time = game.u32(core.LEVEL_TIME_ADDR)
                if ((old_frame > 30 and frame + 20 < old_frame)
                        or (old_time > 1000 and level_time + 1000 < old_time)
                        or (old_frame == 0 and old_time == 0
                            and frame > 10 and level_time > 0)):
                    wait_for_map_ready(game, map_name, cancel, during_opening=True,
                                       allow_stale_checkpoint=True)
                    return
            except OSError as error:
                if isinstance(error, PermissionError) or error.errno not in (299, 487, 998):
                    raise
            time.sleep(0.1)
        raise RuntimeError("Black Ops did not switch maps. Restart it once through the updated manager to install the F10 switch binding.")
    finally:
        switch_file.unlink(missing_ok=True)
        compatibility_file.unlink(missing_ok=True)


def wait_for_focus(game: core.GameProcess, cancel: threading.Event | None = None,
                   timeout: float = 30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _check_cancel(cancel)
        if game.foreground() or game.activate_window():
            return
        time.sleep(0.5)
    raise RuntimeError("Bring Black Ops to the front so the manager can send its save/load keys")


def make_fresh_checkpoint(game: core.GameProcess, map_name: str,
                          cancel: threading.Event | None = None):
    # The save address can briefly become unreadable as the opening cinematic
    # hands control to the game. Do not abandon a playable map on that race.
    deadline = time.monotonic() + 20
    while True:
        _check_cancel(cancel)
        try:
            address = game.u32(core.COMMITTED_PTR)
            other = game.u32(core.WRITE_PTR)
            if address in core.BUFFERS and other in core.BUFFERS and address != other:
                try:
                    previous_address, _, old = core.committed(game)
                    previous_id = old["save_id"]
                except RuntimeError:
                    previous_id = -1
                    previous_address = None
                break
        except OSError as error:
            if isinstance(error, PermissionError) or error.errno not in (299, 487, 998):
                raise
        if time.monotonic() >= deadline:
            raise RuntimeError("The map is playable, but the game's save memory is unavailable. Retry Start Game after closing Black Ops.")
        time.sleep(0.1)
    # The loader can expose initialized save buffers before the engine starts
    # accepting bound keys. Try during the opening screen, then retry once the
    # map is fully playable; no player key press is needed.
    wait_for_focus(game, cancel)
    try:
        core.request_fresh_checkpoint(game, previous_id, timeout=3,
                                      prior_address=previous_address)
    except core.CheckpointNotCommitted:
        # The engine may start accepting bound keys after its save buffers
        # initialize but before the map is fully playable. Retry there once.
        for attempt, timeout in enumerate((3, 5, 12)):
            _check_cancel(cancel)
            try:
                current_address, _, current = core.committed(game)
                if (current["save_id"] != previous_id or
                        (previous_address in core.BUFFERS and
                         current_address != previous_address)):
                    break  # the previous F11 completed just after its timeout
            except RuntimeError:
                pass
            except OSError as error:
                if isinstance(error, PermissionError) or error.errno not in (299, 487, 998):
                    raise
            if attempt == 1:
                wait_for_map_ready(game, map_name, cancel, during_opening=False)
            wait_for_focus(game, cancel)
            try:
                core.request_fresh_checkpoint(game, previous_id, timeout=timeout,
                                              prior_address=previous_address)
                break
            except core.CheckpointNotCommitted:
                if timeout == 12:
                    raise
    _, _, fresh = core.committed(game)
    if fresh["map"] != map_name:
        raise RuntimeError(f"Black Ops loaded {fresh['map']}, but this save needs {map_name}")


def restore_and_continue(game: core.GameProcess, save_path: Path, mode: str,
                         cancel: threading.Event | None = None):
    metadata, _ = core.load_archive(save_path)
    make_fresh_checkpoint(game, metadata["map"], cancel)
    if mode not in ("Solo", "Co-op"):
        raise ValueError("Choose Solo or Co-op for this save before starting it")
    _check_cancel(cancel)
    # Suspend the live server for either mode. The solo pause menu intercepts
    # console and bound keys, preventing the final continue command.
    core.restore(game, save_path, coop=True)
    wait_for_focus(game, cancel)
    # Start Game restores under a brief process suspension, so the pause menu
    # is closed and F12 reaches the engine's loadgame_continue binding.
    game.press_load()
    return metadata


def start_selected_game(save_path: Path, mode: str, cancel: threading.Event | None = None,
                        report=None) -> tuple[core.GameProcess, dict]:
    metadata, _ = core.load_archive(save_path)
    use_legacy = legacy_scripts(metadata)
    running_pid = core.game_pid()
    if running_pid:
        if report:
            report(f"Starting {metadata['map']} in the running game...")
        game = core.GameProcess(running_pid, write=True, suspend=True)
        try:
            # Restart the map even when it already matches. Loading directly
            # into an active server bypasses the opening state that BO1's
            # loadgame_continue expects and can leave a live session broken.
            switch_running_map(game, metadata["map"], cancel, legacy=use_legacy)
            return game, metadata
        except GameProcessReplaced:
            game.close()
            if report:
                report("Black Ops restarted while switching maps. Reconnecting to the selected map...")
            replacement = wait_for_replacement_game(running_pid, cancel)
            try:
                wait_for_map_ready(replacement, metadata["map"], cancel,
                                   during_opening=True)
                return replacement, metadata
            except BaseException:
                replacement.close()
                raise
        except BaseException:
            game.close()
            raise
    prepare_script_variant(legacy=use_legacy)
    command, folder = launch_command(metadata["map"])
    if report:
        report(f"Starting {metadata['map']} with game_mod.dll and the Game Save mod...")
    subprocess.Popen(command, cwd=folder)
    deadline = time.monotonic() + 180
    game = wait_for_game(cancel, write=True, suspend=True)
    while True:
        try:
            if report:
                report("Waiting for the map's save system during its opening screen...")
            wait_for_map_ready(game, metadata["map"], cancel,
                               timeout=max(0, deadline - time.monotonic()),
                               during_opening=True)
            return game, metadata
        except GameProcessReplaced:
            game.close()
            if report:
                report("Black Ops switched processes during startup. Reconnecting to the game...")
            game = wait_for_game(cancel, timeout=max(0, deadline - time.monotonic()),
                                 write=True, suspend=True)
        except BaseException:
            game.close()
            raise
