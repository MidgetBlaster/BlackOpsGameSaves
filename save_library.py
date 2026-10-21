"""Small, independent catalog for user-facing checkpoint names and groups."""

from __future__ import annotations

from datetime import datetime
import json
import hashlib
import io
import os
from pathlib import Path
import re
import struct
from uuid import uuid4
import zipfile

from checkpoint_memory import ARCHIVE
from checkpoint_stats import extract_players

CATALOG = ARCHIVE / "catalog.json"
KINDS = {"manual", "auto"}
MODES = {"Solo", "Co-op", "Unknown"}
EXPORT_FORMAT = 1
MAX_IMPORT_SIZE = 64 * 1024 * 1024


def checkpoint_path(name: str) -> Path:
    if Path(name).name != name or not name.endswith(".bo1checkpoint"):
        raise ValueError("Invalid checkpoint filename")
    path = ARCHIVE / name
    if path.resolve().parent != ARCHIVE.resolve():
        raise ValueError("Checkpoint is outside the save folder")
    return path


def checkpoint_details(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        info = json.loads(archive.read("manifest.json"))
    if info.get("format") != 1 or not isinstance(info.get("round"), int):
        raise ValueError("Unsupported checkpoint manifest")
    return {"map": str(info.get("map", "")), "round": info["round"],
            "saved_at": str(info.get("saved_at", ""))}


def populate_player_stats(path: Path, entry: dict) -> bool:
    """Decode display details once per file; never alter the checkpoint."""
    if entry.get("stats_source") or entry.get("stats_error") or entry.get("error"):
        return False
    try:
        players = extract_players(path)
    except (OSError, RuntimeError, ValueError, KeyError, IndexError,
            struct.error, zipfile.BadZipFile) as error:
        entry["stats_error"] = str(error)
    else:
        entry["players"] = players
        if players:
            entry["player_count"] = len(players)
        entry["stats_source"] = "archive"
    return True


class SaveLibrary:
    def __init__(self, path: Path = CATALOG):
        self.path = path
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            if self.data.get("format") != 1:
                raise ValueError("Unsupported save catalog")
        else:
            self.data = {"format": 1, "active_profile": "imported",
                         "profiles": [{"id": "imported", "title": "Imported saves", "mode": "Unknown"}],
                         "saves": {}}
        self.data.setdefault("next_save_number_by_map", {})
        renamed = False
        for entry in sorted(self.data["saves"].values(),
                            key=lambda item: item.get("saved_at", "")):
            if entry.get("title") in (None, "Saved game", "Save Game") or \
                    entry.get("title") == f"{entry.get('map')} - Round {entry.get('round')}":
                entry["title"] = self._default_title(entry.get("map", ""))
                renamed = True
        if renamed:
            self.write()
        self.scan()

    def write(self):
        self.path.parent.mkdir(exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)

    def _default_title(self, map_name: str) -> str:
        """Assign a stable, increasing title within one map's save list."""
        counters = self.data.setdefault("next_save_number_by_map", {})
        highest = max((int(match.group(1)) for entry in self.data["saves"].values()
                       if entry.get("map") == map_name
                       for match in [re.fullmatch(r"Save Game (\d+)",
                                                  str(entry.get("title", "")))] if match),
                      default=0)
        number = max(int(counters.get(map_name, 1)), highest + 1)
        counters[map_name] = number + 1
        return f"Save Game {number}"

    def scan(self):
        changed = False
        for path in ARCHIVE.glob("*.bo1checkpoint"):
            if path.name in self.data["saves"]:
                entry = self.data["saves"][path.name]
                modified = path.stat().st_mtime_ns
                if entry.get("file_mtime_ns") != modified:
                    try:
                        entry.update(checkpoint_details(path), error="", file_mtime_ns=modified)
                        entry.pop("players", None)
                        entry.pop("player_count", None)
                        entry.pop("stats_source", None)
                        entry.pop("stats_error", None)
                    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
                        entry.update(error=str(exc), file_mtime_ns=modified)
                    changed = True
                continue
            try:
                details = checkpoint_details(path)
                label = self._default_title(details["map"])
                error = ""
            except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
                details = {"map": "", "round": 0, "saved_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()}
                label = path.stem
                error = str(exc)
            self.data["saves"][path.name] = {
                "title": label, "profile_id": "imported", "kind": "manual",
                "favorite": False, "error": error,
                "file_mtime_ns": path.stat().st_mtime_ns, **details,
            }
            changed = True
        for name in list(self.data["saves"]):
            if not checkpoint_path(name).exists():
                del self.data["saves"][name]
                changed = True
            elif populate_player_stats(checkpoint_path(name), self.data["saves"][name]):
                changed = True
        if changed:
            self.write()

    def profiles(self) -> list[dict]:
        return list(self.data["profiles"])

    def profile(self, profile_id: str) -> dict:
        return next(profile for profile in self.data["profiles"] if profile["id"] == profile_id)

    def new_profile(self, title: str, mode: str) -> str:
        title = title.strip()
        if not title or mode not in MODES - {"Unknown"}:
            raise ValueError("Enter a game title and choose Solo or Co-op")
        profile_id = uuid4().hex
        self.data["profiles"].append({"id": profile_id, "title": title, "mode": mode})
        self.data["active_profile"] = profile_id
        self.write()
        return profile_id

    def edit_profile(self, profile_id: str, title: str, mode: str):
        title = title.strip()
        if not title or mode not in MODES - {"Unknown"}:
            raise ValueError("Enter a game title and choose Solo or Co-op")
        profile = self.profile(profile_id)
        profile.update(title=title, mode=mode)
        self.write()

    def set_active_profile(self, profile_id: str):
        self.profile(profile_id)
        self.data["active_profile"] = profile_id
        self.write()

    def register(self, path: Path, *, kind: str, profile_id: str,
                 title: str | None = None) -> dict:
        if kind not in KINDS:
            raise ValueError("Unknown save category")
        self.profile(profile_id)
        target = checkpoint_path(path.name)
        if target.resolve() != path.resolve():
            raise ValueError("Checkpoint is outside the save folder")
        details = checkpoint_details(target)
        entry = self.data["saves"].get(target.name, {})
        if entry.get("file_mtime_ns") != target.stat().st_mtime_ns:
            entry.pop("players", None)
            entry.pop("player_count", None)
            entry.pop("stats_source", None)
            entry.pop("stats_error", None)
        entry.update(details)
        entry.update(profile_id=profile_id, kind=kind, error="",
                     file_mtime_ns=target.stat().st_mtime_ns)
        if title is not None:
            entry["title"] = title.strip() or self._default_title(details["map"])
        elif not entry.get("title"):
            entry["title"] = self._default_title(details["map"])
        entry.setdefault("favorite", False)
        populate_player_stats(target, entry)
        self.data["saves"][target.name] = entry
        self.write()
        return entry

    def edit_save(self, name: str, *, title: str, profile_id: str, kind: str,
                  favorite: bool):
        checkpoint_path(name)
        self.profile(profile_id)
        if kind not in KINDS or not title.strip():
            raise ValueError("Enter a title and choose Manual or Auto")
        self.data["saves"][name].update(title=title.strip(), profile_id=profile_id,
                                         kind=kind, favorite=bool(favorite))
        self.write()

    def toggle_favorite(self, name: str) -> bool:
        entry = self.data["saves"][name]
        entry["favorite"] = not entry["favorite"]
        self.write()
        return entry["favorite"]

    def set_player_stats(self, name: str, players: list[dict]):
        """Keep display details in the catalog without altering a checkpoint."""
        checkpoint_path(name)
        if name not in self.data["saves"] or not 1 <= len(players) <= 4:
            raise ValueError("Choose a save and enter between one and four players")
        cleaned = []
        for number, player in enumerate(players, 1):
            fields = {"name": str(player.get("name") or f"Player {number}").strip(),
                      "weapons": str(player.get("weapons") or "").strip()}
            for key in ("points", "revives", "downs", "kills"):
                value = player.get(key)
                if value in (None, ""):
                    fields[key] = None
                else:
                    value = int(value)
                    if value < 0:
                        raise ValueError(f"{key.title()} cannot be negative")
                    fields[key] = value
            cleaned.append(fields)
        self.data["saves"][name]["players"] = cleaned
        self.data["saves"][name]["player_count"] = len(cleaned)
        self.data["saves"][name]["stats_source"] = "manual"
        self.data["saves"][name].pop("stats_error", None)
        self.write()

    def delete_save(self, name: str):
        path = checkpoint_path(name)
        path.unlink()
        self.data["saves"].pop(name, None)
        self.write()

    def replace_save(self, source: Path, target_name: str) -> dict:
        """Replace one selected checkpoint, preserving its title and favorite."""
        replacement = checkpoint_path(source.name)
        target = checkpoint_path(target_name)
        if replacement.resolve() != source.resolve():
            raise ValueError("Checkpoint is outside the save folder")
        if target_name not in self.data["saves"] or not target.is_file():
            raise FileNotFoundError("The selected save is no longer available")
        details = checkpoint_details(replacement)
        if details["map"] != self.data["saves"][target_name]["map"]:
            raise ValueError("The current map differs from the selected save")
        if replacement != target:
            os.replace(replacement, target)
            self.data["saves"].pop(replacement.name, None)
        entry = self.data["saves"][target_name]
        entry.update(details, error="", file_mtime_ns=target.stat().st_mtime_ns)
        entry.pop("players", None)
        entry.pop("player_count", None)
        entry.pop("stats_source", None)
        entry.pop("stats_error", None)
        populate_player_stats(target, entry)
        self.write()
        return entry

    def export_saves(self, names: list[str], directory: Path) -> Path:
        """Write selected checkpoints and their display metadata to one portable file."""
        if not names:
            raise ValueError("Choose at least one save to export")
        directory = Path(directory)
        if not directory.is_dir():
            raise FileNotFoundError("Choose an existing export folder")
        items = []
        data = {}
        for name in dict.fromkeys(names):
            entry = self.data["saves"].get(name)
            if entry is None:
                raise FileNotFoundError(f"Save no longer exists: {name}")
            path = checkpoint_path(name)
            payload = path.read_bytes()
            checkpoint_details(path)
            key = f"checkpoints/{uuid4().hex}.bo1checkpoint"
            profile = self.profile(entry["profile_id"])
            items.append({"file": key, "sha256": hashlib.sha256(payload).hexdigest(),
                          "title": entry.get("title", "Saved game"),
                          "favorite": bool(entry.get("favorite")),
                          "kind": entry.get("kind", "manual"),
                          "mode": entry.get("saved_mode") or profile["mode"],
                          "players": entry.get("players", []),
                          "player_count": entry.get("player_count"),
                          "stats_source": entry.get("stats_source")})
            data[key] = payload
        destination = directory / f"BlackOps-Game-Saves-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bo1gamesave"
        suffix = 2
        while destination.exists():
            destination = directory / f"BlackOps-Game-Saves-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{suffix}.bo1gamesave"
            suffix += 1
        temporary = destination.with_name(destination.name + ".tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("export.json", json.dumps({"format": EXPORT_FORMAT, "saves": items},
                                                            ensure_ascii=False))
                for key, payload in data.items():
                    archive.writestr(key, payload)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def import_saves(self, package: Path) -> list[str]:
        """Validate a portable package before adding its checkpoints to Imported saves."""
        package = Path(package)
        with zipfile.ZipFile(package) as archive:
            if archive.getinfo("export.json").file_size > 2 * 1024 * 1024:
                raise ValueError("The save package details are too large")
            manifest = json.loads(archive.read("export.json"))
            if manifest.get("format") != EXPORT_FORMAT or not isinstance(manifest.get("saves"), list):
                raise ValueError("Unsupported save package")
            records = manifest["saves"]
            if not records:
                raise ValueError("The save package has an invalid save count")
            prepared = []
            total_size = 0
            for record in records:
                key = record.get("file")
                if not isinstance(key, str) or not key.startswith("checkpoints/") or \
                        Path(key).name != key.split("/")[-1] or key not in archive.namelist():
                    raise ValueError("Invalid checkpoint in save package")
                if archive.getinfo(key).file_size > MAX_IMPORT_SIZE:
                    raise ValueError("A checkpoint in the package is too large")
                total_size += archive.getinfo(key).file_size
                if total_size > 1024 * 1024 * 1024:
                    raise ValueError("The save package is too large")
                payload = archive.read(key)
                if hashlib.sha256(payload).hexdigest() != record.get("sha256"):
                    raise ValueError("The save package checksum does not match")
                with zipfile.ZipFile(io.BytesIO(payload)) as checkpoint:
                    details = json.loads(checkpoint.read("manifest.json"))
                if details.get("format") != 1 or not isinstance(details.get("round"), int) or \
                        not details.get("map"):
                    raise ValueError("The package contains an invalid checkpoint")
                prepared.append((record, payload))
        imported = []
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        for record, payload in prepared:
            name = f"imported-{uuid4().hex}.bo1checkpoint"
            path = checkpoint_path(name)
            _atomic_checkpoint(path, payload)
            try:
                entry = self.register(path, kind=record.get("kind") if record.get("kind") in KINDS else "manual",
                                      profile_id="imported", title=str(record.get("title") or "Saved game"))
            except Exception:
                path.unlink(missing_ok=True)
                raise
            entry["imported"] = True
            entry["favorite"] = bool(record.get("favorite"))
            entry["saved_mode"] = record.get("mode") if record.get("mode") in MODES else "Unknown"
            players = record.get("players")
            if isinstance(players, list) and players:
                entry["players"] = players[:4]
                entry["player_count"] = len(entry["players"])
                entry["stats_source"] = record.get("stats_source") or "imported"
            imported.append(name)
        self.write()
        return imported


def _atomic_checkpoint(path: Path, payload: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
