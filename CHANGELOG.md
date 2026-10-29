# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/)
(while pre-1.0, minor versions may change the notes format or command line).

## [0.2.0] - Unreleased

### Added
- "Yes to all questions" in Settings (and `context_notes.py --yes-to-all`, `make_ass.py --yes-to-all`): a run doesn't
  stop to ask about the work. It downloads subtitles, writes them from the soundtrack when none are found, checks and
  fixes new notes' timing, re-times subtitles that drift, picks up a stopped run, and goes on to the next video; each
  answer is in the log. It never answers sending to Claude, using API credits, or deleting. Off by default. The list
  is `prompts.YES_TO_ALL`, so a question added later isn't answered until it's put there.
- "Always download subtitles" in Settings (and `context_notes.py --download-subs`): when OpenSubtitles.com has
  subtitles for a film that has none, they're downloaded without asking. Off by default. The question itself now says
  what it's about (the film, the release, how often it's been downloaded).
- `app.py --hosted`: use the app from a phone or another computer on your network. It answers private addresses only
  (`--allow` adds a range), on port 8229 with a key kept between starts, and prints the address to use. Opening films
  in VLC, Show in folder, the file dialogs, installing the VLC extension, deleting kept originals and saving the API
  key or OpenSubtitles login stay on the computer running it (hidden elsewhere, and refused if asked for); the VLC
  extension can be downloaded from Settings instead. `--public` is for a server behind your own HTTPS proxy.
- `/refine` in Claude Code: the frames step on your plan, one stretch of the video at a time, by a frame-reviewer agent
  that opens each contact sheet itself. `chat_notes.py show-frames --part 0` begins (it analyses the video and keeps
  the notes as they are), `--part K` prints stretch K exactly as the API's frames step would send it (with the
  replies for the earlier parts applied), and `collect-frames` applies the replies the same way `--refine` does: the
  same notes for the same replies, a backup, a report of every change, and where it stopped, so `/refine` or
  `--refine` picks up there. A reply that isn't the JSON asked for is recorded and the rest applied.
- Notes written on your Claude plan by default, with no API credits. With a Pro or Max plan and Claude Code installed
  and signed in, `--generate` and `--refine` (and so `context_notes.py` and the app) send each part through Claude
  Code in the background (`claude -p`, in `claude_code.py`). It never sees the API key, the dialogue step gets no tools,
  the frames step can only open its contact sheets, and Claude Code's own extras are off (`--safe-mode`).
  `--route api` (or "API credits" in Settings) uses the API as before.
- When the plan can't go on (its usage limit, the 5-hour session at 90% when there's a reading, or Claude Code missing
  or signed out), a run carries on with API credits only if you allow it: `--api-fallback 5` or "Use API credits
  when the plan runs out, up to $5 a run" in Settings (also beside the run options, for one run); the amount counts
  for the whole run. Otherwise it asks once per run, showing what the rest would cost (`plan.fallback`), or stops
  when nobody can be asked. What was written is always kept, and the next run picks up.
- Settings starts with a "Claude" section: the route, the API-credit allowance, and whether Claude Code is installed
  and signed in ("Check Claude Code again"). The banner and "Before you start" say what's missing for the route in use.
- The Plan meter stays current: every request on the plan brings back the plan's 5-hour and 7-day figures (Claude
  Code's stream-json `rate_limit_event`), which also feed the 90% stop, and clicking the meter gets a fresh reading
  (one tiny Haiku request on the plan). "seen 1611 min ago" now reads "seen 27 h ago".
- `usage.py` records requests on the plan too (tokens, no dollars, `"route": "plan"`), keeps them out of the credit
  estimate, and shows how much of the 5-hour session is used after each part when Claude Code has given a reading.
- Defaults for this install, in Settings ("Defaults for every run"): the model, thinking effort, who the notes are for,
  the language to write them in, seconds a word, the box and how solid it is, frames, the timing check, online subtitle
  search, subfolders, the starting folder, and the auto-send choice. They're kept in
  `~/.config/context-notes/settings.json`, and the Terminal scripts read the same file, so both start from the same
  choices. A missing or damaged file gives the built-in defaults. A film's own saved look and audience still win, and
  choices that rewrite or delete files, or that change which subtitles a film shows, are never defaults.
- "Remember starting folder": the folder you choose opens next time (on by default; turn it off and the app opens
  empty).
- `embed.py` puts a film's notes inside the `.mkv` as a "Context Notes" subtitle track (ffmpeg copies every track,
  nothing is re-encoded). Works on any film with a `.notes.ass`, like `tidy.py`: a folder, `--recursive`,
  `--dry-run`, `--yes`, plus `--default` and `--delete-backups`. The new file is checked before it replaces the film;
  the original is kept in `context-notes/<film>/`. `.mp4` is skipped (MP4 can't hold ASS without losing its
  styling), and so are notes from a `--limit` run. `context_notes.py --embed` does it after the notes are done.
- `embed.py --convert` (and "Also convert MP4 films to MKV" in the app): an `.mp4` with notes is rewritten as an `.mkv`
  in one pass, its `mov_text` subtitles become SRT, and the `.mp4` is kept in `context-notes/originals/`. The film's
  working folder follows the new name. It's refused when an `.mkv` of that name is already there. Media servers may
  list a converted film as new.
- Embedding says whether a film is already inside its `.mkv`, and the app's film cards show "Inside the film" with the
  look the notes were built with. The Embed prompt only lists films that need adding or updating.
- Embed and rebuild warnings give the time (a rough range from this NAS's measured read and write speeds), the space,
  the copy kept, and that no Claude or API call is made.
- "Change or delete…" in the app: delete kept originals (a dry run lists them first) and write the notes again (the old
  notes are kept as `.bak`). Each has its own Go button.
- Run options in the app: "Who the notes are for" (`--audience`), "Thinking effort" (`--effort`) and "Don't search
  online for subtitles" (`--offline`).
- Every rebuild keeps the `.notes.ass` it replaces as `<name>.notes.ass.bak` (`.bak2` and so on for later ones). Before a
  rebuild the app shows what changes (`context_notes.py --preview-rebuild`): the box, opacity and speed now and after,
  the subtitles, and the files written. Its dialog can also put the new notes inside the `.mkv` (`--embed`).
- ffprobe's answers are cached in `~/.config/context-notes/probe-cache/`, keyed on each file's path, size and time, so
  a film on a NAS is read once.
- The app's status check runs in the background and the page polls for it, so a slow folder no longer hits the old
  120-second limit (it now allows an hour).
- `usage.py`: what the API calls cost, and the credit probably left. Every finished request is written to a ledger
  (`~/.config/context-notes/usage.jsonl`) with its tokens and cost; `usage.py --set-balance 25` (or `--add-credit`)
  gives it the console's figure, and the estimate counts down from there. Each request prints one line
  (`$0.03 (run $0.11, film $0.42) · about $17.82 left`), the plan line says what's left and warns when a run may
  outspend it, and the last line gives the film's total across steps. It warns below $2 (`--low`). When the API says
  the credit is out, the estimate goes to $0 and the message says where to add credit. `usage.py` alone shows the
  summary (spending today, this month and per film); `--json` gives it to other programs.
- The Claude plan's session (the 5-hour and 7-day windows of Pro and Max): `.claude/statusline.py` is a Claude Code
  status line that saves what Claude Code reports to `session.json` and shows
  `[Opus 4.5] 5h 42% (resets 8:10 PM) · 7d 18% · API ~$17.82`. `usage.py --session` reads it back, and `/notes` repeats
  it after each part. It is switched on in `.claude/settings.local.json` (not committed).
- The week at a glance: `usage.py` adds API spending and requests over the last 7 days, the plan's 7-day figure, and
  how many 5-hour sessions the status line has seen this week (and the busiest one's peak); the app shows them under
  Settings, "This week", and the plan meter adds the week's percentage.
- It stops before the credit runs out: before each request `generate_notes.py` and `refine_notes.py` check the estimate
  against what a request is costing, and when the next one would go under $0 they ask `credit.continue` (Carry on
  anyway / Stop here, once per run); with `--yes` they stop. Finished parts are kept and a rerun picks up.
- `/notes` pauses at 90% of the 5-hour session (`usage.py --session --stop-at 90` exits 3), and measures what each
  part costs as a share of the session (`usage.py --note-parts start|end`, saved in `parts.jsonl`) so it can estimate
  a film up front (`usage.py --parts-estimate N`).
- The app shows both: an API credit meter and a plan session meter in the header, a Settings section to enter the credit
  left, and the credit left in the cost question (with a warning when the run may cost more). `GET /api/usage`,
  `POST /api/credit`, a `usage` event, and `balance_usd` in the `estimate` event (`docs/gui-protocol.md`).
- `tidy.py FOLDER [--recursive] [--dry-run] [--yes]` moves the working files earlier versions left beside the
  videos into their `context-notes` folders. It lists them first and asks (`tidy.move`); files are moved as they
  are, never overwritten, and one that could belong to two videos stays put. `context_notes.py --status` says
  which videos have such files, and the `status` event has `tidy` (how many). The app shows a Tidy button for
  them: it lists what would move, then moves it (`/api/tidy`; `tidy`, `tidy-skip` and `tidy-done` events).
- `context_notes.py --reading-speed WPM`, `--note-background` and `--note-opacity`, passed to every build.
- The app has "On screen": how long notes stay up, in seconds a word (sent as `--reading-speed`; empty keeps each
  film's own), what's behind the notes, and how solid the see-through box is. A finished film whose `.ass` needs only a rebuild shows "Needs a
  rebuild", and the button says "Rebuild (free)".
- `prompts.py`, the groundwork for a GUI. With `CONTEXT_NOTES_UI=json` set, every question, hidden prompt (API key,
  OpenSubtitles login) and cost estimate is written as one JSON line on stdout and answered on stdin, through every
  script a run starts. Without it, the scripts ask exactly as before. See `docs/gui-protocol.md`.
- Windows, natively, without WSL. Network drives and shares work as they are. Cancel works through Ctrl-Break, and
  it works mid-request too (requests wait in a helper thread on Windows). Text from ffmpeg/ffprobe and the
  `analysis.json` and `alignment.json` files is always read and written as UTF-8. The app's folder browser shows the
  drive letters, and the install hints name the right tool (winget, Homebrew or apt). Setup steps are in the README.
- The tests run on Windows, macOS and Linux in GitHub Actions on every push (`.github/workflows/tests.yml`).
- The app sends the cost question's "Send to Claude" by itself after 10 seconds, counting down on the button. Wait
  stops the countdown; a checkbox under Write the notes turns it off (remembered by the browser).
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
- The app's page is kept in parts in `gui/src` (the frame, styles, one HTML file per dialog, scripts by section), which
  `app.py` joins each time the page is asked for: one copy, nothing to rebuild, and the browser gets the same page,
  byte for byte. `gui/index.html` is gone; see `gui/README.md`.
- The code is split into modules, so each job lives in one place: `claude_api.py` (the API key, requests and prices),
  `sending.py` (the estimate, the question and the part-by-part loop that `--generate` and `--refine` share),
  `cli_common.py` (the options `context_notes.py` and `make_ass.py` share), `fileio.py`, `subtitles.py` and
  `timecode.py`. `generate_notes.generate()` and `refine_notes.refine()` are cut into named steps. Nothing a run does
  has changed: the same output, requests and files on every comparison run. Old names still work. In `--help`, the
  look options are together in `make_ass.py` and the effort default is given correctly in `context_notes.py`;
  `make_ass.py --reading-speed 0` now gives the same message as `context_notes.py`.
- `make_ass.py` typed in Terminal also takes the model and effort from Settings (Opus, high unless changed), where it
  used Sonnet before. The effort is left out for Haiku 4.5, which rejects it, so an effort from Settings never stops a
  Haiku run.
- The Terminal scripts take their defaults from Settings, so they match the app. With no `--model` they now use Opus
  (the app's "best"), where they used Sonnet before, and with no `--effort` they use high. Set Settings to Cheaper, or
  pass `--model claude-sonnet-5-5`, to keep the old choice.
- The app no longer remembers the form in the browser (the port changes each start, so it was lost). Choices are saved
  as defaults in Settings instead. "Send 10 seconds after showing the cost" moved there and is on by default: notes are
  sent after 10 seconds unless you press Don't send. Untick it to be asked each time.
- The default "who the notes are for" is "Fluent in American English" (films in English; films in another language keep
  their own default).
- "Write the notes again" moved into "Change or delete…", and it's no longer remembered between sessions, so it can't
  stay ticked by accident.
- A reply Claude sends that can't be read no longer loses that part's notes for good. Its lines are recorded in the
  notes file (`unreadable`, with the saved reply); the next run asks (`notes.unreadable`) and sends just those lines
  again, with the lines before them for context and only the notes before them, and puts the new notes in film
  order. No sync check or frames step is repeated. By hand: `make_ass.py ... --generate --extend`. `--status` and
  the app say so, and such a video isn't "done". A saved reply is never overwritten (`.part<k>.failed2.txt`).
  The frames step does the same: a stretch whose reply can't be read is recorded (`refined.unreadable`, with the
  times), and the next refine asks (`refine.unreadable`) and sends just that stretch, keeping the rest of the
  record; declining sends nothing.
- Working files no longer litter the video's folder. Beside the video stay only the `.notes.ass`, its Plex copy and
  real subtitles; the notes file and its backups, reports, pulled-out and re-timed subtitles, transcripts, chat
  files and the analysis go in `context-notes/<video file name>/` (`workfiles.py`), with the analysis in
  `analysis/` there. A film an earlier version started carries on beside the video as before until `tidy.py`
  moves its files in, and every script finds files in either place. Each `context-notes` folder gets `.plexignore`,
  `.ignore` (Jellyfin, Emby 4.8) and `.embyignore` (Emby 4.9+), so media servers skip it; one already there is kept. Commands are printed with paths relative to
  the video's folder. The app's folder browser doesn't list `context-notes` folders.
- What's done is saved after every request, not only when a run is stopped: a run that ends with no warning (the
  window closed, a crash, a power cut) can pick up after the last request that finished, so what was paid for
  isn't sent again.
- Notes made with `--limit` are added to instead of written again. When a later run wants more of the film,
  `notes.limited` offers "add the rest" (the default; also what `--yes` does), "start again" or "keep these". Adding
  keeps the notes and everything else in the file, and sends only the lines after the old limit; the frames step
  then looks at only the rest of the video too. By hand: `make_ass.py --generate --extend`. Notes files now record
  the `subtitles` they were written from.
- `--refine` tells each stretch of the video what earlier notes already explain (a short line each: the dialogue
  notes and the ones added in earlier stretches), and asks for one note per thing. It may now also drop an existing
  note that only explains again something explained earlier. On Parasite, the semi-basement flat was explained three
  times in six minutes (twice by the frames step), and a sign and the PC bang twice, because each stretch only saw the
  notes inside it. Requests get a little bigger: up to about 3,000 tokens each on a long film.
- The box behind each note is now see-through: 30% solid (it was about 80%). `--note-background` picks
  `see-through` (the default), `dark` (the old look, exactly) or `none` (no box: outlined text, like the dialogue),
  and `--note-opacity` sets how solid the see-through box is (0 to 100), on `make_ass.py` and `context_notes.py`.
  Both are remembered in the notes file (`note_background`, `note_opacity`). In the see-through
  box, the lines' boxes only touch, so they don't overlap into darker bands, and "(less sure)" is in the label's
  colour instead of pink, because a second colour on the label line gave it a darker block.
- "Alpha", not "pre-alpha": new notes open with "Alpha context notes written by Claude ...", and older notes files
  show it that way when built (the files themselves aren't changed). The README, CONTRIBUTING and the VLC extension
  say alpha too.
- `context_notes.py` rebuilds a finished video's `.ass` for free when only the `.ass` is out of date. It's out of date
  when it's older than the notes, built by an older `make_ass.py`, or built with a different look from the one asked
  for. Every `.ass` now has a `; Look:` line at the top (build, background, reading speed) to tell. Such a rebuild
  needs no API key, doesn't look for subtitles again and doesn't ask about the timing check. `--status` says "needs
  rebuilding (free)", and the `status` event has `rebuild`. The first run after updating rebuilds each finished
  video once. `make_ass.py` options that aren't remembered (`--layout stack`, `--keep-duplicates`) need giving again.
- At most three notes on screen (the one hard limit). A fourth note waits until the earliest note leaves; while it waits,
  every note still on screen gives up half a second of timer per second of wait. The build reports how many notes waited.
- A note that appears while earlier notes are still on screen stays up longer: half of each earlier note's own time is added. A note's own time is still capped at 24 s, and the total is capped at 45 s (`LINGER_CEILING`).
- Notes stay up longer: 2 s to notice, then 150 words a minute (0.4 s a word), kept between 6 and 24 s
  (was 180 a minute, 5 to 18 s). Change it per film with `--reading-speed`, `--note-min` and `--note-max`.
- One install step: `pip install -r requirements.txt` now covers everything, including faster-whisper for speech recognition. The separate `requirements-align.txt` and `requirements-dev.txt` are being removed.
- Notes stay up longer when they're long: the ceiling went from 12 s to 18 s (it cut 62 of Amélie's 100 notes
  short). Same 180 words a minute and 5 s floor.

### Fixed
- Embed (and `--convert`) failed on an MP4 with a phone's or camera's timecode track: "Only audio, video, and subtitles
  are supported for Matroska". That track is now left out of the copy, and the list, the prompt and the page say how
  many were left out. Nothing else changes.
- The app's page stopped as it loaded (a leftover handler for the old "remember my choices" code), so nothing on it
  worked. A test now checks that every handler and element the page's script uses exists.
- Embed offered films whose notes were already inside them. It now says so, and only offers films that need the notes put in.
- Choosing other subtitles to show at the bottom (`--show-subs`, "Subtitles shown at the bottom" in the app) on a
  finished film did nothing in the app: the film counted as done, so the button was off. `--status` now counts
  it as a free rebuild ("needs rebuilding (free) to show the English subtitles"), and the page checks again
  when that choice changes.
- The app's "Full title (one film only)" field is hidden when a folder is chosen, as it was meant to be.
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
