"""Apply borderless styling to the retail Black Ops game window."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import time


GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
MONITOR_DEFAULTTONEAREST = 2
HWND_NOTOPMOST = -2


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


def _user():
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowVisible.restype = wintypes.BOOL
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user.GetWindowRect.restype = wintypes.BOOL
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowLongW.restype = ctypes.c_long
    user.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user.SetWindowLongW.restype = ctypes.c_long
    user.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user.MonitorFromWindow.restype = wintypes.HANDLE
    user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user.GetMonitorInfoW.restype = wintypes.BOOL
    user.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user.SetWindowPos.restype = wintypes.BOOL
    return user


@contextmanager
def _physical_pixels(user):
    """Keep monitor and window coordinates in the same DPI coordinate space."""
    try:
        set_context = user.SetThreadDpiAwarenessContext
    except AttributeError:
        yield
        return
    set_context.argtypes = [wintypes.HANDLE]
    set_context.restype = wintypes.HANDLE
    previous = set_context(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    try:
        yield
    finally:
        if previous:
            set_context(previous)


def game_window(pid: int, user=None) -> int:
    """Pick the largest visible top-level window belonging to Black Ops."""
    user = user or _user()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    candidates = []

    @callback_type
    def visit(hwnd, _unused):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user.IsWindowVisible(hwnd):
            rect = RECT()
            if user.GetWindowRect(hwnd, ctypes.byref(rect)):
                area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
                if area:
                    candidates.append((area, hwnd))
        return True

    user.EnumWindows(visit, 0)
    if not candidates:
        raise RuntimeError("Black Ops has no visible game window yet")
    return max(candidates)[1]


def _monitor_rect(hwnd: int, user) -> RECT:
    monitor = user.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not user.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return info.rcMonitor


def is_fullscreen(pid: int, user=None) -> bool:
    user = user or _user()
    hwnd = game_window(pid, user)
    return bool(user.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def is_borderless(pid: int, user=None) -> bool:
    user = user or _user()
    with _physical_pixels(user):
        hwnd = game_window(pid, user)
        style = user.GetWindowLongW(hwnd, GWL_STYLE)
        if style & WS_POPUP == 0 or user.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST:
            return False
        actual = RECT()
        if not user.GetWindowRect(hwnd, ctypes.byref(actual)):
            raise ctypes.WinError(ctypes.get_last_error())
        monitor = _monitor_rect(hwnd, user)
        return (actual.left, actual.top, actual.right, actual.bottom) == (
            monitor.left, monitor.top, monitor.right, monitor.bottom)


def wait_for_windowed(pid: int, timeout: float = 12.0) -> None:
    deadline = time.monotonic() + timeout
    consecutive = 0
    while time.monotonic() < deadline:
        try:
            user = _user()
            hwnd = game_window(pid, user)
            windowed = not (user.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
            windowed &= not (user.GetWindowLongW(hwnd, GWL_STYLE) & WS_POPUP)
            consecutive = consecutive + 1 if windowed else 0
            if consecutive >= 3:
                return
        except RuntimeError:
            consecutive = 0
            pass  # vid_restart can briefly replace the game window
        time.sleep(0.2)
    raise RuntimeError("Black Ops did not switch to windowed mode. Check the F7 binding.")


def wait_for_fullscreen(pid: int, timeout: float = 12.0) -> None:
    deadline = time.monotonic() + timeout
    consecutive = 0
    while time.monotonic() < deadline:
        try:
            consecutive = consecutive + 1 if is_fullscreen(pid) else 0
            if consecutive >= 3:
                return
        except RuntimeError:
            consecutive = 0
            pass
        time.sleep(0.2)
    raise RuntimeError("Black Ops did not switch to fullscreen. Check the F6 binding.")


def make_borderless(pid: int) -> None:
    """Size the window to its monitor and remove its frame without touching save data."""
    user = _user()
    with _physical_pixels(user):
        hwnd = game_window(pid, user)
        if user.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST:
            raise RuntimeError("Black Ops is still in fullscreen mode")
        monitor = _monitor_rect(hwnd, user)
        ctypes.set_last_error(0)
        old_style = user.SetWindowLongW(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE)
        if old_style == 0 and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.set_last_error(0)
        old_exstyle = user.SetWindowLongW(hwnd, GWL_EXSTYLE, 0)
        if old_exstyle == 0 and ctypes.get_last_error():
            raise ctypes.WinError(ctypes.get_last_error())
        width = monitor.right - monitor.left
        height = monitor.bottom - monitor.top
        if not user.SetWindowPos(hwnd, HWND_NOTOPMOST, monitor.left, monitor.top,
                                 width, height, SWP_FRAMECHANGED | SWP_SHOWWINDOW):
            raise ctypes.WinError(ctypes.get_last_error())
    if not is_borderless(pid, user):
        raise RuntimeError("Windows did not apply the borderless window style")
