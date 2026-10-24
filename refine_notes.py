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
The key and cost handling are the same as for --generate (see generate_notes.py).
"""
import base64
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

import generate_notes as gn
import make_ass
import prompts

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
def hms(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t // 60 % 60):02d}:{int(t % 60):02d}"


def srt_ts(t):
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def parse_time(v):
    """Seconds as a number, or 'm:ss' / 'h:mm:ss(.s)' text."""
    if isinstance(v, (int, float)):
        return float(v)
    parts = str(v).strip().split(":")
    try:
        secs = 0.0
        for p in parts:
            secs = secs * 60 + float(p.replace(",", "."))
        return secs
    except ValueError:
        return None


def resolve_time(v, lo, hi):
    """A visual note's time in video seconds. Prefers h:mm:ss text; for bare numbers, tries seconds, then
    decimal minutes (models sometimes write 9.8 for 9:48), then seconds from the start of the stretch."""
    t = parse_time(v)
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
                       f"({hms(float(stopped.get('time', 0)))} into the video). Pick up where it left off?",
                       {"p": "pick up where it left off", "s": again}, "p", auto, id="refine.resume")
    if pick == "p":
        return float(stopped.get("time", 0)), name, None
    if not have:
        return None, None, None
    before = json.loads(make_ass.read_text(backup))
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


def image_tokens(path):
    try:
        from PIL import Image
        w, h = Image.open(path).size
    except Exception:
        return 2500
    f = min(1.0, 1568 / max(w, h))
    return int(w * f * h * f / 750)


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
            line = f"{c['n']} [{hms(c['start'] + offset)}] {said}"
            if extra and c["n"] in extra["text"]:
                line += f"  ‹{extra['lang']}: {extra['text'][c['n']]}›"
            lines.append(line)
    loud = [f"{hms(m['start'])}  {m['end'] - m['start']:.1f} s  +{m['loudness_db']} dB  after: \"{m['after_line']}\""
            for m in moments if lo <= m["start"] < hi]
    listed = {}
    for i, n in enumerate(notes, 1):
        t = times.get(i)
        if visual_only and n.get("kind") != "visual":
            continue
        if t is not None and lo <= t < hi:
            listed[i] = f"#{i} [{hms(t)}, {n.get('kind', 'speech')}, {n.get('category', 'Note')}, " \
                        f"{n.get('confidence', 'high')}] {n['text']}"
    dialogue = ("(left out: the subtitles are not reliably in step with this video)" if visual_only
                else "\n".join(lines) or "(none)")
    text = (f"Title: {title}\nPart {k} of {total}. This stretch: {hms(lo)} to {hms(hi)} (video time).\n\n"
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
            if any(n.get("kind") == "visual" and abs(parse_time(n["at_video"]) - t) <= 3
                   and len(words(n["text"]) & words(text)) / max(1, len(words(n["text"]) | words(text))) > 0.5
                   for n in notes if "at_video" in n):
                log.append(f"  skipped an added visual note at {hms(t)}: duplicates an existing one")
                continue
            note = {"at_video": srt_ts(t), "category": cat, "text": text, "confidence": conf, "kind": "visual"}
            if isinstance(r.get("duration"), (int, float)):
                note["duration"] = max(3.0, min(12.0, float(r["duration"])))
            where = hms(t)
        else:
            raw = {"cue": r.get("cue"), "match": r.get("match", ""), "category": cat, "text": text, "confidence": conf}
            note, why = gn.check_note(raw, cues, in_win[0] if in_win else 1, in_win[-1] if in_win else len(cues))
            if note is None:
                log.append(f"  skipped an added delivery note ({why})")
                continue
            if "match" in note:                      # anchor by line number: stays put wherever it is in the file
                idx = make_ass.find_cue(cues, note.pop("match"), 0, int(note.pop("occurrence", 1)))
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
        d = parse_time(r.get("delay"))
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
def refine(srt_path, notes_path, video, model=gn.DEFAULT_MODEL, frames="keyframes", audience=None, title=None,
           language="English", assume_yes=False, key_file=None, api_url=gn.API_URL, ass_path=None,
           assume_synced=False, film_language=None, original_srt=None, limit=None, effort=None,
           max_tokens=REFINE_MAX_TOKENS, year=None, estimate_only=False):
    """Refine the notes using the video. With estimate_only, stop after the size and cost estimate: no API key
    is needed and nothing is sent; the notes and .ass are untouched (the video analysis is cached as usual)."""
    check_same_episode(video, srt_path, notes_path)
    cues = make_ass.parse_srt(srt_path)
    if not cues:
        sys.exit(f"No subtitle cues found in {srt_path}")
    notes_path = Path(notes_path)
    spec = json.loads(make_ass.read_text(notes_path))
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
    key = None if estimate_only else gn.load_key(key_file)    # fail early if there is no usable key
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
        print(f"  limited to the first {make_ass.fmt_limit(limit)}")
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
        sync_msg = f"picked up at {hms(resume_from)} (part {first} of {total}); {sync_msg}"
        print(f"  Picking up at {hms(resume_from)}: part {first} of {total}.")
    todo = wins[first - 1:]
    if not todo:
        if not estimate_only:
            _save(spec, notes, {}, notes_path, ["(nothing was left to refine)"],
                  notes_path.with_name(first_backup or notes_path.name), sync_msg=sync_msg, model=model, limit=limit,
                  append=True)
        print("Nothing was left to refine" + ("." if estimate_only else "; marked as finished."))
        return None
    mode_note = ("IMPORTANT: for this video the subtitles are NOT reliably in step with the picture. Ignore the grey "
                 "subtitle text under frames. ONLY ADD notes with kind \"visual\"; leave the revise, retime and drop "
                 "lists empty.\n\n") if visual_only else ""
    sys_prompt = SYSTEM.format(audience=audience, language=language, maxnew=MAX_NEW_PER_WINDOW, mode_note=mode_note,
                               foreign_note=foreign_note(film_language, situation), era_section=gn.era_section(year))
    times = note_times(cues, notes, offset)
    est_in = sum(image_tokens(p) for w in todo for p, _, _ in w["sheets"])
    est_in += sum((len(sys_prompt) + len(window_text(w, cues, offset, an["moments"], notes, times, title, 1, 1,
                                                     visual_only, extra)[0])) // 3.5 for w in todo)
    est_out = len(todo) * 500
    est_in = int(est_in)
    c = gn.cost(model, est_in, est_out)
    n_img = sum(len(w["sheets"]) for w in todo)
    print(("Mode: full (subtitles are in sync with the video)." if not visual_only else
           "Mode: on-screen notes only (subtitles not in sync).") + f" Offset used: {offset:+.2f} s.")
    print(f"Plan: {len(todo)} request(s) to {model}, {n_img} contact-sheet images (video frames) plus the dialogue and "
          f"your {len(notes)} notes; about {est_in:,} tokens in and {est_out:,} out"
          + (f", roughly ${c:.2f} in API credits." if c is not None else "."))
    prompts.event("estimate", step="refine", model=model, mode="visual-only" if visual_only else "full",
                  offset=round(offset, 2), requests=len(todo), images=n_img, notes=len(notes), input_tokens=est_in,
                  output_tokens=est_out, cost_usd=None if c is None else round(c, 4), limit=limit)
    if estimate_only:
        print("Estimate only: nothing was sent. (The video analysis is saved, so the real run is quicker.)")
        return None
    if not assume_yes:
        if not prompts.interactive():
            sys.exit("Not an interactive terminal, so add --yes to confirm sending the frames and subtitles to the API.")
        if not prompts.confirm("Send the video frames and subtitle text to the Claude API now?", id="refine.send"):
            sys.exit("Cancelled; nothing was sent. (The video analysis is saved, so a rerun is quicker.)")

    backup = unique_backup(notes_path)
    shutil.copy2(notes_path, backup)
    print(f"Kept a backup of your notes: {backup.name}")
    if ass_path and Path(ass_path).exists():
        ass_backup = unique_backup(ass_path)
        shutil.copy2(ass_path, ass_backup)
        print(f"Kept the old subtitles: {ass_backup.name}")
    log, dropped, tin, tout, total_added, problems = [], {}, 0, 0, 0, []
    total_revised = total_retimed = 0
    def stop_early():
        last = max(resume_from or 0.0, wins[completed - 1]["hi"] if completed else 0.0)
        print()
        _save(spec, notes, dropped, notes_path, log, backup, model=model, usage=(tin, tout), sheets=n_img,
              sync_msg=f"STOPPED EARLY after part {completed} of {total}; {sync_msg}", limit=limit,
              stopped={"time": round(last, 3), "part": completed, "parts": total,
                       "backup": first_backup or backup.name},
              append=resume_from is not None)
        print(f"  Stopped after part {completed} of {total}. The changes so far were saved to the notes file "
              f"(original: {backup.name}). The next refine offers to pick up from here.", flush=True)

    completed = first - 1
    try:
        for k, win in enumerate(todo, first):
            text, listed = window_text(win, cues, offset, an["moments"], notes, times, title, k, total, visual_only,
                                       extra)
            content = []
            for path, t0, t1 in win["sheets"]:
                content.append({"type": "text", "text": f"Contact sheet: frames from {hms(t0)} to {hms(t1)}"})
                content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                            "data": base64.b64encode(Path(path).read_bytes()).decode()}})
            content.append({"type": "text", "text": text})
            prompts.progress("refine", k - 1, total, "requests")        # before the line below, which stays open
            print(f"  part {k}/{total}: {hms(win['lo'])}-{hms(win['hi'])} ...", end=" ", flush=True)
            try:
                reply = gn.call_api(key, model, sys_prompt, content, api_url, timeout=600, max_tokens=max_tokens,
                                    effort=effort)
            except SystemExit:                               # an API error: keep the changes so far
                stop_early()
                raise
            u = reply.get("usage", {})
            tin += u.get("input_tokens", 0)
            tout += u.get("output_tokens", 0)
            reply_text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
            parsed = parse_reply(reply_text)
            if not any(parsed.values()) and reply_text.strip() not in ("{}", ""):
                bad = notes_path.with_suffix(f".refine{k}.failed.txt")
                bad.write_text(reply_text, encoding="utf-8")
                problems.append(f"part {k}: couldn't read the reply; saved it to {bad.name}")
            if reply.get("stop_reason") == "max_tokens":
                problems.append(f"part {k}: reply was cut off, so some changes in this part may be missing")
            added, revised, retimed, dropped_n = apply_reply(parsed, win, cues, offset, notes, times, listed, log, dropped,
                                                             visual_only)
            total_added += added
            total_revised += revised
            total_retimed += retimed
            print(f"{added} added, {revised} revised, {retimed} retimed, {dropped_n} dropped")
            # new notes need times too, so later windows can see them
            times = note_times(cues, notes, offset)
            completed = k
    except KeyboardInterrupt:                    # Ctrl-C, or a GUI's Cancel: keep the changes so far
        stop_early()
        raise
    prompts.progress("refine", total, total, "requests")

    report = _save(spec, notes, dropped, notes_path, log, backup, sync_msg=sync_msg, model=model,
                   usage=(tin, tout), problems=problems, sheets=n_img, limit=limit, append=resume_from is not None)
    actual = gn.cost(model, tin, tout)
    print(f"Refined {notes_path.name}: {total_added} added, {total_revised} revised, {total_retimed} retimed, "
          f"{len(dropped)} dropped; {sync_msg}.")
    print(f"Used {tin:,} input and {tout:,} output tokens" + (f" (about ${actual:.2f})." if actual is not None else "."))
    print(f"Report of every change: {report}")
    for p in problems:
        print("  ! " + p)


def _save(spec, notes, dropped, notes_path, log, backup, sync_msg=None, model=None, usage=None,
          problems=(), sheets=0, limit=None, stopped=None, append=False):
    """Write the refined notes and the report. `stopped` ({time, part, parts, backup}) marks a refine that didn't
    finish, so the next one can pick up there; `append` adds to the report instead of replacing it."""
    spec["notes"] = [n for i, n in enumerate(notes, 1) if i not in dropped]
    spec["refined"] = {"model": model, "date": datetime.date.today().isoformat(), "contact_sheets": sheets}
    if limit:
        spec["refined"]["limit"] = round(limit, 1)
    if stopped:
        spec["refined"]["stopped_after"] = stopped
    make_ass.write_text_safely(notes_path, json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
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
