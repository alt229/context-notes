# Notes file format

A notes file is plain JSON. `make_ass.py` merges it with an SRT to produce the `.ass` overlay. You can write one by hand, let `make_ass.py --generate` write it, or improve it with `--refine`.

```json
{
  "title": "Show - S01E01 - Title",
  "audience": "Fluent in English, didn't grow up in the UK",
  "video_offset": 0.0,
  "notes": [ ... ]
}
```

| Top-level key | Meaning |
|---|---|
| `title` | Shown in the `.ass` header; also used by `--refine` to catch a video from a different episode. |
| `audience` | Who the notes are for. Passed to Claude by `--generate`/`--refine`; informational otherwise. |
| `video_offset` | Seconds added to every subtitle-based note time, so the notes line up with *this* video file. `--refine` writes it when it can measure a constant offset, and `--generate --offset N` records N. `--offset` on the command line overrides it. |
| `film_language` | Two-letter code of the language spoken (`fr`, `de`, `es`...), when it isn't English. Written by `--generate --film-language`; `--refine` reuses it. |
| `original_subtitles` | File name of the original-language subtitles used with `--original-subs`; `--refine` reuses the file if it's beside the subtitles. |
| `limit` | Seconds: the notes were written for the first part of the video only (`--limit`). `refined.limit` is the same for `--refine`. |
| `timing` | How long notes stay up: `{"wpm": 150, "settle": 2, "min": 6, "max": 24}` (any of the four; the rest default). Written when you give `--reading-speed`, `--note-settle`, `--note-min` or `--note-max` to `make_ass.py`. |
| `display_subtitles`, `display_offset` | Subtitles shown at the bottom instead of the ones the notes are placed on (`--display-subs`). |
| `notes` | The list of notes. |

Any other top-level keys are kept and ignored.

## A note

```json
{"match": "taking the mickey", "category": "British English",
 "text": "To “take the mickey” is to tease someone.", "confidence": "high"}
```

| Key | Required | Meaning |
|---|---|---|
| `text` | yes | The note itself. Curly braces are shown as parentheses; `\n` makes a line break. |
| `category` | no (default `Note`) | A label shown in the note's heading, used by the VLC extension to filter by topic. See below. |
| `confidence` | no (default `high`) | `high`, `medium` or `low`. Medium and low show a "(less sure)" flag. |
| `kind` | no (default `speech`) | `speech` for notes about what is said (top-left), `visual` for notes about what is on screen (top-right in the default layout). |
| `keep` | no | `true` keeps the note even if it repeats an earlier one (see "Repeats" below). |

### Where a note attaches (use one)

| Key | Clock | Meaning |
|---|---|---|
| `match` | subtitle | A distinctive piece of the line, matched ignoring case, punctuation and accents. Survives different releases of the same episode. |
| `occurrence` | | With `match`: use the Nth hit instead of the first. |
| `cue` | subtitle | The cue number in the SRT. Brittle across releases; used as a fallback by the generators. |
| `at` | subtitle | `"hh:mm:ss,mmm"` on the subtitle file's clock (`video_offset` is applied). |
| `at_video` | video | `"hh:mm:ss,mmm"` on the video's own clock (`video_offset` is *not* applied). Use this for visual notes. |

Notes are placed in order, and `match` searches forward from the previous match, so list speech notes in the order the lines occur.

### Timing

| Key | Meaning |
|---|---|
| `when` | `"start"` shows the note as the line begins. Default is just after the line ends, so the joke lands before the explanation. |
| `delay` | Extra seconds to wait before showing the note. |
| `duration` | Seconds on screen. Default: 2 s to notice the note plus its words at 150 a minute, kept between 6 and 24 s (change for a whole film with the top-level `timing`). `make_ass.py --timing-report` shows how many seconds a word each note gets and which ones the ceiling cuts short. |

## Repeats

When a later note explains something an earlier one already did (the same quoted term or name, mostly the same
words), `make_ass.py` leaves it out of the `.ass` and says so. The notes file isn't changed. `python3 dedupe.py
notes.json` lists the repeats and the near-misses it kept; `--keep-duplicates` builds with everything, and
`"keep": true` keeps one note. Running gags, setups and payoffs are never treated as repeats.

## Categories

Any text works. The VLC extension and the colour coding know these (case-insensitive); others still display, in a neutral colour, and appear under no topic checkbox.

- Language, slang & wordplay: `British English`, `British slang`, `Idiom`, `Wordplay`, `Archaic word`, and for films not in English `Translation`, `Register`, `Slang`, `Dialect`
- `Bawdy`
- History & culture: `Cultural reference`, `Historical context`
- `IT in-joke`
- Character & delivery: `Character`, `Delivery`, `Theme`
- Running gags & payoffs: `Running gag`, `Setup`, `Payoff`
- Sight gags & staging: `Visual gag`, `Staging`, `On-screen text`
- Props, sets & costume: `Prop`, `Background`, `Costume`
- Trivia: `Trivia`, `Adaptation`, `About these notes`

## Output tags

In the `.ass`, each note's Name field carries `kind/category/confidence`, for example `visual/prop/medium`. The VLC extension filters on that; other players ignore it.

## Example

[`examples/help-desk/`](../examples/help-desk/) has a complete invented scene: SRT, notes file and the resulting `.notes.ass`.
