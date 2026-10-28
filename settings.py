#!/usr/bin/env python3
"""
settings.py - this install's defaults, read by the app and by every script, so both start from the same choices.

They're kept in settings.json in ~/.config/context-notes/ (the folder the API key is in; $XDG_CONFIG_HOME moves it).
A missing or damaged file gives the built-in defaults, which are what the tools did before this file existed.
The Settings page in the app writes the file; the scripts only read it. Change a default and the next run uses it.

Only the defaults that are safe to share are here. Anything that rewrites or deletes files (writing the notes again,
converting, deleting kept originals) is never a default, and neither are the subtitle choices, which change which
subtitles an existing film is shown with. A film's own saved notes always win over these defaults.
"""
import json
import os

import usage  # the config folder, and the test override for it

FILE = "settings.json"
MODELS = {"best": "claude-opus-5-5", "cheaper": "claude-sonnet-5-5"}     # the app's two presets
EFFORTS = ("", "low", "medium", "high", "xhigh", "max")               # "" = high, what both presets use
BACKGROUNDS = ("see-through", "dark", "none")                         # make_ass.BACKGROUNDS (checked by a test)
FRAMES = ("keyframes", "dense")
ROUTES = ("plan", "api")                  # your Claude plan (through Claude Code), or API credits

BUILT_IN = {
    "route": "plan",                      # where the notes are written: the plan, unless it can't (see api_fallback)
    "api_fallback": False,                # when the plan runs out (or Claude Code can't be used): carry on with API
    "api_fallback_usd": 5.0,              # credits, up to this much a run. Off: ask (or stop, with nobody to ask)
    "quality": "best",                    # "best" (Opus) or "cheaper" (Sonnet)
    "effort": "",                         # "" = high
    "audience": "",                       # "" = the built-in text for each film
    "notes_language": "",                 # "" = English
    "seconds_per_word": None,             # None = 0.4 s a word (150 words a minute), or each film's own
    "note_background": "see-through",
    "note_opacity": 30,
    "frames": "keyframes",
    "check_alignment": False,
    "offline": False,                     # True = don't search OpenSubtitles.com for subtitles
    "download_subs": False,               # True = download what OpenSubtitles.com finds without asking
    "yes_to_all": False,                  # True = answer the questions about the work without asking (prompts.py)
    "recursive": False,
    "autosend": True,                     # send 10 seconds after showing the cost; untick to be asked each time
    "start_folder": "",
    "remember_start_folder": True,
}
# kind, and what it allows
KEYS = {
    "route": ("choice", ROUTES),
    "api_fallback": ("bool", None),
    "api_fallback_usd": ("number", (0.01, 1000)),
    "quality": ("choice", ("best", "cheaper")),
    "effort": ("choice", EFFORTS),
    "audience": ("text", 300),
    "notes_language": ("text", 40),
    "seconds_per_word": ("number_or_none", (0.1, 2)),
    "note_background": ("choice", BACKGROUNDS),
    "note_opacity": ("number", (0, 100)),
    "frames": ("choice", FRAMES),
    "check_alignment": ("bool", None),
    "offline": ("bool", None),
    "download_subs": ("bool", None),
    "yes_to_all": ("bool", None),
    "recursive": ("bool", None),
    "autosend": ("bool", None),
    "start_folder": ("text", 1024),
    "remember_start_folder": ("bool", None),
}


def path():
    return usage.data_dir() / FILE


def _number(value, low, high):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


def check(key, value):
    """The value, if it's allowed for this setting; else ValueError saying why."""
    if key not in KEYS:
        raise ValueError(f"{key} isn't a setting, so it can't be saved")
    kind, spec = KEYS[key]
    if kind == "bool":
        ok = isinstance(value, bool)
    elif kind == "choice":
        ok = value in spec
    elif kind == "text":
        ok = isinstance(value, str) and len(value) <= spec and not any(c in value for c in "\r\n\t")
    elif kind == "number":
        ok = _number(value, *spec)
    else:                                   # number_or_none
        ok = value is None or _number(value, *spec)
    if not ok:
        raise ValueError(f"{key}: that doesn't look right ({value!r})")
    return value


def read_file():
    """(what the file sets that is valid, warnings for what isn't). Nothing here raises."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, []
    except (OSError, ValueError):
        return {}, ["settings.json couldn't be read, so the built-in defaults are used"]
    if not isinstance(data, dict):
        return {}, ["settings.json isn't a list of settings, so the built-in defaults are used"]
    values, warnings = {}, []
    for key, value in data.items():
        if key not in KEYS:
            warnings.append(f"{key} isn't a setting any more; it's ignored")
            continue
        try:
            values[key] = check(key, value)
        except ValueError as e:
            warnings.append(f"{e}; the built-in default is used")
    return values, warnings


def effective():
    """Every setting, as the scripts and the page use it."""
    return {**BUILT_IN, **read_file()[0]}


def warnings():
    return read_file()[1]


def save(changes):
    """Keep the given settings. Every one is checked first, and nothing is written if any is wrong."""
    if not isinstance(changes, dict):
        raise ValueError("the settings must be sent as a list of values")
    clean = {key: check(key, value) for key, value in changes.items()}
    current = read_file()[0]
    current.update(clean)
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(FILE + ".tmp")
    tmp.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, target)                 # all at once: a crash never leaves half a file
    return effective()


def reset():
    """Back to the built-in defaults: the file goes."""
    try:
        os.remove(path())
    except FileNotFoundError:
        pass
    return effective()


def cli_defaults():
    """What the terminal scripts take when a flag is left out (applied with argparse's set_defaults). Only the
    choices a run can change without rewriting anything: the look is read by make_ass.py from look_defaults()
    instead, so a film's own saved look is never overwritten."""
    s = effective()
    return {"model": MODELS[s["quality"]], "effort": s["effort"] or "high", "audience": s["audience"] or None,
            "notes_language": s["notes_language"] or None, "frames": s["frames"],
            "check_alignment": s["check_alignment"], "recursive": s["recursive"], "offline": s["offline"],
            "download_subs": s["download_subs"], "yes_to_all": s["yes_to_all"]}


def route_defaults():
    """Where the notes are written when --route and --api-fallback are left out: the route ("plan" or "api"), and the
    dollars of API credit a run may use when the plan runs out (0: ask, or stop when nobody can be asked). Kept out
    of cli_defaults() because an --api-url given by hand (the tests' fake API) means the API: cli_common decides."""
    s = effective()
    return {"route": s["route"], "api_fallback": float(s["api_fallback_usd"]) if s["api_fallback"] else 0.0}


def look_defaults():
    """The box, opacity and words a minute a new .ass is built with, when neither the flags nor the notes file
    give one."""
    s = effective()
    spw = s["seconds_per_word"]
    return {"background": s["note_background"], "opacity": s["note_opacity"],
            "wpm": 60 / spw if spw else 150}


def custom_audience():
    """The audience every new notes file is written for, if one is set; else None (the built-in text per film)."""
    return effective()["audience"] or None
