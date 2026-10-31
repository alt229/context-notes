#!/usr/bin/env python3
"""
embed.py - put a film's notes inside the film, as a subtitle track (.mkv only, for now).
Created 2026-10-24, modified 2026-10-29.

    python3 embed.py film.mkv                       one film: says what it would do, asks, then does it
    python3 embed.py "/Volumes/Movies"              every .mkv in the folder that has a .notes.ass beside it
    python3 embed.py "/Volumes/Movies" --recursive  that folder and every folder under it
    python3 embed.py "/Volumes/Movies" --dry-run    only list what would be embedded
    python3 embed.py film.mkv --default             play with the notes on (otherwise the track is there to choose)
    python3 embed.py "/Volumes/Movies" --delete-backups   free the space the kept originals take (asks first)

It works on films that already have a <video>.notes.ass, however it was made: by context_notes.py (--embed does
this for you after the notes are done) or earlier. No Claude, no cost: ffmpeg copies every track as it is (no
re-encoding) and adds the .ass as one more, called "Context Notes". The track keeps its styling: the colours,
positions and fades of the notes work in VLC, Infuse and other players that show ASS subtitles.
A film with a Behind the Scenes track (<video>.behind-the-scenes.notes.ass, from context_notes.py --behind-the-scenes)
gets that too, as a second track called "Behind the Scenes": choose either one in the player.

How it stays safe:
  - The new file is made first, in the film's context-notes folder (which media servers skip), and checked: the
    same length, the same tracks, chapters and fonts, plus the new one. Only then is it swapped in.
  - Your original is kept there as <film>.original.mkv until you delete it (--delete-backups does, for films that
    now have the notes). Embedding again later (the notes changed) replaces the Context Notes track, never adds a
    second, and leaves that first original alone.
  - Anything wrong, or Ctrl-C: the film is exactly as it was.
  - It needs about the film's size in free space while it works (one film at a time).
Only .mkv: an .mp4 can't hold these subtitles without losing their styling, so .mp4 files are left as they are.
A data track an MKV can't hold (a phone's or camera's timecode) is left out of the copy, and the output says so.
Notes that only cover the first part of a film (--limit) are not embedded: run the whole film first.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze  # noqa: E402
import make_ass  # noqa: E402
import prompts  # noqa: E402
import tidy  # noqa: E402
import workfiles  # noqa: E402

TRACK_TITLE = "Context Notes"
HASH_TAG = "CONTEXT_NOTES_SHA1"          # on the track: which .notes.ass it was made from
# The tracks this puts inside a film, in this order: each from its .ass beside the film, with its own title and tag.
CONTEXT_TRACK = {"key": "context", "title": TRACK_TITLE, "hash_tag": HASH_TAG, "suffix": ".notes.ass"}
BTS_TRACK = {"key": workfiles.BTS, "title": "Behind the Scenes", "hash_tag": "CONTEXT_NOTES_BTS_SHA1",
             "suffix": workfiles.BTS_ASS}
TRACKS = (CONTEXT_TRACK, BTS_TRACK)
LANGUAGE = "eng"
CONTAINERS = {".mkv"}
SPACE_MARGIN = 0.02                      # free space needed: the film's size plus this much, plus 64 MB
VERIFY_SIZE = 0.99                       # the new file can't be smaller than this much of the old one
VERIFY_SIZE_CONVERTED = 0.9              # a converted film can differ in size a little from its .mp4 (container overhead)
CONVERT_FROM = {".mp4"}                  # --convert: these become .mkv first; the .mp4 goes to context-notes/originals
# How fast bytes move to and from the NAS: one 1 GB read and one 1 GB write, measured 2026-10-26 during a ZFS scrub.
# Only for the rough time shown before embedding; it is not a promise.
READ_MBPS = 48
WRITE_MBPS = 62


class Problem(Exception):
    """Something that stops one film (the others go on)."""


def size_text(n):
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    return f"{n / 1e3:.0f} KB"


def have_ffmpeg():
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def ass_path(video, track=CONTEXT_TRACK):
    return Path(str(Path(video).with_suffix("")) + track["suffix"])


def has_notes(video):
    """Is there an .ass of any of our tracks beside the film?"""
    return any(ass_path(video, t).exists() for t in TRACKS)


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_path(video):
    video = Path(video)
    return workfiles.folder(video) / f"{video.stem}.original{video.suffix}"


def originals_path(video):
    """Where the .mp4 of a film converted to .mkv is kept: context-notes/originals/ beside it. Names are unique within
    one folder, so one originals folder per folder is enough."""
    video = Path(video)
    return video.parent / workfiles.FOLDER / "originals" / video.name


def move_working_folder(old, new):
    """A converted film's working files (its notes, say) move to the folder named for its new .mkv."""
    src, dst = workfiles.folder(old), workfiles.folder(new)
    if src.is_dir() and not dst.exists():
        os.rename(src, dst)


def probe(path):
    """ffprobe's view of a file: {"streams": [...], "chapters": [...], "format": {...}}. Kept by analyze.ffprobe_json,
    so a film on a slow disk is read once, not on every look at it."""
    try:
        return analyze.ffprobe_json(path, "-show_streams", "-show_chapters", "-show_format")
    except SystemExit as e:
        raise Problem(f"ffprobe couldn't read it: {str(e.code).splitlines()[-1]}")


def look_of(ass):
    """The look a notes .ass was built with (its "; Look:" line): {"background", "opacity", "wpm"}, or None."""
    try:
        with open(ass, encoding="utf-8-sig", errors="replace") as f:
            m = make_ass.LOOK_LINE.search(f.read(2000))
    except OSError:
        return None
    if not m:
        return None
    return {"background": m["background"], "opacity": float(m["opacity"]) if m["opacity"] else None,
            "wpm": float(m["wpm"])}


def film_state(video):
    """For the page: what embedding would do for one film ("add", "update", "current" or "skip", and why), the look
    its notes were built with (look_of), and the same for each track ("tracks": {key: {action, reason}})."""
    item = inspect(video)
    return {"action": item["action"], "reason": item["reason"], "look": look_of(ass_path(video)),
            "tracks": {t["track"]["key"]: {"action": t["action"], "reason": t["reason"], "look": look_of(t["ass"])}
                       for t in item["tracks"]}}


def tag(stream, name):
    for k, v in (stream.get("tags") or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def notes_tracks(info, track=CONTEXT_TRACK):
    """Subtitle streams this tool made for one track: titled "Context Notes" (or "Behind the Scenes") and carrying
    its hash tag."""
    return [s for s in info["streams"] if s.get("codec_type") == "subtitle"
            and tag(s, "title") == track["title"] and tag(s, track["hash_tag"])]


def partial_notes(video, track=CONTEXT_TRACK):
    """The limit (seconds) of a notes file that only covers the start of the film, else None."""
    video = Path(video)
    if track is BTS_TRACK:
        try:
            return json.loads(workfiles.bts_notes_path(video).read_text(encoding="utf-8")).get("limit") or None
        except (OSError, ValueError, AttributeError):
            return None
    path = workfiles.notes_path(video)
    if not path.exists():
        found = []
        for d in (workfiles.folder(video), video.parent):
            if d.is_dir():
                found += [p for p in d.glob("notes-*.json")]
        if len(found) != 1:
            return None
        path = found[0]
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("limit") or None
    except (OSError, ValueError):
        return None


def inspect(video, convert=False, only=None):
    """What embedding would do for one video: {"video", "action", "reason", "size", "new", "tracks", ...}.
    action: add, update, current (nothing to do), or skip (reason says why). convert: an .mp4 is rewritten as an
    .mkv first (CONVERT_FROM), and its original goes to context-notes/originals. "tracks": each of our tracks with
    an .ass beside the film, with its own action; "new": the tracks the new file gets (all of them, rewritten
    together, when any one needs it); "old": the streams of ours those replace. `only`: judge just that track (for
    the page: is this track inside, and current?)."""
    video = Path(video)
    out = {"video": video, "action": "skip", "reason": "", "size": 0, "sha1": None, "old": [], "convert": False,
           "new": [], "tracks": []}
    converting = convert and video.suffix.lower() in CONVERT_FROM
    if video.suffix.lower() not in CONTAINERS and not converting:
        out["reason"] = (f"{video.suffix.lower() or 'this kind of file'} can't hold these subtitles without losing "
                         f"their styling, so it stays as it is (.mkv only for now)")
        return out
    present = [t for t in ((only,) if only else TRACKS) if ass_path(video, t).exists()]
    if not present:
        out["reason"] = f"no {ass_path(video, only or CONTEXT_TRACK).name} beside it yet"
        return out
    if video.is_symlink():
        out["reason"] = "it is a link to a file elsewhere; embed the file itself"
        return out
    if converting:
        target, kept = video.with_suffix(".mkv"), originals_path(video)
        if target.exists() or kept.exists():
            out["reason"] = ("a .mkv of this name is already here" if target.exists()
                             else f"its .mp4 is already kept in {workfiles.FOLDER}/originals")
            return out
        out["convert"] = True
    wanted, partial = [], []
    for t in present:
        limit = partial_notes(video, t)
        (partial if limit else wanted).append((t, limit))
    if not wanted:
        limit = partial[0][1]
        out["reason"] = (f"the notes only cover the first {int(limit) // 60}:{int(limit) % 60:02d}; "
                         f"run the whole film first")
        return out
    try:
        out["size"] = video.stat().st_size
        info = probe(video)
        for t, _ in wanted:
            out["tracks"].append({"track": t, "ass": ass_path(video, t), "sha1": sha1(ass_path(video, t))})
    except (OSError, Problem) as e:
        out["reason"] = f"couldn't read it: {e}"
        return out
    for t, limit in partial:                     # not embedded until the whole film has its notes
        out["tracks"].append({"track": t, "ass": ass_path(video, t), "sha1": None, "old": [], "action": "skip",
                              "reason": f"the notes only cover the first {int(limit) // 60}:{int(limit) % 60:02d}"})
    for item in out["tracks"]:
        if item["sha1"] is None:
            continue
        old = notes_tracks(info, item["track"])
        item["old"] = [s["index"] for s in old]
        if len(old) == 1 and tag(old[0], item["track"]["hash_tag"]) == item["sha1"]:
            item["action"], item["reason"] = "current", "already inside"
        else:
            item["action"], item["reason"] = ("update" if old else "add"), ""
    out["info"] = info
    ours = [i for i in out["tracks"] if i["sha1"] is not None]
    out["new"] = ours
    out["old"] = sorted(x for i in ours for x in i["old"])
    out["sha1"] = next((i["sha1"] for i in ours if i["track"] is CONTEXT_TRACK), ours[0]["sha1"])
    if all(i["action"] == "current" for i in ours):
        out["action"], out["reason"] = "current", "already has these notes inside"
    else:
        out["action"] = "update" if out["old"] else "add"
    return out


def plan_for(path, recursive=False, convert=False):
    """([inspect() result for every video with a .notes.ass beside it], how many videos have no notes yet).
    For one video, just that video (whatever its state)."""
    path = Path(path)
    if path.is_file():
        return [inspect(path, convert)], 0
    plan, without = [], 0
    for d in tidy.folders_under(path, recursive):
        try:
            names = sorted(d.iterdir())
        except OSError:
            continue
        for p in names:
            if p.suffix.lower() not in workfiles.VIDEO_EXTS or p.name.startswith(".") or not p.is_file():
                continue
            if has_notes(p):
                plan.append(inspect(p, convert))
            else:
                without += 1
    return plan, without


def data_tracks(item):
    """The data tracks of an inspect() result (a camera's or phone's timecode, say). An MKV can't hold them, so the copy
    leaves them out, and the output says so."""
    info = item.get("info") or {}
    return [s for s in info.get("streams", []) if s.get("codec_type") == "data"]


def dropped_text(item):
    n = len(data_tracks(item))
    if not n:
        return ""
    return f"; leaves out {n} data track{'s' if n != 1 else ''} (such as a camera's timecode), which an MKV can't hold"


def describe(item, base):
    v = item["video"]
    name = os.path.relpath(v, base) if base else v.name
    act = item["action"]
    if act in ("add", "update"):
        verb = "put the notes inside" if act == "add" else "replace the notes inside (the .notes.ass changed)"
        if item.get("convert"):
            verb = "convert to .mkv, then put the notes inside"
        if any(i["track"] is not CONTEXT_TRACK for i in item.get("new", [])):
            verb += " (" + ", ".join(f"{i['track']['title']}: {'already inside' if i['action'] == 'current' else i['action']}"
                                     for i in item["new"]) + ")"
        low, high = rewrite_seconds(item["size"])
        return (f"{name}: {verb}  ({size_text(item['size'])}, about {minutes_text(low)} to {minutes_text(high)})"
                + dropped_text(item))
    if act == "current":
        return f"{name}: {item['reason']}"
    return f"{name}: skipped, {item['reason']}"


def rewrite_seconds(size):
    """(low, high) seconds to read a film and write a new copy of it. Low: the reads and writes overlap. High: they
    don't, and it's doubled to allow for a busy disk. From the speeds above, so a rough guide only."""
    read, write = size / (READ_MBPS * 1e6), size / (WRITE_MBPS * 1e6)
    return max(read, write), 2 * (read + write)


def minutes_text(seconds):
    return f"{round(seconds)} s" if seconds < 60 else f"{seconds / 60:.0f} min"


def warning_text(todo):
    """What embedding these films costs, for the prompt, --dry-run and the page: time, the copy kept, and that no
    Claude or API call is made."""
    low = sum(rewrite_seconds(i["size"])[0] for i in todo)
    high = sum(rewrite_seconds(i["size"])[1] for i in todo)
    kept = [i for i in todo if i["action"] == "add"]
    text = (f"About {minutes_text(low)} to {minutes_text(high)} (estimated from this NAS's speed): each film is read "
            "and rewritten whole. No Claude or API calls are made.")
    if kept:
        text += (f" The original of {len(kept)} film(s) stays in its {workfiles.FOLDER} folder "
                 f"({size_text(sum(i['size'] for i in kept))} more) until you run --delete-backups.")
    if any(i.get("convert") for i in todo):
        text += (" Films converted from .mp4 change name to .mkv, so media servers may list them as new; the .mp4s "
                 f"wait in {workfiles.FOLDER}/originals.")
    if any(data_tracks(i) for i in todo):
        text += " Data tracks an MKV can't hold (a camera's timecode, say) are left out."
    return text


def check_space(video, size):
    wdir = workfiles.folder(video)
    where = wdir if wdir.is_dir() else Path(video).parent
    free = shutil.disk_usage(where).free
    need = int(size * (1 + SPACE_MARGIN)) + 64 * 1024 * 1024
    if free < need:
        raise Problem(f"not enough free space to work in: needs about {size_text(need)}, {size_text(free)} free "
                      f"where {Path(video).name} is")


def new_tracks(item, ass=None):
    """[(track, its .ass, its sha1)] for the tracks the new file gets, in order. An inspect() result from before
    there were two tracks (a test's, say) has only "sha1": the Context Notes track, from `ass`."""
    if item.get("new"):
        return [(i["track"], i["ass"], i["sha1"]) for i in item["new"]]
    return [(CONTEXT_TRACK, ass or ass_path(item["video"]), item["sha1"])]


def build_command(video, ass, tmp, item, make_default):
    old = item["old"]
    kept_subs = [s["index"] for s in item["info"]["streams"]
                 if s.get("codec_type") == "subtitle" and s["index"] not in old]
    n = len(kept_subs)
    adding = new_tracks(item, ass)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", "-i", str(video)]
    for _, path, _ in adding:
        cmd += ["-i", str(path)]
    cmd += ["-map", "0", "-map", "-0:d"]     # data tracks (a camera's timecode) can't go into an MKV
    for i in old:
        cmd += ["-map", f"-0:{i}"]
    for k in range(len(adding)):
        cmd += ["-map", str(k + 1)]
    cmd += ["-map_chapters", "0", "-c", "copy"]
    for k, (track, _, digest) in enumerate(adding):
        cmd += [f"-metadata:s:s:{n + k}", f"language={LANGUAGE}", f"-metadata:s:s:{n + k}", f"title={track['title']}",
                f"-metadata:s:s:{n + k}", f"{track['hash_tag']}={digest}"]
    if make_default:                         # the first of ours plays; the others are there to choose
        for k in range(n):
            cmd += [f"-disposition:s:{k}", "0"]
        cmd += [f"-disposition:s:{n}", "default"]
        for k in range(1, len(adding)):
            cmd += [f"-disposition:s:{n + k}", "0"]
    else:
        for k in range(len(adding)):
            cmd += [f"-disposition:s:{n + k}", "0"]
    if item.get("convert"):          # an MP4's text subtitles (mov_text) can't go into an MKV as they are: they become SRT
        codecs = {s["index"]: s.get("codec_name") for s in item["info"]["streams"]}
        for k, i in enumerate(kept_subs):
            if codecs[i] == "mov_text":
                cmd += [f"-c:s:{k}", "srt"]
    cmd += ["-default_mode", "passthrough", "-f", "matroska", str(tmp)]      # else the muxer flags a first subtitle track default
    return cmd


def run_ffmpeg(cmd, duration):
    """Run it, reporting how far it has got. Returns None, or the reason it failed. On Ctrl-C, stops ffmpeg first."""
    last_tenth = -1
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors, stdin=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace")
        try:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and duration:
                    try:
                        secs = max(0.0, int(value) / 1e6)
                    except ValueError:
                        continue
                    secs = min(secs, duration)
                    prompts.progress("embed", secs, duration, "seconds", every=1.0)
                    tenth = int(10 * secs / duration)
                    if tenth != last_tenth:
                        last_tenth = tenth
                        print(f"  {tenth * 10}%", flush=True)
            proc.wait()
        except BaseException:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise
        if proc.returncode:
            errors.seek(0)
            tail = errors.read().decode("utf-8", "replace").strip().splitlines()
            return " ".join(tail[-3:]) or f"ffmpeg stopped with code {proc.returncode}"
    return None


def verify(before, after, item, size_before, size_after):
    """None if the new file is the old one plus the notes track; else what is different."""
    old = set(item["old"])

    def kinds(info, skip=()):
        out = {}
        for s in info["streams"]:
            if s["index"] not in skip and s.get("codec_type") != "data":          # data tracks are left out of the copy
                out[s.get("codec_type")] = out.get(s.get("codec_type"), 0) + 1
        return out
    adding = new_tracks(item)
    want = kinds(before, skip=old)
    want["subtitle"] = want.get("subtitle", 0) + len(adding)
    got = kinds(after)
    if want != got:
        return f"the tracks differ (expected {want}, got {got})"
    kept = [s for s in before["streams"] if s["index"] not in old and s.get("codec_type") not in ("subtitle", "data")]
    now = [s for s in after["streams"] if s.get("codec_type") != "subtitle"]
    if [s.get("codec_name") for s in kept] != [s.get("codec_name") for s in now]:
        return "a track's format changed"
    kept_subs = [s for s in before["streams"] if s["index"] not in old and s.get("codec_type") == "subtitle"]
    now_subs = [s for s in after["streams"] if s.get("codec_type") == "subtitle"]
    def sub_format(s):               # a converted film's mov_text subtitles come out as SRT
        return "subrip" if item.get("convert") and s.get("codec_name") == "mov_text" else s.get("codec_name")
    if [sub_format(s) for s in kept_subs] != [s.get("codec_name") for s in now_subs[:len(now_subs) - len(adding)]]:
        return "an existing subtitle track changed"
    for new, (track, _, digest) in zip(now_subs[len(now_subs) - len(adding):], adding):
        if (new.get("codec_name") != "ass" or tag(new, "title") != track["title"]
                or tag(new, track["hash_tag"]) != digest):
            return "the new subtitle track isn't what was meant"
    if len(before.get("chapters") or []) != len(after.get("chapters") or []):
        return "the chapters differ"
    try:
        d0, d1 = float(before["format"]["duration"]), float(after["format"]["duration"])
    except (KeyError, ValueError):
        return "the length couldn't be read"
    if abs(d0 - d1) > max(1.0, 0.002 * d0):
        return f"the length differs ({d0:.1f} s before, {d1:.1f} s now)"
    floor = VERIFY_SIZE_CONVERTED if item.get("convert") else VERIFY_SIZE
    if size_after < floor * size_before:
        return "the new file is smaller than the old one"
    return None


def swap_in(video, tmp, target=None, away=None):
    """The new file takes the film's place (target: its .mkv, for a converted film). The original goes to its
    context-notes folder, or to away (a converted film's context-notes/originals). If anything goes wrong, the
    original is back where it was."""
    video = Path(video)
    target = Path(target) if target else video
    st = video.stat()
    previous = None
    if away is None:
        backup = backup_path(video)
        if backup.exists():            # an earlier embed already kept the true original: this film (which has an
            previous = workfiles.folder(video) / f"{video.stem}.previous{video.suffix}"     # older notes track) isn't kept
            if previous.exists():
                os.remove(previous)
            away = previous
        else:
            away = backup
    else:
        away = Path(away)
        away.parent.mkdir(parents=True, exist_ok=True)
    os.rename(video, away)
    try:
        os.rename(tmp, target)
    except OSError:
        os.rename(away, video)
        raise
    try:
        os.chmod(target, st.st_mode & 0o7777)
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))            # a media server sees the same date as before
    except OSError:
        pass
    if previous is not None:
        try:
            os.remove(previous)
        except OSError:
            pass


def embed_one(item, make_default=False):
    """Do it for one inspect() result (action add or update). Raises Problem."""
    video = item["video"]
    ass = ass_path(video)
    if not have_ffmpeg():
        raise Problem("ffmpeg isn't installed (see the README)")
    for _, path, digest in new_tracks(item, ass):
        if sha1(path) != digest:
            raise Problem(f"{Path(path).name} changed while this was starting; run it again")
    check_space(video, item["size"])
    wdir = workfiles.make_dirs(workfiles.folder(video))
    tmp = wdir / f"{video.stem}.embedding.mkv"
    try:
        if tmp.exists():
            os.remove(tmp)
        duration = float(item["info"]["format"].get("duration") or 0)
        why = run_ffmpeg(build_command(video, ass, tmp, item, make_default), duration)
        if why:
            raise Problem(f"ffmpeg failed: {why}")
        after = probe(tmp)
        bad = verify(item["info"], after, item, item["size"], tmp.stat().st_size)
        if bad:
            raise Problem(f"the new file didn't check out ({bad}), so {video.name} was left as it was")
        if video.stat().st_size != item["size"]:
            raise Problem(f"{video.name} changed while it was being copied; run it again")
        try:
            if item.get("convert"):
                swap_in(video, tmp, target=video.with_suffix(".mkv"), away=originals_path(video))
                move_working_folder(video, video.with_suffix(".mkv"))
            else:
                swap_in(video, tmp)
        except OSError as e:
            raise Problem(f"couldn't swap the new file in: {e.strerror or e}")
    finally:
        try:
            if tmp.exists():
                os.remove(tmp)
        except OSError:
            pass


def embed_all(items, make_default):
    results = []
    for k, item in enumerate(items, 1):
        v = item["video"]
        print(f"\n=== {v.name}" + (f"  ({k} of {len(items)})" if len(items) > 1 else "") + " ===", flush=True)
        prompts.event("embed-video", path=str(v), index=k, total=len(items))
        try:
            embed_one(item, make_default)
        except Problem as e:
            print(f"! {v.name}: {e}", flush=True)
            prompts.event("embed-result", path=str(v), result="stopped", reason=str(e))
            results.append((v, str(e)))
        else:
            if item.get("convert"):
                print(f"Done: {v.name} is now {v.with_suffix('.mkv').name}, with the notes inside. The .mp4 is kept as "
                      f"{os.path.join(workfiles.FOLDER, 'originals', v.name)}.", flush=True)
            else:
                print(f"Done: the notes are inside {v.name}. The original is kept as "
                      f"{os.path.join(workfiles.FOLDER, v.name, backup_path(v).name)}.", flush=True)
            prompts.event("embed-result", path=str(v), result="embedded", reason=None)
            results.append((v, None))
    return results


def delete_backups(items, a):
    found = []
    for item in items:
        v = item["video"]
        if item["action"] != "current":
            continue                  # only where the film now has the notes: that's when the original isn't needed
        kept = [backup_path(v), workfiles.folder(v) / f"{v.stem}.previous{v.suffix}"]
        if v.suffix.lower() == ".mkv":          # a film converted from .mp4 keeps that .mp4 in originals
            kept.append(originals_path(v.with_suffix(".mp4")))
        for p in kept:
            if p.exists():
                found.append(p)
    if not found:
        print("No kept originals to delete (only films that already have the notes inside count).")
        return 0
    total = sum(p.stat().st_size for p in found)
    for p in found:
        print(f"  {p}  ({size_text(p.stat().st_size)})")
        prompts.event("embed-backup", path=str(p), size=p.stat().st_size)
    if a.dry_run:
        print(f"\n{len(found)} file(s), {size_text(total)}, would be deleted. Nothing was deleted (--dry-run).")
        return 0
    if not a.yes and not prompts.interactive():
        sys.exit("Not an interactive terminal, so add --yes to delete them (or --dry-run to only list them).")
    if not a.yes and prompts.ask(f"\nDelete these {len(found)} kept original(s) ({size_text(total)})? This can't be "
                                 f"undone.", {"y": "yes, delete them", "n": "no, keep them"}, "n",
                                 id="embed.delete") != "y":      # --yes is the answer; otherwise the default is no
        print("Nothing was deleted.")
        return 0
    gone = 0
    for p in found:
        try:
            os.remove(p)
            gone += 1
        except OSError as e:
            print(f"  ! Couldn't delete {p}: {e.strerror or e}")
    print(f"Deleted {gone} file(s), freeing {size_text(total)}.")
    return 0 if gone == len(found) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="a .mkv film, or a folder of films")
    ap.add_argument("--recursive", action="store_true", help="with a folder: include every folder under it")
    ap.add_argument("--dry-run", action="store_true", help="only list what would be done")
    ap.add_argument("--yes", action="store_true", help="don't ask first")
    ap.add_argument("--default", action="store_true",
                    help="make the notes the track that plays by default (otherwise it's there to choose)")
    ap.add_argument("--convert", action="store_true",
                    help="convert .mp4 films to .mkv first, so their notes can go inside; the .mp4 is kept in "
                         f"{workfiles.FOLDER}/originals")
    ap.add_argument("--delete-backups", action="store_true",
                    help="delete the originals this kept, for films that now have the notes inside")
    a = ap.parse_args(argv)
    path = Path(os.path.abspath(Path(a.path).expanduser()))
    if not path.exists():
        sys.exit(f"Can't find {path}")
    if not have_ffmpeg():
        sys.exit("ffmpeg and ffprobe aren't installed; they're needed to embed (see the README).")
    plan, without = plan_for(path, a.recursive, a.convert)
    base = path if path.is_dir() else None
    for item in plan:
        print(describe(item, base))
        low, high = rewrite_seconds(item["size"])
        prompts.event("embed-plan", video=str(item["video"]), action=item["action"], size=item["size"],
                      reason=item["reason"] or None, seconds_low=round(low), seconds_high=round(high),
                      convert=bool(item.get("convert")), dropped=len(data_tracks(item)))
    if without:
        print(f"({without} video(s) here have no .notes.ass yet, so they're not listed.)")
    if a.delete_backups:
        return delete_backups(plan, a)
    todo = [i for i in plan if i["action"] in ("add", "update")]
    if not todo:
        if not plan:
            print("Nothing to embed: no video with a .notes.ass (or .behind-the-scenes.notes.ass) beside it"
                  + ("" if a.recursive or path.is_file() else " here (subfolders: add --recursive)") + ".")
        else:
            print("\nNothing to do.")
        return 0
    total = sum(i["size"] for i in todo)
    biggest = max(i["size"] for i in todo)
    if a.dry_run:
        print(f"\n{len(todo)} film(s), {size_text(total)}, would get their notes inside; the biggest needs "
              f"{size_text(biggest)} free while it works. {warning_text(todo)} Nothing was changed (--dry-run).")
        return 0
    if not a.yes and not prompts.interactive():
        sys.exit("Not an interactive terminal, so add --yes to embed (or --dry-run to only list).")
    prompts.event("estimate", step="embed", films=len(todo), bytes=total, biggest=biggest)
    if prompts.ask(f"\nPut the notes inside {len(todo)} film(s) ({size_text(total)} to copy)? Each is rewritten as a "
                   f"new file first (nothing is re-encoded), checked, then swapped in; the original is kept in its "
                   f"{workfiles.FOLDER} folder until you delete it. {warning_text(todo)}",
                   {"y": "yes, embed", "n": "no"}, "y", a.yes, id="embed.go") != "y":
        print("Nothing was changed.")
        return 0
    try:
        results = embed_all(todo, a.default)
    except KeyboardInterrupt:
        print("\nStopped. The film being worked on is exactly as it was; run the same command to carry on.")
        return 130
    bad = [(v, why) for v, why in results if why]
    print(f"\nEmbedded {len(results) - len(bad)} of {len(results)} film(s)." + ("" if not bad else " Not done:"))
    for v, why in bad:
        print(f"  {v.name}: {why}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
