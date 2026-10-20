#!/bin/sh
# Выполняется Postgres только при пустом томе данных.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -c "CREATE DATABASE analytics"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname analytics -f /sql/001_schema.sql
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname analytics -f /sql/003_load.sql
