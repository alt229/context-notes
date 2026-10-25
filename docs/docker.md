# Running it in Docker, with HTTPS

Two containers: the app (Python, ffmpeg and Claude Code) and Caddy, a small web server that sits in front of it,
gets a certificate from Let's Encrypt and renews it by itself. Nothing in the files is tied to one site: your
domain, your films folder and the rest go in `.env`.

## What you need

- Docker with Compose (Docker Desktop, or `docker` and `docker compose` on a Linux box).
- A domain whose DNS is on Cloudflare, and a Cloudflare API token with **Zone / DNS / Edit** (and Zone / Zone /
  Read) on that zone. The certificate is proved through a DNS record, so nothing has to be reachable from the
  internet; the name itself can point at a private address (a record on your home router is fine).
- The folder with your films, writable: notes, `.ass` files and the `<video> analysis` folders are written beside
  the videos.

## Setting it up

```bash
cp .env.example .env
nano .env            # DOMAIN, ACME_EMAIL, CLOUDFLARE_API_TOKEN, MEDIA_DIR, PUID/PGID (id -u, id -g), ports
docker compose up -d --build
docker compose logs app   # the page's address, with its key, is printed here
```

The first build compiles Caddy with its Cloudflare plugin (a few minutes) and downloads Claude Code. The page's key
is kept in the `cn_config` volume, so the address stays the same across restarts.

Point your DNS name at the machine running Docker. Then open `https://<your domain>/?k=<key>`; the key is the
only thing standing between the page and anyone else on the network, so share the whole address only with people
who may run things.

## Ports

Caddy takes `HTTPS_PORT` (default 443) and `HTTP_PORT` (default 80, used only to redirect to HTTPS) on the Docker
host. If another service needs those, change them in `.env`; with a non-standard HTTPS port also set `PUBLIC_URL`
(for example `https://films.example.com:8443`) so the printed address and the page's checks match what people type.

## Claude on your subscription

The app can write notes through Claude Code instead of an API key (Settings → Claude). Claude Code in the container
needs a sign-in. There are three ways; use one:

1. **Paste a token in Settings (recommended).** On any computer that has Claude Code, run `claude setup-token` in
   Terminal, sign in in the browser it opens, and copy the token it prints. In the app, choose Settings → Claude →
   "Claude Code, on my Claude subscription", paste the token and press "Save the token", then "Check sign-in". The
   token is kept in the `cn_config` volume, readable only by the app. Saving the box empty removes it. Nothing has
   to be mounted.
2. **Sign in inside the container.** `docker compose exec -it app claude auth login`, follow the link it prints,
   paste the code back. The sign-in is kept in the `claude_config` volume (when `CLAUDE_DIR` is empty).
3. **Share a sign-in folder** from the machine running Docker: set `CLAUDE_DIR=/home/you/.claude` in `.env`. The
   folder is shared read-write, because Claude Code refreshes its tokens there.

If both a token and a folder sign-in exist, the token is used. Settings → Claude says if the server is already signed
in another way.

Or use an API key: paste it in Settings; it's kept in the `cn_config` volume, readable only inside the container.

## What's different from running it on your own computer

- The **films live at `/media`** inside the container (your `MEDIA_DIR`), and `/media` is offered in the folder
  chooser. Paths you paste must be as the container sees them, e.g. `/media/Films/Amélie.mkv`.
- **The app starts with `--hosted`**, because your browser is on another computer. The file dialogs ("Choose a
  film…"), "Open in VLC", "Show in folder" and the VLC installer are hidden or refused, since they'd act on the
  server. Each video shows its path instead; play the video in your usual player (the `.notes.ass` is beside it).
  For VLC, download the extension from Settings → VLC extension and put it in VLC's extensions folder on your own
  computer (the page lists where), then restart VLC.
- **Speech recognition** (`--align`, subtitles from the soundtrack) needs `WITH_WHISPER=1` in `.env` before the
  build. It adds a large download and runs on the CPU.
- The app listens on all interfaces inside the container but only answers requests for the one name in `--public-url`
  (plus `127.0.0.1` and `localhost`); Caddy is the only thing that reaches it. The key and the Host/Origin checks
  are the same as when you run `python3 app.py` by hand.

## Looking after it

```bash
docker compose logs -f caddy      # certificate issued? renewals happen by themselves (Caddy renews at 2/3 of the lifetime)
docker compose logs -f app        # what the app is doing
docker compose pull && docker compose up -d --build     # after a git pull
docker compose exec app claude auth status             # is Claude Code signed in? (Settings → Claude shows this too)
docker compose exec app cat /home/app/.config/context-notes/app-key   # the page's key
```

If Caddy can't get the certificate, the usual causes are a token without DNS edit rights on the zone, or `DOMAIN`
not in that zone. Caddy keeps trying with a back-off and logs why.
