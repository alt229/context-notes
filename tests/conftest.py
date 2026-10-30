"""Shared fixtures: sample subtitles, an isolated HOME, and a local stand-in for the Claude API."""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg/ffprobe not installed")
WINDOWS = os.name == "nt"

# A run in a process group of its own, and the way to stop it as Ctrl-C does: SIGINT to the group, or on Windows
# Ctrl-Break (which the scripts treat as Ctrl-C when a GUI is driving them; see prompts.py). INTERRUPTED: the exit
# codes of a script stopped like that.
NEW_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True}
INTERRUPTED = (0xC000013A, 130) if WINDOWS else (-signal.SIGINT, 130)


def interrupt(p):
    if WINDOWS:
        p.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(p.pid, signal.SIGINT)


def place(src, dest):
    """Put a test video at dest: a symlink where the system allows one, else a copy (Windows needs Developer Mode
    for symlinks)."""
    try:
        os.symlink(src, dest)
    except OSError:
        shutil.copyfile(src, dest)
    return Path(dest)


def assert_private(path, mode=0o600):
    """Only its owner can read it. On Windows a file in your user folder is private already; mode bits mean little."""
    if not WINDOWS:
        assert stat.S_IMODE(Path(path).stat().st_mode) == mode


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


@pytest.fixture(autouse=True)
def usage_dir(tmp_path_factory, monkeypatch):
    """Where usage.py keeps its ledger, credit and session files during a test: a folder of its own (not the test's
    tmp_path, which some tests check for stray files), never the real ones in ~/.config. Subprocesses inherit it."""
    d = tmp_path_factory.mktemp("usage-data")
    monkeypatch.setenv("CONTEXT_NOTES_USAGE_DIR", str(d))
    monkeypatch.delenv("CONTEXT_NOTES_RUN_START", raising=False)   # each test is a run of its own (usage.run_start)
    monkeypatch.setenv("CONTEXT_NOTES_YES_TO_ALL", "")   # off, and undone after a test whose run turns it on
    return d


@pytest.fixture(autouse=True)
def fake_claude(tmp_path_factory, monkeypatch):
    """The real Claude Code is never run by a test: `claude` is tests/fake_claude.py (see there for the FAKE_CLAUDE_*
    switches). Returns the log file it writes one line to per request; calls(log) reads it back."""
    log = tmp_path_factory.mktemp("fake-claude") / "calls.jsonl"
    monkeypatch.setenv("CONTEXT_NOTES_CLAUDE", str(ROOT / "tests" / "fake_claude.py"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    for k in ("FAKE_CLAUDE_MODE", "FAKE_CLAUDE_AUTH", "FAKE_CLAUDE_HELP", "FAKE_CLAUDE_SIGNIN", "FAKE_CLAUDE_LOGIN"):
        monkeypatch.delenv(k, raising=False)
    if "claude_code" in sys.modules:                       # its answers are kept for a run: not across tests
        sys.modules["claude_code"].login_cancel()
        sys.modules["claude_code"]._status.clear()
        sys.modules["claude_code"]._flags.clear()
    return log


def claude_calls(log):
    """The requests fake_claude.py answered, oldest first."""
    try:
        return [json.loads(line) for line in Path(log).read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []


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
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("CONTEXT_NOTES_UI", None)                         # tests choose the GUI mode themselves (env_extra)
    if home_dir:
        env["HOME"] = str(home_dir)
        env.pop("XDG_CONFIG_HOME", None)
    env.update(env_extra or {})
    # start_new_session: no terminal attached. Otherwise a hidden prompt (getpass) reads the real terminal you ran
    # pytest in, not `stdin`, and the test waits for you to type.
    return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)], cwd=cwd, env=env,
                          input=stdin, capture_output=True, encoding="utf-8", errors="replace", timeout=300,
                          start_new_session=not WINDOWS)


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


@pytest.fixture
def api_key_file(home):
    """A valid-looking key stored where the scripts look for it."""
    path = home / ".config" / "context-notes" / "api-key"
    path.parent.mkdir(parents=True)
    path.write_text("sk-ant-test-key-1234\n")
    path.chmod(0o600)
    return path
