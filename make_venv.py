#!/usr/bin/env python3
"""
make_venv.py - make this folder's virtual environment (.venv) with the Python version in .python-version, and
install requirements.txt into it. Run it with any Python 3 you have:

    python3 make_venv.py           (Windows: python make_venv.py)
    python3 make_venv.py --check   only say which Python it would use and what .venv is now; change nothing
    python3 make_venv.py --ready   exit 0 if .venv is ready to use (the pinned Python, numpy and Pillow), else 1

It finds that version itself: Windows' py launcher (py -3.14), else python3.14 on the PATH, in Homebrew's folders or
python.org's. It doesn't download Python: if the version isn't there, it says how to install it. A .venv made with
another version is renamed to .venv-<that version> (kept, not deleted) after you say yes; a .venv on the right
version just gets the requirements installed again. Speech recognition (faster-whisper) is installed as a step of
its own, so a computer it has no build for (an Intel Mac on 3.14, say) still gets everything else.
context-notes.bat (Windows) runs --ready before every start, and this with --yes when it isn't ready.
Standard library only. Created 2026-10-30, modified 2026-10-30.
"""
import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompts  # noqa: E402
import pythonpin  # noqa: E402

HERE = pythonpin.HERE
SPEECH = "faster-whisper"                 # installed on its own: the one with the fewest builds


def venv_python(venv):
    return Path(venv) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def venv_version(venv):
    """(3, 15) for the Python a virtual environment was made with (its pyvenv.cfg), or None."""
    try:
        text = (Path(venv) / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"^\s*version(?:_info)?\s*=\s*(\d+)\.(\d+)", text, re.M)
    return (int(m.group(1)), int(m.group(2))) if m else None


def version_of(python):
    """(3, 14) for an interpreter, by asking it; None if it won't run."""
    try:
        r = subprocess.run([str(python), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.fullmatch(r"(\d+)\.(\d+)", r.stdout.strip()) if r.returncode == 0 else None
    return (int(m.group(1)), int(m.group(2))) if m else None


def candidates(pin):
    """Where a Python of the pinned version may be, most likely first."""
    v = pythonpin.dotted(pin)
    if sys.version_info[:2] == tuple(pin):
        yield Path(getattr(sys, "_base_executable", None) or sys.executable)
    if os.name == "nt":
        py = shutil.which("py")
        if py:
            try:
                r = subprocess.run([py, f"-{v}", "-c", "import sys; print(sys.executable)"],
                                   capture_output=True, text=True, timeout=30)
                if r.returncode == 0 and r.stdout.strip():
                    yield Path(r.stdout.strip())
            except (OSError, subprocess.SubprocessError):
                pass
        local = os.environ.get("LOCALAPPDATA", "")
        yield Path(local) / "Programs" / "Python" / f"Python{v.replace('.', '')}" / "python.exe"
        yield Path(local) / "Python" / f"pythoncore-{v}-64" / "python.exe"        # python.org's install manager
        return
    found = shutil.which(f"python{v}")
    if found:
        yield Path(found)
    for d in ("/opt/homebrew/bin", "/usr/local/bin", f"/Library/Frameworks/Python.framework/Versions/{v}/bin",
              f"/opt/homebrew/opt/python@{v}/bin", f"/usr/local/opt/python@{v}/bin", "/usr/bin"):
        yield Path(d) / f"python{v}"


def find_python(pin):
    """A Python of the pinned version on this computer, or None."""
    for p in candidates(pin):
        if p.exists() and version_of(p) == tuple(pin):
            return p
    return None


def install_hint(pin):
    v = pythonpin.dotted(pin)
    if os.name == "nt":
        return (f"Install Python {v} from https://www.python.org/downloads/windows/ (or in PowerShell: "
                f"winget install Python.Python.{v}), then open a new window and run this again.")
    if sys.platform == "darwin":
        return f"Install it with Homebrew (brew install python@{v}) or from https://www.python.org/downloads/macos/."
    return (f"Install python{v} with your package manager (Ubuntu: the deadsnakes PPA has it), or with pyenv "
            f"(pyenv install {v}).")


def requirements(path=HERE / "requirements.txt"):
    """(the rest, speech recognition): requirement lines without their comments."""
    rest, speech = [], []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        spec = re.sub(r"\s+#.*$", "", line).strip()
        if spec and not spec.startswith("#"):
            (speech if spec.lower().startswith(SPEECH) else rest).append(spec)
    return rest, speech


def can_import(python, module):
    try:
        return subprocess.run([str(python), "-c", f"import {module}"], capture_output=True, timeout=300).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run(cmd):
    """Print the command, run it, and return its exit code."""
    cmd = [str(c) for c in cmd]
    print("$ " + (subprocess.list2cmdline(cmd) if os.name == "nt" else shlex.join(cmd)), flush=True)    # pasteable
    return subprocess.run([str(c) for c in cmd]).returncode


def not_ready(venv, pin):
    """Why .venv can't be used as it is (a sentence), or None when it's on the pinned Python and has what the app
    needs most (numpy and Pillow)."""
    have = venv_version(venv) if venv.is_dir() else None
    if not venv.is_dir() or not venv_python(venv).exists():
        return "There's no .venv in this folder yet."
    if have != tuple(pin):
        return (f".venv was made with Python {pythonpin.dotted(have) if have else '(unknown)'}, not "
                f"{pythonpin.dotted(pin)}.")
    missing = [name for module, name in (("numpy", "numpy"), ("PIL", "Pillow")) if not can_import(venv_python(venv), module)]
    if missing:
        return f".venv is missing {' and '.join(missing)}, or {'they are' if len(missing) > 1 else 'it is'} damaged."
    return None


def spare_name(venv, version):
    """.venv-3.15, or .venv-3.15-2 ... if that's taken."""
    base = f"{venv.name}-{pythonpin.dotted(version) if version else 'old'}"
    p, n = venv.with_name(base), 2
    while p.exists():
        p, n = venv.with_name(f"{base}-{n}"), n + 1
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only say which Python it would use; change nothing")
    ap.add_argument("--yes", action="store_true", help="rename a .venv on another version without asking")
    ap.add_argument("--ready", action="store_true",
                    help="only check: exit 0 if .venv is on the pinned Python and has numpy and Pillow, else 1")
    a = ap.parse_args(argv)
    venv = HERE / ".venv"
    pin = pythonpin.pinned()
    if not pin:
        sys.exit(f"{pythonpin.PIN_FILE.name} is missing or doesn't name a version, so there's nothing to match.")
    v = pythonpin.dotted(pin)
    if a.ready:
        why = not_ready(venv, pin)
        print(why or f".venv is ready (Python {v}).")
        return 1 if why else 0
    python = find_python(pin)
    have = venv_version(venv) if venv.is_dir() else None
    print(f"This project is set up for Python {v} ({pythonpin.PIN_FILE.name}).")
    print(f"Python {v}: {python or 'not found on this computer'}")
    print(f".venv: {'none yet' if not venv.is_dir() else 'Python ' + pythonpin.dotted(have) if have else 'version unknown'}")
    if a.check:
        return 0
    if not python:
        sys.exit(f"Can't make the environment without Python {v}. {install_hint(pin)}")
    if venv.is_dir() and have != tuple(pin):
        spare = spare_name(venv, have)
        if not a.yes and not prompts.interactive():
            sys.exit(f".venv was made with another Python. Not an interactive terminal, so add --yes to keep it as "
                     f"{spare.name} and make a new one.")
        if not (a.yes or prompts.confirm(f"\n.venv was made with Python {pythonpin.dotted(have) if have else '(unknown)'}. "
                                         f"Make a new one with {v}? The old one is kept as {spare.name}.",
                                         id="venv.replace")):
            print("Nothing was changed.")
            return 1
        try:
            os.rename(venv, spare)
        except OSError as e:
            sys.exit(f"Couldn't rename .venv ({e.strerror or e}). If the app or a script is running from it, close it "
                     "and run this again.")
        print(f"Kept the old one as {spare.name} (delete it once the new one works).")
    damaged = venv.is_dir() and bool(not_ready(venv, pin))     # the right Python, but numpy or Pillow broken: pip
    if not venv.is_dir() and run([python, "-m", "venv", venv]) != 0:  # would call them installed, so reinstall them
        sys.exit("Making the environment failed (see above).")
    vpy = venv_python(venv)
    rest, speech = requirements()
    force = ["--force-reinstall"] if damaged else []
    if run([vpy, "-m", "pip", "install", "--upgrade", "pip"]) != 0 or run([vpy, "-m", "pip", "install", *force, *rest]) != 0:
        sys.exit("Installing the requirements failed (see above). Run this again once it's sorted out.")
    if speech and (run([vpy, "-m", "pip", "install", *speech]) != 0 or not can_import(vpy, "faster_whisper")):
        print(f"\nSpeech recognition (faster-whisper) isn't installed: it has no build for Python {v} on this "
              "computer yet. Everything else is. It's only needed to write subtitles from the soundtrack and to "
              "re-time or check them by ear.")
    activate = r".venv\Scripts\Activate.ps1" if os.name == "nt" else "source .venv/bin/activate"
    start = "double-click context-notes.bat (or make-shortcut.bat once, for a desktop shortcut)" if os.name == "nt" \
        else f"{pythonpin.PYTHON} app.py"
    print(f"\nDone. In a new window: cd to this folder, then {activate}. To start the app: {start}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
