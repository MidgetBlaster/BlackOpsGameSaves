import json
from pathlib import Path
import tempfile
import zipfile

import save_library as lib


with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
    archive = Path(directory)
    original_archive = lib.ARCHIVE
    lib.ARCHIVE = archive
    try:
        save = archive / "sample-round-004.bo1checkpoint"
        with zipfile.ZipFile(save, "w") as file:
            file.writestr("manifest.json", json.dumps({
                "format": 1, "map": "zombie_cod5_factory", "round": 4,
                "saved_at": "2026-10-20T05:00:00-04:00"}))
            file.writestr("save.bin", b"checkpoint data")
        original = save.read_bytes()
        catalog = lib.SaveLibrary(archive / "catalog.json")
        assert len(catalog.data["saves"]) == 1
        profile = catalog.new_profile("My solo game", "Solo")
        catalog.register(save, kind="auto", profile_id=profile)
        catalog.edit_save(save.name, title="High round attempt", profile_id=profile,
                          kind="auto", favorite=True)
        catalog.set_player_stats(save.name, [{"name": "Player 1", "points": 1400,
                                             "weapons": "M1911, MP40", "revives": 0,
                                             "downs": 1, "kills": 22}])
        reopened = lib.SaveLibrary(archive / "catalog.json")
        entry = reopened.data["saves"][save.name]
        assert (entry["title"], entry["kind"], entry["favorite"], entry["profile_id"]) == (
            "High round attempt", "auto", True, profile)
        assert save.read_bytes() == original
        assert entry["player_count"] == 1 and entry["players"][0]["kills"] == 22
        exported = reopened.export_saves([save.name], archive)
        assert exported.suffix == ".bo1gamesave"
        imported = reopened.import_saves(exported)
        assert len(imported) == 1
        imported_entry = reopened.data["saves"][imported[0]]
        assert imported_entry["imported"] is True
        assert imported_entry["title"] == "High round attempt"
        assert imported_entry["players"][0]["kills"] == 22
        assert imported_entry["saved_mode"] == "Solo"
        assert (archive / imported[0]).read_bytes() == original
        reopened.delete_save(imported[0])
        replacement = archive / "new-round-005.bo1checkpoint"
        with zipfile.ZipFile(replacement, "w") as file:
            file.writestr("manifest.json", json.dumps({
                "format": 1, "map": "zombie_cod5_factory", "round": 5,
                "saved_at": "2026-10-20T05:05:00-04:00"}))
        reopened.replace_save(replacement, save.name)
        assert not replacement.exists()
        assert reopened.data["saves"][save.name]["round"] == 5
        assert reopened.data["saves"][save.name]["title"] == "High round attempt"
        assert reopened.data["saves"][save.name]["favorite"] is True
        assert "players" not in reopened.data["saves"][save.name]
        recovered = lib.SaveLibrary(archive / "catalog.json")
        assert recovered.data["saves"][save.name]["round"] == 5
        assert recovered.data["saves"][save.name]["favorite"] is True
        reopened.delete_save(save.name)
        assert not save.exists() and not reopened.data["saves"]
    finally:
        lib.ARCHIVE = original_archive

print("Save catalog grouping, rename, favorite, and deletion passed")
