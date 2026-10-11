"""Reject Windows alternate data streams before replacing original files."""

import ctypes
from pathlib import Path
import sys

from .vault import VaultError

ERROR_HANDLE_EOF = 38
ERROR_INVALID_PARAMETER = 87
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class StreamData(ctypes.Structure):
    _fields_ = [("StreamSize", ctypes.c_int64), ("cStreamName", ctypes.c_wchar * 296)]


class StreamAPI:
    def __init__(self):
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.first = kernel32.FindFirstStreamW
        self.first.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.POINTER(StreamData),
            ctypes.c_uint32,
        ]
        self.first.restype = ctypes.c_void_p
        self.next = kernel32.FindNextStreamW
        self.next.argtypes = [ctypes.c_void_p, ctypes.POINTER(StreamData)]
        self.next.restype = ctypes.c_int
        self.close = kernel32.FindClose
        self.close.argtypes = [ctypes.c_void_p]
        self.close.restype = ctypes.c_int
        self.last_error = ctypes.get_last_error


def has_alternate_streams(path, api=None):
    """Inspect names and sizes, never stream contents. Tests may inject an API."""
    if sys.platform != "win32" and api is None:
        return False
    api = StreamAPI() if api is None else api
    entry = StreamData()
    handle = api.first(str(Path(path).absolute()), 0, ctypes.byref(entry), 0)
    if handle == INVALID_HANDLE_VALUE:
        error = api.last_error()
        # Documented: no streams, or filesystem does not support streams (e.g. FAT).
        if error in (ERROR_HANDLE_EOF, ERROR_INVALID_PARAMETER):
            return False
        raise VaultError(
            f"Cannot check Windows file streams ({error}). Originals were not changed."
        )
    if handle is None:
        raise VaultError("Invalid Windows stream search handle. Originals were not changed.")
    try:
        for _ in range(1024):
            # Reject named streams even when empty; only the ordinary data fork is archived.
            if entry.cStreamName != "::$DATA":
                return True
            if not api.next(handle, ctypes.byref(entry)):
                error = api.last_error()
                if error == ERROR_HANDLE_EOF:
                    return False
                raise VaultError(
                    f"Cannot finish checking Windows file streams ({error}). Originals were not changed."
                )
        raise VaultError("Too many Windows file streams. Originals were not changed.")
    finally:
        if not api.close(handle):
            raise VaultError("Cannot close Windows stream search. Originals were not changed.")
