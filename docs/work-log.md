# Work log

Older hand-off notes, newest first. Moved here from `CLAUDE.md` ("Where things left off") so that file stays short.
Not read at the start of a session: search it when a topic comes up (rule 11 in `CLAUDE.md`). Code changes are in
`CHANGELOG.md`; this log holds the rest: media runs, what was tried and what was found.

## 2026-11-05: IT Crowd Behind the Scenes (plan route, `--api-fallback 0`, $0)

- 2026-11-04 10:51: S01E01 to S02E04 back to back, about 13 min each, 1.5-2% of the weekly plan each (the week went
  from 36% to 46% over S02E05 to S03E03). Red Dwarf (70 episodes) was cancelled: it would have used up the week.
- From 13:35, one an hour (Erin), from a shell loop: S02E05 to S03E03 done. S02E04's run was stopped as S02E05's
  research began, so S02E05 has an empty fact sheet from then; the paced run redid it.
- S03E04 (18:55): its notes were written and built, then the frames step's ffmpeg crawled at 0.017x for 40 min and
  failed: the Media share was going. From 20:45 every episode was "Can't find" (`/Volumes/Media` gone; on 11-05
  only the `TV Shows` and `TV Shows Volume 2` shares were mounted, over the Tailscale address, and `TV Shows` didn't
  answer).
- S02E03's frames part 6 reply couldn't be read (`.refine6.failed.txt`); its rerun waits with the rest.

## 2026-11-04: TV Shows renamed with `cleanup.py` (Erin away; questions held)

- Left out with `--skip` for Erin's answer: `Dr Who/` (S03E13 is the truncated episode held in place; renaming the
  show folder would move it), `Beavis & Butthead/` (56 episodes would be renumbered by title to TMDB's order) and
  `MythBusters/` + its Xtras folder (53 renumbered; Xtras numbered by year).
- Before running: episode titles in names are now checked against TMDB (Father Ted is numbered straight through:
  18 episodes get TMDB's numbers by title, checked: S1 1-6, S2 1-10, S3 1-8); "080p" isn't a title; Mr Robot's
  and Red Dwarf's spellings match ("m3tadata", "Me²", "Pete (1)").
- Run 10:43 stopped at a locked file (`Only Murders...S01E04`, Finder's Locked: S01E02-E10 all locked, nothing
  else in TV or Movies): 377 renames, log `... 104333 TV Shows.jsonl`. Locked files now go on the by-hand list.
  Run 10:49: 262 renames, log `... 104914 TV Shows.jsonl`. Re-listing (same skips): 0 to rename, 635 tidy, 67 by
  hand, 0 clutter. Left behind: `Forensic.Files.II.S02...[TGx]/` (only the by-hand duplicates); Only Murders has
  S01E01 in `Season 01/` and the 9 locked episodes in `Season 1/`. The Forensic Files S02 release `.txt` is in
  `TV Shows/context-notes/removed/`.

## 2026-11-04: Movies renamed with `cleanup.py`

- tidy.py first (Erin's yes): House of the Long Shadows (14 items), Housebound (8), Waking Ned Devine (4).
- Trial, 09:29 (`--only` Akira, Life of Brian, Waking Ned Devine): 41 renames; log
  `~/.config/context-notes/cleanup/2026-11-04 092905 Movies.jsonl`.
- The rest, 09:30: 132 renames, 31 films, 18 clutter files; log `... 093058 Movies.jsonl`.
- Erin then tidied some by hand (Total Recall into `Total Recall (1990)/`, both The Thing copies into one folder,
  the Bourdain/Mythbusters episodes and The Stand moved out). Repairs run, 10:20: Total Recall (1990) {tmdb-861};
  Old Boy's `.mkv.part` checked complete (Segment size = file size, last video packet 7194.57 s of 7194.61 s) and
  named `Oldboy (2003) {tmdb-670}.mkv`; Holy Grail's Behind the Scenes `.ass` and its notes folder (under
  `...anoXmous_`, with files under `...anoXmous` too) took the film's name, notes found, dates kept;
  `Predator[Eng][Subs].srt` -> `.en.srt`; 7 clutter files from `Other/` and `Logs/`. 24 renames; log
  `... 102010 Movies.jsonl`. Re-listing: 0 to rename, 36 tidy, 5 by hand, 0 clutter.
- Checked: `context_notes.py --status` on Akira and Waking Ned says "needs rebuilding" as before the rename
  (Akira's `.ass` has no look line; Waking Ned's predates the `.notes.ass` name).

## Moved 2026-11-04 (the hand-off as it stood at 09:32, unedited)

Last updated 2026-11-04. Replace this section when a session changes the project (see rule 10).
It's the first thing to read when picking the work up on another computer or after losing the connection.

- **`cleanup.py`, library renaming to the Plex/Jellyfin standard (2026-11-04): built, not yet run on the library.**
  Decided (Erin): its own `cleanup.py` (tidy.py stays as it is); use **guessit** (new dependency, pure Python, pulls
  rebulk, babelfish, python-dateutil, tzdata; only cleanup.py imports it; rule 6 needs a line for it); Plex
  `{tmdb-N}` tags; titles: a library-wide title-language setting defaulting to the computer's language (English
  fallback; needs a free TMDB key for translations), per-film overrides in the list, subtitle files renamed to the
  right language codes (`subcheck`/`languages.guess`), audio-track languages only reported (Erin, 2026-11-04,
  with Reddit's non-English users in mind). Noted: the app and notes are English-only, a separate project.
  Decided order per film: make `Title (Year) {tmdb-N}/`, move the video and everything beside it, move its working
  folder from the shared `Movies/context-notes/<old>/` to `<film>/context-notes/<new>/` (renaming files inside,
  fixing the notes file's `subtitles` field), then that film's clutter into `<film>/context-notes/removed/`; after all
  films, clutter of no film into `Movies/context-notes/removed/` and the shared `context-notes/` removed only if
  empty but the ignore files. Undo log per move. Proposed: identity from guessit + `film_ids.py` lookups
  (extended to films without notes); anything unsure goes on a decide-by-hand list. Trial (scratchpad, read-only):
  guessit read 1,429 names on the share; right on nearly all; misses were release-group words in titles ("Total
  Recall KLAXXON"), no-year names, MythBusters Xtras (`2011X03X01`), episodes in `Movies/`, The Stand's parts titled
  by part name; duplicate The Thing (2011) `.avi`/`.m4v`. Respect Erin's Dr Who specials rule (not Season 00).
  Done for it (uncommitted, 2026-11-04): `guessit>=4.4` in `requirements.txt` (Erin installs it); `tmdb.py`
  (`--set-key` asks hidden, saves `~/.config/context-notes/tmdb.json` mode 600, tests with `/3/authentication`; the
  short API key goes as `api_key`, the Read Access Token as a Bearer header; `tmdb.TMDB(key).get(path, **params)`
  for the cleanup; `CONTEXT_NOTES_TMDB_API` points tests at a stand-in); Settings' TMDB section (`/api/tmdb`,
  `LOCAL_ONLY`; `tmdb` in `/api/info`); question `tmdb.api-key`; README, CHANGELOG, `tests/test_tmdb.py`. Not tried
  Erin's key saved and tested against the real TMDB (accepted; Amélie's titles right in en/de/fr/ja).
  **`cleanup.py` listing built** (uncommitted, 2026-11-04; lists only, changes nothing; `tests/test_cleanup.py`, 9,
  fake TMDB; full suite and ruff pass; README, CHANGELOG, `docs/gui-protocol.md` events `cleanup-film`/`-summary`).
  guessit reads names (TV: the show from its folder name, the episodes' names as a second clue and their earliest
  year as the show's); ids from names/.nfo; TMDB search with `key`/`near` matching and `best_known` (votes) for
  ties; titles via `--language` (default: the computer's, `computer_language`). Run read-only on the share:
  Movies 34 rename / 16 by hand (all real: episodes in Movies, Napoleon discs, The Stand's parts, the two The Thing
  copies, Total Recall KLAXXON) / 19 clutter; TV 1243 rename / 137 by hand (duplicates: Forensic Files .mkv+.m4v,
  MythBusters S02E05.1-style specials, Twilight Zone S3 twice; 19 films in `TV Shows/Movies`; MythBusters Xtras with
  year seasons; the 2nd Blackadder copy) / 4 clutter. Notes to Erin: Dr Who's per-episode years become the show's
  (2005); TMDB's titles are used ("Waking Ned", "Casablanca (1943)": TMDB's release date); Dr Who S03E13 is the
  truncated one she's holding in place. Not built yet: the moves (with undo log, the order Erin decided), the
  title-language setting in Settings and per-film overrides, subtitle language codes, `Subs/` folders, the app.
  Erin read it (2026-11-04): leave the duplicates; Dr Who takes the show's year (2005); "Waking Ned Devine" kept
  (`--set-title 10162`, saved in `~/.config/context-notes/cleanup-titles.json`); tidy.py run (her yes) on House of
  the Long Shadows (14 items), Housebound (8), Waking Ned Devine (4). **Moves built** (uncommitted): asks
  `cleanup.go` (`--yes`); whole-folder rename when a folder's videos all go to one new folder (so `Eng. Subs/`,
  `Logs/` stay with the film), then files, working folder (entries renamed, `subtitles`/`display_subtitles`/`video`
  in its JSON follow, mtime kept), kept originals, clutter to `<film>/context-notes/removed/` (else the library's),
  empty folders removed; undo log `~/.config/context-notes/cleanup/*.jsonl` (fsync per line), `--undo`; `--only`;
  videos changed <2 min ago left; a taken name stops the run. Tests: 15 in `tests/test_cleanup.py` (undo restores
  byte for byte), full suite and ruff pass. **Trial run (Erin's choice, 2026-11-04 09:29):** `--only` Akira, Life
  of Brian, Waking Ned Devine: 41 renames, folders renamed whole, notes found, dates kept; undo log
  `~/.config/context-notes/cleanup/2026-11-04 092905 Movies.jsonl`. Akira's and Waking Ned's "needs rebuilding"
  were already so (no look line; old `.ass` name). **Rest of Movies done** (Erin's go, 09:30): 132 renames, 31
  films, 18 clutter files; log `.../cleanup/2026-11-04 093058 Movies.jsonl`. Re-listing: 0 to rename, 34 tidy,
  16 by hand (untouched), 0 clutter; `antarctica_movie_server.txt` is in `Movies/context-notes/removed/`.
  `Old.Boy...GalaxyRG[TGx]/` holds only a 3.9 GB `.mkv.part` (Dec 2024, an unfinished download): not a video,
  left alone. Next: Erin rescans Plex and checks; then TV Shows (1243 episodes).
  Not built: Settings' title language and the app, subtitle language codes, `Subs/` folders.

- **Life of Brian Behind the Scenes done (2026-11-03, Erin's yes, her plan, $0 API, media only):**
  `/Volumes/Media/Movies/Monty.Pythons.Life.of.Brian.1979.720p.BRRip.x264-x0r/`, one full run of `context_notes.py
  --behind-the-scenes --route plan --api-fallback 0 --yes` (venv `~/.alt229/bin/alt229-dev/bin/python3`). The embedded
  English subs (1359 lines) were pulled out and were already in sync; no commentary track. Look-up: 47 facts (24
  Wikipedia, 7 Irish Times, 6 Mental Floss), 0 spoilers. 40 dialogue notes, then frames: 5 added, 1 revised, 4 retimed, 1
  dropped; 1 repeat left out by dedupe; 44 placed (4 on-screen). `align_check.py` (notes as the 3rd argument): in
  step, 12 of 39 measured, typical 0.05 s. Session 2% -> 6%. No context notes for this film yet. Next: Erin watches it.
- **Holy Grail Behind the Scenes finished (2026-11-03, Erin's ask, her plan, $0 API):** the scripts were given
  `...anoXmous.en.srt` by hand; the name mismatch (`...anoXmous_.mp4`) is still unfixed in code, so the app and
  `context_notes.py` won't find those subtitles. Full sync check: in sync, no shift. `make_ass.py --generate --extend
  --behind-the-scenes` sent lines 211-1506 (6 parts): 49 notes, 49 of 52 facts, 1 spoiler. `--refine` picked up at
  15:00 (parts 4-24): 3 added, 2 retimed, 1 dropped (the Book-of-the-Film note moved to the gorilla-hand page,
  0:43:15). Track: 52 notes placed (49 dialogue, 3 on-screen). `align_check.py` (notes file as 3rd argument) in
  step, 31 of 48 measured, typical 0.01 s. Session 28% -> 38%. Next: Erin watches it in VLC.
- **Band of Brothers notes (2026-11-02, `/notes`, media only):** all 10 episodes to do, order E07-E10 then E01-E06,
  `--year 2001` (Wikipedia: HBO, 2001-09-09). Subtitles: `Season 1/Subs/<video stem>/26_English.srt` (no track
  inside). 38 parts (E01-E10: 5,3,4,3,4,3,5,4,3,4). `/Volumes/TV Shows` read at 1.2 MB/s, so Erin copies episodes
  to `~/Downloads/Band of Brothers` (E07, E08 so far); each `.srt` is copied beside its video as `<stem>.en.srt`.
  The subtitles are OCR'd: names/places lower case, "it." for "Lt.", "80/3" for "Bois". Erin chose to fix the copies:
  `~/.config/context-notes/scratch/bob_fix_srt.py SRT` (line count unchanged; unfixed copy kept as
  `.en.srt.ocr-orig` in the working folder). **E07 done:** sync clean (+0.16 s), 5 parts (parts 1-2 re-anchored to the
  fixed text, originals in `pre-ocr-fix/`), 90 notes placed (Shifty repeat left out by dedupe; #24 first-sergeant
  repeat deleted and #8's Foy sentence cut by hand, `.pre-dedupe.bak` kept), alignment in step (54 windows, -0.35 to
  +0.61 s). **E08 done:** subs fixed (100 lines; "cannood" at line 628 left as is), sync +0.1 s (last third only:
  busy soundtrack), 4 parts, 77 notes placed (Johnny repeat left out), alignment in step (53 of 76 checked, -0.88 to
  +0.23 s, one noisy 2-line reading at 0:25:10; 23 unmeasurable). Frame pass not run on either. Erin has since moved
  E07/E08 with their notes and working folders to `/Volumes/Media/TV Shows/Band Of Brothers/`. E08's "cannood"
  fixed to "Carwood" on the share (Erin's yes) and E08 rebuilt (77 notes; `.pre-carwood.bak` of `.srt` and `.ass`
  in its working folder). All other episodes' `.srt` are copied to Downloads and fixed (the script knows every
  episode's names; also by hand: E02 "The 88s", "Quaker", E02/E03 "Thunder", E03 "be a dear"); all prepared.
  **Written and collected** (repeats trimmed by hand, `.pre-dedupe.bak`), waiting for their videos for sync, build
  and alignment check: E01 (120), E02 (61), E03 (70), E04 (49), E05 (78), E06 (46), E09 (65), E10 (87). All 38
  parts done. Erin is copying E01-E06 to Downloads (slow, ~1.2 MB/s); E09/E10 videos not copied yet. Per video once
  it's complete: subtitle-prep sync check (`analyze.py --frames none --shift auto`), `make_ass.py SRT NOTES --video V
  --timing-report`, subtitle-prep alignment check; ask before any `--fix`. Then offer the frame pass for the folder.
  E07/E08 on the Media share converted to `.mkv` with the Context Notes track inside (`embed.py --convert --yes`,
  Erin's ask); the `.mp4`s are in `context-notes/originals/` there (delete with `--delete-backups` when she's happy).
  Their English subtitles are still the external `.en.srt` beside them.
  2026-11-03: E01-E04 built and alignment-checked in Downloads. E01 (117 placed) and E04 (50) had one 13 s stretch
  each ~1 s late: `align_check --fix` (Erin's yes), rebuilt from `<working folder>/<stem>.en.aligned.srt`, re-check
  clean. E02 (61) and E03 (68) in step (E02's sync-check 1.6 s and E04's +59.5 s were battle-noise false readings).
  E05 (78 placed) and E06 (47) built; E06 in step; E05's one flagged stretch (0:42:58, "5 s late") was the
  recogniser merging "Quiet!" into the radio announcement; the subtitles match the speech, so no fix. E05 also
  got "SS Panzer", "Ardennes", "HQs". **E01-E08 are built and checked.** Left: E09/E10 videos (Erin to copy), then
  their sync, build, alignment; then offer the frame pass, and embedding for the Downloads copies if wanted. The session meter is stale (no reading since 2026-10-31), so parts aren't measured.
- **Committed and published 2026-11-02 (`a60d10c8`): GitHub's tests green again** (run 41568280133: tests pass on
  Windows, macOS and Linux; only `newer-python` fails, by design), **and a Windows installer.** The `tests` workflow had
  failed on every push since late October (Linux passed; `newer-python` fails by design and doesn't count). Windows
  (21): tests read UTF-8 files in cp1252 (now `read_text(encoding="utf-8")` everywhere in `tests/`); the VLC install
  test wrote to the runner's real `%APPDATA%` (conftest now sets `APPDATA`); a Windows-only folder message; real
  bugs: `.claude/statusline.py` now prints UTF-8, `prompts.interactive` no longer counts NUL as a terminal
  (`_terminal`, GetConsoleMode), and `app.py`/`analyze.py`/`claude_api.py`/`find_subs.py` read their files as UTF-8.
  macOS (1): `app.own_names` called `getfqdn` per request, >30 s on GitHub's Macs: now `lru_cache`d, and the hosted
  test stubs it. New `install.ps1` (Erin: "easy install script"): `irm .../install.ps1 | iex` installs Git, Python
  (from `.python-version`), ffmpeg, VLC and Claude Code (both after a yes) with winget, clones to
  `%USERPROFILE%\context-notes`, runs `make-shortcut.bat --no-pause`, starts `context-notes.bat`. README Windows
  section, CHANGELOG, `test_the_windows_installer_hangs_together`. Tested on the Mac: full suite, ruff, and
  `install.ps1` parses in pwsh; GitHub's Windows run passes the suite. **The installer itself hasn't run on Windows
  yet:** Erin is setting up a Windows machine to try the one-liner.
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
  copy was deleted and can't be restored). Season 3 E13 is truncated and held until a full copy arrives.
  Plex (checked read-only in its database on MiSANthrope, 2026-11-03): rescanned and refreshed after the rename; the
  show is matched to Plex's own entry, whose title is literally "Doctor Who (2005)" (the premiere year, to tell it
  from the 1963 and 2023 shows), so the rename can't change it; editing and locking the title in Plex can. Episodes
  carry their real air dates. 34 episodes have no guide data: the specials moved into Series 4, 7 and 13, and all of
  Season 14 (Plex's guide has the 2024 series under its own show, "Doctor Who (2023)"). The file names' per-episode
  year goes against Plex's naming guide (the show's year); harmless now, since the folder "Dr Who" sets the show.
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
- **Uncommitted, 2026-10-30 (late): Windows one-click launchers** (Erin: "ultra easy" for the friend, who likely
  installed Python 3.15). `context-notes.bat` runs `make_venv.py --ready` (new: the pinned Python + numpy + Pillow)
  before every start; when not ready it runs `make_venv.py --yes` with python.org's 3.14 (installer or install manager
  path) or `py -3.14`, offering `winget install Python.Python.3.14 --scope user` (Y/N) or opening python.org.
  New `update.bat` (runs from a %TEMP% copy, since `git pull` may replace it): `git pull --ff-only`, tops up `.venv`,
  then calls `context-notes.bat`. `make-shortcut.bat` makes both desktop shortcuts. `make_venv.py` force-reinstalls
  when numpy/Pillow are damaged on the right Python. Tested: `tests/test_pythonpin.py` (`--ready`; a static check of
  the three .bat files: CRLF, ASCII, labels, named files), full suite, ruff. **Not run on Windows**: the friend's first
  double-click is the test. His first update: Erin sends him `dookie-update.bat` (temporary; see Reminders), which
  he drops in the folder and double-clicks: it removes its own untracked copy (else `git pull` would refuse), pulls,
  makes the shortcuts (`make-shortcut.bat --no-pause`) and starts the app. Also 2026-10-30: alpha -> Beta (see
  Decisions). Both tested only by the suite (all pass) and the static .bat check.
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
- **Breaking Bad S1 E02-E07 notes (2026-10-30, late, `/notes` on the plan; media only, no code changed):** all six
  written (44, 49, 57, 58, 64, 65 notes), built and alignment-checked, `--year 2008` (Erin). Run with
  `~/.alt229/bin/alt229-dev/bin/python3` (bare `python3` is 3.15). Sync: no drift; E03-E06 built from the
  `--shift auto` `.aligned.srt` (+0.26 to +0.40 s), E02/E07 unshifted. E02 had 0:31:38-0:32:27 2.7 s late:
  `align_check --fix`, rebuilt from its `.aligned.srt` (Erin's yes). E04/E07 rebuilt with `--keep-duplicates`
  (Erin): `dedupe.py` treated the opening "Dramatic irony:" as the topic and dropped 3 notes about different scenes.
  Fixed (uncommitted): storytelling labels added to `dedupe.GENERIC_LEADS`, test
  `test_a_storytelling_label_is_not_a_subject` (fails without it), full suite and ruff pass, CHANGELOG "Fixed".
  Frame pass done on all six (2026-10-31, `--route plan --api-fallback 0 --yes`: `--yes-to-all` alone stops at
  "confirm sending" when not in a terminal; with fallback 0, `--yes` stops rather than use API credits,
  `sending.Sender.leave_plan`). $0 API. Now 97, 108, 96, 105, 119, 112 notes; every alignment check after it in
  step. The whole season (notes + frames) took the 5-hour session from about 7% to 61%. Season 1 is finished. To look into later: `--shift auto` overshoot (below). Plex copy: Erin will say what Plex shows. After the shift, E03-E05 read 0.28-0.34 s late (in
  tolerance), so `--shift auto` may overshoot a little. The session meter stayed at 7% all run (stale reading), so
  no parts were measured. Frame pass not run on any of the six.
- **Next step:** Erin watches Breaking Bad S1 E02-E07 and says what she thinks of the notes. Tonight's leftovers first: Erin presses Tidy again on Father Ted S1 (the stray `.bak` moves as `.bak2`); Breaking Bad S01E01 is done on her Mac (2026-10-30, in the `alt229-dev` venv, Python 3.14.8, numpy 2.5.3: full sync check in sync, 771 lines); Homebrew's bare `python3` is 3.15 with a damaged numpy, so run with the venv loaded (or reinstall numpy for 3.15); her friend, once he `git pull`s, installs Python 3.14 and runs `python make_venv.py`. Then: Erin watches Holy Grail's first 15 minutes in VLC (update the extension from the app's Settings) and
  says what she thinks of the Behind the Scenes notes; then the subtitle-name question (above). Erin commits the uncommitted work and the friend runs `git pull`, double-clicks `make-shortcut.bat`,
  starts the app from the new shortcut and looks at Settings, Claude. If it still can't find Claude Code: his
  `claude --version` and `where.exe claude` in PowerShell, and "Where Claude Code is" in Settings. Then Erin's short
  run on her plan (`context_notes.py film.mkv --limit 5:00`), then step 3. Still waiting: her answer on the Plex copy.
