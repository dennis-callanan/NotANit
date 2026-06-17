# NotANit — minimal image.
#
# The config file and the target repo are provided at RUN time via volume mounts;
# secret values are injected via `--env-file` (so they never enter the image).
#
# Build:
#   docker build -t notanit .
#
# Run (see README for details):
#   docker run --rm --env-file .env \
#     -v "$PWD/config.yaml:/app/config.yaml:ro" \
#     -v "/path/to/target-repo:/repo" \
#     notanit
#
# with `pipeline.repo_root: /repo` in config.yaml. Proposals are written to
# /repo/proposals, which appears in the mounted repo on the host.

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code only — config.yaml / .env / the target repo are mounted at runtime.
COPY scripts ./scripts

# Run as a non-root user; /repo is where the target repo is expected to be mounted.
RUN useradd --create-home --uid 1000 notanit
USER notanit

ENTRYPOINT ["python", "-m", "scripts.notanit.main"]
CMD ["--config", "/app/config.yaml"]
