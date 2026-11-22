FROM ghcr.io/openhands/enterprise-server:1.88.0
USER root
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

COPY integration.patch /tmp/modal-integration.patch
RUN cd /app && patch --batch --forward -p1 -i /tmp/modal-integration.patch \
    && uv pip install --python /app/.venv/bin/python 'modal==1.6.0' \
    && rm /tmp/modal-integration.patch
COPY --chown=openhands:openhands openhands /app/openhands
COPY --chown=openhands:openhands migrations /app/migrations
RUN /app/.venv/bin/python -c 'import openhands.app_server.sandbox.modal_gateway'
USER openhands
