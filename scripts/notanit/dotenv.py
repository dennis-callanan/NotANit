"""Minimal ``.env`` loader — no external dependency.

Reads ``KEY=VALUE`` lines from a ``.env`` file into ``os.environ``. By design it
does **not** override variables already present in the real environment, so an
exported shell var always wins over the file. This lets a committed
``.env.example`` document exactly which variables are needed while a local
(gitignored) ``.env`` supplies the values.

Kept deliberately simple: one ``KEY=VALUE`` per line, ``#`` comment lines, and a
leading ``export`` are supported. Put comments on their own line rather than at
the end of a value line — trailing text is treated as part of the value.
"""

import os
from pathlib import Path


def load_dotenv(path: str | Path = ".env", *, override: bool = False) -> bool:
    """Load ``path`` into ``os.environ``. Returns True if the file existed.

    Existing environment variables are left untouched unless ``override`` is set.
    """
    p = Path(path)
    if not p.exists():
        return False

    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip a single pair of surrounding quotes, if present.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
    return True
