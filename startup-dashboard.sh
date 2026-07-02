#!/bin/bash
# Azure App Service startup — Streamlit dashboard (second Web App)
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

if ! "${PYTHON}" -c "import streamlit" >/dev/null 2>&1; then
  echo "Installing dashboard dependencies from requirements.txt..."
  "${PYTHON}" -m pip install --upgrade pip
  "${PYTHON}" -m pip install -r requirements.txt
fi

echo "Python: $("${PYTHON}" --version)"
echo "Starting Streamlit dashboard from ${APP_DIR} on port ${PORT}..."
exec "${PYTHON}" -m streamlit run src/dashboard/app.py \
  --server.port="${PORT}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false
