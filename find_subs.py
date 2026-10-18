#!/usr/bin/env python3
"""
find_subs.py - find subtitles for a video that has none beside it.

    python3 find_subs.py film.mkv                      English subtitles (or --lang de, fr, ...)
    python3 find_subs.py film.mkv --lang de --online   also search OpenSubtitles.com
    python3 find_subs.py film.mkv --transcribe         no subtitles anywhere: make some with speech recognition
    python3 find_subs.py film.mkv --transcribe --limit 10:00   try speech recognition on the first 10 minutes
    python3 find_subs.py --set-opensubtitles           once: save your OpenSubtitles.com login (and test it)
    python3 find_subs.py --test-opensubtitles          check the saved login works (uses no downloads)

Where it looks, in order (context_notes.py does the same when a video has no subtitles):
  1. Nearby files: a Subs/ or Subtitles/ folder beside the video (Subs/2_English.srt, Subs/<film>/English.srt,
     the usual release layouts), and .srt files beside it named for the same film but not exactly like it
     (Das.Boot.1981.Directors.Cut.srt next to "Das Boot (1981).mkv").
  2. OpenSubtitles.com, if you've saved a login (free account; the API allows a handful of downloads a day).
     Subtitles uploaded for your exact file (matched by its fingerprint, the "movie hash") come first: those
     are timed for this release, so the sync check usually has nothing to fix.
  3. Speech recognition (faster-whisper, local, free, slow): writes subtitles from the soundtrack itself.
     The timing is right by construction; the words are whatever the recogniser heard, so names and mumbled
     lines can be wrong. Good enough to hang notes on; real subtitles are better.

Whatever it finds is COPIED beside the video as <video name>.<lang>.srt (downloads and transcripts are written
there directly), so every other script picks it up. Nothing is moved or changed where it was found.
"""
import argparse
import getpass
import json
import os
import re
import shutil
import stat
import struct
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import languages  # noqa: E402
import make_ass  # noqa: E402

SUB_DIRS = re.compile(r"^(subs?|subtitles?|untertitel|sous[- ]titres|subtitulos)$", re.I)
JUNK = re.compile(r"\b(2160p|1080p|720p|576p|480p|bluray|blu-ray|brrip|bdrip|web-?dl|webrip|web|hdtv|dvdrip|remux|x264|"
                  r"x265|h\.?264|h\.?265|hevc|aac\d?(\.\d)?|ac3|dts(-hd)?|ddp?\d?(\.\d)?|atmos|truehd|10bit|hdr|proper|"
                  r"repack|extended|unrated|restored|remastered|directors?\.?cut|dc|uncut|yts|yify|rarbg|internal)\b",
                  re.I)
OS_API = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "context-notes v0.4"


def say(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- 1. nearby files
def title_key(name):
    """'Das.Boot.1981.Directors.Cut.1080p.BluRay.x264' and 'Das Boot (1981)' -> 'das boot 1981'. Everything after
    the year is dropped (release details live there); without a year, the usual release words are."""
    s = unicodedata.normalize("NFC", name)
    s = re.sub(r"\.(srt|mkv|mp4|m4v|mov|avi|webm|ts|m2ts|mpg|mpeg|wmv)$", "", s, flags=re.I)
    s = re.sub(r"[._\-\[\]()]+", " ", s)
    m = re.search(r"\b(19[0-9]{2}|20[0-9]{2})\b", s)
    if m:
        s = s[:m.end()]
    e = re.search(r"(?<![0-9a-z])s?\d{1,2}[ex]\d{2}(?![0-9])", s, re.I)
    if e:
        s = s[:e.start()]                              # 'Blackadder S01E02 Head' -> 'blackadder'; episodes go by code
    s = JUNK.sub(" ", s)
    return re.sub(r"\s+", " ", make_ass.fold(s)).strip()


def show_key(video):
    """The title to search by. Episodes named only 'S02E03 Moss and the German.mp4' take the show's name from the
    folders above, skipping 'Season 2' and the like."""
    key = title_key(video.name)
    for folder in [video.parent, *video.parent.parents][:3]:
        if key:
            break
        if not re.fullmatch(r"(season|series|staffel|saison|temporada|s)\s*\d+|disc\s*\d+", folder.name.strip(), re.I):
            key = title_key(folder.name)
    return key


def episode_code(name):
    m = re.search(r"(?<![0-9a-z])s?(\d{1,2})[ex](\d{2})(?![0-9])", name.lower())
    return (int(m.group(1)), int(m.group(2))) if m else None


def lang_of(path):
    """Language of a subtitle file from its name ('2_English.srt', 'ger.srt', 'Film.de.srt'), else its text.
    Two-letter codes count only as the last part of the name, since 'de', 'it' and 'no' are also words."""
    parts = [x for x in re.split(r"[._\-\s]+", Path(path).stem.lower()) if x]
    for k, part in enumerate(parts):
        c = languages.code(part)
        if c in languages.LANGUAGES and (len(part) > 2 or k == len(parts) - 1):
            return c
    try:
        return languages.guess(" ".join(c["text"] for c in make_ass.parse_srt(path)[:300]))
    except (OSError, ValueError):
        return None


def nearby(video):
    """Candidate .srt files near a video, best first: [(path, lang, why)]."""
    video = Path(video)
    folder, key, ep = video.parent, title_key(video.name), episode_code(video.name)

    def listdir(d):
        try:
            return sorted(d.iterdir())
        except OSError:                                # unreadable folder: just skip it
            return []
    videos_here = [p for p in listdir(folder) if p.is_file() and p.suffix.lower() in
                   {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".ts", ".m2ts", ".mpg", ".mpeg", ".wmv"}]
    alone = len(videos_here) == 1

    def same_film(name):
        """Named for this film or episode. With one video in the folder anything goes; with several, a file named
        for no film in particular (2_English.srt) can't be told apart, so it isn't taken."""
        return (title_key(name) == key and bool(key)) or (ep is not None and episode_code(name) == ep) or alone
    found = []

    def consider(p, why):
        if p.suffix.lower() != ".srt" or p.name.startswith("."):
            return
        if re.search(r"\.aligned(\.first\d+s)?\.srt$|\.transcribed(\.first\d+s)?\.srt$", p.name):
            return                                     # our own derived files
        pep = episode_code(p.name) or episode_code(p.parent.name)
        if ep and pep and pep != ep:
            return                                     # another episode's subtitles
        found.append((p, why))

    # beside the video: same film, differently named
    for p in listdir(folder):
        if p.suffix.lower() != ".srt" or make_ass.fold(p.name).startswith(make_ass.fold(video.stem) + "."):
            continue                                   # already the normal name; context_notes.py sees it
        if same_film(p.name):
            consider(p, "beside the video" + (" (the only video here)" if alone and title_key(p.name) != key else ""))
    # Subs/ folders: Subs/*.srt, Subs/<film or episode>/*.srt
    for d in (x for x in listdir(folder) if x.is_dir() and SUB_DIRS.match(x.name)):
        for p in listdir(d):
            if p.is_file() and same_film(p.name):
                consider(p, f"in {d.name}/")
        for sub in (x for x in listdir(d) if x.is_dir()):
            if same_film(sub.name) or make_ass.fold(sub.name) == make_ass.fold(video.stem):
                for p in listdir(sub):
                    if p.is_file():
                        consider(p, f"in {d.name}/{sub.name}/")
    out = []
    for p, why in found:
        out.append((p, lang_of(p), why))
    return out


def rank(p):
    """Prefer full dialogue (not forced/SDH) and more lines."""
    name = p.name.lower()
    forced = "forced" in name
    sdh = bool(re.search(r"\b(sdh|hi|cc)\b|hearing", re.sub(r"[._\-]", " ", name)))
    try:
        lines = len(make_ass.parse_srt(p))
    except (OSError, ValueError):
        lines = 0
    return (forced, sdh, -lines)


def pick_nearby(video, lang):
    cands = [(p, lg, why) for p, lg, why in nearby(video) if languages.same(lg, lang)]
    if not cands:
        return None, ""
    cands.sort(key=lambda c: rank(c[0]))
    p, _, why = cands[0]
    if rank(p)[0]:
        return None, ""                                # only "forced" subtitles: signs and foreign bits, not dialogue
    return p, why


def place_beside(video, src, lang):
    """Copy src beside the video as <stem>.<lang>.srt (never overwriting); returns the new path."""
    video = Path(video)
    dest = video.with_name(f"{video.stem}.{lang}.srt")
    if dest.exists():
        return dest
    shutil.copy2(src, dest)
    return dest


# ---------------------------------------------------------------- 2. OpenSubtitles.com
def os_config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "context-notes" / "opensubtitles.json"


def os_set_login():
    """Prompt for the OpenSubtitles.com API key and login; store them readable only by this user."""
    say("You need a free account at https://www.opensubtitles.com and an API key from "
        "https://www.opensubtitles.com/consumers (\"New consumer\").")
    api_key = getpass.getpass("API key (hidden): ").strip()
    user = input("Username: ").strip()
    pw = getpass.getpass("Password (hidden): ")
    if not (api_key and user and pw):
        sys.exit("Something was left empty; nothing saved.")
    path = os_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"api_key": api_key, "username": user, "password": pw}, f)
    os.chmod(path, 0o600)
    say(f"Saved to {path} (readable only by you).")
    return os_test(os_load())


def os_test(cfg, api=OS_API):
    """Log in with the saved login and show the account's downloads for today. Uses no downloads. True if it works."""
    if not cfg:
        say("No usable OpenSubtitles login saved. Save one with:  python3 find_subs.py --set-opensubtitles")
        return False
    say("Logging in to OpenSubtitles.com...")
    client = OpenSubtitles(cfg, api)
    try:
        client.login()
    except OpenSubtitlesError as e:
        hint = {401: "The username or password was refused.",
                403: "The API key was refused (check it at https://www.opensubtitles.com/consumers).",
                429: "Too many tries just now; wait a minute and test again."}.get(e.code, "")
        say(f"  ! Login failed. {hint}\n    ({e})")
        if e.code in (401, 403):
            say("    Fix it with:  python3 find_subs.py --set-opensubtitles")
        return False
    except RuntimeError as e:
        say(f"  ! Login failed: {e}")
        return False
    say(f"  OK: logged in as {cfg['username']}; the API key and password work.")
    try:
        info = client._req("GET", "/infos/user", auth=True).get("data") or {}
    except RuntimeError as e:
        say(f"  (Couldn't read the account's download count: {e})")
        return True
    if info.get("remaining_downloads") is not None:
        say(f"  Downloads left today: {info['remaining_downloads']} of {info.get('allowed_downloads', '?')}"
            + (f" ({info['level']} account)" if info.get("level") else "") + ".")
    return True


def os_load():
    """The saved login, or None if there isn't one (or it can't be used: says why)."""
    path = os_config_path()
    if not path.exists():
        return None
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        say(f"  ! Not using {path}: other users can read it. Lock it down:  chmod 600 \"{path}\"")
        return None
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        say(f"  ! {path} isn't valid JSON; run  python3 find_subs.py --set-opensubtitles  again.")
        return None
    if not isinstance(cfg, dict) or not all(cfg.get(k) for k in ("api_key", "username", "password")):
        say(f"  ! {path} is missing api_key, username or password.")
        return None
    return cfg


def movie_hash(path):
    """OpenSubtitles' file fingerprint: size plus the sum of the first and last 64 KB read as 64-bit numbers."""
    size = os.path.getsize(path)
    if size < 65536 * 2:
        return None
    h = size
    with open(path, "rb") as f:
        for where in (0, size - 65536):
            f.seek(where)
            for (v,) in struct.iter_unpack("<Q", f.read(65536)):
                h = (h + v) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


class OpenSubtitlesError(RuntimeError):
    """OpenSubtitles answered with an HTTP error; `code` is its status (401, 403, 429...)."""
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


class OpenSubtitles:
    def __init__(self, cfg, api=OS_API):
        self.cfg, self.api, self.token = cfg, api.rstrip("/"), None

    def _req(self, method, path, params=None, body=None, auth=False, base=None):
        url = (base or self.api) + path
        if params:
            # the API wants parameters sorted and lower-case, or it redirects
            url += "?" + urllib.parse.urlencode(sorted((k.lower(), str(v).lower()) for k, v in params.items()))
        headers = {"Api-Key": self.cfg["api_key"], "User-Agent": USER_AGENT, "Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise OpenSubtitlesError(f"OpenSubtitles said {e.code}: {detail}", e.code) from None
        except urllib.error.URLError as e:
            raise RuntimeError(f"couldn't reach OpenSubtitles ({e.reason})") from None
        except (OSError, ValueError) as e:             # timeouts, dropped connections, a reply that isn't JSON
            raise RuntimeError(f"OpenSubtitles didn't answer properly ({e})") from None

    def login(self):
        r = self._req("POST", "/login", body={"username": self.cfg["username"], "password": self.cfg["password"]})
        self.token = r.get("token")
        if not self.token:
            raise RuntimeError("login failed (no token came back)")
        base = r.get("base_url")
        if base and base not in self.api:
            self.api = f"https://{base}/api/v1" if not base.startswith("http") else base.rstrip("/") + "/api/v1"

    def search(self, lang, moviehash=None, query=None, year=None, season=None, episode=None):
        params = {"languages": lang}
        if moviehash:
            params["moviehash"] = moviehash
        if query:
            params["query"] = query
        if year:
            params["year"] = year
        if season is not None:
            params["season_number"] = season
            params["episode_number"] = episode
        return self._req("GET", "/subtitles", params=params).get("data", [])

    def download(self, file_id):
        if not self.token:
            self.login()
        r = self._req("POST", "/download", body={"file_id": file_id}, auth=True)
        link = r.get("link")
        if not link:
            raise RuntimeError(f"no download link came back ({r.get('message') or r})")
        req = urllib.request.Request(link, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read(), r.get("remaining")
        except (OSError, ValueError) as e:             # URLError and HTTPError are OSErrors
            raise RuntimeError(f"the download failed ({e})") from None


def choose(results):
    """Best search result: made for this exact file first, then not machine/AI-translated, not SDH, most downloaded."""
    def score(r):
        a = r.get("attributes", {})
        return (not a.get("moviehash_match"), bool(a.get("machine_translated") or a.get("ai_translated")),
                bool(a.get("hearing_impaired")), -int(a.get("download_count") or 0))
    usable = [r for r in results if (r.get("attributes") or {}).get("files")]
    return sorted(usable, key=score)[0] if usable else None


def search_online(video, lang, cfg, api=OS_API, ask=None):
    """Search OpenSubtitles, ask, download beside the video. Returns the new path or None."""
    video = Path(video)
    client = OpenSubtitles(cfg, api)
    h = movie_hash(video)
    key = show_key(video)
    m = re.search(r"\b(19|20)\d{2}$", key)
    year = m.group(0) if m else None
    query = key[:m.start()].strip() if m else key
    ep = episode_code(video.name)
    try:
        results = client.search(lang, moviehash=h) if h else []
        exact = [r for r in results if r.get("attributes", {}).get("moviehash_match")]
        if not exact:
            results = client.search(lang, query=query, year=year, season=ep[0] if ep else None,
                                    episode=ep[1] if ep else None) + results
        best = choose(exact or results)
        if best is None:
            say(f"  OpenSubtitles has no {languages.name(lang)} subtitles for “{query}”" + (f" ({year})" if year else "") + ".")
            return None
        a = best["attributes"]
        what = (f"“{a.get('release') or a['files'][0].get('file_name')}”, {int(a.get('download_count') or 0):,} downloads"
                + ("; made for this exact file" if a.get("moviehash_match") else "; NOT matched to your exact file, so "
                   "the sync check may need to fix the timing"))
        say(f"  OpenSubtitles: {what}")
        if ask and ask("  Download it (uses one of your daily downloads)?") != "y":
            return None
        data, remaining = client.download(a["files"][0]["file_id"])
    except RuntimeError as e:
        say(f"  ! {e}")
        return None
    dest = video.with_name(f"{video.stem}.{lang}.srt")
    if dest.exists():
        dest = video.with_name(f"{video.stem}.{lang}.opensubtitles.srt")
    check = video.with_name(f"{video.stem}.{lang}.download-unchecked")
    check.write_bytes(data)
    if not make_ass.parse_srt(check):
        bad = check.with_name(check.name.replace("-unchecked", "-unreadable"))
        check.replace(bad)
        say(f"  ! The download isn't a readable .srt file; left it as {bad.name} for you to look at.")
        return None
    check.replace(dest)
    say(f"  Saved {dest.name}" + (f" ({remaining} downloads left today)" if remaining is not None else ""))
    return dest


# ---------------------------------------------------------------- 3. speech recognition
def transcript_to_cues(asr, max_chars=84, max_len=6.0, pause=0.7):
    """Subtitle-sized lines from a word-timed transcript: a new line at a pause, at the end of a sentence once a
    line is 2 s long, or when it gets too long to read in one go."""
    cues, cur = [], []

    def flush():
        if cur:
            text = "".join(w for _, _, w in cur).strip()
            if text:
                cues.append({"start": cur[0][0], "end": max(cur[-1][1], cur[0][0] + 1.0), "text": wrap(text)})
            cur.clear()
    for seg in asr:
        for s, e, w in seg.get("w") or [[seg["s"], seg["e"], seg["t"]]]:
            if cur and (s - cur[-1][1] > pause or e - cur[0][0] > max_len
                        or len("".join(x[2] for x in cur)) + len(w) > max_chars):
                flush()
            cur.append((s, e, w))
            if cur and re.search(r"[.!?…]$", w.strip()) and e - cur[0][0] >= 2.0:
                flush()
        flush()
    for k in range(len(cues) - 1):                       # never overlap the next line
        cues[k]["end"] = min(cues[k]["end"] + 0.5, cues[k + 1]["start"] - 0.05)
    return cues


def wrap(text, width=42):
    """Two lines at most, broken near the middle."""
    if len(text) <= width:
        return text
    mid = len(text) // 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return text
    cut = min(spaces, key=lambda i: abs(i - mid))
    return text[:cut] + "\n" + text[cut + 1:]


def transcribe_subs(video, lang, model=None, limit=None):
    """Write <video>.<lang>.transcribed.srt from speech recognition (reusing analyze.py's cached transcript)."""
    import analyze
    video = Path(video)
    analyze.need_ffmpeg()
    folder = video.parent / f"{video.stem} analysis"
    folder.mkdir(exist_ok=True)
    _, astream, _ = analyze.probe(video)
    name = analyze.whisper_model(lang, model)
    cache = analyze.transcript_cache(folder, name, lang, limit)
    say(f"  Transcribing with speech recognition ({name}, {languages.name(lang)}); local and free, but slow: very "
        f"roughly a tenth of the running time.")
    asr = analyze.transcribe(video, astream, name, cache, language=lang, limit=limit)
    cues = transcript_to_cues(asr)
    if not cues:
        return None
    dest = video.with_name(f"{video.stem}.{lang}.transcribed{'.first' + str(int(round(limit))) + 's' if limit else ''}.srt")
    analyze.write_srt(cues, {i: 0.0 for i in range(len(cues))}, dest)
    say(f"  Wrote {dest.name}: {len(cues)} lines heard in the soundtrack (names and mumbled lines may be wrong).")
    return dest


def have_whisper():
    try:
        import importlib.util
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


# ---------------------------------------------------------------- all three
def find(video, lang, online=None, transcribe=None, ask=None, model=None, limit=None):
    """Try nearby files, then OpenSubtitles (if a login is saved and `online` isn't False), then speech recognition
    (if `transcribe` isn't False). `ask(question) -> 'y'/'n'` is asked before downloading or transcribing; with
    online/transcribe True those steps run without asking. Returns the .srt beside the video, or None."""
    video = Path(video)
    name = languages.name(lang)
    p, why = pick_nearby(video, lang)
    if p:
        dest = place_beside(video, p, lang)
        say(f"Found {name} subtitles {why}: {p.name}. Copied beside the video as {dest.name}.")
        return dest
    cfg = os_load() if online is not False else None
    if cfg:
        say(f"Searching OpenSubtitles.com for {name} subtitles...")
        got = search_online(video, lang, cfg, ask=None if online else ask)
        if got:
            return got
    elif online:
        say("  (No OpenSubtitles login saved: python3 find_subs.py --set-opensubtitles)")
    if transcribe is False:
        return None
    if not have_whisper():
        say("  Speech recognition could write subtitles from the soundtrack, but it needs faster-whisper:  "
            "pip3 install -r requirements-align.txt")
        return None
    if transcribe or (ask and ask(f"No {name} subtitles found. Write them from the soundtrack with speech recognition "
                                  f"(local, free, slow)?") == "y"):
        return transcribe_subs(video, lang, model, limit)
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", nargs="?")
    ap.add_argument("--lang", default="en", help="language of the subtitles wanted (default en)")
    ap.add_argument("--online", action="store_true", help="search OpenSubtitles.com without asking first")
    ap.add_argument("--offline", action="store_true", help="don't search online")
    ap.add_argument("--transcribe", action="store_true", help="write subtitles with speech recognition if nothing is found")
    ap.add_argument("--model", help="speech model for --transcribe (default: base.en, or small for other languages)")
    ap.add_argument("--limit", type=make_ass.duration_arg, metavar="TIME",
                    help="speech recognition on only the first part, e.g. 10:00, 600 or 10m, to try it quickly "
                         "(10:00 writes <video>.<lang>.transcribed.first600s.srt)")
    ap.add_argument("--list", action="store_true", help="just list subtitle files found nearby, and stop")
    ap.add_argument("--set-opensubtitles", action="store_true", help="save your OpenSubtitles.com login, test it and exit")
    ap.add_argument("--test-opensubtitles", action="store_true",
                    help="check the saved OpenSubtitles.com login works (uses none of your downloads) and exit")
    a = ap.parse_args(argv)
    if a.set_opensubtitles:
        return 0 if os_set_login() else 1
    if a.test_opensubtitles:
        return 0 if os_test(os_load()) else 1
    if not a.video:
        ap.error("the video is required")
    video = Path(a.video)
    if not video.exists():
        sys.exit(f"Can't find {video}")
    lang = languages.code(a.lang) or "en"
    if a.list:
        rows = nearby(video)
        for p, lg, why in rows:
            say(f"  {p}  ({languages.name(lg) if lg else 'language unclear'}, {why})")
        if not rows:
            say("  Nothing nearby.")
        return 0

    def ask(q):
        if not sys.stdin.isatty():
            return "n"
        return "y" if input(f"{q} [y/N] ").strip().lower() in ("y", "yes") else "n"
    got = find(video, lang, online=False if a.offline else (True if a.online else None),
               transcribe=True if a.transcribe else None, ask=ask, model=a.model, limit=a.limit)
    if not got:
        say(f"No {languages.name(lang)} subtitles found for {video.name}.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
