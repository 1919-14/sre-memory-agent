# Runtime image for the SRE Memory Agent on a Hugging Face Space (Docker SDK).
#
# This is the *product* image — it serves the FastAPI API and the built React dashboard
# from one port. It is not the sandbox image (`docker/sandbox.Dockerfile`), which only runs
# generated code and is deliberately minimal.
#
# `deploy/huggingface/sync.sh` copies this file to the root of the Space snapshot as
# `Dockerfile`, because a Space only looks for the Dockerfile at its repository root. The
# dashboard build (`web/dist`) is produced on the GitHub runner and copied in with the
# snapshot, so there is no Node toolchain in this image at all.
#
# Everything the app writes at runtime is redirected to `/data` by `entrypoint.sh`, because
# that is the only path a Space keeps across restarts.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUTF8=1

# `git` is a hard dependency, not a convenience: the agent checks the target repository out
# at the failing revision, reads commit metadata, and reverts to the last known good commit
# during rollback. `curl` is only used for the container healthcheck below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first so the dependency layer is cached independently of the source tree.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

# Spaces route public traffic to this port (`app_port` in the Space card matches it).
ENV API_HOST=0.0.0.0 \
    API_PORT=7860

EXPOSE 7860

# The API answers on /api/status; the timing is generous because the first request
# initialises the storage schema and the demo repository.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7860/api/status > /dev/null || exit 1

CMD ["bash", "entrypoint.sh"]
