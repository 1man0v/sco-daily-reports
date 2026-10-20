#!/bin/bash
set -euo pipefail
export PYTHONPATH="/app/pythonpath${PYTHONPATH:+:$PYTHONPATH}"
export SUPERSET_CONFIG_PATH="/app/pythonpath/superset_config.py"
export FLASK_APP="superset.app:create_app()"
cd /app

echo "upgrade metadata"
ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if superset db upgrade; then
    ok=1
    break
  fi
  echo "db upgrade retry"
  sleep 3
done
test "$ok" = 1

echo "create admin if missing"
superset fab create-admin \
  --username admin \
  --firstname "Отчёты" \
  --lastname "КСО" \
  --email admin@localhost \
  --password "$SUPERSET_ADMIN_PASSWORD" \
  || echo "admin already exists"

echo "init roles"
superset init

echo "listen 8088"
exec gunicorn \
  --bind 0.0.0.0:8088 \
  --workers 2 \
  --threads 4 \
  --timeout 180 \
  --limit-request-line 0 \
  "superset.app:create_app()"
