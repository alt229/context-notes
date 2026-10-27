# Security

## Reporting a problem

Please report security issues privately using GitHub's "Report a vulnerability" button on the Security tab (private vulnerability reporting), rather than a public issue.

## Things worth knowing

- The Anthropic API key is stored in `~/.config/context-notes/api-key` with mode 600 in a mode 700 directory, and the tools refuse to use a key file other users can read. Never commit a key; `.gitignore` excludes `api-key`, `*.key` and `.env`.
- `--generate` and `--refine` send subtitle text (and, for `--refine`, video frames) to the Anthropic API, after a confirmation prompt.
- The scripts run `ffmpeg`/`ffprobe` on files you give them. Treat video files from untrusted sources with the usual caution.
- `~/.config/context-notes/settings.json` holds this install's defaults and the starting folder you chose. It holds no keys or passwords; those stay in their own files.
- `~/.config/context-notes/probe-cache/` keeps `ffprobe`'s answers about your films (file paths, sizes, and track details such as titles and languages), so a file on a NAS is read once. Nothing in it is sent anywhere. Delete the folder to clear it.
