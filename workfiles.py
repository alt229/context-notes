#!/usr/bin/env python3
"""
workfiles.py - where a video's working files go. Every script uses it; tidy.py moves old files in.

Beside the video stays only what players use:

    Parasite.mkv
    Parasite.notes.ass               the notes, for VLC (made by make_ass.py)
    Parasite.en.ass                  the same notes, named for Plex
    Parasite.en.srt                  subtitles: yours, or ones find_subs.py found or downloaded

Everything else goes in a folder of its own, inside one "context-notes" folder beside the videos:

    context-notes/Parasite.mkv/
        notes-Parasite.json          the notes, with their backups (.bak), refine report and pick-up files
        Parasite.embedded.en.srt     subtitles pulled out of the video, re-timed (.aligned) or written by speech
                                     recognition (.transcribed); numbered transcripts; the chat upload file
        analysis/                    the sync report, contact sheets, soundtrack and speech-recognition caches

The context-notes folder also gets the files Plex (.plexignore), Jellyfin and Emby 4.8 (.ignore) and Emby 4.9+
(.embyignore) read to skip a folder when they scan a library: there are no videos in it, only thousands of frames.

Earlier versions left these files beside the video, with the analysis in "<video name> analysis/". A film that
has them carries on that way, exactly as before, until tidy.py moves them all into its folder (place()); the
scripts look in both places either way.
"""
import os
import re
import unicodedata
from pathlib import Path

FOLDER = "context-notes"
ANALYSIS = "analysis"
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".ts", ".m2ts", ".mpg", ".mpeg", ".wmv", ".flv"}
# film.en.aligned.srt and film.embedded.en.srt are made from film.en.srt and the video, so share its notes
DERIVED_SUFFIX = re.compile(r"(\.embedded(\.[a-z]{2})?)?(\.aligned(\.first\d+s)?)?$")


def nfc(name):
    """One spelling for accented names. 'é' can be stored as one character or as 'e' plus an accent mark; macOS
    treats both as the same file, but as text they differ (seen with a downloaded Amélie.2001.mp4)."""
    return unicodedata.normalize("NFC", str(name))


IGNORE_FILES = {                  # what media servers read to skip a folder (their docs, checked 2026-10-24)
    ".ignore": "",                # Jellyfin and Emby 4.8: an empty file skips the folder and all below it
    ".embyignore": "# Made by Context Notes: working files only, nothing for the library.\n*\n",    # Emby 4.9+
    ".plexignore": "# Made by Context Notes: working files only, nothing for the library.\n*\n*/*\n*/*/*\n*/*/*/*\n",
}


def make_dirs(path):
    """mkdir -p for a working folder. The first time a context-notes folder is made, it gets IGNORE_FILES (never
    replacing one that's there)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    for p in (path, *list(path.parents)[:3]):
        if p.parent.name == FOLDER and p.suffix.lower() in VIDEO_EXTS:       # context-notes/<video file name>
            for name, text in IGNORE_FILES.items():
                try:
                    with open(p.parent / name, "x", encoding="utf-8") as f:
                        f.write(text)
                except OSError:                    # there already (yours, or ours), or the folder won't take it
                    pass
            break
    return path


def folder(video):
    """context-notes/<video file name>/ beside the video. Not made here: whatever writes the first file makes it
    (with make_dirs)."""
    video = Path(video)
    return video.parent / FOLDER / video.name


def started_before(video):
    """Did an earlier version start this film? Its working files are beside it (see is_working) and it has no
    context-notes folder of its own yet. Such a film carries on as before until tidy.py moves them."""
    video = Path(video)
    if folder(video).is_dir():
        return False
    if old_analysis(video).is_dir():
        return True
    try:
        names = [nfc(n) for n in os.listdir(video.parent)]
    except OSError:
        return False
    stem = nfc(video.stem)
    mine = [n for n in names if (n.startswith(stem + ".") or n.startswith(f"notes-{stem}.")) and is_working(n, stem)
            and not n.endswith(".chat-replies.txt")]          # that one you make yourself (chat_notes.py)
    if not mine:
        return False
    videos = [video.parent / n for n in names if Path(n).suffix.lower() in VIDEO_EXTS and not n.startswith(".")]
    return any(_owner(n, videos) == [video.parent / nfc(video.name)] for n in mine)


def place(video):
    """Where a video's new working files go: its context-notes folder, or beside it for a film an earlier version
    started (until tidy.py moves its files in)."""
    video = Path(video)
    return video.parent if started_before(video) else folder(video)


def old_analysis(video):
    """Where earlier versions kept the analysis: "<video name> analysis/" beside the video."""
    video = Path(video)
    return video.parent / f"{video.stem} analysis"


def analysis(video):
    """The video's analysis folder: context-notes/<video>/analysis/, or "<video name> analysis/" beside it for a
    film an earlier version started (so its frames, soundtrack and transcripts are reused, not made again)."""
    new, old = folder(video) / ANALYSIS, old_analysis(video)
    if new.is_dir():
        return new
    return old if old.is_dir() or started_before(video) else new


def in_folder(path):
    """Is this file in a video's working folder (context-notes/<video file name>/)?"""
    p = Path(path)
    return p.parent.parent.name == FOLDER and p.parent.suffix.lower() in VIDEO_EXTS


def video_for(path):
    """The video a working or subtitle file belongs to: for context-notes/<video>/<file>, that video; for a file
    beside videos, the one its name starts with (name without the extension, then a dot), the longest if several
    do. None if there is no such video."""
    p = Path(path)
    if in_folder(p):
        return p.parent.parent.parent / p.parent.name
    name, best = nfc(p.name), None
    try:
        entries = sorted(p.parent.iterdir())
    except OSError:
        return None
    for v in entries:
        if (v.suffix.lower() in VIDEO_EXTS and not v.name.startswith(".") and nfc(v.name) != name
                and name.startswith(nfc(v.stem) + ".") and (best is None or len(v.stem) > len(best.stem))):
            best = v
    return best


def folder_for(path, video=None):
    """Where files made from `path` (a subtitle file, say) go: where `video`'s working files go (place()), else
    those of the video the file belongs to (video_for), else beside the file, as before."""
    if video:
        return place(video)
    p = Path(path)
    if in_folder(p):
        return p.parent
    v = video_for(p)
    return place(v) if v else p.parent


def find(video, name):
    """A file a report or notes file names, in the video's working folder or (until tidy.py) beside the video.
    None if it's in neither."""
    for d in (folder(video), Path(video).parent):
        if (d / name).exists():
            return d / name
    return None


def find_near(path, name, video=None):
    """`name` beside `path`, else wherever else that video's files are (its working folder, or beside it). For the
    file names a notes file keeps ("original_subtitles", "display_subtitles"). None if it isn't anywhere."""
    p = Path(path)
    dirs = [p.parent]
    v = Path(video) if video else video_for(p)
    if v is not None:
        dirs += [folder(v), v.parent]
    for d in dirs:
        if (d / name).exists():
            return d / name
    return None


def subtitle_dirs(video):
    """Where a video's subtitle files can be: its working folder (pulled out, re-timed), then beside it."""
    return [folder(video), Path(video).parent]


def notes_path(video, srt=None):
    """An existing notes file for this video (named for the video, its subtitles, or the subtitles before
    re-timing), in its working folder or beside it; else notes-<video name>.json where its new working files go
    (place())."""
    video = Path(video)
    names = [f"notes-{video.stem}.json"]
    if srt:
        names.append(f"notes-{Path(srt).stem}.json")
        names.append(f"notes-{DERIVED_SUFFIX.sub('', Path(srt).stem)}.json")
    for d in (folder(video), video.parent):
        on_disk = {nfc(p.name): p for p in d.glob("notes-*.json")} if d.is_dir() else {}
        for n in names:
            if nfc(n) in on_disk:
                return on_disk[nfc(n)]
    return place(video) / names[0]


# ---------------------------------------------------------------- files earlier versions left beside the videos
MOVED_DIRS = {" analysis": ANALYSIS, " chat-replies": None}     # "<video name> analysis/" -> analysis/; None: same name
WORKING_REST = re.compile(r"""\.(?:
      .*\.ass\.bak\d*                                          # an .ass kept before a refine rebuilt it
    | (?:.*\.)?embedded(?:\..*)?\.srt                          # subtitles pulled out of the video
    | (?:.*\.)?(?:aligned|transcribed)(?:\.first\d+s)?\.srt(?:\.bak\d*|\.rejected)?  # re-timed, speech recognition
    | (?:.*\.)?transcript\.txt                                 # numbered transcripts (analyze.py)
    | chat-(?:upload|replies)\.txt                             # chat_notes.py prepare, and the replies pasted in
    | .*\.download-(?:unchecked|unreadable)                    # an OpenSubtitles download that wasn't a subtitle file
    )$""", re.X)


def _owner(name, videos):
    """The videos (by name without extension) a file beside them belongs to, for the longest such name. Several
    videos can share it (Film.mkv and Film.mp4): then the caller can't tell whose the file is."""
    best, owners = -1, []
    for v in videos:
        stem = nfc(v.stem)
        hit = (name.startswith(stem + ".") or name.startswith(f"notes-{stem}.")
               or any(name == stem + suffix for suffix in MOVED_DIRS))
        if hit and len(stem) >= best:
            if len(stem) > best:
                best, owners = len(stem), []
            owners.append(v)
    return owners


def is_working(name, stem, is_dir=False):
    """Is this file (or folder), beside the video called `stem`, one of ours that belongs in its working folder?
    Kept beside the video: the .notes.ass, the Plex copy and other .ass files, and real subtitles (.srt files that
    weren't pulled out of the video, re-timed or written by speech recognition)."""
    if is_dir:
        return any(name == stem + suffix for suffix in MOVED_DIRS)
    if name.startswith(f"notes-{stem}."):
        return True
    return name.startswith(stem + ".") and bool(WORKING_REST.fullmatch(name[len(stem):]))


def old_files(directory, videos=None):
    """What earlier versions left beside the videos in one folder: {video: [(path, where it goes)]}, plus a list of
    (path, reason) left where they are because they can't be moved safely. `videos`: the videos in it (default:
    all of them). Hidden files are never touched."""
    directory = Path(directory)
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return {}, []
    if videos is None:
        videos = [p for p in entries if p.suffix.lower() in VIDEO_EXTS and not p.name.startswith(".") and p.is_file()]
    plan, skipped = {}, []
    for p in entries:
        name = nfc(p.name)
        if name.startswith(".") or name == FOLDER or p.suffix.lower() in VIDEO_EXTS:
            continue
        owners = _owner(name, videos)
        if not owners:
            continue
        is_dir = p.is_dir()
        if not is_working(name, nfc(owners[0].stem), is_dir):
            continue
        if len(owners) > 1:
            skipped.append((p, f"it could belong to {' or '.join(v.name for v in owners)}"))
            continue
        video = owners[0]
        dest = folder(video) / ((MOVED_DIRS[name[len(nfc(video.stem)):]] or p.name) if is_dir else p.name)
        plan.setdefault(video, []).append((p, dest))
    return plan, skipped
