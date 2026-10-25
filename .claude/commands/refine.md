---
description: Add the on-screen notes to a film with Claude Code (your subscription, no API credits) - Claude looks at frames from the video, adds notes about what's on screen, fixes and retimes the dialogue notes, then the .ass is rebuilt and checked - /refine "<video or folder>" [--film-language de --original-subs <file>] [--frames dense] [--limit 30:00]
argument-hint: "<video or folder>" [--film-language LANG] [--original-subs SRT] [--title "..."] [--year YEAR] [--frames keyframes|dense] [--limit TIME] [--assume-synced]
disable-model-invocation: true
---

You coordinate the frame pass for one film, or every video in a folder, on Erin's subscription. The arguments are:
$ARGUMENTS

Read `CLAUDE.md` first; its rules bind you. Keep your messages short. Nothing here uses the API: never run
`--refine`, `--generate` or `context_notes.py` without `--status`.

**A folder.** If the argument is a folder, list its videos with
`python3 context_notes.py "<folder>" --recursive --status`, which includes subfolders.
- Skip videos with no notes yet (say which, and that `/notes` writes them) and videos already marked "refined".
- Do steps 1 to 5 for each of the others, one video at a time and in order.
- If her usage limit stops the run, rerun `/refine` on the same folder: finished videos are skipped, and finished
  parts are kept.
- Finish with one line per video.

1. **Work out the files.** Run `python3 context_notes.py "<video>" --status`. It names the subtitle file and the notes.
   - If it says "no notes yet", stop: the dialogue notes come first. Say: run `/notes "<video>"` first.
   - If it says "refine stopped part-way", carry on: the steps below pick up where it stopped.
   - For a film not in English watched with English subtitles, pass `--original-subs` and `--film-language` as
     `/notes` did (the notes file remembers them, so they are only needed if Erin gives them).
   - Pass every option Erin gave (`--title`, `--year`, `--frames`, `--limit`, `--assume-synced`, the language ones)
     to every `chat_notes.py` step below, the same way each time.
2. **Count the parts.** Run `python3 chat_notes.py show-frames "<video>" "<srt>" --part 0 [options]`. The first run
   analyses the video (frames and soundtrack, all on this computer; a few minutes for a film) and is then cached.
   It prints `Parts: N`, the mode line and `To do: parts F to N`.
   - Tell Erin N (or how many are left), that each part is one Opus agent run with 4 images on her plan's usage, and
     the mode. "On-screen notes only" means the subtitles couldn't be matched to this video's soundtrack, so the
     existing notes will be left alone; if she has an `.aligned.srt` in use, offer `--assume-synced`.
   - Replies go in `"<video folder>/<stem> frame-replies/"`.
3. **Review.** Run the **frame-reviewer** agent once per part from F to N, in order, two at a time at most (K and
   K+1 together), giving it the video, the subtitle file, K, the replies folder and the options. Skip every part
   whose `frames-K.txt` is already in the folder, so a rerun after a usage limit carries on where it stopped.
   If a run fails or its file is missing afterwards, run that part again before going on.
4. **Collect.** Run `python3 chat_notes.py collect-frames "<video>" "<srt>" "<replies folder>" [options] --model-label "Opus in Claude Code"`.
   It keeps a backup of the notes and of the old `.ass`, applies the parts in order and writes a report of every
   change beside the notes. If it stops at a missing part, do step 3 for that part and run it again.
5. **Build and check.**
   - Run `python3 make_ass.py "<srt>" "<notes>" --video "<video>" --timing-report`.
   - Delegate to **subtitle-prep** for the alignment check.
   - If stretches are out, ask Erin whether to run `align_check.py ... --fix` and rebuild from the `.aligned.srt`.

Finish with 3 to 5 lines: notes added, revised, retimed and dropped (from collect-frames), where the report is,
timing, alignment, next step.
