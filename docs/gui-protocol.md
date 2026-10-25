# Running the scripts from another program (a GUI)

This is protocol version 1. `app.py` (the page in your browser) uses it, and is a working example of everything here.

A GUI runs the same scripts you run in Terminal. It reads what they print, and answers their questions for them.
This page is what that program needs to know. The code is in `prompts.py`.

## Switching it on

Set the environment variable `CONTEXT_NOTES_UI=json` for the script you start. Every script it starts inherits it
(`context_notes.py` runs `analyze.py`, `make_ass.py` and the rest as separate programs), so one setting covers the
whole run.

Without it nothing changes. A person at a terminal gets the usual questions. With no terminal, the scripts take
`--yes` or the safe default, as before.

## What comes out

- **stdout:** ordinary text for a log window, plus **event lines**. An event line is `@context-notes ` followed
  by one JSON object. Every event has `"v": 1` and a `"type"`.
- **stderr:** warnings, and the message a script stops with. Show it in the log too.
- **Exit code:** 0 means it finished. Anything else means it stopped, and the last line of stderr says why.

Set `PYTHONUNBUFFERED=1` as well, so log lines arrive as they are printed. (Event lines are always flushed.)

### `question`

```
@context-notes {"v": 1, "type": "question", "id": "generate.send", "text": "Send the subtitle text to the Claude API now?", "choices": [{"key": "y", "label": "yes"}, {"key": "n", "label": "no"}], "default": "n"}
```

Answer with one line on stdin, containing a choice's `key`.
- An empty line takes the `default`.
- `yes` and `no` also work, because the first letter counts.
- Anything else is asked again: a "Please answer ..." log line, then the same event.
- If stdin is closed, every later question takes its default. For the questions that spend money, the default is no.

### `input`

```
@context-notes {"v": 1, "type": "input", "id": "api-key", "text": "Paste your Anthropic API key (input is hidden), then press Return:", "hidden": true}
```

Answer with the text as one line. `hidden` inputs (keys and passwords) are never printed back out.

### `estimate`

This is sent before anything goes to Claude (the API, or Claude Code). Unless `--yes` or `--estimate-only` was given, the matching
`.send` question follows it.

```
@context-notes {"v": 1, "type": "estimate", "step": "generate", "model": "claude-sonnet-5-5", "backend": "api", "lines": 13, "requests": 1, "input_tokens": 1792, "output_tokens": 139, "cost_usd": 0.005, "limit": null}
```

| Field | Meaning |
|---|---|
| `step` | `generate` (notes from the dialogue) or `refine` (the video-frames pass) |
| `model`, `requests` | which Claude model, and how many requests |
| `backend` | where Claude runs: `api` (the user's key, API credits) or `claude-code` (Claude Code on their subscription) |
| `input_tokens`, `output_tokens`, `cost_usd` | the estimate; `cost_usd` is `null` when the model's price isn't known, and always `null` for `claude-code` (no credits are spent) |
| `limit` | seconds, when `--limit` is in force; otherwise `null` |
| `lines` | generate only: subtitle lines sent |
| `mode`, `offset`, `images`, `notes` | refine only: `full` or `visual-only`; the sync offset used; how many contact-sheet images; how many existing notes |

### `progress`

This reports how far a long task has got, for a progress bar.

```
@context-notes {"v": 1, "type": "progress", "task": "transcribe", "done": 1312.4, "total": 5400.0, "unit": "seconds"}
```

| `task` | Sent by | `unit` |
|---|---|---|
| `soundtrack` | `analyze.py`: the sync check, and the start of `--refine` | seconds of the film |
| `frames` | `analyze.py`: pulling frames for the contact sheets | frames. `total` is `null` until it's done, so show a spinner |
| `transcribe` | speech recognition: `--align`, the alignment check, subtitles from the soundtrack | seconds. A `text` field says what it's doing while `done` is 0 |
| `generate` | `generate_notes.py` | requests to the API |
| `refine` | `refine_notes.py` | requests to the API |

- A `null` total means "unknown": show a spinner. The last event of a task has `done` equal to `total`.
- Long tasks send at most two events a second.
- In a GUI run, speech recognition doesn't print its usual line that keeps rewriting itself. It prints one line
  when it's done.

### `video`, `step` and `video-result`

These come from `context_notes.py`, so a GUI can show which video and which step it's on.

```
@context-notes {"v": 1, "type": "video", "path": "/Movies/Amelie.mkv", "index": 1, "total": 3}
@context-notes {"v": 1, "type": "step", "step": "generate"}
@context-notes {"v": 1, "type": "video-result", "path": "/Movies/Amelie.mkv", "result": "ready"}
```

- `video`: starting video `index` of `total`.
- `step`: `subtitles`, `sync`, `generate`, `refine`, `build` or `alignment`. Only the steps that actually run
  are sent.
- `video-result`: `ready` (built now), `done` (nothing needed doing) or `stopped` (with a `reason`). It isn't
  sent for a video whose run was cancelled.

## Question and input ids

The ids are stable, so a GUI can show its own wording or a special dialog. The `text` is always there as a fallback.

| id | Asked by | Choices (default) | About |
|---|---|---|---|
| `generate.send` | `generate_notes.py` | y / n (**n**) | "Send the subtitle text to the Claude API now?", or with the `claude-code` backend "Send the subtitle text to Claude Code (your subscription) now?" |
| `refine.send` | `refine_notes.py` | y / n (**n**) | "Send the video frames and subtitle text to the Claude API now?", or with `claude-code` "...to Claude Code (your subscription) now?" |
| `generate.resume` | `generate_notes.py` | p / s (p) | The last run stopped part-way: pick up where it left off, or start again |
| `refine.resume` | `refine_notes.py` | p / s (p) | The last refine stopped part-way: pick up, or start again from the notes as they were before it |
| `sync.unmeasured` | `context_notes.py` | y / n (y) | The sync couldn't be measured: treat as in sync? |
| `sync.drift` | `context_notes.py` | a / c / s (a, or c when re-timing isn't possible) | The timing drifts: re-time, carry on, or skip |
| `alignment.check` | `context_notes.py` | y / n (y) | Check every note's timing with speech recognition (slow) |
| `alignment.fix` | `context_notes.py` | y / n (y) | Move the stretches that are out, and rebuild |
| `notes.limited` | `context_notes.py` | y / n (y) | Notes cover only part of the video: write them for all of it? |
| `folder.next` | `context_notes.py` | y / n (y) | One video stopped: go on to the next? |
| `subs.download` | `context_notes.py` (y), `find_subs.py` (n) | y / n | Download subtitles from OpenSubtitles.com (uses a daily download) |
| `subs.transcribe` | `context_notes.py`, `find_subs.py` | y / n (n) | Write subtitles from the soundtrack with speech recognition |
| `api-key` | `make_ass.py --set-api-key` | input, hidden | Saved to `~/.config/context-notes/api-key`, mode 600 |
| `opensubtitles.api-key` | `find_subs.py --set-opensubtitles` | input, hidden | |
| `opensubtitles.username` | `find_subs.py --set-opensubtitles` | input | |
| `opensubtitles.password` | `find_subs.py --set-opensubtitles` | input, hidden | |

`alignment.check` only comes up in a GUI run. With no terminal and no GUI, the scripts skip that question, as they
always have, and print a hint about `--check-alignment` instead.

## `--yes` and `--estimate-only`

- `--yes` works as it does in Terminal: no questions, and the defaults are taken.
- `make_ass.py SRT [NOTES] --generate --estimate-only`, or `make_ass.py SRT NOTES --refine --video V --estimate-only`,
  prints the estimate (and sends the `estimate` event), then stops with exit code 0.
  - No API key is needed, and nothing is sent.
  - No notes, `.bak` or `.ass` files are written.
  - `--refine` still analyses the video. That's kept in `<video> analysis`, so the real run is quicker.
  - It works on one step at a time.

## Example

```
$ CONTEXT_NOTES_UI=json python3 make_ass.py the-help-desk.srt --generate
Plan: 13 lines in 1 request(s) to claude-sonnet-5-5; about 1,792 tokens in and 139 out, roughly $0.00 in API credits.
@context-notes {"v": 1, "type": "estimate", "step": "generate", ...}
@context-notes {"v": 1, "type": "question", "id": "generate.send", ...}
n                                   <- written to stdin by the GUI
Cancelled; nothing was sent.        (stderr; exit code 1)
```

## Rules for the program doing the driving

- Read stdout line by line. Write an answer only when a `question` or `input` event asks for one, and write
  exactly one line per event. All the scripts in a run share stdin, and each one reads exactly its own line.
- Keep the API key out of command lines and logs. Let the scripts read it from the key file, and save it there
  with `--set-api-key`.
- Where Claude runs is the `--backend` flag (`api` or `claude-code`), or the setting saved with `--set-backend`.
  With `claude-code`, no key is needed, but the `claude` command has to be installed and signed in; a script stops
  at once with a plain message when it isn't, before any local work.

## Cancelling

Cancel works like Ctrl-C in Terminal: send `SIGINT` to the run's whole process group.

- Start the run in a process group of its own. In Python that's `subprocess.Popen(..., start_new_session=True)`.
  To cancel, call `os.killpg(p.pid, signal.SIGINT)`.
- Signal the group, not just the process you started, because the step that's running needs the signal too.

What happens then:
- **Notes Claude has already written are kept**, in `notes-<name>.partial.json`. The next run asks whether to pick
  up where it left off (`generate.resume`). Picking up is the default, and it sends only the rest.
- **A cancelled refine keeps the changes made so far**, and the notes file records where it stopped. The next refine
  asks whether to pick up there (`refine.resume`), which is the default.
- **Nothing is left half-written.** Caches, subtitle files, notes and the `.ass` are written all at once, so each
  is either the old version or the new one.
- `context_notes.py` gives the running step up to 10 s to finish tidying up. Then it prints "Stopped. Rerun the
  same command to pick up where this left off." and exits with code 130.
- A script run directly ends as killed by `SIGINT`: status 130 in a shell, or -2 from Python's `subprocess`.
  Python may print a `KeyboardInterrupt` traceback to stderr; after a cancel, that's expected.
- Rerun the same command to carry on. Steps that finished are skipped.

## For people adding to the scripts

- Ask through `prompts.py` (`confirm`, `secret`, `text_input`) or `context_notes.ask(..., id=...)`, never with
  `input()` or `getpass` directly. Give every new question a stable id, and add it to the table above.
- Send events only through `prompts.py`. Never send one while a printed line is still open
  (`print(..., end=" ")`): an event must start its own line, or a GUI misses it. The tests check this.
- Write any file a later run reads with `fileio.write_text_safely()` or `fileio.replacing()`, never in place.
