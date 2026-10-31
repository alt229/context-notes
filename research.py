#!/usr/bin/env python3
"""
research.py - the fact sheet a film's Behind the Scenes notes are written from: what's known about how it was made,
each fact tied to a moment in the film and to the source it came from.

    python3 research.py film.mkv                       look the film up (on your Claude plan, through Claude Code)
    python3 research.py film.mkv --estimate-only       what it would take; nothing is sent
    python3 research.py film.mkv --again               look it up again (the old sheet is kept as a .bak)
    python3 research.py film.mkv --list-audio          the film's audio tracks, numbered, then stop
    python3 research.py film.mkv --commentary 3        use audio track 3 as a commentary
    python3 research.py film.mkv --commentary none     leave the film's commentary tracks out

Where the facts come from:
  1. The film's own commentary tracks, when it has any: an audio track whose title says "commentary" (or the one
     you name with --commentary). Each is transcribed on this computer with faster-whisper (free, but slow), then
     Claude picks out the stories and facts, each timed to when it was said.
     These facts give the track as their source.
  2. The web. Claude searches and reads pages, and keeps only facts it found a source for: interviews, the film's
     own extras, books, reputable articles. On your plan that's Claude Code's WebSearch and WebFetch (and nothing
     else: no files, no commands); with API credits it's the API's web search tool, about 1 cent a search on top.
Each fact says where in the film it belongs, its source, how sure Claude is, and whether it gives away something
that happens later in the film (a spoiler). Real-world facts about the cast and crew never count as spoilers.

The sheet is facts-<video name>.json in the video's working folder (context-notes/<video file name>/). It is saved
after every request, so a run that stops picks up where it left off. make_ass.py --behind-the-scenes writes the
notes from it, and context_notes.py --behind-the-scenes runs this first.
"""
import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

import claude_api
import cli_common
import fileio
import generate_notes as gn
import languages
import prompts  # the questions (and on Windows, lets a GUI's Cancel stop this script cleanly)
import sending
import settings
import timecode
import usage
import workfiles

COMMENTARY_RE = re.compile(r"comment", re.I)
CHUNK_SECONDS = 1800             # a commentary is sent half an hour of film at a time
MIN_FACTS, MAX_FACTS = 15, 120
MINUTES_PER_FACT = 2.5           # what the web search aims for: about one fact every 2.5 minutes of film
WEB_MAX_TOKENS = 16000           # the reply: the whole sheet
COMMENTARY_MAX_TOKENS = 8000
CATEGORIES = ["Behind the scenes", "Stunt", "Injury", "Improvised", "Casting", "Cameo", "Easter egg", "Adaptation",
              "Effects", "Location", "Music", "Design", "Goof", "Myth", "History", "Deleted scene"]

FACT_FORMAT = """[{{"fact": "<what happened or what's true, 1 to 3 sentences>", "scene": "<the moment in the film it \
belongs to>", "line": "<a line spoken there, word for word, if you know it; else empty>", "when": "<h:mm:ss into \
the film, if you know it; else empty>", "category": "<one of: {cats}, or a short label of your own>", "source": \
"<{source}>", "spoiler": false, "confidence": "high" | "medium" | "low"}}]"""

SYSTEM_WEB = """You research a film for its "Behind the Scenes" track: short pop-up notes for fans watching it again, \
like the trivia track on a special-edition DVD. Search the web and read pages, then reply with a fact sheet.

The film: {film}. The viewer's copy runs {runtime}; its file is called "{file}", which may say which cut it is \
(theatrical, extended, director's cut).

Look for what a fan would love to know while watching, each tied to a moment in the film:
- production stories: stunts, injuries and accidents, improvised lines, takes that were kept, reshoots
- casting: who nearly played whom, family and crew in small parts, actors in more than one role
- cameos, easter eggs, in-jokes, nods to other films or to the source
- adaptation: what changed from the book, play or true story; what was invented or left out
- how it was done: effects, make-up, sets, props, costumes, music, and where scenes were really filmed
- goofs worth spotting, and famous stories that turn out to be myths (say so, with the source that shows it)
- the real history behind the story, where it adds something

Rules:
- Every fact needs a source you actually read: an interview, the film's own extras or commentary as reported, a \
book, or a reputable article. Trivia sites, fan wikis and listicles only when another source agrees, and then give \
that other source. If you can't find a source for something you believe, leave it out.
- Never invent quotes, dates, names, numbers or production details. When sources disagree on a detail, say so and \
use "medium" confidence.
- Tie each fact to its moment: describe the scene in a few words, and give a line spoken there if you know it. Leave \
out facts that belong to no moment, unless they suit the opening or the end credits.
- If this copy is a cut with scenes other cuts don't have (extended, director's cut), say so in "scene" for facts \
in those scenes. Skip facts about scenes this cut doesn't have.
- "spoiler": true when the fact, told at its moment, gives away something that happens later in this film (or in a \
sequel, for a series). Facts about the real world, the cast and the crew are never spoilers.
- Aim for about {target} facts, spread through the whole film, in the film's order; more for a famously \
well-documented production, fewer when little is known. Quality first.

When you've finished, reply with the facts only, between <facts> and </facts>, as a JSON array:
{format}"""

SYSTEM_COMMENTARY = """You turn part of a film's audio commentary into a fact sheet for the film's "Behind the \
Scenes" track: short pop-up notes for fans watching it again.

The film: {film}. The commentary track: "{track}". It was transcribed by speech recognition, so names and unusual \
words can be misheard: correct one only when you're sure, otherwise leave the fact out. Each line starts with the \
time in the film when it was said.

Pick out what a fan would enjoy at that moment: how a shot or stunt was done, what went wrong, what was improvised, \
who's who, what changed from the script or the source, in-jokes, cameos, where it was filmed. Skip chit-chat, \
general praise and anything you can't tie to a moment.

Rules:
- Only what the commentary says. Add nothing from elsewhere, and never invent quotes, names or numbers. Say who \
told the story when the speaker is clear ("the director says").
- "when": the time it was said, from the line it starts on (h:mm:ss). If the speaker is clearly talking about a \
different scene, describe that one in "scene" and leave "when" empty.
- "spoiler": true when the fact, told at its moment, gives away something that happens later in this film (or in a \
sequel). Facts about the real world, the cast and the crew are never spoilers.
- "source": "commentary".

Reply with the facts only, between <facts> and </facts>, as a JSON array (or <facts>[]</facts> if this part has \
nothing worth a note):
{format}"""


# ---------------------------------------------------------------- the film
def clean_title(video):
    """A title from the file name when none is given: dots and underscores to spaces (the year stays)."""
    return re.sub(r"\s+", " ", re.sub(r"[._]+", " ", Path(video).stem)).strip()


def target(runtime):
    """How many facts the web search aims for: about one every MINUTES_PER_FACT minutes."""
    return max(MIN_FACTS, min(MAX_FACTS, int(round((runtime or 0) / 60 / MINUTES_PER_FACT))))


def audio_tracks(video):
    """The video's audio tracks, numbered from 1 in file order: [{n, index, title, language, channels, codec}]."""
    import analyze
    info = analyze.ffprobe_json(video, "-show_streams")
    out = []
    for s in info.get("streams") or []:
        if s.get("codec_type") != "audio":
            continue
        tags = s.get("tags") or {}
        out.append({"n": len(out) + 1, "index": s.get("index"), "title": tags.get("title") or tags.get("handler_name")
                    or "", "language": tags.get("language") or "", "channels": s.get("channels"),
                    "codec": s.get("codec_name") or ""})
    return out


def describe(t):
    bits = [t["title"] or "(no title)", t["language"], f"{t['channels']} ch" if t["channels"] else "", t["codec"]]
    return f"track {t['n']}: " + ", ".join(b for b in bits if b)


def commentary_tracks(tracks, wanted="auto"):
    """The tracks to use as commentaries: "auto" those whose title says so, "none" none, or numbers ("3" or "2,3")."""
    if wanted in (None, "", "auto"):
        return [t for t in tracks if COMMENTARY_RE.search(t["title"])]
    if wanted == "none":
        return []
    try:
        numbers = [int(x) for x in str(wanted).replace(" ", "").split(",") if x]
    except ValueError:
        sys.exit(f"--commentary takes auto, none, or audio track numbers like 3 or 2,3 (got {wanted!r}).")
    picked = [t for t in tracks if t["n"] in numbers]
    missing = sorted(set(numbers) - {t["n"] for t in picked})
    if missing:
        sys.exit(f"This video has {len(tracks)} audio track(s), so there's no track {missing[0]}. "
                 f"--list-audio lists them.")
    if any(t["n"] == 1 for t in picked) and len(tracks) > 1:
        print("(Track 1 is usually the film's own soundtrack, not a commentary. Using it as you asked.)")
    return picked


def transcribe_commentary(video, track, model=None):
    """The commentary as [{s, e, t}] (film seconds, text), from faster-whisper; cached in the analysis folder."""
    import analyze
    lang = languages.code(track["language"]) or "en"
    if lang not in languages.LANGUAGES:
        lang = "en"
    name = analyze.whisper_model(lang, model)
    folder = workfiles.make_dirs(workfiles.analysis(video))
    cache = folder / f"commentary-track{track['n']}-{name}.jsonl"
    print(f"Transcribing the commentary ({describe(track)}) with the {name} speech model, on this computer...")
    rows = analyze.transcribe(video, {"channels": 2}, name, cache, language=lang, stream=track["index"])
    return [{"s": r["s"], "e": r["e"], "t": r["t"].strip()} for r in rows if r.get("t", "").strip()]


def commentary_parts(rows, duration):
    """The transcript in CHUNK_SECONDS stretches of film time: [(start, end, [rows])], empty stretches left out."""
    out = []
    t = 0.0
    end = max(duration or 0, max((r["e"] for r in rows), default=0)) + 1
    while t < end:
        part = [r for r in rows if t <= r["s"] < t + CHUNK_SECONDS]
        if part:
            out.append((t, min(t + CHUNK_SECONDS, end), part))
        t += CHUNK_SECONDS
    return out


def commentary_text(film, track, part, k, total):
    lo, hi, rows = part
    lines = [f"[{timecode.hms(r['s'])}] {r['t']}" for r in rows]
    return (f"Film: {film}\nCommentary: {track['title'] or describe(track)}\nPart {k} of {total}: "
            f"{timecode.hms(lo)} to {timecode.hms(hi)} of the film.\n\n" + "\n".join(lines) +
            "\n\nReply with the facts only, between <facts> and </facts>.")


# ---------------------------------------------------------------- reading a reply
TAGGED = re.compile(r"<facts>(.*?)(?:</facts>|\Z)", re.S)


def parse_facts(text):
    """(the fact objects in a reply, whether it could be read). The last <facts>...</facts> block that holds a JSON
    array (an empty one counts: nothing worth a note); without one, the first JSON array of objects in the reply.
    A reply that mentions <facts> after the block (or holds no array at all) isn't taken as an empty answer."""
    for body in reversed(TAGGED.findall(text or "")):
        m = re.search(r"\[\s*(?:\{|\])", body)
        if not m:
            continue
        found = gn.extract_objects(body[m.start():])
        if found or re.match(r"\[\s*\]", body[m.start():]):
            return found, True
    m = re.search(r"\[\s*\{", text or "")
    found = gn.extract_objects(text[m.start():]) if m else []
    return found, bool(found)


def clean_fact(raw, duration=None, source=None):
    """A fact as the sheet keeps it, or None when it has no text. `source`: what to put when it gives none."""
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("fact") or raw.get("text") or "").strip()
    if not text:
        return None
    conf = str(raw.get("confidence") or "high").lower()
    spoiler = raw.get("spoiler")
    if isinstance(spoiler, str):
        spoiler = spoiler.strip().lower() in ("true", "yes", "1")
    fact = {"fact": text[:800], "scene": str(raw.get("scene") or "").strip()[:300],
            "category": str(raw.get("category") or "Behind the scenes").strip()[:40] or "Behind the scenes",
            "source": str(raw.get("source") or source or "").strip()[:500],
            "spoiler": bool(spoiler), "confidence": conf if conf in ("high", "medium", "low") else "medium"}
    line = str(raw.get("line") or "").strip()
    if line:
        fact["line"] = line[:300]
    when = timecode.parse_time(raw.get("when")) if str(raw.get("when") or "").strip() else None
    if when is not None and when >= 0 and (not duration or when <= duration + 1):
        fact["when"] = timecode.hms(when)
    return fact


def fact_lines(facts, ids=None):
    """The facts as the note-writing steps are given them: one line each, with its id."""
    out = []
    for f in facts:
        if ids is not None and f.get("id") not in ids:
            continue
        bits = [f"#{f.get('id')}", f.get("category") or "", f"at {f['when']}" if f.get("when") else "",
                "SPOILER" if f.get("spoiler") else "", f"{f.get('confidence', 'high')} confidence"]
        head = "[" + ", ".join(b for b in bits if b) + "]"
        where = f" Scene: {f['scene']}." if f.get("scene") else ""
        said = f" Line: \"{f['line']}\"." if f.get("line") else ""
        out.append(f"{head} {f['fact']}{where}{said} (Source: {f.get('source') or 'not given'})")
    return out


def load_sheet(path):
    """The fact sheet, or exits saying what's wrong with it."""
    try:
        sheet = json.loads(fileio.read_text(path))
    except OSError:
        sys.exit(f"Can't find the fact sheet {path}. Run  {prompts.PYTHON} research.py <the video>  first.")
    except ValueError:
        sys.exit(f"{Path(path).name} isn't a fact sheet this can read. Run research.py with --again to look the film "
                 f"up again.")
    if not isinstance(sheet, dict) or not isinstance(sheet.get("facts"), list):
        sys.exit(f"{Path(path).name} isn't a fact sheet this can read. Run research.py with --again.")
    return sheet


# ---------------------------------------------------------------- the run
class Researching:
    """A research run in progress: the sheet so far. Saved after every request (with the jobs done), so a run that
    stops picks up where it left off. Used by sending.send_parts (prepare, apply, keep)."""

    def __init__(self, sheet, path, sender, film, duration):
        self.sheet, self.path, self.sender, self.film, self.duration = sheet, path, sender, film, duration
        self.tokens = sending.Tokens()
        self.problems = []

    def prepare(self, job):
        self.sender.system, self.sender.web, self.sender.max_tokens = job["system"], job["web"], job["max_tokens"]
        return job["label"], job["message"]

    def cost_of(self, job):
        """What this job would cost in API credits (for the credit check and the allowance), or None."""
        return estimate_job(job, self.sender.model)[2]

    def apply(self, job, reply):
        text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
        raw, readable = parse_facts(text)
        facts = [f for f in (clean_fact(r, self.duration, job.get("source")) for r in raw) if f]
        if not readable:                         # not done: the next run sends it again
            bad = self.path.with_suffix(f".{job['key'].replace(':', '-')}.failed.txt")
            fileio.write_text_safely(bad, text)
            self.problems.append(f"{job['what']}: couldn't read the reply; saved it to {bad.name}. The next run sends "
                                 f"it again.")
            print("couldn't read the reply")
            self.save()
            return
        if job.get("track"):
            for f in facts:
                f["source"] = f"Commentary: {job['track']}"
        if reply.get("stop_reason") == "max_tokens":
            self.problems.append(f"{job['what']}: the reply was cut off, so some facts may be missing")
        next_id = 1 + max((f.get("id", 0) for f in self.sheet["facts"]), default=0)
        for k, f in enumerate(facts):
            f["id"] = next_id + k
        self.sheet["facts"] += facts
        self.sheet["done"].append(job["key"])
        print(f"{len(facts)} facts")
        self.save()

    def save(self):
        fileio.write_text_safely(self.path, json.dumps(self.sheet, indent=1, ensure_ascii=False) + "\n")

    def keep(self):
        self.save()
        print(f"\n  Stopped. The {len(self.sheet['facts'])} facts found so far are saved in {self.path.name}; the next "
              f"run offers to pick up from there.", flush=True)


def jobs_for(film, video, runtime, tracks, transcripts, file_name):
    """What to send: each commentary in half-hour parts, then the web search."""
    jobs = []
    cats = ", ".join(CATEGORIES)
    for t in tracks:
        parts = commentary_parts(transcripts[t["n"]], runtime)
        title = t["title"] or describe(t)
        system = SYSTEM_COMMENTARY.format(film=film, track=title,
                                          format=FACT_FORMAT.format(cats=cats, source="commentary"))
        for k, part in enumerate(parts, 1):
            jobs.append({"key": f"commentary:{t['n']}:{k}", "web": False, "system": system,
                         "max_tokens": COMMENTARY_MAX_TOKENS, "track": title,
                         "what": f"commentary track {t['n']}, part {k}",
                         "label": f"  commentary track {t['n']}, part {k}/{len(parts)}: "
                                  f"{timecode.hms(part[0])}-{timecode.hms(part[1])} ...",
                         "message": commentary_text(film, t, part, k, len(parts))})
    system = SYSTEM_WEB.format(film=film, runtime=timecode.hms(runtime) if runtime else "an unknown time",
                               file=file_name, target=target(runtime),
                               format=FACT_FORMAT.format(cats=cats, source="the URL of the page you read it on"))
    jobs.append({"key": "web", "web": True, "system": system, "max_tokens": WEB_MAX_TOKENS, "what": "the web search",
                 "label": "  searching the web and reading pages (this takes a few minutes) ...",
                 "message": f"Research the film: {film}. Reply with the fact sheet between <facts> and </facts>."})
    return jobs


PAGE_TOKENS = 2500               # what one web search adds to what Claude reads, roughly


def estimate_job(job, model):
    """(input tokens, output tokens, dollars) one job may take with API credits. For the web search it's an upper
    bound, not a guess at the usual: every search adds its pages (about PAGE_TOKENS) to what is read again at each
    later step of the search, so the input grows with the square of the searches, at most WEB_SEARCHES of them. The
    API's caching can make it cheaper than that."""
    if job["web"]:
        n, start = claude_api.WEB_SEARCHES, int(len(job["system"]) / 3.5) + 500
        tin = n * start + PAGE_TOKENS * n * (n + 1) // 2
        tout = WEB_MAX_TOKENS
        extra = claude_api.WEB_SEARCHES * claude_api.SEARCH_USD
    else:
        tin = int((len(job["system"]) + len(job["message"])) / 3.5)
        tout = 2500
        extra = 0.0
    c = claude_api.cost(model, tin, tout)
    return tin, tout, None if c is None else c + extra


def starting_sheet(path, again, auto, details):
    """The sheet to add to: a stopped run's (picked up, if wanted; --again too, so a stopped look-up again isn't
    started over a second time), else a new one. Returns None when the sheet is finished and --again wasn't given."""
    if path.exists():
        try:
            old = json.loads(fileio.read_text(path))
        except (OSError, ValueError):
            old = None
        if isinstance(old, dict) and old.get("complete") and not again:
            print(f"{path.name} is already there ({len(old.get('facts') or [])} facts). --again looks the film up "
                  f"again.")
            return None
        if (isinstance(old, dict) and not old.get("complete") and isinstance(old.get("facts"), list)
                and old.get("done") and old["facts"]):
            pick = prompts.ask(f"The last look-up stopped after finding {len(old['facts'])} facts (kept in "
                               f"{path.name}). Pick up where it left off?",
                               {"p": "pick up where it left off", "s": "start again"}, "p", auto,
                               id="research.resume")
            if pick == "p":
                return old
    if path.exists():
        backup = fileio.unique_backup(path)
        shutil.copy2(path, backup)
        print(f"Kept the old fact sheet: {backup.name}")
    return {**details, "done": [], "complete": False, "facts": []}


def research(video, title=None, year=None, model=claude_api.DEFAULT_MODEL, effort=None, route="api",
             fallback_usd=0.0, key_file=None, api_url=claude_api.API_URL, assume_yes=False, estimate_only=False,
             again=False, commentary="auto", speech_model=None, out=None):
    """Write the fact sheet. Returns its path (None for an estimate, or when nothing was asked of it)."""
    import analyze
    video = Path(video)
    path = Path(out) if out else workfiles.facts_path(video)
    title = title or clean_title(video)
    year = year or gn.resolve_year(None, video, title)
    film = f"{title} ({year})" if year and str(year) not in title else title
    runtime = analyze.probe(video)[0]
    tracks = audio_tracks(video)
    chosen = commentary_tracks(tracks, commentary)
    if chosen:
        print("Commentary: " + "; ".join(describe(t) for t in chosen))
    elif commentary in (None, "", "auto") and len(tracks) > 1:
        print(f"No commentary track found (none of the {len(tracks)} audio tracks says \"commentary\" in its title; "
              f"--list-audio lists them, and --commentary N uses one anyway).")
    details = {"title": title, "year": int(year) if year else None, "video": video.name,
               "runtime": round(runtime, 1), "model": model, "date": datetime.date.today().isoformat(),
               "commentary": [{"track": t["n"], "title": t["title"]} for t in chosen]}
    sheet = None if estimate_only else starting_sheet(path, again, assume_yes, details)
    if sheet is None and not estimate_only:
        return path

    sender = sending.Sender("research", model, route=route, fallback_usd=fallback_usd, effort=effort,
                            max_tokens=WEB_MAX_TOKENS, timeout=900, key_file=key_file, api_url=api_url,
                            assume_yes=assume_yes, workdir=workfiles.make_dirs(path.parent) if not estimate_only
                            else None)
    sender.ready(estimate_only)
    transcripts = {}
    if chosen:
        if not _have_whisper():
            print("  ! The commentary can't be transcribed: faster-whisper isn't installed (pip3 install "
                  "faster-whisper). Using the web only.")
            chosen = []
        elif not estimate_only:
            if prompts.ask(f"Transcribe {len(chosen)} commentary track(s) ({timecode.hms(runtime)} each) on this "
                           f"computer? Free, but slow.",
                           {"y": "yes, transcribe", "n": "no, use the web only"}, "y", assume_yes,
                           id="research.commentary") == "y":
                for t in chosen:
                    transcripts[t["n"]] = transcribe_commentary(video, t, speech_model)
            else:
                chosen = []
    if estimate_only:                            # a stand-in: about 12 characters of talk a second, all through
        transcripts = {t["n"]: [{"s": float(s), "e": s + 60.0, "t": "x" * 720} for s in range(0, int(runtime), 60)]
                       for t in chosen}
    jobs = jobs_for(film, video, runtime, chosen, transcripts, video.name)
    if sheet is not None:
        jobs = [j for j in jobs if j["key"] not in sheet["done"]]
        if sheet["facts"]:
            print(f"Picking up: {len(sheet['facts'])} facts kept; {len(jobs)} request(s) to go.")

    pieces = [estimate_job(j, model) for j in jobs]
    est_in, est_out = sum(p[0] for p in pieces), sum(p[1] for p in pieces)
    usd = None if any(p[2] is None for p in pieces) else sum(p[2] for p in pieces)
    web = any(j["web"] for j in jobs)
    on_api = not sender.on_plan
    print(f"Plan: look up {film} in {len(jobs)} request(s) to {model}"
          + (f" (the web search: up to {claude_api.WEB_SEARCHES} searches)" if web and on_api else "")
          + (f"; at most about {est_in:,} tokens in and {est_out:,} out, up to about ${usd:.2f} in API credits "
             f"(usually less)." if on_api and usd is not None
             else sending.cost_words(usd, sender.on_plan)))
    per_request = sending.estimate("research", usd, None, on_plan=sender.on_plan, model=model,
                                   requests=len(jobs), searches=claude_api.WEB_SEARCHES if web else 0,
                                   commentary_tracks=len(chosen), input_tokens=est_in, output_tokens=est_out)
    sender.per_request_usd = per_request
    if estimate_only:
        print("Estimate only: nothing was sent.")
        return None
    if jobs:
        sender.confirm(len(jobs), "Have Claude look the film up on the web with the Claude API now?", "research.send",
                       unattended="Not an interactive terminal, so add --yes to confirm the look-up.",
                       cancelled="Cancelled; nothing was sent.",
                       plan_question="Have Claude look the film up on the web now (on your Claude plan, through "
                                     "Claude Code)?")
    usage.begin(film=usage.film_name(path), step="research", per_request=None if sender.on_plan else per_request)
    run = Researching(sheet, path, sender, film, runtime)
    sending.send_parts(run, jobs, sender, "research", 0, assume_yes)
    every = [j["key"] for j in jobs_for(film, video, runtime, chosen, transcripts, video.name)]
    sheet["complete"] = all(k in sheet["done"] for k in every) and bool(sheet["facts"])
    if sheet["complete"]:
        sheet["date"] = datetime.date.today().isoformat()
        sheet["made"] = datetime.datetime.now().isoformat(timespec="microseconds")   # the notes record which sheet
    run.save()
    print(f"Wrote {len(sheet['facts'])} facts -> {path}" + ("" if sheet["complete"] else " (not finished)"))
    print(sending.used_line(sender, model, run.tokens.input, run.tokens.output))
    usage.finish()
    for p in run.problems:
        print("  ! " + p)
    if not sheet["complete"] and sheet["facts"]:
        sys.exit("The look-up isn't finished (see above), so the notes aren't written from it yet. Run the same "
                 "command again: it sends only what's missing.")
    spoilers = sum(1 for f in sheet["facts"] if f.get("spoiler"))
    if spoilers:
        print(f"  {spoilers} of them give away something later in the film (marked as spoilers).")
    if not sheet["facts"]:
        sys.exit("No facts came back, so there's nothing to write Behind the Scenes notes from.")
    return path


def _have_whisper():
    import importlib.util
    return importlib.util.find_spec("faster_whisper") is not None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", help="the film (or episode)")
    ap.add_argument("--title", help="the film's title, e.g. 'The Lord of the Rings: The Two Towers' (default: from the "
                                    "file name)")
    ap.add_argument("--year", help="release year (default: from the title, the file's tags, its name or its folder)")
    ap.add_argument("--again", action="store_true", help="look the film up again (the old sheet is kept as a .bak)")
    ap.add_argument("--commentary", default="auto", metavar="auto|none|N",
                    help="commentary tracks to use: auto (any audio track whose title says commentary; the default), "
                         "none, or track numbers like 3 or 2,3 (see --list-audio)")
    ap.add_argument("--speech-model", help="faster-whisper model for the commentary (default: base.en, or small for "
                                           "other languages)")
    ap.add_argument("--list-audio", action="store_true", help="list the video's audio tracks, numbered, and stop")
    ap.add_argument("--out", help=argparse.SUPPRESS)
    ap.add_argument("--yes", action="store_true", help="don't ask before sending (and take the default answers)")
    ap.add_argument("--yes-to-all", action="store_true", help="answer the questions about the work without asking "
                                                              "(Settings: \"Yes to all questions\")")
    ap.add_argument("--estimate-only", action="store_true", help="show what it would take, then stop: nothing is sent")
    cli_common.add_claude_args(ap, model_default="from Settings, Opus unless changed",
                               effort_default="from Settings, high unless changed", show_key_file=True)
    defaults = settings.cli_defaults()
    ap.set_defaults(model=defaults["model"], effort=defaults["effort"], yes_to_all=defaults["yes_to_all"])
    a = ap.parse_args(argv)
    cli_common.settle_route(a)
    if a.yes_to_all:
        prompts.turn_on_yes_to_all()
    video = Path(a.video)
    if not video.exists():
        sys.exit(f"Can't find {video}")
    if a.list_audio:
        tracks = audio_tracks(video)
        for t in tracks:
            print(describe(t) + ("   <- looks like a commentary" if COMMENTARY_RE.search(t["title"]) else ""))
        if not tracks:
            print("No audio tracks.")
        return 0
    kw = {"api_url": a.api_url} if a.api_url else {}
    research(video, title=a.title, year=a.year, model=a.model or claude_api.DEFAULT_MODEL, effort=a.effort,
             route=a.route, fallback_usd=a.api_fallback, key_file=a.api_key_file, assume_yes=a.yes,
             estimate_only=a.estimate_only, again=a.again, commentary=a.commentary, speech_model=a.speech_model, **kw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
