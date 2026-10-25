#!/usr/bin/env python3
"""
dedupe.py - find notes that explain the same thing twice.

A film's notes are written in parts (and, for chat-written notes, sometimes in several sittings), so the same
idiom, person or place can get explained again an hour later. make_ass.py runs this on every build and leaves
the repeats out of the .ass; the notes file itself is never changed. To look without building:

    python3 dedupe.py notes-film.json              list the repeats (and near-misses worth a look)

A note is a repeat of an earlier one when:
  - both are about the same quoted term or name and the later one mostly says the same thing, or
  - both lead with the same subject ("'Battre la chamade': ..." twice), or
  - the two texts are nearly the same, whatever they are about.
Never treated as repeats: running gags, setups and payoffs (calling back is their point), the "About these
notes" intro, and any note with "keep": true.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fileio  # noqa: E402
import subtitles  # noqa: E402

EXEMPT = {"running gag", "setup", "payoff", "about these notes"}

# Words that say nothing about a note's subject (English: the notes are written in English by default).
STOP = set("""
a an the and or but nor so yet of to in on at by for with from into onto about as than then that this these those it its
it's is are was were be been being has have had do does did not no can could will would shall should may might must
here there where when what which who whom whose why how all any both each few more most other some such only own same
very just also too again ever even still really quite rather much many one two his her hers him he she they them their
theirs you your yours we our ours i me my mine us film scene line joke means meaning word phrase literally term used
says said say calls called call like gets get got make makes made way thing things something someone kind sort
""".split())

LEAD_COLON = re.compile(r"^\s*([^.:;!?]{2,40}?)\s*:\s")       # 'Kaleun: short for ...'


def terms(text):
    """Content words of a note, accents folded: 'The Maginot Line failed' -> {'maginot', 'line', 'failed'}."""
    return {w.strip("'") for w in re.findall(r"[a-z0-9']+", subtitles.fold(text))
            if len(w.strip("'")) > 2 and w.strip("'") not in STOP}


def _clean(s):
    return subtitles.norm(s)


OPEN, CLOSE = "‘'“\"«„", "’'”\"»“"


def quote_spans(text):
    """(start, inner text) of each quoted stretch. A straight or curly apostrophe inside a word (it's, Gainsbourg's,
    d'Enghien) is not a quote mark: an opening mark must not follow a letter, a closing one must not precede one."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch in OPEN and not (i and text[i - 1].isalnum()) and i + 1 < n and text[i + 1].isalnum():
            for j in range(i + 1, min(n, i + 62)):
                if text[j] in CLOSE and not (j + 1 < n and text[j + 1].isalpha()) and text[j - 1] != " ":
                    if j - i - 1 >= 2:
                        out.append((i, text[i + 1:j]))
                    i = j
                    break
        i += 1
    return out


def quoted(text):
    """Quoted terms in a note ('kir', “Le Poinçonneur des Lilas”), normalised."""
    found = set()
    for _, inner in quote_spans(text):
        q = _clean(inner)
        words = q.split()
        if words and len(words) <= 6 and (len(words) > 1 or len(q) >= 3):
            found.add(q)
    return found


def lead(text):
    """The subject a note opens with: a quoted term in its first few words, or 'Term: ...'. '' if none."""
    spans = quote_spans(text[:80])
    if spans and spans[0][0] <= 25:
        return _clean(spans[0][1])
    m = LEAD_COLON.match(text)
    if m and len(m.group(1).split()) <= 5:
        return _clean(m.group(1))
    return ""


# "History: ...", "Pun: ..." label the kind of note, not its subject.
GENERIC_LEADS = {"history", "historical context", "note", "pun", "wordplay", "reference", "cultural reference", "context",
                 "trivia", "idiom", "slang", "translation", "register", "dialect", "joke", "visual gag", "prop",
                 "background", "staging", "costume", "delivery", "fun fact", "aside", "nb", "fact", "detail"}


def subjects(note):
    """What a note is about: its quoted terms and its lead subject."""
    text = note.get("text", "")
    out = quoted(text)
    if lead(text):
        out.add(lead(text))
    return {s for s in out if s and s not in GENERIC_LEADS}


def exempt(note):
    return (note.get("keep") is True or str(note.get("category", "")).strip().lower() in EXEMPT
            or not str(note.get("text", "")).strip())


def compare(a, b):
    """Is note b (later) a repeat of note a? Returns ('duplicate' | 'similar' | None, reason)."""
    ta, tb = terms(a["text"]), terms(b["text"])
    if not ta or not tb:
        return None, ""
    jac = len(ta & tb) / len(ta | tb)
    novel = len(tb - ta) / len(tb)                     # how much of b is new
    shared = subjects(a) & subjects(b)
    la, lb = lead(a["text"]), lead(b["text"])
    ma, mb = _clean(a.get("match", "")), _clean(b.get("match", ""))
    if jac >= 0.5 and min(len(ta), len(tb)) >= 6:      # short notes share words by chance ("slur for Germans")
        return "duplicate", "says nearly the same thing"
    if la and la == lb and la not in GENERIC_LEADS:
        return "duplicate", f"explains ‘{la}’ again"
    if shared and novel < 0.5:
        return "duplicate", f"explains ‘{sorted(shared, key=len)[-1]}’ again"
    if ma and ma == mb and jac >= 0.25:
        return "duplicate", f"a second note on ‘{ma}’"
    if shared or jac >= 0.3:
        why = f"both mention ‘{sorted(shared, key=len)[-1]}’" if shared else "a lot of overlap"
        return "similar", why
    return None, ""


def find_duplicates(notes):
    """Repeats in a list of notes, in order. Returns (duplicates, similar): lists of
    (later index, earlier index, reason), 0-based. A repeat is compared only with notes that are kept,
    so a third copy points at the first one, not the second."""
    dups, similar, kept = [], [], []
    for j, b in enumerate(notes):
        if exempt(b):
            continue
        verdict, why, first = None, "", None
        for i in kept:
            v, w = compare(notes[i], b)
            if v == "duplicate":
                verdict, why, first = v, w, i
                break
            if v == "similar" and verdict is None:
                verdict, why, first = v, w, i
        if verdict == "duplicate":
            dups.append((j, first, why))
            continue
        if verdict == "similar":
            similar.append((j, first, why))
        kept.append(j)
    return dups, similar


def main():
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    spec = json.loads(fileio.read_text(sys.argv[1]))
    notes = spec["notes"] if isinstance(spec, dict) else spec
    dups, similar = find_duplicates(notes)

    def where(n):
        return n.get("match") or n.get("at_video") or n.get("at") or f"cue {n.get('cue')}"
    print(f"{len(notes)} notes: {len(dups)} repeat(s) that make_ass.py leaves out, {len(similar)} near-miss(es) it keeps.")
    for title, rows in (("Left out (repeats)", dups), ("Kept, but worth a look", similar)):
        if rows:
            print(f"\n{title}:")
        for j, i, why in rows:
            print(f"  #{j + 1} ({where(notes[j])!r}) {why}; first in #{i + 1} ({where(notes[i])!r})")
            print(f"      first: {notes[i]['text'][:110]}")
            print(f"      again: {notes[j]['text'][:110]}")
    if dups:
        print('\nTo keep a repeat anyway, add  "keep": true  to that note in the notes file.')


if __name__ == "__main__":
    main()
