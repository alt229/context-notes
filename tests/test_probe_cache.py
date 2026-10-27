import json
import subprocess

import analyze
import usage


def fake_ffprobe(calls):
    def run(cmd, **kw):
        calls.append(cmd)
        out = {"streams": [{"codec_type": "subtitle", "codec_name": "subrip", "tags": {"language": "eng"}}],
               "format": {"duration": "60"}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")
    return run


def test_same_file_is_read_once(usage_dir, tmp_path, monkeypatch):
    video = tmp_path / "film.mkv"
    video.write_bytes(b"x" * 10)
    calls = []
    monkeypatch.setattr(analyze.subprocess, "run", fake_ffprobe(calls))
    first = analyze.subtitle_tracks(video)
    second = analyze.subtitle_tracks(video)
    assert first == second and len(calls) == 1
    assert (usage.data_dir() / analyze.PROBE_DIR).is_dir()


def test_changed_file_is_read_again(usage_dir, tmp_path, monkeypatch):
    video = tmp_path / "film.mkv"
    video.write_bytes(b"x" * 10)
    calls = []
    monkeypatch.setattr(analyze.subprocess, "run", fake_ffprobe(calls))
    analyze.probe(video)
    video.write_bytes(b"y" * 20)                  # a new size: a new answer is needed
    analyze.probe(video)
    assert len(calls) == 2


def test_different_options_are_kept_apart(usage_dir, tmp_path, monkeypatch):
    video = tmp_path / "film.mkv"
    video.write_bytes(b"x" * 10)
    calls = []
    monkeypatch.setattr(analyze.subprocess, "run", fake_ffprobe(calls))
    analyze.subtitle_tracks(video)
    analyze.probe(video)
    assert len(calls) == 2


def test_unreadable_cache_is_ignored(usage_dir, tmp_path, monkeypatch):
    video = tmp_path / "film.mkv"
    video.write_bytes(b"x" * 10)
    calls = []
    monkeypatch.setattr(analyze.subprocess, "run", fake_ffprobe(calls))
    analyze.probe(video)
    for f in (usage.data_dir() / analyze.PROBE_DIR).glob("*.json"):
        f.write_text("not json", encoding="utf-8")
    analyze.probe(video)
    assert len(calls) == 2
