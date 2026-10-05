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
# PYTHON=python3.12 bash setup.sh picks the interpreter when python3 is not
# the one to use.
PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || die "$PYTHON is not installed."
"$PYTHON" --version

# 3.10 or newer, checked before anything is installed. The code uses
# `str | None` annotations at run time, which 3.9 — still /usr/bin/python3 on a
# stock Mac — accepts all the way through the install and then crashes on when
# the backend starts.
new_enough() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
version_of() { "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "unknown"; }

new_enough "$PYTHON" || die "AutoPivot needs Python 3.10 or newer; $PYTHON is $(version_of "$PYTHON").
Install Python 3.12 (https://www.python.org/downloads/, or: brew install python@3.12)
and run this again with it:  PYTHON=python3.12 bash setup.sh"

if [ -x ".venv/bin/python" ]; then
  # A .venv left by an earlier run with an older Python would otherwise be
  # reused as it is, and fail the same way.
  new_enough .venv/bin/python || die "The existing .venv was made with Python $(version_of .venv/bin/python), and AutoPivot needs 3.10 or newer.
Delete it (rm -rf .venv) and run this again."
  echo "Virtual environment already exists."
else
  echo "Creating virtual environment in .venv ..."
  "$PYTHON" -m venv .venv
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
text = p.read_text(encoding="utf-8")
if "JWT_SECRET=" in text:
    p.write_text(
        text.replace("JWT_SECRET=", "JWT_SECRET=" + secrets.token_urlsafe(48), 1),
        encoding="utf-8",
    )
    print("Created .env with a generated signing key.")
else:
    print("warning: created .env, but .env.example has no JWT_SECRET= line, so no")
    print("signing key was written - every backend restart will sign everyone out.")
PY
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
