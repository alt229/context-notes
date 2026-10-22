"""A note that would be the fourth on screen waits for room. While it waits, every note still on screen loses half a
second of timer per second of wait. Three notes on screen is the one hard limit."""
import pytest

import make_ass


def note(start, own, fixed=False):
    return {"start": start, "end": start + own, "fixed_duration": fixed}


def test_three_notes_on_screen_keep_their_times():
    placed = [note(0, 10), note(1, 10), note(2, 10)]
    make_ass.make_room(placed)
    assert [p["start"] for p in placed] == [0, 1, 2]
    assert all("waited" not in p for p in placed)
    assert placed[1]["end"] == 1 + 10 + 5                    # linger: half of note 0's 10 s
    assert placed[2]["end"] == 2 + 10 + 5 + 5                # half of notes 0 and 1


def test_fourth_note_waits_and_every_note_on_screen_gives_up_time():
    placed = [note(0, 10), note(1, 10), note(2, 10), note(6, 10)]
    make_ass.make_room(placed)
    wait = (10 - 6) / 1.5                                  # the earliest note ends at 6 + wait
    cut = 0.5 * wait
    assert placed[3]["waited"] == pytest.approx(wait)
    assert placed[3]["start"] == pytest.approx(6 + wait)
    assert placed[0]["end"] == pytest.approx(6 + wait)     # 10 - cut, ends exactly when the 4th note appears
    assert placed[1]["cut"] == pytest.approx(cut)
    assert placed[2]["cut"] == pytest.approx(cut)


def test_the_wait_is_not_capped_by_the_old_four_seconds():
    placed = [note(0, 24), note(0, 24), note(0, 24), note(1, 10)]
    make_ass.make_room(placed)
    assert placed[3]["waited"] == pytest.approx(23 / 1.5)  # about 15 s, and there are never four on screen
    on_at_start = [q for q in placed[:3] if q["end"] > placed[3]["start"]]
    assert len(on_at_start) == 2


def test_a_note_with_its_own_duration_is_not_shortened():
    placed = [note(0, 10, fixed=True), note(0, 20), note(0, 20), note(5, 10)]
    make_ass.make_room(placed)
    assert placed[0]["end"] == 10                          # the fixed note keeps its time
    assert placed[3]["start"] == pytest.approx(10)         # it waits for the fixed note to end
    assert "cut" not in placed[0]


def test_only_a_fourth_note_waits():
    placed = [note(0, 10), note(1, 10), note(12, 10)]      # never more than two on screen
    make_ass.make_room(placed)
    assert [p["start"] for p in placed] == [0, 1, 12]


def test_linger_uses_the_shortened_timers():
    placed = [note(0, 10), note(1, 10), note(2, 10), note(6, 10)]
    make_ass.make_room(placed)
    wait = 4 / 1.5
    cut = 0.5 * wait
    start = placed[3]["start"]                              # 6 + wait
    assert start == pytest.approx(6 + wait)
    # The held note's linger: half of the shortened timers of notes 1 and 2, which are still up when it starts.
    assert placed[3]["end"] == pytest.approx(start + 10 + 0.5 * (10 - cut) * 2)
