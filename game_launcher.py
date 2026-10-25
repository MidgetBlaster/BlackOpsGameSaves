"""Launch a selected BO1 checkpoint through game_mod and resume its map."""

from __future__ import annotations

from pathlib import Path
import os
import re
import subprocess
import threading
import time

import checkpoint_memory as core
from checkpoint_stats import extract_players
import steam_identity

# Checksum set found in all checkpoints made before the co-op pause GSC was
# added. These saves use the exact original raw source kept below.
LEGACY_SCRIPT_CHECKSUMS = {(1547989158, 617289, 624409)}
SCRIPT_SOURCE = core.ROOT / "maps" / "_zombiemode.gsc"
SCRIPT_VARIANTS = core.ROOT / "scriptdata" / "checkpoint_variants"
OPTIONS_SCRIPT = core.ROOT / "maps" / "_checkpoint_coop_pause.gsc"


def mod_game_path() -> str:
    return f"mods/{core.ROOT.name}"


def legacy_scripts(metadata: dict) -> bool:
    return tuple(metadata.get("script_checksums", ())) in LEGACY_SCRIPT_CHECKSUMS


def enhanced_scripts(metadata: dict) -> bool:
    return metadata.get("script_variant") in ("player_options_v1", "player_options_v2", "map_state_v1")


def round_bridge_scripts(metadata: dict) -> bool:
    return metadata.get("script_variant") in ("player_options_v2", "map_state_v1")


def prepare_script_variant(*, legacy: bool, enhanced: bool = False,
                           round_bridge: bool = False, map_state: bool = False):
    """Select the matching raw script before the next map loads."""
    old = (SCRIPT_VARIANTS / "_zombiemode_legacy.gsc").read_bytes()
    new = (SCRIPT_VARIANTS / "_zombiemode_pause.gsc").read_bytes()
    current = SCRIPT_SOURCE.read_bytes()
    if current not in (old, new):
        raise RuntimeError("The Zombies script was edited outside the save manager. Check it before loading a checkpoint.")
    wanted = old if legacy else new
    old_options = (SCRIPT_VARIANTS / "_checkpoint_coop_pause_v1.gsc").read_bytes()
    new_options = (SCRIPT_VARIANTS / "_checkpoint_coop_pause_v2.gsc").read_bytes()
    bridge_options = (SCRIPT_VARIANTS / "_checkpoint_coop_pause_v3.gsc").read_bytes()
    state_path = SCRIPT_VARIANTS / "_checkpoint_coop_pause_v4.gsc"
    state_options = state_path.read_bytes() if state_path.is_file() else bridge_options
    current_options = OPTIONS_SCRIPT.read_bytes()
    if current_options not in (old_options, new_options, bridge_options, state_options):
        raise RuntimeError("The player options script was edited outside the save manager. Check it before loading a checkpoint.")
    wanted_options = (state_options if map_state and not legacy else
                      bridge_options if round_bridge and not legacy else
                      new_options if enhanced and not legacy else old_options)
    for path, current_data, wanted_data in ((SCRIPT_SOURCE, current, wanted),
                                            (OPTIONS_SCRIPT, current_options, wanted_options)):
        if current_data != wanted_data:
            temporary = path.with_suffix(".gsc.tmp")
            temporary.write_bytes(wanted_data)
            os.replace(temporary, path)


    client_script = core.ROOT / "clientscripts" / "zombie_cosmodrome.csc"
    original_client = SCRIPT_VARIANTS / "zombie_cosmodrome_v1.csc"
    if original_client.is_file():
        known = [path.read_bytes() for path in (
            original_client, SCRIPT_VARIANTS / "zombie_cosmodrome_v2.csc",
            SCRIPT_VARIANTS / "zombie_cosmodrome_v3.csc") if path.is_file()]
        if client_script.read_bytes() not in known:
            raise RuntimeError("Ascension's client script was modified outside the manager")
        desired = original_client.read_bytes()
        # Native and same-session round trips worked with the modified CSC,
        # but an older archive only loaded after restoring this original CSC.
        if client_script.read_bytes() != desired:
            temporary = client_script.with_suffix('.csc.tmp')
            temporary.write_bytes(desired)
            os.replace(temporary, client_script)


class GameProcessReplaced(RuntimeError):
    """The loader's first BlackOps.exe process gave way to another one."""


def launch_command(map_name: str) -> tuple[list[str], Path]:
    if not re.fullmatch(r"[A-Za-z0-9_]+", map_name):
        raise ValueError("The save has an invalid map name")
    if core.CLIENT == "plutonium":
        raise RuntimeError("Start Plutonium T5 through its signed-in launcher, load Game Save from Mods, and run exec checkpoint.cfg once. Then use this manager's New Game or Continue.")
    folder = core.GAME / "bin"
    launcher = folder / "launcher_ldr.exe"
    dll = folder / "game_mod.dll"
    executable = core.GAME / "BlackOps.exe"
    for path in (launcher, dll, executable):
        if not path.is_file():
            raise FileNotFoundError(f"Required game file is missing: {path}")
    # The first three arguments are exactly the user's working loader command
    # from the bin directory. The loader forwards the remaining game arguments.
    command = [str(launcher), "game_mod.dll", "../BlackOps.exe",
             "+set", "fs_game", mod_game_path(),
             "+set", "scr_useFastFileOnly", "0",
             "+exec", "checkpoint.cfg"]
    persona = steam_identity.launch_name(core.GAME)
    if persona:
        command.extend(("+set", "name", persona))
    command.extend(("+devmap", map_name))
    return command, folder


def _check_cancel(cancel: threading.Event | None):
    if cancel is not None and cancel.is_set():
        raise RuntimeError("Starting the saved game was canceled")


def wait_for_game(cancel: threading.Event | None = None, timeout: float | None = None,
                  *, write: bool = False, suspend: bool = False) -> core.GameProcess:
    deadline = None if timeout is None else time.monotonic() + timeout
    while deadline is None or time.monotonic() < deadline:
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
    raise RuntimeError(f"Black Ops did not start within {timeout:g} seconds")


def wait_for_replacement_game(previous_pid: int, cancel: threading.Event | None = None,
                              timeout: float | None = None) -> core.GameProcess:
    deadline = None if timeout is None else time.monotonic() + timeout
    while deadline is None or time.monotonic() < deadline:
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
            if not during_opening and expected_scene in (20, 76):
                playing = playing and core.opening_round_ready(
                    expected_scene, level_time, core.live_round(game))
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
    if expected_scene == 76:
        raise RuntimeError("Moon has not started its first round. Use the teleporter out of No Man's Land before retrying Continue.")
    raise RuntimeError(f"The {map_name} map did not reach playable state after its opening screen")


def switch_running_map(game: core.GameProcess, map_name: str,
                       cancel: threading.Event | None = None, *, legacy: bool = False,
                       enhanced: bool = False, round_bridge: bool = False, map_state: bool = False):
    """Run devmap through a prebound F10 without opening the game console."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", map_name):
        raise ValueError("The save has an invalid map name")
    prepare_script_variant(legacy=legacy, enhanced=enhanced,
                           round_bridge=round_bridge, map_state=map_state)
    switch_file = core.ROOT / "checkpoint_switch.cfg"
    compatibility_file = core.ROOT / "mods" / core.ROOT.name / "checkpoint_switch.cfg"
    compatibility_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = switch_file.with_suffix(".cfg.tmp")
    persona = steam_identity.launch_name(core.GAME)
    command = (
        f"set checkpoint_coop_pause 0\n"
        f"set scr_useFastFileOnly 0\n"
        f'bind F4 "exec checkpoint_weapons.cfg"\n'
        f'bind F5 "exec checkpoint_speed.cfg"\n'
        f'bind F3 "exec checkpoint_speed_local.cfg"\n'
        f'bind F2 "exec checkpoint_power.cfg"\n'
        f"reset player_backSpeedScale\n"
        f"reset player_strafeSpeedScale\n"
        f"set checkpoint_restore_power_on 0\n"
        'set checkpoint_map_restore_token ""\n'
        'set checkpoint_legacy_vision_token ""\n'
        f"set scr_zm_extra_perk_all 1\n"
        f"exec checkpoint_speed.cfg\n"
        + (f'set name "{persona}"\n' if persona else "")
        + f"devmap {map_name}\n")
    temporary.write_text(command, encoding="utf-8")
    os.replace(temporary, switch_file)
    compatibility_file.write_text(command, encoding="utf-8")
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
                wait_for_map_ready(game, map_name, cancel, during_opening=True)
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


def prepare_restore_options(save_path, metadata):
    if round_bridge_scripts(metadata):
        power_restore_config(bool(metadata.get("power_on")),
                             map_state=metadata.get("script_variant") == "map_state_v1")
    weapon_config = None
    if enhanced_scripts(metadata):
        try:
            weapon_config = weapon_restore_config(save_path)
            if not weapon_config:
                metadata["weapon_restore_warning"] = "The saved equipped weapon could not be identified."
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            metadata["weapon_restore_warning"] = f"Could not read the saved equipped weapon: {error}"
    return weapon_config


def restore_and_continue(game: core.GameProcess, save_path: Path, mode: str,
                         cancel: threading.Event | None = None,
                         *, speed_fix_enabled: bool = False):
    prepared = getattr(game, "_ascension_restore", None)
    if prepared is not None and prepared[0] == Path(save_path).resolve():
        metadata, pieces, weapon_config = prepared[1:]
        game._ascension_restore = None  # consume only this selected launch
    else:
        metadata, pieces = core.load_archive(save_path)
        weapon_config = prepare_restore_options(save_path, metadata)

    power_config = round_bridge_scripts(metadata)
    if metadata["map"] == "zombie_cosmodrome":
        # Saved games resume at the initialized-map boundary, as verified by
        # the early Continue test. Do not wait for the lander or round one.
        # The original client script and checkpoint validation remain required.
        wait_for_map_ready(game, metadata["map"], cancel,
                           during_opening=True, allow_stale_checkpoint=True)
    make_fresh_checkpoint(game, metadata["map"], cancel)
    if mode not in ("Solo", "Co-op"):
        raise ValueError("Choose Solo or Co-op for this save before starting it")
    _check_cancel(cancel)
    # Suspend the live server for either mode. The solo pause menu intercepts
    # console and bound keys, preventing the final continue command.
    if metadata["map"] == "zombie_cosmodrome":
        core.restore(game, save_path, coop=True, prepared_archive=(metadata, pieces))
    else:
        core.restore(game, save_path, coop=True)
    wait_for_focus(game, cancel)
    before_continue = (game.u32(core.LEVEL_FRAME_ADDR), game.u32(core.LEVEL_TIME_ADDR))
    if power_config:
        game.press_game_key(0x71, "F2 restore power state before Continue")
    if weapon_config:
        # Arm the saved client-slot/weapon-name requests before the saved VM
        # resumes. Repeat after confirmation if the opening consumes the key.
        game.press_game_key(0x73, "F4 equipped weapon restore before Continue")
    # Start Game restores under a brief process suspension, so the pause menu
    # is closed and F12 reaches the engine's loadgame_continue binding.
    game.press_load()
    if power_config:
        # The first request reaches the opening screen; repeat it as the
        # restored script VM resumes so power is applied before play begins.
        time.sleep(0.2)
        game.press_game_key(0x71, "F2 restore power state during Continue")
    resumed = wait_for_loaded_round(game, metadata.get("round"), cancel,
                                    timeout=8, before_clock=before_continue)
    if not resumed:
        try:
            saved_round = metadata.get("round")
            current_round = core.live_round(game)
            still_at_first_round = (isinstance(saved_round, int) and saved_round > 1 and
                                    current_round in (None, 1))
        except OSError:
            still_at_first_round = False
        if still_at_first_round:
            # Ascension and other maps can accept the fresh F11 checkpoint
            # before the script VM is ready to process the first F12.
            wait_for_map_ready(game, metadata["map"], cancel,
                               during_opening=True, allow_stale_checkpoint=True)
            wait_for_focus(game, cancel)
            before_continue = (game.u32(core.LEVEL_FRAME_ADDR),
                               game.u32(core.LEVEL_TIME_ADDR))
            game.press_load()
            resumed = wait_for_loaded_round(game, metadata.get("round"), cancel,
                                            timeout=20, before_clock=before_continue)
            if not resumed and core.live_round(game) == 1:
                raise RuntimeError(
                    f"{metadata['map']} stayed at round 1 after two Continue attempts. "
                    "The checkpoint is still available; check the Black Ops console "
                    "for a load error before trying again.")
    if not resumed:
        raise RuntimeError(
            "Black Ops did not confirm that the selected checkpoint resumed. "
            "The saved file has been kept. Check the game console for a load error "
            "and retry Continue after the map is playable.")
    if metadata["map"] == "zombie_cosmodrome" and metadata.get("ascension_vision"):
        import ascension_vision
        try:
            ascension_vision.restore(game, metadata["ascension_vision"])
        except (OSError, RuntimeError, ValueError) as error:
            metadata["resume_warning"] = f"Checkpoint loaded, but Ascension vision was not restored: {error}"
    if weapon_config:
        wait_for_focus(game, cancel)
        game.press_game_key(0x73, "F4 equipped weapon restore")
    if speed_fix_enabled and not enhanced_scripts(metadata):
        wait_for_focus(game, cancel)
        game.press_game_key(0x72, "F3 local movement fix")
    return metadata


def power_restore_config(power_on: bool, *, map_state: bool = False):
    """Provide the saved power flag to the map before and during Continue."""
    content = f"set checkpoint_restore_power_on {int(power_on)}\n"
    if map_state:
        content += 'set checkpoint_legacy_vision_token ""\n'
        content += f'set checkpoint_map_restore_token "{time.time_ns()}"\n'
    else:
        content += f'set checkpoint_legacy_vision_token "{time.time_ns()}"\n'
    path = core.ROOT / "checkpoint_power.cfg"
    temporary = path.with_suffix(".cfg.tmp")
    temporary.write_text(content, encoding="ascii")
    os.replace(temporary, path)
    compatibility = core.ROOT / "mods" / core.ROOT.name / "checkpoint_power.cfg"
    compatibility.parent.mkdir(parents=True, exist_ok=True)
    compatibility.write_text(content, encoding="ascii")


def weapon_restore_config(save_path: Path) -> bool:
    """Pass saved raw weapon IDs to GSC, never player-provided command text."""
    players = extract_players(save_path)
    commands = [f'set checkpoint_restore_weapon_{slot} ""' for slot in range(4)]
    equipped = 0
    for player in players:
        slot = player.get("client_slot")
        weapon = player.get("equipped_weapon_raw", "")
        if isinstance(slot, int) and 0 <= slot < 4 and re.fullmatch(r"[A-Za-z0-9_]{1,64}", weapon):
            commands[slot] = f'set checkpoint_restore_weapon_{slot} "{weapon}"'
            equipped += 1
    if not equipped:
        return False
    commands.append(f'set checkpoint_restore_token "{time.time_ns()}"')
    path = core.ROOT / "checkpoint_weapons.cfg"
    temporary = path.with_suffix(".cfg.tmp")
    temporary.write_text("\n".join(commands) + "\n", encoding="ascii")
    os.replace(temporary, path)
    compatibility = core.ROOT / "mods" / core.ROOT.name / "checkpoint_weapons.cfg"
    compatibility.parent.mkdir(parents=True, exist_ok=True)
    compatibility.write_text(path.read_text(encoding="ascii"), encoding="ascii")
    return True


def wait_for_loaded_round(game: core.GameProcess, saved_round: int | None,
                          cancel: threading.Event | None = None,
                          timeout: float = 20,
                          *, before_clock: tuple[int, int] | None = None) -> bool:
    """Confirm Continue by save-reader state, clock change, or restored round."""
    if not saved_round and before_clock is None:
        return False
    started = time.monotonic()
    last_frame = None
    stable = 0
    load_started = False
    while time.monotonic() - started < timeout:
        _check_cancel(cancel)
        try:
            frame = game.u32(core.LEVEL_FRAME_ADDR)
            level_time = game.u32(core.LEVEL_TIME_ADDR)
            menu = game.u32(core.MENU_ADDR)
            observed = core.live_round(game)
            elapsed = time.monotonic() - started
            if before_clock is not None:
                prior_frame, prior_time = before_clock
                if (frame + 20 < prior_frame or level_time + 1000 < prior_time or
                        level_time > prior_time + elapsed * 1000 + 5000):
                    load_started = True
            try:
                committed_address = game.u32(core.COMMITTED_PTR)
                if committed_address in core.BUFFERS and \
                        game.u32(committed_address + core.STATE_OFFSET) == 4:
                    load_started = True
            except OSError as error:
                if isinstance(error, PermissionError) or error.errno not in (299, 487, 998):
                    raise
            round_matches = (isinstance(saved_round, int) and saved_round > 0 and
                             observed in (saved_round, saved_round + 1))
            if (menu == 0 and (load_started or
                    (isinstance(saved_round, int) and saved_round > 1 and round_matches)) and
                    last_frame is not None and frame > last_frame and elapsed >= 1.5):
                stable += 1
                if stable >= 3:
                    return True
            else:
                stable = 0
            last_frame = frame
        except OSError as error:
            if isinstance(error, PermissionError) or error.errno not in (299, 487, 998):
                raise
            stable = 0
        time.sleep(0.25)
    return False


def start_selected_game(save_path: Path, mode: str, cancel: threading.Event | None = None,
                        report=None) -> tuple[core.GameProcess, dict]:
    metadata, pieces = core.load_archive(save_path)
    core.validate_client_script(metadata)
    prepared = None
    if metadata["map"] == "zombie_cosmodrome":
        prepared = (Path(save_path).resolve(), metadata, pieces,
                    prepare_restore_options(save_path, metadata))
    def ready_result(game):
        if prepared is not None:
            game._ascension_restore = prepared
        return game, metadata
    use_legacy = legacy_scripts(metadata)
    use_enhanced = enhanced_scripts(metadata)
    use_round_bridge = round_bridge_scripts(metadata)
    use_map_state = metadata.get("script_variant") == "map_state_v1"
    opening_hint = " Restoring as soon as the map's save buffers initialize."
    running_pid = core.game_pid()
    if running_pid:
        if report:
            report(f"Starting {metadata['map']} in the running game...{opening_hint}")
        game = core.GameProcess(running_pid, write=True, suspend=True)
        try:
            # Restart the map even when it already matches. Loading directly
            # into an active server bypasses the opening state that BO1's
            # loadgame_continue expects and can leave a live session broken.
            switch_running_map(game, metadata["map"], cancel, legacy=use_legacy,
                               enhanced=use_enhanced, round_bridge=use_round_bridge, map_state=use_map_state)
            return ready_result(game)
        except GameProcessReplaced:
            game.close()
            if report:
                report("Black Ops restarted while switching maps. Reconnecting to the selected map...")
            replacement = wait_for_replacement_game(running_pid, cancel)
            try:
                wait_for_map_ready(replacement, metadata["map"], cancel,
                                   during_opening=True)
                return ready_result(replacement)
            except BaseException:
                replacement.close()
                raise
        except BaseException:
            game.close()
            raise
    prepare_script_variant(legacy=use_legacy, enhanced=use_enhanced,
                           round_bridge=use_round_bridge, map_state=use_map_state)
    command, folder = launch_command(metadata["map"])
    if report:
        report(f"Starting {metadata['map']} with game_mod.dll and the Game Save mod...")
    subprocess.Popen(command, cwd=folder)
    game = wait_for_game(cancel, write=True, suspend=True)
    deadline = time.monotonic() + 180
    while True:
        try:
            if report:
                report("Waiting for the map's save system..." + opening_hint)
            wait_for_map_ready(game, metadata["map"], cancel,
                               timeout=max(0, deadline - time.monotonic()),
                               during_opening=True)
            return ready_result(game)
        except GameProcessReplaced:
            game.close()
            if report:
                report("Black Ops switched processes during startup. Reconnecting to the game...")
            game = wait_for_game(cancel, write=True, suspend=True)
            deadline = time.monotonic() + 180
        except BaseException:
            game.close()
            raise


def start_new_game(map_name: str, cancel: threading.Event | None = None,
                   report=None) -> core.GameProcess:
    """Start a fresh map with the mod, without creating or loading a checkpoint."""
    if not re.fullmatch(r"[A-Za-z0-9_]+", map_name):
        raise ValueError("The selected map name is invalid")
    running_pid = core.game_pid()
    if running_pid:
        if report:
            report(f"Starting a new {map_name} game in Black Ops...")
        game = core.GameProcess(running_pid, write=True, suspend=True)
        try:
            switch_running_map(game, map_name, cancel, legacy=False, enhanced=True,
                               round_bridge=True, map_state=True)
            wait_for_map_ready(game, map_name, cancel, during_opening=core.MAP_SCENES.get(map_name) == 76,
                               allow_stale_checkpoint=True)
            return game
        except GameProcessReplaced:
            game.close()
            replacement = wait_for_replacement_game(running_pid, cancel)
            try:
                wait_for_map_ready(replacement, map_name, cancel,
                                   during_opening=core.MAP_SCENES.get(map_name) == 76)
                return replacement
            except BaseException:
                replacement.close()
                raise
        except BaseException:
            game.close()
            raise
    prepare_script_variant(legacy=False, enhanced=True, round_bridge=True, map_state=True)
    command, folder = launch_command(map_name)
    if report:
        report(f"Starting a new {map_name} game with the Game Save mod...")
    subprocess.Popen(command, cwd=folder)
    game = wait_for_game(cancel, write=True, suspend=True)
    deadline = time.monotonic() + 180
    while True:
        try:
            wait_for_map_ready(game, map_name, cancel,
                               timeout=max(0, deadline - time.monotonic()),
                               during_opening=core.MAP_SCENES.get(map_name) == 76)
            return game
        except GameProcessReplaced:
            game.close()
            game = wait_for_game(cancel, write=True, suspend=True)
            deadline = time.monotonic() + 180
        except BaseException:
            game.close()
            raise
