"""The default old-film rule: films more than 40 years old get extra attention to their period."""
from pathlib import Path

import pytest

import generate_notes as gn


def test_rule_applies_only_when_film_is_over_40_years_old():
    assert gn.era_section(1974, this_year=2026) != ""          # 52 years old
    assert gn.era_section(1986, this_year=2026) == ""          # exactly 40: not more than 40
    assert gn.era_section(1985, this_year=2026) != ""          # 41 years old
    assert gn.era_section(2015, this_year=2026) == ""          # recent


def test_rule_is_off_when_the_year_is_unknown():
    assert gn.era_section(None) == ""
    assert gn.era_section("") == ""


def test_rule_text_names_the_year_and_the_four_focus_areas():
    text = gn.era_section("1974", this_year=2026)
    assert "made in 1974" in text
    assert "more than 40 years ago" in text
    for word in ("words", "people", "places", "cultural mood"):
        assert word in text


def test_system_prompt_gets_the_rule_only_when_given_a_year():
    base = dict(audience="x", language="English", cats="c", language_section="", examples="e")
    old = gn.SYSTEM.format(era_section=gn.era_section("1974", this_year=2026), **base)
    new = gn.SYSTEM.format(era_section=gn.era_section("2020", this_year=2026), **base)
    assert "more than 40 years ago" in old
    assert "more than 40 years ago" not in new
    assert "{era_section}" not in old


# ---------------------------------------------------------------- finding the year
@pytest.mark.parametrize("text, year", [
    ("Amadeus (1984) Directors Cut", 1984),
    ("Das.Boot.1981.RESTORED.GERMAN.1080p", 1981),
    ("2001.A.Space.Odyssey.1968", 1968),          # the last year, when the title itself has one
    ("Blade Runner 2049 (2017)", 2017),           # a bracketed year beats the title's year
    ("1917.2019.1080p", 2019),
    ("The IT Crowd - S01E02 - Calamity Jen", None),
    ("Movies", None),
    ("Resolution 4K 2160p", None),                # 2160 is not a year
])
def test_year_in_text(text, year):
    assert gn.year_in_text(text, this_year=2026) == year


def test_find_year_order_title_then_tags_then_file_then_folder(monkeypatch):
    tags = {"value": None}
    monkeypatch.setattr(gn, "year_in_tags", lambda video, this_year=None: tags["value"])
    video = Path("/Films/Amadeus (1984) Directors Cut/Amadeus.mkv")
    assert gn.find_year(video, title="Amadeus (1984, director's cut)") == (1984, "the title")
    tags["value"] = 1985
    assert gn.find_year(video) == (1985, "the file's tags")
    tags["value"] = None
    assert gn.find_year(Path("/Films/Amadeus (1984) Directors Cut/Amadeus.1984.mkv")) == (1984, "the file name")
    assert gn.find_year(Path("/Films/Amadeus (1984) Directors Cut/Amadeus.mkv")) == (1984, "the folder name")
    assert gn.find_year(Path("/Films/Amadeus/Amadeus.mkv")) == (None, None)
    assert gn.find_year() == (None, None)


def test_resolve_year_prefers_the_explicit_year_and_says_where_it_came_from(monkeypatch):
    said = []
    monkeypatch.setattr(gn, "year_in_tags", lambda video, this_year=None: None)
    assert gn.resolve_year("1974", Path("/x/Film (1990)/f.mkv"), None, say=said.append) == 1974
    assert said == []
    assert gn.resolve_year(None, Path("/x/Film (1990)/f.mkv"), None, say=said.append) == 1990
    assert said == ["Release year 1990, from the folder name."]
    said.clear()
    assert gn.resolve_year(None, Path("/x/Film/f.mkv"), None, say=said.append) is None
    assert "old-film rule is off" in said[0]


def test_year_in_tags_ignores_creation_time_and_survives_no_ffprobe(monkeypatch):
    def fake_run(*args, **kwargs):
        return type("R", (), {"stdout": '{"format": {"tags": {"creation_time": "2026-01-01T00:00:00Z", '
                                                            '"DATE_RELEASED": "1974-05-02"}}}'})()
    monkeypatch.setattr(gn.subprocess, "run", fake_run)
    assert gn.year_in_tags(Path("x.mkv"), this_year=2026) == 1974

    def no_ffprobe(*args, **kwargs):
        raise FileNotFoundError("ffprobe")
    monkeypatch.setattr(gn.subprocess, "run", no_ffprobe)
    assert gn.year_in_tags(Path("x.mkv"), this_year=2026) is None
