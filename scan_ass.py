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
  - whether the Plex copy (<stem>.en.ass) is there and matches the notes file.

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

FLOOR = make_ass.DEFAULT_TIMING["min"]
TOLERANCE = 0.25
# Files saved after the three-note limit was added (commit 26b77587) already have it in their start times, so the
# scan doesn't apply the rules to them a second time.
HOLD_RULE_SINCE = datetime(2026, 10, 21, 22, 37)


def parse_time(text):
    h, m, s = text.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


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
            "start": parse_time(parts[1]), "end": parse_time(parts[2]), "text": clean(parts[9]),
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
    return {"notes": len(notes), "stored": stored, "current": current, "before": before, "after": after, "held": held,
            "short": short, "dups": dups, "similar": similar, "plex": plex_state}


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
    return 0


if __name__ == "__main__":
    sys.exit(main())
