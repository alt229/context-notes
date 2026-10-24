#!/usr/bin/env python3
"""
app.py - Context Notes in your web browser, on this computer only.

    python3 app.py                   start it and open the page in your browser
    python3 app.py --no-browser      only print the page's address
    python3 app.py --port 8765       use this port (default: any free one)

The page runs the same scripts as Terminal (context_notes.py and the rest, as described in docs/gui-protocol.md). It
asks the same questions and shows the same cost estimate before anything is sent. Press Ctrl-C here to stop it.

Only this computer can reach it: it listens on 127.0.0.1, and every request must carry the random key in the address
it prints. Standard library only.
"""
import argparse
import hmac
import json
import os
import platform
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import analyze  # noqa: E402  (the video file types)
import find_subs  # noqa: E402  (where the OpenSubtitles login lives)
import generate_notes  # noqa: E402  (where the API key lives)
import languages  # noqa: E402
import make_ass  # noqa: E402
import prompts  # noqa: E402

PAGE = HERE / "gui" / "index.html"
QUALITY = {"best": ["--model", "claude-opus-5-5", "--effort", "high"],
           "cheaper": ["--model", "claude-sonnet-5-5", "--effort", "high"]}
TEXT_OPTIONS = (("film_language", "--film-language"), ("subs_language", "--subs-language"),
                ("show_subs", "--show-subs"), ("show", "--show"), ("title", "--title"),
                ("notes_language", "--notes-language"))
WINDOWS_PATH = re.compile(r"^(?:[a-zA-Z]:[\\/]|\\\\)")
MAX_BODY = 1 << 20


# ---------------------------------------------------------------- this computer
def system():
    """'mac', 'linux', 'wsl' (Linux inside Windows) or 'windows'."""
    if sys.platform == "darwin":
        return "mac"
    if os.name == "nt":
        return "windows"
    if "microsoft" in platform.release().lower() or os.environ.get("WSL_DISTRO_NAME"):
        return "wsl"
    return "linux"


def wslpath(path, to_windows):
    """Convert between a Windows path and its WSL one ('C:\\Films' <-> '/mnt/c/Films'); None if it can't."""
    try:
        r = subprocess.run(["wslpath", "-w" if to_windows else "-u", str(path)], capture_output=True, text=True,
                           timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None


_windows_env = {}


def windows_env(name):
    """A Windows environment variable (USERPROFILE, APPDATA) as a WSL path, or None."""
    if name not in _windows_env:
        value = None
        try:
            r = subprocess.run(["cmd.exe", "/c", "echo", f"%{name}%"], capture_output=True, text=True, timeout=15,
                               cwd="/mnt/c" if os.path.isdir("/mnt/c") else None)
            raw = r.stdout.strip()
            if r.returncode == 0 and raw and "%" not in raw:
                value = wslpath(raw, to_windows=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
        _windows_env[name] = value
    return _windows_env[name]


def clean_path(text, where=None):
    """A path as typed or pasted: quotes trimmed, ~ expanded; in WSL a Windows path (C:\\Films) becomes /mnt/c/Films."""
    s = (text or "").strip().strip('"').strip("'").strip()
    if not s:
        return None
    if (where or system()) == "wsl" and WINDOWS_PATH.match(s):
        s = wslpath(s, to_windows=False) or s
    return Path(os.path.expanduser(s))


def missing_path_hint(text, where=None):
    """Why a path can't be found, when there's something more useful to say than 'not found'."""
    if (where or system()) == "wsl" and (WINDOWS_PATH.match(text.strip().strip('"')) or text.startswith("/mnt/")):
        return ("Windows network drives (like Z: or \\\\nas\\films) aren't visible inside WSL until you mount them, "
                "for example:  sudo mkdir -p /mnt/z && sudo mount -t drvfs Z: /mnt/z")
    return None


def places():
    """Shortcuts for the folder browser."""
    home, where, out = Path.home(), system(), []

    def add(label, path):
        if path and Path(path).is_dir() and str(path) not in [p["path"] for p in out]:
            out.append({"label": label, "path": str(path)})
    add("Home", home)
    for name in ("Movies", "Videos", "Desktop", "Downloads"):
        add(name, home / name)
    if where == "mac":
        for vol in sorted(Path("/Volumes").glob("*")) if Path("/Volumes").is_dir() else []:
            add(vol.name, vol)
    elif where == "wsl":
        profile = windows_env("USERPROFILE")
        add("Windows home", profile)
        if profile:
            add("Windows videos", Path(profile) / "Videos")
        for drive in sorted(Path("/mnt").glob("?")):
            add(f"{drive.name.upper()}: drive", drive)
    else:
        for root in (Path("/media") / home.name, Path("/run/media") / home.name, Path("/mnt")):
            for d in sorted(root.glob("*")) if root.is_dir() else []:
                add(d.name, d)
    return out


def browse(text):
    """Folders and videos in a folder, for the page's own folder browser."""
    p = clean_path(text) if text else Path.home()
    if p is None or not p.exists():
        p = Path.home()
    if p.is_file():
        p = p.parent
    try:
        entries = sorted(p.iterdir(), key=lambda e: e.name.lower())
    except OSError as e:
        return {"path": str(p), "parent": str(p.parent), "dirs": [], "videos": [], "places": places(),
                "error": f"Can't open this folder: {e.strerror or e}"}
    dirs, videos = [], []
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            if e.is_dir():
                dirs.append(e.name)
            elif e.suffix.lower() in analyze.VIDEO_EXTS:
                videos.append(e.name)
        except OSError:
            continue
    return {"path": str(p), "parent": str(p.parent) if p.parent != p else None, "dirs": dirs, "videos": videos,
            "places": places()}


POWERSHELL_FILE = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = 'Choose a video'
$d.Filter = 'Videos|*.mkv;*.mp4;*.m4v;*.avi;*.mov;*.webm;*.ts|All files|*.*'
if ($d.ShowDialog($owner) -eq 'OK') { [Console]::Out.Write($d.FileName) }
"""
POWERSHELL_FOLDER = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Choose a folder of videos'
if ($d.ShowDialog($owner) -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }
"""


def dialog_command(kind, where=None):
    """The command that shows this computer's own file dialog, or None if there isn't one."""
    where = where or system()
    folder = kind == "folder"
    if where == "mac":
        what = 'choose folder with prompt "Choose a folder of videos"' if folder else 'choose file with prompt "Choose a video"'
        return ["osascript", "-e", f"POSIX path of ({what})"]
    if where in ("wsl", "windows"):
        exe = "powershell.exe" if where == "wsl" or shutil.which("powershell.exe") else "powershell"
        return [exe, "-NoProfile", "-STA", "-Command", POWERSHELL_FOLDER if folder else POWERSHELL_FILE]
    if shutil.which("zenity"):
        return ["zenity", "--file-selection", "--title", "Choose a folder of videos" if folder else "Choose a video",
                *(["--directory"] if folder else [])]
    if shutil.which("kdialog"):
        return ["kdialog", "--getexistingdirectory" if folder else "--getopenfilename", str(Path.home())]
    return None


def pick(kind):
    """Show the file dialog. Returns {'path': ...}, {'cancelled': True} or {'error': ..., 'no_dialog': True}."""
    cmd = dialog_command(kind)
    if not cmd:
        return {"error": "This computer has no file dialog the page can use (on Linux, install zenity). "
                         "Use Browse instead.", "no_dialog": True}
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": f"The file dialog didn't open ({e}). Use Browse instead.", "no_dialog": True}
    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        return {"cancelled": True}
    if system() == "wsl":
        out = wslpath(out, to_windows=False) or out
    return {"path": out}


# ---------------------------------------------------------------- settings
def key_info():
    """Whether there's an API key, and its last four characters. The key itself never leaves this process."""
    path = generate_notes.key_path()
    info = {"file": str(path), "found": False, "ends": None, "source": None, "problem": None}
    if path.exists():
        try:
            if os.name == "posix" and path.stat().st_mode & 0o077:
                info["problem"] = f"Other people on this computer can read the key file. Fix it with:  chmod 600 \"{path}\""
            key = path.read_text().strip()
        except OSError as e:
            info["problem"] = f"Can't read the key file: {e.strerror or e}"
            return info
        if key:
            info.update(found=True, ends=key[-4:], source="file")
        else:
            info["problem"] = "The key file is empty."
    elif os.environ.get("ANTHROPIC_API_KEY", "").strip():
        info.update(found=True, ends=os.environ["ANTHROPIC_API_KEY"].strip()[-4:], source="environment")
    return info


def opensubtitles_info():
    path = find_subs.os_config_path()
    try:
        cfg = json.loads(path.read_text()) if path.exists() else None
    except (OSError, ValueError):
        cfg = None
    return {"saved": bool(cfg), "username": (cfg or {}).get("username")}


def vlc_extension_dirs():
    """Where VLC looks for extensions on this computer (more than one on Linux when VLC is also a Flatpak or Snap)."""
    home, where = Path.home(), system()
    if where == "mac":
        return [home / "Library" / "Application Support" / "org.videolan.vlc" / "lua" / "extensions"]
    if where == "wsl":
        appdata = windows_env("APPDATA")
        return [Path(appdata) / "vlc" / "lua" / "extensions"] if appdata else []
    if where == "windows":
        return [Path(os.environ["APPDATA"]) / "vlc" / "lua" / "extensions"] if os.environ.get("APPDATA") else []
    dirs = [home / ".local" / "share" / "vlc" / "lua" / "extensions"]
    if (home / ".var" / "app" / "org.videolan.VLC").is_dir():
        dirs.append(home / ".var" / "app" / "org.videolan.VLC" / "data" / "vlc" / "lua" / "extensions")
    if (home / "snap" / "vlc").is_dir():
        dirs.append(home / "snap" / "vlc" / "current" / ".local" / "share" / "vlc" / "lua" / "extensions")
    return dirs


def vlc_info():
    ours = (HERE / "vlc" / "context_notes.lua").read_bytes()
    out = []
    for d in vlc_extension_dirs():
        f = d / "context_notes.lua"
        out.append({"path": str(f), "installed": f.exists(), "current": f.exists() and f.read_bytes() == ours})
    return out


def install_vlc_extension():
    src = HERE / "vlc" / "context_notes.lua"
    dirs = vlc_extension_dirs()
    if not dirs:
        return {"ok": False, "message": "Couldn't work out where VLC keeps its extensions on this computer."}
    done = []
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            with make_ass.replacing(d / src.name) as tmp:
                shutil.copyfile(src, tmp)
            done.append(str(d / src.name))
        except OSError as e:
            return {"ok": False, "message": f"Couldn't copy it to {d}: {e.strerror or e}"}
    return {"ok": True, "message": "Installed. Restart VLC, then choose View > Context Notes (Extensions on some "
                                   "systems).", "paths": done}


def vlc_command(video, where=None):
    """The command that opens a video in VLC with its notes, or (None, reason)."""
    where, video = where or system(), Path(video)
    ass = Path(str(video.with_suffix("")) + ".notes.ass")
    if where == "mac":
        if not any(Path(p).exists() for p in ("/Applications/VLC.app", str(Path.home() / "Applications/VLC.app"))):
            return None, "VLC isn't in your Applications folder. Get it from https://www.videolan.org."
        return ["open", "-a", "VLC", str(video)], None
    if where in ("wsl", "windows"):
        roots = ["/mnt/c/Program Files", "/mnt/c/Program Files (x86)"] if where == "wsl" else \
            [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        exe = next((p for p in (Path(r) / "VideoLAN" / "VLC" / "vlc.exe" for r in roots) if p.exists()), None)
        if not exe:
            return None, "VLC isn't installed in Windows. Get it from https://www.videolan.org."

        def win(p):
            return (wslpath(p, to_windows=True) or str(p)) if where == "wsl" else str(p)
        return [str(exe), *([f"--sub-file={win(ass)}"] if ass.exists() else []), win(video)], None
    vlc = shutil.which("vlc")
    if vlc:
        return [vlc, *([f"--sub-file={ass}"] if ass.exists() else []), str(video)], None
    if shutil.which("flatpak") and (Path.home() / ".var" / "app" / "org.videolan.VLC").is_dir():
        return ["flatpak", "run", "org.videolan.VLC", *([f"--sub-file={ass}"] if ass.exists() else []), str(video)], None
    return None, "VLC isn't installed. Install it from your software centre or https://www.videolan.org."


def open_detached(cmd):
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "stdin": subprocess.DEVNULL}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def reveal_command(path, where=None):
    """The command that shows a file in Finder / Explorer / the file manager."""
    where, path = where or system(), Path(path)
    if where == "mac":
        return ["open", "-R", str(path)]
    if where == "wsl":
        return ["explorer.exe", f"/select,{wslpath(path, to_windows=True) or path}"]
    if where == "windows":
        return ["explorer", f"/select,{path}"]
    return ["xdg-open", str(path.parent)]


def open_browser(url):
    if system() == "wsl":
        try:
            open_detached(["explorer.exe", url])
            return
        except OSError:
            pass
    webbrowser.open(url)


# ---------------------------------------------------------------- running the scripts
def gui_env():
    return {**os.environ, "CONTEXT_NOTES_UI": "json", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1"}


def script(name, *args):
    return [sys.executable, str(HERE / name), *[str(a) for a in args]]


def split_output(text):
    """(ordinary lines, events) from a script's output in json mode."""
    lines, events = [], []
    for line in text.splitlines():
        if line.startswith(prompts.PREFIX):
            try:
                events.append(json.loads(line[len(prompts.PREFIX):]))
                continue
            except ValueError:
                pass
        lines.append(line)
    return lines, events


def run_quietly(cmd, answers="", timeout=180):
    """Run a script in json mode, feeding `answers` (one line per question), and return (exit code, lines, events)."""
    r = subprocess.run(cmd, input=answers, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=gui_env(), cwd=str(Path.home()), timeout=timeout,
                       **({"start_new_session": True} if os.name == "posix" else {}))
    lines, events = split_output(r.stdout)
    return r.returncode, lines + [ln for ln in r.stderr.splitlines() if ln.strip()], events


class BadRequest(Exception):
    pass


def common_args(o):
    """context_notes.py options shared by --status and a run, from the page's form."""
    p = clean_path(o.get("path"))
    if p is None:
        raise BadRequest("Choose a film or a folder first.")
    if not p.exists():
        raise BadRequest(missing_path_hint(o.get("path", "")) or f"Can't find {p}.")
    args = [str(p)]
    if o.get("recursive"):
        args.append("--recursive")
    for key, flag in TEXT_OPTIONS:
        value = str(o.get(key) or "").strip()
        if value:
            if value.startswith("-"):
                raise BadRequest(f"That doesn't look right: {value}")
            args += [flag, value]
    limit = str(o.get("limit") or "").strip()
    if limit:
        try:
            minutes = float(limit)
        except ValueError:
            raise BadRequest("The time limit is a number of minutes, like 5.")
        if minutes <= 0:
            raise BadRequest("The time limit is a number of minutes, like 5.")
        args += ["--limit", f"{minutes * 60:g}"]
    if o.get("refine") is False:
        args.append("--no-refine")
    if o.get("redo"):
        args.append("--redo")
    return args


def status(o):
    try:
        args = common_args({**o, "title": None})
    except BadRequest as e:
        return {"error": str(e)}
    code, lines, events = run_quietly(script("context_notes.py", *args, "--status"), timeout=120)
    videos = [e for e in events if e.get("type") == "status"]
    if code and not videos:
        return {"error": next((ln for ln in reversed(lines) if ln.strip()), "Couldn't read that folder."), "videos": []}
    return {"videos": videos, "lines": lines}


class Job:
    """One run of context_notes.py, read as it goes. The page polls it, answers its questions and can cancel it."""

    def __init__(self, cmd):
        self.lock = threading.Lock()
        self.items, self.pending, self.returncode, self.cancelled = [], None, None, False
        self.started = time.time()
        kwargs = {"start_new_session": True} if os.name == "posix" else \
            {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, encoding="utf-8", errors="replace", bufsize=1, env=gui_env(),
                                     cwd=str(Path.home()), **kwargs)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            ev = None
            if line.startswith(prompts.PREFIX):
                try:
                    ev = json.loads(line[len(prompts.PREFIX):])
                except ValueError:
                    ev = None
            with self.lock:
                item = {"i": len(self.items)}
                if ev is not None:
                    item["event"] = ev
                    if ev.get("type") in ("question", "input"):
                        self.pending = ev
                else:
                    item["text"] = line
                self.items.append(item)
        code = self.proc.wait()
        with self.lock:
            self.returncode, self.pending = code, None

    @property
    def running(self):
        return self.returncode is None

    def view(self, after=0):
        with self.lock:
            return {"items": self.items[after:], "next": len(self.items), "running": self.running,
                    "returncode": self.returncode, "cancelled": self.cancelled, "pending": self.pending}

    def answer(self, text):
        with self.lock:
            if self.pending is None or not self.running:
                return False
            self.pending = None
        try:
            self.proc.stdin.write(str(text).replace("\r", " ").replace("\n", " ") + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            return False
        return True

    def cancel(self):
        """The same as Ctrl-C in Terminal, sent to the whole run (docs/gui-protocol.md, Cancelling)."""
        if not self.running:
            return False
        self.cancelled = True
        try:
            if os.name == "posix":
                os.killpg(self.proc.pid, signal.SIGINT)
            else:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
        except (OSError, ProcessLookupError):
            return False
        return True


class App:
    def __init__(self, api_url=None):
        self.token = secrets.token_urlsafe(24)
        self.api_url = api_url
        self.job = None
        self.lock = threading.Lock()

    def info(self):
        return {"system": system(), "home": str(Path.home()), "key": key_info(), "opensubtitles": opensubtitles_info(),
                "vlc": vlc_info(), "dialogs": dialog_command("file") is not None,
                "speech": find_subs.have_whisper(),
                "languages": [{"code": c, "name": n} for c, (n, _) in languages.LANGUAGES.items()],
                "running": bool(self.job and self.job.running)}

    def run(self, o):
        with self.lock:
            if self.job and self.job.running:
                return 409, {"error": "Something is already running. Wait for it to finish, or cancel it."}
            try:
                args = common_args(o)
            except BadRequest as e:
                return 400, {"error": str(e)}
            args += QUALITY.get(o.get("quality"), QUALITY["best"])
            if o.get("frames") == "dense":
                args += ["--frames", "dense"]
            if o.get("check_alignment"):
                args.append("--check-alignment")
            if self.api_url:
                args += ["--api-url", self.api_url]
            self.job = Job(script("context_notes.py", *args))
            return 200, {"ok": True}

    def set_key(self, key):
        key = str(key or "").strip()
        if not key:
            return {"ok": False, "message": "Paste your key first."}
        code, lines, _ = run_quietly(script("make_ass.py", "--set-api-key"), answers=key + "\n", timeout=30)
        message = next((ln for ln in lines if ln.strip()), "")
        return {"ok": code == 0, "message": message.replace(key, "…"), "key": key_info()}

    def test_key(self):
        try:
            key = generate_notes.load_key()
        except SystemExit as e:
            return {"ok": False, "message": str(e)}
        url = re.sub(r"/messages$", "/models", self.api_url or generate_notes.API_URL)
        req = urllib.request.Request(url, headers={"x-api-key": key, "anthropic-version": generate_notes.API_VERSION})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
            return {"ok": True, "message": "The key works. (Checking it is free: nothing was sent to Claude.)"}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return {"ok": False, "message": "Anthropic refused this key. Check it, or paste a new one."}
            return {"ok": False, "message": f"Anthropic answered with an error ({e.code}). Try again in a minute."}
        except (urllib.error.URLError, OSError) as e:
            return {"ok": False, "message": f"Couldn't reach Anthropic: {getattr(e, 'reason', e)}. Are you online?"}

    def set_opensubtitles(self, o):
        fields = [str(o.get(k) or "").strip() for k in ("api_key", "username", "password")]
        if not all(fields):
            return {"ok": False, "lines": ["Fill in all three: API key, username and password."]}
        code, lines, _ = run_quietly(script("find_subs.py", "--set-opensubtitles"), answers="\n".join(fields) + "\n",
                                     timeout=60)
        secret = (fields[0], fields[2])
        return {"ok": code == 0, "lines": [ln for ln in lines if not any(s in ln for s in secret)],
                "opensubtitles": opensubtitles_info()}


# ---------------------------------------------------------------- the web server
class Handler(BaseHTTPRequestHandler):
    server_version = "ContextNotes"
    sys_version = ""

    def log_message(self, fmt, *args):            # quiet: the page shows what happens
        pass

    @property
    def app(self):
        return self.server.app

    def _hosts(self):
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _allowed(self):
        """Only this computer, only this page: guards against other web pages and DNS rebinding."""
        hosts = self._hosts()
        if self.headers.get("Host") not in hosts:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in hosts}

    def _key_ok(self, given):
        return hmac.compare_digest(str(given or ""), self.app.token)

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else (json.dumps(body) if not isinstance(body, str) else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _page(self):
        csp = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; "
               "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8", {"Content-Security-Policy": csp})

    def do_GET(self):
        url = urlparse(self.path)
        if not self._allowed():
            return self._send(403, {"error": "Not allowed."})
        if url.path == "/":
            if not self._key_ok(parse_qs(url.query).get("k", [""])[0]):
                return self._send(403, "This page needs the address app.py printed when it started (it ends in ?k=...).",
                                  "text/plain; charset=utf-8")
            return self._page()
        if not url.path.startswith("/api/"):
            return self._send(404, {"error": "Not found."})
        if not self._key_ok(self.headers.get("X-Key")):
            return self._send(403, {"error": "Not allowed."})
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/api/info":
            return self._send(200, self.app.info())
        if url.path == "/api/browse":
            return self._send(200, browse(q.get("path", "")))
        if url.path == "/api/job":
            job = self.app.job
            if job is None:
                return self._send(200, {"items": [], "next": 0, "running": False, "returncode": None, "none": True})
            return self._send(200, job.view(int(q.get("after", 0) or 0)))
        return self._send(404, {"error": "Not found."})

    def do_POST(self):
        url = urlparse(self.path)
        if not self._allowed() or not self._key_ok(self.headers.get("X-Key")):
            return self._send(403, {"error": "Not allowed."})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._send(415, {"error": "Send JSON."})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._send(413, {"error": "Too big."})
        try:
            o = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._send(400, {"error": "That wasn't JSON."})
        if not isinstance(o, dict):
            return self._send(400, {"error": "That wasn't a JSON object."})
        app, path = self.app, url.path
        if path == "/api/status":
            return self._send(200, status(o))
        if path == "/api/run":
            return self._send(*app.run(o))
        if path == "/api/answer":
            ok = bool(app.job and app.job.answer(o.get("answer", "")))
            return self._send(200 if ok else 409, {"ok": ok})
        if path == "/api/cancel":
            ok = bool(app.job and app.job.cancel())
            return self._send(200 if ok else 409, {"ok": ok})
        if path == "/api/pick":
            return self._send(200, pick("folder" if o.get("kind") == "folder" else "file"))
        if path == "/api/key":
            return self._send(200, app.set_key(o.get("key")))
        if path == "/api/key/test":
            return self._send(200, app.test_key())
        if path == "/api/opensubtitles":
            return self._send(200, app.set_opensubtitles(o))
        if path == "/api/vlc/install":
            return self._send(200, {**install_vlc_extension(), "vlc": vlc_info()})
        if path in ("/api/vlc/open", "/api/reveal"):
            target = clean_path(o.get("path"))
            if target is None or not target.exists():
                return self._send(200, {"ok": False, "message": "That file isn't there any more."})
            cmd, why = vlc_command(target) if path == "/api/vlc/open" else (reveal_command(target), None)
            if not cmd:
                return self._send(200, {"ok": False, "message": why})
            try:
                open_detached(cmd)
            except OSError as e:
                return self._send(200, {"ok": False, "message": f"Couldn't open it: {e.strerror or e}"})
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "Not found."})


def make_server(port=0, api_url=None):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.app = App(api_url)
    return server


def address(server):
    host = "localhost" if system() == "wsl" else "127.0.0.1"          # WSL passes localhost through to Windows
    return f"http://{host}:{server.server_address[1]}/?k={server.app.token}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=0, help="port to listen on (default: any free one)")
    ap.add_argument("--no-browser", action="store_true", help="don't open the page; just print its address")
    ap.add_argument("--api-url", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if not PAGE.exists():
        sys.exit(f"Can't find the page {PAGE}. Is the gui folder next to app.py?")
    try:
        server = make_server(a.port, a.api_url)
    except OSError as e:
        sys.exit(f"Couldn't start on port {a.port}: {e.strerror or e}. Try another with --port, or leave it out.")
    url = address(server)
    print(f"Context Notes is running. Open this address in your browser if it doesn't open by itself:\n\n  {url}\n\n"
          "Keep this window open while you use it. Press Ctrl-C here to stop.", flush=True)
    if not a.no_browser:
        open_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        job = server.app.job
        if job and job.running:
            print("\nStopping the run that's going (notes already written are kept)...", flush=True)
            job.cancel()
            try:
                job.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                job.proc.kill()
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
