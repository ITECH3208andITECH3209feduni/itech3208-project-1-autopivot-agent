# AutoPivot Agent

AutoPivot Agent is a FastAPI demo for vehicle image processing. It provides a web interface and API endpoints for vehicle detection, background removal, license plate detection, optional custom backgrounds and optional plate overlays.

## Features

- Upload a vehicle image and process it through the full pipeline.
- Remove image backgrounds with an RMBG-2.0 primary model and BiRefNet version 11 fallback.
- Detect vehicles with YOLO26.
- Detect and hide license plates with nickmuchi/yolos-small-finetuned-license-plate-detection.
- Upload optional custom backgrounds and numberplate overlays.

## Project Structure

- `autopivot_backend.py` - FastAPI backend, static frontend hosting, and image processing endpoints.
- `index.html` - frontend page.
- `style.css` - frontend styling.
- `app.js` - upload, demo, reset, progress, and processing UI logic.
- `assets/demo-car.jpg` - bundled demo image used by the one-click demo.
- `requirements.txt` - Python dependencies.

## Requirements

- Python 3.10+
- A machine with enough RAM/VRAM for the selected vision models.
- **Required**: `HF_TOKEN` for Hugging Face authentication. RMBG-2.0 requires access to the BRIA model license; BiRefNet is used as fallback when the primary model is unavailable.

Install dependencies:

```bash
pip install -r requirements.txt
```

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
```

For larger demo uploads, raise `MAX_FILE_MB`, for example:

```bash
MAX_FILE_MB=50 python autopivot_backend.py
```

## Run Locally

Start the backend:

```bash
python autopivot_backend.py
```

Open:

```text
http://127.0.0.1:8000
```

The backend serves the frontend and static assets. These paths are available:

- `/` — frontend
- `/style.css` and `/static/style.css`
- `/app.js` and `/static/app.js`
- `/static/assets/demo-car.jpg`

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
- `POST /remove-background` — remove background only.
- `POST /process-vehicle` — full pipeline: vehicle detection, background removal, plate detection, plate treatment, optional custom background.
- `POST /detect-and-hide` — detect and hide license plates only.

Upload fields:

- `file` — required vehicle/image upload.
- `background` — optional custom background for `/process-vehicle`.
- `plate_overlay` — optional numberplate overlay for `/process-vehicle` and `/detect-and-hide`.

## Frontend Flow

- `Upload photo` opens the manual file picker.
- `Demo` and `Try demo` load `assets/demo-car.jpg`, select the full pipeline, preview the image, and start processing automatically.
- `Process Image` runs the selected processing mode.
- `Reset Car Upload`, `Reset Background`, and `Reset Numberplate` clear individual inputs.
- `Reset Everything` clears all selected files, progress, errors, preview output, and resets the mode to full pipeline.

## Notes

This is a demo/prototype application. Keep the upload limit and model selection appropriate for the GPU and memory available in your instance.
