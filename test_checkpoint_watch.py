"""Exercise automatic round capture alongside a player's F11 checkpoint."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import checkpoint_memory as core


class FakeGame:
    def __init__(self):
        self.round = 4
        self.round_change = False
        self.magic = 1000
        self.save_id = 1
        self.frame = 100
        self.level_time = 5000
        self.closed = False

    def u32(self, address):
        return {core.SCENE_ADDR: 204, core.MENU_ADDR: 0,
                core.TIMER_ADDR: 300, core.MAGIC_ADDR: self.magic,
                core.SAVE_QUEUE_COUNT: 0, core.ASYNC_DISK_SAVE: 0,
                core.LEVEL_FRAME_ADDR: self.frame,
                core.LEVEL_TIME_ADDR: self.level_time}[address]

    def foreground(self):
        return True

    def read(self, address, size):
        assert (address, size) == (core.ROUND_CHANGE_ADDR, 1)
        return bytes([int(self.round_change)])

    def close(self):
        self.closed = True


def exercise(player_f11, skip_initial_round=None, manual_tick=1,
             advance_round=True, advance_again=False, round_end_tick=None,
             missing_round=False, magic_transition=False, start_round=None,
             manual_continue=False, save_timing="End of Rounds",
             initial_round=4, transition_byte=1, advance_after_manual=False,
             manual_failure=False, auto_failures=0, scene=204,
             resume_archive_round=2, reload_ticks=(2,), first_round_tick=None, restart=False, lose_round_after_manual=False, rounds=None):
    game = FakeGame()
    game.round = initial_round
    clock = [0.0]
    events = []

    class Stop:
        ticks = 0

        def is_set(self):
            if rounds is not None:
                return self.ticks >= 18
            return self.ticks >= (8 if manual_continue and
                                 save_timing != "End of Rounds" else 7)

        def wait(self, _seconds):
            self.ticks += 1
            clock[0] += 3
            game.frame += 60
            game.level_time += 3000
            if manual_continue and self.ticks in reload_ticks:
                game.frame = 10
                game.level_time = 500
                game.round = 0
                if not restart:
                    game.save_id = 2
                else:
                    game.round = 1 if scene != 76 else 0
            if manual_continue and self.ticks == 5:
                game.round_change = True
            if manual_continue and self.ticks == 6:
                game.round_change = False
            if player_f11 and self.ticks in (manual_tick if isinstance(manual_tick, tuple) else (manual_tick,)):
                game.save_id += 1
                if lose_round_after_manual:
                    game.round = 0
            if advance_round and (not player_f11 or advance_after_manual) and self.ticks == 3:
                game.round = initial_round + 1
            if advance_again and self.ticks == 5:
                game.round = 6
            if round_end_tick == self.ticks:
                game.round_change = transition_byte
            if rounds and self.ticks in rounds:
                game.round = rounds[self.ticks]
            if self.ticks == first_round_tick:
                game.round = 1
            if magic_transition and self.ticks == 2:
                game.magic = 2000
            if magic_transition and self.ticks == 3:
                game.magic = 500

    attempts = [0]
    def save(_game, number):
        attempts[0] += 1
        if attempts[0] <= auto_failures:
            raise core.CheckpointNotCommitted("Simulated delayed engine commit")
        game.save_id += 1
        return Path(f"round-{number}.bo1checkpoint")

    def manual_snapshot(_game, number):
        if manual_failure:
            raise OSError("Simulated manual archive error")
        return Path(f"player-{number}.bo1checkpoint")

    with TemporaryDirectory(dir=core.ROOT) as directory:
        with (patch.object(core, "game_pid", return_value=4420),
              patch.object(core, "GameProcess", return_value=game),
              patch.object(core, "live_round", side_effect=lambda _game:
                           None if missing_round or game.round <= 0 else game.round),
              patch.object(core, "effective_scene", return_value=(scene, None)),
              patch.object(core, "archived_round_for_header",
                           side_effect=lambda *_: resume_archive_round if manual_continue else None),
              patch.object(core, "committed", side_effect=lambda _game: (
                  core.SAVE_A, b"", {"map": "zombie_cod5_factory", "save_id": game.save_id})),
              patch.object(core, "snapshot", side_effect=manual_snapshot),
              patch.object(core, "request_and_save", side_effect=save),
              patch.object(core.time, "monotonic", side_effect=lambda: clock[0]),
              patch.object(core, "RECOVERY_FILE", Path(directory) / "latest.bo1checkpoint")):
            core.watch(start_round=start_round, stop_event=Stop(),
                       on_event=lambda *event: events.append(event),
                       skip_initial_round=skip_initial_round, enable_recovery=False,
                       save_timing=save_timing)
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

missing_round_auto = exercise(player_f11=False, skip_initial_round=5,
                              advance_round=False, missing_round=True,
                              magic_transition=True, start_round=5)
assert captures(missing_round_auto) == [("saved", 5)]
missing_round_manual = exercise(player_f11=True, skip_initial_round=5,
                                advance_round=False, missing_round=True,
                                manual_tick=4, start_round=5)
assert captures(missing_round_manual) == [("manual", 5)]

manually_resumed = exercise(player_f11=False, advance_round=False,
                             start_round=4, manual_continue=True)
assert captures(manually_resumed) == [("saved", 2)]
assert captures(exercise(player_f11=False, advance_round=False, start_round=4,
                         manual_continue=True,
                         save_timing="Round Transitions")) == [("saved", 3)]
assert captures(exercise(player_f11=False, advance_round=False, start_round=4,
                         manual_continue=True,
                         save_timing="Start of Round")) == [("saved", 3)]


tracker = core.RoundEndTracker()
assert tracker.update(204, 0, 300, 4, False, 0) is None
assert tracker.update(204, 0, 301, 4, False, 6) is None
assert tracker.update(204, 0, 302, 4, True, 7) is None
assert tracker.update(204, 0, 303, 4, True, 7.2) == (4, 4, "round end")

transition = core.RoundEndTracker("Round Transitions")
assert transition.update(204, 0, 300, 4, False, 0) is None
assert transition.update(204, 0, 301, 4, False, 6) is None
assert transition.update(204, 0, 302, 4, True, 7) is None
assert transition.update(204, 0, 303, 4, True, 7.5) is None
assert transition.update(204, 0, 304, 4, True, 7.8) is None
assert transition.update(204, 0, 305, 5, False, 10) is None
assert transition.update(204, 0, 306, 5, False, 10.2) == (5, 4, "round transition flag")

round_start = core.RoundEndTracker("Start of Round")
assert round_start.update(204, 0, 300, 4, False, 0) is None
assert round_start.update(204, 0, 301, 4, False, 6) is None
assert round_start.update(204, 0, 302, 4, True, 7) is None
assert round_start.update(204, 0, 303, 5, True, 8) is None
assert round_start.update(204, 0, 304, 5, True, 9) is None
assert round_start.update(204, 0, 305, 5, False, 10) is None
assert round_start.update(204, 0, 306, 5, False, 10.5) == (5, 4, "round start flag")
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

restored_zero_round = core.RoundEndTracker("End of Rounds", 5)
assert restored_zero_round.update(204, 0, 300, None, True, 0) is None
assert restored_zero_round.update(204, 0, 301, None, False, 1) is None
assert restored_zero_round.update(204, 0, 302, None, False, 7) is None
assert restored_zero_round.update(204, 0, 303, None, True, 8) is None
assert restored_zero_round.update(204, 0, 304, None, True, 8.2) == (5, 5, "round end")
restored_zero_round.mark_saved(5)
assert restored_zero_round.update(204, 0, 305, None, False, 10) is None
assert restored_zero_round.round == 6

retry_after_transition = core.RoundEndTracker("End of Rounds", 5)
assert retry_after_transition.update(204, 0, 300, None, False, 0) is None
assert retry_after_transition.update(204, 0, 301, None, False, 6) is None
assert retry_after_transition.update(204, 0, 302, None, True, 7) is None
assert retry_after_transition.update(204, 0, 303, None, True, 7.2) == (5, 5, "round end")
retry_after_transition.defer(7.2)
assert retry_after_transition.update(204, 0, 304, None, False, 8) is None
assert retry_after_transition.round == 6
assert retry_after_transition.update(204, 0, 305, None, False, 9.3) == (5, 5, "round end")

restored_start = core.RoundEndTracker("Start of Round", 5)
assert restored_start.update(204, 0, 300, None, True, 0) is None
assert restored_start.update(204, 0, 301, None, False, 1) is None
assert restored_start.update(204, 0, 302, None, False, 7) is None
assert restored_start.update(204, 0, 303, None, True, 8) is None
assert restored_start.update(204, 0, 304, None, False, 9) is None
assert restored_start.update(204, 0, 305, None, False, 9.5) == (6, 5, "round start flag")

reload = core.LevelReloadTracker()
assert not reload.update(100, 5000)
assert not reload.update(160, 8000)
assert reload.update(20, 1000)
assert not reload.update(30, 1500)

print("Automatic rounds and player F11 capture passed")

# Special map openings do not use the ordinary early-black-screen shortcut.
for scene in (20, 76):
    assert not core.opening_round_ready(scene, 60000, None)
assert not core.opening_round_ready(20, 14999, 1)
assert core.opening_round_ready(20, 15000, 1)
assert core.opening_round_ready(76, 60000, 1)
assert core.opening_round_ready(204, 100, None)
assert core.MAP_SCENES['zombie_paris'] == core.MAP_SCENES['zombie_moon']

reload = core.LevelReloadTracker()
assert not reload.update(100, 5000, 0)
assert not reload.update(120, 6000, 1)
assert reload.update(500, 25000, 2)  # manual Continue to a later checkpoint
assert not reload.update(520, 26000, 3)
assert reload.update(521, 26050, 3.1, reading=True)
assert not reload.update(521, 26050, 3.2, reading=True)
assert not reload.update(522, 26100, 3.3)
assert reload.update(10, 500, 4)  # earlier checkpoint

# A queued manual request is awaited rather than adding another F11 request.
from unittest.mock import Mock
queued = Mock()
queued.u32.return_value = 1
with patch.object(core, 'wait_for_new_save') as wait:
    core.request_fresh_checkpoint(queued, 4)
    queued.press_save.assert_not_called()
    wait.assert_called_once()

# Queue repair must still run when the committed buffer is transiently absent.
with (patch.object(core, 'committed', side_effect=[RuntimeError('loading'),
        (core.SAVE_A, b'', {'save_id': 5})]),
      patch.object(core, 'SaveQueueUnblocker') as recovery,
      patch.object(core.time, 'sleep')):
    recovery.return_value.observe.return_value = False
    core.wait_for_new_save(queued, 4)
    assert recovery.return_value.observe.call_count == 2
print('Special openings, bidirectional Continue and queued manual saves passed')

# A player-created round-one save must not mark that round's automatic
# boundary as completed, regardless of the selected timing policy.
for timing in core.SAVE_TIMINGS:
    events = exercise(player_f11=True, initial_round=1,
                      advance_after_manual=True, save_timing=timing)
    assert captures(events) == [('manual', 1), ('saved', 2)], (timing, events)
assert captures(exercise(player_f11=True, initial_round=1,
                         advance_round=False, round_end_tick=3,
                         transition_byte=255)) == [('manual', 1), ('saved', 1)]
print('Round-one manual save followed by automatic save passed')

# F11 arrives on the tick when a delayed fallback boundary becomes due.
# Missing round bytes reproduce the post-Continue path that formerly lost it.
for timing in core.SAVE_TIMINGS:
    events = exercise(True, manual_tick=4, advance_round=False,
                      missing_round=True, magic_transition=True, start_round=5,
                      save_timing=timing)
    expected = 6 if timing == "Start of Round" else 5
    assert captures(events) == [("manual", 5), ("saved", expected)], (timing, events)
    # A disk error from manual capture must not prevent the due automatic save.
    events = exercise(True, manual_tick=4, advance_round=False,
                      missing_round=True, magic_transition=True, start_round=5,
                      save_timing=timing, manual_failure=True)
    assert captures(events) == [("saved", expected)], (timing, events)
    assert any(e[0] == "error" and "Manual" in e[1] for e in events)
    # The round edge is one-shot: retain its request through a failed commit.
    events = exercise(True, manual_tick=5, advance_round=False,
                      missing_round=True, magic_transition=True, start_round=5,
                      save_timing=timing, auto_failures=1)
    assert captures(events) == [("manual", 6), ("saved", expected)], (timing, events)
print("Pending autosaves survive manual captures, manual errors and delayed commits")

# Moon has a playable round-zero opening. F11 never consumes its round-one event.
for timing in core.SAVE_TIMINGS:
    events = exercise(True, scene=76, initial_round=0, manual_tick=1,
                      advance_after_manual=True, save_timing=timing)
    assert captures(events) == [("manual", 0), ("saved", 1)], (timing, events)
    events = exercise(True, scene=76, initial_round=0, manual_tick=4,
                      advance_after_manual=True, save_timing=timing, auto_failures=1)
    assert captures(events) == [("manual", 1), ("saved", 1)], (timing, events)
    events = exercise(True, scene=76, initial_round=0, advance_round=False,
                      manual_tick=4, save_timing=timing)
    assert captures(events) == [("manual", 0)], (timing, events)
    events = exercise(False, scene=76, initial_round=1, skip_initial_round=1,
                      advance_round=False, save_timing=timing)
    assert captures(events) == [], (timing, events)
print("Moon round-zero manual saves preserve the independent round-one autosave")

for timing in core.SAVE_TIMINGS:
    events = exercise(True, scene=76, initial_round=0, advance_round=False,
                      manual_tick=(1,3,5), manual_continue=True,
                      resume_archive_round=0, reload_ticks=(2,4),
                      first_round_tick=6, save_timing=timing)
    assert captures(events) == [("manual",0),("manual",0),("manual",0),("saved",1)], (timing, events)
print("Repeated Moon pre-round Continue/F11 cycles still trigger exactly one round-one autosave")

# Restart keeps a stale committed checkpoint from round nine in memory.
# Both commands must label subsequent manual/automatic saves from the new round.
for command in ("map_restart", "fast_restart"):
    events = exercise(True, initial_round=9, start_round=9,
                      manual_continue=True, restart=True, manual_tick=3,
                      advance_round=False, resume_archive_round=9)
    assert captures(events) == [("manual", 1), ("saved", 1)], (command, captures(events))
    events = exercise(True, initial_round=9, start_round=9, scene=76,
                      manual_continue=True, restart=True, manual_tick=3,
                      advance_round=False, resume_archive_round=9, first_round_tick=4)
    assert captures(events)[0:2] == [("manual", 0), ("saved", 1)], captures(events)
print("Restart discards stale archive rounds and rearms autosaving, including Moon")

# A fresh session has no start/skip baseline. Its first manual save can
# invalidate the HUD byte; the magic fallback must still save the next boundary.
for timing in core.SAVE_TIMINGS:
    events = exercise(True, initial_round=1, advance_round=False,
                      lose_round_after_manual=True, magic_transition=True,
                      save_timing=timing)
    expected = 2 if timing == "Start of Round" else 1
    assert captures(events) == [("manual", 1), ("saved", expected)], captures(events)
print("First manual save losing the round byte does not disable autosaving")

for timing in core.SAVE_TIMINGS:
    events = exercise(True, initial_round=1, advance_round=False,
                      manual_tick=(1, 6, 11), rounds={3:2, 8:3, 13:4},
                      save_timing=timing)
    assert captures(events) == [("manual",1),("saved",2),("manual",2),
                                ("saved",3),("manual",3),("saved",4)], captures(events)
print("Three consecutive rounds autosave with manual saves between every boundary")
