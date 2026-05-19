# LiveKit Agents worker — deploy as a separate Railway service (see CALLPLANE.md).
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libopus0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py bitebuddy_llm.py health-wrapper.py start.sh .
RUN chmod +x start.sh

# Pre-bundle common model weights where supported (best-effort).
RUN python agent.py download-files || true

CMD ["/app/start.sh"]
