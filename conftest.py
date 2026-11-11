"""Общие фикстуры тестов всех лабораторных."""

import ctypes
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest


@contextmanager
def _hold_file(path: Path):
    """Держит файл открытым без общего доступа — так его держит Excel."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                     ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel32.CreateFileW(str(path), 0xC0000000, 0, None, 3, 0x80, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), f"не удалось занять {path}")
    try:
        yield
    finally:
        kernel32.CloseHandle(handle)


@pytest.fixture
def opened_in_excel():
    """``with opened_in_excel(path): ...`` — файл занят другой программой."""
    if sys.platform != "win32":
        pytest.skip("занятый файл проверяется только в Windows")
    return _hold_file
