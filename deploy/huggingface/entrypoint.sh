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

# ── 3. capability defaults ───────────────────────────────────────────────────
# A Space has no Docker daemon, so generated code cannot be run in the container backend.
# `local` states that plainly; `auto` would reach the same backend but also log a downgrade
# warning. The sandbox is a real isolation boundary in the documented setup, so the
# dashboard is left to report this as the degradation it is rather than hiding it.
export SANDBOX_BACKEND="${SANDBOX_BACKEND:-local}"

# Hindsight is an external service. With a key and no explicit URL, the hosted API is the
# reachable one; with neither, the default localhost URL is unreachable and /api/status
# reports memory as unavailable instead of pretending it is connected.
if [ -z "${HINDSIGHT_BASE_URL:-}" ] && [ -n "${HINDSIGHT_API_KEY:-}" ]; then
  export HINDSIGHT_BASE_URL="https://api.hindsight.vectorize.io"
  log "HINDSIGHT_API_KEY present: using hosted memory at $HINDSIGHT_BASE_URL"
fi

# No LLM key means there is nothing to reason with, so the demo falls back to re-rendering
# recorded trajectories. Those runs are labelled `simulated` end to end, and the dashboard
# reports the run mode, so the fallback is visible rather than disguised. Set
# DEMO_REPLAY_MODE=false explicitly to require live reasoning instead.
if [ -z "${DEMO_REPLAY_MODE:-}" ] && [ -z "${GROQ_API_KEY:-}" ]; then
  export DEMO_REPLAY_MODE=true
  log "GROQ_API_KEY is not set: DEMO_REPLAY_MODE=true (recorded trajectories, labelled simulated)"
fi

# ── 4. demo repository ───────────────────────────────────────────────────────
# The repository the agent repairs is generated from the tracked template, with real commits
# that introduce each failure. It lives in the container, not in /data, so it is rebuilt
# rather than migrated when the image changes. `--no-verify` skips the template's own
# four-suite self-check, which belongs in review rather than in a cold start.
if [ ! -d "$APP_DIR/data/demo-repo/.git" ]; then
  log "building the demo repository"
  python scripts/setup_demo_repo.py --no-verify
fi

# ── 5. serve ─────────────────────────────────────────────────────────────────
# One process serves the API and the prebuilt dashboard. Spaces expect a foreground process
# listening on $API_PORT, which FastAPI serves from web/dist with an SPA fallback.
log "starting API on ${API_HOST:-0.0.0.0}:${API_PORT:-7860}"
exec python scripts/serve.py --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-7860}"
