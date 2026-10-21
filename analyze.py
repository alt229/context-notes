#!/usr/bin/env python3
"""
analyze.py - prepare a show or film for annotation.

Fast by default (subtitles only, no extra installs):
    python3 analyze.py episode.srt
        -> episode.transcript.txt     numbered, timestamped dialogue to write notes from

Video with subtitles built in (mp4, m4v, mov, mkv...): no SRT needed (needs ffmpeg):
    python3 analyze.py episode.mp4
        -> episode.embedded.srt       the subtitle track, pulled out of the video
        -> episode.embedded.transcript.txt
    python3 analyze.py episode.mp4 --list-tracks      show the subtitle tracks and stop
    python3 analyze.py episode.mp4 --sub-track 2      pick a track (number from --list-tracks)
    python3 analyze.py episode.mp4 --strip-sdh        drop [laughter], (phone rings), speaker labels
    python3 analyze.py episode.mp4 --video            also run the slower video checks below
                                                      (embedded subtitles are already in sync)

Add the video for the slower checks (needs ffmpeg, numpy, pillow):
    python3 analyze.py episode.srt --video episode.mp4
        -> <video> analysis/report.txt     do the subtitles match this video? how far off?
                                           loud moments with no dialogue (laughs, sight gags, action)
        -> <video> analysis/sheets/*.jpg   contact sheets: frames + timestamps + the line being spoken

    python3 analyze.py episode.srt --video episode.mp4 --frames dense
        -> 4 frames a second instead of keyframes only (more detail, much slower)

Subtitles from a different release or cut (needs: pip3 install faster-whisper):
    python3 analyze.py episode.srt --video episode.mp4 --align
        -> episode.aligned.srt   subtitles re-timed to THIS video using speech recognition;
                                 lines for scenes this cut doesn't have are dropped

Subtitles early or late by the same amount all the way through:
    python3 analyze.py film.fr.srt --video film.mkv --shift auto
        -> film.fr.aligned.srt   measured against the soundtrack and shifted to match
    python3 analyze.py film.fr.srt --shift -2.5        you know the offset: show every line 2.5 s earlier
    python3 analyze.py film.fr.srt --video film.mkv --shift -2.5    ...and check the result against the video
(If the offset changes through the film, a single shift can't fix it: use --align.)

Only the first part of a long film (for testing; applies to the soundtrack, frames and --align):
    python3 analyze.py film.srt --video film.mp4 --limit 5:00

Films not in English:
    python3 analyze.py film.mkv --sub-lang fr          pull out the French subtitle track -> film.embedded.fr.srt
    python3 analyze.py film.fr.srt --video film.mkv --align --film-language fr
                                                       speech recognition in French (model: small)

Install the extras once:  brew install ffmpeg && pip3 install numpy pillow
"""
import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True        # keep the project folder free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
import languages  # noqa: E402
import make_ass  # noqa: E402  (SRT parsing and time formatting)

SR = 16000          # audio sample rate used for analysis
FPS_A = 50          # audio analysis frames per second (20 ms)


def hms(t, frac=False):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if frac else f"{int(h)}:{int(m):02d}:{int(s):02d}"


def clean(text):
    return re.sub(r"<[^>]+>|\{[^}]*\}", "", text).replace("\n", " / ").strip()


def need(module, hint):
    try:
        return __import__(module)
    except ImportError:
        sys.exit(f"This step needs '{module}'. Install it with:  {hint}")


def need_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"This step needs {tool}. Install it with:  brew install ffmpeg")


# ---------------------------------------------------------------- subtitles only
def write_transcript(cues, out):
    with open(out, "w", encoding="utf-8") as f:
        for c in cues:
            f.write(f"{c['n']} [{hms(c['start'])}] {clean(c['text'])}\n")
    return out


# ---------------------------------------------------------------- embedded subtitles
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".ts", ".m2ts", ".mpg", ".mpeg", ".wmv", ".flv"}
TEXT_SUB_CODECS = {"mov_text", "subrip", "srt", "ass", "ssa", "webvtt", "text", "ttml", "microdvd", "subviewer"}
IMAGE_SUB_CODECS = {"dvd_subtitle", "hdmv_pgs_subtitle", "dvb_subtitle", "xsub", "dvb_teletext"}


def subtitle_tracks(video):
    """List the subtitle streams in a video file (empty list if none)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
                        "-select_streams", "s", str(video)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ffprobe couldn't read {video}:\n{r.stderr}")
    tracks = []
    for n, s in enumerate(json.loads(r.stdout).get("streams", [])):
        tags, disp = s.get("tags", {}) or {}, s.get("disposition", {}) or {}
        codec = s.get("codec_name", "?")
        tracks.append({
            "n": n,                                   # position among subtitle tracks (ffmpeg's 0:s:n)
            "codec": codec,
            "lang": (tags.get("language") or "und").lower(),
            "title": tags.get("title", ""),
            "forced": bool(disp.get("forced")),
            "sdh": bool(disp.get("hearing_impaired")) or bool(re.search(r"sdh|hearing|\bcc\b|caption",
                                                                         tags.get("title", ""), re.I)),
            "default": bool(disp.get("default")),
            "text": codec in TEXT_SUB_CODECS,
            "image": codec in IMAGE_SUB_CODECS,
            "frames": tags.get("NUMBER_OF_FRAMES") or tags.get("NUMBER_OF_FRAMES-eng") or "",
        })
    return tracks


def describe_track(t):
    bits = [t["codec"], t["lang"]]
    if t["title"]:
        bits.append(f'"{t["title"]}"')
    for flag in ("default", "forced", "sdh"):
        if t[flag]:
            bits.append(flag.upper() if flag == "sdh" else flag)
    if t["image"]:
        bits.append("IMAGE-BASED, can't be read as text")
    return f"  [{t['n']}] " + ", ".join(bits)


def pick_track(tracks, wanted=None, prefer="en", strict=False):
    """Choose a readable subtitle track: the one asked for, else full dialogue in the preferred language (English
    unless told otherwise), else any text track. With strict=True, None unless the preferred language is there."""
    if wanted is not None:
        if not 0 <= wanted < len(tracks):
            sys.exit(f"--sub-track {wanted}: this video has {len(tracks)} subtitle track(s), numbered 0 to {len(tracks) - 1}.")
        return tracks[wanted]
    readable = [t for t in tracks if t["text"]]
    if strict:
        readable = [t for t in readable if languages.same(t["lang"], prefer)]
    if not readable:
        return None

    def rank(t):
        return (not languages.same(t["lang"], prefer), t["forced"], t["sdh"], not t["default"], t["n"])
    return min(readable, key=rank)


SDH_PATTERNS = (
    r"\[[^\]]*\]", r"\([^)]*\)",                      # [laughter]  (phone rings)
    r"[♪♫♬]+[^\n]*",                    # music-note lines
    r"^\s*[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ0-9 .'\-]{1,24}:\s*",   # SPEAKER LABELS:  at the start of a line (also JÉRÔME:)
)


def strip_sdh(text):
    for p in SDH_PATTERNS:
        text = re.sub(p, "", text, flags=re.M)
    text = re.sub(r"^\s*-\s*$", "", text, flags=re.M)  # leftover bare dialogue dashes
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def extract_subtitles(video, track, out, sdh=False):
    """Write one embedded text subtitle track to an SRT file."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-map", f"0:s:{track['n']}",
                        "-c:s", "srt", "-f", "srt", str(out)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ffmpeg couldn't extract subtitle track {track['n']}:\n{r.stderr[-600:]}")
    cues = make_ass.parse_srt(out)
    if sdh:
        keep = []
        for c in cues:
            body = strip_sdh(c["text"])
            if body:
                keep.append({**c, "text": body})
        cues = keep
        with open(out, "w", encoding="utf-8") as f:
            def ts(t):
                ms = int(round(t * 1000))
                return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
            for n, c in enumerate(cues, 1):
                f.write(f"{n}\n{ts(c['start'])} --> {ts(c['end'])}\n{c['text']}\n\n")
        cues = make_ass.parse_srt(out)
    return cues


# ---------------------------------------------------------------- video helpers
def probe(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                        "-show_streams", str(video)], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"ffprobe couldn't read {video}:\n{r.stderr}")
    info = json.loads(r.stdout)
    dur = float(info["format"].get("duration", 0))
    audio = [s for s in info["streams"] if s.get("codec_type") == "audio"]
    video_s = [s for s in info["streams"] if s.get("codec_type") == "video"]
    return dur, (audio[0] if audio else None), (video_s[0] if video_s else None)


def audio_filter(astream, extra=""):
    """Dialogue lives in the centre channel of 5.1 mixes; use it when present."""
    layout = (astream or {}).get("channel_layout", "")
    chans = int((astream or {}).get("channels", 2))
    base = "pan=mono|c0=FC" if (chans >= 6 or "5.1" in layout or "7.1" in layout) else "aresample=async=1"
    return base + ("," + extra if extra else "")


def limit_args(limit):
    """ffmpeg input option to read only the first `limit` seconds."""
    return ["-t", f"{limit:.3f}"] if limit else []


def limit_tag(limit):
    return f"-first{int(round(limit))}s" if limit else ""


def soundtrack_db(video, astream, folder, limit=None):
    """speech_band_db, cached in the analysis folder so a second pass (e.g. --refine after the sync check) is instant.
    The cache is reused only for the same file (size and modification time) and the same --limit."""
    np = need("numpy", "pip3 install numpy")
    video = Path(video)
    cache = Path(folder) / f"soundtrack{limit_tag(limit)}.npy"
    meta = cache.with_suffix(".json")
    st = video.stat()
    key = {"size": st.st_size, "mtime": int(st.st_mtime), "limit": limit}
    try:
        if cache.exists() and json.loads(meta.read_text()) == key:
            return np.load(cache)
    except (OSError, ValueError):
        pass
    db = speech_band_db(video, astream, limit)
    try:
        np.save(cache, db)
        meta.write_text(json.dumps(key))
    except OSError:
        pass
    return db


def speech_band_db(video, astream, limit=None):
    """Loudness of the speech band, one value per 20 ms, streamed to keep memory low."""
    np = need("numpy", "pip3 install numpy")
    hop = SR // FPS_A
    cmd = ["ffmpeg", "-v", "error", *limit_args(limit), "-i", str(video), "-vn",
           "-af", audio_filter(astream, "highpass=f=300,lowpass=f=3000"),
           "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    out, carry = [], b""
    chunk = hop * 2 * FPS_A * 60                       # one minute of audio per read
    while True:
        data = p.stdout.read(chunk)
        if not data:
            break
        data = carry + data
        usable = len(data) - len(data) % (hop * 2)
        carry = data[usable:]
        x = np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32) / 32768
        frames = x.reshape(-1, hop)
        out.append(20 * np.log10(np.sqrt((frames ** 2).mean(1) + 1e-12)))
    p.wait()
    return np.concatenate(out) if out else np.zeros(0)


COARSE_RATE = 10          # coarse search samples per second
COARSE_MAX = 180.0        # largest offset the coarse search looks for, seconds


def coarse_offset(db, cues, max_lag=COARSE_MAX, lo=None, hi=None):
    """A rough offset (seconds, positive = speech comes after the subtitles) found by sliding the pattern of
    'subtitle on screen' against the pattern of 'speech-band sound' across the whole video. Catches offsets far
    beyond the fine check's few seconds, e.g. subtitles made for a release with a different intro.
    Returns (offset, strength, correlation). strength: the best match divided by the best one more than 5 s away
    (real matches measured 2.5 to 3.5, wrong ones at most 1.3); correlation: 0 to 1 (real 0.14 to 0.19, wrong
    at most 0.07)."""
    np = need("numpy", "pip3 install numpy")
    step = FPS_A // COARSE_RATE
    d = db[:len(db) // step * step].reshape(-1, step).mean(1) if len(db) >= step else np.zeros(0)
    if lo is not None:                            # just one stretch of the video (lo to hi seconds)
        a, b = int(lo * COARSE_RATE), int(hi * COARSE_RATE)
        d = d[a:b]
        cues = [{**c, "start": c["start"] - lo, "end": c["end"] - lo} for c in cues if lo <= c["start"] < hi]
    n = len(d)
    if n < COARSE_RATE * 60 or len(cues) < 20:
        return 0.0, 0.0, 0.0
    speech = (d > np.median(d) + 3).astype(float)
    subs = np.zeros(n)
    for c in cues:
        a, b = int(c["start"] * COARSE_RATE), int(c["end"] * COARSE_RATE)
        if b > a and a < n and b > 0:          # b <= 0 would count from the END of the array
            subs[max(a, 0):min(b, n)] = 1
    speech -= speech.mean()
    subs -= subs.mean()
    size = 1 << int(np.ceil(np.log2(2 * n)))
    corr = np.fft.irfft(np.fft.rfft(speech, size) * np.conj(np.fft.rfft(subs, size)), size)
    k = int(max_lag * COARSE_RATE)
    lags = np.r_[np.arange(0, k + 1), np.arange(-k, 0)]
    vals = np.r_[corr[:k + 1], corr[-k:]]
    best = int(np.argmax(vals))
    far = np.abs(lags - lags[best]) > 5 * COARSE_RATE
    runner_up = vals[far].max() if far.any() else 0.0
    strength = float(vals[best] / runner_up) if runner_up > 0 else 99.0
    norm = float(np.linalg.norm(speech) * np.linalg.norm(subs)) or 1.0
    return lags[best] / COARSE_RATE, strength, float(vals[best] / norm)


def subtitle_offset(cues, reference, max_lag=COARSE_MAX):
    """How far `cues` are from `reference` subtitles that are known to be in step with the video (e.g. English
    subtitles against already-corrected French ones): positive = cues are early. Compares when each file has a
    line on screen, which is far more reliable than the soundtrack on a busy film. Returns (offset, strength,
    correlation). On a test film the real match scored 0.67 correlation and 1.54 strength (subtitle patterns
    repeat every few seconds, so the runner-up is never far behind); use correlation >= 0.4 and strength >= 1.3."""
    np = need("numpy", "pip3 install numpy")
    end = max([c["end"] for c in cues] + [c["end"] for c in reference] + [0.0])
    n = int((end + max_lag + 5) * COARSE_RATE)
    if len(cues) < 20 or len(reference) < 20:
        return 0.0, 0.0, 0.0

    def pattern(cs):
        s = np.zeros(n)
        for c in cs:
            a, b = int(c["start"] * COARSE_RATE), int(c["end"] * COARSE_RATE)
            if b > a and b > 0:                # b <= 0 would count from the END of the array
                s[max(a, 0):min(b, n)] = 1
        return s - s.mean()
    ref, sub = pattern(reference), pattern(cues)
    size = 1 << int(np.ceil(np.log2(2 * n)))
    corr = np.fft.irfft(np.fft.rfft(ref, size) * np.conj(np.fft.rfft(sub, size)), size)
    k = int(max_lag * COARSE_RATE)
    lags = np.r_[np.arange(0, k + 1), np.arange(-k, 0)]
    vals = np.r_[corr[:k + 1], corr[-k:]]
    best = int(np.argmax(vals))
    far = np.abs(lags - lags[best]) > 5 * COARSE_RATE
    runner_up = vals[far].max() if far.any() else 0.0
    strength = float(vals[best] / runner_up) if runner_up > 0 else 99.0
    norm = float(np.linalg.norm(ref) * np.linalg.norm(sub)) or 1.0
    return lags[best] / COARSE_RATE, strength, float(vals[best] / norm)


def sync_check(db, cues, duration):
    """Estimate how far the subtitles are from the speech, overall and per third."""
    np = need("numpy", "pip3 install numpy")
    W = 3 * FPS_A
    pattern, strength, corr = coarse_offset(db, cues)
    confident = strength >= 1.6 and corr >= 0.08
    coarse = pattern if confident and abs(pattern) >= 2.5 else 0.0

    def estimate(starts):
        starts = [s + coarse for s in starts]
        acc = [db[int(s * FPS_A) - W:int(s * FPS_A) + W] for s in starts
               if int(s * FPS_A) - W >= 0 and int(s * FPS_A) + W < len(db)]
        if len(acc) < 8:
            return None, len(acc)
        avg = np.mean(acc, 0)
        rise = np.diff(avg)
        # Look for the onset within 2 s of the cue: further out, the NEXT line's onset can win (seen on a film
        # with lines ~3 s apart). Bigger offsets are found by coarse_offset() first.
        S = 2 * FPS_A
        i = W - S + int(np.argmax(rise[W - S:W + S]))
        return coarse + (i - W) / FPS_A, len(acc)       # speech starts this many s after the cue

    clean_starts = [c["start"] for k, c in enumerate(cues)
                    if k == 0 or c["start"] - cues[k - 1]["end"] >= 1.5]
    thirds = []
    if confident:
        # The whole-pattern match is clear, so it decides. Speech onsets alone are too noisy on a busy film
        # soundtrack: on a test film they pulled a +21.3 s offset to +22.1 s, and called the corrected file
        # drifting, when a second, in-sync subtitle file showed both were wrong. Onsets still fine-tune a small
        # offset when they agree with the pattern match (they are more precise on a clean TV soundtrack).
        if coarse:
            overall, n = coarse, len(clean_starts)
        else:
            fine, n = estimate(clean_starts)
            overall = fine if fine is not None and abs(fine - pattern) <= 0.5 else pattern
            n = n or len(clean_starts)
        for part in range(3):                           # does it hold all the way through?
            lo, hi = part * duration / 3, (part + 1) * duration / 3
            est, s, c = coarse_offset(db, cues, 60, lo, hi)
            thirds.append(est if s >= 1.4 and c >= 0.06 else None)
    else:
        overall, n = estimate(clean_starts)
        for part in range(3):
            lo, hi = part * duration / 3, (part + 1) * duration / 3
            est, m = estimate([s for s in clean_starts if lo <= s < hi])
            thirds.append(est)
    last_end = (cues[-1]["end"] + coarse) if cues else 0
    verdict = []
    if last_end > duration + 30:
        verdict.append(f"The subtitles run to {hms(last_end)} but the video is only {hms(duration)}: "
                       "they're probably for a different cut or release. Use --align.")
    valid = [t for t in thirds if t is not None]
    if verdict:
        pass                                   # already told them to use --align
    elif overall is None:
        verdict.append("Not enough clean dialogue starts to judge the sync.")
    elif valid and max(valid) - min(valid) > 1.0:
        verdict.append("The offset changes through the video (drift or cuts): use --align.")
    elif abs(overall) < 0.25:
        verdict.append("Subtitles look in sync.")
    else:
        verdict.append(f"Subtitles look {'late' if overall < 0 else 'early'} by about {abs(overall):.2f} s: "
                       f"build with  make_ass.py ... --offset {overall:+.2f}")
    return {"offset": None if overall is None else round(overall, 2), "clean_starts": n,
            "thirds": [None if t is None else round(t, 2) for t in thirds],
            "subtitles_end": round(last_end, 1), "video_duration": round(duration, 1),
            "coarse_offset": round(coarse, 1), "verdict": " ".join(verdict)}


def loud_moments(db, cues, offset):
    """Loud stretches with no dialogue: audience laughs, sight gags, action, music."""
    np = need("numpy", "pip3 install numpy")
    n = len(db)
    if not n:
        return []
    sm = np.convolve(db, np.ones(10) / 10, mode="same")
    gap = np.ones(n, bool)
    for c in cues:
        gap[max(0, int((c["start"] + offset - 0.4) * FPS_A)):int((c["end"] + offset + 0.4) * FPS_A)] = False
    base = float(np.median(sm))
    hot = gap & (sm > base + 8)
    out, i = [], 0
    while i < n:
        if hot[i]:
            j = i
            while j < n and hot[j]:
                j += 1
            if (j - i) / FPS_A >= 0.8:
                s, e = i / FPS_A, j / FPS_A
                prev = [c for c in cues if c["end"] + offset <= s + 0.5]
                out.append({"start": round(s, 1), "end": round(e, 1),
                            "loudness_db": round(float(sm[i:j].max()) - base, 1),
                            "after_line": clean(prev[-1]["text"])[:70] if prev else ""})
            i = j
        else:
            i += 1
    return out


def run_ffmpeg_frames(video, outdir, dense, limit=None):
    """Extract small frames; returns list of (time, path)."""
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.jpg"):
        old.unlink()
    pre = ([] if dense else ["-skip_frame", "nokey"]) + limit_args(limit)
    vf = ("fps=4," if dense else "") + "scale=480:-2,showinfo"

    def attempt(sync_flag):
        cmd = ["ffmpeg", "-hide_banner", *pre, "-i", str(video), "-an", "-vf", vf,
               *sync_flag, "-q:v", "4", str(outdir / "%06d.jpg")]
        return subprocess.run(cmd, capture_output=True, text=True)

    # passthrough, not vfr: vfr DROPS frames whose timestamp repeats an earlier one, after showinfo has already
    # printed them, so the list of times got longer than the list of files and every frame after a drop was
    # labelled with the time of the frame before it. On a long film the error adds up to many seconds, which is
    # exactly where on-screen (Prop, Visual gag) notes are timed from. passthrough writes every frame showinfo saw.
    r = attempt(["-fps_mode", "passthrough"])
    if r.returncode and "fps_mode" in r.stderr:        # older ffmpeg
        r = attempt(["-vsync", "passthrough"])
    if r.returncode:
        sys.exit("ffmpeg failed extracting frames:\n" + r.stderr[-800:])
    times = [float(t) for t in re.findall(r"pts_time:(-?[0-9.]+)", r.stderr)]
    files = sorted(outdir.glob("*.jpg"))
    if len(times) != len(files):
        # Seen on Das Boot (HEVC in MP4, Homebrew ffmpeg): 842 frames written against a longer list of times, so
        # the end credits were labelled 2:08 in a 3:28 film. Ask ffprobe for the keyframe times instead, and only
        # trust them if they number exactly as many as the frames.
        keys = keyframe_times(video, limit)
        if len(keys) != len(files):
            sys.exit(f"ffmpeg wrote {len(files)} frames but reported {len(times)} times (ffprobe lists {len(keys)} "
                     f"keyframes), so the frames can't be labelled with their times reliably. Try --frames dense, "
                     f"and please report this with your ffmpeg version (ffmpeg -version).")
        times = keys
    return list(zip(times, files))


def keyframe_times(video, limit=None):
    """Times of the video's keyframes, from the container (no decoding)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
                        "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    keys = []
    for line in r.stdout.splitlines():
        t, _, flags = line.partition(",")
        if "K" in flags and t not in ("", "N/A"):
            keys.append(float(t))
    keys.sort()
    return [t for t in keys if limit is None or t < limit]


def find_font(size):
    from PIL import ImageFont
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                 "C:/Windows/Fonts/arial.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    return ImageFont.load_default()


def contact_sheets(frames, cues, offset, outdir, min_gap=1.5):
    need("PIL", "pip3 install pillow")
    from PIL import Image, ImageDraw
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("sheet_*.jpg"):
        old.unlink()
    picked, last = [], -1e9
    for t, f in frames:
        if t - last >= min_gap:
            picked.append((t, f))
            last = t

    def line_at(t):
        for c in cues:
            if c["start"] + offset - 0.2 <= t <= c["end"] + offset + 0.2:
                return clean(c["text"])
        return ""

    big, small = find_font(18), find_font(14)
    cols, rows, tw, lab = 3, 4, 480, 42
    sheets = []
    for k in range(0, len(picked), cols * rows):
        chunk = picked[k:k + cols * rows]
        ims = [Image.open(f) for _, f in chunk]
        th = ims[0].height
        sheet = Image.new("RGB", (cols * tw + (cols - 1) * 4, rows * (th + lab) + (rows - 1) * 4), (20, 20, 20))
        d = ImageDraw.Draw(sheet)
        for i, ((t, _), im) in enumerate(zip(chunk, ims)):
            x, y = (i % cols) * (tw + 4), (i // cols) * (th + lab + 4)
            sheet.paste(im.resize((tw, th)), (x, y))
            d.text((x + 4, y + th + 2), hms(t, frac=True), font=big, fill=(255, 220, 90))
            d.text((x + 4, y + th + 22), line_at(t)[:60], font=small, fill=(210, 210, 210))
        name = outdir / f"sheet_{len(sheets) + 1:03d}_{hms(chunk[0][0]).replace(':', '.')}.jpg"
        sheet.save(name, quality=82)
        sheets.append((name, chunk[0][0], chunk[-1][0]))     # file, first and last frame time
    return sheets


# ---------------------------------------------------------------- alignment
def whisper_model(film_language=None, model=None):
    """Speech model for --align. The '.en' models only understand English; other languages need a multilingual one."""
    lang = languages.code(film_language) or "en"
    if model:
        if model.endswith(".en") and lang != "en":
            sys.exit(f"The {model} speech model only understands English. For {languages.name(lang)}, use "
                     f"--model small (or base for speed, medium for accuracy).")
        return model
    return "base.en" if lang == "en" else "small"


def transcript_cache(folder, model, film_language=None, limit=None, task="transcribe"):
    lang = languages.code(film_language) or "en"
    kind = "-translated" if task == "translate" else ""
    return Path(folder) / f"transcript-{model}{'' if lang == 'en' else '-' + lang}{kind}{limit_tag(limit)}.jsonl"


def aligned_path(srt, limit=None):
    """Where --align writes the re-timed subtitles. A --limit run gets its own name, so it is never mistaken
    for a full alignment later."""
    srt = Path(srt)
    return srt.with_name(f"{srt.stem}.aligned{'.first' + str(int(round(limit))) + 's' if limit else ''}.srt")


def transcribe(video, astream, model_name, cache, language="en", limit=None, task="transcribe"):
    """Speech to text with timings. task="translate" gives English text for speech in another language."""
    if cache.exists():
        print(f"  using cached transcript {cache.name}")
        return [json.loads(line) for line in cache.open()]
    np = need("numpy", "pip3 install numpy")
    fw = need("faster_whisper", "pip3 install faster-whisper")
    cmd = ["ffmpeg", "-v", "error", *limit_args(limit), "-i", str(video), "-vn", "-af", audio_filter(astream),
           "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    model = fw.WhisperModel(model_name, device="cpu", compute_type="int8")
    t0, total = time.time(), len(audio) / SR
    segs, _ = model.transcribe(audio, language=languages.code(language) or "en", task=task, beam_size=1,
                               word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
    out = []
    with cache.open("w") as f:
        for s in segs:
            row = {"s": s.start, "e": s.end, "t": s.text,
                   "w": [[w.start, w.end, w.word] for w in (s.words or [])]}
            f.write(json.dumps(row) + "\n")
            out.append(row)
            print(f"\r  transcribing: {hms(s.end)} of {hms(total)}  ({time.time() - t0:.0f} s)",
                  end="", flush=True)
    print()
    return out


def align(cues, asr):
    """Match subtitle words to transcript words; return {cue index: offset} and segments."""
    import difflib

    def words(text):
        text = make_ass.fold(re.sub(r"<[^>]+>|\{[^}]*\}", " ", text))      # lower case, accents dropped (été -> ete)
        return [w for w in re.findall(r"[a-z']+", text) if w.strip("'")]

    sw, st, sc = [], [], []
    for i, c in enumerate(cues):
        ws = words(c["text"])
        # Subtitles start with the speech but linger after it, so place words at
        # a normal speaking pace (~3 words/s) from the cue start, not spread
        # across the whole time the subtitle stays on screen.
        step = min((c["end"] - c["start"]) / max(len(ws), 1), 0.33)
        for k, w in enumerate(ws):
            sw.append(w)
            sc.append(i)
            st.append(c["start"] + k * step)
    aw, at = [], []
    for seg in asr:
        for s, e, w in seg["w"]:
            for x in words(w):
                aw.append(x)
                at.append(s)
    anchors = {}
    for b in difflib.SequenceMatcher(None, sw, aw, autojunk=False).get_matching_blocks():
        if b.size >= 3:
            for k in range(b.size):
                anchors.setdefault(sc[b.a + k], []).append(at[b.b + k] - st[b.a + k])
    off = {i: statistics.median(v) for i, v in anchors.items()}

    groups, cur = [], []
    for i in sorted(off):
        if cur and abs(off[i] - statistics.median(off[x] for x in cur)) > 1.5:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    # Real stretches of a cut run for many lines; one- or two-line "stretches"
    # are usually repeated lines matched to the wrong place, so drop them and
    # let those lines take their neighbours' offset.
    groups = [g for g in groups if len(g) >= 3]
    merged = []
    for g in groups:
        if merged and abs(statistics.median(off[x] for x in merged[-1])
                          - statistics.median(off[x] for x in g)) <= 1.5:
            merged[-1] += g
        else:
            merged.append(g)
    groups = merged

    # A short stretch whose neighbours on BOTH sides agree with each other is
    # almost always a repeated phrase matched to the wrong place (a real cut
    # would leave the neighbours with different offsets). Fold it back in.
    def med(g):
        return statistics.median(off[x] for x in g)
    changed = True
    while changed and len(groups) >= 3:
        changed = False
        for k in range(1, len(groups) - 1):
            g, before, after = groups[k], groups[k - 1], groups[k + 1]
            if (len(g) < 10 and abs(med(before) - med(after)) <= 1.5
                    and abs(med(g) - med(before)) > 1.5):
                groups[k - 1] = before + after
                del groups[k:k + 2]
                changed = True
                break
    gd = [med(g) for g in groups]

    assigned = {}
    for gi, g in enumerate(groups):
        for i in range(g[0], g[-1] + 1):
            assigned[i] = gd[gi]
    for gi in range(len(groups) + 1):
        lo = groups[gi - 1][-1] + 1 if gi > 0 else 0
        hi = groups[gi][0] if gi < len(groups) else len(cues)
        dl = gd[gi - 1] if gi > 0 else None
        dr = gd[gi] if gi < len(groups) else None
        left_end = cues[lo - 1]["end"] + dl if dl is not None else -1e9
        right_start = cues[hi]["start"] + dr if dr is not None else 1e9
        for i in range(lo, hi):
            c, cand = cues[i], []
            if dl is not None and c["end"] + dl <= right_start + 0.3:
                cand.append((c["start"] - cues[lo - 1]["end"], dl))
            if dr is not None and c["start"] + dr >= left_end - 0.3:
                cand.append((cues[hi]["start"] - c["end"], dr))
            if dl is not None and dr is not None and abs(dl - dr) <= 1.5:
                cand = [(0, (dl + dr) / 2)]
            if cand:
                assigned[i] = min(cand)[1]
    segments = [{"from": hms(cues[g[0]]["start"]), "to": hms(cues[g[-1]]["end"]),
                 "offset": round(d, 2), "lines": len(g)} for g, d in zip(groups, gd)]
    stats = {"subtitle_words": len(sw), "transcript_words": len(aw),
             "matched_words": sum(len(v) for v in anchors.values()),
             "lines": len(cues), "kept": len(assigned), "dropped": len(cues) - len(assigned)}
    return assigned, segments, stats


def _srt_ts(t):
    """Standard SRT time, 00:00:03,880 (millisecond precision)."""
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def parse_shift(text):
    """argparse type for --shift: 'auto' or seconds such as -2.5 / +1.25 / 0.8s."""
    s = str(text).strip().lower()
    if s == "auto":
        return s
    try:
        return float(s.rstrip("s"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"--shift takes 'auto' or a number of seconds such as -2.5, not {text!r}")


AD_SITE = re.compile(r"(www\.|https?://|\b[\w-]+\.(com|org|net|tv|to|am|ag|me|io|cc|ws|xyz)\b)", re.I)
AD_WORDS = re.compile(r"download|subtit|\bsubs?\b|sync|corrected|ripped|encoded|support us|advertis|opensubtitles|"
                      r"allsubs|addic7ed|subscene|podnapisi|yify|yts|sous-titr|untertitel|subt[ií]tulos|traduction", re.I)


def is_ad(text):
    """'Downloaded From www.AllSubs.org', 'Subtitles by ... www.example.com' and the like."""
    return bool(AD_SITE.search(text) and AD_WORDS.search(text))


def shift_srt(cues, seconds, out):
    """Write every line moved by `seconds` (positive = later), leaving out subtitle-site adverts.
    Lines pushed before 0:00 are dropped. Returns (lines dropped before 0:00, adverts dropped)."""
    ads = {i for i, c in enumerate(cues) if is_ad(c["text"])}
    keep = {i: seconds for i, c in enumerate(cues) if c["end"] + seconds > 0 and i not in ads}
    write_srt(cues, keep, out)
    return len(cues) - len(keep) - len(ads), len(ads)


def dropped_msg(dropped):
    early, ads = dropped
    bits = ([f"{early} line(s) before 0:00"] if early else []) + ([f"{ads} subtitle-site advert(s)"] if ads else [])
    return f"  (left out: {', '.join(bits)})" if bits else ""


def write_srt(cues, assigned, out):
    with open(out, "w", encoding="utf-8") as f:
        n = 0
        for i, c in enumerate(cues):
            if i not in assigned:
                continue
            n += 1
            s, e = c["start"] + assigned[i], c["end"] + assigned[i]
            f.write(f"{n}\n{_srt_ts(s)} --> {_srt_ts(e)}\n{c['text']}\n\n")


# ---------------------------------------------------------------- video analysis as data
def analyze_video(cues, video, frames_mode="keyframes", fallback_offset=0.0, say=print, limit=None):
    """Everything --video does, returned as data (used by make_ass.py --refine).

    Returns a dict: duration, sync (see sync_check), offset_measured (a constant offset in seconds, or
    None if the subtitles drift, don't match, or there was too little dialogue to judge), offset (what to
    use for timing in this run), moments (loud stretches with no dialogue) and sheets
    ((jpg path, first frame time, last frame time) for each contact sheet).
    """
    need_ffmpeg()
    video = Path(video)
    out = video.parent / f"{video.stem} analysis"
    out.mkdir(exist_ok=True)
    duration, astream, vstream = probe(video)
    say(f"  video {hms(duration)}, audio {astream.get('channels') if astream else 0} ch")
    if limit and limit < duration:
        duration = limit
        cues = make_ass.limit_cues(cues, limit)
    say("  measuring the soundtrack...")
    db = soundtrack_db(video, astream, out, limit)
    sync = sync_check(db, cues, duration)
    say("  " + sync["verdict"])
    constant = sync["offset"] is not None and "--align" not in sync["verdict"]
    measured = None
    if constant:
        measured = 0.0 if abs(sync["offset"]) < 0.25 else sync["offset"]
    offset = measured if measured is not None else fallback_offset
    moments = loud_moments(db, cues, offset)
    say(f"  {len(moments)} loud moments with no dialogue")
    say(f"  pulling frames ({frames_mode})...")
    frames = run_ffmpeg_frames(video, out / "frames", dense=(frames_mode == "dense"), limit=limit)
    sheets = contact_sheets(frames, cues, offset, out / "sheets", min_gap=0.9 if frames_mode == "dense" else 1.5)
    say(f"  {len(frames)} frames -> {len(sheets)} contact sheets in {out / 'sheets'}")
    return {"duration": duration, "sync": sync, "offset_measured": measured, "offset": offset,
            "moments": moments, "sheets": sheets}


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", metavar="input",
                    help="subtitle file (.srt), or a video with subtitles built in (.mp4, .mkv, ...)")
    ap.add_argument("--video", nargs="?", const="SELF", metavar="FILE",
                    help="also analyse a video (slower). With no file name, uses the input video itself")
    ap.add_argument("--sub-track", type=int, metavar="N",
                    help="embedded subtitle track to use (numbers from --list-tracks; default: English dialogue)")
    ap.add_argument("--list-tracks", action="store_true", help="list the subtitle tracks in a video and stop")
    ap.add_argument("--strip-sdh", action="store_true",
                    help="drop hearing-impaired text from embedded subtitles: [laughter], (sighs), SPEAKER:, music notes")
    ap.add_argument("--frames", choices=("keyframes", "dense", "none"), default="keyframes",
                    help="contact-sheet frames: keyframes (fast, default), dense (4/s, slow), none")
    ap.add_argument("--align", action="store_true",
                    help="re-time subtitles to this video with speech recognition (needs --video)")
    ap.add_argument("--translate-speech", action="store_true",
                    help="with --align: have speech recognition translate the film's speech into English, and time "
                         "the English subtitles to that. For English subtitles on a film in another language, when "
                         "the other-language subtitles don't match the speech")
    ap.add_argument("--model", default=None,
                    help="speech model for --align: tiny.en (fastest), base.en (default), small.en (best). "
                         "For other languages: base, small (default), medium")
    ap.add_argument("--limit", type=make_ass.duration_arg, metavar="TIME",
                    help="only the first part of the video, e.g. 5:00, 300 or 5m (soundtrack, frames and --align)")
    ap.add_argument("--film-language", metavar="LANG",
                    help="language spoken in the video, e.g. fr, de, es (for --align's speech recognition; default en)")
    ap.add_argument("--sub-lang", metavar="LANG",
                    help="embedded subtitles: pick the track in this language (e.g. fr) -> <video>.embedded.<lang>.srt")
    ap.add_argument("--shift", type=parse_shift, metavar="auto|SECONDS",
                    help="fix subtitles that are early or late by the same amount throughout -> <name>.aligned.srt. "
                         "'auto' measures it against the video's soundtrack (needs --video); a number shifts by that "
                         "many seconds (positive = later, negative = earlier)")
    a = ap.parse_args()
    if a.shift is not None and a.align:
        sys.exit("Use --shift or --align, not both (--align already fixes the timing, including constant offsets).")
    if a.shift == "auto" and not a.video:
        sys.exit("--shift auto measures the offset against the video: add  --video <file>  (or give a number of seconds)")
    if a.translate_speech and not a.align:
        sys.exit("--translate-speech goes with --align (and --video): add --align --video <file>.")
    if a.translate_speech and not languages.code(a.film_language):
        sys.exit("--translate-speech needs the film's language: add --film-language <code>, e.g. ko.")

    src = Path(a.srt)
    if not src.exists():
        sys.exit(f"Can't find {src}")
    embedded = src.suffix.lower() in VIDEO_EXTS
    if not embedded and (a.list_tracks or a.sub_track is not None or a.strip_sdh or a.sub_lang):
        sys.exit("--list-tracks, --sub-track, --sub-lang and --strip-sdh are for video files with built-in subtitles.")
    if a.video == "SELF":
        if not embedded:
            sys.exit("--video with no file name needs a video as the input. Give it one: --video episode.mp4")
        a.video = str(src)

    if embedded:
        need_ffmpeg()
        tracks = subtitle_tracks(src)
        if a.list_tracks:
            print(f"{src.name}: {len(tracks)} subtitle track(s)" + (":" if tracks else ""))
            for t in tracks:
                print(describe_track(t))
            if not tracks:
                print("  This video has no embedded subtitles. Use a separate .srt file instead.")
            return
        if not tracks:
            sys.exit(f"{src.name} has no embedded subtitles. Use a separate .srt file instead, "
                     f"e.g.  python3 analyze.py episode.srt --video {src.name}")
        track = pick_track(tracks, a.sub_track, prefer=a.sub_lang or "en", strict=bool(a.sub_lang))
        if track is None and a.sub_lang:
            sys.exit(f"No {languages.name(a.sub_lang)} text subtitle track in {src.name}:\n"
                     + "\n".join(describe_track(t) for t in tracks))
        if track is None:
            sys.exit("This video's subtitle track(s) are all pictures (typical of DVD/Blu-ray rips), "
                     "which can't be read as text without OCR:\n" + "\n".join(describe_track(t) for t in tracks))
        if not track["text"]:
            others = [describe_track(t) for t in tracks if t["text"]]
            sys.exit(f"Track {track['n']} is picture-based ({track['codec']}) and can't be read as text."
                     + ("\nText tracks you could use instead:\n" + "\n".join(others) if others else ""))
        lang_part = f".{languages.code(a.sub_lang)}" if a.sub_lang else ""
        srt = src.with_name(f"{src.stem}.embedded{lang_part}.srt")
        print(f"Using embedded subtitle track {describe_track(track).strip()}")
        if len(tracks) > 1 and a.sub_track is None:
            print(f"  ({len(tracks)} tracks found; pick another with --sub-track N, see --list-tracks)")
        cues = extract_subtitles(src, track, srt, sdh=a.strip_sdh)
    else:
        srt = src
        cues = make_ass.parse_srt(srt)
    if not cues:
        sys.exit(f"No subtitles found in {srt}")
    tr = write_transcript(cues, srt.with_suffix(".transcript.txt"))
    print(f"{len(cues)} subtitle lines, {hms(cues[0]['start'])} to {hms(cues[-1]['end'])}")
    print(f"  -> {tr}")
    shifted = None
    if isinstance(a.shift, float):
        shifted = aligned_path(srt)
        dropped = shift_srt(cues, a.shift, shifted)
        print(f"Shifted every line {abs(a.shift):.2f} s {'later' if a.shift > 0 else 'earlier'} -> {shifted}"
              + dropped_msg(dropped))
        cues = make_ass.parse_srt(shifted)
        if a.video:
            print("Checking the shifted subtitles against the video...")
    all_cues = cues
    if not a.video:
        if a.align:
            sys.exit("--align needs --video")
        print("Subtitles only. Add --video " + ("" if embedded else "<file> ") + "to check sync and pull frames.")
        return

    need_ffmpeg()
    video = Path(a.video)
    out = video.parent / f"{video.stem} analysis"
    out.mkdir(exist_ok=True)
    duration, astream, vstream = probe(video)
    size = f"{vstream.get('width')}x{vstream.get('height')}" if vstream else "audio only"
    print(f"video {hms(duration)}, {size}, audio {astream.get('channels') if astream else 0} ch")
    limit = a.limit if a.limit and a.limit < duration else None
    if limit:
        duration = limit
        cues = make_ass.limit_cues(cues, limit)
        print(f"Limited to the first {make_ass.fmt_limit(limit)} ({len(cues)} subtitle lines)")
        if not cues:
            sys.exit("No subtitle lines start that early. Use a longer --limit.")

    report = {"video": video.name, "subtitles": srt.name, "limit": limit}
    if shifted:
        report["shift"] = {"seconds": a.shift, "file": shifted.name}
    work_cues = cues
    if a.align:
        model = whisper_model(a.film_language, a.model)
        task = "translate" if a.translate_speech else "transcribe"
        print(f"Aligning subtitles to this video with speech recognition ({model}, "
              f"{languages.name(a.film_language or 'en')}{', translated to English' if a.translate_speech else ''})...")
        asr = transcribe(video, astream, model, transcript_cache(out, model, a.film_language, limit, task),
                         language=a.film_language or "en", limit=limit, task=task)
        assigned, segments, stats = align(cues, asr)
        aligned = aligned_path(srt, limit)
        write_srt(cues, assigned, aligned)
        report["alignment"] = {**stats, "segments": segments, "file": aligned.name}
        print(f"  kept {stats['kept']} of {stats['lines']} lines, {len(segments)} stretch(es) "
              f"with different offsets -> {aligned}")
        work_cues = make_ass.parse_srt(aligned)

    print("Measuring the soundtrack...")
    db = soundtrack_db(video, astream, out, limit)
    sync = sync_check(db, work_cues, duration)
    report["sync"] = sync
    print("  " + sync["verdict"])
    offset = 0.0 if a.align or sync["offset"] is None else sync["offset"]
    if a.shift == "auto":
        if sync["offset"] is None or "--align" in sync["verdict"]:
            print("  Not fixed: a single shift can't fix this (see above). Try --align.")
        elif abs(sync["offset"]) < 0.25:
            print("  Already in sync; nothing to fix.")
        else:
            fixed = aligned_path(srt, limit)
            dropped = shift_srt(all_cues, sync["offset"], fixed)
            report["shift"] = {"seconds": sync["offset"], "file": fixed.name}
            print(f"  Fixed: every line shifted {sync['offset']:+.2f} s -> {fixed}" + dropped_msg(dropped))
            if limit:
                print(f"  (Measured on the first {make_ass.fmt_limit(limit)} only, so the file is named for that. "
                      "Run without --limit to check the whole film.)")
    moments = loud_moments(db, work_cues, offset)
    report["loud_moments_without_dialogue"] = moments
    print(f"  {len(moments)} loud moments with no dialogue (often laughs or sight gags)")

    if a.frames != "none":
        print(f"Pulling frames ({a.frames})...")
        frames = run_ffmpeg_frames(video, out / "frames", dense=(a.frames == "dense"), limit=limit)
        sheets = contact_sheets(frames, work_cues, offset, out / "sheets",
                                min_gap=0.9 if a.frames == "dense" else 1.5)
        report["contact_sheets"] = len(sheets)
        print(f"  {len(frames)} frames -> {len(sheets)} contact sheets in {out / 'sheets'}")

    (out / "analysis.json").write_text(json.dumps(report, indent=1))
    with open(out / "report.txt", "w", encoding="utf-8") as f:
        f.write(f"{video.name}  ({hms(duration)})\nsubtitles: {srt.name}\n\n")
        f.write(f"SYNC: {sync['verdict']}\n  overall offset: {sync['offset']} s; by thirds: {sync['thirds']}\n\n")
        if "alignment" in report:
            al = report["alignment"]
            f.write(f"ALIGNMENT: kept {al['kept']} of {al['lines']} lines; dropped {al['dropped']}\n")
            for s in al["segments"]:
                f.write(f"  {s['from']} - {s['to']}  offset {s['offset']:+.2f} s  ({s['lines']} lines)\n")
            f.write("\n")
        f.write("LOUD MOMENTS WITHOUT DIALOGUE (look here for sight gags):\n")
        for m in moments:
            f.write(f"  {hms(m['start'])}  {m['end'] - m['start']:4.1f}s  +{m['loudness_db']} dB  after: {m['after_line']}\n")
    print(f"Report -> {out / 'report.txt'}")


if __name__ == "__main__":
    main()
