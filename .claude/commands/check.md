---
description: Check one video with no API use - subtitles, sync, repeated notes, note timing and every note's alignment with the speech - and offer fixes. /check "<video>"
argument-hint: "<video>" [--film-language LANG] [--original-subs SRT]
disable-model-invocation: true
---

Check the video in $ARGUMENTS. Read `CLAUDE.md`; its rules bind you.

1. Delegate to the **subtitle-prep** agent with the video path and any language options. Show Erin its report as
   it comes back.
2. For each decision it lists, ask Erin with AskUserQuestion. Typical decisions:
   - Fix the out-of-step stretches: `align_check.py ... --fix`, then
     `make_ass.py <the .aligned.srt> <notes> --video <video>`.
   - Re-time the whole file: `analyze.py --align`.
   - Search online for subtitles: `find_subs.py --online`.
   - Raise the note ceiling: `make_ass.py ... --note-max N`.
3. Run what she approves. Re-check after a fix (the transcript is cached, so it's quick). Finish with 3 lines.
