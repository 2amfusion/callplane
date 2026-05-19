# Callplane SIP bridge — wraps upstream livekit/sip (do not fork the Go service here).
# Deploy as a third Railway service; root directory = livekit-sip/
# Docs: README.md, DEPLOY-SIP.md

FROM livekit/sip:v1.3.0

# Signaling + media (container listens on these; Railway only forwards TCP ports you proxy).
EXPOSE 5060/tcp 5060/udp 5061/tcp 8080/tcp
# Default RTP range in livekit/sip; narrow in SIP_CONFIG_BODY if experimenting on Railway.
EXPOSE 10000-10100/udp

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Config via SIP_CONFIG_BODY or SIP_CONFIG_FILE (see README.md).
# Entrypoint injects health_port from Railway $PORT into SIP_CONFIG_BODY.
ENTRYPOINT ["/docker-entrypoint.sh"]
