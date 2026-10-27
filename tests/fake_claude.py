#!/usr/bin/env python3
"""A stand-in for the `claude` command (Claude Code), so the tests never run or sign in to the real one.

conftest.py points CONTEXT_NOTES_CLAUDE at this file for every test. Environment variables say what it does:
  FAKE_CLAUDE_AUTH   the authMethod `claude auth status` reports: "claude.ai" (the default), "none" (signed out,
                     exit code 1), "api_key", or "missing" (an old Claude Code with no `auth status`)
  FAKE_CLAUDE_MODE   how `claude -p` answers: "both" (the default: the fake API's test replies, notes or frames by the
                     system prompt), "limit" (the plan's usage limit), "limit-after:N" (N answers, then the limit),
                     "signed-out", "fail" (some other error), "garbage" (an answer that isn't JSON),
                     "limit-reached" (the other wording of the limit), "crash-after" (a reply that mentions a
                     session limit, then a non-zero exit), "hang" (never answers), "limit-quiet" (refused, says
                     only so in its rate_limit_event)
  FAKE_CLAUDE_HELP   "old": a --help without the newer options
  FAKE_CLAUDE_RATE   the plan's windows it reports with --output-format stream-json: "five,seven" as fractions
                     ("0.42,0.11" by default), or "none"
  FAKE_CLAUDE_LOG    a file that gets one JSON line per `claude -p` run: its arguments, the prompt, the folder it ran
                     in, which auth variables it could see, and the pictures it opened
"""
import json
import os
import re
import sys
from pathlib import Path

NEW_FLAGS = ("--tools --effort --safe-mode --no-session-persistence --strict-mcp-config --disable-slash-commands "
             "--permission-mode --add-dir --max-turns --system-prompt --output-format --model --print")


def log(entry):
    path = os.environ.get("FAKE_CLAUDE_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def calls_so_far():
    path = os.environ.get("FAKE_CLAUDE_LOG")
    try:
        return len(Path(path).read_text(encoding="utf-8").splitlines()) if path else 0
    except OSError:
        return 0


STREAM = {"on": False, "status": "allowed"}


def result(text, error=False, usage=(1000, 200), code=None):
    final = {"type": "result", "subtype": "success", "is_error": error, "result": text, "num_turns": 1,
             "usage": {"input_tokens": usage[0], "output_tokens": usage[1], "cache_read_input_tokens": 0,
                       "cache_creation_input_tokens": 0}, "stop_reason": "end_turn"}
    if STREAM["on"]:                            # stream-json: one event a line, the plan's windows before the result
        print(json.dumps({"type": "system", "subtype": "init", "session_id": "fake"}))
        rate = os.environ.get("FAKE_CLAUDE_RATE", "0.42,0.11")
        if rate != "none":
            five, seven = (float(x) for x in rate.split(","))
            print(json.dumps({"type": "rate_limit_event", "rate_limit_info": {
                "status": STREAM["status"], "unifiedWindows": {
                    "five_hour": {"utilization": five, "resetsAt": 4102444800, "status": STREAM["status"]},
                    "seven_day": {"utilization": seven, "resetsAt": 4102444800, "status": "allowed"}}}}))
    print(json.dumps(final))
    sys.exit(code if code is not None else (1 if error else 0))


def options(argv):
    """The -p run's options: {flag: [values]} (a flag with no value gets [True])."""
    out, i = {}, 0
    takes = {"--model", "--system-prompt", "--output-format", "--tools", "--add-dir", "--max-turns", "--effort",
             "--permission-mode"}
    while i < len(argv):
        a = argv[i]
        if a in takes and i + 1 < len(argv):
            out.setdefault(a, []).append(argv[i + 1])
            i += 2
        else:
            out.setdefault(a, []).append(True)
            i += 1
    return out


def main(argv):
    if argv[:1] == ["--version"]:
        print("2.1.999 (Claude Code)")
        return 0
    if argv[:1] in (["--help"], ["-h"]):
        print("Usage: claude [options]\n" + ("--model --print --output-format --system-prompt"
                                             if os.environ.get("FAKE_CLAUDE_HELP") == "old" else NEW_FLAGS))
        return 0
    if argv[:2] == ["auth", "status"]:
        method = os.environ.get("FAKE_CLAUDE_AUTH", "claude.ai")
        if method == "missing":
            print("error: unknown command 'auth'", file=sys.stderr)
            return 1
        print(json.dumps({"loggedIn": method != "none", "authMethod": method, "apiProvider": "firstParty"}))
        return 0 if method != "none" else 1
    if "-p" not in argv:
        print("fake claude: only -p, --version, --help and auth status", file=sys.stderr)
        return 2
    opts = options(argv)
    STREAM["on"] = (opts.get("--output-format") or [""])[0] == "stream-json"
    prompt = sys.stdin.read()
    system = (opts.get("--system-prompt") or [""])[0]
    dirs = [str(Path(d).resolve()) for d in opts.get("--add-dir", [])]
    tools = (opts.get("--tools") or [None])[0]
    pictures = re.findall(r"\[Contact sheet image: (.+?) - open it with the Read tool\.\]", prompt)
    opened = []
    for p in pictures:                          # what Read would do: only inside the folders it was given
        if tools == "Read" and any(str(Path(p).resolve()).startswith(d) for d in dirs) and Path(p).is_file():
            opened.append(p)
    n = calls_so_far() + 1
    log({"argv": argv, "prompt": prompt, "system": system, "cwd": os.getcwd(), "opened": opened, "pictures": pictures,
         "env": sorted(k for k in os.environ if k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                                                      "CLAUDE_CODE_OAUTH_TOKEN", "CONTEXT_NOTES_UI"))})
    mode = os.environ.get("FAKE_CLAUDE_MODE", "both")
    if mode.startswith("limit-after:") and n > int(mode.split(":")[1]):
        mode = "limit"
    if mode == "limit":
        result("You've hit your session limit · resets 3:45pm", error=True)
    if mode == "signed-out":
        result("Not logged in · Please run /login", error=True)
    if mode == "fail":
        result("Something went wrong in the fake", error=True)
    if mode == "garbage":
        result("I looked, but here is no JSON at all.")
    if mode == "limit-reached":
        result("You've reached your weekly usage limit. Your limit resets at 3pm.", error=True)
    if mode == "crash-after":
        result('[{"cue": 1, "match": "x", "text": "A joke about the session limit at work"}]', code=1)
    if mode == "limit-quiet":
        STREAM["status"] = "rejected"
        result("Request blocked.", error=True)
    if mode == "hang":
        import time
        time.sleep(120)
    if "You refine" in system:
        if pictures and len(opened) != len(pictures):
            result(f"Couldn't open {sorted(set(pictures) - set(opened))}", error=True)
        result(frame_reply(prompt), usage=(5000, 300))
    if "Lines to annotate" not in prompt:       # anything else (the meter's refresh): a word back
        result("OK", usage=(10, 1))
    result(notes_reply(n, prompt), usage=(2000, 300))


# The same replies as the fake API's in the tests (test_generate_notes.notes_for_each_part and
# test_refine_notes.refine_responder), here without pytest, which a test's own HOME can't import.
def notes_reply(n, user):
    lo = int(re.search(r"Lines to annotate \((\d+) to", user).group(1))
    lines = dict(re.findall(r"^(\d+) \[[\d:]+\] (.*)$", user, re.M))
    words = lines[str(lo + 1)].split()
    notes = [{"cue": lo + 1, "match": " ".join(words[:3]), "category": "Idiom", "text": f"Note {n}", "confidence": "high"},
             {"cue": lo + 2, "match": "words that are not on that line", "category": "Trivia", "text": "Anchored",
              "confidence": "low"},
             {"cue": 9999, "match": "x", "category": "Trivia", "text": "Out of range"}]
    return "```json\n" + json.dumps(notes) + "\n```"


def hms(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{int(s):02d}"


def frame_reply(user):
    h, m, s = re.search(r"This stretch: (\S+) to", user).group(1).split(":")
    lo = int(h) * 3600 + int(m) * 60 + float(s)
    ids = [int(i) for i in re.findall(r"^#(\d+) \[", user, re.M)]
    return json.dumps({"add": [{"at": hms(lo + 5), "kind": "visual", "category": "Prop", "text": f"Prop at {hms(lo + 5)}",
                                "confidence": "high"},
                               {"at": round((lo + 20) / 60, 2), "kind": "visual", "category": "Prop",
                                "text": "Prop in decimal minutes"}],
                       "revise": [{"id": ids[0], "text": "REVISED", "reason": "frames"}] if ids else [],
                       "drop": [{"id": ids[-1], "reason": "wrong"}] if len(ids) > 1 else []})


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
