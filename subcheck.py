#!/usr/bin/env python3
"""
subcheck.py - look for damaged subtitles: the strange characters a bad rip or a wrong conversion leaves behind.
Created 2026-10-30, modified 2026-10-30.

    python3 subcheck.py film.srt                    one subtitle file
    python3 subcheck.py film.mkv                    the .srt files beside a video
    python3 subcheck.py film.mkv --inside           ...and the text tracks inside it (reads the whole video: slow on a NAS)
    python3 subcheck.py "/Volumes/TV Shows/Show" --recursive --inside

tidy.py runs the same check with --check-subs. It looks for:
  - mangled characters: UTF-8 text read as Latin-1 or Windows-1252 and saved again ("Ã©" for "é", "â€™" for "'",
    "Î½" for "ν");
  - look-alike letters: a Greek or Cyrillic letter inside a Latin word ("loνes" with a Greek nu), which text
    recognition (OCR) of picture subtitles makes;
  - broken words, English only: OCR's stray spaces ("all rig ht", "g raveyard", "thing .");
  - "l" for "I", English only: OCR reading a capital I as a small L ("l told you");
  - the replacement character "�", where something along the way couldn't read a character;
  - mislabeled or corrupted: a file or track named or tagged English whose text is clearly French (or another
    language languages.py knows).
Nothing is changed: it only reports. Subtitles pulled out of a video for the check are written to a temporary
folder and deleted.
"""
import argparse
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompts  # noqa: E402,F401  (Ctrl-Break from the app; see CLAUDE.md, Windows)
import languages  # noqa: E402
from fileio import read_text  # noqa: E402

# Characters UTF-8 bytes turn into when read as Windows-1252 (or Latin-1): the lead byte (Â-ô) and what follows.
_CP1252_HIGH = "€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ"
MOJIBAKE_RUN = re.compile(f"[Â-ô][\u0080-¿{_CP1252_HIGH}]+")
LONE_CONSONANT = re.compile(r"(?<![\w'’-])[b-df-hjkmnp-tv-xz](?![\w'’-])")       # "rig ht", "g reat": not a, i, o, l
L_FOR_I = re.compile(r"(?<![\w'’.-])l(?=(?:'[a-z]{1,2})?(?![\w'’.-]))")              # "l told", "l'm", "l'll"
SPACE_BEFORE_STOP = re.compile(r"\w [.,!?](?![.\w])")                         # "thing ." but not "well ..."
TAGS = re.compile(r"<[^>]+>|\{[^}]*\}")
EXAMPLES = 3

KINDS = {
    "mangled": "mangled characters (UTF-8 read as Latin-1 or Windows-1252)",
    "lookalike": "words with a Greek or Cyrillic look-alike letter (from text recognition)",
    "broken": "lines with words broken by stray spaces (from text recognition)",
    "l-for-I": "lines with a small L where a capital I belongs (from text recognition)",
    "unreadable": "unreadable characters (\ufffd)",
    "mislabeled": "mislabeled or corrupted: the language it's labeled with isn't the language of its text",
}
BROKEN_SHARE = 0.01        # broken words count only above 1% of lines (and at least 5): a stray "x" isn't damage


def unmangle(run):
    """What a run of mangled characters was, or None if it isn't one: 'Î½' -> 'ν', 'â€™' -> '’'."""
    for enc in ("cp1252", "latin-1"):
        try:
            fixed = run.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        if fixed != run:
            return fixed
    return None


def script_of(ch):
    name = unicodedata.name(ch, "")
    return name.split(" ", 1)[0] if name else ""


def lookalike_words(text):
    """Words that mix Latin letters with Greek or Cyrillic ones."""
    out = []
    for word in re.findall(r"\w+", text):
        scripts = {script_of(c) for c in word if c.isalpha()}
        if "LATIN" in scripts and scripts & {"GREEK", "CYRILLIC"}:
            out.append(word)
    return out


def problems(text, lang=None):
    """{kind: (count, [examples])} for one subtitle file's text; empty when it looks fine. `lang`: a two-letter
    code, or None to guess it from the text (the broken-word and "l" checks are for English only)."""
    found = {}

    def add(kind, n, example):
        count, examples = found.get(kind, (0, []))
        if len(examples) < EXAMPLES and example not in examples:
            examples.append(example)
        found[kind] = (count + n, examples)

    lines = [TAGS.sub("", line) for line in text.splitlines()
             if line.strip() and "-->" not in line and not line.strip().isdigit()]
    repaired = []
    for line in lines:
        fixed = line
        for m in MOJIBAKE_RUN.finditer(line):
            was = unmangle(m.group())
            if was:
                add("mangled", 1, f"{m.group()} (should be {was})")
                fixed = fixed.replace(m.group(), was, 1)
        repaired.append(fixed)
        if "\ufffd" in line:
            add("unreadable", line.count("\ufffd"), line.strip())
    for line in repaired:                        # after repair, so "loÎ½es" is also counted as "loνes"
        for word in lookalike_words(line):
            add("lookalike", 1, word)
    said, lang = lang, languages.guess("\n".join(repaired))
    if said and lang and not languages.same(said, lang):
        add("mislabeled", 1, f"labeled {languages.name(said)}, but reads as {languages.name(lang)}")
    lang = said or lang
    if lang == "en":                             # other languages have one-letter words ("s", "z", "w", "k")
        for kind, test in (("broken", lambda t: LONE_CONSONANT.search(t) or SPACE_BEFORE_STOP.search(t)),
                           ("l-for-I", L_FOR_I.search)):
            hits = [line for line in repaired if test(line)]
            if len(hits) >= 5 and len(hits) >= BROKEN_SHARE * len(repaired):
                for line in hits:
                    add(kind, 1, line.strip())
    return found


def describe(found):
    """One line per kind of damage, for printing."""
    return [f"{n} {KINDS[kind]}, e.g. " + "; ".join(repr(e) for e in examples)
            for kind, (n, examples) in found.items()]


def check_file(path, lang=None):
    return problems(read_text(path), lang)


def beside(video):
    """The .srt files beside a video, with the language their names give: [(path, lang)]."""
    out = []
    for p in sorted(video.parent.glob(glob_escape(video.stem) + ".*srt")):
        if p.suffix.lower() == ".srt" and p.is_file() and not p.name.startswith("."):
            out.append((p, languages.from_filename(p.name, video.stem)[0]))
    return out


def glob_escape(s):
    return re.sub(r"([*?\[])", r"[\1]", s)


def inside(video):
    """Each text subtitle track inside a video, pulled out to a temporary file: [(track, problems)].
    This reads the whole video."""
    import analyze
    tracks = [t for t in analyze.subtitle_tracks(video) if t["text"]]
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for t in tracks:
            srt = Path(tmp) / f"track{t['n']}.srt"
            try:
                analyze.extract_subtitles(video, t, srt)
            except SystemExit as e:
                out.append((t, {"unreadable": (0, [f"couldn't pull it out: {e}"])}))
                continue
            out.append((t, check_file(srt, languages.code(t["lang"]))))
    return out


def check_video(video, look_inside=False):
    """[(where, problems)] for every subtitle of one video that has damage. `where` is a file name or
    'inside, track N (language)'."""
    out = []
    for p, lang in beside(video):
        found = check_file(p, lang)
        if found:
            out.append((p.name, found))
    if look_inside:
        for t, found in inside(video):
            if found:
                label = languages.name(t["lang"]) if languages.code(t["lang"]) else "language not set"
                if t["title"] and t["title"].lower() != label.lower():
                    label += f", {t['title']}"
                out.append((f"inside, track {t['n'] + 1} ({label})", found))
    return out


def report(video, damaged):
    """Print one video's damage and send it to a GUI (event subs-check, docs/gui-protocol.md)."""
    for where, found in damaged:
        print(f"{video.name}: {where}")
        for line in describe(found):
            print(f"    {line}")
        prompts.event("subs-check", video=str(video), where=where,
                      problems={k: {"count": n, "examples": ex} for k, (n, ex) in found.items()})


def videos_under(path, recursive):
    import workfiles
    if path.is_file():
        return [path]
    walk = os.walk(path) if recursive else [(str(path), [], os.listdir(path))]
    out = []
    for root, dirs, files in walk:
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != workfiles.FOLDER)
        out += [Path(root) / f for f in sorted(files)
                if Path(f).suffix.lower() in workfiles.VIDEO_EXTS and not f.startswith(".")]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="a subtitle file, a video, or a folder of videos")
    ap.add_argument("--recursive", action="store_true", help="with a folder: include every folder under it")
    ap.add_argument("--inside", action="store_true",
                    help="also check the text tracks inside each video (reads the whole video)")
    a = ap.parse_args(argv)
    path = Path(os.path.abspath(Path(a.path).expanduser()))
    if not path.exists():
        sys.exit(f"Can't find {path}")
    if path.suffix.lower() == ".srt":
        found = check_file(path, languages.from_filename(path.name, path.name.split(".")[0])[0])
        for line in describe(found) or ["Looks fine."]:
            print(line)
        return 1 if found else 0
    return check_folder(path, a.recursive, a.inside)


def check_folder(path, recursive=False, look_inside=False):
    """Check every video's subtitles under `path` and print what's damaged. Returns 1 if any are."""
    videos = videos_under(path, recursive)
    if look_inside and len(videos) > 1:
        print(f"Checking the subtitles of {len(videos)} videos, inside them too: each video is read in full, "
              "which takes a minute or two each over a network drive.")
    damaged = 0
    for i, video in enumerate(videos, 1):
        if look_inside:
            prompts.progress("subs-check", i - 1, len(videos), "videos")
        found = check_video(video, look_inside)
        if found:
            damaged += 1
            report(video, found)
    if look_inside:
        prompts.progress("subs-check", len(videos), len(videos), "videos")
    where = "beside and inside" if look_inside else "beside"
    print(f"Checked the subtitles {where} {len(videos)} video(s): "
          + (f"{damaged} with damage." if damaged else "none damaged."))
    if damaged:
        print("Nothing was changed. A clean copy from another source, or OpenSubtitles (find_subs.py), will fix it.")
    return 1 if damaged else 0


if __name__ == "__main__":
    sys.exit(main())
