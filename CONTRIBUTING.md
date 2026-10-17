# Contributing

Thanks for looking. This is a small pre-alpha project; issues and pull requests are welcome.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
ruff check .
```

The tests need no network, API key or real video: the Claude API is replaced by a small local fake server, and videos are synthesized with ffmpeg (tests that need ffmpeg are skipped when it is missing). Please keep it that way, and never put real API keys, real episodes or full subtitle files in tests or examples.

## Guidelines

- Python 3.9+ and standard library first. The networking code deliberately uses only `urllib`; new dependencies need a good reason and belong in the right `requirements*.txt`.
- Run `ruff check .` and `pytest` before opening a PR. Add a test for any bug you fix.
- Anything that sends data to an API must show what is being sent (size, estimated cost) and ask first.
- Anything that overwrites a user's file must keep a backup.
- Notes the model writes are suggestions. Prompts should push towards marking uncertainty rather than confident guesses.

## Particularly welcome

- Reports from other platforms (Windows, Linux, other players than VLC).
- Non-English source material, and non-Latin scripts.
- Better prompts: fewer wrong notes, better visual-gag detection.
- Example notes written about public-domain or openly licensed material.
