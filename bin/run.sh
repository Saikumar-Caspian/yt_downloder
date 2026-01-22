#!/usr/bin/env bash
set -e

BASE_DIR="$HOME/tg-runtime"
LOG_DIR="$BASE_DIR/logs"
APP="$BASE_DIR/app/bot.py"

mkdir -p "$LOG_DIR"

cd "$BASE_DIR"
source venv/bin/activate

set -a
source config/bot.env
set +a

exec python "$APP" >> "$LOG_DIR/bot.log" 2>&1
