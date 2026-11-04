#!/usr/bin/env python3
"""
film_ids.py - find which film or episode each set of notes is for (its IMDb and TMDB ids), and write the ids in.
Created 2026-11-03, modified 2026-11-03.

    python3 film_ids.py "/Volumes/Media/Movies"            every film with notes in the folder and the ones under it
    python3 film_ids.py film.mkv                           one film
    python3 film_ids.py "/Volumes/Media/Movies" --dry-run  only list what it finds; change nothing
    python3 film_ids.py film.mkv --again                   look again, for a film that already has ids
    python3 film_ids.py film.mkv --imdb tt0079470          you know the film: use this id (TMDB's is looked up)

Where the ids come from, in this order:
  1. The notes file, when an earlier run already wrote them (--again looks again).
  2. The file and folder names, as Plex, Jellyfin, Radarr and Sonarr name them: {imdb-tt0079470}, [imdbid-tt0079470],
     {tmdb-583}, [tmdbid-583]. For an episode, ids on the show's folder are the series'.
  3. An .nfo file: <video name>.nfo, movie.nfo, or the only .nfo in a folder with one video (Kodi's <uniqueid>, or a
     release's imdb.com link). For an episode, tvshow.nfo gives the series.
  4. The video's own tags (IMDB, TMDB), as MKVToolNix and some taggers write them.
  5. OpenSubtitles.com, with the API key saved by  python3 find_subs.py --set-opensubtitles  (searching uses none of
     its downloads): first by the file's fingerprint (subtitles made for this exact file: the right film), then by
     an IMDb id found above (to add TMDB's), then by title and year, or show, season and episode. A title search is
     used by itself only when exactly one film fits by title and year; otherwise it asks which (and with --yes, or
     --dry-run, skips the film). --offline leaves this step out.

What it writes, for each film it found:
  - "ids" in the notes file (notes-<video>.json, and behind-the-scenes-<video>.json when there is one): the type
    (movie or episode), imdb, tmdb, title, year; for an episode its season, episode and series; and where they came
    from and when (docs/notes-format.md);
  - a "; Film:" line in the header of <video>.notes.ass, of the Behind the Scenes .ass, and of the Plex copy
    (<video>.en.ass) when it's the same as the .notes.ass, e.g.   ; Film: imdb tt0079470, tmdb movie/583
Each file is kept first as a .bak in the film's context-notes folder. The notes themselves don't change, so nothing
needs a rebuild; later rebuilds keep the line (make_ass.py writes it from the notes file), and embed.py leaves the line
out of its check, so a film with its notes inside it stays current.

It never changes a video or a subtitle file, and uses no API credits. What it sends to OpenSubtitles: the file's
fingerprint (a number made from its size and its first and last 64 KB), and the title, year, season and episode
from the file and folder names.
"""
import argparse
import json
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import analyze
import embed
import find_subs
import make_ass
import prompts  # the questions (and on Windows, lets a GUI's Cancel stop this script cleanly)
import workfiles
from fileio import read_text, replacing, unique_backup, write_text_safely
from generate_notes import year_in_text
from subtitles import fold

IMDB = re.compile(r"\btt(\d{7,9})\b")
NAME_IMDB = re.compile(r"[\[{(]\s*imdb(?:id)?\s*[-=: ]\s*(tt\d{7,9})\s*[\]})]", re.I)
NAME_TMDB = re.compile(r"[\[{(]\s*tmdb(?:id)?\s*[-=: ]\s*(\d+)\s*[\]})]", re.I)
NFO_TMDB = (re.compile(r"<uniqueid[^>]*type=[\"']tmdb[\"'][^>]*>\s*(\d+)\s*<", re.I),
            re.compile(r"<tmdbid>\s*(\d+)\s*<", re.I),
            re.compile(r"themoviedb\.org/(?:movie|tv)/(\d+)", re.I))
NFO_MAX = 1 << 20                        # an .nfo bigger than this isn't a metadata file
SEASON_FOLDER = re.compile(r"(season|series|staffel|saison|temporada|s)\s*\d+|specials|disc\s*\d+", re.I)
PAUSE = 0.6                              # seconds between OpenSubtitles requests (it allows about 5 a second)
CHOICES = 4                              # films offered when a title search isn't sure


def say(msg=""):
    print(msg, flush=True)


# ---------------------------------------------------------------- the films and their files
def notes_files(video):
    """The film's notes files that exist: its context notes (named for the video or for its subtitles) and its Behind
    the Scenes notes."""
    found = []
    p = workfiles.notes_path(video)
    if p.exists():
        found.append(p)
    else:
        stem = workfiles.nfc(video.stem)
        for d in (workfiles.folder(video), video.parent):
            for q in sorted(d.glob("notes-*.json")) if d.is_dir() else []:
                name = workfiles.nfc(q.name)
                if name.startswith(f"notes-{stem}.") and not name.endswith(".partial.json"):
                    found.append(q)
                    break
            if found:
                break
    bts = workfiles.bts_notes_path(video)
    if bts.exists():
        found.append(bts)
    return found


def ass_files(video):
    """The film's built notes beside it: the context notes' .ass and the Behind the Scenes one."""
    return [p for p in (embed.ass_path(video), workfiles.bts_ass_path(video)) if p.exists()]


def has_notes(video):
    return bool(ass_files(video) or notes_files(video))


def films(path):
    """Every video with notes at `path` (a video, or a folder and the folders under it)."""
    if path.is_file():
        return [path] if has_notes(path) else []
    out = []
    for p in sorted(path.rglob("*")):
        try:
            parts = p.relative_to(path).parts
        except ValueError:
            continue
        if (p.suffix.lower() in workfiles.VIDEO_EXTS and not p.name.startswith(".") and workfiles.FOLDER not in parts
                and not any(x.startswith(("#", "@", ".")) for x in parts[:-1]) and p.is_file() and has_notes(p)):
            out.append(p)
    return out


def read_spec(path):
    spec = json.loads(read_text(path))
    return spec if isinstance(spec, dict) else {"notes": spec}


# ---------------------------------------------------------------- ids from this computer
def imdb_id(value):
    """'tt0079470' from 79470, '79470', 'tt79470' or 'tt0079470'; None for nothing usable."""
    if value in (None, "", 0):
        return None
    m = re.fullmatch(r"(?:tt)?0*(\d{1,9})", str(value).strip(), re.I)
    return f"tt{int(m.group(1)):07d}" if m and int(m.group(1)) else None


def show_folder(video):
    """The show's folder for an episode: the first folder above that isn't 'Season 2' or the like."""
    for d in [video.parent, *video.parent.parents][:3]:
        if not SEASON_FOLDER.fullmatch(d.name.strip()):
            return d
    return video.parent


def ids_in_name(text):
    out = {}
    m = NAME_IMDB.search(text)
    if m:
        out["imdb"] = imdb_id(m.group(1))
    m = NAME_TMDB.search(text)
    if m:
        out["tmdb"] = int(m.group(1))
    return out


def ids_in_nfo(path):
    try:
        if path.stat().st_size > NFO_MAX:
            return {}
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return {}
    out = {}
    m = IMDB.search(text)
    if m:
        out["imdb"] = imdb_id(m.group(1))
    for pattern in NFO_TMDB:
        m = pattern.search(text)
        if m:
            out["tmdb"] = int(m.group(1))
            break
    return out


def nfo_for(video):
    """The .nfo that describes this video: <video name>.nfo, movie.nfo, or the only .nfo in a folder with one video."""
    d = video.parent
    for name in (f"{video.stem}.nfo", "movie.nfo"):
        if (d / name).is_file():
            return d / name
    try:
        entries = list(d.iterdir())
    except OSError:
        return None
    nfos = [p for p in entries if p.suffix.lower() == ".nfo" and p.name.lower() != "tvshow.nfo"]
    videos = [p for p in entries if p.suffix.lower() in workfiles.VIDEO_EXTS and not p.name.startswith(".")]
    return nfos[0] if len(nfos) == 1 and len(videos) == 1 else None


def ids_in_tags(video):
    try:
        info = analyze.ffprobe_json(video, "-show_format")
    except (OSError, SystemExit, ValueError):
        return {}
    tags = {k.upper(): str(v) for k, v in ((info.get("format") or {}).get("tags") or {}).items()}
    out = {}
    if imdb_id(tags.get("IMDB") or tags.get("IMDB_ID")):
        out["imdb"] = imdb_id(tags.get("IMDB") or tags.get("IMDB_ID"))
    m = re.search(r"(\d+)\s*$", tags.get("TMDB") or tags.get("TMDB_ID") or "")
    if m:
        out["tmdb"] = int(m.group(1))
    return out


def local_ids(video):
    """(ids for the film or episode itself, ids for its series, where they came from), from names, .nfo files and
    tags. Only what's on this computer."""
    episode = find_subs.episode_code(video.name)
    own, series, where = {}, {}, []

    def take(found, into, label):
        new = {k: v for k, v in found.items() if v and k not in into}
        if new:
            into.update(new)
            where.append(label)

    take(ids_in_name(video.name), own, "the file name")
    if episode:
        show = show_folder(video)
        take(ids_in_name(show.name), series, "the show's folder name")
        if (show / "tvshow.nfo").is_file():
            take(ids_in_nfo(show / "tvshow.nfo"), series, "tvshow.nfo")
    else:
        take(ids_in_name(video.parent.name), own, "the folder name")
    nfo = video.with_suffix(".nfo") if episode else nfo_for(video)
    if nfo and nfo.is_file():
        take(ids_in_nfo(nfo), own, nfo.name)
    if video.suffix.lower() in (".mkv", ".webm", ".mka"):
        take(ids_in_tags(video), own, "the file's tags")
    return own, series, where


# ---------------------------------------------------------------- ids from OpenSubtitles
def from_feature(f):
    """Our ids from an OpenSubtitles result's feature_details."""
    kind = str(f.get("feature_type") or "").lower()
    ids = {"type": "episode" if kind == "episode" else "movie" if kind == "movie" else kind or None,
           "imdb": imdb_id(f.get("imdb_id")), "tmdb": int(f["tmdb_id"]) if f.get("tmdb_id") else None,
           "title": f.get("title") or None, "year": int(f["year"]) if f.get("year") else None}
    if kind == "episode":
        ids["season"], ids["episode"] = f.get("season_number"), f.get("episode_number")
        series = {"imdb": imdb_id(f.get("parent_imdb_id")),
                  "tmdb": int(f["parent_tmdb_id"]) if f.get("parent_tmdb_id") else None,
                  "title": f.get("parent_title") or None}
        ids["series"] = {k: v for k, v in series.items() if v} or None
    return {k: v for k, v in ids.items() if v is not None}


def features(results, exact=False):
    """The different films in a list of search results (with exact, only results made for this exact file)."""
    out = {}
    for r in results:
        a = r.get("attributes") or {}
        f = a.get("feature_details") or {}
        if (exact and not a.get("moviehash_match")) or not (f.get("imdb_id") or f.get("tmdb_id")):
            continue
        out.setdefault((f.get("imdb_id"), f.get("tmdb_id")), f)
    return list(out.values())


def words(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", fold(str(text)).replace("'", "")).split())


def same_title(theirs, ours):
    """Is OpenSubtitles' title the one in our file name? Either contains the other, word for word ('Life of Brian'
    and 'monty pythons life of brian')."""
    a, b = f" {words(theirs)} ", f" {words(ours)} "
    return len(a) > 2 and len(b) > 2 and (a in b or b in a)


def describe(ids):
    """'Life of Brian (1979)', or 'Breaking Bad S01E02 "Cat's in the Bag..." (2008)'."""
    series = ids.get("series") or {}
    if ids.get("type") == "episode":
        name = f"{series.get('title') or '?'} S{ids.get('season') or 0:02d}E{ids.get('episode') or 0:02d}"
        name += f' "{ids["title"]}"' if ids.get("title") else ""
    else:
        name = ids.get("title") or "?"
    return name + (f" ({ids['year']})" if ids.get("year") else "")


class Online:
    """OpenSubtitles' search, paced, and switched off for the rest of the run after an error."""
    def __init__(self, cfg, api=find_subs.OS_API):
        self.client = find_subs.OpenSubtitles(cfg, api)
        self.last = 0.0
        self.broken = None

    def search(self, **params):
        if self.broken:
            return []
        wait = PAUSE - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        try:
            return self.client.search(None, **params)
        except (find_subs.OpenSubtitlesError, RuntimeError) as e:
            self.broken = str(e)
            say(f"  ! OpenSubtitles: {e}. Not searching it again in this run.")
            return []
        finally:
            self.last = time.monotonic()


def by_fingerprint(video, online, episode):
    h = find_subs.movie_hash(video)
    found = features(online.search(moviehash=h), exact=True) if h else []
    if len(found) != 1:
        return None
    ids = from_feature(found[0])
    if episode and (ids.get("type") != "episode" or (ids.get("season"), ids.get("episode")) != episode):
        return None                       # made for this file, but its name says another episode: don't trust it
    return ids


def episode_title(video):
    """The episode's title from its file name, the words after the episode code ('S02E03 Moss and the German' ->
    'moss and the german'), without release words (1080p, bluray...). '' when there's none."""
    m = re.search(r"(?<![0-9a-z])s?\d{1,2}[ex]\d{2}(?![0-9])", video.stem, re.I)
    rest = re.sub(r"[._\-\[\]()]+", " ", video.stem[m.end():]) if m else ""
    return words(find_subs.JUNK.sub(" ", rest))


def by_title(video, online, year, episode, series):
    """(ids when exactly one film fits, [the films that might fit] otherwise)."""
    key = find_subs.show_key(video)
    named_year = year_in_text(key) if key else None
    query = re.sub(r"\s*\b(19|20)\d{2}$", "", key or "").strip()
    if not query:
        return None, []
    if episode:
        found = [from_feature(f) for f in features(online.search(query=query, season=episode[0], episode=episode[1]))]
        found = [i for i in found if i.get("type") == "episode" and (i.get("season"), i.get("episode")) == episode]
        if series.get("imdb"):
            sure = [i for i in found if (i.get("series") or {}).get("imdb") == series["imdb"]]
            if len(sure) == 1:
                return sure[0], []
        found = [i for i in found if same_title((i.get("series") or {}).get("title", ""), query)]
        if len(found) == 1:                       # one show of that name has this season and episode
            return found[0], []
        named = episode_title(video)              # several (a remake, say): the episode's title, else the year
        for sure in ([i for i in found if named and same_title(i.get("title", ""), named)],
                     [i for i in found if named_year and i.get("year") and abs(i["year"] - named_year) <= 1]):
            if len(sure) == 1:
                return sure[0], []
        return None, found[:CHOICES]
    found = [from_feature(f) for f in features(online.search(query=query, **({"year": year} if year else {})))]
    found = [i for i in found if i.get("type") == "movie"]
    fits = [i for i in found if same_title(i.get("title", ""), query)]
    sure = [i for i in fits if year and i.get("year") == year]
    if len(sure) == 1:
        return sure[0], []
    return None, (fits or found)[:CHOICES]


def by_imdb(online, imdb, episode):
    for f in features(online.search(imdb_id=int(imdb[2:]))):
        ids = from_feature(f)
        if ids.get("imdb") == imdb and (not episode or (ids.get("season"), ids.get("episode")) == episode):
            return ids
    return None


# ---------------------------------------------------------------- one film
def look_up(video, spec, online, ask, given=None):
    """(ids, where they came from, [films that might fit, when it wasn't sure]). ids is None when nothing was found.
    given: ids from the command line (--imdb, --tmdb)."""
    episode = find_subs.episode_code(video.name)
    year = spec.get("year") or year_in_text(video.stem) or year_in_text(video.parent.name)
    year = int(year) if str(year or "").isdigit() else None
    own, series, where = local_ids(video)
    if given:
        own, where = {**own, **given}, ["the command line", *where]
    base = {"type": "episode" if episode else "movie", **own}
    if episode:
        base.update(season=episode[0], episode=episode[1])
        if series:
            base["series"] = series
    if own.get("imdb") and (own.get("tmdb") or episode) and (not episode or series.get("tmdb")):
        return base, ", ".join(where), []
    if online is None:
        return (base, ", ".join(where), []) if own or series else (None, "", [])
    found = None
    if own.get("imdb"):
        found = by_imdb(online, own["imdb"], episode)
        how = "OpenSubtitles, by its IMDb id"
    if not found:
        found = by_fingerprint(video, online, episode)
        how = "OpenSubtitles: subtitles made for this exact file"
        if found and own.get("imdb") and found.get("imdb") != own["imdb"]:
            found = None                          # this computer's id disagrees: keep what's here
    choices = []
    if not found and not own:
        found, choices = by_title(video, online, year, episode, series)
        how = "OpenSubtitles, by title" + (" and year" if not episode else ", season and episode")
        if not found and choices:
            found = ask(video, choices)
            how = "OpenSubtitles, by title (you chose it)"
            choices = [] if found else choices
    if not found:
        return (base, ", ".join(where), choices) if own or series else (None, "", choices)
    merged = {**found, **own}                     # what this computer says wins
    if found.get("series") or series:
        merged["series"] = {**(found.get("series") or {}), **series}
    return merged, ", ".join([*where, how]), []


def ask_which(dry_run, yes):
    """The question for a title search that isn't sure: which of these films is it? None for none (or no asking)."""
    def ask(video, choices):
        if dry_run or yes or not (prompts.interactive() or prompts.machine()):
            return None
        options = {str(k): f"{describe(c)}, {c.get('imdb') or 'no IMDb id'}" for k, c in enumerate(choices, 1)}
        options["n"] = "none of these (leave this film without ids)"
        answer = prompts.ask(f"Which film is {video.name}?", options, "n", id="ids.which")
        return choices[int(answer) - 1] if answer.isdigit() and 0 < int(answer) <= len(choices) else None
    return ask


# ---------------------------------------------------------------- writing
def set_film_line(data, line):
    """An .ass file's bytes with its header's "; Film:" line replaced, or added before "Title:" ("" removes it).
    Its BOM, line endings and everything else stay as they were."""
    head, sep, rest = data.partition(b"\n[V4+ Styles]")
    newline = b"\r\n" if b"\r\n" in head else b"\n"
    new = line.encode("utf-8").replace(b"\n", newline)
    if embed.FILM_LINE.search(head):
        head = embed.FILM_LINE.sub(lambda m: new, head, count=1)
    else:
        m = re.search(rb"^Title:", head, re.M) or re.search(rb"^\[Script Info\][^\n]*\n", head, re.M)
        at = (m.start() if m.group(0).startswith(b"Title") else m.end()) if m else 0
        head = head[:at] + new + head[at:]
    return head + sep + rest


def plex_copies(ass):
    """Copies of this .notes.ass beside it, such as the Plex copy <video>.en.ass, that are the same file today."""
    if not ass.name.endswith(".notes.ass"):
        return []
    stem, data = ass.name[:-len(".notes.ass")], ass.read_bytes()
    out = []
    for p in sorted(ass.parent.glob(f"{glob_escape(stem)}.*.ass")):
        if re.fullmatch(r"\.[a-z]{2,3}\.ass", p.name[len(stem):]) and p.read_bytes() == data:
            out.append(p)
    return out


def glob_escape(text):
    return re.sub(r"([*?\[])", r"[\1]", text)


def keep_backup(video, path):
    backup = unique_backup(workfiles.place(video) / path.name)
    workfiles.make_dirs(backup.parent)
    shutil.copy2(path, backup)
    return backup


def write_ids(video, ids):
    """Write ids into the film's notes files, then into the header of its .ass files (after, so each .ass stays newer
    than its notes). Returns [(file, backup)]."""
    done = []
    for path in notes_files(video):
        spec = read_spec(path)
        if spec.get("ids") == ids:
            continue
        done.append((path, keep_backup(video, path)))
        spec["ids"] = ids
        write_text_safely(path, json.dumps(spec, indent=1, ensure_ascii=False) + "\n")
    line = make_ass.film_line({"ids": ids})
    for ass in ass_files(video):
        old = ass.read_bytes()
        new = set_film_line(old, line)
        if new == old:
            continue
        for path in [*plex_copies(ass), ass]:          # the copies first: they're found by matching the .notes.ass
            done.append((path, keep_backup(video, path)))
            with replacing(path) as tmp:
                tmp.write_bytes(new)
            if embed.sha1(path) != embed.sha1_of(old):
                raise RuntimeError(f"{path.name}: changed more than its Film line (restore {done[-1][1]})")
    return done


# ---------------------------------------------------------------- the command
def main(argv=None):
    ap = argparse.ArgumentParser(description="Find each film's IMDb and TMDB ids and write them into its notes.")
    ap.add_argument("path", type=Path, help="a video, or a folder (the folders under it are included)")
    ap.add_argument("--dry-run", action="store_true", help="only list what it finds; change nothing")
    ap.add_argument("--offline", action="store_true", help="don't search OpenSubtitles.com (names, .nfo and tags only)")
    ap.add_argument("--again", action="store_true", help="look again for films that already have ids")
    ap.add_argument("--imdb", help="one video: its IMDb id (tt0079470)")
    ap.add_argument("--tmdb", type=int, help="one video: its TMDB id (583)")
    ap.add_argument("--yes", action="store_true", help="write without asking (a title search that isn't sure is skipped)")
    ap.add_argument("--api-url", default=find_subs.OS_API, help=argparse.SUPPRESS)       # tests: a stand-in server
    a = ap.parse_args(argv)

    path = a.path.expanduser()
    if not path.exists():
        sys.exit(f"Not found: {path}")
    given = {}
    if a.imdb or a.tmdb:
        if not path.is_file():
            sys.exit("--imdb and --tmdb are for one video, not a folder.")
        if a.imdb and not imdb_id(a.imdb):
            sys.exit(f"--imdb {a.imdb}: an IMDb id looks like tt0079470.")
        given = {k: v for k, v in (("imdb", imdb_id(a.imdb)), ("tmdb", a.tmdb)) if v}
    todo = films(path)

    def shown(video):
        """A film's path from the folder given, so two of the same name in different folders tell apart."""
        return str(video.relative_to(path)) if path.is_dir() else video.name

    if not todo:
        say(f"No films with notes at {path}.")
        return 0
    online = None
    if not a.offline:
        cfg = find_subs.os_load()
        if cfg:
            online = Online(cfg, a.api_url)
        else:
            say("No OpenSubtitles.com login is saved, so only names, .nfo files and tags are used. To search it too:"
                "  python3 find_subs.py --set-opensubtitles")
    ask = ask_which(a.dry_run, a.yes)
    plan, have, missing = [], 0, []
    say(f"Looking up {len(todo)} film(s)...")
    for video in todo:
        files = notes_files(video)
        spec = read_spec(files[0]) if files else {}
        if spec.get("ids") and not a.again and not given:
            have += 1
            ids, where = spec["ids"], "already in its notes"
            if all(set_film_line(p.read_bytes(), make_ass.film_line(spec)) == p.read_bytes() for p in ass_files(video)):
                prompts.event("film-ids", video=str(video), ids=ids, source=where, status="done")
                continue
        else:
            ids, where, choices = look_up(video, spec, online, ask, given)
            if not ids:
                missing.append((video, choices))
                prompts.event("film-ids", video=str(video), status="not-found",
                              choices=[{"ids": c, "name": describe(c)} for c in choices])
                continue
            ids = {**ids, "source": where, "found": date.today().isoformat()}
        plan.append((video, ids))
        line = make_ass.film_line({"ids": ids}).strip() or "; Film: (no ids)"
        say(f"  {shown(video)}\n      {describe(ids)}: {line[len('; Film: '):]}   [{where}]")
        prompts.event("film-ids", video=str(video), ids=ids, source=where, status="found")
    for video, choices in missing:
        say(f"  {shown(video)}\n      not found" + (": it might be " + "; ".join(
            f"{describe(c)} {c.get('imdb', '')}".strip() for c in choices) if choices else "")
            + f"   (give it with  {Path(sys.argv[0]).name} \"{video}\" --imdb tt...)")
    say(f"\n{len(plan)} film(s) to write, {have} already had ids, {len(missing)} not found.")
    if not plan:
        return 0
    if a.dry_run:
        say("Nothing was changed (--dry-run).")
        return 0
    if not a.yes and not (prompts.interactive() or prompts.machine()):
        sys.exit("Not an interactive terminal, so add --yes to write them (or --dry-run to only list them).")
    if prompts.ask(f"Write these ids into the notes of {len(plan)} film(s)? (each file is kept as a .bak first)",
                   {"y": "yes, write them", "n": "no"}, "y", a.yes, id="ids.write") != "y":
        say("Nothing was changed.")
        return 0
    problems = 0
    for video, ids in plan:
        try:
            done = write_ids(video, ids)
        except (OSError, ValueError, RuntimeError) as e:
            problems += 1
            say(f"  ! {video.name}: {e}")
            continue
        say(f"  {shown(video)}: " + (", ".join(p.name for p, _ in done) if done else "already up to date"))
    say(f"Done: {len(plan) - problems} film(s)." + (f" {problems} couldn't be written (above)." if problems else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
