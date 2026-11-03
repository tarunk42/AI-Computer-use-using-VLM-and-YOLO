#!/bin/sh
# Full Chromium on its own virtual screen (:1); control server on 127.0.0.1:8002.
cd ~/guided_agent
pkill -f "chromium/control.py" 2>/dev/null; pkill -f "Xvfb :1" 2>/dev/null; sleep 1
rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
Xvfb :1 -screen 0 1280x800x24 -nolisten tcp > /dev/null 2>&1 &
sleep 1
DISPLAY=:1 nohup .venv/bin/python chromium/control.py > chromium/control.log 2>&1 < /dev/null &
