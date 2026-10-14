#!/bin/sh
# Deploy the API, then the frontend, to Vercel production from the repo root.
# Pushes to main deploy automatically through the Git integration; this is
# the manual path. The Vercel projects build from backend/ and frontend/
# (their Root Directory setting), so the CLI must run from the repo root.
set -e
cd "$(dirname "$0")/.."
VERCEL="vercel --global-config ${VERCEL_CONFIG:-$HOME/.vercel-yvc}"
for pair in backend:course-grader-api frontend:course-grader; do
  dir=${pair%%:*}
  project=${pair#*:}
  [ -f "$dir/.vercel/project.json" ] || (cd "$dir" && $VERCEL link --yes --project "$project" >/dev/null)
  org=$(python3 -c "import json; print(json.load(open('$dir/.vercel/project.json'))['orgId'])")
  id=$(python3 -c "import json; print(json.load(open('$dir/.vercel/project.json'))['projectId'])")
  echo "Deploying $project"
  VERCEL_ORG_ID=$org VERCEL_PROJECT_ID=$id $VERCEL deploy --prod --yes
done
