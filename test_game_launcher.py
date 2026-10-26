from unittest.mock import patch
import ctypes
import itertools
from pathlib import Path
from tempfile import TemporaryDirectory
import threading

import checkpoint_memory as core
import game_launcher


for waiting in (lambda cancel: game_launcher.wait_for_game(cancel),
                lambda cancel: game_launcher.wait_for_replacement_game(4420, cancel)):
    cancel = threading.Event()
    with (patch.object(core, "game_pid", return_value=None),
          patch.object(game_launcher.time, "sleep", side_effect=lambda _: cancel.set())):
        try:
            waiting(cancel)
        except RuntimeError as error:
            assert "canceled" in str(error)
        else:
            raise AssertionError("Game startup wait ignored Cancel")


command, directory = game_launcher.launch_command("zombie_cod5_factory")
assert directory.name == "bin"
assert command[1:3] == ["game_mod.dll", "../BlackOps.exe"]
assert command[-2:] == ["+devmap", "zombie_cod5_factory"]
assert command[3:6] == ["+set", "fs_game", f"mods/{core.ROOT.name}"]
assert command[6:9] == ["+set", "scr_useFastFileOnly", "0"]
assert command[9:11] == ["+exec", "checkpoint.cfg"]
assert 'bind F10 "exec checkpoint_switch.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert 'bind F4 "exec checkpoint_weapons.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert 'bind F5 "exec checkpoint_speed.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert 'bind F3 "exec checkpoint_speed_local.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert 'bind F2 "exec checkpoint_power.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert 'bind F7 "exec checkpoint_borderless.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert 'bind F6 "exec checkpoint_fullscreen.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert "r_fullscreen 0\nvid_restart" in (core.ROOT / "checkpoint_borderless.cfg").read_text()
assert "r_fullscreen 1\nvid_restart" in (core.ROOT / "checkpoint_fullscreen.cfg").read_text()
assert game_launcher.legacy_scripts({"script_checksums": [1547989158, 617289, 624409]})
assert not game_launcher.legacy_scripts({"script_checksums": [1, 2, 3]})
assert game_launcher.enhanced_scripts({"script_variant": "player_options_v1"})
assert game_launcher.enhanced_scripts({"script_variant": "player_options_v2"})
assert game_launcher.round_bridge_scripts({"script_variant": "player_options_v2"})
assert not game_launcher.round_bridge_scripts({"script_variant": "player_options_v1"})
assert not game_launcher.enhanced_scripts({"script_checksums": [1, 2, 3]})
with TemporaryDirectory(dir=core.ROOT) as directory:
    folder = Path(directory)
    variant_dir = folder / "variants"
    variant_dir.mkdir()
    (variant_dir / "_zombiemode_legacy.gsc").write_bytes(b"original script")
    (variant_dir / "_zombiemode_pause.gsc").write_bytes(b"pause script")
    (variant_dir / "_checkpoint_coop_pause_v1.gsc").write_bytes(b"old options")
    (variant_dir / "_checkpoint_coop_pause_v2.gsc").write_bytes(b"new options")
    (variant_dir / "_checkpoint_coop_pause_v3.gsc").write_bytes(b"round bridge options")
    active_script = folder / "_zombiemode.gsc"
    active_script.write_bytes(b"pause script")
    options_script = folder / "_checkpoint_coop_pause.gsc"
    options_script.write_bytes(b"new options")
    with (patch.object(game_launcher, "SCRIPT_SOURCE", active_script),
          patch.object(game_launcher, "OPTIONS_SCRIPT", options_script),
          patch.object(game_launcher, "SCRIPT_VARIANTS", variant_dir)):
        game_launcher.prepare_script_variant(legacy=True)
        assert active_script.read_bytes() == b"original script"
        assert options_script.read_bytes() == b"old options"
        game_launcher.prepare_script_variant(legacy=False)
        assert active_script.read_bytes() == b"pause script"
        assert options_script.read_bytes() == b"old options"
        game_launcher.prepare_script_variant(legacy=False, enhanced=True)
        assert options_script.read_bytes() == b"new options"
        game_launcher.prepare_script_variant(legacy=False, enhanced=True, round_bridge=True, map_state=True)
        assert options_script.read_bytes() == b"round bridge options"
    with (patch.object(core, "ROOT", folder),
          patch.object(game_launcher, "extract_players", return_value=[
              {"client_slot": 0, "equipped_weapon_raw": "ithaca_zm"},
              {"client_slot": 1, "equipped_weapon_raw": "thompson_upgraded_zm"},
              {"client_slot": 2, "equipped_weapon_raw": "bad;quit"}])):
        assert game_launcher.weapon_restore_config(folder / "example.bo1checkpoint")
        commands = (folder / "checkpoint_weapons.cfg").read_text()
        assert 'set checkpoint_restore_weapon_0 "ithaca_zm"' in commands
        assert 'set checkpoint_restore_weapon_1 "thompson_upgraded_zm"' in commands
        assert "bad;quit" not in commands
        assert "checkpoint_restore_token" in commands
        game_launcher.power_restore_config(True)
        assert (folder / "checkpoint_power.cfg").read_text().startswith(
            "set checkpoint_restore_power_on 1\n")
        assert (folder / "mods" / folder.name / "checkpoint_power.cfg").read_text().startswith(
            "set checkpoint_restore_power_on 1\n")
try:
    game_launcher.launch_command("factory;quit")
except ValueError:
    pass
else:
    raise AssertionError("Unsafe map name was accepted")


class FakeGame:
    def __init__(self):
        self.sample = 0
        self.states = [
            (1, 0, 0, 0),        # frontend
            (0, 90, 10, 500),    # opening screen
            (0, 220, 11, 550),  # map rendered
            (0, 230, 12, 600),
            (0, 240, 13, 650),
            (0, 250, 14, 700),
            (0, 260, 15, 750),
            (0, 270, 16, 800),
            (0, 280, 17, 850),
        ]

    def u32(self, address):
        menu, timer, frame, level_time = self.states[min(self.sample, len(self.states) - 1)]
        values = {core.MENU_ADDR: menu, core.TIMER_ADDR: timer,
                  core.LEVEL_FRAME_ADDR: frame, core.LEVEL_TIME_ADDR: level_time,
                  core.SCENE_ADDR: 0xFFFFFFFF,
                  core.COMMITTED_PTR: core.SAVE_A,
                  core.WRITE_PTR: core.SAVE_B}
        if address == core.COMMITTED_PTR and self.sample < 5:
            raise OSError(299, "Save region not mapped during startup")
        result = values[address]
        if address == core.SCENE_ADDR:
            self.sample += 1
        return result


fake = FakeGame()
with patch.object(core, "committed", side_effect=RuntimeError("No checkpoint yet")):
    game_launcher.wait_for_map_ready(fake, "zombie_cod5_factory", timeout=5)
assert fake.sample >= 8  # did not proceed while the save region was unmapped

fake.pid = 111
with patch.object(core, "game_pid", return_value=222):
    try:
        game_launcher.wait_for_map_ready(fake, "zombie_cod5_factory", timeout=1)
    except game_launcher.GameProcessReplaced:
        pass
    else:
        raise AssertionError("Did not reconnect after Black Ops switched processes")

sent_flags = []
key_game = object.__new__(core.GameProcess)
key_game.foreground = lambda: True

class FakeUser32:
    def MapVirtualKeyW(self, key, _mode):
        return key

    def SendInput(self, count, event, _size):
        assert count == 1
        sent_flags.append(ctypes.cast(event, ctypes.POINTER(core.INPUT)).contents.data.ki.dwFlags)
        return 1

key_game.user = FakeUser32()
with patch.object(core.time, "sleep") as delay:
    key_game.press_game_key(0x7A, "F11")
assert sent_flags == [8, 10]
delay.assert_called_once_with(0.06)
assert ctypes.sizeof(core.INPUT) == 40


class FreshGame:
    def __init__(self):
        self.commands = []

    def u32(self, address):
        return {core.COMMITTED_PTR: core.SAVE_A,
                core.SAVE_QUEUE_COUNT: 0,
                core.WRITE_PTR: core.SAVE_B,
                core.LEVEL_FRAME_ADDR: 100,
                core.LEVEL_TIME_ADDR: 5000}[address]

    def press_save(self):
        self.commands.append("F11")

    def press_load(self):
        self.commands.append("F12")


fresh_game = FreshGame()
with (patch.object(core, "committed", side_effect=[RuntimeError("No save yet"),
                                                  (core.SAVE_A, b"", {"map": "zombie_cod5_factory"})]),
      patch.object(core, "wait_for_new_save") as wait_for_save,
      patch.object(game_launcher, "wait_for_focus")):
    game_launcher.make_fresh_checkpoint(fresh_game, "zombie_cod5_factory")
assert fresh_game.commands == ["F11"]
wait_for_save.assert_called_once_with(fresh_game, -1, timeout=3, prior_address=None)

retry_game = FreshGame()
with (patch.object(core, "committed", side_effect=[
          (core.SAVE_A, b"", {"map": "zombie_cod5_factory", "save_id": 7}),
          (core.SAVE_A, b"", {"map": "zombie_cod5_factory", "save_id": 7}),
          (core.SAVE_B, b"", {"map": "zombie_cod5_factory", "save_id": 8})]),
      patch.object(core, "wait_for_new_save", side_effect=[core.CheckpointNotCommitted("opening"), None]) as wait_for_save,
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_map_ready") as wait_for_ready):
    game_launcher.make_fresh_checkpoint(retry_game, "zombie_cod5_factory")
assert retry_game.commands == ["F11", "F11"]
assert [call.kwargs["timeout"] for call in wait_for_save.call_args_list] == [3, 3]
wait_for_ready.assert_not_called()

with (patch.object(core, "load_archive", return_value=({"map": "zombie_cod5_factory", "round": 4}, {})),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore") as restore_mock,
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=True)):
    game_launcher.restore_and_continue(fresh_game, core.ARCHIVE / "sample.bo1checkpoint", "Solo")
assert fresh_game.commands[-1] == "F12"
assert restore_mock.call_args.kwargs["coop"] is True
assert "prepared_archive" not in restore_mock.call_args.kwargs

fresh_game.press_game_key = lambda key, description: fresh_game.commands.append((key, description))
with (patch.object(core, "load_archive", return_value=({
          "map": "zombie_cod5_factory", "round": 4,
          "script_variant": "player_options_v1"}, {})),
      patch.object(game_launcher, "weapon_restore_config", return_value=True),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore"),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=True)):
    game_launcher.restore_and_continue(fresh_game, core.ARCHIVE / "sample.bo1checkpoint", "Solo")
assert fresh_game.commands[-2:] == ["F12", (0x73, "F4 equipped weapon restore")]

fresh_game.commands.clear()
with (patch.object(core, "load_archive", return_value=({
          "map": "zombie_cod5_factory", "round": 4, "power_on": True,
          "script_variant": "player_options_v2"}, {})),
      patch.object(game_launcher, "weapon_restore_config", return_value=False),
      patch.object(game_launcher, "power_restore_config") as power_config,
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore"),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=True),
      patch.object(game_launcher.time, "sleep")):
    game_launcher.restore_and_continue(fresh_game, core.ARCHIVE / "sample.bo1checkpoint", "Solo")
power_config.assert_called_once_with(True, map_state=False)
assert fresh_game.commands[:3] == [
    (0x71, "F2 restore power state before Continue"), "F12",
    (0x71, "F2 restore power state during Continue")]

with (patch.object(core, "load_archive", return_value=({"map": "zombie_cod5_factory", "round": 4}, {})),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore"),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=True)):
    game_launcher.restore_and_continue(
        fresh_game, core.ARCHIVE / "sample.bo1checkpoint", "Solo", speed_fix_enabled=True)
assert fresh_game.commands[-2:] == ["F12", (0x72, "F3 local movement fix")]

with (patch.object(core, "load_archive", return_value=({"map": "zombie_cod5_factory", "round": 4}, {})),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore"),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=True) as loaded):
    game_launcher.restore_and_continue(fresh_game, core.ARCHIVE / "sample.bo1checkpoint", "Solo")
loaded.assert_called_once_with(fresh_game, 4, None, timeout=8, before_clock=(100, 5000))


ascension_game = FreshGame()
with (patch.object(core, "load_archive", return_value=({
          "map": "zombie_cosmodrome", "round": 7}, {})),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore"),
      patch.object(core, "live_round", return_value=1),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_map_ready") as map_ready,
      patch.object(game_launcher, "wait_for_loaded_round", side_effect=[False, True]) as loaded):
    restored = game_launcher.restore_and_continue(
        ascension_game, core.ARCHIVE / "ascension.bo1checkpoint", "Solo")
assert ascension_game.commands == ["F12", "F12"]
assert "resume_warning" not in restored
assert map_ready.call_count == 1
map_ready.assert_called_with(ascension_game, "zombie_cosmodrome", None,
                                  during_opening=True, allow_stale_checkpoint=True)
assert loaded.call_args_list[1].kwargs["timeout"] == 20


failed_game = FreshGame()
with (patch.object(core, "load_archive", return_value=({
          "map": "zombie_cosmodrome", "round": 7}, {})),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore"),
      patch.object(core, "live_round", return_value=1),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=False)):
    try:
        game_launcher.restore_and_continue(
            failed_game, core.ARCHIVE / "ascension.bo1checkpoint", "Solo")
    except RuntimeError as error:
        assert "stayed at round 1" in str(error)
    else:
        raise AssertionError("A failed Ascension Continue must be reported")
assert failed_game.commands == ["F12", "F12"]

with (patch.object(core, "load_archive", return_value=({"map": "zombie_cosmodrome", "round": 7}, {})),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore"),
      patch.object(core, "live_round", return_value=None),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_map_ready"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=False)):
    try:
        game_launcher.restore_and_continue(FreshGame(), core.ARCHIVE / "unknown.bo1checkpoint", "Solo")
    except RuntimeError as error:
        assert "did not confirm" in str(error)
    else:
        raise AssertionError("An unconfirmed Continue must not arm the selected overwrite target")


class ContinueSignalGame:
    def __init__(self, state=3):
        self.frame = 100
        self.state = state

    def u32(self, address):
        if address == core.LEVEL_FRAME_ADDR:
            self.frame += 1
            return self.frame
        return {core.LEVEL_TIME_ADDR: 5000,
                core.MENU_ADDR: 0,
                core.COMMITTED_PTR: core.SAVE_A,
                core.SAVE_A + core.STATE_OFFSET: self.state}[address]


for observed_round, state in ((8, 3), (None, 4)):
    signal_game = ContinueSignalGame(state)
    ticks = itertools.count(0, 0.25)
    with (patch.object(core, "live_round", return_value=observed_round),
          patch.object(game_launcher.time, "monotonic", side_effect=lambda: next(ticks)),
          patch.object(game_launcher.time, "sleep")):
        assert game_launcher.wait_for_loaded_round(
            signal_game, 7, timeout=8, before_clock=(100, 5000))


class SwitchGame:
    pid = 4420

    def __init__(self):
        self.switched = False
        self.commands = []

    def u32(self, address):
        if address == core.PAUSED_ADDR:
            return 0
        if address == core.LEVEL_FRAME_ADDR:
            return 20 if self.switched else 1000
        if address == core.LEVEL_TIME_ADDR:
            return 1000 if self.switched else 50000
        raise KeyError(address)

    def press_switch(self):
        self.switched = True
        self.commands.append("F10")

    def close(self):
        pass


switch_game = SwitchGame()
with (patch.object(core, "game_pid", return_value=4420),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "prepare_script_variant") as prepare,
      patch.object(game_launcher, "wait_for_map_ready") as ready):
    game_launcher.switch_running_map(switch_game, "zombie_cod5_factory")
assert switch_game.commands == ["F10"]
prepare.assert_called_once_with(legacy=False, enhanced=False, round_bridge=False, map_state=False)
assert not (core.ROOT / "checkpoint_switch.cfg").exists()
assert not (core.ROOT / "mods" / "devcommands" / "checkpoint_switch.cfg").exists()
assert ready.call_args.kwargs == {"during_opening": True, "allow_stale_checkpoint": True}

with (patch.object(core, "load_archive", return_value=({"map": "zombie_cod5_factory"}, {})),
      patch.object(core, "game_pid", return_value=4420),
      patch.object(core, "GameProcess", return_value=switch_game),
      patch.object(core, "committed", side_effect=RuntimeError("No checkpoint")),
      patch.object(game_launcher, "switch_running_map") as switch,
      patch.object(game_launcher.subprocess, "Popen") as launch):
    same_process, metadata = game_launcher.start_selected_game(
        core.ARCHIVE / "sample.bo1checkpoint", "Solo")
assert same_process is switch_game and metadata["map"] == "zombie_cod5_factory"
switch.assert_called_once()
launch.assert_not_called()

with (patch.object(core, "load_archive", return_value=({"map": "zombie_cod5_factory"}, {})),
      patch.object(core, "game_pid", return_value=4420),
      patch.object(core, "GameProcess", return_value=switch_game),
      patch.object(core, "committed", return_value=(core.SAVE_A, b"", {"map": "zombie_cod5_factory"})),
      patch.object(core, "live_round", return_value=4),
      patch.object(switch_game, "u32", return_value=0xFFFFFFFF),
      patch.object(game_launcher, "switch_running_map") as switch):
    same_map, _ = game_launcher.start_selected_game(core.ARCHIVE / "sample.bo1checkpoint", "Solo")
assert same_map is switch_game
switch.assert_called_once_with(switch_game, "zombie_cod5_factory", None,
                               legacy=False, enhanced=False, round_bridge=False, map_state=False)

replacement_game = object()
with (patch.object(core, "load_archive", return_value=({"map": "zombie_cod5_factory"}, {})),
      patch.object(core, "game_pid", return_value=4420),
      patch.object(core, "GameProcess", return_value=switch_game),
      patch.object(game_launcher, "switch_running_map",
                   side_effect=game_launcher.GameProcessReplaced("restarted")),
      patch.object(game_launcher, "wait_for_replacement_game", return_value=replacement_game) as reconnect,
      patch.object(game_launcher, "wait_for_map_ready") as ready):
    new_game, _ = game_launcher.start_selected_game(
        core.ARCHIVE / "sample.bo1checkpoint", "Solo")
assert new_game is replacement_game
reconnect.assert_called_once_with(4420, None)
assert ready.call_args.kwargs == {"during_opening": True}

with (patch.object(core, "game_pid", return_value=4420),
      patch.object(core, "GameProcess", return_value=switch_game),
      patch.object(game_launcher, "switch_running_map") as switch,
      patch.object(game_launcher, "wait_for_map_ready") as ready):
    fresh_map = game_launcher.start_new_game("zombie_cod5_factory")
assert fresh_map is switch_game
switch.assert_called_once_with(switch_game, "zombie_cod5_factory", None,
                               legacy=False, enhanced=True, round_bridge=True, map_state=True)
assert ready.call_args.kwargs == {"during_opening": False, "allow_stale_checkpoint": True}

print("Launcher readiness and bound save/load keys passed")

for map_name in ('zombie_cosmodrome', 'zombie_moon', 'zombie_paris'):
    special = FakeGame()
    special.states = [(0, 1000 + i, 400 + i, 14000 + i * 1000)
                      for i in range(16)]
    with (patch.object(core, 'committed', side_effect=RuntimeError('No save yet')),
          patch.object(core, 'live_round', side_effect=lambda _: 1 if special.sample >= 10 else None),
          patch.object(game_launcher.time, 'sleep')):
        game_launcher.wait_for_map_ready(special, map_name, during_opening=False)
    assert special.sample >= 11, 'Special intro was bypassed by opening shortcut'
print('Ascension and Moon first-checkpoint readiness passed')

# Restore readiness must not wait for Ascension's intro or Moon's teleport.
for map_name in ('zombie_cosmodrome', 'zombie_moon', 'zombie_paris'):
    special = FakeGame()
    with (patch.object(core, 'committed', side_effect=RuntimeError('No save yet')),
          patch.object(core, 'live_round', return_value=None),
          patch.object(game_launcher.time, 'sleep')):
        game_launcher.wait_for_map_ready(special, map_name, during_opening=True)
    assert special.sample < 10
assert 'set scr_zm_extra_perk_all 1' in (core.ROOT / 'checkpoint.cfg').read_text()
print('Restore before first round and Mule Kick configuration passed')

# Saved Ascension uses early readiness; new-game readiness remains unchanged.
with (patch.object(core, "load_archive", return_value=({"map": "zombie_cosmodrome", "round": 4}, {})),
      patch.object(game_launcher, "wait_for_map_ready") as ready,
      patch.object(game_launcher, "make_fresh_checkpoint") as bootstrap,
      patch.object(core, "restore") as restore_mock,
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=True)):
    fresh_game.commands.clear()
    game_launcher.restore_and_continue(fresh_game, core.ARCHIVE / "ascension.bo1checkpoint", "Solo")
ready.assert_not_called()
bootstrap.assert_called_once()
assert restore_mock.call_args.kwargs["coop"] is True
assert restore_mock.call_args.kwargs["prepared_archive"][0]["map"] == "zombie_cosmodrome"
assert fresh_game.commands == ["F12"]
print("Ascension resumes at early map readiness and validates a current checkpoint")

# Restore the recorded film only after Continue has been confirmed.
import ascension_vision
for map_name in ("zombie_cosmodrome", "zombie_moon"):
    order=[]
    metadata={"map":map_name,"round":4,"ascension_vision":{"format":1}}
    with (patch.object(core,"load_archive",return_value=(metadata,{})),
          patch.object(game_launcher,"wait_for_map_ready"),
          patch.object(game_launcher,"make_fresh_checkpoint"),
          patch.object(core,"restore"),
          patch.object(game_launcher,"wait_for_focus"),
          patch.object(game_launcher,"wait_for_loaded_round",side_effect=lambda *a,**k:order.append("loaded") or True),
          patch.object(ascension_vision,"restore",side_effect=lambda *a:order.append("vision"))):
        game_launcher.restore_and_continue(fresh_game,core.ARCHIVE/"vision.bo1checkpoint","Solo")
    assert order == (["loaded","vision"] if map_name=="zombie_cosmodrome" else ["loaded"])
print("Ascension-only vision restoration occurs after confirmed Continue")

# Preparation must not be repeated while Ascension's intro is running.
path=core.ARCHIVE/"preloaded.bo1checkpoint"
metadata={"map":"zombie_cosmodrome","round":4}
pieces={"save.bin":b"validated archive"}
fresh_game._ascension_restore=(path.resolve(),metadata,pieces,False)
with (patch.object(core,"load_archive",side_effect=AssertionError("Late archive read")),
      patch.object(game_launcher,"prepare_restore_options",side_effect=AssertionError("Late option preparation")),
      patch.object(game_launcher,"wait_for_map_ready"),
      patch.object(game_launcher,"make_fresh_checkpoint"),
      patch.object(core,"restore") as restored,
      patch.object(game_launcher,"wait_for_focus"),
      patch.object(game_launcher,"wait_for_loaded_round",return_value=True)):
    game_launcher.restore_and_continue(fresh_game,path,"Solo")
assert restored.call_args.kwargs["prepared_archive"] == (metadata,pieces)
assert fresh_game._ascension_restore is None
print("Ascension consumes its preloaded archive without disk preparation during the intro")

order=[]
with (patch.object(core,"load_archive",return_value=(metadata,pieces)),
      patch.object(core,"validate_client_script"),
      patch.object(core,"game_pid",return_value=1),
      patch.object(core,"GameProcess",return_value=fresh_game),
      patch.object(game_launcher,"prepare_restore_options",side_effect=lambda *a:order.append("prepare") or False),
      patch.object(game_launcher,"switch_running_map",side_effect=lambda *a,**k:order.append("map"))):
    game_launcher.start_selected_game(path,"Solo")
assert order == ["prepare","map"]
print("Ascension preparation precedes the map switch")

# All three maps submit Continue immediately after the bootstrap/restore sequence.
for map_name in ("zombie_cod5_factory", "zombie_cosmodrome", "zombie_moon"):
    events=[]
    with (patch.object(core,"load_archive",return_value=({"map":map_name,"round":4},{})),
          patch.object(game_launcher,"prepare_restore_options",return_value=False),
          patch.object(game_launcher,"wait_for_map_ready") as ready,
          patch.object(game_launcher,"make_fresh_checkpoint",side_effect=lambda *a:events.append("checkpoint")),
          patch.object(core,"restore",side_effect=lambda *a,**k:events.append("restore")),
          patch.object(game_launcher,"wait_for_focus"),
          patch.object(game_launcher,"wait_for_loaded_round",return_value=True),
          patch.object(fresh_game,"press_load",side_effect=lambda:events.append("continue"))):
        game_launcher.restore_and_continue(fresh_game,core.ARCHIVE/"timing.bo1checkpoint","Solo")
    ready.assert_not_called()
    assert events == ["checkpoint","restore","continue"]
print("Der Riese, Ascension and Moon share the immediate restore sequence")

# Moon applies the overlay at Continue and after renderer reset, never other maps.
import moon_gasmask
for map_name in ("zombie_moon", "zombie_cosmodrome"):
    events=[]
    metadata={"map":map_name,"round":2,"moon_gasmask":{"format":1,"map":"zombie_moon","worn":True}}
    with (patch.object(core,"load_archive",return_value=(metadata,{})),
          patch.object(game_launcher,"prepare_restore_options",return_value=False),
          patch.object(game_launcher,"make_fresh_checkpoint"),
          patch.object(core,"restore"),patch.object(game_launcher,"wait_for_focus"),
          patch.object(game_launcher,"wait_for_loaded_round",return_value=True),
          patch.object(moon_gasmask,"restore",side_effect=lambda *a:events.append("mask")),
          patch.object(fresh_game,"press_load",side_effect=lambda:events.append("continue"))):
        game_launcher.restore_and_continue(fresh_game,core.ARCHIVE/"mask.bo1checkpoint","Solo")
    assert events == (["mask","continue","mask"] if map_name=="zombie_moon" else ["continue"])
print("Moon overlay restoration brackets Continue without affecting other maps")

# Round-one Moon restores client rendering before the normal confirmation delay.
from unittest.mock import Mock
clock=[0.0]
frames=[0]
def read_resume(address):
    if address == core.LEVEL_FRAME_ADDR:
        frames[0]+=1
        return frames[0]
    if address == core.LEVEL_TIME_ADDR: return frames[0]*50
    if address == core.MENU_ADDR: return 0
    if address == core.COMMITTED_PTR: return next(iter(core.BUFFERS))
    if address == next(iter(core.BUFFERS))+core.STATE_OFFSET: return 4 if frames[0]==1 else 3
    return 0
applied=[]
def apply_overlay():
    applied.append(clock[0])
    return len(applied)>1 # first resumed frame can precede material initialization
with (patch.object(game_launcher.time,"monotonic",side_effect=lambda:clock[0]),
      patch.object(game_launcher.time,"sleep",side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)),
      patch.object(core,"live_round",return_value=1)):
    assert game_launcher.wait_for_loaded_round(Mock(u32=read_resume),1,
        before_clock=(100,5000),on_resume=apply_overlay)
assert len(applied)==2 and applied[-1]<0.1
assert clock[0]>=1.5
print("Round-one overlay retries on resumed frames before load confirmation")

# A vision-only Moon save also enables first-frame restoration (no P.E.S. required).
import moon_vision
metadata={"map":"zombie_moon","round":0,"moon_vision":{"format":1}}
with (patch.object(core,"load_archive",return_value=(metadata,{})),
      patch.object(game_launcher,"prepare_restore_options",return_value=False),
      patch.object(game_launcher,"make_fresh_checkpoint"),patch.object(core,"restore"),
      patch.object(game_launcher,"wait_for_focus"),
      patch.object(game_launcher,"wait_for_loaded_round",return_value=True) as waited,
      patch.object(moon_vision,"restore") as vision,
      patch.object(moon_gasmask,"restore") as mask):
    game_launcher.restore_and_continue(fresh_game,core.ARCHIVE/"nml.bo1checkpoint","Solo")
    assert callable(waited.call_args.kwargs["on_resume"])
    assert vision.call_count==2
    mask.assert_not_called()
print("Moon round-zero vision loads independently of gas-mask state")
