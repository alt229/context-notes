#!/usr/bin/env python3
"""
align_check.py - is every note still in step with the film?

The sync check (analyze.py) fixes one constant offset for the whole film. This goes note by note: for each
note it takes the subtitle lines in the WINDOW seconds before it (default 10) and measures how far those lines
are from the speech in the soundtrack. That catches the stretches where a different cut, a missing scene or a
sloppy subtitle file puts lines - and so the notes that follow them - early or late.

    python3 align_check.py film.mkv film.en.srt                     the film's notes file, as context_notes.py finds it
    python3 align_check.py film.mkv film.en.srt --original-subs film.de.srt --film-language de
    python3 align_check.py film.mkv film.srt --fix                   also write <name>.aligned.srt (in the film's
                                                                     context-notes folder) with the stretches that
                                                                     are out corrected
    python3 align_check.py film.mkv film.srt --window 5              look only 5 s back from each note

How: the soundtrack is transcribed once with speech recognition (local, free; cached, and shared with
analyze.py --align), and each line's opening words are found in what is actually said. That needs subtitles in
the language being spoken; for subtitles in another language (English on a German film) give the original-
language ones with --original-subs, and each line is measured through the original line beside it.
(Plain speech detection - where speech starts, without the words - was tried and dropped: on Amélie, which is in
sync, it reported eight stretches out of step. Narration and music fool it.)
Subtitles are never timed to the frame by their makers: lines a few tenths early or late are normal and
left alone. Results go to context-notes/<video file name>/analysis/alignment.txt (see workfiles.py).
"""
import argparse
import difflib
import json
import re
import shutil
import statistics
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402
import fileio  # noqa: E402
import subtitles  # noqa: E402
import timecode  # noqa: E402
import languages  # noqa: E402
import make_ass  # noqa: E402
import workfiles  # noqa: E402

TOLERANCE = 0.7       # seconds out before a stretch is reported. Lines are timed loosely by their makers: on
                      # Amélie's in-sync subtitles, half of all 10 s windows were within 0.3 s, 3 in 4 within 0.6 s
MIN_LINES = 2         # lines measured in a window to judge it (one line on its own is too noisy)


# ---------------------------------------------------------------- measuring lines against the speech
def words(text):
    text = subtitles.fold(re.sub(r"<[^>]+>|\{[^}]*\}", " ", text))
    return [w for w in re.findall(r"[a-z']+", text) if w.strip("'")]


def asr_cue_offsets(cues, asr):
    """{cue index: seconds the speech starts after the line appears}, for lines whose opening words are found in
    the transcript (runs of 3+ matching words, so a lone common word can't anchor a line in the wrong place).
    Measured from a line's first or second word: subtitles appear as speech starts, but linger after it ends."""
    sw, sc, pos = [], [], []
    for i, c in enumerate(cues):
        for k, w in enumerate(words(c["text"])):
            sw.append(w)
            sc.append(i)
            pos.append(k)
    aw, at = [], []
    for seg in asr:
        for s, _e, w in seg.get("w", []):
            for x in words(w):
                aw.append(x)
                at.append(s)
    out = {}
    for b in difflib.SequenceMatcher(None, sw, aw, autojunk=False).get_matching_blocks():
        if b.size < 3:
            continue
        for k in range(b.size):
            a = b.a + k
            i = sc[a]
            if pos[a] <= 1 and i not in out:
                out[i] = at[b.b + k] - (cues[i]["start"] + pos[a] * 0.3)
    return out


def through_original(cues, original, original_offsets):
    """Offsets for subtitles in another language, measured through original-language subtitles that were
    measured against the transcript: each line is paired with the original line starting nearest to it, after
    lining the two files up as a whole. Returns {cue index: offset}."""
    if not original_offsets:
        return {}
    shift, strength, corr = analyze.subtitle_offset(cues, original)
    if strength < 1.3 or corr < 0.4:
        shift = 0.0                       # the files don't resemble each other overall; pair as they are
    starts = [o["start"] for o in original]
    import bisect
    out = {}
    for i, c in enumerate(cues):
        t = c["start"] + shift
        k = bisect.bisect_left(starts, t)
        best = min((j for j in (k - 1, k) if 0 <= j < len(original)), key=lambda j: abs(starts[j] - t), default=None)
        if best is None or abs(starts[best] - t) > 1.5 or best not in original_offsets:
            continue
        out[i] = original_offsets[best] + (starts[best] - c["start"])
    return out


# ---------------------------------------------------------------- per-note check
def note_windows(placed, cues, offset, window):
    """For each dialogue note, the indexes of the lines that start (on the video's clock) in the `window`
    seconds before it appears."""
    import bisect
    starts = [c["start"] + offset for c in cues]
    out = []
    for p in placed:
        if p["kind"] != "speech" or p["category"].lower() == "about these notes":
            continue
        lo, hi = bisect.bisect_left(starts, p["start"] - window), bisect.bisect_right(starts, p["start"])
        out.append((p, list(range(lo, hi))))
    return out


def measure(placed, cues, offset, window, cue_offsets):
    """One row per dialogue note: how far the lines before it are from the speech, after the offset the build
    already applies (positive = lines early). Rows: {k, time, text, lines, measured, offset (None: not judged)}."""
    rows = []
    for p, idx in note_windows(placed, cues, offset, window):
        vals = [cue_offsets[i] - offset for i in idx if i in cue_offsets]
        rows.append({"k": p["k"], "time": round(p["start"], 2), "text": p["text"], "lines": len(idx),
                     "measured": len(vals),
                     "offset": round(float(statistics.median(vals)), 2) if len(vals) >= MIN_LINES else None})
    return rows


def flag(rows):
    """Mark notes in a stretch that is out. A note is out when its own window AND its neighbourhood (it and the
    measured notes either side) are past the tolerance in the same direction, so one loosely timed line doesn't
    count."""
    measured = [r for r in rows if r["offset"] is not None]
    for k, r in enumerate(measured):
        r["smoothed"] = round(statistics.median(x["offset"] for x in measured[max(0, k - 1):k + 2]), 2)
        r["out"] = bool(abs(r["offset"]) > TOLERANCE and abs(r["smoothed"]) > TOLERANCE
                        and (r["offset"] > 0) == (r["smoothed"] > 0))
    for r in rows:
        r.setdefault("out", False)
    return rows


def stretches(rows, gap=180.0):
    """Runs of out-of-step notes (a gap of more than `gap` seconds, or an in-step note between, ends a run)."""
    runs, cur = [], []
    for r in rows:
        if r["offset"] is None:
            continue
        if r["out"] and (not cur or (r["time"] - cur[-1]["time"] <= gap and (r["offset"] > 0) == (cur[-1]["offset"] > 0))):
            cur.append(r)
            continue
        if cur:
            runs.append(cur)
        cur = [r] if r["out"] else []
    if cur:
        runs.append(cur)
    return [{"from": run[0]["time"], "to": run[-1]["time"], "notes": [x["k"] for x in run],
             "offset": round(statistics.median(x["offset"] for x in run), 2)} for run in runs]


def corrections(cues, offset, runs, window):
    """How far to move each line to fix the stretches: lines from `window` s before a stretch's first note to its
    last note move by the stretch's offset; others don't move. Stretch times are on the video's clock, so lines are
    compared there (subtitle time + offset); the shift itself excludes the offset, which the build adds anyway.
    Returns {cue index: shift}."""
    out = {i: 0.0 for i in range(len(cues))}
    for run in runs:
        for i, c in enumerate(cues):
            if run["from"] - window <= c["start"] + offset <= run["to"]:
                out[i] = run["offset"]
    return out


def fixed_path(srt, video=None):
    """film.en.srt -> film.en.aligned.srt in the video's working folder; film.en.aligned.srt stays film.en.aligned.srt
    where it is (a backup is kept), and film.en.aligned.first600s.srt stays that, so a fix to part of a film never
    passes for a whole-film one."""
    srt = Path(srt)
    m = re.search(r"\.aligned(\.first\d+s)?$", srt.stem)
    if m:
        return srt                                               # a --limit file keeps its .firstNNNs tag
    return workfiles.folder_for(srt, video) / (srt.stem + ".aligned.srt")


# ---------------------------------------------------------------- putting it together
def find_transcript(folder, film_lang, limit):
    """A cached transcript in the spoken language that covers the check (from analyze.py --align or an earlier
    check). A whole-film one is preferred."""
    lang = languages.code(film_lang) or "en"
    best = None
    for p in sorted(Path(folder).glob("transcript-*.jsonl")):
        m = re.fullmatch(r"transcript-(.+?)(?:-([a-z]{2}))?(?:-first(\d+)s)?", p.stem)
        if not m or (m.group(2) or "en") != lang:
            continue
        covers = m.group(3) is None or (limit is not None and float(m.group(3)) >= limit - 1)
        if covers and (best is None or m.group(3) is None):
            best = p
    return best


def run_check(video, srt, notes_path, original=None, film_lang=None, window=10.0, transcribe=True, model=None,
              limit=None, fix=False, say=print):
    """The whole check, as data: {rows, runs, fixed (path or None), summary lines, report path}. Exits with a
    message when it can't be done (no transcript and transcribe=False, faster-whisper missing, wrong language)."""
    video, srt = Path(video), Path(srt)
    spec = json.loads(fileio.read_text(notes_path))
    notes = spec["notes"] if isinstance(spec, dict) else spec
    spec = spec if isinstance(spec, dict) else {}
    offset = float(spec.get("video_offset", 0) or 0)
    film_lang = languages.code(film_lang or spec.get("film_language")) or "en"
    cues = subtitles.parse_srt(srt)
    if not cues:
        sys.exit(f"No subtitle lines in {srt}")
    import dedupe
    dups, _ = dedupe.find_duplicates(notes)
    placed, _ = make_ass.place_notes(cues, notes, offset, make_ass.timing_settings(spec), skip={j for j, _, _ in dups})
    if limit:
        placed = [p for p in placed if p["start"] < limit]
    if not any(p["kind"] == "speech" for p in placed):
        sys.exit(f"None of the notes could be placed on {srt.name} (their quotes aren't in it?), so there is nothing "
                 f"to check. Use the subtitle file the notes were written from.")

    # Which subtitles can be compared with the words spoken?
    subs_lang = languages.guess(" ".join(c["text"] for c in cues[:300]))
    if original:
        ref_cues = subtitles.parse_srt(original)
    elif subs_lang is None or languages.same(subs_lang, film_lang):
        ref_cues = cues
    else:
        sys.exit(f"{srt.name} looks {languages.name(subs_lang)}, but the film is in {languages.name(film_lang)}, so its "
                 f"lines can't be found in what is said. Give the {languages.name(film_lang)} subtitles with "
                 f"--original-subs and the lines are measured through them.")

    analyze.need_ffmpeg()
    folder = workfiles.analysis(video)
    workfiles.make_dirs(folder)
    duration, astream, _ = analyze.probe(video)
    if limit and limit >= duration:
        limit = None
    transcript = find_transcript(folder, film_lang, limit)
    if transcript is None:
        if not transcribe:
            sys.exit("No speech-recognition transcript yet; run without --no-transcribe to make one.")
        name = analyze.whisper_model(film_lang, model)
        say(f"  Transcribing the soundtrack ({name}, {languages.name(film_lang)}). Local and free, but slow: very "
            f"roughly a tenth of the film's running time. Done once; later checks and analyze.py --align reuse it.")
        transcript = analyze.transcript_cache(folder, name, film_lang, limit)
        analyze.transcribe(video, astream, name, transcript, language=film_lang, limit=limit)
    asr = [json.loads(line) for line in transcript.open(encoding="utf-8")]
    ref = asr_cue_offsets(ref_cues, asr)
    cue_offsets = ref if ref_cues is cues else through_original(cues, ref_cues, ref)
    in_range = len(subtitles.limit_cues(cues, limit))
    say(f"  {len(cue_offsets)} of {in_range} lines found in what is said ({transcript.name}"
        + (f", through {Path(original).name}" if original else "") + ")")
    if len(cue_offsets) < max(10, 0.15 * in_range):
        sys.exit("  Too few lines matched the speech to check anything. Are the subtitles (or --original-subs) in the "
                 "language being spoken, and for this film?")

    rows = flag(measure(placed, cues, offset, window, cue_offsets))
    runs = stretches(rows)
    checked = [r for r in rows if r["offset"] is not None]
    summary = [f"Alignment check, {window:g} s before each note: {len(checked)} of {len(rows)} dialogue notes "
               f"could be checked (the rest have under {MIN_LINES} recognisable lines before them)."]
    if checked:
        typical = statistics.median(r["offset"] for r in checked)
        summary.append(f"  Typical: lines {abs(typical):.2f} s {'before' if typical > 0 else 'after'} the speech "
                       f"(within {TOLERANCE:g} s counts as in step).")
    if not runs:
        summary.append("  No stretch of the film is out of step." if checked else
                       "  Not enough measurable dialogue to judge.")
    for run in runs:
        when = "early" if run["offset"] > 0 else "late"
        summary.append(f"  ! {timecode.fmt_ass_time(max(run['from'] - window, 0)).split('.')[0]} to "
                       f"{timecode.fmt_ass_time(run['to']).split('.')[0]}: lines {abs(run['offset']):.1f} s {when} "
                       f"(notes {', '.join('#' + str(k) for k in run['notes'][:8])}"
                       + (" ..." if len(run["notes"]) > 8 else "") + ")")

    fixed = None
    if runs and fix:
        fixed = fixed_path(srt, video)
        if fixed.exists():
            backup = analyze_backup(fixed)
            summary.append(f"  Kept the previous {fixed.name} as {backup.name}.")
        subtitles.write_srt(cues, corrections(cues, offset, runs, window), fixed)
        same = fixed.resolve() == srt.resolve()
        summary.append(f"  Wrote {fixed.name}: those stretches moved to match the speech, every other line as it was"
                       + ("." if same else f" ({srt.name} is untouched)."))
    elif runs:
        summary.append("  --fix writes a corrected copy of the subtitles with those stretches moved.")

    report = {"video": video.name, "subtitles": srt.name, "original_subtitles": Path(original).name if original else None,
              "transcript": transcript.name, "window": window, "tolerance": TOLERANCE, "video_offset": offset,
              "stretches": runs, "fixed": fixed.name if fixed else None, "notes": rows}
    fileio.write_text_safely(folder / "alignment.json", json.dumps(report, indent=1, ensure_ascii=False))
    with open(folder / "alignment.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(summary) + "\n\nnote   time      lines  offset  smoothed   (offset: + = lines early)\n")
        for r in rows:
            off = "   -  " if r["offset"] is None else f"{r['offset']:+6.2f}"
            sm = f"{r['smoothed']:+6.2f}" if "smoothed" in r else "      "
            f.write(f"#{r['k']:<5} {timecode.fmt_ass_time(r['time']).split('.')[0]}  {r['lines']:>3}  {off}  {sm}"
                    f"{'  OUT' if r['out'] else '     '}  {r['text'][:50]}\n")
    return {"rows": rows, "runs": runs, "fixed": fixed, "summary": summary, "report": folder / "alignment.txt"}


def analyze_backup(path):
    """film.en.aligned.srt -> film.en.aligned.srt.bak (or .bak2, ...), copied."""
    n, dest = 1, Path(str(path) + ".bak")
    while dest.exists():
        n += 1
        dest = Path(f"{path}.bak{n}")
    shutil.copy2(path, dest)
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("srt", help="the subtitles the notes are placed on")
    ap.add_argument("notes", nargs="?", help="notes file (default: the video's, as context_notes.py finds it)")
    ap.add_argument("--original-subs", metavar="SRT",
                    help="for subtitles not in the spoken language: the original-language subtitles to measure through")
    ap.add_argument("--film-language", metavar="LANG", help="language spoken (default: the notes file's, else en)")
    ap.add_argument("--window", type=float, default=10.0, help="seconds before each note to look at (default 10)")
    ap.add_argument("--no-transcribe", action="store_true",
                    help="only use a transcript made earlier; stop if there isn't one")
    ap.add_argument("--model", help="speech model for transcribing (default: base.en, or small for other languages)")
    ap.add_argument("--limit", type=timecode.duration_arg, metavar="TIME", help="only the first part, e.g. 20:00")
    ap.add_argument("--fix", action="store_true",
                    help="write <subtitles>.aligned.srt (in the video's context-notes folder) with the out-of-step "
                         "stretches moved (original untouched)")
    a = ap.parse_args(argv)
    video, srt = Path(a.video), Path(a.srt)
    for p in (video, srt) + ((Path(a.original_subs),) if a.original_subs else ()):
        if not p.exists():
            sys.exit(f"Can't find {p}")
    if a.notes:
        notes = Path(a.notes)
    else:
        import context_notes
        notes = context_notes.notes_path_for(video, srt)
    if not notes.exists():
        sys.exit(f"Can't find the notes file {notes.name}. Give it as the third argument.")
    if a.window <= 0:
        sys.exit("--window must be more than 0 seconds.")
    print(f"Checking {notes.name} against {video.name}...")
    res = run_check(video, srt, notes, a.original_subs, a.film_language, a.window, not a.no_transcribe, a.model, a.limit,
                    a.fix)
    print("\n".join(res["summary"]))
    print(f"Note-by-note -> {res['report']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
