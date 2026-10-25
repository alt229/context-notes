"""app.py, the page's local server: who may talk to it, what it shows, and whole runs driven over HTTP."""
import base64
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from conftest import assert_private, make_srt, needs_ffmpeg, place

import app


@pytest.fixture
def server(api, home):
    s = app.make_server(0, api.url)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    job = s.app.job
    if job and job.running:
        job.cancel()
        job.proc.wait(timeout=30)
    s.shutdown()
    s.server_close()


def call(server, path, body=None, key=True, headers=None, raw=False):
    """(status, JSON or text) for one request, as the page would make it."""
    port = server.server_address[1]
    h = {"X-Key": server.app.token} if key else {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=h,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, text, hdrs = r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        status, text, hdrs = e.code, e.read().decode(), e.headers
    if raw:
        return status, text, hdrs
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text


def run_job(server, answers, on_event=None, timeout=180):
    """Poll a run the way the page does, answering questions by id ('' = the default). Returns (state, events, log)."""
    deadline, after, events, texts = time.time() + timeout, 0, [], []
    while time.time() < deadline:
        _, r = call(server, f"/api/job?after={after}")
        for item in r["items"]:
            if "event" in item:
                events.append(item["event"])
                if on_event:
                    on_event(item["event"])
            else:
                texts.append(item["text"])
        after = r["next"]
        if r.get("pending"):
            call(server, "/api/answer", {"answer": answers.get(r["pending"]["id"], "")})
        if not r["running"]:
            return r, events, "\n".join(texts)
        time.sleep(0.1)
    raise AssertionError("the run didn't finish")


# ---------------------------------------------------------------- who may talk to it
def test_only_this_page_with_its_key(server):
    port = server.server_address[1]
    status, text, hdrs = call(server, f"/?k={server.app.token}", key=False, raw=True)
    assert status == 200 and "<title>Context Notes</title>" in text
    assert "default-src 'none'" in hdrs["Content-Security-Policy"] and hdrs["Referrer-Policy"] == "no-referrer"
    assert call(server, "/", key=False)[0] == 403                                       # no key in the address
    assert call(server, "/?k=wrong", key=False)[0] == 403
    assert call(server, "/api/info", key=False)[0] == 403
    assert call(server, "/api/info", headers={"X-Key": "wrong"})[0] == 403
    assert call(server, "/api/info", headers={"Host": f"evil.example:{port}"})[0] == 403    # DNS rebinding
    assert call(server, "/api/cancel", {}, headers={"Origin": "http://evil.example"})[0] == 403   # another site
    assert call(server, "/api/info", headers={"Host": f"localhost:{port}"})[0] == 200
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/cancel", data=b"x", method="POST",
                                 headers={"X-Key": server.app.token, "Content-Type": "text/plain"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 415                                                           # forms can't post here


def test_the_key_never_leaves_the_computer(server, api_key_file):
    status, text, _ = call(server, "/api/info", raw=True)
    info = json.loads(text)
    assert status == 200 and info["key"]["found"] and info["key"]["ends"] == "1234"
    assert "sk-ant-test-key" not in text


def test_saving_a_key(server, home):
    status, r = call(server, "/api/key", {"key": "sk-ant-from-the-page-9876"})
    path = home / ".config" / "context-notes" / "api-key"
    assert status == 200 and r["ok"] and r["key"]["ends"] == "9876", r
    assert path.read_text() == "sk-ant-from-the-page-9876\n"
    assert_private(path)
    assert "sk-ant-from" not in json.dumps(r)
    _, r = call(server, "/api/key", {"key": "hunter2"})
    assert not r["ok"] and "doesn't look like an Anthropic API key" in r["message"]
    assert path.read_text() == "sk-ant-from-the-page-9876\n"


def test_checking_a_key_is_free_and_says_whether_it_works(api_key_file, home):
    seen = []

    class Models(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.path)
            ok = self.headers.get("x-api-key") == "sk-ant-test-key-1234"
            self.send_response(200 if ok else 401)
            self.end_headers()
            self.wfile.write(b'{"data": []}')
    fake = ThreadingHTTPServer(("127.0.0.1", 0), Models)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    try:
        a = app.App(api_url=f"http://127.0.0.1:{fake.server_address[1]}/v1/messages")
        assert a.test_key()["ok"] and seen == ["/v1/models"]                              # lists models; sends nothing
        api_key_file.write_text("sk-ant-wrong\n")
        r = a.test_key()
        assert not r["ok"] and "refused" in r["message"]
    finally:
        fake.shutdown()
        fake.server_close()


# ---------------------------------------------------------------- choosing things
def test_browse_lists_folders_and_videos(server, tmp_path):
    films = tmp_path / "Films"
    (films / "Season 1").mkdir(parents=True)
    (films / ".hidden").mkdir()
    (films / "Film.mkv").write_bytes(b"")
    (films / "notes.txt").write_text("x")
    _, r = call(server, f"/api/browse?path={urllib.request.quote(str(films))}")
    assert r["path"] == str(films)
    assert [d["name"] for d in r["dirs"]] == ["Season 1"] and [v["name"] for v in r["videos"]] == ["Film.mkv"]
    assert r["videos"][0]["path"] == str(films / "Film.mkv")                      # full paths: no joining on the page
    assert any(p["label"] == "Home" for p in r["places"])
    _, r = call(server, f"/api/browse?path={urllib.request.quote(str(films / 'Film.mkv'))}")
    assert r["path"] == str(films)                                                       # a file: its folder
    _, r = call(server, "/api/browse?path=/no/such/place")
    assert r["path"] == str(Path.home())


def test_paths_as_people_paste_them(monkeypatch):
    assert app.clean_path('  "/Movies/Amélie.mkv" ') == Path("/Movies/Amélie.mkv")
    assert app.clean_path("~/Films", where="mac") == Path.home() / "Films"
    assert app.clean_path("") is None
    monkeypatch.setattr(app, "wslpath", lambda p, to_windows: "/mnt/d/Films/Amélie.mkv")
    assert app.clean_path(r"D:\Films\Amélie.mkv", where="wsl") == Path("/mnt/d/Films/Amélie.mkv")
    assert app.clean_path(r"D:\Films\Amélie.mkv", where="mac") == Path(r"D:\Films\Amélie.mkv")
    assert "sudo mount -t drvfs Z: /mnt/z" in app.missing_path_hint(r"Z:\Films", where="wsl")
    assert "File Explorer" in app.missing_path_hint(r"\\10.0.0.98\Movies\x.mkv", where="windows")
    assert app.missing_path_hint("/Users/x/film.mkv", where="mac") is None


def test_windows_drives_in_the_folder_browser(monkeypatch):
    if os.name != "nt":
        assert app.windows_drives() == []                                         # none outside Windows
    monkeypatch.setattr(app, "system", lambda: "windows")
    monkeypatch.setattr(app, "windows_drives", lambda: ["C:\\", "Y:\\"])
    shortcuts = app.places()
    assert {"label": "Y: drive", "path": "Y:\\"} in shortcuts and {"label": "C: drive", "path": "C:\\"} in shortcuts


def test_file_dialogs(monkeypatch):
    assert app.dialog_command("file", where="mac")[0] == "osascript"
    assert "choose folder" in app.dialog_command("folder", where="mac")[2]
    assert app.dialog_command("file", where="wsl")[0] == "powershell.exe"
    script = base64.b64decode(app.dialog_command("folder", where="wsl")[-1]).decode("utf-16-le")
    assert "FolderBrowserDialog" in script
    monkeypatch.setattr(app.shutil, "which", lambda name: None)
    assert app.dialog_command("file", where="linux") is None
    monkeypatch.setattr(app, "system", lambda: "linux")
    assert app.pick("file")["no_dialog"]
    monkeypatch.setattr(app.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None)
    assert app.dialog_command("folder", where="linux")[-1] == "--directory"


def test_the_form_becomes_safe_arguments(tmp_path):
    film = tmp_path / "film.mkv"
    film.write_bytes(b"")
    args = app.common_args({"path": str(film), "film_language": "fr", "limit": "5", "refine": False, "redo": True})
    assert args == [str(film), "--film-language", "fr", "--limit", "300", "--no-refine", "--redo"]
    for bad in ({"path": ""}, {"path": str(tmp_path / "missing.mkv")}, {"path": str(film), "limit": "soon"},
                {"path": str(film), "limit": "-2"}, {"path": str(film), "show": "--yes"}):
        with pytest.raises(app.BadRequest):
            app.common_args(bad)


# ---------------------------------------------------------------- VLC
def test_installing_the_vlc_extension(server, home):
    _, r = call(server, "/api/vlc/install", {})
    assert r["ok"] and r["vlc"] and all(v["current"] for v in r["vlc"]), r
    installed = Path(r["paths"][0])
    assert installed.read_bytes() == (app.HERE / "vlc" / "context_notes.lua").read_bytes()
    assert str(installed).startswith(str(home))


def test_opening_in_vlc(monkeypatch, tmp_path):
    video = tmp_path / "film.mkv"
    video.write_bytes(b"")
    monkeypatch.setattr(app.shutil, "which", lambda name: None)
    cmd, why = app.vlc_command(video, where="linux")
    assert cmd is None and "VLC isn't installed" in why
    monkeypatch.setattr(app.shutil, "which", lambda name: "/usr/bin/vlc" if name == "vlc" else None)
    assert app.vlc_command(video, where="linux")[0] == ["/usr/bin/vlc", str(video)]
    (tmp_path / "film.notes.ass").write_text("")
    assert app.vlc_command(video, where="linux")[0] == ["/usr/bin/vlc", f"--sub-file={tmp_path / 'film.notes.ass'}", str(video)]
    assert app.reveal_command(video, where="mac") == ["open", "-R", str(video)]


# ---------------------------------------------------------------- whole runs, as the page drives them
np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from test_refine_notes import make_video  # noqa: E402


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "synced.mp4"
    make_video(path)
    return path


@pytest.fixture
def episode(tmp_path, clip):
    folder = tmp_path / "Show" / "Season 1"
    folder.mkdir(parents=True)
    place(clip, folder / "S01E01 Pilot.mp4")
    return folder


@needs_ffmpeg
def test_status_of_a_folder(server, episode):
    make_srt(episode / "S01E01 Pilot.srt", n=24)
    _, r = call(server, "/api/status", {"path": str(episode)})
    (v,) = r["videos"]
    assert v["name"] == "S01E01 Pilot.mp4" and not v["done"] and v["notes"] == 0 and v["subtitles"] == "S01E01 Pilot.srt"
    _, r = call(server, "/api/status", {"path": str(episode / "nothing here")})
    assert "Can't find" in r["error"]


@needs_ffmpeg
def test_a_whole_run_from_the_page(server, api, api_key_file, episode):
    from test_context_notes import both
    make_srt(episode / "S01E01 Pilot.srt", n=24)
    api.responder = both
    status, r = call(server, "/api/run", {"path": str(episode), "quality": "cheaper"})
    assert status == 200 and r["ok"], r
    assert call(server, "/api/run", {"path": str(episode)})[0] == 409                    # one run at a time
    state, events, log = run_job(server, {"generate.send": "y", "refine.send": "y", "alignment.check": "n"})
    assert state["returncode"] == 0 and not state["cancelled"], log
    assert [e["result"] for e in events if e["type"] == "video-result"] == ["ready"]
    assert {e["id"] for e in events if e["type"] == "question"} == {"generate.send", "refine.send", "alignment.check"}
    assert (episode / "S01E01 Pilot.notes.ass").exists()
    assert {c["body"]["model"] for c in api.calls} == {"claude-sonnet-5-5"}             # "Cheaper"
    _, r = call(server, "/api/status", {"path": str(episode)})
    assert r["videos"][0]["done"] and r["videos"][0]["refined"] == "yes"


@needs_ffmpeg
def test_cancel_while_a_question_waits(server, api, api_key_file, episode):
    """Cancel while the cost question is on screen: on Windows the script is stuck reading the answer, so the app
    also sends it an empty line. Either way it stops, and nothing is sent."""
    make_srt(episode / "S01E01 Pilot.srt", n=24)
    call(server, "/api/run", {"path": str(episode)})
    deadline = time.time() + 120
    while time.time() < deadline:
        _, r = call(server, "/api/job?after=0")
        if (r.get("pending") or {}).get("id") == "generate.send":
            break
        assert r["running"], "\n".join(i.get("text", "") for i in r["items"])
        time.sleep(0.1)
    assert call(server, "/api/cancel", {})[1] == {"ok": True}
    state, _, log = run_job(server, {}, timeout=60)
    assert state["cancelled"] and state["returncode"] != 0 and not api.calls, log


@needs_ffmpeg
def test_cancel_from_the_page(server, api, api_key_file, episode):
    from test_context_notes import both
    from test_progress_and_cancel import LONG, held_after_first
    make_srt(episode / "S01E01 Pilot.srt", n=24, text=LONG)
    gate = threading.Event()
    api.responder = held_after_first(both, gate)
    call(server, "/api/run", {"path": str(episode)})
    sent = []

    def on_event(ev):
        if ev["type"] == "progress" and ev["task"] == "generate" and ev["done"] == 1 and not sent:
            sent.append(call(server, "/api/cancel", {})[1])
    try:
        state, _, log = run_job(server, {"generate.send": "y"}, on_event=on_event)
    finally:
        gate.set()
    assert sent == [{"ok": True}] and state["cancelled"] and state["returncode"] == 130, log
    assert (episode / "context-notes" / "S01E01 Pilot.mp4" / "notes-S01E01 Pilot.partial.json").exists()
    assert {c["body"]["model"] for c in api.calls} == {"claude-opus-5-5"}               # "Best" is the default


def test_tidy_lists_then_moves(server, tmp_path):
    from test_workfiles import old_film
    films = tmp_path / "Films"
    old_film(films)
    code, r = call(server, "/api/tidy", {"path": str(films)})
    assert code == 200 and r["ok"] and r["done"] is None, r
    assert [v["video"] for v in r["videos"]] == [str(films / "Film.mkv")] and len(r["videos"][0]["items"]) == 7
    assert {"from": "Film analysis", "to": "analysis", "folder": True} in r["videos"][0]["items"]
    assert (films / "notes-Film.json").exists()                                    # listing moves nothing
    code, r = call(server, "/api/tidy", {"path": str(films), "move": True})
    assert code == 200 and r["done"] == {"type": "tidy-done", "v": 1, "moved": 7, "problems": []}, r
    assert (films / "context-notes" / "Film.mkv" / "notes-Film.json").exists()
    code, r = call(server, "/api/tidy", {"path": str(films / "nowhere")})
    assert code == 400 and "Choose a film or a folder" in r["error"]
