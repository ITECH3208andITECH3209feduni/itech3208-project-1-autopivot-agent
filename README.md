# AutoPivot

AutoPivot processes vehicle images using three modes:

- Full vehicle processing
- Background removal
- Numberplate detection and hiding

## Project files

- `autopivot_backend.py` starts the server.
- `api.py` receives website and app requests.
- `pipeline_service.py` contains the image-processing workflow.
- `model_registry.py` loads each AI model once and reuses it.
- `config.py` reads settings from `.env`.
- `errors.py` keeps API errors consistent.
- `index.html`, `style.css` and `app.js` are the frontend.
- `assets/` contains `demo-car.jpg` and `demo-showroom.jpg`.
- `tests/test_autopivot.py` contains the regression tests.

## Run the project

1. Install the packages:

```bash
pip install -r requirements.txt
```

2. Copy `.env.example` and rename the copy to `.env`. Add your Hugging Face token:

```env
HF_TOKEN=your_token_here
```

3. Keep both demo images inside the `assets` folder.

4. Start the server:

```bash
python autopivot_backend.py
```

5. Open this address in your browser:

```text
http://127.0.0.1:8000
```

Do not open `index.html` directly. The frontend should be opened through the running FastAPI server.

## API routes

Website routes:

```text
POST /process-vehicle
POST /remove-background
POST /detect-and-hide
```

Future Capacitor routes:

```text
POST /api/v1/process-vehicle
POST /api/v1/remove-background
POST /api/v1/detect-and-hide
```

## Run tests

```bash
python -m pytest
```

The tests use fake models, so they do not download the large AI models.
