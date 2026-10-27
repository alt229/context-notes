"""The all-in-one wrapper: finding files, deciding what to run, and whole runs on synthetic videos."""
import json
import os
import re
import subprocess

import pytest
from conftest import make_srt, needs_ffmpeg, place, run_cli

import context_notes as cn
import workfiles


# ---------------------------------------------------------------- finding things
def test_subtitle_files_and_picking(tmp_path):
    v = tmp_path / "Film.mkv"
    v.write_bytes(b"")
    make_srt(tmp_path / "Film.srt", n=12, text="I don't know what you mean but that is the way it is {i}")
    make_srt(tmp_path / "Film.fr.srt", n=3, text="Bonjour {i}")
    make_srt(tmp_path / "Film.en.forced.srt", n=2)
    make_srt(tmp_path / "._Film.srt", n=2)                      # macOS resource-fork junk on external drives
    make_srt(tmp_path / "Film 2.srt", n=2)                      # a different film
    subs = {s["path"].name: s for s in cn.subtitle_files(v)}
    assert set(subs) == {"Film.srt", "Film.fr.srt", "Film.en.forced.srt"}
    assert subs["Film.srt"]["lang"] == "en"                     # guessed from the text
    assert cn.pick_subtitles(list(subs.values()), "en") == (tmp_path / "Film.srt", False)
    assert cn.pick_subtitles(list(subs.values()), "fr") == (tmp_path / "Film.fr.srt", False)
    assert cn.pick_subtitles(list(subs.values()), "de") == (None, False)

    make_srt(tmp_path / "Film.aligned.first300s.srt", n=2)
    assert cn.pick_subtitles(cn.subtitle_files(v), "en", limit=300) == (tmp_path / "Film.aligned.first300s.srt", True)
    assert cn.pick_subtitles(cn.subtitle_files(v), "en") == (tmp_path / "Film.srt", False)    # not for a full run
    make_srt(tmp_path / "Film.aligned.srt", n=2)
    assert cn.pick_subtitles(cn.subtitle_files(v), "en") == (tmp_path / "Film.aligned.srt", True)


def test_untagged_subtitles_of_unknown_language_are_used_as_a_last_resort(tmp_path):
    v = tmp_path / "ep.mp4"
    v.write_bytes(b"")
    make_srt(tmp_path / "ep.srt", n=2, text="Hi {i}")            # too short to tell the language
    subs = cn.subtitle_files(v)
    assert cn.pick_subtitles(subs, "en") == (None, False)
    assert cn.pick_subtitles(subs, "en", accept_unknown=True) == (tmp_path / "ep.srt", False)


def test_notes_path_prefers_an_existing_file(tmp_path):
    v = tmp_path / "S01E03 Fifty Fifty.mp4"
    srt = tmp_path / "S01E03 Fifty Fifty.aligned.srt"
    assert cn.notes_path_for(v, srt).name == "notes-S01E03 Fifty Fifty.json"
    (tmp_path / "notes-S01E03 Fifty Fifty.aligned.json").write_text("{}")         # from the old manual workflow
    assert cn.notes_path_for(v, srt).name == "notes-S01E03 Fifty Fifty.aligned.json"


@pytest.mark.parametrize("rel, show, title", [
    ("IT Crowd/Season 1/S01E03 Fifty Fifty.mp4", None, "IT Crowd - S01E03 Fifty Fifty"),
    ("IT Crowd/S01E03 Fifty Fifty.mp4", None, "IT Crowd - S01E03 Fifty Fifty"),
    ("Films/Romeo.And.Juliet.1968.720p.BluRay.x264-[YTS.AG].mp4", None, "Romeo And Juliet 1968"),
    ("Films/Amélie.mkv", None, "Amélie"),
    ("sample-media/Amélie.2001.mp4", None, "Amélie 2001"),
    ("x/Season 2/2x01.mkv", "Black Books", "Black Books - 2x01"),
])
def test_guess_title(tmp_path, rel, show, title):
    assert cn.guess_title(tmp_path / rel, show) == title


def test_sync_decision_and_covers():
    assert cn.sync_decision({"offset": 0.1, "verdict": "Subtitles look in sync."}) == "ok"
    assert cn.sync_decision({"offset": 0.9, "verdict": "Subtitles look early by about 0.90 s"}) == "offset"
    assert cn.sync_decision({"offset": 0.4, "verdict": "The offset changes through the video: use --align."}) == "align"
    assert cn.sync_decision({"offset": None, "verdict": "Not enough clean dialogue starts"}) == "unknown"
    assert cn.covers(None, None) and cn.covers(None, 300) and cn.covers(600, 300)
    assert not cn.covers(300, None) and not cn.covers(300, 600)


def test_ask_takes_the_default_when_unattended(capsys):
    assert cn.ask("Go?", {"y": "yes", "n": "no"}, "n", auto=True) == "n"
    assert "-> no (automatic)" in capsys.readouterr().out


# ---------------------------------------------------------------- whole runs (synthetic video, fake API)
np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from test_generate_notes import notes_for_each_part  # noqa: E402
from test_refine_notes import make_video, refine_responder  # noqa: E402


def both(n, body, headers):
    return (refine_responder if "You refine" in body["system"] else notes_for_each_part)(n, body, headers)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("clips")
    make_video(d / "synced.mp4")
    make_video(d / "drift.mp4", burst_period=6.4)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(d / "synced.mp4"), "-c", "copy",
                    "-metadata:s:a:0", "language=fre", str(d / "french.mp4")], check=True)
    return d


def wrapper(*args, home, cwd):
    return run_cli("context_notes.py", *args, cwd=cwd, home_dir=home)


@needs_ffmpeg
def test_wrapper_runs_everything_then_skips_what_is_done(tmp_path, clips, api, api_key_file, home):
    season = tmp_path / "Test Show" / "Season 1"
    season.mkdir(parents=True)
    place(clips / "synced.mp4", season / "S01E01 Pilot.mp4")
    make_srt(season / "S01E01 Pilot.srt", n=24)
    api.responder = both

    r = wrapper(season, "--yes", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"Fixed the timing: S01E01 Pilot.aligned.srt is S01E01 Pilot.srt shifted \+0\.[89]", r.stdout)
    assert "Ready: play S01E01 Pilot.mp4" in r.stdout
    w = workfiles.folder(season / "S01E01 Pilot.mp4")                          # context-notes/S01E01 Pilot.mp4
    shown = os.path.join("context-notes", "S01E01 Pilot.mp4", "")
    assert (f'$ python3 "$CN/make_ass.py" \'{shown}S01E01 Pilot.aligned.srt\' \'{shown}notes-S01E01 Pilot.json\' '
            f'--generate') in r.stdout
    fixed = w / "S01E01 Pilot.aligned.srt"
    assert fixed.exists() and "00:00:03,8" in fixed.read_text()                # 3.0 s + the measured 0.88
    spec = json.loads((w / "notes-S01E01 Pilot.json").read_text())
    assert spec["refined"] and abs(spec.get("video_offset", 0)) < 0.25            # the file is fixed, not the notes
    assert (season / "S01E01 Pilot.notes.ass").exists()
    assert (w / "analysis" / "soundtrack.npy").exists()                         # measured once, reused by --refine
    assert sorted(p.name for p in season.iterdir()) == [                         # beside it: only what players use
        "S01E01 Pilot.en.ass", "S01E01 Pilot.mp4", "S01E01 Pilot.notes.ass", "S01E01 Pilot.srt", "context-notes"]
    first = api.calls[0]["body"]["messages"][0]["content"]
    assert "Title: Test Show - S01E01 Pilot" in first
    calls = len(api.calls)

    r = wrapper(season, "--yes", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0 and "Already done" in r.stdout and len(api.calls) == calls
    r = wrapper(season, "--status", home=home, cwd=tmp_path)
    assert "[ done] S01E01 Pilot.mp4" in r.stdout and "refined" in r.stdout


@needs_ffmpeg
def test_wrapper_limit_then_full_run(tmp_path, clips, api, api_key_file, home):
    place(clips / "synced.mp4", tmp_path / "ep.mp4")
    make_srt(tmp_path / "ep.srt", n=24)
    api.responder = both
    r = wrapper(tmp_path / "ep.mp4", "--yes", "--limit", "1:00", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    w = workfiles.folder(tmp_path / "ep.mp4")
    spec = json.loads((w / "notes-ep.json").read_text())
    assert spec["limit"] == 60 and spec["refined"]["limit"] == 60
    gen = [c for c in api.calls if "You refine" not in c["body"]["system"]]
    assert all("Line 11 of" not in c["body"]["messages"][0]["content"] for c in gen)
    ref = [c for c in api.calls if "You refine" in c["body"]["system"]]
    assert ref and all("to 0:01:01 (video time)" in [b for b in c["body"]["messages"][0]["content"]
                                                     if b["type"] == "text"][-1]["text"] for c in ref[-1:])

    sent = len(api.calls)
    r = wrapper(tmp_path / "ep.mp4", "--yes", "--no-refine", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "only covers the first 1:00" in r.stdout and "-> add the rest (automatic)" in r.stdout
    assert "--generate" in r.stdout and "--extend" in r.stdout
    spec = json.loads((w / "notes-ep.json").read_text())
    assert "limit" not in spec and (w / "notes-ep.json.bak").exists()
    assert spec["refined"]["limit"] == 60                                          # the frames step's record is kept
    firsts = [int(re.search(r"Lines to annotate \((\d+) to", c["body"]["messages"][0]["content"]).group(1))
              for c in api.calls[sent:]]
    assert firsts and min(firsts) == 11                                            # lines 1-10 aren't sent again

    sent = len(api.calls)
    r = wrapper(tmp_path / "ep.mp4", "--yes", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "The frames were looked at for the first 1:00 before, so only the rest is sent now." in r.stdout
    starts = [re.search(r"This stretch: (\S+) to", [b for b in c["body"]["messages"][0]["content"]
                                                     if b["type"] == "text"][-1]["text"]).group(1) for c in api.calls[sent:]]
    assert starts and starts[0] == "0:01:00", starts                               # the first minute isn't sent again
    assert "limit" not in json.loads((w / "notes-ep.json").read_text())["refined"]


@needs_ffmpeg
def test_wrapper_with_drifting_subtitles_carries_on_with_on_screen_notes(tmp_path, clips, api, api_key_file, home,
                                                                          monkeypatch):
    place(clips / "drift.mp4", tmp_path / "ep.mp4")
    make_srt(tmp_path / "ep.srt", n=24)
    api.responder = both
    r = wrapper(tmp_path / "ep.mp4", "--yes", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "doesn't match this video all the way through" in r.stdout
    assert "on-screen notes only" in r.stdout


def french_film(tmp_path, clips):
    place(clips / "french.mp4", tmp_path / "Le Film.mp4")
    make_srt(tmp_path / "Le Film.en.srt", n=24)
    make_srt(tmp_path / "Le Film.fr.srt", n=24, text="Je ne sais pas ce que tu veux dire, réplique {i}")


@needs_ffmpeg
def test_wrapper_french_film_reads_french_subtitles_with_english_notes(tmp_path, clips, api, api_key_file, home):
    french_film(tmp_path, clips)
    api.responder = both
    r = wrapper(tmp_path / "Le Film.mp4", "--yes", "--no-refine", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tagged French" in r.stdout and "Notes written from the French subtitles, in English" in r.stdout
    assert "Le Film.fr.aligned.srt is Le Film.fr.srt shifted" in r.stdout                  # French timing fixed
    body = api.calls[0]["body"]
    assert "The subtitles are in French too" in body["system"] and "never translate the quote" in body["system"]
    assert "Write every note in English" in body["system"] and "Poser un lapin" in body["system"]
    assert "Je ne sais pas" in body["messages"][0]["content"] and "‹fr:" not in body["messages"][0]["content"]
    spec = json.loads((workfiles.folder(tmp_path / "Le Film.mp4") / "notes-Le Film.json").read_text())
    assert spec["film_language"] == "fr" and "original French subtitles" in spec["audience"]
    ass = (tmp_path / "Le Film.notes.ass").read_text(encoding="utf-8-sig")
    assert "Je ne sais pas" in ass and "English line" not in ass


@needs_ffmpeg
def test_wrapper_french_film_with_english_subtitles_compares_both(tmp_path, clips, api, api_key_file, home):
    french_film(tmp_path, clips)
    api.responder = both
    r = wrapper(tmp_path / "Le Film.mp4", "--yes", "--no-refine", "--subs-language", "en", "--api-url", api.url,
                home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Checking the timing of Le Film.fr.srt" in r.stdout and "Using Le Film.fr.aligned.srt" in r.stdout
    body = api.calls[0]["body"]
    assert "The film is in French" in body["system"] and "‹fr: Je ne sais pas" in body["messages"][0]["content"]


@needs_ffmpeg
def test_wrapper_says_when_there_are_no_subtitles(tmp_path, clips, api_key_file, home):
    place(clips / "synced.mp4", tmp_path / "bare.mp4")
    r = wrapper(tmp_path, "--yes", home=home, cwd=tmp_path)
    assert r.returncode == 1 and "No English subtitles for bare.mp4" in r.stdout


def test_wrapper_stops_early_without_an_api_key(tmp_path, home):
    (tmp_path / "ep.mp4").write_bytes(b"")
    make_srt(tmp_path / "ep.srt", n=3)
    r = wrapper(tmp_path, "--yes", home=home, cwd=tmp_path)
    assert r.returncode == 1 and "--set-api-key" in r.stderr and "Checking the subtitles" not in r.stdout
    r = wrapper(tmp_path, "--status", home=home, cwd=tmp_path)
    assert r.returncode == 0 and "[to do] ep.mp4" in r.stdout


def test_accented_names_match_however_they_are_spelled(tmp_path):
    """Downloaded files can name 'é' as e + an accent mark (NFD) while a typed name uses one character (NFC)."""
    import unicodedata
    nfd = unicodedata.normalize("NFD", "Amélie.2001")
    nfc = unicodedata.normalize("NFC", "Amélie.2001")
    assert nfd != nfc
    v = tmp_path / f"{nfc}.mp4"
    v.write_bytes(b"")
    make_srt(tmp_path / f"{nfd}.fr.srt", n=3, text="Bonjour {i}")
    make_srt(tmp_path / f"{nfc}.fr.aligned.srt", n=3, text="Bonjour {i}")
    (tmp_path / f"notes-{nfd}.json").write_text("{}")
    assert cn.pick_subtitles(cn.subtitle_files(v), "fr") == (tmp_path / f"{nfc}.fr.aligned.srt", True)
    assert cn.notes_path_for(v, None) == tmp_path / f"notes-{nfd}.json"


@needs_ffmpeg
def test_wrapper_show_subs_swaps_the_subtitles_on_screen_without_new_api_calls(tmp_path, clips, api, api_key_file,
                                                                                home):
    french_film(tmp_path, clips)
    api.responder = both
    r = wrapper(tmp_path / "Le Film.mp4", "--yes", "--no-refine", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    ass_path = tmp_path / "Le Film.notes.ass"
    before = ass_path.read_text(encoding="utf-8-sig")
    calls = len(api.calls)

    r = wrapper(tmp_path / "Le Film.mp4", "--yes", "--no-refine", "--show-subs", "en", "--api-url", api.url,
                home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(api.calls) == calls                                             # nothing sent
    assert "On screen: Le Film.en" in r.stdout
    after = ass_path.read_text(encoding="utf-8-sig")
    dialogue = [line for line in after.splitlines() if line.startswith("Dialogue: 0,")]
    assert dialogue and all("Line " in d for d in dialogue) and not any("Je ne sais pas" in d for d in dialogue)
    notes_before = [line for line in before.splitlines() if ",speech/" in line]
    notes_after = [line for line in after.splitlines() if ",speech/" in line]
    assert notes_after == notes_before                                        # same notes, same times
    notes = workfiles.folder(tmp_path / "Le Film.mp4") / "notes-Le Film.json"
    spec = json.loads(notes.read_text())
    assert spec["display_subtitles"].startswith("Le Film.en")

    # remembered: a plain run (no --show-subs) leaves it alone; --show-subs fr switches back
    r = wrapper(tmp_path / "Le Film.mp4", "--yes", "--no-refine", home=home, cwd=tmp_path)
    assert "Already done" in r.stdout and "Line 1 of" in ass_path.read_text(encoding="utf-8-sig")
    r = wrapper(tmp_path / "Le Film.mp4", "--yes", "--no-refine", "--show-subs", "fr", home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Je ne sais pas" in [line for line in ass_path.read_text(encoding="utf-8-sig").splitlines()
                                if line.startswith("Dialogue: 0,")][0]
    assert "display_subtitles" not in json.loads(notes.read_text())


@needs_ffmpeg
def test_other_subtitles_on_screen_count_as_a_free_rebuild(tmp_path, clips, api, api_key_file, home):
    french_film(tmp_path, clips)
    api.responder = both
    film = tmp_path / "Le Film.mp4"
    r = wrapper(film, "--yes", "--no-refine", "--api-url", api.url, home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    r = wrapper(film, "--status", "--no-refine", "--show-subs", "fr", home=home, cwd=tmp_path)
    assert "[ done] Le Film.mp4" in r.stdout                                  # French is what it shows already
    r = wrapper(film, "--status", "--no-refine", "--show-subs", "en", home=home, cwd=tmp_path)
    assert "[to do] Le Film.mp4" in r.stdout and "needs rebuilding (free) to show the English subtitles" in r.stdout
    calls = len(api.calls)
    r = wrapper(film, "--yes", "--no-refine", "--show-subs", "en", home=home, cwd=tmp_path)    # no API key needed
    assert r.returncode == 0 and len(api.calls) == calls and "On screen: Le Film.en" in r.stdout, r.stdout + r.stderr
    r = wrapper(film, "--status", "--no-refine", "--show-subs", "en", home=home, cwd=tmp_path)
    assert "[ done] Le Film.mp4" in r.stdout
    r = wrapper(film, "--status", "--no-refine", home=home, cwd=tmp_path)    # no choice given: whatever it shows
    assert "[ done] Le Film.mp4" in r.stdout


def test_subtitles_in_another_language_are_named_in_the_message(tmp_path):
    v = tmp_path / "Casablanca.1942.avi"
    v.write_bytes(b"")
    text = "Com o início da Segunda Grande Guerra, muitos na Europa sonhavam com a liberdade, mas não era fácil {i}"
    p = make_srt(tmp_path / "Casablanca.1942.srt", n=30, text=text)
    p.write_bytes(p.read_text(encoding="utf-8").replace("\n", "\r\n").encode("latin-1"))    # ISO-8859, CRLF
    subs = cn.subtitle_files(v)
    assert subs[0]["lang"] == "pt"
    msg = cn.no_subtitles_message(v, "en")
    assert "Casablanca.1942.srt (looks Portuguese)" in msg and "Casablanca.1942.en.srt" in msg


def test_a_rebuild_keeps_a_backup_of_the_ass_it_replaces(tmp_path):
    video = tmp_path / "Film.mkv"
    (tmp_path / "Film.notes.ass").write_text("old look", encoding="utf-8")
    cn.keep_old_ass(video)
    assert (tmp_path / "Film.notes.ass.bak").read_text(encoding="utf-8") == "old look"
    cn.keep_old_ass(video)                                          # a second rebuild keeps this one too
    assert (tmp_path / "Film.notes.ass.bak2").exists()


def test_the_rebuild_diff_shows_the_look_now_and_after(tmp_path):
    from argparse import Namespace
    ass = tmp_path / "Film.notes.ass"
    ass.write_text("[Script Info]\nTitle: old\n", encoding="utf-8")       # made before 0.2.0: no look line
    st = {"video": tmp_path / "Film.mp4", "ass": ass, "spec": {"note_background": "dark"}, "srt": None,
          "film_language": "en", "display_lang": "en", "subs": []}
    opts = Namespace(reading_speed=None, note_background=None, note_opacity=None, show_subs=None, limit=None)
    diff = cn.rebuild_diff(st, opts)
    rows = {r["setting"]: r for r in diff["rows"]}
    assert rows["Box behind the notes"] == {"setting": "Box behind the notes",
                                            "now": "not recorded (made before 0.2.0)", "after": "dark", "changed": True}
    assert "Box opacity" not in rows                                 # the dark box has no opacity setting
    assert rows["Words a minute"]["after"] == "150"
    assert any(f.startswith("Kept: Film.notes.ass.bak") for f in diff["files"])
    assert any("Film.en.ass" in f for f in diff["files"])
    assert diff["embedded"] is False
