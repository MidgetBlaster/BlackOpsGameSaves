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

with (patch.object(steam_identity, "plutonium_player_name", return_value=None),
      patch.object(steam_identity, "local_persona_name", return_value="DifferentSteamAccount") as steam):
    assert steam_identity.local_player_name(Path("game"), "plutonium") is None
    steam.assert_not_called()


class SignedInGame:
    _identity_dvars = {b"name": 0x10000, b"onlinegame": 0x10100, b"live_service": 0x10200}
    enabled = True
    name = b"Platform Player"

    def u32(self, address):
        if address == 0x10018:
            return 0x20000
        return address + 0x1000

    def read(self, address, size):
        if address == 0x20000:
            return self.name + b"\0"
        if size == 1:
            return bytes([int(self.enabled)])
        return {0x11000: b"name\0", 0x11100: b"onlinegame\0",
                0x11200: b"live_service\0"}[address]

game = SignedInGame()
assert steam_identity.online_name(game) == "Platform Player"
game.enabled = False
assert steam_identity.online_name(game) is None
game.enabled = True
game.name = b"Unknown Soldier"
assert steam_identity.online_name(game) is None
print("Online identity requires enabled services and a registered name")
