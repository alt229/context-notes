"""settings.py: this install's defaults, read by the app and by the terminal scripts."""
import json

import pytest
from conftest import make_srt, run_cli
from test_generate_notes import notes_for_each_part

import generate_notes
import make_ass
import settings


def test_no_file_means_the_built_in_defaults(usage_dir):
    assert settings.effective() == settings.BUILT_IN
    assert settings.warnings() == []


def test_saved_defaults_come_back(usage_dir):
    settings.save({"quality": "cheaper", "audience": "Fluent in American English", "seconds_per_word": 0.5})
    s = settings.effective()
    assert s["quality"] == "cheaper" and s["seconds_per_word"] == 0.5
    assert s["effort"] == ""                                       # the ones not saved keep the built-in value


def test_a_wrong_value_changes_nothing(usage_dir):
    settings.save({"quality": "best"})
    with pytest.raises(ValueError):
        settings.save({"quality": "turbo", "note_opacity": 30})    # all or nothing
    assert settings.effective()["quality"] == "best"
    for bad in ({"note_opacity": 150}, {"notes_language": "two\nlines"}, {"offline": "yes"},
                {"seconds_per_word": 5}, {"note_background": "neon"}):
        with pytest.raises(ValueError):
            settings.save(bad)


def test_destructive_choices_can_never_be_defaults(usage_dir):
    for key in ("redo", "convert", "delete_backups", "tidy_move", "embed", "show_subs"):
        with pytest.raises(ValueError):
            settings.save({key: True})


def test_a_damaged_file_falls_back_and_says_so(usage_dir):
    settings.path().parent.mkdir(parents=True, exist_ok=True)
    settings.path().write_text("{not json", encoding="utf-8")
    assert settings.effective() == settings.BUILT_IN
    assert "couldn't be read" in settings.warnings()[0]
    settings.path().write_text(json.dumps({"quality": "turbo", "offline": True, "old_thing": 1}), encoding="utf-8")
    s = settings.effective()
    assert s["quality"] == "best" and s["offline"] is True          # the bad value falls back, the good one stays
    assert len(settings.warnings()) == 2


def test_reset_goes_back_to_the_built_in_defaults(usage_dir):
    settings.save({"offline": True})
    assert settings.reset() == settings.BUILT_IN
    assert not settings.path().exists()


def test_terminal_defaults_follow_the_settings(usage_dir):
    assert settings.cli_defaults()["model"] == "claude-opus-5-5"   # built-in: "best"
    settings.save({"quality": "cheaper"})
    d = settings.cli_defaults()
    assert d["model"] == "claude-sonnet-5-5" and d["effort"] == "high"
    settings.save({"audience": "Fluent in American English", "frames": "dense", "recursive": True})
    d = settings.cli_defaults()
    assert d["audience"] == "Fluent in American English" and d["frames"] == "dense" and d["recursive"] is True
    # the look is read from look_defaults by make_ass, never sent on every run (that would overwrite saved looks)
    assert "note_background" not in d and "reading_speed" not in d and "show_subs" not in d


def test_look_and_audience_defaults_reach_the_builders(usage_dir):
    settings.save({"note_background": "dark", "note_opacity": 50, "seconds_per_word": 0.5,
                   "audience": "Native English speaker"})
    assert settings.look_defaults() == {"background": "dark", "opacity": 50, "wpm": 120.0}
    assert generate_notes.default_audience("en") == "Native English speaker"
    assert generate_notes.default_audience("ja") == "Native English speaker"


def test_auto_send_is_on_by_default_and_can_be_turned_off(usage_dir):
    assert settings.BUILT_IN["autosend"] is True
    assert "autosend_ack" not in settings.BUILT_IN
    assert settings.save({"autosend": False})["autosend"] is False


def test_the_background_choices_match_make_ass():
    assert set(settings.BACKGROUNDS) == set(make_ass.BACKGROUNDS)


def test_make_ass_by_hand_takes_the_model_and_effort_from_settings(tmp_path, api, api_key_file, home):
    """Typed in Terminal with no --model or --effort, make_ass.py uses Settings (Opus, high), as the app does; the
    flags still win, and the effort is left out for Haiku 4.5, which rejects it."""
    srt = make_srt(tmp_path / "ep.srt", n=6)
    api.responder = notes_for_each_part
    for extra, model, effort in (((), "claude-opus-5-5", "high"),
                                 (("--model", "claude-sonnet-5-5", "--effort", "low"), "claude-sonnet-5-5", "low"),
                                 (("--model", "claude-haiku-4-5-20251001"), "claude-haiku-4-5-20251001", None)):
        api.calls.clear()
        r = run_cli("make_ass.py", srt, "--generate", "--yes", "--force", "--api-url", api.url, *extra, cwd=tmp_path,
                    home_dir=home)
        assert r.returncode == 0, r.stdout + r.stderr
        body = api.calls[0]["body"]
        assert body["model"] == model
        assert (body.get("output_config") or {}).get("effort") == effort


def test_always_download_subtitles_answers_the_question_itself(tmp_path, monkeypatch, usage_dir):
    """Settings' "Always download subtitles" (--download-subs): the subs.download question isn't asked; without it,
    it is. Speech recognition is still only by asking."""
    import types

    import context_notes as cn
    import prompts
    asked = []
    monkeypatch.setattr(prompts, "interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda q: asked.append(q) or "n")

    class Finder:
        def __init__(self):
            self.answers = []

        def find(self, video, lang, online=None, transcribe=None, ask=None, model=None, limit=None):
            self.answers.append(ask("OpenSubtitles.com has English subtitles for ep.mp4: x. Download them?"))
            return None

    video = tmp_path / "ep.mp4"
    for always, answer, was_asked in ((True, "y", False), (False, "n", True)):
        asked.clear()
        f = Finder()
        opts = types.SimpleNamespace(yes=False, offline=False, align_model=None, limit=None, download_subs=always)
        cn._look_further(video, "en", opts, f)
        assert f.answers == [answer] and bool(asked) is was_asked
    assert settings.BUILT_IN["download_subs"] is False
    settings.save({"download_subs": True})
    assert settings.cli_defaults()["download_subs"] is True


def test_yes_to_all_reaches_the_run_and_the_steps_it_starts(tmp_path, usage_dir):
    """Settings' "Yes to all questions" (or --yes-to-all) turns it on for the run: CONTEXT_NOTES_YES_TO_ALL, which
    every step the run starts inherits."""
    import os

    import context_notes as cn
    import prompts
    missing = str(tmp_path / "missing.mp4")
    for saved, flags, on in ((False, [], False), (False, ["--yes-to-all"], True), (True, [], True)):
        os.environ[prompts.YES_ENV] = ""
        settings.save({"yes_to_all": saved})
        assert settings.cli_defaults()["yes_to_all"] is saved
        with pytest.raises(SystemExit):
            cn.main([missing, *flags])
        assert prompts.yes_to_all() is on
    assert settings.BUILT_IN["yes_to_all"] is False


def test_yes_to_all_checks_the_timing_even_with_nobody_there(tmp_path, monkeypatch, usage_dir):
    """With no terminal the alignment question was skipped (only a hint); Yes to all answers it, so the check runs."""
    import types

    import context_notes as cn
    import prompts
    monkeypatch.setattr(prompts, "interactive", lambda: False)
    ran = []
    monkeypatch.setattr(cn, "run", lambda cmd, cwd=None: ran.append(cmd) or 1)
    video, srt, notes = tmp_path / "ep.mp4", tmp_path / "ep.srt", tmp_path / "ep.notes.json"
    for f in (video, srt, notes):
        f.write_text("x")
    opts = types.SimpleNamespace(no_alignment_check=False, check_alignment=False, yes=False, window=10.0, limit=None,
                                 align_model=None)
    assert cn.alignment_step(video, srt, notes, "en", "en", None, opts) == srt and not ran
    prompts.turn_on_yes_to_all()
    assert cn.alignment_step(video, srt, notes, "en", "en", None, opts) == srt
    assert len(ran) == 1 and "align_check.py" in str(ran[0][1])
