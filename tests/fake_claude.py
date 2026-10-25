#!/usr/bin/env python3
"""
A stand-in for the `claude` command (Claude Code), for the tests. Standard library only, and no imports from the
project or the test suite: the `fake_claude` fixture in conftest.py copies this file to a temporary folder as an
executable named `claude` and points CONTEXT_NOTES_CLAUDE_BIN at it, so claude_api.call_claude_code() runs it as a
separate process, exactly as it would run the real thing.

It checks that it was called the way `claude -p` expects (headless, JSON out, the model, the system prompt, no
session persistence, no tools for text and only Read plus --add-dir for images), reads the prompt from stdin, and
answers with the JSON object the real CLI prints. The reply is the same fabricated one the fake API in conftest.py
gives: a few notes for the lines being annotated, or an add/revise/drop set for the frame pass.

Environment:
    FAKE_CLAUDE_LOG      a file; one JSON line per call is appended: {"argv", "prompt", "cwd"}
    FAKE_CLAUDE_FAIL     "limit": fail like a plan whose usage limit is reached; "login": fail like a signed-out CLI;
                         "limit-after-N": succeed for the first N calls (counted in FAKE_CLAUDE_LOG), then "limit"
A flag it doesn't expect, or a call shaped wrongly, exits 3 with the reason on stderr, so the test fails loudly.
"""
import json
import os
import re
import sys
from pathlib import Path


def fail(why):
    print(f"fake claude: {why}", file=sys.stderr)
    sys.exit(3)


def hms(t):
    h, rem = divmod(max(0.0, t), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{int(s):02d}"


def seconds(text):
    out = 0.0
    for p in text.split(":"):
        out = out * 60 + float(p)
    return out


def notes_reply(n, user):
    """What tests/test_generate_notes.py's notes_for_each_part fabricates: a good note on the second line of the
    part, one whose quote isn't on its line, and one outside the range."""
    lo = int(re.search(r"Lines to annotate \((\d+) to", user).group(1))
    lines = dict(re.findall(r"^(\d+) \[[\d:]+\] (.*)$", user, re.M))
    words = lines[str(lo + 1)].split()
    notes = [{"cue": lo + 1, "match": " ".join(words[:3]), "category": "Idiom", "text": f"Note {n}", "confidence": "high"},
             {"cue": lo + 2, "match": "words that are not on that line", "category": "Trivia", "text": "Anchored",
              "confidence": "low"},
             {"cue": 9999, "match": "x", "category": "Trivia", "text": "Out of range"}]
    return "```json\n" + json.dumps(notes) + "\n```"


def refine_reply(user):
    """What tests/test_refine_notes.py's refine_responder fabricates for one stretch of the video."""
    lo = seconds(re.search(r"This stretch: (\S+) to", user).group(1))
    ids = [int(i) for i in re.findall(r"^#(\d+) \[", user, re.M)]
    reply = {"add": [{"at": hms(lo + 5), "kind": "visual", "category": "Prop", "text": f"Prop at {hms(lo + 5)}",
                      "confidence": "high"},
                     {"at": round((lo + 20) / 60, 2), "kind": "visual", "category": "Prop", "text": "Prop in decimal minutes"}],
             "revise": [{"id": ids[0], "text": "REVISED", "reason": "frames"}] if ids else [],
             "drop": [{"id": ids[-1], "reason": "wrong"}] if len(ids) > 1 else []}
    return json.dumps(reply)


def parse(argv):
    opts, add_dirs, i = {}, [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("-p", "--no-session-persistence"):
            opts[a] = True
            i += 1
        elif a in ("--output-format", "--model", "--system-prompt", "--effort", "--tools", "--add-dir", "--max-turns"):
            if i + 1 >= len(argv):
                fail(f"{a} needs a value")
            if a == "--add-dir":
                add_dirs.append(argv[i + 1])
            else:
                opts[a] = argv[i + 1]
            i += 2
        else:
            fail(f"unexpected argument {a!r}")
    return opts, add_dirs


def main():
    opts, add_dirs = parse(sys.argv[1:])
    for flag in ("-p", "--output-format", "--model", "--system-prompt", "--no-session-persistence", "--tools"):
        if flag not in opts:
            fail(f"missing {flag}")
    if opts["--output-format"] != "json":
        fail(f"--output-format is {opts['--output-format']!r}, not json")
    if opts.get("--effort") not in (None, "low", "medium", "high", "xhigh", "max"):
        fail(f"bad --effort {opts['--effort']!r}")
    if sys.stdin.isatty():
        fail("the prompt has to come on stdin")
    prompt = sys.stdin.read()
    if not prompt.strip():
        fail("empty prompt")

    images = re.findall(r"^\[Image \d+: (.+?)  \(open it with your Read tool", prompt, re.M)
    if images:
        if opts["--tools"] != "Read":
            fail(f"images in the prompt but --tools is {opts['--tools']!r}, not Read")
        for img in images:
            p = Path(img)
            if not p.is_file():
                fail(f"image {img} doesn't exist")
            if not any(str(p.parent) == d or str(p).startswith(d.rstrip("/") + "/") for d in add_dirs):
                fail(f"image {img} isn't under any --add-dir {add_dirs}")
        if int(opts.get("--max-turns") or 0) < 2 * len(images) + 1:
            fail(f"--max-turns {opts.get('--max-turns')} leaves no room to Read {len(images)} images")
        if "reply with ONLY the JSON" not in prompt:
            fail("the prompt doesn't tell the model to reply with the JSON as text")
    elif opts["--tools"] != "":
        fail(f"text only, but --tools is {opts['--tools']!r}, not empty")
    if "ANTHROPIC_API_KEY" in os.environ:
        fail("ANTHROPIC_API_KEY is set: the CLI would bill the key, not the subscription")

    log = os.environ.get("FAKE_CLAUDE_LOG")
    n = 1
    if log:
        path = Path(log)
        if path.exists():
            n += sum(1 for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd(), "n": n}) + "\n")

    mode = os.environ.get("FAKE_CLAUDE_FAIL", "")
    m = re.fullmatch(r"limit-after-(\d+)", mode)
    if m and n > int(m.group(1)):
        mode = "limit"
    if mode == "limit":
        print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                          "result": "You've hit your usage limit for this plan. It resets at 3pm.",
                          "usage": {"input_tokens": 0, "output_tokens": 0}, "num_turns": 0, "session_id": "fake"}))
        sys.exit(1)
    if mode == "login":
        print("Not logged in · Please run /login", file=sys.stderr)
        sys.exit(1)

    text = refine_reply(prompt) if "You refine" in opts["--system-prompt"] else notes_reply(n, prompt)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text, "stop_reason": "end_turn",
                      "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_creation_input_tokens": 500,
                                "cache_read_input_tokens": 500},
                      "total_cost_usd": 0.0, "num_turns": 1 + 2 * len(images), "permission_denials": [],
                      "duration_ms": 10, "session_id": "fake"}))


if __name__ == "__main__":
    main()
