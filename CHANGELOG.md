# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/)
(while pre-1.0, minor versions may change the notes format or command line).

## [0.2.0] - Unreleased

### Added
- Claude on your subscription, with no API key: `--backend claude-code` (or once, `make_ass.py --set-backend
  claude-code`) runs every request through the installed Claude Code command (`claude -p`) instead of the API, for
  writing notes, the frame pass, `context_notes.py` and the app (Settings → Where Claude runs). The frame pass gives
  Claude Code the contact sheets to open with its Read tool. The estimate shows the size in tokens and "on your Claude
  subscription" instead of a price; the notes file records `"backend": "claude-code"`. `--backend api` and the saved
  key work as before.
- The frame pass on your Claude subscription, inside Claude Code. `/refine "<video>"` runs a frame-reviewer agent
  (Opus) once per stretch of the video; it opens the contact sheets, adds on-screen notes and fixes the dialogue
  notes the frames show to be wrong. Behind it, `chat_notes.py show-frames VIDEO SRT --part K` prints one stretch
  for the agent (`--part 0` prints how many there are and the mode), and `chat_notes.py collect-frames VIDEO SRT
  DIR` applies the `frames-<k>.txt` replies the way `make_ass.py --refine` applies the API's: a backup of the notes
  and the `.ass`, a report of every change, and if a part's reply is missing the run stops there and the next one
  picks up. Replies that aren't the JSON object asked for are kept as `<notes>.frames<k>.failed.txt`. `/notes` now
  offers `/refine` before the API route.
- `prompts.py`, the groundwork for a GUI. With `CONTEXT_NOTES_UI=json` set, every question, hidden prompt (API key,
  OpenSubtitles login) and cost estimate is written as one JSON line on stdout and answered on stdin, through every
  script a run starts. Without it, the scripts ask exactly as before. See `docs/gui-protocol.md`.
- `app.py`: the whole workflow in your web browser, on your computer only: `python3 app.py`. Choose a film or folder,
  pick the quality, see the cost and answer questions on screen, follow the progress, cancel, and open finished videos
  in VLC. Settings saves the API key and OpenSubtitles login and installs the VLC extension. It works on macOS and
  Linux, and on Windows through WSL. Standard library only; it listens on 127.0.0.1 and needs the random key in its
  address. `context_notes.py --status` also sends a `status` event per video for it.
- Progress for a GUI (with `CONTEXT_NOTES_UI=json`): `progress` events from the soundtrack check, frame pulling,
  speech recognition and each API request, plus `video`, `step` and `video-result` events from `context_notes.py`.
  A GUI cancels a run by sending SIGINT to its process group, as Ctrl-C does. See `docs/gui-protocol.md`.
- Picking up where a stopped run left off. When writing notes or refining stops part-way (an API error, Ctrl-C or a
  GUI's Cancel), the next run asks "Pick up where it left off?". The default is yes, and only the rest is sent. You
  can also start again; for a refine, that starts from the notes as they were before it. `--yes` and unattended
  runs pick up.
- `make_ass.py --generate --estimate-only` and `--refine --estimate-only`: show the size and cost estimate, then
  stop. Nothing is sent, no API key is needed, and no notes, `.bak` or `.ass` are written.
- `dedupe.py`, and on every build: notes that explain something an earlier note already explained are left out of
  the `.ass` (the notes file is untouched). `--keep-duplicates`, or `"keep": true` on a note, keeps them.
- Note timing settings: `--reading-speed`, `--note-settle`, `--note-min`, `--note-max` (remembered in the notes file
  as `timing`), and `--timing-report` (seconds a word per note, which notes the ceiling cuts short, and the dialogue
  subtitles' own pace for comparison).
- `align_check.py`: checks every note against the speech in the 10 s before it (speech recognition, transcript cached
  and shared with `analyze.py --align`); translated subtitles are measured through the original-language ones. Reports
  stretches that are out and `--fix` writes `<name>.aligned.srt` with only those stretches moved.
  `context_notes.py --check-alignment` runs it (also on videos already done) and offers the fix and a rebuild.
- `find_subs.py`, and in `context_notes.py` when a video has no subtitles: looks in `Subs/` folders and at
  differently named files for the same film, then OpenSubtitles.com (with a saved login; the copy made for the exact
  file first), then offers to write subtitles with speech recognition. `--offline` skips the online search.
  `--test-opensubtitles` logs in with the saved login and shows today's downloads left, without using one;
  `--set-opensubtitles` runs the same test after saving.
  `--limit 10:00` runs speech recognition on only the first part, to try it quickly.
- `chat_notes.py show` prints one part (instructions, context, topics already covered) for an agent to annotate;
  `collect` accepts a folder of `part-<k>.txt` replies.
- Claude Code project files: `CLAUDE.md`, `.claude/agents/` (subtitle-prep, note-writer), `.claude/commands/`
  (`/notes`, `/check`).

### Changed
- The shared helpers that had grown inside `make_ass.py` and `generate_notes.py` now have their own files:
  `timecode.py` (reading and writing times), `subtitles.py` (reading SRT files and finding the line a note
  quotes), `fileio.py` (writing files all at once, reading odd encodings, the settings folder) and
  `claude_api.py` (the API key, one request with retries, the price table). Every script and test uses the new
  files directly. The old names still work (`make_ass.parse_srt`, `make_ass.write_text_safely()`,
  `generate_notes.load_key`, `generate_notes.DEFAULT_MODEL` and the rest are re-exported, with a comment
  saying where they went), so your own scripts and the docs' examples keep running. Nothing changes in what
  the scripts do or write.
- The flags the scripts share (`--limit`, `--film-language`, `--original-subs`, `--title`, `--year`, `--audience`,
  `--notes-language`, `--model`, `--effort`, `--api-key-file`, `--yes`, `--frames` and the speech model) are
  defined once, in `cli_common.py`, which also passes them on from `context_notes.py` to the steps it runs. Every
  flag keeps its name and default; `--help` wording is now the same from script to script, and `chat_notes.py`
  gained the full help texts (its `--limit` is checked as `TIME`, like the others). Behind `make_ass.py --generate`
  and `--refine`, `generate_notes.generate()` and `refine_notes.refine()` are now short orchestrators over
  separate steps that can be tested and reused on their own: `plan_generate` / `plan_refine` (everything up to
  and including the cost estimate), `confirm_generate` / `confirm_refine` (the "send?" question),
  `generate_part` / `refine_window` (one request each, the only place that talks to Claude; the contact sheets
  are passed as file paths and encoded only at the API call) and `write_notes_file` / `finish_refine`. What
  they print, ask and write is unchanged.
- The app's page is now built from sources in `gui/src` (styles by layer, one markup partial and one script per
  section) by `gui/assemble.py`, which writes the single self-contained `gui/index.html`. See `gui/README.md`.
- At most three notes on screen (the one hard limit). A fourth note waits until the earliest note leaves; while it waits,
  every note still on screen gives up half a second of timer per second of wait. The build reports how many notes waited.
- A note that appears while earlier notes are still on screen stays up longer: half of each earlier note's own time is added. A note's own time is still capped at 24 s, and the total is capped at 45 s (`LINGER_CEILING`).
- Notes stay up longer: 2 s to notice, then 150 words a minute (0.4 s a word), kept between 6 and 24 s
  (was 180 a minute, 5 to 18 s). Change it per film with `--reading-speed`, `--note-min` and `--note-max`.
- One install step: `pip install -r requirements.txt` now covers everything, including faster-whisper for speech recognition. The separate `requirements-align.txt` and `requirements-dev.txt` are being removed.
- Notes stay up longer when they're long: the ceiling went from 12 s to 18 s (it cut 62 of Amélie's 100 notes
  short). Same 180 words a minute and 5 s floor.

### Fixed
- Stopping speech recognition part-way (Ctrl-C) left half a transcript in the `<video> analysis` folder, and the
  next run used it as if it were the whole film. The transcript is now saved only once it's complete. If you ever
  stopped `--align` or the alignment check part-way, delete that video's `transcript-*.jsonl` file.
- Ctrl-C while Claude was writing notes threw away the notes already written (and paid for). They're now kept in
  `notes-<name>.partial.json`, as they already were after an API error, and the next run offers to pick up there.
- A refine that an API error stopped part-way was marked as finished, so `context_notes.py` reported the film as
  done and never finished the refine. It's now marked as stopped (`--status` says "refine stopped part-way"), and
  the next run offers to pick up. Ctrl-C and Cancel now keep a refine's changes so far too.
- Caches, subtitle files, notes and the `.ass` are written all at once, so a stop at the wrong moment can't leave
  half a file for the next run to trust. The old file's permissions are kept.
- `context_notes.py` gives the running step time to tidy up after Ctrl-C (up to 10 s instead of Python's 0.25 s).
- The tests no longer stop at a hidden "Paste your Anthropic API key" prompt when run in Terminal.
- `chat_notes.py collect` no longer drops the first or last note of a pasted reply block (the part-header pattern
  matched into the JSON braces). `collect` also prints how many repeated explanations the build will leave out.
- On-screen notes (Prop, Costume, Staging, On-screen text...) could be timed far too early, more so the later in the
  film: ffmpeg's `vfr` mode dropped frames after their times had been listed, so every frame after a drop carried an
  earlier frame's time. On Das Boot (3:28) the end credits were labelled 2:08. Frames are now extracted with
  `passthrough`, checked against the times, and labelled from ffprobe's keyframe list if the two ever disagree.
- `context_notes.py` no longer follows a symlinked video to its target folder (subtitles and notes are looked for
  beside the link).
- When re-timing with speech recognition places fewer than half the lines, `context_notes.py` carries on with the
  original timing instead of an almost empty subtitle file.

## [0.1.0] - Unreleased

First public version.

### Added
- `make_ass.py`: merge an SRT with a notes JSON into a boxed-overlay `.ass`; split (speech left, visual right) or stacked layout; creates a blank notes file on first run.
- `make_ass.py --generate`: Claude writes the notes from the dialogue (cost estimate and confirmation first; key stored in `~/.config/context-notes/api-key`).
- `make_ass.py --refine`: Claude re-checks notes against video frames and loud moments, adds visual and delivery notes, retimes and corrects; backs up the notes, the old `.ass`, and writes a change report; records the measured subtitle offset.
- `analyze.py`: numbered transcript; extraction of embedded subtitles from MP4/MKV; sync check, loud moments and contact sheets with `--video`; `--align` to re-time subtitles with faster-whisper.
- `vlc/context_notes.lua`: VLC extension that loads `<video>.notes.ass` and filters notes by topic.
- Safety checks: episode-code mismatch guard, visual-only fallback when subtitles are out of sync, quote re-anchoring to the right line.
- Test suite (no network or real media needed) and CI.
- `context_notes.py`: one command for a video or a folder. Finds subtitles (beside the video or inside it), checks sync and offers `--align`, runs `--generate` and `--refine`, builds the `.ass`, skips what's done; `--status`, `--yes`, `--redo`, `--no-refine`, `--show`.
- `--limit TIME` on `analyze.py`, `make_ass.py --generate/--refine` and `context_notes.py`: work on the first part of a video only. Recorded in the notes file; limited alignments and transcripts get their own file names.
- Foreign-language films: `--film-language` (prompts for translation loss, register, slang, dialect, untranslated on-screen text), `--original-subs` (Claude compares the subtitles you read with the original-language ones), `analyze.py --sub-lang` to extract a track by language, and `--align` in other languages (multilingual speech model).
- `analyze.py --shift auto|SECONDS`: fix subtitles that are early or late by a constant amount; writes `<name>.aligned.srt` and leaves the original alone. `context_notes.py` does this automatically when the sync check finds a constant offset (for the original-language subtitles too).
- For films not in English, `context_notes.py` now defaults to the film's own-language subtitles, with notes in English that quote the original and explain idioms, register, slang and references (`--subs-language en` for English subtitles compared against the original).
- `--show-subs LANG` (`context_notes.py`) and `--display-subs SRT` (`make_ass.py`): show different subtitles on screen (e.g. English) while the notes stay placed on the ones they were written from (e.g. French); remembered in the notes file. The shown file is timed against the main subtitles, not the soundtrack.
- New note categories: `Translation`, `Register`, `Slang`, `Dialect`, `On-screen text` (colours and VLC topics).
- The soundtrack measurement is cached per video, so `--refine` after a sync check is quicker.

### Fixed
- Accented file names (é stored as e + accent mark by some downloads) now match their subtitles and notes.
- Sync patterns: a subtitle line ending before 0:00 no longer marks the whole timeline as "on screen".

### Changed
- `.aligned.srt` files now use standard SRT times (`00:00:03,880`, millisecond precision).
- Quote matching and `--align` ignore accents (`été` matches `ete`, `Straße` matches `Strasse`).
- `make_ass.py --generate --offset N` records the offset in the notes file.
- VLC extension 0.2.4: the new categories appear under "Language, slang & wordplay" and "Sight gags, staging & on-screen text".
