# Simorgh Meet AI service (STT server + minutes worker). CPU only.
# Models are NOT baked in: they are mounted read-only from /opt/simorgh-meet/models.
FROM python:3.12-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml ./
COPY simorgh_ai ./simorgh_ai
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install ".[whisper,sherpa]"

FROM python:3.12-slim-bookworm
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    OMP_NUM_THREADS=1
RUN useradd --system --uid 10001 --create-home simorgh \
 && mkdir -p /data/stt /data/minutes \
 && chown -R simorgh /data
COPY --from=build /opt/venv /opt/venv
USER simorgh
WORKDIR /home/simorgh
EXPOSE 8000
CMD ["simorgh-ai", "stt-server"]
