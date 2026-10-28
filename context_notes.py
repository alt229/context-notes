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
  6. with --embed: also puts the notes inside an .mkv as a subtitle track (embed.py; .mp4 files stay as they are)
Working files (the notes file, re-timed subtitles, reports, frames) go in context-notes/<video file name>/ beside
the video (see workfiles.py). Files earlier versions left beside the video still work; tidy.py moves them in.
Steps already done are skipped (the notes file records them), so it is safe to stop and run it again. A finished
video whose .ass is out of date (a new look, or the notes file was edited) just has its .ass rebuilt, for free.
Every command is printed before it runs, so you can rerun any single step by hand.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import analyze  # noqa: E402
import cli_common  # noqa: E402  (the options context_notes.py and make_ass.py share)
import fileio  # noqa: E402
import subtitles  # noqa: E402
import timecode  # noqa: E402
import embed  # noqa: E402  (whether a film's notes are inside its .mkv: --preview-rebuild)
import languages  # noqa: E402
import make_ass  # noqa: E402
import prompts  # noqa: E402
import settings  # noqa: E402  (this install's defaults: applied to the flags left out below)
import workfiles  # noqa: E402

SEASON_DIR = re.compile(r"^(season|series|saison|staffel|temporada|stagione|seizoen)\s*\d+$|^s\d{1,2}$", re.I)
DERIVED_SUFFIX = workfiles.DERIVED_SUFFIX
RELEASE_JUNK = re.compile(r"\b(2160p|1080p|720p|480p|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|web|hdtv|dvdrip|"
                          r"x264|x265|h\.?264|h\.?265|hevc|aac|ac3|dts|remux|proper|repack|yts|rarbg)\b.*$", re.I)


# ---------------------------------------------------------------- small helpers
def say(msg=""):
    print(msg, flush=True)


def show_cmd(cmd, cwd=None):
    """How the command looks typed by hand: scripts as "$CN/name.py", files in the video's folder (and its
    context-notes folder) relative to it."""
    def short(a):
        a = str(a)
        if a.startswith(str(HERE) + os.sep):
            return '"$CN/' + a[len(str(HERE)) + 1:].replace(os.sep, "/") + '"'
        if cwd and a.startswith(str(cwd) + os.sep):
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
        spec = json.loads(fileio.read_text(path))
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
                  if p.is_file() and p.suffix.lower() in analyze.VIDEO_EXTS and not p.name.startswith(".")
                  and workfiles.FOLDER not in p.relative_to(path).parts)


nfc = workfiles.nfc


def subtitle_files(video):
    """Subtitle files for a video, beside it or in its working folder (pulled out of it, re-timed):
    [{path, lang, tags, aligned, embedded}]. Language comes from the file name (film.fr.srt, film.French.srt) or,
    if the name doesn't say, from the text itself. A name in both places is the working folder's copy."""
    stem, out, found = nfc(video.stem), [], {}
    for d in workfiles.subtitle_dirs(video):
        for p in sorted(d.glob("*.srt")) if d.is_dir() else []:
            found.setdefault(nfc(p.name), p)
    for name, p in sorted(found.items()):
        if name.startswith(".") or not (name == stem + ".srt" or name.startswith(stem + ".")):
            continue
        aligned = re.search(r"\.aligned(\.first(\d+)s)?\.srt$", name)
        base_name = name[:aligned.start()] + ".srt" if aligned else name
        lang, tags = languages.from_filename(base_name, stem)
        if lang is None:
            try:
                lang = languages.guess(" ".join(c["text"] for c in subtitles.parse_srt(p)[:300]))
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
    else notes-<video name>.json in its working folder (context-notes/<video>/)."""
    return workfiles.notes_path(video, srt)


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


def shown_language(spec, subs):
    """The language of the subtitles a finished film's .ass shows at the bottom: those in the notes file's
    "display_subtitles", else the ones the notes are placed on ("subtitles"). None if it can't be told."""
    name = (spec or {}).get("display_subtitles") or (spec or {}).get("subtitles")
    if not name:
        return None
    return next((s["lang"] for s in subs if nfc(s["path"].name) == nfc(name)), None)


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
    # parts whose replies couldn't be read: their lines have no notes until they're sent again (asked about)
    st["unreadable"] = len((spec or {}).get("unreadable") or []) if st["notes_ok"] else 0
    st["refined_ok"] = (bool(refined) and not refined.get("stopped_after")       # a refine that stopped part-way
                        and not refined.get("unreadable")                         # or has stretches to send again
                        and covers((refined or {}).get("limit"), opts.limit) and st["notes_ok"])   # isn't finished
    st["ass_ok"] = ass_current(ass, notes, spec, opts)
    # --show-subs asks for subtitles in another language at the bottom than the .ass shows: a rebuild
    want = getattr(opts, "show_subs", None)
    shown = shown_language(spec, subs) if want and spec else None
    st["show_change"] = want if shown is not None and not languages.same(shown, want) else None
    st["done"] = (st["notes_ok"] and st["ass_ok"] and (st["refined_ok"] or opts.no_refine) and not st["unreadable"]
                  and not st["show_change"])
    # only the .ass is behind: a free rebuild, no Claude
    st["rebuild"] = (st["notes_ok"] and (st["refined_ok"] or opts.no_refine) and not st["unreadable"]
                     and (not st["ass_ok"] or st["show_change"]))
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


def status_fields(st, tidy=0):
    """What --status shows about one video, as data for a GUI (the `status` event). `tidy`: how many files an
    earlier version left beside it (tidy.py moves them into its working folder)."""
    spec = st["spec"] or {}
    refined = spec.get("refined") or {}
    return {"path": str(st["video"]), "name": st["video"].name, "done": st["done"],
            "subtitles": st["srt"].name if st["srt"] else None, "film_language": st["film_language"],
            "notes": st["have"], "limit": spec.get("limit"),
            "notes_stopped": st["notes"].with_suffix(".partial.json").exists(),
            "refined": "stopped" if refined.get("stopped_after") else ("yes" if refined else "no"),
            "ass": st["ass"].name if st["ass"].exists() else None, "rebuild": st["rebuild"],
            "unreadable": st["unreadable"], "refine_unreadable": len(refined.get("unreadable") or []), "tidy": tidy}


def status_line(st):
    subs = st["srt"].name if st["srt"] else "no .srt (will look inside the video)"
    if not st["srt"] and found_elsewhere(st["subs"]):
        subs = f"none in {languages.name(st['display_lang'])}; found {found_elsewhere(st['subs'])}"
    if st["have"]:
        lim = (st["spec"] or {}).get("limit")
        notes = f"{st['have']} notes" + (f" (first {timecode.fmt_limit(lim)})" if lim else "")
        refined = (st["spec"] or {}).get("refined")
        notes += ((", refine stopped part-way" if refined.get("stopped_after") else ", refined") if refined
                  else ", not refined")
        if refined and refined.get("unreadable"):
            notes += (f" ({len(refined['unreadable'])} stretch(es) of frames came back unreadable; the next run offers "
                      f"to send just those again)")
    else:
        notes = "no notes yet"
    if st["unreadable"]:
        notes += f"; {st['unreadable']} part(s) came back unreadable (the next run offers to send just those again)"
    if st["rebuild"]:
        notes += f"; {st['ass'].name if st['ass'].exists() else 'the .ass'} needs rebuilding (free)"
        if st["show_change"]:
            notes += f" to show the {languages.name(st['show_change'])} subtitles"
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


def check_route(opts):
    """Before any work: can Claude be reached the way this run is set to? On the plan, Claude Code must be usable;
    when it isn't, use API credits within --api-fallback (each step then moves to them itself, within that
    allowance for the whole run), or ask once (or stop, when nobody can be asked). On the API, the key must be
    there."""
    import claude_api
    import usage
    usage.run_start()                                      # the allowance counts from here, for every step
    if opts.route == "plan":
        import claude_code
        problem = claude_code.problem()
        if problem:
            say(f"Claude Code can't be used here, so the notes can't go on your Claude plan: {problem}")
            if opts.api_fallback > 0:
                say(f"The steps will use API credits instead, up to {usage.money(opts.api_fallback)} for this run "
                    f"(--api-fallback, or Settings, Claude).")
            elif opts.yes or not prompts.interactive():
                sys.exit("Stopped before any work. Fix Claude Code (above), or allow API credits for when the plan "
                         "can't be used: Settings, Claude, or --api-fallback 5 (or --route api).")
            elif prompts.confirm(f"Claude Code can't be used here, so the notes can't go on your Claude plan: {problem} "
                                 f"Use API credits for this run instead? Each step shows what it would cost first.",
                                 id="plan.fallback"):
                opts.route = "api"
            else:
                sys.exit("Stopped before any work; nothing was sent.")
        else:
            if opts.api_fallback > 0:                      # allowed, but only works with a key: say so now
                try:
                    claude_api.load_key(opts.api_key_file)
                except SystemExit:
                    say(f"(API credits are allowed if the plan runs out, up to {usage.money(opts.api_fallback)}, but "
                        f"no API key is saved; without one, the run stops there instead.)")
            return                                         # on the plan: no API key needed
    try:
        claude_api.load_key(opts.api_key_file)
    except SystemExit as e:
        sys.exit(str(e))


def script(name, *args):
    return [sys.executable, str(HERE / name), *[str(a) for a in args]]


def common_api_args(opts):
    """What the generate and refine steps are given: the Claude options, who the notes are for, and --yes."""
    out = cli_common.claude_args(opts)
    for flag, value in (("--audience", opts.audience), ("--notes-language", opts.notes_language)):
        if value:
            out += [flag, value]
    if opts.yes:
        out.append("--yes")
    return out


limit_args = cli_common.limit_args
look_args = cli_common.look_args


def rebuild_subtitles(st, opts):
    """The subtitles a finished video's notes were placed on, for a rebuild: what inspect() found, else (a film not
    in English) the other language's, as process() falls back to when writing the notes."""
    if st["srt"] or st["film_language"] == "en":
        return st["srt"]
    other = "en" if languages.same(st["display_lang"], st["film_language"]) else st["film_language"]
    return pick_subtitles(st["subs"], other, opts.limit)[0]


def keep_old_ass(video):
    """Before a build rewrites the film's .notes.ass, keep the one there now as <name>.bak (an older backup is never
    overwritten)."""
    ass = ass_path_for(video)
    if ass.exists():
        backup = fileio.unique_backup(ass)
        shutil.copy2(ass, backup)
        say(f"Kept the old subtitles: {backup.name}")


def rebuild_diff(st, opts):
    """What a rebuild would change for one video, for the page to show before anything is written: the look now and
    after, the subtitles, and the files that change beside the film."""
    video, ass, spec = st["video"], st["ass"], st["spec"] or {}
    have, want = ass_look(ass), wanted_look(st["spec"], opts)
    rows = []

    def row(name, now, after):
        rows.append({"setting": name, "now": now, "after": after, "changed": now != after})

    def shown(value, unit=""):
        return "not recorded (made before 0.2.0)" if value is None else f"{value:g}{unit}"

    row("Box behind the notes", have["background"] if have else "not recorded (made before 0.2.0)", want["background"])
    if want["background"] == "see-through":
        row("Box opacity", shown(have and have["opacity"], "% solid"), shown(want["opacity"], "% solid"))
    row("Words a minute", shown(have and have["wpm"]), shown(want["wpm"]))
    after_srt = rebuild_subtitles(st, opts)
    row("Subtitles the notes are placed on", st["srt"].name if st["srt"] else "none",
        after_srt.name if after_srt else "none")
    bottom = spec.get("display_subtitles") or "the same as the notes"
    row("Subtitles at the bottom", bottom, f"{opts.show_subs} (--show-subs)" if opts.show_subs else bottom)
    files = []
    if ass.exists():
        files.append(f"Kept: {fileio.unique_backup(ass).name} (the .notes.ass as it is now)")
    files.append(f"Rebuilt: {ass.name}")
    if ass.name.endswith(".notes.ass"):
        files.append(f"Written beside the film: {ass.name[:-len('.notes.ass')]}.en.ass (the Plex copy, which is "
                     "skipped if a file of that name isn't one of ours)")
    embedded = video.suffix.lower() == ".mkv" and embed.inspect(video)["action"] == "current"
    if embedded:
        files.append(f"Out of date inside {video.name}: its Context Notes track (Embed rewrites the film)")
    return {"video": str(video), "name": video.name, "rows": rows, "files": files, "embedded": embedded}


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

    def ask_yes(q):                   # --download-subs (Settings: always download): yes without asking
        return ask(q, {"y": "yes", "n": "no"}, "y", opts.yes or getattr(opts, "download_subs", False), id="subs.download")

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
    """The corrected subtitle file the last analyze.py --shift auto wrote, if it's there (None if not)."""
    try:
        report = json.loads((workfiles.analysis(video) / "analysis.json").read_text(encoding="utf-8"))
        name = (report.get("shift") or {}).get("file", "")
    except (OSError, ValueError):
        return None
    found = workfiles.find(video, name) if name else None
    return found if found is not None and found.is_file() else None


def sync_original(video, original, opts):
    """Second subtitle files (the original language Claude compares against, or the ones shown on screen with
    --show-subs) must be in step too. Fixes a constant offset; warns about drift. Returns the file to use."""
    say(f"Checking the timing of {original.name} too...")
    if run(script("analyze.py", original, "--video", video, "--frames", "none", "--shift", "auto", *limit_args(opts)),
           video.parent):
        return original
    fixed = report_shift_file(video)
    if fixed:
        say(f"Using {fixed.name} (shifted to match the video).")
        return fixed
    try:
        sync = json.loads((workfiles.analysis(video) / "analysis.json").read_text(encoding="utf-8"))["sync"]
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
    off, strength, corr = analyze.subtitle_offset(subtitles.parse_srt(shown), subtitles.parse_srt(main))
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
        sync = json.loads((workfiles.analysis(video) / "analysis.json").read_text(encoding="utf-8"))["sync"]
    except (OSError, ValueError, KeyError):
        raise Stop("The sync check didn't leave a report to read.")
    decision = sync_decision(sync)
    if decision == "ok":
        return srt, False, 0.0
    if decision == "offset":
        fixed = report_shift_file(video)
        if fixed is None:
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
    aligned = analyze.aligned_path(srt, opts.limit if opts.limit else None, video)
    if not aligned.exists():
        raise Stop(f"Re-timing ran but {aligned.name} wasn't written.")
    kept, total = len(subtitles.parse_srt(aligned)), len(subtitles.limit_cues(subtitles.parse_srt(srt), opts.limit))
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
    folder = workfiles.analysis(video)
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
    fixed = align_check.fixed_path(srt, video)
    if not fixed.exists():
        return srt
    keep_old_ass(video)
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
        keep_old_ass(video)
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
        lim = timecode.fmt_limit(spec["limit"])
        want = "the whole video" if not opts.limit else f"the first {timecode.fmt_limit(opts.limit)}"
        pick = ask(f"{notes.name} only covers the first {lim}. Write notes for {want}? Adding to them keeps these "
                   f"{have} notes and sends only what comes after {lim}; starting again sends everything (the old "
                   f"file is kept as .bak).",
                   {"a": "add the rest", "s": "start again", "n": "no, keep these"}, "a", opts.yes,
                   id="notes.limited")
        need_generate, extend = pick in ("a", "s"), pick == "a"
    refined = (spec or {}).get("refined")
    need_refine = not opts.no_refine and (need_generate or not refined or not covers(refined.get("limit"), opts.limit)
                                          or bool(refined.get("stopped_after"))      # refine_notes asks to pick up
                                          or bool(refined.get("unreadable")))        # ...or to send those again
    unread = (spec or {}).get("unreadable") or []
    retry_only = False                           # send again just the lines whose replies couldn't be read
    if unread and have and not opts.redo and not need_generate:
        where = ", ".join(f"{u['lines'][0]} to {u['lines'][1]}" for u in unread if isinstance(u, dict) and
                          len(u.get("lines") or []) == 2)
        if ask(f"Claude's reply for {len(unread)} part(s) of {notes.name} couldn't be read last time, so lines "
               f"{where} have no notes. Send just those lines again?",
               {"y": "yes, send just those lines", "n": "no, not now"}, "y", opts.yes, id="notes.unreadable") == "y":
            need_generate, extend, retry_only = True, True, True     # the frames step isn't needed for this

    # 2. sync (only before writing notes: re-timing afterwards could break notes anchored by line number)
    assume_synced, offset = aligned or embedded, None
    if need_generate and not aligned and not retry_only:
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
        keep_old_ass(video)
        if run(script("make_ass.py", srt, notes, "--video", video, *display_args, *look_args(opts)), video.parent):
            raise Stop("Building the .ass failed.")
    alignment_step(video, srt, notes, film, display_lang, original, opts)
    say(f"Ready: play {video.name} in VLC; {ass.name} is beside it.")
    return "ready"


def embed_step(video, opts):
    """--embed: put the finished notes inside an .mkv (embed.py checks the new file and keeps the original; an .mp4
    can't hold the styled notes, so it stays as it is). True if all is well."""
    if video.suffix.lower() != ".mkv":
        say(f"(--embed: {video.name} stays as it is; only .mkv films can hold the notes for now.)")
        return True
    say("Putting the notes inside the film (no Claude, no cost)...")
    prompts.event("step", step="embed")
    return run(script("embed.py", video, *(["--yes"] if opts.yes else [])), video.parent) == 0


def left_beside(videos):
    """{video: [(file, where it goes)]} for the files earlier versions left beside these videos (tidy.py)."""
    out, folders = {}, {}
    for v in videos:
        folders.setdefault(v.parent, []).append(v)
    for d in folders:
        plan, _ = workfiles.old_files(d)
        out.update({v: moves for v, moves in plan.items() if v in folders[d]})
    return out


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="a video file, or a folder of them")
    ap.add_argument("--status", action="store_true", help="show what's done and what's left, then stop")
    ap.add_argument("--preview-rebuild", action="store_true",
                    help="show what a rebuild would change (the settings now and after, and the files), and change nothing")
    cli_common.add_limit_arg(ap, "only the first part of each video, e.g. 5:00, 300 or 5m (for testing)")
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
    cli_common.add_claude_args(ap, model_default="from Settings, Opus unless changed",
                               effort_default="from Settings, high unless changed")
    ap.add_argument("--audience", help="who the notes are for")
    ap.add_argument("--notes-language", help="language to write the notes in (default: English)")
    ap.add_argument("--check-alignment", action="store_true",
                    help="check every note against the speech in the seconds before it, and offer to fix stretches "
                         "that are out (transcribes the soundtrack once; also works on videos already done)")
    ap.add_argument("--no-alignment-check", action="store_true", help="don't check or ask about it")
    ap.add_argument("--embed", action="store_true",
                    help="when a film's notes are done, also put them inside the .mkv as a subtitle track (embed.py: "
                         "free, checked, the original is kept; .mp4 files stay as they are). Not for --limit runs")
    ap.add_argument("--window", type=float, default=10.0,
                    help="for the alignment check: seconds before each note to look at (default 10)")
    ap.add_argument("--offline", action="store_true",
                    help="when a video has no subtitles, don't search OpenSubtitles.com for them")
    ap.add_argument("--download-subs", action="store_true",
                    help="download the subtitles OpenSubtitles.com finds without asking (each uses one of your daily "
                         "downloads; Settings: \"Always download subtitles\")")
    ap.add_argument("--align-model", help="speech model for re-timing (default: base.en, or small for other languages)")
    look = ap.add_argument_group("how the notes look (free to change later: the .ass is rebuilt; remembered per video)")
    cli_common.add_look_args(look)
    ap.set_defaults(**settings.cli_defaults())      # the flags left out take this install's defaults
    opts = ap.parse_args(argv)
    cli_common.check_look_args(ap, opts)
    cli_common.settle_route(opts)
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

    if opts.preview_rebuild:                  # what a rebuild would change, for the page to show first: nothing is written
        for v in videos:
            st = inspect(v, opts)
            if st["rebuild"]:
                prompts.event("rebuild-diff", **rebuild_diff(st, opts))
        return 0
    say(f"{len(videos)} video(s)" + (f", first {timecode.fmt_limit(opts.limit)} of each" if opts.limit else "") + ":")
    old = left_beside(videos)
    for v in videos:
        st = inspect(v, opts)
        say(status_line(st))
        prompts.event("status", **status_fields(st, len(old.get(v, []))))
    if old:
        say(f"\n{len(old)} of these video(s) still have working files beside them, from an earlier version. They "
            f"work where they are; to move them into the {workfiles.FOLDER} folder:\n"
            f"  python3 {shlex.quote(str(HERE / 'tidy.py'))} {shlex.quote(str(path))}"
            + (" --recursive" if opts.recursive and path.is_dir() else ""))
    if opts.status:
        return 0
    if not all(st["done"] or st["rebuild"] for st in (inspect(v, opts) for v in videos)):    # a rebuild needs no key
        check_route(opts)                                  # stop now, not after minutes of local work

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
                if k < len(videos) and ask(f"{v.name} stopped: {e} Go on to the next video?",
                                           {"y": "yes", "n": "no, stop here"}, "y", opts.yes, id="folder.next") == "n":
                    break
            else:
                if opts.embed and results[v] in ("done", "ready") and not embed_step(v, opts):
                    say(f"! The notes are done, but couldn't be put inside {v.name} (it is as it was).")
                    results[v] = "not embedded"
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
