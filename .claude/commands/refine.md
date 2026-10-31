---
description: Look at a film's frames with Claude Code (your subscription, no API credits) and improve its notes, one stretch at a time - /refine "<video>" [--frames dense] [--limit 30:00]
argument-hint: "<video>" [--frames dense] [--limit TIME] [--fresh]
disable-model-invocation: true
---

You coordinate the frames step for one film on Erin's subscription: the **frame-reviewer** agent looks at the video
one stretch at a time and adds on-screen notes or fixes the dialogue notes the frames show to be wrong. It is the same
step as the API's `--refine`, with the same instructions, stretches, backups and report. The arguments are:
$ARGUMENTS

Read `CLAUDE.md` first; its rules bind you. Keep your messages short.
On Windows, run every `python3` below as `python` (`python3` there is the Microsoft Store stub).

1. **Find the files.** Run `python3 context_notes.py "<video>" --status`. It says which subtitles the notes are placed
   on (SRT) and whether the notes exist. If there are no notes yet, stop and suggest `/notes "<video>"` first.
2. **Begin.** Run `python3 chat_notes.py show-frames "<video>" "<SRT>" --part 0 [--frames dense] [--limit TIME]`
   (pass `--fresh` only if Erin asked to start again). The first time, it analyses the video (slow, all on this
   computer) and keeps the notes as they are now. It prints `Parts: N`, the mode, which parts already have replies
   (`Done:`) and the next part. Tell Erin N, the mode, and that each part is one Opus agent run on her plan.
   - If it says the subtitles aren't in step with the video, say that only on-screen notes will be added. Erin can
     re-time them first (`analyze.py --align`) and rerun with `--fresh`.
3. **Look at the stretches**, in order, starting at the `Next:` part, one at a time (each part sees what the earlier
   ones changed, so never run two together).
   - Before each part run `python3 usage.py --session --stop-at 90` and put its first line in your update.
     - Exit code 3: the session is 90% or more used. **Don't start the part.** Go to step 4 with what's done, and
       tell Erin she can rerun `/refine` with the same arguments after the reset (it picks up at the next part).
   - Run the **frame-reviewer** agent with VIDEO, SRT and K. When it returns, give its line.
4. **Collect.** Run `python3 chat_notes.py collect-frames "<video>" "<SRT>"`. It applies every reply so far to the
   notes as they were when this began, keeps the old `.ass`, writes the notes and a report of every change. If parts
   are still to do, the notes file says where it stopped, and the next `/refine` picks up there.
5. **Build.** Run `python3 make_ass.py "<SRT>" "<notes file>" --video "<video>" --timing-report` (the notes file is
   the one `--status` named).

Finish with 3 to 5 lines: parts done of N, notes added / revised / retimed / dropped, the report's name, the session
line, next step.
