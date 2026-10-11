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

# The app as it appears in the process table: `python3 autopivot_backend.py`
# as step 6 starts it, or `python autopivot_backend.py` as runpod_setup.sh says
# to start it by hand — any interpreter name or path, flags allowed. The old
# pattern wanted a space straight after "python", so it never matched the
# python3 started below: --status said stopped, --stop left it running, and a
# re-run started a second copy that loaded the models onto the GPU and then
# could not bind the port. Anchored to the start of the command line, so a
# process that only mentions the file (grep, an editor, a test run) is not it.
app_pid()    { pgrep -f '^([^ ]*/)?python[0-9.]* ([^ ]* )*([^ ]*/)?autopivot_backend\.py( |$)' | head -1; }
tunnel_pid() { pgrep -f "cloudflared tunnel" | head -1; }
tunnel_url() {
  grep -ohE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -1
}

# RunPod's own HTTP proxy, as an alternative to the cloudflared tunnel above.
# Deterministic from the pod ID RunPod already injects as an env var — no
# process to start, nothing to poll for. Stable for the pod's whole life:
# stopping and starting keeps the same pod ID, so this URL survives a restart
# where the tunnel's does not. The one thing it needs that this script cannot
# do for you: port 8000 has to be marked as an exposed HTTP port on the pod
# itself, in RunPod's own dashboard (pod settings, or at creation). If that
# was never set, this prints a URL that will not resolve — the tunnel above
# is what still works unconditionally, which is why it is not being replaced.
runpod_proxy_url() {
  [ -n "${RUNPOD_POD_ID:-}" ] && echo "https://${RUNPOD_POD_ID}-${PORT}.proxy.runpod.net"
}

# Vast.ai's own direct port mapping — the equivalent stable alternative to
# the cloudflared tunnel above, for a pod running there instead of on
# RunPod. Vast injects one VAST_TCP_PORT_<internal> env var per port the
# instance was actually rented with mapped (chosen when the instance was
# created, not something this script can change after the fact) — if $PORT
# was one of them, PUBLIC_IPADDR plus that mapped port reaches the API
# directly, no tunnel and no rate limit to hit. Empty if $PORT was never
# one of the ports requested at creation, which this script has no way to
# fix from inside the pod either.
vast_proxy_url() {
  local var_name="VAST_TCP_PORT_${PORT}"
  local mapped_port="${!var_name:-}"
  [ -n "$mapped_port" ] && [ -n "${PUBLIC_IPADDR:-}" ] \
    && echo "http://${PUBLIC_IPADDR}:${mapped_port}"
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
    [ -n "$(runpod_proxy_url)" ] && echo "proxy   : $(runpod_proxy_url)  (stable — needs port $PORT exposed as HTTP on this pod)"
    [ -n "$(vast_proxy_url)" ] && echo "proxy   : $(vast_proxy_url)  (Vast.ai's own port mapping — stable, no tunnel involved)"
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
# It holds the signing key and both admin passwords — including a file made by
# hand, or by a version of this script that did not set its mode.
chmod 600 "$ENV_FILE" 2>/dev/null \
  || warn "could not restrict $ENV_FILE to its owner (chmod 600) — it holds the signing key and admin passwords"

remember() {
  # Persist a value only if it is not already recorded, so re-runs are stable.
  grep -q "^export $1=" "$ENV_FILE" 2>/dev/null || printf 'export %s=%q\n' "$1" "$2" >> "$ENV_FILE"
}

# An admin password, generated. These accounts are reachable from the public
# URL the moment the tunnel is up, and a password written in this repository
# — as the demo ones used to be — is one anyone who finds the URL can sign in
# with first; being made to change it at first sign-in then only asks them to
# pick their own. Grouped, and without look-alike characters (no 0/o, 1/l/i),
# because it still gets typed by several people under time pressure.
new_password() {
  python3 -c 'import secrets
alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
print("-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4)))'
}

if [ -z "${JWT_SECRET:-}" ]; then
  JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
  remember JWT_SECRET "$JWT_SECRET"
  ok "generated a signing key"
fi
# One each, rather than one shared: the accounts sit at different roles (one
# dealership's admin, and the whole platform's), and one password leaking
# should not open both.
if [ -z "${SEED_ADMIN_PASSWORD:-}" ]; then
  SEED_ADMIN_PASSWORD="$(new_password)"
  [ -n "$SEED_ADMIN_PASSWORD" ] || die "could not generate an admin password — is python3 working?"
  remember SEED_ADMIN_PASSWORD "$SEED_ADMIN_PASSWORD"
  ok "generated the dealership admin's password"
fi
if [ -z "${SEED_PLATFORM_ADMIN_PASSWORD:-}" ]; then
  SEED_PLATFORM_ADMIN_PASSWORD="$(new_password)"
  [ -n "$SEED_PLATFORM_ADMIN_PASSWORD" ] || die "could not generate an admin password — is python3 working?"
  remember SEED_PLATFORM_ADMIN_PASSWORD "$SEED_PLATFORM_ADMIN_PASSWORD"
  ok "generated the platform admin's password"
fi
if [ -z "${STORAGE_ROOT:-}" ]; then
  STORAGE_ROOT="$VOLUME/autopivot-storage"
  remember STORAGE_ROOT "$STORAGE_ROOT"
fi
export JWT_SECRET SEED_ADMIN_PASSWORD SEED_PLATFORM_ADMIN_PASSWORD STORAGE_ROOT
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
# Every module the app needs before it can serve a request, not a sample. A
# PyTorch pod image already ships torch, fastapi and friends, so a short list
# here declares "already installed" and skips the install — and then the very
# next step runs alembic, which was never one of the things checked for.
REQUIRED_MODULES="fastapi, sqlalchemy, psycopg, PIL, torch, alembic, bcrypt, jwt, bs4, httpx"

if python3 -c "import ${REQUIRED_MODULES}" 2>/dev/null; then
  ok "already installed"
else
  info "installing (several minutes on a cold pod)…"
  PIP_LOG="$VOLUME/autopivot-pip.log"
  if ! python3 -m pip install -r requirements-ml.txt >"$PIP_LOG" 2>&1; then
    tail -30 "$PIP_LOG" | sed 's/^/  /'
    die "installing dependencies failed — full output in $PIP_LOG"
  fi
  if ! IMPORT_ERROR=$(python3 -c "import ${REQUIRED_MODULES}" 2>&1); then
    printf '  %s\n' "$IMPORT_ERROR"
    die "dependencies installed but will not import — see $PIP_LOG"
  fi
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

# Run through `python3 -m` rather than the `alembic` console script: the script
# lands in a bin directory that is not always on PATH in a pod's shell, and
# "command not found" here used to be swallowed along with everything else.
MIGRATE_LOG="$VOLUME/autopivot-migrate.log"
if python3 -m alembic upgrade head >"$MIGRATE_LOG" 2>&1; then
  grep -E "Running upgrade" "$MIGRATE_LOG" | sed 's/^/  /'
  ok "schema at head"
else
  sed 's/^/  /' "$MIGRATE_LOG"
  die "the migrations failed — full output in $MIGRATE_LOG"
fi

# The migrations reporting success is not the same as the tables being there:
# a DATABASE_URL pointing somewhere unexpected would migrate one database while
# the app reads another, and the first symptom is a login failing with
# "relation users does not exist" long after this script said it was fine.
python3 -m scripts.verify_schema 2>&1 | sed 's/^/  /'
[ "${PIPESTATUS[0]}" -eq 0 ] || die "the schema is not queryable — see the output above"

python3 -m scripts.seed_dealership 2>&1 | sed 's/^/  /'
# Without this the exit status is sed's, so a failed seed reads as a success
# and the admin account simply does not exist.
[ "${PIPESTATUS[0]}" -eq 0 ] || die "seeding the dealership failed — see the output above"

# Separate from the dealership above — a platform administrator belongs to no
# dealership at all, which is exactly what lets it reach the "every dealership
# on the platform" screen rather than one dealership's own roster.
python3 -m scripts.seed_platform_admin 2>&1 | sed 's/^/  /'
[ "${PIPESTATUS[0]}" -eq 0 ] || die "seeding the platform administrator failed — see the output above"

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
# The public tunnel is a convenience, not the only way to reach this pod —
# runpod_proxy_url and vast_proxy_url below are two others, and Cloudflare's
# free anonymous quick-tunnel service rate-limits fairly aggressively on a
# shared-IP host like a rented GPU box, which is a fact about Cloudflare's
# quota, not a sign anything here is broken. A failed tunnel used to abort
# the whole run with `die`; now it is a warning, because the app itself is
# already up by this point regardless of whether the tunnel is.
[ -n "$URL" ] || warn "the tunnel did not produce a URL (see $TUNNEL_LOG) — continuing without it, see the proxy URLs below"

# ── Done ─────────────────────────────────────────────────────────────────────

# Whether each password still signs in to an account, checked against its
# stored hash, so the box below never shows one that has since been changed —
# every account is made to change it at first sign-in. Prints a line per
# password: current, changed, or unknown when there is no such account or the
# database cannot be read. The passwords go through the environment rather
# than the command line, which anyone on the machine can read.
password_state() {  # email password...
  local email="$1"
  shift
  CHECK_EMAIL="$email" CHECK_PASSWORDS="$(printf '%s\n' "$@")" python3 -c '
import os
from api.env import load_environment
load_environment()
from sqlalchemy import select
from sqlalchemy.orm import Session
from api.security import verify_password
from database.connection import get_engine
from database.models import User
email = os.environ["CHECK_EMAIL"].strip().lower()
with Session(get_engine()) as session:
    stored = session.scalar(select(User.password_hash).where(User.email == email))
for password in os.environ["CHECK_PASSWORDS"].split("\n"):
    if stored is None:
        print("unknown")
    else:
        print("current" if verify_password(password, stored) else "changed")
' 2>/dev/null || printf 'unknown\n%.0s' "$@"
}

# One account's lines in the box: heading, email, the password it was seeded with.
show_account() {
  # What this script seeded with before it generated passwords, and the
  # runbook printed. A pod set up back then can still have them, whatever its
  # settings file now says.
  local published=(autopivot-demo-2026 autopivot-platform-2026) states
  states="$(password_state "$2" "$3" "${published[@]}")"
  printf '  %s\n' "$1"
  printf '    Email     %s\n' "$2"
  case "$(printf '%s\n' "$states" | sed -n 1p)" in
    current) printf '    Password  %s\n' "$3" ;;
    changed) printf '    Password  (changed since setup — not shown)\n' ;;
    *)       printf '    Password  (could not be checked — the generated one is in %s)\n' "$ENV_FILE" ;;
  esac
  if printf '%s\n' "$states" | sed -n '2,$p' | grep -qx current; then
    warn "A password published in this repository still signs in to this account:"
    warn "anyone who finds the URL can use it. Sign in and change it now."
  fi
}

PROXY_URL="$(runpod_proxy_url)"
VAST_URL="$(vast_proxy_url)"

# Whether port $PORT is marked as an exposed HTTP port is a RunPod platform
# setting on the pod itself — nothing running inside the pod, this script
# included, can turn it on. What this script CAN do honestly is check whether
# it already happens to be on, rather than print a URL and hope. A real
# response here is /health/api answering; RunPod's own edge returns an
# empty-body 404 for a port it has no route for, which reads nothing like a
# working API and is what you get if this was never enabled.
PROXY_READY=false
if [ -n "$PROXY_URL" ]; then
  PROXY_STATUS="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$PROXY_URL/health/api" 2>/dev/null || true)"
  [ "$PROXY_STATUS" = "200" ] && PROXY_READY=true
fi

# Vast's own mapping is either there or it isn't — decided when the instance
# was created, nothing to poll for — but still worth a real check rather
# than trusting the env var blindly: a stale or reused mapping pointing
# nowhere reads exactly like a working one until something actually asks it
# to answer.
VAST_READY=false
if [ -n "$VAST_URL" ]; then
  VAST_STATUS="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$VAST_URL/health/api" 2>/dev/null || true)"
  [ "$VAST_STATUS" = "200" ] && VAST_READY=true
fi

printf '\n\033[1m════════════════════════════════════════════════════════\033[0m\n'
printf '  \033[1mAutoPivot is live\033[0m\n\n'
if [ -n "$URL" ]; then
  printf '  URL       %s\n' "$URL"
fi
if [ "$PROXY_READY" = true ]; then
  printf '  Stable    %s  (verified — this one survives a pod restart)\n' "$PROXY_URL"
fi
if [ "$VAST_READY" = true ]; then
  printf '  Stable    %s  (verified — Vast.ai'"'"'s own port mapping, survives a pod restart)\n' "$VAST_URL"
fi
if [ -z "$URL" ] && [ "$PROXY_READY" != true ] && [ "$VAST_READY" != true ]; then
  warn "no working public URL yet — see the notes below for what to try"
fi
# The same defaults the two seed scripts use, so an override shows here too.
show_account "Dealership admin" \
  "${SEED_ADMIN_EMAIL:-ana.reid@northshore.co.nz}" "$SEED_ADMIN_PASSWORD"
show_account "Platform admin (belongs to no dealership — for testing dealership creation)" \
  "${SEED_PLATFORM_ADMIN_EMAIL:-admin@autopivot.example.com}" "$SEED_PLATFORM_ADMIN_PASSWORD"
printf '  A password shown here is the initial one; first sign-in asks for a new one.\n'
printf '\033[1m════════════════════════════════════════════════════════\033[0m\n\n'
if [ -n "$PROXY_URL" ] && [ "$PROXY_READY" != true ]; then
  cat <<PROXY
The stable proxy URL ($PROXY_URL) is not answering yet — port $PORT is not
marked as an exposed HTTP port on this pod. That is a RunPod dashboard
setting (pod → Edit → Expose HTTP Ports → add $PORT), not something this
script can turn on from inside the pod. Not required — see below for a way
to skip this altogether.

PROXY
fi
if [ -n "$VAST_URL" ] && [ "$VAST_READY" != true ]; then
  cat <<VASTPROXY
Vast.ai has port $PORT mapped to a public port, but nothing answered there
just now ($VAST_URL). Either the app is still starting up — try
'bash scripts/runpod_up.sh --status' in a few seconds — or this instance's
mapping does not actually reach port $PORT despite the env var existing,
which can happen if the mapping was set up for a different port than this
run used. Re-check with 'env | grep VAST_TCP_PORT_$PORT' if it persists.

VASTPROXY
fi
if [ -z "$URL" ] && [ "$PROXY_READY" != true ] && [ "$VAST_READY" != true ]; then
  cat <<NOURL
No public URL came up this run — every one of URL, the RunPod proxy and the
Vast.ai proxy is either absent or not answering. The app itself is very
likely still fine; check 'tail -f $APP_LOG' and 'bash scripts/runpod_up.sh
--status' before assuming otherwise. If you are on Vast.ai specifically and
no VAST_TCP_PORT_* variable matches port $PORT, this instance was rented
without $PORT in its exposed-port list — the fix is to rerun with PORT set
to one of the ports Vast.ai actually mapped (check with
'env | grep VAST_TCP_PORT'), e.g. 'PORT=8080 bash scripts/runpod_up.sh' —
not something changeable on an instance that already exists.

NOURL
fi
cat <<TUNNELHELP
Simplest path, no dashboard setting and no URL to type on the mobile side —
run this ON YOUR MAC, not here, once this pod's SSH details are in hand
(RunPod console → pod → Connect → "SSH over exposed TCP", not the
ssh.runpod.io proxy variant):

  bash scripts/mobile_dev_tunnel.sh root@<pod-ip> <ssh-port>

Leave it running, then \`flutter run -d "iPhone 17"\` from mobile/ just works —
its default already points at what that tunnel forwards, no URL needed.

TUNNELHELP
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
