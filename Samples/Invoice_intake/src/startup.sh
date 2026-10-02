#!/usr/bin/env bash
# App Service (Linux) startup command: `bash startup.sh`
# mssql-python needs a few system libraries. Most App Service Python images have them;
# install them only if they're missing.
set -e
if ! ldconfig -p 2>/dev/null | grep -q "libltdl.so.7"; then
  echo "Installing system libraries for mssql-python..."
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq libltdl7 libkrb5-3 libgssapi-krb5-2 >/dev/null
fi
exec python -m uvicorn app.main:app \
  --host 0.0.0.0 --port "${PORT:-8000}" \
  --workers "${WEB_WORKERS:-2}" \
  --proxy-headers --forwarded-allow-ips "*" \
  --timeout-keep-alive 30
