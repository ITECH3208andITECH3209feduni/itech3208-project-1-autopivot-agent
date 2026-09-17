# AutoPivot Agent

AutoPivot Agent is a FastAPI web application for preparing vehicle photographs
for a dealership listing. A dealer uploads photographs of a car; the application
detects the vehicle, cuts it out of its background, hides the licence plate, and
places it on a studio backdrop.

This guide takes you from a computer with nothing installed to a working site.
**Follow it in order.** If you get stuck, there is a
[troubleshooting section](#step-7--if-something-goes-wrong) at the end of the
setup steps that diagnoses the common failures.

---

# Part 1 — Getting it running

## What you need first

Three things must be installed before anything else. If you already have them,
skip to [Step 3](#step-3--run-the-installer).

| | Download from | Notes |
|---|---|---|
| **Python 3.11 or 3.12** | [python.org/downloads](https://www.python.org/downloads/) | 3.10 and later all work; 3.11 or 3.12 is the best-tested. |
| **Node.js (LTS version)** | [nodejs.org](https://nodejs.org/) | Runs the website half. Take the default options. |
| **NVIDIA driver 527.41+** | [nvidia.com/drivers](https://www.nvidia.com/Download/index.aspx) | Only if you want the GPU. Without one, everything still works but image processing is slow. |

You do **not** need PostgreSQL, Docker, or the CUDA Toolkit. The database is an
ordinary file, and the CUDA runtime arrives inside the PyTorch package.

### Step 1 — Install Python correctly

Download Python 3.12 — 3.10 and later all work, but 3.12 is the safest
choice — and run the installer.

> **On the first screen, tick "Add python.exe to PATH" before clicking Install.**
>
> This is the single most common thing to get wrong. Without it, none of the
> commands below will be found, and the error message — `'python' is not
> recognized` — does not explain why.

If you have already installed Python without ticking it, run the installer
again, choose **Modify**, and it will let you add it.

To confirm it worked, open a new terminal window
(press `Win` + `R`, type `cmd`, press Enter) and run:

```bat
python --version
```

You should see `Python 3.12.x`. If you see an error, PATH is not set — run the
installer again.

### Step 2 — Check your GPU (optional)

In the same terminal:

```bat
nvidia-smi
```

If a table appears listing your graphics card, you are set. The number in the
top-right corner is your driver version; it needs to be 527.41 or higher.

If the command is not found, you either have no NVIDIA card or no driver. The
site still runs — it will process images on the CPU instead, which is far
slower (expect tens of seconds per photograph rather than a few). Everything
else behaves identically.

---

## Step 3 — Run the installer

Unzip the project somewhere sensible — `C:\Projects\autopivot` is fine. Avoid
OneDrive and Desktop folders with spaces or accented characters in the path;
they cause odd failures in Python tooling.

Then **double-click `setup.bat`**.

A terminal window opens and works through the setup. It takes **10 to 20
minutes**, almost all of it downloading PyTorch, which is about 2.5 GB.

What it is doing, in order:

1. Checks Python is installed and on your PATH.
2. Creates a **virtual environment** in a `.venv` folder — a private copy of
   Python for this project, so its packages cannot conflict with anything else
   on your machine.
3. Creates your **`.env`** configuration file and generates a login signing key
   into it.
4. Installs **the correct build of PyTorch** for your graphics driver. This is
   its own step for a reason — see [below](#why-pytorch-needs-its-own-step).
5. Installs the remaining Python packages, then the website's packages.
6. Creates the **database** and one **sign-in account**.
7. Runs a self-check and prints the result.

> ### Copy the password
>
> The last thing `setup.bat` prints is an email address and a password:
>
> ```
>   Sign in as : admin@demomotors.test
>   Password   : xK3n-mQ8pR2v
> ```
>
> **Copy that password now.** It is generated once and never shown again. If you
> lose it, see [Resetting the sign-in account](#resetting-the-sign-in-account).

Running `setup.bat` again later is safe — every step skips work already done.

### Why PyTorch needs its own step

On Windows, the ordinary `pip install torch` gives you a build with no GPU
support compiled into it at all. It installs without complaint, imports without
complaint, and then silently runs everything on the CPU. Nothing in the output
tells you this has happened; the site simply feels slow forever.

The GPU builds live on PyTorch's own package index and have to be requested by
name. `scripts/install_torch.py` reads your driver version, picks the matching
build, and then verifies that the GPU really is visible before finishing.

To override its choice:

```bat
.venv\Scripts\activate
python scripts\install_torch.py cu118    REM for an older driver
python scripts\install_torch.py cpu      REM no GPU at all
```

---

## Step 4 — Add a Hugging Face token (optional but recommended)

The background removal uses one of two models. The better one, RMBG-2.0,
requires a free account token.

1. Sign up at [huggingface.co/join](https://huggingface.co/join).
2. Create a token at
   [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) —
   a **Read** token is enough.
3. Accept the model licence at
   [huggingface.co/briaai/RMBG-2.0](https://huggingface.co/briaai/RMBG-2.0)
   (open the page and click through the licence prompt).
4. Open the file **`.env`** in the project folder with Notepad or VS Code, find
   the `HF_TOKEN=` line, and paste your token after the `=`:

   ```
   HF_TOKEN=hf_abcdefghijklmnopqrstuvwxyz
   ```

5. Save the file.

Without a token the application falls back to BiRefNet, which works but gives
slightly rougher edges around the vehicle.

---

## Step 5 — Start the site

**Double-click `run.bat`.**

Two terminal windows open — one for the API, one for the website — and your
browser opens at:

```
http://localhost:5173
```

The first time you process an image, the application downloads the vision
models (about 4 GB) and loads them into your graphics card. That first image
takes a minute or two. Every image after that is fast, because the models stay
loaded.

**To stop the site**, close the two terminal windows.

### Signing in

Use the email and password `setup.bat` printed in Step 3.

You will be asked to change the password immediately. This is deliberate:
accounts are provisioned rather than self-registered, so every new account
starts with `must_change_password` set.

---

## Step 6 — Using it

The application works in this order:

1. **Backdrops** — upload the scenes you want vehicles placed onto. A new
   dealership starts with none, so do this first.
2. **New vehicle** — enter the make, model and year to create a listing.
3. **Photographs** — attach photographs to that listing, by file or by pasting
   a listing URL.
4. **Process** — queues one job per photograph. Each is classified, the vehicle
   is detected and cut out, the plate is hidden, and the result is placed on
   your chosen backdrop.
5. **Vehicles** — originals beside processed results.

A photograph the pipeline finds no vehicle in is marked **needs review** rather
than failed. The run was correct; the result needs a person to look at it.

---

## Step 7 — If something goes wrong

The project ships a diagnostic that checks everything and tells you what to do.
Open a terminal in the project folder and run:

```bat
.venv\Scripts\activate
python -m scripts.check_setup
```

It verifies your Python version, every package, your GPU (including running a
real calculation on it), your `.env`, the database, whether a sign-in account
exists, and the website build — then prints the exact command to fix anything
missing. It changes nothing, so it is always safe to run.

### Common problems

| What you see | What it means | Fix |
|---|---|---|
| `'python' is not recognized` | Python is not on your PATH. | Re-run the Python installer, tick "Add python.exe to PATH". |
| `'npm' is not recognized` | Node.js is not installed. | Install it from [nodejs.org](https://nodejs.org/), then run `setup.bat` again. |
| Processing is very slow | The CPU-only PyTorch got installed. Confirm with `check_setup`. | `.venv\Scripts\activate` then `python scripts\install_torch.py` |
| You are signed out every restart | `JWT_SECRET` is blank in `.env`. | Run `setup.bat` again, or paste a value in yourself. |
| Login rejects the password | No account exists, or the password was lost. | See [Resetting the sign-in account](#resetting-the-sign-in-account). |
| `ModuleNotFoundError: No module named 'api'` | A command was run from a subfolder. | `cd` to the project folder first. |
| `Port 8000 is already in use` | An old copy is still running. | Close the leftover terminal windows, or change `PORT` in `.env`. |
| The browser shows "connection refused" | The API window closed or crashed. | Look at the API terminal window for the error. |
| `403` or `429` when importing a listing URL | The site blocks automated requests. | Not fixable from here — see [Listing URL import](#listing-url-import). Download the photographs and upload them instead. |

### Resetting the sign-in account

If you lose the password, delete the account and make a new one:

```bat
.venv\Scripts\activate
del autopivot.db
python -m scripts.init_db
python -m scripts.seed_dealership
```

This wipes all listings and jobs with it. To choose the password yourself
instead of having one generated, set `SEED_ADMIN_PASSWORD` in `.env` before
running the last command.

### Starting completely over

```bat
del autopivot.db
rmdir /s /q storage
rmdir /s /q .venv
setup.bat
```

---

# Part 2 — Working on the code

## Running it from VS Code

Open the project folder in VS Code (**File → Open Folder**). It will offer to
install the recommended extensions — accept, as the Python and Pylance ones are
what make the Run button work.

Press **F5**, or open the Run and Debug panel (`Ctrl` + `Shift` + `D`) and pick
one of:

| Configuration | What it does |
|---|---|
| **AutoPivot: full app (website + GPU API)** | Both halves together, with breakpoints working in the Python code. This is the usual one. |
| **AutoPivot: website + light API (fast start)** | Same, but without loading the vision models: about a second to start instead of a minute, and no VRAM used. Everything works except **Process**, which returns 503. Use this while working on the website. |
| **API: full (GPU processing)** | The API alone, with the models. |
| **API: light (no models, auto-reload)** | The API alone, without them. Restarts on save. |
| **Website only (Vite dev server)** | The website alone. |
| **Setup: create database tables** | Same as `python -m scripts.init_db`. |
| **Setup: create sign-in account** | Same as `python -m scripts.seed_dealership`. |
| **Check setup (GPU, database, packages)** | The diagnostic from Step 7. |

If VS Code asks which Python interpreter to use, choose the one inside `.venv`.
It is already configured as the default, so usually it selects itself.

`Ctrl` + `Shift` + `P` → **Tasks: Run Task** has the setup, database, build and
test steps as well.

## Running it from a terminal

The two halves are separate programs and need a terminal each.

**Terminal 1 — the API:**

```bat
.venv\Scripts\activate
python autopivot_backend.py
```

For the fast-starting version with no vision models — the equivalent of the
"light API" launch configuration:

```bat
.venv\Scripts\activate
python -m uvicorn api.app:app --reload --host 127.0.0.1 --port 8000
```

`--reload` restarts the server whenever you save a Python file.

**Terminal 2 — the website:**

```bat
npm run dev --prefix frontend
```

Then open `http://localhost:5173`.

### Serving everything from one port

The Vite dev server on 5173 proxies API calls through to port 8000. If you
would rather have a single address, build the website and let the API serve it:

```bat
npm run build --prefix frontend
```

Then start the API alone and open `http://127.0.0.1:8000`. Without a build,
that address answers 503 and says so.

## Running the tests

```bat
.venv\Scripts\activate
python -m pytest tests -v
```

Or use the **Testing** panel in VS Code, which is already pointed at `tests/`.

## Configuration

Everything is set in **`.env`** in the project folder. `.env.example` is the
template, and documents every available setting with comments. `setup.bat`
creates `.env` for you by copying it.

A real environment variable overrides the file, so a one-off change needs no
editing:

```bat
set MAX_FILE_MB=50 && python autopivot_backend.py
```

The settings you are most likely to touch:

```bash
HF_TOKEN=                    # Hugging Face token, for the better BG model
JWT_SECRET=                  # login signing key; blank = signed out on restart
HOST=127.0.0.1               # 0.0.0.0 to expose it to your network
PORT=8000
MAX_FILE_MB=20               # upload size limit
STORAGE_ROOT=storage         # where uploaded and processed images are written
HF_HOME=./.cache/huggingface # where the ~4 GB of models are cached
PLATE_TREATMENT=blur         # blur, pixelate or white
CLASSIFY_IMAGES=true         # ask CLIP what each photograph is of first
```

Relative paths in `HF_HOME`, `TORCH_HOME` and `STORAGE_ROOT` are resolved
against the project folder rather than whatever directory you started the
server from — so running from VS Code and running from a terminal always use
the same files.

## The database

By default this uses **SQLite**: one file, `autopivot.db`, in the project
folder. Nothing to install and no server to start.

```bat
python -m scripts.init_db           REM create the tables
python -m scripts.seed_dealership   REM create a dealership and an admin account
```

`init_db` is safe to run repeatedly. To inspect the data, install the **SQLite
Viewer** extension VS Code recommends and click `autopivot.db` in the sidebar.

### Using PostgreSQL instead

Fully supported. Set `DATABASE_URL` in `.env` and nothing else changes:

```bash
DATABASE_URL=postgresql+psycopg://autopivot_user:password@localhost:5432/autopivot
```

`scripts/init_db.py` notices and runs `alembic upgrade head` rather than
building the schema from the models. That difference is deliberate: the
migrations in `migrations/versions/` are written in PostgreSQL's dialect —
`UPDATE ... FROM`, bare `ALTER COLUMN`, `DROP CONSTRAINT` — none of which SQLite
implements. Both paths end at the same schema, because the migrations and
`database/models.py` describe the same tables.

Three things in the model layer carry SQLite variants so one schema builds on
both databases:

- `text[]` becomes JSON.
- `BIGINT` primary keys become `INTEGER`, which is the only form SQLite
  auto-increments — a `BIGINT PRIMARY KEY` silently fails to generate ids.
- Timestamps go through `UtcDateTime` in `database/base.py`, which keeps them
  UTC-aware on both. SQLite has no timestamp type and returns naive values,
  which a browser reads as local time and displays hours off.

## Putting it on your network

The defaults bind to `127.0.0.1`, so the site is reachable only from your own
machine. To expose it, set `HOST=0.0.0.0` in `.env` and add the address you
will use to `ALLOWED_ORIGINS`.

For a temporary public URL, run the app and point a tunnel at port 8000 — for
example [ngrok](https://ngrok.com/), which needs a free account and
`ngrok config add-authtoken <token>` once. Add the tunnel's URL to
`ALLOWED_ORIGINS` too, or the browser blocks the API calls.

---

# Part 3 — How it is built

## Project structure

```
setup.bat / setup.sh      One-time setup. setup.sh is the macOS and Linux version.
run.bat                   Starts the website and the API together.
.env                      Your settings. Created by setup.bat from .env.example.
autopivot.db              The SQLite database. Created by scripts/init_db.py.

autopivot_backend.py      The full application: processing routes and the model registry.
compositing.py            Places a cut-out vehicle into a scene: edges, shadows, colour.
classification.py         Asks CLIP what each photograph is of before processing it.

api/
  app.py                  Application factory. No ML imports, so it runs anywhere.
  env.py                  Loads .env before anything that reads it is imported.
  config.py               Settings shared by both halves.
  security.py             Password hashing and access tokens.
  deps.py                 Database session and authenticated-user dependencies.
  routes_auth.py          Login, current user, password change.
  routes_dashboard.py     Dashboard statistics.
  routes_listings.py      Listings, photograph upload, processing.
  routes_backdrops.py     Backdrop library and authenticated file serving.
  processing.py           Job orchestration, behind a protocol so the light API
                          stays free of ML imports.
  storage.py              Content-addressed file storage, scoped per dealership.
  url_import.py           Fetching and parsing listing pages.
  schemas.py              Request and response models.

database/
  base.py                 Model base, constraint naming, and the column types
                          that keep the schema portable across both databases.
  connection.py           Engine and session setup for SQLite and PostgreSQL.
  models.py               Dealership, user, listing, image and job models.

scripts/
  init_db.py              Creates the schema. create_all on SQLite, Alembic on PostgreSQL.
  seed_dealership.py      Provisions a dealership and its administrator.
  install_torch.py        Installs the PyTorch build matching your NVIDIA driver.
  check_setup.py          Diagnoses a broken setup and says what to run.

frontend/                 React client. src/design.ts is the single source of truth
                          for the visual system; src/Guidelines.tsx renders it as a
                          living style guide at /guidelines.

migrations/               Alembic migrations. Used only on the PostgreSQL path.
assets/backgrounds/       The two measured studio scenes.
tests/                    Test suite. Run with: python -m pytest tests -v
.vscode/                  Run and Debug configurations, tasks, editor settings.
```

## The two halves

The application can be served two ways, and both expose the same routes:

- **`uvicorn api.app:app`** — the light API. Authentication, the dashboard,
  listings and uploads, with no machine-learning import anywhere in the module
  graph. Starts instantly on any machine. `POST /api/listings/{id}/process`
  returns 503, because there are no models to run.
- **`python autopivot_backend.py`** — the full application. Calls the same
  application factory and adds the processing routes on top.

There is therefore one set of auth routes, not two that can drift apart.

## Features

- Upload a vehicle image and process it through the full pipeline.
- Remove image backgrounds with RMBG-2.0, falling back to BiRefNet.
- Detect vehicles with YOLO26, falling back to YOLO11.
- Detect and hide licence plates with
  `nickmuchi/yolos-small-finetuned-license-plate-detection`.
- Upload custom backdrops and numberplate overlays.

## API Endpoints

- `GET /health` — health and model readiness status.
- `GET /health/api` — liveness for the non-ML half, so the light API can be
  health-checked without models.
- `GET /api/status` — API status and configured model names.
- `POST /auth/login` — exchange email and password for a bearer token.
- `GET /auth/me` — the authenticated user plus dealership context.
- `POST /auth/change-password` — rotate the password and clear the
  `must_change_password` flag.
- `GET /api/dashboard/counts` — the totals beside the sidebar nav items.
- `GET /api/dashboard/stats` — vehicles this month, images processed, and the
  number needing review.
- `GET|POST /api/listings` — list and create vehicle listings. The list
  supports `limit`, `offset` and a `processing_status` filter.
- `GET|PATCH|DELETE /api/listings/{id}` — a listing and its images.
- `POST /api/listings/{id}/images` — attach photographs (multipart, repeated
  `files` field).
- `POST /api/listings/{id}/images/from-url` — fetch photographs from a listing
  page and attach them. Returns 422 with a message naming the reason when the
  site cannot be imported from; see "Listing URL import" below.
- `DELETE /api/listings/{id}/images/{image_id}` — remove one photograph.
- `POST /api/listings/{id}/process` — queue every unprocessed photograph,
  optionally against a backdrop. Returns 503 on the light API, which has no
  models.
- `GET /api/listings/{id}/jobs` — progress for the Processing screen.
- `GET|POST /api/backdrops`, `DELETE /api/backdrops/{id}` — the dealership's
  backdrop library.
- `GET /api/files/{path}` — serves a stored file to a member of the dealership
  that owns it.

Both `/api` routes are scoped to the authenticated user's dealership. Platform
admins have no dealership of their own and receive 403 rather than an unscoped
view across every dealership.
- `POST /remove-background` — remove background only.
- `POST /process-vehicle` — full pipeline: vehicle detection, background removal, plate detection, plate treatment, optional custom background.
- `POST /detect-and-hide` — detect and hide license plates only.
- `POST /extract-images-from-url` — fetch the photographs on a listing page
  and return them as base64. Stores nothing; unauthenticated.

Upload fields:

- `file` — required vehicle/image upload.
- `background` — optional custom background for `/process-vehicle`.
- `plate_overlay` — optional numberplate overlay for `/process-vehicle` and `/detect-and-hide`.

## Data isolation

Signing in is required; there is no public interface, and a dealership's own
data is the only data any account can reach. Every `/api` route is scoped to the
authenticated user's dealership, and the composite foreign keys in the schema
enforce the same rule in the database rather than relying on the queries alone.

Platform admins have no dealership of their own and receive 403 rather than an
unscoped view across every dealership.

The user-facing sequence — backdrops, then a vehicle, then processing — is in
[Step 6](#step-6--using-it).

## What a photograph is of

`classification.py` asks CLIP (`openai/clip-vit-base-patch32`) what each
photograph shows before the pipeline touches it, and returns both a **kind**
(`exterior`, `interior`, `detail`, `advertisement`, `unknown`) and, for
exteriors, a **shot angle** (`front`, `front_quarter`, `side`, `rear_quarter`,
`rear`).

Vehicle detection cannot answer the first question. A finance advertisement
contains a real car and passes detection — the first real URL import composited
a Mazda2 out of a "FINANCE MADE EASY" banner into a Nissan Note's gallery, and
put a steering-wheel close-up on the studio turntable. Both are photographs a
detector is right about and a listing is wrong to include.

The prompts describe the **photograph**, not the object: "a close-up photograph
of one car wheel" rather than "a car wheel". A wheel close-up genuinely contains
a car, so object-level wording cannot separate them.

Two thresholds, both env-overridable:

- `CLIP_KIND_CONFIDENCE` (0.55) — how sure the leading description must be.
- `CLIP_KIND_MARGIN` (0.15) — how far clear of the runner-up. This is the
  load-bearing one. A banner built around a car photo scores respectably as
  *both* advertisement and exterior, so a threshold on the leader alone lets it
  through on the strength of the photograph inside it. Two descriptions fitting
  almost equally means the photograph is unidentified, whichever leads.

Anything below either threshold is `unknown` and is not processed. The stated
principle is the same as for plates: rather miss than damage. A wrong exclusion
is one click for the dealer to undo; a wrong inclusion puts a stranger's car in
their listing.

**The defaults are reasoned, not measured.** Calibrate them against real
photographs before trusting them — the module prints the full distribution per
file:

```bash
python classification.py path/to/*.jpg
```

Set `CLASSIFY_IMAGES=false` to skip it entirely. If the model cannot load, the
pipeline logs once and carries on unclassified rather than failing every job.

## Compositing

`compositing.py` places the cut-out vehicle into a scene. The geometry, shadow
construction and colour matching are Suraj Purella's, from his
`Auto_pivot_Scaling` branch; they were lifted out rather than merged, because
that branch replaces the whole application with a standalone processing service.

A straight paste fails for three reasons, and each is addressed:

- **Edges.** The segmentation mask is computed at 1024×1024 and stretched over a
  photograph several times that wide, leaving a fringe of background clinging to
  the silhouette — invisible against white, obvious against a studio floor.
  `refine_alpha_mask` closes pinholes, pulls the edge in one pixel and feathers it.
- **Contact.** Nothing anchored the vehicle to the floor, so it floated.
  Two shadows are laid down — a wide ambient pool and a tighter contact
  shadow — both derived from the vehicle's own silhouette rather than a generic
  ellipse, so they narrow at the bonnet and widen at the wheel arches.
- **Light.** `match_colour` moves the vehicle towards the scene's LAB mean at 12%
  of the difference for lightness and 15% for the colour axes, clamped to ±18
  and ±5. Deliberately weak: a listing photograph has to stay the colour the car
  actually is.

The contact line is the 0.97 quantile of each column's lowest solid pixel, not
the lowest opaque pixel — one stray row of leftover mask would otherwise lift
the whole car off the floor.

### One car, one size

A fourth problem appears only across a whole listing. Every shot used to be
scaled to fill the available box, so a head-on shot — about as wide as it is
tall — ran out of height first and was enlarged until it filled the frame,
while a side-on shot of the same car ran out of width first and came out around
half that size. Flicking through the gallery, the car grew and shrank.

`_fit_vehicle` now scales to a target **height** instead, because height is the
one dimension a turntable leaves alone: a car rotating on the spot barely
changes apparent height, while its projected length collapses from about 4.7 m
side-on to 1.8 m head-on. The target comes from `REFERENCE_VEHICLE_ASPECT`, so
no cross-image state is needed — each photograph reaches the same size on its
own.

A cutout too long to be a car (a panorama, a badly cropped strip) clamps below
`NORMALISE_CLAMP_FLOOR` of its target and falls back to the old rule. Clamping
rather than abandoning matters: an earlier accept-or-reject version put a cliff
exactly where cars are commonest — a real side-on silhouette runs about 3.5
wide to 1 tall once wheels and mirrors are in frame, just past the 3.2
reference, so it failed by a hair and rendered twelve per cent smaller than the
same car at every other angle, which is the defect the whole function exists to
remove.

`reflection_strength` on a preset mirrors the vehicle below its contact line,
fading and clipped to the platform. It is **off by default**: it is only correct
on a surface we have measured and can see is polished, and a dealer's own
backdrop may be carpet, gravel or a workshop floor.

### Backdrops and the ground line

Two built-in scenes are measured by hand and carry full geometry, including an
ellipse over the display base that shadows are clipped to:

| Preset | Placement | Canvas |
|---|---|---|
| `studio_full` | On the raised platform | 1280×960 |
| `studio_closeup` | Centred, no contact shadow | 1280×960 |

A **dealership's own backdrop** has no measured geometry, so the vehicle is
centred horizontally and stood on a ground line at **84% of the canvas height**,
and the output keeps the backdrop's own resolution (capped at 2400px wide).

**That 84% is a guess.** If a dealer's backdrop has its horizon somewhere else,
the vehicle will float above it or sink below it. Giving each backdrop its own
ground-line setting is the fix, and is not built yet.

With no backdrop at all, the cutout returns to its place on a transparent canvas
the size of the original photograph — there is no scene to sit in, so scaling to
a fixed canvas would only discard resolution.

## Licence plates

Plates are found on the cropped vehicle region rather than the finished
composite, so the plate occupies far more of the detector's input, and the
pixels are photographic rather than a cutout on transparency.

Every detection is then checked against three things before anything is painted
over the photograph:

- **Shape** — between `PLATE_MIN_ASPECT` and `PLATE_MAX_ASPECT` (1.2–6.5 by
  default, wide enough for AU/NZ, European slimline and motorcycle plates).
- **Size** — no more than `PLATE_MAX_AREA_RATIO` of the vehicle.
- **Coverage** — at least `PLATE_MIN_COVERAGE` of the box must land on the
  vehicle cutout rather than on transparent background. This is what rejects a
  plate "detected" in empty sky beside the car.

A rejected detection is logged with its reason. The reasoning is that a
misplaced mask is worse than a missing one: an obscuration over empty
background is visible damage to a photograph the dealer intends to publish,
whereas an unmasked plate is simply a photograph that still needs a person.

`PLATE_TREATMENT` selects what replaces the plate — `blur` (default),
`pixelate` or `white`. Both `blur` and `pixelate` downsample to
`PLATE_MOSAIC_WIDTH` first, which is what actually destroys the characters; a
Gaussian blur alone is a convolution and can be partially inverted. Alpha is
never modified, so a treatment can no longer punch an opaque block into the
transparent background.

## Listing URL import

`api/url_import.py` fetches a listing page and attaches the photographs it
finds. **It does not work on every site**, and that is not fixable from our
side. Two patterns defeat it:

- A WAF answers automated requests with 403 or 429 regardless of how the
  request is shaped. `carsales.com.au` does this.
- The page ships an empty shell and paints the gallery with JavaScript, so the
  HTML we receive holds the site's own logos and nothing else.
  `autotrader.com.au` does this.

Both were confirmed by hand. Rather than returning "no images found" and
letting a dealer conclude their listing is broken, known cases are named
explicitly and unknown hosts get a message describing which pattern they hit.

Set `URL_IMPORT_ALLOWED_HOSTS` to a comma-separated list to restrict imports to
named hosts. Empty (the default) means any host that is not already known to be
unsupported.

The SSRF guard rejects hostnames resolving to private, loopback, link-local or
reserved addresses, and re-checks after redirects.

## Notes

This is a prototype, and the defaults are sized for a development machine. If
processing fails with an out-of-memory error, lower `MAX_FILE_MB` in `.env` —
the segmentation models scale their working memory with the input image, so a
smaller upload limit is the quickest way to fit a smaller card.

`compositing.py` stands a vehicle on a ground line at 84% of the canvas height
for any backdrop you upload yourself, because only the two built-in studio
scenes have measured geometry. If your own backdrop has its horizon elsewhere,
the vehicle will float or sink. Giving each backdrop its own ground-line setting
is the fix, and is not built yet.
