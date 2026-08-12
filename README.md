# AutoPivot Agent

AutoPivot Agent is a FastAPI demo for vehicle image processing. It provides a web interface and API endpoints for vehicle detection, background removal, license plate detection, optional custom backgrounds and optional plate overlays.

## Features

- Upload a vehicle image and process it through the full pipeline.
- Remove image backgrounds with an RMBG-2.0 primary model and BiRefNet version 11 fallback.
- Detect vehicles with YOLO26.
- Detect and hide license plates with nickmuchi/yolos-small-finetuned-license-plate-detection.
- Upload optional custom backgrounds and numberplate overlays.

## Project Structure

- `autopivot_backend.py` - vehicle processing endpoints, model registry, and the full application.
- `api/app.py` - application factory: CORS, error handling and auth, with no ML imports.
- `api/config.py` - settings shared by both halves.
- `api/security.py` - password hashing and access tokens.
- `api/deps.py` - database session and authenticated-user dependencies.
- `api/routes_auth.py` - login, current user and password change.
- `api/routes_dashboard.py` - dashboard statistics.
- `api/routes_listings.py` - vehicle listings, photograph upload and processing.
- `api/processing.py` - job orchestration, behind a processor protocol so the
  light API stays free of ML imports.
- `scripts/seed_dealership.py` - provisions a dealership and its administrator.
- `api/storage.py` - content-addressed file storage, scoped per dealership.
- `api/url_import.py` - fetching and parsing listing pages, shared by the light
  API and the processing backend.
- `api/routes_backdrops.py` - backdrop library and authenticated file serving.
- `scripts/runpod_setup.sh` - one-shot setup for a GPU test pod.
- `frontend/` - React client. `src/design.ts` is the single source of truth for
  the visual system; `src/Guidelines.tsx` renders it as a living style guide at
  `/guidelines`.
- `assets/` - sample images kept in the repository; no longer served over HTTP.
- `database/base.py` - shared SQLAlchemy model base and constraint naming rules.
- `database/connection.py` - PostgreSQL engine and database-session setup.
- `database/models.py` - permanent dealership, user, listing, image and job models.
- `requirements.txt` - Python dependencies.

## Requirements

- Python 3.10+
- A machine with enough RAM/VRAM for the selected vision models.
- **Required**: `HF_TOKEN` for Hugging Face authentication. RMBG-2.0 requires access to the BRIA model license; BiRefNet is used as fallback when the primary model is unavailable.

Install dependencies. There are two sets:

```bash
pip install -r requirements.txt
```

Core only — server, auth and database. No machine learning, every package has a
prebuilt Apple Silicon wheel, and it installs in seconds. Enough for
authentication, the dashboard and Alembic.

```bash
pip install -r requirements-ml.txt
```

Everything above plus the vision stack. Several gigabytes, and a CUDA GPU to be
useful.

## Configuration

The backend uses environment variables:

```bash
HF_TOKEN=your_huggingface_token        # required for RMBG-2.0
HOST=0.0.0.0                           # default
PORT=8000                              # default
MAX_FILE_MB=20                         # default upload limit
YOLO_HF_REPO=Ultralytics/YOLO26        # default YOLO26 Hugging Face repo
YOLO_MODEL_PATH=yolo26n.pt             # default YOLO26 detector file
ALLOWED_ORIGINS=http://localhost:8000  # comma-separated CORS origins
DATABASE_URL=postgresql+psycopg://autopivot_user:password@localhost:5432/autopivot
```

Use `.env.example` as the template for setting `DATABASE_URL` in the local shell
or deployment environment. Real database credentials must not be committed.

For larger demo uploads, raise `MAX_FILE_MB`, for example:

```bash
MAX_FILE_MB=50 python autopivot_backend.py
```

## Run Locally

Two ways to run, depending on whether you need vehicle processing.

**Light API** — authentication and dealership data, no models loaded. Starts
instantly on any machine, GPU or not:

```bash
uvicorn api.app:app --reload
```

**Full application** — the light API plus the processing pipeline:

```bash
python autopivot_backend.py
```

Both serve the same auth routes: `autopivot_backend.py` calls the same
application factory and adds the processing routes on top, so there is one set
of routes and no risk of the two drifting apart.

**Frontend** — in a second terminal:

```bash
npm install --prefix frontend && npm run dev --prefix frontend
```

Opens on `http://localhost:5173` and proxies `/auth`, `/api` and `/health` to
the API on port 8000, so the browser stays on one origin in development. Sign in
with the account printed by the seed script.

Open:

```text
http://127.0.0.1:8000
```

`/` serves the React client from `frontend/dist`, so a single port serves the
application and the API on one origin and CORS never comes into it. Build the
client first, or `/` answers 503 telling you so:

```bash
npm ci --prefix frontend && npm run build --prefix frontend
```

Nothing else is published as static files. Images belonging to a dealership are
served through `/api/files/{path}`, which checks that the caller belongs to the
dealership that owns them.

## Database and accounts

Apply the schema, then seed a demo dealership:

```bash
alembic upgrade head
python -m scripts.seed_dealership
```

This provisions one dealership and one administrator, and nothing else — no
vehicles, images or backdrops. A dealership fills up through the application.
Name, location and admin details are configurable via `SEED_DEALERSHIP_NAME`,
`SEED_DEALERSHIP_LOCATION`, `SEED_ADMIN_EMAIL` and `SEED_ADMIN_PASSWORD`; the
password is generated and printed once if unset. Re-running is safe.

There is no registration endpoint by design: dealer accounts are provisioned by
AutoPivot, which is why `users.must_change_password` defaults to true. Seeded
accounts must change their password at first login via `/auth/change-password`.

## Runpod / ngrok / remote access setup

Run the app on Runpod / server as normal, then expose port `8000` with ngrok or your chosen tunnel.  

Note: Ngrok requires auth token and this can be accessed via [official website](https://dashboard.ngrok.com/signup)

Then open Terminal and prompt this:
```bash
pip install pyngrok

ngrok config add-authtoken [YOUR TOKEN FROM NGROK GOES HERE]
```

Example:

```bash
HOST=0.0.0.0 PORT=8000 MAX_FILE_MB=20 python autopivot_backend.py
```

Then open the ngrok URL in your browser. If using browser requests from another origin, set `ALLOWED_ORIGINS` to include that URL.

## API Endpoints

- `GET /health` — health and model readiness status.
- `GET /api/status` — API status and configured model names.
- `POST /auth/login` — exchange email and password for a bearer token.
- `GET /auth/me` — the authenticated user plus dealership context.
- `POST /auth/change-password` — rotate the password and clear the
  `must_change_password` flag.
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

Upload fields:

- `file` — required vehicle/image upload.
- `background` — optional custom background for `/process-vehicle`.
- `plate_overlay` — optional numberplate overlay for `/process-vehicle` and `/detect-and-hide`.

## Application Flow

Signing in is required; there is no public interface. A dealership's own data is
the only data any account can reach.

1. **Backdrops** — upload the scenes vehicles are composited onto. A new
   dealership starts with none.
2. **New vehicle** — make, model and year identify the listing; photographs are
   attached to it.
3. **Process** — queues one job per photograph. Vehicle detection, background
   removal, plate masking, then the chosen backdrop.
4. **Vehicles** — originals beside processed results, with per-image outcomes.

A photograph the pipeline finds no vehicle in completes and is marked as needing
review rather than being recorded as a failure: the run was correct, the result
needs a person.

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

This is a prototype. Keep the upload limit and model selection appropriate for
the GPU and memory available in your instance.
