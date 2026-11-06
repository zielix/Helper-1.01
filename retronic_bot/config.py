"""Konfiguracja i stałe dotyczące obsługi klienta."""

PROCESS_PREFIX = "RetronicDX"

# Sygnatura bloku renderowania; adres globalnej flagi jest wildcardem.
SIGNATURE = bytes.fromhex(
    "8B 0D 00 00 00 00 "
    "33 C0 83 E1 02 0B C1 74 11 "
    "C6 83 D4 01 00 00 01 "
    "C7 83 D8 01 00 00 00 00 00 00 "
    "8B 7D 08"
)
SIGNATURE_MASK = "xx????" + "x" * (len(SIGNATURE) - 6)
PATCH_LENGTH = 0x20
SCAN_CHUNK_SIZE = 0x20000
PROCESS_ACCESS = 0x0008 | 0x0010 | 0x0020 | 0x0400
# Funkcje pikselowe potrzebują uchwytu tylko do sprawdzenia, czy klient działa:
# bez prawa odczytu ani zapisu pamięci (PROCESS_QUERY_LIMITED_INFORMATION).
STATUS_PROCESS_ACCESS = 0x1000
PROCESS_VM_READ = 0x0010

PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100
PAGE_NOACCESS = 0x01
MEM_COMMIT = 0x1000
LIST_MODULES_ALL = 0x03

