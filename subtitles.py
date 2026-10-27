#!/usr/bin/env python3
"""
subtitles.py - reading and writing .srt files, and finding a quoted line in them. Standard library only.

    parse_srt(path)            [{"n", "start", "end", "text"}], numbered from 1
    limit_cues(cues, limit)    only the lines that start before `limit` seconds
    write_srt(cues, assigned, out)   the lines in `assigned` ({index: seconds to move}), renumbered, all at once
    fold(s), norm(s)           text compared without case, accents or punctuation
    find_cue(cues, quote, after_idx, occurrence)   the line a note's quote is in
"""
import re
import unicodedata

from fileio import read_text, write_text_safely
from timecode import TS, srt_ts, ts_to_s


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


def limit_cues(cues, limit):
    """Only the subtitle lines that start before `limit` seconds (all of them if limit is None)."""
    return cues if not limit else [c for c in cues if c["start"] < limit]


def write_srt(cues, assigned, out):
    blocks, n = [], 0
    for i, c in enumerate(cues):
        if i not in assigned:
            continue
        n += 1
        s, e = c["start"] + assigned[i], c["end"] + assigned[i]
        blocks.append(f"{n}\n{srt_ts(s)} --> {srt_ts(e)}\n{c['text']}\n\n")
    write_text_safely(out, "".join(blocks))             # all at once: never half a subtitle file


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
