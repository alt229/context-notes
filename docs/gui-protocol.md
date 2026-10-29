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

This is sent before anything goes to Claude. Unless `--yes` or `--estimate-only` was given, the matching
`.send` question follows it. On the Claude plan (the default route, through Claude Code) it also has `"route": "plan"`,
`cost_usd` is `null`, and `api_cost_usd` says what the same requests would cost in API credits (for when the plan runs
out). On the API there is no `route` field.

```
@context-notes {"v": 1, "type": "estimate", "step": "generate", "model": "claude-sonnet-5-5", "lines": 13, "requests": 1, "input_tokens": 1792, "output_tokens": 139, "cost_usd": 0.005, "limit": null}
```

| Field | Meaning |
|---|---|
| `step` | `generate` (notes from the dialogue) or `refine` (the video-frames pass) |
| `model`, `requests` | which Claude model, and how many API requests |
| `input_tokens`, `output_tokens`, `cost_usd` | the estimate; `cost_usd` is `null` when the model's price isn't known |
| `limit` | seconds, when `--limit` is in force; otherwise `null` |
| `balance_usd` | the estimated credit left (see `usage` below), or `null` when no balance has been set |
| `route`, `api_cost_usd` | on the plan only: `"plan"`, and the cost in API credits if it had to move to them |
| `lines` | generate only: subtitle lines sent |
| `mode`, `offset`, `images`, `notes` | refine only: `full` or `visual-only`; the sync offset used; how many contact-sheet images; how many existing notes |

### `usage`

Sent after each API request that finished, once the part it belongs to has been counted and saved (so a stop can't
lose it). `usage.py` keeps the figures; `balance_usd` is an estimate, because Anthropic doesn't let a program ask for
the real balance.

```
@context-notes {"v": 1, "type": "usage", "step": "generate", "film": "Amelie.mkv", "model": "claude-sonnet-5-5", "request": {"input_tokens": 2000, "output_tokens": 300, "cost_usd": 0.007}, "run": {"requests": 2, "input_tokens": 4000, "output_tokens": 600, "cost_usd": 0.014, "unpriced": 0}, "film_cost_usd": 0.014, "balance_usd": 9.986, "low": false}
```

| Field | Meaning |
|---|---|
| `step` | `generate` or `refine` (`null` for a request that isn't part of a film, such as the benchmark) |
| `film` | the film's name in the ledger: its notes file without `notes-` and `.json` |
| `request` | this request's tokens and cost; `cost_usd` is `null` when the model's price isn't known |
| `run` | the totals for this step of this run; `unpriced` counts requests with no known price |
| `film_cost_usd` | everything recorded for this film so far, across runs and steps |
| `balance_usd`, `low` | the estimated credit left, and whether it is under the warning level; `null` and `false` when no balance has been set |

A request on the plan sends `usage` with `"route": "plan"`, `request` (tokens, `cost_usd` `null`), `run`
(`plan_requests`, and the API `requests` and `cost_usd` so far in this step) and `session_percent` (the 5-hour session
as last seen, or `null`).

### `route`

Sent when a run moves from the Claude plan to API credits part-way (or before the first request, when Claude Code
can't be used): `{"type": "route", "step": "generate", "route": "api", "reason": "...", "allowance_usd": 5.0}`.
`allowance_usd` is what the run may spend in API credits (`--api-fallback`), or `null` after a yes to `plan.fallback`.

The same figures are in `app.py`'s `GET /api/usage` (also inside `/api/info`), which adds `spent` (today, the last
7 days with its request count, this month, all time), the latest `films` and the Claude plan's `session` (the 5-hour
and 7-day windows, read from what Claude Code's status line saved, plus `week`: how many 5-hour sessions it has seen in
the last 7 days and how full the busiest got). `POST /api/credit` with `{"balance": "25.00", "low": "2"}` sets the starting balance. `POST /api/plan/refresh`
gets a fresh reading of the plan's windows (one tiny request through Claude Code) and answers `{"ok": true, "usage":
...}` or `{"ok": false, "error": "..."}`.

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

### `status`

`context_notes.py --status` sends one per video, with what `--status` prints:

```
@context-notes {"v": 1, "type": "status", "path": "/Movies/Amelie.mkv", "name": "Amelie.mkv", "done": false, "subtitles": "Amelie.srt", "film_language": "fr", "notes": 100, "limit": null, "notes_stopped": false, "refined": "yes", "ass": "Amelie.notes.ass", "rebuild": true, "unreadable": 0, "refine_unreadable": 0, "tidy": 0}
```

- `refined`: `yes`, `no` or `stopped` (part-way).
- `rebuild`: the notes are finished and only the `.ass` is out of date (older than the notes, or built with a
  different look from the `--reading-speed` / `--note-background` / `--note-opacity` given, or by an older
  `make_ass.py`, or showing subtitles at the bottom in another language than `--show-subs` asks for). A run rebuilds it for free: nothing is sent to Claude, and no API key is needed.
- `unreadable`: how many parts of the notes came back as replies that couldn't be read, so their lines have no
  notes yet. The next run asks `notes.unreadable` and sends just those lines again. A video with any isn't `done`.
- `refine_unreadable`: the same for the frames step: stretches of the film whose replies couldn't be read. The next
  refine asks `refine.unreadable` and sends just those.
- `tidy`: how many working files an earlier version left beside this video. They work where they are; `tidy.py`
  moves them into its `context-notes` folder (README, "Where the files go"). 0 when there are none.

### `tidy`, `tidy-skip` and `tidy-done`

`tidy.py` lists what it would move, one `tidy` per video, and one `tidy-skip` per file it leaves where it is. After
moving, `tidy-done` says how it went (the app's Tidy button runs it with `--dry-run`, then `--yes`):

```
@context-notes {"v": 1, "type": "tidy", "video": "/Movies/Amelie.mkv", "folder": "/Movies/context-notes/Amelie.mkv", "items": [{"from": "notes-Amelie.json", "to": "notes-Amelie.json", "folder": false}, {"from": "Amelie analysis", "to": "analysis", "folder": true}]}
@context-notes {"v": 1, "type": "tidy-skip", "path": "/Movies/notes-Film.json", "reason": "it could belong to Film.mkv or Film.mp4"}
@context-notes {"v": 1, "type": "tidy-done", "moved": 2, "problems": []}
```

### `embed-plan`, `embed-video`, `embed-result` and `embed-backup`

`embed.py` (the notes inside an `.mkv`, README "Putting the notes inside the film") lists what it would do, one
`embed-plan` per video that has a `.notes.ass`. `action` is `add`, `update` (the notes changed since they were put
inside), `current` (nothing to do) or `skip` (`reason` says why: an `.mp4` without `--convert`, notes that only cover
part of the film, a link). `convert` is true for an `.mp4` that `--convert` will make into an `.mkv` first (its `.mp4`
is then kept in `context-notes/originals`). `size` is the film's size in bytes, `dropped` is how many data tracks (a camera's timecode) an `.mkv` can't hold are left out, and `seconds_low` and `seconds_high` are a rough range for reading and
rewriting it on the NAS (an estimate from the disk's speed, not a promise). While it works it sends `embed-video` and `embed-result` for each film
(`result` is `embedded` or `stopped`, with a `reason`), and `progress` events with `task` `embed` and `unit`
`seconds` (how much of the film has been copied). `--delete-backups` lists each kept original as `embed-backup`.
The app's Embed button runs it with `--dry-run`, then `--yes` as a job like a run:

```
@context-notes {"v": 1, "type": "embed-plan", "video": "/Movies/Amelie.mkv", "action": "add", "size": 4213456789, "reason": null, "seconds_low": 68, "seconds_high": 272}
@context-notes {"v": 1, "type": "embed-plan", "video": "/Movies/Heat.mp4", "action": "skip", "size": 0, "reason": ".mp4 can't hold these subtitles without losing their styling, so it stays as it is (.mkv only for now)"}
@context-notes {"v": 1, "type": "embed-video", "path": "/Movies/Amelie.mkv", "index": 1, "total": 1}
@context-notes {"v": 1, "type": "progress", "task": "embed", "done": 612.4, "total": 7320.0, "unit": "seconds"}
@context-notes {"v": 1, "type": "embed-result", "path": "/Movies/Amelie.mkv", "result": "embedded", "reason": null}
```

`context_notes.py --embed` runs `embed.py` after each finished film, so a run's events can include these, and
`step` gets the name `embed`.

### `rebuild-diff`

`context_notes.py --preview-rebuild` lists what a rebuild would change, for each finished video whose `.ass` is out of
date. It changes nothing. Each `rows` entry is one setting: `now` is what the file has, `after` is what the rebuild
would give, and `changed` says whether they differ. `files` lists what gets written: the kept `.bak`, the rebuilt
`.notes.ass`, the Plex copy, and a note when the `.mkv`'s own copy of the notes goes out of date (`embedded` is true
when the notes are inside the `.mkv` now). The app's rebuild dialog shows these; `--embed` on the run puts the new
notes inside afterwards.

```
@context-notes {"v": 1, "type": "rebuild-diff", "video": "/Movies/Akira/Akira.1988.1080p.mkv", "name": "Akira.1988.1080p.mkv", "rows": [{"setting": "Box behind the notes", "now": "not recorded (made before 0.2.0)", "after": "see-through", "changed": true}], "files": ["Kept: Akira.1988.1080p.notes.ass.bak (the .notes.ass as it is now)", "Rebuilt: Akira.1988.1080p.notes.ass"], "embedded": true}
```

## Question and input ids

The ids are stable, so a GUI can show its own wording or a special dialog. The `text` is always there as a fallback.

| id | Asked by | Choices (default) | About |
|---|---|---|---|
| `generate.send` | `generate_notes.py` | y / n (**n**) | Send the subtitles to Claude (the plan or the API: see `estimate`) |
| `refine.send` | `refine_notes.py` | y / n (**n**) | Send frames and subtitles to Claude |
| `plan.fallback` | `generate_notes.py`, `refine_notes.py`, `context_notes.py` | y / n (**n**) | The Claude plan can't go on (its usage limit, the 5-hour session at 90%, or Claude Code missing or signed out) and no API credits are allowed for the run (`--api-fallback`): carry on with API credits? The text says what the rest would cost. A yes holds for the rest of the run (the later steps don't ask). With `--yes` the answer is no, and the run stops with what was written kept |
| `plan.allowance` | `generate_notes.py`, `refine_notes.py` | y / n (**n**) | The next API request would go past the run's `--api-fallback` allowance: carry on anyway? |
| `credit.continue` | `generate_notes.py`, `refine_notes.py` | y / n (**n**) | A balance is set (`usage.py`) and the next request is expected to cost more than what's left: carry on anyway? Asked once per run, between requests. With `--yes` the answer is no, and the run stops with what was written kept |
| `generate.resume` | `generate_notes.py` | p / s (p) | The last run stopped part-way: pick up where it left off, or start again |
| `refine.unreadable` | `refine_notes.py` | y / n (y) | The frames step couldn't read the reply for some stretches last time: send just those again (n sends nothing) |
| `refine.resume` | `refine_notes.py` | p / s (p) | The last refine stopped part-way: pick up, or start again from the notes as they were before it |
| `sync.unmeasured` | `context_notes.py` | y / n (y) | The sync couldn't be measured: treat as in sync? |
| `sync.drift` | `context_notes.py` | a / c / s (a, or c when re-timing isn't possible) | The timing drifts: re-time, carry on, or skip |
| `alignment.check` | `context_notes.py` | y / n (y) | Check every note's timing with speech recognition (slow) |
| `alignment.fix` | `context_notes.py` | y / n (y) | Move the stretches that are out, and rebuild |
| `notes.limited` | `context_notes.py` | a / s / n (a) | Notes cover only part of the video: add the rest (keeps them; sends only the rest), start again (sends everything), or keep them as they are |
| `notes.unreadable` | `context_notes.py` | y / n (y) | Claude's reply for some parts couldn't be read last time: send just those lines again (no frames step) |
| `folder.next` | `context_notes.py` | y / n (y) | One video stopped: go on to the next? |
| `tidy.move` | `tidy.py` | y / n (y) | Move the working files listed above into their `context-notes` folders |
| `embed.go` | `embed.py` | y / n (y) | Put the notes inside the films listed above (rewrites each; the original is kept) |
| `embed.delete` | `embed.py --delete-backups` | y / n (n) | Delete the kept originals listed (can't be undone) |
| `subs.download` | `context_notes.py` (y), `find_subs.py` (n) | y / n | Download subtitles from OpenSubtitles.com (uses a daily download) |
| `subs.transcribe` | `context_notes.py`, `find_subs.py` | y / n (n) | Write subtitles from the soundtrack with speech recognition |
| `api-key` | `make_ass.py --set-api-key` | input, hidden | Saved to `~/.config/context-notes/api-key`, mode 600 |
| `opensubtitles.api-key` | `find_subs.py --set-opensubtitles` | input, hidden | |
| `opensubtitles.username` | `find_subs.py --set-opensubtitles` | input | |
| `opensubtitles.password` | `find_subs.py --set-opensubtitles` | input, hidden | |

`alignment.check` only comes up in a GUI run. With no terminal and no GUI, the scripts skip that question, as they
always have, and print a hint about `--check-alignment` instead (unless Yes to all questions is on: then it's yes).

### Yes to all questions

With "Yes to all questions" on (Settings, `"yes_to_all"`; or `--yes-to-all`), `context_notes.py` sets
`CONTEXT_NOTES_YES_TO_ALL=1`, so every script the run starts sees it too. These questions are then answered without
asking, and no `question` event is sent for them; the log gets a line ending "(Yes to all questions)":

| id | Answer |
|---|---|
| `subs.download`, `subs.transcribe`, `sync.unmeasured`, `alignment.check`, `alignment.fix`, `notes.unreadable`, `refine.unreadable`, `folder.next`, `embed.go` | y |
| `notes.limited` | a (add the rest) |
| `generate.resume`, `refine.resume` | p (pick up) |
| `sync.drift` | its default (a, or c when re-timing isn't possible) |

It's a list (`prompts.YES_TO_ALL`), so a question added later is asked until it's put there. Sending
(`generate.send`, `refine.send`), API credits (`plan.fallback`, `plan.allowance`, `credit.continue`) and deleting
(`embed.delete`) are never on it.

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

## Cancelling

Cancel works like Ctrl-C in Terminal: send `SIGINT` to the run's whole process group.

- Start the run in a process group of its own. In Python that's `subprocess.Popen(..., start_new_session=True)`.
  To cancel, call `os.killpg(p.pid, signal.SIGINT)`.
- Signal the group, not just the process you started, because the step that's running needs the signal too.
- **On Windows**, which has no Ctrl-C one program can send to a group of others:
  - Start the run with `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`, and send
    `p.send_signal(signal.CTRL_BREAK_EVENT)`. The scripts treat Ctrl-Break as Ctrl-C when they're in json mode.
  - Run your program with a console (`python.exe`, not `pythonw.exe`), or Ctrl-Break can't be delivered.
  - A script that's waiting for an answer only notices Ctrl-Break once its read returns. If a `question` is
    pending, send an empty line too; the script stops before acting on it.

What happens then:
- **Notes Claude has already written are kept**, in `notes-<name>.partial.json`. The next run asks whether to pick
  up where it left off (`generate.resume`). Picking up is the default, and it sends only the rest.
- **A cancelled refine keeps the changes made so far**, and the notes file records where it stopped. The next refine
  asks whether to pick up there (`refine.resume`), which is the default.
- **Nothing is left half-written.** Caches, subtitle files, notes and the `.ass` are written all at once, so each
  is either the old version or the new one.
- **The same goes for a run that ends with no warning** (killed, the window closed, the power cut): the notes so
  far are saved after every request (`<notes>.partial.json`, or the notes file's `refined.stopped_after`), so the
  next run can pick up after the last request that finished.
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
