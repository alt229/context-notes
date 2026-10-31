#!/usr/bin/env python3
"""chat_notes.py - write the dialogue notes in a claude.ai chat (your subscription) instead of through the API.

The chat sees exactly what the API step would: the same instructions, the same numbered lines, the same parts.

  1. python3 chat_notes.py prepare film.mkv film.srt [--film-language de --original-subs film.de.srt] [--title "..."]
        -> context-notes/film.mkv/film.chat-upload.txt
                                  upload this file to a chat in the Project and say "go all"; if a reply ends with
                                  "CONTINUE FROM PART k", say "go all" again
  2. paste every reply, one after another, into one text file, e.g. film.chat-replies.txt
     (to improve a thin part, say "redo k" in the chat and paste that reply at the end: the last PART k wins)
  3. python3 chat_notes.py collect film.mkv film.srt film.chat-replies.txt [same --film-language/--original-subs]
        -> the video's notes file, context-notes/film.mkv/notes-film.json (checked: every quote is looked up in
           the subtitles). An older one beside the video is replaced where it is (with --force).
  4. either build the subtitles with no API use at all:
        python3 make_ass.py film.srt --video film.mkv
     or let the API add the on-screen notes (the refine step only; generate is skipped because the notes exist):
        python3 context_notes.py film.mkv --model claude-opus-5-5 --effort high

Or let Claude Code write them on your subscription: /notes in this project folder runs the note-writer agent once
per part (chat_notes.py show prints a part for it), each reply saved as <folder>/part-<k>.txt; collect takes the folder.
(Everything this writes goes in the video's working folder: see workfiles.py.)

The frames step the same way: /refine runs the frame-reviewer agent once per stretch of the video.
  show-frames film.mkv film.srt --part 0 [--frames dense --limit 30:00 ...]
        analyses the video (cached), keeps the notes as they are now (a backup beside them, which every later step
        starts from), and says how many parts there are and which already have replies. Its options are kept for
        the later steps, in context-notes/film.mkv/frame-replies/start.json.
  show-frames film.mkv film.srt --part K
        prints part K for the agent: the instructions, the contact sheets to open, and the stretch, as the API's
        frames step would send it, with the replies for parts 1 to K-1 already applied. The agent writes
        frame-replies/frames-K.txt.
  collect-frames film.mkv film.srt
        applies the replies in order (up to the first one missing) to the notes as they were, writes the notes file
        and a report of every change, and keeps the old .ass; make_ass.py then rebuilds it. If parts are missing,
        the notes file says where it stopped, so the next /refine (or the API's --refine) picks up there.

For a film not in English that you watch with English subtitles: give the English file as SRT and the original as
--original-subs, with --film-language (e.g. de). Use the same files and options in both steps.
"""
import argparse
import contextlib
import datetime
import io
import json
import re
import shutil
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dedupe  # noqa: E402
import generate_notes as gn  # noqa: E402
import prompts  # noqa: E402
import fileio  # noqa: E402
import subtitles  # noqa: E402
import timecode  # noqa: E402
import workfiles  # noqa: E402

MARK = "CONTEXT-NOTES UPLOAD v1"


def setup(a, say=print):
    cues = subtitles.parse_srt(a.srt)
    if not cues:
        sys.exit(f"No subtitle lines found in {a.srt}")
    limit = timecode.duration_arg(a.limit) if a.limit else None
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
    video = Path(a.video)
    dest = Path(a.out) if a.out else workfiles.place(video) / f"{video.stem}.chat-upload.txt"
    fileio.write_text_safely(dest, "\n".join(out))
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
    dest = Path(a.out) if a.out else workfiles.notes_path(video, a.srt)
    if dest.exists() and not a.force:
        sys.exit(f"{dest} already exists. Add --force to replace it (the old one is kept as .bak).")
    if dest.exists():
        dest.with_suffix(".json.bak").write_bytes(dest.read_bytes())
    ms = int(round(cues[0]["start"] * 1000))
    intro = {"at": f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}",
             "category": "About these notes", "duration": 9, "kind": "speech",
             "text": f"Beta context notes written by Claude ({a.model_label}) for this viewer: "
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
          f"({prompts.PYTHON} dedupe.py {dest.name} lists them)")
    for j, i, why in dups[:8]:
        print(f"    #{j + 1} {why} (first in #{i + 1})")
    if empty:
        print(f"  ! no notes for part(s) {', '.join(map(str, empty))} of {len(parts)}: a reply may be missing from "
              f"{Path(a.replies).name}")
    for p in problems:
        print("  - " + p)


# ---------------------------------------------------------------- the frames step, in a Claude Code conversation
FRAMES_DIR = "frame-replies"
START = "start.json"
FRAME_OPTIONS = ("frames", "limit", "assume_synced", "film_language", "original_subs", "title", "year", "audience",
                 "notes_language")


def frames_dir(video, given=None):
    return Path(given) if given else workfiles.place(Path(video)) / FRAMES_DIR


def frame_files(folder):
    """frames-1.txt, frames-2.txt, ... in a replies folder: {k: path}, in part order."""
    out = {}
    for p in Path(folder).glob("frames-*.txt"):
        m = re.fullmatch(r"frames-(\d+)\.txt", p.name)
        if m:
            out[int(m.group(1))] = p
    return dict(sorted(out.items()))


def read_start(folder):
    try:
        start = json.loads((Path(folder) / START).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return start if isinstance(start, dict) and start.get("notes") and start.get("backup") else None


def frames_state(a, start):
    """What every part, and collect-frames, is made from, the same way each time: the notes as they were when /refine
    started (the backup named in start.json), the video's analysis (cached after part 0), the stretches and the
    instructions, all from the options part 0 was given."""
    import refine_notes as rn
    video, srt = Path(a.video), Path(a.srt)
    notes_path = Path(start["notes"])
    pristine = notes_path.with_name(start["backup"])
    try:
        spec = json.loads(fileio.read_text(pristine))
    except (OSError, ValueError):
        sys.exit(f"Can't read {pristine}, the notes as they were when /refine started. Start again with "
                 f"show-frames --part 0 --fresh.")
    if not isinstance(spec, dict):
        spec = {"notes": spec}
    cues = subtitles.parse_srt(srt)
    if not cues:
        sys.exit(f"No subtitle lines found in {srt}")
    o = start.get("options") or {}
    film_language, original_srt, title, situation, extra, audience, year = rn.film_setup(
        cues, spec, srt, video, o.get("film_language"), o.get("original_subs"), o.get("title"), o.get("audience"),
        o.get("year"))
    an, sync_msg, visual_only = rn.look_at_video(cues, video, o.get("frames") or "keyframes", spec, o.get("limit"),
                                                 bool(o.get("assume_synced")))
    wins = rn.make_windows(an["sheets"], an["duration"])
    if not wins:
        sys.exit("No contact sheets were produced, so there is nothing to look at.")
    return types.SimpleNamespace(
        cues=cues, spec=spec, notes=spec["notes"], notes_path=notes_path, an=an, offset=an["offset"],
        moments=an["moments"], sync_msg=sync_msg, visual_only=visual_only, wins=wins, title=title, extra=extra,
        limit=o.get("limit"), sys_prompt=rn.system_prompt(audience, o.get("notes_language") or "English", visual_only,
                                                          film_language, situation, year))


def apply_frames(st, folder, upto, log, dropped, unread):
    """The replies for parts 1 to `upto` applied in order, as the API's frames step applies its replies (the later
    parts were shown the notes as the earlier ones left them). Stops at the first part with no reply.
    Returns (the last part applied, [added, revised, retimed, dropped], the notes' times now)."""
    import refine_notes as rn
    files = frame_files(folder)
    times = rn.note_times(st.cues, st.notes, st.offset)
    done, counts = 0, [0, 0, 0, 0]
    for k in range(1, upto + 1):
        if k not in files:
            break
        win = st.wins[k - 1]
        _, listed = rn.window_text(win, st.cues, st.offset, st.moments, st.notes, times, st.title, k, len(st.wins),
                                   st.visual_only, st.extra, dropped)
        text = files[k].read_text(encoding="utf-8")
        parsed = rn.parse_reply(text)
        if not any(parsed.values()) and text.strip() not in ("{}", ""):
            unread.append({"from": round(win["lo"], 3), "to": round(win["hi"], 3),
                           "reply": f"{Path(folder).name}/{files[k].name}"})
        got = rn.apply_reply(parsed, win, st.cues, st.offset, st.notes, times, listed, log, dropped, st.visual_only)
        counts = [x + y for x, y in zip(counts, got)]
        times = rn.note_times(st.cues, st.notes, st.offset)
        done = k
    return done, counts, times


def frames_start(a, folder):
    """--part 0: begin (or pick up) a /refine: keep the notes as they are, analyse the video, say what's to do."""
    video, srt = Path(a.video), Path(a.srt)
    start = read_start(folder)
    if start and a.fresh:
        n = 1
        while folder.with_name(f"{FRAMES_DIR}.old-{n}").exists():
            n += 1
        folder.rename(folder.with_name(f"{FRAMES_DIR}.old-{n}"))
        print(f"Started again: the earlier replies are kept in {FRAMES_DIR}.old-{n}.")
        start = None
    if start is None:
        import refine_notes as rn
        notes_path = Path(a.notes) if a.notes else workfiles.notes_path(video, srt)
        if not notes_path.exists():
            sys.exit(f"There are no notes for {video.name} yet ({notes_path.name}). Write them first (/notes, or "
                     f"context_notes.py).")
        rn.check_same_episode(video, srt, notes_path)
        backup = fileio.unique_backup(notes_path)
        shutil.copy2(notes_path, backup)
        options = {k: getattr(a, k, None) for k in FRAME_OPTIONS}
        options["limit"] = timecode.duration_arg(a.limit) if a.limit else None
        start = {"notes": str(notes_path.resolve()), "backup": backup.name,
                 "started": datetime.datetime.now().isoformat(timespec="seconds"), "options": options}
        workfiles.make_dirs(folder)
        fileio.write_text_safely(folder / START, json.dumps(start, indent=1) + "\n")
        print(f"Kept the notes as they are now: {backup.name} (every part starts from these).")
    else:
        print(f"Picking up the /refine started {start.get('started', '')} (its options are kept in "
              f"{FRAMES_DIR}/{START}; --fresh starts again).")
    st = frames_state(a, start)
    n = len(st.wins)
    have = [k for k in frame_files(folder) if k <= n]
    todo = [k for k in range(1, n + 1) if k not in have]
    print(f"Parts: {n}")
    print("Mode: " + ("full (the subtitles are in step with the video)" if not st.visual_only else
                      "on-screen notes only (the subtitles aren't in step with this video)"))
    print(f"Contact sheets: {sum(len(w['sheets']) for w in st.wins)}")
    print(f"Replies: {folder}")
    print("Done: " + (", ".join(map(str, have)) if have else "none"))
    print(f"Next: part {todo[0]}" if todo else "All parts have replies: run collect-frames.")


def show_frames(a):
    """One stretch for the frame-reviewer agent (or --part 0: begin)."""
    import refine_notes as rn
    folder = frames_dir(a.video, a.replies)
    if a.part == 0:
        return frames_start(a, folder)
    start = read_start(folder)
    if start is None:
        sys.exit(f"Begin with  chat_notes.py show-frames \"{a.video}\" \"{a.srt}\" --part 0  (it keeps the notes as "
                 f"they are and analyses the video).")
    with contextlib.redirect_stdout(io.StringIO()):         # the analysis is cached; its lines are noise here
        st = frames_state(a, start)
    n = len(st.wins)
    if not 1 <= a.part <= n:
        sys.exit(f"No part {a.part}: there are parts 1 to {n}.")
    files = frame_files(folder)
    missing = [k for k in range(1, a.part) if k not in files]
    if missing:
        sys.exit(f"Part {a.part} needs the replies for part(s) {', '.join(map(str, missing))} first: they change what "
                 f"it sees.")
    log, dropped, unread = [], {}, []
    _, _, times = apply_frames(st, folder, a.part - 1, log, dropped, unread)
    win = st.wins[a.part - 1]
    text, _ = rn.window_text(win, st.cues, st.offset, st.moments, st.notes, times, st.title, a.part, n,
                             st.visual_only, st.extra, dropped)
    out = [f"PART {a.part} OF {n}: {timecode.hms(win['lo'])} to {timecode.hms(win['hi'])} of the video.",
           f"Write your reply to: {folder / f'frames-{a.part}.txt'}", "",
           "=== INSTRUCTIONS (follow these exactly) ===", st.sys_prompt, "",
           "=== CONTACT SHEETS (open every one with the Read tool before you answer) ==="]
    for path, t0, t1 in win["sheets"]:
        out.append(f"{Path(path).resolve()}   frames from {timecode.hms(t0)} to {timecode.hms(t1)}")
    out += ["", "=== THIS STRETCH ===", text]
    print("\n".join(out))


def collect_frames(a):
    """Apply the replies (frames-1.txt ...) to the notes as they were, and write the notes file and the report."""
    import refine_notes as rn
    video = Path(a.video)
    folder = frames_dir(video, a.replies)
    start = read_start(folder)
    if start is None:
        sys.exit(f"Nothing to collect: {folder / START} isn't there. Begin with show-frames --part 0.")
    st = frames_state(a, start)
    n = len(st.wins)
    log, dropped, unread = [], {}, []
    done, (added, revised, retimed, _), _ = apply_frames(st, folder, n, log, dropped, unread)
    if not done:
        sys.exit(f"No replies yet in {folder} (frames-1.txt ...): nothing was changed.")
    ass = Path(str(video.with_suffix("")) + ".notes.ass")
    if ass.exists():                                       # the .ass is rebuilt next: keep the one there now
        ass_backup = fileio.unique_backup(workfiles.place(video) / ass.name)
        workfiles.make_dirs(ass_backup.parent)
        shutil.copy2(ass, ass_backup)
        print(f"Kept the old subtitles: {ass_backup.name}")
    stopped = None if done == n else {"time": round(st.wins[done - 1]["hi"], 3), "part": done, "parts": n,
                                      "backup": start["backup"]}
    sync_msg = st.sync_msg + (f"; stopped after part {done} of {n}" if stopped else "")
    report = rn._save(st.spec, st.notes, dropped, st.notes_path, log, st.notes_path.with_name(start["backup"]),
                      sync_msg=sync_msg, model=a.model_label, sheets=sum(len(w["sheets"]) for w in st.wins),
                      limit=st.limit, stopped=stopped, unreadable=unread)
    print(f"Applied the replies for {done} of {n} part(s) to {st.notes_path.name}: {added} added, {revised} revised, "
          f"{retimed} retimed, {len(dropped)} dropped; {sync_msg}.")
    print(f"Report of every change: {report}")
    for u in unread:
        print(f"  ! couldn't read {u['reply']}: nothing from it was applied (the next refine offers that stretch again)")
    if stopped:
        print(f"  The replies for part {done + 1} on aren't there yet. The notes file says where this stopped, so the "
              f"next /refine (or the API's --refine) picks up there.")


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
    sf = sub.add_parser("show-frames", help="the frames step in Claude Code: --part 0 begins (or picks up); --part K "
                                            "prints stretch K for the frame-reviewer agent")
    cf = sub.add_parser("collect-frames", help="apply the frame-reviewer's replies to the notes")
    for p in (sf, cf):
        p.add_argument("video")
        p.add_argument("srt", help="the subtitles the notes are placed on")
        p.add_argument("--replies", metavar="DIR", help=f"the replies folder (default: the video's working folder's "
                                                        f"{FRAMES_DIR})")
    sf.add_argument("--part", type=int, required=True)
    sf.add_argument("--fresh", action="store_true", help="with --part 0: start again (the old replies are kept, renamed)")
    sf.add_argument("--notes", help="with --part 0: the notes file (default: the video's own)")
    sf.add_argument("--frames", choices=("keyframes", "dense"), default="keyframes", help="with --part 0")
    sf.add_argument("--limit", help="with --part 0: only the first part of the video, e.g. 30:00")
    sf.add_argument("--assume-synced", action="store_true", help="with --part 0: trust that the subtitles are in step")
    sf.add_argument("--film-language", help="with --part 0: language spoken in the film (default: the notes file's)")
    sf.add_argument("--original-subs", help="with --part 0: the original-language subtitles")
    sf.add_argument("--title")
    sf.add_argument("--year")
    sf.add_argument("--audience")
    sf.add_argument("--notes-language", default="English")
    cf.add_argument("--model-label", default="Opus in Claude Code (/refine)")
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
    {"prepare": prepare, "collect": collect, "show": show, "year": year_cmd, "show-frames": show_frames,
     "collect-frames": collect_frames}[a.cmd](a)


if __name__ == "__main__":
    main()
