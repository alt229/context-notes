"""
timecode.py - reading and writing times, in one place.

Every script reads or prints times in a few shapes: SRT timestamps (00:01:23,500), ASS timestamps (0:01:23.50),
clock-style text for messages (1:02:03) and lengths of time on the command line (5:00, 300, 5m). The helpers here
turn each into seconds and back. Nothing in here reads files or talks to the API.

    parse_ts("00:01:23,500")   -> 83.5          an SRT (or ASS-like) timestamp; raises ValueError otherwise
    parse_time("1:23.5")       -> 83.5          looser: m:ss or h:mm:ss(.s) text, or a bare number; None if unreadable
    parse_duration("5:00")     -> 300.0         a length of time for --limit (300, 5m, 5:00, 1h30m, 1:30:00)
    fmt_ass_time(83.5)         -> "0:01:23.50"
    srt_ts(83.5)               -> "00:01:23,500"
    hms(3725.4)                -> "1:02:05"      (hms(t, frac=True) -> "1:02:05.4")
    fmt_limit(300)             -> "5:00"         a length of time, for messages
"""
import argparse
import re

# One timestamp: hours, minutes, seconds and a comma or dot before the fraction (SRT uses a comma, ASS a dot).
TS = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"


# ---------------------------------------------------------------- text -> seconds
def ts_to_s(h, m, s, ms):
    """The four parts of a timestamp (as text) -> seconds. A short fraction is read as milliseconds: '5' is .500."""
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_ts(text):
    """'00:01:23,500' (or with a dot) -> 83.5. Raises ValueError for anything else."""
    m = re.fullmatch(TS, text.strip())
    if not m:
        raise ValueError(f"bad timestamp: {text!r}")
    return ts_to_s(*m.groups())


def parse_time(v):
    """Seconds as a number, or 'm:ss' / 'h:mm:ss(.s)' text (a comma works as the decimal point). None if unreadable."""
    if isinstance(v, (int, float)):
        return float(v)
    parts = str(v).strip().split(":")
    try:
        secs = 0.0
        for p in parts:
            secs = secs * 60 + float(p.replace(",", "."))
        return secs
    except ValueError:
        return None


def parse_duration(text):
    """'300', '300s', '5m', '5:00', '1:02:03', '1h30m' -> seconds (for --limit)."""
    s = str(text).strip().lower().replace(" ", "")
    try:
        if ":" in s:
            secs = 0.0
            for p in s.split(":"):
                secs = secs * 60 + float(p)
        elif re.fullmatch(r"(\d+(\.\d+)?[hms])+", s):
            secs = sum(float(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, _, u in re.findall(r"(\d+(\.\d+)?)([hms])", s))
        else:
            secs = float(s)
    except ValueError:
        secs = -1
    if secs <= 0:
        raise ValueError(f"can't read {text!r} as a length of time; try 300, 5m, 5:00 or 1:30:00")
    return secs


def duration_arg(text):
    """argparse type for --limit."""
    try:
        return parse_duration(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e))


# ---------------------------------------------------------------- seconds -> text
def fmt_ass_time(t):
    """ASS event time, 0:01:23.50 (hundredths of a second)."""
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def srt_ts(t):
    """Standard SRT time, 00:00:03,880 (millisecond precision)."""
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def hms(t, frac=False):
    """Clock-style time for messages and prompts: 1:02:05, or 1:02:05.4 with frac=True."""
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if frac else f"{int(h)}:{int(m):02d}:{int(s):02d}"


def fmt_limit(limit):
    """300 -> '5:00' (for messages)."""
    t = int(round(limit))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"
