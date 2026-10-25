"""Where working files go (workfiles.py), films an earlier version started, and tidy.py moving their files in."""
import json
import os

from conftest import make_srt, run_cli

import context_notes as cn
import tidy
import workfiles


def touch(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_new_film_gets_a_folder_of_its_own(tmp_path):
    v = touch(tmp_path / "Parasite.mkv")
    w = tmp_path / "context-notes" / "Parasite.mkv"
    assert workfiles.folder(v) == w and workfiles.place(v) == w
    assert workfiles.analysis(v) == w / "analysis"
    assert workfiles.notes_path(v, tmp_path / "Parasite.en.srt") == w / "notes-Parasite.json"
    assert workfiles.folder_for(tmp_path / "Parasite.en.srt") == w                 # the video is found by name
    assert workfiles.folder_for(w / "Parasite.embedded.en.srt") == w
    assert workfiles.folder_for(tmp_path / "Other.srt") == tmp_path                 # no video of that name: as before
    assert workfiles.video_for(w / "Parasite.en.aligned.srt") == v
    assert not workfiles.in_folder(tmp_path / "examples" / "film.srt")


def test_media_servers_are_told_to_skip_the_folder(tmp_path):
    v = touch(tmp_path / "Film.mkv")
    touch(tmp_path / "context-notes" / ".plexignore", "# mine\n")             # one you made yourself stays
    workfiles.make_dirs(workfiles.folder(v) / "analysis" / "frames")
    c = tmp_path / "context-notes"
    assert (c / ".ignore").read_text() == "" and "*" in (c / ".embyignore").read_text()
    assert (c / ".plexignore").read_text() == "# mine\n"
    project = tmp_path / "context-notes-project" / "context-notes" / "examples"      # not a video's folder: nothing
    workfiles.make_dirs(project)
    assert sorted(p.name for p in project.parent.iterdir()) == ["examples"]


def test_a_film_an_earlier_version_started_carries_on_beside_it(tmp_path):
    v = touch(tmp_path / "Film.mp4")
    touch(tmp_path / "Film.srt")
    assert not workfiles.started_before(v)
    touch(tmp_path / "Film.chat-replies.txt")                         # one you make yourself: not a sign
    assert not workfiles.started_before(v)
    touch(tmp_path / "notes-Film.json", "{}")
    assert workfiles.started_before(v) and workfiles.place(v) == tmp_path
    assert workfiles.analysis(v) == tmp_path / "Film analysis"
    assert workfiles.notes_path(v) == tmp_path / "notes-Film.json"
    (tmp_path / "context-notes" / "Film.mp4").mkdir(parents=True)      # once it has a folder, that's where new files go
    assert not workfiles.started_before(v) and workfiles.place(v) == tmp_path / "context-notes" / "Film.mp4"
    assert workfiles.notes_path(v) == tmp_path / "notes-Film.json"   # ...but the old notes are still found


def test_another_films_files_dont_count(tmp_path):
    film, extended = touch(tmp_path / "Film.mp4"), touch(tmp_path / "Film.Extended.mp4")
    touch(tmp_path / "notes-Film.Extended.json", "{}")
    assert workfiles.started_before(extended) and not workfiles.started_before(film)


def test_which_files_are_working_files():
    working = ["notes-Film.json", "notes-Film.json.bak2", "notes-Film.partial.json", "notes-Film.part3.failed.txt",
               "notes-Film.refine-report.txt", "notes-Film.json.before-cleanup.bak", "Film.notes.ass.bak",
               "Film.en.aligned.srt", "Film.aligned.first300s.srt", "Film.en.aligned.srt.bak", "Film.aligned.srt.rejected",
               "Film.embedded.srt", "Film.embedded.fr.srt", "Film.en.transcribed.first600s.srt", "Film.transcript.txt",
               "Film.embedded.transcript.txt", "Film.chat-upload.txt", "Film.chat-replies.txt",
               "Film.en.download-unchecked", "Film.en.download-unreadable"]
    staying = ["Film.notes.ass", "Film.en.ass", "Film.notes-x1.5.ass", "Film.srt", "Film.en.srt", "Film.fr.srt",
               "Film.en.opensubtitles.srt", "Film.SDH.srt", "Film.forced.en.srt", "Film.nfo", "Film-poster.jpg"]
    assert [n for n in working if not workfiles.is_working(n, "Film")] == []
    assert [n for n in staying if workfiles.is_working(n, "Film")] == []
    assert workfiles.is_working("Film analysis", "Film", is_dir=True)
    assert workfiles.is_working("Film chat-replies", "Film", is_dir=True)
    assert not workfiles.is_working("Film extras", "Film", is_dir=True)


def test_subtitles_and_notes_are_found_in_either_place(tmp_path):
    v = touch(tmp_path / "Film.mkv")
    w = workfiles.folder(v)
    w.mkdir(parents=True)
    english = "I don't know what you mean but that is the way it is {i}"
    make_srt(tmp_path / "Film.srt", n=12, text=english)
    make_srt(w / "Film.aligned.srt", n=12, text=english)
    make_srt(w / "Film.embedded.fr.srt", n=2, text="Bonjour {i}")
    assert cn.pick_subtitles(cn.subtitle_files(v), "en") == (w / "Film.aligned.srt", True)
    assert cn.pick_subtitles(cn.subtitle_files(v), "fr")[0] == w / "Film.embedded.fr.srt"
    make_srt(tmp_path / "Film.aligned.srt", n=2)                      # the same name in both: the folder's copy
    assert [s["path"] for s in cn.subtitle_files(v) if s["aligned"]] == [w / "Film.aligned.srt"]
    assert workfiles.find_near(tmp_path / "Film.srt", "Film.embedded.fr.srt") == w / "Film.embedded.fr.srt"
    assert workfiles.find_near(w / "Film.aligned.srt", "Film.srt") == tmp_path / "Film.srt"


def test_videos_in_working_folders_are_not_videos_to_annotate(tmp_path):
    touch(tmp_path / "Film.mkv")
    touch(tmp_path / "context-notes" / "Film.mkv" / "analysis" / "clip.mp4")
    assert cn.find_videos(tmp_path, recursive=True) == [tmp_path / "Film.mkv"]


def old_film(d, stem="Film", ext=".mkv"):
    """What an earlier version left beside a finished film."""
    v = touch(d / f"{stem}{ext}")
    for name in (f"{stem}.srt", f"{stem}.notes.ass", f"{stem}.en.ass", f"{stem}.en.srt"):
        touch(d / name)
    for name in (f"notes-{stem}.json", f"notes-{stem}.json.bak", f"notes-{stem}.refine-report.txt",
                 f"{stem}.aligned.srt", f"{stem}.transcript.txt", f"{stem}.notes.ass.bak"):
        touch(d / name, name)
    touch(d / f"{stem} analysis" / "sheets" / "sheet-001.jpg")
    return v


def test_tidy_lists_asks_and_moves(tmp_path):
    season = tmp_path / "Season 1"
    old_film(season, "S01E01 Pilot")
    old_film(season, "S01E02 Next", ".mp4")
    touch(season / ".DS_Store")
    r = run_cli("tidy.py", tmp_path, "--dry-run")
    assert r.returncode == 0 and "Nothing to tidy" in r.stdout and "--recursive" in r.stdout
    r = run_cli("tidy.py", tmp_path, "--recursive", "--dry-run")
    assert r.returncode == 0 and "14 item(s) for 2 video(s) would move" in r.stdout, r.stdout
    assert "S01E01 Pilot analysis" + os.sep + "  ->  analysis" + os.sep in r.stdout
    assert (season / "notes-S01E01 Pilot.json").exists()                        # a dry run moves nothing
    r = run_cli("tidy.py", tmp_path, "--recursive")
    assert r.returncode == 1 and "add --yes" in r.stderr                         # no terminal: it won't guess
    r = run_cli("tidy.py", tmp_path, "--recursive", "--yes")
    assert r.returncode == 0 and "Moved 14 item(s)." in r.stdout, r.stdout + r.stderr
    assert sorted(p.name for p in season.iterdir()) == [
        ".DS_Store", "S01E01 Pilot.en.ass", "S01E01 Pilot.en.srt", "S01E01 Pilot.mkv", "S01E01 Pilot.notes.ass",
        "S01E01 Pilot.srt", "S01E02 Next.en.ass", "S01E02 Next.en.srt", "S01E02 Next.mp4", "S01E02 Next.notes.ass",
        "S01E02 Next.srt", "context-notes"]
    w = season / "context-notes" / "S01E01 Pilot.mkv"
    assert sorted(p.name for p in w.iterdir()) == [
        "S01E01 Pilot.aligned.srt", "S01E01 Pilot.notes.ass.bak", "S01E01 Pilot.transcript.txt", "analysis",
        "notes-S01E01 Pilot.json", "notes-S01E01 Pilot.json.bak", "notes-S01E01 Pilot.refine-report.txt"]
    assert (w / "analysis" / "sheets" / "sheet-001.jpg").exists()
    assert (w / "notes-S01E01 Pilot.json").read_text() == "notes-S01E01 Pilot.json"     # moved as it was
    r = run_cli("tidy.py", tmp_path, "--recursive", "--yes")
    assert "Nothing to tidy" in r.stdout


def test_tidy_never_overwrites_or_guesses(tmp_path):
    old_film(tmp_path)
    touch(tmp_path / "Film.mp4")                                      # Film.mkv and Film.mp4: whose is notes-Film.json?
    plan, skipped = workfiles.old_files(tmp_path)
    assert plan == {} and len(skipped) == 7
    assert all("Film.mkv or Film.mp4" in why for _, why in skipped)
    (tmp_path / "Film.mp4").unlink()
    taken = touch(tmp_path / "context-notes" / "Film.mkv" / "notes-Film.json", "newer")
    plan, _ = workfiles.old_files(tmp_path)
    moved, problems = tidy.move(plan)
    assert moved == 6 and [p.name for p, _ in problems] == ["notes-Film.json"]
    assert taken.read_text() == "newer" and (tmp_path / "notes-Film.json").exists()


def test_tidy_one_video_and_the_wrapper_points_to_it(tmp_path, home):
    v = old_film(tmp_path)
    other = old_film(tmp_path, "Other")
    (tmp_path / "notes-Film.json").write_text(json.dumps({"notes": []}))
    r = run_cli("context_notes.py", tmp_path, "--status", home_dir=home)
    assert "2 of these video(s) still have working files beside them" in r.stdout and "tidy.py" in r.stdout
    r = run_cli("tidy.py", v, "--yes")
    assert r.returncode == 0 and "Moved 7 item(s)." in r.stdout
    assert (tmp_path / "notes-Other.json").exists() and not (tmp_path / "notes-Film.json").exists()
    r = run_cli("context_notes.py", other, "--status", home_dir=home)
    assert "1 of these video(s) still have" in r.stdout
    r = run_cli("context_notes.py", v, "--status", home_dir=home)
    assert "still have working files" not in r.stdout


def test_scan_ass_and_the_app_know_about_the_folder(tmp_path):
    import app
    import scan_ass
    touch(tmp_path / "Film.mkv")
    ass = touch(tmp_path / "Film.notes.ass")
    notes = touch(tmp_path / "context-notes" / "Film.mkv" / "notes-Film.json", "{}")
    assert scan_ass.notes_file(ass) == notes
    listing = app.browse(str(tmp_path))
    assert [d["name"] for d in listing["dirs"]] == [] and [v["name"] for v in listing["videos"]] == ["Film.mkv"]


def test_chat_notes_writes_into_the_folder(tmp_path):
    v = touch(tmp_path / "Film.mkv")
    srt = make_srt(tmp_path / "Film.srt", n=6, text="I don't know what you mean but that is the way it is {i}")
    r = run_cli("chat_notes.py", "prepare", v, srt, cwd=tmp_path)
    upload = tmp_path / "context-notes" / "Film.mkv" / "Film.chat-upload.txt"
    assert r.returncode == 0 and upload.exists(), r.stdout + r.stderr
    reply = touch(tmp_path / "replies.txt", 'PART 1 OF 1\n[{"cue": 2, "match": "the way it is 2", "category": "idiom", '
                                             '"text": "A note.", "confidence": "high"}]\nDONE')
    r = run_cli("chat_notes.py", "collect", v, srt, reply, cwd=tmp_path)
    assert r.returncode == 0 and (tmp_path / "context-notes" / "Film.mkv" / "notes-Film.json").exists(), r.stdout + r.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["Film.mkv", "Film.srt", "context-notes", "replies.txt"]
