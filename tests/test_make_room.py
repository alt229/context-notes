"""A fourth note waits for room (the earliest note's timer shortens by half a second a second), up to 4 s."""
import pytest

import make_ass


def note(start, own, fixed=False):
    return {"start": start, "end": start + own, "fixed_duration": fixed}


def test_three_notes_on_screen_keep_their_times():
    placed = [note(0, 10), note(1, 10), note(2, 10)]
    make_ass.make_room(placed, 6.0)
    assert [p["start"] for p in placed] == [0, 1, 2]
    assert all("waited" not in p for p in placed)
    assert placed[1]["end"] == 1 + 10 + 5                    # linger: half of note 0's 10 s
    assert placed[2]["end"] == 2 + 10 + 5 + 5                # half of notes 0 and 1


def test_fourth_note_waits_and_shortens_the_earliest_note():
    placed = [note(0, 10), note(1, 10), note(2, 10), note(6, 10)]
    make_ass.make_room(placed, 6.0)
    wait = (10 - 6) / 1.5                                  # 2.67 s: the earliest note ends at 6 + wait
    assert placed[3]["waited"] == pytest.approx(wait)
    assert placed[3]["start"] == pytest.approx(6 + wait)
    assert placed[0]["end"] == pytest.approx(6 + wait)     # 10 - 0.5 * wait
    assert placed[0]["cut"] == pytest.approx(0.5 * wait)


def test_wait_longer_than_four_seconds_shows_at_its_own_time():
    placed = [note(0, 24), note(0, 24), note(0, 24), note(1, 10)]
    make_ass.make_room(placed, 6.0)                        # 23 / 1.5 = 15.3 s is too long
    assert placed[3]["start"] == 1
    assert "waited" not in placed[3]
    assert placed[0]["end"] == 24


def test_earlier_note_keeps_its_six_second_floor():
    placed = [note(0, 6), note(0, 20), note(0, 20), note(5, 10)]
    make_ass.make_room(placed, 6.0)                        # the first note would drop to 5.67 s
    assert placed[3]["start"] == 5
    assert placed[0]["end"] == 6


def test_a_note_with_its_own_duration_is_not_shortened():
    placed = [note(0, 10, fixed=True), note(0, 20), note(0, 20), note(5, 10)]
    make_ass.make_room(placed, 6.0)
    assert placed[3]["start"] == 5
    assert placed[0]["end"] == 10


def test_only_a_fourth_note_waits():
    placed = [note(0, 10), note(1, 10), note(12, 10)]      # never more than two on screen
    make_ass.make_room(placed, 6.0)
    assert [p["start"] for p in placed] == [0, 1, 12]


def test_linger_then_uses_the_shortened_timer():
    placed = [note(0, 10), note(1, 10), note(2, 10), note(6, 10)]
    make_ass.make_room(placed, 6.0)
    start = placed[3]["start"]                              # 6 + 8/3 s
    # The held note's linger: half of note 1's 10 s and note 2's 10 s = 5 + 5. The first note ends at the
    # held note's start, so it adds nothing. Total 10 + 10 = 20 s on screen.
    assert placed[3]["end"] == pytest.approx(start + 20)
