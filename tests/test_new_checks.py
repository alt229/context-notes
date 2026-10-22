"""Repeated notes (dedupe.py), note timing (make_ass.py), the per-note alignment check (align_check.py) and
finding subtitles (find_subs.py). No network and no speech recognition: transcripts are made up."""
import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import align_check
import dedupe
import find_subs
import make_ass
from conftest import make_srt, run_cli


# ---------------------------------------------------------------- dedupe
def n(text, cat="Idiom", **kw):
    return {"match": "x", "category": cat, "text": text, **kw}


def test_same_quoted_subject_repeated_is_a_duplicate():
    notes = [n("'Battre la chamade': a heart pounding wildly, usually from love."),
             n("Unrelated: the Canal Saint-Martin is in eastern Paris."),
             n("“Battre la chamade” again: the heart pounding, here from fear.")]
    dups, _ = dedupe.find_duplicates(notes)
    assert [(j, i) for j, i, _ in dups] == [(2, 0)]


def test_nearly_identical_text_is_a_duplicate_whatever_the_subject():
    a = "Kaleun is navy slang for Kapitänleutnant, the rank of the U-boat's captain."
    dups, _ = dedupe.find_duplicates([n(a), n(a.replace("navy slang", "crew slang"))])
    assert len(dups) == 1


def test_running_gags_intro_and_keep_are_never_dropped():
    a = "'Kaleun' is short for Kapitänleutnant, the captain's rank."
    notes = [n(a), n(a, cat="Running gag"), n(a, keep=True), n(a, cat="About these notes")]
    dups, _ = dedupe.find_duplicates(notes)
    assert dups == []


def test_mentioning_the_same_thing_with_a_new_point_is_kept():
    notes = [n("A 'kir' is white wine with blackcurrant liqueur, the classic café order."),
             n("A 'Moresque' is pastis with almond syrup; next to the kir it marks him as a southerner, and the "
               "barman's eye-roll says what Parisians think of that.")]
    dups, _ = dedupe.find_duplicates(notes)
    assert dups == []


def test_apostrophes_are_not_quotes():
    assert dedupe.quoted("Gainsbourg's song 'Le Poinçonneur des Lilas' isn't d'Enghien") == {"le poinconneur des lilas"}


def test_build_leaves_repeats_out_and_says_so(tmp_path):
    srt = make_srt(tmp_path / "ep.srt", n=6)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"notes": [
        {"cue": 1, "category": "Idiom", "text": "'Take the mickey': to tease someone."},
        {"cue": 4, "category": "Idiom", "text": "'Take the mickey': to tease someone, gently."}]}))
    msgs = []
    placed, _ = make_ass.build(srt, notes, tmp_path / "o.ass", say=msgs.append)
    assert len(placed) == 1 and any("Left out 1 repeated" in m for m in msgs)
    placed, _ = make_ass.build(srt, notes, tmp_path / "o.ass", keep_duplicates=True, say=msgs.append)
    assert len(placed) == 2


# ---------------------------------------------------------------- timing
def test_note_duration_reads_at_the_set_speed_within_limits():
    t = make_ass.timing_settings()
    assert make_ass.note_duration("word " * 3, timing=t) == 6.0                     # floor
    assert abs(make_ass.note_duration("word " * 30, timing=t) - 14.0) < 1e-9          # 2 + 30 * 60/150
    assert make_ass.note_duration("word " * 80, timing=t) == 24.0                    # ceiling
    slow = make_ass.timing_settings({"timing": {"wpm": 120}})
    assert abs(make_ass.note_duration("word " * 30, timing=slow) - 17.0) < 1e-9
    assert make_ass.note_duration("word " * 30, override=4, timing=t) == 4.0


def test_timing_given_on_the_command_line_is_remembered(tmp_path):
    srt = make_srt(tmp_path / "ep.srt", n=6)
    notes = tmp_path / "notes.json"
    long = " ".join(["word"] * 60)          # 2 s + 60 words at 150 a minute = 26 s
    notes.write_text(json.dumps({"notes": [{"cue": 2, "category": "Idiom", "text": long}]}))
    r = run_cli("make_ass.py", srt, notes, "--note-max", "30", "--timing-report", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert json.loads(notes.read_text())["timing"] == {"max": 30.0}
    assert "0 note(s) cut short" in r.stdout
    r = run_cli("make_ass.py", srt, notes, "--timing-report", cwd=tmp_path)          # remembered
    assert "kept between 6 and 30 s" in r.stdout
    r = run_cli("make_ass.py", srt, notes, "--note-max", "10", "--timing-report", cwd=tmp_path)
    assert "1 note(s) cut short by the 10 s ceiling" in r.stdout


# ---------------------------------------------------------------- alignment check
def cues_and_transcript(n=60, gap=5.0, late_from=None, late_to=None, late_by=0.0):
    """Subtitles every `gap` s, each with 5 distinct words; a transcript where the words are spoken exactly
    when the line appears, except lines in [late_from, late_to) whose speech comes `late_by` s EARLIER than the line
    (so those lines are late)."""
    cues, asr = [], []
    for i in range(n):
        start = 2.0 + i * gap
        ws = [f"w{i}x{k}" for k in range(5)]
        cues.append({"n": i + 1, "start": start, "end": start + 2.5, "text": " ".join(ws)})
        spoken = start - (late_by if late_from is not None and late_from <= start < late_to else 0.0)
        asr.append({"s": spoken, "e": spoken + 2, "t": " ".join(ws),
                    "w": [[spoken + 0.3 * k, spoken + 0.3 * k + 0.25, " " + w] for k, w in enumerate(ws)]})
    return cues, asr


def placed_after_each(cues, every=2):
    return [{"k": k + 1, "start": c["end"] + 0.2, "end": c["end"] + 8, "kind": "speech", "category": "Idiom",
             "text": f"note {k}"} for k, c in enumerate(cues) if k % every == 1]


def test_alignment_check_finds_a_late_stretch_and_nothing_else():
    cues, asr = cues_and_transcript(late_from=100, late_to=160, late_by=1.5)
    offsets = align_check.asr_cue_offsets(cues, asr)
    assert len(offsets) == len(cues)
    rows = align_check.flag(align_check.measure(placed_after_each(cues), cues, 0.0, 10.0, offsets))
    runs = align_check.stretches(rows)
    assert len(runs) == 1
    assert abs(runs[0]["offset"] + 1.5) < 0.05                     # negative: lines late
    assert 100 <= runs[0]["from"] <= 125 and 150 <= runs[0]["to"] <= 175


def test_alignment_check_in_sync_film_is_clean_and_offset_is_allowed_for():
    cues, asr = cues_and_transcript()
    offsets = align_check.asr_cue_offsets(cues, asr)
    rows = align_check.flag(align_check.measure(placed_after_each(cues), cues, 0.0, 10.0, offsets))
    assert align_check.stretches(rows) == []
    # The build already shifts everything by video_offset: a constant offset alone is not "out".
    shifted = [{**c, "start": c["start"] - 2.0, "end": c["end"] - 2.0} for c in cues]
    offsets = align_check.asr_cue_offsets(shifted, asr)
    placed = [{**p, "start": p["start"]} for p in placed_after_each(cues)]
    rows = align_check.flag(align_check.measure(placed, shifted, 2.0, 10.0, offsets))
    assert align_check.stretches(rows) == []


def test_alignment_check_measures_translated_subtitles_through_the_original():
    orig, asr = cues_and_transcript(late_from=100, late_to=160, late_by=1.5)
    english = [{"n": c["n"], "start": c["start"] + 0.1, "end": c["end"], "text": f"english line {c['n']}"} for c in orig]
    offsets = align_check.through_original(english, orig, align_check.asr_cue_offsets(orig, asr))
    rows = align_check.flag(align_check.measure(placed_after_each(english), english, 0.0, 10.0, offsets))
    runs = align_check.stretches(rows)
    assert len(runs) == 1 and abs(runs[0]["offset"] + 1.6) < 0.05


def test_alignment_fix_moves_only_the_stretch(tmp_path):
    cues, _ = cues_and_transcript()
    runs = [{"from": 110.0, "to": 150.0, "offset": -1.5, "notes": [1]}]
    shifts = align_check.corrections(cues, 0.0, runs, 10.0)
    moved = {i for i, v in shifts.items() if v}
    assert moved == {i for i, c in enumerate(cues) if 100 <= c["start"] <= 150}
    assert align_check.fixed_path(Path("film.en.srt")).name == "film.en.aligned.srt"
    assert align_check.fixed_path(Path("film.en.aligned.srt")).name == "film.en.aligned.srt"
    assert align_check.fixed_path(Path("f.en.aligned.first600s.srt")).name == "f.en.aligned.first600s.srt"
    # stretch times are on the video's clock: with video_offset 30, the lines that move are 30 s earlier in the file
    shifts = align_check.corrections(cues, 30.0, runs, 10.0)
    assert {i for i, v in shifts.items() if v} == {i for i, c in enumerate(cues) if 70 <= c["start"] <= 120}
    assert set(shifts.values()) == {0.0, -1.5}


def test_find_transcript_prefers_the_whole_film_in_the_right_language(tmp_path):
    for name in ("transcript-small-de-first300s.jsonl", "transcript-small-de.jsonl", "transcript-base.en.jsonl"):
        (tmp_path / name).write_text("")
    assert align_check.find_transcript(tmp_path, "de", None).name == "transcript-small-de.jsonl"
    assert align_check.find_transcript(tmp_path, "en", None).name == "transcript-base.en.jsonl"
    assert align_check.find_transcript(tmp_path, "fr", None) is None


# ---------------------------------------------------------------- finding subtitles
def test_title_key_ignores_release_details():
    assert find_subs.title_key("Das.Boot.1981.Directors.Cut.1080p.BluRay.x264.srt") == "das boot 1981"
    assert find_subs.title_key("Das Boot (1981).mkv") == "das boot 1981"


def test_finds_subtitles_in_a_subs_folder_and_copies_them_beside_the_video(tmp_path):
    video = tmp_path / "Das Boot (1981).mkv"
    video.write_bytes(b"\0" * 1000)
    subs = tmp_path / "Subs"
    subs.mkdir()
    make_srt(subs / "2_English.srt", n=30, text="The captain said that you and I are not done {i}")
    make_srt(subs / "3_English_SDH.srt", n=40, text="[ENGINE HUMS] The captain said that you are {i}")
    make_srt(subs / "4_German.srt", n=30, text="Ich weiß nicht, was du willst, und das ist es {i}")
    got = find_subs.find(video, "en", online=False, transcribe=False)
    assert got == tmp_path / "Das Boot (1981).en.srt" and got.exists()
    assert "captain said" in got.read_text()                        # the full-dialogue one, not the SDH one
    assert (subs / "2_English.srt").exists()                        # copied, not moved
    got = find_subs.find(video, "de", online=False, transcribe=False)
    assert got.name == "Das Boot (1981).de.srt"


def test_other_episodes_subtitles_are_not_taken(tmp_path):
    video = tmp_path / "S01E04 The Red Door.mp4"
    video.write_bytes(b"\0" * 1000)
    (tmp_path / "S01E05.mp4").write_bytes(b"\0" * 1000)
    make_srt(tmp_path / "Show.S01E05.srt", n=30, text="The captain said that you and I are not done {i}")
    assert find_subs.find(video, "en", online=False, transcribe=False) is None
    make_srt(tmp_path / "Show.S01E04.WEB.srt", n=30, text="The captain said that you and I are not done {i}")
    assert find_subs.find(video, "en", online=False, transcribe=False).name == "S01E04 The Red Door.en.srt"


def test_movie_hash_matches_the_published_algorithm(tmp_path):
    p = tmp_path / "v.bin"
    data = bytes(range(256)) * 1024                                 # 256 KB
    p.write_bytes(data)
    want = len(data)
    for chunk in (data[:65536], data[-65536:]):
        for (v,) in struct.iter_unpack("<Q", chunk):
            want = (want + v) % 2 ** 64
    assert find_subs.movie_hash(p) == f"{want:016x}"


def test_transcript_becomes_readable_subtitles():
    asr = [{"s": 0, "e": 9, "t": "", "w": [[0.0 + k * 0.3, 0.25 + k * 0.3, f" word{k}"] for k in range(30)]},
           {"s": 12, "e": 13, "t": "", "w": [[12.0, 12.4, " Later."]]}]
    cues = find_subs.transcript_to_cues(asr)
    assert len(cues) >= 3
    assert all(c["end"] - c["start"] <= 6.6 for c in cues)
    assert all(c["end"] <= d["start"] for c, d in zip(cues, cues[1:]))
    assert cues[-1]["text"] == "Later."


class FakeOpenSubtitles:
    def __init__(self, srt_text, hash_match=True):
        self.calls = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, obj, raw=None):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                fake.calls.append(("GET", self.path, dict(self.headers)))
                if self.path.startswith("/file"):
                    return self.reply(None, srt_text.encode())
                self.reply({"data": [
                    {"attributes": {"moviehash_match": False, "download_count": 900, "release": "Other.Cut",
                                    "files": [{"file_id": 1}]}},
                    {"attributes": {"moviehash_match": hash_match, "download_count": 10, "release": "Exact.Release",
                                    "files": [{"file_id": 2}]}}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.calls.append(("POST", self.path, body))
                if self.path.endswith("/login"):
                    return self.reply({"token": "T"})
                return self.reply({"link": f"http://127.0.0.1:{fake.port}/file/{body['file_id']}", "remaining": 4})

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.port}/api/v1"


def test_opensubtitles_prefers_the_file_made_for_this_release(tmp_path):
    srt_text = make_srt(tmp_path / "x.srt", n=5).read_text()
    api = FakeOpenSubtitles(srt_text)
    video = tmp_path / "Film.2001.mkv"
    video.write_bytes(b"\1" * 200000)
    cfg = {"api_key": "K", "username": "u", "password": "p"}
    got = find_subs.search_online(video, "de", cfg, api=api.url)
    assert got == tmp_path / "Film.2001.de.srt" and "Line 1" in got.read_text()
    search = next(c for c in api.calls if c[0] == "GET" and "/subtitles" in c[1])
    assert "moviehash=" in search[1] and search[2]["Api-Key"] == "K"
    assert ("POST", "/api/v1/download", {"file_id": 2}) in [(m, p, b) for m, p, b in api.calls if m == "POST"]
    api.server.shutdown()


def test_an_episode_named_by_code_searches_by_the_show_folder(tmp_path):
    srt_text = make_srt(tmp_path / "x.srt", n=5).read_text()
    api = FakeOpenSubtitles(srt_text, hash_match=False)
    folder = tmp_path / "IT Crowd" / "Season 2"
    folder.mkdir(parents=True)
    video = folder / "S02E03 Moss and the German.mp4"
    video.write_bytes(b"\1" * 200000)
    cfg = {"api_key": "K", "username": "u", "password": "p"}
    find_subs.search_online(video, "en", cfg, api=api.url)
    searches = [c[1] for c in api.calls if c[0] == "GET" and "/subtitles" in c[1]]
    assert any("query=it+crowd" in s and "season_number=2" in s and "episode_number=3" in s for s in searches)
    api.server.shutdown()


def test_a_shared_subs_folder_only_gives_a_film_its_own_subtitles(tmp_path):
    for name in ("Amelie (2001).mkv", "Das Boot (1981).mkv"):
        (tmp_path / name).write_bytes(b"\0" * 1000)
    subs = tmp_path / "Subs"
    subs.mkdir()
    make_srt(subs / "Amelie.2001.English.srt", n=50, text="The captain said that you and I are not done {i}")
    make_srt(subs / "English.srt", n=40, text="The captain said that you and I are not done {i}")
    assert find_subs.find(tmp_path / "Das Boot (1981).mkv", "en", online=False, transcribe=False) is None
    make_srt(subs / "Das.Boot.1981.Directors.Cut.English.srt", n=30, text="The captain said that you are {i}")
    got = find_subs.find(tmp_path / "Das Boot (1981).mkv", "en", online=False, transcribe=False)
    assert got.name == "Das Boot (1981).en.srt" and "you are" in got.read_text()


def fake_login_server(status):
    """A stand-in for the login and account endpoints: `status` 200 accepts the login, anything else refuses it."""
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            calls.append(("POST", self.path, dict(self.headers)))
            self.rfile.read(int(self.headers["Content-Length"]))
            if status != 200:
                return self.reply(status, {"message": "Error, invalid username/password", "status": status})
            self.reply(200, {"token": "T", "user": {"allowed_downloads": 20}})

        def do_GET(self):
            calls.append(("GET", self.path, dict(self.headers)))
            self.reply(200, {"data": {"allowed_downloads": 20, "remaining_downloads": 17, "level": "Sub leecher"}})

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/api/v1", calls


def test_opensubtitles_login_test_reports_downloads_left(capsys):
    server, url, calls = fake_login_server(200)
    assert find_subs.os_test({"api_key": "K", "username": "erin", "password": "p"}, api=url)
    out = capsys.readouterr().out
    assert "logged in as erin" in out and "17 of 20" in out
    assert not any("/download" in path for _, path, _ in calls)          # testing never spends a download
    info = next(c for c in calls if c[0] == "GET")
    assert info[2]["Authorization"] == "Bearer T"
    server.shutdown()


def test_opensubtitles_login_test_explains_a_refused_password(capsys):
    server, url, _ = fake_login_server(401)
    assert not find_subs.os_test({"api_key": "K", "username": "erin", "password": "wrong"}, api=url)
    out = capsys.readouterr().out
    assert "username or password was refused" in out and "--set-opensubtitles" in out
    server.shutdown()


def test_opensubtitles_login_test_without_a_saved_login(capsys):
    assert not find_subs.os_test(None)
    assert "--set-opensubtitles" in capsys.readouterr().out


def test_find_subs_limit_reaches_speech_recognition(tmp_path, monkeypatch):
    video = tmp_path / "Parasite (2019).mkv"
    video.write_bytes(b"\0" * 1000)
    seen = {}
    monkeypatch.setattr(find_subs, "have_whisper", lambda: True)
    monkeypatch.setattr(find_subs, "transcribe_subs",
                        lambda v, lang, model=None, limit=None: seen.update(lang=lang, limit=limit) or v)
    assert find_subs.main([str(video), "--lang", "ko", "--offline", "--transcribe", "--limit", "10:00"]) == 0
    assert seen == {"lang": "ko", "limit": 600.0}
