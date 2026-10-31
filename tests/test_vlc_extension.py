"""vlc/context_notes.lua, run against a stand-in for VLC's Lua API (there's no VLC here). Needs lupa, a Lua runtime
for Python (`pip install lupa`); without it these tests are skipped. VLC 3 runs Lua 5.2, so that's the one used."""
import os
from pathlib import Path

import pytest

lua52 = pytest.importorskip("lupa.lua52")
ROOT = Path(__file__).resolve().parent.parent
HEAD = ("[Script Info]\nScriptType: v4.00+\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
STAND_IN = """function make_vlc(py)
  local v = {}
  v.input = { item = function() return { uri = function() return "file://" .. py.video end } end,
              add_subtitle = function(p, sel) py.add(p, sel) end }
  v.strings = { make_path = function(u) return (u:gsub("^file://", "")) end, decode_uri = function(u) return u end }
  v.config = { userdatadir = function() return py.user end }
  v.io = { open = function(p, m) return io.open(p, m) end, mkdir = function(p) py.mkdir(p) end,
           unlink = function(p) os.remove(p) end, readdir = function(dir) return py.readdir(dir) end }
  v.msg = { info = function(m) py.log(m) end }
  v.dialog = function()
    return { add_label = function() return { set_text = function() end } end,
             add_check_box = function() return { get_checked = function() return true end } end,
             add_button = function() end, show = function() end, hide = function() end, delete = function() end }
  end
  return v
end"""


def ass(lines):
    return HEAD + "".join(f"Dialogue: 1,0:00:0{i}.00,0:00:0{i + 1}.00,NoteL,{tag},0,0,0,,{text}\n"
                          for i, (tag, text) in enumerate(lines))


CONTEXT = ass([("speech/idiom/high", "An idiom note"), ("visual/prop/medium", "A prop note")])
BTS = ass([("speech/injury/high", "Two toes broken"), ("visual/effects/high", "A painted castle"),
           ("speech/goof/low", "A goof")])


def play(tmp_path, files, video="Film.mkv", saved=None, reload=False):
    """Start the extension with `video` playing beside `files`. Returns ([(file loaded, selected, its text or None
    when it's been removed)], the last status line)."""
    films, user = tmp_path / "films", tmp_path / "user"
    films.mkdir()
    user.mkdir()
    for name, text in {**files, video: "x"}.items():
        (films / name).write_text(text, encoding="utf-8")
    if saved:
        (user / "context-notes-settings.txt").write_text(saved)
    lua = lua52.LuaRuntime(unpack_returned_tuples=True)
    added, said = [], []
    lua.execute(STAND_IN)
    py = lua.table_from({"video": str(films / video), "user": str(user), "log": said.append,
                         "add": lambda p, sel: added.append((p, bool(sel))),
                         "mkdir": lambda p: os.makedirs(p, exist_ok=True),
                         "readdir": lambda d: lua.table_from(sorted(os.listdir(d)))})
    g = lua.globals()
    g.vlc = g.make_vlc(py)
    lua.execute((ROOT / "vlc" / "context_notes.lua").read_text(encoding="utf-8"))
    g.activate()
    if reload:
        g.load_for_current(True)
    status = said[-1].replace("[Context Notes] ", "", 1)                    # as the extension's window shows it
    return [(Path(p).name, sel, Path(p).read_text() if Path(p).exists() else None) for p, sel in added], status


def test_both_sets_of_notes_load_and_the_context_notes_show_first(tmp_path):
    out, status = play(tmp_path, {"Film.notes.ass": CONTEXT, "Film.behind-the-scenes.notes.ass": BTS})
    assert [sel for _, sel, _ in out] == [True, False]
    assert "An idiom note" in out[0][2] and "Two toes broken" in out[1][2]
    assert "Also loaded: 3 of 3 Behind the Scenes notes" in status and "Sub Track" in status


def test_behind_the_scenes_alone_is_shown(tmp_path):
    out, status = play(tmp_path, {"Film.behind-the-scenes.notes.ass": BTS})
    assert [(sel, "Two toes" in text) for _, sel, text in out] == [(True, True)]
    assert status.startswith("Showing 3 of 3 Behind the Scenes notes")


def test_a_renamed_video_finds_both_and_ignores_the_second_when_guessing(tmp_path):
    out, _ = play(tmp_path, {"Old Name.notes.ass": CONTEXT, "Old Name.behind-the-scenes.notes.ass": BTS})
    assert len(out) == 2 and "An idiom" in out[0][2]


def test_the_topic_switches_apply_to_both(tmp_path):
    out, status = play(tmp_path, {"Film.notes.ass": CONTEXT, "Film.behind-the-scenes.notes.ass": BTS},
                       saved="making=false\nless_sure=false\n")
    assert "A prop note" not in out[0][2] and "An idiom note" in out[0][2]          # less sure: off
    assert not any(t in out[1][2] for t in ("Two toes", "painted castle", "A goof"))  # how it was made: off
    assert "0 of 3 Behind the Scenes notes" in status


def test_loading_again_removes_the_copies_it_made_before(tmp_path):
    out, _ = play(tmp_path, {"Film.notes.ass": CONTEXT, "Film.behind-the-scenes.notes.ass": BTS}, reload=True)
    assert [text is None for _, _, text in out] == [True, True, False, False]


def test_no_notes_says_what_it_looked_for(tmp_path):
    out, status = play(tmp_path, {})
    assert out == [] and status == "No notes for this video. Looking for: Film.notes.ass"
