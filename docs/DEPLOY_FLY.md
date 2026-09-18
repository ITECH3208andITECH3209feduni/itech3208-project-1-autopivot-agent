# Deploying the light API to Fly.io

A permanent, always-on home for authentication, listings and the dashboard —
the routes in `api/`, which import no machine-learning stack and need no GPU.
Vehicle processing stays on RunPod; nothing here changes that.

**Why this exists.** RunPod is a GPU pod: it has to be started before use,
bills while running, and its cloudflared tunnel URL regenerates on every
restart. None of that is a problem for what it is actually for — but the
mobile app's current sprint only needs sign-in and the vehicle list, which is
the light API and nothing else (see `docs/HANDOVER.md` §2 for the split).
Putting just that half somewhere that is simply always there removes RunPod
from the loop entirely for this kind of testing, at a cost of a few dollars a
month instead of GPU-pod pricing.

**What stays on RunPod.** Full-pipeline testing — anything that touches
`autopivot_backend.py` — still runs there, and `scripts/runpod_up.sh --status`
now also prints a stable proxy URL for it (see the note at the bottom of this
document).

---

## Prerequisites

- A Fly.io account — [fly.io](https://fly.io), needs a payment method on file
  even within any free allowance.
- The `flyctl` CLI: `brew install flyctl` (or see fly.io/docs/flyctl for other
  platforms).
- A Postgres database it can reach. Two reasonable choices:
  - **Fly's own Postgres** — `fly postgres create`, then
    `fly postgres attach` to this app. Check `flyctl postgres --help` for the
    exact current subcommands; Fly's managed-database offering has changed
    more than once and this document may be behind by the time you run it.
  - **A separate managed Postgres** — Neon or Supabase both have a workable
    free tier and are decoupled from whatever Fly's own offering does next.
    Either way, what this app needs is just a `DATABASE_URL`.

None of the following commands are run for you — they touch your account and
your card, so they are yours to run.

---

## First deploy

From the repository root:

```bash
fly auth login
```

```bash
fly apps create <a-name-nobody-else-has-taken>
```

Update `fly.toml`'s `app =` line to match. Then create the database (pick one
of the two approaches above), and set the secrets this app needs:

```bash
fly secrets set \
  DATABASE_URL="postgresql+psycopg://user:password@host:5432/dbname" \
  JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  ALLOWED_ORIGINS="http://localhost:5173"
```

`ALLOWED_ORIGINS` only matters to a browser client — the mobile app enforces
no CORS policy of its own — so this is a placeholder until the web client
also has a permanent home. Add its real origin then.

Deploy:

```bash
fly deploy
```

`release_command` in `fly.toml` runs `alembic upgrade head` automatically as
part of this, against the `DATABASE_URL` secret above — the schema is created
on the very first deploy, no separate step needed.

Seed a dealership once the schema exists:

```bash
fly ssh console -C "python -m scripts.seed_dealership"
```

Confirm it is actually up:

```bash
curl https://<your-app-name>.fly.dev/health/api
```

Expect `{"status": "ok"}`.

---

## Pointing the mobile app at it

The Flutter client reads its base URL from `--dart-define=API_BASE_URL=...`
at build time, or — more conveniently, since this URL will not change once
deployed — the dev tools screen (`mobile/lib/main_dev.dart`) takes it at
runtime: open the "Connect and sign in" field and paste
`https://<your-app-name>.fly.dev`.

---

## What this deployment does not cover

- **Vehicle processing.** `POST /api/listings/{id}/process` and everything it
  calls lives in `autopivot_backend.py`, which is not part of this image.
  Calling it against the Fly deployment will 503 — that is correct, not a
  bug, per the existing behaviour documented in `README.md`.
- **File storage.** `api/storage.py` writes to local disk, and Fly's
  container filesystem is not persistent across deploys without a Fly
  Volume. Not attached here, because nothing this sprint's mobile scope needs
  serves a stored file yet — see the note in
  `mobile/lib/widgets/authed_image.dart`. Attach a volume before this matters,
  which will be around the same time processing needs to live somewhere
  permanent too.
- **Automatic deploys on push.** `fly deploy` is run by hand for now. A
  GitHub Actions workflow calling it on push to a chosen branch is a
  reasonable follow-up, not set up here.

---

## RunPod's stable proxy URL

For full-pipeline testing, `scripts/runpod_up.sh` now also prints a URL of
the form `https://<pod-id>-8000.proxy.runpod.net` alongside the usual
cloudflared one. Unlike the tunnel URL, it survives a pod stop/start rather
than regenerating — but it only resolves if port 8000 is marked as an exposed
HTTP port on the pod itself, which is a RunPod dashboard setting, not
something the script can turn on for you. If it does not load, that is the
reason, and the cloudflared URL printed alongside it still works either way.
