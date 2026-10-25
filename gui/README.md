# The page (`gui/`)

The web page `app.py` serves is one self-contained HTML file, `gui/index.html`: no outside scripts, styles, fonts or
images, because the page's Content-Security-Policy allows none. That file is **generated**. The sources are in
`gui/src`, and `gui/assemble.py` puts them together.

```
python3 gui/assemble.py            # rebuild gui/index.html from gui/src
python3 gui/assemble.py --check    # exit 1 if gui/index.html is out of date
```

Commit the regenerated `gui/index.html` with the source change; `tests/test_gui_assemble.py` fails when they differ.
`assemble.page()` returns the same page as a string, so `app.py` can serve it straight from the sources.

## The layers

The sources follow atomic design, smallest things first. Each layer only depends on the ones above it.

| Layer | Where | What goes there |
|---|---|---|
| Tokens | `src/styles/tokens.css` | The only place colours, font stacks, radii and the type scale are defined, as CSS custom properties, including the dark-mode values. |
| Base | `src/styles/base.css` | The reset and the page's defaults (`body`, headings, focus rings). |
| Atoms | `src/styles/atoms.css` | One thing at a time: buttons (`.btn`, `.primary`, `.quiet`), inputs and selects, the progress bar, state badges, hints and messages. |
| Molecules | `src/styles/molecules.css` | A few atoms that go together: a labelled field, a checkbox row, a radio choice, the key banner, a note card on the screen, a step, a row of the video list. |
| Organisms | `src/styles/organisms.css` and `src/partials/*.html` | The page's sections: header, screen, steps, chooser, video list, options panel, run bar, log, and the two dialogs. One partial per section, in page order. |
| Layout | `src/styles/layout.css` | The centred column, the two-column body, and generic rows. |
| Page | `assemble.py` | The doctype, `<head>`, one `<style>` with the layers in order, the partials in order, one `<script>`. |

The script is split the same way, in `src/js`:

- `00-util.js`: the `CN` namespace, element helpers (`$`, `el`), `store` (what the browser remembers), and wording helpers.
- `10-api.js`: `CN.api(path, body)`, the one way to talk to `app.py`. It sends the key from the page's address and always
  returns an object, with `error` set when something went wrong.
- `20-state.js`: the wording tables and `CN.state`, what the page knows right now (`info`, `videos`, `running`, ...).
- `components/*.js`: one file per organism. `screen` (the notes, title card and subtitle line), `steps`, `options`
  (reading, remembering and restoring the form), `videoList`, `chooser` (the path box, system dialogs and the file
  browser), `runner` (running, following the job, questions, cancel), `log`, `settings`.
- `90-main.js`: wires the buttons and fields to the components, then starts.

Every file is a function that runs at once. It takes what it needs from `CN` at the top and adds its own functions
with `Object.assign(CN, {...})` at the bottom. Calls into another component go through `CN.name()` at call time, so
the order of the component files doesn't matter; the order of everything else is `src/manifest.json`.

## Adding a control

Say you want a new checkbox friends can tick.

1. **Markup.** Put it in the right partial, usually `src/partials/options.html`, with a unique `id`. Use the
   molecules that exist (`label.check`, `label.field`, `label.choice`), so it looks like its neighbours.
2. **Script.** Add the id to `options()` in `src/js/components/options.js`, so its value goes to `/api/status` and
   `/api/run`, and to `REMEMBERED` if it should be remembered between visits. If changing it should refresh the
   video list, add it to the first id list in `src/js/90-main.js`; if not, the second.
3. **Style.** Usually nothing: the molecules cover it. A new look goes in the lowest layer it belongs to, and any new
   colour or size goes in `tokens.css` first.
4. **The app.** `app.py` has to accept the new field: add it in `common_args` (how it becomes a command-line option)
   and `App.run`. See "The app" in `CLAUDE.md`.
5. **Rebuild and check.** `python3 gui/assemble.py`, then `.venv/bin/python -m pytest -q tests/test_gui_assemble.py
   tests/test_app.py`.

A whole new section is a new partial listed in `src/manifest.json` (under `page`, inside the centred column, or
`dialogs`, outside it), a new `components/*.js` file listed under `scripts`, and its wiring in `90-main.js`.

Two partials share a wrapper: `videos.html` opens the two-column `<div class="columns">` and `actions.html` closes it,
because the video list and the options panel sit side by side. Keep them in that order.

## Checking it by eye

Run `python3 app.py` and open the address it prints. To see the page without a real API, start it with `--api-url`
pointing at the fake API in `tests/conftest.py`. The page must work in both light and dark mode (the tokens carry
both), and down to a phone's width (the screen and the columns stack at 620 px and 820 px).
