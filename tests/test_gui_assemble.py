"""The page friends open (gui/index.html) is generated from gui/src by gui/assemble.py. These tests keep the generated
file in step with the sources, and keep it one self-contained page: every id the script looks for is in the markup,
and nothing is loaded from the web (app.py's Content-Security-Policy would block it anyway)."""
import re
from collections import Counter
from pathlib import Path

from gui import assemble

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "gui" / "index.html"


def parts(html):
    """The page's style, markup and script, as three strings."""
    style = re.search(r"<style>\n(.*?)</style>", html, re.S).group(1)
    markup = re.search(r"<body>\n(.*?)<script>", html, re.S).group(1)
    script = re.search(r"<script>\n(.*?)</script>", html, re.S).group(1)
    return style, markup, script


def ids_used_by(script):
    """Every element id the script asks for: $("x"), msg("x", ...), $(a ? "x" : "y"), and the lists it loops over."""
    ids = set(re.findall(r'\$\("([^"]+)"\)', script)) | set(re.findall(r'\bmsg\("([^"]+)"', script))
    for a, b in re.findall(r'\$\([^)]*\? "(\w+)" : "(\w+)"\)', script):
        ids |= {a, b}
    lists = {m.group(1): re.findall(r'"([^"]+)"', m.group(2))
             for m in re.finditer(r"const (\w+) = (\[[^\]]*\])", script, re.S)}
    for m in re.finditer(r"for \(const (\w+) of (\[[^\]]*\]|\w+)\)(.{0,300})", script, re.S):
        var, source, after = m.groups()
        if f"$({var})" in after:
            ids |= set(re.findall(r'"([^"]+)"', source)) if source.startswith("[") else set(lists.get(source, []))
    return ids


def test_index_html_is_up_to_date():
    assert INDEX.read_bytes() == assemble.page().encode("utf-8"), \
        "gui/index.html doesn't match gui/src. Run: python3 gui/assemble.py"
    assert assemble.main(["--check"]) == 0


def test_every_id_the_script_uses_is_in_the_markup_once():
    _, markup, script = parts(INDEX.read_text(encoding="utf-8"))
    counts = Counter(re.findall(r'\bid="([^"]+)"', markup))
    assert [i for i, n in counts.items() if n > 1] == [], "an id is used twice in the markup"
    used = ids_used_by(script)
    assert len(used) > 40, "the id search found too few ids; did the script's shape change?"
    assert sorted(i for i in used if counts[i] != 1) == [], "the script looks for ids that aren't in the markup"


def test_nothing_is_loaded_from_the_web():
    html = INDEX.read_text(encoding="utf-8")
    style, markup, script = parts(html)
    assert "src=" not in markup, "no element may load something by src (scripts, images, frames)"
    assert "@import" not in style and "url(" not in style, "the style sheet must not fetch anything"
    # The only web addresses are links a person clicks (the Anthropic and OpenSubtitles pages).
    for m in re.finditer(r"https?://", html):
        tag = html[html.rfind("<", 0, m.start()):html.find(">", m.start()) + 1]
        assert tag.startswith("<a ") and 'target="_blank"' in tag, f"a web address outside a plain link: {tag!r}"
    assert "http" not in script, "the script must only talk to app.py, by relative /api/ paths"


def test_no_link_or_external_script_tags():
    html = INDEX.read_text(encoding="utf-8")
    assert "<link" not in html
    assert re.search(r"<script\s+[^>]*src=", html) is None
    assert len(re.findall(r"<script", html)) == 1 and len(re.findall(r"<style", html)) == 1
