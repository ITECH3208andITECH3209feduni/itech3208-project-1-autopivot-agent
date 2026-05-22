# AutoPivot Agent

AutoPivot Agent is a demo application that performs server-side vehicle image processing with background removal, vehicle detection, license plate detection, and optional plate overlay.

## Backend

The backend is implemented in `autopivot_backend.py` using FastAPI. It hosts endpoints for:

- `POST /remove-background` — remove image background with RMBG-2.0
- `POST /detect-vehicles` — detect vehicles with YOLOv8
- `POST /detect-plates` — detect license plates with YOLOS
- `POST /overlay-plate` — cover detected plates with a solid color or uploaded overlay image

## Requirements

- Python 3.10+
- `torch`, `transformers`, `ultralytics`, `fastapi`, `uvicorn`, `pillow`, `numpy`, `pyngrok`

Install dependencies with:

```bash
pip install -r requirements.txt
```

## Run

Start the backend locally:

```bash
python autopivot_backend.py
```

The server listens on `http://127.0.0.1:8000` by default.

To expose the service with ngrok:

```bash
python autopivot_backend.py --ngrok
```

## Frontend

Open `index.html` in a browser and set `BACKEND_URL` in `app.js` if needed. The frontend uploads images to the backend and displays processed results.

## Notes

This repository is a demo implementation and is intended for local testing and prototyping.
