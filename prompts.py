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

"Yes to all questions" (Settings; context_notes.py --yes-to-all) sets CONTEXT_NOTES_YES_TO_ALL=1 for the run, and
the questions about the work itself (YES_TO_ALL below) are then answered without asking, even with no terminal.

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
YES_ENV = "CONTEXT_NOTES_YES_TO_ALL"

# What "Yes to all questions" answers by itself: the questions about the work, each with the answer that goes ahead
# (None: the question's own default, as for sync.drift: re-time, or carry on when that isn't possible). Only these:
# never sending to Claude (that's --yes, or Send automatically in the app), moving to API credits, or deleting; and
# a question added later isn't answered until it's listed here.
YES_TO_ALL = {
    "subs.download": "y", "subs.transcribe": "y",          # download subtitles; write them from the soundtrack
    "sync.unmeasured": "y", "sync.drift": None,            # treat them as in sync; re-time them
    "alignment.check": "y", "alignment.fix": "y",          # check every note's timing; fix the stretches that are out
    "notes.limited": "a", "notes.unreadable": "y",         # add the rest; send again the lines whose reply was lost
    "refine.unreadable": "y",
    "generate.resume": "p", "refine.resume": "p",          # pick up where a stopped run left off
    "folder.next": "y", "embed.go": "y",                   # go on to the next video; --embed: put the notes inside
}


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


def yes_to_all():
    """Is "Yes to all questions" on for this run? (Inherited by every script the run starts.)"""
    return os.environ.get(YES_ENV, "").strip() == "1"


def turn_on_yes_to_all():
    """For the rest of this run, and the scripts it starts: answer the YES_TO_ALL questions without asking."""
    os.environ[YES_ENV] = "1"


def _yes_answer(id, choices, default):
    """The key "Yes to all questions" answers question `id` with, or None (it's off, or doesn't answer this one)."""
    if not id or id not in YES_TO_ALL or not yes_to_all():
        return None
    key = YES_TO_ALL[id] or default
    return key if key in choices else None


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
    usual '[a/S]' prompt, with the default in capitals. When a program is answering, the question goes to it.
    "Yes to all questions" answers the YES_TO_ALL ones first, even over --yes's default."""
    keys = "/".join(k.upper() if k == default else k for k in choices)
    yes = _yes_answer(id, choices, default)
    if yes is not None:
        print(f"{text} -> {choices[yes]} (Yes to all questions)", flush=True)
        return yes
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
    In a terminal: the same '[y/N]' prompt as always. "Yes to all questions" answers the YES_TO_ALL ones."""
    if _yes_answer(id, {"y": "yes", "n": "no"}, "n") == "y":
        print(f"{text} -> yes (Yes to all questions)", flush=True)
        return True
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
