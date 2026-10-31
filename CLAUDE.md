# context-notes: rules and knowledge for every agent in this project

Pop-up notes for films and shows: idioms, slang, register, history and culture, wordplay, sight gags. They are
explained for a viewer who didn't grow up where the film was made. The notes are built into `<video>.notes.ass`
beside the video and shown in VLC (the extension is in `vlc/`). The owner is Erin. She watches mostly French,
German, Spanish and Japanese films, plus British comedy. What she values most is history and culture she wouldn't
know because the film is old or foreign.

Read `README.md` for the full command reference. This file holds what we've learned and the rules.

## Where things left off

Last updated 2026-10-30. Replace this section when a session changes the project (see rule 10).
It's the first thing to read when picking the work up on another computer or after losing the connection.

- **The repo:** this folder is part of Erin's larger repo in `~/.alt229/`; its `.git` isn't visible from the connected
  folder. Leave changes in place and Erin commits them herself (2026-10-30); friends get them with `git pull`.
  Erin publishes with her shell alias `context-notes_publish`, which updates both repos (the `~/.alt229` one and
  github.com/alt229/context-notes); no session needs to touch remotes.
- **Windows (2026-10-30, not committed):** a friend on Windows hit trouble; the fixes are in place, see
  CHANGELOG "Fixed": `prompts.py` makes stdout/stderr never raise on a pipe (`errors="replace"`) and defines
  `PYTHON` ("python" on Windows) for printed hints; `tests/conftest.py` and `tests/test_prompts.py` redirect
  `USERPROFILE` as well as `HOME`; `.claude/settings.json` has a `python` twin for every `python3` allow entry and
  the commands/agents say to use `python` on Windows; `bench.py` falls back from symlink to hard link/copy; the
  transcript cache is explicit UTF-8; README's Windows list gained key-file permissions and long paths. Ruff clean;
  the suite passed in Claude's Linux VM (one cancel-timing test flaked once under load, passed on rerun). `~/.config`
  on Windows is **not** a problem: `Path.home()` is `%USERPROFILE%` there. The stale early-October copy in
  `~/Documents/Claude/Projects/` is now `...-ARCHIVE`; ClaudErius's "two remotes" plan was based on it and is withdrawn.
- **Committed:** Erin committed step 1 (the modules) on 2026-10-27. Steps 2 to 5 below are not committed yet. Ask Erin
  before committing, and never push (`.claude/settings.json` denies it).
- **In progress: the ideas from PR #1, done our way** (the plan is the project doc `claude/pr1-plan.md`; none of the
  PR's code is used). All 5 steps are done:
  1. The modules (see "Where the code lives"); `make_ass.py` by hand takes the model and effort from Settings too.
  2. The plan by default (`--route plan`, Settings "Claude"): both steps through Claude Code in the background, with
     `--api-fallback USD` ("Use API credits when the plan runs out, up to $___ a run") or the `plan.fallback` question,
     and the 90% stop. Tried against the real Claude Code 2.1.311 in the cloud workspace (two tiny requests: text,
     and a contact sheet opened with Read). Not yet run on Erin's Mac: her first real run on the plan is the check.
     A separate review of the money paths found and fixed: an allowance with a model of unknown price (now asks or
     stops), a Claude Code that can't say how it's signed in (now not used: it might be an API key), a yes that only
     lasted one step (now the whole run, `usage.approve_api_for_run`), Claude Code left running after a stop (own
     process group, `claude_code._stop`), the limit words read from the model's reply (now only Claude Code's own),
     and a dollar figure printed for plan requests.
     Also (Erin, 2026-10-27): every plan request saves the plan's windows it reports (`--output-format stream-json`,
  `rate_limit_event.rate_limit_info.unifiedWindows`, utilization 0 to 1, read as a fraction: check it against the
  status line's figures) via `usage.save_plan_reading`; the app's Plan meter is a button that gets a fresh reading
  (`POST /api/plan/refresh`, `claude_code.ping`: one Haiku request, not in the ledger).
  3. `/refine` (2026-10-27): the frames step in a Claude Code conversation (see the pipeline, step 4). Not tried with
     a real agent yet: Erin's first `/refine` is the check (Claude Code will ask to let the agent open the contact
     sheets, which are in the film's folder).
  4. The page from parts (2026-10-27): `gui/src`, joined by `app.page()`; byte for byte the page it was before (checked,
     and in a headless browser). `gui/index.html` was moved to `gui/src/page.html` and cut down to the frame.
  5. `--hosted` (2026-10-27): see "The app" below. Tried in the cloud workspace from a second address: the Mac-only
     actions hidden and refused, the rest working.
  All five steps are built; steps 2 to 5 aren't committed yet. Still tabled: friend log-ins, and waiting for the
  5-hour reset by itself (now possible: background requests report the reset time).
- **Dr Who library tidy (2026-10-30, not project code; the scripts were in a session scratchpad):** all 187 videos
  in `/Volumes/Media/TV Shows/Dr Who` renamed `Doctor Who (AIR YEAR) - sNNeMM.mkv`. 185 episodes carry a segment title
  and Matroska tags (title, date, season, episode, show). S11E01's audio was retagged German to English. Erin's
  rule for specials: each goes at the end of its series, in air order; specials from years with no series (2009,
  2022, 2023) join the series before. So Series 4 runs to E18 (End of Time Part Two), Series 7 to E16 (Time of the
  Doctor) and Series 13 to E12 (Church on Ruby Road), and Season 00 is empty. Plex's guide (TMDB) lists these as
  specials, so they may show without artwork. Undo logs are in `~/.config/drwho-rename/` (the Last Christmas WEB-DL
  copy was deleted and can't be restored). Season 3 E13 is truncated and held until a full copy arrives. Next: a
  Plex rescan.
- **Uncommitted, 2026-10-30 (evening): Tidy's "already there", a damaged numpy, Python 3.15.**
  - Tidy on Father Ted S01E04 left `4. Competition Time.notes.ass.bak` beside the video ("is already there" in its
    context-notes folder). Cause: `context_notes.keep_old_ass` (every rebuild) kept the `.ass` backup beside the video,
    while the frames step keeps its own in the working folder; so the app's Tidy note never went away. Now rebuilds
    use `context_notes.ass_backup` (`workfiles.place(video)`, like refine/chat_notes), and `workfiles.old_files` gives
    a backup whose name is taken the next free number (`_free_name`: `.bak2`, `.bak3`; other files still stay put).
    tidy's list and the page show "(becomes X: that name is taken)". Page grammar: "1 film here still has its",
    "1 item ... moves". Erin's existing stray file moves as `.bak2` on her next Tidy (nothing to restart: tidy runs as
    a script and the page is read per request).
  - Breaking Bad S01E01's sync check crashed: `module 'numpy' has no attribute 'frombuffer'` (Python 3.14 on her
    Mac). No project code touches `sys.modules`; it's a numpy folder with no `__init__.py` (an interrupted install or
    upgrade). `analyze.need()` now says the package is damaged and prints `"<python>" -m pip install
    --force-reinstall numpy`. Not confirmed on her Mac: her next run shows either the new message or nothing wrong.
  - Python pinned to 3.14 (Erin: lock the venv to one version until she updates the repo; no uv, fewer things to
    depend on). Why: `pip download` checks found `requirements.txt` installs on 3.14 on Windows, Linux (x86_64,
    aarch64) and Apple Silicon, but on 3.15 (python.org's default now) nowhere: onnxruntime, faster-whisper's, has no
    3.15 build, and pip then installs nothing, numpy and Pillow included. Intel Macs: onnxruntime stopped at 1.23.2,
    which has no 3.14 build, so speech recognition there needs 3.13 (README says so). Built: `.python-version`
    (`3.14`, the one pin); `pythonpin.py` (`pinned`, `newer_than_pin`, `status`); `make_venv.py` (finds 3.14: `py
    -3.14` on Windows, `python3.14` on the PATH, Homebrew's or python.org's folders; never downloads Python; a `.venv`
    on another version becomes `.venv-<version>` after a yes (question `venv.replace`; `--yes`), then installs
    requirements and faster-whisper as a separate step, saying so when it can't); `requirements.txt`'s faster-whisper
    has `python_version < "3.15"` (a test keeps it one above the pin); the app's window, `context_notes.py` (not in
    json mode) and Settings' About line say when a newer Python started them; CI tests on `.python-version` and a
    `newer-python` job (3.15, allowed to fail) shows when to lift the pin. README (Requirements, Quick start, Windows,
    Development), `.gitignore` (`.venv-*/`). Tried for real in the cloud workspace (Python 3.13, pin set to 3.13 in a
    copy): a stale `.venv` kept as `.venv-3.1`, the new one imports numpy, Pillow and faster_whisper; with the marker
    tightened it installed the rest and printed the speech message. Not run on Windows or a Mac.
    Her Mac has both 3.14 and 3.15 (`__pycache__` has both).
  - Checked on the real files at 9 pm (after the other session's subtitle-check work had landed, and with all these
    changes still in place): `tidy.py --dry-run` on Father Ted S1 lists `4. Competition Time.notes.ass.bak ->
    ...bak2` (the folder's `.bak` is the frames step's, Oct 28 01:27 UTC; the stray one a rebuild's, 17:36; they
    differ). Breaking Bad S01E01 and E02 in the Linux VM (numpy 2.2.6, so not her Mac's numpy): subtitles clean
    (`subcheck`), E02's pulled out, and the sync check in sync on both with `--limit 10:00` (a full pass reads the
    whole 3.5 to 4.3 GB file over the share at about 36 MB/s and doesn't fit the VM's 3-minute limit; E01's full
    attempt was still reading, no error, when it was stopped). Left in their analysis folders: `analysis.json`,
    `report.txt` and `soundtrack-first600s.*` (the full run rewrites the first two and makes its own cache).
    `py_compile` left some `*.cpython-310.pyc` in `__pycache__` (git-ignored; deleting isn't allowed from the VM).
  - Friend's mp4 to mkv trouble: Erin troubleshoots the file locally (the friend only has the app's screen) and pushes
    any fix to him.
  - Another session was editing `tidy.py`, `context_notes.py`, `app.py` and `gui/src/js/60-tidy.js` at the same time
    (03:52 UTC); one test run caught `tidy.py` half-saved. All of these changes were still in place afterwards.
  - Tested: 549 tests (all pass but the Windows-only registry test) in the Linux VM, `ruff check .` clean. New tests: `test_tidy_gives_a_backup_whose_name_is_taken_the_next_number`,
    `test_a_rebuild_of_a_film_an_earlier_version_started_keeps_its_backup_beside_it`, the rebuild-backup test
    rewritten (it had asserted the old place), `test_a_damaged_package_says_so_instead_of_a_traceback`.
    The page's wording isn't checked in a browser. Docs: CHANGELOG "Fixed", README (rebuild backups).
- **Uncommitted, 2026-10-30: damaged-subtitle check, on by default** (S05E08's built-in English track shows "Î½"
  for every "v": OCR read v as Greek ν, then UTF-8 was read as Latin-1, plus OCR's stray spaces; the rename only
  changed titles, so it came that way). `subcheck.py` finds `mangled`, `lookalike`, `broken` and `l-for-I` (English
  only, at least 5 lines and 1%), `unreadable`, and `mislabeled` (Erin's wording: "mislabeled or corrupted"; the
  label's language vs `languages.guess`). Runs: `context_notes.get_subtitles` -> `checked_subtitles` (a clean file of
  that language beside it, else one OpenSubtitles download via `find_subs.search_online`, checked; never for a film
  with notes; never deletes). Settings `check_subs`, `replace_bad_subs` (both on; `--no-subs-check`,
  `--no-replace-bad-subs`). Tidy checks beside files by default (`--no-check-subs`, `--inside` slow); the app's
  Tidy dialog lists them (`subs` in `/api/tidy`), Settings has both boxes. Tested: `tests/test_subcheck.py` (13),
  the full suite, ruff; the real S05E08 (found); all 156 `.srt` on the share: 3 flagged, all real ("l" for "I" in
  Everything Is Illuminated and Predator; Das Boot's `.es.srt` is Portuguese). Not tried: a real OpenSubtitles
  download through it, the page in a browser. `--inside` on all of Dr Who Series 5: E07, E08 and E09 damaged (same
  "Î½" release), the other 11 clean; Breaking Bad S01E01 (both tracks) clean. Fixed: a clean OpenSubtitles
  `.en.srt` beside each of the three (checked: the right episode, 85-97% words in common; were 0.7-1.0 s early, shifted
  to 0.0 against the built-in track). The videos are unchanged; pick the external track in VLC/Plex.
- **Uncommitted, 2026-10-30: Behind the Scenes** (Erin's idea: a director's-cut-DVD style trivia track "for nerds",
  e.g. Viggo breaking two toes kicking the Uruk-hai helmet in The Two Towers, the take kept). Her choices: facts from
  web research with a source each (not Claude's memory); commentary tracks used when a film has one; its own track;
  spoilers included by default, marked "(spoiler)", with leave-out and ask. Built: `research.py` (fact sheet
  `facts-<video>.json`; commentary transcribed with faster-whisper via `analyze.transcribe(stream=)`; plan: Claude
  Code with only `--tools/--allowed-tools WebSearch,WebFetch`, `dontAsk`; API: `web_search_20250305`, `SEARCH_USD`
  per search in the ledger, `pause_turn` sent back), `--behind-the-scenes` in `make_ass.py`/`context_notes.py`
  (notes `behind-the-scenes-<video>.json`, only facts from the sheet, each note carries `fact` and `spoiler`;
  `<video>.behind-the-scenes.notes.ass`, no Plex copy; `--spoilers`, Settings `bts_spoilers`, the film's own `spoilers`,
  question `bts.spoilers`; the look line records it), `--research-again`, `--commentary`, `embed.py` two tracks
  (`TRACKS`, "Behind the Scenes" with `CONTEXT_NOTES_BTS_SHA1`), the app's "Which notes" choice and Settings.
  A separate review found 8 defects, all fixed with a test each: the API allowance and credit check now use the web
  search's own estimate (`Researching.cost_of`, `Sender.next_usd/left_usd`, `usage.guard(next_usd=)`) and are checked
  before every `pause_turn` part (`Sender.before_continuing`); the estimate is an upper bound (input grows with the
  square of the searches, `WEB_SEARCHES` 20, shrinking per part); cache tokens are priced in the ledger
  (`claude_api.billed_input`); a timed-out web request isn't resent; a sheet is complete only when every request was
  read and it has facts (`parse_facts` returns `(facts, readable)`); a stopped `--research-again` is picked up, and
  notes from an older sheet are written again (`made` in the sheet, `facts_made` in the notes); "ask" asks once per
  film and Yes to all takes its default; a note that doesn't say takes its fact's spoiler mark; the page's "Inside the
  film" line for skipped films. Also fixed on the way (old race): a part is counted before its "N notes" line prints.
  Tested: 527 tests (22 in `tests/test_behind_the_scenes.py`, 6 in `tests/test_vlc_extension.py`), ruff clean; the app
  end to end in a headless browser against the fake Claude Code; a frame rendered with libass; the real Claude Code 2.1.314 in the cloud
  workspace took the web flags and searched without asking (one Haiku request); the commentary track picked by
  stream index checked on a synthetic two-track mkv (faster-whisper itself not run). First real run (2026-10-30,
  Erin's yes, her plan via the cloud workspace's Claude Code; the VM's `claude` is a `-p`-only stub that can't be
  used): Holy Grail, first 15 min (clip cut into `Movies/.context-notes-test`, deleted after). Look-up: 52 facts for the
  whole film (26 from Wikipedia, 8 Mental Floss, 6 montypython.com; 0 spoilers; 21 medium), one Claude Code request of
  2.4M tokens in (pages re-read as it works) and 40k out; the 5-hour session read 51% after it, 52% at the end. Notes:
  13 placed in 15 min (spot-checked, accurate), the frames step 0 added and 1 retimed. Results are beside the film
  (`...anoXmous_.behind-the-scenes.notes.ass`, working files in its `context-notes/`). Found: the film's subtitles
  are `...anoXmous.en.srt` but the video is `...anoXmous_.mp4`, so `context_notes.py` doesn't find them (the notes
  file names the real `.en.srt`, re-timed +0.30 s); continuing that film needs a fix or a rename.
  None of the 44 films in `/Volumes/Media/Movies` has a commentary track (Holy Grail's and The Untouchables' second
  English tracks are stereo copies of the soundtrack, 0.92 to 0.99 correlation), and there's no LOTR there.
  File name (Erin, 2026-10-30): `<video>.behind-the-scenes.notes.ass` (`workfiles.BTS_ASS`), so the VLC extension
  (0.3.0) finds it beside the context notes and loads both: context shown, Behind the Scenes as a second track (Sub
  Track), each filtered by the same topic boxes (new: "How it was made", "Casting, cameos & easter eggs", "Goofs &
  myths"); its fallback guess ignores Behind the Scenes files, and `scan_ass.py` skips them. Tested in Lua 5.1 to 5.4
  with a VLC stand-in (`tests/test_vlc_extension.py`, needs `pip install lupa`, skipped without), not in VLC itself.
  Tabled by Erin: `/notes` (chat route) for this track.
- **Uncommitted, 2026-10-30: Windows shortcut and PATH** (the friend's run said "Claude Code isn't installed, or
  isn't where this can find it" after Erin signed him in; he starts the app from a desktop shortcut Erin made, which
  she thinks runs `python app.py`). A program started from a shortcut keeps Explorer's PATH from when it started.
  Now `claude_code.windows_path_now()` reads the PATH from the registry (HKLM then HKCU, `%VARS%` expanded),
  `fresh_path()` adds what's missing at the end (nothing moves, the venv stays first), `app.main()` does that on
  Windows at start (so ffmpeg and VLC too), and `command()` also tries `in_fresh_path()` before `PLACES`. WinGet's
  Links and Packages folders are in `PLACES`. New `make-shortcut.bat` makes "Context Notes.lnk" on the desktop
  (PowerShell + WScript.Shell, target `context-notes.bat`, start in this folder). Tested: 499 tests (498 pass, the
  registry test is Windows-only and skipped), the new PATH test fails without the fix, `ruff check .` clean. Not run
  on Windows: `make-shortcut.bat` and the registry read are untested until the friend runs them (CI covers the
  registry test). The cause on his computer isn't confirmed: a stale PATH is the likeliest; it could also be Claude
  Code not installed (only the Claude app), or "Run as administrator" as another user. Docs: README (Windows),
  CHANGELOG.
- **Uncommitted, 2026-10-30: signing Claude Code in from Settings** (Erin's ask: a friend she's testing the app with
  has no Claude account of his own, so she signs him in as herself, and the only way had been the link-and-code dance
  in Terminal). `claude auth login --claudeai` with no terminal prints the link and waits for the code on stdin
  (checked on the real 2.1.309), so `claude_code.login_start/login_state/login_finish/login_cancel/logout` drive it
  and `app.py` has `/api/claude/login`, `.../state`, `.../code`, `.../cancel` and `/api/claude/logout` (all but
  `state` in `LOCAL_ONLY`). Settings, Claude: "Sign in to Claude Code…" (or "Sign in as someone else…") shows the
  link (Copy the link: the account's owner can open it on her own computer and send the code back; the code is tied to
  that one attempt), a box for the code, Finish, Cancel; "Sign out" beside it. Also "Where Claude Code is"
  (`claude_path` in `settings.py`; `command()` takes it after `CONTEXT_NOTES_CLAUDE`; saving it makes the app look
  again) and more `PLACES` (npm global, nvm, Volta, Windows). `tests/fake_claude.py` learnt `auth login`/`logout`
  (`FAKE_CLAUDE_SIGNIN`, `FAKE_CLAUDE_LOGIN`). Tested: 495 tests pass (in three batches, in the Linux VM the desktop
  app gives this session), `ruff check .` clean, and the whole flow in a headless browser against the fake Claude
  Code (sign in, a refused code, sign out, a wrong path). Not tried with the real Claude Code's sign-in page, and not
  on Windows. Docs: README, CHANGELOG, docs/gui-protocol.md. Note: his runs count against Erin's plan windows.
- **Uncommitted, 2026-10-29: the timecode fix.** A phone's or camera's MP4 has a timecode track (a data stream), and
  `--convert` copied it into the MKV, which refused it ("Only audio, video, and subtitles are supported for Matroska").
  Now `embed.py` leaves data tracks out (`-map -0:d` in `build_command`, `data_tracks`, and `verify()` ignores them).
  The list, the prompt, the page (`dropped` in `embed-plan`, `gui/src/js/62-danger.js`) and the README say how many
  were left out. Tested: `test_convert_leaves_out_a_camera_timecode_track_and_says_so` fails on the old code and passes
  now; all 490 tests pass; `ruff check` is clean on the two Python files; a synthetic timecode MP4 converts and decodes.
  Not run on the friend's file, and the page change is checked only by the tests, not in a browser. The friend got past
  the error; the cause of the fix is not known. Still open: a plain `.srt` beside a film isn't embedded (`embed.py`
  only takes `.notes.ass`), and Erin hasn't said whether she wants that.
- **Fixed on the way (2026-10-27):** the page's script stopped on load (`remember` was removed but its listener
  stayed), so the app showed nothing. A test now checks every handler and `$("id")` the script uses.
- **Also added (2026-10-27, Erin's asks; not committed):** "Always download subtitles" (`download_subs`,
  `--download-subs`) and "Yes to all questions" (`yes_to_all`, `--yes-to-all`) in Settings, Defaults for every run.
  Yes to all sets `CONTEXT_NOTES_YES_TO_ALL=1` for the run and its steps; `prompts.ask`/`confirm` then answer the
  questions in `prompts.YES_TO_ALL` (the work: subtitles, sync, alignment, pick up, next video, embed) and never
  sending, API credits or deleting. A new question isn't on that list unless it's added (and to docs/gui-protocol.md).
- **Done earlier on 2026-10-27:** the install's defaults. `settings.py` keeps them in `~/.config/context-notes/settings.json`
  (built-in defaults when the file is missing or damaged). The Settings page has a "Defaults for every run" section, and
  the page no longer remembers choices in the browser (the port changes each start). The Terminal scripts read the same
  defaults (`cli_defaults`, through argparse's `set_defaults`); the look is read by `make_ass.py` from `look_defaults`,
  so a film's saved look is never overwritten. Auto-send moved into Settings and is on by default (untick to be asked
  each time). "Remember starting folder" saves the folder you choose.
- **Done before that:** `embed.py --convert` (an `.mp4` becomes an `.mkv`, and the `.mp4` goes to
  `context-notes/originals/`), the "already inside" check, the time and space warnings, the "Change or delete…" panel
  (delete kept originals, write the notes again), the run options for audience, effort and offline subtitles, the
  rebuild preview with a `.bak` kept on every rebuild and an optional re-embed, the new default audience ("Fluent in
  American English"), a probe cache, the background status check, and the docs and changelog to match.
- **Tested:** the full suite passes (549 on 2026-10-30, `python3 -m pytest -q`), `ruff check .` is clean. The module split was
  compared with the code before it, and the API route still is after step 2 (same output, requests and files; only
  the forwarded `--route api --api-fallback 0` and `--help` differ). The Settings "Claude" section and the run option
  were checked in a headless browser. The other dialogs added before step 1 haven't been looked at in a browser.
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
  before 0.2.0 (Akira's "now" column says "not recorded"); and a check in `tidy.py` for episode accuracy: each video's season and episode numbers against the episode list (TMDB order), flagging duplicate numbers, files in the wrong season folder and files whose picture stops early (the Dr Who check found all three). Frames can confirm the season (the Doctor and companions); the episode number needs the dialogue.
- **Not in the GUI yet:** `--window`, `--align-model`, and `find_subs.py --transcribe`.
- **Test media:** the temporary test folders on the NAS (`Movies/.embed-rewrite-test` and `TV Shows/.convert-test`)
  were deleted. Nothing in the library was changed.
- **New computer:** Python 3.14 (`.python-version`) and `python3 make_venv.py`, which makes `.venv` with `pytest`,
  `ruff`, `numpy`, `pillow` and faster-whisper. `ffmpeg` and
  `ffprobe` are needed. MKVToolNix (`mkvpropedit`, `mkvmerge`) is installed here for checks; the code doesn't use it yet.
  The Media share is mounted
  at `/Volumes/Media`. The probe cache lives in `~/.config/context-notes/probe-cache/` and isn't in the repo.
- **Next step:** Tonight's leftovers first: Erin presses Tidy again on Father Ted S1 (the stray `.bak` moves as `.bak2`); re-runs Breaking Bad S01E01 on her Mac (the code is checked; her Mac's numpy isn't: either it works, or the new message names the Python with the damaged numpy and the reinstall command); her friend, once he `git pull`s, installs Python 3.14 and runs `python make_venv.py`. Then: Erin watches Holy Grail's first 15 minutes in VLC (update the extension from the app's Settings) and
  says what she thinks of the Behind the Scenes notes; then the subtitle-name question (above). Erin commits the uncommitted work and the friend runs `git pull`, double-clicks `make-shortcut.bat`,
  starts the app from the new shortcut and looks at Settings, Claude. If it still can't find Claude Code: his
  `claude --version` and `where.exe claude` in PowerShell, and "Where Claude Code is" in Settings. Then Erin's short
  run on her plan (`context_notes.py film.mkv --limit 5:00`), then step 3. Still waiting: her answer on the Plex copy.

## The pipeline (one command per step; `context_notes.py` runs them all)

1. **Subtitles.** An `.srt` beside the video, or a track inside it. If there's none, `find_subs.py` looks in `Subs/`
   folders, then OpenSubtitles.com, then offers speech recognition.
2. **Sync.** `analyze.py SRT --video V --frames none --shift auto` fixes a constant offset. `--align` re-times with
   faster-whisper when the offset drifts (different cut).
   **Behind the Scenes** (`--behind-the-scenes`): after sync, `research.py` writes the fact sheet (commentary tracks,
   then the web), and steps 3 to 5 work from it, on their own notes file and `.ass` (README, "Behind the Scenes").
3. **Dialogue notes.** `make_ass.py --generate`, on one of two routes (`--route`, Settings: "Claude"):
   - The plan (the default since 2026-10-27): each part through Claude Code in the background (`claude_code.py`,
     `claude -p`), no API credits. When the plan can't go on (its limit, the 5-hour session at 90%, Claude Code
     missing or signed out), it moves to API credits only within `--api-fallback` dollars for the run, or after a yes
     to `plan.fallback`; unattended without that, it stops and keeps what was written.
   - The API: `--route api`, which costs credits.
   - Also in a Claude Code conversation: `chat_notes.py prepare`, then one reply per part, then
     `chat_notes.py collect`. In this project, `/notes` does this with the **note-writer** agent.
4. **Frame notes.** `make_ass.py --refine`, on the same two routes. It sends contact sheets of keyframes; on the plan,
   Claude Code opens them itself with its Read tool (only that folder). Also in a Claude Code conversation:
   `/refine` runs the **frame-reviewer** agent once per stretch (`chat_notes.py show-frames --part 0` begins and
   keeps the notes as they were; `--part K` shows stretch K with parts 1 to K-1 applied; `collect-frames` applies
   the replies in `<working folder>/frame-replies/` to the kept notes). Same replies, same notes as `--refine`
   (`tests/test_chat_frames.py` checks it); a stop is recorded as `stopped_after`, so either route picks up.
5. **Build.** `make_ass.py SRT NOTES --video V`. Repeats are left out (`dedupe.py`); timing and the box behind the
   notes come from the notes file's `timing` and `note_background`. The `.ass` header's `; Look:` line records the
   build (`make_ass.BUILD`), background and reading speed. `context_notes.py` rebuilds a finished video's `.ass`
   (free, no API key) when it's older than the notes or its look line is missing or different. Bump `BUILD` when
   a change to the build output should reach existing `.ass` files.
6. **Check.** `align_check.py V SRT` measures every note against the speech in the 10 s before it. `--fix` corrects
   stretches that are out.

## Decisions already made (with the evidence: project doc "benchmark-results.md")

- **Behind the Scenes only from sourced facts** (Erin, 2026-10-30). Production trivia is where a model's memory is
  weakest and trivia sites are full of myths, so the track's notes come only from the fact sheet: a note (or a frames
  addition) that tells no fact id from it is dropped. Spoilers are a per-note mark decided at the build, never a
  rewrite; real-world facts (cast, crew, an actor's later life) aren't spoilers. Context notes are never touched.

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
  - Every route takes the model and effort from Settings (Opus, high unless changed), `make_ass.py` by hand too
    (Erin, 2026-10-27). `claude_api.DEFAULT_MODEL` (`claude-sonnet-5-5`) is only the default when calling
    `generate()` or `refine()` from Python. The effort is left out for Haiku 4.5, which rejects it
    (`claude_api.supports_effort`).
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
    (`~/.config/context-notes/usage.jsonl`, written in `claude_api._call_api` through `_record_usage`, so
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
2. **Never spend API credits without a yes from Erin in this conversation.** That covers `--generate --route api`,
   `--refine --route api`, `--api-fallback` above 0, `bench.py` and `judge.py`. Each one prints a cost estimate first,
   so show it. `/notes` and the default plan route use the subscription, not the API; still ask before a real run on
   her plan (it uses her 5-hour session). Tests never run the real Claude Code (`tests/fake_claude.py`).
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
   `fileio.write_text_safely()` or `fileio.replacing()`, so Ctrl-C or a GUI's Cancel can't leave half a file.
9. **Write for Erin.** Plain English in messages and docs, and say what to do next. She runs macOS (Apple
   Silicon, Homebrew, Python 3.14) and works in Terminal. Her friends use the app on macOS, Windows and Linux.
10. **Update "Where things left off" before a session ends.** Any chat that changes this project rewrites that section
    in place: what changed, what's uncommitted, what was tested, what's waiting on Erin, and what's next. Replace
    stale lines rather than adding a log, and keep it short enough to read in a minute. Do this even when the session
    ends with a question instead of a change.

## Where the code lives (split into modules on 2026-10-27)

Open the module that holds the job, not the script that used to. README's second file table lists them.

- **Talking to Claude:** `claude_api.py` (key, request, retries, prices, `wait_awake`, `image_tokens`,
  `encode_images`) and `claude_code.py` (the plan: `status`/`problem`, `call`, `CantGoOn`). `sending.Sender` picks
  between them per request and moves to the API (`leave_plan`, `within_allowance`); the steps pass contact sheets as
  `{"type": "image", "path": ...}` and only the API attaches them. The loop both steps use is `sending.send_parts`:
  `usage.guard` before each part, the step reads and saves the reply, then `usage.report`; any stop keeps what was
  written. `usage.run_start()` (env `CONTEXT_NOTES_RUN_START`, set by `context_notes.py`) makes the API allowance
  count per run across steps. Ledger lines from the plan have `"route": "plan"` and no dollars.
- **The steps:** `generate_notes.generate()` is `read_cues`, `notes_to_extend`, `starting_point`, `Parts`, the
  estimate, `send_parts` with a `Writing`, then `notes_file`. `refine_notes.refine()` is `load_notes`,
  `where_to_start`, `look_at_video`, `plan_windows`, the estimate, `keep_backups`, `send_parts` with a `Refining`,
  then `_save`. Each reply is read by `read_part` / `apply_reply`.
- **Options:** `cli_common.py` defines the ones `context_notes.py` and `make_ass.py` share (model, effort, key file,
  `--limit`, the look) and passes them on (`claude_args`, `look_args`, `limit_args`). New Claude options go there.
- **Behind the Scenes:** `research.py` (the look-up: `research()`, `Researching` for `send_parts`, `parse_facts`,
  `fact_lines`); `generate_notes.BTS_SYSTEM`/`bts_system_prompt` and `refine_notes.BTS_SYSTEM`; the paths in
  `workfiles` (`bts_notes_path`, `facts_path`, `bts_ass_path`, `PREFIXES`); `make_ass.spoiler_choice`;
  `context_notes.track_args`/`wanted_spoilers`; `embed.TRACKS`.
- **Files and text:** `fileio.py` (writing safely, backups, `config_dir`), `subtitles.py` (`.srt` and quote matching),
  `timecode.py` (times).
- **Old names still work** (`make_ass.write_text_safely`, `generate_notes.call_api`, `refine_notes.hms`, ...) for older
  code and `bench/`. Patch the module a function lives in: replacing an old name doesn't reach the code that moved.
  `bench/bench.py` replaces `claude_api.call_api`; replacing `generate_notes.call_api` would let real, paid requests
  through.
- **Checked:** besides the tests, the split was compared with the code before it on 13 synthetic runs (33 steps: pick-up,
  `--extend`, unreadable replies, API errors, `--limit`, the wrapper). The output, the 38 requests and all 1,234 files
  were the same; only `--help` changed.

## The app (`app.py` and the page in `gui/src`)

- The page is in parts (since 2026-10-27): `gui/src/page.html` with `styles/*.css`, `html/*.html` (one file per
  dialog) and `js/*.js`, joined in name order by `app.page()` on each request (`gui/README.md`). Edit the part, reload
  the page; there is no built copy. To change one dialog, open only its `html/6x-*.html` and the `js/` file with the
  same name.

- A local web page for friends who don't use Terminal. It runs `context_notes.py` with `CONTEXT_NOTES_UI=json`
  (`docs/gui-protocol.md`) and shows the questions, the cost, progress and Cancel.
- Standard library only. One page for the browser, with no external scripts, fonts or images.
- Security: by default it listens on 127.0.0.1 only, every request needs the random key, and `Host` and `Origin` are
  checked. `--hosted` (Erin, 2026-10-27) listens on every address ("::", dual stack) but answers only `app.PRIVATE`
  ranges (+ `--allow`), checks that `Host` is an IP address or this computer's own name (DNS rebinding), uses port
  8229 and a kept key (`app_key`, `~/.config/context-notes/app-key`, mode 600). From anything but loopback,
  `LOCAL_ONLY` endpoints and deleting kept originals are refused (403), and the page hides them (`.local-only`,
  `body.remote`). `--public` (servers only) drops the address rule. The API key never goes to the page; it only shows
  the last 4 characters. Keep all of this when changing it.
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
  - Network requests wait through `claude_api.wait_awake`.
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
| `frame-reviewer` | Opus | Look at ONE stretch of a film's contact sheets (`chat_notes.py show-frames --part K`, opening each sheet with Read) and write `frames-<k>.txt`: what to add, revise, retime or drop. The `/refine` command's agent. |

Commands: `/notes <video> [options]` (subscription-written notes, end to end), `/refine <video> [options]` (the
frames step on the subscription, one stretch at a time) and `/check <video>` (subtitles, sync, alignment and
repeats, with no API use).
