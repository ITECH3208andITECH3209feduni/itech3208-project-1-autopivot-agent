#!/usr/bin/env bash
# One-shot setup for an AutoPivot test pod.
#
#   export DATABASE_URL=postgresql+psycopg://...
#   export JWT_SECRET=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
#   export HF_TOKEN=hf_...
#   bash scripts/runpod_setup.sh
#
# Installs dependencies, applies migrations, seeds demo data, and reports what
# to run next. Safe to re-run: pip is idempotent, Alembic skips applied
# revisions, and the seed leaves existing rows alone.

set -euo pipefail

cd "$(dirname "$0")/.."

say()  { printf '\n\033[1m== %s\033[0m\n' "$1"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$1"; }
die()  { printf '\033[31merror: %s\033[0m\n' "$1" >&2; exit 1; }

# ── Preflight ────────────────────────────────────────────────────────────────
say "Checking configuration"

[ -n "${DATABASE_URL:-}" ] || die \
  "DATABASE_URL is not set. Point it at a PostgreSQL instance, e.g.
  export DATABASE_URL=postgresql+psycopg://user:pass@host:5432/autopivot"

if [ -z "${JWT_SECRET:-}" ]; then
  warn "JWT_SECRET is not set — a random key will be generated per process,
         so tokens will not survive a restart. For a stable test session:
         export JWT_SECRET=\$(python -c \"import secrets;print(secrets.token_urlsafe(48))\")"
fi

if [ -z "${HF_TOKEN:-}" ]; then
  warn "HF_TOKEN is not set. RMBG-2.0 needs it and the BRIA licence accepted
         at https://huggingface.co/briaai/RMBG-2.0 — BiRefNet will be used as
         the fallback instead. Auth and the dashboard are unaffected."
fi

# A pod's disk is wiped when it is terminated. Anything written under a network
# volume survives; anything else does not, including every processed image.
# On a pod with a network volume mounted, that volume is the only sensible
# default — the previous default put images on disk that dies with the pod, and
# a warning nobody acts on is not a safeguard.
if [ -z "${STORAGE_ROOT:-}" ] && mountpoint -q /workspace 2>/dev/null; then
  STORAGE_ROOT=/workspace/autopivot-storage
  echo "  STORAGE_ROOT defaulted to $STORAGE_ROOT (network volume detected)"
fi
STORAGE_ROOT="${STORAGE_ROOT:-storage}"
case "$STORAGE_ROOT" in
  /workspace/*|/runpod-volume/*) ;;
  *) warn "STORAGE_ROOT is '$STORAGE_ROOT', which is on the pod's ephemeral disk.
         Uploaded and processed images will be lost when the pod is terminated,
         and the database will still hold rows pointing at them. Point it at a
         network volume for anything you want to keep:
         export STORAGE_ROOT=/workspace/autopivot-storage" ;;
esac

if printf '%s' "${DATABASE_URL:-}" | grep -qE '@(localhost|127\.0\.0\.1)'; then
  # A local URL is deliberate when scripts/runpod_database.sh has put PostgreSQL
  # on this pod, and a mistake otherwise. Ask the port which it is rather than
  # assuming — the earlier version of this warning fired on a perfectly good
  # in-pod database and was simply wrong.
  if (command -v pg_isready >/dev/null 2>&1 && pg_isready -q -h 127.0.0.1) \
     || (command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':5432 '); then
    echo "  using the PostgreSQL running on this pod"
  else
    warn "DATABASE_URL points at localhost but nothing is listening there. Either
           run 'bash scripts/runpod_database.sh' to start PostgreSQL on this pod,
           or point DATABASE_URL at a hosted instance."
  fi
fi

echo "  DATABASE_URL  ${DATABASE_URL%%:*}://… (host hidden)"
# Reported as set or unset only. The previous form, ${VAR:+set}${VAR:-unset},
# printed "set" followed by the value itself — putting the signing key and the
# HuggingFace token into the terminal scrollback and shell history.
echo "  JWT_SECRET    $([ -n "${JWT_SECRET:-}" ] && echo set || echo unset)"
echo "  HF_TOKEN      $([ -n "${HF_TOKEN:-}" ] && echo set || echo unset)"
echo "  STORAGE_ROOT  $STORAGE_ROOT"
echo "  GPU           $(command -v nvidia-smi >/dev/null 2>&1 \
                        && nvidia-smi --query-gpu=name --format=csv,noheader | head -1 \
                        || echo 'none detected — models will run on CPU')"
export STORAGE_ROOT

# ── Dependencies ─────────────────────────────────────────────────────────────
say "Installing dependencies"
# requirements-ml.txt pulls in requirements.txt plus the vision stack. RunPod
# PyTorch images ship torch already; pip leaves the existing build alone rather
# than pulling a second multi-gigabyte wheel.
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-ml.txt
echo "  done"

# ── Schema ───────────────────────────────────────────────────────────────────
say "Applying migrations"
alembic upgrade head
echo "  schema at head"

# ── Provisioning ─────────────────────────────────────────────────────────────
say "Provisioning the dealership"
# Creates one dealership and one administrator, and nothing else. Safe to
# re-run against a hosted database that already has them.
python -m scripts.seed_dealership

# ── Next steps ───────────────────────────────────────────────────────────────
say "Ready"
cat <<'NEXT'
Start the full application — autopivot_backend.py, not uvicorn api.app:app.
Only this entrypoint registers the vehicle processor; the light API answers
503 on /api/listings/{id}/process by design.

    HOST=0.0.0.0 PORT=8000 python autopivot_backend.py

Startup loads the background-removal models, which are downloaded on first
run — a couple of gigabytes. Watch for this line before testing:

    AutoPivot ready — device=cuda  active_bg_model=...

If it says device=cpu, the GPU is not visible to torch and processing will be
unusably slow.

Expose port 8000 through the pod's HTTP settings, or:

    ngrok config add-authtoken <token> && ngrok http 8000

Then, against the public URL:

    /docs                       try /auth/login, then the listings endpoints
    /health                     per-model readiness
    /api/listings               create a vehicle
    /api/listings/{id}/images   attach photographs
    /api/listings/{id}/process  run the pipeline
    /api/listings/{id}/jobs     poll progress

Set ALLOWED_ORIGINS to include wherever the React client is served from, or
its requests will be blocked before they arrive:

    export ALLOWED_ORIGINS=https://your-tunnel-url

The React client is not served by this process. Run it locally against the
tunnel, or build it and serve the output separately:

    npm run build --prefix frontend
NEXT
