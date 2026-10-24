"""Client isolation and Plutonium payload installation checks."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import plutonium_support as p
import game_save_installer as i

with TemporaryDirectory() as folder:
    root = Path(folder)
    source = root / 'source'
    source.mkdir()
    (root / 'Plutonium').mkdir()
    (source / 'checkpoint.cfg').write_text('bind F11 "devsave 1"')
    (source / 'maps').mkdir()
    (source / 'maps' / 'test.gsc').write_text('main() {}')
    manager = source / 'app.exe'; manager.write_bytes(b'app')
    icon = source / 'icon.ico'; icon.write_bytes(b'icon')
    with (patch.dict(os.environ, LOCALAPPDATA=str(root)),
          patch.object(i, 'MOD_FILES', ('checkpoint.cfg',)),
          patch.object(i, 'MOD_FOLDERS', ('maps',))):
        target = p.install_mod(source, root / 'game', manager, icon, i._copy_if_changed)
        assert target == root / 'Plutonium/storage/t5/mods/Game Save'
        assert (target / 'maps/test.gsc').read_text() == 'main() {}'
        assert json.loads((target / 'client.json').read_text())['client'] == 'plutonium'
        assert not (target / 'checkpoint_saves').exists()
        with patch.object(p, 't5_process', return_value=True):
            executable, client = p.executable_for_process(root / 'Plutonium/bin/plutonium-bootstrapper-win32.exe', 1)
            assert executable == root / 'Plutonium/games/t5sp.exe'
            assert client == 'plutonium'
        with patch.object(p, 't5_process', return_value=False):
            try:
                p.executable_for_process(root / 'Plutonium/bin/plutonium-bootstrapper-win32.exe', 1)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Accepted non-T5SP client')
print('Plutonium payload and client isolation passed')
