"""cleanup.py: planning standard names for a film or TV library. It only lists; nothing on disk may change."""
import json
import os
import time

import pytest

pytest.importorskip("guessit")

import cleanup  # noqa: E402


class FakeTMDB:
    """A few films and shows, answered the way TMDB's API answers (only the fields cleanup reads)."""
    MOVIES = [
        {"id": 583, "title": "Life of Brian", "original_title": "Life of Brian", "release_date": "1979-08-17",
         "vote_count": 3000},
        {"id": 149, "title": "Akira", "original_title": "AKIRA", "release_date": "1988-07-16", "vote_count": 5101},
        {"id": 1536217, "title": "空前のアニメ巨編 AKIRA アキラが動き出す!", "original_title": "空前のアニメ巨編 AKIRA",
         "release_date": "1988-08-07", "vote_count": 0},
        {"id": 106, "title": "Predator", "original_title": "Predator", "release_date": "1987-06-12", "vote_count": 9648},
        {"id": 1308427, "title": "Predator", "original_title": "Grabljivac", "release_date": "1987-01-01",
         "vote_count": 0},
        {"id": 240, "title": "The Godfather Part II", "original_title": "The Godfather Part II",
         "release_date": "1974-12-20", "vote_count": 12000},
        {"id": 194, "title": "Amélie", "original_title": "Le Fabuleux Destin d'Amélie Poulain",
         "release_date": "2001-04-25", "vote_count": 11000},
        {"id": 762, "title": "Monty Python and the Holy Grail", "original_title": "Monty Python and the Holy Grail",
         "release_date": "1975-04-03", "vote_count": 6000},
        {"id": 861, "title": "Total Recall", "original_title": "Total Recall", "release_date": "1990-06-01",
         "vote_count": 7000},
        {"id": 64635, "title": "Total Recall", "original_title": "Total Recall", "release_date": "2012-08-02",
         "vote_count": 6500},
        {"id": 670, "title": "Oldboy", "original_title": "올드보이", "release_date": "2003-11-21", "vote_count": 9000},
    ]
    SHOWS = [
        {"id": 57243, "name": "Doctor Who", "original_name": "Doctor Who", "first_air_date": "2005-03-26",
         "vote_count": 3000},
        {"id": 121, "name": "Doctor Who", "original_name": "Doctor Who", "first_air_date": "1963-11-23",
         "vote_count": 900},
        {"id": 59317, "name": "Who Killed Dr Bogle and Mrs Chandler?", "original_name": "x",
         "first_air_date": "2006-01-01", "vote_count": 1},
        {"id": 59659, "name": "Halt and Catch Fire", "original_name": "Halt and Catch Fire",
         "first_air_date": "2014-06-01", "vote_count": 900},
        {"id": 1813, "name": "Father Ted", "original_name": "Father Ted", "first_air_date": "1995-04-21",
         "vote_count": 400, "seasons": [{"season_number": 0}, {"season_number": 1}, {"season_number": 2}]},
    ]
    EPISODES = {(57243, 5): {3: "Victory of the Daleks"}, (59659, 1): {1: "I/O"},
                (1813, 0): {1: "A Christmassy Ted"}, (1813, 1): {1: "Good Luck, Father Ted"},
                (1813, 2): {1: "Hell", 5: "A Song for Europe", 7: "Think Fast, Father Ted"}}
    GERMAN = {194: "Die fabelhafte Welt der Amélie"}

    def __init__(self):
        self.asked = []

    def get(self, path, **params):
        self.asked.append((path, params))
        parts = path.split("/")
        if parts[0] == "search":
            pool = self.MOVIES if parts[1] == "movie" else self.SHOWS
            q = cleanup.words(params["query"])
            year = params.get("primary_release_year") or params.get("first_air_date_year") or params.get("year")
            hits = [x for x in pool if set(q.split()) & set(cleanup.words(x.get("title") or x.get("name")).split())
                    or cleanup.key(params["query"]) == cleanup.key(x.get("title") or x.get("name"))]
            if year:
                hits = [x for x in hits if (x.get("release_date") or x.get("first_air_date")).startswith(str(year))]
            return {"results": hits}
        if parts[0] == "movie":
            x = next(m for m in self.MOVIES if m["id"] == int(parts[1]))
            title = self.GERMAN.get(x["id"]) if params.get("language") == "de-DE" else None
            return {**x, "title": title or x["title"]}
        if parts[0] == "tv" and len(parts) == 2:
            return next(s for s in self.SHOWS if s["id"] == int(parts[1]))
        if parts[0] == "tv" and parts[2] == "season":
            eps = self.EPISODES.get((int(parts[1]), int(parts[3])), {})
            return {"episodes": [{"episode_number": n, "name": t} for n, t in eps.items()]}
        return {}


OLD = 1_700_000_000                                  # 2023: long enough ago that nothing looks mid-copy


def touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (OLD, OLD))
    return path


def snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def plan(root, kind="auto", language="en-US"):
    return cleanup.plan_library(root, kind, cleanup.Lookup(FakeTMDB(), language))


def by_video(entries):
    return {e["video"].name: e for e in entries}


def test_films_get_their_own_folder_and_their_files_go_with_them(tmp_path):
    root = tmp_path / "Movies"
    release = root / "Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r"
    video = touch(release / "Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r.mkv")
    touch(release / f"{video.stem}.en.srt")
    touch(release / f"{video.stem}.notes.ass")
    touch(release / "context-notes" / video.name / "notes-x.json")
    touch(release / "readme.txt")
    touch(root / "Akira.1988.1080p.mkv")
    before = snapshot(root)
    p = plan(root)
    moves = by_video(p.moves)
    brian = moves[video.name]
    assert brian["target"] == root / "Life of Brian (1979) {tmdb-583}" / "Life of Brian (1979) {tmdb-583}.mkv"
    assert sorted(r for _, r in brian["sidecars"]) == [".en.srt", ".notes.ass"]
    assert brian["work"] == release / "context-notes" / video.name
    assert moves["Akira.1988.1080p.mkv"]["target"].parent.name == "Akira (1988) {tmdb-149}"   # not the Japanese one
    assert [c.name for c in p.clutter] == ["readme.txt"]
    assert snapshot(root) == before                                                          # nothing changed


def test_a_far_better_known_film_wins_a_tie_and_a_sequel_isnt_a_part(tmp_path):
    root = tmp_path / "Movies"
    touch(root / "Predator[1987]DvDrip[Eng]-FXG" / "Predator[1987]DvDrip[Eng]-FXG.avi")
    touch(root / "The Godfather Part 2 1974 BDRip x264 - 4PlayHD.mp4")
    moves = by_video(plan(root).moves)
    assert moves["Predator[1987]DvDrip[Eng]-FXG.avi"]["target"].name == "Predator (1987) {tmdb-106}.avi"
    assert moves["The Godfather Part 2 1974 BDRip x264 - 4PlayHD.mp4"]["target"].name == \
        "The Godfather Part II (1974) {tmdb-240}.mp4"


def test_two_copies_of_one_film_and_unknown_ones_are_left_to_decide(tmp_path):
    root = tmp_path / "Movies"
    touch(root / "Akira (1988).avi")
    touch(root / "Akira 1988.m4v")
    touch(root / "Total Recall KLAXXON.avi")
    touch(root / "Mythbusters S04 E01.mkv")
    touch(root / "NAPOLEON DISC 1" / "BDMV" / "STREAM" / "00000.m2ts")
    p = plan(root)
    hand = {e["video"].name: e["reason"] for e in p.by_hand}
    assert not p.moves
    assert "same name as Akira 1988.m4v" in hand["Akira (1988).avi"]
    assert "TMDB has more than one: Total Recall (1990" in hand["Total Recall KLAXXON.avi"]   # no year to tell
    assert "TV episode, in a films folder" in hand["Mythbusters S04 E01.mkv"]
    assert "disc copied as it is" in hand["NAPOLEON DISC 1"]                          # one entry, not one per file


def test_titles_come_in_the_language_asked_for(tmp_path):
    root = tmp_path / "Movies"
    touch(root / "Amelie.2001.1080p.mkv")
    (e,) = plan(root, language="de-DE").moves
    assert e["target"].name == "Die fabelhafte Welt der Amélie (2001) {tmdb-194}.mkv"


def test_a_show_is_found_from_its_episodes_names_and_gets_episode_titles(tmp_path):
    root = tmp_path / "TV Shows"
    touch(root / "Dr Who" / "Season 05" / "Doctor Who (2010) - s05e03.mkv")
    touch(root / "Dr Who" / "Season 05" / "Doctor Who (2010) - s05e03.en.srt")
    touch(root / "Dr Who" / "Season 01" / "Doctor Who (2005) - s01e01.mkv")
    touch(root / "Halt Catch Fire" / "Season 1" / "halt.and.catch.fire.s01e01.1080p.bluray.x264-shortbrehd.mkv")
    p = plan(root)
    moves = by_video(p.moves)
    e = moves["Doctor Who (2010) - s05e03.mkv"]
    assert e["target"] == (root / "Doctor Who (2005) {tmdb-57243}" / "Season 05"
                           / "Doctor Who (2005) - s05e03 - Victory of the Daleks.mkv")
    assert [r for _, r in e["sidecars"]] == [".en.srt"]
    hand = {e["video"].name: e["reason"] for e in p.by_hand}
    assert "TMDB has no s01e01 for Doctor Who: your own numbering?" in hand["Doctor Who (2005) - s01e01.mkv"]
    assert moves["halt.and.catch.fire.s01e01.1080p.bluray.x264-shortbrehd.mkv"]["target"].parent.parent.name == \
        "Halt and Catch Fire (2014) {tmdb-59659}"


def test_episode_titles_match_loosely_but_not_too_loosely():
    same = cleanup.same_episode_title
    assert same("Pete", "Pete (1)") and same("Me", "Me²") and same("ep2 6 succ3ss0r p12", "eps2.6_succ3ss0r.p12")
    assert same("Buried in Concrete - Daddy Longlegs - Jet Taxi", "Buried in Concrete")
    assert not same("Series Finale", "whoami") and not same("Hell", "Help") and not same("Hel", "Help")


def test_loose_matches_are_strict_enough():
    assert cleanup.near("Halt and Catch Fire", "Halt Catch Fire")
    assert not cleanup.near("Who Killed Dr Bogle and Mrs Chandler?", "Dr Who")
    assert cleanup.key("Beavis and Butt-Head") == cleanup.key("Beavis & Butthead")
    assert cleanup.key("The IT Crowd") == cleanup.key("IT Crowd")
    assert cleanup.words("空前のアニメ巨編 AKIRA") != cleanup.words("Akira")


def test_names_every_system_takes():
    assert cleanup.safe("Mission: Impossible") == "Mission - Impossible"
    assert cleanup.safe('What? "Now" <a|b> 1/2...') == "What Now ab 1-2"


def test_without_tmdb_names_come_from_the_file_names(tmp_path):
    root = tmp_path / "Movies"
    touch(root / "Casablanca.1942.avi")
    (e,) = cleanup.plan_library(root, "auto", None).moves
    assert e["target"] == root / "Casablanca (1942)" / "Casablanca (1942).avi"


def test_the_listing_says_nothing_changed(tmp_path, home, monkeypatch, capsys):
    root = tmp_path / "Movies"
    touch(root / "Casablanca.1942.avi")
    before = snapshot(root)
    assert cleanup.main([str(root), "--offline", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Nothing has been changed" in out and "Casablanca (1942)/Casablanca (1942).avi" in out.replace(os.sep, "/")
    assert snapshot(root) == before


# ---------------------------------------------------------------- doing it, and putting it back
def everything(root):
    """Every file and folder under root with its contents, for 'exactly as it was'."""
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in root.rglob("*")}


@pytest.fixture
def fake_tmdb(monkeypatch):
    monkeypatch.setattr(cleanup.tmdb, "load", lambda *a, **k: "key")
    monkeypatch.setattr(cleanup.tmdb, "TMDB", lambda key: FakeTMDB())


def a_movie_library(tmp_path):
    root = tmp_path / "Movies"
    release = root / "Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r"
    stem = release.name
    touch(release / f"{stem}.mkv")
    touch(release / f"{stem}.en.srt")
    touch(release / f"{stem}.notes.ass")
    touch(release / "Eng. Subs" / "English.srt")
    touch(release / "readme.txt")
    work = release / "context-notes" / f"{stem}.mkv"
    notes = touch(work / f"notes-{stem}.json",
                  json.dumps({"subtitles": f"{stem}.en.srt", "notes": [{"match": "x"}]}, indent=1).encode())
    touch(work / f"{stem} chat-replies" / "part-1.txt")
    touch(work / "analysis" / "report.txt")
    for name, text in cleanup.workfiles.IGNORE_FILES.items():
        touch(release / "context-notes" / name, text.encode())
    touch(root / "Akira.1988.1080p.mkv")
    touch(root / "Total Recall KLAXXON.avi")
    return root, notes


def test_renaming_moves_everything_with_the_film_and_undo_puts_it_all_back(tmp_path, home, fake_tmdb, capsys):
    root, _ = a_movie_library(tmp_path)
    before = everything(root)
    assert cleanup.main([str(root), "--yes"]) == 0
    out = capsys.readouterr().out
    brian = root / "Life of Brian (1979) {tmdb-583}"
    new = "Life of Brian (1979) {tmdb-583}"
    assert sorted(x.name for x in brian.iterdir()) == sorted(["Eng. Subs", "context-notes", f"{new}.en.srt",
                                                               f"{new}.mkv", f"{new}.notes.ass"])   # renamed whole
    work = brian / "context-notes" / f"{new}.mkv"
    notes = work / f"notes-{new}.json"
    assert json.loads(notes.read_text(encoding="utf-8"))["subtitles"] == f"{new}.en.srt"
    assert notes.stat().st_mtime == OLD                                           # so nothing needs a rebuild
    assert (work / f"{new} chat-replies" / "part-1.txt").is_file() and (work / "analysis" / "report.txt").is_file()
    assert (brian / "context-notes" / "removed" / "readme.txt").is_file()
    akira = root / "Akira (1988) {tmdb-149}"
    assert (akira / "Akira (1988) {tmdb-149}.mkv").is_file()
    assert (root / "Total Recall KLAXXON.avi").is_file()                           # by hand: untouched
    assert not (root / "Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r").exists()
    assert cleanup.workfiles.notes_path(brian / f"{new}.mkv") == notes            # the scripts find its notes
    (log,) = (home / ".config" / "context-notes" / "cleanup").glob("*.jsonl")
    assert "Undo log" in out and str(log) in out
    again = cleanup.plan_library(root, "auto", cleanup.Lookup(FakeTMDB(), "en-US"))
    assert not again.moves and len(again.tidy) == 2 and not again.clutter         # a second run has nothing to do
    assert cleanup.main(["--undo", str(log)]) == 0
    assert everything(root) == before
    assert (root / "Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r" / "context-notes" / "Monty.Pythons.Life.of."
            "Brian.1979.720p.BRRip.x264-x0r.mkv" / "notes-Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r.json"
            ).stat().st_mtime == OLD


def test_only_and_no_change_without_a_yes(tmp_path, home, fake_tmdb, monkeypatch):
    root, _ = a_movie_library(tmp_path)
    before = everything(root)
    monkeypatch.setattr(cleanup.prompts, "confirm", lambda text, id=None: False)
    assert cleanup.main([str(root)]) == 0 and everything(root) == before           # asked, said no
    monkeypatch.setattr(cleanup.prompts, "confirm", lambda text, id=None: id == "cleanup.go")
    assert cleanup.main([str(root), "--only", "akira"]) == 0
    assert (root / "Akira (1988) {tmdb-149}").is_dir()
    assert (root / "Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r" / "readme.txt").is_file()   # not chosen


def test_a_show_folder_is_renamed_and_seasons_numbered_in_two_digits(tmp_path, home, fake_tmdb):
    root = tmp_path / "TV Shows"
    touch(root / "Dr Who" / "Season 5" / "Doctor Who (2010) - s05e03.mkv")
    touch(root / "Dr Who" / "Season 5" / "Doctor Who (2010) - s05e03.en.srt")
    touch(root / "Dr Who" / "Season 5" / ".DS_Store")
    touch(root / "Dr Who" / "Season 1" / "Doctor Who (2005) - s01e01.mkv")     # the show began in the earliest year
    assert cleanup.main([str(root), "--yes"]) == 0
    show = root / "Doctor Who (2005) {tmdb-57243}"
    assert sorted(p.name for p in (show / "Season 05").iterdir()) == [
        "Doctor Who (2005) - s05e03 - Victory of the Daleks.en.srt", "Doctor Who (2005) - s05e03 - Victory of the Daleks.mkv"]
    assert sorted(p.name for p in show.iterdir()) == ["Season 05", "Season 1"]    # "Season 5" emptied and gone;
    #                         s01e01 isn't on TMDB's list here, so it waits for a decision, in the renamed show folder


def test_your_own_title_is_kept(tmp_path, home, fake_tmdb):
    root = tmp_path / "Movies"
    touch(root / "Amelie.2001.1080p.mkv")
    assert cleanup.main([str(root), "--set-title", "194", "Amélie", "--dry-run"]) == 0
    (e,) = cleanup.plan_library(root, "auto", cleanup.Lookup(FakeTMDB(), "de-DE")).moves
    assert e["target"].name == "Amélie (2001) {tmdb-194}.mkv"
    cleanup.set_title("movie", "194", "")
    (e,) = cleanup.plan_library(root, "auto", cleanup.Lookup(FakeTMDB(), "de-DE")).moves
    assert e["target"].name.startswith("Die fabelhafte Welt")


def test_a_video_still_being_copied_is_left_for_later(tmp_path):
    root = tmp_path / "Movies"
    video = touch(root / "Akira.1988.1080p.mkv")
    os.utime(video, (time.time(), time.time()))
    p = plan(root)
    assert not p.moves and "still being copied" in p.by_hand[0]["reason"]


def test_a_taken_name_stops_the_run(tmp_path, home):
    a, b = touch(tmp_path / "a.mkv"), touch(tmp_path / "b.mkv")
    log = cleanup.Log(tmp_path / "log.jsonl")
    with pytest.raises(cleanup.Stop, match="there already"):
        cleanup.move(a, b, log)
    log.close()
    assert a.is_file() and b.is_file() and log.count == 0


# ---------------------------------------------------------------- putting names right after a hand tidy
def matroska(path, payload=1000, cut=0):
    """A tiny Matroska file: the EBML header, then a Segment that says it holds `payload` bytes (`cut` fewer are
    there, as in a download that stopped)."""
    data = (b"\x1a\x45\xdf\xa3\x84\x42\x86\x81\x01" + b"\x18\x53\x80\x67\x01" + payload.to_bytes(7, "big")
            + b"\0" * (payload - cut))
    return touch(path, data)


def test_a_film_named_only_by_its_folder_and_a_finished_download(tmp_path, home, fake_tmdb):
    root = tmp_path / "Movies"
    touch(root / "Total Recall (1990)" / "Total Recall KLAXXON.avi")
    matroska(root / "Old.Boy.2003.KOREAN.2160p-GalaxyRG[TGx]" / "Old.Boy.2003.KOREAN.2160p-GalaxyRG.mkv.part")
    matroska(root / "Akira.1988.1080p.mkv.part", cut=10)
    p = plan(root)
    moves = by_video(p.moves)
    assert moves["Total Recall KLAXXON.avi"]["target"].name == "Total Recall (1990) {tmdb-861}.avi"
    assert moves["Old.Boy.2003.KOREAN.2160p-GalaxyRG.mkv.part"]["target"].name == "Oldboy (2003) {tmdb-670}.mkv"
    assert "unfinished download" in by_video(p.by_hand)["Akira.1988.1080p.mkv.part"]["reason"]
    assert cleanup.main([str(root), "--yes"]) == 0
    assert (root / "Oldboy (2003) {tmdb-670}" / "Oldboy (2003) {tmdb-670}.mkv").is_file()
    assert (root / "Akira.1988.1080p.mkv.part").is_file()                         # a stopped download stays


def test_names_left_from_before_are_put_right_and_undo_puts_them_back(tmp_path, home, fake_tmdb):
    root = tmp_path / "Movies"
    film = root / "Monty Python and the Holy Grail (1975) {tmdb-762}"
    new = film.name
    touch(film / f"{new}.mp4")
    touch(film / f"{new}.en.srt")
    old, older = "Holy.Grail.1975.anoXmous_", "Holy.Grail.1975.anoXmous"
    touch(film / f"{old}.behind-the-scenes.notes.ass")
    touch(film / "Grail[Eng][Subs].srt", b"1\n00:00:01,000 --> 00:00:02,000\nWe are the knights who say Ni, and "
          b"we want a shrubbery that looks nice and is not too expensive.\n")
    touch(film / "Other" / "Torrent downloaded from Demonoid.com.txt")
    work = film / "context-notes" / f"{old}.mp4"
    touch(work / f"behind-the-scenes-{old}.json", json.dumps({"subtitles": f"{older}.en.srt", "notes": []}).encode())
    touch(work / f"facts-{old}.json", json.dumps({"video": f"{old}.mp4", "facts": []}).encode())
    touch(work / f"{older}.en.transcript.txt")
    before = everything(root)
    p = plan(root)
    assert sorted((f["kind"], f["src"].name, f["dst"].name) for f in p.fixes) == [
        ("rename", "Grail[Eng][Subs].srt", f"{new}.srt"),        # too little text to tell its language
        ("rename", f"{old}.behind-the-scenes.notes.ass", f"{new}.behind-the-scenes.notes.ass"),
        ("work", f"{old}.mp4", f"{new}.mp4")]
    assert cleanup.main([str(root), "--yes"]) == 0
    video = film / f"{new}.mp4"
    assert cleanup.workfiles.bts_ass_path(video).is_file()
    assert cleanup.workfiles.bts_notes_path(video).is_file()                       # the scripts find its notes
    newwork = cleanup.workfiles.folder(video)
    assert sorted(x.name for x in newwork.iterdir()) == sorted([f"behind-the-scenes-{new}.json", f"facts-{new}.json",
                                                                 f"{new}.en.transcript.txt"])
    assert json.loads(cleanup.workfiles.bts_notes_path(video).read_text(encoding="utf-8"))["subtitles"] == f"{new}.en.srt"
    assert json.loads((newwork / f"facts-{new}.json").read_text(encoding="utf-8"))["video"] == f"{new}.mp4"
    assert (film / "context-notes" / "removed" / "Other" / "Torrent downloaded from Demonoid.com.txt").is_file()
    assert not (film / "Other").exists()
    (log,) = (home / ".config" / "context-notes" / "cleanup").glob("*.jsonl")
    assert cleanup.main(["--undo", str(log)]) == 0
    assert everything(root) == before


def test_a_stray_subtitle_gets_its_language_from_its_text(tmp_path, home, fake_tmdb):
    root = tmp_path / "Movies"
    film = root / "Akira (1988) {tmdb-149}"
    touch(film / f"{film.name}.mkv")
    lines = ["The city is going to be destroyed and we have to get out of here.", "Where is the boy? Find him now.",
             "I told you that they would come back for us before the night was over.", "What are you doing here?",
             "We have no time left, so you had better run as fast as you can.", "Kaneda! Help me, please!"]
    touch(film / "Akira[Eng][Subs].srt", "".join(f"{k}\n00:00:{k:02d},000 --> 00:00:{k:02d},900\n{x}\n\n"
                                                for k, x in enumerate(lines * 5, 1)).encode())
    touch(film / "akira.ger.srt")
    (a, b) = sorted(plan(root).fixes, key=lambda f: f["src"].name)
    assert (a["src"].name, a["dst"].name) == ("Akira[Eng][Subs].srt", f"{film.name}.en.srt")
    assert (b["src"].name, b["dst"].name) == ("akira.ger.srt", f"{film.name}.ger.srt")


def test_episodes_numbered_through_the_series_get_tmdbs_numbers_by_their_titles(tmp_path):
    root = tmp_path / "TV Shows"
    for name in ("Season 1/1. Good Luck, Father Ted.mp4", "Season 2/11. A Song for Europe.mp4", "Season 2/7. Hell.mp4",
                 "Season 2/9. Some Episode TMDB Lacks.mp4", "Season 2/8. Night of the Nearly Dead.mp4",
                 "Season 3/17. A Christmassy Ted.mp4"):
        touch(root / "Father Ted" / name)
    p = plan(root)
    moves, hand = by_video(p.moves), {e["video"].name: e["reason"] for e in p.by_hand}
    show = "Father Ted (1995) {tmdb-1813}"
    assert moves["1. Good Luck, Father Ted.mp4"]["target"].name == "Father Ted (1995) - s01e01 - Good Luck, Father Ted.mp4"
    song = moves["11. A Song for Europe.mp4"]
    assert song["target"] == root / show / "Season 02" / "Father Ted (1995) - s02e05 - A Song for Europe.mp4"
    assert "the name said s02e11" in song["note"]
    assert moves["7. Hell.mp4"]["target"].name == "Father Ted (1995) - s02e01 - Hell.mp4"   # s02e07 is another one
    assert "TMDB has no s02e09 (or “Some Episode TMDB Lacks”)" in hand["9. Some Episode TMDB Lacks.mp4"]
    assert "TMDB has no s02e08" in hand["8. Night of the Nearly Dead.mp4"]
    assert "TMDB has no s03e17" in hand["17. A Christmassy Ted.mp4"]            # a special: yours to place


def test_skip_leaves_a_whole_show_alone(tmp_path, home, fake_tmdb):
    root = tmp_path / "TV Shows"
    touch(root / "Dr Who" / "Season 5" / "Doctor Who (2010) - s05e03.mkv")
    touch(root / "Dr Who" / "Season 1" / "Doctor Who (2005) - s01e01.mkv")
    touch(root / "Halt Catch Fire" / "Season 1" / "halt.and.catch.fire.s01e01.1080p.bluray.x264-shortbrehd.mkv")
    before = {k: v for k, v in everything(root).items() if k.startswith("Dr Who")}
    assert cleanup.main([str(root), "--yes", "--skip", "Dr Who"]) == 0
    assert {k: v for k, v in everything(root).items() if k.startswith("Dr Who")} == before
    assert (root / "Halt and Catch Fire (2014) {tmdb-59659}" / "Season 01").is_dir()


@pytest.mark.skipif(not hasattr(os, "chflags") or not hasattr(__import__("stat"), "UF_IMMUTABLE"),
                    reason="file flags (Finder's Locked box) are a macOS/BSD idea")
def test_a_locked_file_is_left_for_a_decision(tmp_path):
    import stat
    root = tmp_path / "Movies"
    video = touch(root / "Akira.1988.1080p.mkv")
    os.chflags(video, stat.UF_IMMUTABLE)
    try:
        p = plan(root)
        assert not p.moves and "locked" in p.by_hand[0]["reason"]
    finally:
        os.chflags(video, 0)
