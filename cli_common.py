#!/usr/bin/env python3
"""
cli_common.py - the command-line options that mean the same in context_notes.py and make_ass.py, defined once, and
the code that passes them on from one script to the next.

- add_claude_args(group, ...): how to talk to Claude: --model, --effort, --route, --api-fallback, --api-key-file and
  --api-url (hidden). settle_route(opts) fills in the route and the API-credit allowance after parsing.
- add_look_args(group): how the notes look: --reading-speed, --note-background, --note-opacity.
  check_look_args(ap, opts) rejects a reading speed of 0 or less after parsing.
- add_limit_arg(group, help): --limit, a time like 5:00, 300 or 5m.
- add_spoiler_arg(group): --spoilers, for the Behind the Scenes track (include, leave-out, ask).
- claude_args(opts), look_args(opts), limit_args(opts), spoiler_args(opts): the same options, as they'd be typed,
  for the next script.
- percent_arg: the type of --note-opacity.

Options whose meaning differs between the scripts (--title, --yes, --audience, --film-language, ...) stay with each
script, and so does the speech model's --model in analyze.py, align_check.py and find_subs.py.
"""
import argparse

import settings
import timecode

EFFORTS = tuple(e for e in settings.EFFORTS if e)          # low ... max ("" in settings means "high")


def percent_arg(text):
    """--note-opacity: a number from 0 to 100, with or without a % sign."""
    try:
        value = float(str(text).strip().rstrip("%"))
    except ValueError:
        value = -1.0
    if not 0 <= value <= 100:
        raise argparse.ArgumentTypeError(f"{text!r} isn't a number from 0 (invisible) to 100 (solid), like 30")
    return int(value) if value.is_integer() else value


# ---------------------------------------------------------------- talking to Claude

def dollars_arg(text):
    """--api-fallback: dollars, from 0 to 1000 ('5', '$2.50')."""
    import usage
    try:
        value = usage.parse_dollars(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None
    if not 0 <= value <= 1000:
        raise argparse.ArgumentTypeError(f"{text!r} isn't an amount from $0 to $1,000")
    return value


def add_claude_args(group, model_default, effort_default, show_key_file=False):
    """--model, --effort, --route, --api-fallback, --api-key-file and the hidden --api-url. The model and effort
    defaults differ between the scripts, so each says what its own are."""
    group.add_argument("--route", choices=settings.ROUTES, default=None,
                       help="where Claude writes the notes: plan (your Claude plan, through Claude Code, with no API "
                            "credits) or api (API credits). Default: from Settings, the plan unless changed")
    group.add_argument("--api-fallback", type=dollars_arg, default=None, metavar="USD",
                       help="when the plan runs out or Claude Code can't be used, carry on with API credits, up to "
                            "this many dollars for this run. 0: ask first, or stop when nobody can be asked "
                            "(default: from Settings, 0 unless changed)")
    group.add_argument("--model", default=None, help=f"Claude model (default: {model_default})")
    group.add_argument("--effort", choices=EFFORTS, default=None,
                       help=f"the model's effort setting (default: {effort_default}; left out for Haiku 4.5, which "
                            "doesn't support it)")
    group.add_argument("--api-key-file",
                       help="read the API key from this file instead of the default location" if show_key_file
                       else argparse.SUPPRESS)
    group.add_argument("--api-url", help=argparse.SUPPRESS)


def settle_route(opts):
    """After parsing: the route and the API-credit allowance, from Settings when the flags were left out. An
    --api-url given by hand (a test's stand-in API) means the API unless --route says otherwise."""
    defaults = settings.route_defaults()
    if getattr(opts, "route", None) is None:
        opts.route = "api" if getattr(opts, "api_url", None) else defaults["route"]
    if getattr(opts, "api_fallback", None) is None:
        opts.api_fallback = defaults["api_fallback"]
    return opts


def claude_args(opts):
    """The Claude options that were given, for the next script."""
    out = []
    for flag, name in (("--model", "model"), ("--api-url", "api_url"), ("--api-key-file", "api_key_file"),
                       ("--effort", "effort"), ("--route", "route")):
        value = getattr(opts, name, None)
        if value:
            out += [flag, value]
    if getattr(opts, "api_fallback", None) is not None:
        out += ["--api-fallback", f"{opts.api_fallback:g}"]
    return out


# ---------------------------------------------------------------- how the notes look

def add_look_args(group):
    """--reading-speed, --note-background and --note-opacity. None when left out, so a film's saved look wins."""
    look = settings.look_defaults()
    wpm = look["wpm"]
    group.add_argument("--reading-speed", type=float, metavar="WPM",
                       help=f"words a minute each note is timed for (default {wpm:g}, {60 / wpm:g} s a word; lower "
                            "keeps notes up longer)")
    group.add_argument("--note-background", choices=list(settings.BACKGROUNDS),
                       help=f"the box behind each note (default {look['background']}; dark is the look before 0.2.0; "
                            "none outlines the text instead)")
    group.add_argument("--note-opacity", type=percent_arg, metavar="PERCENT",
                       help=f"how solid the see-through box is, from 0 (invisible) to 100 (solid); default "
                            f"{look['opacity']:g}")


def check_look_args(ap, opts):
    """What argparse can't check: a reading speed has to be above 0."""
    if opts.reading_speed is not None and opts.reading_speed <= 0:
        wpm = settings.look_defaults()["wpm"]
        ap.error(f"--reading-speed is words a minute, a number above 0 (the default, {wpm:g}, is {60 / wpm:g} s a word)")


def look_args(opts):
    """How the notes look on screen. Given to every build, which remembers them in the notes file."""
    out = []
    if getattr(opts, "reading_speed", None):
        out += ["--reading-speed", f"{opts.reading_speed:g}"]
    if getattr(opts, "note_background", None):
        out += ["--note-background", opts.note_background]
    if getattr(opts, "note_opacity", None) is not None:
        out += ["--note-opacity", f"{opts.note_opacity:g}"]
    return out


def add_spoiler_arg(group):
    """--spoilers, for the Behind the Scenes track. None when left out, so a film's own choice wins."""
    group.add_argument("--spoilers", choices=list(settings.SPOILERS),
                       help="Behind the Scenes notes that give away something later in the film: include them, "
                            "leave-out, or ask (once per film; remembered). Free to change later: only the .ass is "
                            f"rebuilt. Default: the film's own choice, else {settings.spoilers_default()}")


def spoiler_args(opts):
    return ["--spoilers", opts.spoilers] if getattr(opts, "spoilers", None) else []


# ---------------------------------------------------------------- --limit

def add_limit_arg(group, help):
    group.add_argument("--limit", type=timecode.duration_arg, metavar="TIME", help=help)


def limit_args(opts):
    return ["--limit", f"{opts.limit:g}"] if getattr(opts, "limit", None) else []
