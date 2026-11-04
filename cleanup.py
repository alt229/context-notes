#!/usr/bin/env python3
"""
cleanup.py - plan tidy, standard names for a film or TV library, the way Plex, Jellyfin and Emby name them.
Created 2026-11-04, modified 2026-11-04.

    python3 cleanup.py "/Volumes/Media/Movies"          list what each film would be renamed to, ask, then do it
    python3 cleanup.py "/Volumes/Media/Movies" --dry-run   only list
    python3 cleanup.py "/Volumes/Media/Movies" --only Akira --only "Life of Brian"   just these (part of the path)
    python3 cleanup.py "/Volumes/Media/TV Shows"        the same for shows: Show (Year)/Season 01/...
    python3 cleanup.py "/Volumes/Media/Movies" --language de-DE   titles in German (default: this computer's language)
    python3 cleanup.py "/Volumes/Media/Movies" --offline          names only, no TMDB look-ups
    python3 cleanup.py "/Volumes/Media/Movies" --set-title 10162 "Waking Ned Devine"   your title for TMDB's film 10162
    python3 cleanup.py --undo ~/.config/context-notes/cleanup/<log>.jsonl            put everything back

Nothing is deleted. Every rename is written to an undo log (~/.config/context-notes/cleanup/) the moment it's done,
so a run that's stopped part way can be put back with --undo. Videos on the "decide by hand" list aren't touched.

The names it plans:
    Movies/Life of Brian (1979) {tmdb-583}/Life of Brian (1979) {tmdb-583}.mkv
    TV Shows/Doctor Who (2005) {tmdb-57243}/Season 05/Doctor Who (2005) - s05e03 - Victory of the Daleks.mkv
Everything named after a video moves with it (its subtitles, .notes.ass, Behind the Scenes .ass, Plex copy, .nfo,
kept .original copy) and so does its context-notes folder. A film loose in the library folder gets a folder of its own.

How it knows what each video is: guessit reads the file and folder names (title, year, season, episode, edition,
part); ids already in the names or an .nfo are used as they are; then TMDB (python3 tmdb.py --set-key) confirms it
and gives the title in your language, the year and the episode titles. A video goes on the "decide by hand" list when
TMDB finds no film or more than one, when an episode sits in a films folder (or the other way round), when two
videos would get the same name, or when the new name is taken already.

In what order (Erin, 2026-11-04): a folder that holds one film (or one show) is renamed as a whole, so whatever else
is in it stays with it; then each video and the files named after it get their new names; its context-notes folder
follows it (the files in it renamed, the notes file's subtitle names updated, its date kept so nothing needs a
rebuild); then clutter (release notes, .url and .txt files, samples, screenshots) moves into the film's own
context-notes/removed/ (clutter of no film: the library's context-notes/removed/); last, folders left empty go.

What it sends to TMDB: the titles and years read from your file names, and the ids found. Nothing else.
"""
import argparse
import difflib
import json
import locale
import os
import re
import stat
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import fileio
import film_ids
import find_subs
import languages
import prompts  # the questions (and on Windows, lets a GUI's Cancel stop this script cleanly)
import tmdb
import workfiles
from subtitles import fold

TV_WORDS = re.compile(r"\b(tv|shows?|series|serien|séries|series de tv|episodes?)\b", re.I)
EXTRAS = {"behind the scenes", "deleted scenes", "featurettes", "interviews", "scenes", "shorts", "trailers", "other",
          "extras", "specials features"}
ARTWORK = {"poster", "folder", "cover", "fanart", "backdrop", "banner", "logo", "clearart", "landscape", "thumb",
           "disc", "background", "season-specials-poster"}
CLUTTER_EXTS = {".txt", ".url", ".website", ".lnk", ".exe", ".bat", ".nzb", ".torrent", ".sfv", ".md5", ".par2",
                ".nfo", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".html", ".htm", ".rtf", ".log"}
PARTIAL = re.compile(r"\.(part|crdownload|!qb|download|partial)$", re.I)   # a download's name until it finishes
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".sup", ".smi"}
SUB_REST = re.compile(r"\.([a-z]{2,3})((?:\.(?:forced|sdh|cc|hi))*)\.(srt|ass|ssa|vtt|sub|idx|sup|smi)$")
DISC_DIRS = {"bdmv", "video_ts"}          # a disc copied as it is: Plex can't play these folders
SAMPLE = re.compile(r"(^|[\W_])sample([\W_]|$)", re.I)
BAD_CHARS = str.maketrans({c: None for c in '?*"<>|'})
CHOICES = 3
JUNK = {".ds_store", "thumbs.db", "desktop.ini"}   # what a folder can hold and still count as empty
BUSY_SECONDS = 120                                 # a video changed this recently may still be being copied
NOTES_FIELDS = ("subtitles", "display_subtitles", "video")   # names in a notes file that follow the rename
PLEX_ADVICE = ("Before renaming, if Plex (or Jellyfin, Emby) shows this library: in Plex, Settings > Library, turn off "
               "\"Empty trash automatically after every scan\" until it has rescanned, so nothing is dropped from it "
               "(watch history stays with the film).")


def say(msg=""):
    print(msg, flush=True)


def guessit_or_exit():
    try:
        from guessit import guessit
    except ImportError:
        sys.exit("guessit isn't installed. Install it with:  python3 -m pip install -r requirements.txt")
    return guessit


# ---------------------------------------------------------------- names
def safe(text):
    """A name every system will take: 'Mission: Impossible' -> 'Mission - Impossible', no ? * " < > | / \\."""
    text = unicodedata.normalize("NFC", str(text))
    text = re.sub(r"\s*:\s*", " - ", text).replace("/", "-").replace("\\", "-").translate(BAD_CHARS)
    return re.sub(r"\s+", " ", text).strip().rstrip(". ")


def computer_language():
    """'de-DE' from the computer's settings; 'en-US' when they don't say."""
    for value in (os.environ.get("LC_ALL"), os.environ.get("LANG"), (locale.getlocale() or [None])[0]):
        m = re.match(r"([a-z]{2})[_-]([A-Z]{2})", value or "")
        if m and value not in ("C", "POSIX"):
            return f"{m.group(1)}-{m.group(2)}"
    return "en-US"


def words(text):
    """'The Lord Of The Rings: The Two Towers' -> 'the lord of the rings the two towers'. Letters of every script
    count, so a Japanese title with 'AKIRA' in it isn't the same as 'Akira'."""
    return " ".join(re.sub(r"[\W_]+", " ", fold(str(text or "")).replace("'", "")).split())


def key(text):
    """For comparing titles loosely: 'The IT Crowd' ~ 'IT Crowd', 'Beavis & Butthead' ~ 'Beavis and Butt-Head'."""
    w = words(str(text or "").replace("&", " and ")).split()
    if w and w[0] in ("the", "a", "an"):
        w = w[1:]
    return "".join(w)


def near(theirs, ours):
    """The same words in the same order once the little ones are left out: 'Halt Catch Fire' is 'Halt and Catch
    Fire', but 'Dr Who' isn't 'Who Killed Dr Bogle and Mrs Chandler'."""
    small = {"the", "a", "an", "and", "of"}

    def big(text):
        return [w for w in words(str(text or "").replace("&", " and ")).split() if w not in small]
    return bool(big(ours)) and big(ours) == big(theirs)


def year_of(date):
    m = re.match(r"(\d{4})", date or "")
    return int(m.group(1)) if m else None


def one(value):
    """guessit gives a list when it found two: take the first."""
    return value[0] if isinstance(value, list) and value else value


def film_name(title, year, tmdb_id):
    return safe(f"{title}" + (f" ({year})" if year else "") + (f" {{tmdb-{tmdb_id}}}" if tmdb_id else ""))


def movie_target(root, m, ext):
    base = film_name(m["title"], m.get("year"), m.get("tmdb"))
    name = base
    if m.get("edition"):
        name += f" {{edition-{safe(m['edition'])}}}"
    if m.get("part"):
        name += f" - pt{m['part']}"
    return root / base / (name + ext.lower())


def episode_target(root, show, ep, ext):
    folder = film_name(show["title"], show.get("year"), show.get("tmdb"))
    season = ep["season"]
    code = f"s{season:02d}e{ep['episode']:02d}" + (f"-e{ep['last']:02d}" if ep.get("last") else "")
    name = safe(f"{show['title']}" + (f" ({show['year']})" if show.get("year") else "") + f" - {code}"
                + (f" - {ep['title']}" if ep.get("title") else ""))
    return root / folder / f"Season {season:02d}" / (name + ext.lower())


def titles_path():
    return fileio.config_dir() / "cleanup-titles.json"


def load_titles():
    """Your own titles, by TMDB id: {"movie": {"10162": "Waking Ned Devine"}, "tv": {...}}."""
    try:
        data = json.loads(titles_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"movie": {}, "tv": {}}
    return {k: dict(data.get(k) or {}) for k in ("movie", "tv")} if isinstance(data, dict) else {"movie": {}, "tv": {}}


def set_title(kind, tmdb_id, title):
    titles = load_titles()
    if title:
        titles[kind][str(tmdb_id)] = title
    else:
        titles[kind].pop(str(tmdb_id), None)
    fileio.write_text_safely(titles_path(), json.dumps(titles, indent=1, ensure_ascii=False) + "\n")
    return titles


# ---------------------------------------------------------------- what's in the library
def is_tv(root, kind):
    return kind == "tv" if kind != "auto" else bool(TV_WORDS.search(root.name))


def videos_under(root, discs=None):
    """Every video under root, leaving out context-notes folders, hidden and NAS system folders, extras folders,
    samples, and the copies embed.py keeps (<name>.original.mkv) and makes (<name>.embedding.mkv). A folder holding
    a disc as it was copied (BDMV, VIDEO_TS) isn't looked inside; it goes in `discs`."""
    out = []
    for dirpath, dirs, files in os.walk(root):
        if any(d.lower() in DISC_DIRS for d in dirs):
            if discs is not None:
                discs.append(Path(dirpath))
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d != workfiles.FOLDER and not d.startswith((".", "#", "@"))
                         and d.lower() not in EXTRAS)
        for f in sorted(files):
            p = Path(dirpath) / f
            if (real_ext(p) in workfiles.VIDEO_EXTS and not f.startswith(".") and not SAMPLE.search(p.stem)
                    and not re.search(r"\.(original|embedding)$", p.stem, re.I)):
                out.append(p)
    return out


def real_ext(p):
    """'.mkv' for film.mkv, and for film.mkv.part (a download, maybe finished, that kept its download name)."""
    p = Path(p)
    return (Path(p.stem).suffix if PARTIAL.search(p.name) else p.suffix).lower()


def matroska_complete(path):
    """Is this Matroska file as long as its own header says? A download that stopped is shorter (the Segment's
    declared size runs past the end of the file); a finished one ends exactly there."""
    def vint(b, i):
        n = 1
        while n <= 8 and not b[i] & (0x80 >> (n - 1)):
            n += 1
        val = b[i] & ((0x80 >> (n - 1)) - 1)
        for k in range(1, n):
            val = (val << 8) | b[i + k]
        return val, n, val == (1 << (7 * n)) - 1         # all ones: "size unknown" (a live recording)
    try:
        size = Path(path).stat().st_size
        with open(path, "rb") as f:
            b = f.read(64)
        if b[:4] != b"\x1a\x45\xdf\xa3":
            return False
        hdr, n, _ = vint(b, 4)
        seg = 4 + n + hdr
        if b[seg:seg + 4] != b"\x18\x53\x80\x67":
            return False
        segsize, n, unknown = vint(b, seg + 4)
        return not unknown and seg + 4 + n + segsize == size
    except (OSError, IndexError):
        return False

def beside(video, names):
    """(file, its new name's ending) for everything beside the video named after it: 'Film.en.srt' -> '.en.srt'.
    Another video whose name starts the same ('Film.Part2.mkv') isn't one, unless it's embed.py's '.original' copy."""
    stem = workfiles.nfc(video.stem)
    out = []
    for n in names:
        name = workfiles.nfc(n)
        if name == workfiles.nfc(video.name) or not name.startswith(stem + "."):
            continue
        rest = name[len(stem):]
        if Path(name).suffix.lower() in workfiles.VIDEO_EXTS and not re.match(r"\.(original|embedding)\.", rest, re.I):
            continue
        out.append((video.parent / n, rest))
    for prefix in workfiles.PREFIXES:                       # working files an earlier version left beside it
        for n in names:
            name = workfiles.nfc(n)
            if name.startswith(f"{prefix}{stem}."):
                out.append((video.parent / n, (prefix, name[len(prefix) + len(stem):])))
    return out


def clutter_in(folder, names, videos_here, sidecars):
    """Files in a folder that belong to no video and aren't artwork or a show's own files."""
    taken = {workfiles.nfc(p.name) for p, _ in sidecars} | {workfiles.nfc(v.name) for v in videos_here}
    out = []
    for n in names:
        p = folder / n
        name = workfiles.nfc(n)
        if name in taken or n.startswith(".") or not p.is_file():
            continue
        low, ext = p.stem.lower(), p.suffix.lower()
        if ext in (".jpg", ".jpeg", ".png") and (low in ARTWORK or low.endswith(("-poster", "-fanart", "-thumb"))):
            continue
        if name.lower() in ("tvshow.nfo", "movie.nfo", "season.nfo"):
            continue
        if (ext in CLUTTER_EXTS or (ext in workfiles.VIDEO_EXTS and SAMPLE.search(p.stem))):
            out.append(p)
    return out


# ---------------------------------------------------------------- TMDB
class Lookup:
    """TMDB look-ups, each asked once per run."""
    def __init__(self, client, language):
        self.client, self.language, self.cache = client, language, {}

    def _get(self, path, **params):
        key = (path, tuple(sorted(params.items())))
        if key not in self.cache:
            try:
                self.cache[key] = self.client.get(path, **params)
            except tmdb.TMDBError as e:
                self.cache[key] = None if e.code == 404 else {"error": str(e)}
            except RuntimeError as e:
                self.cache[key] = {"error": str(e)}
        return self.cache[key]

    def find(self, kind, title, year):
        """(chosen result or None, other candidates, error). kind is 'movie' or 'tv'."""
        date = "release_date" if kind == "movie" else "first_air_date"
        yearkey = "primary_release_year" if kind == "movie" else "first_air_date_year"
        params = {"query": title, "include_adult": "false"}
        r = self._get(f"search/{kind}", **params, **({yearkey: year} if year else {}))
        if r and r.get("error"):
            return None, [], r["error"]
        results = (r or {}).get("results") or []
        if not results and year:                            # the year in the name can be a re-release's
            r = self._get(f"search/{kind}", **params, year=year) if kind == "movie" else None
            results = (r or {}).get("results") or []
        name = "title" if kind == "movie" else "name"
        exact = [x for x in results if key(x.get(name)) == key(title) or key(x.get("original_" + name)) == key(title)]
        if year:
            exact_year = [x for x in exact if year_of(x.get(date)) == year]
            if len(exact_year) == 1 or best_known(exact_year):
                return best_known(exact_year) or exact_year[0], [], None
        if best_known(exact):
            return best_known(exact), [], None
        if len(results) == 1 and (year or exact):
            return results[0], [], None
        if len(exact) == 1 and (not year or len(results) <= 2):
            return exact[0], [], None
        close = [x for x in results if near(x.get(name), title)]
        if not exact and len(close) == 1 and (len(results) == 1 or not year or year_of(close[0].get(date)) == year):
            return close[0], [], None
        return None, results[:CHOICES], None

    def details(self, kind, tmdb_id):
        return self._get(f"{kind}/{tmdb_id}", language=self.language)

    def all_episodes(self, show_id):
        """{(season, episode): title} for every numbered season (specials, season 0, left out)."""
        d = self.details("tv", show_id) or {}
        out = {}
        for s in d.get("seasons") or []:
            n = s.get("season_number")
            if n:
                out.update({(n, e): name for e, name in self.episode_titles(show_id, n).items()})
        return out

    def episode_titles(self, show_id, season):
        r = self._get(f"tv/{show_id}/season/{season}", language=self.language)
        return {e.get("episode_number"): e.get("name") for e in (r or {}).get("episodes") or []} if r else {}


def best_known(results):
    """The one result far better known than the rest (TMDB's votes), as with Predator (1987): the film, and a stray
    second entry with no votes. None when it's close."""
    if len(results) < 2:
        return None
    ranked = sorted(results, key=lambda x: x.get("vote_count") or 0, reverse=True)
    top, second = ranked[0].get("vote_count") or 0, ranked[1].get("vote_count") or 0
    return ranked[0] if top >= 20 and top >= 10 * max(second, 1) else None


def describe_choice(kind, x):
    name = x.get("title") if kind == "movie" else x.get("name")
    return f"{name} ({year_of(x.get('release_date') or x.get('first_air_date')) or '?'}, tmdb {x.get('id')})"


# ---------------------------------------------------------------- the plan
class Plan:
    def __init__(self):
        self.tidy, self.moves, self.by_hand, self.clutter, self.notes, self.fixes = [], [], [], [], [], []


def identify_movie(video, root, guess, lookup, titles=None, guessit=None):
    """(movie dict, reason it's by hand or None)."""
    if guess.get("type") == "episode" or guess.get("season") is not None:
        return None, "looks like a TV episode, in a films folder"
    title = one(guess.get("title"))
    if not title:
        return None, "couldn't read a title from the name"
    m = {"title": title, "year": guess.get("year"), "edition": " ".join(guess["edition"])
         if isinstance(guess.get("edition"), list) else guess.get("edition"),
         "part": one(guess.get("cd"))}                      # 'Part II' is usually a sequel, not half a film
    own = {**film_ids.ids_in_name(video.parent.name if video.parent != root else ""), **film_ids.ids_in_name(video.name)}
    nfo = film_ids.nfo_for(video)
    if nfo:
        own = {**film_ids.ids_in_nfo(nfo), **own}
    if not lookup:
        m["tmdb"] = own.get("tmdb")
        m["title"] = (titles or {}).get("movie", {}).get(str(m["tmdb"])) or m["title"]
        return m, None
    tmdb_id = own.get("tmdb")
    if not tmdb_id and own.get("imdb"):
        found = lookup._get(f"find/{own['imdb']}", external_source="imdb_id") or {}
        hits = found.get("movie_results") or []
        tmdb_id = hits[0]["id"] if len(hits) == 1 else None
    if not tmdb_id:
        tries = [(title, m["year"])]
        if video.parent != root and guessit:               # 'Total Recall (1990)/Total Recall KLAXXON.avi'
            g = guessit(video.parent.name, {"type": "movie"})
            folder_title, folder_year = title_year(one(g.get("title")), g.get("year"))
            if folder_title and (key(folder_title), folder_year) != (key(title), m["year"]):
                tries.append((folder_title, folder_year or m["year"]))
        hit, others, error = None, [], None
        for t, y in tries:
            hit, found, error = lookup.find("movie", t, y)
            others = others or found
            if hit or error:
                break
        if error:
            return None, f"TMDB: {error}"
        if not hit:
            what = "; ".join(describe_choice("movie", x) for x in others)
            return None, (f"TMDB has more than one: {what}" if others else
                          f"TMDB has no film called “{title}”" + (f" ({m['year']})" if m["year"] else ""))
        tmdb_id = hit["id"]
        if not m["year"]:
            m["year"] = year_of(hit.get("release_date"))
    d = lookup.details("movie", tmdb_id)
    if not d or d.get("error"):
        return None, f"TMDB has no film {tmdb_id}" + (f" ({d['error']})" if d and d.get("error") else "")
    m.update(title=(titles or {}).get("movie", {}).get(str(tmdb_id)) or d.get("title") or title,
             year=year_of(d.get("release_date")) or m["year"], tmdb=tmdb_id)
    return m, None


def show_of(video, root):
    """The show's folder: the first folder under root on the way to the video."""
    rel = video.relative_to(root)
    return root / rel.parts[0] if len(rel.parts) > 1 else None


def title_year(title, year):
    """('The Twilight Zone', 1959) from guessit's ('The Twilight Zone 1959', None)."""
    m = re.fullmatch(r"(.+?)\s+((?:19|20)\d\d)", title or "")
    return (m.group(1), year or int(m.group(2))) if m else (title, year)


def identify_show(folder, guessit, lookup, shows, hints=(), titles=None):
    """The show for a show folder, asked once: {'title', 'year', 'tmdb'} or a reason string. `hints` are (title,
    year) read from its episodes' names: a second title to try, and the earliest year as the show's (Doctor Who's
    episodes are named with their own years; the show began in the earliest)."""
    if folder in shows:
        return shows[folder]
    g = guessit(folder.name, {"type": "episode"})
    title, year = title_year(one(g.get("title")), g.get("year"))
    tries = [(title, year)] if title else []
    named = [title_year(t, y) for t, y in hints if t]
    if named:
        common = max({key(t) for t, _ in named}, key=lambda k: sum(key(t) == k for t, _ in named))
        file_title = next(t for t, _ in named if key(t) == common)
        years = [y for t, y in named if y and key(t) in (common, key(title))]
        if title and not year and years and key(title) == common:
            tries = [(title, min(years))]
        if key(file_title) != key(title):
            tries.append((file_title, min(years) if years else None))
        title = title or file_title
    ids = film_ids.ids_in_name(folder.name)
    if (folder / "tvshow.nfo").is_file():
        ids = {**film_ids.ids_in_nfo(folder / "tvshow.nfo"), **ids}
    show = {"title": title, "year": year, "tmdb": ids.get("tmdb")}
    if not title:
        show = "couldn't read the show's name from its folder"
    elif lookup:
        tmdb_id = ids.get("tmdb")
        if not tmdb_id:
            hit, others, error = None, [], None
            for t, y in tries:
                hit, found, error = lookup.find("tv", t, y)
                others = others or found
                if hit or error:
                    break
            if error:
                show = f"TMDB: {error}"
            elif not hit:
                what = "; ".join(describe_choice("tv", x) for x in others)
                show = (f"TMDB has more than one show: {what}" if others else f"TMDB has no show called “{title}”")
            else:
                tmdb_id = hit["id"]
        if tmdb_id:
            d = lookup.details("tv", tmdb_id)
            if not d or d.get("error"):
                show = f"TMDB has no show {tmdb_id}"
            else:
                show = {"title": (titles or {}).get("tv", {}).get(str(tmdb_id)) or d.get("name") or title,
                        "year": year_of(d.get("first_air_date")) or year, "tmdb": tmdb_id}
    shows[folder] = show
    return show


def identify_episode(video, root, guess, guessit, lookup, shows, hints=(), titles=None):
    """(target path or None, reason it's by hand or None, a note or None)."""
    folder = show_of(video, root)
    if folder is None:
        return None, "an episode loose in the shows folder: which show is it?", None
    season, episode = guess.get("season"), guess.get("episode")
    if isinstance(season, list) or season is None or episode is None:
        if season is None and guessit(video.name).get("type") == "movie" and guessit(video.name).get("year"):
            return None, "looks like a film, in a shows folder", None
        return None, "couldn't read the season and episode from the name", None
    if season > 100:
        return None, f"the season number is a year ({season}): which season is it?", None
    show = identify_show(folder, guessit, lookup, shows, hints, titles)
    if isinstance(show, str):
        return None, show, None
    episodes = episode if isinstance(episode, list) else [episode]
    file_title = one(guess.get("episode_title"))
    if file_title and (re.fullmatch(r"\d*[0-9]{3,4}[pi]", str(file_title).strip(), re.I)
                       or not re.search(r"[^\W\d_]{2}", str(file_title))):
        file_title = None                                   # '080p': a piece of the resolution, not a title
    note = None
    if lookup and show.get("tmdb"):
        code = f"s{season:02d}e{episodes[0]:02d}"
        names = [lookup.episode_titles(show["tmdb"], season).get(e) for e in episodes]
        if file_title and not same_episode_title(file_title, names[0]):
            # The name's title isn't TMDB's for that number: numbered straight through the series ('Season 2/11. A
            # Song for Europe' is s02e05), or misread. TMDB's number for that title, when there's exactly one.
            found = [se for se, name in lookup.all_episodes(show["tmdb"]).items()
                     if same_episode_title(file_title, name)]
            if len(found) == 1 and len(episodes) == 1:
                (season, first), = found
                episodes, names = [first], [lookup.episode_titles(show["tmdb"], season).get(first)]
                note = f"numbered by its title: the name said {code}; TMDB has “{file_title}” as s{season:02d}e{first:02d}"
            elif names[0]:
                return None, f"the name says “{file_title}”, but TMDB's {code} is “{names[0]}”: which is it?", None
            else:
                return None, f"TMDB has no {code} (or “{file_title}”) for {show['title']}: your own numbering?", None
        if not all(names):
            return None, f"TMDB has no {code} for {show['title']}: your own numbering?", None
        file_title = " + ".join(dict.fromkeys(names))
    ep = {"season": season, "episode": episodes[0], "last": episodes[-1] if len(episodes) > 1 else None,
          "title": file_title}
    return episode_target(root, show, ep, video.suffix), None, note


def same_episode_title(ours, theirs):
    """'Are You Right There, Father Ted' is TMDB's 'Are You Right There Father Ted?'; 'Buried in Concrete - Daddy
    Longlegs - Jet Taxi' (a file naming each myth) holds TMDB's 'Buried in Concrete'; 'Pete' is 'Pete (1)' and 'Me'
    is 'Me²' (a part number); 'ep2.6_succ3ss0r' is 'eps2.6_succ3ss0r' (spelled a little differently)."""
    a, b = key(ours), key(theirs)
    if not (a and b):
        return False
    if a == b or (min(len(a), len(b)) >= 5 and (a in b or b in a)):
        return True
    short, long_ = sorted((a, b), key=len)
    if long_.startswith(short) and long_[len(short):].isdigit():
        return True
    return min(len(a), len(b)) >= 8 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


def plan_library(root, kind="auto", lookup=None, guessit=None, titles=None):
    guessit = guessit or guessit_or_exit()
    titles = load_titles() if titles is None else titles
    tv = is_tv(root, kind)
    plan, shows, targets, discs = Plan(), {}, {}, []
    folders = {}
    for v in videos_under(root, discs):
        folders.setdefault(v.parent, []).append(v)
    for d in discs:
        plan.by_hand.append({"video": d, "target": None, "sidecars": [], "note": None, "work": None,
                             "reason": "a disc copied as it is (BDMV or VIDEO_TS folder): players can't open it as a "
                                       "film; make it one file (e.g. with MakeMKV) or leave it"})
    guesses = {v: dict(guessit(PARTIAL.sub("", str(v.relative_to(root))), {"type": "episode"} if tv else {}))
               for vs in folders.values() for v in vs}
    hints = {}
    if tv:
        for v, g in guesses.items():
            if show_of(v, root) and g.get("title") and g.get("season") is not None:
                hints.setdefault(show_of(v, root), []).append((one(g["title"]), g.get("year")))
    for folder, videos in sorted(folders.items()):
        try:
            names = sorted(os.listdir(folder))
        except OSError as e:
            plan.notes.append(f"Couldn't read {folder}: {e.strerror or e}")
            continue
        sidecars_here = []
        for video in videos:
            sidecars = [] if PARTIAL.search(video.name) else beside(video, names)
            sidecars_here += sidecars
            guess = guesses[video]
            note = None
            if tv:
                target, reason, note = identify_episode(video, root, guess, guessit, lookup, shows,
                                                        hints.get(show_of(video, root), ()), titles)
            else:
                m, reason = identify_movie(video, root, guess, lookup, titles, guessit)
                target = movie_target(root, m, real_ext(video)) if m else None
            if target is not None and PARTIAL.search(video.name):
                if real_ext(video) in (".mkv", ".webm") and matroska_complete(video):
                    note = "a finished download that kept its download name (checked: the file is complete)"
                else:
                    target, reason = None, ("an unfinished download: the file is shorter than its header says"
                                            if real_ext(video) in (".mkv", ".webm") else
                                            "a download's name (.part): finished? Only .mkv files can be checked")
            entry = {"video": video, "target": target, "sidecars": sidecars, "reason": reason, "note": note,
                     "work": workfiles.folder(video) if workfiles.folder(video).is_dir() else None}
            if target is not None and (locked(video) or any(locked(x) for x, _ in sidecars)):
                target = entry["target"] = None
                entry["reason"] = "locked (Finder's Get Info > Locked): left as it is; unlock it to rename"
            if target is not None and recently_changed(video):
                target, entry["reason"] = None, "changed in the last 2 minutes: still being copied? Try again later"
                entry["target"] = None
            if target is None:
                plan.by_hand.append(entry)
                continue
            if workfiles.nfc(target) == workfiles.nfc(video):
                plan.tidy.append(entry)
                continue
            targets.setdefault(workfiles.nfc(target.with_suffix("")).lower(), []).append(entry)  # .avi and .m4v
        plan.clutter += clutter_in(folder, names, videos, sidecars_here)
    for same in targets.values():
        if len(same) > 1:
            for e in same:
                others = ", ".join(x["video"].name for x in same if x is not e)
                e["reason"] = f"would get the same name as {others} (a duplicate?)"
                plan.by_hand.append(e)
        elif same[0]["target"].exists() and not same_file(same[0]["target"], same[0]["video"]):
            same[0]["reason"] = "the new name is taken already"
            plan.by_hand.append(same[0])
        else:
            plan.moves.append(same[0])
    plan.by_hand.sort(key=lambda e: str(e["video"]))
    plan.moves.sort(key=lambda e: str(e["video"]))
    if not tv:
        repairs(plan, root, folders)
    return plan


def stray_rest(p):
    """The ending a subtitle or notes file named for no video gets on the film's name: '.behind-the-scenes.notes.ass',
    '.notes.ass', '.de.srt', or the language its name or text says ('Predator[Eng][Subs].srt' -> '.en.srt')."""
    low = workfiles.nfc(p.name).lower()
    for ending in (workfiles.BTS_ASS, ".notes.ass"):
        if low.endswith(ending):
            return ending
    m = SUB_REST.search(low)
    if m and languages.code(m.group(1)) in languages.LANGUAGES:
        return m.group(0)
    lang = find_subs.lang_of(p) if p.suffix.lower() == ".srt" else None
    return (f".{lang}" if lang else "") + p.suffix.lower()


def repairs(plan, root, folders):
    """In a folder that holds one film: subtitle and notes files named for no video get the film's name; a lone
    context-notes folder named for a video that isn't there (an older name) becomes the film's; clutter in its
    subfolders ('Other/', 'Logs/') joins the clutter. Folders of subtitles ('Subs', 'Eng. Subs') are left as they are."""
    final = {e["video"]: e["target"] for e in plan.moves + plan.tidy}
    for folder, videos in sorted(folders.items()):
        if folder == root or len(videos) != 1 or videos[0] not in final:
            continue
        video, target = videos[0], final[videos[0]]
        stem = workfiles.nfc(video.stem)
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        taken = set()
        for p in entries:
            name = workfiles.nfc(p.name)
            if (not p.is_file() or name.startswith(".") or p.suffix.lower() not in SUB_EXTS
                    or name.startswith(stem + ".") or any(name.startswith(f"{x}{stem}.") for x in workfiles.PREFIXES)):
                continue
            dst = target.parent / (target.stem + stray_rest(p))
            if dst.exists() or dst in taken:
                plan.notes.append(f"Left as it is (its new name {dst.name} is taken): {rel(p, root)}")
                continue
            taken.add(dst)
            plan.fixes.append({"kind": "rename", "src": p, "dst": dst, "video": target, "film": video})
        work = folder / workfiles.FOLDER
        if work.is_dir() and not workfiles.folder(video).is_dir():
            strays = [d for d in work.iterdir() if d.is_dir() and real_ext(d) in workfiles.VIDEO_EXTS
                      and not (folder / d.name).exists()]
            if len(strays) == 1:
                plan.fixes.append({"kind": "work", "src": strays[0], "dst": workfiles.folder(target), "video": target,
                                   "film": video})
        for sub in entries:
            if (sub.is_dir() and sub.name != workfiles.FOLDER and not sub.name.startswith(".")
                    and "sub" not in sub.name.lower() and sub.name.lower() not in DISC_DIRS):
                try:
                    plan.clutter += clutter_in(sub, sorted(os.listdir(sub)), [], [])
                except OSError:
                    pass


def locked(path):
    """Finder's Locked box (the uchg flag) or the system's immutable flag: such a file can't be renamed."""
    flags = getattr(stat, "UF_IMMUTABLE", 0) | getattr(stat, "SF_IMMUTABLE", 0)
    try:
        return bool(getattr(os.stat(path), "st_flags", 0) & flags)
    except OSError:
        return False


def recently_changed(video):
    try:
        return time.time() - video.stat().st_mtime < BUSY_SECONDS
    except OSError:
        return True


def same_file(a, b):
    try:
        return os.path.samefile(a, b)                      # a case-only rename on a case-insensitive disk
    except OSError:
        return False


def new_sidecar_name(target, rest):
    if isinstance(rest, tuple):                            # (prefix, ending): notes-<name>.json beside the video
        prefix, ending = rest
        return f"{prefix}{target.stem}{ending}"
    return target.stem + rest


# ---------------------------------------------------------------- doing it
class Stop(Exception):
    """Something isn't as the plan expected (a name taken, a file gone): the run stops; what's done stays logged."""


class Log:
    """The undo log: one JSON line per change, written (and flushed to disk) the moment the change is made."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a", encoding="utf-8")
        self.count = 0

    def add(self, op, **fields):
        self.f.write(json.dumps({"op": op, **{k: str(v) if isinstance(v, Path) else v for k, v in fields.items()}},
                                ensure_ascii=False) + "\n")
        self.f.flush()
        os.fsync(self.f.fileno())
        self.count += op == "move"

    def close(self):
        self.f.close()


def log_path(root):
    return fileio.config_dir() / "cleanup" / f"{datetime.now():%Y-%m-%d %H%M%S} {safe(root.name) or 'library'}.jsonl"


def make_dir(path, log):
    """mkdir -p, logging each folder it makes (undo removes them again if they're empty)."""
    missing = []
    p = Path(path)
    while not p.exists():
        missing.append(p)
        p = p.parent
    for d in reversed(missing):
        d.mkdir()
        log.add("mkdir", path=d)


def move(src, dst, log):
    """Rename src to dst, on the same disk only (a rename is instant and can't half-happen; a copy can). Refuses a
    name that's taken; a change of case only (Akira -> AKIRA on a Mac or a NAS share) goes through a spare name."""
    src, dst = Path(src), Path(dst)
    if workfiles.nfc(src) == workfiles.nfc(dst):
        return dst
    if not src.exists():
        raise Stop(f"{src} isn't there any more")
    if dst.exists() and not same_file(src, dst):
        raise Stop(f"{dst} is there already")
    make_dir(dst.parent, log)
    try:
        if dst.exists():                                    # the same file, another case
            spare = src.with_name(src.name + ".cleanup-renaming")
            os.rename(src, spare)
            os.rename(spare, dst)
        else:
            os.rename(src, dst)
    except OSError as e:
        raise Stop(f"couldn't rename {src.name} to {dst}: {e.strerror or e}") from None
    log.add("move", src=src, dst=dst)
    return dst


def ignore_files(context_folder, log):
    """The files that keep media servers out of a context-notes folder, made the way workfiles.make_dirs does."""
    make_dir(context_folder, log)
    for name, text in workfiles.IGNORE_FILES.items():
        try:
            with open(Path(context_folder) / name, "x", encoding="utf-8") as f:
                f.write(text)
            log.add("create", path=Path(context_folder) / name)
        except OSError:
            pass


def renamed_entry(name, old_stems, new_stem):
    """A working folder's entry named for an old name of the video, named for the new one: notes-<stem>.json,
    <stem>.en.srt, '<stem> chat-replies'. None for anything else. The longest old name that fits wins."""
    n = workfiles.nfc(name)
    for old_stem in sorted({workfiles.nfc(x) for x in ([old_stems] if isinstance(old_stems, str) else old_stems)},
                           key=len, reverse=True):
        for prefix in ("", *workfiles.PREFIXES):
            start = prefix + old_stem
            if n.startswith(start) and n[len(start):len(start) + 1] in (".", " ") and old_stem != new_stem:
                return prefix + new_stem + n[len(start):]
    return None


def stems_in_notes(folder):
    """The names a working folder's notes files say its video and subtitles had: 'Film.anoXmous_' from
    "video": "Film.anoXmous_.mp4", 'Film.anoXmous' from "subtitles": "Film.anoXmous.en.srt". A film renamed by
    hand before can leave files under both."""
    out = set()
    for p in sorted(Path(folder).glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for field in NOTES_FIELDS if isinstance(data, dict) else ():
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            name = Path(value).name
            if field == "video":
                out.add(Path(name).stem)
                continue
            stem = workfiles.DERIVED_SUFFIX.sub("", Path(name).stem)
            stem = re.sub(r"\.[a-z]{2,3}$", "", stem) if languages.code(stem.rsplit(".", 1)[-1]) else stem
            out.add(workfiles.DERIVED_SUFFIX.sub("", stem))
    return {x for x in out if len(x) >= 3}


def follow_in_notes(path, old_stem, new_stem, log):
    """The notes file's subtitle (and video) names, renamed with the video. Its date is kept, so the .ass doesn't
    look older than the notes (that would make the next run rebuild it, and an embedded copy out of date)."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    changes = []
    for field in NOTES_FIELDS:
        value = data.get(field)
        if isinstance(value, str):
            new = renamed_entry(Path(value).name, old_stem, new_stem)
            if new:
                changes.append((field, value, str(Path(value).with_name(new)) if Path(value).name != value else new))
    if not changes:
        return
    stat = path.stat()
    for field, old, new in changes:
        done = False
        for enc in {json.dumps(old, ensure_ascii=False), json.dumps(old)}:
            pattern = re.compile(r'("' + re.escape(field) + r'"\s*:\s*)' + re.escape(enc))
            if pattern.search(text):
                text = pattern.sub(lambda m: m.group(1) + json.dumps(new, ensure_ascii=False), text, count=1)
                done = True
                break
        if not done:
            continue
        log.add("edit", path=path, field=field, old=old, new=new, mtime=stat.st_mtime, atime=stat.st_atime)
    fileio.write_text_safely(path, text)
    os.utime(path, (stat.st_atime, stat.st_mtime))


def move_work_folder(old_video, target, log):
    """context-notes/<old video name>/ -> context-notes/<new video name>/ beside the new video, its entries renamed
    (from every old name its notes files mention, not only the video's)."""
    old = workfiles.folder(old_video)
    if not old.is_dir():
        return
    new = workfiles.folder(target)
    ignore_files(new.parent, log)
    move(old, new, log)
    old_stems, new_stem = {workfiles.nfc(old_video.stem)} | stems_in_notes(new), target.stem
    for name in sorted(os.listdir(new)):
        renamed = renamed_entry(name, old_stems, new_stem)
        dst = move(new / name, new / renamed, log) if renamed else new / name
        if dst.suffix.lower() == ".json" and dst.is_file():
            follow_in_notes(dst, old_stems, new_stem, log)


def move_originals(old_video, target, log):
    """embed.py --convert's kept .mp4 (context-notes/originals/<old name>.mp4) follows the film."""
    folder = old_video.parent / workfiles.FOLDER / "originals"
    if not folder.is_dir():
        return
    for p in sorted(folder.iterdir()):
        if workfiles.nfc(p.stem) == workfiles.nfc(old_video.stem):
            dst = target.parent / workfiles.FOLDER / "originals" / (target.stem + p.suffix)
            ignore_files(dst.parent.parent, log)
            move(p, dst, log)


def top_of(path, root):
    rel = Path(path).relative_to(root)
    return root / rel.parts[0] if len(rel.parts) > 1 else None


def remove_if_empty(d, root, log):
    """Remove a folder this left empty, and the ones above it it leaves empty, up to the library folder. A folder
    with only .DS_Store-style files counts as empty, and a context-notes folder with only its ignore files too."""
    d = Path(d)
    while d != root and root in d.parents and d.is_dir():
        try:
            names = os.listdir(d)
        except OSError:
            return
        ours = set(workfiles.IGNORE_FILES) if d.name == workfiles.FOLDER else set()
        if any(n.lower() not in JUNK and n not in ours for n in names):
            return
        for n in names:
            p = d / n
            if p.is_dir():
                return
            text = p.read_text(encoding="utf-8", errors="replace") if n in ours else None
            p.unlink()
            log.add("delete", path=p, text=text)
        d.rmdir()
        log.add("rmdir", path=d)
        d = d.parent


def apply_plan(plan, root, log, only_clutter_under=None):
    """Do what the plan lists, in Erin's order. Returns the folders left behind that still hold something."""
    renamed = {}

    def now(p):
        p = Path(p)
        for old, new in renamed.items():
            if p == old or old in p.parents:
                return new / p.relative_to(old)
        return p

    # 1. a folder that holds one film (or one show) is renamed as a whole
    wanted = {}
    for e in plan.moves:
        old_top, new_top = top_of(e["video"], root), top_of(e["target"], root)
        if old_top and new_top:
            wanted.setdefault(old_top, set()).add(new_top)
    claimed = set()
    for old_top, news in sorted(wanted.items()):
        if len(news) != 1:
            continue
        new_top = next(iter(news))
        if workfiles.nfc(new_top) == workfiles.nfc(old_top) or new_top in claimed:
            continue
        if new_top.exists() and not same_file(new_top, old_top):
            continue
        say(f"  {old_top.name}/  ->  {new_top.name}/")
        move(old_top, new_top, log)
        renamed[old_top] = new_top
        claimed.add(new_top)
    # 2. each video, the files named after it, its notes folder, its kept original
    left = set()
    for e in plan.moves:
        video, target = now(e["video"]), e["target"]
        if workfiles.nfc(video) != workfiles.nfc(target):
            say(f"  {rel(video, root)}  ->  {rel(target, root)}")
        sidecars = [(now(p), r) for p, r in e["sidecars"]]
        move(video, target, log)
        for p, r in sidecars:
            move(p, target.parent / new_sidecar_name(target, r), log)
        move_work_folder(video, target, log)
        move_originals(video, target, log)
        left.add(video.parent)
        left.add(video.parent / workfiles.FOLDER)
    # 2b. repairs beside films that hold one film: stray subtitle and notes files, a notes folder under an old name
    for f in plan.fixes:
        src = now(f["src"])
        say(f"  {rel(src, root)}  ->  {rel(f['dst'], root)}")
        if f["kind"] == "rename":
            move(src, f["dst"], log)
        else:
            move_work_folder(src.parent.parent / src.name, f["video"], log)
    # 3. clutter: into its film's (or show's) context-notes/removed/, else the library's
    tops = set(renamed.values()) | {top_of(e["target"], root) for e in plan.moves + plan.tidy} - {None}
    for p in sorted(plan.clutter):
        p = now(p)
        top = top_of(p, root)
        if top in tops:
            dst = top / workfiles.FOLDER / "removed" / p.relative_to(top)
        elif only_clutter_under is not None:
            continue                                       # --only: just the chosen films' clutter
        else:
            dst = root / workfiles.FOLDER / "removed" / p.relative_to(root)
        ignore_files(top / workfiles.FOLDER if top in tops else root / workfiles.FOLDER, log)
        move(p, dst, log)
        left.add(p.parent)
    # 4. folders left empty
    for d in sorted(left, key=lambda x: len(x.parts), reverse=True):
        remove_if_empty(d, root, log)
    homes = {e["target"].parent for e in plan.moves} | tops
    return sorted(d for d in left if d.is_dir() and d != root and d.name != workfiles.FOLDER
                  and d not in homes and not any(t in d.parents for t in homes))


def undo(log_file):
    """Put back everything a run's log says it did, last change first."""
    lines = [json.loads(ln) for ln in Path(log_file).read_text(encoding="utf-8").splitlines() if ln.strip()]
    say(f"Putting back {sum(x['op'] == 'move' for x in lines)} renames from {log_file} ...")
    problems = 0
    for x in reversed(lines):
        try:
            if x["op"] == "move":
                src, dst = Path(x["src"]), Path(x["dst"])
                if src.exists() and not same_file(src, dst):
                    raise OSError(f"{src} is there again")
                src.parent.mkdir(parents=True, exist_ok=True)
                os.rename(dst, src)
            elif x["op"] == "mkdir":
                Path(x["path"]).rmdir()
            elif x["op"] == "create":
                Path(x["path"]).unlink()
            elif x["op"] == "rmdir":
                Path(x["path"]).mkdir(exist_ok=True)
            elif x["op"] == "delete" and x.get("text") is not None:
                Path(x["path"]).write_text(x["text"], encoding="utf-8")
            elif x["op"] == "edit":
                path = Path(x["path"])
                text = path.read_text(encoding="utf-8")
                pattern = re.compile(r'("' + re.escape(x["field"]) + r'"\s*:\s*)' +
                                     re.escape(json.dumps(x["new"], ensure_ascii=False)))
                fileio.write_text_safely(path, pattern.sub(
                    lambda m: m.group(1) + json.dumps(x["old"], ensure_ascii=False), text, count=1))
                os.utime(path, (x["atime"], x["mtime"]))
        except OSError as e:
            problems += 1
            say(f"  ! {x['op']} {x.get('dst') or x.get('path')}: {getattr(e, 'strerror', None) or e}")
    say("Done." if not problems else f"Done, but {problems} couldn't be put back (above).")
    return 0 if not problems else 1


# ---------------------------------------------------------------- the listing
def working(name, stem):
    """A working file an earlier version left beside the video (tidy.py's job), not one a player uses."""
    return workfiles.is_working(workfiles.nfc(name), stem) or re.search(r"\.(bak\d*|txt)$", name, re.I) is not None


def rel(path, root):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def show_plan(plan, root, language, lookup, dry_run=True):
    say(f"Library: {root}")
    say(f"Titles in: {language}" if lookup else "Titles: as read from the names (not checked with TMDB)")
    say("Nothing has been changed. This is only the list.\n")
    if plan.moves:
        say(f"Would rename ({len(plan.moves)}):")
        for e in plan.moves:
            say(f"  {rel(e['video'], root)}")
            say(f"    -> {rel(e['target'], root)}")
            stem = workfiles.nfc(e["video"].stem)
            players = [r for p, r in e["sidecars"] if not isinstance(r, tuple) and not working(p.name, stem)]
            leftovers = len(e["sidecars"]) - len(players)
            if players:
                say("       with: " + ", ".join(players))
            if leftovers:
                say(f"       + {leftovers} working file{'s' if leftovers != 1 else ''} beside it "
                    "(tidy.py moves them into its notes folder first)")
            if e["work"]:
                say(f"       and its notes folder -> {rel(e['target'].parent / workfiles.FOLDER / e['target'].name, root)}")
            if e["note"]:
                say(f"       note: {e['note']}")
            prompts.event("cleanup-film", video=str(e["video"]), target=str(e["target"]), status="rename",
                          sidecars=[str(p) for p, _ in e["sidecars"]], note=e["note"])
        say()
    if plan.by_hand:
        say(f"Decide by hand ({len(plan.by_hand)}):")
        for e in plan.by_hand:
            say(f"  {rel(e['video'], root)}")
            say(f"    {e['reason']}")
            prompts.event("cleanup-film", video=str(e["video"]), status="by-hand", reason=e["reason"])
        say()
    if plan.fixes:
        say(f"Names to put right beside the films ({len(plan.fixes)}):")
        for f in plan.fixes:
            what = "its notes folder, under an older name" if f["kind"] == "work" else "named for no video here"
            say(f"  {rel(f['src'], root)}  ({what})")
            say(f"    -> {rel(f['dst'], root)}")
            prompts.event("cleanup-fix", src=str(f["src"]), dst=str(f["dst"]), change=f["kind"])
        say()
    if plan.clutter:
        say(f"Clutter ({len(plan.clutter)}): " + ("listed only" if dry_run else "moves into context-notes/removed/ "
                                                                     "after a yes"))
        for p in sorted(plan.clutter):
            say(f"  {rel(p, root)}")
        say()
    for n in plan.notes:
        say(f"  ! {n}")
    say(f"{len(plan.moves)} to rename, {len(plan.tidy)} already tidy, {len(plan.by_hand)} to decide by hand, "
        f"{len(plan.fixes)} names to put right, {len(plan.clutter)} clutter.")
    prompts.event("cleanup-summary", rename=len(plan.moves), tidy=len(plan.tidy), by_hand=len(plan.by_hand),
                  fixes=len(plan.fixes), clutter=len(plan.clutter))


def chosen(plan, only):
    """--only: the videos whose path has one of these words in it."""
    if not only:
        return plan
    words_ = [w.lower() for w in only]

    def keep(e):
        return any(w in str(e["video"]).lower() for w in words_)
    plan.moves = [e for e in plan.moves if keep(e)]
    plan.by_hand = [e for e in plan.by_hand if keep(e)]
    plan.tidy = [e for e in plan.tidy if keep(e)]
    plan.fixes = [f for f in plan.fixes if any(w in str(f["film"]).lower() for w in words_)]
    plan.clutter = [p for p in plan.clutter if any(w in str(p).lower() for w in words_)
                    or any(p.parent == e["video"].parent for e in plan.moves)]
    return plan


def skipped(plan, skip):
    """--skip: leave out the videos (and their clutter and names to put right) with one of these in their path. A
    show folder holding a skipped video isn't renamed as a whole either: its videos go one by one."""
    if not skip:
        return plan
    words_ = [w.lower() for w in skip]

    def out(p):
        return any(w in str(p).lower() for w in words_)
    plan.moves = [e for e in plan.moves if not out(e["video"])]
    plan.by_hand = [e for e in plan.by_hand if not out(e["video"])]
    plan.tidy = [e for e in plan.tidy if not out(e["video"])]
    plan.fixes = [f for f in plan.fixes if not out(f["film"])]
    plan.clutter = [p for p in plan.clutter if not out(p)]
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser(description="Give a film or TV library standard names (lists, asks, then renames).")
    ap.add_argument("path", type=Path, nargs="?", help="the library folder: your films, or your TV shows")
    ap.add_argument("--kind", choices=("auto", "movies", "tv"), default="auto",
                    help="films or TV shows (auto: TV when the folder's name says TV, Shows or Series)")
    ap.add_argument("--language", help="the language for titles, e.g. en-US, de-DE, fr-FR (default: this computer's)")
    ap.add_argument("--offline", action="store_true", help="don't ask TMDB; name from the file names only")
    ap.add_argument("--dry-run", action="store_true", help="only list; change nothing")
    ap.add_argument("--yes", action="store_true", help="rename without asking")
    ap.add_argument("--only", action="append", metavar="TEXT",
                    help="only the videos with this in their path (repeat it for more)")
    ap.add_argument("--skip", action="append", metavar="TEXT",
                    help="leave out the videos with this in their path (repeat it for more)")
    ap.add_argument("--set-title", nargs=2, metavar=("TMDB_ID", "TITLE"),
                    help="your own title for this TMDB film (or show, in a TV folder); an empty TITLE removes it")
    ap.add_argument("--undo", type=Path, metavar="LOG", help="put back everything a run did, from its undo log")
    a = ap.parse_args(argv)
    if a.undo:
        return undo(a.undo.expanduser())
    if not a.path:
        ap.error("give the library folder (or --undo LOG)")
    root = a.path.expanduser()
    if not root.is_dir():
        sys.exit(f"Not a folder: {root}")
    if a.set_title:
        kind = "tv" if is_tv(root, a.kind) else "movie"
        set_title(kind, a.set_title[0].strip(), a.set_title[1].strip())
        say(f"Your title for TMDB {kind} {a.set_title[0]}: " + (f"“{a.set_title[1].strip()}”" if a.set_title[1].strip()
                                                               else "none (TMDB's is used)") + f" ({titles_path()})\n")
    language = a.language or computer_language()
    lookup = None
    if not a.offline:
        key = tmdb.load()
        if key:
            lookup = Lookup(tmdb.TMDB(key), language)
        else:
            say("No TMDB key saved, so titles come from the names only. Save one with:  python3 tmdb.py --set-key\n")
    say(f"Reading {root} ...")
    plan = skipped(chosen(plan_library(root, a.kind, lookup), a.only), a.skip)
    show_plan(plan, root, language, lookup, a.dry_run)
    if a.dry_run or not (plan.moves or plan.clutter or plan.fixes):
        return 0
    say("\n" + PLEX_ADVICE)
    what = ", ".join(x for x in (f"rename {len(plan.moves)} video(s) with their files" if plan.moves else "",
                                 f"put {len(plan.fixes)} name(s) right" if plan.fixes else "",
                                 "move the clutter" if plan.clutter else "") if x)
    what = what[0].upper() + what[1:]
    if not (a.yes or prompts.confirm(what + "?", id="cleanup.go")):
        say("Nothing was changed.")
        return 0
    log = Log(log_path(root))
    say(f"Undo log: {log.path}")
    code = 0
    try:
        behind = apply_plan(plan, root, log, only_clutter_under=root if a.only else None)
        for d in behind:
            say(f"  Left in place (it still holds other things): {rel(d, root)}")
        say(f"Done: {log.count} renames.")
    except Stop as e:
        say(f"  ! Stopped: {e}. What was done so far is in the undo log.")
        code = 1
    except KeyboardInterrupt:
        say("  ! Stopped. What was done so far is in the undo log.")
        code = 130
    finally:
        log.close()
    say(f"To put it all back:  python3 cleanup.py --undo \"{log.path}\"")
    return code


if __name__ == "__main__":
    sys.exit(main())
