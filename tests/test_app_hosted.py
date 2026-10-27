"""app.py --hosted: devices on your own network may use the app; what only works on the Mac itself stays there."""
import os
import stat
import threading
import urllib.error
import urllib.request

import pytest
from conftest import WINDOWS

import app


@pytest.mark.parametrize("client, local, hosted", [
    ("127.0.0.1", True, True), ("::1", True, True), ("::ffff:127.0.0.1", True, True),
    ("192.168.1.20", False, True), ("::ffff:192.168.1.20", False, True), ("10.0.0.5", False, True),
    ("172.20.1.1", False, True), ("100.64.3.4", False, True), ("169.254.1.1", False, True),
    ("fd12:3456::1", False, True), ("fe80::1%en0", False, True),
    ("172.32.0.1", False, False), ("8.8.8.8", False, False), ("2001:db8::1", False, False), ("junk", False, False),
])
def test_who_may_connect(client, local, hosted):
    assert app.Access("local").client_ok(client) is local
    assert app.Access("hosted").client_ok(client) is hosted
    assert app.Access("public").client_ok(client) is True


def test_an_allowed_range_is_added():
    a = app.Access("hosted", ["203.0.113.0/24"])
    assert a.client_ok("203.0.113.9") and not a.client_ok("203.0.114.9")
    with pytest.raises(Exception):
        app.network_arg("not a range")


def test_the_host_header_is_an_address_or_this_computers_name():
    a = app.Access("hosted")
    name = sorted(app.own_names() - {"localhost"})[0] if len(app.own_names()) > 1 else "localhost"
    for host in ("192.168.1.5:8229", "[fe80::1]:8229", "localhost:8229", f"{name}:8229"):
        assert a.host_ok(host, 8229), host
    for host in ("evil.example:8229", "192.168.1.5:9999", "192.168.1.5", "[::1]"):
        assert not a.host_ok(host, 8229), host
    assert app.Access("public").host_ok("notes.example.com", 443)


@pytest.fixture
def hosted(api, home, monkeypatch):
    """A --hosted server, and a switch that makes its requests look like they come from another device."""
    s = app.make_server(0, api.url, "hosted", (), "k" * 32)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def ask(server, path, body=None, host=None, query_key=False):
    import json
    port = server.server_address[1]
    h = {} if query_key else {"X-Key": server.app.token}
    if host:
        h["Host"] = host
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=h,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def test_on_this_computer_everything_works(hosted):
    import json
    status, body, _ = ask(hosted, "/api/info")
    info = json.loads(body)
    assert status == 200 and info["local"] is True and info["mode"] == "hosted"
    assert ask(hosted, "/api/key", {"key": ""})[0] == 200                        # answered (the key is refused, not the asking)


def test_from_another_device_the_mac_only_actions_are_refused(hosted, monkeypatch, tmp_path):
    import json
    monkeypatch.setattr(app.Access, "loopback", staticmethod(lambda client: False))    # as if from a phone
    info = json.loads(ask(hosted, "/api/info")[1])
    assert info["local"] is False
    for path, body in (("/api/key", {"key": "sk-ant-x"}), ("/api/opensubtitles", {}), ("/api/pick", {}),
                       ("/api/vlc/install", {}), ("/api/vlc/open", {"path": str(tmp_path)}),
                       ("/api/reveal", {"path": str(tmp_path)}),
                       ("/api/backups", {"path": str(tmp_path), "go": True})):
        status, body, _ = ask(hosted, path, body)
        assert status == 403 and b"only works in a browser on the computer running the app" in body, path
    assert ask(hosted, "/api/backups", {"path": str(tmp_path)})[0] != 403          # listing them is fine
    assert ask(hosted, "/api/settings", {"recursive": True})[0] == 200
    status, body, headers = ask(hosted, f"/api/vlc/extension?k={hosted.app.token}", query_key=True)
    assert status == 200 and b"context" in body.lower() and "context_notes.lua" in headers["Content-Disposition"]
    assert ask(hosted, "/api/vlc/extension?k=wrong", query_key=True)[0] == 403


def test_a_made_up_name_for_this_computer_is_refused(hosted):
    port = hosted.server_address[1]
    assert ask(hosted, "/api/info", host=f"evil.example:{port}")[0] == 403        # DNS rebinding
    assert ask(hosted, "/api/info", host=f"192.168.1.5:{port}")[0] == 200


def test_the_key_is_kept_and_only_yours(home):
    first = app.app_key()
    assert app.app_key() == first and len(first) >= 20
    path = app.fileio.config_dir() / "app-key"
    if not WINDOWS:
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert app.app_key(new=True) != first


def test_the_start_message_gives_the_addresses_to_use(hosted, monkeypatch):
    monkeypatch.setattr(app, "lan_addresses", lambda: ["192.168.1.5"])
    text = app.hosted_message(hosted, app.address(hosted), "hosted")
    port, key = hosted.server_address[1], hosted.app.token
    assert f"From another device: http://192.168.1.5:{port}/?k={key}" in text and "only work in a browser" in text


def test_the_command_line(capsys):
    with pytest.raises(SystemExit):
        app.main(["--allow", "10.8.0.0/24"])                                     # --allow goes with --hosted
    assert "--allow and --new-key go with --hosted" in capsys.readouterr().err
