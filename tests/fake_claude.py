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
  FAKE_CLAUDE_HELP   "old": a --help without the newer options; "no-allowed-tools": one without --allowed-tools
  FAKE_CLAUDE_RATE   the plan's windows it reports with --output-format stream-json: "five,seven" as fractions
                     ("0.42,0.11" by default), or "none"
  FAKE_CLAUDE_LOG    a file that gets one JSON line per `claude -p` run: its arguments, the prompt, the folder it ran
                     in, which auth variables it could see, and the pictures it opened
  FAKE_CLAUDE_SIGNIN a file: when it exists, `auth status` says signed in (claude.ai) whatever FAKE_CLAUDE_AUTH says.
                     `auth login` prints the sign-in link and waits for the code on stdin, as the real one does with
                     no terminal: "good" (any code not "bad") makes the file and exits 0; "bad" exits 1 with a
                     message. `auth logout` removes it. FAKE_CLAUDE_LOGIN "no-link" ends at once without a link,
                     "silent" prints nothing and waits.
"""
import json
import os
import re
import sys
from pathlib import Path

NEW_FLAGS = ("--tools --effort --safe-mode --no-session-persistence --strict-mcp-config --disable-slash-commands "
             "--permission-mode --add-dir --max-turns --system-prompt --output-format --model --print "
             "--allowedTools, --allowed-tools")


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
             "--permission-mode", "--allowed-tools"}
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
        help_kind = os.environ.get("FAKE_CLAUDE_HELP")
        flags = NEW_FLAGS.replace("--allowedTools, --allowed-tools", "") if help_kind == "no-allowed-tools" else NEW_FLAGS
        print("Usage: claude [options]\n" + ("--model --print --output-format --system-prompt"
                                             if help_kind == "old" else flags))
        return 0
    signin = os.environ.get("FAKE_CLAUDE_SIGNIN")
    if argv[:2] == ["auth", "status"]:
        method = os.environ.get("FAKE_CLAUDE_AUTH", "claude.ai")
        if method == "missing":
            print("error: unknown command 'auth'", file=sys.stderr)
            return 1
        if signin and Path(signin).exists():
            method = "claude.ai"
        print(json.dumps({"loggedIn": method != "none", "authMethod": method, "apiProvider": "firstParty"}))
        return 0 if method != "none" else 1
    if argv[:2] == ["auth", "login"]:
        how = os.environ.get("FAKE_CLAUDE_LOGIN", "")
        if how == "no-link":
            print("Something is wrong with the fake's network", file=sys.stderr)
            return 1
        if how == "silent":
            import time
            time.sleep(120)
        print("Opening browser to sign in…")
        print("If the browser didn't open, visit: https://claude.example/oauth/authorize?code=true&state=fake")
        print("Paste code here if prompted > ", end="", flush=True)
        code = sys.stdin.readline().strip()
        if code and code != "bad":
            if signin:
                Path(signin).write_text(code, encoding="utf-8")
            print("\nLogged in as fake@example.com")
            return 0
        print("\nInvalid authorization code" if code else "\nNo code given", file=sys.stderr)
        return 1
    if argv[:2] == ["auth", "logout"]:
        if signin and Path(signin).exists():
            Path(signin).unlink()
        print("Logged out")
        return 0
    if "-p" not in argv:
        print("fake claude: only -p, --version, --help and auth status/login/logout", file=sys.stderr)
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
    if "You research a film" in system:          # research.py's web search: it may only search and read pages
        if tools != "WebSearch,WebFetch" or (opts.get("--allowed-tools") or [None])[0] != "WebSearch,WebFetch":
            result(f"Not allowed to search: tools {tools!r}", error=True)
        result("I searched and read three pages.\n<facts>" + json.dumps(FACTS) + "</facts>", usage=(30000, 2000))
    if "audio commentary" in system:
        times = re.findall(r"^\[(\d+:\d\d:\d\d)\] (.*)$", prompt, re.M)
        result("<facts>" + json.dumps([{"fact": f"The director says: {t}", "scene": "", "when": w, "category":
                                        "Behind the scenes", "source": "commentary", "spoiler": False}
                                       for w, t in times[:2]]) + "</facts>", usage=(4000, 300))
    if 'refine the "Behind the Scenes"' in system:
        result(bts_frame_reply(prompt), usage=(5000, 300))
    if "Behind the Scenes" in system and "Lines to annotate" in prompt:
        result(bts_notes_reply(prompt), usage=(2000, 300))
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


# research.py's web search: three facts, one a spoiler, one with no dialogue (for the frames step to place)
FACTS = [{"fact": "The actor broke two toes kicking a helmet here, and the take was kept.", "scene": "the kick",
          "line": "", "category": "Injury", "source": "https://example.com/interview", "spoiler": False,
          "confidence": "high"},
         {"fact": "This character turns out to be the villain.", "scene": "the first meeting", "category": "Casting",
          "source": "https://example.com/book", "spoiler": True, "confidence": "medium"},
         {"fact": "The castle is a painted model.", "scene": "the castle on the hill, no dialogue", "category":
          "Effects", "source": "https://example.com/vfx", "spoiler": False, "confidence": "high"}]


def bts_notes_reply(user):
    """The Behind the Scenes notes for a part: facts 1 and 2 on its second and third lines (2 a spoiler on the sheet,
    which this note doesn't repeat), and one that tells no fact from the sheet (#99), which the step leaves out.
    Facts already used aren't used again."""
    lo = int(re.search(r"Lines to annotate \((\d+) to", user).group(1))
    lines = dict(re.findall(r"^(\d+) \[[\d:]+\] (.*)$", user, re.M))
    used = {int(i) for i in re.findall(r"#(\d+)", user.split("Facts already used", 1)[1])} if \
        "Facts already used" in user else set()
    out = []
    for fact, k, spoiler in ((1, lo + 1, False), (2, lo + 2, True)):
        if fact in used or str(k) not in lines:
            continue
        note = {"cue": k, "match": " ".join(lines[str(k)].split()[:3]), "fact": fact, "category": "Injury",
                "text": f"Fact {fact} told here", "spoiler": spoiler, "confidence": "high"}
        if spoiler:                              # not said: the step takes the fact sheet's own mark
            del note["spoiler"]
        out.append(note)
    out.append({"cue": lo, "match": "x", "fact": 99, "category": "Trivia", "text": "Not on the sheet"})
    return json.dumps(out)


def bts_frame_reply(user):
    """The frames step: fact 3 at five seconds into the stretch (if it's still to place), and a note with no fact,
    which the step leaves out."""
    h, m, s = re.search(r"This stretch: (\S+) to", user).group(1).split(":")
    lo = int(h) * 3600 + int(m) * 60 + float(s)
    left = re.search(r"Facts not placed yet[^:]*: (.*)$", user, re.M)
    add = [{"at": hms(lo + 5), "kind": "visual", "category": "Prop", "text": "Not a fact from the sheet"}]
    if left and "#3" in left.group(1):
        add.append({"at": hms(lo + 5), "kind": "visual", "fact": 3, "category": "Effects",
                    "text": "That castle is a painted model", "spoiler": False, "confidence": "high"})
    return json.dumps({"add": add})


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
