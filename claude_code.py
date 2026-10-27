#!/usr/bin/env python3
"""
claude_code.py - requests through Claude Code on your Claude plan (Pro or Max), instead of API credits.

Each request is one run of Claude Code in the background (`claude -p`, its "print" mode), and the reply comes back
in the same shape as an API reply, so the steps read it the same way. What that run can see and do is kept small:
- It can't use the API key. ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN are taken out of its environment, so it
  signs in with your Claude account only. If Claude Code itself is signed in with an API key, it isn't used at all
  (problem() says why), because that would bill API credits behind your back.
- No tools for the dialogue notes. For the frames, only Read, for the contact sheets' folder (--add-dir).
- It runs in the notes' folder, never this project's, with Claude Code's own extras off where it has the switch
  (--safe-mode: no CLAUDE.md, hooks, MCP servers, plugins or skills), and keeps no session afterwards.
- The system prompt is the step's own (--system-prompt); the model and effort are the run's.

status() is what Settings shows (installed? signed in, and how?); problem() says why Claude Code can't be used, or
None. call() raises CantGoOn when the plan can't go on (its usage limit; signed out part-way), which sending.py turns
into the question about API credits. Any other failure stops the run with Claude Code's own words.

CONTEXT_NOTES_CLAUDE names the program to run instead of `claude` (the tests' stand-in, tests/fake_claude.py).
Standard library only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

ENV_BIN = "CONTEXT_NOTES_CLAUDE"
# Everything that would sign Claude Code in some other way than your Claude account (its docs, "Authentication
# precedence"): an API key or bearer token, a cloud provider, an Anthropic profile.
HIDDEN = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
          "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_PROFILE", "ANTHROPIC_FEDERATION_RULE_ID",
          "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT",                # when this itself runs inside Claude Code
          "CONTEXT_NOTES_UI")                                    # our GUI protocol is for our scripts only
PLAN_METHODS = ("claude.ai", "oauth_token")                      # `claude auth status` authMethod: on the plan
# Where the installers put it, for when the app was started without those folders on the PATH.
PLACES = ("~/.claude/local/claude", "~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")
TIMEOUT = 900                     # seconds for one request (the frames: Claude Code opens each contact sheet)

# "You've hit your session limit · resets 3:45pm" (or weekly, or Opus), and older wordings. Not "Server is temporarily
# limiting requests (not your usage limit)", which is the service being busy.
LIMIT_RE = re.compile(r"(?:hit|reached) your (?:\w+ ){0,2}limit|usage limit (?:reached|will reset|resets)|"
                      r"out of (?:extra )?usage|(?:5-hour|weekly|session) limit", re.I)
NOT_LIMIT_RE = re.compile(r"not your usage limit|temporarily limiting", re.I)
SIGNED_OUT_RE = re.compile(r"/login|not (?:logged|signed) in|log ?in again|invalid api key|oauth token|"
                           r"authenticat|credentials", re.I)


class CantGoOn(Exception):
    """The plan can't take this request: the message says why, for the question about API credits."""


def command():
    """The program to run, as a list, or None when Claude Code isn't installed (or can't be found)."""
    given = os.environ.get(ENV_BIN)
    if given:
        return [sys.executable, given] if given.endswith(".py") else [given]
    found = shutil.which("claude")
    if not found:
        found = next((str(p) for p in (Path(x).expanduser() for x in PLACES)
                      if p.is_file() and os.access(p, os.X_OK)), None)
    return [found] if found else None


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in HIDDEN}


def _quick(args, timeout=30):
    """A short, local Claude Code command (--version, --help, auth status): its output, or None if it failed."""
    cmd = command()
    if not cmd:
        return None
    try:
        r = subprocess.run(cmd + args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, env=clean_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r


_status = {}
_flags = {}
_lock = threading.Lock()                 # the app asks from two threads at start


def features():
    """The options this Claude Code has (from its --help), so older versions get only what they understand."""
    if "set" not in _flags:
        r = _quick(["--help"])
        _flags["set"] = set(re.findall(r"--[a-z][a-z-]+", r.stdout)) if r is not None and r.returncode == 0 else set()
    return _flags["set"]


def status(refresh=False):
    """{installed, path, version, signed_in, method, problem}. `signed_in` is None when this version can't say (no
    `claude auth status`): the first request finds out. Kept for the rest of this run unless `refresh`."""
    with _lock:
        if _status and not refresh:
            return dict(_status)
        out = _check()
        _status.clear()
        _status.update(out)
        return dict(out)


def _check():
    cmd = command()
    out = {"installed": bool(cmd), "path": cmd[-1] if cmd else None, "version": None, "signed_in": None,
           "method": None, "problem": None}
    if not cmd:
        out["problem"] = ("Claude Code isn't installed, or isn't where this can find it. Install it from "
                          "https://claude.com/claude-code, then sign in by running `claude` once in Terminal.")
    else:
        r = _quick(["--version"])
        if r is None or r.returncode != 0:
            out["problem"] = f"Claude Code ({cmd[-1]}) didn't start. Try running `claude` in Terminal to see why."
        else:
            first = (r.stdout.strip().splitlines() or [""])[0]
            found = re.search(r"\d+\.\d+(?:\.\d+)?", first)        # "2.1.311 (Claude Code)" -> "2.1.311"
            out["version"] = found.group(0) if found else (first.strip() or None)
            r = _quick(["auth", "status"])           # JSON; exit code 0 when signed in, 1 when not
            data = None
            if r is not None:
                try:
                    data = json.loads(r.stdout)
                except ValueError:
                    data = None
            if not isinstance(data, dict):
                out["problem"] = ("Claude Code couldn't say how it's signed in, so it isn't used: if it were signed in "
                                  "with an API key, it would use API credits without saying so. Update it (`claude "
                                  "update`) and sign in with your Claude account.")
            else:
                method = data.get("authMethod")
                out["method"] = method
                out["signed_in"] = r.returncode == 0 and method != "none" and data.get("loggedIn") is not False
                if not out["signed_in"]:
                    out["problem"] = ("Claude Code isn't signed in. Run `claude` once in Terminal and sign in with "
                                      "your Claude account (or run `claude auth login`).")
                elif method not in PLAN_METHODS:
                    out["problem"] = (f"Claude Code is signed in another way ({method}), not with your Claude plan, so "
                                      f"it would use API credits or another account. Sign in with your Claude account "
                                      f"instead (`claude auth login`), or choose API credits in Settings.")
    return out


def problem():
    return status()["problem"]


def prompt_for(content):
    """(the prompt text, the contact sheets it asks Claude Code to open). `content` is a request's text, or its
    blocks: text, and pictures given as files ({"type": "image", "path": ...})."""
    if isinstance(content, str):
        return content, []
    parts, images = [], []
    for block in content:
        if block.get("type") == "text":
            parts.append(block["text"])
        elif block.get("type") == "image" and "path" in block:
            path = str(Path(block["path"]).resolve())
            images.append(path)
            parts.append(f"[Contact sheet image: {path} - open it with the Read tool.]")
        else:
            raise ValueError("Claude Code is given pictures as files, not attached")
    text = "\n\n".join(parts)
    if images:
        text += ("\n\nOpen every contact sheet image listed above with the Read tool and look at it before you "
                 "answer. Then reply with only the JSON asked for.")
    return text, images


def _talk(p, prompt, timeout):
    return p.communicate(prompt, timeout=timeout)


GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}


def _stop(p):
    """Claude Code and anything it started (a launcher script runs node underneath): all of it, and without waiting
    for ever on pipes something else might still hold."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=20)
        else:
            import signal
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        p.kill()
    except OSError:
        pass
    try:
        p.communicate(timeout=10)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        pass


def call(model, system, content, effort=None, workdir=None, folders=(), timeout=TIMEOUT, record=True):
    """One request on the plan. Returns a dict shaped like the API's reply: {"content": [{"type": "text", ...}],
    "usage": {"input_tokens", "output_tokens"}, "stop_reason", "route": "plan", "plan_reading": the plan's windows
    as Claude Code reported them, or None}, and notes it in usage.py's ledger (no dollars) unless `record` is False.
    The plan's windows are saved for the meter and the 90% stop (usage.save_plan_reading). Raises CantGoOn when the
    plan can't take it; exits with Claude Code's message for anything else."""
    import claude_api
    import usage
    cmd = command()
    if not cmd or status()["problem"]:
        raise CantGoOn(status()["problem"] or "Claude Code isn't installed.")
    prompt, images = prompt_for(content)
    flags = features()
    if "--tools" not in flags:
        raise CantGoOn("This Claude Code is too old to be limited to the tools a step needs. Update it "
                       "(`claude update`), then run this again.")
    # stream-json: the result, and before it the plan's windows (rate_limit_event), which plain json leaves out
    args = ["-p", "--output-format", "stream-json", "--verbose", "--model", model, "--system-prompt", system or ""]
    for flag in ("--no-session-persistence", "--safe-mode", "--strict-mcp-config", "--disable-slash-commands"):
        if flag in flags:
            args.append(flag)
    if effort and "--effort" in flags and claude_api.supports_effort(model):
        args += ["--effort", effort]
    if images:
        args += ["--tools", "Read"]
        for d in sorted({str(Path(f).resolve()) for f in folders} | {str(Path(i).parent) for i in images}):
            args += ["--add-dir", d]
        args += ["--max-turns", str(2 * len(images) + 4)]
        if "--permission-mode" in flags:
            args += ["--permission-mode", "dontAsk"]        # anything that would need a yes is refused
    else:
        args += ["--tools", ""]
    cwd = Path(workdir) if workdir else Path(images[0]).parent if images else Path.home()
    try:
        # In a process group of its own, so a stop (Cancel, Ctrl-C, too long) ends all of it (_stop).
        p = subprocess.Popen(cmd + args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace", cwd=str(cwd), env=clean_env(), **GROUP)
    except OSError as e:
        raise CantGoOn(f"Claude Code ({cmd[-1]}) couldn't be started: {e.strerror or e}.") from None
    try:
        if claude_api.WAIT_IN_THREAD:
            out, err = claude_api.wait_awake(_talk, p, prompt, timeout)
        else:
            out, err = _talk(p, prompt, timeout)
    except subprocess.TimeoutExpired:
        _stop(p)
        sys.exit(f"Claude Code didn't answer within {timeout // 60} minutes, so this stopped. Run it again to pick up.")
    except KeyboardInterrupt:                    # Cancel or Ctrl-C: stop Claude Code too
        _stop(p)
        raise
    events = []
    for line in out.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            events.append(e)
    reading, refused = None, False
    for e in events:
        if e.get("type") == "rate_limit_event" and isinstance(e.get("rate_limit_info"), dict):
            reading = e["rate_limit_info"]
            refused = refused or reading.get("status") == "rejected"
    if reading is not None:
        try:
            usage.save_plan_reading(reading)
        except Exception:                        # the meter is a nicety: never stop a run over it
            pass
    data = next((e for e in reversed(events) if e.get("type") == "result"), {})
    text = data["result"] if isinstance(data.get("result"), str) else ""
    error_state = bool(data) and (data.get("is_error") or data.get("subtype", "success") != "success")
    failed = p.returncode != 0 or error_state
    if failed or not data:
        errors = " ".join(str(e) for e in data.get("errors") or [] if e) if isinstance(data.get("errors"), list) else ""
        why = " ".join((text.strip() or errors or err.strip() or out.strip()[-800:] or f"exit code {p.returncode}")
                       .split())
        # Claude Code's own message (an error result, or no JSON at all), not a reply from the model that the
        # program then failed after: only that can say the plan's limit is reached or the sign-in is gone.
        own = why if (error_state or not data) else " ".join((errors or err).split())
        if refused or (LIMIT_RE.search(own) and not NOT_LIMIT_RE.search(own)):
            raise CantGoOn(f"Your Claude plan's usage limit is reached (Claude Code says: {why[:300]}).")
        if SIGNED_OUT_RE.search(own):
            _status.clear()
            raise CantGoOn(f"Claude Code can't sign in to your plan (it says: {why[:300]}).")
        if data.get("subtype") == "error_max_turns":
            why = f"it ran out of turns before it answered ({why[:300]})"
        sys.exit(f"Claude Code stopped: {why[:800]}\nWhat was written so far is kept; run the same command again to "
                 f"pick up.")
    used = data.get("usage") or {}
    tin = sum(int(used.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    tout = int(used.get("output_tokens") or 0)
    if record:
        try:
            usage.record(model, tin, tout, None, route="plan")
        except Exception:                        # the notes matter more than the ledger
            pass
    return {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": tin, "output_tokens": tout},
            "stop_reason": data.get("stop_reason") or "end_turn", "route": "plan", "plan_reading": reading}


def ping():
    """A fresh reading of the plan's windows, for the meter's refresh: one tiny request (Haiku, no tools, a word in
    and out; Claude Code adds about 15,000 tokens of its own context, mostly cached). Nothing goes in the ledger.
    Returns True when a reading came back. Raises CantGoOn (or exits) like call()."""
    import tempfile
    reply = call("haiku", "Reply with the single word OK.", "OK?", workdir=tempfile.gettempdir(), timeout=120,
                 record=False)
    return reply["plan_reading"] is not None
