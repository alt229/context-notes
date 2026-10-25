"""Shared fixtures: sample subtitles, an isolated HOME, and a local stand-in for the Claude API."""
import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg/ffprobe not installed")


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def make_srt(path, n=24, spacing=6.0, length=2.5, first=3.0, text="Line {i} of the original test script"):
    blocks = []
    for i in range(1, n + 1):
        start = first + spacing * (i - 1)
        blocks.append(f"{i}\n{srt_time(start)} --> {srt_time(start + length)}\n{text.format(i=i)}\n")
    Path(path).write_text("\n".join(blocks), encoding="utf-8")
    return Path(path)


@pytest.fixture
def sample_srt(tmp_path):
    return make_srt(tmp_path / "show.srt")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty HOME, so tests never touch (or read) the real API key."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CONTEXT_NOTES_UI", raising=False)     # tests choose the GUI mode themselves
    return h


def run_cli(script, *args, cwd=None, home_dir=None, stdin=None, env_extra=None):
    """Run one of the scripts as a user would, returning the CompletedProcess."""
    import os
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("CONTEXT_NOTES_UI", None)                         # tests choose the GUI mode themselves (env_extra)
    if home_dir:
        env["HOME"] = str(home_dir)
        env.pop("XDG_CONFIG_HOME", None)
    env.update(env_extra or {})
    # start_new_session: no terminal attached. Otherwise a hidden prompt (getpass) reads the real terminal you ran
    # pytest in, not `stdin`, and the test waits for you to type.
    return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)], cwd=cwd, env=env,
                          input=stdin, capture_output=True, text=True, timeout=300, start_new_session=True)


def message(text, stop_reason="end_turn", usage=(1000, 200)):
    return {"type": "message", "id": "msg_test", "model": "test", "stop_reason": stop_reason,
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": usage[0], "output_tokens": usage[1]}}


class FakeApi:
    """A local HTTP server that speaks just enough of the Messages API.

    Set `.responder = fn(call_number, request_body, headers) -> (status, payload_dict[, headers_dict])`.
    Every request is recorded in `.calls`.
    """

    def __init__(self):
        self.calls = []
        self.responder = lambda n, body, headers: (200, message("[]"))
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                api.calls.append({"body": body, "headers": {k.lower(): v for k, v in self.headers.items()}})
                out = api.responder(len(api.calls), body, self.headers)
                status, payload = out[0], out[1]
                self.send_response(status)
                for k, v in (out[2] if len(out) > 2 else {}).items():
                    self.send_header(k, v)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/messages"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api():
    server = FakeApi()
    yield server
    server.close()


@pytest.fixture(autouse=True)
def _claude_runs_where_the_test_says(monkeypatch):
    """A developer's own backend setting and `claude` path never leak into a test."""
    monkeypatch.delenv("CONTEXT_NOTES_BACKEND", raising=False)
    monkeypatch.delenv("CONTEXT_NOTES_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("FAKE_CLAUDE_FAIL", raising=False)


class FakeClaude:
    """The stand-in `claude` command (tests/fake_claude.py), installed for one test. `calls` is what it was given:
    one dict per run with "argv", "prompt" and "cwd". fail(mode) makes the next runs fail ("limit", "login",
    "limit-after-N"; see fake_claude.py)."""

    def __init__(self, exe, log, monkeypatch):
        self.exe, self.log, self._mp = exe, log, monkeypatch

    @property
    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(ln) for ln in self.log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def fail(self, mode):
        self._mp.setenv("FAKE_CLAUDE_FAIL", mode)


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    """tests/fake_claude.py, copied to a temporary folder as an executable called `claude`, with
    CONTEXT_NOTES_CLAUDE_BIN pointing at it (so claude_api finds it, in this process and in the scripts it runs)."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    exe = bin_dir / "claude"
    source = (ROOT / "tests" / "fake_claude.py").read_text(encoding="utf-8").split("\n", 1)[1]
    exe.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")       # this Python, wherever `python3` points
    exe.chmod(0o755)
    log = tmp_path / "fake-claude-calls.jsonl"
    monkeypatch.setenv("CONTEXT_NOTES_CLAUDE_BIN", str(exe))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    return FakeClaude(exe, log, monkeypatch)


@pytest.fixture
def api_key_file(home):
    """A valid-looking key stored where the scripts look for it."""
    path = home / ".config" / "context-notes" / "api-key"
    path.parent.mkdir(parents=True)
    path.write_text("sk-ant-test-key-1234\n")
    path.chmod(0o600)
    return path
