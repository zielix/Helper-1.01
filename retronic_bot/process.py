"""Wyszukiwanie procesu RetronicDX i jego modułu głównego."""

import ctypes
import ctypes.wintypes as wt
import subprocess

from .config import LIST_MODULES_ALL, PROCESS_ACCESS, PROCESS_PREFIX, PROCESS_VM_READ
from .memory import CloseHandle, OpenProcess

psapi = ctypes.WinDLL("psapi", use_last_error=True)
EnumProcessModulesEx = psapi.EnumProcessModulesEx
EnumProcessModulesEx.argtypes = [
    wt.HANDLE, ctypes.POINTER(wt.HMODULE), wt.DWORD,
    ctypes.POINTER(wt.DWORD), wt.DWORD,
]
EnumProcessModulesEx.restype = wt.BOOL
GetModuleFileNameExW = psapi.GetModuleFileNameExW
GetModuleFileNameExW.argtypes = [wt.HANDLE, wt.HMODULE, wt.LPWSTR, wt.DWORD]
GetModuleFileNameExW.restype = wt.DWORD


def find_process(access=PROCESS_ACCESS):
    output = subprocess.check_output(
        ["tasklist", "/FO", "CSV", "/NH"], text=True, errors="ignore"
    )
    for line in output.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) < 2 or not parts[0].lower().startswith(PROCESS_PREFIX.lower()):
            continue
        pid = int(parts[1])
        handle = OpenProcess(access, False, pid)
        if not handle:
            continue
        if not access & PROCESS_VM_READ:
            # Bez prawa odczytu nie da się wyliczyć modułów; wystarcza sam PID.
            return pid, handle, None, None
        modules = (wt.HMODULE * 4096)()
        needed = wt.DWORD()
        if not EnumProcessModulesEx(
            handle, modules, ctypes.sizeof(modules), ctypes.byref(needed), LIST_MODULES_ALL
        ):
            CloseHandle(handle)
            continue
        count = min(needed.value // ctypes.sizeof(wt.HMODULE), len(modules))
        for i in range(count):
            name = ctypes.create_unicode_buffer(520)
            if not GetModuleFileNameExW(handle, modules[i], name, len(name)):
                continue
            full_path = name.value
            filename = full_path.replace("/", "\\").rsplit("\\", 1)[-1]
            if filename.lower().startswith(PROCESS_PREFIX.lower()):
                base = ctypes.cast(modules[i], ctypes.c_void_p).value
                return pid, handle, base, full_path
        CloseHandle(handle)
    return None, None, None, None

