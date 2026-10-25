#!/usr/bin/env python3
"""chat_notes.py - write the dialogue notes in a claude.ai chat (your subscription) instead of through the API.

The chat sees exactly what the API step would: the same instructions, the same numbered lines, the same parts.

  1. python3 chat_notes.py prepare film.mkv film.srt [--film-language de --original-subs film.de.srt] [--title "..."]
        -> film.chat-upload.txt   upload this file to a chat in the Project and say "go all"; if a reply ends with
                                  "CONTINUE FROM PART k", say "go all" again
  2. paste every reply, one after another, into one text file, e.g. film.chat-replies.txt
     (to improve a thin part, say "redo k" in the chat and paste that reply at the end: the last PART k wins)
  3. python3 chat_notes.py collect film.mkv film.srt film.chat-replies.txt [same --film-language/--original-subs]
        -> notes-<video name>.json beside the video (checked: every quote is looked up in the subtitles)
  4. either build the subtitles with no API use at all:
        python3 make_ass.py film.srt notes-film.json --video film.mkv
     or let the API add the on-screen notes (the refine step only; generate is skipped because the notes exist):
        python3 context_notes.py film.mkv --model claude-opus-5-5 --effort high

Or let Claude Code write them on your subscription: /notes in this project folder runs the note-writer agent once
per part (chat_notes.py show prints a part for it), each reply saved as <folder>/part-<k>.txt; collect takes the folder.

For a film not in English that you watch with English subtitles: give the English file as SRT and the original as
--original-subs, with --film-language (e.g. de). Use the same files and options in both steps.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dedupe  # noqa: E402
import generate_notes as gn  # noqa: E402
import make_ass  # noqa: E402

MARK = "CONTEXT-NOTES UPLOAD v1"


def setup(a, say=print):
    cues = make_ass.parse_srt(a.srt)
    if not cues:
        sys.exit(f"No subtitle lines found in {a.srt}")
    limit = make_ass.duration_arg(a.limit) if a.limit else None
    cues = make_ass.limit_cues(cues, limit)
    situation, extra = gn.subtitle_setup(cues, a.film_language, a.original_subs, say=say)
    audience = a.audience or gn.default_audience(a.film_language, situation)
    return cues, situation, extra, audience, limit


def prepare(a):
    cues, situation, extra, audience, limit = setup(a)
    year = gn.resolve_year(a.year, a.video, a.title)
    foreign = situation is not None
    title = a.title or Path(a.video).stem
    system = gn.SYSTEM.format(
        audience=audience, language=a.notes_language, era_section=gn.era_section(year),
        cats=", ".join(gn.FOREIGN_CATEGORIES if foreign else gn.CATEGORIES),
        language_section=(gn.language_section(a.film_language, situation).replace("{language}", a.notes_language)
                          if foreign else ""),
        examples=((gn.ORIGINAL_EXAMPLES if situation == "original" else gn.FOREIGN_EXAMPLES) if foreign
                  else gn.ENGLISH_EXAMPLES))
    parts = gn.chunks(cues, extra)
    out = [MARK, f"Title: {title}", f"Parts: {len(parts)}", "",
           "=== INSTRUCTIONS FOR THIS FILM (follow these exactly) ===", system, ""]
    for k, part in enumerate(parts, 1):
        out.append(f"=== PART {k} OF {len(parts)} (lines {part[0]['n']} to {part[-1]['n']}) ===")
        out += [gn.fmt_line(c, extra) for c in part]
        out.append("")
    dest = Path(a.out or Path(a.video).with_suffix("").as_posix() + ".chat-upload.txt")
    dest.write_text("\n".join(out), encoding="utf-8")
    print(f"Wrote {dest} ({len(cues)} lines in {len(parts)} parts, about {sum(map(len, out)) // 4:,} tokens).")
    print("Upload it to a chat in the Project and say \"go all\" (again if a reply ends \"CONTINUE FROM PART k\"). "
          "Paste every reply into one text file.")


def read_upload(path):
    """An upload file -> (title, instructions, {part number: [lines]})."""
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith(MARK):
        sys.exit(f"{path} isn't an upload file from  chat_notes.py prepare.")
    title = re.search(r"^Title: (.*)$", text, re.M).group(1)
    head, _, rest = text.partition("=== INSTRUCTIONS FOR THIS FILM (follow these exactly) ===\n")
    blocks = re.split(r"^=== PART (\d+) OF \d+ \(lines \d+ to \d+\) ===\n", rest, flags=re.M)
    instructions, parts = blocks[0].strip(), {}
    for k in range(1, len(blocks) - 1, 2):
        parts[int(blocks[k])] = [x for x in blocks[k + 1].split("\n") if x.strip()]
    return title, instructions, parts


def part_files(folder):
    """part-1.txt, part-2.txt, ... in a replies folder, in part order: {k: path}."""
    out = {}
    for p in Path(folder).glob("part-*.txt"):
        m = re.fullmatch(r"part-(\d+)\.txt", p.name)
        if m:
            out[int(m.group(1))] = p
    return dict(sorted(out.items()))


def show(a):
    """One part, ready for an agent to annotate: the instructions, a few lines before it for context, the part,
    and (with --covered) what the notes for earlier parts already explained."""
    title, instructions, parts = read_upload(a.upload)
    k = a.part
    if k not in parts:
        sys.exit(f"No PART {k}: the file has parts 1 to {len(parts)}.")
    out = [f"Title: {title}", f"You are writing PART {k} OF {len(parts)}.", "",
           "=== INSTRUCTIONS FOR THIS FILM (follow these exactly) ===", instructions, ""]
    if k - 1 in parts:
        out.append("=== CONTEXT: the last lines of the previous part (do not annotate) ===")
        out += parts[k - 1][-gn.CONTEXT_LINES:]
        out.append("")
    if a.covered and Path(a.covered).is_dir():
        seen = []
        for j, p in part_files(a.covered).items():
            if j < k:
                seen += [f"- \"{o.get('match') or ' '.join(str(o.get('text', '')).split()[:8]) + '...'}\" "
                         f"({o.get('category', 'Note')})" for o in objects(p.read_text(encoding="utf-8"))]
        if seen:
            out.append("=== TOPICS ALREADY COVERED IN EARLIER PARTS (don't explain these again) ===")
            out += seen[-80:]
            out.append("")
    out.append(f"=== PART {k} OF {len(parts)} ===")
    out += parts[k]
    print("\n".join(out))


# A "PART k OF N" line that starts a reply block. Only spaces and simple markers may surround it: a looser
# pattern (\W*) also eats the JSON braces around the first and last note of a block.
PART_HEAD_RE = re.compile(r"^[ \t=*#_-]*PART (\d+) OF (\d+)[ \t=*#_-]*$", re.M | re.I)


def objects(text):
    """Every JSON object with a cue and a text in the pasted replies (code fences and prose are ignored)."""
    dec, i, found = json.JSONDecoder(), 0, []
    while True:
        i = text.find("{", i)
        if i < 0:
            return found
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and "cue" in obj and "text" in obj:
            found.append(obj)
        i = end


def collect(a):
    cues, situation, extra, audience, limit = setup(a, say=lambda *_: None)
    if Path(a.replies).is_dir():         # a folder of part-k.txt files (one per part, as the note-writer agent writes)
        files = part_files(a.replies)
        if not files:
            sys.exit(f"No part-<k>.txt files in {a.replies}.")
        text = "\n".join(p.read_text(encoding="utf-8") for p in files.values())
    else:
        text = Path(a.replies).read_text(encoding="utf-8")
    parts = gn.chunks(cues, extra)
    part_of = {c["n"]: k for k, p in enumerate(parts, 1) for c in p}
    # Notes outside any "PART k OF N" block are sorted into parts by line number. A "PART k" block (e.g. from
    # "redo k") replaces everything earlier for that part; the last block for a part wins.
    by_part = {}
    heads = list(PART_HEAD_RE.finditer(text))
    for h, nxt in zip([None] + heads, heads + [None]):
        seg = text[(h.end() if h else 0):(nxt.start() if nxt else len(text))]
        if h is None:
            for o in objects(seg):
                by_part.setdefault(part_of.get(int(o["cue"]) if str(o["cue"]).isdigit() else 0, 0), []).append(o)
        else:
            k = int(h.group(1))
            if k in by_part:
                print(f"  PART {k}: using the later version")
            by_part[k] = objects(seg)
    raw = [o for k in sorted(by_part) for o in by_part[k]]
    if not raw:
        sys.exit(f"No notes found in {a.replies}. Paste the chat's replies (the JSON arrays) into it.")
    notes, problems, seen = [], [], set()
    for r in raw:
        key = (str(r.get("cue")), str(r.get("text")).strip())
        if key in seen:
            problems.append(f"line {r.get('cue')}: duplicate note skipped")
            continue
        seen.add(key)
        note, why = gn.check_note(r, cues, 1, len(cues))
        if note is None:
            problems.append(f"dropped a note ({why})")
            continue
        if why:
            problems.append(why)
        notes.append((int(r["cue"]), note))
    notes.sort(key=lambda x: x[0])
    empty = [k for k, p in enumerate(parts, 1) if not any(p[0]["n"] <= c <= p[-1]["n"] for c, _ in notes)]
    video = Path(a.video)
    dest = Path(a.out) if a.out else video.parent / f"notes-{video.stem}.json"
    if dest.exists() and not a.force:
        sys.exit(f"{dest} already exists. Add --force to replace it (the old one is kept as .bak).")
    if dest.exists():
        dest.with_suffix(".json.bak").write_bytes(dest.read_bytes())
    ms = int(round(cues[0]["start"] * 1000))
    intro = {"at": f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}",
             "category": "About these notes", "duration": 9, "kind": "speech",
             "text": f"Alpha context notes written by Claude ({a.model_label}) for this viewer: "
                     f"{audience.rstrip('.')}. Each note appears just after its line. “(less sure)” means: check me."
                     + (f" These notes cover only the first {make_ass.fmt_limit(limit)}." if limit else "")}
    year = gn.resolve_year(a.year, video, a.title)
    spec = {"title": f"{a.title or video.stem} (context notes)", "audience": audience,
            "scope": "Dialogue notes written from the subtitles only (no video or audio was analysed), in a claude.ai chat",
            "generated_by": a.model_label}
    if situation is not None:
        spec["film_language"] = gn.languages.code(a.film_language)
        if a.original_subs:
            spec["original_subtitles"] = Path(a.original_subs).name
    if limit:
        spec["limit"] = round(limit, 1)
    if year:
        spec["year"] = int(year)
    spec["notes"] = [intro] + [n for _, n in notes]
    make_ass.write_text_safely(dest, json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
    print(f"Wrote {len(notes)} notes -> {dest}")
    dups, similar = dedupe.find_duplicates(spec["notes"])
    print(f"  {len(dups)} repeated explanation(s) will be left out of the .ass, {len(similar)} near-miss(es) kept "
          f"(python3 dedupe.py {dest.name} lists them)")
    for j, i, why in dups[:8]:
        print(f"    #{j + 1} {why} (first in #{i + 1})")
    if empty:
        print(f"  ! no notes for part(s) {', '.join(map(str, empty))} of {len(parts)}: a reply may be missing from "
              f"{Path(a.replies).name}")
    for p in problems:
        print("  - " + p)


def year_cmd(a):
    """Print the release year for the /notes command to show Erin, or "none" so it can offer a lookup."""
    year, where = gn.find_year(a.video, a.title)
    print(f"year: {year} (from {where})" if year else "year: none")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("show", help="print one part of an upload file, with the instructions and context, to annotate")
    sh.add_argument("upload")
    sh.add_argument("--part", type=int, required=True)
    sh.add_argument("--covered", metavar="DIR", help="folder of part-<k>.txt replies: list what earlier parts covered")
    sy = sub.add_parser("year", help="print the film's release year and where it was found (or none)")
    sy.add_argument("video")
    sy.add_argument("--title")
    for name in ("prepare", "collect"):
        p = sub.add_parser(name)
        p.add_argument("video")
        p.add_argument("srt", help="the subtitles the notes are placed on (the ones you'll watch with)")
        if name == "collect":
            p.add_argument("replies", help="text file with the chat's replies pasted in, or a folder of part-<k>.txt "
                                           "files (one reply per part)")
            p.add_argument("--model-label", default="Opus 5.5 in a claude.ai chat")
            p.add_argument("--force", action="store_true")
        p.add_argument("--film-language", help="language spoken in the film, e.g. de, ja (omit for English)")
        p.add_argument("--original-subs", help="with --film-language: the original-language subtitles")
        p.add_argument("--title")
        p.add_argument("--year", help="release year, e.g. 1974: films more than 40 years old get extra attention "
                                      "to their words, people, places and period")
        p.add_argument("--audience")
        p.add_argument("--notes-language", default="English")
        p.add_argument("--limit", help="only the first part, e.g. 30:00")
        p.add_argument("-o", "--out")
    a = ap.parse_args()
    {"prepare": prepare, "collect": collect, "show": show, "year": year_cmd}[a.cmd](a)


if __name__ == "__main__":
    main()
