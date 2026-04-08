#!/bin/bash
# Run trading bot every 5 minutes during market hours
# Market hours: Mon-Fri 9:30 AM - 4:00 PM ET (1:30 PM - 8:00 PM GMT)

cd ~/projects/trading-bot
~/projects/trading-bot/venv/bin/python trading_bot.py >> ~/projects/trading-bot/runs.log 2>&1
