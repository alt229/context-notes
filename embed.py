#!/usr/bin/env python3
"""
embed.py - put a film's notes inside the film, as a subtitle track (.mkv only, for now).

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

How it stays safe:
  - The new file is made first, in the film's context-notes folder (which media servers skip), and checked: the
    same length, the same tracks, chapters and fonts, plus the new one. Only then is it swapped in.
  - Your original is kept there as <film>.original.mkv until you delete it (--delete-backups does, for films that
    now have the notes). Embedding again later (the notes changed) replaces the Context Notes track, never adds a
    second, and leaves that first original alone.
  - Anything wrong, or Ctrl-C: the film is exactly as it was.
  - It needs about the film's size in free space while it works (one film at a time).
Only .mkv: an .mp4 can't hold these subtitles without losing their styling, so .mp4 files are left as they are.
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
import prompts  # noqa: E402
import tidy  # noqa: E402
import workfiles  # noqa: E402

TRACK_TITLE = "Context Notes"
HASH_TAG = "CONTEXT_NOTES_SHA1"          # on the track: which .notes.ass it was made from
LANGUAGE = "eng"
CONTAINERS = {".mkv"}
SPACE_MARGIN = 0.02                      # free space needed: the film's size plus this much, plus 64 MB
VERIFY_SIZE = 0.99                       # the new file can't be smaller than this much of the old one


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


def ass_path(video):
    return Path(str(Path(video).with_suffix("")) + ".notes.ass")


def sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_path(video):
    video = Path(video)
    return workfiles.folder(video) / f"{video.stem}.original{video.suffix}"


def probe(path):
    """ffprobe's view of a file: {"streams": [...], "chapters": [...], "format": {...}}."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_chapters", "-show_format", "-of", "json",
                        str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        last = (r.stderr or "").strip().splitlines()[-1:] or [str(r.returncode)]
        raise Problem(f"ffprobe couldn't read it: {last[0]}")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise Problem("ffprobe's answer couldn't be read")


def tag(stream, name):
    for k, v in (stream.get("tags") or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def notes_tracks(info):
    """Subtitle streams this tool made: titled "Context Notes" and carrying the hash tag."""
    return [s for s in info["streams"] if s.get("codec_type") == "subtitle"
            and tag(s, "title") == TRACK_TITLE and tag(s, HASH_TAG)]


def partial_notes(video):
    """The limit (seconds) of a notes file that only covers the start of the film, else None."""
    video = Path(video)
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


def inspect(video):
    """What embedding would do for one video: {"video", "action", "reason", "size", ...}.
    action: add, update, current (nothing to do), or skip (reason says why)."""
    video = Path(video)
    out = {"video": video, "action": "skip", "reason": "", "size": 0, "sha1": None, "old": []}
    ass = ass_path(video)
    if video.suffix.lower() not in CONTAINERS:
        out["reason"] = (f"{video.suffix.lower() or 'this kind of file'} can't hold these subtitles without losing "
                         f"their styling, so it stays as it is (.mkv only for now)")
        return out
    if not ass.exists():
        out["reason"] = f"no {ass.name} beside it yet"
        return out
    if video.is_symlink():
        out["reason"] = "it is a link to a file elsewhere; embed the file itself"
        return out
    limit = partial_notes(video)
    if limit:
        out["reason"] = (f"the notes only cover the first {int(limit) // 60}:{int(limit) % 60:02d}; "
                         f"run the whole film first")
        return out
    try:
        out["size"] = video.stat().st_size
        out["sha1"] = sha1(ass)
        info = probe(video)
    except (OSError, Problem) as e:
        out["reason"] = f"couldn't read it: {e}"
        return out
    old = notes_tracks(info)
    out["old"] = [s["index"] for s in old]
    out["info"] = info
    if len(old) == 1 and tag(old[0], HASH_TAG) == out["sha1"]:
        out["action"], out["reason"] = "current", "already has these notes inside"
    else:
        out["action"] = "update" if old else "add"
    return out


def plan_for(path, recursive=False):
    """([inspect() result for every video with a .notes.ass beside it], how many videos have no notes yet).
    For one video, just that video (whatever its state)."""
    path = Path(path)
    if path.is_file():
        return [inspect(path)], 0
    plan, without = [], 0
    for d in tidy.folders_under(path, recursive):
        try:
            names = sorted(d.iterdir())
        except OSError:
            continue
        for p in names:
            if p.suffix.lower() not in workfiles.VIDEO_EXTS or p.name.startswith(".") or not p.is_file():
                continue
            if ass_path(p).exists():
                plan.append(inspect(p))
            else:
                without += 1
    return plan, without


def describe(item, base):
    v = item["video"]
    name = os.path.relpath(v, base) if base else v.name
    act = item["action"]
    if act in ("add", "update"):
        verb = "put the notes inside" if act == "add" else "replace the notes inside (the .notes.ass changed)"
        return f"{name}: {verb}  ({size_text(item['size'])})"
    if act == "current":
        return f"{name}: {item['reason']}"
    return f"{name}: skipped, {item['reason']}"


def check_space(video, size):
    wdir = workfiles.folder(video)
    where = wdir if wdir.is_dir() else Path(video).parent
    free = shutil.disk_usage(where).free
    need = int(size * (1 + SPACE_MARGIN)) + 64 * 1024 * 1024
    if free < need:
        raise Problem(f"not enough free space to work in: needs about {size_text(need)}, {size_text(free)} free "
                      f"where {Path(video).name} is")


def build_command(video, ass, tmp, item, make_default):
    old = item["old"]
    kept_subs = [s["index"] for s in item["info"]["streams"]
                 if s.get("codec_type") == "subtitle" and s["index"] not in old]
    n = len(kept_subs)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", "-i", str(video),
           "-i", str(ass), "-map", "0"]
    for i in old:
        cmd += ["-map", f"-0:{i}"]
    cmd += ["-map", "1", "-map_chapters", "0", "-c", "copy",
            f"-metadata:s:s:{n}", f"language={LANGUAGE}", f"-metadata:s:s:{n}", f"title={TRACK_TITLE}",
            f"-metadata:s:s:{n}", f"{HASH_TAG}={item['sha1']}"]
    if make_default:
        for k in range(n):
            cmd += [f"-disposition:s:{k}", "0"]
        cmd += [f"-disposition:s:{n}", "default"]
    else:
        cmd += [f"-disposition:s:{n}", "0"]
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
            if s["index"] not in skip:
                out[s.get("codec_type")] = out.get(s.get("codec_type"), 0) + 1
        return out
    want = kinds(before, skip=old)
    want["subtitle"] = want.get("subtitle", 0) + 1
    got = kinds(after)
    if want != got:
        return f"the tracks differ (expected {want}, got {got})"
    kept = [s for s in before["streams"] if s["index"] not in old and s.get("codec_type") != "subtitle"]
    now = [s for s in after["streams"] if s.get("codec_type") != "subtitle"]
    if [s.get("codec_name") for s in kept] != [s.get("codec_name") for s in now]:
        return "a track's format changed"
    kept_subs = [s for s in before["streams"] if s["index"] not in old and s.get("codec_type") == "subtitle"]
    now_subs = [s for s in after["streams"] if s.get("codec_type") == "subtitle"]
    if [s.get("codec_name") for s in kept_subs] != [s.get("codec_name") for s in now_subs[:-1]]:
        return "an existing subtitle track changed"
    new = now_subs[-1] if now_subs else {}
    if new.get("codec_name") != "ass" or tag(new, "title") != TRACK_TITLE or tag(new, HASH_TAG) != item["sha1"]:
        return "the new subtitle track isn't what was meant"
    if len(before.get("chapters") or []) != len(after.get("chapters") or []):
        return "the chapters differ"
    try:
        d0, d1 = float(before["format"]["duration"]), float(after["format"]["duration"])
    except (KeyError, ValueError):
        return "the length couldn't be read"
    if abs(d0 - d1) > max(1.0, 0.002 * d0):
        return f"the length differs ({d0:.1f} s before, {d1:.1f} s now)"
    if size_after < VERIFY_SIZE * size_before:
        return "the new file is smaller than the old one"
    return None


def swap_in(video, tmp):
    """The new file takes the film's place; the original goes to its context-notes folder. If anything goes wrong,
    the original is back where it was."""
    video = Path(video)
    st = video.stat()
    backup = backup_path(video)
    previous = None
    if backup.exists():            # an earlier embed already kept the true original: this film (which has an
        previous = workfiles.folder(video) / f"{video.stem}.previous{video.suffix}"     # older notes track) isn't kept
        if previous.exists():
            os.remove(previous)
        away = previous
    else:
        away = backup
    os.rename(video, away)
    try:
        os.rename(tmp, video)
    except OSError:
        os.rename(away, video)
        raise
    try:
        os.chmod(video, st.st_mode & 0o7777)
        os.utime(video, ns=(st.st_atime_ns, st.st_mtime_ns))            # a media server sees the same date as before
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
    if sha1(ass) != item["sha1"]:
        raise Problem(f"{ass.name} changed while this was starting; run it again")
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
        for p in (backup_path(v), workfiles.folder(v) / f"{v.stem}.previous{v.suffix}"):
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
    ap.add_argument("--delete-backups", action="store_true",
                    help="delete the originals this kept, for films that now have the notes inside")
    a = ap.parse_args(argv)
    path = Path(os.path.abspath(Path(a.path).expanduser()))
    if not path.exists():
        sys.exit(f"Can't find {path}")
    if not have_ffmpeg():
        sys.exit("ffmpeg and ffprobe aren't installed; they're needed to embed (see the README).")
    plan, without = plan_for(path, a.recursive)
    base = path if path.is_dir() else None
    for item in plan:
        print(describe(item, base))
        prompts.event("embed-plan", video=str(item["video"]), action=item["action"], size=item["size"],
                      reason=item["reason"] or None)
    if without:
        print(f"({without} video(s) here have no .notes.ass yet, so they're not listed.)")
    if a.delete_backups:
        return delete_backups(plan, a)
    todo = [i for i in plan if i["action"] in ("add", "update")]
    if not todo:
        if not plan:
            print("Nothing to embed: no video with a .notes.ass beside it"
                  + ("" if a.recursive or path.is_file() else " here (subfolders: add --recursive)") + ".")
        else:
            print("\nNothing to do.")
        return 0
    total = sum(i["size"] for i in todo)
    biggest = max(i["size"] for i in todo)
    if a.dry_run:
        print(f"\n{len(todo)} film(s), {size_text(total)}, would get their notes inside; the biggest needs "
              f"{size_text(biggest)} free while it works. Nothing was changed (--dry-run).")
        return 0
    if not a.yes and not prompts.interactive():
        sys.exit("Not an interactive terminal, so add --yes to embed (or --dry-run to only list).")
    prompts.event("estimate", step="embed", films=len(todo), bytes=total, biggest=biggest)
    if prompts.ask(f"\nPut the notes inside {len(todo)} film(s) ({size_text(total)} to copy)? Each is rewritten as a "
                   f"new file first (nothing is re-encoded), checked, then swapped in; the original is kept in its "
                   f"{workfiles.FOLDER} folder until you delete it.",
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
