"""How the notes look on screen: the box behind them, the "; Look:" line that records how a .ass was built (so
context_notes.py can rebuild an out-of-date one for free), seconds a word from the app, and the old "Pre-alpha"
intro note shown as "Alpha"."""
import json
import re

import pytest
from conftest import make_srt, run_cli

import app
import make_ass

FIELDS = ("Name Fontname Fontsize PrimaryColour SecondaryColour OutlineColour BackColour Bold Italic Underline "
          "StrikeOut ScaleX ScaleY Spacing Angle BorderStyle Outline Shadow Alignment MarginL MarginR MarginV "
          "Encoding").split()


def style(text, name):
    line = next(ln for ln in text.splitlines() if ln.startswith(f"Style: {name},"))
    return dict(zip(FIELDS, line[len("Style: "):].split(",")))


def look(path):
    m = make_ass.LOOK_LINE.search(path.read_text(encoding="utf-8-sig"))
    return m and (int(m["build"]), m["background"], float(m["wpm"]))


def opacity(path):
    m = make_ass.LOOK_LINE.search(path.read_text(encoding="utf-8-sig"))
    return m and m["opacity"] and float(m["opacity"])


def quiet(*_):
    pass


@pytest.fixture
def film(tmp_path):
    srt = make_srt(tmp_path / "s.srt", n=4)
    notes = tmp_path / "n.json"
    notes.write_text(json.dumps({"title": "T", "notes": [
        {"match": "Line 2", "category": "Idiom", "text": "A note"},
        {"at_video": "00:00:20,000", "kind": "visual", "category": "Prop", "text": "A prop"}]}))
    return srt, notes, tmp_path / "s.ass"


# ---------------------------------------------------------------- the box
def test_the_default_box_is_see_through(film):
    srt, notes, out = film
    make_ass.build(srt, notes, out, say=quiet)
    text = out.read_text(encoding="utf-8-sig")
    left, right = style(text, "NoteL"), style(text, "NoteR")
    assert left["BorderStyle"] == right["BorderStyle"] == "3"                     # still a box...
    assert left["OutlineColour"] == left["BackColour"] == "&HB2101010"            # ...30% solid (B2 = 70% clear)
    assert right["OutlineColour"] == right["BackColour"] == "&HB2281810"
    assert look(out) == (make_ass.BUILD, "see-through", 150.0) and opacity(out) == 30.0


def test_see_through_boxes_never_overlap(film):
    """A see-through box that overlaps another shows a darker band: the lines' boxes only touch (\\ybord0), and the
    label line is one colour, so it gets one box."""
    srt, notes, out = film
    spec = json.loads(notes.read_text())
    spec["notes"][0]["confidence"] = "medium"
    notes.write_text(json.dumps(spec))
    make_ass.build(srt, notes, out, say=quiet)
    unsure, sure = sorted((ln for ln in out.read_text(encoding="utf-8-sig").splitlines() if ln.startswith("Dialogue: 1")),
                          key=lambda ln: "less sure" not in ln)
    colour = make_ass.CATEGORY_COLOURS["idiom"]
    assert unsure.endswith(f",,{{\\fad(250,350)\\ybord0}}{{\\fs26\\b1\\c{colour}}}IDIOM  (less sure){{\\b0}}"
                           "{\\fs35\\c&HF0F0F0&}\\NA note")
    prop = make_ass.CATEGORY_COLOURS["prop"]
    assert sure.endswith(f",,{{\\fad(250,350)\\ybord0}}{{\\fs26\\b1\\c{prop}}}PROP{{\\b0}}{{\\fs35\\c&HF0F0F0&}}\\NA prop")
    make_ass.build(srt, notes, out, background="dark", say=quiet)                    # dark: the pink flag, as before
    assert "IDIOM{\\b0}  {\\c&H8C8CFF&}(less sure){\\c&HF0F0F0&}" in out.read_text(encoding="utf-8-sig")


@pytest.mark.parametrize("percent, alpha", [(0, "FF"), (30, "B2"), (50, "80"), (100, "00"), (12.5, "DF")])
def test_how_solid_the_box_is(film, percent, alpha):
    srt, notes, out = film
    make_ass.build(srt, notes, out, opacity=percent, say=quiet)
    text = out.read_text(encoding="utf-8-sig")
    assert style(text, "NoteL")["OutlineColour"] == style(text, "NoteL")["BackColour"] == f"&H{alpha}101010"
    assert style(text, "NoteR")["BackColour"] == f"&H{alpha}281810"
    assert opacity(out) == percent
    make_ass.build(srt, notes, out, background="dark", opacity=percent, say=quiet)       # only for see-through
    assert style(out.read_text(encoding="utf-8-sig"), "NoteL")["BackColour"] == "&H38101010" and opacity(out) is None


def test_cli_opacity_is_remembered_and_checked(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"notes": [{"cue": 1, "text": "hi"}]}))
    ass = tmp_path / "Ep.notes.ass"

    def build(*extra):
        return run_cli("make_ass.py", srt, notes, "--video", "Ep.mp4", *extra, cwd=tmp_path, home_dir=home)

    assert build("--note-opacity", "30%").returncode == 0
    assert "note_opacity" not in json.loads(notes.read_text())                        # the default isn't written in
    assert build("--note-opacity", "55").returncode == 0 and opacity(ass) == 55
    assert json.loads(notes.read_text())["note_opacity"] == 55
    assert build().returncode == 0 and opacity(ass) == 55                            # kept on later rebuilds
    for bad in ("101", "-1", "half"):
        r = build("--note-opacity", bad)
        assert r.returncode == 2 and "from 0 (invisible) to 100 (solid)" in r.stderr, r.stderr
    notes.write_text(json.dumps({"note_opacity": "lots", "notes": [{"cue": 1, "text": "hi"}]}))
    r = build()
    assert r.returncode == 1 and '"note_opacity" in the notes file must be a number from 0 to 100' in r.stderr


def test_dark_is_exactly_the_look_before(film):
    srt, notes, out = film
    make_ass.build(srt, notes, out, background="dark", say=quiet)
    text = out.read_text(encoding="utf-8-sig")
    assert ("Style: NoteL,Arial,35,&H00F0F0F0,&H000000FF,&H38101010,&H38101010,0,0,0,0,100,100,0,0,3,14,0,7,44,1040,"
            "36,1\n") in text
    assert ("Style: NoteR,Arial,35,&H00F0F0F0,&H000000FF,&H38281810,&H38281810,0,0,0,0,100,100,0,0,3,14,0,9,1040,44,"
            "36,1\n") in text


def test_no_box_outlines_the_text_and_leaves_the_dialogue_alone(film):
    srt, notes, out = film
    make_ass.build(srt, notes, out, background="dark", say=quiet)
    before = out.read_text(encoding="utf-8-sig")
    make_ass.build(srt, notes, out, background="none", say=quiet)
    text = out.read_text(encoding="utf-8-sig")
    for name in ("NoteL", "NoteR"):
        s = style(text, name)
        assert (s["BorderStyle"], s["Outline"], s["Shadow"], s["OutlineColour"]) == ("1", "2", "1", "&H00101010")
        assert {k: v for k, v in s.items() if k not in ("OutlineColour", "BackColour", "BorderStyle", "Outline", "Shadow")} \
            == {k: v for k, v in style(before, name).items()
                if k not in ("OutlineColour", "BackColour", "BorderStyle", "Outline", "Shadow")}
    assert style(text, "Dialogue") == style(before, "Dialogue")
    events = lambda t: [ln for ln in t.splitlines() if ln.startswith("Dialogue: ")]   # noqa: E731
    assert events(text) == events(before)                                            # same notes, same times


def test_the_look_line_and_a_title_that_looks_like_a_placeholder(film):
    srt, notes, out = film
    spec = json.loads(notes.read_text())
    notes.write_text(json.dumps({**spec, "title": "Odd {fs} {border} title", "timing": {"wpm": 120},
                                 "note_background": "none"}))
    make_ass.build(srt, notes, out, say=quiet)
    text = out.read_text(encoding="utf-8-sig")
    assert look(out) == (make_ass.BUILD, "none", 120.0)                              # from the notes file
    assert "Title: Odd {fs} {border} title\n" in text                                 # left as it is
    assert text.index("; Generated by make_ass.py") < 300                             # the Plex copy still knows it


def test_cli_remembers_the_background_like_the_timing(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"notes": [{"cue": 1, "text": "hi"}]}))
    ass = tmp_path / "Ep.notes.ass"

    def build(*extra):
        return run_cli("make_ass.py", srt, notes, "--video", "Ep.mp4", *extra, cwd=tmp_path, home_dir=home)

    assert build().returncode == 0
    assert "note_background" not in json.loads(notes.read_text())                    # the default isn't written in
    assert look(ass)[1] == "see-through" and look(tmp_path / "Ep.en.ass")[1] == "see-through"
    r = build("--note-background", "none", "--reading-speed", "100")
    assert r.returncode == 0, r.stderr
    spec = json.loads(notes.read_text())
    assert spec["note_background"] == "none" and spec["timing"] == {"wpm": 100}
    assert build().returncode == 0 and look(ass) == (make_ass.BUILD, "none", 100.0)   # a later rebuild keeps both
    assert build("--note-background", "see-through").returncode == 0
    assert json.loads(notes.read_text())["note_background"] == "see-through"           # and switching back works
    r = build("--note-background", "pink")
    assert r.returncode == 2 and "invalid choice" in r.stderr
    notes.write_text(json.dumps({"note_background": "pink", "notes": [{"cue": 1, "text": "hi"}]}))
    r = build()
    assert r.returncode == 1 and '"note_background" in the notes file must be one of' in r.stderr


# ---------------------------------------------------------------- Alpha
def test_an_old_pre_alpha_intro_shows_as_alpha_and_the_file_is_left_alone(tmp_path):
    srt = make_srt(tmp_path / "s.srt", n=4)
    notes = tmp_path / "n.json"
    notes.write_text(json.dumps({"notes": [
        {"at": "00:00:01,000", "category": "About these notes", "duration": 9, "kind": "speech",
         "text": "Pre-alpha context notes written by Claude (claude-opus-5-5) for this viewer: x. Each note..."},
        {"match": "Line 2", "category": "Idiom", "text": "Pre-alpha context notes, said in another note"}]}),
        encoding="utf-8")
    before = notes.read_bytes()
    out = tmp_path / "s.ass"
    make_ass.build(srt, notes, out, say=quiet)
    text = out.read_text(encoding="utf-8-sig")
    assert r"\NAlpha context notes written by Claude (claude-opus-5-5)" in text
    assert "Pre-alpha context notes written" not in text
    assert "Pre-alpha context notes, said in another note" in text                    # only the intro note changes
    assert notes.read_bytes() == before


def test_new_notes_say_alpha(tmp_path, api, api_key_file):
    import generate_notes as gn
    from test_generate_notes import notes_for_each_part
    api.responder = notes_for_each_part
    spec = gn.generate(make_srt(tmp_path / "ep.srt", n=30), tmp_path / "notes.json", title="T", assume_yes=True,
                       api_url=api.url)
    assert spec["notes"][0]["text"].startswith("Alpha context notes written by Claude")


# ---------------------------------------------------------------- context_notes.py: a free rebuild
def finished(folder, name="Ep", **extra):
    """A video whose notes are written and refined (no .ass yet)."""
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / f"{name}.mp4"
    video.write_bytes(b"")
    make_srt(folder / f"{name}.srt", n=6, text="I don't know what you mean but that is the way it is {i}")
    notes = folder / f"notes-{name}.json"
    notes.write_text(json.dumps({"title": name, "refined": {"model": "m"},
                                 "notes": [{"cue": 2, "category": "Idiom", "text": "hi"}], **extra}))
    return video, notes


def wrapper(*args, home, cwd):
    return run_cli("context_notes.py", *map(str, args), cwd=cwd, home_dir=home)


def test_an_ass_from_before_is_rebuilt_for_free_with_no_api_key(tmp_path, home):
    video, notes = finished(tmp_path / "films")
    ass = video.with_name("Ep.notes.ass")
    assert run_cli("make_ass.py", video.with_suffix(".srt"), notes, "--video", video, "--note-background", "dark",
                   cwd=video.parent, home_dir=home).returncode == 0
    ass.write_text(re.sub(r"^; Look:.*\n", "", ass.read_text(encoding="utf-8-sig"), flags=re.M),
                   encoding="utf-8-sig")                                              # as built before 0.2.0
    r = wrapper(video.parent, "--status", home=home, cwd=tmp_path)
    assert "[to do] Ep.mp4" in r.stdout and "Ep.notes.ass needs rebuilding (free)" in r.stdout, r.stdout
    r = wrapper(video, home=home, cwd=tmp_path)                       # no key in this home, no --api-url
    assert r.returncode == 0, r.stdout + r.stderr
    assert "rebuilding Ep.notes.ass (free: nothing is sent to Claude)" in r.stdout and "Ready: play Ep.mp4" in r.stdout
    assert look(ass) == (make_ass.BUILD, "dark", 150.0)                                # the remembered look is kept
    assert "Already done" in wrapper(video, home=home, cwd=tmp_path).stdout


def test_a_new_look_for_a_finished_video_only_rebuilds_it(tmp_path, home):
    video, notes = finished(tmp_path / "films")
    ass = video.with_name("Ep.notes.ass")
    r = wrapper(video, home=home, cwd=tmp_path)                       # notes done, no .ass yet: built
    assert r.returncode == 0 and look(ass) == (make_ass.BUILD, "see-through", 150.0), r.stdout + r.stderr
    assert "Already done" in wrapper(video, home=home, cwd=tmp_path).stdout
    r = wrapper(video, "--status", "--reading-speed", "120", home=home, cwd=tmp_path)
    assert "needs rebuilding (free)" in r.stdout
    r = wrapper(video, "--reading-speed", "120", "--note-background", "none", home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "--reading-speed 120 --note-background none" in r.stdout
    assert look(ass) == (make_ass.BUILD, "none", 120.0)
    spec = json.loads(notes.read_text())
    assert spec["timing"] == {"wpm": 120} and spec["note_background"] == "none"
    for again in ((), ("--reading-speed", "120"), ("--note-background", "none")):      # remembered: nothing to do
        assert "Already done" in wrapper(video, *again, home=home, cwd=tmp_path).stdout
    assert "Already done" in wrapper(video, "--note-opacity", "60", home=home, cwd=tmp_path).stdout   # no box: moot
    r = wrapper(video, "--note-background", "see-through", "--note-opacity", "60", home=home, cwd=tmp_path)
    assert "rebuilding" in r.stdout and "--note-background see-through --note-opacity 60" in r.stdout, r.stdout
    assert look(ass)[1] == "see-through" and opacity(ass) == 60
    assert "Already done" in wrapper(video, home=home, cwd=tmp_path).stdout
    assert "needs rebuilding" in wrapper(video, "--status", "--note-opacity", "30", home=home, cwd=tmp_path).stdout
    r = wrapper(video, "--note-opacity", "150", home=home, cwd=tmp_path)
    assert r.returncode == 2 and "from 0 (invisible) to 100 (solid)" in r.stderr
    r = wrapper(video, "--reading-speed", "0", home=home, cwd=tmp_path)
    assert r.returncode == 2 and "--reading-speed is words a minute" in r.stderr


def test_a_rebuild_is_reported_to_the_app(tmp_path, home):
    video, _ = finished(tmp_path / "films")
    assert wrapper(video, home=home, cwd=tmp_path).returncode == 0
    (v,) = app.status({"path": str(video)})["videos"]
    assert v["done"] and not v["rebuild"]
    (v,) = app.status({"path": str(video), "seconds_per_word": "0.5"})["videos"]       # 120 words a minute
    assert not v["done"] and v["rebuild"] and v["notes"] == 1


# ---------------------------------------------------------------- the app's form
def test_seconds_a_word_and_the_background_from_the_form(tmp_path):
    f = tmp_path / "film.mkv"
    f.write_bytes(b"")
    assert app.common_args({"path": str(f), "seconds_per_word": "0.5", "note_background": "none"}) == \
        [str(f), "--reading-speed", "120", "--note-background", "none"]
    assert app.common_args({"path": str(f), "seconds_per_word": "0,6"})[-2:] == ["--reading-speed", "100"]
    assert app.common_args({"path": str(f), "seconds_per_word": " ", "note_background": ""}) == [str(f)]
    for bad in ("soon", "0", "-1", "3", "nan", "inf"):
        with pytest.raises(app.BadRequest, match="Seconds a word"):
            app.common_args({"path": str(f), "seconds_per_word": bad})
    with pytest.raises(app.BadRequest):
        app.common_args({"path": str(f), "note_background": "--yes"})
    assert app.common_args({"path": str(f), "box_opacity": "45%"}) == [str(f), "--note-opacity", "45"]
    assert app.common_args({"path": str(f), "box_opacity": "0"})[-1] == "0" and \
        app.common_args({"path": str(f), "box_opacity": "12,5"})[-1] == "12.5"
    for bad in ("101", "-5", "lots", "nan"):
        with pytest.raises(app.BadRequest, match="How solid the box is"):
            app.common_args({"path": str(f), "box_opacity": bad})


def test_a_foreign_film_with_notes_from_english_subtitles_is_rebuilt_from_them(tmp_path, home):
    """As Parasite: a Korean film, no Korean subtitles, notes written from the English ones."""
    folder = tmp_path / "films"
    folder.mkdir()
    video = folder / "Film.mkv"
    video.write_bytes(b"")
    make_srt(folder / "Film.embedded.en.srt", n=6, text="I don't know what you mean but that is the way it is {i}")
    notes = folder / "notes-Film.json"
    notes.write_text(json.dumps({"title": "Film", "film_language": "ko", "limit": 900.0,
                                 "refined": {"model": "m", "limit": 900.0},
                                 "notes": [{"cue": 2, "category": "Idiom", "text": "hi"}]}))
    r = wrapper(video, "--limit", "15:00", "--status", home=home, cwd=tmp_path)
    assert "needs rebuilding (free)" in r.stdout, r.stdout
    r = wrapper(video, "--limit", "15:00", home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Film.embedded.en.srt notes-Film.json --video Film.mkv" in r.stdout
    assert "No Korean subtitles found" not in r.stdout and "Every note's timing" not in r.stdout
    assert look(folder / "Film.notes.ass") == (make_ass.BUILD, "see-through", 150.0)
    assert "Already done" in wrapper(video, "--limit", "15:00", home=home, cwd=tmp_path).stdout
