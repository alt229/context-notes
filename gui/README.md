# The app's page

`app.py` serves one self-contained page (no external files). It's kept here in parts, and `app.py` joins them each
time the page is asked for (`app.page()`), so there is one copy of everything and nothing to rebuild: edit a part,
reload the page.

- `src/page.html`: the frame. Its three `include` lines are replaced by the files of
  - `src/styles/*.css` (inside the one `<style>`),
  - `src/html/*.html` (the body: the top, the screen, the form, then one file per dialog),
  - `src/js/*.js` (inside the one `<script>`; they share one scope, so a name defined in one file is used in others).
- Each folder's files are joined in name order. The number in front fixes the order: put a new part where it
  belongs (`35-something.js`), and keep `00-core.js` first and `99-start.js` last.
- `tests/test_page.py` checks the join; `tests/test_usage.py` checks that every `$("id")` the script uses is in the
  markup and every handler given by name is defined.
