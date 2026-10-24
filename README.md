# Context Notes

Pop-up explanations for shows and films: idioms, slang, cultural references, historical context, wordplay, delivery, and sight gags that are easy to miss if you didn't grow up where the show was made.

Notes appear as small boxed overlays while you watch, in VLC (or any player that handles ASS subtitles). Dialogue stays at the bottom; notes about what is *said* pop up top-left just after the line, and notes about what is *on screen* pop up top-right.

![A note about British slang popping up over a subtitled scene](docs/screenshot.png)

> **Status: pre-alpha.** It works end to end, but it is young, tested mostly on English-language British comedy, and the notes are written by an AI. Expect rough edges, and expect the occasional wrong note (see [Limitations](#limitations)).

## Why

- **Watching in a second language.** Idioms, local customs, historic figures and in-jokes get lost when you don't have the background.
- **Archaic language.** Shakespeare and friends: what a word meant then, and which jokes are bawdy.
- **Teaching.** Makes older or foreign material more approachable without a course in front of it.

## How it works

```
 episode.mp4 / episode.srt
        │
        ▼
 analyze.py        transcript, subtitle sync check, loud moments, contact sheets
        │          (optional --align re-times subtitles from another release)
        ▼
 notes JSON        one small file of notes, written by hand or by Claude
        │          make_ass.py --generate   (from the dialogue)
        │          make_ass.py --refine     (re-checked against the video's frames and soundtrack)
        ▼
 make_ass.py       merges subtitles + notes into  <video>.notes.ass
        │
        ▼
 VLC               loads the .notes.ass next to the video; the extension in vlc/ adds topic checkboxes
```

| File | What it does |
|---|---|
| `context_notes.py` | **Start here.** Runs the whole workflow for one video or a folder: finds the subtitles, checks sync (offers `--align` if needed), `--generate`, `--refine`, builds the `.ass`. Skips steps already done. |
| `analyze.py` | Prepares an episode: numbered transcript, pulls embedded subtitles out of an MP4/MKV, checks whether an SRT matches the video, finds loud moments with no dialogue, builds contact sheets, optionally re-aligns subtitles. |
| `make_ass.py` | Merges an SRT and a notes file into one `.ass`. Also the front door for `--generate` and `--refine`. |
| `generate_notes.py` | Calls the Claude API to write a first notes file from the dialogue. (Used through `make_ass.py`.) |
| `refine_notes.py` | Calls the Claude API with frames and loud moments to add visual/delivery notes, fix and retime existing ones. (Used through `make_ass.py`.) |
| `vlc/context_notes.lua` | VLC extension: loads the `.notes.ass` automatically and lets you switch note topics on and off. |
| `align_check.py` | Checks every note against the speech in the seconds before it; reports stretches that are out and can fix them. |
| `find_subs.py` | Finds subtitles for a video that has none beside it: `Subs/` folders, OpenSubtitles.com, or speech recognition. |
| `dedupe.py` | Lists notes that explain something an earlier note already did (the build leaves those out). |
| `chat_notes.py` | Write the dialogue notes in a claude.ai chat or with Claude Code (your subscription) instead of the API. |
| `languages.py` | Language codes and names shared by the scripts (`fr`, `fre`, `French` are all French). |
| `prompts.py` | How the scripts ask questions: in Terminal as usual, or answered by another program such as a GUI ([docs/gui-protocol.md](docs/gui-protocol.md)). |

## Requirements

- Python 3.9 or newer
- `ffmpeg` and `ffprobe` for anything that touches a video (`brew install ffmpeg`, `apt install ffmpeg`, or [ffmpeg.org](https://ffmpeg.org/download.html))
- `pip install -r requirements.txt` (one step: numpy and Pillow for the video checks, faster-whisper for speech recognition, and pytest and ruff for development. faster-whisper is a large download; skip it with `pip install numpy Pillow` if you won't use speech recognition)
- An Anthropic API key, only if you want Claude to write or refine notes

Writing notes by hand and building the `.ass` needs nothing beyond Python.

## Quick start

```bash
git clone https://github.com/alt229/context-notes.git
cd context-notes
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Try the bundled example (no API key, no video needed)
python3 make_ass.py examples/help-desk/the-help-desk.srt examples/help-desk/notes-the-help-desk.json -o /tmp/demo.ass
```

Then with your own episodes (put your own files wherever you like; nothing in this repository needs them to live in it):

```bash
# One-time: save your API key (stored in ~/.config/context-notes/api-key, mode 600)
python3 make_ass.py --set-api-key

# Everything, for one episode or a whole season folder
python3 context_notes.py "/Volumes/Media/TV Shows/IT Crowd/Season 1"
python3 context_notes.py "S01E03 Fifty Fifty.mp4"
python3 context_notes.py "Season 1" --status          # what's done and what's left; runs nothing
python3 context_notes.py film.mkv --limit 5:00        # try the first 5 minutes of a long film
```

`context_notes.py` prints every command before it runs it, so you can see (and rerun) each step. It asks before anything costs money (the scripts' own cost prompts), and only asks you a question when there's a real choice, such as subtitles that drift. `--yes` takes the default answer everywhere, for unattended runs. Rerunning it skips whatever is already done.

The same steps by hand:

```bash
# 1. Is the SRT in sync? (local, free)  --frames none skips the contact sheets, which --refine makes anyway
python3 analyze.py episode.srt --video episode.mp4 --frames none

# 2. Have Claude write a first set of notes from the subtitles (shows a cost estimate and asks first)
python3 make_ass.py episode.srt --generate --video episode.mp4 --title "Show - S01E01 - Title"

# 3. Optional: make it better by letting Claude look at the video
python3 make_ass.py episode.srt --refine --video episode.mp4

# 4. Play episode.mp4 in VLC. episode.notes.ass sits next to it.
```

Your video has subtitles inside it? Skip the SRT: `python3 analyze.py episode.mp4` extracts them (`--list-tracks`, `--sub-track N`, `--strip-sdh` are there if you need them).

## Using it

### `context_notes.py`

```bash
context_notes.py PATH                          # a video, or a folder of videos (--recursive for subfolders)
context_notes.py PATH --status                 # done / to do, per video
context_notes.py PATH --limit 5:00             # first 5 minutes only (also 300, 5m, 1:30:00)
context_notes.py PATH --film-language fr       # see "Films not in English" below
context_notes.py PATH --show "The IT Crowd"    # name used in the titles Claude sees (default: from the folders)
context_notes.py PATH --no-refine              # skip the video-frames step
context_notes.py PATH --redo                   # write the notes again (the old file is kept as .bak)
context_notes.py PATH --yes                    # don't stop to ask anything
```

What it decides for you:

- **Which subtitles.** `<video>.srt`, `<video>.en.srt`, `<video>.English.srt` and so on beside the video; a re-timed `<video>.aligned.srt` if you made one; otherwise the text track inside the video.
- **Sync.** If the subtitles are early or late by a constant amount, the offset goes into the notes file. If the timing drifts (a different cut or release), it offers to re-time them with `analyze.py --align`, carry on, or skip.
- **Title.** `IT Crowd/Season 1/S01E03 Fifty Fifty.mp4` becomes "IT Crowd - S01E03 Fifty Fifty", so the title always matches the file.
- **What's left.** Notes written? Refined? `.ass` older than the notes? Notes made with `--limit` when you now want the whole thing? It runs only what's missing.

### Testing on part of a film: `--limit`

`--limit 5:00` works on `context_notes.py`, `analyze.py` and `make_ass.py --generate/--refine`. Only the first five minutes of dialogue are sent to Claude, and the soundtrack check, frames and `--align` speech recognition stop at five minutes too, so a test costs a few cents and a minute or two. The notes file records the limit; a later full run notices and offers to write notes for the whole film (keeping the old file as `.bak`). A limited `--align` writes `<name>.aligned.first300s.srt`, so it is never mistaken for a full alignment.

### Films not in English

```bash
context_notes.py "Amélie.mkv"                        # audio tagged French? it notices. Otherwise:
context_notes.py "Amélie.mkv" --film-language fr
make_ass.py film.en.srt --generate --film-language fr --original-subs film.fr.srt     # by hand
```

By default you watch with the film's **own-language subtitles** (`film.fr.srt`, or the French track inside the video) and the notes, written in English, explain only what a good non-native reader would miss: idioms and set phrases, false friends, slang and regional speech, **register** (tu/vous, du/Sie, tú/usted and what a switch means), how strong an insult really is, references any native viewer would get, and untranslated text on screen. Notes quote the French exactly (so they attach to the right line) and explain it in English; whole lines are never translated. New categories: `Translation`, `Register`, `Slang`, `Dialect`, `On-screen text`.

**Notes from the French, English subtitles on screen:** add `--show-subs en`. The notes stay exactly where they were found in the French; only the subtitles at the bottom change, so if the notes already exist this just rebuilds the `.notes.ass` (no API cost). The choice is remembered in the notes file, and `--show-subs fr` switches back. Before using the English file it's compared with the corrected French subtitles and shifted if needed. By hand: `make_ass.py film.fr.srt notes.json --video film.mkv --display-subs film.en.srt`.

The notes themselves are in English; `--notes-language Spanish` (or any language) writes them in another.

Want Claude to work *from* the English subtitles instead? `--subs-language en` uses `film.en.srt` and also gives Claude the French lines alongside, so it can point out what the translation loses.

### Subtitles that are early or late

```bash
analyze.py film.fr.srt --video film.mkv --shift auto     # measure against the soundtrack, write film.fr.aligned.srt
analyze.py film.fr.srt --shift -2.5                      # you know the offset: every line 2.5 s earlier
analyze.py film.fr.srt --video film.mkv --shift -2.5     # ...and check the result against the video
```

The corrected copy is `<name>.aligned.srt`; your original is never changed, and `context_notes.py` picks the corrected copy up automatically (it also runs `--shift auto` itself when it finds a constant offset). If the offset changes through the film (a different cut), a single shift can't fix it: use `--align`.

`analyze.py --align --film-language fr` re-times French subtitles with French speech recognition (multilingual `small` model by default). Re-timing only works for subtitles in the language being spoken, so English subtitles for a French film can't be re-timed this way; look for a set made for your release.

### `make_ass.py`

```bash
make_ass.py episode.srt                        # first run: creates a blank notes-<name>.json to fill in
make_ass.py episode.srt notes.json --video episode.mp4     # -> episode.notes.ass
                                                            #    and episode.en.ass, the same file named so Plex lists it as
                                                            #    'English (ASS)' instead of 'Unknown' (--no-plex-copy: skip)
                                                            #    UNFINISHED: on IT Crowd S2/S3 this doesn't work yet in Plex
make_ass.py episode.srt notes.json --layout stack          # notes in one column instead of split left/right
make_ass.py episode.srt notes.json --report                # how crowded each layout would be
make_ass.py episode.srt --generate [--title ... --audience ... --notes-language ...]
make_ass.py episode.srt --refine --video episode.mp4 [--frames dense] [--assume-synced]
make_ass.py episode.srt --generate --limit 5:00                # first 5 minutes only
make_ass.py episode.srt --generate --estimate-only             # size and cost only: nothing sent, nothing written
make_ass.py film.en.srt --generate --film-language fr --original-subs film.fr.srt
make_ass.py --set-api-key
```

`--generate --offset 0.88` also records the offset in the notes file, so later rebuilds line up without it.

`--generate` and `--refine` print a size and cost estimate and ask before anything is sent (`--yes` skips the question). `--estimate-only` prints the estimate and stops. Nothing is sent, no API key is needed, and no notes or `.ass` are written (`--refine` still analyses the video and keeps that for the real run). Both keep backups: the old notes file as `.bak`, and `--refine` also keeps the previous `.ass` and writes a plain-text report of every change.

`--refine` checks the subtitle sync first. If it cannot measure one constant offset (subtitles from a different cut, say), it falls back to *visual-only* notes rather than guessing. Fix the subtitles with `analyze.py --align` and pass the aligned SRT, or use `--assume-synced` if you know they are right. It also refuses to run if the file names suggest the video is a different episode from the notes.

### `analyze.py`

```bash
analyze.py episode.srt                         # numbered transcript
analyze.py episode.mp4                         # extract embedded subtitles + transcript
analyze.py episode.srt --video episode.mp4     # sync check, loud moments, contact sheets
analyze.py episode.srt --video episode.mp4 --align   # re-time subtitles to this video (faster-whisper)
analyze.py episode.srt --video episode.mp4 --frames none   # sync check only (fast)
analyze.py film.mkv --sub-lang fr              # extract the French track -> film.embedded.fr.srt
analyze.py film.fr.srt --video film.mkv --align --film-language fr --limit 5:00
```

The soundtrack measurement is cached in the `<video> analysis` folder, so `--refine` after a sync check doesn't decode the audio a second time.

### No subtitles?

`context_notes.py` looks further when there is no `.srt` beside the video and no text track inside it (or run
`find_subs.py film.mkv --lang de` yourself): a `Subs/` or `Subtitles/` folder (`Subs/2_English.srt`,
`Subs/<film>/English.srt`), and `.srt` files beside it named for the same film but not exactly like it. Then
OpenSubtitles.com, once you've saved a free login with `find_subs.py --set-opensubtitles` (stored in
`~/.config/context-notes/opensubtitles.json`, mode 600); a file uploaded for your exact release comes first, since
its timing will match. Last, it offers to write subtitles from the soundtrack with speech recognition
(`<film>.<lang>.transcribed.srt`). Whatever it finds is copied beside the video; nothing is moved.

### Repeated notes

A film's notes are written in parts, so the same idiom or person can get explained twice. `make_ass.py` leaves a
note out of the `.ass` when an earlier one already explained the same thing, and lists what it left out. The notes
file isn't changed: `--keep-duplicates` builds with everything, `"keep": true` keeps one note, and
`python3 dedupe.py notes.json` shows the repeats and near-misses. Running gags, setups and payoffs are never treated
as repeats.

### How long notes stay up

Each note gets 2 s to be noticed plus its words at 0.4 s a word (150 a minute), between 6 and 24 s. A note that appears while earlier notes are still up stays longer, by half of each earlier note's time (never more than 45 s). `make_ass.py ... --timing-report`
shows how many seconds a word each note gets, which ones the 24 s ceiling cuts short, and how fast the film's own
subtitles go for comparison. Change it per film with `--reading-speed 180`, `--note-max 30`, `--note-min`,
`--note-settle`; the values are remembered in the notes file, so later rebuilds keep them.

### Checking every note's timing

```bash
context_notes.py film.mkv --check-alignment                 # also works on a film that's already done
align_check.py film.mkv film.de.srt                         # by hand; notes found beside the film
align_check.py film.mkv film.en.srt --original-subs film.de.srt --film-language de
align_check.py film.mkv film.de.srt --fix                   # -> film.de.aligned.srt, stretches that were out moved
```

The sync check fixes one offset for the whole film. This goes note by note: it finds the words of the lines in the
10 s before each note (`--window 5` for less) in a speech-recognition transcript of the soundtrack, and reports the
stretches where those lines are more than 0.7 s early or late. English subtitles on a German film are measured
through the German ones. The transcript is made once (slow: very roughly a tenth of the running time) and shared with
`analyze.py --align`. The note-by-note table is in `<video> analysis/alignment.txt`.

### Notes file format

A notes file is JSON: a title, an audience, and a list of notes. A note attaches to a line by quoting it, so the same notes survive a different release of the episode. Full reference, including visual notes, timing options and categories, in [docs/notes-format.md](docs/notes-format.md). A small example:

```json
{
  "title": "Show - S01E01",
  "audience": "Fluent in English, didn't grow up in the UK",
  "notes": [
    {"match": "taking the mickey", "category": "British English",
     "text": "To “take the mickey” is to tease someone. Mildly cheeky, never harsh."},
    {"at_video": "00:14:33,000", "kind": "visual", "category": "Visual gag",
     "text": "The sign behind him reads ..."}
  ]
}
```

## Using it with Claude Code

This folder is also a Claude Code project. Run `claude` in it and:

- `/notes "<film>.mkv"`: Claude Code writes the dialogue notes itself, on your Claude subscription instead of API
  credits. A note-writer agent (Opus) takes the film one part at a time; the result goes through
  `chat_notes.py collect`, then the `.ass` is built and checked for repeats and timing.
- `/check "<film>.mkv"`: subtitles found and synced, every note's timing checked, fixes offered.

`CLAUDE.md` holds what the project has learned so far (benchmark results, defaults, pitfalls). The agents are in
`.claude/agents/`; edit the `model:` line to change which Claude each one uses.

## Running it from another program

The groundwork for a GUI is in place, though there is no GUI yet. A program that starts the scripts with the
environment variable `CONTEXT_NOTES_UI=json` gets every question, hidden prompt, cost estimate and progress report as
a line of JSON on stdout, and answers on stdin. It cancels a run the way Ctrl-C does. Without that variable, nothing
changes. Details and the list of questions are in [docs/gui-protocol.md](docs/gui-protocol.md).

Stopping part-way, with Ctrl-C, a GUI's Cancel or an API error, is safe. The notes Claude has already written, and
a refine's changes so far, are kept. The next run asks whether to pick up where it left off; that's the default, so
nothing you've paid for is sent twice. No file is ever left half-written.

## VLC extension

Copy `vlc/context_notes.lua` into VLC's extensions folder, restart VLC, then choose **VLC → Extensions → Context Notes**.

| OS | Folder |
|---|---|
| macOS | `~/Library/Application Support/org.videolan.vlc/lua/extensions/` |
| Linux | `~/.local/share/vlc/lua/extensions/` |
| Windows | `%APPDATA%\vlc\lua\extensions\` |

The extension looks for `<video name>.notes.ass` beside the video and gives you checkboxes for each kind of note. It has mainly been tried on macOS; reports from other systems are welcome. The `.notes.ass` file also works in any player without the extension, with every note shown.

## API key and cost

- Claude calls use your own Anthropic API key. API usage is billed separately from a claude.ai subscription.
- The key is read from `--api-key-file`, then `~/.config/context-notes/api-key` (or `$XDG_CONFIG_HOME/context-notes/api-key`), then the `ANTHROPIC_API_KEY` environment variable as a fallback. The file must be readable only by you; `--set-api-key` creates it that way.
- Rough costs at the default model's list price: writing notes (`--generate`) is on the order of a few cents per episode; `--refine`, which sends images, is on the order of 10 to 25 cents. The tool shows an estimate and asks before sending. Prices change; check [Anthropic's pricing page](https://platform.claude.com/docs/en/about-claude/pricing).

## Privacy

`--generate` sends the subtitle text to the Anthropic API. `--refine` also sends frames from your video as small JPEG contact sheets. Nothing is sent without the confirmation prompt (unless you pass `--yes`), and nothing else leaves your machine. The scripts use only the Python standard library for networking.

## Limitations

- **Notes are AI-written and can be wrong.** Medium- and low-confidence notes are marked "(less sure)". Treat them as a starting point, especially for historical claims, etymology and "who is this person" notes. Check anything you intend to rely on or teach.
- **Tuned for English-language material.** Foreign-language support (`--film-language`) is new and has been tested only on synthetic clips; expect the prompts to need tuning on real French, German and Spanish films. Non-Latin-script subtitles are untested.
- **Frame sampling is coarse.** A sight gag between sampled frames can be missed.
- **Pre-alpha.** Interfaces and the notes format may change between releases; see the [changelog](CHANGELOG.md).

## Please don't commit media

Do not add video files, full subtitle files, or generated `.ass`/transcripts of commercial shows and films to a public repository. They are copyrighted. The `.gitignore` here excludes the usual suspects, and the bundled example uses an invented scene written for this project. Sharing *notes* files (which contain your own commentary plus short quoted match phrases) is a grey area; when in doubt, share the commentary and leave the dialogue out.

## Development

```bash
pip install -r requirements.txt
pytest          # no network, no API key, no real video needed (a fake API server and synthetic ffmpeg clips are used)
ruff check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE).
