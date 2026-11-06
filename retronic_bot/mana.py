"""Read the current mana value from a selected on-screen text region."""

import os
import re
import shutil
import subprocess

from .battle import capture_region


def find_tesseract():
    """Find the Tesseract OCR executable or raise an actionable error."""
    executable = shutil.which("tesseract")
    if executable:
        return executable

    candidates = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                     "Tesseract-OCR", "tesseract.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     "Tesseract-OCR", "tesseract.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                     "Tesseract-OCR", "tesseract.exe"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    raise RuntimeError(
        "Nie znaleziono Tesseract OCR. Zainstaluj Tesseract i dodaj "
        "tesseract.exe do PATH; szczegóły są w README.md."
    )


def read_current_mana(target_pid, region):
    """Return the first OCR-recognized integer in the selected mana text region."""
    frame = capture_region(target_pid, region, grayscale=False)
    if frame is None:
        return None

    import cv2
    import numpy

    gray = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
    enlarged = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(
        enlarged, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )
    if numpy.count_nonzero(binary) < binary.size // 2:
        binary = cv2.bitwise_not(binary)
    success, encoded = cv2.imencode(".png", binary)
    if not success:
        raise RuntimeError("Nie udało się przygotować obrazu many do OCR.")

    result = subprocess.run(
        [
            find_tesseract(),
            "stdin",
            "stdout",
            "--psm",
            "7",
            "-c",
            "tessedit_char_whitelist=0123456789/",
        ],
        input=encoded.tobytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        details = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(details or "Tesseract OCR nie odczytał obrazu.")

    text = result.stdout.decode("utf-8", errors="replace")
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None
