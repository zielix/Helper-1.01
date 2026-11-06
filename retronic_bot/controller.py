"""Stan i przełączanie funkcji light hacka dla interfejsu."""

import ctypes
import ctypes.wintypes as wt

from .config import PATCH_LENGTH
from .memory import CloseHandle, GetExitCodeProcess, patch_code, read_memory
from .patcher import build_patch
from .pe import parse_text_section
from .process import find_process
from .scanner import scan_module_text


class LightHackController:
    def __init__(self):
        self.handle = None
        self.address = None
        self.original_bytes = None
        self.pid = None

    @property
    def enabled(self):
        return self.handle is not None

    def enable(self):
        if self.enabled:
            return self.pid

        pid, handle, base, module_path = find_process()
        if not handle:
            raise RuntimeError("Nie znaleziono uruchomionego klienta RetronicDX.")

        try:
            text_rva, text_size = parse_text_section(module_path)
            hits = scan_module_text(handle, base, text_rva, text_size)
            if not hits:
                raise RuntimeError(
                    "Nie znaleziono sygnatury renderera w sekcji .text. "
                    "Jeśli light hack był już wcześniej włączony, zamknij i uruchom "
                    "klienta ponownie — poprzedni patch nadpisuje bajty sygnatury. "
                    "Jeśli to świeżo uruchomiony klient, jego kompilacja może różnić "
                    "się od tej, dla której przygotowano sygnaturę."
                )
            if len(hits) > 1:
                raise RuntimeError(
                    f"Znaleziono {len(hits)} pasujące bloki; patchowanie zostało przerwane."
                )

            address = hits[0]
            original = read_memory(handle, address, PATCH_LENGTH)
            if original is None:
                raise RuntimeError("Nie można odczytać oryginalnych bajtów klienta.")
            patch = build_patch()
            if original == patch:
                raise RuntimeError(
                    "Patch jest już aktywny. Zamknij klienta i uruchom go ponownie, "
                    "aby używać przełącznika z tego okna."
                )

            patch_code(handle, address, patch)
            if read_memory(handle, address, PATCH_LENGTH) != patch:
                # Przywróć blok, jeśli zapis nie przeszedł weryfikacji.
                patch_code(handle, address, original)
                raise RuntimeError("Weryfikacja patcha nie powiodła się.")

            self.handle = handle
            self.address = address
            self.original_bytes = original
            self.pid = pid
            return pid
        except Exception:
            CloseHandle(handle)
            raise

    def disable(self):
        if not self.enabled:
            return

        exit_code = wt.DWORD()
        if GetExitCodeProcess(self.handle, ctypes.byref(exit_code)) and exit_code.value != 259:
            # Proces klienta już nie działa, więc nie ma pamięci, którą trzeba przywracać.
            self._release_handle()
            return "process_closed"

        patch = build_patch()
        current = read_memory(self.handle, self.address, PATCH_LENGTH)
        if current is None:
            raise RuntimeError("Nie można odczytać pamięci klienta; patch pozostał aktywny.")
        if current != patch:
            raise RuntimeError(
                "Kod klienta zmienił się od czasu włączenia. Nie przywróciłem bajtów, "
                "aby nie nadpisać tej zmiany."
            )

        patch_code(self.handle, self.address, self.original_bytes)
        if read_memory(self.handle, self.address, PATCH_LENGTH) != self.original_bytes:
            raise RuntimeError("Nie udało się potwierdzić przywrócenia oryginalnego kodu.")

        self._release_handle()
        return "restored"

    def _release_handle(self):
        CloseHandle(self.handle)
        self.handle = None
        self.address = None
        self.original_bytes = None
        self.pid = None

    def close(self):
        """Przy zamykaniu okna spróbuj przywrócić klienta."""
        if self.enabled:
            self.disable()

