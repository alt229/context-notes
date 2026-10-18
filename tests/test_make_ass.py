import json

import pytest
from conftest import make_srt, run_cli

import make_ass


# ---------------------------------------------------------------- reading subtitles
def test_parse_srt_handles_bom_crlf_missing_index_and_dot_milliseconds(tmp_path):
    raw = "﻿1\r\n00:00:01,000 --> 00:00:02,500\r\nHello\r\n\r\n00:00:03.250 --> 00:00:04.000\r\nNo index here\r\n"
    p = tmp_path / "a.srt"
    p.write_bytes(raw.encode("utf-8"))
    cues = make_ass.parse_srt(p)
    assert [c["text"] for c in cues] == ["Hello", "No index here"]
    assert cues[0]["start"] == 1.0 and cues[0]["end"] == 2.5
    assert cues[1]["start"] == 3.25
    assert [c["n"] for c in cues] == [1, 2]


def test_read_text_falls_back_to_cp1252(tmp_path):
    p = tmp_path / "a.srt"
    p.write_bytes("1\n00:00:01,000 --> 00:00:02,000\ncafé \u201cquoted\u201d\n".encode("cp1252"))
    assert make_ass.parse_srt(p)[0]["text"] == "café \u201cquoted\u201d"


# ---------------------------------------------------------------- matching quotes to lines
CUES = [{"n": i + 1, "start": float(i), "end": i + 0.9, "text": t} for i, t in enumerate([
    "Come in.", "<i>I tell you what.</i> I'd actually\nrecommend my good friend", "as the go-to guy on anything",
    "Come in.", "It's Roy’s idea"])]


def test_norm_strips_tags_case_punctuation_and_curly_quotes():
    assert make_ass.norm("<i>It’s</i> ROY!") == "it's roy"


def test_find_cue_basic_spanning_and_occurrence():
    assert make_ass.find_cue(CUES, "go-to guy", 0) == 2
    assert make_ass.find_cue(CUES, "good friend as the go-to", 0) == 1          # quote spans two cues
    assert make_ass.find_cue(CUES, "Come in", 0, occurrence=2) == 3
    assert make_ass.find_cue(CUES, "no such words", 0) is None


def test_find_cue_prefers_hits_after_the_previous_note():
    assert make_ass.find_cue(CUES, "come in", 1) == 3
    assert make_ass.find_cue(CUES, "come in", 0) == 0


# ---------------------------------------------------------------- placing notes
def test_place_notes_timing_rules():
    notes = [
        {"match": "go-to guy", "text": "ends-after", "category": "Idiom"},
        {"match": "go-to guy", "text": "starts-with", "when": "start", "delay": 1.5},
        {"cue": 5, "text": "by number"},
        {"at": "00:00:10,000", "text": "subtitle clock"},
        {"at_video": "00:00:20,000", "text": "video clock", "kind": "visual", "duration": 4},
        {"match": "words that are not there", "text": "lost"},
    ]
    placed, missing = make_ass.place_notes(CUES, notes, offset=2.0)
    by_text = {p["text"]: p for p in placed}
    assert by_text["ends-after"]["start"] == pytest.approx(2 + 2.9 + 0.2)       # end of line + offset + 0.2
    assert by_text["starts-with"]["start"] == pytest.approx(2 + 2.0 + 1.5)      # start + offset + delay
    assert by_text["by number"]["start"] == pytest.approx(4.9 + 2.0 + 0.2)
    assert by_text["subtitle clock"]["start"] == pytest.approx(12.0)             # offset applies
    assert by_text["video clock"]["start"] == pytest.approx(20.0)                # offset does not
    assert by_text["video clock"]["end"] == pytest.approx(24.0)
    assert by_text["video clock"]["kind"] == "visual"
    assert [k for k, _ in missing] == [6]


def test_confidence_and_default_category():
    placed, _ = make_ass.place_notes(CUES, [{"cue": 1, "text": "x", "confidence": "LOW"}], 0)
    assert placed[0]["confidence"] == "low" and placed[0]["category"] == "Note"


# ---------------------------------------------------------------- building the .ass
def test_build_applies_offset_and_tags_notes(tmp_path):
    srt = make_srt(tmp_path / "s.srt", n=4)
    notes = tmp_path / "n.json"
    notes.write_text(json.dumps({"title": "T", "notes": [
        {"match": "Line 2", "category": "Idiom", "text": "A note with {braces}", "confidence": "medium"},
        {"at_video": "00:00:20,000", "kind": "visual", "category": "Prop", "text": "A prop"}]}))
    out = tmp_path / "s.ass"
    placed, missing = make_ass.build(srt, notes, out, offset=0.88)
    assert len(placed) == 2 and not missing
    ass = out.read_text(encoding="utf-8-sig")
    assert "Dialogue: 0,0:00:03.88,0:00:06.38,Dialogue" in ass                    # 3.0 + 0.88
    assert ",speech/idiom/medium," in ass and ",visual/prop/high," in ass
    assert "(less sure)" in ass
    assert "{braces}" not in ass and "(braces)" in ass                            # override-block characters neutralised
    assert "Title: T" in ass


# ---------------------------------------------------------------- command line
def test_cli_creates_blank_notes_then_refuses_to_build_from_it(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    r = run_cli("make_ass.py", srt, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0 and "created a blank one" in r.stdout
    blank = tmp_path / "notes-ep.json"
    assert json.loads(blank.read_text())["notes"] == []
    r = run_cli("make_ass.py", srt, cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "no notes in it yet" in r.stderr


def test_cli_builds_with_notes_and_names_output_after_video(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"video_offset": -0.5, "notes": [{"cue": 1, "text": "hi"}]}))
    r = run_cli("make_ass.py", srt, notes, "--video", "Some Video.mp4", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stderr
    ass = (tmp_path / "Some Video.notes.ass").read_text(encoding="utf-8-sig")
    assert "Dialogue: 0,0:00:02.50," in ass                                          # video_offset from the notes file


def test_cli_writes_a_plex_copy_but_not_over_someone_elses_file(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"notes": [{"cue": 1, "text": "hi"}]}))
    r = run_cli("make_ass.py", srt, notes, "--video", "Ep.mp4", cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "Ep.en.ass").read_bytes() == (tmp_path / "Ep.notes.ass").read_bytes()
    theirs = tmp_path / "Other.en.ass"
    theirs.write_text("[Script Info]\nTitle: real subtitles\n")
    r = run_cli("make_ass.py", srt, notes, "--video", "Other.mp4", cwd=tmp_path, home_dir=home)
    assert "isn't one of ours" in r.stdout and theirs.read_text().endswith("real subtitles\n")
    run_cli("make_ass.py", srt, notes, "--video", "Third.mp4", "--no-plex-copy", cwd=tmp_path, home_dir=home)
    assert not (tmp_path / "Third.en.ass").exists()


def test_cli_generate_refuses_to_overwrite_existing_notes(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"notes": [{"cue": 1, "text": "mine"}]}))
    r = run_cli("make_ass.py", srt, notes, "--generate", "--yes", cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "already has 1 notes" in r.stderr
    assert json.loads(notes.read_text())["notes"][0]["text"] == "mine"


def test_cli_refine_needs_video(tmp_path, home):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"notes": [{"cue": 1, "text": "x"}]}))
    r = run_cli("make_ass.py", srt, notes, "--refine", cwd=tmp_path, home_dir=home)
    assert r.returncode == 1 and "--refine needs the video" in r.stderr


def test_build_can_show_other_subtitles_while_placing_notes_on_the_main_ones(tmp_path, home):
    fr = make_srt(tmp_path / "f.fr.srt", n=4, text="Réplique {i}")
    en = make_srt(tmp_path / "f.en.srt", n=4, first=3.2, text="English line {i}")
    notes = tmp_path / "n.json"
    notes.write_text(json.dumps({"video_offset": 0.5, "notes": [{"match": "Réplique 2", "text": "A note"}]}))
    r = run_cli("make_ass.py", fr, notes, "--video", "f.mp4", "--display-subs", en, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stderr
    ass = (tmp_path / "f.notes.ass").read_text(encoding="utf-8-sig")
    assert "Dialogue: 0,0:00:03.20," in ass and "English line 1" in ass and "Réplique" not in ass
    assert ",speech/note/high," in ass and "0:00:12.20" in ass          # note: end of French line 2 (11.5) + 0.5 + 0.2
    assert json.loads(notes.read_text())["display_subtitles"] == "f.en.srt"
    r = run_cli("make_ass.py", fr, notes, "--video", "f.mp4", cwd=tmp_path, home_dir=home)    # remembered
    assert "English line 1" in (tmp_path / "f.notes.ass").read_text(encoding="utf-8-sig")
