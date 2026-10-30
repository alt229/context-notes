"""The plan route: requests through Claude Code (claude_code.py), and moving to API credits when the plan can't go
on (sending.Sender). Claude Code is always tests/fake_claude.py here (conftest.fake_claude)."""
import json
import time

import pytest
from conftest import claude_calls, make_srt, needs_ffmpeg, run_cli
from test_app import call, server  # noqa: F401  (the app fixture)
from test_generate_notes import notes_for_each_part
from test_progress_and_cancel import LONG
from test_usage import events_in

import app
import claude_code
import cli_common
import generate_notes as gn
import prompts
import settings
import usage


def plan_generate(tmp_path, *extra, env=None, home=None, n=30):
    srt = tmp_path / "ep.srt"
    if not srt.exists():
        make_srt(srt, n=n, text=LONG)
    return run_cli("make_ass.py", srt, "--generate", "--yes", *extra, cwd=tmp_path, home_dir=home, env_extra=env)


def five_hour_at(percent):
    usage.write_session({"rate_limits": {"five_hour": {"used_percentage": percent, "resets_at": time.time() + 3600}}})


# ---------------------------------------------------------------- is Claude Code there, and signed in?
@pytest.mark.parametrize("auth, signed_in, problem", [
    ("claude.ai", True, None),
    ("oauth_token", True, None),
    ("none", False, "isn't signed in"),
    ("api_key", True, "signed in another way (api_key)"),
    ("missing", None, "couldn't say how it's signed in"),   # can't tell: it might be an API key, so not used
])
def test_status(monkeypatch, auth, signed_in, problem):
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", auth)
    s = claude_code.status(refresh=True)
    assert s["installed"] and s["version"] == "2.1.999" and s["signed_in"] is signed_in
    assert (s["problem"] is None) if problem is None else (problem in s["problem"])


def test_not_installed(monkeypatch):
    monkeypatch.setattr(claude_code, "command", lambda: None)
    s = claude_code.status(refresh=True)
    assert not s["installed"] and "isn't installed" in s["problem"]
    with pytest.raises(claude_code.CantGoOn):
        claude_code.call("claude-opus-5-5", "s", "hello")


def test_the_prompt_lists_the_contact_sheets_as_files(tmp_path):
    sheet = tmp_path / "sheet.jpg"
    sheet.write_bytes(b"x")
    text, images = claude_code.prompt_for([{"type": "text", "text": "Contact sheet: frames from 0:00:00 to 0:00:10"},
                                           {"type": "image", "path": str(sheet)}, {"type": "text", "text": "Go."}])
    assert images == [str(sheet.resolve())] and f"[Contact sheet image: {sheet.resolve()} - open it" in text
    assert text.index("Contact sheet: frames") < text.index("[Contact sheet image") < text.index("Go.")
    with pytest.raises(ValueError):                # an attached picture can't be handed to Claude Code
        claude_code.prompt_for([{"type": "image", "source": {"type": "base64", "data": "AAAA"}}])


# ---------------------------------------------------------------- the options
def test_the_route_comes_from_settings_and_an_api_url_means_the_api(usage_dir):
    import argparse
    ap = argparse.ArgumentParser()
    cli_common.add_claude_args(ap, "m", "e")
    opts = cli_common.settle_route(ap.parse_args([]))
    assert (opts.route, opts.api_fallback) == ("plan", 0.0)
    assert cli_common.settle_route(ap.parse_args(["--api-url", "http://x"])).route == "api"
    assert cli_common.settle_route(ap.parse_args(["--api-url", "http://x", "--route", "plan"])).route == "plan"
    settings.save({"route": "api", "api_fallback": True, "api_fallback_usd": 7.5})
    opts = cli_common.settle_route(ap.parse_args([]))
    assert (opts.route, opts.api_fallback) == ("api", 7.5)
    opts = cli_common.settle_route(ap.parse_args(["--route", "plan", "--api-fallback", "$2.50"]))
    assert cli_common.claude_args(opts)[-4:] == ["--route", "plan", "--api-fallback", "2.5"]
    for bad in ("lots", "-1", "5000"):
        with pytest.raises(SystemExit):
            ap.parse_args(["--api-fallback", bad])


# ---------------------------------------------------------------- writing the notes on the plan
def test_generate_on_the_plan(tmp_path, home, fake_claude):
    r = plan_generate(tmp_path, env={"ANTHROPIC_API_KEY": "sk-ant-should-never-reach-claude-code",
                                     prompts.ENV: "json"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "on your Claude plan through Claude Code (no API credits)" in r.stdout
    assert "No API key" not in r.stdout + r.stderr                     # none needed
    calls = claude_calls(fake_claude)
    assert len(calls) > 1
    for c in calls:
        argv = c["argv"]
        assert argv[argv.index("--model") + 1] == "claude-opus-5-5"     # Settings' model and effort
        assert argv[argv.index("--effort") + 1] == "high"
        assert argv[argv.index("--tools") + 1] == ""                   # no tools for the dialogue
        assert "--safe-mode" in argv and "--no-session-persistence" in argv
        assert "You write short" in c["system"] and "Lines to annotate" in c["prompt"]
        assert c["env"] == [] and c["cwd"] == str(tmp_path.resolve())  # no key, no GUI protocol; the notes' folder
    spec = json.loads((tmp_path / "notes-ep.json").read_text())
    assert any(n["text"].startswith("Note ") for n in spec["notes"])
    evs = events_in(r.stdout)
    est = next(e for e in evs if e["type"] == "estimate")
    assert est["route"] == "plan" and est["cost_usd"] is None and est["api_cost_usd"] > 0
    assert [e for e in evs if e["type"] == "usage"][0]["route"] == "plan"
    ents = usage.entries()
    assert len(ents) == len(calls) and all(e["route"] == "plan" and e["usd"] is None for e in ents)
    usage.set_balance(10)
    assert usage.balance()["spent_usd"] == 0 and usage.summary()["spent"]["plan_requests"] == len(calls)


def test_the_estimate_on_the_plan_needs_nothing(tmp_path, home, fake_claude):
    r = plan_generate(tmp_path, "--estimate-only")
    assert r.returncode == 0 and "on your Claude plan" in r.stdout and not claude_calls(fake_claude)


def test_the_plan_limit_part_way_stops_unattended_and_keeps_the_parts(tmp_path, home, fake_claude, monkeypatch, api,
                                                                    api_key_file):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit-after:1")
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "usage limit is reached" in r.stderr and "--api-fallback" in r.stderr
    assert "You've hit your session limit" in r.stderr
    kept = json.loads((tmp_path / "notes-ep.partial.json").read_text())
    assert kept["notes"] and not api.calls                         # part 1 kept; no API credit used
    # With an allowance, the rerun picks up on the plan, meets the limit again, and finishes with API credits.
    api.responder = notes_for_each_part
    r = plan_generate(tmp_path, "--route", "plan", "--api-fallback", "5", "--api-url", api.url)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Carrying on with API credits, up to $5.00 for this run" in r.stdout
    assert api.calls and not (tmp_path / "notes-ep.partial.json").exists()
    steps = [e.get("route", "api") for e in usage.entries()]
    assert steps[0] == "plan" and steps[-1] == "api"


def test_the_allowance_stops_the_run_when_it_is_used_up(tmp_path, home, monkeypatch, api, api_key_file):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    api.responder = notes_for_each_part              # Opus at 2,000 in and 300 out: $0.014 a request
    r = plan_generate(tmp_path, "--route", "plan", "--api-fallback", "0.02", "--api-url", api.url)
    assert r.returncode == 1 and len(api.calls) == 1
    assert "would go past the $0.02 allowed for it" in r.stderr
    assert json.loads((tmp_path / "notes-ep.partial.json").read_text())["notes"]


def test_signed_out_at_the_start_unattended_sends_nothing(tmp_path, home, monkeypatch, fake_claude, api):
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "none")
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "Claude Code can't be used here" in r.stdout and "isn't signed in" in r.stderr
    assert not claude_calls(fake_claude) and not (tmp_path / "notes-ep.json").exists()
    assert "roughly $" in r.stdout                   # the estimate is given in API credits, for the choice


def test_ninety_percent_of_the_session_stops_before_the_limit(tmp_path, home, fake_claude):
    five_hour_at(95)
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "5-hour session is 95% used" in r.stderr and not claude_calls(fake_claude)
    five_hour_at(40)
    r = plan_generate(tmp_path)
    assert r.returncode == 0 and claude_calls(fake_claude)
    assert "5-hour session 42% used when last seen" in r.stdout      # what each request itself reported


def test_each_request_brings_back_the_plans_windows(tmp_path, home, monkeypatch, fake_claude):
    """The background requests report the plan's windows themselves (stream-json), so the meter and the 90% stop
    work with no Claude Code window open: here the first part says 95%, so the second isn't started."""
    monkeypatch.setenv("FAKE_CLAUDE_RATE", "0.95,0.30")
    assert usage.session() is None
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "5-hour session is 95% used" in r.stderr
    assert len(claude_calls(fake_claude)) == 1
    s = usage.session()
    assert s["five_hour"]["percent"] == 95 and s["seven_day"]["percent"] == 30
    assert json.loads((tmp_path / "notes-ep.partial.json").read_text())["notes"]    # the first part is kept


def test_a_refusal_in_the_plans_windows_is_the_limit(tmp_path, home, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit-quiet")
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "usage limit is reached" in r.stderr


def test_a_fresh_reading_on_demand(server, monkeypatch, fake_claude):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_RATE", "0.12,0.34")
    status, r = call(server, "/api/plan/refresh", {})
    assert status == 200 and r["ok"], r
    assert r["usage"]["session"]["five_hour"]["percent"] == 12
    c = claude_calls(fake_claude)[-1]
    argv = c["argv"]
    assert argv[argv.index("--model") + 1] == "haiku" and argv[argv.index("--tools") + 1] == ""
    assert not usage.entries()                                    # a reading isn't a request worth a ledger line
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "none")
    claude_code.status(refresh=True)
    status, r = call(server, "/api/plan/refresh", {})
    assert not r["ok"] and "isn't signed in" in r["error"]


def test_attended_the_question_decides(tmp_path, home, monkeypatch, api, api_key_file, fake_claude):
    """In-process, as in a terminal: the plan's limit asks once whether to go on with API credits."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit-after:1")
    asked = []
    monkeypatch.setattr(prompts, "interactive", lambda: True)
    monkeypatch.setattr(prompts, "confirm", lambda text, id=None: asked.append((id, text)) or True)
    api.responder = notes_for_each_part
    srt = make_srt(tmp_path / "ep.srt", n=30, text=LONG)
    gn.generate(srt, tmp_path / "n.json", route="plan", api_url=api.url)
    ids = [i for i, _ in asked]
    assert ids == ["generate.send", "plan.fallback"]
    assert "Carry on with API credits instead?" in asked[1][1] and "would cost about $" in asked[1][1]
    assert len(claude_calls(fake_claude)) == 2 and api.calls       # the second part went to the API
    assert (tmp_path / "n.json").exists()
    monkeypatch.setattr(prompts, "confirm", lambda text, id=None: id != "plan.fallback")
    (tmp_path / "n.json").unlink()
    fake_claude.unlink()                             # its count starts again: one answer, then the limit
    monkeypatch.setenv(usage.RUN_ENV, usage.now_stamp())          # a new run: the yes above was for that one
    with pytest.raises(SystemExit) as e:
        gn.generate(srt, tmp_path / "n.json", route="plan", api_url=api.url)
    assert "Stopped" in str(e.value) and (tmp_path / "n.partial.json").exists()


def test_other_failures_stop_with_claude_codes_words(tmp_path, home, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "Claude Code stopped: Something went wrong in the fake" in r.stderr
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "signed-out")            # signed out part-way: the plan can't go on
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "can't sign in to your plan" in r.stderr


def test_an_old_claude_code_is_treated_as_unusable(tmp_path, home, monkeypatch, fake_claude):
    monkeypatch.setenv("FAKE_CLAUDE_HELP", "old")
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "too old" in r.stderr and not claude_calls(fake_claude)


# ---------------------------------------------------------------- the frames on the plan
@needs_ffmpeg
def test_refine_on_the_plan_opens_the_contact_sheets_itself(tmp_path, home, fake_claude, videos):
    from conftest import place
    place(videos / "synced.mp4", tmp_path / "synced.mp4")
    make_srt(tmp_path / "synced.srt", n=24)
    notes = [{"at": "00:00:03,000", "category": "About these notes", "text": "Intro", "kind": "speech"}]
    notes += [{"match": f"Line {i} of", "category": "Idiom", "text": f"Original note {i}", "kind": "speech"}
              for i in (2, 5, 8)]
    (tmp_path / "notes-synced.json").write_text(json.dumps({"title": "Test (context notes)", "notes": notes}))
    r = run_cli("make_ass.py", "synced.srt", "notes-synced.json", "--refine", "--video", "synced.mp4", "--yes",
                cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = claude_calls(fake_claude)
    assert calls
    for c in calls:
        argv = c["argv"]
        assert argv[argv.index("--tools") + 1] == "Read" and "--add-dir" in argv
        assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
        assert c["pictures"] and c["opened"] == c["pictures"]    # every sheet was inside a folder it may read
    spec = json.loads((tmp_path / "notes-synced.json").read_text())
    assert "REVISED" in [n["text"] for n in spec["notes"]] and spec["refined"]["contact_sheets"] > 0


@pytest.fixture(scope="module")
def videos(tmp_path_factory):
    from test_refine_notes import make_video
    d = tmp_path_factory.mktemp("video")
    make_video(d / "synced.mp4")
    return d


# ---------------------------------------------------------------- the app
def test_the_app_says_how_claude_code_is_and_checks_again(server, monkeypatch):  # noqa: F811
    _, info = call(server, "/api/info")
    assert info["claude"]["installed"] and info["claude"]["problem"] is None and info["claude"]["signed_in"]
    assert info["settings"]["route"] == "plan" and info["settings"]["api_fallback"] is False
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "none")
    _, r = call(server, "/api/claude/check", {})
    assert "isn't signed in" in r["claude"]["problem"]
    assert "isn't signed in" in call(server, "/api/info")[1]["claude"]["problem"]


# ---------------------------------------------------------------- signing in from the page
def test_signing_in_from_the_page(server, monkeypatch, tmp_path):  # noqa: F811
    """`claude auth login` prints a link and waits for the code: the page shows the link, the code goes back in."""
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "none")
    monkeypatch.setenv("FAKE_CLAUDE_SIGNIN", str(tmp_path / "signed-in"))
    assert "isn't signed in" in call(server, "/api/claude/check", {})[1]["claude"]["problem"]
    assert call(server, "/api/claude/login/state", {})[1] == {"waiting": False}
    _, r = call(server, "/api/claude/login", {})
    assert r["ok"] and r["url"].startswith("https://claude.example/oauth/authorize?")
    assert call(server, "/api/claude/login", {})[1]["url"] == r["url"]           # again: the same sign-in
    assert call(server, "/api/claude/login/state", {})[1] == {"waiting": True, "url": r["url"]}
    _, r = call(server, "/api/claude/login/code", {"code": ""})
    assert r["waiting"] and "Paste the code" in r["error"]
    _, r = call(server, "/api/claude/login/code", {"code": "bad"})               # refused: the sign-in is over
    assert r["waiting"] is False and r["ok"] is False and "Invalid authorization code" in r["error"]
    assert "isn't signed in" in r["claude"]["problem"]
    assert call(server, "/api/claude/login/state", {})[1] == {"waiting": False}
    assert call(server, "/api/claude/login", {})[1]["ok"]                        # once more, with the right code
    _, r = call(server, "/api/claude/login/code", {"code": "  abc#def  "})
    assert r["waiting"] is False and r["ok"] and r["claude"]["signed_in"] and r["claude"]["problem"] is None
    assert (tmp_path / "signed-in").read_text() == "abc#def"
    assert call(server, "/api/info")[1]["claude"]["signed_in"]
    _, r = call(server, "/api/claude/logout", {})
    assert r["ok"] and not r["claude"]["signed_in"] and not (tmp_path / "signed-in").exists()
    assert "isn't signed in" in call(server, "/api/info")[1]["claude"]["problem"]


def test_a_sign_in_that_goes_wrong_or_is_given_up(server, monkeypatch):  # noqa: F811
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "none")
    monkeypatch.setenv("FAKE_CLAUDE_LOGIN", "no-link")
    _, r = call(server, "/api/claude/login", {})
    assert r["ok"] is False and "wrong with the fake's network" in r["error"]
    monkeypatch.delenv("FAKE_CLAUDE_LOGIN")
    assert call(server, "/api/claude/login", {})[1]["ok"]                        # waiting for its code: given up
    p = claude_code._login["process"]
    assert p.poll() is None
    _, r = call(server, "/api/claude/login/cancel", {})
    assert "isn't signed in" in r["claude"]["problem"] and p.poll() is not None
    assert call(server, "/api/claude/login/state", {})[1] == {"waiting": False}
    monkeypatch.setattr(claude_code, "command", lambda: None)
    assert "isn't installed" in call(server, "/api/claude/login", {})[1]["error"]


def test_a_sign_in_without_a_link_in_time_is_given_up(monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_AUTH", "none")
    monkeypatch.setenv("FAKE_CLAUDE_LOGIN", "silent")
    monkeypatch.setattr(claude_code, "LINK_WAIT", 1)
    r = claude_code.login_start()
    assert r["ok"] is False and "within 1 seconds" in r["error"]
    assert claude_code._login["process"] is None


# ---------------------------------------------------------------- where Claude Code is
def test_where_claude_code_is(tmp_path, monkeypatch, home):
    monkeypatch.delenv("CONTEXT_NOTES_CLAUDE")
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    old = tmp_path / "nvm/node/v20/bin/claude"
    new = tmp_path / "nvm/node/v22/bin/claude"
    for i, f in enumerate((old, new)):
        f.parent.mkdir(parents=True)
        f.write_text("#!/bin/sh\necho 1.0.0 (Claude Code)\n")
        f.chmod(0o755)
        import os
        os.utime(f, (1000 + i, 1000 + i))
    monkeypatch.setattr(claude_code, "PLACES", (str(tmp_path / "missing/claude"), str(tmp_path / "nvm/node/*/bin/claude")))
    assert claude_code.command() == [str(new)]                                    # the newest of a glob
    settings.save({"claude_path": str(tmp_path / "nowhere/claude")})
    assert claude_code.command() is None
    assert "isn't at the place saved in Settings" in claude_code.status(refresh=True)["problem"]
    settings.save({"claude_path": str(old)})
    assert claude_code.command() == [str(old)]                                    # the saved path wins
    settings.save({"claude_path": ""})
    assert claude_code.command() == [str(new)]
    monkeypatch.setattr(claude_code, "PLACES", ())
    assert claude_code.command() is None
    assert "isn't installed" in claude_code.status(refresh=True)["problem"]


def test_saving_a_new_path_in_the_app_looks_again(server):  # noqa: F811
    status, r = call(server, "/api/settings", {"claude_path": "/nowhere/claude"})
    assert status == 200 and r["settings"]["claude_path"] == "/nowhere/claude"
    assert "claude" in r and r["claude"]["installed"]                 # looked again (the tests' stand-in still wins)
    status, r = call(server, "/api/settings", {"recursive": True})
    assert status == 200 and "claude" not in r
    assert call(server, "/api/settings", {"claude_path": ""})[0] == 200


def test_the_app_saves_the_claude_settings(server):  # noqa: F811
    status, r = call(server, "/api/settings", {"route": "api", "api_fallback": True, "api_fallback_usd": 3})
    assert status == 200 and (r["settings"]["route"], r["settings"]["api_fallback_usd"]) == ("api", 3)
    assert settings.route_defaults() == {"route": "api", "api_fallback": 3.0}
    for bad in ({"route": "free"}, {"api_fallback_usd": 0}, {"api_fallback_usd": "lots"}):
        assert call(server, "/api/settings", bad)[0] == 400


def test_the_pages_allowance_is_for_one_run(server, tmp_path):  # noqa: F811
    assert app.fallback_args({}) == []                                  # the page didn't say: Settings decides
    assert app.fallback_args({"api_fallback": False}) == ["--api-fallback", "0"]
    assert app.fallback_args({"api_fallback": True, "api_fallback_usd": "$2.50"}) == ["--api-fallback", "2.5"]
    for bad in ("", "lots", "0", "5000"):
        with pytest.raises(app.BadRequest):
            app.fallback_args({"api_fallback": True, "api_fallback_usd": bad})
    status, r = call(server, "/api/run", {"path": str(tmp_path), "api_fallback": True, "api_fallback_usd": "lots"})
    assert status == 400 and "Use API credits up to" in r["error"]


# ---------------------------------------------------------------- what the review found
def test_an_allowance_needs_a_price_to_be_kept_to(tmp_path, home, monkeypatch, api, api_key_file):
    """A model with no known price can't be held to --api-fallback, so it asks (here: nobody can, so it stops)."""
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    api.responder = notes_for_each_part
    r = plan_generate(tmp_path, "--route", "plan", "--api-fallback", "1", "--api-url", api.url,
                      "--model", "claude-unknown-model")
    assert r.returncode == 1 and "isn't known here" in r.stderr and not api.calls


def test_a_yes_to_api_credits_holds_for_the_rest_of_the_run(tmp_path, home, monkeypatch, api, api_key_file,
                                                            fake_claude):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit")
    monkeypatch.setenv(usage.RUN_ENV, usage.now_stamp())          # one run, two steps (as context_notes.py does)
    asked = []
    monkeypatch.setattr(prompts, "interactive", lambda: True)
    monkeypatch.setattr(prompts, "confirm", lambda text, id=None: asked.append(id) or True)
    api.responder = notes_for_each_part
    srt = make_srt(tmp_path / "ep.srt", n=30, text=LONG)
    gn.generate(srt, tmp_path / "a.json", route="plan", api_url=api.url)
    gn.generate(srt, tmp_path / "b.json", route="plan", api_url=api.url)
    assert asked.count("plan.fallback") == 1                        # the second step didn't ask again
    monkeypatch.setenv(usage.RUN_ENV, usage.now_stamp())          # a new run asks again
    gn.generate(srt, tmp_path / "c.json", route="plan", api_url=api.url)
    assert asked.count("plan.fallback") == 2


def test_the_closing_line_gives_dollars_only_for_the_api(tmp_path, home, monkeypatch, api, api_key_file, fake_claude):
    r = plan_generate(tmp_path)
    assert "output tokens, on your Claude plan (no API credits)." in r.stdout
    fake_claude.unlink()
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "limit-after:1")
    api.responder = notes_for_each_part
    r = plan_generate(tmp_path, "--force", "--route", "plan", "--api-fallback", "5", "--api-url", api.url)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "request(s) on your Claude plan," in r.stdout and "with API credits (about $" in r.stdout


@pytest.mark.parametrize("mode, cant_go_on", [("limit-reached", True), ("crash-after", False)])
def test_only_claude_codes_own_words_mean_the_limit(tmp_path, home, monkeypatch, mode, cant_go_on):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    r = plan_generate(tmp_path)
    assert r.returncode == 1
    assert ("usage limit is reached" in r.stderr) is cant_go_on
    assert ("Claude Code stopped" in r.stderr) is not cant_go_on


def test_a_request_that_never_answers_is_stopped_with_everything_it_started(monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")
    t = time.time()
    with pytest.raises(SystemExit) as e:
        claude_code.call("claude-opus-5-5", "s", "Lines to annotate (1 to 2)", timeout=2)
    assert "didn't answer within" in str(e.value) and time.time() - t < 30
