"""The Python version .venv is made with (pythonpin.py, .python-version) and make_venv.py, which makes it."""
import re
import sys
from pathlib import Path

import pytest

import make_venv
import pythonpin


def test_the_pin_is_read_from_python_version(tmp_path):
    f = tmp_path / ".python-version"
    for text, want in (("3.14\n", (3, 14)), ("3.14.2", (3, 14)), ("# a comment\npython-3.13\n", (3, 13)),
                       ("system\n", None)):
        f.write_text(text, encoding="utf-8")
        assert pythonpin.pinned(f) == want, text
    assert pythonpin.pinned(tmp_path / "missing") is None


def test_only_a_newer_python_gets_the_note():
    note = pythonpin.newer_than_pin((3, 15), (3, 14))
    assert "Python 3.15" in note and "set up for Python 3.14" in note and "make_venv.py" in note
    assert pythonpin.newer_than_pin((3, 14), (3, 14)) is None
    assert pythonpin.newer_than_pin((3, 12), (3, 14)) is None          # older ones are fine (3.9 and up)
    assert pythonpin.newer_than_pin((3, 15), ()) is None               # no pin, no note
    st = pythonpin.status()
    assert st["pinned"] == pythonpin.dotted(pythonpin.pinned()) and st["version"].startswith(pythonpin.dotted(sys.version_info))


def test_the_requirements_marker_moves_with_the_pin():
    """Lifting the pin means changing .python-version and the marker on faster-whisper together."""
    pin = pythonpin.pinned()
    text = (pythonpin.HERE / "requirements.txt").read_text(encoding="utf-8")
    m = re.search(r'^faster-whisper[^;\n]*;\s*python_version\s*<\s*"(\d+)\.(\d+)"', text, re.M)
    assert pin and m and (int(m.group(1)), int(m.group(2))) == (pin[0], pin[1] + 1)


def fake_setup(monkeypatch, tmp_path, can_speak=False):
    """make_venv in tmp_path, with a found Python, and the commands recorded instead of run."""
    monkeypatch.setattr(make_venv, "HERE", tmp_path)
    monkeypatch.setattr(make_venv, "find_python", lambda pin: Path("/fake/python3.14"))
    monkeypatch.setattr(make_venv, "can_import", lambda python, module: can_speak)
    ran = []

    def run(cmd):
        ran.append([str(c) for c in cmd])
        if cmd[1:3] == ["-m", "venv"]:
            Path(cmd[3]).mkdir()
            (Path(cmd[3]) / "pyvenv.cfg").write_text("version = 3.14.0\n", encoding="utf-8")
        return 0
    monkeypatch.setattr(make_venv, "run", run)
    return ran


def test_a_venv_on_another_version_is_kept_and_a_new_one_made(tmp_path, monkeypatch, capsys):
    ran = fake_setup(monkeypatch, tmp_path)
    old = tmp_path / ".venv"
    old.mkdir()
    (old / "pyvenv.cfg").write_text("home = /x\nversion = 3.1.0\n", encoding="utf-8")
    (tmp_path / ".venv-3.1").mkdir()                                   # that name is taken: -2
    assert make_venv.main(["--yes"]) == 0
    assert (tmp_path / ".venv-3.1-2" / "pyvenv.cfg").read_text(encoding="utf-8").endswith("version = 3.1.0\n")
    vpy = str(make_venv.venv_python(tmp_path / ".venv"))
    assert ran[0][1:] == ["-m", "venv", str(tmp_path / ".venv")]
    rest, speech = make_venv.requirements()
    assert ran[1:] == [[vpy, "-m", "pip", "install", "--upgrade", "pip"], [vpy, "-m", "pip", "install", *rest],
                       [vpy, "-m", "pip", "install", *speech]]
    assert "numpy>=1.21" in rest and not any("whisper" in r for r in rest) and speech[0].startswith("faster-whisper")
    out = capsys.readouterr().out
    assert "Speech recognition (faster-whisper) isn't installed" in out and "Done." in out


def test_a_venv_on_the_right_version_is_only_topped_up(tmp_path, monkeypatch, capsys):
    ran = fake_setup(monkeypatch, tmp_path, can_speak=True)
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text(f"version = {pythonpin.dotted(pythonpin.pinned())}.1\n")
    assert make_venv.main([]) == 0
    assert not any("venv" == c for cmd in ran for c in cmd) and len(ran) == 3
    assert "isn't installed" not in capsys.readouterr().out


def test_nothing_changes_without_a_yes_or_without_the_python(tmp_path, monkeypatch):
    ran = fake_setup(monkeypatch, tmp_path)
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("version = 3.1.0\n")
    with pytest.raises(SystemExit) as e:                               # nobody to say yes
        make_venv.main([])
    assert "add --yes" in str(e.value) and ran == [] and (tmp_path / ".venv").is_dir()
    assert make_venv.main(["--check"]) == 0 and ran == []
    monkeypatch.setattr(make_venv, "find_python", lambda pin: None)
    with pytest.raises(SystemExit) as e:
        make_venv.main(["--yes"])
    assert "Can't make the environment without Python" in str(e.value) and ran == []
    assert sorted(p.name for p in tmp_path.iterdir()) == [".venv"]


def test_the_python_found_is_the_pinned_version():
    here = make_venv.find_python(sys.version_info[:2])                 # this one counts
    assert here is not None and make_venv.version_of(here) == tuple(sys.version_info[:2])
    assert make_venv.find_python((3, 99)) is None
