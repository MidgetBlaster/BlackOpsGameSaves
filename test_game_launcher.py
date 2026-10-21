from unittest.mock import patch
import ctypes
from pathlib import Path
from tempfile import TemporaryDirectory

import checkpoint_memory as core
import game_launcher


command, directory = game_launcher.launch_command("zombie_cod5_factory")
assert directory.name == "bin"
assert command[1:3] == ["game_mod.dll", "../BlackOps.exe"]
assert command[-2:] == ["+devmap", "zombie_cod5_factory"]
assert command[3:6] == ["+set", "fs_game", f"mods/{core.ROOT.name}"]
assert command[6:9] == ["+set", "scr_useFastFileOnly", "0"]
assert command[9:11] == ["+exec", "checkpoint.cfg"]
assert 'bind F10 "exec checkpoint_switch.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert 'bind F7 "exec checkpoint_borderless.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert 'bind F6 "exec checkpoint_fullscreen.cfg"' in (core.ROOT / "checkpoint.cfg").read_text()
assert "r_fullscreen 0\nvid_restart" in (core.ROOT / "checkpoint_borderless.cfg").read_text()
assert "r_fullscreen 1\nvid_restart" in (core.ROOT / "checkpoint_fullscreen.cfg").read_text()
assert game_launcher.legacy_scripts({"script_checksums": [1547989158, 617289, 624409]})
assert not game_launcher.legacy_scripts({"script_checksums": [1, 2, 3]})
with TemporaryDirectory(dir=core.ROOT) as directory:
    folder = Path(directory)
    variant_dir = folder / "variants"
    variant_dir.mkdir()
    (variant_dir / "_zombiemode_legacy.gsc").write_bytes(b"original script")
    (variant_dir / "_zombiemode_pause.gsc").write_bytes(b"pause script")
    active_script = folder / "_zombiemode.gsc"
    active_script.write_bytes(b"pause script")
    with (patch.object(game_launcher, "SCRIPT_SOURCE", active_script),
          patch.object(game_launcher, "SCRIPT_VARIANTS", variant_dir)):
        game_launcher.prepare_script_variant(legacy=True)
        assert active_script.read_bytes() == b"original script"
        game_launcher.prepare_script_variant(legacy=False)
        assert active_script.read_bytes() == b"pause script"
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
                core.WRITE_PTR: core.SAVE_B}[address]

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

with (patch.object(core, "load_archive", return_value=({"map": "zombie_cod5_factory"}, {})),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore") as restore_mock,
      patch.object(game_launcher, "wait_for_focus")):
    game_launcher.restore_and_continue(fresh_game, core.ARCHIVE / "sample.bo1checkpoint", "Solo")
assert fresh_game.commands[-1] == "F12"
assert restore_mock.call_args.kwargs == {"coop": True}

with (patch.object(core, "load_archive", return_value=({"map": "zombie_cod5_factory", "round": 4}, {})),
      patch.object(game_launcher, "make_fresh_checkpoint"),
      patch.object(core, "restore"),
      patch.object(game_launcher, "wait_for_focus"),
      patch.object(game_launcher, "wait_for_loaded_round", return_value=True) as loaded):
    game_launcher.restore_and_continue(fresh_game, core.ARCHIVE / "sample.bo1checkpoint", "Solo")
loaded.assert_called_once_with(fresh_game, 4, None)


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
prepare.assert_called_once_with(legacy=False)
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
switch.assert_called_once_with(switch_game, "zombie_cod5_factory", None, legacy=False)

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
switch.assert_called_once_with(switch_game, "zombie_cod5_factory", None, legacy=False)
assert ready.call_args.kwargs == {"during_opening": False, "allow_stale_checkpoint": True}

print("Launcher readiness and bound save/load keys passed")
