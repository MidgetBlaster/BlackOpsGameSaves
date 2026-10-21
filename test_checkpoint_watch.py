"""Exercise automatic round capture alongside a player's F11 checkpoint."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import checkpoint_memory as core


class FakeGame:
    def __init__(self):
        self.round = 4
        self.round_change = False
        self.save_id = 1
        self.closed = False

    def u32(self, address):
        return {core.SCENE_ADDR: 204, core.MENU_ADDR: 0,
                core.TIMER_ADDR: 300, core.MAGIC_ADDR: 1000}[address]

    def foreground(self):
        return True

    def read(self, address, size):
        assert (address, size) == (core.ROUND_CHANGE_ADDR, 1)
        return bytes([int(self.round_change)])

    def close(self):
        self.closed = True


def exercise(player_f11, skip_initial_round=None, manual_tick=1,
             advance_round=True, advance_again=False, round_end_tick=None):
    game = FakeGame()
    clock = [0.0]
    events = []

    class Stop:
        ticks = 0

        def is_set(self):
            return self.ticks >= 7

        def wait(self, _seconds):
            self.ticks += 1
            clock[0] += 3
            if player_f11 and self.ticks == manual_tick:
                game.save_id += 1
            if advance_round and not player_f11 and self.ticks == 3:
                game.round = 5
            if advance_again and self.ticks == 5:
                game.round = 6
            if round_end_tick == self.ticks:
                game.round_change = True

    def save(_game, number):
        game.save_id += 1
        return Path(f"round-{number}.bo1checkpoint")

    def manual_snapshot(_game, number):
        return Path(f"player-{number}.bo1checkpoint")

    with TemporaryDirectory(dir=core.ROOT) as directory:
        with (patch.object(core, "game_pid", return_value=4420),
              patch.object(core, "GameProcess", return_value=game),
              patch.object(core, "live_round", side_effect=lambda _game: game.round),
              patch.object(core, "effective_scene", return_value=(204, None)),
              patch.object(core, "committed", side_effect=lambda _game: (
                  core.SAVE_A, b"", {"map": "zombie_cod5_factory", "save_id": game.save_id})),
              patch.object(core, "snapshot", side_effect=manual_snapshot),
              patch.object(core, "request_and_save", side_effect=save),
              patch.object(core.time, "monotonic", side_effect=lambda: clock[0]),
              patch.object(core, "RECOVERY_FILE", Path(directory) / "latest.bo1checkpoint")):
            core.watch(stop_event=Stop(), on_event=lambda *event: events.append(event),
                       skip_initial_round=skip_initial_round, enable_recovery=False)
    assert game.closed
    return events


def captures(events):
    return [(kind, number) for kind, number, _ in events
            if kind in ("saved", "manual", "recovery")]


manual_events = exercise(player_f11=True)
assert captures(manual_events) == [("manual", 4)]

auto_events = exercise(player_f11=False)
assert captures(auto_events) == [("saved", 5)]

round_end_events = exercise(player_f11=False, advance_round=False,
                            round_end_tick=3)
assert captures(round_end_events) == [("saved", 4)]
assert ("round_end", 4, None) in round_end_events

assert captures(exercise(player_f11=False, advance_round=False)) == []
assert captures(exercise(player_f11=False, skip_initial_round=4,
                         advance_round=False)) == []

resumed_events = exercise(player_f11=False, skip_initial_round=4)
assert captures(resumed_events) == [("saved", 5)]

off_by_one_resume = exercise(player_f11=False, skip_initial_round=5,
                             advance_again=True)
assert captures(off_by_one_resume) == [("saved", 6)]

opening_transition = exercise(player_f11=True, skip_initial_round=4)
assert captures(opening_transition) == []

later_manual = exercise(player_f11=True, skip_initial_round=4, manual_tick=4)
assert captures(later_manual) == [("manual", 4)]


tracker = core.RoundEndTracker()
assert tracker.update(204, 0, 300, 4, False, 0) is None
assert tracker.update(204, 0, 301, 4, False, 6) is None
assert tracker.update(204, 0, 302, 4, True, 7) is None
assert tracker.update(204, 0, 303, 4, True, 7.2) == (4, 4, "round end")
tracker.mark_saved(4)
assert tracker.update(204, 0, 304, 4, False, 10) is None
assert tracker.update(204, 0, 305, 5, False, 11) is None
assert tracker.update(204, 0, 306, 5, True, 12) is None
assert tracker.update(204, 0, 307, 5, False, 14) is None
assert tracker.update(204, 0, 308, 5, False, 20) is None
assert tracker.update(204, 0, 309, 5, True, 21) is None
assert tracker.update(204, 0, 310, 5, True, 21.2) == (5, 5, "round end")

counter_fallback = core.RoundEndTracker()
assert counter_fallback.update(204, 0, 300, 4, False, 0) is None
assert counter_fallback.update(204, 0, 301, 5, False, 10) is None
assert counter_fallback.update(204, 0, 302, 5, False, 10.5) == (5, 4, "round counter")

edge_and_counter = core.RoundEndTracker()
assert edge_and_counter.update(204, 0, 300, 4, False, 0) is None
assert edge_and_counter.update(204, 0, 301, 5, True, 8) is None
assert edge_and_counter.update(204, 0, 302, 5, True, 8.2) == (5, 4, "round end")
edge_and_counter.mark_saved(4)
assert edge_and_counter.update(204, 0, 303, 5, False, 11) is None

load_jump = core.RoundEndTracker()
assert load_jump.update(204, 0, 300, 1, False, 0) is None
assert load_jump.update(204, 0, 301, 4, False, 10) is None
assert load_jump.update(204, 0, 302, 4, False, 11) is None

print("Automatic rounds and player F11 capture passed")
