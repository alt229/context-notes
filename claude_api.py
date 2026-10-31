#!/usr/bin/env python3
"""
claude_api.py - the Claude API: the API key, the prices, sending a request and noting what it cost. Used through
sending.py by generate_notes.py (dialogue notes) and refine_notes.py (frame notes) on the "api" route, or when the plan
runs out; and by bench/ and app.py. (The plan route, through Claude Code, is claude_code.py.) Standard library only.

The API key is read from (first match wins):
    1. --api-key-file PATH
    2. ~/.config/context-notes/api-key        (or $XDG_CONFIG_HOME/context-notes/api-key)
    3. the ANTHROPIC_API_KEY environment variable (fallback only)
The file must be readable only by you (chmod 600); set_key() (make_ass.py --set-api-key) creates it that way.

call_api() sends one request and returns the reply as a dict. It retries up to three times when the API is busy
(429, 500, 502, 503, 529, honouring retry-after) or the network drops, and stops the program with a plain message
for anything else. Every finished request is noted in usage.py's ledger. cost() turns token counts into dollars at
the list prices in PRICES; image_tokens() estimates what an image costs to send. Calls cost API credits, billed
separately from a Claude subscription; every script shows a size and cost estimate and asks before sending.
"""
import base64
import json
import os
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import fileio
import prompts
import usage

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


# ---------------------------------------------------------------- the API key
def key_path():
    return fileio.config_dir() / "api-key"


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
        sys.exit(f"{path} is empty. Run  {prompts.PYTHON} make_ass.py --set-api-key")
    if explicit:
        sys.exit(f"Can't find the key file {explicit}")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    sys.exit(f"No API key found. Save one with:\n  {prompts.PYTHON} make_ass.py --set-api-key\n"
             f"(stored in {key_path()})")


# ---------------------------------------------------------------- API call
# On Windows a program waiting for a network reply doesn't notice Ctrl-C (or a GUI's Cancel) until the reply comes,
# which can be minutes. There the request waits in a helper thread while this one stays awake.
WAIT_IN_THREAD = os.name == "nt"


def wait_awake(fn, *args, **kwargs):
    """fn(*args, **kwargs), run in a helper thread while this thread waits in short steps, so Ctrl-C and Cancel are
    noticed at once. Whatever fn raises (sys.exit included) is raised here; its result is returned."""
    out = {}

    def work():
        try:
            out["value"] = fn(*args, **kwargs)
        except BaseException as e:                         # carried over to the waiting thread
            out["error"] = e
    t = threading.Thread(target=work, daemon=True)
    t.start()
    while t.is_alive():
        t.join(0.2)
    if "error" in out:
        raise out["error"]
    return out.get("value")


def call_api(key, model, system, user, url=API_URL, timeout=300, max_tokens=MAX_TOKENS, effort=None, web=False,
             before_more=None):
    """One request to the Messages API (see _call_api). On Windows it waits awake, so Cancel works mid-request."""
    # only when asked: stand-ins for _call_api (bench/, tests) predate these
    more = {"web": True, "before_more": before_more} if web else {}
    if WAIT_IN_THREAD:
        return wait_awake(_call_api, key, model, system, user, url, timeout, max_tokens, effort, **more)
    return _call_api(key, model, system, user, url, timeout, max_tokens, effort, **more)


def encode_images(user):
    """The request's content with each picture given as a file ({"type": "image", "path": ...}, how the steps pass
    contact sheets) read and attached as base64 JPEG, as the API wants it. Text, and pictures already attached, are
    left as they are. The steps keep paths so the plan route (claude_code.py) can hand Claude Code the files."""
    if not isinstance(user, list):
        return user
    out = []
    for block in user:
        if isinstance(block, dict) and block.get("type") == "image" and "path" in block:
            block = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(Path(block["path"]).read_bytes()).decode()}}
        out.append(block)
    return out


NO_EFFORT = ("claude-haiku-4-5",)          # models that reject output_config.effort


def supports_effort(model):
    return not str(model).startswith(NO_EFFORT)


def _call_api(key, model, system, user, url=API_URL, timeout=300, max_tokens=MAX_TOKENS, effort=None, web=False,
              before_more=None):
    """`user` is a string, or a list of content blocks (text and images).
    `effort` ("low", "medium", "high", ...) is sent as output_config.effort; None leaves the model's own default.
    It's left out for the models that reject it (Haiku 4.5), so the effort from Settings never breaks a run.
    `web`: the research step (research.py), which may search the web (the API's own web search tool, at most
    WEB_SEARCHES searches, each SEARCH_USD on top of the tokens). A long search turn comes back paused
    ("pause_turn"); it is sent back as it is, so Claude carries on, and the reply returned holds every part of it.
    Each part is a request of its own, recorded as it comes: `before_more()` is called before each one after the first
    (the run's API-credit allowance and credit check; it stops the run by exiting), and the searches left shrink, so
    the whole turn makes at most WEB_SEARCHES. A web request that times out isn't sent again: it may have been
    billed."""
    messages = [{"role": "user", "content": encode_images(user)}]
    payload = {"model": model, "max_tokens": max_tokens, "system": system, "messages": messages}
    if effort and supports_effort(model):
        payload["output_config"] = {"effort": effort}
    if web:
        payload["tools"] = [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": WEB_SEARCHES}]
    reply = _post(key, model, payload, url, timeout, retry_timeouts=not web)
    if not web:
        return reply
    content, used = list(reply.get("content") or []), dict(reply.get("usage") or {})
    for _ in range(PAUSES):
        if reply.get("stop_reason") != "pause_turn":
            break
        if before_more:
            before_more()
        messages.append({"role": "assistant", "content": reply.get("content") or []})
        left = WEB_SEARCHES - searches_in(used)
        payload["tools"] = [{**payload["tools"][0], "max_uses": max(1, left)}]
        reply = _post(key, model, payload, url, timeout, retry_timeouts=False)
        content += list(reply.get("content") or [])
        more = reply.get("usage") or {}
        for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            if k in used or k in more:
                used[k] = int(used.get(k) or 0) + int(more.get(k) or 0)
        used["server_tool_use"] = {"web_search_requests": searches_in(used) + searches_in(more)}
    return {**reply, "content": content, "usage": used}


def searches_in(used):
    """The web searches a reply's usage says were made."""
    return int(((used or {}).get("server_tool_use") or {}).get("web_search_requests") or 0)


def billed_input(used):
    """Input tokens as they're priced: cache writes at 1.25 times the input price, cache reads at a tenth of it."""
    return (int(used.get("input_tokens") or 0) + 1.25 * int(used.get("cache_creation_input_tokens") or 0)
            + 0.1 * int(used.get("cache_read_input_tokens") or 0))


WEB_SEARCH_TOOL = "web_search_20250305"    # the API's web search tool; works on every model (its docs, October 2026)
WEB_SEARCHES = 20                          # searches one research request may make on the API (pauses included)
SEARCH_USD = 0.01                          # $10 per 1,000 searches, on top of the tokens
PAUSES = 8                                 # times a paused search turn is sent back before giving up on it


def _post(key, model, payload, url, timeout, retry_timeouts=True):
    """Send one request, retrying when the API is busy or the network drops; note what it cost. Without
    `retry_timeouts` (a web search, which may have run and been billed), a request that times out stops the run."""
    body = json.dumps(payload).encode()
    headers = {"x-api-key": key, "anthropic-version": API_VERSION,
               "content-type": "application/json", "user-agent": "context-notes/0.1"}
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                reply = json.load(r)
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
            if e.code == 400 and "credit balance" in str(msg).lower():
                usage.mark_empty()                   # the API knows better than the estimate (usage.py)
                sys.exit(f"API error {e.code}: {msg}\nAdd credit at https://platform.claude.com/settings/billing, "
                         f"then run the same command again: what was already written is kept.")
            sys.exit(f"API error {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            timed_out = isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError)
            if timed_out and not retry_timeouts:
                sys.exit(f"The web search didn't answer within {timeout // 60} minutes, so this stopped (it may still "
                         f"have been billed). Run the same command again to pick up.")
            if attempt < 3:
                print(f"    network problem ({e}); retrying...")
                time.sleep(2 ** (attempt + 1))
                continue
            sys.exit(f"Couldn't reach the API: {e}")
        _record_usage(model, reply)
        return reply


def _record_usage(model, reply):
    """Note what a finished request cost (usage.py), without ever letting the bookkeeping stop a paid run."""
    try:
        used = reply.get("usage") or {}
        tout = int(used.get("output_tokens") or 0)
        tin = sum(int(used.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                  "cache_read_input_tokens"))
        usd = cost(model, billed_input(used), tout)
        usage.record(model, tin, tout, None if usd is None else usd + searches_in(used) * SEARCH_USD)
    except Exception:                        # a reply shaped oddly: the notes matter more than the ledger
        pass


def cost(model, tin, tout):
    if model not in PRICES:
        return None
    pi, po = PRICES[model]
    return tin * pi / 1e6 + tout * po / 1e6


def image_tokens(path):
    try:
        from PIL import Image
        w, h = Image.open(path).size
    except Exception:
        return 2500
    f = min(1.0, 1568 / max(w, h))
    return int(w * f * h * f / 750)


# ---------------------------------------------------------------- one window of the video
