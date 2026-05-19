# Callplane SIP bridge — wraps upstream livekit/sip (do not fork the Go service here).
# Deploy as a third Railway service; root directory = livekit-sip/
# Docs: README.md, DEPLOY-SIP.md

FROM livekit/sip:v1.3.0

# YAML merge/validate for health_port injection (replaces fragile sed).
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-yaml \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

# Signaling + media (container listens on these; Railway only forwards TCP ports you proxy).
EXPOSE 5060/tcp 5060/udp 5061/tcp 8080/tcp
# Default RTP range in livekit/sip; narrow in SIP_CONFIG_BODY if experimenting on Railway.
EXPOSE 10000-10100/udp

COPY inject-config.py /inject-config.py
COPY health-wrapper.sh /health-wrapper.sh
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /inject-config.py /health-wrapper.sh /docker-entrypoint.sh

# Config via SIP_CONFIG_BODY → inject-config.py → SIP_CONFIG_FILE (see README.md).
# Railway: railway.json startCommand runs /docker-entrypoint.sh (wrapper binds $PORT first).
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["/docker-entrypoint.sh"]

# Railway probes $PORT via health-wrapper (immediate 200). livekit/sip health is internal.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
  CMD python3 -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('PORT','8080'), timeout=3)"
