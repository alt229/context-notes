#!/usr/bin/env python3
"""
usage.py - what the API calls cost, how much credit is probably left, and how much of your Claude plan's session is used.

    python3 usage.py                          # the summary: credit left, spending, the latest films, the session
    python3 usage.py --films 20               # more films
    python3 usage.py --session                # one line about your plan's session (the 5-hour window)
    python3 usage.py --set-balance 25.00      # tell it what Billing in the Anthropic console shows right now
    python3 usage.py --set-balance 25 --low 3 # ... and warn below $3 (the default is $2)
    python3 usage.py --add-credit 20          # you topped up by $20
    python3 usage.py --json                   # the summary for another program
    python3 usage.py --session --stop-at 90   # as --session, but exit with code 3 when the session is 90%+ used
    python3 usage.py --parts-estimate 12      # how much of a session 12 /notes parts should take, from earlier ones
    python3 usage.py --note-parts start       # (/notes does these two around each part to learn that)
    python3 usage.py --note-parts end --count 2 --film "Amelie"

Two meters, because they work differently:

1. API credit. Anthropic has no way to ask "how much credit is left?", so this keeps a ledger of what *this tool's*
   requests cost (usage.jsonl) and subtracts it from the balance you last told it (credit.json). That makes the figure
   an estimate: spending that didn't come from here (other tools on the same key) isn't in it. Type the console's
   figure in again whenever you top up, or the estimate drifts. If the API itself says the credit has run out, the
   estimate is set to $0 on the spot.
2. The Claude plan's session (Pro/Max: the 5-hour and 7-day windows). The API doesn't see this at all. Claude Code
   tells its status line, and .claude/statusline.py saves what it hears in session.json; this reads it back. So it
   only moves while Claude Code is open in this project (the notes written with /notes use the plan).

It also keeps the week in view: API spending over the last 7 days, the plan's 7-day figure, and how many 5-hour
sessions the status line has seen this week (and how full the busiest got). Sessions used somewhere the status line
didn't run (claude.ai chat, another computer) are in the plan's percentages but not in that count.

Everything lives in ~/.config/context-notes/ (or $XDG_CONFIG_HOME/context-notes/), next to the API key. Standard
library only.
"""
import argparse
import datetime
import json
import math
import os
import sys
import time
from pathlib import Path

ENV_DIR = "CONTEXT_NOTES_USAGE_DIR"          # moves all three files (the tests use it)
LOW_DEFAULT = 2.0                            # warn below this many dollars, unless told otherwise
STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"              # UTC, to the millisecond, so stamps compare as text
STALE_S = 15 * 60                            # a session reading older than this is called out


# ---------------------------------------------------------------- where things live
def data_dir():
    override = os.environ.get(ENV_DIR, "").strip()
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "context-notes"


def ledger_path():
    return data_dir() / "usage.jsonl"


def credit_path():
    return data_dir() / "credit.json"


def session_path():
    return data_dir() / "session.json"


def history_path():
    return data_dir() / "sessions.json"


def now_stamp():
    n = datetime.datetime.now(datetime.timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def parse_stamp(text):
    try:
        return datetime.datetime.strptime(text, STAMP).replace(tzinfo=datetime.timezone.utc)
    except (TypeError, ValueError):
        return None


def _write(path, text):
    """Write a whole file at once (make_ass.write_text_safely), so a Ctrl-C can't leave half of it. Imported late:
    the status line only needs make_ass when it has something to write."""
    import make_ass
    make_ass.write_text_safely(path, text)


def _append(path, text):
    """Add one line to the ledger. One write() on an O_APPEND file, so a stop mid-run can't tear a line in half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0), 0o600)
    try:
        os.write(fd, (text + "\n").encode("utf-8"))
    finally:
        os.close(fd)


# ---------------------------------------------------------------- recording
_run = {"film": None, "step": None, "requests": 0, "tin": 0, "tout": 0, "usd": 0.0, "unpriced": 0, "last": None,
        "per_request": None, "carry_on": False}
_warned = []


def begin(film=None, step=None, per_request=None):
    """A paid step is starting: label what follows (which film, which step) and zero this run's totals.
    `per_request`: the plan's estimate for one request, used until real ones show what they cost."""
    _run.update(film=film, step=step, requests=0, tin=0, tout=0, usd=0.0, unpriced=0, last=None,
                per_request=per_request, carry_on=False)


def next_cost():
    """What the next request is expected to cost: the average so far in this run, else the plan's estimate, else None."""
    priced = _run["requests"] - _run["unpriced"]
    if priced > 0:
        return _run["usd"] / priced
    return _run["per_request"]


def film_name(notes_path):
    """The name a film goes by in the ledger: its notes file without 'notes-' and '.json'."""
    name = Path(notes_path).name
    if name.startswith("notes-"):
        name = name[len("notes-"):]
    return name[:-len(".json")] if name.lower().endswith(".json") else name


def record(model, tin, tout, usd):
    """One finished request: into the ledger and this run's totals. `usd` is None when the model's price isn't known.
    Prints nothing, because a progress line may still be open (report() speaks, after the line is finished).
    Never raises: bookkeeping must not stop a paid run."""
    _run["requests"] += 1
    _run["tin"] += tin
    _run["tout"] += tout
    if usd is None:
        _run["unpriced"] += 1
    else:
        _run["usd"] += usd
    _run["last"] = {"model": model, "input_tokens": tin, "output_tokens": tout, "cost_usd": usd}
    entry = {"t": now_stamp(), "film": _run["film"], "step": _run["step"], "model": model, "in": tin, "out": tout,
             "usd": None if usd is None else round(usd, 6)}
    try:
        _append(ledger_path(), json.dumps(entry, ensure_ascii=False))
    except OSError as e:
        if not _warned:
            _warned.append(True)
            print(f"\n  ! Couldn't record the cost in {ledger_path()}: {e.strerror or e}", file=sys.stderr, flush=True)


def entries():
    """Every readable line of the ledger, oldest first. A damaged line is skipped, not fatal."""
    try:
        text = ledger_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("t"), str):
            out.append(e)
    return out


# ---------------------------------------------------------------- the credit estimate
def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def parse_dollars(text):
    """'25', '$25.50', '1,200' -> a float. ValueError (with words for a person) for anything else."""
    if text is None or not str(text).strip():
        raise ValueError("Type an amount in dollars first.")
    try:
        value = float(str(text).replace("$", "").replace(",", "").strip())
    except ValueError:
        raise ValueError(f"'{text}' isn't an amount in dollars.") from None
    if not math.isfinite(value):
        raise ValueError(f"'{text}' isn't an amount in dollars.")
    return value


def credit():
    """What you last told it: {balance_usd, as_of, [low_usd]}, or None when nothing is set."""
    try:
        c = json.loads(credit_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(c, dict) or not _number(c.get("balance_usd")) or not isinstance(c.get("as_of"), str):
        return None
    return c


def balance(ents=None):
    """The estimate: the balance you set, less what the ledger recorded since. None when no balance is set."""
    c = credit()
    if c is None:
        return None
    spent, unpriced = 0.0, 0
    for e in entries() if ents is None else ents:
        if e["t"] > c["as_of"]:
            if _number(e.get("usd")):
                spent += e["usd"]
            else:
                unpriced += 1
    low = c["low_usd"] if _number(c.get("low_usd")) else LOW_DEFAULT
    left = c["balance_usd"] - spent
    return {"balance_usd": round(left, 4), "set_usd": c["balance_usd"], "as_of": c["as_of"],
            "spent_usd": round(spent, 4), "low_usd": low, "low": left < low, "unpriced": unpriced}


def set_balance(usd, low=None):
    """Remember what the console shows now. `low`: the warning level (kept from before when not given)."""
    if not _number(usd) or usd < 0:
        raise ValueError("The balance must be a number of dollars, 0 or more.")
    if low is not None and (not _number(low) or low < 0):
        raise ValueError("The warning level must be a number of dollars, 0 or more.")
    old = credit() or {}
    data = {"balance_usd": round(float(usd), 4), "as_of": now_stamp()}
    keep = low if low is not None else old.get("low_usd")
    if _number(keep):
        data["low_usd"] = round(float(keep), 4)
    _write(credit_path(), json.dumps(data, indent=1) + "\n")
    return balance()


def add_credit(usd):
    """You topped up: the estimate plus `usd`, counted from now."""
    if not _number(usd) or usd <= 0:
        raise ValueError("The amount added must be more than 0.")
    now = balance()
    if now is None:
        raise ValueError("No balance is set yet. Use --set-balance with what the console shows.")
    return set_balance(max(now["balance_usd"], 0.0) + usd)


def mark_empty():
    """The API itself said the credit has run out: that beats any estimate. Only when a balance is being tracked."""
    c = credit()
    if c is None:
        return False
    try:
        set_balance(0.0)
    except (OSError, ValueError):
        return False
    return True


# ---------------------------------------------------------------- the plan's session
def write_session(payload):
    """Claude Code's status line payload in; the 5-hour and 7-day readings saved. False when it had none (an API key,
    or before the first reply)."""
    limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return False
    out = {"seen": time.time()}
    for key in ("five_hour", "seven_day"):
        w = limits.get(key)
        if isinstance(w, dict) and _number(w.get("used_percentage")):
            out[key] = {"used_percentage": float(w["used_percentage"]),
                        "resets_at": w["resets_at"] if _number(w.get("resets_at")) else None}
    if len(out) == 1:
        return False
    _write(session_path(), json.dumps(out, indent=1) + "\n")
    try:
        _note_window(out)
    except (OSError, ValueError):                  # the week's tally is a nicety: never fail the status line over it
        pass
    return True


WINDOW_S = 600                                      # readings of one 5-hour window agree on its end to within this
WEEK_S = 7 * 24 * 3600


def _history():
    try:
        h = json.loads(history_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    wins = h.get("windows") if isinstance(h, dict) else None
    return {k: v for k, v in wins.items() if isinstance(v, dict) and _number(v.get("peak"))} if isinstance(wins, dict) else {}


def _note_window(reading):
    """Keep the highest use seen in each 5-hour window (named by when it ends), for a week and a day."""
    w = reading.get("five_hour")
    if not w or w["resets_at"] is None:
        return
    key = str(int(round(w["resets_at"] / WINDOW_S)) * WINDOW_S)
    wins = _history()
    seen = wins.get(key, {})
    wins[key] = {"peak": max(seen.get("peak", 0.0), w["used_percentage"]), "first_seen": seen.get("first_seen", reading["seen"])}
    cutoff = reading["seen"] - WEEK_S - 24 * 3600
    wins = {k: v for k, v in wins.items() if float(k) > cutoff}
    _write(history_path(), json.dumps({"windows": wins}, indent=1) + "\n")


def sessions_this_week(now=None):
    """{sessions, busiest}: the 5-hour windows the status line has seen in the last 7 days, and the highest use any of
    them reached. None when it has seen none."""
    now = time.time() if now is None else now
    peaks = [v["peak"] for k, v in _history().items() if now - WEEK_S < float(k)]
    return {"sessions": len(peaks), "busiest": max(peaks)} if peaks else None


def session(now=None):
    """The last readings, with what they mean now: {seen, age_s, five_hour: {percent, resets_at, reset_since,
    last_percent, seconds_left}, seven_day: {...}}. `percent` is None once the window has reset since the reading.
    None when there's no reading at all."""
    try:
        d = json.loads(session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not _number(d.get("seen")):
        return None
    now = time.time() if now is None else now
    out = {"seen": d["seen"], "age_s": max(0, int(now - d["seen"]))}
    for key in ("five_hour", "seven_day"):
        w = d.get(key)
        if not isinstance(w, dict) or not _number(w.get("used_percentage")):
            continue
        at = w.get("resets_at") if _number(w.get("resets_at")) else None
        passed = at is not None and at <= now
        out[key] = {"percent": None if passed else w["used_percentage"], "last_percent": w["used_percentage"],
                    "resets_at": at, "reset_since": passed, "seconds_left": None if at is None or passed else int(at - now)}
    if "five_hour" not in out and "seven_day" not in out:
        return None
    out["week"] = sessions_this_week(now)
    return out


# ---------------------------------------------------------------- what a /notes part costs the session
PAUSE_DEFAULT = 90.0                                # /notes stops starting parts at this much of the 5-hour session


def parts_path():
    return data_dir() / "parts.jsonl"


def pending_path():
    return data_dir() / "parts-pending.json"


def _five():
    s = session()
    w = s.get("five_hour") if s else None
    return w if w and w["percent"] is not None else None


def note_parts_start(say=print):
    """Remember where the session stands, just before one or more /notes parts are written."""
    w = _five()
    if w is None:
        say("No session reading, so these parts won't be measured.")
        return False
    _write(pending_path(), json.dumps({"pct": w["percent"], "resets_at": w["resets_at"], "t": time.time()}) + "\n")
    say(f"Session at {w['percent']:.0f}% before these parts.")
    return True


def note_parts_end(count=1, film=None, say=print):
    """After the parts: how far the session moved. Recorded only when it's a fair measure (same window, and it moved)."""
    try:
        start = json.loads(pending_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        say("The start of these parts wasn't noted, so they aren't measured.")
        return None
    try:
        pending_path().unlink()
    except OSError:
        pass
    w = _five()
    if w is None:
        say("No session reading now, so these parts aren't measured.")
        return None
    same = (w["resets_at"] is None or start.get("resets_at") is None
            or abs(w["resets_at"] - start["resets_at"]) < WINDOW_S)
    delta = w["percent"] - start["pct"]
    if not same or delta < 0:
        say("The session reset in between, so these parts aren't measured.")
        return None
    if delta == 0:
        say("The session figure hasn't moved yet (the status line updates after a reply), so these parts aren't measured.")
        return None
    count = max(int(count), 1)
    entry = {"t": now_stamp(), "film": film, "parts": count, "delta_pct": round(delta, 2), "per_part": round(delta / count, 3)}
    try:
        _append(parts_path(), json.dumps(entry, ensure_ascii=False))
    except OSError as e:
        say(f"Couldn't record it in {parts_path()}: {e.strerror or e}")
        return None
    say(f"Those {count} {'part' if count == 1 else 'parts'} took about {delta:.1f}% of the session "
        f"({entry['per_part']:.1f}% a part).")
    return entry


def parts_measured():
    try:
        text = parts_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and _number(e.get("per_part")) and e["per_part"] > 0:
            out.append(e)
    return out[-40:]


def parts_estimate(n, stop_at=PAUSE_DEFAULT):
    """A few lines: how much of a session `n` parts should take, from the parts measured before."""
    seen = sorted(e["per_part"] for e in parts_measured())
    if not seen:
        return ["No earlier parts have been measured yet, so there's no estimate. This film's parts start the measurement."]
    mid = seen[len(seen) // 2] if len(seen) % 2 else (seen[len(seen) // 2 - 1] + seen[len(seen) // 2]) / 2
    lines = [f"Earlier parts ({len(seen)} measured) took about {mid:.1f}% of a session each (from {seen[0]:.1f}% to "
             f"{seen[-1]:.1f}%). {n} parts is roughly {n * mid:.0f}% of a session."]
    w = _five()
    if w is not None:
        fit = max(0, int((stop_at - w["percent"]) // mid))
        when = f", which resets {clock(w['resets_at'])}" if w["resets_at"] else ""
        if fit >= n:
            lines.append(f"The session is {w['percent']:.0f}% used now, so all {n} should fit before {stop_at:.0f}%.")
        else:
            lines.append(f"The session is {w['percent']:.0f}% used now, so about {fit} should fit before {stop_at:.0f}%; "
                         f"then it pauses until the session resets{when}.")
    return lines


# ---------------------------------------------------------------- words
def money(usd):
    if usd is None:
        return "?"
    if 0 < usd < 0.005:
        return "<$0.01"
    return f"${usd:,.2f}"


def clock(epoch, with_day=False):
    t = datetime.datetime.fromtimestamp(epoch)
    text = t.strftime("%I:%M %p").lstrip("0")
    return f"{t.strftime('%a')} {text}" if with_day else text


def _span(seconds):
    m = int(round(seconds / 60))
    if m < 60:
        return f"{max(m, 1)} min"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m:02d} min" if m else f"{h} h"
    return f"{h // 24} days"


def session_line(s=None, now=None):
    """One sentence about the plan's session, for a person or for Claude to repeat."""
    s = session(now) if s is None else s
    if s is None:
        return ("No session reading yet. Claude Code's status line records one while you work in this project "
                "(see the README, 'Usage').")
    parts = []
    for key, name, day in (("five_hour", "5-hour session", False), ("seven_day", "7-day", True)):
        w = s.get(key)
        if w is None:
            continue
        if w["reset_since"]:
            parts.append(f"{name}: was {w['last_percent']:.0f}% when last seen, and has reset since "
                         f"({clock(w['resets_at'], day)}), so it's probably lower now")
        else:
            when = f", resets {clock(w['resets_at'], day)} (in {_span(w['seconds_left'])})" if w["resets_at"] else ""
            parts.append(f"{name}: {w['percent']:.0f}% used{when}")
    line = "; ".join(parts) + "."
    if s["age_s"] > STALE_S:
        line += f" (Last reading {_span(s['age_s'])} ago.)"
    return line


def week_line(s=None):
    """One sentence about the plan's week: the 7-day figure and the sessions seen, or None when there's nothing to say."""
    s = session() if s is None else s
    if not s:
        return None
    w = s.get("seven_day")
    parts = []
    if w and not w["reset_since"]:
        parts.append(f"{w['percent']:.0f}% of the plan's weekly limit used")
    if s.get("week"):
        n = s["week"]["sessions"]
        parts.append(f"{n} {'session' if n == 1 else 'sessions'} seen here (the busiest reached {s['week']['busiest']:.0f}%)")
    return ("This week: " + "; ".join(parts) + ".") if parts else None


# ---------------------------------------------------------------- stopping at the credit
def guard(assume_yes=False):
    """Call before each request. Returns None to go on, or a one-line message to stop with.

    With a balance set and the next request expected to cost more than what's left, ask whether to carry on (the
    estimate can be out of date: credit added and not mentioned). Asked once per run. With --yes, or nobody to ask, the
    answer is no, because the safe default for anything that spends money is no."""
    if _run["carry_on"]:
        return None
    bal, cost = balance(), next_cost()
    if bal is None or cost is None or bal["balance_usd"] >= cost:
        return None
    import prompts
    left = money(max(bal["balance_usd"], 0))
    stop = (f"Stopped before the next request: about {left} of credit is left and the next one is expected to cost about "
            f"{money(cost)}. Add credit (python3 usage.py --add-credit 20, or Settings in the app), then run the same "
            f"command again: what was written is kept, and only the rest is sent.")
    if assume_yes or not prompts.interactive():
        return stop
    if prompts.confirm(f"The credit estimate says about {left} is left, and the next request is expected to cost about "
                       f"{money(cost)}. Carry on anyway? (The estimate only counts what this tool has spent. If you've "
                       f"added credit since, it's fine to carry on; then update the figure in Settings, or with "
                       f"python3 usage.py --add-credit 20.)", id="credit.continue"):
        _run["carry_on"] = True
        return None
    return stop


# ---------------------------------------------------------------- what's printed while a run goes on
def _film_cost(film, ents):
    if not film:
        return None
    return sum(e["usd"] for e in ents if e.get("film") == film and _number(e.get("usd")))


def plan_note(cost_usd, say=print):
    """After the 'Plan:' line: what the credit stands at, and a warning when this run may outspend it. Prints nothing
    when no balance is set. Returns the balance estimate (or None), for the estimate event."""
    bal = balance()
    if bal is None:
        return None
    say(f"Tracked credit: about {money(max(bal['balance_usd'], 0))} left (an estimate; usage.py has the details).")
    if cost_usd is not None and cost_usd > bal["balance_usd"]:
        say(f"  ! This run is estimated at {money(cost_usd)}, more than the credit left. It may stop part-way; "
            f"add credit and rerun the same command to pick up where it left off.")
    return bal


def report(say=print):
    """Call when the line for a request is finished: one line of cost, and a `usage` event for a GUI. Does nothing
    when no request has been recorded since the last call (a stub in a test, a cached bench run)."""
    last = _run["last"]
    if last is None:
        return None
    _run["last"] = None
    import prompts
    ents = entries()
    bal = balance(ents)
    film_usd = _film_cost(_run["film"], ents)
    if last["cost_usd"] is None:
        text = f"{last['input_tokens']:,} tokens in, {last['output_tokens']:,} out (the price of this model isn't known)"
    else:
        text = money(last["cost_usd"])
        extra = []
        if _run["requests"] > 1:
            extra.append(f"run {money(_run['usd'])}")
        if film_usd is not None and abs(film_usd - _run["usd"]) >= 0.005:
            extra.append(f"film {money(film_usd)}")
        if extra:
            text += f" ({', '.join(extra)})"
    if bal is not None:
        text += f" · about {money(max(bal['balance_usd'], 0))} left"
        if bal["low"]:
            text += f"  ! under your warning level of {money(bal['low_usd'])}"
    say("    " + text)
    prompts.event("usage", step=_run["step"], film=_run["film"], model=last["model"],
                  request={k: last[k] for k in ("input_tokens", "output_tokens", "cost_usd")},
                  run={"requests": _run["requests"], "input_tokens": _run["tin"], "output_tokens": _run["tout"],
                       "cost_usd": round(_run["usd"], 6), "unpriced": _run["unpriced"]},
                  film_cost_usd=None if film_usd is None else round(film_usd, 6),
                  balance_usd=None if bal is None else bal["balance_usd"], low=bool(bal and bal["low"]))
    return bal


def finish(say=print):
    """After a step's 'Used ... tokens' line: what the film has cost in all, if that adds anything."""
    ents = entries()
    film = _run["film"]
    film_usd = _film_cost(film, ents)
    bal = balance(ents)
    if film_usd is None or (bal is None and abs(film_usd - _run["usd"]) < 0.005):
        return
    steps = {}
    for e in ents:
        if e.get("film") == film and _number(e.get("usd")):
            steps[e.get("step") or "other"] = steps.get(e.get("step") or "other", 0.0) + e["usd"]
    names = {"generate": "notes", "refine": "frames"}
    split = ", ".join(f"{names.get(k, k)} {money(v)}" for k, v in steps.items())
    text = f"This film has cost {money(film_usd)} so far" + (f" ({split})" if len(steps) > 1 else "")
    if bal is not None:
        text += f"; about {money(max(bal['balance_usd'], 0))} credit left"
    say(text + ".")


# ---------------------------------------------------------------- the summary
def summary(films=8):
    """Everything the CLI prints and the app shows, as plain data."""
    ents = entries()
    today = datetime.date.today()
    spent = {"today": 0.0, "week": 0.0, "week_requests": 0, "month": 0.0, "all": 0.0, "unpriced": 0}
    week_start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    by = {}
    for e in ents:
        when = parse_stamp(e["t"])
        usd = e.get("usd")
        if not _number(usd):
            spent["unpriced"] += 1
            usd = 0.0
        spent["all"] += usd
        if when is not None:
            day = when.astimezone().date()
            if day == today:
                spent["today"] += usd
            if (day.year, day.month) == (today.year, today.month):
                spent["month"] += usd
            if when > week_start:
                spent["week"] += usd
                spent["week_requests"] += 1
        f = by.setdefault(e.get("film") or "(no film)", {"usd": 0.0, "steps": {}, "requests": 0, "last": e["t"]})
        f["usd"] += usd
        f["requests"] += 1
        f["last"] = max(f["last"], e["t"])
        step = e.get("step") or "other"
        f["steps"][step] = f["steps"].get(step, 0.0) + usd
    recent = sorted(by.items(), key=lambda kv: kv[1]["last"], reverse=True)[:films]
    return {"balance": balance(ents), "spent": {k: round(v, 4) if isinstance(v, float) else v for k, v in spent.items()},
            "films": [{"film": k, "cost_usd": round(v["usd"], 4), "requests": v["requests"], "last": v["last"],
                       "steps": {s: round(c, 4) for s, c in v["steps"].items()}} for k, v in recent],
            "session": session(), "dir": str(data_dir())}


def _local(stamp):
    when = parse_stamp(stamp)
    return when.astimezone().strftime("%d %b %H:%M") if when else stamp


def show(s):
    names = {"generate": "notes", "refine": "frames"}
    bal = s["balance"]
    print("API credit (an estimate)")
    if bal is None:
        print("  No balance set. Look at Billing in the Anthropic console, then:  python3 usage.py --set-balance 25.00")
    else:
        print(f"  About {money(max(bal['balance_usd'], 0))} left"
              + ("   ! LOW" if bal["low"] else "")
              + f"   (you set {money(bal['set_usd'])} on {_local(bal['as_of'])}; {money(bal['spent_usd'])} spent since)")
        print(f"  Warns below {money(bal['low_usd'])}.")
        if bal["unpriced"]:
            print(f"  {bal['unpriced']} request(s) since then used a model with no known price, so they aren't counted.")
    sp = s["spent"]
    print(f"\nSpent through this tool:  today {money(sp['today'])} · last 7 days {money(sp['week'])} "
          f"({sp['week_requests']} requests) · this month {money(sp['month'])} · all time {money(sp['all'])}")
    if s["films"]:
        print("\nFilms, latest first")
        for f in s["films"]:
            split = " · ".join(f"{names.get(k, k)} {money(v)}" for k, v in f["steps"].items())
            print(f"  {f['film'][:58]:<58}  {money(f['cost_usd']):>8}   {split}")
    print("\nClaude plan session\n  " + session_line(s["session"]))
    if week_line(s["session"]):
        print("  " + week_line(s["session"]))
    print("\nOnly this tool's own requests are counted. Spending elsewhere on the same account isn't, so enter the "
          "console's figure again after a top-up.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="API cost, estimated credit left, and the Claude plan's session use.")
    ap.add_argument("--set-balance", metavar="USD", help="what Billing in the Anthropic console shows now")
    ap.add_argument("--add-credit", metavar="USD", help="you topped up by this much")
    ap.add_argument("--low", metavar="USD", help="with --set-balance: warn below this (default $2)")
    ap.add_argument("--session", action="store_true", help="one line about the Claude plan's session")
    ap.add_argument("--stop-at", type=float, metavar="PCT", help="with --session: exit with code 3 at this much used")
    ap.add_argument("--parts-estimate", type=int, metavar="N", help="how much of a session N /notes parts should take")
    ap.add_argument("--note-parts", choices=("start", "end"), help="measure what /notes parts cost the session")
    ap.add_argument("--count", type=int, default=1, metavar="K", help="with --note-parts end: how many parts ran")
    ap.add_argument("--film", metavar="NAME", help="with --note-parts end: the film's name")
    ap.add_argument("--films", type=int, default=8, metavar="N", help="how many films to list (default 8)")
    ap.add_argument("--json", action="store_true", help="the summary as JSON")
    a = ap.parse_args(argv)
    try:
        if a.set_balance is not None:
            b = set_balance(parse_dollars(a.set_balance), parse_dollars(a.low) if a.low is not None else None)
            print(f"Saved. Counting from now, about {money(b['balance_usd'])} left; warns below {money(b['low_usd'])}.")
            return 0
        if a.add_credit is not None:
            b = add_credit(parse_dollars(a.add_credit))
            print(f"Saved. About {money(b['balance_usd'])} left; warns below {money(b['low_usd'])}.")
            return 0
        if a.low is not None:
            sys.exit("--low goes with --set-balance, e.g.  python3 usage.py --set-balance 25 --low 3")
    except ValueError as e:
        sys.exit(str(e))
    except OSError as e:
        sys.exit(f"Couldn't save it in {data_dir()}: {e.strerror or e}")
    if a.note_parts == "start":
        note_parts_start()
        return 0
    if a.note_parts == "end":
        note_parts_end(a.count, a.film)
        return 0
    if a.parts_estimate is not None:
        print("\n".join(parts_estimate(max(a.parts_estimate, 0), a.stop_at if a.stop_at is not None else PAUSE_DEFAULT)))
        return 0
    if a.session:
        print(session_line())
        w = _five()
        if a.stop_at is not None and w is not None and w["percent"] >= a.stop_at:
            print(f"That's {a.stop_at:.0f}% or more: don't start another part until the session resets"
                  + (f" ({clock(w['resets_at'])})." if w["resets_at"] else "."))
            return 3
        return 0
    s = summary(a.films)
    if a.json:
        print(json.dumps(s, indent=1))
    else:
        show(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
