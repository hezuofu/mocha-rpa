"""File-system plugin for the RPA framework.

Provides common file operations — copy, move, delete, glob, mkdir, read/write —
integrated with the framework's plugin lifecycle.

Usage::

    from mocharpa.plugins.file.plugin import FilePlugin
    from mocharpa.plugin.base import PluginManager

    mgr = PluginManager(context)
    fs = FilePlugin()
    mgr.register(fs)
    mgr.start_all()

    fs.copy("src.txt", "dst.txt")
    files = fs.glob("data/*.csv")
    content = fs.read_text("config.json")
    fs.write_text("output.txt", "hello")
    mgr.shutdown_all()
"""

from __future__ import annotations

import glob as _glob
import logging
import os
import shutil
from typing import Any, List, Optional

from mocharpa.plugins.base import Plugin

logger = logging.getLogger("rpa.file")


class FilePlugin:
    """Plugin for file-system operations.

    All paths are resolved relative to *base_dir* when provided (otherwise
    the current working directory).  Methods raise standard Python exceptions
    (``FileNotFoundError``, ``OSError``, etc.) on failure so callers can
    use :func:`mocharpa.utils.maybe` or :func:`mocharpa.flow.sequence.try_catch`
    for graceful error handling.

    Attributes:
        name: Plugin identifier (``"file"``).
        base_dir: Optional root directory prepended to all paths.
    """

    name = "file"

    def __init__(self, *, base_dir: str = "") -> None:
        self._base_dir = base_dir
        self._context: Any = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def initialize(self, context: Any) -> None:
        self._context = context
        if self._base_dir:
            os.makedirs(self._base_dir, exist_ok=True)
        logger.info("FilePlugin initialized (base_dir=%s)", self._base_dir or "cwd")

    def cleanup(self) -> None:
        logger.info("FilePlugin cleaned up")

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _path(self, p: str) -> str:
        if os.path.isabs(p) or not self._base_dir:
            return p
        return os.path.join(self._base_dir, p)

    # ------------------------------------------------------------------
    # Read / write
    # ------------------------------------------------------------------

    def read_text(self, path: str, *, encoding: str = "utf-8") -> str:
        """Read the full contents of a text file."""
        return open(self._path(path), "r", encoding=encoding).read()

    def read_bytes(self, path: str) -> bytes:
        """Read the full contents of a binary file."""
        return open(self._path(path), "rb").read()

    def write_text(
        self, path: str, content: str, *, encoding: str = "utf-8"
    ) -> None:
        """Write text to a file (overwrites).  Creates parent directories."""
        target = self._path(path)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding=encoding) as f:
            f.write(content)
        logger.info("Wrote %s (%d chars)", target, len(content))

    def write_bytes(self, path: str, content: bytes) -> None:
        """Write binary data to a file (overwrites)."""
        target = self._path(path)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "wb") as f:
            f.write(content)
        logger.info("Wrote %s (%d bytes)", target, len(content))

    def append_text(
        self, path: str, content: str, *, encoding: str = "utf-8"
    ) -> None:
        """Append text to a file."""
        target = self._path(path)
        with open(target, "a", encoding=encoding) as f:
            f.write(content)

    # ------------------------------------------------------------------
    # Copy / move / delete
    # ------------------------------------------------------------------

    def copy(self, src: str, dst: str) -> str:
        """Copy a file.  Returns the destination path."""
        s, d = self._path(src), self._path(dst)
        os.makedirs(os.path.dirname(d) or ".", exist_ok=True)
        shutil.copy2(s, d)
        logger.info("Copied %s → %s", s, d)
        return d

    def move(self, src: str, dst: str) -> str:
        """Move (rename) a file or directory.  Returns the destination path."""
        s, d = self._path(src), self._path(dst)
        os.makedirs(os.path.dirname(d) or ".", exist_ok=True)
        shutil.move(s, d)
        logger.info("Moved %s → %s", s, d)
        return d

    def delete(self, path: str) -> None:
        """Delete a file or an empty directory."""
        target = self._path(path)
        if os.path.isdir(target):
            os.rmdir(target)
        else:
            os.unlink(target)
        logger.info("Deleted %s", target)

    def rmtree(self, path: str) -> None:
        """Recursively delete a directory and its contents."""
        target = self._path(path)
        shutil.rmtree(target)
        logger.info("Removed tree %s", target)

    # ------------------------------------------------------------------
    # Directory operations
    # ------------------------------------------------------------------

    def mkdir(self, path: str, *, parents: bool = True) -> str:
        """Create a directory.  Returns the path."""
        target = self._path(path)
        os.makedirs(target, exist_ok=parents)
        logger.info("Created directory %s", target)
        return target

    def listdir(self, path: str = ".") -> List[str]:
        """List entries in a directory (names only)."""
        return os.listdir(self._path(path))

    # ------------------------------------------------------------------
    # Glob
    # ------------------------------------------------------------------

    def glob(self, pattern: str, *, recursive: bool = False) -> List[str]:
        """Return file paths matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g. ``"data/*.csv"``, ``"**/*.pdf"``).
            recursive: If True, ``**`` traverses subdirectories.
        """
        full_pattern = self._path(pattern)
        return _glob.glob(full_pattern, recursive=recursive)

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def exists(self, path: str) -> bool:
        """Return True if the path exists."""
        return os.path.exists(self._path(path))

    def is_file(self, path: str) -> bool:
        return os.path.isfile(self._path(path))

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(self._path(path))

    def size(self, path: str) -> int:
        """Return file size in bytes."""
        return os.path.getsize(self._path(path))

    def stat(self, path: str) -> dict:
        """Return file/directory metadata as a dict."""
        s = os.stat(self._path(path))
        return {
            "size": s.st_size,
            "mtime": s.st_mtime,
            "ctime": s.st_ctime,
            "is_file": os.path.isfile(self._path(path)),
            "is_dir": os.path.isdir(self._path(path)),
        }
