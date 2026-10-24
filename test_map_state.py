from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import shutil
import checkpoint_memory as core
import game_launcher as launch

source = core.ROOT / 'scriptdata/checkpoint_variants'
with TemporaryDirectory() as temp:
    root = Path(temp)
    variants = root / 'scriptdata/checkpoint_variants'
    shutil.copytree(source, variants)
    (root / 'maps').mkdir()
    (root / 'clientscripts').mkdir()
    main = root / 'maps/_zombiemode.gsc'
    options = root / 'maps/_checkpoint_coop_pause.gsc'
    client = root / 'clientscripts/zombie_cosmodrome.csc'
    main.write_bytes((variants / '_zombiemode_pause.gsc').read_bytes())
    options.write_bytes((variants / '_checkpoint_coop_pause_v3.gsc').read_bytes())
    client.write_bytes((variants / 'zombie_cosmodrome_v1.csc').read_bytes())
    with (patch.object(core,'ROOT',root),patch.object(launch,'SCRIPT_SOURCE',main),
          patch.object(launch,'OPTIONS_SCRIPT',options),patch.object(launch,'SCRIPT_VARIANTS',variants)):
        launch.prepare_script_variant(legacy=False,enhanced=True,round_bridge=True,map_state=True)
        assert options.read_bytes()==(variants/'_checkpoint_coop_pause_v4.gsc').read_bytes()
        assert client.read_bytes()==(variants/'zombie_cosmodrome_v2.csc').read_bytes()
        launch.power_restore_config(False,map_state=True)
        config=(root/'checkpoint_power.cfg').read_text()
        assert 'checkpoint_map_restore_token' in config
        assert 'set checkpoint_restore_power_on 0' in config
        launch.prepare_script_variant(legacy=False,enhanced=True,round_bridge=True)
        assert options.read_bytes()==(variants/'_checkpoint_coop_pause_v3.gsc').read_bytes()
        launch.power_restore_config(False)
        assert 'checkpoint_legacy_vision_token' in (root/'checkpoint_power.cfg').read_text()
        launch.prepare_script_variant(legacy=True)
        assert main.read_bytes()==(variants/'_zombiemode_legacy.gsc').read_bytes()
        assert options.read_bytes()==(variants/'_checkpoint_coop_pause_v1.gsc').read_bytes()
print('Map-state variant selection, legacy checksums and restore requests passed')
