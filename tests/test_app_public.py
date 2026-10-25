"""app.py behind a reverse proxy (the Docker setup): --host, --public-url, --key-file and CONTEXT_NOTES_PLACES."""
import json
import os
import stat
import threading
import urllib.error
import urllib.request

import pytest

import app


@pytest.fixture
def public_server(api, home):
    s = app.make_server(0, api.url, host="127.0.0.1", public_url="https://films.example.com/", token="fixed-key")
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def ask(server, headers, path="/api/info"):
    port = server.server_address[1]
    h = {"X-Key": server.app.token, **headers}
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_the_public_name_is_answered_and_others_refused(public_server):
    port = public_server.server_address[1]
    assert ask(public_server, {"Host": "films.example.com"}) == 200
    assert ask(public_server, {"Host": "films.example.com:443"}) == 200
    assert ask(public_server, {"Host": "films.example.com:8443",                 # any port: the proxy's choice
                               "Origin": "https://films.example.com:8443"}) == 200
    assert ask(public_server, {"Host": "films.example.com", "Origin": "https://films.example.com"}) == 200
    assert ask(public_server, {"Host": f"127.0.0.1:{port}"}) == 200                 # local use still works
    assert ask(public_server, {"Host": "evil.example.com"}) == 403
    assert ask(public_server, {"Host": "films.example.com", "Origin": "https://evil.example.com"}) == 403
    assert ask(public_server, {"Host": "films.example.com", "Origin": "http://films.example.com"}) == 403


def test_the_address_uses_the_public_url_and_the_fixed_key(public_server):
    assert app.address(public_server) == "https://films.example.com/?k=fixed-key"


def test_without_a_public_url_only_this_computer_is_answered(api, home):
    s = app.make_server(0, api.url)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        assert ask(s, {"Host": "films.example.com"}) == 403
        assert ask(s, {"Host": f"127.0.0.1:{s.server_address[1]}"}) == 200
    finally:
        s.shutdown()
        s.server_close()


def test_the_key_file_is_made_once_and_reused(tmp_path):
    path = tmp_path / "keys" / "app-key"
    first = app.load_or_make_key(path)
    assert path.exists() and len(first) > 20
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert app.load_or_make_key(path) == first
    path.write_text("my-own-key\n")
    assert app.load_or_make_key(path) == "my-own-key"


def test_extra_places_from_the_environment(tmp_path, monkeypatch):
    films = tmp_path / "films"
    films.mkdir()
    monkeypatch.setenv("CONTEXT_NOTES_PLACES", str(films) + os.pathsep + str(tmp_path / "missing"))
    labels = {p["label"]: p["path"] for p in app.places()}
    assert labels.get("films") == str(films)
    assert not any(p.endswith("missing") for p in labels.values())


def test_the_command_line_accepts_the_new_flags(tmp_path, monkeypatch):
    seen = {}

    class Fake:
        app = type("A", (), {"job": None, "token": "k", "public_url": "https://films.example.com"})()
        server_address = ("0.0.0.0", 8080)

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    def fake_make_server(port, api_url, host="127.0.0.1", token=None, public_url=None, hosted=False):
        seen.update(port=port, host=host, token=token, public_url=public_url, hosted=hosted)
        return Fake()

    monkeypatch.setattr(app, "make_server", fake_make_server)
    key_file = tmp_path / "app-key"
    assert app.main(["--host", "0.0.0.0", "--port", "8080", "--no-browser", "--public-url",
                     "https://films.example.com", "--key-file", str(key_file)]) == 0
    assert seen == {"port": 8080, "host": "0.0.0.0", "token": key_file.read_text().strip(),
                    "public_url": "https://films.example.com", "hosted": False}
    assert json.dumps(seen)  # serialisable, nothing odd slipped in
