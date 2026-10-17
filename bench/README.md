# Benchmarking models and effort settings

Runs the real pipeline (`generate` then `refine`) on the same stretch of a film once per **model x effort** cell,
then reports cost, time, note counts and, optionally, blind-judged quality. Your normal notes files are never
touched; everything lands under `--out`.

| Script | What it does |
|---|---|
| `bench.py` | Runs (or resumes) the matrix. Every API response is cached, so rerunning is free and a crash loses nothing. |
| `judge.py` | Optional blind judge. Pools every cell's notes for each stretch, shuffles and anonymises them, and rates accuracy and usefulness. Dialogue notes are checked against the subtitles, visual notes against the real contact sheets. |
| `report.py` | ASCII tables and bars, a cost/value frontier, `report.md`, `results.csv`, `results.json`. |

## Run it

```bash
cd context-notes
FILM="sample-media/Akira/Akira.1988.1080p.mkv"
SUBS="sample-media/Akira/Akira.1988.1080p.jp.aligned.srt"      # the subtitle file the notes are written from
OUT="sample-media/Akira/bench/run-45min"
KEY="$HOME/.config/context-notes/api-key"

# 1. the matrix (Haiku 4.5 has no effort setting, so it gets one "default" cell automatically)
python3 bench/bench.py run "$FILM" --subs "$SUBS" --film-language jp --limit 45:00 \
    --models claude-haiku-4-5-20251001 claude-sonnet-5-5 claude-opus-5-5 claude-fable-5-1 --efforts low high \
    --cell claude-sonnet-5-5:low:rep2 \
    --out "$OUT" --api-key-file "$KEY" \
    --reuse-analysis "sample-media/Akira/Akira.1988.1080p analysis"       # optional, see below
python3 bench/bench.py status --out "$OUT"

# 2. quality (about $4 with an Opus judge on 45 minutes)
python3 bench/judge.py --out "$OUT" --english-subs sample-media/Akira/Akira.1988.1080p.en.aligned.srt --api-key-file "$KEY"
#    add --original-second-track when SUBS is in the film's own language (real Japanese for Akira); the default
#    wording assumes SUBS is a translation in another language and flags notes that only explain that wording ("ko")
#    for another film also pass --film-desc "the 2001 French film Amélie" --language French --knowledge "the film, French culture and Paris"
#    (the judge's prompts default to Akira)

# 3. tables
python3 bench/report.py --out "$OUT"
```

Adding a candidate later: run `bench.py run ... --cell claude-opus-5-5:xhigh` (any `MODEL:EFFORT[:TAG]`; `TAG` lets you
repeat the same settings), then re-run `judge.py` and `report.py`. A different model in each step is
`--cell claude-sonnet-5-5:high+claude-opus-5-5:medium` (generate `MODEL:EFFORT`, then refine `MODEL:EFFORT`); when the
plain `claude-sonnet-5-5:high` cell is in the same run, the hybrid reuses that cell's generate output instead of
paying for it again. Re-run the **judge for everything together**:
it pools all cells per stretch, so a new cell changes what the judge sees and verdicts are only comparable within one
judge run.

Notes on options:

- `--reuse-analysis DIR` rebuilds the video analysis for `--limit` from an earlier full run's frames, contact sheets
  and soundtrack instead of decoding the film again, and checks the sheet names against the ones on disk. Without it,
  the analysis is computed fresh (slow on a long film, and not every ffmpeg build honours keyframe-only decoding).
- `--budget SECONDS` (also on `judge.py`) stops starting new API calls after that long and exits with code 3, meaning
  "run me again". Only needed where one command can't live long; omit it for a single uninterrupted run.
- `--max-tokens-generate/--max-tokens-refine` default to 16000/12000 here (the pipeline's own limits are 8000/6000), so
  higher efforts are never cut short. Check `truncated` in `results.json` stays 0.
- `--effort` also exists on `make_ass.py --generate/--refine` and `context_notes.py`; with no flag, behaviour is unchanged.
- English-language films: pass `--film-language en` to `bench.py`, and `--single-track` (the writers and the judge read
  the same subtitles) plus `--viewer "a fluent English speaker who didn't grow up in the UK"` to `judge.py`, along with
  `--film-desc/--language English/--knowledge`. `judge.py` saves every judged note with its category in
  `judge-results.json`; `report.py` prints a table of valuable notes by type (history/culture, language, other
  dialogue, visual) from the writers' own category labels.
- `cell.json` and the cached analysis store absolute paths. If a run folder is moved, or the session's mount path
  changes, re-judging and reporting fail until those paths are rewritten (done once for the Amelie folder; the judge
  cache itself still matches because it is keyed on content).
- Subtitle prep for odd inputs: `make_ass.read_text` reads UTF-16 and other encodings (a decode loop that tries
  cp1252 will happily turn UTF-16 into garbage); strip WebVTT colour tags from embedded mov_text tracks.

## Reading the results

"valuable" = a note the judge rated accurate-or-minor and useful (use >= 2), excluding notes that only explain the
subtitle file's other-language wording. Run-to-run noise is measured by repeating cells (`:rep2`); treat gaps smaller
than that as noise. The judge is a Claude model and fallible: in a spot-check it caught real hallucinations but also
wrongly flagged one correct note. It sees frames at contact-sheet resolution only. Spot-check anything surprising.

## Subtitle input (Akira)

Run 1 (`run-45min/`) was written from `Akira.1988.1080p.jp.srt`, which at the time was a **Korean** subtitle file, so
10 to 16 of every ~30 dialogue notes explained Korean wording that isn't in the film or the English subtitles you watch
with. Run 2 (`run-45min-jp/`) uses a real Japanese SRT (hearing-impaired style: speaker labels and sound cues in
parentheses). Check sync first: `analyze.sync_check` found it a constant 1.98 s early, so the run uses a copy shifted
by +1.98 s (`run-45min-jp/_prep/Akira.1988.1080p.jp.shifted.srt`; `analyze.py ... --shift auto` makes the same thing).
Treat run 1's dialogue-note numbers as unreliable: Opus looked no better than Sonnet on dialogue notes only because
its extra notes were Korean-wording notes, which "valuable" excludes. The visual-note numbers in run 1 are fine.

## Results

Run 1, Korean subtitle file (`run-45min/report.md`): Haiku 4.5 invents about half of its on-screen notes; Sonnet 5.5
high is the best value; Opus 5.5 high is the quality ceiling; Fable 5.1 costs about 3 times what Opus does for no more
valuable notes; medium was worth running only for Sonnet and Opus.

Run 2, real Japanese subtitles, first 45 minutes, October 2026 (`run-45min-jp/report.md`). Cost is what the cell would
cost run alone; the hybrids share Sonnet's generate output.

| cell (generate + refine) | cost | notes | valuable | fully accurate | wrong | illuminating (use 3) | valuable per $ |
|---|---|---|---|---|---|---|---|
| Sonnet high | $0.53 | 91 | 68 | 54% | 10 | 3 | 128 |
| Sonnet high + Opus low | $0.86 | 89 | 84 | 75% | 3 | 10 | 97 |
| Sonnet high + Opus medium | $1.07 | 101 | 93 | 80% | 2 | 13 | 87 |
| Sonnet high + Opus high | $1.19 | 103 | 94 | 69% | 3 | 9 | 79 |
| Opus high | $1.35 | 112 | 106 | 90% | 0 | 20 | 78 |

- Opus does much better with real Japanese: its dialogue step writes 48 notes ($0.30) against Sonnet's 38 ($0.09),
  and 53 of its 57 dialogue notes are valuable against 35 of 38, with 11 illuminating ones against 1 (Japanese
  history and politics, register, slang, the 1988 tax fight, wordplay).
- Sonnet generate + Opus refine saves about 12% against Opus for both and loses about 11% of the valuable notes and
  more than half of the illuminating ones. Opus's own dialogue step is not where to save money.
- In the hybrids, medium refine is about as good as high (93 vs 94 valuable) for $0.12 less.
- Refine cost is driven by the frames (about 155k input tokens, one frame every ~4.4 s: 610 of the 642 keyframes in 45
  minutes are already used), not by effort: low to high effort moves the refine bill by about 40%.
- Judge cost for these five cells was $2.56; the five cells cost $4.74.

Run 3, Amélie (2001), French dialogue, first 30 minutes, `sample-media/Amelie/Amelie-bench/run-30min/report.md`. Notes were
written from `Amélie.2001.fr.aligned.srt` and judged against `Amélie.2001.en.srt`. 379 keyframes, 29 contact sheets,
about 83k refine input tokens (about half of Akira's). `analyze.sync_check` flags the aligned French file in its last
third (a measurement quirk: it agrees with the in-sync English file to within about 0.3 s all the way through), so no
shift was applied.

| cell (generate + refine) | cost | notes | valuable | fully accurate | wrong | illuminating (use 3) | valuable per $ |
|---|---|---|---|---|---|---|---|
| Sonnet high | $0.30 | 83 | 65 | 65% | 5 | 10 | 213 |
| Sonnet high + Opus medium | $0.66 | 83 | 75 | 87% | 1 | 21 | 113 |
| Opus high | $0.92 | 92 | 87 | 92% | 0 | 20 | 95 |

- The hybrid is much closer to Opus here than on Akira: 14% fewer valuable notes for 28% less cost, and as many
  illuminating notes (21 vs 20). Opus's refine rewrote 12 of Sonnet's 50 dialogue notes (Akira hybrids: 4 to 6),
  fixing some errors (Diana's timeline, Wallace called "a fountain brand") but not all (the couvent/couvent
  pronunciation note stayed wrong).
- Sonnet alone wrote 5 wrong notes (3 visual, 2 dialogue). Two visual ones were checked against the contact sheets and
  the judge was right both times: the chalkboard says 13,80 F/kg (francs), not euros, and the neck-cracking waitress
  wears red, not yellow.
- Sonnet's French dialogue notes held up better than its Japanese ones (43 of 50 valuable, 8 illuminating, against 35
  of 38 and 1 on Akira). Two films, so language and film can't be separated.
- Cost: $1.80 for the three cells plus $1.36 for the judge.

Run 4, four English-language titles, first 30 minutes of each (Blackadder II "Beer" and Red Dwarf "Backwards" are whole
episodes, 29:13 and 27:22). Outputs are in `sample-media/<title folder>/bench/run-30min/` with a `report.md` each. The
fourth cell is new: **Opus high + Sonnet high**, where Opus writes the dialogue notes and Sonnet does the frame pass
(the reverse of the other hybrid). Notes were written from the English subtitles themselves (Blackadder's embedded
track with its colour tags stripped, Romeo and Juliet's UTF-16 SRT converted to UTF-8, Waking Ned Devine's SRT shifted
-1.02 s) and judged with `--single-track --viewer "a fluent English speaker who didn't grow up in the UK"`.

| film | cell (generate + refine) | cost | notes | valuable | fully accurate | wrong | illuminating (use 3) | valuable per $ |
|---|---|---|---|---|---|---|---|---|
| Blackadder II S02E05 (29 min) | Sonnet high | $0.39 | 81 | 60 | 54% | 7 | 6 | 155 |
| Blackadder II S02E05 (29 min) | Sonnet high + Opus medium | $0.69 | 86 | 72 | 67% | 5 | 10 | 104 |
| Blackadder II S02E05 (29 min) | Opus high + Sonnet high | $0.50 | 80 | 70 | 81% | 0 | 16 | 140 |
| Blackadder II S02E05 (29 min) | Opus high | $0.89 | 81 | 73 | 81% | 2 | 17 | 82 |
| Red Dwarf S03E01 (27 min) | Sonnet high | $0.34 | 80 | 54 | 66% | 10 | 7 | 160 |
| Red Dwarf S03E01 (27 min) | Sonnet high + Opus medium | $0.63 | 77 | 65 | 87% | 1 | 13 | 103 |
| Red Dwarf S03E01 (27 min) | Opus high + Sonnet high | $0.47 | 58 | 43 | 62% | 9 | 8 | 92 |
| Red Dwarf S03E01 (27 min) | Opus high | $0.90 | 71 | 68 | 89% | 0 | 23 | 76 |
| Romeo and Juliet 1968 (30 min) | Sonnet high | $0.22 | 58 | 48 | 69% | 1 | 4 | 218 |
| Romeo and Juliet 1968 (30 min) | Sonnet high + Opus medium | $0.47 | 59 | 52 | 80% | 0 | 6 | 111 |
| Romeo and Juliet 1968 (30 min) | Opus high + Sonnet high | $0.39 | 77 | 73 | 87% | 1 | 16 | 185 |
| Romeo and Juliet 1968 (30 min) | Opus high | $0.68 | 76 | 71 | 91% | 1 | 18 | 105 |
| Waking Ned Devine (30 min) | Sonnet high | $0.30 | 62 | 49 | 65% | 4 | 4 | 161 |
| Waking Ned Devine (30 min) | Sonnet high + Opus medium | $0.56 | 66 | 56 | 74% | 4 | 6 | 100 |
| Waking Ned Devine (30 min) | Opus high + Sonnet high | $0.50 | 73 | 60 | 74% | 4 | 4 | 119 |
| Waking Ned Devine (30 min) | Opus high | $0.79 | 79 | 71 | 84% | 2 | 7 | 90 |

Pooled over the four titles (each cell's cost as if run alone; actual spend was $7.43 for the 16 cells plus $5.58 for
the four judge runs):

| cell | cost | valuable | wrong | dialogue notes valuable | frame notes valuable | history/culture valuable (illuminating) |
|---|---|---|---|---|---|---|
| Sonnet high | $1.25 | 211 | 22 | 144 | 67 | 32 (4) |
| Sonnet high + Opus medium | $2.35 | 245 | 10 | 157 | 88 | 37 (6) |
| Opus high + Sonnet high | $1.87 | 246 | 14 | 177 | 69 | 44 (13) |
| Opus high | $3.25 | 283 | 5 | 189 | 94 | 56 (22) |

- Each step follows the model that does it. Dialogue notes written by Opus: 177 to 189 valuable; by Sonnet: 144 to 157.
  Frame notes from an Opus refine: 88 to 94 valuable; from a Sonnet refine: 67 to 69.
- Which half matters depends on the title. Opus high's dialogue notes beat Sonnet high's by 20 valuable notes on
  Romeo and Juliet and on Waking Ned Devine and by none on Red Dwarf; its frame notes beat Sonnet's by 15 on Red Dwarf
  and by only 2 to 3 on those two. So Opus
  high + Sonnet high matched Opus high on Romeo and Juliet (73 vs 71 valuable at 57% of the cost) and nearly on
  Blackadder (70 vs 73), but trailed on Waking Ned Devine (60 vs 71) and failed on Red Dwarf (43 vs 68, 9 wrong:
  Sonnet's frame pass mixed up which character was where). Sonnet high + Opus medium is the mirror image: level with
  Opus on Red Dwarf and Blackadder, barely ahead of Sonnet alone on Romeo and Juliet (52 vs 48).
- Neither hybrid is a safe default across titles; each trails Opus high by 11 to 25 valuable notes on two of the four.
  Opus high on both steps was never more than 2 valuable notes behind the best cell on any title.
- History and culture (the writer's own category labels: cultural reference, historical context, period detail, trivia,
  background): pooled over all six films run so far, Opus high wrote 99 valuable ones, 33 of them illuminating; Sonnet
  high wrote 68, 8 illuminating. Examples only Opus-written notes covered: the UK driving test's number-plate eyesight
  check and Holly's recasting between series 2 and 3 (Red Dwarf); Juliet being not yet 14 against 16 in Shakespeare's
  source poem (Romeo and Juliet).
- Judge reliability: of the 5 notes the judge called wrong in Opus high, I checked 2 against the frames. One was a
  clear judge error (the Romeo and Juliet windows are round glass discs, not a diamond lattice); the other probably was
  (Baldrick is holding the door in the Blackadder frames, though the note's "empty frame" detail can't be seen). So
  Opus's true wrong count is likely 3 to 4 of 307, not 5. The frames did support the judge on Sonnet's Red Dwarf "H"
  mark note (it is on Rimmer, the man in the magenta tuxedo); the bunk-bed note could not be settled at contact-sheet
  resolution. Checked sheets are in `sample-media/spotcheck-run4/`.
- Sync: `analyze.sync_check` is unreliable under a laugh track and on music-heavy audio (Blackadder's three thirds
  disagreed by up to 3.4 s; Waking Ned Devine's estimate moved by about 1.4 s between thirds), so the Blackadder embedded
  track was left as is and Waking Ned Devine got a constant -1.02 s. Treat both as good to about +-1 s.

Escalation (Sonnet first, Opus only for notes it is unsure about), tested offline on the existing runs with no new API
calls. Sonnet high's notes from all six films (454 notes, 37 judged wrong) already carry the writer's own confidence:

| Sonnet's self-reported confidence | notes | wrong | minor-or-wrong |
|---|---|---|---|
| high | 161 | 7 (4%) | 34 (21%) |
| medium | 234 | 22 (9%) | 97 (41%) |
| low | 59 | 8 (14%) | 34 (58%) |

- Confidence carries signal but not enough to route on. Escalating medium and low (65% of notes) catches 30 of the 37
  wrong notes; escalating only low (13% of notes) catches 8. By category, staging, delivery, costume, prop, visual gag,
  background and on-screen-text notes hold 24 of the 37 in 47% of the notes.
- Opus's refine cost about 2.4 times Sonnet's on Akira, so escalating more than about 58% of the work costs more than
  running Opus outright.
- Fixing every wrong note cannot close the gap: on the four run 4 titles Sonnet high wrote 22 wrong notes against a
  72-note valuable gap to Opus high. Most of the gap is notes Sonnet never wrote, which no confidence flag can see.
- Where Sonnet is wrong it is often about who: on Red Dwarf, 8 of its 10 wrong notes swap which character says or does
  something.
