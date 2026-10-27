"""embed.py: putting a film's notes inside the .mkv as a subtitle track, and the wrapper's --embed."""
import hashlib
import os
import shutil
import subprocess
from collections import namedtuple

import pytest
from conftest import needs_ffmpeg, run_cli

import context_notes as cn
import embed
import workfiles

ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288

[V4+ Styles]
Format: @STYLE_FORMAT@
Style: NoteL,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,1,0,7,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,NoteL,,0,0,0,,{\\fad(250,350)}A note
"""
STYLE_FORMAT = ("Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
                "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
                "MarginL, MarginR, MarginV, Encoding")
ASS = ASS.replace("@STYLE_FORMAT@", STYLE_FORMAT)
Usage = namedtuple("Usage", "total used free")


def digest(path):
    return hashlib.sha1(open(path, "rb").read()).hexdigest()


def make_clips(d):
    """Small films in a folder: plain.mkv, disc.mkv (a subtitle track and chapters) and plain.mp4."""
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=4:size=160x120:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-t", "4", str(d / "plain.mkv")], check=True)
    # one with a subtitle track (default) and two chapters, like a film from a disc
    (d / "subs.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
    (d / "chapters.txt").write_text(";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=2000\ntitle=One\n"
                                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=2000\nEND=4000\ntitle=Two\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(d / "plain.mkv"), "-i", str(d / "subs.srt"), "-i",
                    str(d / "chapters.txt"), "-map", "0", "-map", "1", "-map_chapters", "2", "-c", "copy", "-c:s", "srt",
                    "-metadata:s:s:0", "language=eng", "-disposition:s:0", "default", str(d / "disc.mkv")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(d / "plain.mkv"), "-c", "copy", str(d / "plain.mp4")],
                   check=True)
    return d


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    return make_clips(tmp_path_factory.mktemp("embed-clips"))


def film(tmp_path, clips, source="plain.mkv", name="Film"):
    video = tmp_path / f"{name}{os.path.splitext(source)[1]}"
    shutil.copyfile(clips / source, video)
    video.with_suffix(".notes.ass").write_text(ASS, encoding="utf-8-sig")
    return video


def notes_track(video):
    tracks = embed.notes_tracks(embed.probe(video))
    assert len(tracks) <= 1
    return tracks[0] if tracks else None


@needs_ffmpeg
def test_adds_a_notes_track_and_keeps_the_original(tmp_path, clip):
    video = film(tmp_path, clip)
    before = digest(video)
    r = run_cli("embed.py", video, "--yes", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    track = notes_track(video)
    assert track["codec_name"] == "ass" and embed.tag(track, "title") == "Context Notes"
    assert embed.tag(track, "language") == "eng" and track["disposition"]["default"] == 0     # there to choose
    assert embed.tag(track, embed.HASH_TAG) == embed.sha1(video.with_suffix(".notes.ass"))
    kept = embed.backup_path(video)
    assert kept == tmp_path / "context-notes" / "Film.mkv" / "Film.original.mkv" and digest(kept) == before
    assert (tmp_path / "context-notes" / ".plexignore").exists()                # media servers skip the folder
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Film.mkv", "Film.notes.ass", "context-notes"]
    assert not list((tmp_path / "context-notes" / "Film.mkv").glob("*.embedding.mkv"))


@needs_ffmpeg
def test_default_makes_the_notes_play(tmp_path, clip):
    video = film(tmp_path, clip)
    assert run_cli("embed.py", video, "--yes", "--default", cwd=tmp_path).returncode == 0
    assert notes_track(video)["disposition"]["default"] == 1


@needs_ffmpeg
def test_a_second_run_changes_nothing(tmp_path, clip):
    video = film(tmp_path, clip)
    assert run_cli("embed.py", video, "--yes", cwd=tmp_path).returncode == 0
    stat = video.stat()
    r = run_cli("embed.py", video, "--yes", cwd=tmp_path)
    assert r.returncode == 0 and "already has these notes inside" in r.stdout and "Nothing to do" in r.stdout
    assert video.stat().st_mtime_ns == stat.st_mtime_ns and video.stat().st_size == stat.st_size


@needs_ffmpeg
def test_changed_notes_replace_the_track_and_the_first_original_stays(tmp_path, clip):
    video = film(tmp_path, clip)
    before = digest(video)
    assert run_cli("embed.py", video, "--yes", cwd=tmp_path).returncode == 0
    ass = video.with_suffix(".notes.ass")
    ass.write_text(ASS + "Dialogue: 0,0:00:02.00,0:00:03.50,NoteL,,0,0,0,,EDITED\n", encoding="utf-8-sig")
    r = run_cli("embed.py", video, "--yes", cwd=tmp_path)
    assert r.returncode == 0 and "replace the notes inside" in r.stdout, r.stdout + r.stderr
    assert embed.tag(notes_track(video), embed.HASH_TAG) == embed.sha1(ass)          # one track, from the new notes
    assert digest(embed.backup_path(video)) == before                                # still the true original
    assert sorted(p.name for p in (tmp_path / "context-notes" / "Film.mkv").iterdir()) == ["Film.original.mkv"]


@needs_ffmpeg
def test_other_tracks_and_chapters_are_kept(tmp_path, clip):
    video = film(tmp_path, clip, "disc.mkv")
    assert run_cli("embed.py", video, "--yes", cwd=tmp_path).returncode == 0
    info = embed.probe(video)
    subs = [s for s in info["streams"] if s["codec_type"] == "subtitle"]
    assert [s["codec_name"] for s in subs] == ["subrip", "ass"]                      # the notes come last
    assert subs[0]["disposition"]["default"] == 1 and subs[1]["disposition"]["default"] == 0
    assert len(info["chapters"]) == 2 and [s["codec_type"] for s in info["streams"][:2]] == ["video", "audio"]


@needs_ffmpeg
def test_what_is_skipped_and_why(tmp_path, clip):
    mp4 = film(tmp_path, clip, "plain.mp4", "Movie")
    assert embed.inspect(mp4)["action"] == "skip" and ".mkv only" in embed.inspect(mp4)["reason"]
    bare = tmp_path / "Bare.mkv"
    shutil.copyfile(clip / "plain.mkv", bare)
    assert embed.inspect(bare)["action"] == "skip" and "no Bare.notes.ass" in embed.inspect(bare)["reason"]
    part = film(tmp_path, clip, name="Part")
    workfiles.make_dirs(workfiles.folder(part))
    (workfiles.folder(part) / "notes-Part.json").write_text('{"limit": 300, "notes": []}')
    why = embed.inspect(part)
    assert why["action"] == "skip" and "only cover the first 5:00" in why["reason"]
    r = run_cli("embed.py", part, "--yes", cwd=tmp_path)
    assert r.returncode == 0 and "Nothing to do" in r.stdout and embed.notes_tracks(embed.probe(part)) == []
    target = film(tmp_path, clip, name="Target")
    link = tmp_path / "Link.mkv"
    try:
        os.symlink(target, link)
    except OSError:                                                                  # Windows without Developer Mode
        return
    link.with_suffix(".notes.ass").write_text(ASS)
    assert embed.inspect(link)["action"] == "skip" and "link" in embed.inspect(link)["reason"]


@needs_ffmpeg
def test_a_folder_lists_what_it_would_do_and_dry_run_changes_nothing(tmp_path, clip):
    a, m = film(tmp_path, clip, name="A"), film(tmp_path, clip, "plain.mp4", "B")
    sub = tmp_path / "Season 2"
    sub.mkdir()
    c = film(sub, clip, name="C")
    before = {p: digest(p) for p in (a, m, c)}
    r = run_cli("embed.py", tmp_path, "--dry-run", cwd=tmp_path)
    assert r.returncode == 0 and "A.mkv: put the notes inside" in r.stdout and "B.mp4: skipped" in r.stdout, r.stdout
    assert "C.mkv" not in r.stdout and "would get their notes inside" in r.stdout          # subfolders: --recursive
    r = run_cli("embed.py", tmp_path, "--recursive", "--dry-run", cwd=tmp_path)
    assert "C.mkv" in r.stdout.replace(os.sep, "/") or "Season 2" in r.stdout
    assert {p: digest(p) for p in (a, m, c)} == before and not (tmp_path / "context-notes").exists()


@needs_ffmpeg
def test_a_new_file_that_fails_its_check_leaves_the_film_alone(tmp_path, clip, monkeypatch, capsys):
    video = film(tmp_path, clip)
    before = digest(video)
    monkeypatch.setattr(embed, "verify", lambda *a: "the tracks differ")
    assert embed.main([str(video), "--yes"]) == 1
    assert "was left as it was" in capsys.readouterr().out
    assert digest(video) == before and not embed.backup_path(video).exists()
    assert not list((tmp_path / "context-notes" / "Film.mkv").glob("*.embedding.mkv"))


@needs_ffmpeg
def test_not_enough_free_space_is_said_before_anything_is_written(tmp_path, clip, monkeypatch, capsys):
    video = film(tmp_path, clip)
    before = digest(video)
    monkeypatch.setattr(embed.shutil, "disk_usage", lambda p: Usage(10**9, 10**9, 1000))
    assert embed.main([str(video), "--yes"]) == 1
    assert "not enough free space" in capsys.readouterr().out and digest(video) == before
    assert not list(tmp_path.rglob("*.embedding.mkv"))


@needs_ffmpeg
def test_delete_backups_only_where_the_notes_are_inside(tmp_path, clip):
    done, waiting = film(tmp_path, clip, name="Done"), film(tmp_path, clip, name="Waiting")
    assert run_cli("embed.py", done, "--yes", cwd=tmp_path).returncode == 0
    workfiles.make_dirs(workfiles.folder(waiting))
    embed.backup_path(waiting).write_bytes(b"someone's own file")                  # not ours to delete: no notes inside
    assert run_cli("embed.py", tmp_path, "--delete-backups", "--dry-run", cwd=tmp_path).returncode == 0
    assert embed.backup_path(done).exists()
    r = run_cli("embed.py", tmp_path, "--delete-backups", "--yes", cwd=tmp_path)
    assert r.returncode == 0 and "Deleted 1 file(s)" in r.stdout, r.stdout + r.stderr
    assert not embed.backup_path(done).exists() and embed.backup_path(waiting).exists()
    assert len(embed.notes_tracks(embed.probe(done))) == 1


def test_the_wrapper_embeds_mkv_and_leaves_mp4_alone(tmp_path, monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(cn, "run", lambda cmd, cwd: ran.append(cmd) or 0)

    class Opts:
        yes = True
    assert cn.embed_step(tmp_path / "Film.mkv", Opts()) is True
    assert len(ran) == 1 and ran[0][1].endswith("embed.py") and "--yes" in ran[0] and str(tmp_path / "Film.mkv") in ran[0]
    ran.clear()
    assert cn.embed_step(tmp_path / "Film.mp4", Opts()) is True and not ran
    assert "Film.mp4 stays as it is" in capsys.readouterr().out
    Opts.yes = False
    cn.embed_step(tmp_path / "Film.mkv", Opts())
    assert "--yes" not in ran[0]
    monkeypatch.setattr(cn, "run", lambda cmd, cwd: 1)
    assert cn.embed_step(tmp_path / "Film.mkv", Opts()) is False


def test_rewrite_time_is_a_range_from_the_measured_speeds():
    size = 2_100_000_000
    low, high = embed.rewrite_seconds(size)
    assert low == pytest.approx(max(size / (embed.READ_MBPS * 1e6), size / (embed.WRITE_MBPS * 1e6)))
    assert high == pytest.approx(2 * (size / (embed.READ_MBPS * 1e6) + size / (embed.WRITE_MBPS * 1e6)))
    assert 0 < low < high


def test_warning_gives_time_no_api_and_the_copy_kept_only_for_new_films():
    new = {"size": 2_000_000_000, "action": "add"}
    old = {"size": 1_000_000_000, "action": "update"}
    text = embed.warning_text([new, old])
    assert "About 1 min to 4 min" in text
    assert "No Claude or API calls are made." in text
    assert "The original of 1 film(s) stays in its" in text and "--delete-backups" in text
    assert "stays in its" not in embed.warning_text([old])          # replacing a film keeps no new copy


def test_look_of_reads_the_look_line(tmp_path):
    ass = tmp_path / "Film.notes.ass"
    ass.write_text("[Script Info]\n; Look: build 2, background see-through, opacity 30%, 150 words a minute\n",
                   encoding="utf-8")
    assert embed.look_of(ass) == {"background": "see-through", "opacity": 30.0, "wpm": 150.0}
    ass.write_text("[Script Info]\n; Look: build 2, background none, 150 words a minute\n", encoding="utf-8")
    assert embed.look_of(ass) == {"background": "none", "opacity": None, "wpm": 150.0}
    assert embed.look_of(tmp_path / "missing.ass") is None


@needs_ffmpeg
def test_film_state_says_whether_the_notes_are_inside(tmp_path, clip):
    video = film(tmp_path, clip)
    assert embed.film_state(video)["action"] == "add"
    assert run_cli("embed.py", video, "--yes", cwd=tmp_path).returncode == 0
    state = embed.film_state(video)
    assert state["action"] == "current" and "look" in state
    mp4 = film(tmp_path, clip, "plain.mp4", name="Other")
    state = embed.film_state(mp4)
    assert state["action"] == "skip" and ".mkv only" in state["reason"]


def subbed_mp4(tmp_path, clips, name="Film"):
    """An .mp4 with a text subtitle track (mov_text, as MP4 files carry them) and its notes beside it."""
    video = tmp_path / f"{name}.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(clips / "plain.mp4"), "-i", str(clips / "subs.srt"),
                    "-map", "0", "-map", "1", "-c", "copy", "-c:s", "mov_text", str(video)], check=True)
    video.with_suffix(".notes.ass").write_text(ASS, encoding="utf-8-sig")
    return video


@needs_ffmpeg
def test_mp4_is_skipped_unless_converting(tmp_path, clip):
    video = subbed_mp4(tmp_path, clip)
    r = run_cli("embed.py", video, "--dry-run", cwd=tmp_path)
    assert ".mkv only" in r.stdout and "convert" not in r.stdout


@needs_ffmpeg
def test_convert_makes_an_mkv_and_keeps_the_mp4_in_originals(tmp_path, clip):
    video = subbed_mp4(tmp_path, clip)
    before = digest(video)
    r = run_cli("embed.py", video, "--convert", "--dry-run", cwd=tmp_path)
    assert "convert to .mkv, then put the notes inside" in r.stdout
    r = run_cli("embed.py", video, "--convert", "--yes", cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    mkv = tmp_path / "Film.mkv"
    assert mkv.exists() and not video.exists()
    assert digest(tmp_path / "context-notes" / "originals" / "Film.mp4") == before
    track = notes_track(mkv)
    assert track["codec_name"] == "ass" and embed.tag(track, "title") == "Context Notes"
    subs = [s["codec_name"] for s in embed.probe(mkv)["streams"] if s["codec_type"] == "subtitle"]
    assert subs == ["subrip", "ass"]              # the film's own subtitles became SRT; the notes track is last
    assert embed.film_state(mkv)["action"] == "current"
    assert (tmp_path / "context-notes" / ".plexignore").exists()


@needs_ffmpeg
def test_delete_backups_also_removes_the_kept_mp4(tmp_path, clip):
    video = subbed_mp4(tmp_path, clip)
    assert run_cli("embed.py", video, "--convert", "--yes", cwd=tmp_path).returncode == 0
    kept = tmp_path / "context-notes" / "originals" / "Film.mp4"
    assert kept.exists()
    assert run_cli("embed.py", tmp_path / "Film.mkv", "--delete-backups", "--yes", cwd=tmp_path).returncode == 0
    assert not kept.exists()


@needs_ffmpeg
def test_convert_is_refused_when_an_mkv_of_that_name_is_there(tmp_path, clip):
    video = subbed_mp4(tmp_path, clip)
    film(tmp_path, clip, name="Film")                    # Film.mkv already exists
    r = run_cli("embed.py", video, "--convert", "--dry-run", cwd=tmp_path)
    assert "a .mkv of this name is already here" in r.stdout and "Nothing to do" in r.stdout
