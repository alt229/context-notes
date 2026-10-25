"""A reply that can't be read: its lines are recorded in the notes file, and the next run sends only those again."""
import json
import re

import pytest
from conftest import make_srt, message, needs_ffmpeg, place, run_cli
from test_generate_notes import notes_for_each_part
from test_pick_up import REFINE, asked, estimate, props, stretch_start
from test_progress_and_cancel import LONG
from test_prompts import drive
from test_refine_notes import refine_responder

import generate_notes as gn
import make_ass


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    from test_refine_notes import make_video
    path = tmp_path_factory.mktemp("clip") / "synced.mp4"
    make_video(path)
    return path


@pytest.fixture
def project(tmp_path, clip):
    """The same film and notes test_pick_up.py refines (two parts)."""
    place(clip, tmp_path / "synced.mp4")
    make_srt(tmp_path / "synced.srt", n=24)
    notes = [{"at": "00:00:03,000", "category": "About these notes", "text": "Intro", "kind": "speech"}]
    notes += [{"match": f"Line {i} of", "category": "Idiom", "text": f"Note {i}", "confidence": "high", "kind": "speech"}
              for i in (2, 5, 8, 12)]
    (tmp_path / "notes-synced.json").write_text(json.dumps({"title": "Test Show (context notes)", "notes": notes}))
    return tmp_path


def lines_sent(call):
    m = re.search(r"Lines to annotate \((\d+) to (\d+)\)", call["body"]["messages"][0]["content"])
    return int(m.group(1)), int(m.group(2))


def garbled(which):
    """notes_for_each_part, except the `which`-th request to write notes gets a reply that isn't JSON."""
    count = []

    def responder(n, body, headers):
        if "You refine" in body["system"]:
            return refine_responder(n, body, headers)
        count.append(n)
        if len(count) == which:
            return 200, message("I'm sorry, I can't produce that list right now.")
        return notes_for_each_part(n, body, headers)
    return responder


def test_an_unreadable_reply_is_recorded_and_only_its_lines_are_sent_again(tmp_path, api, api_key_file, home):
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    api.responder = garbled(2)
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(api.calls) >= 3
    lo, hi = lines_sent(api.calls[1])
    spec = json.loads((tmp_path / "notes-ep.json").read_text())
    assert spec["unreadable"] == [{"lines": [lo, hi], "reply": "notes-ep.part2.failed.txt"}]
    assert "can't produce" in (tmp_path / "notes-ep.part2.failed.txt").read_text()
    assert "The next run offers to send just those again" in r.stdout
    cues = make_ass.parse_srt(srt)
    placed = gn.note_lines(cues, spec["notes"][1:])
    earlier = [n for n, line in zip(spec["notes"][1:], placed) if line is not None and line < lo]

    sent = len(api.calls)
    api.responder = notes_for_each_part
    r = run_cli("make_ass.py", srt, "--generate", "--extend", "--yes", "--api-url", api.url, cwd=tmp_path,
                home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(api.calls) == sent + 1 and lines_sent(api.calls[-1]) == (lo, hi)       # only those lines
    assert f"Sending again only the lines whose replies couldn't be read last time: {lo} to {hi}." in r.stdout
    asked = api.calls[-1]["body"]["messages"][0]["content"]
    assert f"[context] {lo - 1} [" in asked                                            # the lines just before
    topics = asked.split("Topics already covered by earlier notes (don't repeat):\n")[1].split("\n\n")[0]
    assert len(topics.splitlines()) == len(earlier) > 0                                  # nothing from later on
    assert all(f'"{n["match"]}"' in topics for n in earlier if "match" in n)
    spec = json.loads((tmp_path / "notes-ep.json").read_text())
    assert "unreadable" not in spec and (tmp_path / "notes-ep.json.bak").exists()
    lines = [x for x in gn.note_lines(cues, spec["notes"][1:]) if x is not None]
    assert lines == sorted(lines) and any(lo <= x <= hi for x in lines)                # in film order
    assert f"Note {sent + 1}" in (tmp_path / "ep.ass").read_text(encoding="utf-8-sig")


def test_unreadable_again_stays_recorded_and_is_never_overwritten(tmp_path, api, api_key_file, home):
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    api.responder = garbled(2)
    run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    api.responder = garbled(1)
    r = run_cli("make_ass.py", srt, "--generate", "--extend", "--yes", "--api-url", api.url, cwd=tmp_path,
                home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    spec = json.loads((tmp_path / "notes-ep.json").read_text())
    assert [u["reply"] for u in spec["unreadable"]] == ["notes-ep.part2.failed2.txt"]
    assert (tmp_path / "notes-ep.part2.failed.txt").exists()


def test_extend_with_nothing_missing_sends_nothing(tmp_path, api, api_key_file, home):
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    api.responder = notes_for_each_part
    run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    sent = len(api.calls)
    r = run_cli("make_ass.py", srt, "--generate", "--extend", "--yes", "--api-url", api.url, cwd=tmp_path,
                home_dir=home)
    assert r.returncode == 0 and "nothing to add, nothing sent" in r.stdout and len(api.calls) == sent


@needs_ffmpeg
def test_the_wrapper_asks_and_sends_only_those_lines(tmp_path, clip, api, api_key_file, home):
    place(clip, tmp_path / "ep.mp4")
    make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    api.responder = garbled(2)
    r = run_cli("context_notes.py", "ep.mp4", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    r = run_cli("context_notes.py", "ep.mp4", "--status", cwd=tmp_path, home_dir=home)
    assert "[to do] ep.mp4" in r.stdout and "1 part(s) came back unreadable" in r.stdout
    sent = len(api.calls)
    r = run_cli("context_notes.py", "ep.mp4", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Send just those lines again? -> yes, send just those lines (automatic)" in r.stdout
    new = api.calls[sent:]
    assert len(new) == 1 and "You refine" not in new[0]["body"]["system"]              # no frames step again
    assert "--extend" in r.stdout and "Checking the subtitles against the soundtrack" not in r.stdout
    r = run_cli("context_notes.py", "ep.mp4", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert "Already done" in r.stdout and len(api.calls) == sent + 1


# ---------------------------------------------------------------- the frames step
def unreadable_first_stretch(project, api, home):
    """A refine whose first reply isn't JSON. Returns the stretch recorded for it."""
    api.responder = lambda n, body, h: (200, message("Looking at these frames, I'd say...")) if n == 1 else \
        refine_responder(n, body, h)
    r = run_cli("make_ass.py", *REFINE, "--yes", "--api-url", api.url, cwd=project, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    first = stretch_start(api.calls[0])
    refined = json.loads((project / "notes-synced.json").read_text())["refined"]
    assert [(u["reply"], abs(u["from"] - first) < 0.01) for u in refined["unreadable"]] == [
        ("notes-synced.refine1.failed.txt", True)]
    assert "stopped_after" not in refined and props(project) == 1                  # only the second part's prop
    api.responder = refine_responder
    api.calls.clear()
    return refined


@needs_ffmpeg
def test_refine_sends_an_unreadable_stretch_again_on_its_own(project, api, api_key_file, home):
    before = unreadable_first_stretch(project, api, home)
    r = run_cli("context_notes.py", "synced.mp4", "--status", cwd=project, home_dir=home)
    assert "[to do] synced.mp4" in r.stdout and "1 stretch(es) of frames came back unreadable" in r.stdout
    code, out, evs = drive([*REFINE, "--api-url", api.url], {"refine.send": "y"}, project, home, script="make_ass.py")
    assert code == 0, out
    assert asked(evs) == ["refine.unreadable", "refine.send"]
    assert estimate(evs)["requests"] == 1 and len(api.calls) == 1
    assert abs(stretch_start(api.calls[0]) - before["unreadable"][0]["from"]) < 0.01      # just that stretch
    refined = json.loads((project / "notes-synced.json").read_text())["refined"]
    assert refined == {k: v for k, v in before.items() if k != "unreadable"}               # the record stands
    assert props(project) == 2
    r = run_cli("context_notes.py", "synced.mp4", "--status", cwd=project, home_dir=home)
    assert "[ done] synced.mp4" in r.stdout, r.stdout


@needs_ffmpeg
def test_refine_unreadable_declined_sends_nothing(project, api, api_key_file, home):
    before = unreadable_first_stretch(project, api, home)
    code, out, evs = drive([*REFINE, "--api-url", api.url], {"refine.unreadable": "n"}, project, home,
                           script="make_ass.py")
    assert code == 0 and not api.calls and "Nothing was sent" in out, out
    assert json.loads((project / "notes-synced.json").read_text())["refined"] == before
