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
The file must be readable only by you (chmod 600); --set-api-key creates it that way.

Uses only the Python standard library. Calls cost API credits, which are billed
separately from a claude.ai subscription. A preview of the size and approximate
cost is shown before anything is sent.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import languages
import make_ass
import prompts
import usage

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
# USD per million tokens (input, output). Checked October 2026; see
# https://platform.claude.com/docs/en/about-claude/pricing for current figures.
PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}
CHUNK_CHARS = 10000        # transcript characters per request (about 2,500 tokens)
CONTEXT_LINES = 6          # lines of the previous chunk shown for orientation
MAX_TOKENS = 8000          # reply limit per request
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
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
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


# ---------------------------------------------------------------- API key
def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "context-notes"


def key_path():
    return config_dir() / "api-key"


def set_key():
    """Prompt (hidden) for the API key and store it where only this user can read it."""
    path = key_path()
    key = prompts.secret("Paste your Anthropic API key (input is hidden), then press Return: ", id="api-key").strip()
    if not key:
        sys.exit("Nothing entered; nothing saved.")
    if not key.startswith("sk-ant-"):
        sys.exit("That doesn't look like an Anthropic API key (they start with sk-ant-). Nothing saved.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    os.chmod(path, 0o600)
    print(f"Saved to {path} (readable only by you). Key ends in ...{key[-4:]}")
    print("Create or manage keys at https://console.anthropic.com/settings/keys")


def load_key(explicit=None):
    path = Path(explicit).expanduser() if explicit else key_path()
    if path.exists():
        if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            sys.exit(f"{path} can be read by other users. Lock it down first:\n  chmod 600 \"{path}\"")
        key = path.read_text().strip()
        if key:
            return key
        sys.exit(f"{path} is empty. Run  python3 make_ass.py --set-api-key")
    if explicit:
        sys.exit(f"Can't find the key file {explicit}")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    sys.exit("No API key found. Save one with:\n  python3 make_ass.py --set-api-key\n"
             f"(stored in {key_path()})")


# ---------------------------------------------------------------- API call
# On Windows a program waiting for a network reply doesn't notice Ctrl-C (or a GUI's Cancel) until the reply comes,
# which can be minutes. There the request waits in a helper thread while this one stays awake.
WAIT_IN_THREAD = os.name == "nt"


def wait_awake(fn, *args, **kwargs):
    """fn(*args, **kwargs), run in a helper thread while this thread waits in short steps, so Ctrl-C and Cancel are
    noticed at once. Whatever fn raises (sys.exit included) is raised here; its result is returned."""
    out = {}

    def work():
        try:
            out["value"] = fn(*args, **kwargs)
        except BaseException as e:                         # carried over to the waiting thread
            out["error"] = e
    t = threading.Thread(target=work, daemon=True)
    t.start()
    while t.is_alive():
        t.join(0.2)
    if "error" in out:
        raise out["error"]
    return out.get("value")


def call_api(key, model, system, user, url=API_URL, timeout=300, max_tokens=MAX_TOKENS, effort=None):
    """One request to the Messages API (see _call_api). On Windows it waits awake, so Cancel works mid-request."""
    if WAIT_IN_THREAD:
        return wait_awake(_call_api, key, model, system, user, url, timeout, max_tokens, effort)
    return _call_api(key, model, system, user, url, timeout, max_tokens, effort)


def _call_api(key, model, system, user, url=API_URL, timeout=300, max_tokens=MAX_TOKENS, effort=None):
    """`user` is a string, or a list of content blocks (text and images).
    `effort` ("low", "medium", "high", ...) is sent as output_config.effort; None leaves the model's own default
    (Haiku 4.5 rejects the field, so only pass it for models that support it)."""
    payload = {"model": model, "max_tokens": max_tokens, "system": system,
               "messages": [{"role": "user", "content": user}]}
    if effort:
        payload["output_config"] = {"effort": effort}
    body = json.dumps(payload).encode()
    headers = {"x-api-key": key, "anthropic-version": API_VERSION,
               "content-type": "application/json", "user-agent": "context-notes/0.1"}
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                reply = json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e)["error"]["message"]
            except Exception:
                msg = e.reason
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                wait = float(e.headers.get("retry-after") or 2 ** (attempt + 1) * 2)
                print(f"    API busy ({e.code}); retrying in {wait:.0f} s...")
                time.sleep(min(wait, 60))
                continue
            if e.code == 401:
                sys.exit("The API rejected the key (401). Check it, or save a new one with --set-api-key.")
            if e.code == 400 and "credit balance" in str(msg).lower():
                usage.mark_empty()                   # the API knows better than the estimate (usage.py)
                sys.exit(f"API error {e.code}: {msg}\nAdd credit at https://platform.claude.com/settings/billing, "
                         f"then run the same command again: what was already written is kept.")
            sys.exit(f"API error {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < 3:
                print(f"    network problem ({e}); retrying...")
                time.sleep(2 ** (attempt + 1))
                continue
            sys.exit(f"Couldn't reach the API: {e}")
        _record_usage(model, reply)
        return reply


def _record_usage(model, reply):
    """Note what a finished request cost (usage.py), without ever letting the bookkeeping stop a paid run."""
    try:
        used = reply.get("usage") or {}
        tin, tout = int(used.get("input_tokens") or 0), int(used.get("output_tokens") or 0)
        usage.record(model, tin, tout, cost(model, tin, tout))
    except Exception:                        # a reply shaped oddly: the notes matter more than the ledger
        pass


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
    line = f"{c['n']} [{make_ass.fmt_ass_time(c['start']).split('.')[0]}] " + \
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
    n = make_ass.norm(match)
    normed = [make_ass.norm(c["text"]) for c in cues]

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


def cost(model, tin, tout):
    if model not in PRICES:
        return None
    pi, po = PRICES[model]
    return tin * pi / 1e6 + tout * po / 1e6


def subtitle_setup(cues, film_language=None, original_srt=None, say=print):
    """Work out how the subtitles relate to the film's language. Returns (situation, extra) for
    language_section() and fmt_line(): situation is None for an English film."""
    if not is_foreign(film_language):
        return None, None
    lang = languages.code(film_language)
    if original_srt:
        original = make_ass.parse_srt(original_srt)
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
    Returns (the notes already written, the last subtitle line they cover, the parts whose replies couldn't be
    read); ([], 0, []) to start from the beginning."""
    if not partial.exists():
        return [], 0, []
    try:
        kept = json.loads(partial.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], 0, []
    if not isinstance(kept, dict) or not kept.get("through_line") or not kept.get("notes"):
        print(f"(Not picking up from {partial.name}: it doesn't record where the last run stopped.)")
        return [], 0, []
    same = (kept.get("subtitles") == Path(srt_path).name and kept.get("limit") == (round(limit, 1) if limit else None)
            and languages.code(kept.get("film_language") or "en") == languages.code(film_language or "en"))
    if not same:
        print(f"(Not picking up from {partial.name}: it was written from other subtitles or settings.)")
        return [], 0, []
    notes, through = kept["notes"], int(kept["through_line"])
    pick = prompts.ask(f"The last run stopped after Claude had written {len(notes)} notes, up to line {through} of "
                       f"{cues[-1]['n']} (kept in {partial.name}). Pick up where it left off?",
                       {"p": "pick up where it left off (sends only the rest)", "s": "start again (sends everything)"},
                       "p", auto, id="generate.resume")
    return (notes, through, list(kept.get("unreadable") or [])) if pick == "p" else ([], 0, [])


def failed_reply_path(notes_path, k):
    """Where a reply that couldn't be read is kept: <notes>.part<k>.failed.txt, or .failed2.txt and so on, so an
    earlier one is never overwritten."""
    n = 1
    while True:
        p = Path(notes_path).with_suffix(f".part{k}.failed{'' if n == 1 else n}.txt")
        if not p.exists():
            return p
        n += 1


def unreadable_parts(spec, cues):
    """The stretches of lines whose replies couldn't be read when the notes were written ("unreadable" in the notes
    file: [{"lines": [first, last], "reply": the reply, saved}]), as (first, last) within these subtitles."""
    have = {c["n"] for c in cues}
    out = []
    for u in (spec or {}).get("unreadable") or []:
        try:
            lo, hi = int(u["lines"][0]), int(u["lines"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if lo in have:
            out.append((lo, hi))
    return out


def note_lines(cues, notes):
    """The subtitle line (from 1) each note is placed on, worked out as the build does (make_ass.place_notes): in
    order, each quote looked for from the line before. None for a note timed by the clock or not found."""
    out, last = [], 0
    for n in notes:
        idx = None
        if "at_video" not in n and "at" not in n:
            if "cue" in n:
                idx = int(n["cue"]) - 1 if 0 < int(n["cue"]) <= len(cues) else None
            elif "match" in n:
                idx = make_ass.find_cue(cues, n["match"], last, int(n.get("occurrence", 1)))
        if idx is not None:
            last = idx
        out.append(None if idx is None else cues[idx]["n"])
    return out


def insert_in_order(cues, notes, new, hi):
    """`new` (notes for lines up to `hi`) put before the first note placed on a later line. The order matters: the
    build looks for each quote from the line of the note before it."""
    lines = note_lines(cues, notes)
    at = next((i for i, line in enumerate(lines) if line is not None and line > hi), len(notes))
    return notes[:at] + new + notes[at:]


def same_subtitles(name):
    """film.en.aligned.srt and film.en.srt are the same lines (re-timed), so notes from one work on the other."""
    return re.sub(r"\.aligned(\.first\d+s)?(?=\.srt$)", "", str(name), flags=re.I)


def notes_to_extend(notes_path, srt_path, cues, film_language, limit):
    """Notes written for only the first part of a film (--limit), now wanted for more of it: the existing notes file
    to keep and add to; also notes whose replies couldn't be read ("unreadable"), to send those lines again.
    Returns (its spec, its notes without the intro, the last subtitle line they cover, or None when they cover what's
    asked); exits if they can't be added to."""
    try:
        spec = json.loads(make_ass.read_text(notes_path))
    except (OSError, ValueError):
        sys.exit(f"Can't read {notes_path} to add to it.")
    if not isinstance(spec, dict) or not spec.get("notes"):
        sys.exit(f"{Path(notes_path).name} has no notes to add to; leave off --extend to write them.")
    had = spec.get("limit")
    more = bool(had) and not (limit and limit <= had + 1)
    if not more and not spec.get("unreadable"):
        return spec, [], None
    if languages.code(spec.get("film_language") or "en") != languages.code(film_language or "en"):
        sys.exit(f"Can't add to {Path(notes_path).name}: it was written for a film in another language. "
                 f"Use --force to start again.")
    if spec.get("subtitles") and same_subtitles(spec["subtitles"]) != same_subtitles(Path(srt_path).name):
        sys.exit(f"Can't add to {Path(notes_path).name}: it was written from {spec['subtitles']}, not "
                 f"{Path(srt_path).name}. Use --force to start again.")
    kept = [n for n in spec["notes"] if str(n.get("category", "")).lower() != "about these notes"]
    if not more:
        return spec, kept, None
    covered = make_ass.limit_cues(cues, had)
    if not covered:
        sys.exit(f"{Path(notes_path).name} covers none of these subtitles. Use --force to start again.")
    return spec, kept, covered[-1]["n"]


def generate(srt_path, notes_path, model=DEFAULT_MODEL, audience=None, title=None, language="English",
             assume_yes=False, key_file=None, api_url=API_URL, film_language=None, original_srt=None,
             limit=None, video_offset=None, effort=None, max_tokens=MAX_TOKENS, year=None, estimate_only=False,
             extend=False):
    """Write the notes file. With estimate_only, stop after the size and cost estimate: no API key is needed,
    nothing is sent and nothing is written (returns None). With extend, keep the notes already in the notes file
    (written with a shorter --limit) and write notes only for the lines after them: everything else in that file
    (the frames step's notes and record, the look settings) is kept too."""
    all_cues = make_ass.parse_srt(srt_path)
    if not all_cues:
        sys.exit(f"No subtitle cues found in {srt_path}")
    cues = make_ass.limit_cues(all_cues, limit)
    if not cues:
        sys.exit(f"No subtitle lines start in the first {make_ass.fmt_limit(limit)} of {srt_path}.")
    base = None                                  # with extend: the notes file being added to
    gaps = []                                    # with extend: (first, last) lines whose replies couldn't be read
    if extend and Path(notes_path).exists():
        base, kept_notes, kept_through = notes_to_extend(notes_path, srt_path, cues, film_language, limit)
        gaps = unreadable_parts(base, cues)
        if kept_through is None and not gaps:
            print(f"{Path(notes_path).name} already covers "
                  f"{('the first ' + make_ass.fmt_limit(limit)) if limit else 'the whole video'}: nothing to add, "
                  f"nothing sent.")
            return None if estimate_only else base
    key = None if estimate_only else load_key(key_file)     # fail early if there's no usable key
    title = title or Path(srt_path).stem
    situation, extra = subtitle_setup(cues, film_language, original_srt)
    audience = audience or (base or {}).get("audience") or default_audience(film_language, situation)
    if limit:
        print(f"Limited to the first {make_ass.fmt_limit(limit)}: {len(cues)} of {len(all_cues)} lines.")
    partial = Path(notes_path).with_suffix(".partial.json")
    earlier, through, unread = pick_up_choice(partial, srt_path, cues, film_language, limit,
                                              assume_yes or estimate_only)
    if through:
        gaps = []                                # picking up: they stay recorded (unread) for the next run to offer
    if base is not None and not through:
        earlier, through = kept_notes, kept_through or cues[-1]["n"]
        unread = [u for u in base.get("unreadable") or []      # outside what's asked (--limit): still recorded
                  if not isinstance(u, dict) or tuple((u.get("lines") or [None, None])[:2]) not in gaps]
        if kept_through:
            print(f"Keeping the {len(earlier)} notes for the first {make_ass.fmt_limit(base['limit'])} (up to line "
                  f"{through}); only the lines after them are sent.")
        if gaps:
            print(f"Sending again only the lines whose replies couldn't be read last time: "
                  f"{', '.join(f'{lo} to {hi}' for lo, hi in gaps)}.")
    # Parts are made from the lines not yet covered, so a pick-up or an addition never sends a line twice. (For a
    # stopped run that's the same split as the first time: a new part starts from nothing either way.)
    rest = [c for c in cues if c["n"] > through]
    all_parts = chunks(cues, extra)
    first = 1 + sum(1 for p in all_parts if p[-1]["n"] <= through)
    todo = chunks(rest, extra)
    parts = first - 1 + len(todo)
    again = [p for lo, hi in gaps for p in chunks([c for c in cues if lo <= c["n"] <= hi], extra)]
    send = [c for p in again for c in p] + rest
    if first > 1 and base is None:
        print(f"Picking up where the last run stopped: {len(earlier)} notes kept; part {first} of {parts} is next.")
    pieces = [estimate(p, extra) for p in again] + ([estimate(rest, extra)] if rest else [])
    n_send, est_in, est_out = [sum(x[i] for x in pieces) for i in range(3)] if pieces else (0, 0, 0)
    c = cost(model, est_in, est_out)
    print(f"Plan: {len(send)} lines in {n_send} request(s) to {model}; about {est_in:,} tokens in and "
          f"{est_out:,} out" + (f", roughly ${c:.2f} in API credits." if c is not None else "."))
    bal = usage.plan_note(c)
    per_request = None if c is None or not n_send else c / n_send           # for usage.guard, until real costs are known
    prompts.event("estimate", step="generate", model=model, lines=len(send), requests=n_send, input_tokens=est_in,
                  output_tokens=est_out, cost_usd=None if c is None else round(c, 4), limit=limit,
                  balance_usd=None if bal is None else bal["balance_usd"])
    if estimate_only:
        print("Estimate only: nothing was sent.")
        return None
    if send and not assume_yes:
        if not prompts.interactive():
            sys.exit("Not an interactive terminal, so add --yes to confirm sending the subtitles to the API.")
        if not prompts.confirm("Send the subtitle text to the Claude API now?", id="generate.send"):
            sys.exit("Cancelled; nothing was sent.")
    if base is not None:                         # adding to a notes file: keep it as it was, too
        backup = make_ass.unique_backup(notes_path)
        shutil.copy2(notes_path, backup)
        print(f"Kept a backup: {backup.name}")
    foreign = situation is not None
    system = SYSTEM.format(audience=audience, language=language, era_section=era_section(year),
                           cats=", ".join(FOREIGN_CATEGORIES if foreign else CATEGORIES),
                           language_section=(language_section(film_language, situation).replace("{language}", language)
                                             if foreign else ""),
                           examples=(ORIGINAL_EXAMPLES if situation == "original" else FOREIGN_EXAMPLES) if foreign
                           else ENGLISH_EXAMPLES)

    usage.begin(film=usage.film_name(notes_path), step="generate", per_request=per_request)
    notes, tin, tout, problems = list(earlier), 0, 0, []
    prev_tail = [c for c in cues if c["n"] <= through][-CONTEXT_LINES:]
    done_line = through                          # the last subtitle line whose part is finished
    done_parts = first - 1
    pending = [[p[0]["n"], p[-1]["n"]] for p in again]       # to send again, and not sent yet

    def save_partial():
        """After every part, so even a run that ends without warning (the window closed, the computer lost power)
        leaves what was paid for, and the next run can pick up there."""
        if notes:
            missing = unread + [{"lines": g} for g in pending]
            make_ass.write_text_safely(partial, json.dumps(
                {"notes": notes, "through_line": done_line, "subtitles": Path(srt_path).name,
                 "film_language": film_language, "limit": round(limit, 1) if limit else None, "model": model,
                 **({"unreadable": missing} if missing else {})},
                indent=1, ensure_ascii=False))

    def keep_partial():
        if notes:
            save_partial()
            print(f"\n  Stopped after part {done_parts} of {parts}. The {len(notes)} notes written so far "
                  f"were saved to {partial.name}; the next run offers to pick up from there.", flush=True)

    jobs = [(None, p) for p in again] + list(enumerate(todo, first))       # (part number, or None: sent again)
    done_before = first - 1 if todo else 0
    total = done_before + len(jobs)
    try:
        for i, (k, part) in enumerate(jobs):
            lo, hi = part[0]["n"], part[-1]["n"]
            stop = usage.guard(assume_yes)
            if stop:                             # about to run out of credit: keep what was paid for, then say so
                keep_partial()
                sys.exit(stop)
            prompts.progress("generate", done_before + i, total, "requests")    # before the line below (stays open)
            if k is None:                        # lines whose reply couldn't be read before: only earlier context
                number = next((j for j, p in enumerate(all_parts, 1) if p[0]["n"] <= lo <= p[-1]["n"]), 1)
                print(f"  part {number}/{len(all_parts)} again: lines {lo}-{hi} ...", end=" ", flush=True)
                before = [n for n, line in zip(notes, note_lines(cues, notes)) if line is not None and line < lo]
                message = user_message(title, part, [c for c in cues if c["n"] < lo][-CONTEXT_LINES:], before,
                                       number, len(all_parts), extra)
            else:
                number = k
                print(f"  part {k}/{parts}: lines {lo}-{hi} ...", end=" ", flush=True)
                message = user_message(title, part, prev_tail, notes, k, parts, extra)
            try:
                reply = call_api(key, model, system, message, api_url, max_tokens=max_tokens, effort=effort)
            except SystemExit:                               # an API error: keep what was paid for
                keep_partial()
                raise
            used = reply.get("usage", {})        # (not `usage`: that's the module)
            tin += used.get("input_tokens", 0)
            tout += used.get("output_tokens", 0)
            if reply.get("stop_reason") == "refusal":
                problems.append(f"part {number}: the model declined to write notes for these lines")
            text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
            raw_notes = extract_objects(text)
            kept, part_notes = 0, []
            for r in raw_notes:
                note, why = check_note(r, cues, lo, hi)
                if note is None:
                    problems.append(f"part {number}: dropped a note ({why})")
                    continue
                if why:
                    problems.append(f"part {number}: {why}")
                part_notes.append(note)
                kept += 1
            if reply.get("stop_reason") == "max_tokens":
                problems.append(f"part {number}: reply was cut off, so later notes in this part may be missing")
            if not raw_notes and text.strip() not in ("[]", ""):
                bad = failed_reply_path(notes_path, number)
                bad.write_text(text, encoding="utf-8")
                problems.append(f"part {number}: couldn't read the reply; saved it to {bad.name}")
                unread.append({"lines": [lo, hi], "reply": bad.name})       # the next run offers to send it again
            print(f"{kept} notes")
            if k is None:
                notes = insert_in_order(cues, notes, part_notes, hi)      # in film order: the build relies on it
                pending.remove([lo, hi])
                save_partial()
                usage.report()                   # once the part is counted and saved, never before
                continue
            prev_tail = part[-CONTEXT_LINES:]
            notes.extend(part_notes)             # a part counts once all of it is in, so a stop never splits one
            done_line, done_parts = hi, k
            if k < parts:
                save_partial()
            usage.report()
    except KeyboardInterrupt:                    # Ctrl-C, or a GUI's Cancel, at any point: keep what was paid for
        keep_partial()
        raise
    prompts.progress("generate", total, total, "requests")

    ms = int(round(cues[0]["start"] * 1000))
    earlier_model = (base or {}).get("generated_by")
    by = model if not earlier_model or earlier_model == model else f"{earlier_model} and {model}"
    intro = {"at": f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}",
             "category": "About these notes", "duration": 9, "kind": "speech",
             "text": f"Alpha context notes written by Claude ({by}) for this viewer: {audience.rstrip('.')}. "
                     "Each note appears just after its line. “(less sure)” means: check me."
                     + (f" These notes cover only the first {make_ass.fmt_limit(limit)}." if limit else "")}
    spec = dict(base or {})                      # adding to a notes file: keep everything else in it
    spec.update({"title": f"{title} (context notes)", "audience": audience,
                 "scope": spec.get("scope") or "Dialogue notes written from the subtitles only (no video or audio "
                                               "was analysed)",
                 "generated_by": by, "subtitles": Path(srt_path).name})
    if video_offset is not None:
        spec["video_offset"] = round(float(video_offset), 2)
    if foreign:
        spec["film_language"] = languages.code(film_language)
        if original_srt:
            spec["original_subtitles"] = Path(original_srt).name
    spec.pop("limit", None)
    if limit:
        spec["limit"] = round(limit, 1)
    if year:
        spec["year"] = int(year)
    spec.pop("notes", None)
    spec.pop("unreadable", None)
    if unread:
        spec["unreadable"] = unread              # lines with no notes yet: the next run offers to send them again
    spec["notes"] = [intro] + notes
    make_ass.write_text_safely(notes_path, json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
    try:
        partial.unlink()                         # its notes are in the notes file now
    except OSError:
        pass

    actual = cost(model, tin, tout)
    print(f"Wrote {len(notes)} notes -> {notes_path}")
    print(f"Used {tin:,} input and {tout:,} output tokens" + (f" (about ${actual:.2f})." if actual is not None else "."))
    usage.finish()
    for p in problems:
        print("  ! " + p)
    if unread:
        print(f"  The lines of {len(unread)} part(s) have no notes yet. The next run offers to send just those again "
              f"(by hand: the same make_ass.py command with --generate --extend).")
    if not notes:
        sys.exit("No usable notes came back.")
    return spec


if __name__ == "__main__":
    if "--set-api-key" in sys.argv:
        set_key()
    else:
        sys.exit(__doc__)
