#!/usr/bin/env bash
# ============================================================================
# AutoPivot - one-time setup for macOS and Linux
#
#     bash setup.sh
#
# The Windows equivalent is setup.bat. Safe to run again: every step skips
# work that is already done.
# ============================================================================

set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
die() { printf '\033[31merror: %s\033[0m\n' "$1" >&2; exit 1; }

say "Python"
command -v python3 >/dev/null 2>&1 || die "python3 is not installed."
python3 --version

if [ -x ".venv/bin/python" ]; then
  echo "Virtual environment already exists."
else
  echo "Creating virtual environment in .venv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip --quiet

say "Configuration"
if [ -f .env ]; then
  echo ".env already exists - leaving it alone."
else
  cp .env.example .env
  python - <<'PY'
import pathlib, secrets
p = pathlib.Path(".env")
p.write_text(
    p.read_text(encoding="utf-8").replace(
        "JWT_SECRET=", "JWT_SECRET=" + secrets.token_urlsafe(48), 1
    ),
    encoding="utf-8",
)
PY
  echo "Created .env with a generated signing key."
  echo "Add your Hugging Face token to it as HF_TOKEN when you have one."
fi

say "PyTorch"
python scripts/install_torch.py

say "Python packages"
python -m pip install -r requirements-ml.txt

say "Website"
if command -v npm >/dev/null 2>&1; then
  npm install --prefix frontend
else
  echo "warning: npm not found - install Node.js LTS from https://nodejs.org/"
fi

say "Database"
python -m scripts.init_db
echo
python -m scripts.seed_dealership

say "Checking the setup"
python -m scripts.check_setup || true

say "Done"
cat <<'EOF'

Start the API:       source .venv/bin/activate && python autopivot_backend.py
Start the website:   npm run dev --prefix frontend
Start both:          bash run.sh
Then open:           http://localhost:5173

Sign in with the email and password printed above - the password is only
shown once.
EOF
