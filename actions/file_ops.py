"""
RIO v1 — actions/file_ops.py
Create and read text files.

create_file input format:  "filename.txt|file content here"
read_file   input format:  "filename.txt"  or  full path
"""

from pathlib import Path
from core.logger import get_logger

log = get_logger(__name__)


def _base_dir(cfg: dict) -> Path:
    """Default directory for files (from config, default ~/Desktop)."""
    raw = cfg.get("actions", {}).get("files_dir", "~/Desktop")
    return Path(raw).expanduser().resolve()


def _safe_filename(filename: str) -> str | None:
    """
    Validate a filename. Returns an error message string if unsafe, else None.
    Blocks: empty names, path traversal (../), absolute paths, shell chars.
    """
    if not filename or not filename.strip():
        return "Filename cannot be empty."
    if len(filename) > 200:
        return "Filename is too long (max 200 chars)."
    if ".." in filename:
        return "Filename cannot contain '..' (path traversal blocked)."
    if filename.startswith(("/", "\\")) or (len(filename) > 1 and filename[1] == ":"):
        return "Absolute paths are not allowed for security."
    _BAD = set('<>:"|?*\r\n\x00')
    if any(c in _BAD for c in filename):
        return "Filename contains invalid characters."
    return None  # safe


def create_file(value: str, cfg: dict) -> str:
    """
    Create a file. `value` must be "filename|content".
    If no pipe separator, creates an empty file named `value`.
    Never raises.
    """
    if "|" in value:
        filename, content = value.split("|", maxsplit=1)
    else:
        filename, content = value, ""

    filename = filename.strip()
    content  = content.strip()

    # Validate filename before touching the filesystem
    err = _safe_filename(filename)
    if err:
        log.warning(f"[GUARD] create_file: {err}")
        return f"Cannot create file: {err}"

    target = _base_dir(cfg) / filename
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        log.info(f"[FILE] Created: {target}")
        return f"Created file: {target}"
    except PermissionError:
        log.error(f"[ERROR] Permission denied: {target}")
        return f"Action failed safely: no permission to write {filename}."
    except Exception as e:
        log.error(f"[ERROR] create_file failed: {e}")
        return "Action failed safely: could not create file."


def read_file(path: str, cfg: dict) -> str:
    """
    Read a file. If path has no directory, looks in base_dir first.
    Never raises.
    """
    path = path.strip()

    # Block path traversal
    if ".." in path:
        log.warning(f"[GUARD] read_file: path traversal blocked: {path!r}")
        return "Cannot read file: path traversal ('..') is not allowed."

    target = Path(path).expanduser()

    # If just a filename, look in base_dir
    if not target.is_absolute() and not target.exists():
        target = _base_dir(cfg) / path

    if not target.exists():
        return f"File not found: {path}"

    # Only allow reading regular files, not devices/pipes/sockets
    if not target.is_file():
        log.warning(f"[GUARD] read_file: not a regular file: {target}")
        return f"Cannot read: {path} is not a regular file."

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) > 1000:
            content = content[:1000] + "\n[...truncated]"
        log.info(f"[FILE] Read: {target} ({len(content)} chars)")
        return content or "(empty file)"
    except PermissionError:
        log.error(f"[ERROR] Permission denied: {target}")
        return "Action failed safely: no permission to read that file."
    except Exception as e:
        log.error(f"[ERROR] read_file failed: {e}")
        return "Action failed safely: could not read file."
