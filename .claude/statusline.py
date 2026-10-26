#!/usr/bin/env python3
"""
Claude Code status line for this project: how much of your plan's session is used, and the API credit left.

    [Opus 4.5] 5h 42% (resets 8:10 PM) · 7d 18% · API ~$17.82

Claude Code runs this after each reply and hands it a JSON description on stdin. On a Pro or Max plan that includes
`rate_limits` (the 5-hour and 7-day windows). This saves those readings to ~/.config/context-notes/session.json, which
`python3 usage.py --session` and the /notes command read back. The credit figure is the estimate from usage.py.

It is switched on by .claude/settings.local.json (kept out of git, so it's yours alone). Standard library only, and it
never fails: a status line that throws would leave an empty bar.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))      # usage.py is one folder up


def paint(code, text):
    return f"\033[{code}m{text}\033[0m"


def level(percent):
    return 32 if percent < 50 else 33 if percent < 80 else 31              # green, yellow, red


def build(payload):
    import usage
    fresh = usage.write_session(payload)           # False on an API key, or before the first reply
    model = payload.get("model") if isinstance(payload, dict) else None
    name = model.get("display_name") if isinstance(model, dict) else None
    info = []
    s = usage.session() if fresh else None
    for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
        w = (s or {}).get(key)
        if not w or w["percent"] is None:
            continue
        text = f"{label} {w['percent']:.0f}%"
        if key == "five_hour" and w["resets_at"]:
            text += f" (resets {usage.clock(w['resets_at'])})"
        info.append(paint(level(w["percent"]), text))
    bal = usage.balance()
    if bal is not None:
        info.append(paint(31 if bal["low"] else 36, f"API ~{usage.money(max(bal['balance_usd'], 0))}"))
    return " ".join(x for x in (f"[{name}]" if name else "", " · ".join(info)) if x)


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    try:
        print(build(payload))
    except Exception:                              # never leave the bar empty because of a bug in here
        print("")


if __name__ == "__main__":
    main()
