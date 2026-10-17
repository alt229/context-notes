import json
import subprocess

import pytest
from conftest import make_srt, needs_ffmpeg, run_cli

import analyze
import make_ass


def test_hms_and_clean():
    assert analyze.hms(3725.4) == "1:02:05"
    assert analyze.hms(3725.4, frac=True) == "1:02:05.4"
    assert analyze.clean("<i>Hi</i>\n{\\an8}there") == "Hi / there"


def test_write_transcript(tmp_path, sample_srt):
    cues = make_ass.parse_srt(sample_srt)
    out = analyze.write_transcript(cues, tmp_path / "t.txt")
    lines = out.read_text().splitlines()
    assert lines[0] == "1 [0:00:03] Line 1 of the original test script"
    assert len(lines) == len(cues)


# ---------------------------------------------------------------- embedded subtitle helpers
@pytest.mark.parametrize("raw, expected", [
    ("[laughter]", ""),
    ("ROY: Have you tried that?", "Have you tried that?"),
    ("Hello (sighs) there", "Hello  there"),
    ("♪ theme music ♪", ""),
    ("- Yes?\n- (coughs)", "- Yes?"),
    ("Plain dialogue", "Plain dialogue"),
])
def test_strip_sdh(raw, expected):
    assert " ".join(analyze.strip_sdh(raw).split()) == " ".join(expected.split())


def _track(n, codec="subrip", lang="eng", title="", forced=False, sdh=False, default=False):
    return {"n": n, "codec": codec, "lang": lang, "title": title, "forced": forced, "sdh": sdh, "default": default,
            "text": codec in analyze.TEXT_SUB_CODECS, "image": codec in analyze.IMAGE_SUB_CODECS, "frames": ""}


def test_pick_track_prefers_english_full_dialogue():
    tracks = [_track(0, "hdmv_pgs_subtitle"), _track(1, forced=True), _track(2, sdh=True), _track(3),
              _track(4, lang="fre", default=True)]
    assert analyze.pick_track(tracks)["n"] == 3
    assert analyze.pick_track(tracks, wanted=4)["n"] == 4


def test_pick_track_with_only_pictures_returns_none_and_bad_number_exits():
    tracks = [_track(0, "hdmv_pgs_subtitle")]
    assert analyze.pick_track(tracks) is None
    with pytest.raises(SystemExit):
        analyze.pick_track(tracks, wanted=3)
    assert "IMAGE-BASED" in analyze.describe_track(tracks[0])


@needs_ffmpeg
def test_extract_embedded_subtitles_end_to_end(tmp_path):
    en = make_srt(tmp_path / "en.srt", n=3, text="[laughter] ROY: Line {i} here")
    de = make_srt(tmp_path / "de.srt", n=1, text="Zeile {i}")
    video = tmp_path / "ep.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=20:r=5",
                    "-i", str(en), "-i", str(de), "-map", "0", "-map", "1", "-map", "2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
                    "-metadata:s:s:1", "language=ger", "-t", "20", str(video)], check=True)
    tracks = analyze.subtitle_tracks(video)
    assert [(t["lang"], t["codec"]) for t in tracks] == [("eng", "mov_text"), ("ger", "mov_text")]
    out = tmp_path / "ep.embedded.srt"
    cues = analyze.extract_subtitles(video, analyze.pick_track(tracks), out, sdh=True)
    assert [c["text"] for c in cues] == ["Line 1 here", "Line 2 here", "Line 3 here"]
    r = run_cli("analyze.py", video, "--list-tracks")
    assert r.returncode == 0 and "mov_text, eng" in r.stdout
    r = run_cli("analyze.py", video, "--sub-track", 1)
    assert r.returncode == 0 and "Zeile 1" in (tmp_path / "ep.embedded.transcript.txt").read_text()


@needs_ffmpeg
def test_video_without_subtitles_says_so(tmp_path):
    video = tmp_path / "plain.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=2:r=5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    r = run_cli("analyze.py", video)
    assert r.returncode == 1 and "no embedded subtitles" in r.stderr


# ---------------------------------------------------------------- sync check and loud moments
np = pytest.importorskip("numpy")


def _db(seconds, bursts):
    db = np.full(int(seconds * analyze.FPS_A), -90.0)
    for start, length in bursts:
        db[int(start * analyze.FPS_A):int((start + length) * analyze.FPS_A)] = -20.0
    return db


def _cues(n=24, spacing=6.0, first=3.0, length=2.5):
    return [{"n": i + 1, "start": first + spacing * i, "end": first + spacing * i + length, "text": "x"} for i in range(n)]


def test_sync_check_finds_constant_offset():
    cues = _cues()
    db = _db(160, [(c["start"] + 0.9, 2.0) for c in cues])
    sync = analyze.sync_check(db, cues, 160)
    assert sync["offset"] == pytest.approx(0.9, abs=0.1)
    assert "early" in sync["verdict"] and "--offset" in sync["verdict"]


def test_sync_check_reports_in_sync():
    cues = _cues()
    db = _db(160, [(c["start"], 2.0) for c in cues])
    assert analyze.sync_check(db, cues, 160)["verdict"] == "Subtitles look in sync."


def test_sync_check_flags_drift_and_wrong_cut():
    cues = _cues()
    drift = _db(160, [(3.9 + 6.4 * i, 2.0) for i in range(24)])
    assert "--align" in analyze.sync_check(drift, cues, 160)["verdict"]
    assert "different cut" in analyze.sync_check(_db(60, []), cues, 60)["verdict"]


def test_loud_moments_ignores_dialogue_and_finds_gaps():
    cues = _cues()
    db = _db(160, [(c["start"], 2.0) for c in cues] + [(66.2, 1.8)])      # an extra burst between lines
    moments = analyze.loud_moments(db, cues, 0.0)
    assert len(moments) == 1 and moments[0]["start"] == pytest.approx(66.2, abs=0.2)


# ---------------------------------------------------------------- aligning to a transcript
def test_align_finds_one_constant_shift():
    words = ["alpha", "bravo", "charlie", "delta", "echo"]
    cues = [{"n": i + 1, "start": 10.0 * i, "end": 10.0 * i + 3, "text": " ".join(f"{w}{i}" for w in words)}
            for i in range(8)]
    # the same words, 2.0 s later and spoken at about three a second
    asr = [{"s": 0, "e": 0, "t": "", "w": [[c["start"] + 2.0 + k * 0.33, 0, w] for k, w in enumerate(c["text"].split())]}
           for c in cues]
    assigned, segments, stats = analyze.align(cues, asr)
    assert stats["dropped"] == 0 and len(segments) == 1
    assert all(v == pytest.approx(2.0, abs=0.05) for v in assigned.values())


def test_write_srt_drops_unassigned_lines(tmp_path):
    cues = [{"n": 1, "start": 1.0, "end": 2.0, "text": "keep"}, {"n": 2, "start": 3.0, "end": 4.0, "text": "drop"}]
    out = tmp_path / "a.srt"
    analyze.write_srt(cues, {0: 0.5}, out)
    parsed = make_ass.parse_srt(out)
    assert [c["text"] for c in parsed] == ["keep"] and parsed[0]["start"] == pytest.approx(1.5)


def test_cli_transcript_only_and_help(tmp_path, sample_srt):
    r = run_cli("analyze.py", sample_srt, cwd=tmp_path)
    assert r.returncode == 0 and "Subtitles only" in r.stdout
    assert (tmp_path / "show.transcript.txt").exists()
    assert json.dumps(r.stdout)  # printable
    r = run_cli("analyze.py", sample_srt, "--align", cwd=tmp_path)
    assert r.returncode == 1 and "--align needs --video" in r.stderr
