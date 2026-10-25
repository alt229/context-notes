#!/usr/bin/env python3
"""
prompts.py - how the scripts ask you things: in a terminal, or through another program such as a GUI.

In a terminal nothing changes. Questions take a typed answer, keys and passwords are typed hidden, and with no
terminal at all (a pipe, cron) the scripts behave as they always have: --yes, or the safe default.

A program that runs the scripts for you sets the environment variable  CONTEXT_NOTES_UI=json . Every script it
starts, and every script those start, then:
  - writes each question, hidden prompt and cost estimate as ONE line on stdout, starting with "@context-notes ":
        @context-notes {"v": 1, "type": "question", "id": "generate.send", "text": "...", ...}
  - reads each answer as one line on stdin: the choice's key (e.g. "y"), or an empty line for the default.
Everything else they print stays ordinary text, for a log window. Full description: docs/gui-protocol.md.

Standard library only.
"""
import getpass
import json
import os
import signal
import sys
import time

ENV = "CONTEXT_NOTES_UI"
PREFIX = "@context-notes "
VERSION = 1


def machine():
    """True when a program, not a person at a terminal, is answering (CONTEXT_NOTES_UI=json)."""
    return os.environ.get(ENV, "").strip().lower() == "json"


def _stop_on_break(signum, frame):
    raise KeyboardInterrupt


# Windows has no Ctrl-C a program can send to a group of others, so a GUI's Cancel arrives as Ctrl-Break, which would
# end a script on the spot. Treat it like Ctrl-C instead, so a stopped run keeps what it can (docs/gui-protocol.md).
if os.name == "nt" and machine() and hasattr(signal, "SIGBREAK"):
    try:
        signal.signal(signal.SIGBREAK, _stop_on_break)
    except ValueError:                                     # not the main thread: nothing to do
        pass


def interactive():
    """Can a question be asked at all? Yes in a terminal, and when a program answers (json mode)."""
    return machine() or bool(sys.stdin and sys.stdin.isatty())


def event(kind, **fields):
    """json mode: write one event line on stdout. In a terminal this does nothing."""
    if not machine():
        return
    sys.stdout.write(PREFIX + json.dumps({"v": VERSION, "type": kind, **fields}) + "\n")
    sys.stdout.flush()


_last_progress = {}


def progress(task, done, total=None, unit=None, every=0.0, **fields):
    """json mode: how far a long task has got (`done` of `total` `unit`s; total None means unknown, so show a
    spinner). With `every`, at most one event per `every` seconds for this task, apart from the first and the last.
    In a terminal this does nothing."""
    if not machine():
        return
    now = time.monotonic()
    last = _last_progress.get(task)
    final = total is not None and done is not None and done >= total
    if every and last is not None and not final and now - last < every:
        return
    _last_progress[task] = now
    if isinstance(done, float):
        done = round(done, 1)
    if isinstance(total, float):
        total = round(total, 1)
    event("progress", task=task, done=done, total=total, unit=unit, **fields)


def read_answer():
    """One line from stdin without its line ending, or None at the end of input.
    Reads the file descriptor a byte at a time, so it never takes more than its own line: a script and the
    scripts it starts all share the same stdin."""
    if sys.stdin is None:
        return None
    try:
        fd = sys.stdin.fileno()
    except (AttributeError, OSError, ValueError):          # stdin replaced by something without a descriptor (tests)
        line = sys.stdin.readline()
        return line.rstrip("\r\n") if line else None
    data = bytearray()
    while True:
        b = os.read(fd, 1)
        if not b:
            return data.decode("utf-8", "replace") if data else None
        if b == b"\n":
            return data.decode("utf-8", "replace").rstrip("\r")
        data += b


def question(text, choices, default, id=None):
    """json mode: ask a one-letter question and return the chosen key. `choices` is like {'y': 'yes', 'n': 'no'}.
    An empty answer, or the end of input, takes the default; an answer that fits no choice asks again."""
    while True:
        event("question", id=id, text=text, choices=[{"key": k, "label": v} for k, v in choices.items()],
              default=default)
        got = read_answer()
        if got is None:
            return default
        got = got.strip().lower()
        if not got:
            return default
        if got in choices:
            return got
        if got[0] in choices:
            return got[0]
        print("  Please answer " + " or ".join(f"'{k}' ({v})" for k, v in choices.items()), flush=True)


def ask(text, choices, default, auto=False, id=None):
    """Ask a one-letter question and return the chosen key. `choices` is like {'a': 'align', 's': 'skip'}.
    With auto (--yes), or nobody to answer (no terminal, no GUI), takes the default and says so. In a terminal: the
    usual '[a/S]' prompt, with the default in capitals. When a program is answering, the question goes to it."""
    keys = "/".join(k.upper() if k == default else k for k in choices)
    if auto or not interactive():
        print(f"{text} -> {choices[default]} (automatic)", flush=True)
        return default
    if machine():
        return question(text, choices, default, id)
    while True:
        try:
            got = input(f"{text} [{keys}] ").strip().lower()
        except EOFError:
            return default
        if not got:
            return default
        if got[0] in choices:
            return got[0]
        print("  Please answer " + " or ".join(f"'{k}' ({v})" for k, v in choices.items()), flush=True)


def confirm(text, id=None):
    """A yes/no question that defaults to no (asked before anything costs money or downloads). True for yes.
    In a terminal: the same '[y/N]' prompt as always."""
    if machine():
        return question(text, {"y": "yes", "n": "no"}, "n", id) == "y"
    return input(f"{text} [y/N] ").strip().lower() in ("y", "yes")


def secret(text, id=None):
    """Hidden input: an API key or a password. In a terminal: getpass, as always.
    json mode: one line from stdin, never written back out."""
    if machine():
        event("input", id=id, text=text.strip(), hidden=True)
        return read_answer() or ""
    return getpass.getpass(text)


def text_input(text, id=None):
    """Ordinary typed input, such as a user name. In a terminal: input(), as always."""
    if machine():
        event("input", id=id, text=text.strip(), hidden=False)
        return read_answer() or ""
    return input(text)
