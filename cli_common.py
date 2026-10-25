"""
cli_common.py - the command-line flags several scripts share, defined once.

make_ass.py, context_notes.py, chat_notes.py, analyze.py, align_check.py and find_subs.py each build their own
argparse parser, and many of their flags are the same: --limit, --film-language, --title, --model, --yes and so on.
They are defined here, so a flag's name, type, metavar and help text can't drift from one script to the next, and
so context_notes.py passes them on to the scripts it runs from the same list (claude_args_from and friends).

Each adder takes a parser or an argument group. A script that means something a little different by a flag (say,
where its default comes from) gives its own help text as a keyword named after the flag's dest:
    cli_common.add_film_args(ap, only=("film_language",), film_language="language spoken (default: en)")
The flag itself stays the same, so the forwarding functions keep working.

Standard library only.
"""
import argparse

import claude_api
import timecode

EFFORTS = ("low", "medium", "high", "xhigh", "max")

# ---------------------------------------------------------------- the texts
LIMIT_HELP = "only the first part of the video, e.g. 5:00, 300 or 5m (for testing)"
YES_HELP = "don't stop to ask: approve the API costs and take the default answer to every question"
FRAMES_HELP = "frames for the refine step: keyframes (default, cheaper) or dense (4 a second: far more images, costs more)"
SPEECH_MODEL_HELP = "speech model for {purpose} (default: base.en, or small for other languages)"

# dest -> (flag, argparse keywords). The dest is what the parsed options are called (opts.film_language).
FILM_FLAGS = {
    "film_language": ("--film-language", dict(
        metavar="LANG",
        help="language spoken in the film or show, e.g. fr, de, es (default: English). Changes what Claude looks for: "
             "register (tu/vous), slang, regional speech, and what the subtitles lose in translation")),
    "original_subs": ("--original-subs", dict(
        metavar="SRT",
        help="with --film-language: subtitles in the ORIGINAL language, timed to the same video, so Claude can compare "
             "them with the subtitles you watch with (e.g. film.fr.srt beside film.en.srt)")),
    "title": ("--title", dict(
        help="show/film and episode, e.g. 'The IT Crowd - S01E02 - Calamity Jen' (helps Claude get the facts right; "
             "default: the subtitle file name)")),
    "year": ("--year", dict(
        help="release year, e.g. 1974 (films more than 40 years old get extra attention to their words, people, places "
             "and period). Default: read from the title, the file's tags, the file name or the folder name")),
    "audience": ("--audience", dict(help="who the notes are for (default: fluent in English, didn't grow up in the UK)")),
    "notes_language": ("--notes-language", dict(default="English", help="language to write the notes in (default: English)")),
}

CLAUDE_FLAGS = {
    "model": ("--model", dict(default=None, help=f"Claude model to use (default: {claude_api.DEFAULT_MODEL})")),
    "effort": ("--effort", dict(choices=EFFORTS, default=None,
                                help="the model's effort setting (default: the model's own default; Haiku 4.5 doesn't "
                                     "support it)")),
    "backend": ("--backend", dict(choices=claude_api.BACKENDS, default=None,
                                  help="where Claude runs: your Anthropic API key, or Claude Code on your Claude "
                                       "subscription (default: what --set-backend saved, else api)")),
    "api_url": ("--api-url", dict(help=argparse.SUPPRESS)),
    "api_key_file": ("--api-key-file", dict(help="read the API key from this file instead of the default location")),
}


# ---------------------------------------------------------------- adding the flags
def _add(ap, flags, only, overrides, **changes):
    """Add the flags in `flags` (all of them, or just the dests in `only`). `overrides` replaces help texts by dest;
    `changes` replaces other keywords by dest (e.g. notes_language={"default": None})."""
    unknown = set(overrides) - set(flags)
    if unknown:
        raise TypeError(f"no such flag here: {', '.join(sorted(unknown))}")
    for dest, (flag, kw) in flags.items():
        if only is not None and dest not in only:
            continue
        kw = dict(kw, **changes.get(dest, {}))
        if dest in overrides:
            kw["help"] = overrides[dest]
        ap.add_argument(flag, **kw)


def add_film_args(ap, only=None, notes_language_default="English", **help):
    """--film-language, --original-subs, --title, --year, --audience and --notes-language: what the film is and who
    the notes are for. `only` names the dests wanted, e.g. only=("film_language", "original_subs"); a keyword per
    dest replaces that flag's help text."""
    _add(ap, FILM_FLAGS, only, help, notes_language={"default": notes_language_default})


def add_claude_args(ap, show_key_file=True):
    """--model, --effort, --backend, --api-url (hidden) and --api-key-file: how to reach Claude. show_key_file=False
    hides --api-key-file from --help too (it still works)."""
    _add(ap, CLAUDE_FLAGS, None, {} if show_key_file else {"api_key_file": argparse.SUPPRESS})


def add_limit_arg(ap, help=LIMIT_HELP):
    """--limit TIME: 5:00, 300 or 5m, read as seconds (timecode.duration_arg)."""
    ap.add_argument("--limit", type=timecode.duration_arg, metavar="TIME", help=help)


def add_yes_arg(ap, help=YES_HELP):
    """--yes: approve the costs and take every default."""
    ap.add_argument("--yes", action="store_true", help=help)


def add_frames_arg(ap, choices=("keyframes", "dense"), help=FRAMES_HELP):
    """--frames: how many frames the refine step looks at (analyze.py also allows "none")."""
    ap.add_argument("--frames", choices=choices, default="keyframes", help=help)


def add_speech_model_arg(ap, flag="--model", purpose="transcribing", help=None):
    """The faster-whisper model for speech recognition (--model in analyze.py, find_subs.py and align_check.py;
    --align-model in context_notes.py, where --model is Claude's)."""
    ap.add_argument(flag, default=None, help=help or SPEECH_MODEL_HELP.format(purpose=purpose))


# ---------------------------------------------------------------- passing the flags on to another script
def _args_from(opts, flags, only=None):
    out = []
    for dest, (flag, _) in flags.items():
        if only is not None and dest not in only:
            continue
        value = getattr(opts, dest, None)
        if value:
            out += [flag, str(value)]
    return out


def claude_args_from(opts):
    """The --model, --effort, --backend, --api-url and --api-key-file given, as arguments for a script started from
    here."""
    return _args_from(opts, CLAUDE_FLAGS)


def film_args_from(opts, only=None):
    """The film flags given (--film-language, --original-subs, --title, --year, --audience, --notes-language), as
    arguments for a script started from here. `only` names the dests to pass on."""
    return _args_from(opts, FILM_FLAGS, only)


def yes_args_from(opts):
    return ["--yes"] if getattr(opts, "yes", False) else []


def limit_args_from(opts):
    limit = getattr(opts, "limit", None)
    return ["--limit", f"{limit:g}"] if limit else []
