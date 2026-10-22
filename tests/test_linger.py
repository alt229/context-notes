"""A note that appears while earlier notes are still up stays longer: half of each earlier note's own time."""
import make_ass


def note(start, own, fixed=False):
    return {"start": start, "end": start + own, "fixed_duration": fixed}


def test_a_note_with_nothing_on_screen_keeps_its_own_time():
    placed = [note(0, 10), note(20, 10)]
    make_ass.linger(placed)
    assert [(p["start"], p["end"]) for p in placed] == [(0, 10), (20, 30)]


def test_third_note_gets_half_of_each_earlier_note_on_screen():
    placed = [note(0, 10), note(2, 10), note(4, 14)]    # all three overlap
    make_ass.linger(placed)
    assert placed[0]["end"] == 10                        # the first note keeps its own timer
    assert placed[1]["end"] == 2 + 10 + 5                # half of note 1's 10 s
    assert placed[2]["end"] == 4 + 14 + 5 + 5            # half of note 1 and of note 2: 24 s


def test_extension_can_pass_24_seconds_but_not_45():
    placed = [note(0, 24), note(1, 24), note(2, 24)]     # the third gets 12 + 12 = 24 s extra on its 24 s
    make_ass.linger(placed)
    assert placed[2]["end"] == 2 + make_ass.LINGER_CEILING
    assert placed[2]["end"] - placed[2]["start"] == 45.0


def test_only_notes_still_on_screen_count():
    placed = [note(0, 10), note(12, 10)]                 # note 1 is gone by the time note 2 appears
    make_ass.linger(placed)
    assert placed[1]["end"] == 22


def test_notes_with_their_own_duration_are_left_alone():
    placed = [note(0, 10), note(2, 10, fixed=True)]
    make_ass.linger(placed)
    assert placed[1]["end"] == 12
