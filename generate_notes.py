#!/usr/bin/env python3
"""
generate_notes.py - have Claude write the context notes for a subtitle file.

You normally don't run this directly; use make_ass.py:

    python3 make_ass.py --set-api-key                     # once: save your API key (hidden prompt)
    python3 make_ass.py episode.srt --generate            # write notes, then build the .ass
    python3 make_ass.py episode.srt --generate --video episode.mp4 --title "The IT Crowd - S01E02 - Calamity Jen"

The API key is read from (first match wins):
    1. --api-key-file PATH
    2. ~/.config/context-notes/api-key        (or $XDG_CONFIG_HOME/context-notes/api-key)
    3. the ANTHROPIC_API_KEY environment variable (fallback only)
The file must be readable only by you (chmod 600); --set-api-key creates it that way. The key handling and the
request itself live in claude_api.py.

Claude can run two ways (the "backend", claude_api.load_backend): through the API with your key (costs API credits,
billed separately from a claude.ai subscription), or through Claude Code on your Claude subscription
(`--backend claude-code`, or once: `make_ass.py --set-backend claude-code`). A preview of the size and, for the
API, the approximate cost is shown before anything is sent.

Uses only the Python standard library.
"""
import dataclasses
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import claude_api
import fileio
import languages
import prompts
import subtitles
import timecode

# Moved out of this file (the API client and key handling -> claude_api.py, the settings folder -> fileio.py).
# Kept here so older callers and docs that say generate_notes.load_key, generate_notes.DEFAULT_MODEL and so on
# still work. New code imports claude_api directly.
from claude_api import (API_URL, API_VERSION, DEFAULT_MODEL, MAX_TOKENS, PRICES,  # noqa: F401  (moved to claude_api.py)
                        call_api, cost, key_path, load_key, set_key)
from fileio import config_dir  # noqa: F401  (moved to fileio.py)

CHUNK_CHARS = 10000        # transcript characters per request (about 2,500 tokens)
CONTEXT_LINES = 6          # lines of the previous chunk shown for orientation
DEFAULT_AUDIENCE = "Fluent in English, didn't grow up in the UK"

CATEGORIES = ["British English", "Idiom", "Wordplay", "Cultural reference", "Historical context",
              "IT in-joke", "Character", "Delivery", "Running gag", "Setup", "Payoff", "Trivia",
              "Background", "Theme", "Archaic word", "Bawdy", "Adaptation"]
FOREIGN_CATEGORIES = ["Translation", "Register", "Slang", "Dialect", "Idiom", "Wordplay", "Cultural reference",
                      "Historical context", "Character", "Delivery", "Running gag", "Setup", "Payoff", "Trivia",
                      "Background", "Theme", "Bawdy"]


def is_foreign(film_language):
    return bool(film_language) and languages.code(film_language) != "en"


def default_audience(film_language=None, situation=None):
    if is_foreign(film_language):
        lang = languages.name(film_language)
        if situation == "original":
            return (f"English speaker watching with the original {lang} subtitles: follows most of the {lang} but "
                    f"isn't a native speaker, so misses idioms, slang, wordplay, register and cultural references")
        return (f"Native English speaker who doesn't speak {lang} well "
                "and didn't grow up where the film was made")
    return DEFAULT_AUDIENCE


OLD_FILM_YEARS = 40        # the default rule: a film more than this many years old gets extra attention to its period
OLD_FILM_RULE = ("This film was made in {year}, more than {years} years ago, so its period will be unfamiliar to the "
                 "viewer. Pay special attention to: words, slang and phrases that have dropped out of use or changed "
                 "meaning; people (actors, singers, politicians, public figures) who were known then and mean little "
                 "to a viewer now or from elsewhere; places, shops, institutions and customs that have changed or "
                 "gone; and the cultural mood of the time (manners, class, fashion, politics, attitudes) that a viewer "
                 "today wouldn't feel. Don't note ordinary modern vocabulary.\n\n")


def era_section(year=None, this_year=None):
    """The default old-film rule, or "" when the release year isn't known or the film is 40 years old or less."""
    if not year:
        return ""
    this_year = this_year or time.localtime().tm_year
    if this_year - int(year) <= OLD_FILM_YEARS:
        return ""
    return OLD_FILM_RULE.format(year=year, years=OLD_FILM_YEARS)


PAREN_YEAR_RE = re.compile(r"[(\[]\s*((?:18|19|20)\d{2})\s*[)\]]")   # "Amadeus (1984) Directors Cut"
YEAR_RE = re.compile(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)")          # "Das.Boot.1981.RESTORED.1080p"


def year_in_text(text, this_year=None):
    """A release year in a title, file name or folder name: a year in brackets if there is one, else the last
    plausible year (so "2001.A.Space.Odyssey.1968" gives 1968). None if there isn't one."""
    this_year = this_year or time.localtime().tm_year
    bracketed = [int(y) for y in PAREN_YEAR_RE.findall(text) if 1888 <= int(y) <= this_year]
    if bracketed:
        return bracketed[0]
    loose = [int(y) for y in YEAR_RE.findall(text) if 1888 <= int(y) <= this_year]
    return loose[-1] if loose else None


def year_in_tags(video, this_year=None):
    """A year from the file's own tags (date, year, DATE_RELEASED...), or None. Creation time is ignored: for an
    old rip it's the day someone made the file."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(video)],
                           capture_output=True, text=True, timeout=60)
        tags = (json.loads(r.stdout or "{}").get("format") or {}).get("tags") or {}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    for key, value in tags.items():
        if "date" in key.lower() or "year" in key.lower():
            found = year_in_text(str(value), this_year)
            if found:
                return found
    return None


def find_year(video=None, title=None):
    """Where the release year is, looking in order: the title you gave, the file's tags, the file name, the folder
    name. Returns (year, where it was found), or (None, None)."""
    this_year = time.localtime().tm_year
    sources = []
    if title:
        sources.append(("the title", lambda: year_in_text(title, this_year)))
    if video:
        video = Path(video)
        sources += [("the file's tags", lambda: year_in_tags(video, this_year)),
                    ("the file name", lambda: year_in_text(video.stem, this_year)),
                    ("the folder name", lambda: year_in_text(video.parent.name, this_year))]
    for where, look in sources:
        year = look()
        if year:
            return year, where
    return None, None


def resolve_year(explicit=None, video=None, title=None, say=print):
    """The year to use: --year if given, else found from the title, tags, file or folder. Says which one it used."""
    if explicit:
        return int(explicit)
    year, where = find_year(video, title)
    if year:
        say(f"Release year {year}, from {where}.")
    else:
        say("No release year found in the title, the file or its folder. The old-film rule is off; "
            "add --year 1974 (for example) to turn it on.")
    return year


# ---------------------------------------------------------------- prompts
SYSTEM = """You write short "pop-up" context notes for someone watching a show or film with its subtitles on, \
in the spirit of Pop-Up Video: small asides that appear just after a line and explain what the viewer may not \
know. You are given numbered subtitle lines; you reply with notes as JSON.

Viewer: {audience}.
Write every note in {language}.

What deserves a note:
- idioms, slang, regional or period vocabulary, wordplay and puns the viewer might miss
- cultural, historical, political or pop-culture references; real people, places, institutions
- humour that depends on a convention or piece of knowledge (explain the mechanism briefly, not the whole joke)
- delivery and timing that carries the comedy or drama (a pause, a non-denial, an understatement)
- setups and payoffs, running gags, and what a line reveals about a character
- the occasional well-established piece of trivia, when it genuinely adds something
Skip anything the viewer would obviously understand. Fewer, better notes beat many; aim for roughly one note per \
6 to 10 lines of dialogue, and none where nothing needs saying.

Rules:
- Be accurate. Never invent facts, quotes, casting or production details. If you are not sure, set "confidence" to \
"medium" or "low" (the viewer sees a "less sure" tag) or leave the note out.
- No spoilers: only use what has happened in the lines you've been shown or earlier. Don't hint at later events.
- Each note is at most about 40 words, plain and friendly, no markdown.
- "cue" must be the number of the line your quote comes from. Attach a note to the line where the joke or \
reference actually lands (the punchline), not to the setup before it.
- Notes are about the lines marked for annotation; lines marked [context] are only for orientation.
- Don't repeat a topic already covered by the earlier notes you're told about.

{era_section}{language_section}Tone and length to aim for (examples from another episode):
{examples}

Reply with ONLY a JSON array, no prose and no code fences. Each element:
{{"cue": <line number the note belongs to>, "match": "<3 to 8 words quoted exactly from that line>", \
"category": "<one of: {cats}, or a short label of your own>", "text": "<the note>", \
"confidence": "high" | "medium" | "low"}}
If nothing deserves a note, reply with []."""


ENGLISH_EXAMPLES = """\
- British English: "A CV (curriculum vitae) is the British word for a résumé."
- Delivery: "Listen to the wording: she confirms she SAID it, not that it's true. A careful non-denial."
- Character: "Bluffing 101: name the most basic things possible, confidently, and keep going.\""""

ORIGINAL_EXAMPLES = """\
- Idiom: "'Poser un lapin' (literally 'to put down a rabbit'): to stand someone up. She's been waiting an hour."
- Register: "He switches from 'vous' to 'tu' here. Without asking first, that's a deliberate step toward intimacy, \
or a put-down."
- Cultural reference: "'Le bac' is the exam at the end of French secondary school. Failing it is a big, public deal."
(Those examples are French; use the same approach for whatever language the film is in.)"""

FOREIGN_EXAMPLES = """\
- Translation: "The subtitle says 'idiot', but 'connard' is far ruder: closer to 'bastard'. The insult is meant to sting."
- Register: "He switches from 'vous' to 'tu' here. Without asking first, that's a deliberate step toward intimacy, \
or a put-down."
- Cultural reference: "'Le bac' is the exam at the end of French secondary school. Failing it is a big, public deal."
(Those examples are French; use the same approach for whatever language the film is in.)"""


def language_section(film_language, subs_situation):
    """Extra instructions for a film that isn't in English. subs_situation: 'original' (the viewer reads subtitles in
    the film's own language), 'paired' (a translation, with the original lines given) or 'translated' (a translation,
    original not available)."""
    if not is_foreign(film_language):
        return ""
    lang = languages.name(film_language)
    register = languages.REGISTER.get(languages.code(film_language), "formal and informal ways of saying 'you'")
    subs = {
        "original": f"The subtitles are in {lang} too, and the viewer reads them: they follow most of the {lang} but "
                    f"aren't a native speaker. Don't translate lines. Note only what a good non-native reader would "
                    f"miss, and explain it in {{language}}: start with the {lang} phrase (and a short literal meaning "
                    f"when that helps), then what it really means and how it lands. Quote \"match\" exactly as it is "
                    f"written in the {lang} subtitle line; never translate the quote.",
        "paired": f"The subtitles the viewer reads are a translation. After a line, ‹{languages.code(film_language)}: ...› "
                  f"gives the original {lang} subtitle for the same moment (it can be missing, or split differently). "
                  f"Compare the two: the gap between them is where most of the interesting notes are. Quote \"match\" "
                  f"from the translated line, never from the ‹...› original.",
        "translated": f"The subtitles the viewer reads are a translation, and you can't see the original {lang} wording. "
                      f"Don't claim what was said in {lang} unless you are confident (and then say \"medium\" "
                      f"confidence).",
    }[subs_situation]
    if subs_situation == "original":
        first = ("idioms and set phrases whose meaning isn't the sum of the words, false friends, puns and wordplay, "
                 "and how strong a swear word or insult really is")
        skip = ("Don't translate whole lines or explain ordinary vocabulary; the viewer can read it. Explain what a "
                "dictionary wouldn't tell them.")
    else:
        first = ("what the subtitles lose: puns and wordplay that don't survive translation, swearing much stronger or "
                 "milder than the subtitle, a name, title or reference the subtitle replaced, softened or dropped")
        skip = "Don't translate lines the subtitles already handle well, and don't explain the language for its own sake."
    return f"""The film is in {lang}. {subs}

For a {lang}-language film, also look for:
- {first}
- register: {register}, and what a switch between them says about the relationship
- slang, regional speech, accents and dialects, and what they signal about class, region, age or background
- references a {lang}-speaking audience gets instantly: history, politics, institutions, school, TV, songs, food, \
holidays, places
{skip}

"""


def pair_original(cues, original):
    """Match each original-language line to the displayed line it overlaps most in time.
    Returns ({displayed cue n: 'original text'}, share of displayed lines that got one)."""
    def clean(t):
        return re.sub(r"<[^>]+>|\{[^}]*\}", "", t).replace("\n", " / ").strip()
    paired = {}
    starts = [c["start"] for c in cues]
    import bisect
    for o in original:
        best, best_ov = None, 0.0
        k = bisect.bisect_left(starts, o["start"] - 15)
        while k < len(cues) and cues[k]["start"] < o["end"]:
            c = cues[k]
            ov = min(c["end"], o["end"]) - max(c["start"], o["start"])
            if ov > best_ov:
                best, best_ov = c["n"], ov
            k += 1
        if best is not None:
            paired.setdefault(best, []).append(clean(o["text"]))
    out = {n: " / ".join(v) for n, v in paired.items()}
    return out, (len(out) / len(cues) if cues else 0.0)


def fmt_line(c, extra=None):
    line = f"{c['n']} [{timecode.fmt_ass_time(c['start']).split('.')[0]}] " + \
        re.sub(r"<[^>]+>|\{[^}]*\}", "", c["text"]).replace("\n", " / ").strip()
    if extra and c["n"] in extra["text"]:
        line += f"  ‹{extra['lang']}: {extra['text'][c['n']]}›"
    return line


def chunks(cues, extra=None):
    out, cur, size = [], [], 0
    for c in cues:
        n = len(fmt_line(c, extra)) + 1
        if cur and size + n > CHUNK_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += n
    if cur:
        out.append(cur)
    return out


def user_message(title, part, prev_tail, earlier_notes, k, total, extra=None):
    lines = []
    if prev_tail:
        lines.append("[context] (earlier lines, do not annotate)")
        lines += ["[context] " + fmt_line(c, extra) for c in prev_tail]
        lines.append("")
    lines.append(f"Lines to annotate ({part[0]['n']} to {part[-1]['n']}):")
    lines += [fmt_line(c, extra) for c in part]
    covered = ""
    if earlier_notes:
        covered = "\n\nTopics already covered by earlier notes (don't repeat):\n" + "\n".join(
            f"- \"{n.get('match') or ' '.join(n['text'].split()[:8]) + '...'}\" ({n['category']})"
            for n in earlier_notes[-60:])
    return (f"Title: {title}\nPart {k} of {total}.\n\n" + "\n".join(lines) + covered +
            "\n\nReply with the JSON array only.")


# ---------------------------------------------------------------- parsing and checking
def extract_objects(text):
    """Pull note objects out of a reply, tolerating code fences and a truncated tail."""
    start = text.find("[")
    if start < 0:
        return []
    dec, i, out = json.JSONDecoder(), start + 1, []
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text) or text[i] != "{":
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        out.append(obj)
    return out


def check_note(raw, cues, lo, hi):
    """Turn a model-written note into a notes.json entry, or return (None, reason)."""
    try:
        cue = int(raw["cue"])
        text = str(raw["text"]).strip()
    except (KeyError, TypeError, ValueError):
        return None, "missing cue or text"
    if not text:
        return None, "empty text"
    if not lo <= cue <= hi:
        return None, f"cue {cue} is outside the lines being annotated"
    conf = str(raw.get("confidence", "high")).lower()
    note = {"category": str(raw.get("category") or "Note").strip(), "text": text,
            "confidence": conf if conf in ("high", "medium", "low") else "medium", "kind": "speech"}
    match = str(raw.get("match") or "").strip()
    idx = cue - 1
    n = subtitles.norm(match)
    normed = [subtitles.norm(c["text"]) for c in cues]

    def has(i):                        # same test make_ass uses, incl. quotes spanning two lines
        if n in normed[i]:
            return True
        return i + 1 < len(normed) and n in normed[i] + " " + normed[i + 1] and n not in normed[i + 1]

    if n:
        # The quote is more trustworthy than the line number (models are often a line out), so look
        # for it in the stated line first, then in the closest lines either side.
        for i in sorted(range(max(lo - 1, idx - 3, 0), min(hi, idx + 4, len(cues))), key=lambda i: abs(i - idx)):
            if has(i):
                hits = [k for k in range(len(cues)) if has(k)]
                note = {"match": match, **note}
                if len(hits) > 1:
                    note["occurrence"] = hits.index(i) + 1
                if i != idx:
                    return note, f"line {cue}: quote found in line {i + 1} instead; placed there"
                return note, None
    # The quote isn't anywhere near that line, so anchor to the line number instead (still placed,
    # just less portable between releases of the same episode).
    return {"cue": cue, **note}, f"line {cue}: quote not found nearby; anchored by line number"


# ---------------------------------------------------------------- main entry point
def estimate(cues, extra=None):
    parts = chunks(cues, extra)
    sys_chars = len(SYSTEM) + (1500 if extra else 0)
    in_chars = sum(sys_chars + 400 + sum(len(fmt_line(c, extra)) + 1 for c in p) + CONTEXT_LINES * 60 + 60 * 40
                   for p in parts)
    est_in = in_chars // 3.5
    est_out = int(len(cues) / 7 * 75)          # about one note per 7 lines, ~75 tokens each
    return len(parts), int(est_in), est_out


def subtitle_setup(cues, film_language=None, original_srt=None, say=print):
    """Work out how the subtitles relate to the film's language. Returns (situation, extra) for
    language_section() and fmt_line(): situation is None for an English film."""
    if not is_foreign(film_language):
        return None, None
    lang = languages.code(film_language)
    if original_srt:
        original = subtitles.parse_srt(original_srt)
        paired, share = pair_original(cues, original)
        say(f"Original {languages.name(lang)} subtitles: {len(original)} lines, matched to {share:.0%} of the lines "
            f"you'll see.")
        if share < 0.4:
            say("  ! That's low: the two subtitle files may be timed for different releases. Notes will still work, "
                "but Claude will see fewer original lines. (analyze.py --align can re-time one of them.)")
        return "paired", {"lang": lang, "text": paired}
    shown = languages.guess(" ".join(c["text"] for c in cues[:300]))
    if shown is not None and shown != lang:
        say(f"These subtitles look like {languages.name(shown)}, a translation of the {languages.name(lang)} dialogue.")
        return "translated", None
    return "original", None


def pick_up_choice(partial, srt_path, cues, film_language, limit, auto):
    """Notes from a run that stopped part-way are kept in <notes>.partial.json. If there is one for these subtitles,
    ask whether to pick up where it left off (the default: only the rest is sent) or start again.
    Returns (the notes already written, the last subtitle line they cover); ([], 0) to start from the beginning."""
    if not partial.exists():
        return [], 0
    try:
        kept = json.loads(partial.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], 0
    if not isinstance(kept, dict) or not kept.get("through_line") or not kept.get("notes"):
        print(f"(Not picking up from {partial.name}: it doesn't record where the last run stopped.)")
        return [], 0
    same = (kept.get("subtitles") == Path(srt_path).name and kept.get("limit") == (round(limit, 1) if limit else None)
            and languages.code(kept.get("film_language") or "en") == languages.code(film_language or "en"))
    if not same:
        print(f"(Not picking up from {partial.name}: it was written from other subtitles or settings.)")
        return [], 0
    notes, through = kept["notes"], int(kept["through_line"])
    pick = prompts.ask(f"The last run stopped after Claude had written {len(notes)} notes, up to line {through} of "
                       f"{cues[-1]['n']} (kept in {partial.name}). Pick up where it left off?",
                       {"p": "pick up where it left off (sends only the rest)", "s": "start again (sends everything)"},
                       "p", auto, id="generate.resume")
    return (notes, through) if pick == "p" else ([], 0)


@dataclasses.dataclass
class GeneratePlan:
    """Everything decided before anything is sent: what plan_generate() worked out and printed. generate() runs it;
    a test or another front end can look at it first."""
    srt_path: Path
    notes_path: Path
    partial: Path                    # <notes>.partial.json, where a stopped run keeps its notes
    cues: list                       # the subtitle lines (after --limit)
    all_parts: list                  # the lines in request-sized parts
    first: int                       # the first part to send (after 1 when picking up a stopped run)
    earlier: list                    # notes kept from the stopped run
    through: int                     # the last subtitle line those notes cover
    send: list                       # the lines that will be sent
    title: str
    audience: str
    situation: object                # None for an English film, else "original", "paired" or "translated"
    extra: object                    # the original-language lines for "paired", else None
    system: str                      # the system prompt, filled in
    language: str
    year: object
    model: str
    limit: object
    film_language: object
    original_srt: object
    video_offset: object
    n_send: int                      # the estimate: requests, tokens in and out, dollars (None for an unknown model)
    est_in: int
    est_out: int
    cost: object
    key: object = None               # the API key (None with estimate_only, or on the subscription)
    backend: str = "api"             # "api" (your key) or "claude-code" (your subscription)


def plan_generate(srt_path, notes_path, model=claude_api.DEFAULT_MODEL, audience=None, title=None, language="English",
                  assume_yes=False, key_file=None, film_language=None, original_srt=None, limit=None, video_offset=None,
                  year=None, estimate_only=False, backend=None):
    """Everything up to the "send?" question: read the subtitles, work out the language situation, offer to pick up a
    stopped run, print the plan and send the `estimate` event. Nothing is sent and nothing is written. The backend is
    settled here (claude_api.load_backend: --backend, the environment, the saved setting, else the API), and the API
    key is read, or Claude Code looked for, before any of that work, so a missing one stops the run at once (not with
    estimate_only)."""
    all_cues = subtitles.parse_srt(srt_path)
    if not all_cues:
        sys.exit(f"No subtitle cues found in {srt_path}")
    cues = subtitles.limit_cues(all_cues, limit)
    if not cues:
        sys.exit(f"No subtitle lines start in the first {timecode.fmt_limit(limit)} of {srt_path}.")
    backend = claude_api.load_backend(backend)
    key = None
    if not estimate_only:                                              # fail early if there's no way to reach Claude
        if backend == "api":
            key = claude_api.load_key(key_file)
        else:
            claude_api.check_claude_code()
    title = title or Path(srt_path).stem
    situation, extra = subtitle_setup(cues, film_language, original_srt)
    audience = audience or default_audience(film_language, situation)
    if limit:
        print(f"Limited to the first {timecode.fmt_limit(limit)}: {len(cues)} of {len(all_cues)} lines.")
    all_parts = chunks(cues, extra)
    parts = len(all_parts)
    partial = Path(notes_path).with_suffix(".partial.json")
    earlier, through = pick_up_choice(partial, srt_path, cues, film_language, limit, assume_yes or estimate_only)
    first = 1 + sum(1 for p in all_parts if p[-1]["n"] <= through)
    send = [cue for p in all_parts[first - 1:] for cue in p]       # all the lines, unless picking up
    if first > 1:
        print(f"Picking up where the last run stopped: {len(earlier)} notes kept; part {first} of {parts} is next.")
    n_send, est_in, est_out = estimate(send, extra) if send else (0, 0, 0)
    c = claude_api.cost(model, est_in, est_out, backend)
    print(f"Plan: {len(send)} lines in {n_send} request(s) to {model}; about {est_in:,} tokens in and "
          f"{est_out:,} out" + claude_api.cost_note(c, backend))
    prompts.event("estimate", step="generate", model=model, backend=backend, lines=len(send), requests=n_send,
                  input_tokens=est_in, output_tokens=est_out, cost_usd=None if c is None else round(c, 4), limit=limit)
    foreign = situation is not None
    system = SYSTEM.format(audience=audience, language=language, era_section=era_section(year),
                           cats=", ".join(FOREIGN_CATEGORIES if foreign else CATEGORIES),
                           language_section=(language_section(film_language, situation).replace("{language}", language)
                                             if foreign else ""),
                           examples=(ORIGINAL_EXAMPLES if situation == "original" else FOREIGN_EXAMPLES) if foreign
                           else ENGLISH_EXAMPLES)
    return GeneratePlan(srt_path=Path(srt_path), notes_path=Path(notes_path), partial=partial, cues=cues,
                        all_parts=all_parts, first=first, earlier=earlier, through=through, send=send, title=title,
                        audience=audience, situation=situation, extra=extra, system=system, language=language,
                        year=year, model=model, limit=limit, film_language=film_language, original_srt=original_srt,
                        video_offset=video_offset, n_send=n_send, est_in=est_in, est_out=est_out, cost=c, key=key,
                        backend=backend)


def confirm_generate(plan, assume_yes=False):
    """The "send?" question (--yes answers it). Stops the run on no, or when there is nobody to ask."""
    if plan.send and not assume_yes:
        where = "Claude Code (your subscription)" if plan.backend == "claude-code" else "the Claude API"
        if not prompts.interactive():
            sys.exit(f"Not an interactive terminal, so add --yes to confirm sending the subtitles to {where}.")
        if not prompts.confirm(f"Send the subtitle text to {where} now?", id="generate.send"):
            sys.exit("Cancelled; nothing was sent.")


def generate_part(plan, k, part, prev_tail, notes, key, api_url=claude_api.API_URL, max_tokens=claude_api.MAX_TOKENS,
                  effort=None):
    """One request: the lines of `part` (with `prev_tail` for orientation and `notes` so far, whose topics aren't
    repeated) go to Claude, and its reply is checked line by line. Returns (the notes it wrote, usage, problems).
    The one call to Claude is claude_api.send (the API or Claude Code, by plan.backend); the message itself is built
    by user_message(). Claude Code runs in the notes file's folder."""
    lo, hi = part[0]["n"], part[-1]["n"]
    message = user_message(plan.title, part, prev_tail, notes, k, len(plan.all_parts), plan.extra)
    reply = claude_api.send(plan.backend, plan.model, plan.system, message, key=key, api_url=api_url,
                            max_tokens=max_tokens, effort=effort, workdir=plan.notes_path.resolve().parent)
    usage = reply.get("usage", {})
    problems = []
    if reply.get("stop_reason") == "refusal":
        problems.append(f"part {k}: the model declined to write notes for these lines")
    text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
    raw_notes = extract_objects(text)
    part_notes = []
    for r in raw_notes:
        note, why = check_note(r, plan.cues, lo, hi)
        if note is None:
            problems.append(f"part {k}: dropped a note ({why})")
            continue
        if why:
            problems.append(f"part {k}: {why}")
        part_notes.append(note)
    if reply.get("stop_reason") == "max_tokens":
        problems.append(f"part {k}: reply was cut off, so later notes in this part may be missing")
    if not raw_notes and text.strip() not in ("[]", ""):
        bad = plan.notes_path.with_suffix(f".part{k}.failed.txt")
        bad.write_text(text, encoding="utf-8")
        problems.append(f"part {k}: couldn't read the reply; saved it to {bad.name}")
    return part_notes, usage, problems


def write_notes_file(plan, notes):
    """Write the notes file all at once: an intro note, the settings the notes were written with, and the notes.
    The partial file from a stopped run goes, since its notes are in the notes file now. Returns the file's contents."""
    ms = int(round(plan.cues[0]["start"] * 1000))
    intro = {"at": f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}",
             "category": "About these notes", "duration": 9, "kind": "speech",
             "text": f"Pre-alpha context notes written by Claude ({plan.model}) for this viewer: {plan.audience.rstrip('.')}. "
                     "Each note appears just after its line. “(less sure)” means: check me."
                     + (f" These notes cover only the first {timecode.fmt_limit(plan.limit)}." if plan.limit else "")}
    spec = {"title": f"{plan.title} (context notes)", "audience": plan.audience,
            "scope": "Dialogue notes written from the subtitles only (no video or audio was analysed)",
            "generated_by": plan.model}
    if plan.backend != "api":
        spec["backend"] = plan.backend
    if plan.video_offset is not None:
        spec["video_offset"] = round(float(plan.video_offset), 2)
    if plan.situation is not None:
        spec["film_language"] = languages.code(plan.film_language)
        if plan.original_srt:
            spec["original_subtitles"] = Path(plan.original_srt).name
    if plan.limit:
        spec["limit"] = round(plan.limit, 1)
    if plan.year:
        spec["year"] = int(plan.year)
    spec["notes"] = [intro] + notes
    fileio.write_text_safely(plan.notes_path, json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
    try:
        plan.partial.unlink()                    # its notes are in the notes file now
    except OSError:
        pass
    return spec


def generate(srt_path, notes_path, model=claude_api.DEFAULT_MODEL, audience=None, title=None, language="English",
             assume_yes=False, key_file=None, api_url=claude_api.API_URL, film_language=None, original_srt=None,
             limit=None, video_offset=None, effort=None, max_tokens=claude_api.MAX_TOKENS, year=None, estimate_only=False,
             backend=None):
    """Write the notes file: plan_generate, the "send?" question, one request per part, write_notes_file.
    With estimate_only, stop after the size and cost estimate: no API key is needed, nothing is sent and nothing is
    written (returns None). A run that stops part-way keeps its notes in <notes>.partial.json for the next one.
    `backend` is "api", "claude-code" or None (the saved setting, else the API)."""
    plan = plan_generate(srt_path, notes_path, model=model, audience=audience, title=title, language=language,
                         assume_yes=assume_yes, key_file=key_file, film_language=film_language,
                         original_srt=original_srt, limit=limit, video_offset=video_offset, year=year,
                         estimate_only=estimate_only, backend=backend)
    if estimate_only:
        print("Estimate only: nothing was sent.")
        return None
    confirm_generate(plan, assume_yes)

    parts = len(plan.all_parts)
    notes, tin, tout, problems = list(plan.earlier), 0, 0, []
    prev_tail = plan.all_parts[plan.first - 2][-CONTEXT_LINES:] if plan.first > 1 else []
    done_line = plan.through                     # the last subtitle line whose part is finished

    def keep_partial(k):
        if notes:
            fileio.write_text_safely(plan.partial, json.dumps(
                {"notes": notes, "through_line": done_line, "subtitles": plan.srt_path.name,
                 "film_language": film_language, "limit": round(limit, 1) if limit else None, "model": model,
                 "backend": plan.backend},
                indent=1, ensure_ascii=False))
            print(f"\n  Stopped after part {k - 1} of {parts}. The {len(notes)} notes written so far "
                  f"were saved to {plan.partial.name}; the next run offers to pick up from there.", flush=True)

    k = plan.first
    try:
        for k, part in enumerate(plan.all_parts[plan.first - 1:], plan.first):
            lo, hi = part[0]["n"], part[-1]["n"]
            prompts.progress("generate", k - 1, parts, "requests")     # before the line below, which stays open
            print(f"  part {k}/{parts}: lines {lo}-{hi} ...", end=" ", flush=True)
            try:
                part_notes, usage, part_problems = generate_part(plan, k, part, prev_tail, notes, plan.key, api_url,
                                                                 max_tokens, effort)
            except SystemExit:                               # an API error: keep what was paid for
                keep_partial(k)
                raise
            tin += usage.get("input_tokens", 0)
            tout += usage.get("output_tokens", 0)
            problems += part_problems
            print(f"{len(part_notes)} notes")
            prev_tail = part[-CONTEXT_LINES:]
            notes.extend(part_notes)             # a part counts once all of it is in, so a stop never splits one
            done_line = hi
    except KeyboardInterrupt:                    # Ctrl-C, or a GUI's Cancel, at any point: keep what was paid for
        keep_partial(k)
        raise
    prompts.progress("generate", parts, parts, "requests")

    spec = write_notes_file(plan, notes)
    actual = claude_api.cost(model, tin, tout, plan.backend)
    print(f"Wrote {len(notes)} notes -> {notes_path}")
    print(f"Used {tin:,} input and {tout:,} output tokens" + claude_api.used_note(actual, plan.backend))
    for p in problems:
        print("  ! " + p)
    if not notes:
        sys.exit("No usable notes came back.")
    return spec


if __name__ == "__main__":
    if "--set-api-key" in sys.argv:
        claude_api.set_key()
    else:
        sys.exit(__doc__)
