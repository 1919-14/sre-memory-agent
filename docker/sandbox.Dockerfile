# Sandbox image for the SRE Memory Agent.
#
# Generated code is executed here and nowhere else. The container contract is fixed by
# `src/sre_agent/sandbox/backends.py`, which runs:
#
#   docker run --rm --network none --memory 1g --cpus 2 --pids-limit 256 \
#     -v <workspace>:/workspace -w /workspace <this image> python -m pytest -q ...
#
# so this image only has to provide a Python interpreter with pytest, a writable working
# directory, and nothing else. Isolation itself (no network, resource caps, no access to
# the host beyond the mounted workspace) is enforced by the `docker run` flags above, not
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
