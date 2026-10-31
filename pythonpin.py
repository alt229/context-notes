#!/usr/bin/env python3
"""
pythonpin.py - the Python version this project's virtual environment is made with, kept in .python-version (one
line: 3.14). Standard library only.

Until everything in requirements.txt installs on a newer Python on macOS, Windows and Linux, .venv is made with the
pinned version (make_venv.py does it). In October 2026 Python 3.15 was out, but onnxruntime, which faster-whisper
(speech recognition) needs, had no 3.15 build anywhere. A newer Python still runs the rest; the app and
context_notes.py say so when they start (newer_than_pin), and the app's Settings shows it too (status).

To lift the pin: change .python-version, and the python_version marker on faster-whisper in requirements.txt. The
"newer Python" job in .github/workflows/tests.yml shows when that's safe (it turns green).
Created 2026-10-30.
"""
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIN_FILE = HERE / ".python-version"
PYTHON = "python" if os.name == "nt" else "python3"          # what to type (prompts.PYTHON, without importing it)


def pinned(path=PIN_FILE):
    """(3, 14) from .python-version, or None if it's missing or doesn't name a version."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        m = re.fullmatch(r"\s*(?:c?python-?)?(\d+)\.(\d+)(?:\.\d+)?\s*", line, re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def dotted(version):
    return ".".join(str(n) for n in version[:2])


def newer_than_pin(version=None, pin=None):
    """A sentence saying this Python is newer than the pin and what to do, or None (the pinned one, an older one,
    or no pin)."""
    version = tuple((version or sys.version_info)[:2])
    pin = pinned() if pin is None else pin
    if not pin or version <= tuple(pin):
        return None
    return (f"This is Python {dotted(version)}. Context Notes is set up for Python {dotted(pin)} for now: speech "
            f"recognition (faster-whisper) can't be installed on {dotted(version)} yet, and the rest hasn't been "
            f"tried on it. To make this folder's environment with {dotted(pin)}: {PYTHON} make_venv.py")


def status():
    """For the app's Settings: this Python, the pin, and the sentence above when it's newer."""
    pin = pinned()
    advice = newer_than_pin(pin=pin)
    return {"version": ".".join(str(n) for n in sys.version_info[:3]), "pinned": dotted(pin) if pin else None,
            "newer": bool(advice), "advice": advice}
