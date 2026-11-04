"""tmdb.py: saving and testing the TMDB key, from Terminal and from the app's Settings."""
import json
import os
import stat
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import tmdb

GOOD_KEY = "0123456789abcdef0123456789abcdef"                       # the short API key: a query parameter
GOOD_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ4In0.c2lnbmF0dXJl"     # the Read Access Token: a Bearer header


@pytest.fixture
def fake_tmdb():
    """A stand-in for TMDB that accepts GOOD_KEY (as api_key) and GOOD_TOKEN (as a Bearer header)."""
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            url = urlparse(self.path)
            key = (parse_qs(url.query).get("api_key") or [None])[0]
            auth = self.headers.get("Authorization")
            calls.append((url.path, key, auth))
            ok = key == GOOD_KEY or auth == f"Bearer {GOOD_TOKEN}"
            body = ({"success": True, "status_code": 1, "status_message": "Success."} if ok else
                    {"success": False, "status_code": 7, "status_message": "Invalid API key: You must be granted a valid key."})
            data = json.dumps(body).encode()
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/3", calls
    server.shutdown()


def test_the_short_key_goes_as_a_parameter_and_the_token_as_a_header(fake_tmdb, capsys):
    url, calls = fake_tmdb
    assert tmdb.test(GOOD_KEY, api=url) and tmdb.test(GOOD_TOKEN, api=url)
    assert calls == [("/3/authentication", GOOD_KEY, None), ("/3/authentication", None, f"Bearer {GOOD_TOKEN}")]
    assert "TMDB accepted the key" in capsys.readouterr().out


def test_a_refused_key_says_how_to_fix_it(fake_tmdb, capsys):
    url, _ = fake_tmdb
    assert not tmdb.test("nope", api=url)
    out = capsys.readouterr().out
    assert "TMDB refused the key" in out and "tmdb.py --set-key" in out and "Invalid API key" in out


def test_no_saved_key_says_how_to_save_one(home, capsys):
    assert tmdb.load() is None and not tmdb.test(None)
    assert "tmdb.py --set-key" in capsys.readouterr().out


def test_set_key_saves_it_privately_and_tests_it(home, fake_tmdb, monkeypatch, capsys):
    url, _ = fake_tmdb
    monkeypatch.setattr(tmdb.prompts, "secret", lambda text, id=None: f"  {GOOD_KEY[:16]}\n{GOOD_KEY[16:]} ")  # pasted badly
    assert tmdb.set_key(api=url)
    path = tmdb.config_path()
    assert json.loads(path.read_text(encoding="utf-8")) == {"api_key": GOOD_KEY}
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert tmdb.load() == GOOD_KEY
    assert GOOD_KEY not in capsys.readouterr().out                     # never printed


@pytest.mark.skipif(os.name != "posix", reason="file permissions are a POSIX idea")
def test_a_key_file_others_can_read_isnt_used(home, capsys):
    path = tmdb.save(GOOD_KEY)
    os.chmod(path, 0o644)
    assert tmdb.load() is None
    assert "chmod 600" in capsys.readouterr().out


def test_the_app_saves_and_tests_the_key_without_showing_it(home, fake_tmdb, monkeypatch, api):
    import app
    from test_app import call
    url, _ = fake_tmdb
    monkeypatch.setenv("CONTEXT_NOTES_TMDB_API", url)                   # the tmdb.py the app starts asks the stand-in
    s = app.make_server(0, api.url)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        assert call(s, "/api/info")[1]["tmdb"] == {"saved": False, "ends": None}
        status, r = call(s, "/api/tmdb", {"api_key": ""})
        assert status == 200 and not r["ok"] and "Paste the TMDB key" in r["lines"][0]
        status, r = call(s, "/api/tmdb", {"api_key": GOOD_KEY})
        assert status == 200 and r["ok"], r
        assert r["tmdb"] == {"saved": True, "ends": GOOD_KEY[-4:]}
        assert not any(GOOD_KEY in ln for ln in r["lines"]) and any("accepted" in ln for ln in r["lines"])
        status, r = call(s, "/api/tmdb", {"api_key": "wrong-key"})
        assert not r["ok"] and any("refused" in ln for ln in r["lines"])
        assert r["tmdb"]["saved"]                                          # saved, though TMDB refused it
    finally:
        s.shutdown()
        s.server_close()
