"""scan_ass.py reads built notes and applies today's rules to their start times, without changing the file."""
import pytest

import scan_ass


def write_ass(path, events):
    lines = ["[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for start, end, style, name, text in events:
        lines.append(f"Dialogue: 1,{start},{end},{style},{name},0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_reads_note_events_and_their_category(tmp_path):
    f = tmp_path / "film.notes.ass"
    write_ass(f, [
        ("0:00:01.00", "0:00:09.00", "Dialogue", "dialogue", r"Hello"),
        ("0:00:10.00", "0:00:20.00", "NoteL", "speech/idiom/high", r"{\fs26}IDIOM{\b0}\NA note here"),
    ])
    notes = scan_ass.read_notes(f)
    assert len(notes) == 1
    assert notes[0]["category"] == "idiom"
    assert notes[0]["text"] == "IDIOM A note here"
    assert notes[0]["start"] == 10 and notes[0]["end"] == 20


def test_four_notes_at_once_are_counted(tmp_path):
    windows = [(0, 10), (1, 10), (2, 10), (3, 10)]
    seconds, most = scan_ass.four_plus(windows)
    assert most == 4
    assert seconds == pytest.approx(7.0, abs=0.2)                   # 3 s to 10 s, while all four are up


def test_projection_applies_the_three_note_limit(tmp_path):
    notes = [{"start": 0.0, "text": "a b c d e f g h i j"}, {"start": 1.0, "text": "a b"},
             {"start": 2.0, "text": "a b"}, {"start": 5.0, "text": "a b"}]
    before, after, held = scan_ass.projection(notes)
    assert before[1] >= 4
    assert after[1] <= 3
    assert held
