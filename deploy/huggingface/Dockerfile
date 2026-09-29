# Runtime image for the SRE Memory Agent on a Hugging Face Space (Docker SDK).
#
# This is the *product* image — it serves the FastAPI API and the built React dashboard
# from one port, and it also runs the agent's memory layer. It is not the sandbox image
# (`docker/sandbox.Dockerfile`), which only runs generated code and is deliberately minimal.
#
# `deploy/huggingface/sync.sh` copies this file to the root of the Space snapshot as
# `Dockerfile`, because a Space only looks for the Dockerfile at its repository root. The
# dashboard build (`web/dist`) is produced on the GitHub runner and copied in with the
# snapshot, so there is no Node toolchain in this image at all.
#
# Two processes run here, because a Space gets one container: the API, and a Hindsight server
# for the agent to remember with (see `entrypoint.sh`). That choice costs image size —
# `hindsight-all` bundles PostgreSQL and the embedding models — and buys the thing this
# project is actually about: an agent whose memory survives a restart.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUTF8=1

# `git` is a hard dependency, not a convenience: the agent checks the target repository out
# at the failing revision, reads commit metadata, and reverts to the last known good commit
# during rollback. `curl` is the container healthcheck and the memory server's readiness
# probe. `util-linux` provides `setpriv`, which drops privileges for the memory server.
# `openssh-client` is for the sandbox: the Docker CLI's `ssh://` transport shells out to `ssh`,
# which is how a daemon elsewhere is reached without managing certificates.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl ca-certificates util-linux openssh-client \
    && rm -rf /var/lib/apt/lists/*

# The Docker *client*, and only the client. A Space cannot run a daemon — that needs privileged
# mode or the host socket, and Spaces provide neither — but generated code still has to be
# isolated, so the sandbox talks to a daemon elsewhere through `DOCKER_HOST` (see step 3 of
# `entrypoint.sh`). With no daemon configured, the agent reports the local backend as the
# degradation it is rather than calling it isolation.
#
# x86_64 because that is what every Space's cpu-basic/free tier is; the static CLI is used
# instead of `apt-get install docker.io`, which would also pull the daemon and its dependencies
# into the image for nothing.
ARG DOCKER_CLI_VERSION=27.3.1
RUN curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz" \
    | tar -xz --strip-components=1 -C /usr/local/bin docker/docker \
    && docker --version

WORKDIR /app

# Requirements first so the dependency layer is cached independently of the source tree.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# The memory server (see step 4 of `entrypoint.sh`). Two choices here are deliberate:
#
#  * CPU-only torch, installed first and from its own index. The default Linux wheel requires
#    the CUDA runtime (`nvidia-cudnn`, `-nccl`, `-cusparselt`, ...), several GB that a
#    cpu-basic Space can never use. Installing the CPU build first leaves that requirement
#    already satisfied, so the resolver below has no reason to fetch it.
#  * `hindsight-all` pinned to the release the memory layer is verified against
#    (`HINDSIGHT.md`) — client and server are the same version here, so they cannot drift.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir "hindsight-all==0.10.1" "pg0-embedded>=0.15.0"
# `pg0-embedded` is named explicitly even though `hindsight-all` pulls it in: the launcher
# imports it directly to start the database (see `memory/embedded.py`), so it is a real
# dependency of this image rather than an implementation detail of a transitive extra.

# Fail the build rather than silently ship a GPU-sized image if the CPU wheel did not take.
RUN python -c "import torch, sys; sys.exit('CUDA torch build in a CPU-only image') if torch.version.cuda else 0"

COPY . .

RUN chmod +x entrypoint.sh

# Hindsight's embedded PostgreSQL refuses to run as root, so the memory server runs as this
# user while the API stays root — which is what keeps /data writable whatever the Space
# mounts there. Its home is under /data because embedded PostgreSQL stores its data in
# $HOME/.pg0, and /data is the only path a Space preserves across a restart.
RUN useradd --uid 1000 --home-dir /data/hindsight --create-home --shell /usr/sbin/nologin hindsight

# Spaces route public traffic to this port (`app_port` in the Space card matches it). The
# memory server listens on 127.0.0.1:8888, which is deliberately not published.
#
# HINDSIGHT_BASE_URL is deliberately absent: `entrypoint.sh` treats "no base URL configured" as
# the signal to use Hindsight Cloud once HINDSIGHT_API_KEY is present, and a default here would
# make that state unreachable — setting a key would silently keep using the in-container server.
# Without a key, the entrypoint points the agent at 127.0.0.1:8888 itself.
ENV API_HOST=0.0.0.0 \
    API_PORT=7860 \
    SANDBOX_BACKEND=local

EXPOSE 7860

# The API answers on /api/status. `start-period` covers the whole cold start: the memory
# server is brought up first (PostgreSQL initialisation plus an embedding-model download on a
# fresh /data), and the API itself initialises storage and the demo repository after that.
HEALTHCHECK --interval=30s --timeout=5s --start-period=240s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7860/api/status > /dev/null || exit 1

CMD ["bash", "entrypoint.sh"]
