"""film_ids.py: finding a film's IMDb and TMDB ids and writing them into its notes and its .ass headers."""
import codecs
import hashlib
import json
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import ROOT

import embed
import film_ids
import find_subs
import make_ass

EXAMPLE = ROOT / "examples" / "help-desk"
BRIAN = {"feature_type": "Movie", "year": 1979, "title": "Life of Brian", "imdb_id": 79470, "tmdb_id": 583}
CAT = {"feature_type": "Episode", "year": 2008, "title": "Cat's in the Bag...", "imdb_id": 1054724, "tmdb_id": 62086,
       "season_number": 1, "episode_number": 2, "parent_imdb_id": 903747, "parent_title": "Breaking Bad",
       "parent_tmdb_id": 1396}


class FakeOpenSubtitles:
    """Answers /subtitles searches: `by_hash` for a moviehash search (made for this exact file), `by_query` for any
    other. Each is a list of feature_details."""
    def __init__(self, by_hash=(), by_query=()):
        self.calls = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                fake.calls.append(q)
                found = [(f, True) for f in by_hash] if "moviehash" in q else [(f, False) for f in by_query]
                body = json.dumps({"data": [{"attributes": {"moviehash_match": m, "feature_details": f}}
                                            for f, m in found]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/v1"


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setattr(film_ids, "PAUSE", 0)
    monkeypatch.setattr(find_subs, "os_load", lambda: {"api_key": "K", "username": "u", "password": "p"})


def film(folder, name, plex_copy=True, ids=None):
    """A video (big enough for a fingerprint) with notes built from the example scene: the notes file in its
    context-notes folder, its .notes.ass beside it and, by default, the Plex copy."""
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / name
    video.write_bytes(os.urandom(65536 * 3))
    work = folder / "context-notes" / name
    work.mkdir(parents=True)
    spec = json.loads((EXAMPLE / "notes-the-help-desk.json").read_text(encoding="utf-8"))
    if ids:
        spec["ids"] = ids
    notes = work / f"notes-{video.stem}.json"
    notes.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    ass = embed.ass_path(video)
    make_ass.build(EXAMPLE / "the-help-desk.srt", notes, ass, say=lambda *a: None)
    if plex_copy:
        shutil.copyfile(ass, video.with_name(f"{video.stem}.en.ass"))
    return video, notes, ass


# ---------------------------------------------------------------- reading ids
def test_imdb_ids_are_written_the_one_way():
    assert [film_ids.imdb_id(x) for x in (79470, "79470", "tt79470", "tt0079470", "TT0079470")] == ["tt0079470"] * 5
    assert film_ids.imdb_id(None) is None and film_ids.imdb_id(0) is None and film_ids.imdb_id("x") is None
    assert film_ids.imdb_id(10872600) == "tt10872600"


def test_ids_in_media_server_names():
    assert film_ids.ids_in_name("Life of Brian (1979) {imdb-tt0079470}") == {"imdb": "tt0079470"}
    assert film_ids.ids_in_name("Life of Brian (1979) [tmdbid-583] [imdbid-tt0079470]") == {"imdb": "tt0079470",
                                                                                           "tmdb": 583}
    assert film_ids.ids_in_name("Life of Brian (1979) 1080p") == {}


def test_ids_in_kodi_and_release_nfo_files(tmp_path):
    kodi = tmp_path / "movie.nfo"
    kodi.write_text('<movie><uniqueid type="imdb" default="true">tt0079470</uniqueid>'
                    '<uniqueid type="tmdb">583</uniqueid></movie>', encoding="utf-8")
    release = tmp_path / "x0r.nfo"
    release.write_bytes(b"\xdb\xdb Monty Python \xb0 https://www.imdb.com/title/tt0079470/ \xdb")   # cp437 art
    assert film_ids.ids_in_nfo(kodi) == {"imdb": "tt0079470", "tmdb": 583}
    assert film_ids.ids_in_nfo(release) == {"imdb": "tt0079470"}


def test_a_release_nfo_counts_only_when_the_folder_has_one_video(tmp_path):
    video = tmp_path / "Brian.1979.mkv"
    video.write_bytes(b"x")
    (tmp_path / "x0r.nfo").write_text("imdb.com/title/tt0079470", encoding="utf-8")
    assert film_ids.nfo_for(video) == tmp_path / "x0r.nfo"
    (tmp_path / "Other.1980.mkv").write_bytes(b"x")
    assert film_ids.nfo_for(video) is None


# ---------------------------------------------------------------- the header line
def test_the_film_line_for_a_movie_and_an_episode():
    assert make_ass.film_line({"ids": {"type": "movie", "imdb": "tt0079470", "tmdb": 583}}) == \
        "; Film: imdb tt0079470, tmdb movie/583\n"
    episode = film_ids.from_feature(CAT)
    assert make_ass.film_line({"ids": episode}) == \
        "; Film: imdb tt1054724, tmdb tv/1396/season/1/episode/2, series imdb tt0903747\n"
    assert make_ass.film_line({}) == "" and make_ass.film_line([]) == "" and make_ass.film_line({"ids": {}}) == ""


def test_a_build_without_ids_is_unchanged_and_with_them_gains_only_the_line(tmp_path):
    spec = json.loads((EXAMPLE / "notes-the-help-desk.json").read_text(encoding="utf-8"))
    plain, with_ids = tmp_path / "plain.json", tmp_path / "ids.json"
    plain.write_text(json.dumps(spec), encoding="utf-8")
    with_ids.write_text(json.dumps({**spec, "ids": {"type": "movie", "imdb": "tt0079470", "tmdb": 583}}),
                        encoding="utf-8")
    a, b = tmp_path / "a.notes.ass", tmp_path / "b.notes.ass"
    make_ass.build(EXAMPLE / "the-help-desk.srt", plain, a, say=lambda *x: None)
    make_ass.build(EXAMPLE / "the-help-desk.srt", with_ids, b, say=lambda *x: None)
    assert "; Film:" not in a.read_text(encoding="utf-8-sig")
    lines_a, lines_b = a.read_text(encoding="utf-8-sig").splitlines(), b.read_text(encoding="utf-8-sig").splitlines()
    assert [x for x in lines_b if x not in lines_a] == ["; Film: imdb tt0079470, tmdb movie/583"]
    assert len(lines_b) == len(lines_a) + 1
    assert lines_b[lines_b.index("; Film: imdb tt0079470, tmdb movie/583") + 1].startswith("Title:")


def test_the_embed_check_ignores_the_film_line_and_is_unchanged_without_it(tmp_path):
    ass = tmp_path / "x.notes.ass"
    shutil.copyfile(EXAMPLE / "the-help-desk.notes.ass", ass)
    before = embed.sha1(ass)
    assert before == hashlib.sha1(ass.read_bytes()).hexdigest()          # no line: the hash it always was
    ass.write_bytes(film_ids.set_film_line(ass.read_bytes(), "; Film: imdb tt0079470, tmdb movie/583\n"))
    assert b"; Film: imdb tt0079470" in ass.read_bytes() and embed.sha1(ass) == before
    ass.write_bytes(ass.read_bytes().replace(b"Dialogue:", b"Dialogue:  ", 1))
    assert embed.sha1(ass) != before                                      # a real change still counts


def test_setting_the_line_keeps_the_bom_and_windows_line_endings_and_replaces_an_old_one():
    data = codecs.BOM_UTF8 + b"[Script Info]\r\n; Look: build 2\r\nTitle: X\r\n\r\n[V4+ Styles]\r\nStyle: a\r\n"
    once = film_ids.set_film_line(data, "; Film: imdb tt0000001\n")
    assert once == codecs.BOM_UTF8 + (b"[Script Info]\r\n; Look: build 2\r\n; Film: imdb tt0000001\r\nTitle: X\r\n"
                                      b"\r\n[V4+ Styles]\r\nStyle: a\r\n")
    twice = film_ids.set_film_line(once, "; Film: imdb tt0000002\n")
    assert twice == once.replace(b"tt0000001", b"tt0000002")
    assert film_ids.set_film_line(twice, "") == data


# ---------------------------------------------------------------- whole runs
def test_a_film_found_by_its_fingerprint_gets_its_ids_everywhere(tmp_path, capsys):
    api = FakeOpenSubtitles(by_hash=[BRIAN])
    video, notes, ass = film(tmp_path / "Movies", "Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r.mkv")
    hash_before = embed.sha1(ass)
    assert film_ids.main([str(tmp_path / "Movies"), "--yes", "--api-url", api.url]) == 0
    ids = json.loads(notes.read_text(encoding="utf-8"))["ids"]
    assert {k: ids[k] for k in ("type", "imdb", "tmdb", "title", "year")} == \
        {"type": "movie", "imdb": "tt0079470", "tmdb": 583, "title": "Life of Brian", "year": 1979}
    assert ids["source"] == "OpenSubtitles: subtitles made for this exact file" and ids["found"]
    plex = video.with_name(f"{video.stem}.en.ass")
    for p in (ass, plex):
        assert "; Film: imdb tt0079470, tmdb movie/583\n" in p.read_text(encoding="utf-8-sig")
    assert ass.read_bytes() == plex.read_bytes()
    assert embed.sha1(ass) == hash_before                 # a film with these notes inside it stays current
    assert ass.stat().st_mtime >= notes.stat().st_mtime   # so no rebuild is due
    kept = sorted(p.name for p in (tmp_path / "Movies" / "context-notes" / video.name).glob("*.bak"))
    assert kept == sorted([f"{notes.name}.bak", f"{ass.name}.bak", f"{plex.name}.bak"])
    assert "moviehash" in api.calls[0] and "languages" not in api.calls[0]

    # A second run finds them in the notes and changes nothing.
    stamp = ass.stat().st_mtime_ns
    assert film_ids.main([str(tmp_path / "Movies"), "--yes", "--api-url", api.url]) == 0
    assert "0 film(s) to write, 1 already had ids" in capsys.readouterr().out
    assert ass.stat().st_mtime_ns == stamp and len(api.calls) == 1


def test_a_rebuild_keeps_the_line(tmp_path):
    api = FakeOpenSubtitles(by_hash=[BRIAN])
    video, notes, ass = film(tmp_path, "Life.of.Brian.1979.mkv", plex_copy=False)
    film_ids.main([str(video), "--yes", "--api-url", api.url])
    make_ass.build(EXAMPLE / "the-help-desk.srt", notes, ass, say=lambda *a: None)
    assert "; Film: imdb tt0079470, tmdb movie/583\n" in ass.read_text(encoding="utf-8-sig")


def test_dry_run_changes_nothing(tmp_path, capsys):
    api = FakeOpenSubtitles(by_hash=[BRIAN])
    video, notes, ass = film(tmp_path, "Life.of.Brian.1979.mkv")
    before = {p: p.read_bytes() for p in (notes, ass)}
    assert film_ids.main([str(tmp_path), "--dry-run", "--api-url", api.url]) == 0
    out = capsys.readouterr().out
    assert "Life of Brian (1979): imdb tt0079470, tmdb movie/583" in out and "Nothing was changed" in out
    assert all(p.read_bytes() == b for p, b in before.items())
    assert not list((tmp_path / "context-notes").rglob("*.bak"))


def test_an_nfo_is_enough_offline(tmp_path):
    video, notes, ass = film(tmp_path / "Brian", "Life.of.Brian.1979.mkv", plex_copy=False)
    (tmp_path / "Brian" / "x0r.nfo").write_text("https://www.imdb.com/title/tt0079470/", encoding="utf-8")
    assert film_ids.main([str(tmp_path), "--yes", "--offline"]) == 0
    ids = json.loads(notes.read_text(encoding="utf-8"))["ids"]
    assert ids["imdb"] == "tt0079470" and ids["source"] == "x0r.nfo" and "tmdb" not in ids
    assert "; Film: imdb tt0079470\n" in ass.read_text(encoding="utf-8-sig")


def test_an_nfo_imdb_id_gets_tmdbs_from_opensubtitles(tmp_path):
    api = FakeOpenSubtitles(by_query=[BRIAN])
    video, notes, ass = film(tmp_path / "Brian", "Life.of.Brian.1979.mkv", plex_copy=False)
    (tmp_path / "Brian" / "x0r.nfo").write_text("https://www.imdb.com/title/tt0079470/", encoding="utf-8")
    assert film_ids.main([str(tmp_path), "--yes", "--api-url", api.url]) == 0
    ids = json.loads(notes.read_text(encoding="utf-8"))["ids"]
    assert (ids["imdb"], ids["tmdb"]) == ("tt0079470", 583) and api.calls[0]["imdb_id"] == "79470"
    assert ids["source"] == "x0r.nfo, OpenSubtitles, by its IMDb id"


def test_an_episode_found_by_show_season_and_episode(tmp_path):
    api = FakeOpenSubtitles(by_query=[CAT, {**CAT, "parent_title": "Breaking Badly", "imdb_id": 1, "tmdb_id": 2}])
    video, notes, ass = film(tmp_path / "Breaking Bad" / "Season 1", "Breaking Bad (2008) - s01e02.mkv",
                             plex_copy=False)
    assert film_ids.main([str(tmp_path), "--yes", "--api-url", api.url]) == 0
    ids = json.loads(notes.read_text(encoding="utf-8"))["ids"]
    assert ids["series"] == {"imdb": "tt0903747", "tmdb": 1396, "title": "Breaking Bad"}
    assert (ids["type"], ids["imdb"], ids["season"], ids["episode"]) == ("episode", "tt1054724", 1, 2)
    assert api.calls[-1]["query"] == "breaking bad" and api.calls[-1]["season_number"] == "1"
    assert "tmdb tv/1396/season/1/episode/2" in ass.read_text(encoding="utf-8-sig")


def test_one_show_with_that_episode_is_enough_without_a_year(tmp_path):
    api = FakeOpenSubtitles(by_query=[CAT])
    video, notes, ass = film(tmp_path / "Breaking Bad" / "Season 1", "breaking.bad.s01e02.1080p.bluray.x264-ingot.mkv",
                             plex_copy=False)
    assert film_ids.main([str(tmp_path), "--yes", "--api-url", api.url]) == 0
    assert json.loads(notes.read_text(encoding="utf-8"))["ids"]["imdb"] == "tt1054724"


TZ_1959 = {"feature_type": "Episode", "year": 1962, "title": "The Little People", "imdb_id": 734655,
           "season_number": 3, "episode_number": 28, "parent_title": "The Twilight Zone", "parent_imdb_id": 52520}
TZ_1985 = {**TZ_1959, "year": 1987, "title": "The Card", "imdb_id": 11, "parent_imdb_id": 88591}


def test_a_remake_is_told_apart_by_the_episode_title_in_the_name(tmp_path):
    api = FakeOpenSubtitles(by_query=[TZ_1985, TZ_1959])
    video, notes, ass = film(tmp_path / "The Twilight Zone" / "Season 3", "S03E28 The Little People.mp4",
                             plex_copy=False)
    assert film_ids.main([str(tmp_path), "--yes", "--api-url", api.url]) == 0
    ids = json.loads(notes.read_text(encoding="utf-8"))["ids"]
    assert (ids["imdb"], ids["series"]["imdb"]) == ("tt0734655", "tt0052520")


def test_two_shows_it_cant_tell_apart_are_left_alone(tmp_path, capsys):
    api = FakeOpenSubtitles(by_query=[TZ_1985, TZ_1959])
    video, notes, ass = film(tmp_path / "The Twilight Zone" / "Season 3", "The.Twilight.Zone.S03E28.mp4",
                             plex_copy=False)
    assert film_ids.main([str(tmp_path), "--yes", "--api-url", api.url]) == 0
    assert "ids" not in json.loads(notes.read_text(encoding="utf-8"))
    out = capsys.readouterr().out
    assert "The Twilight Zone/Season 3/The.Twilight.Zone.S03E28.mp4" in out and "it might be" in out


def test_the_episode_title_in_a_file_name():
    assert film_ids.episode_title(Path("S02E03 Moss and the German.mp4")) == "moss and the german"
    assert film_ids.episode_title(Path("breaking.bad.s01e01.1080p.bluray.x264-ingot.mkv")) == "ingot"
    assert film_ids.episode_title(Path("Akira.1988.mkv")) == ""


def test_a_title_search_that_isnt_sure_is_skipped_with_yes(tmp_path, capsys):
    api = FakeOpenSubtitles(by_query=[{**BRIAN, "year": 1980}, {**BRIAN, "imdb_id": 5, "year": 1981}])
    video, notes, ass = film(tmp_path, "Life.of.Brian.1979.mkv", plex_copy=False)
    assert film_ids.main([str(tmp_path), "--yes", "--api-url", api.url]) == 0
    out = capsys.readouterr().out
    assert "not found: it might be Life of Brian (1980) tt0079470; Life of Brian (1981) tt0000005" in out
    assert "ids" not in json.loads(notes.read_text(encoding="utf-8"))
    assert "; Film:" not in ass.read_text(encoding="utf-8-sig")


def test_a_title_search_that_isnt_sure_asks_which(tmp_path, monkeypatch):
    api = FakeOpenSubtitles(by_query=[{**BRIAN, "year": 1980}, {**BRIAN, "imdb_id": 5, "year": 1981}])
    video, notes, ass = film(tmp_path, "Life.of.Brian.1979.mkv", plex_copy=False)
    asked = []
    monkeypatch.setattr(film_ids.prompts, "interactive", lambda: True)
    monkeypatch.setattr(film_ids.prompts, "ask", lambda text, choices, default, auto=False, id=None:
                        asked.append((id, choices)) or ("2" if id == "ids.which" else "y"))
    assert film_ids.main([str(tmp_path), "--api-url", api.url]) == 0
    assert asked[0][0] == "ids.which" and asked[0][1]["2"] == "Life of Brian (1981), tt0000005"
    assert json.loads(notes.read_text(encoding="utf-8"))["ids"]["imdb"] == "tt0000005"


def test_ids_given_on_the_command_line(tmp_path):
    video, notes, ass = film(tmp_path, "Some Film.mkv", plex_copy=False)
    assert film_ids.main([str(video), "--yes", "--offline", "--imdb", "79470", "--tmdb", "583"]) == 0
    ids = json.loads(notes.read_text(encoding="utf-8"))["ids"]
    assert (ids["imdb"], ids["tmdb"], ids["source"]) == ("tt0079470", 583, "the command line")


def test_a_plex_copy_that_differs_is_left_alone(tmp_path):
    api = FakeOpenSubtitles(by_hash=[BRIAN])
    video, notes, ass = film(tmp_path, "Life.of.Brian.1979.mkv")
    plex = video.with_name(f"{video.stem}.en.ass")
    plex.write_bytes(plex.read_bytes() + b"Dialogue: 0,0:00:01.00,0:00:02.00,NoteL,,0,0,0,,old\n")
    old = plex.read_bytes()
    film_ids.main([str(tmp_path), "--yes", "--api-url", api.url])
    assert plex.read_bytes() == old and b"; Film:" in ass.read_bytes()


def test_films_in_working_and_recycle_folders_are_skipped(tmp_path):
    film(tmp_path, "A.mkv", plex_copy=False)
    film(tmp_path / "#recycle", "B.mkv", plex_copy=False)
    (tmp_path / "C.mkv").write_bytes(b"no notes")
    assert [p.name for p in film_ids.films(tmp_path)] == ["A.mkv"]


def test_without_a_saved_login_it_uses_only_this_computer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(find_subs, "os_load", lambda: None)
    film(tmp_path, "Life.of.Brian.1979.mkv", plex_copy=False)
    assert film_ids.main([str(tmp_path), "--yes"]) == 0
    out = capsys.readouterr().out
    assert "--set-opensubtitles" in out and "1 not found" in out


def test_the_script_runs_on_its_own(tmp_path):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, str(ROOT / "film_ids.py"), "--help"], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0 and "IMDb" in r.stdout


def test_notes_files_named_for_the_subtitles_are_found(tmp_path):
    video, notes, ass = film(tmp_path, "Film.mkv", plex_copy=False)
    renamed = notes.with_name("notes-Film.en.json")
    notes.rename(renamed)
    assert film_ids.notes_files(video) == [renamed]
    Path(str(renamed).replace(".en.json", ".en.partial.json")).write_text("{}", encoding="utf-8")
    assert film_ids.notes_files(video) == [renamed]
