"""The frames step in a Claude Code conversation (/refine): chat_notes.py show-frames and collect-frames, which show
the frame-reviewer agent each stretch as the API's frames step would send it, and apply its replies the same way."""
import json
import re
from pathlib import Path

import pytest
from conftest import make_srt, needs_ffmpeg, place, run_cli
from test_refine_notes import make_video, refine_responder

pytest.importorskip("numpy")
pytest.importorskip("PIL")

NOTES = [{"at": "00:00:03,000", "category": "About these notes", "text": "Intro", "kind": "speech"}]
NOTES += [{"match": f"Line {i} of", "category": "Idiom", "text": f"Original note {i}", "confidence": "high",
           "kind": "speech"} for i in (2, 5, 8, 12)]
NOTES.append({"at_video": "00:00:10,000", "category": "Visual gag", "text": "A red balloon floats by", "kind": "visual"})


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("clip")
    make_video(d / "synced.mp4")
    return d / "synced.mp4"


def film(folder, clip):
    folder.mkdir(parents=True, exist_ok=True)
    place(clip, folder / "ep.mp4")
    make_srt(folder / "ep.srt", n=24)
    (folder / "notes-ep.json").write_text(json.dumps({"title": "Test Show (context notes)", "notes": NOTES}))
    return folder


def chat(folder, home, *args):
    return run_cli("chat_notes.py", *args, cwd=folder, home_dir=home)


def answer(shown):
    """What the agent would write: the fake API's reply to the same stretch."""
    stretch = shown.split("=== THIS STRETCH ===\n", 1)[1]
    body = {"messages": [{"content": [{"type": "text", "text": stretch}]}]}
    return refine_responder(1, body, {})[1]["content"][0]["text"]


def replies(folder):
    """Where the replies go: the video's working folder (beside it here, as notes-ep.json is) + frame-replies."""
    import workfiles
    return workfiles.place(folder / "ep.mp4") / "frame-replies"


def parts_of(out):
    return int(re.search(r"^Parts: (\d+)$", out, re.M).group(1))


@needs_ffmpeg
def test_the_chat_route_gives_the_same_notes_as_the_api(tmp_path, clip, api, api_key_file, home):
    """The same replies give the same notes either way: the stretches shown are the API's, earlier parts' changes
    included."""
    a = film(tmp_path / "api", clip)
    api.responder = refine_responder
    r = run_cli("make_ass.py", "ep.srt", "notes-ep.json", "--refine", "--video", "ep.mp4", "--yes", "--api-url",
                api.url, cwd=a, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    by_api = json.loads((a / "notes-ep.json").read_text())

    c = film(tmp_path / "chat", clip)
    r = chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", "0")
    assert r.returncode == 0, r.stdout + r.stderr
    n = parts_of(r.stdout)
    assert n == len(api.calls) and "Next: part 1" in r.stdout and "Mode: full" in r.stdout
    start = json.loads((replies(c) / "start.json").read_text())
    assert (c / start["backup"]).read_text() == (c / "notes-ep.json").read_text()       # kept as it was
    for k in range(1, n + 1):
        r = chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", str(k))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "You refine" in r.stdout and f"PART {k} OF {n}" in r.stdout
        api_text = [b["text"] for b in api.calls[k - 1]["body"]["messages"][0]["content"] if b["type"] == "text"][-1]
        assert r.stdout.rstrip("\n").endswith(api_text)                  # exactly what the API was sent for it
        sheets = re.findall(r"^(.+?\.jpg)   frames from", r.stdout, re.M)
        assert sheets and all(Path(p).is_file() for p in sheets)
        (replies(c) / f"frames-{k}.txt").write_text(answer(r.stdout))
    r = chat(c, home, "collect-frames", "ep.mp4", "ep.srt")
    assert r.returncode == 0, r.stdout + r.stderr
    by_chat = json.loads((c / "notes-ep.json").read_text())
    assert by_chat["notes"] == by_api["notes"] and by_chat["video_offset"] == by_api["video_offset"]
    assert "stopped_after" not in by_chat["refined"] and by_chat["refined"]["model"] == "Opus in Claude Code (/refine)"
    assert (c / "notes-ep.refine-report.txt").exists()


@needs_ffmpeg
def test_part_way_it_records_where_it_stopped_and_picks_up(tmp_path, clip, home):
    c = film(tmp_path / "f", clip)
    n = parts_of(chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", "0").stdout)
    assert n > 1
    r = chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", "2")
    assert r.returncode == 1 and "needs the replies for part(s) 1 first" in r.stderr
    shown = chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", "1").stdout
    (replies(c) / "frames-1.txt").write_text(answer(shown))
    r = chat(c, home, "collect-frames", "ep.mp4", "ep.srt")
    assert r.returncode == 0 and f"for 1 of {n} part(s)" in r.stdout
    spec = json.loads((c / "notes-ep.json").read_text())
    assert spec["refined"]["stopped_after"]["part"] == 1 and "REVISED" in [x["text"] for x in spec["notes"]]
    r = run_cli("context_notes.py", "ep.mp4", "--status", cwd=c, home_dir=home)
    assert "stopped" in r.stdout.lower()
    r = chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", "0")           # picks up where it was
    assert "Picking up" in r.stdout and "Done: 1" in r.stdout and "Next: part 2" in r.stdout
    for k in range(2, n + 1):
        shown = chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", str(k)).stdout
        (replies(c) / f"frames-{k}.txt").write_text(answer(shown))
    r = chat(c, home, "collect-frames", "ep.mp4", "ep.srt")
    spec = json.loads((c / "notes-ep.json").read_text())
    assert r.returncode == 0 and "stopped_after" not in spec["refined"]
    # applied to the notes as they were when /refine began, once: part 1's change isn't made a second time
    assert sum(1 for x in spec["notes"] if x.get("original_text") == "Intro") == 1


@needs_ffmpeg
def test_an_unreadable_reply_is_recorded_and_the_rest_applied(tmp_path, clip, home):
    c = film(tmp_path / "f", clip)
    n = parts_of(chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", "0").stdout)
    (replies(c) / "frames-1.txt").write_text("I looked carefully but I'm not sure what to say.")
    for k in range(2, n + 1):
        shown = chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", str(k)).stdout
        (replies(c) / f"frames-{k}.txt").write_text(answer(shown))
    r = chat(c, home, "collect-frames", "ep.mp4", "ep.srt")
    assert r.returncode == 0 and "couldn't read frame-replies/frames-1.txt" in r.stdout
    spec = json.loads((c / "notes-ep.json").read_text())
    assert spec["refined"]["unreadable"][0]["reply"] == "frame-replies/frames-1.txt"


@needs_ffmpeg
def test_fresh_starts_again_and_keeps_the_old_replies(tmp_path, clip, home):
    c = film(tmp_path / "f", clip)
    chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", "0")
    (replies(c) / "frames-1.txt").write_text("{}")
    r = chat(c, home, "show-frames", "ep.mp4", "ep.srt", "--part", "0", "--fresh")
    assert r.returncode == 0 and "frame-replies.old-1" in r.stdout and "Done: none" in r.stdout
    assert (replies(c).parent / "frame-replies.old-1" / "frames-1.txt").exists()


def test_it_needs_a_start_and_notes(tmp_path, home):
    (tmp_path / "ep.mp4").write_bytes(b"")
    make_srt(tmp_path / "ep.srt", n=3)
    r = chat(tmp_path, home, "show-frames", "ep.mp4", "ep.srt", "--part", "1")
    assert r.returncode == 1 and "Begin with" in r.stderr
    r = chat(tmp_path, home, "collect-frames", "ep.mp4", "ep.srt")
    assert r.returncode == 1 and "Nothing to collect" in r.stderr
    r = chat(tmp_path, home, "show-frames", "ep.mp4", "ep.srt", "--part", "0")
    assert r.returncode == 1 and "no notes for ep.mp4 yet" in r.stderr
