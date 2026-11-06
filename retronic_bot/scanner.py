"""Skanowanie sekcji .text za pomocą sygnatury bajtowej."""

import ctypes

from .config import MEM_COMMIT, SCAN_CHUNK_SIZE, SIGNATURE, SIGNATURE_MASK
from .memory import MEMORY_BASIC_INFORMATION, VirtualQueryEx, read_memory, region_readable


def masked_find(data, signature, mask):
    matches = []
    length = len(signature)
    if len(data) < length:
        return matches
    for i in range(len(data) - length + 1):
        if all(ch != "x" or data[i + j] == signature[j] for j, ch in enumerate(mask)):
            matches.append(i)
    return matches


def scan_module_text(handle, base, text_rva, text_size):
    start = base + text_rva
    end = start + text_size
    hits = []
    address = start
    overlap = len(SIGNATURE) - 1
    tail = b""
    while address < end:
        mbi = MEMORY_BASIC_INFORMATION()
        if not VirtualQueryEx(
            handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi)
        ):
            address += 0x1000
            continue
        region_base = ctypes.cast(mbi.BaseAddress, ctypes.c_void_p).value
        region_end = region_base + mbi.RegionSize
        lo, hi = max(address, start), min(region_end, end)
        if lo < hi and mbi.State == MEM_COMMIT and region_readable(mbi.Protect):
            pos = lo
            while pos < hi:
                size = min(SCAN_CHUNK_SIZE, hi - pos)
                blob = read_memory(handle, pos, size)
                if blob is None:
                    pos += size
                    tail = b""
                    continue
                data = tail + blob
                data_base = pos - len(tail)
                for relative in masked_find(data, SIGNATURE, SIGNATURE_MASK):
                    hit = data_base + relative
                    if start <= hit < end:
                        hits.append(hit)
                tail = data[-overlap:] if len(data) >= overlap else data
                pos += size
            tail = b""
        address = max(region_end, address + 0x1000)
    return sorted(set(hits))

