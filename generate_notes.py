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
import getpass
import json
import os
import re
import stat
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import languages
import make_ass

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


# ---------------------------------------------------------------- API key
def config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "context-notes"


def key_path():
    return config_dir() / "api-key"


def set_key():
    """Prompt (hidden) for the API key and store it where only this user can read it."""
    path = key_path()
    key = getpass.getpass("Paste your Anthropic API key (input is hidden), then press Return: ").strip()
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
def call_api(key, model, system, user, url=API_URL, timeout=300, max_tokens=MAX_TOKENS, effort=None):
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
                return json.load(r)
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
            sys.exit(f"API error {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < 3:
                print(f"    network problem ({e}); retrying...")
                time.sleep(2 ** (attempt + 1))
                continue
            sys.exit(f"Couldn't reach the API: {e}")


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

{language_section}Tone and length to aim for (examples from another episode):
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


def generate(srt_path, notes_path, model=DEFAULT_MODEL, audience=None, title=None, language="English",
             assume_yes=False, key_file=None, api_url=API_URL, film_language=None, original_srt=None,
             limit=None, video_offset=None, effort=None, max_tokens=MAX_TOKENS):
    all_cues = make_ass.parse_srt(srt_path)
    if not all_cues:
        sys.exit(f"No subtitle cues found in {srt_path}")
    cues = make_ass.limit_cues(all_cues, limit)
    if not cues:
        sys.exit(f"No subtitle lines start in the first {make_ass.fmt_limit(limit)} of {srt_path}.")
    key = load_key(key_file)                    # fail early if there's no usable key
    title = title or Path(srt_path).stem
    situation, extra = subtitle_setup(cues, film_language, original_srt)
    audience = audience or default_audience(film_language, situation)
    if limit:
        print(f"Limited to the first {make_ass.fmt_limit(limit)}: {len(cues)} of {len(all_cues)} lines.")
    parts, est_in, est_out = estimate(cues, extra)
    c = cost(model, est_in, est_out)
    print(f"Plan: {len(cues)} lines in {parts} request(s) to {model}; about {est_in:,} tokens in and "
          f"{est_out:,} out" + (f", roughly ${c:.2f} in API credits." if c is not None else "."))
    if not assume_yes:
        if not sys.stdin.isatty():
            sys.exit("Not an interactive terminal, so add --yes to confirm sending the subtitles to the API.")
        if input("Send the subtitle text to the Claude API now? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Cancelled; nothing was sent.")
    foreign = situation is not None
    system = SYSTEM.format(audience=audience, language=language,
                           cats=", ".join(FOREIGN_CATEGORIES if foreign else CATEGORIES),
                           language_section=(language_section(film_language, situation).replace("{language}", language)
                                             if foreign else ""),
                           examples=(ORIGINAL_EXAMPLES if situation == "original" else FOREIGN_EXAMPLES) if foreign
                           else ENGLISH_EXAMPLES)

    notes, tin, tout, problems = [], 0, 0, []
    prev_tail = []
    for k, part in enumerate(chunks(cues, extra), 1):
        lo, hi = part[0]["n"], part[-1]["n"]
        print(f"  part {k}/{parts}: lines {lo}-{hi} ...", end=" ", flush=True)
        try:
            reply = call_api(key, model, system, user_message(title, part, prev_tail, notes, k, parts, extra), api_url,
                             max_tokens=max_tokens, effort=effort)
        except SystemExit:
            if notes:
                keep = Path(notes_path).with_suffix(".partial.json")
                keep.write_text(json.dumps({"notes": notes}, indent=1, ensure_ascii=False), encoding="utf-8")
                print(f"\n  Stopped after part {k - 1} of {parts}. The {len(notes)} notes written so far "
                      f"were saved to {keep.name}.")
            raise
        usage = reply.get("usage", {})
        tin += usage.get("input_tokens", 0)
        tout += usage.get("output_tokens", 0)
        if reply.get("stop_reason") == "refusal":
            problems.append(f"part {k}: the model declined to write notes for these lines")
        text = "".join(b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text")
        raw_notes = extract_objects(text)
        kept = 0
        for r in raw_notes:
            note, why = check_note(r, cues, lo, hi)
            if note is None:
                problems.append(f"part {k}: dropped a note ({why})")
                continue
            if why:
                problems.append(f"part {k}: {why}")
            notes.append(note)
            kept += 1
        if reply.get("stop_reason") == "max_tokens":
            problems.append(f"part {k}: reply was cut off, so later notes in this part may be missing")
        if not raw_notes and text.strip() not in ("[]", ""):
            bad = Path(notes_path).with_suffix(f".part{k}.failed.txt")
            bad.write_text(text, encoding="utf-8")
            problems.append(f"part {k}: couldn't read the reply; saved it to {bad.name}")
        print(f"{kept} notes")
        prev_tail = part[-CONTEXT_LINES:]

    ms = int(round(cues[0]["start"] * 1000))
    intro = {"at": f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}",
             "category": "About these notes", "duration": 9, "kind": "speech",
             "text": f"Pre-alpha context notes written by Claude ({model}) for this viewer: {audience.rstrip('.')}. "
                     "Each note appears just after its line. “(less sure)” means: check me."
                     + (f" These notes cover only the first {make_ass.fmt_limit(limit)}." if limit else "")}
    spec = {"title": f"{title} (context notes)", "audience": audience,
            "scope": "Dialogue notes written from the subtitles only (no video or audio was analysed)",
            "generated_by": model}
    if video_offset is not None:
        spec["video_offset"] = round(float(video_offset), 2)
    if foreign:
        spec["film_language"] = languages.code(film_language)
        if original_srt:
            spec["original_subtitles"] = Path(original_srt).name
    if limit:
        spec["limit"] = round(limit, 1)
    spec["notes"] = [intro] + notes
    Path(notes_path).write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    actual = cost(model, tin, tout)
    print(f"Wrote {len(notes)} notes -> {notes_path}")
    print(f"Used {tin:,} input and {tout:,} output tokens" + (f" (about ${actual:.2f})." if actual is not None else "."))
    for p in problems:
        print("  ! " + p)
    if not notes:
        sys.exit("No usable notes came back.")
    return spec


if __name__ == "__main__":
    if "--set-api-key" in sys.argv:
        set_key()
    else:
        sys.exit(__doc__)
