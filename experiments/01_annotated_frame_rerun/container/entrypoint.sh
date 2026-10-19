#!/bin/sh
# Lightweight X11 + VNC + SSH desktop for the UI-detection experiment.
set -e

VNC_PASSWORD="${VNC_PASSWORD:-1234}"
ROOT_PASSWORD="${ROOT_PASSWORD:-cua1234}"
RESOLUTION="${RESOLUTION:-1280x800}"

export HOME=/root
export DISPLAY=:0
export MOZ_DISABLE_CONTENT_SANDBOX=1

mkdir -p /tmp/.X11-unix /var/log /root/.ssh
chmod 1777 /tmp/.X11-unix

# --- SSH -------------------------------------------------------------------
ssh-keygen -A >/dev/null 2>&1 || true
if [ -f /etc/ssh/authorized_keys ]; then
    cp /etc/ssh/authorized_keys /root/.ssh/authorized_keys
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
fi
echo "root:${ROOT_PASSWORD}" | chpasswd

# --- X server (Xorg + dummy driver, no real GPU) ---------------------------
Xorg :0 -noreset -nolisten tcp -logfile /var/log/xorg.log &
for i in $(seq 1 100); do
    [ -e /tmp/.X11-unix/X0 ] && break
    sleep 0.2
done
if [ ! -e /tmp/.X11-unix/X0 ]; then
    echo "[!] X server failed to start" >&2
    tail -20 /var/log/xorg.log >&2 || true
    exit 1
fi

# --- window manager --------------------------------------------------------
openbox >/var/log/openbox.log 2>&1 &
sleep 0.6

# --- mock site + browser ---------------------------------------------------
cd /opt/site
python3 -m http.server 8080 --bind 127.0.0.1 >/var/log/http.log 2>&1 &
sleep 0.8

firefox --kiosk "http://127.0.0.1:8080/" >/var/log/firefox.log 2>&1 &

# --- VNC -------------------------------------------------------------------
x11vnc -display :0 -forever -shared -rfbport 5900 \
       -passwd "${VNC_PASSWORD}" -noxdamage -quiet \
       -bg -o /var/log/x11vnc.log

echo "[i] desktop ready: Xorg ${RESOLUTION}, VNC :5900, sshd :22"

exec /usr/sbin/sshd -D -e
