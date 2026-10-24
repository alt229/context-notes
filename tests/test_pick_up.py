"""Picking up where a stopped run left off: note-writing (from <notes>.partial.json) and refine (from the notes file)."""
import json
import re
import signal
import threading

import pytest
from conftest import make_srt, needs_ffmpeg, run_cli
from test_progress_and_cancel import LONG, cancel_when, held_after_first
from test_prompts import drive

import refine_notes as rn

FAIL = (400, {"error": {"message": "credit balance is too low"}})          # the API stopping a run part-way


def first_line_sent(call):
    return int(re.search(r"Lines to annotate \((\d+) to", call["body"]["messages"][0]["content"]).group(1))


def asked(evs):
    return [e["id"] for e in evs if e["type"] == "question"]


def estimate(evs):
    return next(e for e in evs if e["type"] == "estimate")


# ---------------------------------------------------------------- writing the notes
def stopped_note_writing(tmp_path, api, home):
    """A note-writing run that the API stops after its first part. Returns the subtitle file and what was kept."""
    from test_generate_notes import notes_for_each_part
    api.responder = lambda n, body, h: notes_for_each_part(n, body, h) if n < 2 else FAIL
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "the next run offers to pick up from there" in r.stdout, r.stdout + r.stderr
    kept = json.loads((tmp_path / "notes-ep.partial.json").read_text())
    assert kept["subtitles"] == "ep.srt" and kept["through_line"] > 1 and kept["notes"]
    api.responder = notes_for_each_part
    api.calls.clear()
    return srt, kept


def test_note_writing_picks_up_where_it_stopped(tmp_path, api, api_key_file, home):
    srt, kept = stopped_note_writing(tmp_path, api, home)
    code, out, evs = drive([srt, "--generate", "--api-url", api.url], {"generate.send": "y"}, tmp_path, home,
                           script="make_ass.py")
    assert code == 0, out
    assert asked(evs) == ["generate.resume", "generate.send"]
    assert estimate(evs)["lines"] == 24 - kept["through_line"] and len(api.calls) == estimate(evs)["requests"]
    assert first_line_sent(api.calls[0]) == kept["through_line"] + 1             # nothing is sent twice
    notes = json.loads((tmp_path / "notes-ep.json").read_text())["notes"]
    assert all(n in notes for n in kept["notes"])                                 # the first part's notes are in
    assert not (tmp_path / "notes-ep.partial.json").exists()                      # and the partial file is gone


def test_note_writing_can_start_again(tmp_path, api, api_key_file, home):
    srt, _ = stopped_note_writing(tmp_path, api, home)
    code, out, evs = drive([srt, "--generate", "--api-url", api.url], {"generate.resume": "s", "generate.send": "y"},
                           tmp_path, home, script="make_ass.py")
    assert code == 0, out
    assert estimate(evs)["lines"] == 24 and first_line_sent(api.calls[0]) == 1
    assert not (tmp_path / "notes-ep.partial.json").exists()


def test_yes_picks_up_without_asking(tmp_path, api, api_key_file, home):
    srt, kept = stopped_note_writing(tmp_path, api, home)
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Pick up where it left off? -> pick up where it left off (sends only the rest) (automatic)" in r.stdout
    assert first_line_sent(api.calls[0]) == kept["through_line"] + 1


def test_a_partial_file_from_other_subtitles_is_not_used(tmp_path, api, api_key_file, home):
    srt, kept = stopped_note_writing(tmp_path, api, home)
    kept["subtitles"] = "another release.srt"
    (tmp_path / "notes-ep.partial.json").write_text(json.dumps(kept))
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Not picking up from notes-ep.partial.json: it was written from other subtitles" in r.stdout
    assert first_line_sent(api.calls[0]) == 1


def test_an_estimate_counts_only_what_is_left(tmp_path, api, api_key_file, home):
    srt, kept = stopped_note_writing(tmp_path, api, home)
    r = run_cli("make_ass.py", srt, "--generate", "--estimate-only", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0 and f"Plan: {24 - kept['through_line']} lines" in r.stdout, r.stdout + r.stderr
    assert (tmp_path / "notes-ep.partial.json").exists()                          # an estimate changes nothing


# ---------------------------------------------------------------- refining with the video
np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from test_refine_notes import make_video, refine_responder  # noqa: E402


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
    return tmp_path


REFINE = ["synced.srt", "notes-synced.json", "--refine", "--video", "synced.mp4"]


def props(project):
    """Each refine part adds one 'Prop at <time>' note, so this counts the parts the final notes went through."""
    return sum(n["text"].startswith("Prop at") for n in json.loads((project / "notes-synced.json").read_text())["notes"])


def stopped_refine(project, api, home):
    """A refine that the API stops after the first of its two parts."""
    api.responder = lambda n, body, h: refine_responder(n, body, h) if n < 2 else FAIL
    r = run_cli("make_ass.py", *REFINE, "--yes", "--api-url", api.url, cwd=project, home_dir=home)
    assert r.returncode == 1 and "The next refine offers to pick up from here." in r.stdout, r.stdout + r.stderr
    stopped = json.loads((project / "notes-synced.json").read_text())["refined"]["stopped_after"]
    assert (stopped["part"], stopped["parts"], stopped["backup"]) == (1, 2, "notes-synced.json.bak")
    assert props(project) == 1
    api.responder = refine_responder
    api.calls.clear()
    return stopped


def stretch_start(call):
    text = [b for b in call["body"]["messages"][0]["content"] if b["type"] == "text"][-1]["text"]
    return rn.parse_time(re.search(r"This stretch: (\S+) to", text).group(1))


@needs_ffmpeg
def test_refine_picks_up_where_it_stopped(project, api, api_key_file, home):
    stopped = stopped_refine(project, api, home)
    code, out, evs = drive([*REFINE, "--api-url", api.url], {"refine.send": "y"}, project, home, script="make_ass.py")
    assert code == 0, out
    assert asked(evs) == ["refine.resume", "refine.send"]
    assert estimate(evs)["requests"] == 1 and len(api.calls) == 1
    assert stretch_start(api.calls[0]) >= stopped["time"] - 0.01                    # only the second part was sent
    assert props(project) == 2                                                       # each part once
    spec = json.loads((project / "notes-synced.json").read_text())
    assert "stopped_after" not in spec["refined"]
    report = (project / "notes-synced.refine-report.txt").read_text()
    assert report.count("Refinement of") == 2 and "STOPPED EARLY after part 1 of 2" in report and "picked up at" in report


@needs_ffmpeg
def test_refine_can_start_again_from_the_notes_before_it(project, api, api_key_file, home):
    stopped_refine(project, api, home)
    code, out, evs = drive([*REFINE, "--api-url", api.url], {"refine.resume": "s", "refine.send": "y"}, project, home,
                           script="make_ass.py")
    assert code == 0 and "Starting again from notes-synced.json.bak." in out, out
    assert len(api.calls) == 2 and props(project) == 2           # from the notes as they were, not on top of part 1


@needs_ffmpeg
def test_the_wrapper_finishes_a_stopped_refine(project, api, api_key_file, home):
    stopped_refine(project, api, home)
    r = run_cli("context_notes.py", "synced.mp4", "--status", cwd=project, home_dir=home)
    assert "[to do] synced.mp4" in r.stdout and "refine stopped part-way" in r.stdout, r.stdout
    r = run_cli("context_notes.py", "synced.mp4", "--yes", "--api-url", api.url, cwd=project, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Pick up where it left off? -> pick up where it left off (automatic)" in r.stdout and len(api.calls) == 1
    r = run_cli("context_notes.py", "synced.mp4", "--status", cwd=project, home_dir=home)
    assert "[ done] synced.mp4" in r.stdout and ", refined" in r.stdout, r.stdout


@needs_ffmpeg
def test_cancel_during_refine_keeps_the_changes_so_far(project, api, api_key_file, home):
    gate = threading.Event()
    api.responder = held_after_first(refine_responder, gate)
    cancel = cancel_when(lambda ev: ev["type"] == "progress" and ev["task"] == "refine" and ev["done"] == 1)
    try:
        code, out, _ = drive([*REFINE, "--yes", "--api-url", api.url], {}, project, home, script="make_ass.py",
                             on_event=cancel)
    finally:
        gate.set()
    assert cancel.sent and code == -signal.SIGINT, out
    assert json.loads((project / "notes-synced.json").read_text())["refined"]["stopped_after"]["part"] == 1
    assert props(project) == 1
