# Callplane SIP bridge — wraps upstream livekit/sip (do not fork the Go service here).
# Deploy as a third Railway service; root directory = livekit-sip/
# Docs: README.md, DEPLOY-SIP.md

FROM livekit/sip:v1.3.0

# Lightweight HTTP server for Railway health probes on $PORT (see health-wrapper.sh).
RUN apt-get update && apt-get install -y --no-install-recommends python3-minimal \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Signaling + media (container listens on these; Railway only forwards TCP ports you proxy).
EXPOSE 5060/tcp 5060/udp 5061/tcp 8080/tcp 8081/tcp
# Default RTP range in livekit/sip; narrow in SIP_CONFIG_BODY if experimenting on Railway.
EXPOSE 10000-10100/udp

COPY docker-entrypoint.sh /docker-entrypoint.sh
COPY health-wrapper.sh /health-wrapper.sh
RUN chmod +x /docker-entrypoint.sh /health-wrapper.sh

# Config via SIP_CONFIG_BODY or SIP_CONFIG_FILE (see README.md).
# Entrypoint: wrapper on $PORT (always 200) + livekit/sip health_port on 8081.
ENTRYPOINT ["/docker-entrypoint.sh"]
