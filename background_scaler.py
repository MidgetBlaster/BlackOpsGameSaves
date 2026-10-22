"""Resize the lobby PNG with Windows GDI+ for a Tkinter photo background."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path
import sys


PIXEL_FORMAT_32BPP_ARGB = 0x26200A
IMAGE_LOCK_MODE_READ = 1
INTERPOLATION_HIGH_QUALITY_BICUBIC = 7


class _StartupInput(ctypes.Structure):
    _fields_ = [("version", wintypes.UINT), ("debug_callback", ctypes.c_void_p),
                ("suppress_background_thread", wintypes.BOOL),
                ("suppress_external_codecs", wintypes.BOOL)]


class _Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int),
                ("width", ctypes.c_int), ("height", ctypes.c_int)]


class _BitmapData(ctypes.Structure):
    _fields_ = [("width", wintypes.UINT), ("height", wintypes.UINT),
                ("stride", ctypes.c_int), ("pixel_format", ctypes.c_int),
                ("scan0", ctypes.c_void_p), ("reserved", ctypes.c_size_t)]


def resized_ppm(path: Path, width: int, height: int) -> bytes:
    """Return a smoothly resized PPM that Tk can load without Pillow."""
    if sys.platform != "win32":
        raise OSError("Windows GDI+ is required for background scaling")
    if width < 1 or height < 1 or width > 8192 or height > 8192:
        raise ValueError("Invalid background size")
    dll = ctypes.WinDLL("gdiplus", use_last_error=True)
    ptr = ctypes.c_void_p
    dll.GdiplusStartup.argtypes = [ctypes.POINTER(ctypes.c_size_t),
                                   ctypes.POINTER(_StartupInput), ptr]
    dll.GdiplusStartup.restype = ctypes.c_int
    dll.GdipCreateBitmapFromFile.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ptr)]
    dll.GdipCreateBitmapFromFile.restype = ctypes.c_int
    dll.GdipCreateBitmapFromScan0.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                              ctypes.c_int, ptr, ctypes.POINTER(ptr)]
    dll.GdipCreateBitmapFromScan0.restype = ctypes.c_int
    dll.GdipGetImageGraphicsContext.argtypes = [ptr, ctypes.POINTER(ptr)]
    dll.GdipGetImageGraphicsContext.restype = ctypes.c_int
    dll.GdipSetInterpolationMode.argtypes = [ptr, ctypes.c_int]
    dll.GdipSetInterpolationMode.restype = ctypes.c_int
    dll.GdipDrawImageRectI.argtypes = [ptr, ptr, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int]
    dll.GdipDrawImageRectI.restype = ctypes.c_int
    dll.GdipBitmapLockBits.argtypes = [ptr, ctypes.POINTER(_Rect), ctypes.c_uint,
                                       ctypes.c_int, ctypes.POINTER(_BitmapData)]
    dll.GdipBitmapLockBits.restype = ctypes.c_int
    dll.GdipBitmapUnlockBits.argtypes = [ptr, ctypes.POINTER(_BitmapData)]
    dll.GdipBitmapUnlockBits.restype = ctypes.c_int
    dll.GdipDisposeImage.argtypes = [ptr]
    dll.GdipDeleteGraphics.argtypes = [ptr]
    dll.GdiplusShutdown.argtypes = [ctypes.c_size_t]

    def check(status: int, operation: str):
        if status:
            raise OSError(f"GDI+ {operation} failed ({status})")

    token = ctypes.c_size_t()
    check(dll.GdiplusStartup(ctypes.byref(token), ctypes.byref(_StartupInput(1, None, 0, 0)),
                             None), "startup")
    source = ptr()
    target = ptr()
    graphics = ptr()
    bitmap_data = _BitmapData()
    locked = False
    try:
        check(dll.GdipCreateBitmapFromFile(str(path), ctypes.byref(source)), "open PNG")
        check(dll.GdipCreateBitmapFromScan0(width, height, 0, PIXEL_FORMAT_32BPP_ARGB,
                                            None, ctypes.byref(target)), "create bitmap")
        check(dll.GdipGetImageGraphicsContext(target, ctypes.byref(graphics)), "graphics")
        check(dll.GdipSetInterpolationMode(graphics, INTERPOLATION_HIGH_QUALITY_BICUBIC),
              "interpolation")
        check(dll.GdipDrawImageRectI(graphics, source, 0, 0, width, height), "draw image")
        rect = _Rect(0, 0, width, height)
        check(dll.GdipBitmapLockBits(target, ctypes.byref(rect), IMAGE_LOCK_MODE_READ,
                                     PIXEL_FORMAT_32BPP_ARGB, ctypes.byref(bitmap_data)),
              "read pixels")
        locked = True
        stride = bitmap_data.stride
        base = (bitmap_data.scan0 if stride > 0 else
                bitmap_data.scan0 + (height - 1) * stride)
        pixels = ctypes.string_at(base, abs(stride) * height)
        rgb = bytearray(width * height * 3)
        for y in range(height):
            source_row = y * stride if stride > 0 else (height - 1 - y) * -stride
            output_row = y * width * 3
            for x in range(width):
                index = source_row + x * 4
                output = output_row + x * 3
                rgb[output] = pixels[index + 2]
                rgb[output + 1] = pixels[index + 1]
                rgb[output + 2] = pixels[index]
        return f"P6\n{width} {height}\n255\n".encode("ascii") + rgb
    finally:
        if locked:
            dll.GdipBitmapUnlockBits(target, ctypes.byref(bitmap_data))
        if graphics:
            dll.GdipDeleteGraphics(graphics)
        if target:
            dll.GdipDisposeImage(target)
        if source:
            dll.GdipDisposeImage(source)
        dll.GdiplusShutdown(token)
