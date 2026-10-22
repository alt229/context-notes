#!/usr/bin/env python3
"""
make_ass.py - merge an SRT subtitle file with a notes file into one ASS track.

Dialogue keeps its original timing at the bottom of the screen. Each note pops
up in a boxed bubble at the top-left when the line it belongs to is spoken.

Notes live in their own JSON file and are matched to the subtitles by quoting
a distinctive bit of the line, not by cue number, so the same notes work with
different releases of the same episode (different cue numbers and timings).

Usage:
    python3 make_ass.py episode.srt                                      # first run: creates a blank notes-<name>.json
    python3 make_ass.py episode.srt --generate --video episode.mp4       # Claude writes the notes (API credits), then builds
    python3 make_ass.py episode.srt --refine --video episode.mp4         # Claude improves the notes using the video's
                                                                         # frames and soundtrack; backs up notes + old .ass
    python3 make_ass.py --set-api-key                                    # once: save your API key
    python3 make_ass.py episode.srt notes.json --video episode.mp4      # -> episode.notes.ass
    python3 make_ass.py episode.srt notes.json [-o out.ass] [--offset 0.0] [--layout split|stack]
    python3 make_ass.py film.srt --generate --limit 5:00          # try it on the first 5 minutes only
    python3 make_ass.py film.en.srt --generate --film-language fr --original-subs film.fr.srt
                                                                         # a French film: notes on what the
                                                                         # English subtitles lose
    python3 make_ass.py film.fr.srt notes.json --video film.mkv --display-subs film.en.srt
                                                                         # notes placed on the French lines,
                                                                         # English subtitles on screen

notes.json:
    {
      "title": "The IT Crowd - S01E01 - Yesterday's Jam",
      "audience": "...",
      "notes": [
        {"match": "turning it off and on again",
         "category": "IT in-joke",
         "text": "The note itself.",
         "confidence": "high"},          # high | medium | low  (default high)
        {"cue": 42, ...}                  # or anchor by cue number
        {"at": "00:01:23,500", ...}       # or by an explicit timestamp
      ]
    }
Visual notes: {"at_video": "00:14:33,000", "kind": "visual", ...} are timed to the
video itself, so the subtitle offset is not applied to them.
Optional per-note keys: "duration" (seconds), "occurrence" (match the Nth hit),
"when": "start" (show as the line begins; default is just after it ends, so
the joke lands before the explanation), "delay" (extra seconds).
"""
import argparse
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import languages

PLAY_X, PLAY_Y = 1920, 1080

# category -> label colour (ASS colours are &HBBGGRR&)
CATEGORY_COLOURS = {
    "british english": "&H5AC8FF&",   # amber
    "archaic word": "&H5AC8FF&",
    "historical context": "&HFFB45A&",  # sky blue
    "bawdy": "&H9696FF&",             # rose
    "adaptation": "&HC8C8C8&",        # grey
    "british slang": "&H5AC8FF&",
    "idiom": "&H5AC8FF&",
    "wordplay": "&H50E6E6&",          # yellow
    "it in-joke": "&H7CE07C&",        # green
    "cultural reference": "&HFFB45A&",  # sky blue
    "character": "&HD28CFF&",         # pink
    "theme": "&HD28CFF&",
    "delivery": "&HFFE08C&",          # pale cyan
    "running gag": "&H8CA0FF&",       # salmon
    "setup": "&H8CA0FF&",
    "payoff": "&H8CA0FF&",
    "trivia": "&HC8C8C8&",            # grey
    "visual gag": "&H50B4FF&",        # orange
    "prop": "&H50B4FF&",
    "background": "&HB4DC8C&",        # teal
    "staging": "&HB4DC8C&",
    "costume": "&HB4DC8C&",
    "about these notes": "&HC8C8C8&",
    # foreign-language films
    "translation": "&H50E6E6&",       # yellow, like wordplay
    "register": "&H5AC8FF&",          # amber, like the other language notes
    "slang": "&H5AC8FF&",
    "dialect": "&H5AC8FF&",
    "on-screen text": "&H50B4FF&",    # orange, like props
}
DEFAULT_LABEL_COLOUR = "&HE6E6E6&"


# ---------------------------------------------------------------- SRT parsing
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


TS = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"


def ts_to_s(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_duration(text):
    """'300', '300s', '5m', '5:00', '1:02:03', '1h30m' -> seconds (for --limit)."""
    s = str(text).strip().lower().replace(" ", "")
    try:
        if ":" in s:
            secs = 0.0
            for p in s.split(":"):
                secs = secs * 60 + float(p)
        elif re.fullmatch(r"(\d+(\.\d+)?[hms])+", s):
            secs = sum(float(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, _, u in re.findall(r"(\d+(\.\d+)?)([hms])", s))
        else:
            secs = float(s)
    except ValueError:
        secs = -1
    if secs <= 0:
        raise ValueError(f"can't read {text!r} as a length of time; try 300, 5m, 5:00 or 1:30:00")
    return secs


def duration_arg(text):
    """argparse type for --limit."""
    try:
        return parse_duration(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


def limit_cues(cues, limit):
    """Only the subtitle lines that start before `limit` seconds (all of them if limit is None)."""
    return cues if not limit else [c for c in cues if c["start"] < limit]


def fmt_limit(limit):
    """300 -> '5:00' (for messages)."""
    t = int(round(limit))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def parse_ts(text):
    m = re.fullmatch(TS, text.strip())
    if not m:
        raise ValueError(f"bad timestamp: {text!r}")
    return ts_to_s(*m.groups())


def parse_srt(path):
    text = read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.split("\n")
        # find the timing line (index line is optional / sometimes missing)
        for i, line in enumerate(lines):
            m = re.match(TS + r"\s*-->\s*" + TS, line.strip())
            if m:
                g = m.groups()
                start, end = ts_to_s(*g[:4]), ts_to_s(*g[4:])
                body = "\n".join(lines[i + 1:]).strip()
                if body:
                    cues.append({"start": start, "end": end, "text": body})
                break
    for n, c in enumerate(cues, 1):
        c["n"] = n
    return cues


# ---------------------------------------------------------------- matching
def fold(s):
    """Lower-case and drop accents: 'Été, Straße, cœur' -> 'ete, strasse, coeur'. Curly apostrophes become '."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    for a, b in (("ß", "ss"), ("œ", "oe"), ("æ", "ae"), ("ø", "o"), ("ł", "l"), ("’", "'"), ("‘", "'")):
        s = s.replace(a, b)
    return s


def norm(s):
    s = re.sub(r"<[^>]+>|\{[^}]*\}", " ", s)          # strip tags
    s = re.sub(r"[^a-z0-9' ]+", " ", fold(s))
    return re.sub(r"\s+", " ", s).strip()


def find_cue(cues, needle, after_idx, occurrence=1):
    """Find the cue containing `needle`, preferring hits after the previous
    note's cue so repeated phrases resolve in order. Lines that span two cues
    are handled by also testing each cue joined with the next one."""
    n = norm(needle)
    if not n:
        return None
    normed = [norm(c["text"]) for c in cues]
    hits = []
    for i, here in enumerate(normed):
        if n in here:
            hits.append(i)
        elif i + 1 < len(normed) and n in here + " " + normed[i + 1] and n not in normed[i + 1]:
            hits.append(i)   # quote spans this cue and the next
    if not hits:
        return None
    ordered = [h for h in hits if h >= after_idx] + [h for h in hits if h < after_idx]
    if occurrence > 1:
        ordered = sorted(hits)
        return ordered[occurrence - 1] if occurrence <= len(ordered) else None
    return ordered[0]


# ---------------------------------------------------------------- ASS output
def fmt_ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def srt_to_ass_text(t):
    t = t.replace("{", "(").replace("}", ")") if not re.search(r"\{\\", t) else t
    t = re.sub(r"<\s*i\s*>", r"{\\i1}", t, flags=re.I)
    t = re.sub(r"<\s*/\s*i\s*>", r"{\\i0}", t, flags=re.I)
    t = re.sub(r"<\s*b\s*>", r"{\\b1}", t, flags=re.I)
    t = re.sub(r"<\s*/\s*b\s*>", r"{\\b0}", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)          # drop font/colour tags etc.
    return t.replace("\n", r"\N")


def escape_note(t):
    # keep the note literal: no override blocks, explicit line breaks only
    return t.replace("{", "(").replace("}", ")").replace("\n", r"\N")


# How long a note stays up: time to notice it, plus time to read it at a set pace, within a floor and a ceiling.
# The ceiling used to be 12 s, which cut 62 of Amélie's 100 notes short (a 40-word note got 0.30 s a word, with
# the film's own subtitles competing for the same eyes). Later defaults (150 words a minute, 6 s floor, 24 s
# ceiling, 0.4 s a word) were set for Erin's films, after friends found the notes went by too fast.
# Change per film with --reading-speed etc.
DEFAULT_TIMING = {"wpm": 150, "settle": 2.0, "min": 6.0, "max": 24.0}


def timing_settings(spec=None, **overrides):
    """DEFAULT_TIMING, then the notes file's "timing", then any non-None overrides (from the command line)."""
    out = dict(DEFAULT_TIMING)
    saved = (spec or {}).get("timing") if isinstance(spec, dict) else None
    for source in (saved if isinstance(saved, dict) else {}, overrides):
        for k, v in source.items():
            if k not in DEFAULT_TIMING or v is None:
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = -1
            if v <= 0:
                sys.exit(f'Note timing "{k}" must be a number above 0 (got {source[k]!r}). Check "timing" in the '
                         f'notes file.')
            out[k] = v
    if out["min"] > out["max"]:
        sys.exit(f"The shortest time on screen ({out['min']:g} s) is longer than the longest ({out['max']:g} s).")
    return out


def note_duration(text, override=None, timing=None):
    """Seconds on screen: settle time + words at the reading speed, kept between min and max. A note's own
    "duration" wins."""
    if override:
        return float(override)
    t = timing or DEFAULT_TIMING
    words = len(text.split())
    return min(t["max"], max(t["min"], t["settle"] + words * 60.0 / t["wpm"]))


def timing_report(placed, cues, timing):
    """How long notes stay up per word, and which ones the ceiling cuts short. Returns printable lines."""
    import statistics
    rows = [(p, len(p["text"].split())) for p in placed
            if p["category"].lower() != "about these notes" and not p.get("fixed_duration")]
    if not rows:
        return ["No notes to report on."]
    target = 60.0 / timing["wpm"]
    spw = [(p["end"] - p["start"]) / max(w, 1) for p, w in rows]
    rushed = sorted(((p["end"] - p["start"] - timing["settle"]) / max(w, 1), p, w) for p, w in rows
                    if p["end"] - p["start"] < timing["settle"] + w * target - 0.05)
    dlg = [(c["end"] - c["start"]) / max(len(c["text"].split()), 1) for c in cues if c["text"].split()]
    out = [f"Note timing: {timing['settle']:g} s to notice + {timing['wpm']:g} words a minute ({target:.2f} s a word), "
           f"kept between {timing['min']:g} and {timing['max']:g} s.",
           f"  {len(rows)} notes, {statistics.median(w for _, w in rows):.0f} words typical (longest {max(w for _, w in rows)}); "
           f"on screen {statistics.median(p['end'] - p['start'] for p, _ in rows):.1f} s typical, "
           f"{statistics.median(spw):.2f} s a word overall.",
           f"  {len(rushed)} note(s) cut short by the {timing['max']:g} s ceiling"
           + (f"; the worst get {rushed[0][0]:.2f} s a word to read:" if rushed else ".")]
    for r, p, w in rushed[:5]:
        out.append(f"    {fmt_ass_time(p['start']).split('.')[0]}  {w} words, {p['end'] - p['start']:.1f} s  "
                   f"{p['text'][:70]}...")
    if dlg:
        out.append(f"  For comparison, the dialogue subtitles stay up {statistics.median(dlg):.2f} s a word (median).")
    if rushed:
        out.append("  Longer notes need a higher --note-max (or a lower --reading-speed means everything stays longer).")
    return out


LAYOUTS = {
    # stack: every note in one column at the top-left
    "stack": {"speech": ("NoteL", 7), "visual": ("NoteL", 7)},
    # split: dialogue-based notes top-left, visual notes top-right
    "split": {"speech": ("NoteL", 7), "visual": ("NoteR", 9)},
}

HEADER = f"""[Script Info]
; Generated by make_ass.py - dialogue from the SRT, notes from notes.json
Title: {{title}}
ScriptType: v4.00+
PlayResX: {PLAY_X}
PlayResY: {PLAY_Y}
WrapStyle: 0
ScaledBorderAndShadow: yes
Collisions: Normal
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dialogue,Arial,{{dfs}},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1.5,2,120,120,55,1
Style: NoteL,Arial,{{fs}},&H00F0F0F0,&H000000FF,&H38101010,&H38101010,0,0,0,0,100,100,0,0,3,14,0,7,44,{{inner}},36,1
Style: NoteR,Arial,{{fs}},&H00F0F0F0,&H000000FF,&H38281810,&H38281810,0,0,0,0,100,100,0,0,3,14,0,9,{{inner}},44,36,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


# A note that appears while earlier notes are still on screen can stay up longer, but never past this many seconds
# from its start (an edge case: a burst of notes should not fill the screen).
LINGER_CEILING = 45.0


def linger(placed):
    """Half of each earlier note's own time on screen is added to a note that appears while that earlier note is
    still up. Each earlier note counts once. Notes with their own \"duration\" are left alone."""
    base_end = {id(p): p["end"] for p in placed}
    timed = sorted(placed, key=lambda p: p["start"])
    for j, p in enumerate(timed):
        if p["fixed_duration"]:
            continue
        extra = sum(0.5 * (base_end[id(q)] - q["start"]) for q in timed[:j] if base_end[id(q)] > p["start"])
        p["end"] = min(base_end[id(p)] + extra, p["start"] + LINGER_CEILING)


# At most this many notes on screen at once. This is the one hard limit: a note that would be the fourth waits for room.
MAX_ON_SCREEN = 3
# Each second the waiting note waits takes this much off every note still on screen (its timer).
CUT_PER_WAIT = 0.5


def make_room(placed):
    """When a note would be the fourth on screen, it waits until there's room. The earliest note to leave frees the
    slot. Each second the note waits, every note still on screen loses CUT_PER_WAIT seconds of its timer, so the
    earliest one ends at its start + wait. Notes with their own duration aren't shortened; if the earliest of those
    is the one leaving, the wait is just until it ends. Sets each note's final start and end (linger included)."""
    origin = {id(p): p["start"] for p in placed}
    base = {id(p): p["end"] - p["start"] for p in placed}
    waits, cuts = {}, {}
    while True:
        for p in placed:
            p["start"] = origin[id(p)] + waits.get(id(p), 0.0)
            p["end"] = p["start"] + base[id(p)] - cuts.get(id(p), 0.0)
        linger(placed)
        # Earlier notes' final ends don't depend on later notes, so the first note that needs room can be decided
        # now. Each decision is kept, so this loop runs at most once per note.
        order = sorted(placed, key=lambda p: p["start"])
        if not _decide_one_wait(order, base, waits, cuts):
            break
    for p in placed:
        if id(p) in waits:
            p["waited"] = waits[id(p)]
        if id(p) in cuts:
            p["cut"] = cuts[id(p)]


def _decide_one_wait(order, base, waits, cuts):
    """Find the first note that would be the fourth on screen and make it wait. Records its wait and the cut to
    each note still on screen. Returns False when no note needs room."""
    for j, p in enumerate(order):
        if id(p) in waits:
            continue
        on = [q for q in order[:j] if q["end"] > p["start"]]
        if len(on) < MAX_ON_SCREEN:
            continue
        first = min(on, key=lambda q: q["end"])
        if first["fixed_duration"]:
            wait, cut = first["end"] - p["start"], 0.0
        else:
            wait = (first["end"] - p["start"]) / (1 + CUT_PER_WAIT)
            cut = CUT_PER_WAIT * wait
        waits[id(p)] = wait
        for q in on:
            if not q["fixed_duration"]:
                left = max(base[id(q)] - cuts.get(id(q), 0.0), 0.0)     # a timer can't go below zero
                cuts[id(q)] = cuts.get(id(q), 0.0) + min(cut, left)
        return True
    return False


def place_notes(cues, notes, offset, timing=None, skip=()):
    """Resolve each note to a time window. Returns (placed, missing). `skip`: 0-based indexes to leave out
    (repeats found by dedupe.py); they still count for anchoring later notes in order."""
    placed, missing, last_idx = [], [], 0
    for k, note in enumerate(notes, 1):
        idx = None
        if "at_video" in note:            # already on the video's clock
            start = parse_ts(note["at_video"])
        elif "at" in note:                # on the subtitle file's clock
            start = parse_ts(note["at"]) + offset
        else:
            if "cue" in note:
                idx = int(note["cue"]) - 1
                if not 0 <= idx < len(cues):
                    idx = None
            elif "match" in note:
                idx = find_cue(cues, note["match"], last_idx, int(note.get("occurrence", 1)))
            if idx is None:
                missing.append((k, note.get("match") or note.get("cue")))
                continue
            last_idx = idx
            # By default a note appears just after its line finishes, so the
            # viewer hears the joke before reading the explanation.
            if note.get("when", "end") == "start":
                start = cues[idx]["start"] + offset
            else:
                start = cues[idx]["end"] + offset + 0.2
        if k - 1 in skip:
            continue
        start += float(note.get("delay", 0))
        text = note["text"].strip()
        placed.append({
            "k": k,
            "start": start,
            "end": start + note_duration(text, note.get("duration"), timing),
            "fixed_duration": bool(note.get("duration")),
            "kind": note.get("kind", "speech"),
            "category": note.get("category", "Note"),
            "confidence": note.get("confidence", "high").lower(),
            "text": text,
        })
    make_room(placed)
    return placed, missing


def overlap_report(placed):
    """How crowded would each layout be? Sampled every 0.1 s."""
    if not placed:
        return {}
    end = max(p["end"] for p in placed)
    stats = {"both_sides_s": 0.0, "max_left_split": 0, "max_right_split": 0, "max_stack": 0,
             "stack3_s": 0.0, "split3_s": 0.0}
    t = 0.0
    while t < end:
        sp = sum(1 for p in placed if p["kind"] == "speech" and p["start"] <= t < p["end"])
        vi = sum(1 for p in placed if p["kind"] == "visual" and p["start"] <= t < p["end"])
        if sp and vi:
            stats["both_sides_s"] += 0.1
        stats["max_left_split"] = max(stats["max_left_split"], sp)
        stats["max_right_split"] = max(stats["max_right_split"], vi)
        stats["max_stack"] = max(stats["max_stack"], sp + vi)
        if sp + vi >= 3:
            stats["stack3_s"] += 0.1
        if sp >= 3 or vi >= 3:
            stats["split3_s"] += 0.1
        t += 0.1
    return {k: round(v, 1) if isinstance(v, float) else v for k, v in stats.items()}


def plex_copy(out_path, language="English"):
    """UNFINISHED: doesn't work in Plex yet (see CLAUDE.md, Known pitfalls).
    Copy '<video>.notes.ass' to '<video>.en.ass'. Plex labels a subtitle file by the language code before the
    extension ('English (ASS)'), and shows '.notes.ass' as 'Unknown'. VLC keeps using the .notes.ass. A file of that
    name that this script didn't write is left alone. Returns the copy's path, or None."""
    out_path = Path(out_path)
    if not out_path.name.endswith(".notes.ass"):
        return None
    lang = languages.code(language) or "en"
    target = out_path.with_name(out_path.name[:-len(".notes.ass")] + f".{lang}.ass")
    if target.exists() and "Generated by make_ass.py" not in read_text(target)[:300]:
        print(f"Not writing the Plex copy: {target.name} already exists and isn't one of ours.")
        return None
    shutil.copyfile(out_path, target)
    print(f"Plex copy -> {target}")
    return target


def build(srt_path, notes_path, out_path, offset=0.0, layout="split", display_srt=None, display_offset=0.0,
          timing=None, keep_duplicates=False, font_scale=1.0, say=print):
    """display_srt: subtitles to show at the bottom instead of srt_path (e.g. English, when the notes were written
    from the French). Notes are still placed using srt_path; display_offset is for display_srt's own timing.
    timing: see timing_settings() (default: the notes file's own, else DEFAULT_TIMING). Repeated explanations
    (dedupe.py) are left out unless keep_duplicates."""
    cues = parse_srt(srt_path)
    if not cues:
        sys.exit(f"No subtitle cues found in {srt_path}")
    shown, shown_offset = cues, offset
    if display_srt:
        shown, shown_offset = parse_srt(display_srt), display_offset
        if not shown:
            sys.exit(f"No subtitle cues found in {display_srt}")
    spec = json.loads(read_text(notes_path))
    notes = spec["notes"] if isinstance(spec, dict) else spec
    title = spec.get("title", Path(srt_path).stem) if isinstance(spec, dict) else Path(srt_path).stem

    if timing is None:
        timing = timing_settings(spec if isinstance(spec, dict) else None)
    dups = []
    if not keep_duplicates:
        import dedupe
        dups, _ = dedupe.find_duplicates(notes)
    placed, missing = place_notes(cues, notes, offset, timing, skip={j for j, _, _ in dups})
    held = [p["waited"] for p in placed if p.get("waited")]
    if held:
        print(f"Made room for {len(held)} note(s) so no more than {MAX_ON_SCREEN} show at once: longest wait "
              f"{max(held):.1f} s; {sum(1 for p in placed if p.get('cut'))} note(s) shortened.")
    lay = LAYOUTS[layout]
    # split layout uses two narrower columns and a slightly smaller font
    fs, inner = (35, 1040) if layout == "split" else (38, 760)
    dfs = 58                                     # dialogue size
    if font_scale != 1.0:
        # Same box shape, just bigger: the text column grows with the type (capped at the screen width).
        text_w = min(PLAY_X - 88, round((PLAY_X - 44 - inner) * font_scale))
        fs, inner, dfs = round(fs * font_scale), PLAY_X - 44 - text_w, round(dfs * font_scale)

    events = []
    for c in shown:
        events.append((c["start"] + shown_offset, c["end"] + shown_offset, 0, "Dialogue", "", srt_to_ass_text(c["text"])))
    for p in placed:
        style, _ = lay[p["kind"]]
        colour = CATEGORY_COLOURS.get(p["category"].lower(), DEFAULT_LABEL_COLOUR)
        flag = "  {\\c&H8C8CFF&}(less sure){\\c&HF0F0F0&}" if p["confidence"] in ("low", "medium") else ""
        body = (
            "{\\fad(250,350)}"
            f"{{\\fs{fs - 9}\\b1\\c{colour}}}{escape_note(p['category'].upper())}{{\\b0}}{flag}"
            f"{{\\fs{fs}\\c&HF0F0F0&}}\\N{escape_note(p['text'])}"
        )
        # The Name field is ignored by renderers, so it carries the note's tags
        # (kind/category/confidence) for tools like the VLC extension to filter on.
        tag = f"{p['kind']}/{p['category'].lower()}/{p['confidence']}".replace(",", " ")
        events.append((p["start"], p["end"], 1, style, tag, body))

    events.sort(key=lambda e: (e[0], e[2]))
    out = [HEADER.replace("{title}", title).replace("{fs}", str(fs)).replace("{inner}", str(inner))
           .replace("{dfs}", str(dfs))]
    for s, e, layer, style, name, text in events:
        out.append(f"Dialogue: {layer},{fmt_ass_time(s)},{fmt_ass_time(e)},{style},{name},0,0,0,,{text}\n")
    Path(out_path).write_text("".join(out), encoding="utf-8-sig")

    n_sp = sum(1 for p in placed if p["kind"] == "speech")
    say(f"{len(shown)} dialogue cues" + (f" from {Path(display_srt).name}" if display_srt else "")
        + f", {len(placed)}/{len(notes)} notes placed "
        f"({n_sp} dialogue, {len(placed) - n_sp} visual), layout={layout} -> {out_path}")
    for k, what in missing:
        say(f"  ! note #{k} not matched: {what!r}")
    if dups:
        say(f"  Left out {len(dups)} repeated explanation(s) (python3 dedupe.py {Path(notes_path).name} lists them; "
            f"--keep-duplicates keeps them):")
        for j, i, why in dups[:8]:
            say(f"    #{j + 1} {why} (first in #{i + 1}): {notes[j]['text'][:60]}...")
        if len(dups) > 8:
            say(f"    ... and {len(dups) - 8} more")
    return placed, missing


def create_blank_notes(path, srt):
    """Start a notes file for a subtitle file that doesn't have one yet."""
    stem = Path(srt).stem
    skeleton = {
        "title": f"{stem} (context notes)",
        "audience": "Fluent in English, didn't grow up in the UK",
        "scope": "Dialogue notes come from the subtitles; visual notes (kind: visual) come from frames of the video",
        "notes": [],
    }
    path.write_text(json.dumps(skeleton, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"There was no notes file yet, so I created a blank one: {path.resolve()}")
    print("It has no notes in it. This script only merges notes into the subtitles; it doesn't write them.")
    print("To have Claude write them for you (uses API credits; first run  make_ass.py --set-api-key):")
    print(f"  python3 make_ass.py \"{srt}\" --generate")
    print("Or to fill it in by hand / with a chat:")
    print(f"  1. python3 analyze.py \"{srt}\"     (makes a numbered transcript to write notes from)")
    print(f"  2. give the transcript to Claude and ask for the notes, saved to {path.name}")
    print("  3. run this command again")
    print('Each note looks like:  {"match": "part of the line", "category": "idiom", "text": "The note.", "confidence": "high"}')


def display_choice(a, spec, notes_path):
    """Which subtitles to show, from --display-subs or the notes file's 'display_subtitles' (a file name beside the
    subtitle file). A new --display-subs is saved in the notes file so later rebuilds (e.g. after --refine) keep it;
    --display-subs <the main subtitle file> switches back. Returns (path or None, offset)."""
    if not isinstance(spec, dict):
        return (a.display_subs if a.display_subs and Path(a.display_subs).resolve() != Path(a.srt).resolve()
                else None), (a.display_offset or 0.0)
    changed = False
    if a.display_subs:
        if not Path(a.display_subs).exists():
            sys.exit(f"Can't find the subtitles to show: {a.display_subs}")
        if Path(a.display_subs).resolve() == Path(a.srt).resolve():
            changed = spec.pop("display_subtitles", None) is not None
            spec.pop("display_offset", None)
        elif spec.get("display_subtitles") != Path(a.display_subs).name:
            spec["display_subtitles"] = Path(a.display_subs).name
            changed = True
    if a.display_offset is not None and spec.get("display_subtitles"):
        changed = changed or spec.get("display_offset") != a.display_offset
        spec["display_offset"] = a.display_offset
    if changed:
        notes_path.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    name = spec.get("display_subtitles")
    if not name:
        return None, 0.0
    path = Path(a.display_subs) if a.display_subs else Path(a.srt).parent / name
    if not path.exists():
        print(f"  ! The notes file says to show {name}, but it isn't beside {Path(a.srt).name}; showing "
              f"{Path(a.srt).name} instead.")
        return None, 0.0
    return path, float(spec.get("display_offset", 0) or 0)


def remember_timing(a, spec, notes_path):
    """Timing from the command line is saved in the notes file ("timing"), so a rebuild after --refine keeps it."""
    given = {"wpm": a.reading_speed, "min": a.note_min, "max": a.note_max, "settle": a.note_settle}
    given = {k: v for k, v in given.items() if v is not None}
    timing_settings(spec if isinstance(spec, dict) else None, **given)      # check before saving anything
    if isinstance(spec, dict) and given:
        saved = dict(spec.get("timing") or {})
        if any(saved.get(k) != v for k, v in given.items()):
            saved.update(given)
            spec["timing"] = saved
            notes_path.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return timing_settings(spec if isinstance(spec, dict) else None, **given)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", nargs="?")
    ap.add_argument("notes", nargs="?",
                    help="notes JSON. Optional: defaults to notes-<subtitle name>.json in the current folder, "
                         "and a blank one is created there if it doesn't exist yet")
    ap.add_argument("-o", "--out", help="output .ass (default: <video>.notes.ass if --video, else SRT name + .ass)")
    ap.add_argument("--video", help="the video file. Normally used ONLY to name the output <video name>.notes.ass "
                                    "(what the VLC extension looks for) and never read; with --refine the "
                                    "video is analysed. Other video analysis lives in analyze.py")
    ap.add_argument("--offset", type=float, default=None,
                    help="shift subtitles by N seconds (default: notes file's video_offset, else 0)")
    ap.add_argument("--font-scale", type=float, default=1.0, metavar="X",
                    help="make notes and dialogue X times bigger, to find a good size. Writes a separate "
                         "<video>.notes-xX.ass and no Plex copy, so your normal .ass is left alone")
    ap.add_argument("--layout", choices=sorted(LAYOUTS), default="split",
                    help="split: dialogue notes left, visual notes right; stack: one column")
    ap.add_argument("--report", action="store_true", help="print how crowded each layout would be")
    ap.add_argument("--no-plex-copy", action="store_true",
                    help="don't also write <video>.en.ass (the name Plex labels 'English (ASS)')")
    t = ap.add_argument_group("how long notes stay on screen (remembered in the notes file once given)")
    t.add_argument("--reading-speed", type=float, metavar="WPM",
                   help=f"words a minute a note is timed for (default {DEFAULT_TIMING['wpm']})")
    t.add_argument("--note-min", type=float, metavar="S", help=f"shortest time on screen (default {DEFAULT_TIMING['min']:g} s)")
    t.add_argument("--note-max", type=float, metavar="S",
                   help=f"longest time on screen, so long notes don't pile up (default {DEFAULT_TIMING['max']:g} s)")
    t.add_argument("--note-settle", type=float, metavar="S",
                   help=f"time to notice a note before reading starts (default {DEFAULT_TIMING['settle']:g} s)")
    t.add_argument("--timing-report", action="store_true",
                   help="print how many seconds a word each note gets, and which ones the ceiling cuts short")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="keep notes that explain something an earlier note already explained (left out by default; "
                         "see dedupe.py)")
    g = ap.add_argument_group("writing the notes with Claude (uses API credits)")
    g.add_argument("--generate", action="store_true",
                   help="have Claude write the notes file from the subtitles, then build the .ass")
    g.add_argument("--refine", action="store_true",
                   help="improve the existing notes using the video (needs --video): sets the sync offset, adds "
                        "notes about what's on screen, fixes or retimes notes; backs up the notes and the old .ass "
                        "first, then rebuilds the .ass")
    g.add_argument("--frames", choices=("keyframes", "dense"), default="keyframes",
                   help="with --refine: keyframes (default, cheaper) or dense (4 a second: far more images, costs more)")
    g.add_argument("--assume-synced", action="store_true",
                   help="with --refine: trust that the subtitles are in step with the video (use with an "
                        ".aligned.srt from analyze.py --align). Without it, if the sync can't be confirmed, "
                        "--refine only adds on-screen notes and leaves your existing notes alone")
    g.add_argument("--set-api-key", action="store_true",
                   help="save your Anthropic API key to ~/.config/context-notes/api-key (hidden prompt) and exit")
    g.add_argument("--title", help="show/film and episode, e.g. 'The IT Crowd - S01E02 - Calamity Jen' "
                                   "(helps Claude get the facts right; default: the subtitle file name)")
    g.add_argument("--audience", help="who the notes are for (default: fluent in English, didn't grow up in the UK)")
    g.add_argument("--year", help="release year, e.g. 1974 (films more than 40 years old get extra attention to "
                                  "their words, people, places and period). Default: read from the title, the file's "
                                  "tags, the file name or the folder name")
    g.add_argument("--notes-language", default="English", help="language to write the notes in (default: English)")
    g.add_argument("--film-language", metavar="LANG",
                   help="language spoken in the film or show, e.g. fr, de, es (default: English). Changes what Claude "
                        "looks for: register (tu/vous), slang, regional speech, and what the subtitles lose in translation")
    g.add_argument("--original-subs", metavar="SRT",
                   help="with --film-language: subtitles in the ORIGINAL language, timed to the same video, so Claude can "
                        "compare them with the subtitles you watch with (e.g. film.fr.srt beside film.en.srt)")
    ap.add_argument("--display-subs", metavar="SRT",
                    help="show these subtitles at the bottom instead (e.g. film.en.srt when the notes were written from "
                         "film.fr.srt). Notes are still placed using the main subtitle file. Remembered in the notes "
                         "file; give the main subtitle file again to switch back")
    ap.add_argument("--display-offset", type=float, default=None,
                    help="shift the --display-subs subtitles by N seconds (default: remembered value, else 0)")
    g.add_argument("--limit", type=duration_arg, metavar="TIME",
                   help="with --generate/--refine: only the first part of the video, e.g. 5:00, 300 or 5m (for testing)")
    g.add_argument("--model", default=None, help="Claude model to use (default: claude-sonnet-5-5)")
    g.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default=None,
                   help="with --generate/--refine: the model's effort setting (default: the model's own default; "
                        "Haiku 4.5 doesn't support it)")
    g.add_argument("--max-tokens", type=int, default=None, metavar="N",
                   help="with --generate/--refine: reply limit per request (higher efforts may need more room)")
    g.add_argument("--yes", action="store_true", help="don't ask before sending the subtitles to the API")
    g.add_argument("--force", action="store_true", help="with --generate: replace an existing notes file (a .bak copy is kept)")
    g.add_argument("--api-key-file", help="read the API key from this file instead of the default location")
    g.add_argument("--api-url", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.set_api_key:
        import generate_notes
        generate_notes.set_key()
        return
    if not a.srt:
        ap.error("the subtitle file is required")
    if not Path(a.srt).exists():
        sys.exit(f"Can't find {a.srt}")
    if not a.notes:
        a.notes = f"notes-{Path(a.srt).stem}.json"          # current folder
    notes_path = Path(a.notes)
    if a.original_subs and not Path(a.original_subs).exists():
        sys.exit(f"Can't find the original-language subtitles {a.original_subs}")
    if a.generate:
        if notes_path.exists():
            spec = json.loads(read_text(a.notes))
            have = len(spec["notes"] if isinstance(spec, dict) else spec)
            if have and not a.force:
                sys.exit(f"{a.notes} already has {have} notes. Use --force to have Claude replace them "
                         f"(a backup copy is kept), or leave off --generate to build from the existing file.")
            if have:
                shutil.copy2(notes_path, str(notes_path) + ".bak")
                print(f"Kept a backup: {notes_path}.bak")
        import generate_notes
        kw = {"model": a.model or generate_notes.DEFAULT_MODEL}
        if a.api_url:
            kw["api_url"] = a.api_url
        if a.effort:
            kw["effort"] = a.effort
        if a.max_tokens:
            kw["max_tokens"] = a.max_tokens
        generate_notes.generate(a.srt, notes_path, audience=a.audience, title=a.title,
                                year=generate_notes.resolve_year(a.year, a.video or a.srt, a.title),
                                language=a.notes_language, assume_yes=a.yes, key_file=a.api_key_file,
                                film_language=a.film_language, original_srt=a.original_subs, limit=a.limit,
                                video_offset=a.offset, **kw)
    elif not notes_path.exists():
        create_blank_notes(notes_path, a.srt)
        return
    else:
        spec = json.loads(read_text(a.notes))
        if not (spec["notes"] if isinstance(spec, dict) else spec):
            sys.exit(f"{a.notes} has no notes in it yet, so there is nothing to merge. "
                     f"Add notes to it, or run again with --generate to have Claude write them.")
    if a.out:
        out = a.out
    elif a.video:
        out = str(Path(a.video).with_suffix("")) + (f".notes-x{a.font_scale:g}.ass" if a.font_scale != 1.0 else ".notes.ass")
    else:
        out = str(Path(a.srt).with_suffix(".ass"))
    if a.refine:
        if not a.video:
            sys.exit("--refine needs the video: add  --video \"<the video file>\"")
        if not Path(a.video).exists():
            sys.exit(f"Can't find the video {a.video}")
        import generate_notes
        import refine_notes
        rkw = {k: v for k, v in (("api_url", a.api_url), ("effort", a.effort), ("max_tokens", a.max_tokens)) if v}
        refine_notes.refine(a.srt, notes_path, a.video, model=a.model or generate_notes.DEFAULT_MODEL,
                            frames=a.frames, ass_path=out, audience=a.audience, title=a.title, language=a.notes_language,
                            assume_yes=a.yes, key_file=a.api_key_file, assume_synced=a.assume_synced,
                            film_language=a.film_language, original_srt=a.original_subs, limit=a.limit,
                            year=a.year, **rkw)
    offset = a.offset
    spec = json.loads(read_text(a.notes))
    if offset is None:
        offset = float(spec.get("video_offset", 0)) if isinstance(spec, dict) else 0.0
    display, display_offset = display_choice(a, spec, notes_path)
    timing = remember_timing(a, spec, notes_path)
    placed, _ = build(a.srt, a.notes, out, offset, a.layout, display, display_offset, timing=timing,
                      keep_duplicates=a.keep_duplicates, font_scale=a.font_scale)
    if not a.no_plex_copy and a.font_scale == 1.0:
        plex_copy(out, a.notes_language)
    if a.report:
        print(json.dumps(overlap_report(placed), indent=1))
    if a.timing_report:
        print("\n".join(timing_report(placed, parse_srt(a.srt), timing)))


if __name__ == "__main__":
    main()
