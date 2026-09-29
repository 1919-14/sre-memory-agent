#!/usr/bin/env bash
#
# Publish the current working tree to a Hugging Face Docker Space.
#
#   SPACE=vssksn/sre-memory-agent HF_TOKEN=hf_xxx bash deploy/huggingface/sync.sh
#
# Why a snapshot instead of `git push origin main`: a Space is a public, permanent artifact,
# so it should hold the deployable tree and nothing else — no environment file, no generated
# database, no virtualenv, no history of large binaries. This builds one commit from the
# working tree and forces it onto the Space's branch.
#
# The commit is assembled through a temporary git index (`GIT_INDEX_FILE`), so HEAD, the real
# index and the working tree are never touched: publishing cannot lose uncommitted work, and
# the source repository is left exactly as it was found.
#
# The files that make the Space runnable (Dockerfile, entrypoint.sh, README.md) live next to
# this script and are copied to the snapshot root, because a Space only looks for them at its
# repository root. That keeps this repository's own README from being overwritten by the
# Space card.
#
# Environment:
#   SPACE            owner/name of the Space       (default: vssksn/sre-memory-agent)
#   HF_TOKEN         write token for the Space     (required for an https target)
#   HF_BRANCH        branch to publish to          (default: main)
#   HF_SPACE_URL     full git remote URL           (default: https://huggingface.co/spaces/$SPACE)
#   HF_GIT_USER      user part of the remote URL   (default: the Space's owner)
#   ALLOW_DIRTY=1    publish with uncommitted changes present
#   ALLOW_LARGE=1    publish a file larger than the 10 MiB guard
#   PUBLISH_SCREENSHOTS=1  publish the dashboard screenshots with the Space (default: no)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

SPACE="${SPACE:-vssksn/sre-memory-agent}"
HF_BRANCH="${HF_BRANCH:-main}"
HF_SPACE_URL="${HF_SPACE_URL:-https://huggingface.co/spaces/$SPACE}"
HF_GIT_USER="${HF_GIT_USER:-${SPACE%%/*}}"
SPACE_FILES=(deploy/huggingface/Dockerfile deploy/huggingface/entrypoint.sh deploy/huggingface/README.md)

log() { printf '[hf-sync] %s\n' "$*"; }
die() { printf '[hf-sync] error: %s\n' "$*" >&2; exit 1; }

for file in "${SPACE_FILES[@]}"; do
  [ -f "$file" ] || die "$file is missing (run this from the repository)."
done

# ── preflight ────────────────────────────────────────────────────────────────
git rev-parse --git-dir >/dev/null 2>&1 || die "$REPO_ROOT is not a git repository."

case "$HF_SPACE_URL" in
  http*)
    [ -n "${HF_TOKEN:-}" ] || die "HF_TOKEN is not set (required to publish to $HF_SPACE_URL)."
    ;;
esac

# The dashboard is a build artefact and is gitignored, so it only exists once it has been
# built. Publishing without it would deploy an API with no user interface.
[ -f web/dist/index.html ] || die "web/dist/index.html is missing. Build the dashboard first:
    cd web && npm ci && npm run build"

# Not a safety guard — the snapshot is built from the working tree either way, so nothing can
# be lost. It is here so a half-finished change is not published to a public Space by accident.
if [ -n "$(git status --porcelain --untracked-files=no)" ] && [ "${ALLOW_DIRTY:-0}" != "1" ]; then
  die "the working tree has uncommitted changes. Commit or stash them first,
    or re-run with ALLOW_DIRTY=1 to publish exactly what is on disk."
fi

log "publishing the working tree to $HF_SPACE_URL ($HF_BRANCH)"

# A clean checkout (CI) publishes only tracked files. A local run can also publish files that
# are not committed yet — including a stray one nobody meant to ship — so name them rather
# than letting the Space be the first place they show up.
untracked="$(git ls-files --others --exclude-standard | head -5 || true)"
if [ -n "$untracked" ]; then
  untracked_count="$(git ls-files --others --exclude-standard | wc -l | tr -d ' ')"
  log "note: $untracked_count file(s) are not tracked by git and will be published as-is:"
  printf '%s\n' "$untracked" | while read -r path; do printf '[hf-sync]   %s\n' "$path"; done
fi

# ── staging area for the snapshot ────────────────────────────────────────────
# A private index and — for an https target — a private credential file. Neither outlives
# this script. The token goes in the credential helper rather than in the remote URL so that
# a failed push cannot print it into a build log.
export GIT_INDEX_FILE
GIT_INDEX_FILE="$(mktemp)"
# git refuses to read a zero-byte index, so let it create the file itself.
rm -f "$GIT_INDEX_FILE"
CRED_FILE="$(mktemp)"
chmod 600 "$CRED_FILE"
trap 'rm -f "$GIT_INDEX_FILE" "$CRED_FILE"' EXIT

git read-tree --empty
git add -A
# Build artefact (gitignored) and the recorded trajectories the replay path re-renders.
git add -f web/dist
[ -d data/runs ] && git add -f data/runs
# Continuous integration belongs to the source repository, not to the deployment snapshot.
git rm -r -q --cached .github 2>/dev/null || true

# The dashboard screenshots are binaries, and the Space does not need to carry them: the landing
# page reads them from this repository instead (see web/src/lib/site.ts). `web/dist` is force-added
# above, so the copies Vite made of them have to go too — otherwise the same bytes would be
# smuggled into the snapshot through the build artefact.
if [ "${PUBLISH_SCREENSHOTS:-0}" != "1" ]; then
  git rm -r -q --cached --ignore-unmatch web/public/screenshots web/dist/screenshots >/dev/null 2>&1 || true
  log "screenshots excluded from the snapshot (PUBLISH_SCREENSHOTS=1 includes them)"
fi

# Space metadata lives at the snapshot root. These are injected straight into the snapshot
# index — the working tree is never written to, so this repository's own README.md and root
# stay exactly as they are. Order matters: this runs after `git add -A` so it replaces the
# staged README.md rather than being replaced by it.
add_snapshot_file() {  # add_snapshot_file <source> <path in snapshot> [mode]
  local src="$1" dest="$2" mode="${3:-100644}" blob
  [ -f "$src" ] || die "$src is missing."
  # Normalise to LF: a CRLF entrypoint.sh fails on the Space with "command not found", and
  # the snapshot should be byte-identical whichever platform published it.
  blob="$(tr -d '\r' <"$src" | git hash-object -w --stdin)"
  git update-index --add --cacheinfo "$mode,$blob,$dest"
}

add_snapshot_file deploy/huggingface/Dockerfile Dockerfile
add_snapshot_file deploy/huggingface/entrypoint.sh entrypoint.sh 100755
add_snapshot_file deploy/huggingface/README.md README.md

# ── guard rails ──────────────────────────────────────────────────────────────
# A Space is public by default and its history is permanent: a credential or a generated
# database published here is not something a later commit can undo.
staged_secrets="$(git diff --cached --name-only \
  | grep -E '(^|/)\.env$|(^|/)\.env\.local$|(^|/)\.env\..*\.local$|\.pem$|\.key$|(^|/)secrets\.json$' || true)"
[ -z "$staged_secrets" ] || die "refusing to publish credentials:
$staged_secrets"

# Sized from the index, not from disk: the Space files are injected into the index and have
# no working-tree copy to measure, and what gets published is the index either way.
staged_big="$(git ls-files -s | while IFS=$'\t' read -r meta path; do
  oid="${meta#* }"; oid="${oid%% *}"
  size="$(git cat-file -s "$oid" 2>/dev/null || echo 0)"
  [ "$size" -gt 10485760 ] && printf '  %s (%s MiB)\n' "$path" "$((size / 1048576))"
done || true)"
if [ -n "$staged_big" ] && [ "${ALLOW_LARGE:-0}" != "1" ]; then
  die "refusing to publish files larger than 10 MiB:
$staged_big
    Re-run with ALLOW_LARGE=1 if that is intended."
fi

# ── commit ───────────────────────────────────────────────────────────────────
# The identity is passed per-commit rather than written into this repository's git config.
tree="$(git write-tree)"
source_ref="${GITHUB_SHA:-$(git rev-parse HEAD)}"
commit="$(GIT_AUTHOR_NAME="sre-memory-agent" GIT_AUTHOR_EMAIL="sre-memory-agent@users.noreply.github.com" \
  GIT_COMMITTER_NAME="sre-memory-agent" GIT_COMMITTER_EMAIL="sre-memory-agent@users.noreply.github.com" \
  git commit-tree "$tree" -m "deploy: SRE Memory Agent snapshot from ${source_ref:0:12}")"

count="$(git ls-tree -r --name-only "$tree" | wc -l | tr -d ' ')"
log "snapshot $commit: $count files"
git ls-tree -r "$tree" | awk '{print $3, $4}' | while read -r oid path; do
  printf '%s %s\n' "$(git cat-file -s "$oid")" "$path"
done | sort -rn | head -5 | while read -r size path; do
  printf '[hf-sync]   largest: %6s KiB  %s\n' "$((size / 1024))" "$path"
done
if [ -n "${GITHUB_SERVER_URL:-}" ]; then
  log "source commit: ${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/commit/$source_ref"
fi

# ── push ─────────────────────────────────────────────────────────────────────
case "$HF_SPACE_URL" in
  http*)
    printf 'https://%s:%s@%s\n' "$HF_GIT_USER" "$HF_TOKEN" "${HF_SPACE_URL#http*://}" >"$CRED_FILE"
    git -c credential.helper="store --file=$CRED_FILE" \
      push --force --quiet "$HF_SPACE_URL" "$commit:refs/heads/$HF_BRANCH"
    ;;
  *)
    git push --force --quiet "$HF_SPACE_URL" "$commit:refs/heads/$HF_BRANCH"
    ;;
esac

log "published to https://huggingface.co/spaces/$SPACE"
log "the Space rebuilds the image from this commit, then logs '[entrypoint] starting API'."
