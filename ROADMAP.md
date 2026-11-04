# Roadmap: sharing notes beyond one computer

Written 2026-11-03 from a planning chat with Erin. Everything here is **Proposed** (Claude suggested it) unless it
says **Decided**. Nothing in it is built yet. When a step is done, it leaves this file and goes in the
[changelog](CHANGELOG.md).

## The idea

OpenSubtitles.com hosts `.srt` files that anyone can download for a film. A site for context notes would let people
find notes someone else already wrote, and get them into Plex, Jellyfin, Emby, Kodi or a NAS without running the
whole pipeline themselves.

## The key choice: share the notes, not the `.ass`

- A `.notes.ass` is timed to one release of a film: one cut, one frame rate, one subtitle file. Hosting `.ass` files
  would mean one per release, matched by a hash of the video file, the way OpenSubtitles does it. That's a lot of
  copies of the same notes, most of them slightly out of step.
- The notes file (`notes-*.json`, see [docs/notes-format.md](docs/notes-format.md)) already avoids this. A note
  attaches to a line by quoting a piece of it (`match`), and `make_ass.py` places it against whatever subtitles the
  viewer has, after the sync step. One notes file per film or episode can serve every release.
- So the site hosts notes files, and the viewer's copy of the app (or a plugin, below) builds the `.ass` locally
  against their own video and subtitles. The existing sync and alignment checks (`analyze.py --shift auto`,
  `align_check.py`) then confirm it fits.
- It's also the safer file to share: the notes are our own commentary. The `.ass` and subtitle files carry the
  film's dialogue.

## Step 1: get the notes file ready to share (in this repo, no server)

Useful on its own: it's also how Erin would hand notes to a friend today.

- **A versioned format.** A `format` number at the top of the notes file, and `docs/notes-format.md` as the spec.
  Older files without it read as version 1.
- **Who the film is: built** (2026-11-03, `film_ids.py`, see the changelog): IMDb and TMDB ids, and season, episode
  and series for an episode, in the notes file and the `.ass` header. Still to do: look the ids up as part of a run
  (`context_notes.py`), and the running time.
- **Less dialogue in the file.** `match` should hold only the few words needed to find the line (or a hash of the
  line, if quotes turn out to be a problem). `README.md` already calls shared notes files "a grey area" for this
  reason.
- **`export` and `import`.** `export` writes a clean copy for sharing: no paths from this computer, no subtitle
  file names, no working-file records (`partial`, `unreadable`, `refined.stopped_after`, backups). `import` takes one
  in, then runs the sync check and the build as usual.
- **"Find shared notes first."** A step in `context_notes.py` (and the app) before writing new notes: if shared
  notes exist for this film, offer them, which costs nothing and uses none of the plan.
- **Behind the Scenes.** Share the fact sheet's facts with their sources, never text copied from the source pages.
  The rule that its notes come only from sourced facts (Decided 2026-10-30) makes this straightforward.

## Step 2: a free catalog to test the idea

- A GitHub repository, or a static site on GitHub Pages or Cloudflare Pages: an `index.json` listing titles, and
  one notes file per film or episode.
- Contributions arrive as pull requests, and every one is reviewed before it's listed.
- The app's "Find shared notes" reads `index.json` and downloads the one it needs.
- Costs about $0 and leaves nothing running. It answers the real question first: does anyone want this?

## Step 3: a real site, once people are uploading

Only once step 2 shows real use.

- **Accounts and uploads**, search by title, and an **API** with keys and rate limits, so one app or plugin can't
  overwhelm it.
- **Quality.** AI-written notes have errors (see the model choice in `CLAUDE.md`: 0 to 2 wrong per film on Opus
  high, more on Sonnet), so this matters more than on a subtitle site: flag a wrong note, vote, a version history,
  and corrections that go back to the uploader.
- **Several sets per title**, for different audiences ("Fluent in American English", and note languages other than
  English later).
- **Checked uploads.** Every upload is checked against the format's schema. If `.ass` files are ever accepted, their
  styling tags are stripped: they can be abused to cover the picture or make giant text.
- **A small stack is enough:** one app server, Postgres, object storage behind a CDN. Roughly $10 to $50 a month
  until traffic is large.

## Step 4: getting the notes onto people's TVs

This is where Plex and NAS users actually get the notes. Probably in this order:

- **Bazarr provider.** Most NAS users who run Sonarr and Radarr already let Bazarr fetch their subtitles. A
  "Context Notes" provider would put notes beside every film and episode automatically. Likely the most useful single
  piece.
- **Docker companion.** One container for Synology, Unraid and TrueNAS that watches the media folders, matches each
  video, downloads and builds its notes, and asks Plex, Jellyfin or Emby to rescan. `workfiles.py` and the ignore
  files it writes (`.plexignore`, `.ignore`, `.embyignore`) already handle the folder layout.
- **Plex.** Plex removed third-party plugins in 2018, so nothing can plug into Plex itself. The way in is a file
  beside the video, which Bazarr or the companion writes. Two things to know: many Plex clients burn ASS subtitles
  into the picture on the server (transcoding), and the Plex copy (`<video>.en.ass`) is still unfinished (see
  "Known pitfalls" in `CLAUDE.md`). Solve the Plex copy before this.
- **Jellyfin and Emby.** Both take subtitle-provider plugins written in C#, the way their OpenSubtitles plugins work.
  The Emby findings (one track at a time, ASS often handled badly by clients) are in
  [docs/emby-plugin-plan.md](docs/emby-plugin-plan.md); Jellyfin is likely similar.
- **Kodi.** A subtitle add-on, in Python.
- **VLC.** The extension (`vlc/context_notes.lua`) could download from the site directly.
- **Embedding.** `embed.py` already puts the notes inside an `.mkv` for anyone who wants them there.

## Step 5: the legal and running side

Needed before the site in step 3 opens to the public. Not legal advice: check each with someone who knows.

- **Terms of service, a privacy policy and a takedown policy.** Accounts and email addresses bring in GDPR for
  viewers in the EU.
- **DMCA agent.** In the US, register a DMCA agent with the Copyright Office (about $6). It's what protects a host
  when users upload something they shouldn't. Several subtitle sites have been taken down by rights holders, which
  is the main reason to keep dialogue out of shared files (step 1).
- **An LLC**, once there's money or real traffic, to keep the liability off Erin personally.
- **Claude's terms.** Check them before generating notes for public distribution at scale on a Claude
  subscription. The API's commercial terms are the clearer fit for that.
- **Paying for it.** Donations, or a supporter tier like OpenSubtitles' VIP. Contributors write notes on their own
  plans or credits; the site only stores the results.

## Open

- Whether to go ahead at all, and when (Erin).
- Quoted words or a hash of the line in `match` for shared files: a hash removes the dialogue but makes a notes
  file hard to read or fix by hand.
- Where the catalog lives in step 2: a repository of its own, or a folder of github.com/alt229/context-notes.
- Who reviews contributions in step 2.

## Next step when picked up

Step 1's format number, with `export` and `import` (the film ids are built), tested by sharing one of Erin's finished
films (Breaking Bad S1, say) with a friend whose copy is a different release.
