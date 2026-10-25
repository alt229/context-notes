# Context Notes in a container: the web app, ffmpeg, and Claude Code (for the subscription backend).
# Build and run with docker compose (see docs/docker.md). Nothing here is specific to one site:
# the domain, the films folder and the rest come from .env.
FROM python:3.12-slim-bookworm

ARG PUID=1000
ARG PGID=1000
ARG WITH_WHISPER=0          # 1: also install faster-whisper (speech recognition; a large download)

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd -g "${PGID}" app && useradd -m -u "${PUID}" -g "${PGID}" -s /bin/bash app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir numpy Pillow \
 && if [ "${WITH_WHISPER}" = "1" ]; then pip install --no-cache-dir faster-whisper; fi

USER app
ENV HOME=/home/app \
    PATH="/home/app/.local/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    CONTEXT_NOTES_PLACES=/media

# Claude Code, so --backend claude-code works in the container. Sign in once with:
#   docker compose exec -it app claude auth login
RUN curl -fsSL https://claude.ai/install.sh | bash \
 && mkdir -p /home/app/.config/context-notes /home/app/.claude

# The code last, so a code change doesn't redo the steps above.
COPY --chown=app:app . .

EXPOSE 8080
CMD ["python3", "app.py", "--host", "0.0.0.0", "--port", "8080", "--no-browser", "--hosted", \
     "--key-file", "/home/app/.config/context-notes/app-key"]
