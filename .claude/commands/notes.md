---
description: Write a film's dialogue notes with Claude Code (your subscription, no API credits), build the .ass and check it - /notes "<video or folder>" [--film-language de --original-subs <file>] [--limit 30:00]
argument-hint: "<video or folder>" [--film-language LANG] [--original-subs SRT] [--title "..."] [--limit TIME]
disable-model-invocation: true
---

You coordinate writing context notes for one film, or every video in a folder, on Erin's subscription. The arguments
are: $ARGUMENTS

Read `CLAUDE.md` first; its rules bind you. Keep your messages short.

**A folder.** If the argument is a folder, list its videos with
`python3 context_notes.py "<folder>" --recursive --status`, which includes subfolders.
- Skip every video that already has a `<stem>.notes.ass` beside it.
- Tell Erin which ones are to do, and roughly 2 Opus runs per 25-minute episode.
- Then do steps 1 to 6 for each one, one video at a time and in order. Ask questions as they come up.
- Leave out step 7 per video. At the end, offer the frame pass once for the whole folder: `/refine "<folder>"`
  on the subscription, or on the API `python3 context_notes.py "<folder>" --recursive --model claude-opus-5-5 --effort high`,
  which asks before each video.
- If her usage limit stops the run, rerun `/notes` on the same folder. Finished videos are skipped, and finished
  parts are kept.
- Finish with one line per video, then the next step.

0. **Find the release year.** Run `python3 chat_notes.py year "<video>" [--title "..."]` (the title only if Erin gave one).
   - If it prints `year: 1981 (from ...)`, use it. Say the year and where it came from, in one line.
   - If it prints `year: none`, ask Erin with AskUserQuestion: "No release year is in the file, its folder or the title.
     Look it up online?" Options: "Yes, look it up (Recommended)" (first, so it is the default) and "No, skip it".
   - On yes, use WebSearch for the film's title and "release year". Take the year of the original release, not a remake
     or a re-release. Tell Erin the year you found and the source. Then pass `--year <year>` to every later step.
   - On no, carry on without `--year`. The old-film rule stays off.
   - Pass the same `--year` to every later `chat_notes.py` step (`prepare` and `collect`).

1. **Work out the files.** The video comes from the arguments. Find the subtitles the notes will be placed on with
   `python3 context_notes.py "<video>" --status`. For a film not in English watched with English subtitles, also
   pass the original-language file with `--original-subs` and `--film-language`. If there are no subtitles, delegate
   to the **subtitle-prep** agent first. If anything is unclear, ask Erin with AskUserQuestion.
2. **Check sync before writing.** Delegate to **subtitle-prep** (sync only, there are no notes yet). If the timing
   drifts, ask Erin whether to re-time first (`analyze.py --align`, slow and local).
3. **Prepare.** Run `python3 chat_notes.py prepare "<video>" "<srt>" [options] -o "<video folder>/<stem>.chat-upload.txt"`.
   Note the number of parts N. Replies go in `"<video folder>/<stem> chat-replies/"`.
4. **Write.**
   - Tell Erin N, and that each part is one Opus agent run on her plan's usage.
   - Run the **note-writer** agent once per part. Do parts in order, two at a time at most (K and K+1 together),
     so each part sees what earlier parts covered.
   - If her usage limit stops the run, the finished part files stay. Rerun `/notes` with the same arguments and skip
     the parts already in the folder.
5. **Collect.** Run `python3 chat_notes.py collect "<video>" "<srt>" "<replies folder>" [same options] --model-label "Opus in Claude Code"`.
   If a notes file already exists, ask Erin before adding `--force`.
6. **Build and check.**
   - Run `python3 make_ass.py "<srt>" "<notes>" --video "<video>" --timing-report`.
   - Delegate to **subtitle-prep** for the alignment check.
   - If stretches are out, ask Erin whether to run `align_check.py ... --fix` and rebuild from the `.aligned.srt`.
7. **Offer the frame pass.** The on-screen notes (what's in the frames: signs, props, costume, period detail) are a
   separate pass. Offer two routes, the subscription first:
   - `/refine "<video>"` with the same options: Claude Code looks at the frames itself with the **frame-reviewer**
     agent, one Opus run per part on her plan's usage, no API credits.
   - The API: `python3 context_notes.py "<video>" --model claude-opus-5-5 --effort high` skips generate because the
     notes exist. Show its cost estimate and run it only if Erin says yes.

Finish with 3 to 5 lines: notes written, repeats left out, timing, alignment, next step.
