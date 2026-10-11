#!/usr/bin/env bash
# Copy the app's front end into deploy/vercel/public and deploy it. Run from the repo root.
set -euo pipefail
mkdir -p deploy/vercel/public
cp src/coursebook/app/static/index.html deploy/vercel/public/index.html
cd deploy/vercel && npx --yes vercel@latest deploy --prod --yes
