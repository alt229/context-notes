# Emby plugin: findings and open questions

Status: **not started.** Written 2026-10-22 so the work can pick up later. Nothing here is built or tested.

## Goal

An Emby plugin with the same idea as the VLC extension (`vlc/context_notes.lua`): check or uncheck the topics you want
to see more or less of (language and slang, bawdy jokes, history and culture, and so on), and see only those notes.

## What exists today

- The VLC extension filters notes by the tag in each line's ASS "Name" field, `kind/category/confidence`
  (`make_ass.py` writes it, around line 551).
- Its `TOPICS` table maps each category to a checkbox. It lives in `vlc/context_notes.lua`, so it is only available to
  the VLC extension.
- Nothing Emby-related is in the repo. No code, no sample files, no notes.

## Findings

**Emby's plugin model**
- Server plugins are C#/.NET DLLs built against Emby's SDK. Python code can't run inside Emby, so the plugin is a new
  language for this project.
- The SDK has a "Simple UI" template that generates a settings page, which is the natural home for the topic
  checkboxes. Templates and sample code are in the SDK.
- Source: Emby plugin dev docs, https://betadev.emby.media/doc/plugins/dev/index.html
- Source: Emby plugin UI docs, https://betadev.emby.media/doc/plugins/ui/index.html
- Source: older server plugin wiki, https://github.com/MediaBrowser/MediaBrowser/wiki/How-to-build-a-Server-Plugin
- The beta docs may not match the release server. Check the version before building.

**Subtitle display is the real constraint**
- Emby shows one subtitle track at a time. VLC draws each note as its own box, top-left or top-right, over the picture.
  Emby can't do that layout.
- ASS (the format our notes use) is handled badly by many clients. Reports say the styling and fonts are often dropped,
  and that burning subtitles in on the server is the reliable fix. That costs server CPU and gives no per-user choice.
  - https://emby.media/community/topic/118836-question-regarding-ssaass-subtitles
  - https://emby.media/community/topic/136069-ass-subtitles-dont-render-on-android-tv
  - https://emby.media/community/topic/91995-shield-tv-and-ass-subtitles
- These are forum posts from 2017 to 2025, not official documentation. Test them on our own server before relying on them.

## Options

**A. Server plugin, recommended first.**
- Settings page with the topic checkboxes, saved per user.
- On change, build a filtered subtitle file beside the video, the same way `make_ass.py` builds `.notes.ass`.
  Write the notes as plain SRT cues, which every Emby client plays.
- Gives up the boxes and side placement. Notes appear as ordinary subtitle lines.
- Works on every device. Needs a C# build setup, and a rebuild for each Emby release.

**B. Web-client overlay.**
- Closest to the VLC look: boxes over the picture, with checkboxes.
- Web browser only. Doesn't reach TV or phone apps.
- Needs a way to inject JavaScript into Emby's web client. Not verified; Emby may have no supported hook for it.

## Work that helps either option

- Move the `TOPICS` table out of `vlc/context_notes.lua` into a shared JSON file that the VLC extension, the Emby plugin,
  and `make_ass.py` all read. That keeps the category list in one place.

## Open questions for Erin

1. Which devices do you watch on: TV apps, phone, or web? This decides between A and B.
2. Which Emby server version do you run?
3. Should topic choices be per user, or one setting for the whole server?

## Related

- The Plex copy (`<video>.en.ass`) still doesn't work on IT Crowd Seasons 2 to 3. Emby will have the same
  external-subtitle naming problem, so solve it once for both. See `README.md`, "make_ass.py".

## Next step when picked up

A small spike: a C# plugin that adds the checkbox page and writes one filtered SRT. Test it on a real Emby server.
