# context-notes: rules and knowledge for every agent in this project

Pop-up notes for films and shows: idioms, slang, register, history and culture, wordplay, sight gags. They are
explained for a viewer who didn't grow up where the film was made. The notes are built into `<video>.notes.ass`
beside the video and shown in VLC (the extension is in `vlc/`). The owner is Erin. She watches mostly French,
German, Spanish and Japanese films, plus British comedy. What she values most is history and culture she wouldn't
know because the film is old or foreign.

Read `README.md` for the full command reference. This file holds what we've learned and the rules.

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
5. **Build.** `make_ass.py SRT NOTES --video V`. Repeats are left out (`dedupe.py`) and timing comes from the notes
   file's `timing`.
6. **Check.** `align_check.py V SRT` measures every note against the speech in the 10 s before it. `--fix` corrects
   stretches that are out.

## Decisions already made (with the evidence: project doc "benchmark-results.md")

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
- **Note timing.** 2 s settle + 180 wpm, 5 s floor, 18 s ceiling. The old 12 s ceiling cut 62 of Amélie's 100 notes
  short. Raising it added only 1.5 s of three notes on screen at once over the whole film.
- **Alignment check.** Speech recognition only, with a tolerance of 0.7 s and at least 2 recognised lines per window.
  - Subtitle makers time lines loosely: on Amélie's in-sync subtitles, a quarter of 10 s windows were more than
    0.6 s off.
  - Speech detection without words (Silero VAD, or loudness) was tried and dropped. On Amélie, which is in sync, it
    reported eight stretches out of step.
  - Tested on Amélie: a 3-minute stretch moved by 1.2 s was found (measured as 1.3 s), on both the French subtitles
    and the English ones measured through the French. After `--fix`, the re-check was clean.

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
4. **Originals are never changed.** Scripts write `.aligned.srt`, `.bak` and new files beside the original. Keep it
   that way in new code.
5. **Test before saying it works.**
   - Run `python3 -m pytest -q` (no network, no API, synthetic clips) and `ruff check` on the files you touched.
   - For anything that measures audio or timing, also try it on real media and report the numbers.
   - Separate what you ran from what you inferred.
6. **Keep scripts runnable on their own.** Use the Python 3.9+ stdlib, plus numpy, Pillow and faster-whisper only
   where already used. Every step prints the command it runs.
7. **Write for Erin.** Plain English in messages and docs, and say what to do next. She runs macOS (Apple
   Silicon, Homebrew, Python 3.14) and works in Terminal.

## Agents in this project

| Agent | Model | Job |
|---|---|---|
| `subtitle-prep` | Haiku | Find subtitles, run the sync and alignment checks, and summarise what the reports say. It runs scripts and reads their output; it doesn't write code. |
| `note-writer` | Opus | Write the notes for ONE part of a film (`chat_notes.py show`) as a JSON array, saved as `part-<k>.txt`. This replaces the API's `--generate` and runs on the subscription. |

Commands: `/notes <video> [options]` (subscription-written notes, end to end) and `/check <video>` (subtitles,
sync, alignment and repeats, with no API use).
