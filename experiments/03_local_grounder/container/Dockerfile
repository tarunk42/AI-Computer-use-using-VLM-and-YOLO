FROM alpine:3.22

ENV HOME=/root \
    MOZ_DISABLE_CONTENT_SANDBOX=1 \
    DISPLAY=:0

# Minimal X11 + VNC + SSH + one browser + input automation.
RUN apk add --no-cache \
        xorg-server xf86-video-dummy xkeyboard-config xkbcomp \
        x11vnc openbox openssh-server firefox \
        ttf-dejavu font-noto python3 bash curl xdotool scrot \
    && rm -rf /var/cache/apk/* /var/lib/apk/*

COPY xorg.conf       /etc/X11/xorg.conf
COPY authorized_keys /etc/ssh/authorized_keys
COPY site/           /opt/site/
COPY entrypoint.sh   /usr/local/bin/entrypoint.sh

RUN chmod +x /usr/local/bin/entrypoint.sh \
    && sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config \
    && sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/'      /etc/ssh/sshd_config \
    && mkdir -p /root/.mozilla /root/.cache

EXPOSE 22 5900 8080

CMD ["/usr/local/bin/entrypoint.sh"]
