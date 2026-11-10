"""--resync (the video was swapped for another copy) and the below-1080p warning (Erin, 2026-11-09)."""
import json
import re
import subprocess

import pytest
from conftest import make_srt, needs_ffmpeg, run_cli

import analyze
import context_notes as cn
import workfiles

np = pytest.importorskip("numpy")      # the sync check measures the soundtrack with numpy


def make_video(path, burst_period=6.0, shift=0.9):
    """150 s of test pattern with a tone burst a little after each subtitle starts (as tests/test_refine_notes.py)."""
    expr = f"0.5*sin(2*PI*1000*t)*(gte(t,{3 + shift})*lt(mod(t-{3 + shift},{burst_period}),2))"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=150:size=320x240:rate=10",
                    "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=16000:d=150", "-c:v", "libx264", "-g", "10",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "150", str(path)], check=True)


NOTES = [{"at": "00:00:03,000", "category": "About these notes", "text": "Intro", "kind": "speech"},
         {"match": "Line 2 of", "category": "Idiom", "text": "Original note 2", "kind": "speech"},
         {"match": "Line 5 of", "category": "Idiom", "text": "Original note 5", "kind": "speech"},
         {"at_video": "00:00:10,000", "category": "Visual gag", "text": "A red balloon floats by", "kind": "visual"}]


def film(tmp_path, shift=0.9, name="ep.mp4", folder_name=None):
    """A finished film: the video, its subtitles, a notes file that records the offset a refine measured against
    this copy (video_offset), and the built .ass."""
    video = tmp_path / name
    make_video(video, shift=shift)
    make_srt(tmp_path / "ep.srt", n=24)
    w = workfiles.folder(tmp_path / (folder_name or name))
    w.mkdir(parents=True)
    spec = {"title": "Test Show (context notes)", "subtitles": "ep.srt", "video_offset": shift,
            "refined": {"model": "test", "date": "2026-11-01"}, "notes": NOTES}
    notes = w / "notes-ep.json"
    notes.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    r = run_cli("make_ass.py", tmp_path / "ep.srt", notes, "--video", video, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    return video, notes


def starts(ass_path, text):
    """When a note with this text appears in the .ass, in seconds."""
    for line in ass_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("Dialogue:") and text in line:
            return _ass_time(line.split(",")[1])
    raise AssertionError(f"{text!r} not in {ass_path.name}")


def _ass_time(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


SOUND_ONLY = {"CONTEXT_NOTES_WHISPER": "0"}      # as a computer without faster-whisper: the sound-only sync check


def test_below_full_hd():
    assert analyze.below_full_hd((720, 400)) and analyze.below_full_hd((1280, 720))
    assert not analyze.below_full_hd((1920, 1080)) and not analyze.below_full_hd((1920, 800))
    assert not analyze.below_full_hd((1440, 1080)) and not analyze.below_full_hd((3840, 2160))
    assert not analyze.below_full_hd((1394, 1076)) and analyze.below_full_hd((1600, 900))    # a cropped 1080p; 900p
    assert not analyze.below_full_hd(None)


@needs_ffmpeg
def test_status_says_when_a_film_is_below_1080p(tmp_path, home):
    video, _ = film(tmp_path)
    r = run_cli("context_notes.py", video, "--status", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "picture: 320x240, below 1080p" in r.stdout and "Plex" in r.stdout
    st = cn.inspect(video, _opts())
    fields = cn.status_fields(st)
    assert fields["size"] == "320x240" and fields["low_res"] is True


def _opts():
    import argparse
    import settings
    return argparse.Namespace(limit=None, subs_language=None, show_subs=None, redo=False, no_refine=False,
                              behind_the_scenes=False, film_language=None, resync=False, **settings.cli_defaults())


@needs_ffmpeg
def test_resync_moves_the_notes_to_a_swapped_copy(tmp_path, home):
    video, notes = film(tmp_path, shift=0.9)
    ass = tmp_path / "ep.notes.ass"
    assert abs(starts(ass, "red balloon") - 10.0) < 0.05
    # (a transcript the alignment check cached for the old copy, which nothing would notice is stale)
    stale = workfiles.analysis(video) / "transcript-base.en.jsonl"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("{}\n")

    make_video(video, shift=1.6)       # the swap: the same film, 0.7 s later (the clip's 6 s tone period makes
                                       # a bigger shift ambiguous for the sync check; real speech isn't periodic)
    r = run_cli("context_notes.py", video, "--resync", "--yes", cwd=tmp_path, home_dir=home, env_extra=SOUND_ONLY)
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"Moved 1 on-screen note\(s\) by \+0\.[5-9]\d s", r.stdout), r.stdout
    assert "Ready: play ep.mp4" in r.stdout and "Removed 1 cached transcript" in r.stdout and not stale.exists()
    spec = json.loads(notes.read_text(encoding="utf-8"))
    assert abs(spec["video_offset"] - 1.6) < 0.15
    moved = spec["notes"][3]
    assert moved["kind"] == "visual" and abs(_ass_time(moved["at_video"].replace(",", ".")) - 10.7) < 0.15
    assert spec["resynced"]["video_offset_before"] == 0.9 and abs(spec["resynced"]["moved_by"] - 0.7) < 0.15
    old = json.loads(notes.with_name(notes.name + ".bak").read_text(encoding="utf-8"))
    assert old["notes"][3]["at_video"] == "00:00:10,000" and old["video_offset"] == 0.9
    assert (workfiles.folder(video) / "ep.notes.ass.bak").exists()           # the .ass before the rebuild
    assert abs(starts(ass, "red balloon") - 10.7) < 0.15                    # on the new copy's clock
    assert abs(starts(ass, "Original note 2") - (11.5 + 1.6 + 0.2)) < 0.15  # line 2 ends at 11.5; placed +offset, +0.2

    r = run_cli("context_notes.py", video, "--resync", "--yes", cwd=tmp_path, home_dir=home, env_extra=SOUND_ONLY)
    assert r.returncode == 0 and "already fit this copy" in r.stdout and "Already done" in r.stdout, r.stdout
    assert json.loads(notes.read_text(encoding="utf-8")) == spec


def test_line_shift_moves_a_moment_as_its_nearest_line_moved():
    old = [{"start": 10.0 * i, "end": 10.0 * i + 2} for i in range(1, 11)]              # lines at 10, 20, ... 100
    new = [{"start": c["start"] + (0.6 if c["start"] < 55 else 8.3), "end": c["end"]} for c in old]   # a 7.7 s insert
    shift = cn.line_shift(old, new)
    assert shift(12.0) == pytest.approx(12.6) and shift(3.0) == pytest.approx(3.6)       # before the first line too
    assert shift(54.0) == pytest.approx(54.6) and shift(56.0) == pytest.approx(64.3)     # the gap: the nearer line
    assert shift(120.0) == pytest.approx(128.3)
    # the old subtitles sat 0.9 s from the old video (video_offset): a note at 12.9 on the video is line 10's moment
    assert cn.line_shift(old, new, before=0.9)(12.9) == pytest.approx(12.6)


def test_shift_video_times_moves_the_refine_record_too():
    spec = {"notes": [{"at_video": "00:01:00,000"}, {"match": "x"}, {"at_video": "00:00:00,100"}],
            "refined": {"unreadable": [{"from": 100.0, "to": 160.0}], "stopped_after": {"time": 200.0}}}
    assert cn.shift_video_times(spec, lambda t: t - 0.5) == 2
    assert spec["notes"][0]["at_video"] == "00:00:59,500" and spec["notes"][2]["at_video"] == "00:00:00,000"
    assert spec["refined"]["unreadable"][0] == {"from": 99.5, "to": 159.5} and spec["refined"]["stopped_after"]["time"] == 199.5


@needs_ffmpeg
def test_resync_retimes_a_different_cut_with_speech(tmp_path, home, monkeypatch):
    """The new copy has 7.7 s more in the middle: the sync check can't follow it, so --resync re-times the subtitles
    (speech recognition, stood in for here) and moves each on-screen note as the lines around it moved."""
    import subtitles
    video, notes = film(tmp_path, shift=0.9)
    make_video(video, burst_period=6.4)                              # the timing drifts: not a constant shift

    def fake_retime(video, srt, st, opts):
        cues = subtitles.parse_srt(srt)
        aligned = analyze.aligned_path(srt, None, video)
        subtitles.write_srt(cues, {i: (0.6 if c["start"] < 55 else 8.3) for i, c in enumerate(cues)}, aligned)
        return aligned, [{"from": "0:00:03", "to": "0:00:50", "offset": 0.6, "lines": 9},
                         {"from": "0:01:00", "to": "0:02:20", "offset": 8.3, "lines": 15}]
    monkeypatch.setattr(cn, "retime_for_resync", fake_retime)
    monkeypatch.setattr(cn, "have_whisper", lambda: True)
    opts = _opts()
    opts.yes, opts.check_alignment, opts.align_model, opts.window = True, False, None, 10.0
    monkeypatch.setenv("HOME", str(home))
    assert cn.resync(video, cn.inspect(video, opts), opts) == "ready"
    spec = json.loads(notes.read_text(encoding="utf-8"))
    assert spec["subtitles"] == "ep.aligned.srt" and spec["video_offset"] == 0.0     # the original ep.srt is untouched
    assert spec["resynced"]["method"] == "align" and len(spec["resynced"]["stretches"]) == 2
    assert spec["resynced"]["subtitles_before"] == "ep.srt" and spec["resynced"]["video_offset_before"] == 0.9
    # the balloon at 10.0 on the old video is 9.1 on the old subtitles' clock, among lines that moved +0.6
    assert spec["notes"][3]["at_video"] == "00:00:09,700"
    ass = tmp_path / "ep.notes.ass"
    assert abs(starts(ass, "red balloon") - 9.7) < 0.05
    assert abs(starts(ass, "Original note 2") - (11.5 + 0.6 + 0.2)) < 0.15            # line 2 ends at 11.5, +0.6, +0.2
    assert (workfiles.folder(video) / "ep.aligned.srt").exists() and notes.with_name(notes.name + ".bak").exists()


@needs_ffmpeg
def test_resync_with_speech_says_when_nothing_moved(tmp_path, home, monkeypatch):
    import subtitles
    video, notes = film(tmp_path, shift=0.9)
    before = notes.read_text(encoding="utf-8")

    def same_timing(video, srt, st, opts):
        cues = subtitles.parse_srt(srt)
        aligned = analyze.aligned_path(srt, None, video)
        subtitles.write_srt(cues, {i: 0.1 for i in range(len(cues))}, aligned)
        return aligned, [{"from": "0:00:03", "to": "0:02:20", "offset": 0.1, "lines": 24}]
    monkeypatch.setattr(cn, "retime_for_resync", same_timing)
    monkeypatch.setattr(cn, "have_whisper", lambda: True)
    opts = _opts()
    opts.yes, opts.check_alignment, opts.align_model, opts.window = True, False, None, 10.0
    monkeypatch.setenv("HOME", str(home))
    assert cn.resync(video, cn.inspect(video, opts), opts) == "done"
    assert notes.read_text(encoding="utf-8") == before and not (workfiles.folder(video) / "ep.aligned.srt").exists()


@needs_ffmpeg
def test_resync_leaves_a_different_cut_alone_without_speech_recognition(tmp_path, home):
    video, notes = film(tmp_path, shift=0.9)
    before = notes.read_text(encoding="utf-8")
    make_video(video, burst_period=6.4)                              # the timing drifts: not a constant shift
    r = run_cli("context_notes.py", video, "--resync", "--yes", cwd=tmp_path, home_dir=home, env_extra=SOUND_ONLY)
    assert r.returncode == 1 and "needs faster-whisper" in r.stdout and "Nothing was changed" in r.stdout, r.stdout + r.stderr
    assert notes.read_text(encoding="utf-8") == before and not notes.with_name(notes.name + ".bak").exists()


@needs_ffmpeg
def test_resync_finds_the_notes_when_the_file_type_changed(tmp_path, home):
    video, notes = film(tmp_path, shift=0.9, name="ep.mkv", folder_name="ep.mp4")     # notes under the old .mp4 name
    assert notes.parent.name == "ep.mp4"
    r = run_cli("context_notes.py", video, "--resync", "--yes", cwd=tmp_path, home_dir=home, env_extra=SOUND_ONLY)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Renamed context-notes/ep.mp4/ to context-notes/ep.mkv/" in r.stdout
    assert (workfiles.folder(video) / "notes-ep.json").exists() and not notes.exists()
    assert "already fit this copy" in r.stdout                        # the same copy: nothing to move
