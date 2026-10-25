"""
fileio.py - reading and writing files the way every script in this project does it.

Anything a later run reads (caches, subtitles, notes, .ass) is written all at once with write_text_safely() or
replacing(), so Ctrl-C, an error or a GUI's Cancel can't leave half a file behind (CLAUDE.md, rule 8). read_text()
copes with the encodings subtitle files turn up in. config_dir() is where the scripts keep their settings
(~/.config/context-notes, or $XDG_CONFIG_HOME/context-notes).
"""
import contextlib
import os
import shutil
import stat
from pathlib import Path


@contextlib.contextmanager
def replacing(path):
    """Write a file all at once. Yields a temporary name beside `path` to write to; when the block ends, that file
    takes the place of `path`, with the old file's permissions. If the block is interrupted (an error, Ctrl-C, a
    GUI's Cancel), `path` is left as it was and the temporary file is removed, so no later run finds half a file."""
    path = Path(path)
    if path.is_symlink():                                  # write the file the link points to; keep the link
        path = path.resolve()
    tmp = path.with_name(f".{path.name}.part{os.getpid()}")
    try:
        yield tmp
        try:
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        except OSError:                                    # no old file: the new one keeps the usual permissions
            pass
        try:
            os.replace(tmp, path)
        except PermissionError:                            # Windows, when another program has the old file open:
            shutil.copyfile(tmp, path)                     # write into it, as before
            tmp.unlink()
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def write_text_safely(path, text, encoding="utf-8"):
    """Path(path).write_text(text), but all at once (see replacing())."""
    try:
        with replacing(path) as tmp:
            tmp.write_text(text, encoding=encoding)
    except PermissionError:          # the folder won't take a new file, though the file itself may be writable:
        Path(path).write_text(text, encoding=encoding)          # write it in place, as before


def read_text(path):
    """The file as text. Handles UTF-16 with a BOM, UTF-8 (with or without one), cp1252 and latin-1, in that order."""
    raw = Path(path).read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):          # UTF-16 with BOM
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def config_dir():
    """Where the scripts keep their settings: $XDG_CONFIG_HOME/context-notes, else ~/.config/context-notes."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "context-notes"
