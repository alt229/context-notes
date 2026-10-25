#!/usr/bin/env python3
"""
tidy.py - move the working files earlier versions left beside your videos into their context-notes folders.

    python3 tidy.py "/Volumes/Movies"               one folder: lists what would move, asks, then moves it
    python3 tidy.py "/Volumes/Movies" --recursive   that folder and every folder under it
    python3 tidy.py "/Volumes/Movies" --dry-run     only list what would move
    python3 tidy.py film.mkv                        one video's files

Beside each video stays only what players use: <video>.notes.ass, its Plex copy (<video>.en.ass) and real
subtitles (yours, or ones find_subs.py found or downloaded). The rest moves into context-notes/<video file name>/
(see workfiles.py): the notes file with its backups, reports and pick-up files; subtitles pulled out of the video,
re-timed (.aligned) or written by speech recognition (.transcribed); numbered transcripts; chat upload files
and the "<video name> chat-replies" folder; and the "<video name> analysis" folder, which becomes analysis/.

Files are moved as they are, never copied, changed or overwritten. A file whose name is already taken in the
folder, or that could belong to two videos (film.mkv and film.mp4), stays where it is and is listed.
The scripts find files in either place, so nothing has to be tidied before the next run.
"""
import argparse
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prompts  # noqa: E402
import workfiles  # noqa: E402


def folders_under(path, recursive):
    """The folders to look in: `path`, and with recursive every folder under it except working folders."""
    if not recursive:
        return [path]
    out = []
    for root, dirs, files in os.walk(path):
        stems = {Path(f).stem for f in files if Path(f).suffix.lower() in workfiles.VIDEO_EXTS}
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != workfiles.FOLDER
                         and not (d.endswith(" analysis") and d[:-len(" analysis")] in stems))    # frames: skip
        out.append(Path(root))
    return out


def plan_for(path, recursive=False):
    """({video: [(file, where it goes)]}, [(file, why it stays)]) for a folder, or for one video."""
    if path.is_file():
        plan, skipped = workfiles.old_files(path.parent)
        return {v: m for v, m in plan.items() if v == path}, [s for s in skipped if path.name in s[1]]
    plan, skipped = {}, []
    for d in folders_under(path, recursive):
        p, s = workfiles.old_files(d)
        plan.update(p)
        skipped += s
    return plan, skipped


def describe(path, plan, skipped):
    """What would move, as lines to print."""
    lines = []
    for video, moves in plan.items():
        where = video.parent / workfiles.FOLDER / video.name
        shown = os.path.relpath(where, path if path.is_dir() else path.parent)
        lines.append(f"{video.name}: {len(moves)} item(s) -> {shown}{os.sep}")
        for src, dest in moves:
            arrow = f"  ->  {dest.name}{os.sep}" if src.is_dir() else ""
            lines.append(f"    {src.name}{os.sep if src.is_dir() else ''}{arrow}")
    for src, why in skipped:
        lines.append(f"  (staying where it is: {src}, because {why})")
    return lines


def move(plan):
    """Move everything in the plan. Returns (moved, [(file, why it wasn't)])."""
    moved, problems = 0, []
    for moves in plan.values():
        for src, dest in moves:
            if dest.exists():
                problems.append((src, f"{dest} is already there"))
                continue
            try:
                workfiles.make_dirs(dest.parent)
                os.rename(src, dest)            # the same drive, so a rename: instant, even for a folder of frames
            except OSError as e:
                problems.append((src, e.strerror or str(e)))
                continue
            moved += 1
    return moved, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="a folder of videos, or one video")
    ap.add_argument("--recursive", action="store_true", help="with a folder: include every folder under it")
    ap.add_argument("--dry-run", action="store_true", help="only list what would move")
    ap.add_argument("--yes", action="store_true", help="move them without asking")
    a = ap.parse_args(argv)
    path = Path(os.path.abspath(Path(a.path).expanduser()))
    if not path.exists():
        sys.exit(f"Can't find {path}")
    plan, skipped = plan_for(path, a.recursive)
    if not plan:
        print("Nothing to tidy: no working files beside the videos"
              + ("" if a.recursive or path.is_file() else " here (subfolders: add --recursive)") + ".")
        for line in describe(path, plan, skipped):
            print(line)
        return 0
    for line in describe(path, plan, skipped):
        print(line)
    for video, moves in plan.items():             # the same list, for a GUI (docs/gui-protocol.md)
        prompts.event("tidy", video=str(video), folder=str(workfiles.folder(video)),
                      items=[{"from": src.name, "to": dest.name, "folder": src.is_dir()} for src, dest in moves])
    for src, why in skipped:
        prompts.event("tidy-skip", path=str(src), reason=why)
    items = sum(len(m) for m in plan.values())
    if a.dry_run:
        print(f"\n{items} item(s) for {len(plan)} video(s) would move. Nothing was moved (--dry-run).")
        return 0
    if not a.yes and not prompts.interactive():
        sys.exit("Not an interactive terminal, so add --yes to move them (or --dry-run to only list them).")
    if prompts.ask(f"\nMove these {items} item(s) for {len(plan)} video(s) into their {workfiles.FOLDER} folders?",
                   {"y": "yes, move them", "n": "no"}, "y", a.yes, id="tidy.move") != "y":
        print("Nothing was moved.")
        return 0
    moved, problems = move(plan)
    print(f"Moved {moved} item(s).")
    prompts.event("tidy-done", moved=moved, problems=[{"path": str(src), "reason": why} for src, why in problems])
    for src, why in problems:
        print(f"  ! Left {src} where it is: {why}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
