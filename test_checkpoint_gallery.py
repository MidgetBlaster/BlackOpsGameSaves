"""Check the mission-select layout and its three-save preview."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import checkpoint_gui as gui
import tkinter.font as tkfont


def test_recent_saves():
    base = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
    entries = {
        f"kino-{round_number}": {
            "map": "zombie_theater", "round": round_number,
            "saved_at": (base + timedelta(minutes=round_number)).isoformat(),
            "title": f"Save Game {round_number}", "favorite": False,
            "profile_id": "imported", "saved_mode": "Solo",
        }
        for round_number in range(1, 5)
    }
    entries["riese"] = {"map": "zombie_cod5_factory", "round": 9,
                        "saved_at": base.isoformat(), "title": "Other map",
                        "favorite": False, "profile_id": "imported"}
    entries["kino-4"]["players"] = [{"name": "Test Player", "points": 1200,
                                      "kills": 9, "downs": 0, "revives": 1,
                                      "weapons": "M1911"}]
    assert [name for name, _ in gui.recent_map_saves(entries, "zombie_theater", "All saves")] == [
        "kino-4", "kino-3", "kino-2"]
    imported = dict(entries)
    imported["kino-offset"] = {
        "map": "zombie_theater", "saved_at": "2026-10-22T08:05:00-04:00",
        "imported": True,
    }
    assert [name for name, _ in gui.recent_map_saves(imported, "zombie_theater", "All saves")] == [
        "kino-offset", "kino-4", "kino-3"]

    class Library:
        def __init__(self):
            self.data = {"saves": entries, "profiles": [{"id": "imported", "title": "Imported",
                                                            "mode": "Unknown"}],
                         "active_profile": "imported"}

        def scan(self):
            pass

        def profiles(self):
            return self.data["profiles"]

    with (patch.object(gui, "SaveLibrary", Library),
          patch.object(gui.core, "promote_recovery", return_value=None),
          patch.object(gui.core, "game_pid", return_value=1),
          patch.object(gui.CheckpointApp, "_start_watch"),
          patch.object(gui.CheckpointApp, "_fov_loop")):
        app = gui.CheckpointApp()
        try:
            app.update()
            assert tkfont.Font(root=app, family=gui.FONT_FAMILY,
                               size=12).actual("family") == gui.FONT_FAMILY
            assert "Backspeed/strafe fix" in app.speed_button.cget("text")
            assert app.speed_button.cget("fg") == "#6dda82"
            assert app.gallery_selected_map == "zombie_theater"
            assert len(app.gallery_rows) == len(gui.MAP_ART)
            canvas = app.gallery_canvas
            assert not app.heading.winfo_manager()
            assert canvas.bbox("gallery-map-10")[3] <= canvas.winfo_height()
            assert canvas.bbox("gallery-save-2")[3] <= canvas.winfo_height(), (
                canvas.bbox("gallery-save-2"), canvas.winfo_height())
            assert canvas.bbox("gallery-page-next")[3] <= canvas.winfo_height()
            assert canvas.bbox("gallery-action-continue")[3] <= canvas.winfo_height()
            assert app.map_images["preview:zombie_theater"].width() == 256
            assert app.map_images["preview:zombie_theater"].height() == 256
            app.geometry("1010x700")
            app.update()
            assert canvas.bbox("gallery-map-10")[3] <= canvas.winfo_height()
            assert canvas.bbox("gallery-save-2")[3] <= canvas.winfo_height(), (
                canvas.bbox("gallery-save-2"), canvas.winfo_height())
            assert app.map_images["compact:zombie_theater"].width() == 205
            assert app.map_images["compact:zombie_theater"].height() == 205
            assert canvas.bbox("gallery-preview")[3] <= canvas.winfo_height()
            assert canvas.bbox("gallery-page-next")[3] <= canvas.winfo_height()
            assert not canvas.cget("scrollregion")
            assert not canvas.bind("<MouseWheel>")
            texts = [canvas.itemcget(item, "text") for item in canvas.find_all()
                     if canvas.type(item) == "text"]
            assert any(text.startswith("4 SAVES TOTAL") for text in texts)
            assert "MISSION SELECT" in texts
            assert all(f"Save Game {number}" in texts for number in (2, 3, 4))
            assert "Save Game 1" not in texts
            assert "RECENT SAVES" not in texts
            assert "1/2" in texts
            assert len(app.gallery_visible_saves) == 3
            assert app.gallery_canvas.tag_bind("gallery-map-6", "<Enter>")
            rectangle, title = app.gallery_rows["zombie_theater"]
            assert canvas.itemcget(rectangle, "fill") == "#f5f4f1"
            assert canvas.itemcget(title, "fill") == "#0d0d0d"
            app._change_gallery_page(1)
            assert app.gallery_page_index == 1
            assert len(app.gallery_visible_saves) == 1
            app._select_gallery_save(app.gallery_visible_saves[0])
            assert len(app.selected_names()) == 1
            with patch.object(app, "start_selected_game") as start:
                app.continue_latest_game()
                assert app.selected_name() == "kino-4"
                start.assert_called_once_with()
            texts = [canvas.itemcget(item, "text") for item in canvas.find_all()
                     if canvas.type(item) == "text"]
            assert "PLAYER STATS" in texts
            assert "Test Player" in texts
            app.started_save_name = "kino-3"
            app.save_policy.set("Replace started save")
            checkpoint = Path("new-auto.bo1checkpoint")
            with patch.object(app.library, "replace_save", create=True,
                              return_value=entries["kino-4"]) as replace:
                app.events.put(("saved", checkpoint, "auto", "imported", None))
                app._poll_events()
                replace.assert_called_once_with(checkpoint, "kino-4")
            app._select_gallery_map("zombie_cod5_factory")
            rectangle, title = app.gallery_rows["zombie_cod5_factory"]
            assert canvas.itemcget(rectangle, "fill") == "#f5f4f1"
            assert canvas.itemcget(title, "fill") == "#0d0d0d"
            app.show_map("zombie_cod5_factory")
            assert not app.heading.winfo_manager()
            assert app.current_map is None
            assert app.gallery_selected_map == "zombie_cod5_factory"
            app.show_gallery()
            assert app.heading_title.cget("text") == "MISSION SELECT"
            assert app.gallery_page.winfo_manager() == "pack"
            assert not app.saves_page.winfo_manager()
        finally:
            app.destroy()


def test_speed_fix_remembers_off():
    class Library:
        catalog = {"saves": {}, "profiles": [], "active_profile": None}

        def __init__(self):
            self.data = self.catalog

        def scan(self):
            pass

        def profiles(self):
            return []

        def write(self):
            pass

    with TemporaryDirectory(dir=Path(__file__).parent) as directory:
        with (patch.object(gui, "SaveLibrary", Library),
              patch.object(gui.core, "ROOT", Path(directory)),
              patch.object(gui.core, "promote_recovery", return_value=None),
              patch.object(gui.core, "game_pid", return_value=None),
              patch.object(gui.game_launcher, "prepare_script_variant"),
              patch.object(gui.CheckpointApp, "_start_watch"),
              patch.object(gui.CheckpointApp, "_fov_loop")):
            first = gui.CheckpointApp()
            try:
                assert first.speed_fix_enabled
                assert (Path(directory) / "checkpoint_speed.cfg").read_text() == (
                    "set checkpoint_speed_fix 1\n")
                first.toggle_speed_fix()
                assert first.library.data["speed_fix_enabled"] is False
            finally:
                first.destroy()
            reopened = gui.CheckpointApp()
            try:
                assert not reopened.speed_fix_enabled
                assert reopened.speed_button.cget("fg") == "#f07575"
                assert (Path(directory) / "checkpoint_speed.cfg").read_text() == (
                    "set checkpoint_speed_fix 0\n")
            finally:
                reopened.destroy()


if __name__ == "__main__":
    test_recent_saves()
    test_speed_fix_remembers_off()
    print("Mission-select layout and recent saves passed")
