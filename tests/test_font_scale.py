"""--font-scale writes bigger notes and dialogue, keeping the text column's width in step with the type."""
import json

import make_ass
from conftest import make_srt


def build_with(tmp_path, scale, layout="split"):
    srt = make_srt(tmp_path / "ep.srt", n=6)
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps({"notes": [{"cue": 2, "category": "Idiom", "text": "A short note."}]}))
    out = tmp_path / f"o-{scale}.ass"
    make_ass.build(srt, notes, out, layout=layout, font_scale=scale, say=lambda *_: None)
    return out.read_text(encoding="utf-8-sig")


def test_default_sizes_are_unchanged(tmp_path):
    text = build_with(tmp_path, 1.0)
    assert "Style: Dialogue,Arial,58," in text
    assert "NoteL,Arial,35," in text
    assert ",44,1040,36,1" in text


def test_bigger_scale_grows_type_and_keeps_the_column_in_proportion(tmp_path):
    text = build_with(tmp_path, 1.3)
    assert "Style: Dialogue,Arial,75," in text          # 58 * 1.3
    assert "NoteL,Arial,46," in text                    # 35 * 1.3
    assert ",44,789,36,1" in text                       # text column 836 * 1.3 = 1087 px wide


def test_scale_is_capped_at_the_screen_width(tmp_path):
    text = build_with(tmp_path, 3.0)
    assert ",44,44,36,1" in text                        # 1920 - 88 px of text width, the most the screen allows
