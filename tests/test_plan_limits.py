"""The plan's limits a run keeps to (Erin, 2026-11-04): the weekly stop (--week-stop-at), waiting out a full 5-hour
session (--wait-for-reset), and --pace between videos. No network, no real Claude Code."""
import argparse
import time
from types import SimpleNamespace

import pytest
from conftest import claude_calls
from test_claude_code import plan_generate

import app
import claude_code
import cli_common
import context_notes
import sending
import settings
import usage


@pytest.fixture(autouse=True)
def limits():
    """Each test starts from the built-in limits, and leaves them that way."""
    before = dict(usage._limits)
    yield
    usage._limits.clear()
    usage._limits.update(before)


def reading(five=10, seven=20, five_reset_in=3600):
    now = time.time()
    usage.write_session({"rate_limits": {"five_hour": {"used_percentage": five, "resets_at": now + five_reset_in},
                                         "seven_day": {"used_percentage": seven, "resets_at": now + 3 * 86400}}})


# ---------------------------------------------------------------- the weekly stop
def test_the_weekly_stop_says_why_and_100_leaves_it_to_the_plan():
    reading(seven=92)
    assert "weekly limit is 92% used" in usage.week_full() and "stops at 90%" in usage.week_full()
    assert usage.week_full(95) is None
    assert usage.week_full(100) is None
    reading(seven=50)
    assert usage.week_full() is None


def test_a_run_stops_at_the_weekly_stop_and_goes_on_below_it(tmp_path, home, fake_claude):
    reading(seven=92)
    r = plan_generate(tmp_path)
    assert r.returncode == 1 and "weekly limit is 92% used" in r.stderr and not claude_calls(fake_claude)
    r = plan_generate(tmp_path, "--week-stop-at", "95")
    assert r.returncode == 0 and claude_calls(fake_claude)


def test_settings_set_the_weekly_stop(tmp_path, home, fake_claude):
    reading(seven=92)
    settings.save({"week_stop_at": 100})
    r = plan_generate(tmp_path)
    assert r.returncode == 0 and claude_calls(fake_claude)


# ---------------------------------------------------------------- waiting out a full 5-hour session
@pytest.fixture
def sender(monkeypatch):
    """A Sender on the plan whose requests and waits are recorded instead of made."""
    calls, waits = [], []

    def call(*a, **k):
        calls.append(a)
        if s.refuse:
            raise claude_code.CantGoOn(s.refuse.pop(0))
        return {"content": [{"type": "text", "text": "[]"}]}

    monkeypatch.setattr(claude_code, "call", call)
    monkeypatch.setattr(usage, "wait_until", lambda until, why, step=None: waits.append((until, why)))
    s = sending.Sender("generate", "claude-opus-5-5", route="plan", assume_yes=True)
    s.refuse, s.calls, s.waits = [], calls, waits
    return s


def test_a_full_session_stops_the_run_unless_it_is_waited_out(sender):
    reading(five=95, five_reset_in=1800)
    with pytest.raises(SystemExit) as e:
        sender("hello")
    assert "5-hour session is 95% used" in str(e.value) and not sender.calls and not sender.waits
    usage.set_plan_limits(wait_for_reset=True)
    assert sender("hello")["content"]
    (until, why), = sender.waits
    assert abs(until - (time.time() + 1800 + 60)) < 5 and "95% used" in why       # a minute's grace after the reset
    assert len(sender.calls) == 1


def test_the_week_is_never_waited_out(sender):
    usage.set_plan_limits(wait_for_reset=True)
    reading(five=95, seven=93)
    with pytest.raises(SystemExit) as e:
        sender("hello")
    assert "weekly limit is 93% used" in str(e.value) and not sender.waits and not sender.calls


def test_the_plans_own_session_limit_is_waited_out_once_but_a_sign_in_problem_is_not(sender):
    usage.set_plan_limits(wait_for_reset=True)
    reading(five=60)                                     # under 90%, but Claude Code says the limit came first
    sender.refuse = ["You've hit your session limit · resets 3:45pm"]
    assert sender("hello")["content"] and len(sender.waits) == 1 and len(sender.calls) == 2
    sender.refuse = ["Claude Code isn't signed in: run /login"]
    with pytest.raises(SystemExit):
        sender("hello")
    assert len(sender.waits) == 1


def test_without_a_reset_time_there_is_nothing_to_wait_for(sender):
    usage.set_plan_limits(wait_for_reset=True)
    reading(five=95, five_reset_in=-60)                  # the window has reset since: the reading says nothing now
    assert sender("hello")["content"] and not sender.waits


def test_the_wait_itself_ends_on_time_and_tells_the_app(capsys, monkeypatch):
    events = []
    monkeypatch.setattr(usage.time, "sleep", lambda s: None)
    ticks = [1000.0, 1000.0, 1030.0, 1061.0]                # then it stays at the last
    monkeypatch.setattr(usage.time, "time", lambda: ticks.pop(0) if len(ticks) > 1 else ticks[0])
    import prompts
    monkeypatch.setattr(prompts, "event", lambda kind, **f: events.append((kind, f)))
    usage.wait_until(1060, "Your plan's 5-hour session is 95% used.", step="generate")
    assert "Waiting until" in capsys.readouterr().out
    assert [f["until"] for _, f in events] == [1060, None]
    usage.wait_until(900, "already past")                # nothing to wait for
    assert len(events) == 2


# ---------------------------------------------------------------- the options
def test_the_options_come_from_settings_and_pass_on_to_each_step():
    settings.save({"week_stop_at": 75, "wait_for_reset": True})
    opts = cli_common.settle_route(argparse.Namespace(route=None, api_fallback=None, week_stop_at=None,
                                                      wait_for_reset=None, api_url=None))
    assert opts.week_stop_at == 75 and opts.wait_for_reset is True
    assert usage._limits == {"week_stop_at": 75, "wait_for_reset": True}
    args = cli_common.claude_args(opts)
    assert args[args.index("--week-stop-at") + 1] == "75" and "--wait-for-reset" in args
    opts.wait_for_reset = False
    assert "--no-wait-for-reset" in cli_common.claude_args(opts)


@pytest.mark.parametrize("text, ok", [("90", 90), ("90%", 90), ("100", 100), ("0", None), ("101", None), ("x", None)])
def test_week_stop_at_takes_a_percentage(text, ok):
    if ok is None:
        with pytest.raises(argparse.ArgumentTypeError):
            cli_common.week_arg(text)
    else:
        assert cli_common.week_arg(text) == ok


def test_the_app_passes_the_run_forms_choices_on():
    assert app.limits_args({}) == []
    assert app.limits_args({"week_stop_at": "80", "wait_for_reset": True, "pace_minutes": "60"}) == [
        "--week-stop-at", "80", "--wait-for-reset", "--pace", "60"]
    assert app.limits_args({"week_stop_at": "", "wait_for_reset": False, "pace_minutes": ""}) == ["--no-wait-for-reset"]
    with pytest.raises(app.BadRequest):
        app.limits_args({"week_stop_at": "150"})
    with pytest.raises(app.BadRequest):
        app.limits_args({"pace_minutes": "-5"})


# ---------------------------------------------------------------- --pace
def test_pace_waits_only_between_videos_that_need_claude(monkeypatch):
    state = {"done": False, "rebuild": False}
    monkeypatch.setattr(context_notes, "inspect", lambda v, opts: dict(state))
    waits = []
    monkeypatch.setattr(usage, "wait_until", lambda until, why, step=None: waits.append(until))
    opts = SimpleNamespace(pace=60)
    video = SimpleNamespace(name="ep.mkv")
    first = context_notes.pace(video, opts, None)
    assert not waits and abs(first - time.time()) < 5             # the first video starts at once
    second = context_notes.pace(video, opts, first)
    assert waits == [first + 3600] and second >= first
    state["done"] = True
    assert context_notes.pace(video, opts, second) == second and len(waits) == 1    # a finished one isn't waited for
    assert context_notes.pace(video, SimpleNamespace(pace=0), second) == second


def test_a_folder_run_ends_when_the_plans_limit_stops_a_video():
    opts = SimpleNamespace(route="plan", api_fallback=0.0, wait_for_reset=False)
    reading(five=10, seven=95)
    assert "weekly limit" in context_notes.plan_stopped(opts)
    reading(five=95, seven=20)
    assert "5-hour session" in context_notes.plan_stopped(opts)
    opts.wait_for_reset = True                            # each step waits it out instead
    assert context_notes.plan_stopped(opts) is None
    opts.api_fallback = 5.0                               # the steps carry on with API credits
    reading(five=10, seven=95)
    assert context_notes.plan_stopped(opts) is None
