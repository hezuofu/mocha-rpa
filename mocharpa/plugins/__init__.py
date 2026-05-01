"""Plugin exports for the RPA framework.

All plugin classes are conditionally exported — import errors are silently
suppressed when optional dependencies are not installed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Browser (Playwright)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.browser.driver import PlaywrightDriver
except ImportError:
    PlaywrightDriver = None  # type: ignore[assignment]

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
# Database (sqlalchemy)
# ---------------------------------------------------------------------------
try:
    from mocharpa.plugins.database.plugin import DatabasePlugin
except ImportError:
    DatabasePlugin = None  # type: ignore[assignment]

__all__ = [
    "PlaywrightDriver",
    "HTTPPlugin",
    "ExcelPlugin",
    "WordPlugin",
    "DatabasePlugin",
]
