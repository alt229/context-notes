"""Damaged subtitles (subcheck.py, and tidy.py --check-subs): mangled characters, OCR mistakes, nothing changed."""
import subprocess
from types import SimpleNamespace

from conftest import needs_ffmpeg, run_cli

import context_notes as cn
import find_subs
import settings
import subcheck

# Doctor Who S05E08's built-in English track (2026-10-30): UTF-8 text read as Latin-1, from OCR that read every
# v as a Greek nu and left stray spaces.
DAMAGED = ["but you'Î½e got to keep at it, all rig ht?", "Now, who loÎ½es you more than me?",
           "HaÎ½e a g reat weekend !", "and I'Î½e d ressed for Rio.",
           "It's a g raÎ½eyard !", "Come to reliÎ½e past glories, I'd imag ine.",
           "No sig ns of it haÎ½ing been messed with.", "Body, coffin, eÎ½erything ."]
CLEAN = ["Well... I suppose so.", "I'm not going. I'll stay here, OK?", "It's a graveyard!",
         "The C.I.A. got you, Dutch.", "Plan B. Then plan C, then a cup of tea.", "Oh, I love a big mining thing."]


def srt(path, lines):
    path.write_text("".join(f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n{t}\n\n" for i, t in enumerate(lines, 1)),
                    encoding="utf-8")
    return path


def test_finds_what_the_dr_who_track_had():
    found = subcheck.problems("\n".join(DAMAGED * 3), "en")
    assert found["mangled"][0] == 24 and "Î½ (should be ν)" in found["mangled"][1]
    assert found["lookalike"][0] == 24 and "loνes" in found["lookalike"][1]       # counted after the repair
    # a lone letter or a space before a stop shows it ("g reat", "thing ."); "rig ht" alone would need a dictionary
    assert found["broken"][0] == 12


def test_clean_english_and_other_languages_pass():
    assert subcheck.problems("\n".join(CLEAN * 10), "en") == {}
    french = "Il était une fois à Montmartre.\nÇa va, Amélie ? « Oui. »\nL'été, c'est où ?\nJ'y vais.\n" * 10
    assert subcheck.problems(french, "fr") == {}
    croatian = "Ti si govnar s televizije.\nBrže! - Ni s njima\nIdemo k njemu, v redu?\n" * 10   # one-letter words
    assert subcheck.problems(croatian, None) == {}
    assert subcheck.problems("Ein Mann, ein Wort.\nСпасибо, товарищ.\n" * 10, None) == {}  # whole Cyrillic words


def test_small_l_for_capital_i_needs_more_than_one():
    one = "\n".join(CLEAN * 10 + ["Then l said no."])
    assert subcheck.problems(one, "en") == {}
    many = "\n".join(CLEAN + ["l told you to.", "Did l ask?", "l'm going in.", "l'll go.", "So l did."])
    assert subcheck.problems(many, "en")["l-for-I"][0] == 5


def test_other_mangling_and_unreadable_characters():
    found = subcheck.problems("CafÃ© au lait\nItâ€™s mine\nA � here\n", "en")
    assert found["mangled"][0] == 2 and "â€™ (should be ’)" in found["mangled"][1]
    assert found["unreadable"][0] == 1


def test_tidy_reports_damaged_subtitles_beside_a_video_and_changes_nothing(tmp_path):
    (tmp_path / "Show - s05e08.mkv").write_bytes(b"not really a video")
    bad = srt(tmp_path / "Show - s05e08.en.srt", DAMAGED)
    before = bad.read_bytes()
    (tmp_path / "Show - s05e09.mkv").write_bytes(b"not really a video")
    srt(tmp_path / "Show - s05e09.en.srt", CLEAN)
    r = run_cli("tidy.py", tmp_path, "--dry-run")                                  # on by default
    assert r.returncode == 0, r.stderr
    assert "Show - s05e08.mkv: Show - s05e08.en.srt" in r.stdout and "8 mangled characters" in r.stdout
    assert "s05e09" not in r.stdout and "Checked the subtitles beside 2 video(s): 1 with damage." in r.stdout
    assert bad.read_bytes() == before
    r = run_cli("tidy.py", tmp_path, "--dry-run", env_extra={"CONTEXT_NOTES_UI": "json"})
    assert '"type": "subs-check"' in r.stdout and '"where": "Show - s05e08.en.srt"' in r.stdout
    r = run_cli("tidy.py", tmp_path, "--dry-run", "--no-check-subs")
    assert "mangled" not in r.stdout and "Checked the subtitles" not in r.stdout


def test_tidy_and_a_run_take_the_settings(tmp_path):
    assert settings.cli_defaults()["subs_check"] is True and settings.cli_defaults()["replace_bad_subs"] is True
    settings.save({"check_subs": False, "replace_bad_subs": False})
    assert settings.cli_defaults()["subs_check"] is False and settings.cli_defaults()["replace_bad_subs"] is False
    (tmp_path / "Film.mkv").write_bytes(b"x")
    srt(tmp_path / "Film.en.srt", DAMAGED)
    r = run_cli("tidy.py", tmp_path, "--dry-run")
    assert "mangled" not in r.stdout, r.stdout


def test_mislabeled_or_corrupted():
    portuguese = ("A tripulação do Marten. Eles partem amanhã. Não vá errar o buraco! O que está havendo aqui? "
                  "Não esqueça, você e eu temos que ir para casa com isso, que é um bom dia para o mar.\n") * 5
    found = subcheck.problems(portuguese, "es")
    assert found["mislabeled"][1] == ["labeled Spanish, but reads as Portuguese"]
    assert "mislabeled" not in subcheck.problems(portuguese, "pt") and "mislabeled" not in subcheck.problems(portuguese)
    assert "mislabeled or corrupted" in subcheck.describe(found)[0]


# ---------------------------------------------------------------- a run: damaged subtitles are noticed and replaced
def opts(**kw):
    return SimpleNamespace(**{"offline": False, "replace_bad_subs": True, "subs_check": True, "limit": None, **kw})


def film_with_damaged_subs(tmp_path):
    video = tmp_path / "Show - s05e08.mkv"
    video.write_bytes(b"not really a video")
    return video, srt(tmp_path / "Show - s05e08.en.srt", DAMAGED)


def test_a_run_uses_a_clean_file_beside_it_instead(tmp_path, monkeypatch):
    video, bad = film_with_damaged_subs(tmp_path)
    clean = srt(tmp_path / "Show - s05e08.en.opensubtitles.srt", CLEAN)
    monkeypatch.setattr(find_subs, "os_load", lambda: (_ for _ in ()).throw(AssertionError("no download needed")))
    assert cn.get_subtitles(video, "en", opts()) == (clean, False)
    assert cn.get_subtitles(video, "en", opts(subs_check=False)) == (bad, False)


def test_a_run_downloads_a_clean_copy_once(tmp_path, monkeypatch):
    video, bad = film_with_damaged_subs(tmp_path)
    calls = []

    def search(v, lang, cfg, api=None, ask=None):
        calls.append(ask)
        return srt(tmp_path / "Show - s05e08.en.opensubtitles.srt", CLEAN)
    monkeypatch.setattr(find_subs, "os_load", lambda: {"api_key": "k"})
    monkeypatch.setattr(find_subs, "search_online", search)
    got = cn.get_subtitles(video, "en", opts())
    assert got == (tmp_path / "Show - s05e08.en.opensubtitles.srt", False) and calls == [None]   # without asking
    assert cn.get_subtitles(video, "en", opts()) == got and len(calls) == 1      # the next run: no second download
    assert bad.read_text(encoding="utf-8").count("\u00ce\u00bd") == 8                          # the damaged file is kept


def test_a_run_goes_on_with_damaged_subs_when_it_cant_do_better(tmp_path, monkeypatch, capsys):
    video, bad = film_with_damaged_subs(tmp_path)
    monkeypatch.setattr(find_subs, "os_load", lambda: None)
    assert cn.get_subtitles(video, "en", opts()) == (bad, False)
    assert "looks damaged" in capsys.readouterr().out
    monkeypatch.setattr(find_subs, "os_load", lambda: (_ for _ in ()).throw(AssertionError("asked not to")))
    assert cn.get_subtitles(video, "en", opts(replace_bad_subs=False)) == (bad, False)
    assert cn.get_subtitles(video, "en", opts(offline=True)) == (bad, False)
    monkeypatch.setattr(find_subs, "os_load", lambda: {"api_key": "k"})          # a download that's damaged too
    monkeypatch.setattr(find_subs, "search_online", lambda *a, **k: srt(tmp_path / "Show - s05e08.en.opensubtitles.srt", DAMAGED))
    assert cn.get_subtitles(video, "en", opts()) == (bad, False)


def test_a_film_with_notes_keeps_its_subtitles(tmp_path, monkeypatch, capsys):
    video, bad = film_with_damaged_subs(tmp_path)
    notes = tmp_path / "context-notes" / video.name / f"notes-{video.stem}.json"
    notes.parent.mkdir(parents=True)
    notes.write_text("{}")
    monkeypatch.setattr(find_subs, "os_load", lambda: (_ for _ in ()).throw(AssertionError("notes are anchored")))
    assert cn.get_subtitles(video, "en", opts()) == (bad, False)
    assert "notes were written from them" in capsys.readouterr().out


@needs_ffmpeg
def test_looks_inside_a_video(tmp_path):
    sub = srt(tmp_path / "in.srt", DAMAGED)
    video = tmp_path / "Film.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x36:d=10", "-i", str(sub),
                    "-map", "0", "-map", "1", "-c:v", "libx264", "-c:s", "srt", "-metadata:s:s:0", "language=eng",
                    str(video)], check=True)
    sub.unlink()
    assert subcheck.check_video(video) == []                                        # nothing beside it
    (where, found), = subcheck.check_video(video, look_inside=True)
    assert where == "inside, track 1 (English)" and found["mangled"][0] == 8
