ARG OPENWEBUI_VERSION=v0.9.6
FROM ghcr.io/open-webui/open-webui:${OPENWEBUI_VERSION}

RUN pip install --no-cache-dir honcho-ai==2.1.2

