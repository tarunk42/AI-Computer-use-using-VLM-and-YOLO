#!/bin/sh
# Start the X server, window manager, control server, and keep Firefox running.
Xvfb :0 -screen 0 ${W}x${H}x24 -nolisten tcp &
sleep 1
openbox &
python3 /opt/control.py &
while true; do
  firefox --width "$W" --height "$H" "$START_URL"
  sleep 1
done
