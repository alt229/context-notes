"""Questions and cost prompts: unchanged in a terminal, and answerable by another program (CONTEXT_NOTES_UI=json)."""
import io
import json
import os
import subprocess
import sys
import threading

import pytest
from conftest import NEW_GROUP, ROOT, assert_private, make_srt, needs_ffmpeg, place, run_cli

import find_subs
import prompts

GUI = {"CONTEXT_NOTES_UI": "json"}


def events(out):
    lines = out.splitlines()
    glued = [line for line in lines if prompts.PREFIX in line and not line.startswith(prompts.PREFIX)]
    assert not glued, f"an event that doesn't start its own line, so a GUI would miss it: {glued[0]!r}"
    return [json.loads(line[len(prompts.PREFIX):]) for line in lines if line.startswith(prompts.PREFIX)]


@pytest.fixture
def gui(home, monkeypatch):
    """json mode in this process, answering from `feed(text)`. (After `home`, which clears the setting.)"""
    monkeypatch.setenv("CONTEXT_NOTES_UI", "json")

    def feed(text):
        monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    return feed


# ---------------------------------------------------------------- a terminal: nothing changes
def test_terminal_mode_is_the_default_and_prints_no_events(monkeypatch, capsys):
    monkeypatch.delenv("CONTEXT_NOTES_UI", raising=False)
    assert not prompts.machine()
    prompts.event("estimate", cost_usd=1.0)
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("CONTEXT_NOTES_UI", "something else")
    assert not prompts.machine()


def test_terminal_prompts_are_the_same_calls_as_before(monkeypatch):
    monkeypatch.delenv("CONTEXT_NOTES_UI", raising=False)
    seen = []
    answers = iter(["Y", "", "no", "erin"])
    monkeypatch.setattr("builtins.input", lambda p: (seen.append(p), next(answers))[1])
    monkeypatch.setattr(prompts.getpass, "getpass", lambda p: (seen.append(p), "hidden")[1])
    assert prompts.confirm("Send it?") is True
    assert prompts.confirm("Send it?") is False
    assert prompts.confirm("Send it?") is False
    assert prompts.text_input("Username: ") == "erin"
    assert prompts.secret("Password (hidden): ") == "hidden"
    assert seen == ["Send it? [y/N] "] * 3 + ["Username: ", "Password (hidden): "]


# ---------------------------------------------------------------- json mode, one function at a time
def test_question_round_trip(gui, capsys):
    gui("a\n")
    assert prompts.question("What now?", {"a": "align", "c": "carry on"}, "c", id="sync.drift") == "a"
    (ev,) = events(capsys.readouterr().out)
    assert ev == {"v": 1, "type": "question", "id": "sync.drift", "text": "What now?",
                  "choices": [{"key": "a", "label": "align"}, {"key": "c", "label": "carry on"}], "default": "c"}


@pytest.mark.parametrize("answer", ["\n", "", "  \n"])
def test_an_empty_answer_or_the_end_of_input_takes_the_default(gui, answer):
    gui(answer)
    assert prompts.question("Go?", {"y": "yes", "n": "no"}, "n") == "n"


def test_an_answer_that_fits_no_choice_is_asked_again(gui, capsys):
    gui("maybe\nYes\n")
    assert prompts.question("Go?", {"y": "yes", "n": "no"}, "n") == "y"
    out = capsys.readouterr().out
    assert len(events(out)) == 2 and "Please answer 'y' (yes) or 'n' (no)" in out


def test_confirm_defaults_to_no(gui, capsys):
    gui("")
    assert prompts.confirm("Send?", id="generate.send") is False
    gui("y\n")
    assert prompts.confirm("Send?", id="generate.send") is True
    evs = events(capsys.readouterr().out)
    assert [e["default"] for e in evs] == ["n", "n"] and evs[0]["id"] == "generate.send"


def test_secret_is_read_but_never_written_out(gui, capsys):
    gui("sk-ant-secret-9999\n")
    assert prompts.secret("Paste your key: ", id="api-key") == "sk-ant-secret-9999"
    out = capsys.readouterr().out
    assert events(out) == [{"v": 1, "type": "input", "id": "api-key", "text": "Paste your key:", "hidden": True}]
    assert "sk-ant-secret" not in out


def test_each_reader_takes_only_its_own_line(monkeypatch):
    """The scripts a run starts share stdin, so one must never read ahead into the next one's answer."""
    r, w = os.pipe()
    os.write(w, b"y\nn\r\n")
    os.close(w)
    monkeypatch.setattr(sys, "stdin", os.fdopen(r, "r"))
    assert prompts.read_answer() == "y"
    assert os.read(r, 100) == b"n\r\n"                      # still there for the next reader
    assert prompts.read_answer() is None                    # end of input


def test_opensubtitles_login_from_a_gui(gui, home, monkeypatch, capsys):
    monkeypatch.setattr(find_subs, "os_test", lambda cfg: True)     # no network
    gui("OSKEY\nerin\npass word\n")
    assert find_subs.os_set_login()
    path = home / ".config" / "context-notes" / "opensubtitles.json"
    assert json.loads(path.read_text()) == {"api_key": "OSKEY", "username": "erin", "password": "pass word"}
    assert_private(path)
    out = capsys.readouterr().out
    assert [(e["id"], e["hidden"]) for e in events(out)] == [
        ("opensubtitles.api-key", True), ("opensubtitles.username", False), ("opensubtitles.password", True)]
    assert "OSKEY" not in out and "pass word" not in out


# ---------------------------------------------------------------- the scripts, run as a GUI would
def test_cli_set_api_key_from_a_gui(tmp_path, home):
    r = run_cli("make_ass.py", "--set-api-key", cwd=tmp_path, home_dir=home, stdin="sk-ant-gui-5678\n", env_extra=GUI)
    assert r.returncode == 0, r.stderr
    path = home / ".config" / "context-notes" / "api-key"
    assert path.read_text() == "sk-ant-gui-5678\n"
    assert_private(path)
    assert [e["id"] for e in events(r.stdout)] == ["api-key"]
    assert "sk-ant-gui" not in r.stdout + r.stderr and "5678" in r.stdout


def test_cli_without_a_terminal_still_needs_yes(tmp_path, api, api_key_file, home):
    r = run_cli("make_ass.py", make_srt(tmp_path / "ep.srt"), "--generate", "--api-url", api.url,
                cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "add --yes" in r.stderr and not api.calls
    assert not events(r.stdout)


def test_cli_generate_shows_the_estimate_and_asks_the_gui(tmp_path, api, api_key_file, home):
    from test_generate_notes import notes_for_each_part
    api.responder = notes_for_each_part
    srt = make_srt(tmp_path / "ep.srt")
    r = run_cli("make_ass.py", srt, "--generate", "--api-url", api.url, cwd=tmp_path, home_dir=home,
                stdin="n\n", env_extra=GUI)
    assert r.returncode == 1 and "Cancelled; nothing was sent." in r.stderr
    assert not api.calls and not (tmp_path / "notes-ep.json").exists()
    est, ask = events(r.stdout)
    assert est["type"] == "estimate" and est["step"] == "generate" and est["lines"] == 24
    assert est["requests"] >= 1 and est["input_tokens"] > 0 and est["cost_usd"] > 0 and est["limit"] is None
    assert ask["type"] == "question" and ask["id"] == "generate.send" and ask["default"] == "n"

    r = run_cli("make_ass.py", srt, "--generate", "--api-url", api.url, cwd=tmp_path, home_dir=home,
                stdin="y\n", env_extra=GUI)
    assert r.returncode == 0, r.stdout + r.stderr
    assert api.calls and (tmp_path / "notes-ep.json").exists() and (tmp_path / "ep.ass").exists()


@pytest.mark.parametrize("gui_mode", [False, True])
def test_cli_estimate_only_sends_and_writes_nothing(tmp_path, api, home, gui_mode):
    srt = make_srt(tmp_path / "ep.srt")                          # no API key saved: an estimate doesn't need one
    r = run_cli("make_ass.py", srt, "--generate", "--estimate-only", "--api-url", api.url, cwd=tmp_path, home_dir=home,
                env_extra=GUI if gui_mode else None)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Plan: 24 lines" in r.stdout and "Estimate only: nothing was sent." in r.stdout
    assert not api.calls and sorted(p.name for p in tmp_path.iterdir()) == ["ep.srt", "home"]
    assert [e["type"] for e in events(r.stdout)] == (["estimate"] if gui_mode else [])


def test_cli_estimate_only_leaves_existing_notes_alone(tmp_path, api, home):
    srt = make_srt(tmp_path / "ep.srt")
    notes = tmp_path / "notes-ep.json"
    notes.write_text('{"notes": [{"match": "Line 2 of", "text": "Mine"}]}')
    before = notes.read_text()
    r = run_cli("make_ass.py", srt, "--generate", "--estimate-only", cwd=tmp_path, home_dir=home)   # no --force needed
    assert r.returncode == 0, r.stdout + r.stderr
    assert notes.read_text() == before and not list(tmp_path.glob("*.bak")) and not (tmp_path / "ep.ass").exists()


def test_cli_estimate_only_needs_one_step(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt")
    r = run_cli("make_ass.py", srt, "--estimate-only", cwd=tmp_path, home_dir=home)
    assert r.returncode == 2 and "goes with --generate or --refine" in r.stderr
    r = run_cli("make_ass.py", srt, "--generate", "--refine", "--estimate-only", cwd=tmp_path, home_dir=home)
    assert r.returncode == 2 and "one step at a time" in r.stderr
    r = run_cli("make_ass.py", srt, "--refine", "--estimate-only", "--video", srt, cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "nothing to estimate" in r.stderr
    assert not (tmp_path / "notes-ep.json").exists()             # no blank notes file either


# ---------------------------------------------------------------- with video (synthetic clips)
np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from test_refine_notes import make_video  # noqa: E402


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "synced.mp4"
    make_video(path)
    return path


@pytest.fixture
def project(tmp_path, clip):
    place(clip, tmp_path / "synced.mp4")
    make_srt(tmp_path / "synced.srt", n=24)
    notes = [{"at": "00:00:03,000", "category": "About these notes", "text": "Intro", "kind": "speech"}]
    notes += [{"match": f"Line {i} of", "category": "Idiom", "text": f"Note {i}", "confidence": "high", "kind": "speech"}
              for i in (2, 5, 8, 12)]
    notes.append({"at_video": "00:00:10,000", "category": "Visual gag", "text": "A red balloon", "kind": "visual"})
    (tmp_path / "notes-synced.json").write_text(json.dumps({"title": "Test Show (context notes)", "notes": notes}))
    return tmp_path


@needs_ffmpeg
def test_cli_refine_estimate_only(project, api, home):
    before = (project / "notes-synced.json").read_text()
    r = run_cli("make_ass.py", "synced.srt", "notes-synced.json", "--refine", "--video", "synced.mp4", "--estimate-only",
                "--api-url", api.url, cwd=project, home_dir=home, env_extra=GUI)
    assert r.returncode == 0, r.stdout + r.stderr
    (est,) = [e for e in events(r.stdout) if e["type"] == "estimate"]
    assert est["step"] == "refine" and est["mode"] == "full" and est["images"] > 0 and est["notes"] == 6
    assert "Estimate only: nothing was sent." in r.stdout and not api.calls
    finished = {e["task"] for e in events(r.stdout) if e["type"] == "progress" and e["total"] and e["done"] == e["total"]}
    assert finished == {"soundtrack", "frames"}                  # the video analysis reports how far it has got
    assert (project / "notes-synced.json").read_text() == before
    assert not (project / "synced.notes.ass").exists() and not list(project.glob("*.bak"))


def drive(args, answers, cwd, home, script="context_notes.py", on_event=None):
    """Run a script the way a GUI would: read its output line by line and answer each question by id (anything not
    in `answers` gets an empty line, the default). `on_event(event, process)` sees every event, e.g. to press
    Cancel. Returns (exit code, output, events)."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "HOME": str(home), **GUI}
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("XDG_CONFIG_HOME", None)
    p = subprocess.Popen([sys.executable, str(ROOT / script), *map(str, args)], cwd=cwd, env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8",
                         errors="replace", **NEW_GROUP)
    timer = threading.Timer(240, p.kill)
    timer.start()
    out, evs = [], []
    try:
        for line in p.stdout:
            out.append(line)
            if line.startswith(prompts.PREFIX):
                ev = json.loads(line[len(prompts.PREFIX):])
                evs.append(ev)
                if ev["type"] in ("question", "input"):
                    p.stdin.write(answers.get(ev["id"], "") + "\n")
                    p.stdin.flush()
                if on_event:
                    on_event(ev, p)
        code = p.wait()
        events("".join(out))                      # fails the test if an event was glued to other text
        return code, "".join(out), evs
    finally:
        timer.cancel()


@needs_ffmpeg
def test_a_gui_can_drive_the_whole_wrapper(tmp_path, clip, api, api_key_file, home):
    """Questions from context_notes.py itself and from the scripts it starts all reach the GUI, in order."""
    from test_context_notes import both
    place(clip, tmp_path / "ep.mp4")
    make_srt(tmp_path / "ep.srt", n=24)
    api.responder = both
    code, out, evs = drive(["ep.mp4", "--api-url", api.url],
                           {"generate.send": "y", "refine.send": "y", "alignment.check": "n"}, tmp_path, home)
    assert code == 0, out
    asked = [e["id"] for e in evs if e["type"] == "question"]
    assert asked == ["generate.send", "refine.send", "alignment.check"]
    assert [e["step"] for e in evs if e["type"] == "estimate"] == ["generate", "refine"]
    assert [e["step"] for e in evs if e["type"] == "step"] == ["subtitles", "sync", "generate", "refine"]
    assert [(e["type"], e["index"], e["total"]) for e in evs if e["type"] == "video"] == [("video", 1, 1)]
    assert [e["result"] for e in evs if e["type"] == "video-result"] == ["ready"]
    finished = {e["task"] for e in evs if e["type"] == "progress" and e["total"] and e["done"] == e["total"]}
    assert {"soundtrack", "generate", "frames", "refine"} <= finished
    assert (tmp_path / "ep.notes.ass").exists() and "Ready: play ep.mp4" in out
    assert json.loads((tmp_path / "context-notes" / "ep.mp4" / "notes-ep.json").read_text())["refined"]
