"""Plutonium T5 discovery; never launch with the offline -lan switch."""
from pathlib import Path
import json
import os
import subprocess
from functools import lru_cache


def home():
    return Path(os.environ['LOCALAPPDATA']) / 'Plutonium'


@lru_cache(maxsize=16)
def t5_process(pid):
    # Cache by PID: process enumeration runs several times per second.
    command = (f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {int(pid)}').CommandLine")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                             '-Command', command], capture_output=True, text=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=5)
    import shlex
    return any(word.strip('"').lower() == 't5sp'
               for word in shlex.split(result.stdout, posix=False))


def executable_for_process(path, pid):
    path = Path(path)
    if path.name.lower() == 'blackops.exe':
        return path, 'steam'
    if (path.name.lower() == 'plutonium-bootstrapper-win32.exe'
            and path.resolve() == (home() / 'bin' / path.name).resolve()
            and t5_process(pid)):
        return home() / 'games' / 't5sp.exe', 'plutonium'
    raise RuntimeError(f'Unsupported game process: {path.name}')


def install_mod(source, game_directory, manager, icon, copy):
    """Install an independent mod/app/profile without importing Steam saves."""
    import checkpoint_memory as core
    import game_save_installer as installer
    root = home()
    if not root.is_dir():
        return None
    target = root / 'storage' / 't5' / 'mods' / 'Game Save'
    target.mkdir(parents=True, exist_ok=True)
    for name in installer.MOD_FILES:
        copy(source / name, target / name)
    for folder in installer.MOD_FOLDERS:
        for path in (source / folder).rglob('*'):
            if path.is_file():
                copy(path, target / path.relative_to(source))
    iwd = source / 'Game Save.iwd'
    if iwd.is_file():
        copy(iwd, target / iwd.name)
    copy(manager, target / 'BlackOpsGameSaves.exe')
    copy(icon, target / 'BlackOpsGameSaves.ico')
    (target / 'client.json').write_text(json.dumps({
        'client': 'plutonium', 'game_directory': str(game_directory.resolve())}), encoding='utf-8')
    executable = root / 'games' / 't5sp.exe'
    if executable.is_file():
        core.save_memory_profile(core.memory_profile(executable), target / 'memory_profile_plutonium.json')
    return target
