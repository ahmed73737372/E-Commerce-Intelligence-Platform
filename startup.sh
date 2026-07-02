#!/bin/bash
# Azure App Service startup — FastAPI API server
set -euo pipefail

APP_DIR="${APP_PATH:-/home/site/wwwroot}"
cd "${APP_DIR}"
export PYTHONPATH="${APP_DIR}:${PYTHONPATH:-}"

PORT="${PORT:-${WEBSITES_PORT:-8000}}"

PYTHON="python"
if [ -f "${APP_DIR}/antenv/bin/python" ]; then
  PYTHON="${APP_DIR}/antenv/bin/python"
  export PATH="${APP_DIR}/antenv/bin:${PATH}"
fi

if ! "${PYTHON}" -c "import uvicorn" >/dev/null 2>&1; then
  echo "Installing API dependencies from requirements.txt..."
  "${PYTHON}" -m pip install --upgrade pip
  "${PYTHON}" -m pip install -r requirements.txt
fi

echo "Python: $("${PYTHON}" --version)"
echo "Working directory: $(pwd)"
echo "PYTHONPATH=${PYTHONPATH}"
echo "Starting FastAPI from ${APP_DIR} on port ${PORT}..."

# application.py at repo root — no PYTHONPATH required, but we set it anyway.
exec "${PYTHON}" -m uvicorn application:app \
  --app-dir "${APP_DIR}" \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --log-level info \
  --timeout-keep-alive 120
