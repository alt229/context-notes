#!/usr/bin/env python3
"""
fileio.py - writing files all at once, reading text in whatever encoding it came in, and where this install keeps
its settings. Standard library only; every script uses it.

    replacing(path)              a temporary name to write to; it takes path's place only once the block has finished
    write_text_safely(path, s)   Path.write_text, all at once (so Ctrl-C or a GUI's Cancel never leaves half a file)
    unique_backup(path)          path.bak, or .bak2, .bak3 ... (never over an earlier backup)
    read_text(path)              UTF-8 (with or without a BOM), UTF-16 with a BOM, cp1252 or latin-1
    config_dir()                 ~/.config/context-notes, or $XDG_CONFIG_HOME/context-notes
"""
import contextlib
import os
import shutil
import stat
from pathlib import Path

import workfiles


@contextlib.contextmanager
def replacing(path):
    """Write a file all at once. Yields a temporary name beside `path` to write to; when the block ends, that file
    takes the place of `path`, with the old file's permissions. If the block is interrupted (an error, Ctrl-C, a
    GUI's Cancel), `path` is left as it was and the temporary file is removed, so no later run finds half a file."""
    path = Path(path)
    if path.is_symlink():                                  # write the file the link points to; keep the link
        path = path.resolve()
    try:
        workfiles.make_dirs(path.parent)                  # a video's context-notes folder, the first time
    except OSError:                                        # (writing the file then says what's wrong)
        pass
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


def unique_backup(path):
    """path.bak, or .bak2, .bak3 ... so an earlier backup is never overwritten."""
    p = Path(path)
    n = 1
    while True:
        b = p.with_name(p.name + (".bak" if n == 1 else f".bak{n}"))
        if not b.exists():
            return b
        n += 1


def write_text_safely(path, text, encoding="utf-8"):
    """Path(path).write_text(text), but all at once (see replacing())."""
    try:
        with replacing(path) as tmp:
            tmp.write_text(text, encoding=encoding)
    except PermissionError:          # the folder won't take a new file, though the file itself may be writable:
        Path(path).write_text(text, encoding=encoding)          # write it in place, as before


def read_text(path):
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
    """Where this install keeps its key, logins, settings and ledger."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "context-notes"
