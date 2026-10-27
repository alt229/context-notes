# context-notes: rules and knowledge for every agent in this project

Pop-up notes for films and shows: idioms, slang, register, history and culture, wordplay, sight gags. They are
explained for a viewer who didn't grow up where the film was made. The notes are built into `<video>.notes.ass`
beside the video and shown in VLC (the extension is in `vlc/`). The owner is Erin. She watches mostly French,
German, Spanish and Japanese films, plus British comedy. What she values most is history and culture she wouldn't
know because the film is old or foreign.

Read `README.md` for the full command reference. This file holds what we've learned and the rules.

## Where things left off

Last updated 2026-10-27. Replace this section when a session changes the project (see rule 10).
It's the first thing to read when picking the work up on another computer or after losing the connection.

- **Nothing is committed.** `git status` shows the changed or new files on `master` (last commit `9789e942`). Ask Erin
  before committing.
- **Done on 2026-10-27:** the install's defaults. `settings.py` keeps them in `~/.config/context-notes/settings.json`
  (built-in defaults when the file is missing or damaged). The Settings page has a "Defaults for every run" section, and
  the page no longer remembers choices in the browser (the port changes each start). The Terminal scripts read the same
  defaults (`cli_defaults`, through argparse's `set_defaults`); the look is read by `make_ass.py` from `look_defaults`,
  so a film's saved look is never overwritten. Auto-send moved into Settings and is on by default (untick to be asked
  each time). "Remember starting folder" saves the folder you choose.
- **Done in this session:** `embed.py --convert` (an `.mp4` becomes an `.mkv`, and the `.mp4` goes to
  `context-notes/originals/`), the "already inside" check, the time and space warnings, the "Change or delete…" panel
  (delete kept originals, write the notes again), the run options for audience, effort and offline subtitles, the
  rebuild preview with a `.bak` kept on every rebuild and an optional re-embed, the new default audience ("Fluent in
  American English"), a probe cache, the background status check, and the docs and changelog to match.
- **Tested:** the full suite passes (`python3 -m pytest -q`), `ruff check .` is clean, and the page's script parses.
  The new dialogs have not been looked at in a browser yet.
- **Waiting on Erin:**
  0. Confirmed by Erin (2026-10-27): with no `--model`, scripts use Opus (the app's "best") and with no `--effort` they
     use high, where the Terminal used Sonnet before. Auto-send is on by default, with no warning gate; Erin chose this
     (2026-10-27), and the warning is in the Settings text. Untick it to be asked each time.
  1. The Plex copy `<film>.en.ass`: keep writing it, skip it on GUI rebuilds, or keep it and ask what Plex shows for
     IT Crowd (see Known pitfalls). There are 22 copies on the share, 19 of them for IT Crowd.
  2. The Akira rebuild, which waits on 1. Akira's `.ass` has no look line. A rebuild keeps the old file as a `.bak`,
     writes the Plex copy, and makes the Context Notes track inside `Akira.mkv` out of date. Re-embedding would
     rewrite the 2.8 GB film.
- **Ideas, not built:** store the look as a Matroska track tag (`CONTEXT_NOTES_LOOK`, which ffmpeg writes and ffprobe reads back,
  checked on a test file); add the min, max and settle timing to the `Look:` line; show the old box for files made
  before 0.2.0 (Akira's "now" column says "not recorded").
- **Not in the GUI yet:** `--window`, `--align-model`, and `find_subs.py --transcribe`.
- **Test media:** the temporary test folders on the NAS (`Movies/.embed-rewrite-test` and `TV Shows/.convert-test`)
  were deleted. Nothing in the library was changed.
- **New computer:** Python 3 with `pytest`, `ruff`, `numpy` and `pillow` in a virtual environment. `ffmpeg` and
  `ffprobe` are needed. MKVToolNix (`mkvpropedit`, `mkvmerge`) is installed here for checks; the code doesn't use it yet.
  The Media share is mounted
  at `/Volumes/Media`. The probe cache lives in `~/.config/context-notes/probe-cache/` and isn't in the repo.
- **Next step:** Erin's answer on the Plex copy, then a browser check of the new dialogs.

## The pipeline (one command per step; `context_notes.py` runs them all)

1. **Subtitles.** An `.srt` beside the video, or a track inside it. If there's none, `find_subs.py` looks in `Subs/`
   folders, then OpenSubtitles.com, then offers speech recognition.
2. **Sync.** `analyze.py SRT --video V --frames none --shift auto` fixes a constant offset. `--align` re-times with
   faster-whisper when the offset drifts (different cut).
3. **Dialogue notes.** Two routes:
   - The API: `make_ass.py --generate`, which costs credits.
   - The subscription: `chat_notes.py prepare`, then one reply per part, then `chat_notes.py collect`. In this
     project, `/notes` does this with the **note-writer** agent.
4. **Frame notes.** `make_ass.py --refine` uses the API only; there is no subscription route yet. It sends contact
   sheets of keyframes.
5. **Build.** `make_ass.py SRT NOTES --video V`. Repeats are left out (`dedupe.py`); timing and the box behind the
   notes come from the notes file's `timing` and `note_background`. The `.ass` header's `; Look:` line records the
   build (`make_ass.BUILD`), background and reading speed. `context_notes.py` rebuilds a finished video's `.ass`
   (free, no API key) when it's older than the notes or its look line is missing or different. Bump `BUILD` when
   a change to the build output should reach existing `.ass` files.
6. **Check.** `align_check.py V SRT` measures every note against the speech in the 10 s before it. `--fix` corrects
   stretches that are out.

## Decisions already made (with the evidence: project doc "benchmark-results.md")

- **Old-film rule (default, for every route).** A film more than 40 years old gets extra attention to words, people,
  phrases, places and the cultural mood of its period, where a generic viewer wouldn't get them. The year comes from
  `--year`, else the title, the file's tags, the file name, then the folder name (`generate_notes.find_year`). Without
  a year the rule is off. The notes file stores the year, so `--refine` uses the same one. The text is
  `generate_notes.OLD_FILM_RULE`, and it is in the dialogue prompt and the refine prompt. In `/notes`, when no year is
  found, Claude offers to look it up on the web (default yes) before it writes the notes.
- **Model choice.** Opus high on both steps is the safe default. Over six films it had the most valuable notes,
  0 to 2 wrong per film, and by far the most history and culture notes (99 valuable, 33 of them illuminating,
  against Sonnet high's 68 and 8).
  - Sonnet high is the budget option: about a third of the cost, with 6 to 11% wrong notes, mostly in the frame pass
    and mostly mixing up who's who.
  - Haiku is unusable for refine: half its on-screen notes describe things that aren't in the frames.
  - Fable costs about 3x Opus for nothing more.
  - Neither hybrid (Sonnet for one step, Opus for the other) is safe across titles.
  - Erin's plan: films she loves (Das Boot, Waking Ned Devine, Akira) get Opus high; British series (Blackadder,
    Red Dwarf) get Sonnet high.
  - `generate_notes.DEFAULT_MODEL` is still `claude-sonnet-5-5`. Pass `--model claude-opus-5-5 --effort high` for
    Opus.
- **Routing by the model's own confidence** isn't worth building. It would have to flag about 65% of notes to catch
  most errors.
- **Refine cost** is driven by frames (about 155k input tokens per 45 min). Denser frames cost proportionally more.
- **Note timing.** 2 s settle + 150 wpm (0.4 s a word), 6 s floor, 24 s ceiling. A note that appears while earlier
  notes are up gets half of each one's own time added, up to a 45 s total (`make_ass.linger`). At most three notes show at once, the one hard limit: a fourth note waits, and while it waits every note on
  screen gives up half a second of timer per second of wait (`make_ass.make_room`). The old 12 s ceiling cut 62 of
  Amélie's 100 notes short. Raising it added only 1.5 s of three notes on screen at once over the whole film. The
  settle, floor, ceiling and speed were changed on 2026-10-21 after friends found the notes too brief.
- **Refine and repeats** (Erin, 2026-10-24). Each refine stretch used to see only the notes inside it, so on
  Parasite the frames step explained the semi-basement flat at 0:43 and 1:35 (and a dialogue note did at 5:59), the
  corner-shop sign twice and the PC bang twice, 4 s apart. Now each stretch gets "Already explained earlier in the
  film": the last 100 earlier notes, the first 16 words of each (`refine_notes.earlier_notes`), and may drop an
  existing note that only repeats one. Not yet checked on a real run.
- **Note background** (Erin, 2026-10-24: "slightly or fully transparent"). Default `see-through` at 30% solid
  (`DEFAULT_OPACITY`, Erin's choice; `--note-opacity` / `note_opacity` changes it, and the `; Look:` line records
  it); `dark` is the old look (`&H38`, about 80% solid), byte for byte; `none` is outlined text. Renderers draw one box per line,
  and per stretch of a line in one colour or weight, padded by the Outline. Overlapping see-through boxes show
  darker bands, so see-through uses `\ybord0` (the lines' boxes just touch) and a one-colour label line ("(less
  sure)" in the label colour). Checked by rendering with libass (ffmpeg's `ass` filter) on bright, busy and dark
  frames.
- **"Alpha"** (Erin, 2026-10-24). The intro note of older notes files still says "Pre-alpha"; `make_ass.alpha_intro`
  shows it as "Alpha" at build time and leaves the file alone.
- **Credit and session meters** (Erin, 2026-10-25: "show the balance of credits as we process movies", for the API
  and for the session that resets every few hours, in the GUI too, and the week's totals).
  - **API credit is an estimate.** Anthropic has no endpoint for the prepaid balance (the Admin API is for
    organizations and only reports spending). So `usage.py` keeps a ledger of this tool's own requests
    (`~/.config/context-notes/usage.jsonl`, written in `generate_notes._call_api` through `_record_usage`, so
    generate, refine, bench and judge all count) and subtracts it from the balance Erin last gave
    (`usage.py --set-balance`, or the app's Settings). It leaves out other spending on the account. When the API says
    "credit balance is too low" the estimate goes to $0 (`usage.mark_empty`).
  - **The plan's session is not visible to the API.** Claude Code gives its status line `rate_limits.five_hour` and
    `seven_day` (`used_percentage`, `resets_at`) on Pro and Max, after the first reply. `.claude/statusline.py`
    saves them to `session.json` (and the highest use of each 5-hour window to `sessions.json`, for "sessions this
    week"); `usage.py --session` and the app read them back, and `/notes` repeats the reading after each part. It's
    switched on in `.claude/settings.local.json` (git-ignored; it holds her path). It only moves while Claude Code
    is open here, and a window that has reset since the last reading is shown as reset, never as the old figure.
  - **Stopping at the credit** (Erin: "do it now"). `usage.guard(assume_yes)` runs at the top of every request loop
    (generate and refine). It compares the balance with `next_cost()` (the average of this run's priced requests,
    else the plan's `per_request`), asks `credit.continue` once per run, and with `--yes` or no way to ask returns
    a stop message. Callers keep their partial notes (`keep_partial` / `stop_early`) and `sys.exit` with it. No balance
    set means no guard.
  - **`/notes` pause and learning** (Erin: "do it at 90%", "do it now"). `usage.py --session --stop-at 90` exits 3
    when the 5-hour window is that full; `--note-parts start|end` brackets a part and records the percentage it moved
    in `parts.jsonl` only when the window is the same and the figure moved; `--parts-estimate N` uses the median.
  - **Order matters:** `usage.report()` (the cost line and the `usage` event) goes after a part is counted and saved,
    never before. A Ctrl-C that lands as the part's line is printed must find the part in `notes`
    (`test_ctrl_c_in_a_terminal_keeps_the_notes_too` sends it at exactly that moment).
  - Tests use `CONTEXT_NOTES_USAGE_DIR` (autouse fixture `usage_dir`), so they never touch the real ledger. Any new test
    that runs a script inherits it.
- **Alignment check.** Speech recognition only, with a tolerance of 0.7 s and at least 2 recognised lines per window.
  - Subtitle makers time lines loosely: on Amélie's in-sync subtitles, a quarter of 10 s windows were more than
    0.6 s off.
  - Speech detection without words (Silero VAD, or loudness) was tried and dropped. On Amélie, which is in sync, it
    reported eight stretches out of step.
  - Tested on Amélie: a 3-minute stretch moved by 1.2 s was found (measured as 1.3 s), on both the French subtitles
    and the English ones measured through the French. After `--fix`, the re-check was clean.

- **Stopped runs pick up where they left off** (Erin, 2026-10-24). This covers an API error, Ctrl-C and Cancel.
  - The next run asks "Pick up where it left off?" (`generate.resume`, `refine.resume`). The default is yes, and
    `--yes` takes it.
  - Note-writing keeps its notes in `<notes>.partial.json`, with the last subtitle line covered. The file is used
    only for the same subtitle file, `--limit` and film language, and it's removed once the notes file is written.
  - Refine writes `refined.stopped_after` (time, part, parts, backup) into the notes file. `context_notes.py` treats
    that as unfinished. "Start again" restores the backup made before the stopped refine.
  - Both are also written after every finished request, not only on a stop, so a run killed outright (the window
    closed, a crash, the power) loses at most the request in flight (Erin, 2026-10-24: "save the amount of times
    the subtitles get sent").
  - Parts are made from the lines not covered yet (`chunks(rest)`), so picking up never sends a line twice. For a
    stopped run that's the same split as before, because a part starts from nothing either way.
- **Notes made with `--limit` are added to, not written again** (Erin, 2026-10-24). `notes.limited` offers "add
  the rest" (the default), "start again" or "keep these". Adding is `make_ass.py --generate --extend`
  (`generate_notes.notes_to_extend`): the notes file keeps everything it has (frame notes, `refined`, the look
  settings), gets a fresh intro note and a backup, and only the lines after the old limit are sent. Notes files now
  record their `subtitles`; a re-timed `.aligned` copy counts as the same. Refine then sees `refined.limit` short of
  what's asked and looks at only the rest, starting its parts at the old limit.
- **Unreadable replies are sent again, alone** (Erin, 2026-10-24). A part whose reply has no readable JSON is
  recorded in the notes file as `unreadable: [{lines: [first, last], reply}]` and its reply kept
  (`.part<k>.failed.txt`, never overwritten). `context_notes.py` then isn't "done": it asks `notes.unreadable` and
  runs `--generate --extend`, which sends only those lines (`generate_notes.unreadable_parts`), with the lines just
  before them as context and only earlier notes listed, and puts the new notes in film order
  (`insert_in_order`; the build looks for each quote from the note before it, so order matters). No sync check and
  no frames step for this. The partial file carries the list too.
  - The frames step records them as `refined.unreadable: [{from, to, reply}]` (video seconds). The next refine
    asks `refine.unreadable` and sends only the windows that overlap them; the refined record is kept as it was
    (`_save(record=...)`), and a stop then leaves no `stopped_after` (it would mean "pick up from 0:00"), only the
    stretches still to send. Declining sends nothing. Notes refine adds are pinned to a time or a line number, so
    their order doesn't matter.
- **Working files go in `context-notes/<video file name>/`** (Erin, 2026-10-24: working files "litter the movie
  folders"; she chose one shared `context-notes` folder per media folder, with a folder per video in it).
  - Beside the video stay only what players use: `.notes.ass`, the Plex `.en.ass` and real subtitles (hers, or ones
    `find_subs.py` found or downloaded). Everything else moves: the notes file and its `.bak`, report, partial and
    failed files; `.embedded`, `.aligned` and `.transcribed` subtitles; transcripts; chat files; `.ass.bak`; and the
    analysis, as `analysis/`.
  - `workfiles.py` decides. `folder()` is the new place. `place()` is where new files go: beside the video for a film
    an earlier version started (`started_before`), so such a film carries on exactly as before until `tidy.py`
    moves its files (Erin chose a tidy command over moving them on the next run). Reads look in both places
    (`notes_path`, `find`, `find_near`, `subtitle_files`); a name in both is the folder's copy.
  - New code that writes a working file uses `workfiles.place()` or `folder_for()`, never `video.parent`, and makes
    folders with `workfiles.make_dirs()`: the first time, it writes `IGNORE_FILES` into the context-notes folder
    (Plex `.plexignore`, Jellyfin/Emby 4.8 `.ignore`, Emby 4.9+ `.embyignore`; from their docs, 2026-10-24).
  - Checked by running the old and new code side by side on synthetic films (13 wrapper runs: same output,
    requests and files once the paths are mapped), and on films the old code started, untidied and tidied.
- **Notes inside the film: `embed.py`, `.mkv` only** (optional, both after a run (`--embed`) and as a tidy-style
  command for films that already have a `.notes.ass`). Erin, 2026-10-26: at first "leave the mp4s as is for now"; then
  an opt-in `--convert` (and the app's checkbox) that makes the `.mkv` and keeps the `.mp4` in `context-notes/originals/`.
  - ffmpeg stream copy adds the `.ass` as a track titled "Context Notes", language eng, with the `.notes.ass`'s SHA-1
    in a track tag (`CONTEXT_NOTES_SHA1`): that is how it knows a film is current, or needs its track replaced
    (never a second). Off by default (`-default_mode passthrough`, else the muxer flags a lone subtitle track default);
    `--default` turns it on. MP4 can only take `mov_text`, which loses the styling, so without `--convert` it is skipped.
  - `--convert` (`CONVERT_FROM`): the film is written as `<stem>.mkv` in one pass; kept `mov_text` tracks become
    `subrip` (`-c:s:N srt`, checked by `verify`). The `.mp4` goes to `context-notes/originals/<name>.mp4` (names are
    unique per folder); the film's `context-notes/<stem>.mp4` working folder moves to `<stem>.mkv`, so its notes are
    still found. Refused if a `.mkv` of that name, or the kept `.mp4`, is already there. `--delete-backups` also deletes
    the kept `.mp4` of a converted film that now has its notes.
  - Never edits the film in place: builds `context-notes/<film>/<stem>.embedding.mkv`, checks it (`verify`: track
    counts and codecs, existing subtitle tracks, chapters, length, size), then `swap_in` moves the original to
    `<stem>.original.mkv` (kept; a later update drops only the earlier embedded version) and renames the new file in,
    restoring the original if that fails. It needs the film's size in free space. `--delete-backups` only deletes
    originals of films that now carry the notes (`action == "current"`), and `--yes` there is the answer, not the default.
  - Skips: not `.mkv` (unless `--convert` makes it one), no `.notes.ass`, a symlink, or notes from a `--limit` run
    (`partial_notes`). `film_state()` gives the page one film's action and the look its `.ass` says it was built with.
  - Events (`embed-plan` with `convert` and `seconds_low`/`seconds_high`, `embed-video`, `embed-result`, `progress` task
    `embed`, `embed-backup`) and `rebuild-diff` (`context_notes.py --preview-rebuild`) are in docs/gui-protocol.md.
    The app's Embed button lists with `--dry-run`, then starts `embed.py --yes` as a job (`App.embed`, `/api/embed`).
    "Change or delete…" uses `App.backups` (`/api/backups`: a dry run lists kept originals, `go` deletes them as a job).
    The rebuild dialog calls `/api/rebuild-preview` (read-only), and its Go runs `/api/run`, with `--embed` if asked.
  - Time and space warnings use `READ_MBPS`/`WRITE_MBPS` (measured on this NAS during a scrub, 2026-10-26): a rough
    range, not a promise. ffprobe answers come from `analyze.ffprobe_json`, cached per file in
    `~/.config/context-notes/probe-cache/` (keyed on path, size, mtime and the options asked).

## Known pitfalls

- Frame timestamps: before 0.2.0, `analyze.run_ffmpeg_frames` paired showinfo times with written frames, and Homebrew
  ffmpeg's `vfr` mode dropped frames, so on-screen notes on Das Boot were up to an hour early (credits labelled 2:08
  in a 3:28 film). Fixed. Any notes file refined before then may have mistimed visual notes; the dialogue notes are
  fine.

- The sync check is unreliable under laugh tracks and music-heavy soundtracks (about ±1 s on Blackadder and Waking
  Ned Devine).
- Re-timing (`--align`) needs subtitles in the language being spoken. English subtitles on a German film can only
  be measured through the German ones (`--original-subs`).
- `bench/` runs store absolute paths in `cell.json`. Rewrite them if a run folder moves.
- Pre-existing lint warnings in `bench/` and `chat_notes.py` are known. Don't mix fixes for them into unrelated
  changes.
- **Unfinished: the Plex copy.** `make_ass.py` also writes `<video>.en.ass` (`plex_copy`) so Plex would label
  the notes "English (ASS)" instead of "Unknown". It looked right on S02E01–02, but Erin reports it doesn't work
  on IT Crowd Seasons 2–3 (2026-10-17). Not yet looked into: ask her what Plex shows before changing it.
- Notes attach to lines by quoting them (`match`). Re-timing a subtitle file keeps every line, so notes stay
  attached. Never renumber or drop lines in a file that has notes anchored by `cue`.

## Rules

1. **Never commit or upload media.** Videos, subtitle files, transcripts, `.ass` and `notes-*.json` of commercial
   films are copyrighted (see `.gitignore`). Media lives outside this folder. Ask Erin for the path, and expect a
   permission prompt to read it.
2. **Never spend API credits without a yes from Erin in this conversation.** That covers `--generate`, `--refine`,
   `bench.py` and `judge.py`. Each one prints a cost estimate first, so show it. `/notes` uses the subscription,
   not the API.
3. **API keys** live in `~/.config/context-notes/api-key` (mode 600). Erin prefers config files to environment
   variables. Never print a key.
4. **Originals are never changed.** Scripts write `.aligned.srt`, `.bak` and other new files into the video's
   working folder (`workfiles.place()`), never over the original. Keep it that way in new code.
5. **Test before saying it works.**
   - Run `python3 -m pytest -q` (no network, no API, synthetic clips) and `ruff check` on the files you touched.
   - For anything that measures audio or timing, also try it on real media and report the numbers.
   - Separate what you ran from what you inferred.
6. **Keep scripts runnable on their own.** Use the Python 3.9+ stdlib, plus numpy, Pillow and faster-whisper only
   where already used. Every step prints the command it runs.
7. **Ask through `prompts.py`.** New questions use `prompts.confirm`, `secret` or `text_input`, or
   `context_notes.ask(..., id=...)`. Never call `input()` or `getpass` directly, so a GUI can answer them. Give each
   question a stable id and add it to the table in `docs/gui-protocol.md`. Events go through `prompts.py` too, and
   never while a printed line is still open (`end=" "`).
8. **Write files all at once.** Anything a later run reads (caches, subtitles, notes, `.ass`) is written with
   `make_ass.write_text_safely()` or `make_ass.replacing()`, so Ctrl-C or a GUI's Cancel can't leave half a file.
9. **Write for Erin.** Plain English in messages and docs, and say what to do next. She runs macOS (Apple
   Silicon, Homebrew, Python 3.14) and works in Terminal. Her friends use the app on macOS, Windows and Linux.
10. **Update "Where things left off" before a session ends.** Any chat that changes this project rewrites that section
    in place: what changed, what's uncommitted, what was tested, what's waiting on Erin, and what's next. Replace
    stale lines rather than adding a log, and keep it short enough to read in a minute. Do this even when the session
    ends with a question instead of a change.

## The app (`app.py` and `gui/index.html`)

- A local web page for friends who don't use Terminal. It runs `context_notes.py` with `CONTEXT_NOTES_UI=json`
  (`docs/gui-protocol.md`) and shows the questions, the cost, progress and Cancel.
- Standard library only. One HTML file, with no external scripts, fonts or images.
- Security: it listens on 127.0.0.1 only, every request needs the random key, and `Host` and `Origin` are checked.
  The API key never goes to the page; it only shows the last 4 characters. Keep all of this when changing it.
- Defaults live in `settings.py` (`settings.json`). A new default goes in `BUILT_IN` and `KEYS` (what it allows), and
  is read in one of three places: `cli_defaults()` (flags left out, via `set_defaults` in `context_notes.py`),
  `look_defaults()` (`make_ass.py`), or `custom_audience()` (`generate_notes.py`). Never add a key that rewrites,
  deletes or changes a film's subtitles. Subtitle choices and the look of a film with saved notes stay per film.
- New options friends should reach go in the page's form, and in `common_args` / `App.run` in `app.py`. Options
  that change how a finished film looks (seconds a word, the background) go in `common_args`, so `--status`
  reports "Needs a rebuild" for them. Options that only affect new notes (`--audience`, `--effort`) or the run
  (`--offline`) also go there, but a rebuild ignores them. "Write the notes again" (`redo`) is never remembered.
- Rebuilds keep a backup of the `.ass` they replace (`keep_old_ass` → `<name>.notes.ass.bak`, `.bak2`, ...). The GUI
  shows the change first (`rebuild_diff` → `--preview-rebuild`), so keep that list in step with what a build writes.
- Windows runs natively (Erin, 2026-10-24: friends keep their media on NAS drives, which WSL makes a chore). WSL
  still works, through a small layer: Windows paths, `explorer.exe`, `vlc.exe`, and PowerShell file dialogs.
- Tests: `tests/test_app.py` (HTTP, whole runs, cancel). To look at the page, run it with `--api-url` pointing at the
  fake API from `tests/conftest.py` and open it in a headless browser.

## Windows

- **Cancel.** The app starts a run with `CREATE_NEW_PROCESS_GROUP` and sends Ctrl-Break. `prompts.py` turns that
  into KeyboardInterrupt in json mode. So:
  - Every script the app runs must `import prompts`, or Ctrl-Break kills it on the spot.
  - The app needs a console (`python.exe`, not `pythonw.exe`). Keep it that way in any launcher.
- **Blocking calls don't notice Ctrl-Break.**
  - Network requests wait through `generate_notes.wait_awake`.
  - A question that's waiting gets an empty line from the app's cancel.
- **Text.** Windows Python isn't UTF-8 by default. Pass `encoding="utf-8"` for subprocess output and for files that
  can hold non-English text. The app sets `PYTHONUTF8=1` for its runs.
- **Tests.**
  - Use `conftest.place` (a symlink or a copy), `assert_private`, `interrupt`, `NEW_GROUP` and `INTERRUPTED`
    instead of Unix-only calls.
  - `.github/workflows/tests.yml` runs Windows, macOS and Linux.
  - Tests that can't work on Windows say why in their `skipif`.

## Agents in this project

| Agent | Model | Job |
|---|---|---|
| `subtitle-prep` | Haiku | Find subtitles, run the sync and alignment checks, and summarise what the reports say. It runs scripts and reads their output; it doesn't write code. |
| `note-writer` | Opus | Write the notes for ONE part of a film (`chat_notes.py show`) as a JSON array, saved as `part-<k>.txt`. This replaces the API's `--generate` and runs on the subscription. |

Commands: `/notes <video> [options]` (subscription-written notes, end to end) and `/check <video>` (subtitles,
sync, alignment and repeats, with no API use).
