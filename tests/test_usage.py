"""usage.py: the cost ledger, the credit estimate, the plan's session reading, and how they show in a run and the app."""
import json
import subprocess
import sys
import time

import pytest
from conftest import ROOT, make_srt, message, run_cli
from test_app import call, server  # noqa: F401  (the app fixture)
from test_generate_notes import notes_for_each_part
from test_progress_and_cancel import LONG

import generate_notes as gn
import prompts
import usage

MODEL = "claude-sonnet-5-5"


def tick():
    time.sleep(0.01)          # stamps are to the millisecond: keep "set" and "spent" in a clear order


def events_in(text):
    return [json.loads(line[len(prompts.PREFIX):]) for line in text.splitlines() if line.startswith(prompts.PREFIX)]


# ---------------------------------------------------------------- the credit estimate
def test_the_estimate_counts_down_from_what_you_set():
    assert usage.balance() is None
    usage.set_balance(20, low=3)
    tick()
    usage.begin("Film", "generate")
    usage.record(MODEL, 1000, 200, 0.25)
    usage.record(MODEL, 1000, 200, 0.25)
    b = usage.balance()
    assert b["balance_usd"] == 19.5 and b["spent_usd"] == 0.5 and b["low_usd"] == 3 and not b["low"]
    usage.record(MODEL, 1000, 200, 17.0)
    assert usage.balance()["low"]


def test_spending_before_the_balance_was_set_is_not_taken_off_again():
    usage.begin("Film", "generate")
    usage.record(MODEL, 1, 1, 5.0)
    tick()
    usage.set_balance(10)
    assert usage.balance()["balance_usd"] == 10 and usage.balance()["low_usd"] == usage.LOW_DEFAULT


def test_a_request_with_no_known_price_is_counted_but_not_priced():
    usage.set_balance(10)
    tick()
    usage.begin("Film", "refine")
    usage.record("some-new-model", 500, 50, None)
    b = usage.balance()
    assert b["balance_usd"] == 10 and b["unpriced"] == 1


def test_topping_up_adds_to_the_estimate_and_keeps_the_warning_level():
    usage.set_balance(10, low=4)
    tick()
    usage.begin("Film", "generate")
    usage.record(MODEL, 1, 1, 3.0)
    tick()
    b = usage.add_credit(5)
    assert b["balance_usd"] == 12 and b["low_usd"] == 4
    with pytest.raises(ValueError):
        usage.add_credit(0)


def test_adding_credit_needs_a_balance_first():
    with pytest.raises(ValueError, match="No balance is set"):
        usage.add_credit(5)


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), True, "5"])
def test_a_balance_must_be_a_real_amount(bad):
    with pytest.raises(ValueError):
        usage.set_balance(bad)
    assert usage.credit() is None


def test_the_api_saying_credit_is_out_beats_the_estimate_but_only_when_tracking():
    assert usage.mark_empty() is False and usage.credit() is None            # nothing tracked: nothing invented
    usage.set_balance(8)
    assert usage.mark_empty() is True and usage.balance()["balance_usd"] == 0


def test_a_damaged_ledger_line_is_skipped():
    usage.set_balance(10)
    tick()
    usage.begin("Film", "generate")
    usage.record(MODEL, 1, 1, 1.0)
    with open(usage.ledger_path(), "a", encoding="utf-8") as f:
        f.write('{"t": "2099-01-01T00:00:00.000Z", "usd": 2\n')          # cut off mid-line, as a killed run could
    tick()
    usage.record(MODEL, 1, 1, 1.0)
    assert usage.balance()["balance_usd"] == 8


def test_dollars_are_read_the_way_people_write_them():
    assert usage.parse_dollars("$1,200.50") == 1200.5 and usage.parse_dollars(" 3 ") == 3
    for bad in ("", None, "abc", "nan", "inf"):
        with pytest.raises(ValueError):
            usage.parse_dollars(bad)


def test_a_film_goes_by_its_notes_file_name():
    assert usage.film_name("/m/context-notes/Amelie.mkv/notes-Amelie.mkv.json") == "Amelie.mkv"
    assert usage.film_name("n.json") == "n"


def test_money_is_shown_in_cents():
    assert usage.money(0) == "$0.00" and usage.money(0.004) == "<$0.01" and usage.money(1234.5) == "$1,234.50"
    assert usage.money(None) == "?"


# ---------------------------------------------------------------- what's printed during a run
def test_report_prints_a_line_and_sends_an_event(capsys, monkeypatch):
    monkeypatch.setenv(prompts.ENV, "json")
    usage.set_balance(10)
    tick()
    usage.begin("Film", "generate")
    assert usage.report() is None                                            # nothing recorded yet: silent
    usage.record(MODEL, 2000, 300, 0.007)
    tick()
    usage.record(MODEL, 2000, 300, 0.007)
    out = capsys.readouterr().out
    assert out == ""                                                         # recording never prints
    bal = usage.report()
    out = capsys.readouterr().out
    line = out.splitlines()[0]
    assert line == "    $0.01 (run $0.01) · about $9.99 left"                  # cents: 0.007 and 0.014 show as $0.01
    assert bal["balance_usd"] == 9.986
    (ev,) = events_in(out)
    assert ev["type"] == "usage" and ev["step"] == "generate" and ev["film"] == "Film"
    assert ev["request"] == {"input_tokens": 2000, "output_tokens": 300, "cost_usd": 0.007}
    assert ev["run"]["requests"] == 2 and ev["run"]["cost_usd"] == 0.014 and ev["balance_usd"] == 9.986 and not ev["low"]
    assert usage.report() is None                                            # once per request


def test_report_warns_when_the_credit_is_low(capsys):
    usage.set_balance(2.01)
    tick()
    usage.begin("Film", "refine")
    usage.record(MODEL, 1, 1, 0.5)
    usage.report()
    assert "under your warning level of $2.00" in capsys.readouterr().out


def test_report_without_a_balance_still_gives_the_cost_and_names_an_unknown_price(capsys):
    usage.begin("Film", "generate")
    usage.record(MODEL, 1, 1, 0.5)
    usage.report()
    assert capsys.readouterr().out.strip() == "$0.50"
    usage.record("some-new-model", 1500, 90, None)
    usage.report()
    assert "1,500 tokens in, 90 out (the price of this model isn't known)" in capsys.readouterr().out


def test_the_film_total_shows_once_it_adds_something(capsys):
    usage.begin("Film", "generate")
    usage.record(MODEL, 1, 1, 0.25)
    usage.finish()
    assert capsys.readouterr().out == ""                       # same as the run, no balance: nothing to add
    usage.begin("Film", "refine")
    usage.record(MODEL, 1, 1, 0.5)
    usage.finish()
    assert "This film has cost $0.75 so far (notes $0.25, frames $0.50)." in capsys.readouterr().out


def test_the_plan_line_warns_when_a_run_may_outspend_the_credit(capsys):
    assert usage.plan_note(1.0) is None and capsys.readouterr().out == ""
    usage.set_balance(0.5)
    assert usage.plan_note(1.0)["balance_usd"] == 0.5
    out = capsys.readouterr().out
    assert "about $0.50 left" in out and "may stop part-way" in out
    usage.plan_note(0.1)
    assert "may stop" not in capsys.readouterr().out


# ---------------------------------------------------------------- the API calls feed it
def test_every_finished_request_is_recorded_with_its_cost(api, api_key_file, tmp_path):
    api.responder = notes_for_each_part
    srt = make_srt(tmp_path / "ep.srt", n=30, text=LONG)
    gn.generate(srt, tmp_path / "notes-Some.Film.json", assume_yes=True, api_url=api.url)
    ents = usage.entries()
    assert len(ents) == len(api.calls) > 1
    assert all(e["film"] == "Some.Film" and e["step"] == "generate" and e["model"] == MODEL for e in ents)
    assert all(e["in"] == 2000 and e["out"] == 300 and e["usd"] == pytest.approx(0.007) for e in ents)


def test_a_failed_request_costs_nothing_and_credit_out_is_noticed(api):
    usage.set_balance(5)
    tick()
    api.responder = lambda n, body, h: (400, {"error": {"message": "Your credit balance is too low to access the API."}})
    with pytest.raises(SystemExit) as e:
        gn.call_api("k", MODEL, "s", "u", api.url)
    assert "credit balance is too low" in str(e.value) and "platform.claude.com/settings/billing" in str(e.value)
    assert usage.entries() == [] and usage.balance()["balance_usd"] == 0


def test_a_reply_without_usage_does_not_break_the_run(api):
    api.responder = lambda n, body, h: (200, {"type": "message", "content": [], "usage": None})
    assert gn.call_api("k", MODEL, "s", "u", api.url)["type"] == "message"
    assert usage.entries()[0]["in"] == 0


def test_a_whole_cli_run_shows_the_cost_and_sends_events(tmp_path, api, api_key_file, home, usage_dir):
    srt = make_srt(tmp_path / "ep.srt", n=24, text=LONG)
    api.responder = notes_for_each_part
    usage.set_balance(10)
    tick()
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home,
                env_extra={prompts.ENV: "json", "PYTHONUNBUFFERED": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    evs = events_in(r.stdout)
    spent = [e for e in evs if e["type"] == "usage"]
    assert len(spent) == len(api.calls) > 1
    assert [e["run"]["requests"] for e in spent] == list(range(1, len(spent) + 1))
    assert spent[-1]["balance_usd"] == pytest.approx(10 - 0.007 * len(spent))
    est = next(e for e in evs if e["type"] == "estimate")
    assert est["balance_usd"] == 10
    lines = r.stdout.splitlines()
    assert any(" left" in ln and ln.startswith("    $0.01") for ln in lines)
    assert any(ln.startswith("Tracked credit: about $10.00 left") for ln in lines)
    for event_line in (ln for ln in lines if ln.startswith(prompts.PREFIX)):       # an event always starts its own line
        assert event_line.endswith("}")
    assert "sk-ant" not in (usage_dir / "usage.jsonl").read_text()


def test_a_cli_run_with_no_balance_set_prints_no_tracked_credit_line(tmp_path, api, api_key_file, home):
    srt = make_srt(tmp_path / "ep.srt", n=6)
    api.responder = lambda n, body, h: (200, message("[]"))
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "Tracked credit" not in r.stdout and "@context-notes" not in r.stdout


# ---------------------------------------------------------------- the plan's session
RESET = 4_000_000_000        # far off, so a window is "still open"


def payload(five=42.3, seven=18.0, reset=RESET):
    return {"model": {"display_name": "Opus 4.5"},
            "rate_limits": {"five_hour": {"used_percentage": five, "resets_at": reset},
                            "seven_day": {"used_percentage": seven, "resets_at": reset + 1000}}}


def test_the_session_is_saved_and_read_back():
    assert usage.session() is None and "No session reading yet" in usage.session_line()
    assert usage.write_session(payload()) is True
    s = usage.session()
    assert s["five_hour"]["percent"] == 42.3 and s["seven_day"]["percent"] == 18.0 and s["age_s"] < 5
    line = usage.session_line()
    assert line.startswith("5-hour session: 42% used, resets ") and "7-day: 18% used" in line


def test_a_window_that_has_reset_since_is_not_reported_as_still_used():
    usage.write_session(payload(five=63, reset=int(time.time()) - 60))
    w = usage.session()["five_hour"]
    assert w["reset_since"] and w["percent"] is None and w["last_percent"] == 63
    assert "was 63% when last seen, and has reset since" in usage.session_line()


def test_an_old_reading_says_how_old():
    usage.write_session(payload())
    assert "Last reading 1 h ago" in usage.session_line(now=time.time() + 3600)
    assert "Last reading" not in usage.session_line()


@pytest.mark.parametrize("bad", [{}, {"rate_limits": None}, {"rate_limits": {}}, {"rate_limits": {"five_hour": {}}},
                                 {"rate_limits": {"five_hour": {"used_percentage": "lots"}}}, "text", None])
def test_no_readings_means_nothing_is_saved(bad):
    assert usage.write_session(bad) is False and usage.session() is None


def test_one_window_on_its_own_is_fine():
    assert usage.write_session({"rate_limits": {"five_hour": {"used_percentage": 10, "resets_at": RESET}}})
    s = usage.session()
    assert "five_hour" in s and "seven_day" not in s


def test_a_garbled_session_file_is_ignored():
    usage.session_path().parent.mkdir(parents=True, exist_ok=True)
    usage.session_path().write_text("{nope")
    assert usage.session() is None


def run_statusline(stdin):
    return subprocess.run([sys.executable, str(ROOT / ".claude" / "statusline.py")], input=stdin, capture_output=True,
                          encoding="utf-8", timeout=60)


def test_the_status_line_shows_both_meters_and_saves_the_reading():
    usage.set_balance(20)
    r = run_statusline(json.dumps(payload()))
    assert r.returncode == 0 and r.stderr == ""
    shown = r.stdout
    assert "[Opus 4.5]" in shown and "5h 42%" in shown and "7d 18%" in shown and "API ~$20.00" in shown
    assert usage.session()["five_hour"]["percent"] == 42.3          # the subprocess wrote into the same folder


def test_the_status_line_survives_anything():
    for stdin in ("", "not json", "[]", '{"model": 5}', json.dumps({"rate_limits": {"five_hour": 7}})):
        r = run_statusline(stdin)
        assert r.returncode == 0 and r.stderr == "", (stdin, r.stderr)


def test_the_status_line_does_not_show_an_old_reading_when_there_is_no_new_one():
    usage.write_session(payload())
    assert "5h" not in run_statusline(json.dumps({"model": {"display_name": "Sonnet"}})).stdout


# ---------------------------------------------------------------- the week
def test_readings_of_one_window_count_as_one_session_with_its_highest_use():
    now = int(time.time())
    for pct, jitter in ((30, 0), (60, 2), (85, -3)):                     # the end of a window wobbles by seconds
        usage.write_session(payload(five=pct, reset=now + 9000 + jitter))
    assert usage.session()["week"] == {"sessions": 1, "busiest": 85.0}
    usage.write_session(payload(five=10, reset=now + 9000 + 5 * 3600))   # the next window
    assert usage.session()["week"] == {"sessions": 2, "busiest": 85.0}


def test_only_the_last_seven_days_of_sessions_count():
    now = time.time()
    usage.write_session(payload(five=70, reset=int(now) - 8 * 24 * 3600))
    usage.write_session(payload(five=20, reset=int(now) + 3600))
    assert usage.sessions_this_week(now) == {"sessions": 1, "busiest": 20.0}
    assert usage.sessions_this_week(now + 9 * 24 * 3600) is None


def test_the_week_line_says_what_is_known():
    assert usage.week_line() is None
    usage.write_session(payload(seven=22))
    assert usage.week_line() == ("This week: 22% of the plan's weekly limit used; "
                                 "1 session seen here (the busiest reached 42%).")


def test_api_spending_over_the_last_seven_days():
    usage.begin("Film", "generate")
    usage.record(MODEL, 1, 1, 0.25)
    usage.record(MODEL, 1, 1, 0.5)
    old = {"t": "2020-01-01T00:00:00.000Z", "film": "Old", "step": "generate", "model": MODEL, "in": 1, "out": 1, "usd": 9.0}
    with open(usage.ledger_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(old) + "\n")
    sp = usage.summary()["spent"]
    assert sp["week"] == 0.75 and sp["week_requests"] == 2 and sp["all"] == 9.75


# ---------------------------------------------------------------- the command line
def test_the_command_line_sets_shows_and_adds(usage_dir):
    r = run_cli("usage.py", "--set-balance", "25", "--low", "3")
    assert r.returncode == 0 and "about $25.00 left; warns below $3.00" in r.stdout
    assert run_cli("usage.py", "--add-credit", "$5").stdout.startswith("Saved. About $30.00 left")
    shown = run_cli("usage.py").stdout
    assert "About $30.00 left" in shown and "Claude plan session" in shown
    data = json.loads(run_cli("usage.py", "--json").stdout)
    assert data["balance"]["balance_usd"] == 30 and data["films"] == [] and data["dir"] == str(usage_dir)
    assert "No session reading yet" in run_cli("usage.py", "--session").stdout


def test_the_command_line_says_what_is_wrong():
    for args in (["--set-balance", "lots"], ["--add-credit", "5"], ["--low", "3"]):
        r = run_cli("usage.py", *args)
        assert r.returncode != 0 and r.stderr.strip() and "Traceback" not in r.stderr, args


def test_the_summary_lists_films_with_their_steps():
    for film, step, usd in (("A", "generate", 0.1), ("A", "refine", 0.4), ("B", "generate", 0.2)):
        usage.begin(film, step)
        usage.record(MODEL, 1, 1, usd)
        tick()
    s = usage.summary()
    assert [f["film"] for f in s["films"]] == ["B", "A"]                       # latest first
    a = s["films"][1]
    assert a["cost_usd"] == 0.5 and a["steps"] == {"generate": 0.1, "refine": 0.4}
    assert s["spent"]["all"] == 0.7 and s["spent"]["today"] == 0.7 and s["spent"]["month"] == 0.7


# ---------------------------------------------------------------- the app
def test_the_app_reports_usage_and_takes_a_balance(server, usage_dir):      # noqa: F811
    status, u = call(server, "/api/usage")
    assert status == 200 and u["balance"] is None and u["session"] is None
    assert call(server, "/api/info")[1]["usage"]["balance"] is None
    assert call(server, "/api/usage", key=False)[0] == 403
    assert call(server, "/api/credit", {"balance": "5"}, key=False)[0] == 403
    status, r = call(server, "/api/credit", {"balance": "$12.50", "low": "1"})
    assert status == 200 and r["ok"] and r["usage"]["balance"]["balance_usd"] == 12.5 and r["usage"]["balance"]["low_usd"] == 1
    assert (usage_dir / "credit.json").exists()
    for bad in ({}, {"balance": ""}, {"balance": "lots"}, {"balance": "-3"}, {"balance": "5", "low": "x"}):
        status, r = call(server, "/api/credit", bad)
        assert status == 200 and r["ok"] is False and r["message"], bad
    assert call(server, "/api/usage")[1]["balance"]["balance_usd"] == 12.5          # a bad entry changed nothing


def test_the_page_has_what_the_app_fills_in():
    page = (ROOT / "gui" / "index.html").read_text(encoding="utf-8")
    for needle in ('id="apiMeter"', 'id="sessionMeter"', 'id="creditInput"', 'id="saveCreditBtn"', 'id="weekList"',
                   '"/api/usage"', '"/api/credit"', 'ev.type === "usage"', "creditText("):
        assert needle in page, needle
