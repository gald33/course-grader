#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[course-grader] Preparing data directories..."
mkdir -p data/artifacts data/snapshots data/exports data/secrets

if [[ ! -f data/secrets/google_client.json ]]; then
  cat > data/secrets/google_client.json <<'JSON'
{
  "installed": {
    "client_id": "PUT_YOUR_CLIENT_ID_HERE",
    "project_id": "PUT_YOUR_PROJECT_ID_HERE",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "PUT_YOUR_CLIENT_SECRET_HERE",
    "redirect_uris": [
      "http://localhost:8000/api/oauth/google/callback"
    ]
  }
}
JSON
  echo "[course-grader] Created data/secrets/google_client.json template."
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "[course-grader] Docker CLI not found. Install Docker Desktop first: https://www.docker.com/products/docker-desktop/"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "[course-grader] Starting Docker Desktop..."
  open -a Docker || true
  echo "[course-grader] Waiting for Docker daemon..."
  for i in {1..90}; do
    if docker info >/dev/null 2>&1; then
      echo "[course-grader] Docker is ready."
      break
    fi
    sleep 2
  done
fi

if ! docker info >/dev/null 2>&1; then
  echo "[course-grader] Docker daemon is not ready. Open Docker Desktop and retry."
  exit 1
fi

echo "[course-grader] Building and starting services..."
docker compose up -d --build

echo "[course-grader] Waiting for backend health..."
for i in {1..90}; do
  if curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "[course-grader] Backend is healthy."
    break
  fi
  sleep 2
done

if ! curl -fsS http://localhost:8000/api/health >/dev/null 2>&1; then
  echo "[course-grader] Backend health check failed. Inspect logs: docker compose logs -f backend worker"
  exit 1
fi

echo ""
echo "[course-grader] Ready"
echo "Frontend: http://localhost:3000"
echo "Backend : http://localhost:8000"
echo ""
echo "Tip: run 'make open' to open both URLs in your browser."
