#!/usr/bin/env bash
#
# Container entrypoint for the SRE Memory Agent Hugging Face Space.
#
# Responsibilities, in order: point the agent's writable state at the one persistent path,
# seed the recorded trajectories the replay path reads, derive honest capability defaults
# from the secrets that are actually present, build the demo repository, then serve.
#
# Every override below is a default: anything set in the Space's environment already wins,
# so this file never becomes the only place a setting can be changed.

set -euo pipefail

APP_DIR="${APP_DIR:-/app}"
cd "$APP_DIR"

log() { printf '[entrypoint] %s\n' "$*"; }

# ── 1. persistent storage ────────────────────────────────────────────────────
# Incident history, recorded trajectories and the runbook all go under /data: /data is the
# only path a Space preserves across a restart, and a memory agent whose history disappears
# on every deploy is not a memory agent. These are absolute paths, so `Settings.abspath`
# passes them through untouched.
export DATABASE_URL="${DATABASE_URL:-sqlite:////data/agent.db}"
export RUNS_DIR="${RUNS_DIR:-/data/runs}"
export RUNBOOK_DIR="${RUNBOOK_DIR:-/data/runbook}"
# stdout is what the Space log shows; a log file inside the container would be lost with it.
export LOG_TO_FILE="${LOG_TO_FILE:-false}"
mkdir -p /data/runs /data/runbook

# ── 2. recorded trajectories ─────────────────────────────────────────────────
# `data/runs/*.json` ships in the image (see deploy/huggingface/sync.sh) and is what the
# replay path re-renders when there is no LLM key. Copy them once into the persistent
# directory, and never overwrite a trajectory recorded by a real run in this Space.
if [ -d "$APP_DIR/data/runs" ]; then
  seeded=0
  for source in "$APP_DIR"/data/runs/*.json; do
    [ -e "$source" ] || continue
    target="/data/runs/$(basename "$source")"
    if [ ! -e "$target" ]; then
      cp "$source" "$target"
      seeded=$((seeded + 1))
    fi
  done
  [ "$seeded" -gt 0 ] && log "seeded $seeded recorded trajectories into /data/runs"
fi

# ── 3. sandbox ───────────────────────────────────────────────────────────────
# A Space cannot run a Docker daemon (that needs privileged mode or the host socket, neither of
# which Spaces provide), so container isolation comes from a daemon *elsewhere*, reached with
# the Docker CLI's own `DOCKER_HOST`. Everything below only materialises credentials; the
# address itself is passed straight through as a Space variable or secret.
#
# `auto` is deliberately the default rather than `local`: it uses the container backend when a
# daemon answers and says why it could not when none does, so the dashboard reports a real
# downgrade instead of a silent one. Nothing here claims isolation the run did not have.
export SANDBOX_BACKEND="${SANDBOX_BACKEND:-auto}"

if [ -n "${DOCKER_SSH_KEY:-}" ]; then
  # `ssh://` transport: the Docker CLI shells out to `ssh`, which reads the default identity
  # from ~/.ssh. Written here rather than baked into the image because it is a credential.
  mkdir -p /root/.ssh && chmod 700 /root/.ssh
  printf '%s\n' "$DOCKER_SSH_KEY" > /root/.ssh/id_rsa
  chmod 600 /root/.ssh/id_rsa
  # The daemon host is not known in advance, so its key cannot be pinned. accept-new still
  # refuses a *changed* key, which is the attack that matters.
  printf 'Host *\n  StrictHostKeyChecking accept-new\n' > /root/.ssh/config
  chmod 600 /root/.ssh/config
  log "DOCKER_SSH_KEY set: the sandbox can reach a daemon over ssh://"
fi

if [ -n "${DOCKER_CA_CERT:-}" ] || [ -n "${DOCKER_CLIENT_CERT:-}" ] || [ -n "${DOCKER_CLIENT_KEY:-}" ]; then
  # `tcp://` transport: the Docker CLI expects ca.pem/cert.pem/key.pem in DOCKER_CERT_PATH.
  # The PEM bodies arrive as secrets, so they are written to files under /data — the only path
  # a Space preserves — and never inlined into the image.
  mkdir -p /data/.docker && chmod 700 /data/.docker
  [ -n "${DOCKER_CA_CERT:-}" ] && printf '%s\n' "$DOCKER_CA_CERT" > /data/.docker/ca.pem
  [ -n "${DOCKER_CLIENT_CERT:-}" ] && printf '%s\n' "$DOCKER_CLIENT_CERT" > /data/.docker/cert.pem
  [ -n "${DOCKER_CLIENT_KEY:-}" ] && printf '%s\n' "$DOCKER_CLIENT_KEY" > /data/.docker/key.pem
  chmod 600 /data/.docker/*.pem 2>/dev/null || true
  export DOCKER_CERT_PATH=/data/.docker
  export DOCKER_TLS_VERIFY="${DOCKER_TLS_VERIFY:-1}"
  log "Docker TLS certificates written to $DOCKER_CERT_PATH (DOCKER_TLS_VERIFY=$DOCKER_TLS_VERIFY)"
  # A PEM that lost its newlines on the way into a secret is the usual cause of a TLS
  # handshake failure, and it is silent otherwise. Say so at boot instead.
  for pem in ca cert key; do
    if [ -f "/data/.docker/$pem.pem" ] && ! head -c 20 "/data/.docker/$pem.pem" | grep -q -- '-----BEGIN'; then
      log "WARNING: $pem.pem does not start with '-----BEGIN' — check that the secret kept its line breaks"
    fi
  done
fi

if [ -n "${DOCKER_HOST:-}" ]; then
  log "sandbox daemon: $DOCKER_HOST (generated code runs in a container there)"
else
  log "no DOCKER_HOST: the sandbox falls back to the local backend and reports it as a degradation"
fi

# Memory defaults to the server in this container (step 4) — that is what a self-contained
# deployment needs, and what the image is built for. Moving it out is one secret: with
# HINDSIGHT_API_KEY set and no HINDSIGHT_BASE_URL, Hindsight Cloud is used and step 4 is
# skipped entirely. That is why the image does not preset HINDSIGHT_BASE_URL: presetting it
# would make "no URL configured" — the signal for Cloud — impossible to express, and a key
# alone would silently keep pointing at the in-container server.
if [ -n "${HINDSIGHT_API_KEY:-}" ] && [ -z "${HINDSIGHT_BASE_URL:-}" ]; then
  export HINDSIGHT_BASE_URL="https://api.hindsight.vectorize.io"
  log "HINDSIGHT_API_KEY is set: using hosted memory at $HINDSIGHT_BASE_URL"
fi
# Every path from here gives the API a concrete address: `localhost` can resolve to ::1 first,
# and a refused connection there reads as a broken memory layer rather than a missing one.
export HINDSIGHT_BASE_URL="${HINDSIGHT_BASE_URL:-http://127.0.0.1:8888}"

# No LLM key means there is nothing to reason with, so the demo falls back to re-rendering
# recorded trajectories. Those runs are labelled `simulated` end to end, and the dashboard
# reports the run mode, so the fallback is visible rather than disguised. Set
# DEMO_REPLAY_MODE=false explicitly to require live reasoning instead.
if [ -z "${DEMO_REPLAY_MODE:-}" ] && [ -z "${GROQ_API_KEY:-}" ]; then
  export DEMO_REPLAY_MODE=true
  log "GROQ_API_KEY is not set: DEMO_REPLAY_MODE=true (recorded trajectories, labelled simulated)"
fi

# ── 4. memory server ─────────────────────────────────────────────────────────
# Hindsight runs *inside this container*: a Space gets one container and no second host, and
# the agent's memory is the point of this project, so the memory layer is self-hosted rather
# than dropped. Two properties of embedded PostgreSQL shape what follows:
#   * it refuses to run as root, so the server runs as an unprivileged user;
#   * it stores its database in $HOME/.pg0, so HOME points under /data and memory survives a
#     restart — along with the embedding-model cache, which would otherwise be re-downloaded
#     on every boot.
case "$HINDSIGHT_BASE_URL" in
  *localhost* | *127.0.0.1* | *0.0.0.0*)
    if [ -z "${GROQ_API_KEY:-}" ]; then
      log "no GROQ_API_KEY: memory server skipped (Hindsight extracts memories with an LLM)"
    elif ! python -c "import hindsight" 2>/dev/null; then
      log "hindsight-all is not installed: the agent will report memory as unavailable"
    else
      # 127.0.0.1 rather than localhost: the server binds a single address, and `localhost`
      # can resolve to ::1 first, which would look like a refused connection.
      export HINDSIGHT_BASE_URL="http://127.0.0.1:8888"
      MEMORY_HOME="/data/hindsight"
      mkdir -p "$MEMORY_HOME"
      # The mount at /data belongs to root; the unprivileged server needs its own tree.
      chown -R 1000:1000 "$MEMORY_HOME"
      log "starting the memory server (first start initialises PostgreSQL and downloads its"
      log "embedding models; they are kept in $MEMORY_HOME and reused after a restart)"
      setpriv --reuid=1000 --regid=1000 --init-groups \
        env HOME="$MEMORY_HOME" \
        python scripts/start_hindsight.py --host 127.0.0.1 --port 8888 &
      MEMORY_PID=$!

      # The API waits for memory so the agent connects on its first look rather than reporting
      # a degraded memory layer for the whole session. The wait is bounded: a Space must open
      # its port in reasonable time, and if the server is slower than that the agent's own
      # retry picks it up later instead of failing the boot.
      waited=0
      while :; do
        if curl -fsS -m 2 "http://127.0.0.1:8888/version" >/dev/null 2>&1; then
          log "memory server ready after ${waited}s"
          break
        fi
        if ! kill -0 "$MEMORY_PID" 2>/dev/null; then
          log "the memory server exited during startup; continuing without memory"
          break
        fi
        if [ "$waited" -ge "${HINDSIGHT_WAIT_SECONDS:-180}" ]; then
          log "memory server still starting after ${waited}s: starting the API anyway"
          log "the agent will connect on a later check once the server answers"
          break
        fi
        sleep 5
        waited=$((waited + 5))
        if [ $((waited % 30)) -eq 0 ]; then
          log "waiting for the memory server (${waited}s)"
        fi
      done
    fi
    ;;
  *)
    log "using the configured Hindsight at $HINDSIGHT_BASE_URL (no in-container server)"
    ;;
esac

# ── 5. demo repository ───────────────────────────────────────────────────────
# The repository the agent repairs is generated from the tracked template, with real commits
# that introduce each failure. It lives in the container, not in /data, so it is rebuilt
# rather than migrated when the image changes. `--no-verify` skips the template's own
# four-suite self-check, which belongs in review rather than in a cold start.
if [ ! -d "$APP_DIR/data/demo-repo/.git" ]; then
  log "building the demo repository"
  python scripts/setup_demo_repo.py --no-verify
fi

# ── 6. serve ─────────────────────────────────────────────────────────────────
# One process serves the API and the prebuilt dashboard. Spaces expect a foreground process
# listening on $API_PORT, which FastAPI serves from web/dist with an SPA fallback.
log "starting API on ${API_HOST:-0.0.0.0}:${API_PORT:-7860}"
exec python scripts/serve.py --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-7860}"
