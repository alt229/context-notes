"""The frame pass on the subscription: chat_notes.py show-frames prints one stretch for the frame-reviewer agent, and
collect-frames applies the agents' frames-<k>.txt replies the way make_ass.py --refine applies the API's."""
import json
import re

import pytest
from conftest import make_srt, needs_ffmpeg, run_cli

import timecode

pytest.importorskip("numpy")
pytest.importorskip("PIL")
from test_refine_notes import make_video  # noqa: E402

LABEL = "Opus in Claude Code"


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "synced.mp4"
    make_video(path)
    return path


@pytest.fixture
def project(tmp_path, clip):
    (tmp_path / "synced.mp4").symlink_to(clip)
    make_srt(tmp_path / "synced.srt", n=24)
    notes = [{"at": "00:00:03,000", "category": "About these notes", "text": "Intro", "kind": "speech"}]
    notes += [{"match": f"Line {i} of", "category": "Idiom", "text": f"Note {i}", "confidence": "high", "kind": "speech"}
              for i in (2, 5, 8, 12)]
    (tmp_path / "notes-synced.json").write_text(json.dumps({"title": "Test Show (context notes)", "notes": notes}))
    (tmp_path / "replies").mkdir()
    return tmp_path


def show(project, part, *extra):
    r = run_cli("chat_notes.py", "show-frames", "synced.mp4", "synced.srt", "--part", part, "--replies", "replies", *extra,
                cwd=project)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def collect(project, *extra):
    return run_cli("chat_notes.py", "collect-frames", "synced.mp4", "synced.srt", "replies", "--model-label", LABEL, *extra,
                   cwd=project)


def parts(project):
    return int(re.search(r"^Parts: (\d+)$", show(project, 0), re.M).group(1))


def stretch(text):
    """(lo, hi) of the part shown, in seconds."""
    m = re.search(r"PART \d+ OF \d+ \(frames (\S+) to (\S+)\)", text)
    return timecode.parse_time(m.group(1)), timecode.parse_time(m.group(2))


def listed_ids(text):
    return [int(i) for i in re.findall(r"^#(\d+) \[", text, re.M)]


def prop(k, lo):
    return {"at": timecode.hms(lo + 5), "kind": "visual", "category": "Prop", "text": f"Prop from part {k}", "confidence": "high"}


def write_reply(project, k, reply):
    (project / "replies" / f"frames-{k}.txt").write_text(json.dumps(reply, indent=1), encoding="utf-8")


def write_all_replies(project, n, skip=()):
    for k in range(1, n + 1):
        if k not in skip:
            write_reply(project, k, {"add": [prop(k, stretch(show(project, k))[0])]})


def spec(project):
    return json.loads((project / "notes-synced.json").read_text())


def props(project):
    return sorted(n["text"] for n in spec(project)["notes"] if n["text"].startswith("Prop from part"))


# ---------------------------------------------------------------- show-frames
@needs_ffmpeg
def test_show_frames_prints_one_part_for_the_agent(project):
    out = show(project, 1)
    assert out.startswith("Title: Test Show\nYou are reviewing PART 1 OF ")
    assert "=== INSTRUCTIONS (follow these exactly) ===" in out and "Frames are SAMPLED" in out
    sheets = out.split("=== CONTACT SHEETS: open each of these image files with the Read tool before writing anything ===\n")[1]
    paths = [line.split("   frames from ")[0] for line in sheets.split("\n\n")[0].splitlines()]
    assert 1 <= len(paths) <= 4 and all(p.startswith("/") and p.endswith(".jpg") for p in paths)
    assert all((project / p).exists() for p in paths), paths
    assert "=== THE DIALOGUE, EXISTING NOTES AND LOUD MOMENTS FOR THIS PART ===" in out
    assert "Dialogue in this stretch:" in out and "Line 2 of the original test script" in out
    assert "Existing notes in this stretch:" in out and 1 in listed_ids(out)      # the intro note, as #1
    assert f"Write the file {project / 'replies'}/frames-1.txt" in out
    assert "Plan:" not in out and "Analysing" not in out and "estimate" not in out       # none of plan_refine's chatter
    assert not list(project.glob("*.bak")) and "refined" not in spec(project)             # nothing was changed


@needs_ffmpeg
def test_part_zero_prints_the_count_and_the_mode(project):
    out = show(project, 0)
    n = int(re.search(r"^Parts: (\d+)$", out, re.M).group(1))
    assert n >= 2 and "Mode: full (subtitles are in sync with the video)." in out and f"To do: parts 1 to {n}" in out
    r = run_cli("chat_notes.py", "show-frames", "synced.mp4", "synced.srt", "--part", n + 1, cwd=project)
    assert r.returncode == 1 and f"parts 1 to {n}" in r.stderr


@needs_ffmpeg
def test_a_later_part_sees_what_earlier_parts_changed(project):
    lo, hi = stretch(show(project, 1))
    # a visual note just at the edge of part 1 (the stretch allows a second's slack) lands in part 2's listing
    write_reply(project, 1, {"add": [{"at": timecode.hms(hi + 1), "kind": "visual", "category": "Prop", "text": "Edge prop"}]})
    out = show(project, 2)
    assert "Edge prop" in out and "Edge prop" not in show(project, 2, "--replies", str(project / "elsewhere"))


# ---------------------------------------------------------------- collect-frames
@needs_ffmpeg
def test_collect_frames_applies_every_part(project):
    n = parts(project)
    original = (project / "notes-synced.json").read_text()
    write_all_replies(project, n)
    first = show(project, 1)
    ids = listed_ids(first)
    reply = json.loads((project / "replies" / "frames-1.txt").read_text())
    reply["revise"] = [{"id": ids[-1], "text": "REVISED", "reason": "the frames show it"}]
    reply["drop"] = [{"id": 99, "reason": "not listed, so ignored"}]
    write_reply(project, 1, reply)

    r = collect(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Mode: full" in r.stdout and r.stdout.count(" added, ") == n + 1          # one line per part, then the summary
    assert "part 1/" in r.stdout and "1 added, 1 revised, 0 retimed, 0 dropped" in r.stdout
    assert f"Refined notes-synced.json: {n} added, 1 revised, 0 retimed, 0 dropped" in r.stdout
    assert "Report of every change: " in r.stdout

    s = spec(project)
    assert props(project) == [f"Prop from part {k}" for k in range(1, n + 1)]
    assert s["notes"][ids[-1] - 1]["text"] == "REVISED" and s["notes"][ids[-1] - 1]["original_text"].startswith("Note")
    assert s["refined"]["model"] == LABEL and "stopped_after" not in s["refined"] and s["refined"]["contact_sheets"] > 0
    assert s["video_offset"] == pytest.approx(0.9, abs=0.1)
    assert (project / "notes-synced.json.bak").read_text() == original
    report = (project / "notes-synced.refine-report.txt").read_text()
    assert f"({LABEL})" in report and "REVISED" in report and "Prop from part 1" in report
    assert not list(project.glob("*.failed.txt"))


@needs_ffmpeg
def test_collect_frames_stops_at_a_missing_part_and_picks_up_later(project):
    n = parts(project)
    end_of_part_1 = stretch(show(project, 1))[1]
    write_all_replies(project, n, skip=range(2, n + 1))
    run_cli("make_ass.py", "synced.srt", "notes-synced.json", "--video", "synced.mp4", cwd=project)
    r = collect(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"Stopped after part 1 of {n}: there is no replies/frames-2.txt yet" in r.stdout
    s = spec(project)
    stopped = s["refined"]["stopped_after"]
    assert (stopped["part"], stopped["parts"], stopped["backup"]) == (1, n, "notes-synced.json.bak")
    assert stopped["time"] == pytest.approx(end_of_part_1, abs=0.01)
    assert props(project) == ["Prop from part 1"] and s["refined"]["model"] == LABEL
    assert (project / "synced.notes.ass.bak").exists()
    status = run_cli("context_notes.py", "synced.mp4", "--status", cwd=project)
    assert "refine stopped part-way" in status.stdout, status.stdout
    assert f"To do: parts 2 to {n}" in show(project, 0)
    r = run_cli("chat_notes.py", "show-frames", "synced.mp4", "synced.srt", "--part", 1, cwd=project)
    assert r.returncode == 1 and "already in the notes" in r.stderr

    write_all_replies(project, n, skip=[1])
    r = collect(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "part 1/" not in r.stdout and f"part 2/{n}" in r.stdout
    s = spec(project)
    assert "stopped_after" not in s["refined"]
    assert props(project) == [f"Prop from part {k}" for k in range(1, n + 1)]            # each part applied once
    report = (project / "notes-synced.refine-report.txt").read_text()
    assert report.count("Refinement of") == 2 and f"STOPPED EARLY after part 1 of {n}" in report and "picked up at" in report
    assert (project / "notes-synced.json.bak2").exists()
    status = run_cli("context_notes.py", "synced.mp4", "--status", cwd=project)
    assert ", refined" in status.stdout


@needs_ffmpeg
def test_an_unreadable_reply_is_kept_and_the_run_goes_on(project):
    n = parts(project)
    write_all_replies(project, n)
    (project / "replies" / "frames-1.txt").write_text("Sorry, I could not open the images.", encoding="utf-8")
    r = collect(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "part 1: couldn't read frames-1.txt" in r.stdout and "saved it to notes-synced.frames1.failed.txt" in r.stdout
    assert (project / "notes-synced.frames1.failed.txt").read_text() == "Sorry, I could not open the images."
    assert props(project) == [f"Prop from part {k}" for k in range(2, n + 1)]
    assert "! part 1: couldn't read" in (project / "notes-synced.refine-report.txt").read_text()


@needs_ffmpeg
def test_collect_frames_with_no_replies_changes_nothing(project):
    before = (project / "notes-synced.json").read_text()
    r = collect(project)
    assert r.returncode == 1 and "No frames-<k>.txt files" in r.stderr
    assert (project / "notes-synced.json").read_text() == before and not list(project.glob("*.bak"))
