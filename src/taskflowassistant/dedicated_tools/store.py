"""In-memory registry for generated export files (Excel/PDF/Markdown).

Mirrors `main.py`'s `jobs` dict: a plain in-process dict keyed by a random
id, holding just enough metadata to serve and clean up a file. Fine for this
app's scale (single instance, ephemeral by design anyway — see the note in
`connection/config.py` about Render wiping disk on every redeploy); a
multi-instance deployment would need this backed by shared storage instead.

Files are meant to be one-shot: `main.py`'s `/files/{file_id}` route deletes
a file (via `release_file`) right after it finishes serving it, so a link
only works once. `_STALE_TTL_SECONDS` is only a safety net for a file that's
generated but never downloaded at all.
"""

import time
import uuid
from pathlib import Path

# Relative to the process's working directory, same convention as
# `connection/config.py`'s KNOWLEDGE_BASE_DIR ("data/knowledge_base") —
# both assume the app is run from the project root.
EXPORTS_DIR = Path("data/exports")

_STALE_TTL_SECONDS = 1800  # 30 minutes

_registry: dict[str, dict] = {}


def register_file(path: Path, filename: str) -> str:
    """Register a freshly-written file and return the id its download link should use."""
    _prune_stale()
    file_id = uuid.uuid4().hex
    _registry[file_id] = {"path": path, "filename": filename, "created_at": time.monotonic()}
    return file_id


def get_file(file_id: str) -> dict | None:
    """Look up a registered file's {"path", "filename"} by id, or None if unknown/expired."""
    return _registry.get(file_id)


def release_file(file_id: str) -> None:
    """Delete a registered file from disk and drop it from the registry.

    Called by `main.py`'s download route as a background task, right after
    the file has finished being sent to the client.
    """
    entry = _registry.pop(file_id, None)
    if entry is not None:
        entry["path"].unlink(missing_ok=True)


def _prune_stale() -> None:
    """Delete any file that was generated but never downloaded within the TTL."""
    now = time.monotonic()
    stale_ids = [file_id for file_id, entry in _registry.items() if now - entry["created_at"] > _STALE_TTL_SECONDS]
    for file_id in stale_ids:
        release_file(file_id)
