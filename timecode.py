#!/usr/bin/env python3
"""
timecode.py - times as the scripts read and write them. Standard library only.

    parse_ts("00:01:02,500")   62.5      SRT (or ASS-style with a dot) to seconds; ts_to_s does the parts
    srt_ts(62.5)               "00:01:02,500"
    fmt_ass_time(62.5)         "0:01:02.50"
    hms(62.5)                  "0:01:02"  (hms(62.5, frac=True): "0:01:02.5")
    parse_time("1:02")         62.0       a time a model wrote: seconds, m:ss or h:mm:ss(.s); None if unreadable
    parse_duration("5:00")     300.0      a length typed on the command line (300, 5m, 5:00, 1h30m)
    duration_arg                          the same, as an argparse type (--limit)
    fmt_limit(300)             "5:00"
"""
import argparse
import re

TS = r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"


def ts_to_s(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


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


def fmt_limit(limit):
    """300 -> '5:00' (for messages)."""
    t = int(round(limit))
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def parse_ts(text):
    m = re.fullmatch(TS, text.strip())
    if not m:
        raise ValueError(f"bad timestamp: {text!r}")
    return ts_to_s(*m.groups())


def fmt_ass_time(t):
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def hms(t, frac=False):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if frac else f"{int(h)}:{int(m):02d}:{int(s):02d}"


def srt_ts(t):
    """Standard SRT time, 00:00:03,880 (millisecond precision)."""
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def parse_time(v):
    """Seconds as a number, or 'm:ss' / 'h:mm:ss(.s)' text."""
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
