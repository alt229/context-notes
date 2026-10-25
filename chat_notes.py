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

The frame pass (on-screen notes from the video's frames, normally make_ass.py --refine on the API) has the same route:
  python3 chat_notes.py show-frames film.mkv film.srt --part 0             -> how many parts, and the mode
  python3 chat_notes.py show-frames film.mkv film.srt --part K --replies DIR   -> one part for an agent: the instructions,
                                   the contact-sheet image files to open, the dialogue and the existing notes
  python3 chat_notes.py collect-frames film.mkv film.srt DIR --model-label "Opus in Claude Code"
                                   -> applies DIR/frames-<k>.txt in order to the notes file (backup kept, report written)
In this project, /refine does all of that with the frame-reviewer agent. The video analysis is the same as --refine's
and is cached in "<video> analysis/", so the second command is quick.

For a film not in English that you watch with English subtitles: give the English file as SRT and the original as
--original-subs, with --film-language (e.g. de). Use the same files and options in both steps.
"""
import argparse
import contextlib
import io
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cli_common  # noqa: E402
import dedupe  # noqa: E402
import fileio  # noqa: E402
import generate_notes as gn  # noqa: E402
import subtitles  # noqa: E402
import timecode  # noqa: E402

MARK = "CONTEXT-NOTES UPLOAD v1"


def setup(a, say=print):
    cues = subtitles.parse_srt(a.srt)
    if not cues:
        sys.exit(f"No subtitle lines found in {a.srt}")
    limit = a.limit or None                    # seconds (cli_common.add_limit_arg read it)
    cues = subtitles.limit_cues(cues, limit)
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
             "text": f"Pre-alpha context notes written by Claude ({a.model_label}) for this viewer: "
                     f"{audience.rstrip('.')}. Each note appears just after its line. “(less sure)” means: check me."
                     + (f" These notes cover only the first {timecode.fmt_limit(limit)}." if limit else "")}
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
    fileio.write_text_safely(dest, json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
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


# ---------------------------------------------------------------- the frame pass (make_ass.py --refine) for an agent
def frames_plan(a, model=None):
    """The same plan the API's refine makes (refine_notes.plan_refine): the video analysis, cached in
    "<video> analysis/", the sync mode, the stretches of 4 contact sheets. Nothing is sent and the notes file isn't
    touched. Its Mode/Plan/estimate chatter is kept off stdout, because an agent reads what show-frames prints.
    Returns (plan, the mode lines to show)."""
    import refine_notes as rn
    video = Path(a.video)
    notes = Path(a.notes) if a.notes else video.parent / f"notes-{video.stem}.json"
    if not notes.exists():
        sys.exit(f"No notes file at {notes}. Write the dialogue notes first (/notes, or chat_notes.py collect).")
    kw = {"model": model} if model else {}
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        plan = rn.plan_refine(srt_path=a.srt, notes_path=notes, video=video, frames=a.frames, audience=a.audience,
                              title=a.title, language=a.notes_language, assume_yes=True, assume_synced=a.assume_synced,
                              film_language=a.film_language, original_srt=a.original_subs, limit=a.limit or None,
                              year=a.year, estimate_only=True, **kw)
    mode = [line for line in buf.getvalue().splitlines() if line.startswith("Mode:")]
    return plan, mode


def frame_files(folder):
    """frames-1.txt, frames-2.txt, ... in a replies folder: {k: path}."""
    out = {}
    for p in Path(folder).glob("frames-*.txt"):
        m = re.fullmatch(r"frames-(\d+)\.txt", p.name)
        if m:
            out[int(m.group(1))] = p
    return dict(sorted(out.items()))


def apply_frames_reply(plan, k, win, text, times, log, dropped, save_failed=True):
    """One part's reply (the JSON object the agent wrote) applied to plan.notes, exactly as the API route applies a
    reply: the existing notes are listed for this stretch (their ids are what the agent saw, see show_frames), the
    reply is parsed and applied. Returns {"added", "revised", "retimed", "dropped", "problems"}."""
    import refine_notes as rn
    _, listed = rn.window_content(plan, k, win, plan.notes, times)
    parsed = rn.parse_reply(text)
    problems = []
    if not any(parsed.values()) and text.strip() not in ("{}", ""):
        bad = plan.notes_path.with_suffix(f".frames{k}.failed.txt")
        if save_failed:
            fileio.write_text_safely(bad, text)
        problems.append(f"part {k}: couldn't read frames-{k}.txt as the JSON object; saved it to {bad.name}")
    added, revised, retimed, dropped_n = rn.apply_reply(parsed, win, plan.cues, plan.offset, plan.notes, times, listed,
                                                        log, dropped, plan.visual_only)
    return {"added": added, "revised": revised, "retimed": retimed, "dropped": dropped_n, "problems": problems}


def replay_frames(plan, folder, upto):
    """Apply the finished parts before `upto` (frames-<j>.txt in `folder`, j from plan.first) to plan.notes, so a later
    part is shown and collected with the notes as they stand then, the way the API route sees them.
    Returns the note times after them."""
    import refine_notes as rn
    times = plan.times
    files = frame_files(folder) if folder and Path(folder).is_dir() else {}
    for j, win in enumerate(plan.wins[plan.first - 1:upto - 1], plan.first):
        if j in files:
            apply_frames_reply(plan, j, win, files[j].read_text(encoding="utf-8"), times, [], {}, save_failed=False)
            times = rn.note_times(plan.cues, plan.notes, plan.offset)
    return times


def show_frames(a):
    """One stretch of the video, ready for an agent to review: the refine instructions, the contact-sheet files to
    open, the dialogue, loud moments and existing notes. --part 0 prints just how many parts there are."""
    import refine_notes as rn
    plan, mode = frames_plan(a)
    total, first = plan.total, plan.first
    if a.part == 0:
        print(f"Parts: {total}")
        print("\n".join(mode))
        print(f"To do: parts {first} to {total}" if plan.todo else "To do: nothing (every part is already in the notes)")
        if first > 1:
            print(f"  (the last refine stopped after part {first - 1}; those parts are in the notes already)")
        print(f"Sync: {plan.sync_msg}")
        return
    if not plan.todo:
        sys.exit("Nothing is left to refine: every part is already in the notes.")
    if not 1 <= a.part <= total:
        sys.exit(f"No part {a.part}: this video has parts 1 to {total}.")
    if a.part < first:
        sys.exit(f"Part {a.part} is already in the notes (the last refine stopped after part {first - 1}). "
                 f"Parts {first} to {total} are left.")
    k = a.part
    win = plan.wins[k - 1]
    times = replay_frames(plan, a.replies, k)
    content, _ = rn.window_content(plan, k, win, plan.notes, times)
    dest = f"{Path(a.replies).resolve()}/frames-{k}.txt" if a.replies else f"frames-{k}.txt in the replies folder you were given"
    out = [f"Title: {plan.title}",
           f"You are reviewing PART {k} OF {total} (frames {timecode.hms(win['lo'])} to {timecode.hms(win['hi'])}).", "",
           "=== INSTRUCTIONS (follow these exactly) ===", plan.sys_prompt, "",
           "=== CONTACT SHEETS: open each of these image files with the Read tool before writing anything ==="]
    out += [f"{Path(path).resolve()}   frames from {timecode.hms(t0)} to {timecode.hms(t1)}" for path, t0, t1 in win["sheets"]]
    out += ["", "=== THE DIALOGUE, EXISTING NOTES AND LOUD MOMENTS FOR THIS PART ==="]
    out += [b["text"] for b in content if b["type"] == "text" and not b["text"].startswith("Contact sheet:")]
    out += ["", "=== WHAT TO WRITE ===",
            f"Write the file {dest} containing exactly the JSON object the instructions describe: no prose before or "
            "after it, no code fences, no \"PART\" line. If nothing needs changing, the file holds {}.",
            "Only times printed in yellow under a frame you have looked at may be used in \"at\". Only the ids listed "
            "above under \"Existing notes in this stretch\" may be used in revise, retime and drop."]
    print("\n".join(out))


def collect_frames(a):
    """Apply the agents' frames-<k>.txt replies to the notes file, in part order, the way make_ass.py --refine applies
    the API's. A backup of the notes (and the .ass) is kept, and the report of every change is written beside them.
    If a part's file is missing, the run stops there and the notes file says so (refined.stopped_after), so the next
    collect-frames picks up from that part."""
    import refine_notes as rn
    plan, mode = frames_plan(a, model=a.model_label)
    notes_path, total, first = plan.notes_path, plan.total, plan.first
    print("\n".join(mode))
    print(f"  {plan.sync_msg}")
    if not plan.todo:
        rn._save(plan.spec, plan.notes, {}, notes_path, ["(nothing was left to refine)"],
                 notes_path.with_name(plan.first_backup or notes_path.name), sync_msg=plan.sync_msg, model=plan.model,
                 limit=plan.limit, append=True)
        print("Nothing was left to refine; marked as finished.")
        return
    folder = Path(a.replies)
    files = frame_files(folder) if folder.is_dir() else {}
    if not any(k >= first for k in files):
        sys.exit(f"No frames-<k>.txt files for parts {first} to {total} in {folder}. Nothing was changed.")

    backup = rn.unique_backup(notes_path)
    shutil.copy2(notes_path, backup)
    print(f"Kept a backup of your notes: {backup.name}")
    video = Path(a.video)
    ass_path = Path(str(video.with_suffix("")) + ".notes.ass")
    if ass_path.exists():
        ass_backup = rn.unique_backup(ass_path)
        shutil.copy2(ass_path, ass_backup)
        print(f"Kept the old subtitles: {ass_backup.name}")

    log, dropped, problems, times = [], {}, [], plan.times
    totals = {"added": 0, "revised": 0, "retimed": 0}
    completed = first - 1
    for k, win in enumerate(plan.todo, first):
        if k not in files:
            break
        print(f"  part {k}/{total}: {timecode.hms(win['lo'])}-{timecode.hms(win['hi'])} ...", end=" ", flush=True)
        done = apply_frames_reply(plan, k, win, files[k].read_text(encoding="utf-8"), times, log, dropped)
        problems += done["problems"]
        for key in totals:
            totals[key] += done[key]
        print(f"{done['added']} added, {done['revised']} revised, {done['retimed']} retimed, {done['dropped']} dropped")
        times = rn.note_times(plan.cues, plan.notes, plan.offset)       # new notes need times too, for later parts
        completed = k

    if completed < total:                        # a part's file is missing: keep what we have, pick up next time
        last = max(plan.resume_from or 0.0, plan.wins[completed - 1]["hi"] if completed else 0.0)
        rn._save(plan.spec, plan.notes, dropped, notes_path, log, backup, model=plan.model, sheets=plan.n_img,
                 sync_msg=f"STOPPED EARLY after part {completed} of {total}; {plan.sync_msg}", limit=plan.limit,
                 stopped={"time": round(last, 3), "part": completed, "parts": total,
                          "backup": plan.first_backup or backup.name},
                 problems=problems, append=plan.resume_from is not None)
        print(f"  Stopped after part {completed} of {total}: there is no {folder.name}/frames-{completed + 1}.txt yet. "
              f"The changes so far were saved to {notes_path.name} (original: {backup.name}).\n"
              f"  Next: review the missing parts, then run collect-frames again; it picks up at part {completed + 1}.")
        for p in problems:
            print("  ! " + p)
        sys.exit(1)

    report = rn.finish_refine(plan, plan.notes, dropped, log, backup, usage=None, problems=problems)
    print(f"Refined {notes_path.name}: {totals['added']} added, {totals['revised']} revised, {totals['retimed']} retimed, "
          f"{len(dropped)} dropped; {plan.sync_msg}.")
    print(f"Report of every change: {report}")
    for p in problems:
        print("  ! " + p)
    print(f"Next: python3 make_ass.py \"{a.srt}\" \"{notes_path}\" --video \"{video}\" --timing-report")


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
    cli_common.add_film_args(sy, only=("title",), title="the film's title, when the file name doesn't give the year "
                                                        "(e.g. 'Amadeus (1984)')")
    for name in ("prepare", "collect"):
        p = sub.add_parser(name)
        p.add_argument("video")
        p.add_argument("srt", help="the subtitles the notes are placed on (the ones you'll watch with)")
        if name == "collect":
            p.add_argument("replies", help="text file with the chat's replies pasted in, or a folder of part-<k>.txt "
                                           "files (one reply per part)")
            p.add_argument("--model-label", default="Opus 5.5 in a claude.ai chat")
            p.add_argument("--force", action="store_true")
        cli_common.add_film_args(p)      # --film-language, --original-subs, --title, --year, --audience, --notes-language
        cli_common.add_limit_arg(p, help="only the first part, e.g. 30:00")
        p.add_argument("-o", "--out")
    for name in ("show-frames", "collect-frames"):
        p = sub.add_parser(name, help=("print one stretch of the video (its contact sheets, dialogue and notes) for an agent "
                                       "to review; --part 0 prints how many there are" if name == "show-frames" else
                                       "apply the agents' frames-<k>.txt replies to the notes file, like --refine does"))
        p.add_argument("video")
        p.add_argument("srt", help="the subtitles the notes are placed on (the ones you'll watch with)")
        if name == "show-frames":
            p.add_argument("--part", type=int, required=True, help="which stretch (1 to N), or 0 for the count and the mode")
            p.add_argument("--replies", metavar="DIR", help="folder of frames-<k>.txt replies: earlier parts' changes are "
                                                          "applied first, and the part's file is named in the instructions")
        else:
            p.add_argument("replies", metavar="DIR", help="folder of frames-<k>.txt files (one JSON reply per part)")
            p.add_argument("--model-label", default="Opus in Claude Code", help="recorded in the notes file as the refiner")
        p.add_argument("--notes", help="the notes file (default: notes-<video name>.json beside the video)")
        cli_common.add_film_args(p)
        cli_common.add_limit_arg(p)
        cli_common.add_frames_arg(p)
        p.add_argument("--assume-synced", action="store_true",
                       help="trust the subtitles' timing even if the soundtrack check can't confirm it (e.g. an .aligned.srt)")
    a = ap.parse_args()
    {"prepare": prepare, "collect": collect, "show": show, "year": year_cmd,
     "show-frames": show_frames, "collect-frames": collect_frames}[a.cmd](a)


if __name__ == "__main__":
    main()
