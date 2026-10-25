#!/usr/bin/env python3
"""
context_notes.py - the whole workflow, for one video or a folder of them.

    python3 context_notes.py "S01E03 Fifty Fifty.mp4"
    python3 context_notes.py "/Volumes/Media/TV Shows/IT Crowd/Season 1"
    python3 context_notes.py "Season 1" --status               what's done and what's left; runs nothing
    python3 context_notes.py film.mkv --limit 5:00             try it on the first 5 minutes
    python3 context_notes.py film.mkv --film-language fr       a French film (often detected from the audio track)
    python3 context_notes.py "Season 1" --reading-speed 120    notes stay up longer (free: only rebuilds the .ass)

For each video it:
  1. finds the subtitles: an .srt beside the video (film.srt, film.en.srt, ...) or a track inside it;
     for a film not in English, also the original-language subtitles (film.fr.srt, or a track inside).
     None? It looks in Subs/ folders, on OpenSubtitles.com (with a saved login) and, if you say so, writes
     them with speech recognition (find_subs.py)
  2. checks they are in sync with the video (local and free). If the timing drifts, it offers to
     re-time them with speech recognition (analyze.py --align)
  3. has Claude write the notes from the dialogue        (make_ass.py --generate: shows the cost, asks first)
  4. has Claude improve them using the video's frames    (make_ass.py --refine: shows the cost, asks first)
  5. leaves <video>.notes.ass beside the video for VLC
Steps already done are skipped (the notes file records them), so it is safe to stop and run it again. A finished
video whose .ass is out of date (a new look, or the notes file was edited) just has its .ass rebuilt, for free.
Every command is printed before it runs, so you can rerun any single step by hand.
"""
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import analyze  # noqa: E402
import languages  # noqa: E402
import make_ass  # noqa: E402
import prompts  # noqa: E402

SEASON_DIR = re.compile(r"^(season|series|saison|staffel|temporada|stagione|seizoen)\s*\d+$|^s\d{1,2}$", re.I)
DERIVED_SUFFIX = re.compile(r"(\.embedded(\.[a-z]{2})?)?(\.aligned(\.first\d+s)?)?$")
RELEASE_JUNK = re.compile(r"\b(2160p|1080p|720p|480p|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|web|hdtv|dvdrip|"
                          r"x264|x265|h\.?264|h\.?265|hevc|aac|ac3|dts|remux|proper|repack|yts|rarbg)\b.*$", re.I)


# ---------------------------------------------------------------- small helpers
def say(msg=""):
    print(msg, flush=True)


def show_cmd(cmd, cwd=None):
    """How the command looks typed by hand: scripts as "$CN/name.py", files in the video's folder by name only."""
    def short(a):
        a = str(a)
        if a.startswith(str(HERE) + os.sep):
            return '"$CN/' + a[len(str(HERE)) + 1:].replace(os.sep, "/") + '"'
        if cwd and a.startswith(str(cwd) + os.sep) and os.sep not in a[len(str(cwd)) + 1:]:
            a = a[len(str(cwd)) + 1:]
        return shlex.quote(a)
    return "$ " + " ".join(["python3"] + [short(c) for c in cmd[1:]])


def ask(question, choices, default, auto=False, id=None):
    """Ask a one-letter question. `choices` is like {'a': 'align', 's': 'skip'}; returns the chosen key.
    With auto (--yes) or no terminal, takes the default and says so. When a program is answering
    (CONTEXT_NOTES_UI=json, see prompts.py), the question goes to it, tagged with `id`."""
    return prompts.ask(question, choices, default, auto, id)


def covers(have, want):
    """Do notes made with --limit `have` cover a request for `want`? (None means the whole video.)"""
    if have is None:
        return True
    return want is not None and have >= want - 1


def load_notes(path):
    try:
        spec = json.loads(make_ass.read_text(path))
    except (OSError, ValueError):
        return None
    return spec if isinstance(spec, dict) else {"notes": spec}


def guess_title(video, show=None):
    """'Season 1/S01E03 Fifty Fifty.mp4' under 'IT Crowd' -> 'IT Crowd - S01E03 Fifty Fifty'.
    'Romeo.And.Juliet.1968.720p.BluRay.x264.mp4' -> 'Romeo And Juliet 1968'."""
    stem = video.stem
    if " " not in stem and ("." in stem or "_" in stem):
        stem = stem.replace(".", " ").replace("_", " ")
    stem = re.sub(r"[\s\-\[\(]+$", "", RELEASE_JUNK.sub("", stem)).strip() or video.stem
    if show is None:
        parent = video.absolute().parent
        if SEASON_DIR.match(parent.name):
            show = parent.parent.name
        elif analyze_episode_code(stem):
            show = parent.name
    return f"{show} - {stem}" if show and show.lower() not in stem.lower() else stem


def analyze_episode_code(name):
    return re.search(r"(?<![0-9A-Za-z])[sS]?\d{1,2}[eExX]\d{2}(?![0-9A-Za-z])", name) is not None


# ---------------------------------------------------------------- finding files
def find_videos(path, recursive=False):
    if path.is_file():
        return [path]
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in path.glob(pattern)
                  if p.is_file() and p.suffix.lower() in analyze.VIDEO_EXTS and not p.name.startswith("."))


def nfc(name):
    """One spelling for accented names. 'é' can be stored as one character or as 'e' plus an accent mark; macOS
    treats both as the same file, but as text they differ (seen with a downloaded Amélie.2001.mp4)."""
    return unicodedata.normalize("NFC", str(name))


def subtitle_files(video):
    """Subtitle files beside a video: [{path, lang, tags, aligned, embedded}]. Language comes from the file name
    (film.fr.srt, film.French.srt) or, if the name doesn't say, from the text itself."""
    stem, out = nfc(video.stem), []
    for p in sorted(video.parent.glob("*.srt")):
        name = nfc(p.name)
        if name.startswith(".") or not (name == stem + ".srt" or name.startswith(stem + ".")):
            continue
        aligned = re.search(r"\.aligned(\.first(\d+)s)?\.srt$", name)
        base_name = name[:aligned.start()] + ".srt" if aligned else name
        lang, tags = languages.from_filename(base_name, stem)
        if lang is None:
            try:
                lang = languages.guess(" ".join(c["text"] for c in make_ass.parse_srt(p)[:300]))
            except (OSError, ValueError):
                lang = None
        out.append({"path": p, "lang": lang, "tags": tags, "embedded": "embedded" in tags,
                    "aligned": bool(aligned), "aligned_limit": float(aligned.group(2)) if aligned and aligned.group(2)
                    else None, "base": base_name})
    return out


def pick_subtitles(subs, lang, limit=None, accept_unknown=False):
    """The best subtitle file in `lang`: a full-dialogue file you supplied over one pulled out of the video, and its
    re-timed (.aligned) version when there is one that covers `limit`. Returns (path, aligned?) or (None, False).
    accept_unknown: if no file is known to be in `lang`, settle for one whose language can't be told."""
    def usable(s, unknown_ok):
        ok_lang = languages.same(s["lang"], lang) or (unknown_ok and s["lang"] is None)
        return not s["aligned"] and ok_lang and "forced" not in s["tags"]
    plain = [s for s in subs if usable(s, False)] or [s for s in subs if usable(s, accept_unknown)]
    if not plain:
        return None, False
    plain.sort(key=lambda s: (s["embedded"], "sdh" in s["tags"], len(s["path"].name)))
    base = plain[0]["path"]
    for s in subs:
        if s["aligned"] and s["base"] == nfc(base.name) and (s["aligned_limit"] is None or s["aligned_limit"] == limit):
            return s["path"], True
    return base, False


def embedded_text_tracks(video):
    try:
        return [t for t in analyze.subtitle_tracks(video) if t["text"]]
    except SystemExit:
        return []


def audio_language(video):
    try:
        _, astream, _ = analyze.probe(video)
    except SystemExit:
        return None
    return languages.code(((astream or {}).get("tags") or {}).get("language"))


def notes_path_for(video, srt):
    """An existing notes file for this video (by video name, subtitle name, or the aligned subtitle name),
    else notes-<video name>.json beside the video."""
    names = [f"notes-{video.stem}.json"]
    if srt:
        names.append(f"notes-{Path(srt).stem}.json")
        names.append(f"notes-{DERIVED_SUFFIX.sub('', Path(srt).stem)}.json")
    on_disk = {nfc(p.name): p for p in video.parent.glob("notes-*.json")}
    for n in names:
        if nfc(n) in on_disk:
            return on_disk[nfc(n)]
    return video.parent / names[0]


def ass_path_for(video):
    return Path(str(video.with_suffix("")) + ".notes.ass")


# ---------------------------------------------------------------- what's been done
def film_language(video, opts, spec=None):
    """(language spoken, how we know): --film-language, else the notes file, else the audio track's tag, else English."""
    if opts.film_language:
        return languages.code(opts.film_language), "option"
    if spec and spec.get("film_language"):
        return languages.code(spec["film_language"]), "notes"
    tagged = audio_language(video)
    if tagged and tagged != "en" and tagged in languages.LANGUAGES:
        return tagged, "audio"
    return "en", "default"


def ass_look(ass):
    """What a built .ass says it was built with (its "; Look:" line): {"build", "background", "opacity", "wpm"},
    or None for one built before 0.2.0."""
    try:
        with open(ass, encoding="utf-8-sig", errors="replace") as f:
            m = make_ass.LOOK_LINE.search(f.read(2000))
    except OSError:
        return None
    if not m:
        return None
    return {"build": int(m["build"]), "background": m["background"], "wpm": float(m["wpm"]),
            "opacity": float(m["opacity"]) if m["opacity"] else None}


def wanted_look(spec, opts):
    """The look a build would give now: the options given, else the notes file's own, else the defaults."""
    timing = (spec or {}).get("timing")
    saved = timing.get("wpm") if isinstance(timing, dict) else None
    try:
        wpm = float(getattr(opts, "reading_speed", None) or saved or make_ass.DEFAULT_TIMING["wpm"])
    except (TypeError, ValueError):
        wpm = None                                   # a bad value in the notes file: the rebuild says what's wrong
    background = (getattr(opts, "note_background", None) or (spec or {}).get("note_background")
                  or make_ass.DEFAULT_BACKGROUND)
    opacity = getattr(opts, "note_opacity", None)
    if opacity is None:
        opacity = (spec or {}).get("note_opacity", make_ass.DEFAULT_OPACITY)
    try:
        opacity = float(opacity)
    except (TypeError, ValueError):
        opacity = None
    return {"build": make_ass.BUILD, "background": background, "wpm": wpm, "opacity": opacity}


def ass_current(ass, notes, spec, opts):
    """Is the .ass newer than the notes, and built the way it would be built now?"""
    if not (ass.exists() and notes.exists() and ass.stat().st_mtime >= notes.stat().st_mtime):
        return False
    have, want = ass_look(ass), wanted_look(spec, opts)
    if have is None or want["wpm"] is None or have["build"] < want["build"] or have["background"] != want["background"]:
        return False
    if want["background"] == "see-through" and (want["opacity"] is None or have["opacity"] is None
                                                 or abs(have["opacity"] - want["opacity"]) > 0.05):
        return False
    return abs(have["wpm"] - want["wpm"]) < 0.05


def inspect(video, opts):
    subs = subtitle_files(video)
    film, how = film_language(video, opts)
    display = opts.subs_language or film
    srt, aligned = pick_subtitles(subs, display, opts.limit, accept_unknown=True)
    notes = notes_path_for(video, srt)
    spec = load_notes(notes) if notes.exists() else None
    if spec and spec.get("film_language") and how == "default":
        film, how = film_language(video, opts, spec)
    have = len(spec.get("notes", [])) if spec else 0
    refined = (spec or {}).get("refined")
    ass = ass_path_for(video)
    st = {"video": video, "subs": subs, "srt": srt, "aligned": aligned, "notes": notes, "spec": spec, "have": have,
          "film_language": film, "film_language_from": how, "ass": ass, "display_lang": display}
    st["notes_ok"] = have > 0 and covers((spec or {}).get("limit"), opts.limit) and not opts.redo
    st["refined_ok"] = (bool(refined) and not refined.get("stopped_after")       # a refine that stopped part-way
                        and covers((refined or {}).get("limit"), opts.limit) and st["notes_ok"])   # isn't finished
    st["ass_ok"] = ass_current(ass, notes, spec, opts)
    st["done"] = st["notes_ok"] and st["ass_ok"] and (st["refined_ok"] or opts.no_refine)
    # only the .ass is behind: a free rebuild, no Claude
    st["rebuild"] = st["notes_ok"] and (st["refined_ok"] or opts.no_refine) and not st["ass_ok"]
    return st


def found_elsewhere(subs):
    """'Casablanca.1942.srt (looks Portuguese)' for subtitle files in other languages."""
    return ", ".join(f"{s['path'].name} ({'looks ' + languages.name(s['lang']) if s['lang'] else 'language unclear'})"
                     for s in subs if not s["aligned"])


def no_subtitles_message(video, lang):
    others = found_elsewhere(subtitle_files(video))
    name = languages.name(lang)
    msg = f"No {name} subtitles for {video.name}."
    if others:
        msg += (f" Found {others}, but this is treated as a film in {name}, so its notes need {name} subtitles."
                f"\n  Put {name} subtitles beside it as {video.stem}.{lang}.srt (the other file can stay)."
                f"\n  If the film really is in another language, add --film-language with that code (e.g. pt).")
    else:
        msg += f" Put them beside it as {video.stem}.srt or {video.stem}.{lang}.srt (none inside the video either)."
    return msg


def status_fields(st):
    """What --status shows about one video, as data for a GUI (the `status` event)."""
    spec = st["spec"] or {}
    refined = spec.get("refined") or {}
    return {"path": str(st["video"]), "name": st["video"].name, "done": st["done"],
            "subtitles": st["srt"].name if st["srt"] else None, "film_language": st["film_language"],
            "notes": st["have"], "limit": spec.get("limit"),
            "notes_stopped": st["notes"].with_suffix(".partial.json").exists(),
            "refined": "stopped" if refined.get("stopped_after") else ("yes" if refined else "no"),
            "ass": st["ass"].name if st["ass"].exists() else None, "rebuild": st["rebuild"]}


def status_line(st):
    subs = st["srt"].name if st["srt"] else "no .srt (will look inside the video)"
    if not st["srt"] and found_elsewhere(st["subs"]):
        subs = f"none in {languages.name(st['display_lang'])}; found {found_elsewhere(st['subs'])}"
    if st["have"]:
        lim = (st["spec"] or {}).get("limit")
        notes = f"{st['have']} notes" + (f" (first {make_ass.fmt_limit(lim)})" if lim else "")
        refined = (st["spec"] or {}).get("refined")
        notes += ((", refine stopped part-way" if refined.get("stopped_after") else ", refined") if refined
                  else ", not refined")
    else:
        notes = "no notes yet"
    if st["rebuild"]:
        notes += f"; {st['ass'].name if st['ass'].exists() else 'the .ass'} needs rebuilding (free)"
    state = "done" if st["done"] else "to do"
    return f"  [{state:>5}] {st['video'].name}\n          subtitles: {subs}; {notes}"


# ---------------------------------------------------------------- running the scripts
class Stop(Exception):
    """This video can't go further (missing files, or you said no)."""


def run(cmd, cwd):
    say(show_cmd(cmd, cwd))
    with subprocess.Popen(cmd, cwd=cwd) as p:
        try:
            return p.wait()
        except KeyboardInterrupt:
            # Ctrl-C (or a GUI's Cancel) reaches the running step too. Give it time to keep what it can (notes
            # already paid for) and tidy up, rather than the quarter of a second Python allows by default.
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
            raise


def script(name, *args):
    return [sys.executable, str(HERE / name), *[str(a) for a in args]]


def common_api_args(opts):
    out = []
    for flag, value in (("--model", opts.model), ("--audience", opts.audience), ("--notes-language", opts.notes_language),
                        ("--api-url", opts.api_url), ("--api-key-file", opts.api_key_file),
                        ("--effort", getattr(opts, "effort", None))):
        if value:
            out += [flag, value]
    if opts.yes:
        out.append("--yes")
    return out


def limit_args(opts):
    return ["--limit", f"{opts.limit:g}"] if opts.limit else []


def rebuild_subtitles(st, opts):
    """The subtitles a finished video's notes were placed on, for a rebuild: what inspect() found, else (a film not
    in English) the other language's, as process() falls back to when writing the notes."""
    if st["srt"] or st["film_language"] == "en":
        return st["srt"]
    other = "en" if languages.same(st["display_lang"], st["film_language"]) else st["film_language"]
    return pick_subtitles(st["subs"], other, opts.limit)[0]


def look_args(opts):
    """How the notes look on screen. Given to every build, which remembers them in the notes file."""
    out = []
    if getattr(opts, "reading_speed", None):
        out += ["--reading-speed", f"{opts.reading_speed:g}"]
    if getattr(opts, "note_background", None):
        out += ["--note-background", opts.note_background]
    if getattr(opts, "note_opacity", None) is not None:
        out += ["--note-opacity", f"{opts.note_opacity:g}"]
    return out


def get_subtitles(video, lang, opts, required=True, accept_unknown=False):
    """An .srt in `lang` for this video, pulling it out of the video if that's where it is."""
    st_subs = subtitle_files(video)
    srt, aligned = pick_subtitles(st_subs, lang, opts.limit, accept_unknown)
    if srt:
        return srt, aligned
    tracks = [t for t in embedded_text_tracks(video) if languages.same(t["lang"], lang)]
    if not tracks:
        if required:
            raise Stop(f"No {languages.name(lang)} subtitles: no {video.stem}.srt (or .{lang}.srt) beside it and no "
                       f"{languages.name(lang)} text track inside it.")
        return None, False
    say(f"Pulling the {languages.name(lang)} subtitles out of the video...")
    if run(script("analyze.py", video, "--sub-lang", lang), video.parent):
        raise Stop("Couldn't extract the subtitles.")
    srt, aligned = pick_subtitles(subtitle_files(video), lang, opts.limit)
    if not srt:
        raise Stop("Extraction ran but no subtitle file appeared.")
    return srt, aligned


def look_further(video, lang, opts, film=None):
    """No subtitles beside the video or inside it: try Subs/ folders and similar names, OpenSubtitles.com (if a
    login is saved) and speech recognition (find_subs.py). Returns the .srt now beside the video, or None."""
    import find_subs
    say(f"No {languages.name(lang)} subtitles beside the video or inside it; looking further...")
    try:
        return _look_further(video, lang, opts, find_subs, film)
    except Stop:
        raise
    except (SystemExit, Exception) as e:        # one video's search must not stop a whole folder
        say(f"  ! Looking for subtitles failed: {e}")
        return None


def _look_further(video, lang, opts, find_subs, film=None):
    # Speech recognition writes what is SAID, so it can only make subtitles in the film's own language.
    can_transcribe = film is None or languages.same(lang, film)

    def ask_yes(q):
        return ask(q, {"y": "yes", "n": "no"}, "y", opts.yes, id="subs.download")

    def ask_no(q):                    # transcribing a whole film is slow: only when asked for, never by --yes
        return ask(q, {"y": "yes", "n": "no"}, "n", opts.yes, id="subs.transcribe")
    got = find_subs.find(video, lang, online=False if opts.offline else None,
                         transcribe=None if can_transcribe else False,
                         ask=lambda q: (ask_no if "speech recognition" in q else ask_yes)(q),
                         model=opts.align_model, limit=opts.limit)
    if got:
        say(f"Using {got.name}.")
    return got


def report_shift_file(video):
    """The corrected subtitle file the last analyze.py --shift auto wrote, if any ('' if none)."""
    try:
        report = json.loads((video.parent / f"{video.stem} analysis" / "analysis.json").read_text(encoding="utf-8"))
        return (report.get("shift") or {}).get("file", "")
    except (OSError, ValueError):
        return ""


def sync_original(video, original, opts):
    """Second subtitle files (the original language Claude compares against, or the ones shown on screen with
    --show-subs) must be in step too. Fixes a constant offset; warns about drift. Returns the file to use."""
    say(f"Checking the timing of {original.name} too...")
    if run(script("analyze.py", original, "--video", video, "--frames", "none", "--shift", "auto", *limit_args(opts)),
           video.parent):
        return original
    fixed = report_shift_file(video)
    if fixed and (video.parent / fixed).exists():
        say(f"Using {fixed} (shifted to match the video).")
        return video.parent / fixed
    try:
        sync = json.loads((video.parent / f"{video.stem} analysis" / "analysis.json").read_text(encoding="utf-8"))["sync"]
        if sync_decision(sync) == "align":
            say(f"  ! {original.name} drifts against this video, so fewer of its lines will line up. "
                f"analyze.py --align --film-language ... can re-time it.")
    except (OSError, ValueError, KeyError):
        pass
    return original


def match_timing(video, shown, main, notes, opts):
    """Line up subtitles that will only be SHOWN with the main subtitles the notes are placed on, which are
    already in step with the video. Compares the two subtitle files directly (instant, and much more reliable
    than the soundtrack); falls back to the soundtrack if they don't resemble each other."""
    spec = load_notes(notes) if notes.exists() else None
    main_offset = float((spec or {}).get("video_offset", 0) or 0)
    off, strength, corr = analyze.subtitle_offset(make_ass.parse_srt(shown), make_ass.parse_srt(main))
    if strength < 1.3 or corr < 0.4:
        say(f"{shown.name} and {main.name} don't line up clearly, so checking {shown.name} against the soundtrack.")
        return sync_original(video, shown, opts)
    off = round(off + main_offset, 1)
    if abs(off) < 0.5:              # different subtitlers time lines a few tenths apart; that's in step
        say(f"{shown.name} is in step with {main.name} (within {abs(off):.1f} s).")
        return shown
    say(f"{shown.name} is {abs(off):.1f} s {'early' if off > 0 else 'late'} compared with {main.name}; fixing that.")
    if run(script("analyze.py", shown, "--shift", f"{off:+.1f}"), video.parent):
        return shown
    fixed = analyze.aligned_path(shown)
    return fixed if fixed.exists() else shown


def sync_decision(sync):
    """'ok', 'offset' (constant, measured), 'align' (drifts or different cut) or 'unknown' (couldn't measure)."""
    if "--align" in (sync.get("verdict") or ""):
        return "align"
    if sync.get("offset") is None:
        return "unknown"
    return "ok" if abs(sync["offset"]) < 0.25 else "offset"


def have_whisper():
    try:
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


def check_sync(video, srt, film, display_lang, embedded, opts):
    """Local sync check; may re-time the subtitles. Returns (srt to use, assume_synced, offset or None)."""
    say("Checking the subtitles against the soundtrack (local, free)...")
    if run(script("analyze.py", srt, "--video", video, "--frames", "none", "--shift", "auto", *limit_args(opts)),
           video.parent):
        raise Stop("The sync check failed.")
    try:
        sync = json.loads((video.parent / f"{video.stem} analysis" / "analysis.json").read_text(encoding="utf-8"))["sync"]
    except (OSError, ValueError, KeyError):
        raise Stop("The sync check didn't leave a report to read.")
    decision = sync_decision(sync)
    if decision == "ok":
        return srt, False, 0.0
    if decision == "offset":
        fixed = video.parent / report_shift_file(video)
        if not fixed.name or not fixed.exists():
            raise Stop("The timing could be fixed with a constant shift, but no corrected file was written.")
        say(f"Fixed the timing: {fixed.name} is {srt.name} shifted {sync['offset']:+.2f} s (your original is untouched).")
        return fixed, True, 0.0
    if decision == "unknown":
        if embedded:
            say("Couldn't measure the sync, but these subtitles came from inside the video, so they should be in step.")
            return srt, True, None
        yes = ask("Couldn't measure the sync (not enough clear dialogue). Treat the subtitles as in sync?",
                  {"y": "yes, treat as in sync", "n": "no, refine will only add on-screen notes"}, "y", opts.yes,
                  id="sync.unmeasured")
        return srt, yes == "y", None

    # The timing drifts, or the subtitles are from a different cut.
    can_align = languages.same(display_lang, film or "en")
    choices = {}
    if can_align:
        choices["a"] = "re-time them with speech recognition (local, free, slow)"
    choices["c"] = "carry on (notes about dialogue may be mistimed; refine adds on-screen notes only)"
    choices["s"] = "skip this video"
    if not can_align:
        say(f"  (Re-timing needs subtitles in the language being spoken; these are {languages.name(display_lang)} "
            f"and the film is in {languages.name(film)}. Look for subtitles made for this exact release.)")
    elif not have_whisper():
        say("  (Re-timing needs faster-whisper:  pip3 install -r requirements.txt)")
        del choices["a"]
    default = "a" if "a" in choices else "c"
    pick = ask("The subtitle timing doesn't match this video all the way through. What now?", choices, default, opts.yes,
               id="sync.drift")
    if pick == "s":
        raise Stop("Skipped at your request.")
    if pick == "c":
        return srt, False, None
    cmd = script("analyze.py", srt, "--video", video, "--align", "--frames", "none", *limit_args(opts))
    if film and film != "en":
        cmd += ["--film-language", film]
    if opts.align_model:
        cmd += ["--model", opts.align_model]
    if run(cmd, video.parent):
        raise Stop("Re-timing failed.")
    aligned = analyze.aligned_path(srt, opts.limit if opts.limit else None)
    if not aligned.exists():
        raise Stop(f"Re-timing ran but {aligned.name} wasn't written.")
    kept, total = len(make_ass.parse_srt(aligned)), len(make_ass.limit_cues(make_ass.parse_srt(srt), opts.limit))
    if kept < 0.5 * total:
        rejected = aligned.with_name(aligned.name + ".rejected")
        aligned.replace(rejected)               # out of the way, or the next run would pick it up as the timing
        say(f"  ! Re-timing only placed {kept} of {total} lines (the speech recognition couldn't follow these "
            f"subtitles), so I'm not using it (kept as {rejected.name}). Carrying on with the original timing: "
            f"refine adds on-screen notes only.")
        return srt, False, None
    return aligned, True, 0.0


def alignment_step(video, srt, notes, film, display_lang, original, opts):
    """Check every note against the speech in the seconds before it (align_check.py) and offer to fix stretches
    that are out. Runs when asked (--check-alignment), when a transcript is already cached (then it's quick), or
    when you say yes to the question. Returns the subtitle file to build from (a fixed copy, or `srt`)."""
    import align_check
    if opts.no_alignment_check or not notes.exists():
        return srt
    folder = video.parent / f"{video.stem} analysis"
    cached = align_check.find_transcript(folder, film, opts.limit) if folder.exists() else None
    if not (opts.check_alignment or cached):
        if opts.yes or not prompts.interactive():
            say("(Every note's timing can be checked against the speech: --check-alignment. It transcribes the "
                "soundtrack once, which is slow.)")
            return srt
        if ask("Check every note's timing against the speech? (speech recognition: local, free, slow the first time)",
               {"y": "yes", "n": "no"}, "y", id="alignment.check") == "n":
            return srt
    if not languages.same(display_lang, film) and original is None:
        say(f"(Skipping the alignment check: the {languages.name(display_lang)} subtitles can only be measured through "
            f"{languages.name(film)} ones, and there are none.)")
        return srt
    args = [video, srt, notes, "--window", f"{opts.window:g}", "--film-language", film or "en", *limit_args(opts)]
    if original is not None and not languages.same(display_lang, film):
        args += ["--original-subs", original]
    if opts.align_model:
        args += ["--model", opts.align_model]
    say("Checking every note against the speech before it...")
    prompts.event("step", step="alignment")
    if run(script("align_check.py", *args), video.parent):
        say("  (The alignment check couldn't finish; the notes are built as they are.)")
        return srt
    try:
        runs = json.loads((folder / "alignment.json").read_text(encoding="utf-8"))["stretches"]
    except (OSError, ValueError, KeyError):
        return srt
    if not runs:
        return srt
    if ask(f"Move the {len(runs)} stretch(es) of subtitles that are out to match the speech, and rebuild the notes? "
           "(writes a corrected copy; the original stays)", {"y": "yes", "n": "no"}, "y", opts.yes,
           id="alignment.fix") == "n":
        return srt
    if run(script("align_check.py", *args, "--fix"), video.parent):
        return srt
    fixed = align_check.fixed_path(srt)
    if not fixed.exists():
        return srt
    if run(script("make_ass.py", fixed, notes, "--video", video, *look_args(opts)), video.parent):
        raise Stop("Rebuilding the .ass from the corrected subtitles failed.")
    say(f"Rebuilt {ass_path_for(video).name} from {fixed.name}.")
    return fixed


def original_for(video, film, display_lang, opts):
    """The original-language subtitles for a film watched with translated ones (None if not needed or not found)."""
    if languages.same(display_lang, film):
        return None
    try:
        original, _ = get_subtitles(video, film, opts, required=False)
    except Stop:
        return None
    return original


def process(video, opts):
    st = inspect(video, opts)
    if st["done"] and not opts.show_subs:
        say(f"Already done: notes written{' and refined' if st['refined_ok'] else ''}, {st['ass'].name} is up to date. "
            "(--redo starts over)")
        if opts.check_alignment and st["srt"]:
            alignment_step(video, st["srt"], st["notes"], st["film_language"], st["display_lang"],
                           original_for(video, st["film_language"], st["display_lang"], opts), opts)
        return "done"
    placed_on = rebuild_subtitles(st, opts) if st["rebuild"] else None
    if placed_on and not opts.show_subs and not opts.check_alignment:
        say(f"The notes are done; rebuilding {st['ass'].name} (free: nothing is sent to Claude).")
        say(f"$ cd {shlex.quote(str(video.absolute().parent))}")
        prompts.event("step", step="build")
        if run(script("make_ass.py", placed_on, st["notes"], "--video", video, *look_args(opts)), video.parent):
            raise Stop("Building the .ass failed.")
        say(f"Ready: play {video.name} in VLC; {st['ass'].name} is beside it.")
        return "ready"
    say(f"$ cd {shlex.quote(str(video.absolute().parent))}")
    prompts.event("step", step="subtitles")

    film = st["film_language"]
    foreign = film != "en"
    if st["film_language_from"] == "audio":
        say(f"The audio track is tagged {languages.name(film)}, so I'm treating this as a {languages.name(film)} "
            f"film. (If that's wrong, rerun with --film-language en.)")

    # 1. subtitles. For a film not in English, the default is its own language's subtitles, with notes in English.
    display_lang = opts.subs_language or film
    srt, aligned = get_subtitles(video, display_lang, opts, required=False, accept_unknown=True)
    if srt is None and foreign:
        other = "en" if display_lang == film else film
        srt, aligned = get_subtitles(video, other, opts, required=False)
        if srt:
            say(f"No {languages.name(display_lang)} subtitles, so I'll use the {languages.name(other)} ones.")
            display_lang = other
    if srt is None:
        srt = look_further(video, display_lang, opts, film)
        aligned = False
    if srt is None:
        raise Stop(no_subtitles_message(video, display_lang))
    original = None
    if foreign and display_lang != film:
        original, original_aligned = get_subtitles(video, film, opts, required=False)
        if original:
            if not original_aligned:
                original = sync_original(video, original, opts)
            say(f"Original-language subtitles: {original.name} (Claude compares them with what you'll read).")
        else:
            say(f"No {languages.name(film)} subtitles found, so Claude can't compare the translation with the "
                f"original wording. Add {video.stem}.{film}.srt beside the video for richer notes.")
    if foreign:
        shown_lang = languages.name(opts.show_subs or display_lang)
        say(f"Film language: {languages.name(film)}. Notes written from the {languages.name(display_lang)} "
            f"subtitles, in {opts.notes_language or 'English'}. On screen: {shown_lang} subtitles"
            + ("" if opts.show_subs else " (--show-subs en for English)") + ".")
    say(f"Subtitles: {srt.name}" + (" (re-timed to this video)" if aligned else ""))
    embedded = ".embedded" in srt.name
    notes = notes_path_for(video, srt)
    spec = load_notes(notes) if notes.exists() else None
    have = len((spec or {}).get("notes", []))

    need_generate = opts.redo or not have
    extend = False                               # keep the notes there are and write only the rest
    if have and not opts.redo and not covers(spec.get("limit"), opts.limit):
        lim = make_ass.fmt_limit(spec["limit"])
        want = "the whole video" if not opts.limit else f"the first {make_ass.fmt_limit(opts.limit)}"
        pick = ask(f"{notes.name} only covers the first {lim}. Write notes for {want}? Adding to them keeps these "
                   f"{have} notes and sends only what comes after {lim}; starting again sends everything (the old "
                   f"file is kept as .bak).",
                   {"a": "add the rest", "s": "start again", "n": "no, keep these"}, "a", opts.yes,
                   id="notes.limited")
        need_generate, extend = pick in ("a", "s"), pick == "a"
    refined = (spec or {}).get("refined")
    need_refine = not opts.no_refine and (need_generate or not refined or not covers(refined.get("limit"), opts.limit)
                                          or bool(refined.get("stopped_after")))     # refine_notes asks to pick up

    # 2. sync (only before writing notes: re-timing afterwards could break notes anchored by line number)
    assume_synced, offset = aligned or embedded, None
    if need_generate and not aligned:
        prompts.event("step", step="sync")
        srt, assume_synced, offset = check_sync(video, srt, film, display_lang, embedded, opts)
        notes = notes_path_for(video, srt) if not have else notes

    title = opts.title or guess_title(video, opts.show)
    lang_args = (["--film-language", film] if foreign else []) + (["--original-subs", original] if original else [])

    # Subtitles on screen: by default the ones the notes are written from; --show-subs picks another language
    # (e.g. notes found in the French, English subtitles shown). make_ass.py remembers the choice.
    display_args = []
    if opts.show_subs:
        if languages.same(opts.show_subs, display_lang):
            display_args = ["--display-subs", srt]                  # also switches back from an earlier choice
        else:
            shown, shown_aligned = get_subtitles(video, opts.show_subs, opts)
            if not shown_aligned:
                shown = match_timing(video, shown, srt, notes, opts)
            say(f"On screen: {shown.name} ({languages.name(opts.show_subs)}); the notes stay where they were "
                f"found in {srt.name}.")
            display_args = ["--display-subs", shown]
    lang_args += display_args

    # 3. Claude writes the notes
    if need_generate:
        say(f"Writing the notes for “{title}”...")
        prompts.event("step", step="generate")
        cmd = script("make_ass.py", srt, notes, "--generate", "--video", video, "--title", title,
                     *limit_args(opts), *lang_args, *common_api_args(opts), *look_args(opts))
        if offset:
            cmd += ["--offset", f"{offset:+.2f}"]
        if have:
            cmd.append("--extend" if extend else "--force")
        if run(cmd, video.parent):
            raise Stop("Stopped at the note-writing step (nothing more was sent).")

    # 4. Claude refines them with the video
    if need_refine:
        say("Improving the notes using the video's frames...")
        prompts.event("step", step="refine")
        cmd = script("make_ass.py", srt, notes, "--refine", "--video", video, "--frames", opts.frames,
                     *limit_args(opts), *lang_args, *common_api_args(opts), *look_args(opts))
        if assume_synced:
            cmd.append("--assume-synced")
        if run(cmd, video.parent):
            raise Stop("Stopped at the refine step. The notes written so far are kept, and the .ass is built from them.")

    # 5. make sure the .ass is current
    ass = ass_path_for(video)
    stale = not ass_current(ass, notes, load_notes(notes), opts)
    if not need_generate and not need_refine and (stale or display_args):
        prompts.event("step", step="build")
        if run(script("make_ass.py", srt, notes, "--video", video, *display_args, *look_args(opts)), video.parent):
            raise Stop("Building the .ass failed.")
    alignment_step(video, srt, notes, film, display_lang, original, opts)
    say(f"Ready: play {video.name} in VLC; {ass.name} is beside it.")
    return "ready"


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="a video file, or a folder of them")
    ap.add_argument("--status", action="store_true", help="show what's done and what's left, then stop")
    ap.add_argument("--limit", type=make_ass.duration_arg, metavar="TIME",
                    help="only the first part of each video, e.g. 5:00, 300 or 5m (for testing)")
    ap.add_argument("--film-language", metavar="LANG",
                    help="language spoken in the video: fr, de, es, ... (default: from the audio track's tag, else en)")
    ap.add_argument("--subs-language", metavar="LANG",
                    help="subtitles Claude writes the notes from (default: the film's own language, so a French film's "
                         "notes explain the French). en: work from English subtitles, compared with the original. "
                         "To only change what's SHOWN on screen, use --show-subs")
    ap.add_argument("--show-subs", metavar="LANG",
                    help="subtitles to show on screen, e.g. en: notes found in the French, English subtitles shown. "
                         "No API cost if the notes exist (just rebuilds the .ass); remembered for later runs")
    ap.add_argument("--show", help="show name for the titles Claude sees (default: guessed from the folder names)")
    ap.add_argument("--title", help="full title, for a single video (default: show name + file name)")
    ap.add_argument("--yes", action="store_true",
                    help="don't stop to ask: approve the API costs and take the default answer to every question")
    ap.add_argument("--no-refine", action="store_true", help="skip the (pricier) video-frames step")
    ap.add_argument("--redo", action="store_true", help="write the notes again even if they exist (old ones kept as .bak)")
    ap.add_argument("--recursive", action="store_true", help="with a folder: include subfolders")
    ap.add_argument("--frames", choices=("keyframes", "dense"), default="keyframes", help="for the refine step")
    ap.add_argument("--model", help="Claude model (default: claude-sonnet-5-5)")
    ap.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"),
                    help="the model's effort setting (default: the model's own default; Haiku 4.5 doesn't support it)")
    ap.add_argument("--audience", help="who the notes are for")
    ap.add_argument("--notes-language", help="language to write the notes in (default: English)")
    ap.add_argument("--check-alignment", action="store_true",
                    help="check every note against the speech in the seconds before it, and offer to fix stretches "
                         "that are out (transcribes the soundtrack once; also works on videos already done)")
    ap.add_argument("--no-alignment-check", action="store_true", help="don't check or ask about it")
    ap.add_argument("--window", type=float, default=10.0,
                    help="for the alignment check: seconds before each note to look at (default 10)")
    ap.add_argument("--offline", action="store_true",
                    help="when a video has no subtitles, don't search OpenSubtitles.com for them")
    ap.add_argument("--align-model", help="speech model for re-timing (default: base.en, or small for other languages)")
    look = ap.add_argument_group("how the notes look (free to change later: the .ass is rebuilt; remembered per video)")
    look.add_argument("--reading-speed", type=float, metavar="WPM",
                      help=f"words a minute each note is timed for (default {make_ass.DEFAULT_TIMING['wpm']:g}, "
                           "0.4 s a word; lower keeps notes up longer)")
    look.add_argument("--note-background", choices=list(make_ass.BACKGROUNDS),
                      help=f"the box behind each note (default {make_ass.DEFAULT_BACKGROUND}; dark is the look "
                           "before 0.2.0; none outlines the text instead)")
    look.add_argument("--note-opacity", type=make_ass.percent_arg, metavar="PERCENT",
                      help=f"how solid the see-through box is, from 0 (invisible) to 100 (solid); default "
                           f"{make_ass.DEFAULT_OPACITY}")
    ap.add_argument("--api-key-file", help=argparse.SUPPRESS)
    ap.add_argument("--api-url", help=argparse.SUPPRESS)
    opts = ap.parse_args(argv)
    if opts.reading_speed is not None and opts.reading_speed <= 0:
        ap.error("--reading-speed is words a minute, a number above 0 (the default, 150, is 0.4 s a word)")
    opts.subs_language = languages.code(opts.subs_language) if opts.subs_language else None
    opts.show_subs = languages.code(opts.show_subs) if opts.show_subs else None

    # absolute (steps run with the video folder as cwd), but NOT resolved: a symlinked video keeps its own name and
    # folder, so its subtitles and notes are looked for beside the link, not beside the file it points to
    path = Path(os.path.abspath(Path(opts.path).expanduser()))
    if not path.exists():
        sys.exit(f"Can't find {path}")
    videos = find_videos(path, opts.recursive)
    if not videos:
        sys.exit(f"No video files in {path}" + ("" if opts.recursive else " (subfolders: add --recursive)"))
    if opts.title and len(videos) > 1:
        sys.exit("--title is for a single video. For a folder, use --show and the file names do the rest.")

    say(f"{len(videos)} video(s)" + (f", first {make_ass.fmt_limit(opts.limit)} of each" if opts.limit else "") + ":")
    for v in videos:
        st = inspect(v, opts)
        say(status_line(st))
        prompts.event("status", **status_fields(st))
    if opts.status:
        return 0
    if not all(st["done"] or st["rebuild"] for st in (inspect(v, opts) for v in videos)):    # a rebuild needs no key
        import generate_notes
        try:
            generate_notes.load_key(opts.api_key_file)          # stop now, not after minutes of local work
        except SystemExit as e:
            sys.exit(str(e))

    say(f'\n$ CN={shlex.quote(str(HERE))}')
    results = {}
    try:
        for k, v in enumerate(videos, 1):
            say(f"\n=== {v.name}" + (f"  ({k} of {len(videos)})" if len(videos) > 1 else "") + " ===")
            prompts.event("video", path=str(v), index=k, total=len(videos))
            try:
                results[v] = process(v, opts)
            except Stop as e:
                say(f"! {e}")
                results[v] = "stopped"
                prompts.event("video-result", path=str(v), result="stopped", reason=str(e))
                if k < len(videos) and ask("Go on to the next video?", {"y": "yes", "n": "no, stop here"}, "y",
                                           opts.yes, id="folder.next") == "n":
                    break
            else:
                prompts.event("video-result", path=str(v), result=results[v])
    except KeyboardInterrupt:
        say("\nStopped. Rerun the same command to pick up where this left off.")
        return 130
    if len(videos) > 1:
        say("\nSummary:")
        for v in videos:
            say(f"  {results.get(v, 'not reached'):>11}  {v.name}")
    return 0 if all(r in ("done", "ready") for r in results.values()) and len(results) == len(videos) else 1


if __name__ == "__main__":
    sys.exit(main())
