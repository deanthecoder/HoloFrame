"""Select an active Windows laptop panel without changing desktop settings."""

import ctypes as ct
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Display:
    """An active display in physical desktop pixels."""

    x: int
    y: int
    width: int
    height: int
    internal: bool = False


class _Luid(ct.Structure):
    _fields_ = [("low", ct.c_uint32), ("high", ct.c_int32)]


class _Source(ct.Structure):
    _fields_ = [("adapter", _Luid), ("id", ct.c_uint32),
                ("mode", ct.c_uint32), ("flags", ct.c_uint32)]


class _Target(ct.Structure):
    _fields_ = [("adapter", _Luid), ("id", ct.c_uint32),
                ("mode", ct.c_uint32), ("technology", ct.c_uint32),
                ("rotation", ct.c_uint32), ("scaling", ct.c_uint32),
                ("refresh_numerator", ct.c_uint32), ("refresh_denominator", ct.c_uint32),
                ("scanline", ct.c_uint32), ("available", ct.c_int32),
                ("flags", ct.c_uint32)]


class _Path(ct.Structure):
    _fields_ = [("source", _Source), ("target", _Target), ("flags", ct.c_uint32)]


class _SourceMode(ct.Structure):
    _fields_ = [("width", ct.c_uint32), ("height", ct.c_uint32),
                ("format", ct.c_uint32), ("x", ct.c_int32), ("y", ct.c_int32)]


class _ModeUnion(ct.Union):
    # DISPLAYCONFIG_TARGET_MODE occupies 48 bytes with 8-byte alignment.
    # Only the source-mode member is read; preserve the native union's layout.
    _fields_ = [("source", _SourceMode), ("target_storage", ct.c_uint64 * 6)]


class _Mode(ct.Structure):
    _fields_ = [("type", ct.c_uint32), ("id", ct.c_uint32),
                ("adapter", _Luid), ("data", _ModeUnion)]


def active_displays() -> list[Display]:
    """Read active Windows display paths; other platforms use Panda's default."""
    if sys.platform != "win32":
        return []
    user32 = ct.WinDLL("user32")
    # Request physical coordinates before Panda creates its first window.
    user32.SetProcessDpiAwarenessContext.argtypes = [ct.c_void_p]
    user32.SetProcessDpiAwarenessContext(ct.c_void_p(-4))
    size = user32.GetDisplayConfigBufferSizes
    size.argtypes = [ct.c_uint32, ct.POINTER(ct.c_uint32), ct.POINTER(ct.c_uint32)]
    query = user32.QueryDisplayConfig
    query.argtypes = [ct.c_uint32, ct.POINTER(ct.c_uint32), ct.POINTER(_Path),
                      ct.POINTER(ct.c_uint32), ct.POINTER(_Mode), ct.c_void_p]
    for _ in range(3):
        path_count, mode_count = ct.c_uint32(), ct.c_uint32()
        status = size(2, ct.byref(path_count), ct.byref(mode_count))  # QDC_ONLY_ACTIVE_PATHS
        if status:
            raise ct.WinError(status)
        paths, modes = (_Path * path_count.value)(), (_Mode * mode_count.value)()
        status = query(2, ct.byref(path_count), paths, ct.byref(mode_count), modes, None)
        if status == 122:  # Topology changed between sizing and reading.
            continue
        if status:
            raise ct.WinError(status)
        displays = {}
        for path in paths[:path_count.value]:
            if not path.target.available or path.source.mode >= mode_count.value:
                continue
            mode = modes[path.source.mode]
            if mode.type != 1:
                continue
            source = mode.data.source
            if not source.width or not source.height:
                continue
            bounds = (source.x, source.y, source.width, source.height)
            # LVDS, embedded DisplayPort/UDI, and INTERNAL denote built-in panels.
            internal = path.target.technology in (6, 11, 13, 0x80000000)
            previous = displays.get(bounds)
            displays[bounds] = Display(*bounds, internal or bool(previous and previous.internal))
        return sorted(displays.values(), key=lambda d: (d.x, d.y))
    raise RuntimeError("Display configuration kept changing during startup")


def select_display(displays: list[Display], index: int | None = None) -> Display | None:
    """Prefer an explicit index, then the laptop panel, then the primary display."""
    if index is not None:
        if not 0 <= index < len(displays):
            raise ValueError(f"monitor_index must be between 0 and {len(displays) - 1}")
        return displays[index]
    return next((d for d in displays if d.internal),
                next((d for d in displays if d.x == 0 and d.y == 0),
                     displays[0] if displays else None))
