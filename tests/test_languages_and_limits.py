"""--limit, accent-safe matching, language helpers and the foreign-film prompts."""
import json

import pytest
from conftest import make_srt, run_cli
from test_generate_notes import notes_for_each_part

import analyze
import generate_notes as gn
import languages
import subtitles
import timecode


# ---------------------------------------------------------------- --limit
@pytest.mark.parametrize("text, seconds", [("300", 300), ("5:00", 300), ("1:02:03", 3723), ("5m", 300),
                                           ("90s", 90), ("1h30m", 5400), ("2.5m", 150)])
def test_parse_duration(text, seconds):
    assert timecode.parse_duration(text) == pytest.approx(seconds)


@pytest.mark.parametrize("bad", ["", "0", "-5", "soon", "5x"])
def test_parse_duration_rejects_nonsense(bad):
    with pytest.raises(ValueError):
        timecode.parse_duration(bad)


def test_limit_cues_and_fmt_limit():
    cues = [{"n": i + 1, "start": 10.0 * i, "end": 10.0 * i + 3, "text": "x"} for i in range(10)]
    assert [c["n"] for c in subtitles.limit_cues(cues, 30)] == [1, 2, 3]
    assert subtitles.limit_cues(cues, None) is cues
    assert timecode.fmt_limit(300) == "5:00" and timecode.fmt_limit(3723) == "1:02:03"


def test_limited_alignment_and_transcripts_get_their_own_names(tmp_path):
    assert analyze.aligned_path(tmp_path / "ep.srt").name == "ep.aligned.srt"
    assert analyze.aligned_path(tmp_path / "ep.srt", 300).name == "ep.aligned.first300s.srt"
    assert analyze.transcript_cache(tmp_path, "base.en").name == "transcript-base.en.jsonl"      # unchanged name
    assert analyze.transcript_cache(tmp_path, "small", "fr", 300).name == "transcript-small-fr-first300s.jsonl"


def test_whisper_model_for_each_language():
    assert analyze.whisper_model() == "base.en" and analyze.whisper_model("fr") == "small"
    assert analyze.whisper_model("de", "medium") == "medium"
    with pytest.raises(SystemExit) as e:
        analyze.whisper_model("es", "base.en")
    assert "only understands English" in str(e.value)


def test_generate_with_limit_sends_only_early_lines_and_records_it(tmp_path, api, api_key_file):
    srt = make_srt(tmp_path / "ep.srt", n=30)            # a line every 6 s from 0:03
    api.responder = notes_for_each_part
    spec = gn.generate(srt, tmp_path / "n.json", assume_yes=True, api_url=api.url, limit=60, video_offset=0.9)
    sent = api.calls[0]["body"]["messages"][0]["content"]
    assert "Line 10 of" in sent and "Line 11 of" not in sent                   # line 10 starts at 0:57, 11 at 1:03
    assert spec["limit"] == 60 and spec["video_offset"] == 0.9
    assert "first 1:00" in spec["notes"][0]["text"]


def test_cli_analyze_limit_only_checks_the_first_part(tmp_path, sample_srt):
    r = run_cli("analyze.py", sample_srt, "--limit", "nonsense", cwd=tmp_path)
    assert r.returncode == 2 and "can't read" in r.stderr


# ---------------------------------------------------------------- accents and other languages
def test_fold_and_norm_handle_accents():
    assert subtitles.fold("Été, Straße, cœur, L’homme") == "ete, strasse, coeur, l'homme"
    assert subtitles.norm("¿Qué pasó? «Très bien», ÇA VA") == "que paso tres bien ca va"
    cues = [{"n": 1, "start": 0.0, "end": 1.0, "text": "Ça, c'est le côté obscur."}]
    assert subtitles.find_cue(cues, "ca c'est le cote", 0) == 0                 # model quotes without accents
    assert subtitles.find_cue(cues, "le côté obscur", 0) == 0


def test_align_matches_accented_words():
    words = ["été", "déjà", "très", "fenêtre", "garçon"]
    cues = [{"n": i + 1, "start": 10.0 * i, "end": 10.0 * i + 3, "text": " ".join(f"{w}{'x' * i}" for w in words)}
            for i in range(6)]
    asr = [{"s": 0, "e": 0, "t": "", "w": [[c["start"] + 1.5 + k * 0.33, 0, w.replace("é", "e")]
                                           for k, w in enumerate(c["text"].split())]} for c in cues]
    assigned, segments, stats = analyze.align(cues, asr)
    assert stats["dropped"] == 0 and all(v == pytest.approx(1.5, abs=0.05) for v in assigned.values())


@pytest.mark.parametrize("label, code", [("fre", "fr"), ("fra", "fr"), ("French", "fr"), ("fr-CA", "fr"),
                                         ("ger", "de"), ("deu", "de"), ("es-419", "es"), ("spa", "es"),
                                         ("eng", "en"), ("und", None), (None, None), ("xyz", "xyz")])
def test_language_codes(label, code):
    assert languages.code(label) == code


def test_language_from_filename():
    assert languages.from_filename("Film.fr.srt", "Film") == ("fr", set())
    assert languages.from_filename("Film.French.forced.srt", "Film") == ("fr", {"forced"})
    assert languages.from_filename("Film.embedded.de.srt", "Film") == ("de", {"embedded"})
    assert languages.from_filename("Film.srt", "Film") == (None, set())


def test_guess_language_of_subtitle_text():
    fr = "Je ne sais pas ce que tu veux dire, mais c'est la vie et on ne peut rien y faire. " * 4
    de = "Ich weiß nicht, was du meinst, aber das ist nicht so schlimm und es ist ja egal. " * 4
    es = "No sé qué quieres decir, pero la vida es así y no se puede hacer nada con eso. " * 4
    en = "I don't know what you mean, but that is life and there is nothing you can do with it. " * 4
    assert [languages.guess(t) for t in (fr, de, es, en)] == ["fr", "de", "es", "en"]
    assert languages.guess("Bonjour") is None


def test_pick_track_by_language():
    def track(n, lang, **kw):
        return {"n": n, "codec": "subrip", "lang": lang, "title": "", "forced": False, "sdh": False, "default": False,
                "text": True, "image": False, "frames": "", **kw}
    tracks = [track(0, "eng"), track(1, "fre", forced=True), track(2, "fre"), track(3, "ger")]
    assert analyze.pick_track(tracks)["n"] == 0
    assert analyze.pick_track(tracks, prefer="fr")["n"] == 2                     # full dialogue beats forced
    assert analyze.pick_track(tracks, prefer="es")["n"] == 0                     # not there: any text track...
    assert analyze.pick_track(tracks, prefer="es", strict=True) is None          # ...unless it must be Spanish


def test_strip_sdh_handles_accented_speaker_labels():
    assert analyze.strip_sdh("JÉRÔME: Salut !") == "Salut !"


# ---------------------------------------------------------------- foreign-film prompts
EN = [{"n": i + 1, "start": 5.0 * i, "end": 5.0 * i + 3, "text": t} for i, t in enumerate(
    ["You idiot!", "Shall we go?", "See you tomorrow.", "Nothing."])]
FR = [{"n": i + 1, "start": 5.0 * i + 0.2, "end": 5.0 * i + 2.8, "text": t} for i, t in enumerate(
    ["Espèce de con !", "On y va ?", "À demain."])]


def test_pair_original_matches_by_time():
    paired, share = gn.pair_original(EN, FR)
    assert paired == {1: "Espèce de con !", 2: "On y va ?", 3: "À demain."} and share == 0.75
    line = gn.fmt_line(EN[0], {"lang": "fr", "text": paired})
    assert line.endswith("You idiot!  ‹fr: Espèce de con !›")


def test_language_section_and_audience():
    assert gn.language_section(None, None) == "" and gn.language_section("en", "paired") == ""
    s = gn.language_section("fr", "paired")
    assert "The film is in French" in s and "tu vs vous" in s and "never from the ‹...› original" in s
    assert "du vs Sie" in gn.language_section("de", "translated")
    assert "Spanish" in gn.default_audience("es") and gn.default_audience("en") == gn.DEFAULT_AUDIENCE


def test_generate_for_a_french_film_with_original_subtitles(tmp_path, api, api_key_file):
    srt = make_srt(tmp_path / "film.en.srt", n=10, text="English line {i} of the film")
    orig = make_srt(tmp_path / "film.fr.srt", n=10, text="Réplique française numéro {i}")
    api.responder = lambda n, body, h: (200, {"type": "message", "stop_reason": "end_turn", "usage": {}, "content": [
        {"type": "text", "text": json.dumps([{"cue": 2, "match": "English line 2", "category": "Register",
                                              "text": "Formal 'vous' here.", "confidence": "high"}])}]})
    spec = gn.generate(srt, tmp_path / "n.json", assume_yes=True, api_url=api.url, film_language="fr",
                       original_srt=orig)
    body = api.calls[0]["body"]
    assert "‹fr: Réplique française numéro 3›" in body["messages"][0]["content"]
    assert "The film is in French" in body["system"] and "Translation" in body["system"]
    assert spec["film_language"] == "fr" and spec["original_subtitles"] == "film.fr.srt"
    assert "French" in spec["audience"] and spec["notes"][1]["match"] == "English line 2"


def test_generate_for_an_english_show_is_unchanged(tmp_path, api, api_key_file):
    api.responder = notes_for_each_part
    spec = gn.generate(make_srt(tmp_path / "ep.srt", n=5), tmp_path / "n.json", assume_yes=True, api_url=api.url)
    system = api.calls[0]["body"]["system"]
    assert "The film is in" not in system and "A CV (curriculum vitae)" in system and "{" not in system.split("Reply")[0]
    assert "film_language" not in spec and "limit" not in spec


def test_make_ass_cli_rejects_missing_original_subtitles(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    r = run_cli("make_ass.py", srt, "--generate", "--original-subs", "nope.srt", cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "Can't find the original-language subtitles" in r.stderr


# ---------------------------------------------------------------- fixing a constant offset: analyze.py --shift
def test_shift_by_a_known_amount(tmp_path):
    srt = make_srt(tmp_path / "film.fr.srt", n=4)                   # lines at 3, 9, 15, 21 s
    r = run_cli("analyze.py", srt, "--shift", "-6", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "6.00 s earlier" in r.stdout and "1 line(s) before 0:00" in r.stdout
    fixed = subtitles.parse_srt(tmp_path / "film.fr.aligned.srt")
    assert [c["start"] for c in fixed] == [3.0, 9.0, 15.0] and fixed[0]["text"] == "Line 2 of the original test script"
    r = run_cli("analyze.py", srt, "--shift", "+1.5", cwd=tmp_path)
    assert subtitles.parse_srt(tmp_path / "film.fr.aligned.srt")[0]["start"] == 4.5
    assert srt.read_text() == make_srt(tmp_path / "again.srt", n=4).read_text()          # the original is untouched


def test_shift_needs_a_video_to_measure_and_not_with_align(tmp_path, sample_srt):
    r = run_cli("analyze.py", sample_srt, "--shift", "auto", cwd=tmp_path)
    assert r.returncode == 1 and "add  --video" in r.stderr
    r = run_cli("analyze.py", sample_srt, "--shift", "soon", cwd=tmp_path)
    assert r.returncode == 2 and "'auto' or a number" in r.stderr
    r = run_cli("analyze.py", sample_srt, "--shift", "1", "--align", "--video", "x.mp4", cwd=tmp_path)
    assert r.returncode == 1 and "not both" in r.stderr


def test_generate_with_french_subtitles_quotes_french_and_explains_in_english(tmp_path, api, api_key_file):
    srt = make_srt(tmp_path / "film.fr.srt", n=10, text="Je ne sais pas ce que tu veux dire, réplique {i}")
    api.responder = notes_for_each_part
    spec = gn.generate(srt, tmp_path / "n.json", assume_yes=True, api_url=api.url, film_language="fr")
    system = api.calls[0]["body"]["system"]
    assert "The subtitles are in French too" in system and "explain it in English" in system
    assert "never translate the quote" in system and "Poser un lapin" in system
    assert "what the subtitles lose" not in system                       # that's for reading a translation
    assert "original French subtitles" in spec["audience"]


# ---------------------------------------------------------------- large offsets and subtitle adverts
def _film(offset, seconds=900, seed=3):
    """Irregular dialogue (like a real film, unlike evenly spaced test lines) and a soundtrack where each line's
    speech starts `offset` seconds after its subtitle."""
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(seed)
    cues, t = [], 5.0
    while t < seconds - 60:
        length = float(rng.uniform(1.0, 4.0))
        cues.append({"n": len(cues) + 1, "start": t, "end": t + length, "text": "x"})
        t += length + float(rng.exponential(2.5)) + 0.3
    db = np.full(int(seconds * analyze.FPS_A), -60.0) + rng.normal(0, 2, int(seconds * analyze.FPS_A))
    for c in cues:
        a, b = int((c["start"] + offset) * analyze.FPS_A), int((c["end"] + offset - 0.3) * analyze.FPS_A)
        db[max(a, 0):max(b, 0)] = -25.0
    return db, cues, seconds


@pytest.mark.parametrize("offset", [21.3, -35.0, 0.0])
def test_sync_check_finds_large_offsets(offset):
    db, cues, seconds = _film(offset)
    sync = analyze.sync_check(db, cues, seconds)
    assert sync["offset"] == pytest.approx(offset, abs=0.3)
    assert "--align" not in sync["verdict"]
    assert all(t is not None and abs(t - offset) <= 0.3 for t in sync["thirds"])


def test_coarse_offset_says_when_it_is_unsure():
    np = pytest.importorskip("numpy")
    db, cues, seconds = _film(10.0)
    scrambled = np.roll(db, 300 * analyze.FPS_A)[::-1].copy()          # soundtrack unrelated to the subtitles
    _, strength, corr = analyze.coarse_offset(scrambled, cues)
    assert strength < 1.6 or corr < 0.08


@pytest.mark.parametrize("text, ad", [
    ("Downloaded From www.AllSubs.org", True), ("Subtitles by explosiveskull\nwww.OpenSubtitles.org", True),
    ("Sous-titres : www.sous-titres.eu", True), ("Check www.example.com for the menu", False),
    ("Je vais télécharger le film", False), ("Le 3 septembre 1973", False)])
def test_is_ad(text, ad):
    assert analyze.is_ad(text) == ad


def test_shift_leaves_out_adverts(tmp_path):
    srt = tmp_path / "film.fr.srt"
    srt.write_text("1\n00:00:02,000 --> 00:00:02,000\nDownloaded From www.AllSubs.org\n\n"
                   "2\n00:00:16,095 --> 00:00:20,057\n- Le 3 septembre 1973\n\n", encoding="utf-8")
    r = run_cli("analyze.py", srt, "--shift", "21.3", cwd=tmp_path)
    assert r.returncode == 0 and "1 subtitle-site advert(s)" in r.stdout
    fixed = subtitles.parse_srt(tmp_path / "film.fr.aligned.srt")
    assert [c["text"] for c in fixed] == ["- Le 3 septembre 1973"] and fixed[0]["start"] == pytest.approx(37.395)
    assert "00:00:37,395 --> 00:00:41,357" in (tmp_path / "film.fr.aligned.srt").read_text()


@pytest.mark.parametrize("shift", [0.0, 2.0, -21.3, 47.5])
def test_subtitle_offset_between_two_subtitle_files(shift):
    _, ref, _ = _film(0.0)
    other = [{**c, "start": c["start"] - shift + 0.1, "end": c["end"] - shift - 0.2} for c in ref]   # timed a bit differently
    off, strength, corr = analyze.subtitle_offset(other, ref)
    assert off == pytest.approx(shift, abs=0.25) and strength >= 1.3 and corr >= 0.4


def test_subtitle_offset_of_unrelated_files_is_unsure():
    _, a, _ = _film(0.0, seed=1)
    _, b, _ = _film(0.0, seed=2)
    off, strength, corr = analyze.subtitle_offset(a, b)
    assert strength < 1.3 or corr < 0.4


def test_lines_pushed_before_zero_do_not_fill_the_pattern():
    """A line ending before 0:00 gave a negative slice end, which Python counts from the END of the array."""
    db, cues, seconds = _film(0.0)
    early = [{**c, "start": c["start"] - 30, "end": c["end"] - 30} for c in cues]
    assert analyze.coarse_offset(db, early)[0] == pytest.approx(30, abs=0.3)
    assert analyze.subtitle_offset(early, cues)[0] == pytest.approx(30, abs=0.3)
