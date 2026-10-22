"""Persist BO1 Zombies' committed in-memory save across game launches.

Addresses and layout: MisaDev4/bo1-zombies-decompiled, g_sp_savegame.{h,cpp}.
Supported executable: the known BlackOps.exe or an identical code/data layout.
"""

from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager, nullcontext
import ctypes
from ctypes import wintypes
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import zipfile

ROOT = (Path(sys.executable) if getattr(sys, "frozen", False) else Path(__file__)).resolve().parent
GAME = ROOT.parent.parent
ARCHIVE = ROOT / "checkpoint_saves"
RECOVERY_FILE = ARCHIVE / "recovery" / "latest.bo1checkpoint"
RECOVERY_INTERVAL = 60
SUPPORTED_SHA256 = "1141278c4599025c85d0e27d1629a5e8ecb0568559c4d9653e693018c3b25f1e"
SUPPORTED_LAYOUT_SHA256 = "cb385008f998fe9b5b7173047bfbfc0954fa78e7ca89a33f365a8bf9b8a813b1"
LAYOUT_SECTIONS = (b".text", b".rdata", b".data", b".tls", b".rodata")
BASE = 0x400000
COMMITTED_PTR = 0x01D04BA0
WRITE_PTR = 0x01D04BA4
COMMITTED_FLAG = 0x023A5594
SAVE_QUEUE = 0x02899800
SAVE_QUEUE_COUNT = 0x02899CD4
SAVE_REQUEST_SIZE = 0x19C
ASYNC_DISK_SAVE = 0x01C77020
ASYNC_CALLBACK_SAVE = 0x01C77024
CALLBACK_NOW_OFFSET = 0x104F1
SAVE_A = 0x01D04BA8
SAVE_B = 0x01D1509C
SAVE_SIZE = 0x104F4
MEMFILE_SIZE = 0x8024
STATE_OFFSET = 0x10048
HEADER_OFFSET = 0x1004C
HEADER_SIZE = 0x498
BUFFERS = {
    SAVE_A: (0x01D25590, 0x01F25590),
    SAVE_B: (0x02065590, 0x02265590),
}
BUFFER_SIZES = (0x200000, 0x140000)
SCENE_ADDR = BASE + 0x896268
MENU_ADDR = BASE + 0x4212FEC
TIMER_ADDR = BASE + 0x2F08A30
MAGIC_ADDR = BASE + 0x1656994
ROUND_BYTE_ADDR = BASE + 0x16569B6
ROUND_CHANGE_ADDR = BASE + 0x165695D
PAUSED_ADDR = BASE + 0x8902B4
# Original engine level.framenum and level.time, identified in g_sp_savegame.cpp.
LEVEL_FRAME_ADDR = 0x01C0488C
LEVEL_TIME_ADDR = 0x01C04890
SCENES = {5: "kino", 10: "five", 15: "dead_ops", 20: "ascension",
          28: "call_of_the_dead", 44: "shangri_la", 76: "moon",
          108: "nacht", 140: "verruckt", 172: "shi_no_numa", 204: "der_riese"}
START_TICKS = {5: 190, 10: 190, 15: 50, 20: 580, 28: 190, 44: 190,
               76: 195, 108: 195, 140: 200, 172: 198, 204: 195}
SAVE_TIMINGS = ("End of Rounds", "Round Transitions", "Start of Round")
POWER_MARKER = b"BOGS_POWER_ON_V1"
MAP_SCENES = {
    "zombie_theater": 5,
    "zombie_pentagon": 10,
    "zombie_cosmodrome": 20,
    "zombie_coast": 28,
    "zombie_temple": 44,
    "zombie_moon": 76,
    "zombie_cod5_prototype": 108,
    "zombie_cod5_asylum": 140,
    "zombie_cod5_sumpf": 172,
    "zombie_cod5_factory": 204,
}


def executable_layout_fingerprint(data: bytes) -> str | None:
    """Identify the mapped code/data while ignoring resources and file overlays."""
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    try:
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_offset > len(data) - 24 or data[pe_offset:pe_offset + 4] != b"PE\0\0":
            return None
        machine, section_count = struct.unpack_from("<HH", data, pe_offset + 4)
        optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
        optional_offset = pe_offset + 24
        if (machine != 0x14C or optional_size < 36 or
                optional_offset + optional_size > len(data) or
                struct.unpack_from("<H", data, optional_offset)[0] != 0x10B):
            return None
        entry_point = struct.unpack_from("<I", data, optional_offset + 16)[0]
        image_base, alignment = struct.unpack_from("<II", data, optional_offset + 28)
        table = optional_offset + optional_size
        if section_count > 96 or table + section_count * 40 > len(data):
            return None
        sections = {}
        for index in range(section_count):
            offset = table + index * 40
            name = data[offset:offset + 8].rstrip(b"\0")
            if name not in LAYOUT_SECTIONS:
                continue
            if name in sections:
                return None
            virtual_size, address, raw_size, raw_offset = struct.unpack_from("<IIII", data, offset + 8)
            characteristics = struct.unpack_from("<I", data, offset + 36)[0]
            if raw_size == 0 or raw_offset > len(data) or raw_size > len(data) - raw_offset:
                return None
            sections[name] = (virtual_size, address, raw_size, characteristics,
                              data[raw_offset:raw_offset + raw_size])
        if set(sections) != set(LAYOUT_SECTIONS):
            return None
        digest = hashlib.sha256()
        digest.update(struct.pack("<IIII", machine, entry_point, image_base, alignment))
        for name in LAYOUT_SECTIONS:
            virtual_size, address, raw_size, characteristics, content = sections[name]
            digest.update(name + b"\0")
            digest.update(struct.pack("<IIII", virtual_size, address, raw_size, characteristics))
            digest.update(content)
        return digest.hexdigest()
    except (struct.error, OverflowError):
        return None


def verify_game_executable(executable: Path) -> str:
    """Accept only the tested file or one with identical mapped code/data."""
    data = Path(executable).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest == SUPPORTED_SHA256:
        return digest
    if executable_layout_fingerprint(data) == SUPPORTED_LAYOUT_SHA256:
        return digest
    raise RuntimeError(
        "Unsupported BlackOps.exe build for memory saves.\n"
        f"File: {executable}\nSHA-256: {digest}\nSize: {len(data):,} bytes\n"
        "Its game code or memory layout differs from the tested build. "
        "No game memory or files were changed. Share this SHA-256 with the mod maintainer to request support.")


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", INPUT_UNION)]


class GameProcess:
    def __init__(self, pid: int, write: bool = False, suspend: bool = False):
        if sys.platform != "win32":
            raise RuntimeError("Windows is required")
        self.pid = pid
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        k = self.kernel
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k.ReadProcessMemory.restype = wintypes.BOOL
        k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
        k.WriteProcessMemory.restype = wintypes.BOOL
        k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.user.GetForegroundWindow.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
        self.user.MapVirtualKeyW.restype = wintypes.UINT
        self.user.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user.SendInput.restype = wintypes.UINT
        rights = 0x1010 | (0x0028 if write else 0) | (0x0800 if suspend else 0)
        self.handle = k.OpenProcess(rights, False, pid)
        if not self.handle:
            error = ctypes.get_last_error()
            if error == 5:
                raise PermissionError("Could not access Black Ops memory. Run this companion at the game's privilege level (usually Administrator).")
            raise OSError(error, f"OpenProcess({pid}) failed")
        try:
            length = wintypes.DWORD(32768)
            path = ctypes.create_unicode_buffer(length.value)
            if not k.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(length)):
                raise OSError(ctypes.get_last_error(), "Could not identify the game executable")
            executable = Path(path.value)
            if executable.name.lower() != "blackops.exe":
                raise RuntimeError(f"Unsupported process: {executable.name}")
            verify_game_executable(executable)
            if self.read(BASE, 2) != b"MZ":
                raise RuntimeError("The game image is not at the expected base address")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def read(self, address: int, size: int) -> bytes:
        data = (ctypes.c_ubyte * size)()
        count = ctypes.c_size_t()
        if not self.kernel.ReadProcessMemory(self.handle, ctypes.c_void_p(address), data,
                                             size, ctypes.byref(count)) or count.value != size:
            error = ctypes.get_last_error()
            if error == 5:
                raise PermissionError("Black Ops denied memory reads. Administrator access is required.")
            raise OSError(error, f"Cannot read game memory at 0x{address:X}")
        return bytes(data)

    def write(self, address: int, data: bytes):
        source = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        count = ctypes.c_size_t()
        if not self.kernel.WriteProcessMemory(self.handle, ctypes.c_void_p(address), source,
                                              len(data), ctypes.byref(count)) or count.value != len(data):
            error = ctypes.get_last_error()
            if error == 5:
                raise PermissionError("Black Ops denied memory writes. Administrator access is required.")
            raise OSError(error, f"Cannot write game memory at 0x{address:X}")

    def u32(self, address: int) -> int:
        return struct.unpack("<I", self.read(address, 4))[0]

    @contextmanager
    def suspended(self):
        # Freeze all game threads while replacing a co-op checkpoint. The pause
        # menu does not stop the server when multiple clients are connected.
        native = ctypes.WinDLL("ntdll", use_last_error=True)
        native.NtSuspendProcess.argtypes = [wintypes.HANDLE]
        native.NtSuspendProcess.restype = wintypes.LONG
        native.NtResumeProcess.argtypes = [wintypes.HANDLE]
        native.NtResumeProcess.restype = wintypes.LONG
        status = native.NtSuspendProcess(self.handle)
        if status != 0:
            raise RuntimeError(f"Could not stop the game for a cooperative restore (NTSTATUS 0x{status & 0xFFFFFFFF:08X})")
        try:
            yield
        finally:
            status = native.NtResumeProcess(self.handle)
            if status != 0:
                raise RuntimeError(f"Could not resume the game after restore (NTSTATUS 0x{status & 0xFFFFFFFF:08X})")

    def foreground(self) -> bool:
        owner = wintypes.DWORD()
        self.user.GetWindowThreadProcessId(self.user.GetForegroundWindow(), ctypes.byref(owner))
        return owner.value == self.pid

    def activate_window(self) -> bool:
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsWindowVisible.restype = wintypes.BOOL
        self.user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        self.user.EnumWindows.restype = wintypes.BOOL
        self.user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.SetForegroundWindow.restype = wintypes.BOOL
        windows = []

        @callback_type
        def find_window(window, _unused):
            owner = wintypes.DWORD()
            self.user.GetWindowThreadProcessId(window, ctypes.byref(owner))
            if owner.value == self.pid and self.user.IsWindowVisible(window):
                windows.append(window)
                return False
            return True

        self.user.EnumWindows(find_window, 0)
        if not windows:
            return False
        self.user.ShowWindow(windows[0], 9)  # SW_RESTORE
        self.user.SetForegroundWindow(windows[0])
        return self.foreground()

    def press_save(self):
        self.press_game_key(0x7A, "F11 save")

    def press_load(self):
        self.press_game_key(0x7B, "F12 load")

    def press_switch(self):
        self.press_game_key(0x79, "F10 map switch")

    def press_coop_pause(self):
        self.press_game_key(0x78, "F9 co-op pause")

    def press_coop_resume(self):
        self.press_game_key(0x77, "F8 co-op resume")

    def press_speed_fix(self):
        self.press_game_key(0x74, "F5 movement settings")

    def press_game_key(self, virtual_key: int, description: str):
        if not self.foreground():
            raise RuntimeError(f"Bring Black Ops to the foreground before requesting the {description} key")
        scan = self.user.MapVirtualKeyW(virtual_key, 0)
        if not scan:
            raise RuntimeError(f"Windows could not map the {description} key")
        self._send_scan(scan, 8, description)
        try:
            time.sleep(0.06)  # let the game sample the key-down state
        finally:
            self._send_scan(scan, 10, description)

    def _send_scan(self, scan: int, flags: int, description: str):
        event = INPUT()
        event.type = 1
        event.data.ki.wScan = scan
        event.data.ki.dwFlags = flags
        if self.user.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            raise OSError(f"Windows rejected the {description} key")

def game_pid() -> int | None:
    if sys.platform != "win32":
        raise RuntimeError("Windows is required")

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = kernel.Process32FirstW.argtypes
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "Could not enumerate game processes")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while found:
            if entry.szExeFile.lower() == "blackops.exe":
                return entry.th32ProcessID
            found = kernel.Process32NextW(handle, ctypes.byref(entry))
        return None
    finally:
        kernel.CloseHandle(handle)


def header_info(image: bytes) -> dict:
    h = image[HEADER_OFFSET:HEADER_OFFSET + HEADER_SIZE]
    text = lambda start, length: h[start:start + length].split(b"\0", 1)[0].decode("ascii", "replace")
    return {"version": struct.unpack_from("<I", h, 0)[0],
            "map_checksum": struct.unpack_from("<I", h, 4)[0],
            "script_checksums": list(struct.unpack_from("<III", h, 0x14)),
            "map": text(0x20, 256), "filename": text(0x3E0, 128),
            "save_id": struct.unpack_from("<I", h, 0x0C)[0],
            "body_size": struct.unpack_from("<I", h, 0x490)[0],
            "secondary_size": struct.unpack_from("<I", h, 0x494)[0]}


def validate_image(address: int, image: bytes) -> dict:
    if address not in BUFFERS or len(image) != SAVE_SIZE:
        raise RuntimeError("Unexpected save buffer address or size")
    expected = BUFFERS[address]
    actual = (struct.unpack_from("<I", image, 0)[0],
              struct.unpack_from("<I", image, MEMFILE_SIZE)[0])
    if actual != expected:
        raise RuntimeError(f"Save buffer pointers do not match the decompiled engine layout: {actual!r}")
    if struct.unpack_from("<I", image, STATE_OFFSET)[0] != 3:
        raise RuntimeError("The game has no committed checkpoint yet")
    h = header_info(image)
    if h["version"] not in (0x133, 0x134) or not h["filename"].startswith("save\\"):
        raise RuntimeError("The committed checkpoint header is invalid")
    if not (0 < h["body_size"] <= BUFFER_SIZES[0] and
            0 <= h["secondary_size"] <= BUFFER_SIZES[1]):
        raise RuntimeError("The checkpoint payload size is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_]+", h["map"]):
        raise RuntimeError(f"The checkpoint map name is invalid: {h['map']!r} (checksum {h['map_checksum']})")
    return h


def committed(game: GameProcess) -> tuple[int, bytes, dict]:
    address = game.u32(COMMITTED_PTR)
    image = game.read(address, SAVE_SIZE) if address in BUFFERS else b""
    h = validate_image(address, image)
    return address, image, h


def snapshot(game: GameProcess, round_number: int, target: Path | None = None) -> Path:
    address, image, h = committed(game)
    parts = [game.read(addr, size) for addr, size in zip(BUFFERS[address], BUFFER_SIZES)]
    if game.u32(COMMITTED_PTR) != address or game.read(address, SAVE_SIZE) != image:
        raise RuntimeError("The game changed the save while it was being copied; retry")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if target is None:
        target = ARCHIVE / f"{h['map']}-round-{round_number:03d}-{stamp}.bo1checkpoint"
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = {"format": 1, "executable_sha256": SUPPORTED_SHA256,
                "save_address": address, "round": round_number,
                "saved_at": datetime.now().astimezone().isoformat(), **h}
    options_script = ROOT / "maps" / "_checkpoint_coop_pause.gsc"
    options_variant = (ROOT / "scriptdata" / "checkpoint_variants" /
                       "_checkpoint_coop_pause_v2.gsc")
    bridge_variant = (ROOT / "scriptdata" / "checkpoint_variants" /
                      "_checkpoint_coop_pause_v3.gsc")
    if (options_script.is_file() and options_variant.is_file() and
            options_script.read_bytes() == options_variant.read_bytes()):
        metadata["script_variant"] = "player_options_v1"
    elif (options_script.is_file() and bridge_variant.is_file() and
          options_script.read_bytes() == bridge_variant.read_bytes()):
        metadata["script_variant"] = "player_options_v2"
        metadata["power_on"] = any(POWER_MARKER in part for part in parts)
    pieces = {"save.bin": image, "state.bin": parts[0], "secondary.bin": parts[1]}
    metadata["sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in pieces.items()}
    temporary = target.with_suffix(".part")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            archive.writestr("manifest.json", json.dumps(metadata, indent=2))
            for name, data in pieces.items():
                archive.writestr(name, data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def promote_recovery() -> Path | None:
    """Expose the last rolling checkpoint after a game or companion exit."""
    if not RECOVERY_FILE.exists():
        return None
    metadata, _ = load_archive(RECOVERY_FILE)
    ARCHIVE.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = ARCHIVE / f"{metadata['map']}-recovery-{stamp}.bo1checkpoint"
    os.replace(RECOVERY_FILE, target)
    return target


def load_archive(path: Path) -> tuple[dict, dict[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        metadata = json.loads(archive.read("manifest.json"))
        if metadata.get("format") != 1 or metadata.get("executable_sha256") != SUPPORTED_SHA256:
            raise RuntimeError("Unsupported checkpoint format or executable")
        pieces = {name: archive.read(name) for name in ("save.bin", "state.bin", "secondary.bin")}
    if [len(pieces[name]) for name in pieces] != [SAVE_SIZE, *BUFFER_SIZES]:
        raise RuntimeError("Checkpoint file lengths are invalid")
    for name, data in pieces.items():
        if hashlib.sha256(data).hexdigest() != metadata["sha256"].get(name):
            raise RuntimeError(f"Checkpoint integrity check failed: {name}")
    h = validate_image(metadata["save_address"], pieces["save.bin"])
    if any(metadata.get(key) != h[key] for key in ("map", "map_checksum", "script_checksums", "save_id")):
        raise RuntimeError("Checkpoint manifest does not match its save header")
    return metadata, pieces


def latest_archive() -> Path:
    entries = sorted(ARCHIVE.glob("*.bo1checkpoint"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not entries:
        raise RuntimeError("No checkpoint archive exists yet. In-game, run 'devsave 1', then run 'python checkpoint.py capture'; or keep 'watch' running until it prints 'Saved round'.")
    return entries[0]


def restore(game: GameProcess, path: Path, coop: bool = False):
    metadata, pieces = load_archive(path)
    # A co-op server cannot be paused through the menu. Its process must be
    # suspended for the entire read/check/write transaction.
    with game.suspended() if coop else nullcontext():
        current_address, _, current = committed(game)
        if (current["map"], current["map_checksum"], current["script_checksums"]) != (
                metadata["map"], metadata["map_checksum"], metadata["script_checksums"]):
            raise RuntimeError("The current map or scripts differ from the checkpoint. No game memory was changed.")
        before = (game.u32(LEVEL_FRAME_ADDR), game.u32(LEVEL_TIME_ADDR))
        if coop:
            if before[1] == 0:
                raise RuntimeError("The cooperative game is not fully loaded")
        else:
            time.sleep(0.8)
            after = (game.u32(LEVEL_FRAME_ADDR), game.u32(LEVEL_TIME_ADDR))
            if before[1] == 0 or before != after:
                raise RuntimeError(f"The game simulation is still advancing or not fully loaded (frame/time {before} -> {after}). Pause the solo game before restoring.")
        target = game.u32(WRITE_PTR)
        if target not in BUFFERS or target == current_address:
            raise RuntimeError("The game's inactive save buffer pointer is invalid")
        if game.u32(target + STATE_OFFSET) != 0:
            raise RuntimeError("The inactive save buffer is busy; pause and retry")
        image = bytearray(pieces["save.bin"])
        struct.pack_into("<I", image, 0, BUFFERS[target][0])
        struct.pack_into("<I", image, MEMFILE_SIZE, BUFFERS[target][1])
        validate_image(target, image)
        # Keep a reversible copy of the current checkpoint before process writes.
        backup = ARCHIVE / f"before-restore-{datetime.now():%Y%m%d-%H%M%S-%f}.bo1backup"
        snapshot(game, 0).replace(backup)
        try:
            for data, destination in zip((pieces["state.bin"], pieces["secondary.bin"]), BUFFERS[target]):
                game.write(destination, data)
            game.write(target, image)
            if game.read(target, SAVE_SIZE) != image:
                raise RuntimeError("Restored checkpoint could not be verified")
            if (game.u32(LEVEL_FRAME_ADDR), game.u32(LEVEL_TIME_ADDR)) != before:
                raise RuntimeError("The game resumed while restore was preparing the inactive buffer; no checkpoint was published")
            game.write(COMMITTED_FLAG, struct.pack("<I", 1))
            game.write(COMMITTED_PTR, struct.pack("<II", target, current_address))
            game.write(current_address + STATE_OFFSET, struct.pack("<I", 0))
        except BaseException:
            print(f"Restore failed. Previous in-memory checkpoint was saved at {backup}", file=sys.stderr)
            raise
    print(f"Restored {metadata['map']} round {metadata['round']} into memory.")
    print("Return to the game console and run: loadgame_continue")
    print("After loading, restart automatic saves with: python .\\checkpoint.py watch")
    print(f"Previous in-memory checkpoint: {backup}")


class RoundTracker:
    def __init__(self, start_round: int = 1):
        self.start_round = start_round
        self.scene = None
        self.round = None
        self.magic = None
        self.timer = None
        self.skipped = start_round > 1
        self.pending = None
        self.saved_round = None

    def update(self, scene: int | None, menu: int, timer: int, magic: int,
               now: float, observed_round: int | None = None):
        if observed_round is not None:
            if ((scene is not None and self.scene is not None and scene != self.scene)
                    or (self.round is not None and observed_round < self.round)):
                self.__init__(self.start_round)
            if scene is not None:
                self.scene = scene
            self.timer = timer
            if menu != 0 or timer <= START_TICKS.get(scene, 195):
                return None
            if self.round is None:
                # Attaching to a running map or returning from Continue is
                # not an end-of-round event.
                self.round = observed_round
                self.pending = None
                return None
            if observed_round > self.round:
                self.round = observed_round
                self.pending = (observed_round, now + 0.4)
            if self.pending and now >= self.pending[1]:
                round_number = self.pending[0]
                self.pending = None
                if round_number != self.saved_round:
                    return round_number
            return None
        if scene != self.scene or (self.timer is not None and timer + 100 < self.timer):
            self.__init__(self.start_round)
            self.scene = scene
        self.timer = timer
        if scene not in SCENES or menu != 0:
            self.pending = None
            return None
        if timer <= START_TICKS[scene]:
            self.magic = magic
            return None
        if self.round is None:
            self.round = self.start_round
            self.pending = None
        elif self.magic == 2000 and magic == 500:
            if self.skipped:
                self.round += 1
                self.pending = (self.round, now + 0.4)
            else:
                self.skipped = True
        self.magic = magic
        if self.pending and now >= self.pending[1]:
            round_number = self.pending[0]
            self.pending = None
            return round_number
        return None


class RoundEndTracker:
    """Detect the selected wave boundary without saving on first attach."""

    def __init__(self, timing: str = "End of Rounds",
                 baseline_round: int | None = None):
        if timing not in SAVE_TIMINGS:
            raise ValueError(f"Unknown auto save timing: {timing}")
        self.timing = timing
        self.scene = None
        self.round = baseline_round
        self.round_change = None
        self.active_since = None
        self.transition_armed = False
        self.transition_completed_round = None
        self.completed_round = None
        self.pending = None  # save label, completed round, due time, signal

    def update(self, scene: int | None, menu: int, timer: int,
               round_number: int | None, round_change: bool,
               now: float) -> tuple[int, int, str] | None:
        if (scene is not None and self.scene is not None and scene != self.scene):
            self.__init__(self.timing)
        if round_number is not None and self.round is not None and round_number < self.round:
            self.__init__(self.timing)
        if scene is not None:
            self.scene = scene
        inferred = round_number is None
        if inferred:
            round_number = self.round
        if round_number is None or menu != 0 or timer <= START_TICKS.get(scene, 195):
            self.active_since = None
            self.transition_armed = False
            self.transition_completed_round = None
            self.round_change = round_change
            return None

        previous_round = self.round
        previous_change = self.round_change
        if previous_round is None:
            self.round = round_number
        elif round_number > previous_round:
            # The counter advances after the end-of-round script. If the HUD
            # flag did not yield a save, use this transition as a fallback.
            if round_number > previous_round + 1:
                self.pending = None  # loadgame_continue, not a played round
            elif (self.completed_round != previous_round and
                  not round_change and previous_change is not True):
                delay = 0.5 if self.timing == "Start of Round" else 0.4
                self.pending = (round_number, previous_round, now + delay,
                                "round start" if self.timing == "Start of Round" else "round counter")
            self.round = round_number

        if round_change:
            completed_at_edge = (previous_round if previous_round is not None and
                                 round_number == previous_round + 1 else round_number)
            if (previous_change is False and self.active_since is not None
                    and now - self.active_since >= 5):
                self.transition_armed = True
                self.transition_completed_round = completed_at_edge
                if self.timing == "End of Rounds" and self.completed_round != completed_at_edge:
                    self.pending = (round_number, completed_at_edge, now + 0.1, "round end")
            self.active_since = None
        elif previous_change and self.transition_armed:
            # The transition flag clears after between_round_over. A loaded
            # game's round byte may stay zero, so advance our inferred round.
            completed = self.transition_completed_round or self.round
            if inferred:
                self.round += 1
            if self.completed_round != completed:
                if self.timing == "Round Transitions":
                    self.pending = (self.round, completed, now + 0.1,
                                    "round transition flag")
                elif self.timing == "Start of Round":
                    self.pending = (self.round, completed, now + 0.4,
                                    "round start flag")
            self.active_since = now
            self.transition_armed = False
            self.transition_completed_round = None
        elif previous_change is not False or self.active_since is None:
            self.active_since = now
            if previous_change:
                self.transition_armed = False
        self.round_change = round_change

        if (self.pending and now >= self.pending[2] and
                (self.timing != "Start of Round" or not round_change)):
            label, completed, _due, signal = self.pending
            if self.completed_round != completed:
                return label, completed, signal
            self.pending = None
        return None

    def mark_saved(self, completed_round: int):
        self.completed_round = completed_round
        self.pending = None

    def defer(self, now: float):
        if self.pending:
            label, completed, _due, signal = self.pending
            self.pending = (label, completed, now + 2, signal)


class CheckpointNotCommitted(RuntimeError):
    """The bound save key was sent, but the game did not commit a save."""


class SaveQueueUnblocker:
    """Recover memory checkpoints blocked by an abandoned devsave disk write."""

    def __init__(self):
        self.signature = None
        self.since = None
        self.first_frame = None

    def observe(self, game: GameProcess, now: float) -> bool:
        count = game.u32(SAVE_QUEUE_COUNT)
        pointer = game.u32(ASYNC_DISK_SAVE)
        if not 0 < count <= 3 or pointer not in BUFFERS:
            self.signature = self.since = self.first_frame = None
            return False
        if (game.u32(pointer + STATE_OFFSET) != 0 or
                game.read(pointer + CALLBACK_NOW_OFFSET, 1) != b"\0"):
            self.signature = self.since = self.first_frame = None
            return False
        ids = tuple(game.u32(SAVE_QUEUE + index * SAVE_REQUEST_SIZE + 0x180)
                    for index in range(count))
        signature = (pointer, ids)
        if signature != self.signature:
            self.signature, self.since = signature, now
            self.first_frame = game.u32(LEVEL_FRAME_ADDR)
            return False
        if now - self.since < 3 or game.u32(LEVEL_FRAME_ADDR) - self.first_frame < 20:
            return False
        with game.suspended():
            if (game.u32(ASYNC_DISK_SAVE) != pointer or
                    game.u32(pointer + STATE_OFFSET) != 0 or
                    game.read(pointer + CALLBACK_NOW_OFFSET, 1) != b"\0" or
                    game.u32(SAVE_QUEUE_COUNT) != count or
                    any(game.u32(SAVE_QUEUE + index * SAVE_REQUEST_SIZE + 0x180) != ids[index]
                        for index in range(count))):
                self.signature = self.since = self.first_frame = None
                return False
            for index in range(count):
                request = SAVE_QUEUE + index * SAVE_REQUEST_SIZE
                if (game.read(request, 64).split(b"\0", 1)[0] == b"1" and
                        game.u32(request + 0x184) == 1 and
                        game.u32(request + 0x188) == 6):
                    # The persistent archive needs only the memory commit.
                    # Avoid another asynchronous disk write blocking the queue.
                    game.write(request + 0x188, struct.pack("<I", 2))
            if game.u32(ASYNC_CALLBACK_SAVE) == pointer:
                game.write(ASYNC_CALLBACK_SAVE, struct.pack("<I", 0))
            game.write(ASYNC_DISK_SAVE, struct.pack("<I", 0))
        self.signature = self.since = self.first_frame = None
        return True


def wait_for_new_save(game: GameProcess, prior_id: int, timeout: float = 12,
                      prior_address: int | None = None):
    deadline = time.monotonic() + timeout
    unblocker = SaveQueueUnblocker()
    while time.monotonic() < deadline:
        try:
            address, _, h = committed(game)
            if h["save_id"] != prior_id or (prior_address in BUFFERS and address != prior_address):
                return
            if unblocker.observe(game, time.monotonic()):
                print("Cleared a stalled disk write; pending checkpoints can commit to memory.", flush=True)
        except RuntimeError:
            pass
        except OSError as error:
            if isinstance(error, PermissionError) or error.errno not in (299, 487, 998):
                raise
        time.sleep(0.25)
    raise CheckpointNotCommitted("F11 did not commit a checkpoint; check its binding and whether the map allows saving")


def request_fresh_checkpoint(game: GameProcess, prior_id: int, timeout: float = 12,
                             prior_address: int | None = None):
    game.press_save()
    wait_for_new_save(game, prior_id, timeout=timeout, prior_address=prior_address)


def live_round(game: GameProcess) -> int | None:
    """Read the current Zombies round from the retail game's round counter."""
    if game.u32(TIMER_ADDR) == 0 or game.u32(LEVEL_TIME_ADDR) == 0:
        return None
    number = game.read(ROUND_BYTE_ADDR, 1)[0]
    return number if number > 0 else None


def request_and_save(game: GameProcess, round_number: int | None = None,
                     target: Path | None = None):
    if round_number is None:
        round_number = live_round(game)
        if round_number is None:
            raise RuntimeError("Could not read the current Zombies round. Start a map and wait until it is playable.")
    try:
        prior_address, _, prior = committed(game)
        prior_id = prior["save_id"]
    except RuntimeError:
        prior_id = -1
        prior_address = None
    except OSError as error:
        if isinstance(error, PermissionError) or error.errno not in (299, 487, 998):
            raise
        # The first checkpoint after a map load can have valid buffer pointers
        # before the committed buffer itself is readable.
        prior_id = -1
        prior_address = None
    request_fresh_checkpoint(game, prior_id, prior_address=prior_address)
    saved = snapshot(game, round_number, target=target)
    print(f"Saved round {round_number}: {saved}", flush=True)
    return saved


def effective_scene(game: GameProcess, raw_scene: int) -> tuple[int | None, str | None]:
    if raw_scene in SCENES:
        return raw_scene, None
    # The LiveSplit scene address is -1 on some supported retail installs.
    # The committed engine checkpoint contains the actual map identity.
    try:
        _, _, header = committed(game)
    except (RuntimeError, OSError):
        return None, None
    return MAP_SCENES.get(header["map"]), header["map"]


def archived_round_for_header(map_name: str, save_id: int,
                              save_image: bytes | None = None) -> int | None:
    """Recover the round of a checkpoint resumed with an in-game Continue."""
    digest = hashlib.sha256(save_image).hexdigest() if save_image else None
    # Restore publishes an archive into the other engine buffer. Its two
    # memfile pointers change even though the saved game is otherwise equal.
    def portable_digest(image: bytes) -> bytes | None:
        if len(image) != SAVE_SIZE:
            return None
        return hashlib.sha256(image[4:MEMFILE_SIZE] +
                              image[MEMFILE_SIZE + 4:]).digest()

    portable = portable_digest(save_image) if save_image else None
    possible_rounds = set()
    archives = sorted(ARCHIVE.glob("*.bo1checkpoint"),
                      key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in archives:
        try:
            with zipfile.ZipFile(path) as archive:
                metadata = json.loads(archive.read("manifest.json"))
                if metadata.get("map") != map_name or metadata.get("save_id") != save_id:
                    continue
                number = metadata.get("round")
                if isinstance(number, int) and number > 0:
                    possible_rounds.add(number)
                    if digest is None or metadata.get("sha256", {}).get("save.bin") == digest:
                        return number
                    if portable is not None and portable_digest(
                            archive.read("save.bin")) == portable:
                        return number
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            continue
    return next(iter(possible_rounds)) if len(possible_rounds) == 1 else None


class LevelReloadTracker:
    """Notice a same-process loadgame_continue by the map clock rewinding."""

    def __init__(self):
        self.frame = None
        self.level_time = None

    def update(self, frame: int, level_time: int) -> bool:
        rewound = (self.frame is not None and
                   (frame + 20 < self.frame or level_time + 1000 < self.level_time))
        self.frame, self.level_time = frame, level_time
        return rewound


def watch(start_round: int | None = None, stop_event=None, on_event=None, save_lock=None,
          skip_initial_round: int | None = None, enable_recovery: bool = True,
          save_timing: str = "End of Rounds"):
    if save_timing not in SAVE_TIMINGS:
        raise ValueError(f"Unknown auto save timing: {save_timing}")
    print("Watching Black Ops rounds. Load checkpoint.cfg in the game; Ctrl+C stops.", flush=True)
    pid = None
    game = None
    tracker = RoundTracker(start_round or 1)
    tracker.saved_round = skip_initial_round
    end_tracker = RoundEndTracker(save_timing, start_round or skip_initial_round)
    resume_manual_after = (time.monotonic() + 5 if skip_initial_round is not None else 0)
    waiting_for_focus = None
    last_phase = None
    last_marker = None
    marker_ready = False
    last_round = None
    last_reported_round = None
    reload_tracker = LevelReloadTracker()
    reload_pending = False
    next_recovery = time.monotonic() + RECOVERY_INTERVAL
    unblocker = SaveQueueUnblocker()
    try:
        while stop_event is None or not stop_event.is_set():
            found = game_pid()
            if found != pid:
                if game:
                    try:
                        final_address, _, final_header = committed(game)
                        final_marker = (final_address, final_header["map"], final_header["save_id"])
                        if (last_round and time.monotonic() >= resume_manual_after and
                                final_marker != last_marker):
                            with save_lock if save_lock is not None else nullcontext():
                                final_path = snapshot(game, last_round)
                            if on_event:
                                on_event("manual", last_round, final_path)
                            RECOVERY_FILE.unlink(missing_ok=True)
                    except (OSError, RuntimeError):
                        pass  # an exited process usually cannot be read anymore
                    game.close()
                    try:
                        recovered = promote_recovery()
                        if recovered and on_event:
                            on_event("recovery", last_round, recovered)
                    except (OSError, RuntimeError, KeyError, zipfile.BadZipFile) as error:
                        if on_event:
                            on_event("error", f"Could not publish the recovery checkpoint: {error}", None)
                game = None
                pid = found
                tracker = RoundTracker(start_round or 1)
                tracker.saved_round = skip_initial_round
                end_tracker = RoundEndTracker(save_timing, start_round or skip_initial_round)
                waiting_for_focus = None
                last_phase = None
                last_marker = None
                marker_ready = False
                last_round = None
                last_reported_round = None
                reload_tracker = LevelReloadTracker()
                reload_pending = False
                next_recovery = time.monotonic() + RECOVERY_INTERVAL
                unblocker = SaveQueueUnblocker()
                if pid:
                    game = GameProcess(pid, write=True, suspend=True)
                    print(f"Attached to Black Ops process {pid}", flush=True)
                    print("Monitoring Zombies rounds and player F11 checkpoints.", flush=True)
                else:
                    print("Waiting for Black Ops...", flush=True)
            if game:
                round_number = None
                completed_round = None
                try:
                    raw_scene = game.u32(SCENE_ADDR)
                    menu = game.u32(MENU_ADDR)
                    timer = game.u32(TIMER_ADDR)
                    magic = game.u32(MAGIC_ADDR)
                    round_change = bool(game.read(ROUND_CHANGE_ADDR, 1)[0])
                    frame = game.u32(LEVEL_FRAME_ADDR)
                    level_time = game.u32(LEVEL_TIME_ADDR)
                    if reload_tracker.update(frame, level_time):
                        reload_pending = True
                        marker_ready = False
                        resume_manual_after = time.monotonic() + 5
                        print("Detected a same-process checkpoint reload; waiting for its round.",
                              flush=True)
                    scene, checkpoint_map = effective_scene(game, raw_scene)
                    if unblocker.observe(game, time.monotonic()):
                        print("Cleared a stalled disk write; pending checkpoints can commit to memory.", flush=True)
                    observed_round = live_round(game)
                    if reload_pending and scene is not None and menu == 0 and timer > START_TICKS[scene]:
                        try:
                            reload_address, reload_image, reload_header = committed(game)
                        except (RuntimeError, OSError):
                            pass
                        else:
                            resumed_round = (observed_round or archived_round_for_header(
                                reload_header["map"], reload_header["save_id"],
                                reload_image) or last_round or 1)
                            tracker = RoundTracker(resumed_round)
                            end_tracker = RoundEndTracker(save_timing, resumed_round)
                            skip_initial_round = resumed_round
                            last_marker = (reload_address, reload_header["map"],
                                           reload_header["save_id"])
                            marker_ready = True
                            last_round = resumed_round
                            last_reported_round = None
                            reload_pending = False
                            print(f"Resumed checkpoint round {resumed_round}; automatic saves rearmed.",
                                  flush=True)
                    current_round = observed_round or end_tracker.round or tracker.round
                    if current_round is not None:
                        last_round = current_round
                        if current_round != last_reported_round:
                            print(f"Watching round {current_round} (round-end flag={int(round_change)})", flush=True)
                            if on_event:
                                on_event("round_seen", current_round, None)
                            last_reported_round = current_round
                    if scene is None:
                        phase = (raw_scene, "scene")
                    elif menu != 0:
                        phase = (scene, "menu")
                    elif timer <= START_TICKS[scene]:
                        phase = (scene, "starting")
                    else:
                        phase = (scene, "tracking")
                    if phase != last_phase:
                        source = f", checkpoint_map={checkpoint_map}" if checkpoint_map else ""
                        print(f"Round detector: {phase[1]} (scene={raw_scene}, effective_scene={scene}, menu={menu}, timer={timer}, magic={magic}{source})", flush=True)
                        last_phase = phase
                    try:
                        current_address, _, current_header = committed(game)
                        marker = (current_address, current_header["map"], current_header["save_id"])
                    except (RuntimeError, OSError):
                        marker = None
                    if marker is None:
                        # The save buffers may be unmapped while Continue
                        # finishes. Do not turn their return into an F11 save.
                        pass
                    elif time.monotonic() < resume_manual_after:
                        # F12 can change the committed buffer while the saved
                        # round appears. That transition is not a player F11.
                        last_marker = marker
                        marker_ready = True
                    elif not marker_ready:
                        last_marker = marker
                        marker_ready = True
                    elif marker is not None and marker != last_marker and current_round is not None:
                        with save_lock if save_lock is not None else nullcontext():
                            manual_path = snapshot(game, current_round)
                        print(f"Captured player F11 save: {manual_path}", flush=True)
                        if on_event:
                            on_event("manual", current_round, manual_path)
                        last_marker = marker
                        tracker.round = current_round
                        tracker.saved_round = current_round
                        tracker.pending = None
                        next_recovery = time.monotonic() + RECOVERY_INTERVAL
                        RECOVERY_FILE.unlink(missing_ok=True)
                    now = time.monotonic()
                    end_candidate = end_tracker.update(scene, menu, timer,
                                                       observed_round, round_change, now)
                    if end_candidate:
                        round_number, completed_round, signal = end_candidate
                        if (now < resume_manual_after or
                                (skip_initial_round is not None and
                                 signal == "round counter" and
                                 round_number <= skip_initial_round)):
                            # Do not save a fresh-map transition while Continue
                            # is loading the selected checkpoint.
                            end_tracker.mark_saved(completed_round)
                            round_number = None
                        else:
                            print(f"Round {completed_round} ended ({signal}); requesting checkpoint", flush=True)
                            if on_event:
                                on_event("round_end", completed_round, None)
                    elif observed_round is None and start_round is not None:
                        fallback = tracker.update(scene, menu, timer, magic, now)
                        if fallback is not None:
                            completed_round = max(1, fallback - 1)
                            end_tracker.round = max(end_tracker.round or 0, fallback)
                            if (end_tracker.completed_round != completed_round and
                                    not (end_tracker.pending and end_tracker.pending[1] == completed_round) and
                                    now >= resume_manual_after):
                                round_number = (fallback if save_timing == "Start of Round"
                                                else completed_round)
                                print(f"Round {completed_round} ended (round magic); requesting checkpoint", flush=True)
                                if on_event:
                                    on_event("round_end", completed_round, None)
                    if round_number:
                        if game.foreground() or game.activate_window():
                            if save_lock is None:
                                saved = request_and_save(game, round_number)
                            else:
                                with save_lock:
                                    saved = request_and_save(game, round_number)
                            if on_event:
                                on_event("saved", round_number, saved)
                            tracker.saved_round = round_number
                            if completed_round is not None:
                                end_tracker.mark_saved(completed_round)
                            saved_address, _, saved_header = committed(game)
                            last_marker = (saved_address, saved_header["map"], saved_header["save_id"])
                            next_recovery = time.monotonic() + RECOVERY_INTERVAL
                            RECOVERY_FILE.unlink(missing_ok=True)
                            waiting_for_focus = None
                        else:
                            if waiting_for_focus != round_number:
                                print(f"Round {round_number} detected; return to Black Ops so F11 can save it.", flush=True)
                            waiting_for_focus = round_number
                            if completed_round is not None:
                                end_tracker.defer(time.monotonic())
                            else:
                                tracker.pending = (round_number, time.monotonic() + 1)
                    if (enable_recovery and observed_round is not None and menu == 0 and game.foreground()
                            and time.monotonic() >= next_recovery):
                        next_recovery = time.monotonic() + RECOVERY_INTERVAL
                        with save_lock if save_lock is not None else nullcontext():
                            request_and_save(game, observed_round, target=RECOVERY_FILE)
                        recovery_address, _, recovery_header = committed(game)
                        last_marker = (recovery_address, recovery_header["map"], recovery_header["save_id"])
                except (OSError, RuntimeError) as error:
                    if round_number is not None:
                        if completed_round is not None:
                            end_tracker.defer(time.monotonic())
                        else:
                            tracker.pending = (round_number, time.monotonic() + 2)
                    if isinstance(error, OSError) and error.errno == 5:
                        raise PermissionError("Black Ops denied memory access. Administrator access is required.") from error
                    print(f"Checkpoint error: {error}", file=sys.stderr, flush=True)
                    if on_event:
                        on_event("error", str(error), None)
            if stop_event is None:
                time.sleep(0.25)
            else:
                stop_event.wait(0.25)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        if game:
            game.close()


def elevated_command() -> str:
    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    command = (
        "$Host.UI.RawUI.WindowTitle = 'BO1 Checkpoint Companion'; "
        f"Set-Location -LiteralPath {quote(str(ROOT))}; "
        f"& {quote(sys.executable)} {quote(str(ROOT / 'checkpoint.py'))} "
        + " ".join(quote(arg) for arg in ("--elevated", *sys.argv[1:]))
    )
    return base64.b64encode(command.encode("utf-16le")).decode("ascii")


def launch_elevated():
    encoded = elevated_command()
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, ctypes.c_int]
    shell.ShellExecuteW.restype = ctypes.c_void_p
    result = shell.ShellExecuteW(None, "runas", "powershell.exe",
                                 f"-NoProfile -NoExit -EncodedCommand {encoded}",
                                 str(ROOT), 1)
    if not result or result <= 32:
        raise OSError(int(result or ctypes.get_last_error()),
                      "Windows did not open the Administrator PowerShell window")
    print("Administrator PowerShell opened. The watcher status will remain visible in that window.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="action", required=True)
    watcher = sub.add_parser("watch", help="request and persist a checkpoint at each detected round")
    watcher.add_argument("--resume-round", type=int,
                         help="legacy fallback if the live round counter is unavailable")
    watcher.add_argument("--save-timing", choices=SAVE_TIMINGS,
                         default=SAVE_TIMINGS[0], help="when to request each automatic checkpoint")
    sub.add_parser("save", help="request and persist one checkpoint now (game must have focus)")
    capture_cmd = sub.add_parser("capture", help="archive the game's already committed devsave without pressing a key")
    capture_cmd.add_argument("round", type=int, nargs="?",
                             help="optional override for the detected Zombies round")
    sub.add_parser("inspect", help="show the current save header without changing game memory")
    restore_cmd = sub.add_parser("restore", help="restore a checkpoint into a paused game on the same map")
    restore_cmd.add_argument("file", nargs="?", type=Path)
    restore_cmd.add_argument("--coop", action="store_true",
                             help="briefly suspend the host process for a cooperative restore")
    sub.add_parser("list", help="list saved memory checkpoints")
    args = parser.parse_args()
    try:
        if args.action == "list":
            for path in sorted(ARCHIVE.glob("*.bo1checkpoint"), reverse=True):
                metadata, _ = load_archive(path)
                print(f"{metadata['map']} round {metadata['round']}: {path}")
            return
        if args.action == "watch":
            if args.resume_round is not None and args.resume_round < 1:
                raise ValueError("--resume-round must be at least 1")
            watch(args.resume_round, save_timing=args.save_timing)
            return
        pid = game_pid()
        if not pid:
            raise RuntimeError("Start Black Ops and load the map first")
        game = GameProcess(pid, write=args.action in ("save", "restore"),
                           suspend=args.action == "save" or (args.action == "restore" and args.coop))
        try:
            if args.action == "save":
                print("Switch to Black Ops now; requesting a save in 5 seconds...", flush=True)
                time.sleep(5)
                request_and_save(game)
            elif args.action == "capture":
                round_number = args.round if args.round is not None else live_round(game)
                if round_number is None or round_number < 1:
                    raise ValueError("The current round must be at least 1")
                saved = snapshot(game, round_number)
                details, _ = load_archive(saved)
                print(f"Captured {details['map']} round {round_number}, save {details['filename']}, ID {details['save_id']}: {saved}")
            elif args.action == "inspect":
                address = game.u32(COMMITTED_PTR)
                if address not in BUFFERS:
                    raise RuntimeError(f"No committed save buffer at the expected address (0x{address:X})")
                image = game.read(address, SAVE_SIZE)
                details = header_info(image)
                details["save_address"] = f"0x{address:X}"
                details["state"] = game.u32(address + STATE_OFFSET)
                details["pause_signal"] = game.u32(PAUSED_ADDR)
                details["level_frame"] = game.u32(LEVEL_FRAME_ADDR)
                details["level_time"] = game.u32(LEVEL_TIME_ADDR)
                details["scene"] = game.u32(SCENE_ADDR)
                details["effective_scene"], details["checkpoint_map"] = effective_scene(game, details["scene"])
                details["menu"] = game.u32(MENU_ADDR)
                details["timer"] = game.u32(TIMER_ADDR)
                details["magic"] = game.u32(MAGIC_ADDR)
                details["round_byte"] = game.read(ROUND_BYTE_ADDR, 1)[0]
                details["round_change"] = game.read(ROUND_CHANGE_ADDR, 1)[0]
                print(json.dumps(details, indent=2))
            else:
                restore(game, args.file or latest_archive(), coop=args.coop)
        finally:
            game.close()
    except PermissionError as error:
        if sys.platform == "win32" and not args.elevated:
            try:
                launch_elevated()
                return
            except OSError as launch_error:
                parser.exit(1, f"Error: {launch_error}\n")
        parser.exit(1, f"Error: {error}\n")
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, KeyError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
