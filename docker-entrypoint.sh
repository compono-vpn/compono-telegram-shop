#!/bin/sh
set -e

ASSETS_DIR="/opt/remnashop/assets"
DEFAULT_DIR="/opt/remnashop/assets.default"
BACKUP_DIR="/opt/remnashop/assets_backup"

if [ "$SKIP_ASSETS_RESET" = "true" ]; then
    echo "Skipping asset backup and reset."
else
    if [ -d "$ASSETS_DIR" ] && [ "$(ls -A "$ASSETS_DIR")" ]; then
        mkdir -p "$BACKUP_DIR"
        timestamp=$(date +"%Y%m%d_%H%M%S")
        tar czf "$BACKUP_DIR/assets_backup_$timestamp.tar.gz" -C "$ASSETS_DIR" .
        echo "Backup saved to $BACKUP_DIR/assets_backup_$timestamp.tar.gz"
    fi

    rm -rf "$ASSETS_DIR"/*
    cp -r "$DEFAULT_DIR"/* "$ASSETS_DIR"
    echo "Assets directory reset and updated from defaults."
fi

echo "Migrating database..."

if ! alembic -c src/infrastructure/database/alembic.ini upgrade head; then
    echo "Database migration failed! Exiting container..."
    exit 1
fi

echo "Migrations deployed successfully!"

UVICORN_RELOAD_ARGS=""
if [ "$UVICORN_RELOAD_ENABLED" = "true" ]; then
  echo "Uvicorn will run with reload enabled."
  UVICORN_RELOAD_ARGS="--reload --reload-dir /opt/remnashop/src --reload-dir /opt/remnashop/assets --reload-include *.ftl"
else
  echo "Uvicorn will run without reload."
fi

exec uvicorn src.__main__:application --host "${APP_HOST}" --port "${APP_PORT}" --factory --use-colors ${UVICORN_RELOAD_ARGS}