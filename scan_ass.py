#!/usr/bin/env python3
"""
scan_ass.py - check built notes (.notes.ass) against the current rules, without rebuilding anything.

    python3 scan_ass.py "/Volumes/Media"          every *.notes.ass under the folder (skips .bak files)
    python3 scan_ass.py one.notes.ass             one file

For each file it reports:
  - how many notes are on screen at once as stored in the file, and for how long four or more are up;
  - the same numbers if today's rules (linger, then the three-note limit) were applied to the file's note start times;
  - notes on screen for less than the 6 s floor (less 0.25 s tolerance) and shorter than today's timing gives;
  - repeats (dedupe.py rules, on the text in the file);
  - whether the Plex copy (<stem>.en.ass) is there and matches the notes file;
  - the notes file (notes-<stem>.json) beside it: missing, or newer than the .ass (so a rebuild is due);
  - notes whose own timer would change under today's timing, notes read faster than a word a third of a second, and
    notes that appear within half a second of another (a cluster).

It reads only the .ass files (and the Plex copy's size). It never changes a file and uses no API credits.

Created: 2026-10-21
Modified: 2026-10-21
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import dedupe
import make_ass
import timecode

FLOOR = make_ass.DEFAULT_TIMING["min"]
TOLERANCE = 0.25
# Files saved after the three-note limit was added (commit 26b77587) already have it in their start times, so the
# scan doesn't apply the rules to them a second time.
HOLD_RULE_SINCE = datetime(2026, 10, 21, 22, 37)


def clean(text):
    """The words on screen, without the formatting tags and line breaks."""
    text = re.sub(r"\{[^}]*\}", " ", text).replace("\\N", " ").replace("\\n", " ")
    return " ".join(text.split())


def read_notes(path):
    """Note events (NoteL and NoteR styles) from a built .ass file, in file order."""
    notes = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("Dialogue: 1,"):
            continue
        parts = line.split(",", 9)
        style, name = parts[3], parts[4]
        if style not in ("NoteL", "NoteR"):
            continue
        kind, category, confidence = (name.split("/") + ["", "", ""])[:3]
        notes.append({
            "start": timecode.parse_time(parts[1]), "end": timecode.parse_time(parts[2]), "text": clean(parts[9]),
            "category": category, "kind": kind, "confidence": confidence,
        })
    return notes


def four_plus(windows):
    """Seconds (0.1 s steps) with four or more windows up, and the most up at once."""
    if not windows:
        return 0.0, 0
    end = max(e for _, e in windows)
    seconds, most, t = 0.0, 0, 0.0
    while t < end:
        n = sum(1 for s, e in windows if s <= t < e)
        most = max(most, n)
        if n >= make_ass.MAX_ON_SCREEN + 1:
            seconds += 0.1
        t += 0.1
    return round(seconds, 1), most


def projection(notes):
    """What today's rules would do with these start times: each note's own time, linger, then the three-note limit."""
    placed = [{"start": n["start"], "end": n["start"] + make_ass.note_duration(n["text"], None, make_ass.DEFAULT_TIMING),
               "fixed_duration": False} for n in notes]
    make_ass.linger(placed)
    before = four_plus([(p["start"], p["end"]) for p in placed])
    make_ass.make_room(placed)
    held = [p["waited"] for p in placed if p.get("waited")]
    after = four_plus([(p["start"], p["end"]) for p in placed])
    return before, after, held


def scan(path):
    notes = read_notes(path)
    stored = four_plus([(n["start"], n["end"]) for n in notes])
    current = datetime.fromtimestamp(path.stat().st_mtime) >= HOLD_RULE_SINCE
    before, after, held = (stored, stored, []) if current else projection(notes)
    short = [n for n in notes if n["end"] - n["start"] < FLOOR - TOLERANCE
             and n["end"] - n["start"] < make_ass.note_duration(n["text"], None, make_ass.DEFAULT_TIMING) - 0.05]
    ordered = sorted(notes, key=lambda n: n["start"])
    dups, similar = dedupe.find_duplicates([{"text": n["text"], "category": n["category"], "match": ""}
                                            for n in ordered])
    plex = path.with_name(path.name[:-len(".notes.ass")] + ".en.ass")
    if plex.exists():
        plex_state = "same size" if plex.stat().st_size == path.stat().st_size else "DIFFERENT size (rebuild it)"
    else:
        plex_state = "no Plex copy"
    return {"extra": extra_checks(path, notes), "notes": len(notes), "stored": stored, "current": current,
            "before": before, "after": after, "held": held,
            "short": short, "dups": dups, "similar": similar, "plex": plex_state}


def notes_file(path):
    """The notes file this .ass was built from (notes-<stem>.json, or a variant such as .aligned.json), newest first."""
    stem = path.name[:-len(".notes.ass")]
    names = {stem, stem.split()[0]}                       # "S01E01 Yesterdays Jam" also matches "notes-S01E01.json"
    found = [p for name in names for p in path.parent.glob(f"notes-{name}*.json") if not p.name.endswith(".bak")]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def extra_checks(path, notes):
    """Checks that need no speech recognition: is the notes file missing or newer, do the timers match today's
    timing, are notes read too fast, do notes bunch up, and is the Plex copy byte-for-byte the same."""
    out = {}
    src = notes_file(path)
    out["notes_file"] = "missing" if src is None else (
        "newer than the .ass, rebuild" if src.stat().st_mtime > path.stat().st_mtime else "older or same age")
    retimed = [n for n in notes if abs((n["end"] - n["start"]) - make_ass.note_duration(
        n["text"], None, make_ass.DEFAULT_TIMING)) > 0.5]
    out["retimed"] = len(retimed)
    out["fast"] = [n for n in notes if n["text"] and (n["end"] - n["start"]) / len(n["text"].split()) < 0.33]
    ordered = sorted(notes, key=lambda n: n["start"])
    out["bunched"] = sum(1 for a, b in zip(ordered, ordered[1:]) if b["start"] - a["start"] < 0.5)
    seen, out["exact_repeats"] = set(), 0
    for n in ordered:
        out["exact_repeats"] += n["text"] in seen
        seen.add(n["text"])
    plex = path.with_name(path.name[:-len(".notes.ass")] + ".en.ass")
    out["plex_identical"] = plex.exists() and plex.read_bytes() == path.read_bytes()
    out["categories"] = sorted({n["category"].lower() for n in notes})
    return out


def files_under(target):
    target = Path(target)
    if target.is_file():
        return [target]
    return sorted(p for p in target.rglob("*.notes.ass") if not p.name.endswith(".bak"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("target", help="a folder (searched recursively) or one .notes.ass file")
    a = ap.parse_args(argv)
    files = files_under(a.target)
    if not files:
        sys.exit(f"No .notes.ass files under {a.target}")
    for path in files:
        r = scan(path)
        rel = path.parent.name + "/" + path.name if path.parent.name else path.name
        print(f"\n{rel}")
        print(f"  {r['notes']} notes. As stored: most on screen {r['stored'][1]}, four or more for {r['stored'][0]} s.")
        if r["current"]:
            print("  Saved after the three-note limit, so these are today's numbers.")
        else:
            print(f"  Today's rules on these start times: most on screen {r['after'][1]}, four or more for "
                  f"{r['after'][0]} s (before the limit: {r['before'][1]} at once, {r['before'][0]} s).")
            if r["held"]:
                print(f"  The limit would hold {len(r['held'])} note(s), longest wait {max(r['held']):.1f} s.")
        if r["short"]:
            print(f"  {len(r['short'])} note(s) are on screen for less than {FLOOR:g} s, shorter than today's timing "
                  f"gives (the file was built with older timing; rebuild to lengthen them).")
            for n in r["short"][:5]:
                print(f"    {n['start']:.1f} s: {n['text'][:60]!r}")
        if r["dups"]:
            print(f"  {len(r['dups'])} repeated note(s) would be left out (dedupe.py).")
        print(f"  Plex copy: {r['plex']}.")
        x = r["extra"]
        print(f"  Notes file: {x['notes_file']}. {x['retimed']} note(s) would get a different on-screen time "
              f"under today's timing. {len(x['fast'])} note(s) read faster than a third of a second a word. "
              f"{x['bunched']} pair(s) start within half a second. {x['exact_repeats']} exact repeat(s).")
        if x["plex_identical"]:
            print("  Plex copy is byte-for-byte the notes file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
