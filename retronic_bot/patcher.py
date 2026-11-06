"""Budowanie i aplikowanie zmiany light hacka."""

from .config import PATCH_LENGTH
from .memory import patch_code, read_memory


def build_patch():
    # drawLights = 1; minimumAmbientLight = 1.0f
    patch = bytearray()
    patch += bytes.fromhex("c6 83 d4 01 00 00 01")
    patch += bytes.fromhex("c7 83 d8 01 00 00 00 00 80 3f")
    patch += b"\x90" * (PATCH_LENGTH - len(patch))
    return bytes(patch)


def apply_light_patch(handle, address):
    current = read_memory(handle, address, PATCH_LENGTH)
    if current is None:
        raise RuntimeError("Nie można odczytać bloku renderera.")
    if current == build_patch():
        return "already_active"
    patch = build_patch()
    patch_code(handle, address, patch)
    if read_memory(handle, address, PATCH_LENGTH) != patch:
        raise RuntimeError("Weryfikacja patcha nieudana.")
    return "applied"

