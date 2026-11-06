"""Odczyt podstawowych informacji PE z pliku modułu."""

import struct
from pathlib import Path


def parse_text_section(path):
    data = Path(path).read_bytes()
    if data[:2] != b"MZ":
        raise RuntimeError("Moduł nie jest PE.")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise RuntimeError("Nieprawidłowy nagłówek PE.")
    section_count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_header_size = struct.unpack_from("<H", data, pe + 20)[0]
    section_table = pe + 24 + optional_header_size
    for i in range(section_count):
        offset = section_table + 40 * i
        name = data[offset:offset + 8].rstrip(b"\0").decode("ascii", errors="ignore")
        virtual_size, virtual_address, raw_size, _ = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        if name == ".text":
            return virtual_address, max(virtual_size, raw_size)
    raise RuntimeError("Nie znaleziono sekcji .text.")

