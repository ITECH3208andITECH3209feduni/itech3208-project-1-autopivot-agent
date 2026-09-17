#!/usr/bin/env bash
# Provision PostgreSQL inside a RunPod pod, on persistent storage.
#
#   bash scripts/runpod_database.sh
#   source /workspace/autopivot-db.env      # exports DATABASE_URL
#   bash scripts/runpod_setup.sh
#
# Everything then lives on one machine: database, files and the application.
#
# WHY THE DATA DIRECTORY MATTERS
# A pod's container filesystem is destroyed when the pod is terminated. Only a
# network volume survives. PGDATA defaults to /workspace, which is where RunPod
# mounts one — but /workspace is an ordinary directory when no volume is
# attached, and then the database dies with the pod like everything else. The
# script checks and says which case you are in.
#
# Safe to re-run: an existing cluster is started rather than reinitialised.

set -euo pipefail

cd "$(dirname "$0")/.."

say()  { printf '\n\033[1m== %s\033[0m\n' "$1"; }
warn() { printf '\033[33mwarning: %s\033[0m\n' "$1"; }
die()  { printf '\033[31merror: %s\033[0m\n' "$1" >&2; exit 1; }

PGDATA="${PGDATA:-/workspace/autopivot-pgdata}"
PGPORT="${PGPORT:-5432}"
DB_NAME="${DB_NAME:-autopivot}"
DB_USER="${DB_USER:-autopivot}"
ENV_FILE="${ENV_FILE:-/workspace/autopivot-db.env}"
LOG_FILE="${LOG_FILE:-/workspace/autopivot-pg.log}"

[ "$(id -u)" -eq 0 ] || die "Run as root. RunPod pods give you root by default."

# ── Backup mode ──────────────────────────────────────────────────────────────
# Only needed when the cluster had to fall back to the container filesystem.
if [ "${1:-}" = "--backup" ]; then
  BACKUP_DIR="${BACKUP_DIR:-$(dirname "$PGDATA")/autopivot-backups}"
  PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)"
  mkdir -p "$BACKUP_DIR"
  stamp="$(date +%Y%m%d-%H%M%S)"
  # Plain SQL rather than custom format: it restores into any later PostgreSQL
  # version, so a pod with a different release can still load it.
  su postgres -c "$PGBIN/pg_dump -p $PGPORT --format=plain --no-owner '$DB_NAME'" \
    > "$BACKUP_DIR/$DB_NAME-$stamp.sql"
  ln -sf "$DB_NAME-$stamp.sql" "$BACKUP_DIR/latest.sql"
  echo "Wrote $BACKUP_DIR/$DB_NAME-$stamp.sql"
  echo "Remember the image files too: STORAGE_ROOT must also be on the volume."
  exit 0
fi

# ── Persistence check ────────────────────────────────────────────────────────
say "Checking where the data will live"
echo "  PGDATA  $PGDATA"

parent="$(dirname "$PGDATA")"
mkdir -p "$parent"
# A network volume shows up as its own mount point. Without one, /workspace is
# just a directory on the container's overlay filesystem.
if mountpoint -q "$parent" 2>/dev/null; then
  echo "  $parent is a mounted volume — the database will survive this pod"
else
  warn "$parent is NOT a mounted volume. The database will be destroyed when
         this pod is terminated, along with every uploaded and processed image.
         Fine for a throwaway session. Attach a RunPod network volume and mount
         it at /workspace if you want it to persist."
fi

# ── Install ──────────────────────────────────────────────────────────────────
say "Installing PostgreSQL"
if ! command -v initdb >/dev/null 2>&1 && [ ! -d /usr/lib/postgresql ]; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq postgresql postgresql-contrib >/dev/null
fi

PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)"
[ -n "$PGBIN" ] || die "PostgreSQL did not install. Check the apt output above."
echo "  using $PGBIN"

# ── Initialise ───────────────────────────────────────────────────────────────
# PostgreSQL refuses to start unless PGDATA is owned by the account running it,
# and it refuses to run as root at all. Network volumes frequently reject chown
# even for root, so there are three cases to handle rather than one.
say "Preparing the cluster"

FALLBACK_PGDATA="${FALLBACK_PGDATA:-/var/lib/postgresql/autopivot}"
BACKUP_DIR="${BACKUP_DIR:-$parent/autopivot-backups}"
mkdir -p "$PGDATA" 2>/dev/null || true

pgdata_usable=false
if chown postgres:postgres "$PGDATA" 2>/dev/null; then
  pgdata_usable=true
else
  vol_uid="$(stat -c %u "$PGDATA")"
  vol_gid="$(stat -c %g "$PGDATA")"
  if [ "$vol_uid" -ne 0 ]; then
    # The volume will not let us change who owns the files, but they already
    # belong to a non-root account. Move the postgres user to that uid instead
    # of trying to move the files — same result, and it is the only direction
    # this filesystem permits.
    groupmod -o -g "$vol_gid" postgres 2>/dev/null || true
    usermod -o -u "$vol_uid" -g "$vol_gid" postgres 2>/dev/null || true
    chown -R "$vol_uid:$vol_gid" /var/lib/postgresql 2>/dev/null || true
    echo "  volume refuses chown — postgres now runs as uid $vol_uid to match it"
    pgdata_usable=true
  fi
fi

if [ "$pgdata_usable" = false ]; then
  # One more attempt before giving up on the volume. Root cannot change who owns
  # a file on a squashed mount, but a directory created *by* the postgres
  # account is already owned by postgres, so no ownership change is needed.
  # Only safe while the directory is empty — rmdir refuses otherwise, which is
  # the guard that stops this touching an existing cluster.
  if rmdir "$PGDATA" 2>/dev/null \
     && su postgres -s /bin/sh -c "mkdir -p '$PGDATA'" 2>/dev/null \
     && [ "$(stat -c %U "$PGDATA" 2>/dev/null)" = "postgres" ]; then
    echo "  postgres created the directory itself — the volume can hold the cluster"
    pgdata_usable=true
  fi
fi

if [ "$pgdata_usable" = false ]; then
  warn "The volume refuses chown and its files belong to root. PostgreSQL will
         not run as root, so the cluster cannot live there. Falling back to
         $FALLBACK_PGDATA on the container filesystem.

         That directory does NOT survive the pod being terminated. This script
         dumps to $BACKUP_DIR on the volume and restores from it automatically,
         so run 'bash scripts/runpod_database.sh --backup' before shutting the
         pod down."
  PGDATA="$FALLBACK_PGDATA"
  mkdir -p "$PGDATA" "$BACKUP_DIR"
  chown -R postgres:postgres "$PGDATA"
fi

chmod 700 "$PGDATA" 2>/dev/null || true
# The socket directory has to exist and be writable, and is often absent in a
# slim container image.
mkdir -p /var/run/postgresql
chown postgres:postgres /var/run/postgresql
touch "$LOG_FILE" 2>/dev/null && chown postgres:postgres "$LOG_FILE" 2>/dev/null || true

if [ -f "$PGDATA/PG_VERSION" ]; then
  echo "  cluster already exists — leaving its data alone"
else
  # -E UTF8 is not optional. A container usually has no locale set, so initdb
  # would otherwise default to SQL_ASCII — and psycopg 3 returns bytes rather
  # than str on a SQL_ASCII connection, which breaks SQLAlchemy before it can
  # even read the server version. --locale=C keeps collation predictable
  # without needing locales generated in the image.
  su postgres -c "$PGBIN/initdb -D '$PGDATA' -E UTF8 --locale=C \
      --auth-local=trust --auth-host=scram-sha-256" >/dev/null
  echo "  cluster created (UTF8)"
fi

# ── Start ────────────────────────────────────────────────────────────────────
say "Starting PostgreSQL"
if su postgres -c "$PGBIN/pg_ctl -D '$PGDATA' status" >/dev/null 2>&1; then
  echo "  already running"
else
  # Bound to loopback deliberately. The application runs on this same pod, so
  # nothing needs to reach the database from outside — and an exposed port with
  # a guessable password is how demo databases end up mined.
  su postgres -c "$PGBIN/pg_ctl -D '$PGDATA' -l '$LOG_FILE' \
      -o '-c listen_addresses=127.0.0.1 -p $PGPORT' -w start" >/dev/null
  echo "  started on 127.0.0.1:$PGPORT"
fi

# ── Role and database ────────────────────────────────────────────────────────
say "Creating the role and database"

DB_PASSWORD="${DB_PASSWORD:-}"
generated=false
if [ -z "$DB_PASSWORD" ]; then
  DB_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  generated=true
fi

psql_super() { su postgres -c "$PGBIN/psql -p $PGPORT -tAc \"$1\""; }

if [ "$(psql_super "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'")" = "1" ]; then
  echo "  role $DB_USER exists — password left unchanged"
  generated=false
else
  psql_super "CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD'" >/dev/null
  echo "  created role $DB_USER"
fi

if [ "$(psql_super "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'")" = "1" ]; then
  echo "  database $DB_NAME exists"
else
  # Encoding stated explicitly and templated from template0, so the database is
  # UTF8 even if the cluster around it was initialised as SQL_ASCII by an
  # earlier run of this script.
  psql_super "CREATE DATABASE $DB_NAME OWNER $DB_USER ENCODING 'UTF8' TEMPLATE template0" >/dev/null
  echo "  created database $DB_NAME (UTF8)"
fi

# An earlier run of this script created the database without stating an
# encoding, which in a container with no locale means SQL_ASCII. psycopg then
# returns bytes rather than text and SQLAlchemy cannot read even the server
# version. Recreate it — but only while it is empty, so this can never discard
# real data.
encoding="$(psql_super "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname='$DB_NAME'")"
if [ "$encoding" != "UTF8" ]; then
  warn "Database $DB_NAME has encoding $encoding, not UTF8."
  tables="$(su postgres -c "$PGBIN/psql -p $PGPORT -d '$DB_NAME' -tAc \
      \"SELECT count(*) FROM information_schema.tables WHERE table_schema='public'\"" 2>/dev/null || echo 1)"
  if [ "${tables:-1}" = "0" ]; then
    psql_super "DROP DATABASE $DB_NAME" >/dev/null
    psql_super "CREATE DATABASE $DB_NAME OWNER $DB_USER ENCODING 'UTF8' TEMPLATE template0" >/dev/null
    echo "  it was empty, so it has been recreated as UTF8"
  else
    die "It already holds $tables tables, so this script will not drop it. Back it
       up, drop it by hand, and run this script again:
         su postgres -c \"$PGBIN/pg_dump -p $PGPORT '$DB_NAME'\" > backup.sql
         su postgres -c \"$PGBIN/psql -p $PGPORT -c 'DROP DATABASE $DB_NAME'\""
  fi
fi

# ── Restore, if this is a rebuilt fallback cluster ───────────────────────────
# Only runs when the database is genuinely empty, so it can never overwrite
# data that is already there.
if [ -f "$BACKUP_DIR/latest.sql" ]; then
  tables="$(psql_super "SELECT count(*) FROM information_schema.tables \
      WHERE table_schema='public'" 2>/dev/null || echo 0)"
  if [ "${tables:-0}" = "0" ]; then
    say "Restoring from the most recent backup"
    su postgres -c "$PGBIN/psql -p $PGPORT -q -d '$DB_NAME'" < "$BACKUP_DIR/latest.sql" >/dev/null 2>&1 \
      && echo "  restored $BACKUP_DIR/latest.sql" \
      || warn "restore reported errors — check $BACKUP_DIR/latest.sql"
  fi
fi

# ── Hand off ─────────────────────────────────────────────────────────────────
if [ "$generated" = true ]; then
  URL="postgresql+psycopg://$DB_USER:$DB_PASSWORD@127.0.0.1:$PGPORT/$DB_NAME"
  # 0600 so the password is not world-readable on a shared pod.
  umask 077
  printf 'export DATABASE_URL=%s\n' "$URL" > "$ENV_FILE"
  echo "  connection string written to $ENV_FILE"
fi

say "Ready"
cat <<NEXT
Load the connection string into your shell:

    source $ENV_FILE

Then apply the schema and provision a dealership:

    alembic upgrade head
    python -m scripts.seed_dealership

Or run the full application setup, which does both:

    bash scripts/runpod_setup.sh

Useful afterwards:

    su postgres -c "$PGBIN/pg_ctl -D '$PGDATA' status"    # is it running
    tail -f $LOG_FILE                                      # server log

To bring your local data across instead of starting empty, on your Mac:

    pg_dump -h 127.0.0.1 -p 5432 -U vadim -Fc autopivot > autopivot.dump

then copy it to the pod and restore:

    pg_restore -h 127.0.0.1 -p $PGPORT -U $DB_USER -d $DB_NAME --no-owner autopivot.dump

Note that a restore brings the database but NOT the image files — those live
under STORAGE_ROOT and have to be copied separately, or the rows will point at
files that are not there.
NEXT
