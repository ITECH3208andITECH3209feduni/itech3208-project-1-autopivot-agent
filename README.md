# AutoPivot Agent

AutoPivot prepares vehicle photos for a dealership listing. It can:

- remove the original background;
- detect the vehicle and licence plate;
- blur, pixelate or cover the plate;
- place the vehicle in a showroom background; and
- add realistic sizing, tyre contact and shadows.

The project has a FastAPI backend and a React/Vite website. The backend uses
PyTorch for the vision models and chooses the best available device
automatically.

## Device selection

By default the application checks:

1. NVIDIA CUDA on Windows or Linux;
2. Apple Metal (MPS) on a compatible Apple Silicon Mac; and
3. CPU when no usable accelerator is found.

A small test runs before an accelerator is selected. If the test fails, the
application continues on the CPU instead of stopping.

To choose a device yourself, add this to `.env`:

```dotenv
AUTOPIVOT_DEVICE=auto   # auto, cuda, mps or cpu
```

The selected device is printed in the backend log and is available from
`/health` and `/api/status`.

## Requirements

Install these before starting:

- Python 3.10 or newer (Python 3.11 or 3.12 is recommended).
- Node.js LTS and npm.
- An NVIDIA driver for CUDA acceleration on Windows/Linux, or an Apple Silicon
  Mac for MPS acceleration. A GPU is optional; CPU mode also works.

You do not need Docker or the CUDA Toolkit for local development. The PyTorch
installer selects the appropriate package for the computer.

## Windows setup

Open the project folder in VS Code or any terminal or IDE. From the project root, run
the setup script:

```powershell
setup.bat
```

It creates the virtual environment, installs the correct PyTorch build,
installs the Python and website packages, creates the SQLite database and
prints a login account. If an NVIDIA GPU is not available, it installs a CPU
build. Add `HF_TOKEN` or change `AUTOPIVOT_DEVICE` in `.env` when needed.

Start the site with:

```powershell
run.bat
```

This opens the backend and website in separate windows and opens the website at
<http://localhost:5173>.

If PowerShell blocks activation, run this once as your normal user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate the environment again.

## macOS setup

Open Terminal in the project folder and run:

```bash
bash setup.sh
```

The script creates the virtual environment, installs the normal PyPI PyTorch
wheel, keeps Apple Silicon MPS support, installs the website and creates the
local database and login account. Intel Macs continue with CPU mode.

Start both parts with:

```bash
bash run.sh
```

The site opens at <http://localhost:5173>. Press `Ctrl+C` in that terminal to
stop both processes.

## Linux setup

Open a terminal in the project folder and run:

```bash
bash setup.sh
```

The installer uses CUDA when `nvidia-smi` detects a compatible NVIDIA driver.
Without one, it installs the CPU build. Start the application with:

```bash
bash run.sh
```


Windows terminal 1:

```powershell
.\.venv\Scripts\Activate.ps1
python autopivot_backend.py
```

macOS/Linux terminal 1:

```bash
source .venv/bin/activate
python autopivot_backend.py
```

Terminal 2 on every operating system:

```bash
npm run dev --prefix frontend
```

Open <http://localhost:5173>. The full API loads the vision models; the light
API starts quickly but cannot process images.

## Hugging Face token

The recommended background model, `briaai/RMBG-2.0`, requires a free Hugging
Face account and accepted model licence.

1. Create a **Read** token at <https://huggingface.co/settings/tokens>.
2. Accept the licence at <https://huggingface.co/briaai/RMBG-2.0>.
3. Put the token in `.env`:

   ```dotenv
   HF_TOKEN=hf_your_token_here
   ```

Without the token, AutoPivot uses the BiRefNet fallback. The application still
starts and can process images.

## Database and login

For local development, `.env.example` leaves `DATABASE_URL` blank. The
application then uses a local SQLite file named `autopivot.db`; no database
server is required.

The setup commands create the database and a demo dealership account. Copy the
email and generated password printed by `seed_dealership.py`. The first login
asks you to change that password.

PostgreSQL is also supported for a shared environment. Set a PostgreSQL URL in
`.env` before running the database setup:

```dotenv
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/autopivot
```

Never commit `.env`, passwords, tokens or model caches to GitHub.

## Models and first run

The first full backend start may download several large model files from
Hugging Face. This is normal. They are cached and reused on later starts.

To see what is installed and which device will be used, run:

Windows:

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.check_setup
```

macOS/Linux:

```bash
source .venv/bin/activate
python -m scripts.check_setup
```

The check reports CUDA, MPS or CPU, package status, database status and the
frontend installation.

## Common problems

| Problem | What to check |
|---|---|
| `ModuleNotFoundError` | Activate `.venv` and run commands from the project root. |
| Processing is slow | Run `scripts.check_setup`; the selected device may be CPU. |
| MPS is not selected | Use an Apple Silicon Mac and install PyTorch with `python scripts/install_torch.py`. |
| Login fails | Run `python -m scripts.seed_dealership` and use the printed credentials. |
| Browser says connection refused | Start both parts, or run `run.bat`/`bash run.sh`. |
| Port 8000 is busy | Stop the older backend process or change `PORT` in `.env`. |
| Model download fails | Check internet access, `HF_TOKEN` and the model licence. |

## Tests

Pytest is not part of the runtime dependencies. Install it in the active
virtual environment, then run:

```bash
python -m pip install pytest
python -m pytest tests -v
```

The device-selection tests use fake CUDA and MPS backends, so they do not need
physical GPU hardware.

## Project structure

```text
autopivot_backend.py       Full FastAPI application and model registry
device_utils.py             CUDA/MPS/CPU selection and diagnostics
classification.py           CLIP image classification
compositing.py              Vehicle placement, sizing and shadows
api/                        Authentication, listings and processing API
database/                   SQLAlchemy models and database connection
scripts/                    Setup, device checks, database and seed commands
frontend/                   React/Vite website
assets/backgrounds/         Studio background images
tests/                      Automated tests
.vscode/                    VS Code launch and task configurations
setup.bat / setup.sh        One-time setup scripts
run.bat / run.sh            Start scripts for Windows and macOS/Linux
```

## License

This project is for the AutoPivot university project and local development.
