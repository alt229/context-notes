#!/usr/bin/env python3
"""
tmdb.py - your TMDB (themoviedb.org) key: save it, test it, and ask TMDB things with it.
Created 2026-11-04, modified 2026-11-04.

    python3 tmdb.py --set-key     once: save your TMDB key (asked for hidden, never on the command line) and test it
    python3 tmdb.py --test        check the saved key works

TMDB gives film and show titles in other languages, episode titles and air dates, for the library cleanup. A free
account at https://www.themoviedb.org/signup, then https://www.themoviedb.org/settings/api: either the "API Key"
(32 letters and digits) or the longer "API Read Access Token" works; paste one.

The key is kept in ~/.config/context-notes/tmdb.json, readable only by you. Testing sends only the key.
"""
import argparse
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request

import fileio
import prompts  # the questions (and on Windows, lets a GUI's Cancel stop this script cleanly)

API = os.environ.get("CONTEXT_NOTES_TMDB_API") or "https://api.themoviedb.org/3"   # tests: a stand-in
SIGN_UP = "https://www.themoviedb.org/settings/api"
AGENT = "context-notes"


def say(msg=""):
    print(msg, flush=True)


def config_path():
    return fileio.config_dir() / "tmdb.json"


def is_token(key):
    """The API Read Access Token (a JWT, sent as a Bearer header) rather than the short API key (a query parameter)."""
    return key.count(".") == 2


def save(key):
    """Write the key, readable only by this user. Returns the file's path."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"api_key": key}, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def load(quiet=False):
    """The saved key, or None if there isn't one (or it can't be used: says why, unless quiet)."""
    path = config_path()
    if not path.exists():
        return None
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        if not quiet:
            say(f"  ! Not using {path}: other users can read it. Lock it down:  chmod 600 \"{path}\"")
        return None
    try:
        key = (json.loads(path.read_text(encoding="utf-8")) or {}).get("api_key", "")
    except (OSError, ValueError, AttributeError):
        key = ""
    if not isinstance(key, str) or not key.strip():
        if not quiet:
            say(f"  ! {path} has no usable key; run  python3 tmdb.py --set-key  again.")
        return None
    return key.strip()


class TMDBError(RuntimeError):
    """TMDB answered with an HTTP error; `code` is its status (401, 404, 429...)."""
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


class TMDB:
    """A few GET requests to TMDB's API (version 3) with the saved key."""
    def __init__(self, key, api=API, timeout=20):
        self.key, self.api, self.timeout = key, api.rstrip("/"), timeout

    def get(self, path, **params):
        params = {k: v for k, v in params.items() if v is not None}
        headers = {"Accept": "application/json", "User-Agent": AGENT}
        if is_token(self.key):
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        url = f"{self.api}/{path.lstrip('/')}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode("utf-8")).get("status_message") or ""
            except (ValueError, AttributeError, OSError):
                detail = ""
            raise TMDBError(f"TMDB said {e.code}" + (f": {detail}" if detail else ""), e.code) from None
        except (urllib.error.URLError, OSError) as e:
            raise RuntimeError(f"couldn't reach TMDB ({getattr(e, 'reason', e)})") from None
        except ValueError as e:
            raise RuntimeError(f"TMDB didn't answer properly ({e})") from None


def test(key, api=API):
    """Ask TMDB whether the key works. True if it does; says what's wrong if not."""
    if not key:
        say("No TMDB key saved. Save one with:  python3 tmdb.py --set-key")
        return False
    say("Checking the key with TMDB...")
    try:
        TMDB(key, api).get("authentication")
    except TMDBError as e:
        hint = {401: f"TMDB refused the key. Copy it again from {SIGN_UP}",
                429: "Too many tries just now; wait a minute and test again."}.get(e.code, "")
        say(f"  ! The key didn't work. {hint}\n    ({e})")
        if e.code == 401:
            say("    Fix it with:  python3 tmdb.py --set-key")
        return False
    except RuntimeError as e:
        say(f"  ! Couldn't check the key: {e}")
        return False
    say("  OK: TMDB accepted the key.")
    return True


def set_key(api=API):
    """Ask for the key (hidden), save it, test it. True if it works."""
    say(f"You need a free TMDB account and its key from {SIGN_UP}: the \"API Key\" or the \"API Read Access Token\".")
    key = "".join(prompts.secret("TMDB key (hidden): ", id="tmdb.api-key").split())
    if not key:
        sys.exit("Nothing was pasted; nothing saved.")
    path = save(key)
    say(f"Saved to {path} (readable only by you).")
    return test(key, api)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Save and test your TMDB (themoviedb.org) key.")
    ap.add_argument("--set-key", action="store_true", help="save your TMDB key (asked for, hidden), test it and exit")
    ap.add_argument("--test", action="store_true", help="check the saved key works and exit")
    a = ap.parse_args(argv)
    if a.set_key:
        return 0 if set_key() else 1
    if a.test:
        return 0 if test(load()) else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
