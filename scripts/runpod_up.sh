#!/usr/bin/env bash
# Bring the whole of AutoPivot up on a RunPod pod, in one command.
#
#   bash scripts/runpod_up.sh            # start everything, print the public URL
#   bash scripts/runpod_up.sh --status   # what is running, and where
#   bash scripts/runpod_up.sh --stop     # stop the app and the tunnel
#   bash scripts/runpod_up.sh --backup   # dump the database to the volume
#
# Database, files, API, built client and a public tunnel. Safe to re-run: it
# skips anything already done, so a second run costs seconds rather than
# repeating a multi-gigabyte install.
#
# Configuration is generated once and kept in $ENV_FILE on the network volume,
# so restarting the pod does not invent a new signing key — which would sign
# every user out — or a new admin password you then have to hunt for.

set -uo pipefail

cd "$(dirname "$0")/.."
PROJECT_DIR="$PWD"

VOLUME="${VOLUME:-/workspace}"
ENV_FILE="${ENV_FILE:-$VOLUME/autopivot.env}"
APP_LOG="${APP_LOG:-$VOLUME/autopivot-app.log}"
TUNNEL_LOG="${TUNNEL_LOG:-$VOLUME/autopivot-tunnel.log}"
PORT="${PORT:-8000}"

say()  { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
info() { printf '  %s\n' "$1"; }
warn() { printf '  \033[33m! %s\033[0m\n' "$1"; }
die()  { printf '\n\033[31merror: %s\033[0m\n' "$1" >&2; exit 1; }

app_pid()    { pgrep -f "python .*autopivot_backend.py" | head -1; }
tunnel_pid() { pgrep -f "cloudflared tunnel" | head -1; }
tunnel_url() {
  grep -ohE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -1
}

# ── Subcommands ──────────────────────────────────────────────────────────────

case "${1:-}" in
  --stop)
    [ -n "$(app_pid)" ]    && kill "$(app_pid)"    && echo "stopped the app"
    [ -n "$(tunnel_pid)" ] && kill "$(tunnel_pid)" && echo "stopped the tunnel"
    echo "PostgreSQL left running — stop it with:"
    echo "  su postgres -c \"\$(ls -d /usr/lib/postgresql/*/bin | tail -1)/pg_ctl -D \$PGDATA stop\""
    exit 0
    ;;
  --status)
    [ -n "$(app_pid)" ]    && echo "app     : running (pid $(app_pid))"    || echo "app     : stopped"
    [ -n "$(tunnel_pid)" ] && echo "tunnel  : running (pid $(tunnel_pid))" || echo "tunnel  : stopped"
    [ -n "$(tunnel_url)" ] && echo "url     : $(tunnel_url)"
    [ -f "$ENV_FILE" ]     && echo "config  : $ENV_FILE"
    exit 0
    ;;
  --backup)
    exec bash scripts/runpod_database.sh --backup
    ;;
esac

# ── 1. Configuration ─────────────────────────────────────────────────────────
say "Configuration"

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  ok "loaded $ENV_FILE"
else
  umask 077
  : > "$ENV_FILE"
  ok "created $ENV_FILE"
fi

remember() {
  # Persist a value only if it is not already recorded, so re-runs are stable.
  grep -q "^export $1=" "$ENV_FILE" 2>/dev/null || printf 'export %s=%q\n' "$1" "$2" >> "$ENV_FILE"
}

if [ -z "${JWT_SECRET:-}" ]; then
  JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  remember JWT_SECRET "$JWT_SECRET"
  ok "generated a signing key"
fi
if [ -z "${SEED_ADMIN_PASSWORD:-}" ]; then
  # Chosen rather than generated: a demo password gets typed by several people
  # under time pressure, and a random one gets pasted wrongly.
  SEED_ADMIN_PASSWORD="autopivot-demo-2026"
  remember SEED_ADMIN_PASSWORD "$SEED_ADMIN_PASSWORD"
fi
if [ -z "${STORAGE_ROOT:-}" ]; then
  STORAGE_ROOT="$VOLUME/autopivot-storage"
  remember STORAGE_ROOT "$STORAGE_ROOT"
fi
export JWT_SECRET SEED_ADMIN_PASSWORD STORAGE_ROOT
mkdir -p "$STORAGE_ROOT"

mountpoint -q "$VOLUME" 2>/dev/null \
  && ok "$VOLUME is a network volume — files and config persist" \
  || warn "$VOLUME is not a mounted volume; everything here dies with the pod"

# ── 2. Database ──────────────────────────────────────────────────────────────
say "Database"
if [ -z "${DATABASE_URL:-}" ]; then
  bash scripts/runpod_database.sh >/dev/null || die "database setup failed — run scripts/runpod_database.sh on its own to see why"
  # shellcheck disable=SC1090
  . "$VOLUME/autopivot-db.env"
  remember DATABASE_URL "$DATABASE_URL"
fi
export DATABASE_URL

if ! pg_isready -q -h 127.0.0.1 -p 5432 2>/dev/null; then
  bash scripts/runpod_database.sh >/dev/null || die "PostgreSQL would not start — see $VOLUME/autopivot-pg.log"
fi
ok "PostgreSQL is up"

# ── 3. Python dependencies ───────────────────────────────────────────────────
say "Python dependencies"
if python3 -c "import fastapi, sqlalchemy, psycopg, PIL, torch" 2>/dev/null; then
  ok "already installed"
else
  info "installing (several minutes on a cold pod)…"
  python3 -m pip install --quiet -r requirements-ml.txt 2>&1 | grep -v "^WARNING: Running pip" || true
  ok "installed"
fi

# transformers tracks torch's internals closely: releases from 4.46 import
# DTensor from torch.distributed.tensor, which torch below 2.5 does not have.
# Unpinned, pip takes the newest and the app dies on import.
if ! python3 -c "from transformers import AutoModelForImageSegmentation" 2>/dev/null; then
  warn "transformers is incompatible with this image's torch — pinning"
  python3 -m pip install --quiet "transformers>=4.40,<4.46" 2>&1 | grep -v "^WARNING: Running pip" || true
  python3 -c "from transformers import AutoModelForImageSegmentation" 2>/dev/null \
    && ok "transformers pinned and importing" \
    || die "transformers still will not import — check the torch version"
fi

# ── 4. Schema and dealership ─────────────────────────────────────────────────
say "Schema and dealership"
alembic upgrade head 2>&1 | grep -E "Running upgrade|ERROR" || true
ok "schema at head"
python3 -m scripts.seed_dealership | sed 's/^/  /'

# ── 5. Client ────────────────────────────────────────────────────────────────
say "Client"
if ! command -v npm >/dev/null 2>&1; then
  [ -s "$HOME/.nvm/nvm.sh" ] || {
    info "installing Node…"
    curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash >/dev/null 2>&1
  }
  # shellcheck disable=SC1090
  . "$HOME/.nvm/nvm.sh" && nvm install --lts >/dev/null 2>&1
fi
command -v npm >/dev/null 2>&1 || die "Node is not available and could not be installed"

if [ -f frontend/dist/index.html ] && [ -z "${REBUILD:-}" ]; then
  ok "already built (REBUILD=1 to force)"
else
  npm ci --prefix frontend >/dev/null 2>&1 || die "npm ci failed"
  npm run build --prefix frontend >/dev/null 2>&1 || die "the client build failed — run it directly to see the error"
  ok "built"
fi

# ── 6. Application ───────────────────────────────────────────────────────────
say "Application"
if [ -n "$(app_pid)" ]; then
  ok "already running (pid $(app_pid))"
else
  # setsid so it outlives this shell and the SSH session.
  HOST=0.0.0.0 PORT="$PORT" setsid nohup python3 autopivot_backend.py > "$APP_LOG" 2>&1 &
  info "starting — first run downloads the background-removal model, ~900MB"
  for _ in $(seq 1 180); do
    curl -sf "http://localhost:$PORT/health/api" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -sf "http://localhost:$PORT/health/api" >/dev/null 2>&1 \
    || die "the app did not come up within three minutes — see $APP_LOG"
  ok "listening on $PORT"
fi

device="$(grep -oE 'device=[a-z]+' "$APP_LOG" 2>/dev/null | tail -1)"
case "$device" in
  device=cuda) ok "running on the GPU" ;;
  device=cpu)  warn "running on CPU — processing will be unusably slow" ;;
esac

# ── 7. Public URL ────────────────────────────────────────────────────────────
say "Public URL"
if [ -z "$(tunnel_pid)" ]; then
  command -v cloudflared >/dev/null 2>&1 || {
    info "installing cloudflared…"
    curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
      -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared
  }
  : > "$TUNNEL_LOG"
  setsid nohup cloudflared tunnel --no-autoupdate --url "http://localhost:$PORT" > "$TUNNEL_LOG" 2>&1 &
  for _ in $(seq 1 40); do
    [ -n "$(tunnel_url)" ] && break
    sleep 1
  done
fi

URL="$(tunnel_url)"
[ -n "$URL" ] || die "the tunnel did not produce a URL — see $TUNNEL_LOG"

# ── Done ─────────────────────────────────────────────────────────────────────
printf '\n\033[1m════════════════════════════════════════════════════════\033[0m\n'
printf '  \033[1mAutoPivot is live\033[0m\n\n'
printf '  URL       %s\n' "$URL"
printf '  Email     ana.reid@northshore.co.nz\n'
printf '  Password  %s\n' "$SEED_ADMIN_PASSWORD"
printf '\033[1m════════════════════════════════════════════════════════\033[0m\n\n'
cat <<NEXT
If a password manager fills something else, that is what the server sees —
check DevTools > Network > login > Payload before assuming the password is wrong.

  bash scripts/runpod_up.sh --status    what is running, and where
  bash scripts/runpod_up.sh --backup    dump the database to the volume
  bash scripts/runpod_up.sh --stop      stop the app and the tunnel
  tail -f $APP_LOG    server log

NEXT

if ! mountpoint -q "$VOLUME" 2>/dev/null || [ ! -d "${PGDATA:-/workspace/autopivot-pgdata}/base" ]; then
  warn "The database is on the container filesystem, not the volume."
  warn "Run 'bash scripts/runpod_up.sh --backup' before stopping the pod."
fi
