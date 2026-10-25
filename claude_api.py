"""
claude_api.py - the one place the scripts talk to Claude, and where the key and the backend setting live.

Used by generate_notes.py (dialogue notes), refine_notes.py (frame notes), bench/ and app.py. Standard library only.

There are two ways to reach Claude (the "backend"):
    api          your own Anthropic API key; billed per token as API credits
    claude-code  the Claude Code command (`claude -p`) installed on this computer, signed in to your Claude
                 subscription; uses the plan's allowance, not credits
load_backend() picks one: --backend, else $CONTEXT_NOTES_BACKEND, else ~/.config/context-notes/backend (written by
set_backend(), make_ass.py --set-backend), else "api". send() dispatches a request to call_api() or
call_claude_code(); the scripts call send() and nothing else.

The API key is read from (first match wins):
    1. --api-key-file PATH                    (load_key(explicit))
    2. ~/.config/context-notes/api-key        (or $XDG_CONFIG_HOME/context-notes/api-key)
    3. the ANTHROPIC_API_KEY environment variable (fallback only)
The file must be readable only by you (chmod 600); set_key() (make_ass.py --set-api-key) creates it that way.

call_api() sends one request and returns the reply as a dict. It retries up to three times when the API is busy
(429, 500, 502, 503, 529, honouring retry-after) or the network drops, and stops the program with a plain message
for anything else. call_claude_code() runs `claude -p` once and returns the same shape of dict. cost() turns token
counts into dollars at the list prices in PRICES (None on the subscription). image_tokens() estimates what an image
costs to send. Every script shows a size and cost estimate and asks before sending anything.
"""
import base64
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import fileio
import prompts
from fileio import config_dir

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
# USD per million tokens (input, output). Checked October 2026; see
# https://platform.claude.com/docs/en/about-claude/pricing for current figures.
PRICES = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-fable-5-1": (10.0, 50.0),
}
MAX_TOKENS = 8000          # reply limit per request

BACKENDS = ("api", "claude-code")
BACKEND_ENV = "CONTEXT_NOTES_BACKEND"
CLAUDE_BIN_ENV = "CONTEXT_NOTES_CLAUDE_BIN"     # where the `claude` command is (tests point it at a stand-in)
CLAUDE_CODE_TIMEOUT = 900                     # seconds for one `claude -p` run


# ---------------------------------------------------------------- API key
def key_path():
    return config_dir() / "api-key"


def set_key():
    """Prompt (hidden) for the API key and store it where only this user can read it."""
    path = key_path()
    key = prompts.secret("Paste your Anthropic API key (input is hidden), then press Return: ", id="api-key").strip()
    if not key:
        sys.exit("Nothing entered; nothing saved.")
    if not key.startswith("sk-ant-"):
        sys.exit("That doesn't look like an Anthropic API key (they start with sk-ant-). Nothing saved.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    os.chmod(path, 0o600)
    print(f"Saved to {path} (readable only by you). Key ends in ...{key[-4:]}")
    print("Create or manage keys at https://console.anthropic.com/settings/keys")


def load_key(explicit=None):
    path = Path(explicit).expanduser() if explicit else key_path()
    if path.exists():
        if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            sys.exit(f"{path} can be read by other users. Lock it down first:\n  chmod 600 \"{path}\"")
        key = path.read_text().strip()
        if key:
            return key
        sys.exit(f"{path} is empty. Run  python3 make_ass.py --set-api-key")
    if explicit:
        sys.exit(f"Can't find the key file {explicit}")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    sys.exit("No API key found. Save one with:\n  python3 make_ass.py --set-api-key\n"
             f"(stored in {key_path()})")


# ---------------------------------------------------------------- which backend
def backend_path():
    return config_dir() / "backend"


def load_backend(explicit=None):
    """Where Claude runs: the --backend flag, else $CONTEXT_NOTES_BACKEND, else the saved setting
    (make_ass.py --set-backend), else "api"."""
    for name, where in ((explicit, "--backend"), (os.environ.get(BACKEND_ENV), f"the {BACKEND_ENV} setting")):
        if name:
            name = str(name).strip()
            if name not in BACKENDS:
                sys.exit(f"{where} is {name!r}; it has to be one of: {', '.join(BACKENDS)}")
            return name
    path = backend_path()
    if path.exists():
        name = path.read_text().strip()
        if name in BACKENDS:
            return name
        if name:
            sys.exit(f"{path} says {name!r}; it has to be one of: {', '.join(BACKENDS)}.\n"
                     "Fix it with:  python3 make_ass.py --set-backend api   (or claude-code)")
    return "api"


def set_backend(name):
    """Save where Claude runs (make_ass.py --set-backend). Written all at once; readable only by you, like the key."""
    if name not in BACKENDS:
        sys.exit(f"The backend has to be one of: {', '.join(BACKENDS)}")
    path = backend_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fileio.write_text_safely(path, name + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    if name == "claude-code":
        print(f"Saved to {path}: Claude runs through Claude Code, on your Claude subscription (no API credits).")
        found = claude_bin()
        print(f"Claude Code found at {found}." if found else
              "Claude Code isn't installed yet (no `claude` command found). Install it from https://claude.com/claude-code "
              "and run `claude` once to sign in; the scripts will say so until then.")
    else:
        print(f"Saved to {path}: Claude runs through the Anthropic API, with your API key (API credits).")


def claude_bin():
    """The `claude` command, or None if it isn't installed. $CONTEXT_NOTES_CLAUDE_BIN overrides the search."""
    return os.environ.get(CLAUDE_BIN_ENV) or shutil.which("claude")


def check_claude_code():
    """The `claude` command, or stop now with a plain hint (like load_key does for a missing key)."""
    found = claude_bin()
    if not found:
        sys.exit("Claude Code isn't installed (no `claude` command found), so Claude can't run on your subscription.\n"
                 "  Install it from https://claude.com/claude-code and run `claude` once to sign in, then try again.\n"
                 "  Or use your API key instead:  python3 make_ass.py --set-backend api")
    return found


# ---------------------------------------------------------------- API call
def encode_images(content):
    """The content blocks for one request, ready to send. An image given as a file,
    {"type": "image", "path": "...", "media_type": "image/jpeg"}, is read and base64-encoded here and nowhere else,
    so the scripts can build a message from file paths and another backend could take the paths as they are. Text
    blocks, and images already encoded, pass through unchanged."""
    out = []
    for block in content:
        if block.get("type") == "image" and "path" in block:
            data = base64.b64encode(Path(block["path"]).read_bytes()).decode()
            block = {"type": "image", "source": {"type": "base64", "media_type": block.get("media_type", "image/jpeg"),
                                                 "data": data}}
        out.append(block)
    return out


def call_api(key, model, system, user, url=API_URL, timeout=300, max_tokens=MAX_TOKENS, effort=None):
    """`user` is a string, or a list of content blocks (text and images).
    `effort` ("low", "medium", "high", ...) is sent as output_config.effort; None leaves the model's own default
    (Haiku 4.5 rejects the field, so only pass it for models that support it)."""
    payload = {"model": model, "max_tokens": max_tokens, "system": system,
               "messages": [{"role": "user", "content": user}]}
    if effort:
        payload["output_config"] = {"effort": effort}
    body = json.dumps(payload).encode()
    headers = {"x-api-key": key, "anthropic-version": API_VERSION,
               "content-type": "application/json", "user-agent": "context-notes/0.1"}
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e)["error"]["message"]
            except Exception:
                msg = e.reason
            if e.code in (429, 500, 502, 503, 529) and attempt < 3:
                wait = float(e.headers.get("retry-after") or 2 ** (attempt + 1) * 2)
                print(f"    API busy ({e.code}); retrying in {wait:.0f} s...")
                time.sleep(min(wait, 60))
                continue
            if e.code == 401:
                sys.exit("The API rejected the key (401). Check it, or save a new one with --set-api-key.")
            sys.exit(f"API error {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < 3:
                print(f"    network problem ({e}); retrying...")
                time.sleep(2 ** (attempt + 1))
                continue
            sys.exit(f"Couldn't reach the API: {e}")


# ---------------------------------------------------------------- Claude Code (the subscription)
def claude_code_prompt(content):
    """The user prompt for `claude -p`, and the folders its Read tool needs. `content` is a string, or the content
    blocks the API route sends, un-encoded: text blocks are joined; each image block becomes a line that tells the
    model where the file is and to open it with its Read tool (which shows it the picture) before answering."""
    if isinstance(content, str):
        return content, []
    parts, folders, n_img = [], [], 0
    for block in content:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "image" and "path" in block:
            n_img += 1
            path = Path(block["path"]).resolve()
            parts.append(f"[Image {n_img}: {path}  (open it with your Read tool to see it)]")
            if str(path.parent) not in folders:
                folders.append(str(path.parent))
        elif block.get("type") == "image":
            parts.append("[an image that can't be shown this way was left out]")
    if n_img:
        parts.append(f"Before answering, open each of the {n_img} image file(s) named above with your Read tool and look "
                     "at it. Then reply with ONLY the JSON asked for, as text, and don't write any files.")
    return "\n\n".join(p for p in parts if p), folders


def call_claude_code(model, system, content, effort=None, timeout=CLAUDE_CODE_TIMEOUT, max_turns=None, workdir=None):
    """One request through Claude Code (`claude -p`, headless) on the user's subscription. Returns a dict shaped
    like call_api()'s reply: {"content": [{"type": "text", "text": ...}], "usage": {"input_tokens", "output_tokens"},
    "stop_reason", "backend": "claude-code"}. Stops the program with the CLI's own message when it fails (not signed
    in, the plan's usage limit reached, ...). `workdir` is the folder the CLI runs in, normally the media folder, so
    no other project's instructions are loaded into the session."""
    bin_ = check_claude_code()
    prompt, folders = claude_code_prompt(content)
    cmd = [bin_, "-p", "--output-format", "json", "--model", model, "--system-prompt", system, "--no-session-persistence"]
    if effort:
        cmd += ["--effort", effort]
    if folders:
        cmd += ["--tools", "Read"]
        for d in folders:
            cmd += ["--add-dir", d]
        if max_turns is None:
            max_turns = 2 * sum(1 for b in content if b.get("type") == "image") + 4
    else:
        cmd += ["--tools", ""]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}   # the subscription, not a key
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=workdir or None, env=env)
    except FileNotFoundError:
        sys.exit(f"Couldn't run Claude Code ({bin_}). Is it installed? https://claude.com/claude-code")
    except subprocess.TimeoutExpired:
        sys.exit(f"Claude Code didn't answer within {timeout // 60} minutes. Try again, or use the API (--backend api).")
    data = None
    for chunk in (r.stdout.strip(), (r.stdout.strip().splitlines() or [""])[-1]):
        try:
            data = json.loads(chunk)
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        data = {}
    text = data.get("result") if isinstance(data.get("result"), str) else ""
    if r.returncode != 0 or data.get("is_error") or (data and data.get("subtype", "success") != "success"):
        why = text.strip() or r.stderr.strip() or r.stdout.strip()[-800:] or f"exit code {r.returncode}"
        what = data.get("subtype") or ""
        if what == "error_max_turns":
            why = f"it ran out of turns before answering ({why})"
        sys.exit(f"Claude Code stopped: {why}\n  (If you're signed out, run `claude` once to sign in. If your plan's "
                 "usage limit is reached, wait for it to reset or use the API: --backend api.)")
    usage = data.get("usage") or {}
    tin = sum(int(usage.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    return {"content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": tin, "output_tokens": int(usage.get("output_tokens") or 0)},
            "stop_reason": data.get("stop_reason") or "end_turn", "backend": "claude-code",
            "cost_usd": data.get("total_cost_usd"), "num_turns": data.get("num_turns")}


def send(backend, model, system, content, *, key=None, api_url=API_URL, timeout=300, max_tokens=MAX_TOKENS,
         effort=None, workdir=None):
    """One request to Claude, wherever it runs. `content` is a string or un-encoded content blocks (images as
    {"type": "image", "path": ...}). "api": call_api() with the images base64-encoded; "claude-code":
    call_claude_code() (max_tokens doesn't apply there). Both return the same shape of reply."""
    if backend == "claude-code":
        return call_claude_code(model, system, content, effort=effort, timeout=max(timeout, CLAUDE_CODE_TIMEOUT),
                                workdir=workdir)
    if backend != "api":
        sys.exit(f"Unknown backend {backend!r}; it has to be one of: {', '.join(BACKENDS)}")
    user = content if isinstance(content, str) else encode_images(content)
    return call_api(key, model, system, user, api_url, timeout=timeout, max_tokens=max_tokens, effort=effort)


# ---------------------------------------------------------------- cost
def cost(model, tin, tout, backend="api"):
    """Dollars for this many input and output tokens at the model's list price, or None for a model not in PRICES.
    On the subscription (backend "claude-code") there are no credits to count, so None."""
    if backend != "api" or model not in PRICES:
        return None
    pi, po = PRICES[model]
    return tin * pi / 1e6 + tout * po / 1e6


def cost_note(c, backend="api", prefix=", roughly "):
    """The end of a "Plan:" line: ", roughly $0.12 in API credits.", ", on your Claude subscription (no API credits)."
    or "." when the price isn't known."""
    if backend == "claude-code":
        return ", on your Claude subscription (no API credits)."
    return f"{prefix}${c:.2f} in API credits." if c is not None else "."


def used_note(c, backend="api"):
    """The end of a "Used N input and M output tokens" line."""
    if backend == "claude-code":
        return " (on your Claude subscription; the input count includes Claude Code's own cached context)."
    return f" (about ${c:.2f})." if c is not None else "."


def image_tokens(path):
    """Roughly how many input tokens an image costs: (width x height) / 750 after scaling to fit 1568 px."""
    try:
        from PIL import Image
        w, h = Image.open(path).size
    except Exception:
        return 2500
    f = min(1.0, 1568 / max(w, h))
    return int(w * f * h * f / 750)
