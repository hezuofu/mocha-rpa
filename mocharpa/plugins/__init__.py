"""Plugin system for the RPA framework.

Re-exports the :class:`Plugin` protocol and :class:`PluginManager` from
:mod:`mocharpa.plugins.base`, together with all built-in plugin classes
(conditionally imported so that missing optional dependencies are silent).
"""

from __future__ import annotations

from mocharpa.plugins.base import Plugin, PluginManager

# ---------------------------------------------------------------------------
# HTTP (requests)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.http.client import HTTPPlugin
except ImportError:
    HTTPPlugin = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Excel (openpyxl)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.excel.plugin import ExcelPlugin
except ImportError:
    ExcelPlugin = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Word (python-docx)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.word.plugin import WordPlugin
except ImportError:
    WordPlugin = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# File (builtins)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.file.plugin import FilePlugin
except ImportError:
    FilePlugin = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Queue (builtins — sqlite3)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.queue.plugin import QueuePlugin
except ImportError:
    QueuePlugin = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# CSV (builtins)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.csv.plugin import CSVPlugin
except ImportError:
    CSVPlugin = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Database (sqlalchemy)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.database.plugin import DatabasePlugin
except ImportError:
    DatabasePlugin = None  # type: ignore[assignment]

__all__ = [
    "Plugin",
    "PluginManager",
    "HTTPPlugin",
    "ExcelPlugin",
    "WordPlugin",
    "CSVPlugin",
    "DatabasePlugin",
    "FilePlugin",
    "QueuePlugin",
]
