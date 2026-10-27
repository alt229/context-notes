"""The app's page is kept in parts (gui/src) and joined by app.py each time it's asked for."""
from conftest import ROOT
from test_app import call, server  # noqa: F401  (the app fixture)

import app

SRC = ROOT / "gui" / "src"


def test_the_page_is_joined_from_its_parts_in_order():
    text = app.page()
    assert text.startswith("<!doctype html>") and text.rstrip().endswith("</html>")
    for marker, _, _ in app.PAGE_PARTS:
        assert marker not in text                                   # every part was put in
    assert text.count("<style>") == 1 and text.count("<script>") == 1
    for _, folder, suffix in app.PAGE_PARTS:
        files = sorted((SRC / folder).glob("*" + suffix), key=lambda p: p.name)
        assert files, folder
        at = [text.index(p.read_text(encoding="utf-8")) for p in files]
        assert at == sorted(at), f"{folder}: out of order"           # name order is page order
    assert not (ROOT / "gui" / "index.html").exists()               # one copy: no built page beside the parts


def test_each_part_is_named_for_its_place():
    for _, folder, suffix in app.PAGE_PARTS:
        for p in (SRC / folder).iterdir():
            assert p.suffix == suffix and p.name[:2].isdigit() and p.name[2] == "-", p.name


def test_the_server_sends_the_joined_page(server):  # noqa: F811
    status, text, _ = call(server, f"/?k={server.app.token}", key=False, raw=True)
    assert status == 200 and text == app.page()
