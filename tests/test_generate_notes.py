import getpass
import json
import os
import re

import pytest
from conftest import WINDOWS, assert_private, make_srt, message, run_cli

import generate_notes as gn
import make_ass


# ---------------------------------------------------------------- reading replies
def test_extract_objects_tolerates_fences_chatter_and_truncation():
    text = 'Sure!\n```json\n[{"a": 1}, {"b": "x, y"}, {"c": [1, 2]}, {"d": "cut off'
    assert gn.extract_objects(text) == [{"a": 1}, {"b": "x, y"}, {"c": [1, 2]}]
    assert gn.extract_objects("no json here") == []
    assert gn.extract_objects("[]") == []


# ---------------------------------------------------------------- checking notes against the subtitles
CUES = [{"n": i + 1, "start": float(i), "end": i + 0.9, "text": t} for i, t in enumerate([
    "Come in.", "I tell you what. I'd actually\nrecommend my good friend Roy there",
    "as the go-to guy on anything\nwith more than seven eyes.", "He's on a call.", "Come in."])]


def check(**raw):
    return gn.check_note({"category": "X", "text": "t", **raw}, CUES, 1, 5)


def test_check_note_exact_quote():
    note, why = check(cue=3, match="more than seven eyes")
    assert why is None and note["match"] == "more than seven eyes" and "cue" not in note


def test_check_note_moves_to_the_line_that_has_the_quote():
    """Models are often a line out; the quote wins (this was a real bug in the first version)."""
    for stated in (2, 4):
        note, why = check(cue=stated, match="more than seven eyes")
        assert note["match"] == "more than seven eyes" and "found in line 3" in why


def test_check_note_repeated_phrase_gets_an_occurrence_number():
    note, _ = check(cue=5, match="Come in")
    assert note["occurrence"] == 2
    note, _ = check(cue=1, match="Come in")
    assert note["occurrence"] == 1


def test_check_note_falls_back_to_the_line_number():
    note, why = check(cue=4, match="words from nowhere")
    assert note["cue"] == 4 and "match" not in note and "anchored" in why
    note, why = check(cue=4)
    assert note["cue"] == 4 and "anchored" in why


def test_check_note_rejects_bad_input():
    assert check(cue=99, match="x")[0] is None                      # outside the lines being annotated
    assert gn.check_note({"text": "no cue"}, CUES, 1, 5)[0] is None
    assert check(cue=1, text="  ")[0] is None
    assert check(cue=1, confidence="certain")[0]["confidence"] == "medium"


def test_chunks_respect_the_size_budget(monkeypatch):
    cues = make_ass_cues(100)
    monkeypatch.setattr(gn, "CHUNK_CHARS", 500)
    parts = gn.chunks(cues)
    assert len(parts) > 3 and sum(len(p) for p in parts) == 100
    assert [c["n"] for p in parts for c in p] == list(range(1, 101))


def make_ass_cues(n):
    return [{"n": i + 1, "start": float(i), "end": i + 0.5, "text": f"Line number {i + 1} of the script"} for i in range(n)]


def test_cost_uses_the_price_table():
    assert gn.cost("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
    assert gn.cost("some-future-model", 1, 1) is None


# ---------------------------------------------------------------- API key storage
def test_set_key_writes_a_private_file(home, monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "  sk-ant-abc123456  ")
    gn.set_key()
    path = home / ".config" / "context-notes" / "api-key"
    assert path.read_text() == "sk-ant-abc123456\n"
    assert_private(path)
    assert_private(path.parent, 0o700)
    assert gn.load_key() == "sk-ant-abc123456"


def test_set_key_rejects_things_that_are_not_keys(home, monkeypatch):
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "hunter2")
    with pytest.raises(SystemExit):
        gn.set_key()
    assert not (home / ".config" / "context-notes" / "api-key").exists()


@pytest.mark.skipif(WINDOWS, reason="Windows keeps the key private through your user folder, not mode bits")
def test_load_key_refuses_a_world_readable_file(api_key_file):
    api_key_file.chmod(0o644)
    with pytest.raises(SystemExit) as e:
        gn.load_key()
    assert "chmod 600" in str(e.value)


def test_load_key_order_file_then_environment(home, monkeypatch):
    with pytest.raises(SystemExit) as e:
        gn.load_key()
    assert "--set-api-key" in str(e.value)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    assert gn.load_key() == "sk-ant-from-env"
    explicit = home / "mykey"
    explicit.write_text("sk-ant-explicit\n")
    explicit.chmod(0o600)
    assert gn.load_key(str(explicit)) == "sk-ant-explicit"


def test_xdg_config_home_is_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert gn.key_path() == tmp_path / "xdg" / "context-notes" / "api-key"


# ---------------------------------------------------------------- talking to the API
def test_call_api_sends_the_documented_request(api):
    api.responder = lambda n, body, headers: (200, message("hello"))
    reply = gn.call_api("sk-ant-k", "model-x", "SYSTEM", "USER", api.url, max_tokens=123)
    assert reply["content"][0]["text"] == "hello"
    call = api.calls[0]
    assert call["headers"]["x-api-key"] == "sk-ant-k" and call["headers"]["anthropic-version"] == "2023-06-01"
    assert call["body"] == {"model": "model-x", "max_tokens": 123, "system": "SYSTEM",
                            "messages": [{"role": "user", "content": "USER"}]}


def test_call_api_retries_when_busy_and_gives_clear_errors(api, monkeypatch):
    monkeypatch.setattr(gn.time, "sleep", lambda s: None)
    api.responder = lambda n, body, h: (529, {"error": {"message": "Overloaded"}}, {"retry-after": "1"}) if n == 1 \
        else (200, message("ok"))
    assert gn.call_api("k", "m", "s", "u", api.url)["content"][0]["text"] == "ok" and len(api.calls) == 2
    api.responder = lambda n, body, h: (401, {"error": {"message": "invalid x-api-key"}})
    with pytest.raises(SystemExit) as e:
        gn.call_api("k", "m", "s", "u", api.url)
    assert "rejected the key" in str(e.value)
    api.responder = lambda n, body, h: (400, {"error": {"message": "Your credit balance is too low"}})
    with pytest.raises(SystemExit) as e:
        gn.call_api("k", "m", "s", "u", api.url)
    assert "credit balance is too low" in str(e.value)


# ---------------------------------------------------------------- generating notes
def notes_for_each_part(n, body, headers):
    user = body["messages"][0]["content"]
    lo = int(re.search(r"Lines to annotate \((\d+) to", user).group(1))
    lines = dict(re.findall(r"^(\d+) \[[\d:]+\] (.*)$", user, re.M))
    words = lines[str(lo + 1)].split()
    notes = [{"cue": lo + 1, "match": " ".join(words[:3]), "category": "Idiom", "text": f"Note {n}", "confidence": "high"},
             {"cue": lo + 2, "match": "words that are not on that line", "category": "Trivia", "text": "Anchored",
              "confidence": "low"},
             {"cue": 9999, "match": "x", "category": "Trivia", "text": "Out of range"}]
    return 200, message("```json\n" + json.dumps(notes) + "\n```", usage=(2000, 300))


def test_generate_writes_a_notes_file_and_reports_problems(tmp_path, api, api_key_file, monkeypatch, capsys):
    monkeypatch.setattr(gn, "CHUNK_CHARS", 400)
    srt = make_srt(tmp_path / "ep.srt", n=30)
    api.responder = notes_for_each_part
    out = tmp_path / "notes.json"
    spec = gn.generate(srt, out, title="Test Show - S01E01", assume_yes=True, api_url=api.url)
    assert len(api.calls) > 2
    saved = json.loads(out.read_text())
    assert saved == spec and saved["generated_by"] == "claude-sonnet-5-5"
    intro, *notes = saved["notes"]
    assert intro["category"] == "About these notes" and intro["at"] == "00:00:03,000"
    assert any("match" in n for n in notes) and any("cue" in n for n in notes)
    assert all(n["kind"] == "speech" for n in notes)
    assert "Test Show - S01E01" in api.calls[0]["body"]["messages"][0]["content"]
    printed = capsys.readouterr().out
    assert "outside the lines being annotated" in printed and "Used" in printed
    # every note must be placeable in the subtitles
    placed, missing = make_ass.place_notes(make_ass.parse_srt(srt), saved["notes"], 0)
    assert not missing and len(placed) == len(saved["notes"])


def test_generate_passes_earlier_topics_to_later_requests(tmp_path, api, api_key_file, monkeypatch):
    monkeypatch.setattr(gn, "CHUNK_CHARS", 400)
    api.responder = notes_for_each_part
    gn.generate(make_srt(tmp_path / "ep.srt", n=30), tmp_path / "n.json", assume_yes=True, api_url=api.url)
    first, second = (c["body"]["messages"][0]["content"] for c in api.calls[:2])
    assert "already covered" not in first and "already covered" in second
    assert "[context]" in second


def test_generate_saves_partial_progress_when_the_api_fails(tmp_path, api, api_key_file, monkeypatch):
    monkeypatch.setattr(gn, "CHUNK_CHARS", 400)
    good = notes_for_each_part
    api.responder = lambda n, body, h: (good(n, body, h) if n < 2
                                        else (400, {"error": {"message": "credit balance is too low"}}))
    with pytest.raises(SystemExit):
        gn.generate(make_srt(tmp_path / "ep.srt", n=30), tmp_path / "n.json", assume_yes=True, api_url=api.url)
    assert json.loads((tmp_path / "n.partial.json").read_text())["notes"]
    assert not (tmp_path / "n.json").exists()


def test_generate_needs_confirmation_unless_yes(tmp_path, api, api_key_file):
    srt = make_srt(tmp_path / "ep.srt", n=3)
    with pytest.raises(SystemExit) as e:
        gn.generate(srt, tmp_path / "n.json", api_url=api.url)       # stdin is not a terminal under pytest
    assert "--yes" in str(e.value) and not api.calls


def test_cli_generate_then_build(tmp_path, api, home):
    key = home / ".config" / "context-notes" / "api-key"
    key.parent.mkdir(parents=True)
    key.write_text("sk-ant-test\n")
    os.chmod(key, 0o600)
    api.responder = notes_for_each_part
    srt = make_srt(tmp_path / "ep.srt", n=8)
    r = run_cli("make_ass.py", srt, "--generate", "--yes", "--api-url", api.url, cwd=tmp_path, home_dir=home)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "notes-ep.json").exists() and (tmp_path / "ep.ass").exists()
    assert api.calls[0]["headers"]["x-api-key"] == "sk-ant-test"


@pytest.mark.skipif(WINDOWS, reason="on Windows a hidden prompt reads the keyboard, never stdin")
def test_cli_set_api_key_reads_from_stdin(tmp_path, home):
    r = run_cli("make_ass.py", "--set-api-key", cwd=tmp_path, home_dir=home, stdin="sk-ant-xyz-9876\n")
    assert r.returncode == 0 and "9876" in r.stdout and "sk-ant-xyz" not in r.stdout
    assert (home / ".config" / "context-notes" / "api-key").read_text() == "sk-ant-xyz-9876\n"
