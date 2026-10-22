# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [Semantic Versioning](https://semver.org/)
(while pre-1.0, minor versions may change the notes format or command line).

## [0.2.0] - Unreleased

### Added
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
- Notes stay up longer: 2 s to notice, then 150 words a minute (0.4 s a word), kept between 6 and 24 s
  (was 180 a minute, 5 to 18 s). Change it per film with `--reading-speed`, `--note-min` and `--note-max`.
- One install step: `pip install -r requirements.txt` now covers everything, including faster-whisper for speech recognition. The separate `requirements-align.txt` and `requirements-dev.txt` are being removed.
- Notes stay up longer when they're long: the ceiling went from 12 s to 18 s (it cut 62 of Amélie's 100 notes
  short). Same 180 words a minute and 5 s floor.

### Fixed
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
