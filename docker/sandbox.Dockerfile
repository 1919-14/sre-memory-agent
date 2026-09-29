# Sandbox image for the SRE Memory Agent.
#
# Generated code is executed here and nowhere else. The container contract is fixed by
# `src/sre_agent/sandbox/backends.py`, which builds one of two commands depending on whether
# the daemon shares this filesystem:
#
#   # a daemon that can see the workspace (local Docker): mounted read-only in practice
#   docker run --rm --network none --memory 1g --cpus 2 --pids-limit 256 \
#     -v <workspace>:/workspace -w /workspace <this image> python -m pytest -q ...
#
#   # a daemon that cannot (remote DOCKER_HOST): the workspace is streamed in on stdin and
#   # extracted into an ephemeral tmpfs, never touching the daemon's disk
#   docker run -i --rm ... --tmpfs /workspace:rw,size=512m,mode=1777 -w /workspace \
#     <this image> python -c '<extract stdin, then exec>' python -m pytest -q ...
#
# Either way this image only has to provide a Python interpreter with pytest: the streamed
# archive is unpacked by that interpreter's own stdlib rather than by tar(1), which is why
# there is nothing else in here. Isolation itself (no network, resource caps, and no access
# to the host beyond what is mounted or streamed) is enforced by the `docker run` flags, not
# by anything in this file.
#
# The demo service under repair is standard-library only, so pytest is the sole dependency.
# A repository with real dependencies needs its own image; point SANDBOX_IMAGE at it rather
# than adding packages here, so the sandbox never carries more than the code needs.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir "pytest>=8,<9"

# Generated code never runs as root. `PYTHONDONTWRITEBYTECODE` plus the runner's
# `-p no:cacheprovider` mean the mounted workspace is only ever read, so this user needs no
# write permission on the host directory.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin sandbox
USER sandbox

WORKDIR /workspace

# Overridden by the runner with the exact pytest arguments for each stage. Present so the
# image is still useful when run by hand.
CMD ["python", "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]
