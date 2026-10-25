"""Claude on your subscription: the claude-code backend (claude_api.call_claude_code, run through the stand-in `claude`
in tests/fake_claude.py), the setting that chooses it, and the flag, scripts and app that carry it."""
import argparse
import json
import os
import shutil
import stat
import types

import pytest
from conftest import make_srt, needs_ffmpeg, run_cli
from test_progress_and_cancel import LONG
from test_prompts import drive

import app
import claude_api
import context_notes
import generate_notes as gn

MODEL = "claude-sonnet-5-5"


def flag_value(argv, flag):
    return argv[argv.index(flag) + 1]


def flag_values(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]


# ---------------------------------------------------------------- the setting
def test_load_backend_order_flag_then_environment_then_file_then_api(home, monkeypatch):
    assert claude_api.load_backend() == "api"
    assert claude_api.backend_path() == home / ".config" / "context-notes" / "backend"
    claude_api.set_backend("claude-code")
    assert claude_api.load_backend() == "claude-code"
    monkeypatch.setenv("CONTEXT_NOTES_BACKEND", "api")
    assert claude_api.load_backend() == "api"
    assert claude_api.load_backend("claude-code") == "claude-code"
    with pytest.raises(SystemExit, match="CONTEXT_NOTES_BACKEND"):
        monkeypatch.setenv("CONTEXT_NOTES_BACKEND", "gemini")
        claude_api.load_backend()
    monkeypatch.delenv("CONTEXT_NOTES_BACKEND")
    claude_api.backend_path().write_text("something else\n")
    with pytest.raises(SystemExit, match="--set-backend"):
        claude_api.load_backend()
    claude_api.backend_path().write_text("\n")                       # an empty file means: not chosen
    assert claude_api.load_backend() == "api"


def test_set_backend_writes_a_private_file_all_at_once(home, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))                        # no `claude` installed here
    claude_api.set_backend("claude-code")
    path = claude_api.backend_path()
    assert path.read_text() == "claude-code\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert not list(path.parent.glob(".*.part*"))                     # written through fileio.replacing
    out = capsys.readouterr().out
    assert "on your Claude subscription" in out and "isn't installed" in out
    claude_api.set_backend("api")
    assert path.read_text() == "api\n" and "API credits" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        claude_api.set_backend("gemini")


def test_cli_set_backend(home, tmp_path, fake_claude):
    r = run_cli("make_ass.py", "--set-backend", "claude-code", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stderr
    assert "Saved to" in r.stdout and f"Claude Code found at {fake_claude.exe}" in r.stdout
    assert (home / ".config" / "context-notes" / "backend").read_text() == "claude-code\n"
    r = run_cli("make_ass.py", "--set-backend", "openai", cwd=tmp_path, home_dir=home)
    assert r.returncode == 2 and "invalid choice" in r.stderr


def test_help_shows_the_new_flags(tmp_path):
    for script in ("make_ass.py", "context_notes.py"):
        text = " ".join(run_cli(script, "--help", cwd=tmp_path).stdout.split())
        assert "--backend {api,claude-code}" in text, script
        assert "Claude subscription" in text, script
    assert "--set-backend {api,claude-code}" in " ".join(run_cli("make_ass.py", "--help", cwd=tmp_path).stdout.split())


def test_the_flag_is_forwarded_by_context_notes():
    opts = argparse.Namespace(model=None, effort=None, backend="claude-code", api_url=None, api_key_file=None,
                              audience=None, notes_language=None, yes=False)
    assert context_notes.common_api_args(opts) == ["--backend", "claude-code"]


# ---------------------------------------------------------------- Claude Code not installed
def test_not_installed_stops_early_with_a_plain_hint(home, tmp_path, monkeypatch):
    real_path = os.environ["PATH"]
    monkeypatch.setenv("PATH", str(tmp_path))                        # nothing called `claude` anywhere
    assert claude_api.claude_bin() is None
    with pytest.raises(SystemExit) as e:
        claude_api.check_claude_code()
    assert "isn't installed" in str(e.value) and "--set-backend api" in str(e.value)
    srt = make_srt(tmp_path / "ep.srt", n=3)
    with pytest.raises(SystemExit, match="isn't installed"):
        gn.plan_generate(srt, tmp_path / "n.json", backend="claude-code")
    # the scripts stop before any work, and don't ask for an API key
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--backend", "claude-code", cwd=tmp_path, home_dir=home,
                env_extra={"PATH": str(tmp_path)})
    assert r.returncode == 1 and "Claude Code isn't installed" in r.stderr and "--set-api-key" not in r.stderr
    assert not (tmp_path / "notes-ep.json").exists()
    (tmp_path / "ep.mp4").write_bytes(b"")
    tools = tmp_path / "bin"                                        # ffprobe but no claude
    tools.mkdir()
    for name in ("ffprobe", "ffmpeg"):
        if shutil.which(name, path=real_path):
            (tools / name).symlink_to(shutil.which(name, path=real_path))
    r = run_cli("context_notes.py", tmp_path, "--yes", "--backend", "claude-code", cwd=tmp_path, home_dir=home,
                env_extra={"PATH": str(tools)})
    assert r.returncode == 1 and "Claude Code isn't installed" in r.stderr and "Checking the subtitles" not in r.stdout
    # an estimate needs neither Claude Code nor a key
    r = run_cli("make_ass.py", srt, "--generate", "--estimate-only", "--backend", "claude-code", cwd=tmp_path,
                home_dir=home, env_extra={"PATH": str(tmp_path), "CONTEXT_NOTES_UI": "json"})
    assert r.returncode == 0, r.stderr
    (est,) = [json.loads(ln.split(" ", 1)[1]) for ln in r.stdout.splitlines() if ln.startswith("@context-notes")]
    assert est["type"] == "estimate" and est["backend"] == "claude-code" and est["cost_usd"] is None
    assert "on your Claude subscription (no API credits)" in r.stdout


def test_context_notes_skips_the_key_check_on_claude_code(home, tmp_path, fake_claude):
    (tmp_path / "ep.mp4").write_bytes(b"")
    make_srt(tmp_path / "ep.srt", n=3)
    r = run_cli("context_notes.py", tmp_path, "--yes", "--backend", "claude-code", cwd=tmp_path, home_dir=home)
    assert "--set-api-key" not in r.stderr and "Checking the subtitles" in r.stdout     # past the early check, no key
    r = run_cli("context_notes.py", tmp_path, "--yes", cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "--set-api-key" in r.stderr                            # the API still wants one


# ---------------------------------------------------------------- the call itself
def test_call_claude_code_text(fake_claude, tmp_path):
    prompt = "Lines to annotate (1 to 3):\n1 [0:00:03] Line one of the test\n2 [0:00:09] Line two of the test\n3 [0:00:15] Three"
    reply = claude_api.call_claude_code(MODEL, "SYSTEM PROMPT", prompt, effort="high", workdir=tmp_path)
    assert reply["backend"] == "claude-code" and reply["stop_reason"] == "end_turn"
    assert reply["usage"] == {"input_tokens": 2000, "output_tokens": 200}        # input + cache written + cache read
    assert reply["content"][0]["type"] == "text" and "Note 1" in reply["content"][0]["text"]
    (call,) = fake_claude.calls
    argv = call["argv"]
    assert argv[:4] == ["-p", "--output-format", "json", "--model"] and flag_value(argv, "--model") == MODEL
    assert flag_value(argv, "--system-prompt") == "SYSTEM PROMPT" and "--no-session-persistence" in argv
    assert flag_value(argv, "--effort") == "high" and flag_value(argv, "--tools") == ""
    assert "--add-dir" not in argv and "--max-turns" not in argv
    assert call["prompt"] == prompt and call["cwd"] == str(tmp_path)


def test_call_claude_code_images(fake_claude, tmp_path):
    sheets = tmp_path / "ep analysis"
    sheets.mkdir()
    for k in (1, 2):
        (sheets / f"sheet{k}.jpg").write_bytes(b"\xff\xd8 not really a jpeg")
    content = [{"type": "text", "text": "Contact sheet: frames from 0:00:00 to 0:01:00"},
               {"type": "image", "path": str(sheets / "sheet1.jpg"), "media_type": "image/jpeg"},
               {"type": "text", "text": "Contact sheet: frames from 0:01:00 to 0:02:00"},
               {"type": "image", "path": str(sheets / "sheet2.jpg"), "media_type": "image/jpeg"},
               {"type": "text", "text": "Title: T\nPart 1 of 1. This stretch: 0:00:00 to 0:02:00 (video time).\n\n"
                                        "Existing notes in this stretch:\n#1 [0:00:03, speech, Idiom, high] x"}]
    reply = claude_api.call_claude_code(MODEL, "You refine notes", content, workdir=tmp_path)
    assert "REVISED" in reply["content"][0]["text"]
    (call,) = fake_claude.calls
    argv = call["argv"]
    assert flag_value(argv, "--tools") == "Read" and flag_values(argv, "--add-dir") == [str(sheets.resolve())]
    assert flag_value(argv, "--max-turns") == "8"                                 # 2 per image + 4
    assert str(sheets / "sheet1.jpg") in call["prompt"] and str(sheets / "sheet2.jpg") in call["prompt"]
    assert call["prompt"].index("0:00:00 to 0:01:00") < call["prompt"].index("sheet1.jpg") < call["prompt"].index("sheet2.jpg")
    assert "Read tool" in call["prompt"] and "ONLY the JSON" in call["prompt"]
    assert "base64" not in call["prompt"]


def test_send_dispatches_to_the_api_or_claude_code(api, fake_claude, tmp_path):
    jpg = tmp_path / "s.jpg"
    jpg.write_bytes(b"\xff\xd8x")
    content = [{"type": "text", "text": "Lines to annotate (1 to 2):\n1 [0:00:03] A b c\n2 [0:00:09] D e f"},
               {"type": "image", "path": str(jpg)}]
    r = claude_api.send("api", MODEL, "S", content, key="sk-ant-k", api_url=api.url)
    assert r["content"][0]["text"] == "[]" and "backend" not in r
    sent = api.calls[0]["body"]["messages"][0]["content"]
    assert sent[1]["source"]["type"] == "base64" and not fake_claude.calls          # images encoded for the API
    r = claude_api.send("claude-code", MODEL, "S", content, workdir=tmp_path)
    assert r["backend"] == "claude-code" and len(api.calls) == 1 and len(fake_claude.calls) == 1
    r = claude_api.send("claude-code", MODEL, "S", "Lines to annotate (1 to 2):\n1 [0:00:03] A b c\n2 [0:00:09] D e f")
    assert flag_value(fake_claude.calls[-1]["argv"], "--tools") == ""
    with pytest.raises(SystemExit):
        claude_api.send("gemini", MODEL, "S", "x")


def test_cost_is_none_on_the_subscription():
    assert claude_api.cost(MODEL, 1_000_000, 0) == 2.0 and claude_api.cost(MODEL, 1_000_000, 0, "claude-code") is None
    assert claude_api.cost_note(0.5, "claude-code") == ", on your Claude subscription (no API credits)."
    assert claude_api.cost_note(0.5) == ", roughly $0.50 in API credits." and claude_api.cost_note(None) == "."
    assert claude_api.used_note(None, "claude-code").startswith(" (on your Claude subscription;")


def test_a_failing_cli_stops_the_run_with_its_own_message(fake_claude, tmp_path):
    fake_claude.fail("limit")
    with pytest.raises(SystemExit) as e:
        claude_api.call_claude_code(MODEL, "S", "Lines to annotate (1 to 2):\n1 [0:00:03] A b c\n2 [0:00:09] D e f")
    assert "usage limit" in str(e.value) and "Claude Code stopped" in str(e.value) and "--backend api" in str(e.value)
    fake_claude.fail("login")
    with pytest.raises(SystemExit, match="Not logged in"):
        claude_api.call_claude_code(MODEL, "S", "Lines to annotate (1 to 2):\n1 [0:00:03] A b c\n2 [0:00:09] D e f")


# ---------------------------------------------------------------- writing notes, end to end
def test_generate_on_claude_code_without_an_api_key(home, tmp_path, fake_claude):
    srt = make_srt(tmp_path / "ep.srt", n=12)
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--backend", "claude-code", "--model", MODEL, "--effort", "high",
                cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "on your Claude subscription (no API credits)." in r.stdout and "cached context)." in r.stdout
    assert "$" not in r.stdout
    spec = json.loads((tmp_path / "notes-ep.json").read_text())
    assert spec["generated_by"] == MODEL and spec["backend"] == "claude-code" and len(spec["notes"]) > 1
    assert (tmp_path / "ep.ass").exists()
    (call,) = fake_claude.calls
    assert call["cwd"] == str(tmp_path) and flag_value(call["argv"], "--effort") == "high"
    assert "Title: ep" in call["prompt"] and "You write short" in flag_value(call["argv"], "--system-prompt")


def test_the_saved_setting_is_used_without_the_flag(home, tmp_path, fake_claude):
    claude_api.set_backend("claude-code")
    srt = make_srt(tmp_path / "ep.srt", n=12)
    r = run_cli("make_ass.py", srt, "--generate", "--yes", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp_path / "notes-ep.json").read_text())["backend"] == "claude-code" and fake_claude.calls
    # --backend api on top of it wants the key again
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--force", "--backend", "api", cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "--set-api-key" in r.stderr and len(fake_claude.calls) == 1


def test_gui_sees_the_backend_in_the_estimate_and_the_question(home, tmp_path, fake_claude):
    srt = make_srt(tmp_path / "ep.srt", n=12)
    code, out, evs = drive([srt, "--generate", "--backend", "claude-code"], {"generate.send": "y"}, tmp_path, home,
                           script="make_ass.py")
    assert code == 0, out
    est = next(e for e in evs if e["type"] == "estimate")
    assert est["backend"] == "claude-code" and est["cost_usd"] is None and est["input_tokens"] > 0
    q = next(e for e in evs if e["type"] == "question")
    assert q["id"] == "generate.send" and q["text"] == "Send the subtitle text to Claude Code (your subscription) now?"
    code, out, evs = drive([srt, "--generate", "--estimate-only"], {}, tmp_path, home, script="make_ass.py")
    est = next(e for e in evs if e["type"] == "estimate")
    assert est["backend"] == "api" and est["cost_usd"] > 0                          # the API route is unchanged


def test_usage_limit_mid_run_keeps_the_finished_parts(home, tmp_path, fake_claude):
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    fake_claude.fail("limit-after-1")
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--backend", "claude-code", cwd=tmp_path, home_dir=home)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Claude Code stopped: You've hit your usage limit for this plan" in r.stderr
    assert "Stopped after part 1" in r.stdout and "the next run offers to pick up from there" in r.stdout
    kept = json.loads((tmp_path / "notes-ep.partial.json").read_text())
    assert kept["notes"] and kept["through_line"] > 1 and kept["backend"] == "claude-code"
    assert not (tmp_path / "notes-ep.json").exists() and len(fake_claude.calls) == 2
    # picking up: only the rest is sent
    fake_claude.fail("")
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--backend", "claude-code", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stderr
    assert "Picking up where the last run stopped" in r.stdout and not (tmp_path / "notes-ep.partial.json").exists()
    assert f"Lines to annotate ({kept['through_line'] + 1} to" in fake_claude.calls[2]["prompt"]


# ---------------------------------------------------------------- the frame pass, end to end (synthetic clip)
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
    (tmp_path / "synced.mp4").symlink_to(clip)
    make_srt(tmp_path / "synced.srt", n=24)
    notes = [{"at": "00:00:03,000", "category": "About these notes", "text": "Intro", "kind": "speech"}]
    notes += [{"match": f"Line {i} of", "category": "Idiom", "text": f"Original note {i}", "confidence": "high", "kind": "speech"}
              for i in (2, 5, 8, 12)]
    (tmp_path / "notes-synced.json").write_text(json.dumps({"title": "Test Show (context notes)", "notes": notes}))
    return tmp_path


@needs_ffmpeg
def test_refine_on_claude_code_reads_the_contact_sheets_with_the_read_tool(project, home, fake_claude):
    original = (project / "notes-synced.json").read_text()
    r = run_cli("make_ass.py", "synced.srt", "notes-synced.json", "--refine", "--video", "synced.mp4", "--yes",
                "--backend", "claude-code", cwd=project, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Mode: full" in r.stdout and "contact-sheet images" in r.stdout
    assert "on your Claude subscription (no API credits)." in r.stdout and "cached context)." in r.stdout
    spec = json.loads((project / "notes-synced.json").read_text())
    assert spec["refined"]["backend"] == "claude-code" and spec["refined"]["model"] == MODEL
    texts = [n["text"] for n in spec["notes"]]
    assert "REVISED" in texts and any(t.startswith("Prop at") for t in texts)
    assert (project / "notes-synced.json.bak").read_text() == original
    assert "Prop at" in (project / "synced.notes.ass").read_text(encoding="utf-8-sig")
    calls = fake_claude.calls
    assert len(calls) >= 2
    for call in calls:
        argv = call["argv"]
        assert flag_value(argv, "--tools") == "Read" and call["cwd"] == str(project)
        add_dirs = flag_values(argv, "--add-dir")
        assert add_dirs == [str((project / "synced analysis" / "sheets").resolve())]   # the fake checked each image is in it
        assert "You refine" in flag_value(argv, "--system-prompt") and int(flag_value(argv, "--max-turns")) >= 6
        assert ".jpg" in call["prompt"] and "Existing notes in this stretch" in call["prompt"]


@needs_ffmpeg
def test_context_notes_runs_both_steps_on_claude_code(home, tmp_path, clip, fake_claude):
    season = tmp_path / "Test Show" / "Season 1"
    season.mkdir(parents=True)
    os.symlink(clip, season / "S01E01 Pilot.mp4")
    make_srt(season / "S01E01 Pilot.srt", n=24)
    r = run_cli("context_notes.py", season, "--yes", "--backend", "claude-code", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Ready: play S01E01 Pilot.mp4" in r.stdout and "--backend claude-code" in r.stdout
    spec = json.loads((season / "notes-S01E01 Pilot.json").read_text())
    assert spec["backend"] == "claude-code" and spec["refined"]["backend"] == "claude-code"
    assert (season / "S01E01 Pilot.notes.ass").exists()
    tools = [flag_value(c["argv"], "--tools") for c in fake_claude.calls]
    assert tools[0] == "" and "Read" in tools and all(c["cwd"] == str(season) for c in fake_claude.calls)


# ---------------------------------------------------------------- the app
@pytest.fixture
def server(api, home):
    import threading
    s = app.make_server(0, api.url)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def test_app_reports_and_saves_the_backend(server, home, fake_claude):
    from test_app import call
    status, info = call(server, "/api/info")
    assert status == 200 and info["backend"] == "api"
    assert info["claude_code"] == {"installed": True, "path": str(fake_claude.exe)}
    status, r = call(server, "/api/backend", {"backend": "claude-code"})
    assert status == 200 and r["ok"] and "subscription" in r["message"] and r["backend"] == "claude-code"
    assert (home / ".config" / "context-notes" / "backend").read_text() == "claude-code\n"
    assert call(server, "/api/info")[1]["backend"] == "claude-code"
    _, r = call(server, "/api/backend", {"backend": "gemini"})
    assert not r["ok"] and call(server, "/api/info")[1]["backend"] == "claude-code"
    assert call(server, "/api/backend", {"backend": "api"}, key=False)[0] == 403
    _, r = call(server, "/api/backend", {"backend": "api"})
    assert r["ok"] and "API" in r["message"] and call(server, "/api/info")[1]["backend"] == "api"


def test_app_says_when_claude_code_is_missing(server, home, monkeypatch):
    from test_app import call
    monkeypatch.setenv("PATH", str(home))
    assert call(server, "/api/info")[1]["claude_code"] == {"installed": False, "path": None}
    _, r = call(server, "/api/backend", {"backend": "claude-code"})
    assert r["ok"] and "isn't installed" in r["message"] and not r["claude_code"]["installed"]


def test_app_run_passes_the_backend(home, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "Job", lambda cmd: types.SimpleNamespace(cmd=cmd, running=False))
    a = app.App()
    assert a.run({"path": str(tmp_path)})[0] == 200
    assert a.job.cmd[-4:] == ["--effort", "high", "--backend", "api"]
    claude_api.set_backend("claude-code")
    a.run({"path": str(tmp_path)})
    assert flag_value(a.job.cmd, "--backend") == "claude-code"
    a.run({"path": str(tmp_path), "backend": "api"})
    assert flag_value(a.job.cmd, "--backend") == "api"
    assert a.run({"path": str(tmp_path), "backend": "gemini"})[0] == 400
