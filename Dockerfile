# NotANit — minimal image.
#
# The config file and the folder holding the target docs are provided at RUN time
# via volume mounts; secret values are injected via `--env-file` (so they never
# enter the image).
#
# Build:
#   docker build -t notanit .
#
# Run (see README for details):
#   docker run --rm --env-file .env \
#     -v "$PWD/config.yaml:/app/config.yaml:ro" \
#     -v "/path/to/docs-folder:/docs" \
#     notanit
#
# with `pipeline.target_root: /docs` in config.yaml. The target doc files are edited
# in place in the mounted folder, so the changes appear on the host.

FROM python:3.12-slim

WORKDIR /app

# Install dependencies first so this layer caches across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code only — config.yaml / .env / the target docs are mounted at runtime.
COPY scripts ./scripts

# Run as a non-root user; /docs is where the target docs folder is expected to be mounted.
RUN useradd --create-home --uid 1000 notanit
USER notanit

# WORKDIR is /app, so config.yaml mounted at /app/config.yaml is found by default.
ENTRYPOINT ["python", "-m", "scripts.notanit.main"]
