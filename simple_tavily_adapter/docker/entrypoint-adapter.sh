#!/bin/bash
# Adapter entrypoint.
# Mirrors the upstream hermes-agent entrypoint (HERMES_HOME bootstrap + gosu
# drop) but then execs uvicorn instead of `hermes`. The FastAPI server spawns
# `hermes acp` as a subprocess per /research job, so we need hermes wired up
# identically to how the bundled entrypoint would have done it.
set -e

HERMES_HOME="${HERMES_HOME:-/opt/data}"
INSTALL_DIR="/opt/hermes"

if [ "$(id -u)" = "0" ]; then
    if [ -n "$HERMES_UID" ] && [ "$HERMES_UID" != "$(id -u hermes)" ]; then
        usermod -u "$HERMES_UID" hermes
    fi
    if [ -n "$HERMES_GID" ] && [ "$HERMES_GID" != "$(id -g hermes)" ]; then
        groupmod -o -g "$HERMES_GID" hermes 2>/dev/null || true
    fi

    actual_hermes_uid=$(id -u hermes)
    if [ -d "$HERMES_HOME" ] && [ "$(stat -c %u "$HERMES_HOME" 2>/dev/null)" != "$actual_hermes_uid" ]; then
        chown -R hermes:hermes "$HERMES_HOME" 2>/dev/null || true
    fi

    chown -R hermes:hermes /app 2>/dev/null || true
    if [ -d /srv/searxng-docker/jobs ]; then
        chown -R hermes:hermes /srv/searxng-docker/jobs 2>/dev/null || true
    fi

    exec gosu hermes "$0" "$@"
fi

# Running as hermes from here on.
source "${INSTALL_DIR}/.venv/bin/activate"

mkdir -p "$HERMES_HOME"/{cron,sessions,logs,hooks,memories,skills,skins,plans,workspace,home}

[ ! -f "$HERMES_HOME/.env" ] && cp "$INSTALL_DIR/.env.example" "$HERMES_HOME/.env" 2>/dev/null || true
if [ ! -f "$HERMES_HOME/config.yaml" ]; then
    cp /app/hermes-data/config.yaml "$HERMES_HOME/config.yaml" 2>/dev/null \
        || cp "$INSTALL_DIR/cli-config.yaml.example" "$HERMES_HOME/config.yaml" 2>/dev/null \
        || true
fi
if [ ! -f "$HERMES_HOME/SOUL.md" ]; then
    cp /app/hermes-data/SOUL.md "$HERMES_HOME/SOUL.md" 2>/dev/null \
        || cp "$INSTALL_DIR/docker/SOUL.md" "$HERMES_HOME/SOUL.md" 2>/dev/null \
        || true
fi

# Sync bundled skills into HERMES_HOME/skills (merges with any user-mounted
# custom skills that sit alongside the bundle).
if [ -d "$INSTALL_DIR/skills" ]; then
    python3 "$INSTALL_DIR/tools/skills_sync.py" 2>/dev/null || true
fi
if [ -d /app/hermes_skills ]; then
    cp -a /app/hermes_skills/. "$HERMES_HOME/skills/" 2>/dev/null || true
fi

exec "$@"
