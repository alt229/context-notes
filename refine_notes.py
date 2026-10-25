#!/usr/bin/env python3
"""
refine_notes.py - improve an existing notes file by looking at the video.

You normally run this through make_ass.py:

    python3 make_ass.py episode.srt --refine --video episode.mp4

What it does (the process used by hand for S01E01):
  1. Checks the subtitle sync against the soundtrack and records the offset in the notes file
     ("video_offset"), so the rebuilt .ass lines up with this video.
  2. Pulls frames from the video into contact sheets and finds loud moments with no dialogue.
  3. Sends Claude your existing notes, the dialogue, those loud moments and the contact sheets
     (as images), a few minutes of the video at a time, and asks it to
        - add notes about what is on screen (sight gags, props, signs, costumes, staging),
        - add delivery/timing notes where a laugh or silence carries the joke,
        - revise a note only when the frames show it is wrong or can be made clearly better,
        - retime notes that appear before the thing they explain,
        - drop a note only when the frames show it is wrong.
  4. Writes the result to the notes file. The old file is kept as <notes>.json.bak, and a plain-text
     report of every change (with the old wording) is saved next to it.

make_ass.py then rebuilds the .ass; the old .ass is kept as <name>.ass.bak.
The key, backend and cost handling are the same as for --generate (see claude_api.py). On the subscription
(--backend claude-code) the contact sheets aren't uploaded as images: Claude Code opens the JPEGs with its Read
tool, so it runs with the media folder added (--add-dir).
"""
import dataclasses
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

import claude_api
import fileio
import generate_notes as gn
import make_ass
import prompts
import subtitles
import timecode

SHEETS_PER_REQUEST = 4            # contact sheets (12 frames each) per request
REFINE_MAX_TOKENS = 6000
MAX_NEW_PER_WINDOW = 8

SYSTEM = """{mode_note}You refine "pop-up" context notes for a show or film, using frames from the video. Viewers watch with \
subtitles and see a small note appear just after a line, or at a moment in the video, explaining what they may \
not know. Notes already exist for the dialogue. Your job is to improve them using what you can SEE and the sound \
information you're given.

Viewer: {audience}.
Write every note in {language}.
{foreign_note}
{era_section}You get, for one stretch of the video:
- contact sheets (images): grids of frames, 3 columns by 4 rows. Under each frame, in yellow, is its time in the \
video (h:mm:ss.s); in grey, the subtitle line being spoken then (may be empty). Frames are SAMPLED, not continuous: \
you cannot see what happens between them, so never claim to have seen it.
- the dialogue for the stretch (times are video times)
- loud moments with no dialogue (usually an audience laugh, a sound gag or action)
- the existing notes for the stretch, each with an id, when it appears, its kind and category

What to do:
1. ADD notes about things the viewer may miss on screen: sight gags, props, text on screens/signs/posters/T-shirts, \
costume, set dressing, background jokes, staging, running visual gags, period or cultural details. Use kind \
"visual" and give "at": the time exactly as printed in yellow under the frame where it is visible, as h:mm:ss \
(for example "0:09:48"; never decimal minutes or seconds).
2. ADD a few notes about delivery and timing where the loud-moment list or a long silence shows where the joke \
lands (kind "speech", with "cue": the line number it follows). Only when it helps the viewer.
3. REVISE an existing note only if the frames show it is wrong, or add something that clearly improves it. Give \
the replacement "text" and a short "reason". Don't rewrite for style.
4. RETIME an existing note ("delay" in seconds, 0 to 15) when it appears before the thing it explains, \
for instance a note that gives away a punchline before it is spoken or seen.
5. DROP an existing note only if the frames clearly show it is wrong. Give a "reason".

Rules:
- Be accurate. Describe only what you can see. Never invent text on screen, names, trivia or production details. \
If you aren't sure, say "medium" or "low" in "confidence" (the viewer sees a "less sure" tag) or leave it out.
- No spoilers: only use what is in this stretch or earlier. Don't hint at later events.
- Each note is at most about 40 words, plain and friendly, no markdown.
- Don't repeat what an existing note already says. Fewer, better notes beat many: usually 0 to {maxnew} additions \
for a stretch, and often none.
- Refer to existing notes only by the ids listed for this stretch.

Reply with ONLY a JSON object, no prose and no code fences:
{{"add": [{{"at": "<h:mm:ss>", "kind": "visual", "category": "<Visual gag | Prop | Staging | Costume | Background | \
Cultural reference | Trivia | your own short label>", "text": "...", "confidence": "high" | "medium" | "low"}}, \
{{"cue": <line number>, "kind": "speech", "category": "Delivery", "text": "...", "confidence": "high"}}],
 "revise": [{{"id": <id>, "text": "...", "reason": "..."}}],
 "retime": [{{"id": <id>, "delay": <seconds>, "reason": "..."}}],
 "drop": [{{"id": <id>, "reason": "..."}}]}}
Leave out any list you have nothing for (or use []). If there is nothing to change, reply {{}}."""


# ---------------------------------------------------------------- small helpers
def resolve_time(v, lo, hi):
    """A visual note's time in video seconds. Prefers h:mm:ss text; for bare numbers, tries seconds, then
    decimal minutes (models sometimes write 9.8 for 9:48), then seconds from the start of the stretch."""
    t = timecode.parse_time(v)
    if t is None:
        return None, None
    if isinstance(v, str) and ":" in v:
        return (t, None) if lo - 1 <= t <= hi + 1 else (None, None)
    for how, cand in (("seconds", t), ("minutes", t * 60), ("seconds into this stretch", lo + t)):
        if lo - 1 <= cand <= hi + 1:
            return cand, (None if how == "seconds" else f"read {v} as {how}")
    return None, None


EPISODE_RE = re.compile(r"(?<![0-9A-Za-z])[sS]?(\d{1,2})[eExX](\d{2})(?![0-9A-Za-z])")


def episode_codes(*names):
    """{name: (season, episode)} for the names that contain something like S01E03, 1e03 or 1x03."""
    out = {}
    for n in names:
        m = EPISODE_RE.search(Path(str(n)).name)
        if m:
            out[Path(str(n)).name] = (int(m.group(1)), int(m.group(2)))
    return out


def check_same_episode(*names):
    codes = episode_codes(*names)
    if len(set(codes.values())) > 1:
        lines = "\n".join(f"  {c[0]:>2}x{c[1]:02d}  {n}" for n, c in codes.items())
        sys.exit("These files look like different episodes, so I stopped before analysing or sending anything:\n"
                 f"{lines}\nCheck the --video, subtitle and notes file names.")


def unique_backup(path):
    p = Path(path)
    n = 1
    while True:
        b = p.with_name(p.name + (".bak" if n == 1 else f".bak{n}"))
        if not b.exists():
            return b
        n += 1


def resume_choice(notes_path, stopped, auto):
    """The last refine of these notes stopped part-way (an API error, Ctrl-C or Cancel). Ask whether to pick up where
    it left off (the default) or start again from the notes as they were before it.
    Returns (time to pick up from or None, name of the backup from before that refine, notes to start again from)."""
    name = stopped.get("backup")
    backup = Path(notes_path).with_name(name) if name else None
    have = backup is not None and backup.exists()
    again = f"start again from your notes as they were before it ({name})" if have else "start again from the beginning"
    pick = prompts.ask(f"The last refine stopped after part {stopped.get('part', 0)} of {stopped.get('parts', '?')} "
                       f"({timecode.hms(float(stopped.get('time', 0)))} into the video). Pick up where it left off?",
                       {"p": "pick up where it left off", "s": again}, "p", auto, id="refine.resume")
    if pick == "p":
        return float(stopped.get("time", 0)), name, None
    if not have:
        return None, None, None
    before = json.loads(fileio.read_text(backup))
    print(f"Starting again from {name}.")
    return None, name, before if isinstance(before, dict) else {"notes": before}


def note_times(cues, notes, offset):
    """When each note appears (video time), by 1-based position; None if it can't be placed."""
    placed, missing = make_ass.place_notes(cues, notes, offset)
    gone = {k for k, _ in missing}
    it = iter(placed)
    return {k: (None if k in gone else next(it)["start"]) for k in range(1, len(notes) + 1)}


def words(text):
    return set(re.findall(r"[a-z0-9']+", text.lower()))


# ---------------------------------------------------------------- one window of the video
def make_windows(sheets, duration):
    groups = [sheets[i:i + SHEETS_PER_REQUEST] for i in range(0, len(sheets), SHEETS_PER_REQUEST)]
    out = []
    for k, g in enumerate(groups):
        lo = 0.0 if k == 0 else g[0][1]
        hi = groups[k + 1][0][1] if k + 1 < len(groups) else duration + 1
        out.append({"sheets": g, "lo": lo, "hi": hi})
    return out


def foreign_note(film_language, situation):
    if not situation:
        return ""
    lang = gn.languages.name(film_language)
    note = (f"\nThe film is in {lang}. Signs, letters, newspapers, screens and text messages in {lang} are often NOT "
            f"subtitled: when one matters to the scene, say what it says (category \"On-screen text\"). Also look for "
            f"gestures, places, brands and customs a {lang}-speaking audience would recognise at once.\n")
    if situation == "original":
        note += (f"The dialogue is the {lang} subtitles the viewer reads. Quote {lang} exactly when you need to; "
                 f"write the notes themselves in the language given above.\n")
    if situation == "paired":
        note += (f"In the dialogue, ‹{gn.languages.code(film_language)}: ...› after a line is the original {lang} "
                 f"subtitle for that moment.\n")
    return note


def window_text(win, cues, offset, moments, notes, times, title, k, total, visual_only=False, extra=None):
    lo, hi = win["lo"], win["hi"]
    lines = []
    for c in cues:
        if lo <= c["start"] + offset < hi:
            said = re.sub(r"<[^>]+>|\{[^}]*\}", "", c["text"]).replace("\n", " / ").strip()
            line = f"{c['n']} [{timecode.hms(c['start'] + offset)}] {said}"
            if extra and c["n"] in extra["text"]:
                line += f"  ‹{extra['lang']}: {extra['text'][c['n']]}›"
            lines.append(line)
    loud = [f"{timecode.hms(m['start'])}  {m['end'] - m['start']:.1f} s  +{m['loudness_db']} dB  after: \"{m['after_line']}\""
            for m in moments if lo <= m["start"] < hi]
    listed = {}
    for i, n in enumerate(notes, 1):
        t = times.get(i)
        if visual_only and n.get("kind") != "visual":
            continue
        if t is not None and lo <= t < hi:
            listed[i] = f"#{i} [{timecode.hms(t)}, {n.get('kind', 'speech')}, {n.get('category', 'Note')}, " \
                        f"{n.get('confidence', 'high')}] {n['text']}"
    dialogue = ("(left out: the subtitles are not reliably in step with this video)" if visual_only
                else "\n".join(lines) or "(none)")
    text = (f"Title: {title}\nPart {k} of {total}. This stretch: {timecode.hms(lo)} to {timecode.hms(hi)} (video time).\n\n"
            f"Dialogue in this stretch:\n" + dialogue +
            "\n\nLoud moments with no dialogue:\n" + ("\n".join(loud) or "(none)") +
            "\n\nExisting notes in this stretch:\n" + ("\n".join(listed.values()) or "(none)") +
            "\n\nReply with the JSON object only.")
    return text, listed


def array_after(text, key):
    m = re.search(r'"%s"\s*:\s*\[' % key, text)
    return gn.extract_objects(text[m.end() - 1:]) if m else []


def parse_reply(text):
    return {k: array_after(text, k) for k in ("add", "revise", "retime", "drop")}


# ---------------------------------------------------------------- applying the reply
def note_id(r):
    try:
        return int(str(r.get("id")).lstrip("#"))
    except (TypeError, ValueError):
        return None


def apply_reply(reply, win, cues, offset, notes, times, listed, log, dropped, visual_only=False):
    lo, hi = win["lo"], win["hi"]
    in_win = [c["n"] for c in cues if lo <= c["start"] + offset < hi]
    added = revised = retimed = dropped_n = 0

    for r in reply["add"][:MAX_NEW_PER_WINDOW + 4]:
        try:
            text = str(r["text"]).strip()
        except (KeyError, TypeError):
            continue
        conf = str(r.get("confidence", "medium")).lower()
        conf = conf if conf in ("high", "medium", "low") else "medium"
        kind = "speech" if str(r.get("kind", "visual")).lower() == "speech" else "visual"
        if visual_only and kind == "speech":
            continue
        cat = str(r.get("category") or ("Delivery" if kind == "speech" else "Visual gag")).strip()
        if not text:
            continue
        if kind == "visual":
            t, how = resolve_time(r.get("at"), lo, hi)
            if t is None:
                log.append(f"  skipped an added visual note: time {r.get('at')!r} is outside this stretch")
                continue
            if how:
                log.append(f"  (time {r.get('at')!r}: {how})")
            if any(n.get("kind") == "visual" and abs(timecode.parse_time(n["at_video"]) - t) <= 3
                   and len(words(n["text"]) & words(text)) / max(1, len(words(n["text"]) | words(text))) > 0.5
                   for n in notes if "at_video" in n):
                log.append(f"  skipped an added visual note at {timecode.hms(t)}: duplicates an existing one")
                continue
            note = {"at_video": timecode.srt_ts(t), "category": cat, "text": text, "confidence": conf, "kind": "visual"}
            if isinstance(r.get("duration"), (int, float)):
                note["duration"] = max(3.0, min(12.0, float(r["duration"])))
            where = timecode.hms(t)
        else:
            raw = {"cue": r.get("cue"), "match": r.get("match", ""), "category": cat, "text": text, "confidence": conf}
            note, why = gn.check_note(raw, cues, in_win[0] if in_win else 1, in_win[-1] if in_win else len(cues))
            if note is None:
                log.append(f"  skipped an added delivery note ({why})")
                continue
            if "match" in note:                      # anchor by line number: stays put wherever it is in the file
                idx = subtitles.find_cue(cues, note.pop("match"), 0, int(note.pop("occurrence", 1)))
                note = {"cue": (idx if idx is not None else int(r["cue"]) - 1) + 1, **note}
            where = f"line {note['cue']}"
        notes.append(note)
        added += 1
        log.append(f"  + [{where}] {cat} ({conf}): {text}")

    if visual_only:
        reply = {**reply, "revise": [], "retime": [], "drop": []}
    for r in reply["revise"]:
        i = note_id(r)
        if i not in listed or not str(r.get("text", "")).strip():
            continue
        n = notes[i - 1]
        n.setdefault("original_text", n["text"])
        log.append(f"  ~ #{i} revised ({r.get('reason', 'no reason given')})\n"
                   f"      was: {n['text']}\n      now: {r['text'].strip()}")
        n["text"] = r["text"].strip()
        revised += 1

    for r in reply["retime"]:
        i = note_id(r)
        d = timecode.parse_time(r.get("delay"))
        if i not in listed or d is None:
            continue
        d = max(-3.0, min(15.0, d))
        n = notes[i - 1]
        log.append(f"  > #{i} retimed: delay {n.get('delay', 0)} -> {d:g} s ({r.get('reason', 'no reason given')})")
        n["delay"] = d
        retimed += 1

    for r in reply["drop"]:
        i = note_id(r)
        if i in listed and i not in dropped:
            dropped[i] = r.get("reason", "no reason given")
            log.append(f"  - #{i} dropped ({dropped[i]}): {notes[i - 1]['text']}")
            dropped_n += 1
    return added, revised, retimed, dropped_n


# ---------------------------------------------------------------- main entry point
@dataclasses.dataclass
class RefinePlan:
    """Everything decided before anything is sent: what plan_refine() worked out and printed. refine() runs it."""
    srt_path: Path
    notes_path: Path
    video: object
    spec: dict                       # the notes file as read (or the backup, when starting again)
    notes: list                      # spec["notes"]; the run changes this list in place
    cues: list
    offset: float                    # the sync offset used for this video
    moments: list                    # loud moments with no dialogue
    wins: list                       # every stretch of the video
    todo: list                       # the stretches still to send (empty: nothing left)
    first: int                       # the part number of todo[0]
    total: int
    resume_from: object              # video time a stopped refine is picked up from, or None
    first_backup: object             # the backup from before that stopped refine, or None
    visual_only: bool                # the subtitles can't be trusted: only add on-screen notes
    sync_msg: str                    # for the report
    title: str
    audience: str
    situation: object
    extra: object
    year: object
    language: str
    film_language: object
    model: str
    limit: object
    sys_prompt: object = None        # None when there is nothing to do
    times: object = None             # when each note appears (video time), by 1-based position
    n_img: int = 0                   # the estimate: contact sheets, tokens in and out, dollars (None: unknown model)
    est_in: int = 0
    est_out: int = 0
    cost: object = None
    key: object = None               # the API key (None with estimate_only, or on the subscription)
    backend: str = "api"             # "api" (your key) or "claude-code" (your subscription)


def plan_refine(srt_path, notes_path, video, model=claude_api.DEFAULT_MODEL, frames="keyframes", audience=None,
                title=None, language="English", assume_yes=False, key_file=None, assume_synced=False,
                film_language=None, original_srt=None, limit=None, year=None, estimate_only=False, backend=None):
    """Everything up to the "send?" question: read the notes, offer to pick up a stopped refine, analyse the video
    (the slow part; cached), decide full or visual-only mode, cut the video into stretches, print the plan and send
    the `estimate` event. Nothing is sent and the notes file is untouched. The backend is settled
    (claude_api.load_backend) and the API key read, or Claude Code looked for, before the analysis, so a missing one
    stops the run at once (not with estimate_only)."""
    check_same_episode(video, srt_path, notes_path)
    cues = subtitles.parse_srt(srt_path)
    if not cues:
        sys.exit(f"No subtitle cues found in {srt_path}")
    notes_path = Path(notes_path)
    spec = json.loads(fileio.read_text(notes_path))
    if not isinstance(spec, dict):
        spec = {"notes": spec}
    notes = spec["notes"]
    if not notes:
        sys.exit(f"{notes_path} has no notes to refine. Run with --generate first.")
    stopped = (spec.get("refined") or {}).get("stopped_after")
    resume_from, first_backup = None, None
    if stopped:
        resume_from, first_backup, before = resume_choice(notes_path, stopped, assume_yes or estimate_only)
        if before is not None:
            spec, notes = before, before["notes"]
    backend = claude_api.load_backend(backend)
    key = None
    if not estimate_only:                                             # fail early if there's no way to reach Claude
        if backend == "api":
            key = claude_api.load_key(key_file)
        else:
            claude_api.check_claude_code()
    film_language = film_language or spec.get("film_language")
    if not original_srt and spec.get("original_subtitles"):
        near = Path(srt_path).parent / spec["original_subtitles"]
        original_srt = near if near.exists() else None
    title = title or re.sub(r"\s*\(context notes\)\s*$", "", str(spec.get("title") or Path(srt_path).stem))
    situation, extra = gn.subtitle_setup(cues, film_language, original_srt)
    audience = audience or spec.get("audience") or gn.default_audience(film_language, situation)
    year = year or spec.get("year") or gn.resolve_year(None, video, title)

    import analyze
    print("Analysing the video (the slow part, all on this computer)...")
    if limit:
        print(f"  limited to the first {timecode.fmt_limit(limit)}")
    previous = float(spec.get("video_offset", 0) or 0)
    an = analyze.analyze_video(cues, video, frames, fallback_offset=previous, limit=limit)
    offset = an["offset"]
    sync_msg = None
    if an["offset_measured"] is not None:
        spec["video_offset"] = round(an["offset_measured"], 2)
        sync_msg = (f"sync offset set to {spec['video_offset']:+.2f} s" +
                    (f" (was {previous:+.2f})" if round(previous, 2) != spec["video_offset"] else " (unchanged)"))
    else:
        sync_msg = f"sync offset left at {previous:+.2f} s ({an['sync']['verdict'].rstrip('.')})"
    print("  " + sync_msg)

    synced = an["offset_measured"] is not None or assume_synced
    visual_only = not synced
    if visual_only:
        print("  ! The subtitles can't be matched to this video's soundtrack, so revisions to your existing notes would be\n"
              "    guesswork. I'll only ADD notes about what's on screen and leave your existing notes alone.\n"
              "    (If you've already run  analyze.py --align  and are using the .aligned.srt, add --assume-synced.)")

    wins = make_windows(an["sheets"], an["duration"])
    if not wins:
        sys.exit("No contact sheets were produced, so there is nothing to look at.")
    total, first = len(wins), 1
    if resume_from is not None:
        first = 1 + sum(1 for w in wins if w["hi"] <= resume_from + 0.01)
        sync_msg = f"picked up at {timecode.hms(resume_from)} (part {first} of {total}); {sync_msg}"
        print(f"  Picking up at {timecode.hms(resume_from)}: part {first} of {total}.")
    todo = wins[first - 1:]
    plan = RefinePlan(srt_path=Path(srt_path), notes_path=notes_path, video=video, spec=spec, notes=notes, cues=cues,
                      offset=offset, moments=an["moments"], wins=wins, todo=todo, first=first, total=total,
                      resume_from=resume_from, first_backup=first_backup, visual_only=visual_only, sync_msg=sync_msg,
                      title=title, audience=audience, situation=situation, extra=extra, year=year, language=language,
                      film_language=film_language, model=model, limit=limit, key=key, backend=backend)
    if not todo:
        return plan                              # refine() says so and marks the notes finished
    mode_note = ("IMPORTANT: for this video the subtitles are NOT reliably in step with the picture. Ignore the grey "
                 "subtitle text under frames. ONLY ADD notes with kind \"visual\"; leave the revise, retime and drop "
                 "lists empty.\n\n") if visual_only else ""
    plan.sys_prompt = SYSTEM.format(audience=audience, language=language, maxnew=MAX_NEW_PER_WINDOW, mode_note=mode_note,
                                    foreign_note=foreign_note(film_language, situation), era_section=gn.era_section(year))
    plan.times = note_times(cues, notes, offset)
    est_in = sum(claude_api.image_tokens(p) for w in todo for p, _, _ in w["sheets"])
    est_in += sum((len(plan.sys_prompt) + len(window_text(w, cues, offset, an["moments"], notes, plan.times, title, 1, 1,
                                                          visual_only, extra)[0])) // 3.5 for w in todo)
    plan.est_out = len(todo) * 500
    plan.est_in = int(est_in)
    plan.cost = c = claude_api.cost(model, plan.est_in, plan.est_out, backend)
    plan.n_img = n_img = sum(len(w["sheets"]) for w in todo)
    print(("Mode: full (subtitles are in sync with the video)." if not visual_only else
           "Mode: on-screen notes only (subtitles not in sync).") + f" Offset used: {offset:+.2f} s.")
    print(f"Plan: {len(todo)} request(s) to {model}, {n_img} contact-sheet images (video frames) plus the dialogue and "
          f"your {len(notes)} notes; about {plan.est_in:,} tokens in and {plan.est_out:,} out"
          + claude_api.cost_note(c, backend))
    prompts.event("estimate", step="refine", model=model, backend=backend, mode="visual-only" if visual_only else "full",
                  offset=round(offset, 2), requests=len(todo), images=n_img, notes=len(notes), input_tokens=plan.est_in,
                  output_tokens=plan.est_out, cost_usd=None if c is None else round(c, 4), limit=limit)
    return plan


def confirm_refine(plan, assume_yes=False):
    """The "send?" question (--yes answers it). Stops the run on no, or when there is nobody to ask."""
    if not assume_yes:
        where = "Claude Code (your subscription)" if plan.backend == "claude-code" else "the Claude API"
        if not prompts.interactive():
            sys.exit(f"Not an interactive terminal, so add --yes to confirm sending the frames and subtitles to {where}.")
        if not prompts.confirm(f"Send the video frames and subtitle text to {where} now?", id="refine.send"):
            sys.exit("Cancelled; nothing was sent. (The video analysis is saved, so a rerun is quicker.)")


def window_content(plan, k, win, notes, times):
    """What Claude is shown for one stretch: each contact sheet (as a file path; the image is read and encoded only
    at the API call) with a caption, then the dialogue, loud moments and existing notes as text.
    Returns (content blocks, the existing notes listed, by id)."""
    text, listed = window_text(win, plan.cues, plan.offset, plan.moments, notes, times, plan.title, k, plan.total,
                               plan.visual_only, plan.extra)
    content = []
    for path, t0, t1 in win["sheets"]:
        content.append({"type": "text", "text": f"Contact sheet: frames from {timecode.hms(t0)} to {timecode.hms(t1)}"})
        content.append({"type": "image", "path": str(path), "media_type": "image/jpeg"})
    content.append({"type": "text", "text": text})
    return content, listed


def refine_window(plan, k, win, notes, times, key, log, dropped, api_url=claude_api.API_URL,
                  max_tokens=REFINE_MAX_TOKENS, effort=None):
    """One request: the stretch `win` goes to Claude and its reply is applied to `notes` (apply_reply, which also
    writes to `log` and `dropped`). Returns (what happened, usage): a dict with the parsed reply, the counts of notes
    added, revised, retimed and dropped, and any problems with the reply. The one call to Claude is claude_api.send
    (the API or Claude Code, by plan.backend): for the API the images are base64-encoded there and nowhere else; Claude
    Code is given their paths and opens them itself, running in the notes file's folder."""
    content, listed = window_content(plan, k, win, notes, times)
    reply = claude_api.send(plan.backend, plan.model, plan.sys_prompt, content, key=key, api_url=api_url,
                            timeout=600, max_tokens=max_tokens, effort=effort, workdir=plan.notes_path.resolve().parent)
    usage = reply.get("usage", {})
    reply_text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
    parsed = parse_reply(reply_text)
    problems = []
    if not any(parsed.values()) and reply_text.strip() not in ("{}", ""):
        bad = plan.notes_path.with_suffix(f".refine{k}.failed.txt")
        bad.write_text(reply_text, encoding="utf-8")
        problems.append(f"part {k}: couldn't read the reply; saved it to {bad.name}")
    if reply.get("stop_reason") == "max_tokens":
        problems.append(f"part {k}: reply was cut off, so some changes in this part may be missing")
    added, revised, retimed, dropped_n = apply_reply(parsed, win, plan.cues, plan.offset, notes, times, listed, log,
                                                     dropped, plan.visual_only)
    return {"parsed": parsed, "added": added, "revised": revised, "retimed": retimed, "dropped": dropped_n,
            "problems": problems}, usage


def finish_refine(plan, notes, dropped, log, backup, usage, problems):
    """A refine that got to the end: write the notes file and the report (_save). Returns the report's path."""
    return _save(plan.spec, notes, dropped, plan.notes_path, log, backup, sync_msg=plan.sync_msg, model=plan.model,
                 usage=usage, problems=problems, sheets=plan.n_img, limit=plan.limit,
                 append=plan.resume_from is not None, backend=plan.backend)


def refine(srt_path, notes_path, video, model=claude_api.DEFAULT_MODEL, frames="keyframes", audience=None, title=None,
           language="English", assume_yes=False, key_file=None, api_url=claude_api.API_URL, ass_path=None,
           assume_synced=False, film_language=None, original_srt=None, limit=None, effort=None,
           max_tokens=REFINE_MAX_TOKENS, year=None, estimate_only=False, backend=None):
    """Refine the notes using the video: plan_refine, the "send?" question, backups, one request per stretch
    (refine_window), finish_refine. With estimate_only, stop after the size and cost estimate: no API key is needed
    and nothing is sent; the notes and .ass are untouched (the video analysis is cached as usual). A run that stops
    part-way saves its changes with `refined.stopped_after`, so the next one can pick up there.
    `backend` is "api", "claude-code" or None (the saved setting, else the API)."""
    plan = plan_refine(srt_path, notes_path, video, model=model, frames=frames, audience=audience, title=title,
                       language=language, assume_yes=assume_yes, key_file=key_file, assume_synced=assume_synced,
                       film_language=film_language, original_srt=original_srt, limit=limit, year=year,
                       estimate_only=estimate_only, backend=backend)
    notes_path, spec, notes = plan.notes_path, plan.spec, plan.notes
    total, first, sync_msg, resume_from, first_backup = plan.total, plan.first, plan.sync_msg, plan.resume_from, plan.first_backup
    if not plan.todo:
        if not estimate_only:
            _save(spec, notes, {}, notes_path, ["(nothing was left to refine)"],
                  notes_path.with_name(first_backup or notes_path.name), sync_msg=sync_msg, model=model, limit=limit,
                  append=True, backend=plan.backend)
        print("Nothing was left to refine" + ("." if estimate_only else "; marked as finished."))
        return None
    if estimate_only:
        print("Estimate only: nothing was sent. (The video analysis is saved, so the real run is quicker.)")
        return None
    confirm_refine(plan, assume_yes)

    backup = unique_backup(notes_path)
    shutil.copy2(notes_path, backup)
    print(f"Kept a backup of your notes: {backup.name}")
    if ass_path and Path(ass_path).exists():
        ass_backup = unique_backup(ass_path)
        shutil.copy2(ass_path, ass_backup)
        print(f"Kept the old subtitles: {ass_backup.name}")
    log, dropped, tin, tout, total_added, problems = [], {}, 0, 0, 0, []
    total_revised = total_retimed = 0
    n_img, times = plan.n_img, plan.times
    def stop_early():
        last = max(resume_from or 0.0, plan.wins[completed - 1]["hi"] if completed else 0.0)
        print()
        _save(spec, notes, dropped, notes_path, log, backup, model=model, usage=(tin, tout), sheets=n_img,
              sync_msg=f"STOPPED EARLY after part {completed} of {total}; {sync_msg}", limit=limit,
              stopped={"time": round(last, 3), "part": completed, "parts": total,
                       "backup": first_backup or backup.name},
              append=resume_from is not None, backend=plan.backend)
        print(f"  Stopped after part {completed} of {total}. The changes so far were saved to the notes file "
              f"(original: {backup.name}). The next refine offers to pick up from here.", flush=True)

    completed = first - 1
    try:
        for k, win in enumerate(plan.todo, first):
            prompts.progress("refine", k - 1, total, "requests")        # before the line below, which stays open
            print(f"  part {k}/{total}: {timecode.hms(win['lo'])}-{timecode.hms(win['hi'])} ...", end=" ", flush=True)
            try:
                done, u = refine_window(plan, k, win, notes, times, plan.key, log, dropped, api_url=api_url,
                                        max_tokens=max_tokens, effort=effort)
            except SystemExit:                               # an API error: keep the changes so far
                stop_early()
                raise
            tin += u.get("input_tokens", 0)
            tout += u.get("output_tokens", 0)
            problems += done["problems"]
            total_added += done["added"]
            total_revised += done["revised"]
            total_retimed += done["retimed"]
            print(f"{done['added']} added, {done['revised']} revised, {done['retimed']} retimed, {done['dropped']} dropped")
            # new notes need times too, so later windows can see them
            times = note_times(plan.cues, notes, plan.offset)
            completed = k
    except KeyboardInterrupt:                    # Ctrl-C, or a GUI's Cancel: keep the changes so far
        stop_early()
        raise
    prompts.progress("refine", total, total, "requests")

    report = finish_refine(plan, notes, dropped, log, backup, usage=(tin, tout), problems=problems)
    actual = claude_api.cost(model, tin, tout, plan.backend)
    print(f"Refined {notes_path.name}: {total_added} added, {total_revised} revised, {total_retimed} retimed, "
          f"{len(dropped)} dropped; {sync_msg}.")
    print(f"Used {tin:,} input and {tout:,} output tokens" + claude_api.used_note(actual, plan.backend))
    print(f"Report of every change: {report}")
    for p in problems:
        print("  ! " + p)


def _save(spec, notes, dropped, notes_path, log, backup, sync_msg=None, model=None, usage=None,
          problems=(), sheets=0, limit=None, stopped=None, append=False, backend="api"):
    """Write the refined notes and the report. `stopped` ({time, part, parts, backup}) marks a refine that didn't
    finish, so the next one can pick up there; `append` adds to the report instead of replacing it."""
    spec["notes"] = [n for i, n in enumerate(notes, 1) if i not in dropped]
    spec["refined"] = {"model": model, "date": datetime.date.today().isoformat(), "contact_sheets": sheets}
    if backend != "api":
        spec["refined"]["backend"] = backend
    if limit:
        spec["refined"]["limit"] = round(limit, 1)
    if stopped:
        spec["refined"]["stopped_after"] = stopped
    fileio.write_text_safely(notes_path, json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
    report = notes_path.with_name(notes_path.stem + ".refine-report.txt")
    with open(report, "a" if append else "w", encoding="utf-8") as f:
        f.write(("\n" if append else "") + f"Refinement of {notes_path.name} on {datetime.date.today().isoformat()} ({model})\n"
                f"Original saved as {backup.name}\n{sync_msg or ''}\n")
        if usage:
            f.write(f"Tokens: {usage[0]:,} in, {usage[1]:,} out\n")
        f.write("\n" + "\n".join(log) + "\n")
        for p in problems:
            f.write(f"! {p}\n")
    return report
