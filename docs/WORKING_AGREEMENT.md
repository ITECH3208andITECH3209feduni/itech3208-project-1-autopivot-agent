# Working agreement

How four people work on this repository at once without spending the sprint
fixing each other's merges.

Written for a sprint running four streams in parallel: pipeline realism, the
settings and admin section, and a mobile capture app built by two people.

---

## The real problem

Parallel work does not cause conflicts. **Shared files cause conflicts.** Two
people can work on completely different features all week and never collide, or
collide daily, depending entirely on whether their work touches the same files.

So the question is not "how do we avoid conflicts" but "which files does more
than one stream need, and what do we do about those".

In this repository there are six, and they account for almost every conflict
that will happen:

| File | Who wants it | Why |
|---|---|---|
| `migrations/` | Settings, Mobile | Both add columns |
| `database/models.py` | Settings, Mobile | Both add columns |
| `api/schemas.py` | Settings, Mobile | Both add request and response shapes |
| `frontend/src/api/client.ts` | Settings, Mobile | Shared types |
| `autopivot_backend.py` | Pipeline, Mobile | Pipeline integration point |
| `api/app.py` | Settings | Router registration |

Everything else is naturally owned by one stream.

---

## The sharpest risk: Alembic migrations

This one deserves its own section because git will not save you.

**Alembic revisions form a linear chain.** Each migration names the one before
it in `down_revision`. If two people each create a migration on the same day,
both name the current head as their parent, and the chain forks. Git merges
both files without complaint — there is no text conflict, because they are
different files. The break only appears when someone runs `alembic upgrade
head` and is told there are multiple heads.

That is a semantic conflict git cannot see, and it will happen on a pod during
a demo if it is not prevented.

**The rule: one migration at a time, announced.** Before creating a migration,
say so in the team channel. Create it, merge it to main, then tell people it is
in. It takes a minute and it removes the problem entirely.

**The safety net already exists.** `tests/test_migrations.py` includes
`test_the_revision_chain_is_linear_with_one_head`, which fails if the chain
forks. Run the tests before pushing and this is caught on a laptop rather than
on a pod:

```bash
pytest tests/test_migrations.py -q
```

It also catches the constraint-naming mistake that broke a clean deployment
once already.

---

## Foundation first, then parallel

**Before the four streams start, one person lands everything they all need, in
one pull request.** A day's work that saves a week of merges.

That means:

1. **Every schema change all streams need, in one migration.** The settings
   store for the admin section, and the capture-metadata column for mobile.
   Both are known now; there is no reason to discover them separately in
   week two.
2. **The API contracts.** Endpoint paths, request and response shapes, in
   `api/schemas.py`. They can return stubs at first — what matters is that the
   shape is agreed and everyone builds against it rather than inventing it.
3. **The shared types** in `frontend/src/api/client.ts`, matching those shapes.

After that lands, each stream works against a stable base and touches only its
own files. This is exactly what made five parallel agents work on this codebase
without collisions: the shared pieces were built first, and everything after
had a locked file list.

---

## Ownership map

**One owner per file.** If you need a change in a file you do not own, ask the
owner rather than editing it. That sounds bureaucratic and takes about thirty
seconds in practice.

### Stream 1 — Pipeline realism

Owns: `compositing.py`, any new pure modules (`elevation.py` and similar),
`tests/test_compositing.py`, `assets/backgrounds/`.

Does **not** touch `autopivot_backend.py`. Realism work is self-contained in
`compositing.py`, which imports only OpenCV, NumPy and Pillow and has no GPU
dependency — see `docs/HANDOVER.md` §10. New capability is exposed as a new
keyword argument with a default that preserves current behaviour; the
integrator wires it in.

### Stream 2 — Settings and admin

Owns: `api/routes_settings.py` and `api/routes_admin.py` (both new),
`frontend/src/pages/SettingsPage.tsx`, `frontend/src/pages/AdminPage.tsx`.

Needs, from the foundation: the settings column, its schemas, its client types.
Needs one line each in `api/app.py` and `frontend/src/App.tsx` to register —
request those in the foundation PR so they exist before the work starts.

### Streams 3 and 4 — Mobile

Own everything under `mobile/`. A new top-level directory, so almost nothing
they do can conflict with the web application at all.

Needs, from the foundation: the capture-metadata column, the upload endpoint
shape, refresh-token authentication.

### Integrator

Owns: `autopivot_backend.py`, `api/app.py`, `api/processing.py`,
`database/models.py`, `migrations/`, `frontend/src/api/client.ts`,
`frontend/src/components/primitives.tsx`, `frontend/src/design.ts`.

One person holds the shared files and the pipeline wiring. Everyone else builds
modules with clean interfaces; the integrator connects them. This is the role
that keeps the six shared files from becoming a battleground.

---

## Two people on one mobile app

The hardest split, because it is one application rather than two.

**Do the skeleton together, first.** Navigation, the API client, the type
definitions, the sign-in screen. Half a day, both people, one branch. Everything
after depends on it and neither person should be guessing what the other chose.

**Then split by screen, not by layer.** Splitting "one does UI, one does logic"
means both people in every file every day. Splitting by screen means each owns
whole files:

- **Person A** — sign-in, vehicle list, the capture queue, upload and its
  retry behaviour, the result view.
- **Person B** — the camera screen: viewfinder, ghost silhouette overlay, tilt
  guide, and later the on-device frame processor.

Person B's work is the harder and more coupled half — a camera pipeline with an
inference loop is not something two people can share productively. Person A's
half is broader and more separable.

**Shared between them:** the type definitions and the API client. Treat those
the way the web app treats `client.ts` — change by agreement, not unilaterally.

---

## Branches

**Short-lived. Merge to main at least every two days.**

This is the lesson your own history already taught. `Autopivot-refactored-pipeline`
and `Auto_pivot_Scaling` each diverged so far from main that neither could be
merged — the work had to be lifted out by hand, function by function, and one
of them replaced the entire application with a standalone service because it
had been built against a version of the codebase that no longer existed.

None of that was a mistake in the code. It is what happens to any branch that
lives for weeks while main moves underneath it.

- One branch per story, named for its Jira key: `APA-201-camera-overlay`.
- Merge to main when the story is done, not when the sprint is.
- If a branch cannot be merged within two days, it is too big — split the story.
- `git pull origin main` into your branch daily. A small conflict today is
  cheaper than a large one on Friday.

---

## Before you push

```bash
pytest tests/ -q
```

122 tests, no GPU, no database, a couple of seconds. They exist specifically to
catch the mistakes that are expensive later:

- a forked migration chain
- a constraint name that Alembic will double-prefix
- an import of a name that does not exist in one of our own modules
- a pure module reaching for torch, which would make the geometry suite
  un-runnable on a laptop
- the vehicle changing size between gallery angles

And for the frontend:

```bash
npm run build --prefix frontend
```

There is no frontend test runner, so the type check and build **are** the
verification. A build that fails on main blocks three other people.

---

## Integration

Everyone converging at the end is where projects break, so it gets planned
rather than hoped for.

- **An integration day**, not an integration afternoon. Nominate it in advance.
- **Nobody starts new work that day.** The whole point is to have people
  available when their code turns out to need something.
- **The integrator drives**, everyone else stays reachable.
- **Demo the whole flow end to end** on the pod, not on a laptop. The
  difference has already cost this project a session — see decision 12 in
  `docs/DECISIONS.md`.

---

## Definition of done

Already agreed on the Jira board and worth restating, because it only works if
it is actually applied:

- Runs locally without errors
- Pushed to a branch named for its story
- Pull request created and **reviewed by another team member**
- Meets the acceptance criteria on the ticket
- Tests pass

The review requirement is the one most easily skipped under deadline pressure
and the one that most reliably prevents a bad merge. It is also assessed: the
Team Artefacts document asks for evidence that tasks were allocated, worked and
completed to a definition of done.
