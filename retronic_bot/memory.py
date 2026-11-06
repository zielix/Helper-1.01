"""Niskopoziomowe operacje pamięci procesu Windows."""

import ctypes
import ctypes.wintypes as wt

from .config import (
    MEM_COMMIT,
    PAGE_EXECUTE_READ,
    PAGE_EXECUTE_READWRITE,
    PAGE_EXECUTE_WRITECOPY,
    PAGE_GUARD,
    PAGE_NOACCESS,
)


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", wt.LPVOID),
        ("AllocationBase", wt.LPVOID),
        ("AllocationProtect", wt.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Protect", wt.DWORD),
        ("Type", wt.DWORD),
    ]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
OpenProcess = k32.OpenProcess
OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
OpenProcess.restype = wt.HANDLE
CloseHandle = k32.CloseHandle
CloseHandle.argtypes = [wt.HANDLE]
CloseHandle.restype = wt.BOOL
GetExitCodeProcess = k32.GetExitCodeProcess
GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
GetExitCodeProcess.restype = wt.BOOL
ReadProcessMemory = k32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    wt.HANDLE, wt.LPCVOID, wt.LPVOID, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
ReadProcessMemory.restype = wt.BOOL
WriteProcessMemory = k32.WriteProcessMemory
WriteProcessMemory.argtypes = [
    wt.HANDLE, wt.LPVOID, wt.LPCVOID, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
WriteProcessMemory.restype = wt.BOOL
VirtualProtectEx = k32.VirtualProtectEx
VirtualProtectEx.argtypes = [
    wt.HANDLE, wt.LPVOID, ctypes.c_size_t, wt.DWORD,
    ctypes.POINTER(wt.DWORD),
]
VirtualProtectEx.restype = wt.BOOL
FlushInstructionCache = k32.FlushInstructionCache
FlushInstructionCache.argtypes = [wt.HANDLE, wt.LPCVOID, ctypes.c_size_t]
FlushInstructionCache.restype = wt.BOOL
VirtualQueryEx = k32.VirtualQueryEx
VirtualQueryEx.argtypes = [
    wt.HANDLE, wt.LPCVOID, ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
VirtualQueryEx.restype = ctypes.c_size_t


def read_memory(handle, address, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    if not ReadProcessMemory(
        handle, ctypes.c_void_p(address), buf, size, ctypes.byref(got)
    ):
        return None
    return buf.raw[:got.value]


def write_memory(handle, address, payload):
    written = ctypes.c_size_t()
    buf = ctypes.create_string_buffer(payload)
    if not WriteProcessMemory(
        handle, ctypes.c_void_p(address), buf, len(payload), ctypes.byref(written)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if written.value != len(payload):
        raise RuntimeError(f"Zapisano {written.value}/{len(payload)} bajtów.")


def patch_code(handle, address, payload):
    old_protect = wt.DWORD()
    if not VirtualProtectEx(
        handle, ctypes.c_void_p(address), len(payload),
        PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        write_memory(handle, address, payload)
        FlushInstructionCache(handle, ctypes.c_void_p(address), len(payload))
    finally:
        restored = wt.DWORD()
        VirtualProtectEx(
            handle, ctypes.c_void_p(address), len(payload),
            old_protect.value, ctypes.byref(restored)
        )


def region_readable(protect):
    if protect & (PAGE_GUARD | PAGE_NOACCESS):
        return False
    return protect in {
        0x02, 0x04, 0x08,
        PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY,
        0x01 | PAGE_EXECUTE_READ,
    } or bool(protect & (PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))

