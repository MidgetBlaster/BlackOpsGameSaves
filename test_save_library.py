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
        assert catalog.data["save_policy"] == "Replace started save"
        assert len(catalog.data["saves"]) == 1
        assert catalog.data["saves"][save.name]["title"] == "Save Game 1"
        second = archive / "sample-round-005.bo1checkpoint"
        with zipfile.ZipFile(second, "w") as file:
            file.writestr("manifest.json", json.dumps({
                "format": 1, "map": "zombie_cod5_factory", "round": 5,
                "saved_at": "2026-10-20T05:02:00-04:00"}))
            file.writestr("save.bin", b"second checkpoint")
        catalog.scan()
        assert catalog.data["saves"][second.name]["title"] == "Save Game 2"
        selected_package = catalog.export_saves([save.name, second.name], archive)
        with zipfile.ZipFile(selected_package) as package:
            assert len(json.loads(package.read("export.json"))["saves"]) == 2
        imported_pair = catalog.import_saves(selected_package)
        assert len(imported_pair) == 2
        assert all(catalog.data["saves"][name]["imported"] for name in imported_pair)
        for name in imported_pair:
            catalog.delete_save(name)
        catalog.delete_save(second.name)
        with zipfile.ZipFile(second, "w") as file:
            file.writestr("manifest.json", json.dumps({
                "format": 1, "map": "zombie_cod5_factory", "round": 6,
                "saved_at": "2026-10-20T05:03:00-04:00"}))
        catalog.scan()
        assert catalog.data["saves"][second.name]["title"] == "Save Game 3"
        catalog.delete_save(second.name)
        profile = catalog.new_profile("My solo game", "Solo")
        catalog.register(save, kind="auto", profile_id=profile)
        catalog.edit_save(save.name, title="High round attempt", profile_id=profile,
                          kind="auto", favorite=True)
        catalog.set_player_stats(save.name, [{"name": "Player 1", "points": 1400,
                                             "weapons": "M1911, MP40", "revives": 0,
                                             "downs": 1, "kills": 22}])
        reopened = lib.SaveLibrary(archive / "catalog.json")
        assert reopened.data["save_policy"] == "Replace started save"
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
        again = archive / "new-round-006.bo1checkpoint"
        with zipfile.ZipFile(again, "w") as file:
            file.writestr("manifest.json", json.dumps({
                "format": 1, "map": "zombie_cod5_factory", "round": 6,
                "saved_at": "2026-10-20T05:06:00-04:00"}))
        reopened.replace_save(again, save.name)
        assert not again.exists()
        assert set(reopened.data["saves"]) == {save.name}
        assert set(archive.glob("*.bo1checkpoint")) == {save}
        assert reopened.data["saves"][save.name]["round"] == 6
        recovered = lib.SaveLibrary(archive / "catalog.json")
        assert recovered.data["saves"][save.name]["round"] == 6
        assert recovered.data["saves"][save.name]["favorite"] is True
        reopened.delete_save(save.name)
        assert not save.exists() and not reopened.data["saves"]
    finally:
        lib.ARCHIVE = original_archive

print("Save catalog grouping, rename, favorite, and deletion passed")

# Old history-based cached stats refresh once using the current inventory decoder.
from unittest.mock import patch
from save_library import populate_player_stats
entry={"stats_source":"archive","players":[{"weapons":"old gun history"}]}
with patch("save_library.extract_players",return_value=[{"weapons":"current loadout"}]) as decode:
    assert populate_player_stats(Path("cache-test.bo1checkpoint"),entry)
    assert entry["players"][0]["weapons"] == "current loadout"
    assert not populate_player_stats(Path("cache-test.bo1checkpoint"),entry)
    decode.assert_called_once()
print("Legacy weapon history cache refreshes once")
