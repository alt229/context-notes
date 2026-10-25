"""cli_common.py: the shared flags are registered the same way everywhere, and forwarding them round-trips."""
import argparse

import pytest
from conftest import run_cli

import cli_common
import context_notes


def full_parser():
    ap = argparse.ArgumentParser()
    cli_common.add_film_args(ap)
    cli_common.add_claude_args(ap)
    cli_common.add_limit_arg(ap)
    cli_common.add_yes_arg(ap)
    cli_common.add_frames_arg(ap)
    cli_common.add_speech_model_arg(ap, flag="--align-model", purpose="re-timing")
    return ap


ALL_FLAGS = ["--film-language", "fr", "--original-subs", "film.fr.srt", "--title", "Le Film", "--year", "1974",
             "--audience", "friends", "--notes-language", "Spanish", "--model", "claude-opus-5-5", "--effort", "high",
             "--api-url", "http://127.0.0.1:1/v1/messages", "--api-key-file", "/k", "--limit", "5:00", "--yes",
             "--frames", "dense", "--align-model", "small"]


def test_adders_register_the_flags_with_their_types_and_defaults():
    ap = full_parser()
    a = ap.parse_args([])
    assert a.notes_language == "English" and a.frames == "keyframes" and a.yes is False
    assert a.film_language is None and a.model is None and a.effort is None and a.limit is None
    a = ap.parse_args(ALL_FLAGS)
    assert a.film_language == "fr" and a.original_subs == "film.fr.srt" and a.title == "Le Film" and a.year == "1974"
    assert a.audience == "friends" and a.notes_language == "Spanish" and a.model == "claude-opus-5-5"
    assert a.effort == "high" and a.api_url.startswith("http://127.0.0.1") and a.api_key_file == "/k"
    assert a.limit == 300.0 and a.yes is True and a.frames == "dense" and a.align_model == "small"
    with pytest.raises(SystemExit):
        ap.parse_args(["--effort", "enormous"])
    with pytest.raises(SystemExit):
        ap.parse_args(["--limit", "soon"])


def test_only_and_help_overrides():
    ap = argparse.ArgumentParser()
    cli_common.add_film_args(ap, only=("film_language", "original_subs"), film_language="SPOKEN HERE",
                             notes_language_default=None)
    text = ap.format_help()
    assert "SPOKEN HERE" in text and "--original-subs SRT" in text and "--title" not in text
    assert not hasattr(ap.parse_args([]), "title")
    with pytest.raises(TypeError):
        cli_common.add_film_args(argparse.ArgumentParser(), year_of_release="x")
    ap = argparse.ArgumentParser()
    cli_common.add_film_args(ap, only=("notes_language",), notes_language_default=None)
    assert ap.parse_args([]).notes_language is None
    ap = argparse.ArgumentParser()
    cli_common.add_claude_args(ap, show_key_file=False)
    assert "--api-key-file" not in ap.format_help() and ap.parse_args(["--api-key-file", "k"]).api_key_file == "k"


def test_forwarding_round_trips_the_values():
    ap = full_parser()
    a = ap.parse_args(ALL_FLAGS)
    forwarded = (cli_common.film_args_from(a) + cli_common.claude_args_from(a) + cli_common.limit_args_from(a)
                 + cli_common.yes_args_from(a))
    b = ap.parse_args(forwarded)
    for dest in ("film_language", "original_subs", "title", "year", "audience", "notes_language", "model", "effort",
                 "api_url", "api_key_file", "limit", "yes"):
        assert getattr(b, dest) == getattr(a, dest), dest
    # flags that weren't given aren't passed on, and `only` narrows the list
    empty = ap.parse_args([])
    assert cli_common.film_args_from(empty) == ["--notes-language", "English"]
    assert cli_common.claude_args_from(empty) == [] and cli_common.limit_args_from(empty) == []
    assert cli_common.yes_args_from(empty) == []
    assert cli_common.film_args_from(a, only=("audience", "notes_language")) == ["--audience", "friends",
                                                                                "--notes-language", "Spanish"]
    assert cli_common.limit_args_from(argparse.Namespace(limit=90.0)) == ["--limit", "90"]
    assert cli_common.claude_args_from(argparse.Namespace()) == []            # an opts object without the fields


def test_context_notes_passes_its_api_flags_to_make_ass():
    opts = argparse.Namespace(model="claude-opus-5-5", effort="high", api_url=None, api_key_file="/k",
                              audience=None, notes_language=None, yes=True)
    assert context_notes.common_api_args(opts) == ["--model", "claude-opus-5-5", "--effort", "high",
                                                   "--api-key-file", "/k", "--yes"]
    opts = argparse.Namespace(model=None, effort=None, api_url=None, api_key_file=None, audience="kids",
                              notes_language="German", yes=False, limit=300.0)
    assert context_notes.common_api_args(opts) == ["--audience", "kids", "--notes-language", "German"]
    assert context_notes.limit_args(opts) == ["--limit", "300"]


SCRIPT_FLAGS = {
    "make_ass.py": ["--limit TIME", "--film-language LANG", "--original-subs SRT", "--title TITLE", "--year YEAR",
                    "--audience AUDIENCE", "--notes-language NOTES_LANGUAGE", "--model MODEL", "--effort",
                    "--api-key-file API_KEY_FILE", "--yes", "--frames {keyframes,dense}"],
    "context_notes.py": ["--limit TIME", "--film-language LANG", "--title TITLE", "--audience AUDIENCE",
                         "--notes-language NOTES_LANGUAGE", "--model MODEL", "--effort", "--yes",
                         "--frames {keyframes,dense}", "--align-model ALIGN_MODEL", "--show SHOW"],
    "analyze.py": ["--model MODEL", "--limit TIME", "--film-language LANG", "--frames {keyframes,dense,none}"],
    "find_subs.py": ["--model MODEL", "--limit TIME"],
    "align_check.py": ["--film-language LANG", "--original-subs SRT", "--model MODEL", "--limit TIME"],
}


@pytest.mark.parametrize("script", sorted(SCRIPT_FLAGS))
def test_each_script_lists_its_shared_flags_in_help(script, tmp_path):
    r = run_cli(script, "--help", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    text = " ".join(r.stdout.split())
    for flag in SCRIPT_FLAGS[script]:
        assert flag in text, f"{script} --help lacks {flag}"
    assert "--api-url" not in text                                       # hidden everywhere


def test_chat_notes_prepare_and_collect_take_the_film_flags(tmp_path):
    for sub in ("prepare", "collect"):
        text = " ".join(run_cli("chat_notes.py", sub, "--help", cwd=tmp_path).stdout.split())
        for flag in ("--film-language LANG", "--original-subs SRT", "--title TITLE", "--year YEAR",
                     "--audience AUDIENCE", "--notes-language NOTES_LANGUAGE", "--limit TIME"):
            assert flag in text, f"chat_notes.py {sub} --help lacks {flag}"
