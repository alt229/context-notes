"""Hosted mode (--hosted: the browser is on another computer), the VLC extension download, and the Claude sign-in
token (saved on the server, passed to `claude` as CLAUDE_CODE_OAUTH_TOKEN)."""
import json
import os
import stat
import threading

import pytest
from test_app import call
from test_prompts import drive

import app
import claude_api

TOKEN = "sk-ant-oat01-secret-token-ABCDEF123456"
PROMPT = "Lines to annotate (1 to 3):\n1 [0:00:03] Line one of the test\n2 [0:00:09] Line two of the test\n3 [0:00:15] Three"
LUA = app.HERE / "vlc" / "context_notes.lua"


def start(api, **kw):
    s = app.make_server(0, api.url, **kw)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


@pytest.fixture
def server(api, home):
    s = start(api)
    yield s
    s.shutdown()
    s.server_close()


@pytest.fixture
def hosted(api, home):
    s = start(api, hosted=True)
    yield s
    s.shutdown()
    s.server_close()


def token_file(home):
    return home / ".config" / "context-notes" / "claude-code-token"


# ---------------------------------------------------------------- hosted mode
def test_hosted_info_hides_this_computers_features(hosted, server):
    info = call(hosted, "/api/info")[1]
    assert info["hosted"] is True and info["dialogs"] is False and info["vlc"] == []
    assert call(server, "/api/info")[1]["hosted"] is False


@pytest.mark.parametrize("path,body", [("/api/vlc/install", {}), ("/api/vlc/open", {"path": "/x.mkv"}),
                                       ("/api/reveal", {"path": "/x.mkv"}), ("/api/pick", {"kind": "file"})])
def test_hosted_refuses_what_acts_on_the_server(hosted, path, body, monkeypatch):
    monkeypatch.setattr(app, "open_detached", lambda cmd: pytest.fail("opened something on the server"))
    status, r = call(hosted, path, body)
    assert status == 400 and r == {"error": "Not available when the app runs on another computer."}
    assert call(hosted, path, body, key=False)[0] == 403              # the key is still checked first


def test_local_mode_still_answers_those_four(server, home, tmp_path, monkeypatch):
    monkeypatch.setattr(app, "pick", lambda kind: {"cancelled": True})
    monkeypatch.setattr(app, "open_detached", lambda cmd: None)
    assert call(server, "/api/pick", {"kind": "file"}) == (200, {"cancelled": True})
    assert call(server, "/api/vlc/install", {})[1]["ok"]
    missing = str(tmp_path / "gone.mkv")
    for path in ("/api/vlc/open", "/api/reveal"):
        status, r = call(server, path, {"path": missing})
        assert status == 200 and not r["ok"] and "isn't there" in r["message"]


def test_the_command_line_has_hosted(monkeypatch):
    seen = {}

    class Fake:
        app = type("A", (), {"job": None, "token": "k", "public_url": None})()
        server_address = ("127.0.0.1", 1)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(app, "make_server", lambda *a, **kw: seen.update(kw) or Fake())
    assert app.main(["--no-browser", "--hosted"]) == 0 and seen["hosted"] is True
    assert app.main(["--no-browser"]) == 0 and seen["hosted"] is False


# ---------------------------------------------------------------- the VLC extension download
def test_the_extension_downloads_with_the_key_in_the_address(server):
    status, text, headers = call(server, f"/api/vlc/extension?k={server.app.token}", key=False, raw=True)
    assert status == 200 and text.encode() == LUA.read_bytes()
    assert headers["Content-Disposition"] == 'attachment; filename="context_notes.lua"'
    assert headers["Content-Type"].startswith("text/x-lua")
    assert call(server, "/api/vlc/extension", raw=True)[0] == 200                  # the header works too


def test_the_extension_needs_the_key_and_the_right_host(server):
    assert call(server, "/api/vlc/extension", key=False, raw=True)[0] == 403
    assert call(server, "/api/vlc/extension?k=wrong", key=False, raw=True)[0] == 403
    bad_host = call(server, f"/api/vlc/extension?k={server.app.token}", key=False, raw=True,
                    headers={"Host": "evil.example.com"})
    assert bad_host[0] == 403 and "Lua" not in bad_host[1]
    assert call(server, f"/api/vlc/extension?k={server.app.token}", key=False, raw=True,
                headers={"Origin": "https://evil.example.com"})[0] == 403
    # the key in the address opens nothing else
    assert call(server, f"/api/info?k={server.app.token}", key=False)[0] == 403


# ---------------------------------------------------------------- the Claude sign-in token
def test_saving_and_removing_the_token(server, home):
    status, r = call(server, "/api/claude/token", {"token": f"  {TOKEN}\n"})
    assert status == 200 and r["ok"] and TOKEN not in json.dumps(r)
    f = token_file(home)
    assert f.read_text() == TOKEN + "\n"
    assert stat.S_IMODE(f.stat().st_mode) == 0o600 and stat.S_IMODE(f.parent.stat().st_mode) == 0o700
    assert not [p for p in f.parent.iterdir() if p.name.startswith(".claude-code-token")]      # no temp file left
    info_text = json.dumps(call(server, "/api/info")[1])
    assert TOKEN not in info_text and call(server, "/api/info")[1]["claude_code"]["token_saved"] is True
    assert claude_api.load_claude_token() == TOKEN
    status, r = call(server, "/api/claude/token", {"token": "  "})
    assert status == 200 and r["ok"] and not f.exists()
    assert call(server, "/api/info")[1]["claude_code"]["token_saved"] is False
    assert claude_api.load_claude_token() is None
    assert call(server, "/api/claude/token", {"token": ""})[1]["ok"]                   # removing nothing is fine


def test_token_endpoint_checks_and_refuses_junk(server, home):
    assert call(server, "/api/claude/token", {"token": TOKEN}, key=False)[0] == 403
    assert call(server, "/api/claude/status", {}, key=False)[0] == 403
    _, r = call(server, "/api/claude/token", {"token": "two words"})
    assert not r["ok"] and not token_file(home).exists() and "two words" not in json.dumps(r)


def test_status_follows_the_sign_in(server, home, fake_claude, monkeypatch):
    status, r = call(server, "/api/claude/status", {})
    assert status == 200 and r["signed_in"] is False and r["method"] is None and r["message"] == "Not signed in."
    monkeypatch.setenv("FAKE_CLAUDE_LOGGED_IN", "1")
    r = call(server, "/api/claude/status", {})[1]
    assert r["signed_in"] is True and r["method"] == "claude.ai" and "claude.ai" in r["message"]
    monkeypatch.delenv("FAKE_CLAUDE_LOGGED_IN")
    call(server, "/api/claude/token", {"token": TOKEN})                    # a saved token counts
    r = call(server, "/api/claude/status", {})[1]
    assert r["signed_in"] is True and TOKEN not in json.dumps(r)


def test_status_when_claude_code_is_missing(server, home, monkeypatch):
    monkeypatch.setenv("PATH", str(home))
    r = call(server, "/api/claude/status", {})[1]
    assert r["signed_in"] is False and r["installed"] is False and "isn't installed" in r["message"]


def test_the_saved_token_goes_to_claude_in_the_environment(home, fake_claude, tmp_path, monkeypatch):
    claude_api.call_claude_code("m", "SYSTEM", PROMPT,
                                workdir=tmp_path)
    assert fake_claude.calls[-1]["oauth_token"] is None
    claude_api.set_claude_token(TOKEN)
    claude_api.call_claude_code("m", "SYSTEM", PROMPT,
                                workdir=tmp_path)
    assert fake_claude.calls[-1]["oauth_token"] == TOKEN
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "from-the-environment")           # an existing one wins
    claude_api.call_claude_code("m", "SYSTEM", PROMPT,
                                workdir=tmp_path)
    assert fake_claude.calls[-1]["oauth_token"] == "from-the-environment"


def test_set_claude_token_on_the_command_line(home, tmp_path):
    code, out, events = drive(["--set-claude-token"], {"claude-code-token": TOKEN}, tmp_path, home, script="make_ass.py")
    assert code == 0, out
    assert any(e.get("id") == "claude-code-token" and e.get("hidden") for e in events)
    assert token_file(home).read_text() == TOKEN + "\n" and TOKEN not in out
    assert stat.S_IMODE(token_file(home).stat().st_mode) == 0o600
    code, out, _ = drive(["--set-claude-token"], {}, tmp_path, home, script="make_ass.py")     # empty: remove
    assert code == 0 and not token_file(home).exists() and "Removed" in out


def test_an_interrupted_save_leaves_the_old_token(home, monkeypatch):
    claude_api.set_claude_token("first-token")
    def boom(*a, **k):
        raise OSError("disk full")
    with monkeypatch.context() as m:
        m.setattr(os, "fdopen", boom)
        with pytest.raises(OSError):
            claude_api.set_claude_token("second-token")
    assert claude_api.load_claude_token() == "first-token"
