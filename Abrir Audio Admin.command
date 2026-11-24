#!/bin/bash
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PORT="${AUDIO_ADMIN_PORT:-8060}"
(sleep 2; open "http://127.0.0.1:$PORT") &
exec python3 app.py
