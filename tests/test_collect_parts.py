"""collect must keep every note in a pretty-printed reply block, including the first and last one."""
import json

import chat_notes


def note(cue):
    return {"cue": cue, "match": f"line {cue}", "category": "Trivia", "text": f"Note on line {cue}.", "confidence": "high"}


def test_part_headers_do_not_eat_json_braces():
    block = json.dumps([note(5), note(9), note(12)], indent=2)     # multi-line, like the note-writer's replies
    text = f"PART 1 OF 2\n{block}\n\nPART 2 OF 2\n{block}\n"
    heads = list(chat_notes.PART_HEAD_RE.finditer(text))
    assert [h.group(1) for h in heads] == ["1", "2"]
    for h, nxt in zip(heads, heads[1:] + [None]):
        seg = text[h.end(): nxt.start() if nxt else len(text)]
        assert [o["cue"] for o in chat_notes.objects(seg)] == [5, 9, 12]


def test_plain_and_marked_headers_still_match():
    text = "PART 3 OF 6\n=== PART 4 OF 6 ===\n**PART 5 OF 6**\n"
    assert [h.group(1) for h in chat_notes.PART_HEAD_RE.finditer(text)] == ["3", "4", "5"]


def test_collect_reports_repeated_explanations(tmp_path):
    from conftest import make_srt, run_cli
    srt = make_srt(tmp_path / "ep.srt", n=6)
    replies = tmp_path / "replies.txt"
    same = "Calling a cab is British slang for taking a taxi, so the joke is about the cost."
    replies.write_text("PART 1 OF 1\n" + json.dumps([
        {"cue": 2, "match": "Line 2 of the original", "category": "Idiom", "text": same, "confidence": "high"},
        {"cue": 4, "match": "Line 4 of the original", "category": "Idiom", "text": same, "confidence": "high"},
    ], indent=2) + "\n", encoding="utf-8")
    r = run_cli("chat_notes.py", "collect", tmp_path / "film.mp4", srt, replies, "--year", "1983",
                "--out", tmp_path / "notes.json", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "1 repeated explanation(s) will be left out" in r.stdout
    assert "#2" in r.stdout
