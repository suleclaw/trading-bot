#!/bin/bash
# Trading Bot Scheduler
# Runs every 5 minutes during market hours (Mon-Fri 9:30 AM - 4:00 PM ET)
# Market hours in UTC: 13:30 - 20:00 Mon-Fri

cd ~/projects/trading-bot

LOCK_FILE="/tmp/trading-bot.pid"
UV_PATH="/root/.local/bin/uv"
if [ ! -f "$UV_PATH" ]; then
    UV_PATH=$(which uv 2>/dev/null)
fi

# Bail if already running
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        exit 0
    fi
    # Stale lock — remove it
    rm -f "$LOCK_FILE"
fi

# Grab the lock
echo $$ > "$LOCK_FILE"
trap "rm -f '$LOCK_FILE'" EXIT

# Run the bot
$UV_PATH run python scheduler.py --continuous >> ~/projects/trading-bot/runs.log 2>&1
