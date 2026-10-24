"""Progress reports, and stopping part-way (Ctrl-C, or a GUI's Cancel): nothing half-written, nothing paid for lost."""
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import types

import pytest
from conftest import ROOT, make_srt, needs_ffmpeg, run_cli
from test_prompts import GUI, drive, events

import analyze
import make_ass
import prompts

LONG = "Line {i} of the original test script, " + "and then it goes on and on " * 32     # several requests' worth


def cancel_when(test):
    """An on_event for drive(): send Ctrl-C's signal to the whole run (as a GUI's Cancel does) at the first event
    `test` accepts. `.sent` says whether it happened."""
    def on_event(ev, p):
        if not on_event.sent and test(ev):
            on_event.sent = True
            os.killpg(p.pid, signal.SIGINT)
    on_event.sent = False
    return on_event


def second_request(ev):
    return ev["type"] == "progress" and ev["task"] == "generate" and ev["done"] == 1


def held_after_first(responder, gate):
    """The fake API answers the first request and keeps later ones waiting until `gate` is set."""
    return lambda n, body, h: (n > 1 and gate.wait(20), responder(n, body, h))[1]


def leftovers(folder):
    return [p.name for p in folder.rglob(".*.part*")]


# ---------------------------------------------------------------- writing files all at once
def test_write_text_safely_writes_and_keeps_permissions(tmp_path):
    plain = tmp_path / "plain.txt"
    plain.write_text("x")
    new = tmp_path / "new.txt"
    make_ass.write_text_safely(new, "héllo\n")
    assert new.read_text(encoding="utf-8") == "héllo\n"
    assert stat.S_IMODE(new.stat().st_mode) == stat.S_IMODE(plain.stat().st_mode)     # a new file: the usual mode
    plain.chmod(0o640)
    make_ass.write_text_safely(plain, "y")
    assert plain.read_text() == "y" and stat.S_IMODE(plain.stat().st_mode) == 0o640   # an old file keeps its own
    assert not leftovers(tmp_path)


def test_write_text_safely_writes_through_a_symlink(tmp_path):
    real = tmp_path / "real.json"
    real.write_text("old")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    make_ass.write_text_safely(link, "new")
    assert link.is_symlink() and real.read_text() == "new"


def test_an_interrupted_write_leaves_the_old_file_and_no_temporary_one(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text("the old notes")
    with pytest.raises(KeyboardInterrupt):
        with make_ass.replacing(path) as tmp:
            tmp.write_text("half of the new no")
            raise KeyboardInterrupt
    assert path.read_text() == "the old notes"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.json"]


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs folder permissions that apply")
def test_a_folder_that_takes_no_new_files_is_written_in_place_as_before(tmp_path):
    folder = tmp_path / "locked"
    folder.mkdir()
    path = folder / "film.notes.ass"
    path.write_text("old")
    folder.chmod(0o500)                     # no new files allowed, but the existing one is still writable
    try:
        make_ass.write_text_safely(path, "new")
        assert path.read_text() == "new"
    finally:
        folder.chmod(0o700)


# ---------------------------------------------------------------- the speech-recognition transcript cache
class FakeWhisper:
    """Stands in for faster_whisper: four segments over 40 s of audio; `stop_at` raises Ctrl-C's KeyboardInterrupt
    before that segment."""
    stop_at = None

    def WhisperModel(self, *args, **kwargs):
        fake = self

        class Model:
            def transcribe(self, audio, **kw):
                def segments():
                    for i in range(4):
                        if i == fake.stop_at:
                            raise KeyboardInterrupt
                        yield types.SimpleNamespace(start=i * 10.0, end=i * 10.0 + 9, text=f" line {i}", words=[])
                return segments(), None
        return Model()


@pytest.fixture
def fake_speech(monkeypatch):
    np = pytest.importorskip("numpy")
    whisper = FakeWhisper()
    monkeypatch.setattr(analyze, "need", lambda module, hint: {"numpy": np, "faster_whisper": whisper}[module])
    silence = types.SimpleNamespace(stdout=bytes(2 * analyze.SR * 40), returncode=0)      # 40 s of soundtrack
    monkeypatch.setattr(analyze, "subprocess", types.SimpleNamespace(run=lambda cmd, **kw: silence))
    monkeypatch.setattr(prompts, "_last_progress", {})
    return whisper


def test_a_stopped_transcription_leaves_no_cache_behind(tmp_path, fake_speech):
    cache = tmp_path / "transcript-base.en.jsonl"
    fake_speech.stop_at = 2
    with pytest.raises(KeyboardInterrupt):
        analyze.transcribe(tmp_path / "film.mkv", None, "base.en", cache)
    # Before: the first two segments were left in the cache, and the next run used them as the whole film.
    assert not cache.exists() and not leftovers(tmp_path)
    fake_speech.stop_at = None
    assert len(analyze.transcribe(tmp_path / "film.mkv", None, "base.en", cache)) == 4
    assert len(cache.read_text().splitlines()) == 4


def test_transcription_progress_in_a_gui_and_in_a_terminal(tmp_path, fake_speech, monkeypatch, capsys):
    analyze.transcribe(tmp_path / "f.mkv", None, "base.en", tmp_path / "a.jsonl")
    out = capsys.readouterr().out
    assert "\r  transcribing: " in out and not events(out)                       # the terminal, as before
    monkeypatch.setenv("CONTEXT_NOTES_UI", "json")
    analyze.transcribe(tmp_path / "f.mkv", None, "base.en", tmp_path / "b.jsonl")
    out = capsys.readouterr().out
    evs = events(out)
    assert {e["type"] for e in evs} == {"progress"} and {e["task"] for e in evs} == {"transcribe"}
    assert evs[0]["total"] is None and (evs[-1]["done"], evs[-1]["total"]) == (40.0, 40.0)
    assert "\r" not in out and "transcribed" in out                              # no rewritten line in a GUI's log


# ---------------------------------------------------------------- progress while writing notes
def test_generate_reports_each_request(tmp_path, api, api_key_file, home):
    from test_generate_notes import notes_for_each_part
    api.responder = notes_for_each_part
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home,
                env_extra=GUI)
    assert r.returncode == 0, r.stdout + r.stderr
    n = [e for e in events(r.stdout) if e["type"] == "estimate"][0]["requests"]
    done = [(e["done"], e["total"]) for e in events(r.stdout) if e["type"] == "progress" and e["task"] == "generate"]
    assert n >= 2 and done == [(k, n) for k in range(n + 1)] and len(api.calls) == n
    assert "part 1/" in r.stdout                                                    # the log lines are still there


# ---------------------------------------------------------------- cancelling
def test_cancel_while_writing_notes_keeps_what_was_paid_for(tmp_path, api, api_key_file, home):
    from test_generate_notes import notes_for_each_part
    gate = threading.Event()
    api.responder = held_after_first(notes_for_each_part, gate)
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    cancel = cancel_when(second_request)
    try:
        code, out, _ = drive([srt, "--generate", "--yes", "--api-url", api.url], {}, tmp_path, home,
                             script="make_ass.py", on_event=cancel)
    finally:
        gate.set()
    assert cancel.sent and code == -signal.SIGINT, out
    assert "Stopped after part 1 of" in out
    assert json.loads((tmp_path / "notes-ep.partial.json").read_text())["notes"]      # part 1's notes, kept
    assert not (tmp_path / "notes-ep.json").exists() and not (tmp_path / "ep.ass").exists()
    assert not leftovers(tmp_path)


def test_ctrl_c_in_a_terminal_keeps_the_notes_too(tmp_path, api, api_key_file, home):
    """No GUI: the same signal a Ctrl-C sends, after the first part's line is finished."""
    from test_generate_notes import notes_for_each_part
    gate = threading.Event()
    api.responder = held_after_first(notes_for_each_part, gate)
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "HOME": str(home)}
    for name in ("ANTHROPIC_API_KEY", "XDG_CONFIG_HOME", "CONTEXT_NOTES_UI"):
        env.pop(name, None)
    p = subprocess.Popen([sys.executable, str(ROOT / "make_ass.py"), str(srt), "--generate", "--yes", "--api-url",
                          api.url], cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, start_new_session=True)
    out = []
    try:
        for line in p.stdout:
            out.append(line)
            if line.startswith("  part 1/") and line.rstrip().endswith("notes"):
                os.killpg(p.pid, signal.SIGINT)
        code = p.wait(timeout=30)
    finally:
        gate.set()
    text = "".join(out)
    assert code == -signal.SIGINT and "Stopped after part 1 of" in text and "@context-notes" not in text, text
    assert (tmp_path / "notes-ep.partial.json").exists() and not (tmp_path / "notes-ep.json").exists()


np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from test_refine_notes import make_video  # noqa: E402


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "synced.mp4"
    make_video(path)
    return path


@needs_ffmpeg
def test_cancel_in_the_wrapper_then_run_it_again(tmp_path, clip, api, api_key_file, home):
    from test_context_notes import both
    os.symlink(clip, tmp_path / "ep.mp4")
    make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    gate = threading.Event()
    api.responder = held_after_first(both, gate)
    cancel = cancel_when(second_request)
    try:
        code, out, evs = drive(["ep.mp4", "--api-url", api.url], {"generate.send": "y"}, tmp_path, home,
                               on_event=cancel)
    finally:
        gate.set()
    assert cancel.sent and code == 130, out
    assert "Stopped after part 1 of" in out                       # the step had time to keep its notes...
    assert "Stopped. Rerun the same command" in out               # ...and the wrapper says what to do next
    assert (tmp_path / "notes-ep.partial.json").exists() and not (tmp_path / "notes-ep.json").exists()
    assert not (tmp_path / "ep.notes.ass").exists() and not leftovers(tmp_path)
    assert not [e for e in evs if e["type"] == "video-result"]    # it never finished the video

    api.responder = both
    before = len(api.calls)
    code, out, evs = drive(["ep.mp4", "--api-url", api.url],
                           {"generate.send": "y", "refine.send": "y", "alignment.check": "n"}, tmp_path, home)
    assert code == 0, out
    assert [e["id"] for e in evs if e["type"] == "question"][0] == "generate.resume"       # picked up (the default)...
    sent = [c["body"]["messages"][0]["content"] for c in api.calls[before:] if "You refine" not in c["body"]["system"]]
    assert "Lines to annotate (1 to" not in sent[0]                                        # ...so part 1 wasn't resent
    assert not (tmp_path / "notes-ep.partial.json").exists()
    assert [e["result"] for e in evs if e["type"] == "video-result"] == ["ready"]
    assert (tmp_path / "ep.notes.ass").exists() and json.loads((tmp_path / "notes-ep.json").read_text())["refined"]
