# AutoPivot

AutoPivot is a vehicle-image processing demo with three modes:

- Full vehicle processing
- Background removal
- Numberplate detection and hiding

The full pipeline detects the main vehicle, removes its background, places it in an AutoPivot showroom, applies light edge/colour/shadow matching, then detects and hides numberplates.

## Project structure

```text
api.py                 FastAPI routes and validation
autopivot_backend.py   Server entry point
pipeline_service.py    Image-processing workflow
model_registry.py      Loads and reuses AI models
config.py              Runtime settings and showroom presets
errors.py              Consistent API errors
index.html             Frontend structure
style.css              Frontend styling
app.js                  Frontend behaviour
assets/backgrounds/    AutoPivot showroom images
```

## Setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env`.

3. Add your Hugging Face token to `.env`:

```env
HF_TOKEN=your_token_here
```

4. Start the server:

```bash
python autopivot_backend.py
```

5. Open:

```text
http://127.0.0.1:8000
```

Do not open `index.html` directly; use the FastAPI server.

## Background presets

- `studio_full` — full vehicle on the raised AutoPivot display base
- `studio_closeup` — close-up/interior framing
- `transparent` — no replacement background
- `custom` — uploaded background

The full-car preset stores only the display-base ellipse, tyre contact line, and vehicle scale in `config.py`. This replaces the previous separate measurement document and multiple platform/rim masks.

## API routes

```text
POST /process-vehicle
POST /remove-background
POST /detect-and-hide

POST /api/v1/process-vehicle
POST /api/v1/remove-background
POST /api/v1/detect-and-hide
```

## Main processing flow

```text
vehicle detection
→ background removal
→ small alpha-edge cleanup
→ resize and position
→ subtle colour matching
→ soft ground shadow
→ numberplate detection/hiding
→ final image
```

Floor reflections are intentionally not generated.
