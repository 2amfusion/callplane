# Callplane SIP bridge — wraps upstream livekit/sip (do not fork the Go service here).
# Deploy as a third Railway service; root directory = livekit-sip/
# Docs: README.md, DEPLOY-SIP.md

FROM livekit/sip:v1.3.0

# Upstream: ENTRYPOINT ["livekit-sip", "--config=/sip/config.yaml"], USER unset (root).
# We replace ENTRYPOINT with /start.sh so health-wrapper binds Railway $PORT first.
ENV PYTHONUNBUFFERED=1

# YAML merge/validate for health_port injection (replaces fragile sed).
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-yaml curl \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Signaling + media (container listens on these; Railway only forwards TCP ports you proxy).
EXPOSE 5060/tcp 5060/udp 5061/tcp 8080/tcp
# Default RTP range in livekit/sip; narrow in SIP_CONFIG_BODY if experimenting on Railway.
EXPOSE 10000-10100/udp

COPY inject-config.py /inject-config.py
COPY health-wrapper.py /health-wrapper.py
COPY health-wrapper.sh /health-wrapper.sh
COPY docker-entrypoint.sh /docker-entrypoint.sh
COPY start.sh /start.sh
RUN chmod +x /inject-config.py /health-wrapper.py /health-wrapper.sh /docker-entrypoint.sh /start.sh

# Config via SIP_CONFIG_BODY → inject-config.py → SIP_CONFIG_FILE (see README.md).
# start.sh binds health-wrapper on $PORT, then execs docker-entrypoint.sh.
# MUST override upstream ENTRYPOINT [/livekit-sip] — empty CMD; do not set startCommand in Railway (see railway.json).
ENTRYPOINT ["/start.sh"]

# Railway probes $PORT via health-wrapper (immediate 200). livekit/sip health is internal.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD python3 -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % (os.environ.get('PORT') or '8080'), timeout=3)"
