"""Check Steam's active persona is selected for a safe Black Ops name."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import steam_identity


with TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
    root = Path(temp)
    config = root / "config"
    config.mkdir()
    users = config / "loginusers.vdf"
    users.write_text('''"users"
{
  "76561198000000001" { "PersonaName" "Old Player" "MostRecent" "0" }
  "76561198000000002" { "PersonaName" "Current Player" "MostRecent" "1" }
}
''', encoding="utf-8")
    assert steam_identity.persona_from_vdf(users) == "Current Player"
    with patch.object(steam_identity, "_steam_roots", return_value=[root]):
        assert steam_identity.launch_name(root / "game") == "Current Player"
    users.write_text('"users" { "76561198000000002" { "PersonaName" "Bad;\"quit" "MostRecent" "1" } }',
                     encoding="utf-8")
    with patch.object(steam_identity, "_steam_roots", return_value=[root]):
        assert steam_identity.launch_name(root / "game") in (None, "Bad")

assert steam_identity.safe_player_name("Unknown Soldier 0") is None
assert steam_identity.safe_player_name('Good;"quit') == "Goodquit"

print("Steam persona detection passed")
