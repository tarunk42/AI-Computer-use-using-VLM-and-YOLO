# Browser desktop for the guided agent: Xvfb + Openbox + Firefox, driven by a tiny HTTP
# control server (screenshot / click / type / key / scroll). No SSH: one kept-alive HTTP
# connection from the host does everything.
FROM alpine:3.22

RUN apk add --no-cache xvfb openbox firefox xdotool python3 py3-pillow \
        font-noto font-dejavu font-noto-emoji ttf-liberation dbus-x11 ca-certificates tzdata

COPY policies.json /usr/lib/firefox/distribution/policies.json
COPY control.py start.sh /opt/
RUN chmod +x /opt/start.sh && adduser -D -u 1000 web

USER web
ENV DISPLAY=:0 W=1280 H=800 START_URL=https://en.wikipedia.org/wiki/Main_Page
EXPOSE 8000
CMD ["/opt/start.sh"]
