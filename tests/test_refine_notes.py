import json
import re
import subprocess

import pytest
from conftest import make_srt, message, needs_ffmpeg, run_cli

import refine_notes as rn
import timecode


# ---------------------------------------------------------------- times
@pytest.mark.parametrize("value, lo, hi, expected, how", [
    ("0:09:48", 540, 600, 588.0, None),                       # h:mm:ss is what we ask for
    ("0:09:48.2", 540, 600, 588.2, None),
    ("0:20:00", 540, 600, None, None),                        # outside the stretch
    (12.0, 0, 96, 12.0, None),                                # plain seconds
    (9.8, 540, 600, 588.0, "minutes"),                        # decimal minutes (a real failure seen with the API)
    (3, 540, 600, 543.0, "seconds into this stretch"),
    (99999, 0, 96, None, None),
    ("soon", 0, 96, None, None),
])
def test_resolve_time(value, lo, hi, expected, how):
    t, note = rn.resolve_time(value, lo, hi)
    assert t == pytest.approx(expected) if expected is not None else t is None
    assert (how in note) if how else note is None


def test_parse_time_and_formatters():
    assert timecode.parse_time("1:02:03.5") == 3723.5 and timecode.parse_time("2:30") == 150 and timecode.parse_time("x") is None
    assert timecode.hms(3725) == "1:02:05" and timecode.srt_ts(3725.5) == "01:02:05,500"


# ---------------------------------------------------------------- guarding against the wrong video
def test_episode_codes_and_mismatch_guard():
    codes = rn.episode_codes("1e01-Yesterday's Jam.srt", "S01E01 Yesterdays Jam.mp4",
                             "Romeo.And.Juliet.1968.720p.BluRay.x264-[YTS.AG].mp4", "show 2x07.mkv", "notes-S01E03 Fifty.json")
    assert codes == {"1e01-Yesterday's Jam.srt": (1, 1), "S01E01 Yesterdays Jam.mp4": (1, 1),
                     "show 2x07.mkv": (2, 7), "notes-S01E03 Fifty.json": (1, 3)}
    rn.check_same_episode("a S01E01.srt", "b 1x01.mp4", "film.mkv")             # fine
    with pytest.raises(SystemExit) as e:
        rn.check_same_episode("S01E03 Fifty Fifty.srt", "S01E02 Calamity Jen.mp4", "notes-S01E03.json")
    assert "different episodes" in str(e.value)


# ---------------------------------------------------------------- applying replies
CUES = [{"n": i + 1, "start": 10.0 * i, "end": 10.0 * i + 3, "text": f"Dialogue line {i + 1}"} for i in range(10)]


def fresh_notes():
    return [{"match": "line 2", "category": "Idiom", "text": "A", "confidence": "high", "kind": "speech"},
            {"match": "line 3", "category": "Idiom", "text": "B", "confidence": "high", "kind": "speech"},
            {"match": "line 4", "category": "Idiom", "text": "C", "confidence": "high", "kind": "speech"},
            {"at_video": "00:00:25,000", "category": "Prop", "text": "A red balloon floats past the window", "kind": "visual"}]


def apply(reply, visual_only=False, notes=None):
    notes = notes if notes is not None else fresh_notes()
    win = {"lo": 0.0, "hi": 100.0}
    times = rn.note_times(CUES, notes, 0.0)
    listed = {i: "x" for i in range(1, len(notes) + 1)}
    log, dropped = [], {}
    full = {"add": [], "revise": [], "retime": [], "drop": [], **reply}
    counts = rn.apply_reply(full, win, CUES, 0.0, notes, times, listed, log, dropped, visual_only)
    return notes, counts, dropped, log


def test_adds_visual_and_delivery_notes():
    notes, (added, *_), _, _ = apply({"add": [
        {"at": "0:00:42", "kind": "visual", "category": "Prop", "text": "A poster", "confidence": "high"},
        {"cue": 5, "kind": "speech", "category": "Delivery", "text": "A pause", "match": "line 5"}]})
    assert added == 2
    assert notes[-2] == {"at_video": "00:00:42,000", "category": "Prop", "text": "A poster",
                         "confidence": "high", "kind": "visual"}
    assert notes[-1]["cue"] == 5 and "match" not in notes[-1]            # anchored by number: order-independent


def test_skips_times_outside_the_stretch_and_duplicates():
    notes, (added, *_), _, log = apply({"add": [
        {"at": "0:09:00", "kind": "visual", "text": "too late"},
        {"at": "0:00:26", "kind": "visual", "text": "A red balloon floats past the window"}]})
    assert added == 0 and len(notes) == 4
    assert any("outside this stretch" in line for line in log) and any("duplicates" in line for line in log)


def test_revise_retime_and_drop_use_listed_ids_and_keep_the_original_wording():
    notes, (_, revised, retimed, dropped_n), dropped, _ = apply({
        "revise": [{"id": "#1", "text": "A2", "reason": "frames"}, {"id": 99, "text": "ignored"}],
        "retime": [{"id": 2, "delay": 40, "reason": "late"}],
        "drop": [{"id": 3, "reason": "wrong"}]})
    assert (revised, retimed, dropped_n) == (1, 1, 1)
    assert notes[0]["text"] == "A2" and notes[0]["original_text"] == "A"
    assert notes[1]["delay"] == 15.0                                     # clamped
    assert list(dropped) == [3] and len(notes) == 4                      # removal happens at save time


def test_visual_only_mode_only_adds_visual_notes():
    notes, counts, dropped, _ = apply({
        "add": [{"at": "0:00:42", "kind": "visual", "text": "A poster"}, {"cue": 5, "kind": "speech", "text": "A pause"}],
        "revise": [{"id": 1, "text": "changed"}], "retime": [{"id": 2, "delay": 3}], "drop": [{"id": 3}]},
        visual_only=True)
    assert counts == (1, 0, 0, 0) and not dropped
    assert notes[0]["text"] == "A" and "delay" not in notes[1]


def test_note_times_and_windows():
    times = rn.note_times(CUES, fresh_notes() + [{"match": "nothing like it", "text": "lost"}], 1.0)
    assert times[1] == pytest.approx(10 + 3 + 0.2 + 1.0) and times[4] == 25.0 and times[5] is None
    sheets = [(f"s{i}.jpg", i * 10.0, i * 10.0 + 9) for i in range(10)]
    wins = rn.make_windows(sheets, 100.0)
    assert len(wins) == 3 and wins[0]["lo"] == 0.0 and wins[0]["hi"] == wins[1]["lo"] == 40.0 and wins[-1]["hi"] == 101.0


def test_reply_parsing_survives_truncation():
    text = '```json\n{"add": [{"at": "0:00:01", "text": "done"}, {"at": "0:00:0'
    assert rn.parse_reply(text)["add"] == [{"at": "0:00:01", "text": "done"}]
    assert rn.parse_reply("{}") == {"add": [], "revise": [], "retime": [], "drop": []}


# ---------------------------------------------------------------- the whole thing, on a synthetic video
np = pytest.importorskip("numpy")
pytest.importorskip("PIL")


def make_video(path, burst_period=6.0, shift=0.9):
    """150 s of test pattern with a tone burst a little after each subtitle starts (and one non-dialogue burst)."""
    expr = (f"0.5*sin(2*PI*1000*t)*(gte(t,{3 + shift})*lt(mod(t-{3 + shift},{burst_period}),2)+gte(t,67)*lt(t,69.2))")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=150:size=320x240:rate=10",
                    "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=16000:d=150", "-c:v", "libx264", "-g", "10",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "150", str(path)], check=True)


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    d = tmp_path_factory.mktemp("video")
    make_video(d / "synced.mp4")
    make_video(d / "drift.mp4", burst_period=6.4)
    return d


@pytest.fixture
def project(tmp_path, videos):
    for name in ("synced.mp4", "drift.mp4"):
        (tmp_path / name).symlink_to(videos / name)
    make_srt(tmp_path / "synced.srt", n=24)
    (tmp_path / "drift.srt").write_text((tmp_path / "synced.srt").read_text())
    notes = [{"at": "00:00:03,000", "category": "About these notes", "text": "Intro", "kind": "speech"}]
    notes += [{"match": f"Line {i} of", "category": "Idiom", "text": f"Original note {i}", "confidence": "high", "kind": "speech"}
              for i in (2, 5, 8, 12)]
    notes.append({"at_video": "00:00:10,000", "category": "Visual gag", "text": "A red balloon floats by", "kind": "visual"})
    for name in ("synced", "drift"):
        (tmp_path / f"notes-{name}.json").write_text(json.dumps({"title": "Test Show (context notes)", "notes": notes}))
    return tmp_path


def refine_responder(n, body, headers):
    user = [b for b in body["messages"][0]["content"] if b["type"] == "text"][-1]["text"]
    lo = timecode.parse_time(re.search(r"This stretch: (\S+) to", user).group(1))
    ids = [int(i) for i in re.findall(r"^#(\d+) \[", user, re.M)]
    reply = {"add": [{"at": timecode.hms(lo + 5), "kind": "visual", "category": "Prop", "text": f"Prop at {timecode.hms(lo + 5)}",
                      "confidence": "high"},
                     {"at": round((lo + 20) / 60, 2), "kind": "visual", "category": "Prop", "text": "Prop in decimal minutes"}],
             "revise": [{"id": ids[0], "text": "REVISED", "reason": "frames"}] if ids else [],
             "drop": [{"id": ids[-1], "reason": "wrong"}] if len(ids) > 1 else []}
    return 200, message(json.dumps(reply), usage=(5000, 300))


@needs_ffmpeg
def test_plan_refine_works_out_the_plan_without_the_network(project, capsys):
    import claude_api
    original = (project / "notes-synced.json").read_text()
    plan = rn.plan_refine(project / "synced.srt", project / "notes-synced.json", project / "synced.mp4", estimate_only=True)
    assert plan.key is None and not plan.visual_only and plan.first == 1 and plan.todo == plan.wins and plan.total >= 2
    assert plan.offset == pytest.approx(0.9, abs=0.1) and plan.title == "Test Show" and plan.resume_from is None
    assert plan.n_img == sum(len(w["sheets"]) for w in plan.wins) and plan.est_in > plan.n_img * 100
    assert plan.cost == pytest.approx(claude_api.cost(plan.model, plan.est_in, plan.est_out))
    assert "sync offset set to" in plan.sync_msg and "NOT reliably" not in plan.sys_prompt
    assert plan.times[1] == pytest.approx(3.0 + plan.offset) and len(plan.times) == len(plan.notes)
    out = capsys.readouterr().out
    assert "Mode: full (subtitles are in sync with the video)." in out
    assert f"Plan: {len(plan.todo)} request(s) to claude-sonnet-5-5, {plan.n_img} contact-sheet images" in out
    assert (project / "notes-synced.json").read_text() == original and not list(project.glob("*.bak"))

    # the message for one stretch names the sheets by path; they are encoded only at the API call
    content, listed = rn.window_content(plan, 1, plan.todo[0], plan.notes, plan.times)
    images = [b for b in content if b["type"] == "image"]
    assert images and all(b["path"].endswith(".jpg") and "source" not in b for b in images)
    assert content[-1]["type"] == "text" and "Part 1 of" in content[-1]["text"] and 1 in listed
    encoded = claude_api.encode_images(content)
    assert all(b["source"]["type"] == "base64" for b in encoded if b["type"] == "image")

    plan = rn.plan_refine(project / "drift.srt", project / "notes-drift.json", project / "drift.mp4", estimate_only=True)
    assert plan.visual_only and "NOT reliably in step" in plan.sys_prompt
    assert "Mode: on-screen notes only" in capsys.readouterr().out


@needs_ffmpeg
def test_refine_end_to_end_synced(project, api, api_key_file, home):
    run_cli("make_ass.py", "synced.srt", "notes-synced.json", "--video", "synced.mp4", cwd=project, home_dir=home)
    old_ass = (project / "synced.notes.ass").read_text(encoding="utf-8-sig")
    original = (project / "notes-synced.json").read_text()
    api.responder = refine_responder
    r = run_cli("make_ass.py", "synced.srt", "notes-synced.json", "--refine", "--video", "synced.mp4", "--yes",
                "--api-url", api.url, cwd=project, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Mode: full" in r.stdout

    spec = json.loads((project / "notes-synced.json").read_text())
    assert spec["video_offset"] == pytest.approx(0.9, abs=0.1)                       # sync offset written
    assert spec["refined"]["contact_sheets"] > 0
    texts = [n["text"] for n in spec["notes"]]
    assert "REVISED" in texts and "Prop in decimal minutes" in texts
    assert any(n.get("original_text") == "Intro" for n in spec["notes"])        # the first listed note was revised

    assert (project / "notes-synced.json.bak").read_text() == original                # backups
    assert (project / "synced.notes.ass.bak").read_text(encoding="utf-8-sig") == old_ass
    assert (project / "notes-synced.refine-report.txt").exists()

    ass = (project / "synced.notes.ass").read_text(encoding="utf-8-sig")
    assert re.search(r"Dialogue: 0,0:00:03\.[89]\d,", ass)                                # offset applied on rebuild
    assert "Prop at" in ass

    content = api.calls[0]["body"]["messages"][0]["content"]
    images = [b for b in content if b["type"] == "image"]
    assert images and all(b["source"]["media_type"] == "image/jpeg" for b in images)
    assert '"at": "<h:mm:ss>"' in api.calls[0]["body"]["system"]


@needs_ffmpeg
def test_refine_only_adds_visual_notes_when_sync_cannot_be_confirmed(project, api, api_key_file, home):
    original = json.loads((project / "notes-drift.json").read_text())["notes"]
    api.responder = refine_responder
    r = run_cli("make_ass.py", "drift.srt", "notes-drift.json", "--refine", "--video", "drift.mp4", "--yes",
                "--api-url", api.url, cwd=project, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "on-screen notes only" in r.stdout and "--assume-synced" in r.stdout
    notes = json.loads((project / "notes-drift.json").read_text())["notes"]
    assert notes[:len(original)] == original and len(notes) > len(original)          # existing notes untouched
    assert all(n["kind"] == "visual" for n in notes[len(original):])
    assert "NOT reliably in step" in api.calls[0]["body"]["system"]

    r = run_cli("make_ass.py", "drift.srt", "notes-drift.json", "--refine", "--video", "drift.mp4", "--yes",
                "--assume-synced", "--api-url", api.url, cwd=project, home_dir=home)
    assert "Mode: full" in r.stdout


@needs_ffmpeg
def test_refine_refuses_a_video_for_a_different_episode(project, api, api_key_file, home):
    (project / "S01E03 Fifty.srt").write_text((project / "synced.srt").read_text())
    (project / "S01E02 Calamity.mp4").symlink_to(project / "synced.mp4")
    (project / "notes-S01E03.json").write_text((project / "notes-synced.json").read_text())
    r = run_cli("make_ass.py", "S01E03 Fifty.srt", "notes-S01E03.json", "--refine", "--video", "S01E02 Calamity.mp4",
                "--yes", "--api-url", api.url, cwd=project, home_dir=home)
    assert r.returncode == 1 and "different episodes" in r.stderr and not api.calls


@needs_ffmpeg
def test_declining_the_prompt_changes_nothing(project, api, api_key_file, home):
    before = (project / "notes-synced.json").read_text()
    r = run_cli("make_ass.py", "synced.srt", "notes-synced.json", "--refine", "--video", "synced.mp4",
                "--api-url", api.url, cwd=project, home_dir=home)              # not a terminal, no --yes
    assert r.returncode == 1 and "--yes" in r.stderr and not api.calls
    assert (project / "notes-synced.json").read_text() == before
    assert not list(project.glob("*.bak"))


@needs_ffmpeg
def test_refine_keeps_what_it_has_when_the_api_fails_midway(project, api, api_key_file, home):
    api.responder = lambda n, body, h: refine_responder(n, body, h) if n == 1 else (400, {"error": {"message": "no credit"}})
    r = run_cli("make_ass.py", "synced.srt", "notes-synced.json", "--refine", "--video", "synced.mp4", "--yes",
                "--api-url", api.url, cwd=project, home_dir=home)
    assert r.returncode == 1 and "Stopped after part 1" in r.stdout
    assert "STOPPED EARLY" in (project / "notes-synced.refine-report.txt").read_text()
    assert (project / "notes-synced.json.bak").exists()
