"""CSV plugin for the RPA framework.

Provides CSV read/write/append operations using Python's built-in ``csv`` module,
integrated with the framework's plugin lifecycle.

Usage::

    from mocharpa.plugins.csv.plugin import CSVPlugin
    from mocharpa.plugins.base import PluginManager

    mgr = PluginManager(context)
    csv_plugin = CSVPlugin()
    mgr.register(csv_plugin)
    mgr.start_all()

    rows = csv_plugin.read("data.csv")           # list of dicts
    csv_plugin.write("out.csv", rows)
    csv_plugin.append("out.csv", [{"name": "Bob"}])
    mgr.shutdown_all()
"""

from __future__ import annotations

import csv
import logging
import os
from typing import Any, Dict, List, Optional

from mocharpa.plugins.base import Plugin

logger = logging.getLogger("rpa.csv")


class CSVPlugin:
    """Plugin for CSV file operations.

    Attributes:
        name: Plugin identifier (``"csv"``).
    """

    name = "csv"

    def __init__(self, *, default_delimiter: str = ",", encoding: str = "utf-8") -> None:
        self._default_delimiter = default_delimiter
        self._encoding = encoding
        self._context: Any = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def initialize(self, context: Any) -> None:
        self._context = context
        logger.info("CSVPlugin initialized")

    def cleanup(self) -> None:
        logger.info("CSVPlugin cleaned up")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read(
        self,
        path: str,
        *,
        delimiter: Optional[str] = None,
        as_dicts: bool = True,
    ) -> List[Dict[str, Any]]:
        """Read a CSV file.

        Args:
            path: Path to the CSV file.
            delimiter: Field delimiter (default: ``","``).
            as_dicts: If True (default), return list of dicts keyed by header row.
                If False, return list of lists.

        Returns:
            List of dicts (or lists if ``as_dicts=False``).
        """
        delim = delimiter or self._default_delimiter
        with open(path, "r", newline="", encoding=self._encoding) as f:
            if as_dicts:
                reader = csv.DictReader(f, delimiter=delim)
                return list(reader)
            else:
                reader = csv.reader(f, delimiter=delim)
                return list(reader)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(
        self,
        path: str,
        data: List[Any],
        *,
        delimiter: Optional[str] = None,
        fieldnames: Optional[List[str]] = None,
    ) -> None:
        """Write rows to a CSV file (overwrites).

        Args:
            path: Output path.
            data: List of dicts or list of lists.
            delimiter: Field delimiter.
            fieldnames: Column names (required if data is list of dicts with
                inconsistent keys, or if data is list of lists).
        """
        delim = delimiter or self._default_delimiter
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        with open(path, "w", newline="", encoding=self._encoding) as f:
            if not data:
                if fieldnames:
                    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=delim)
                    writer.writeheader()
                return

            first = data[0]
            if isinstance(first, dict):
                keys = fieldnames or list(first.keys())
                writer = csv.DictWriter(f, fieldnames=keys, delimiter=delim)
                writer.writeheader()
                writer.writerows(data)
            else:
                writer = csv.writer(f, delimiter=delim)
                if fieldnames:
                    writer.writerow(fieldnames)
                writer.writerows(data)

        logger.info("Wrote %d rows to %s", len(data), path)

    # ------------------------------------------------------------------
    # Append
    # ------------------------------------------------------------------

    def append(
        self,
        path: str,
        data: List[Any],
        *,
        delimiter: Optional[str] = None,
    ) -> None:
        """Append rows to an existing CSV file.

        If the file does not exist, it is created with a header row.

        Args:
            path: Target path.
            data: List of dicts or list of lists.
            delimiter: Field delimiter.
        """
        delim = delimiter or self._default_delimiter
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        file_exists = os.path.exists(path)

        with open(path, "a", newline="", encoding=self._encoding) as f:
            if not data:
                return

            first = data[0]
            if isinstance(first, dict):
                keys = list(first.keys())
                writer = csv.DictWriter(f, fieldnames=keys, delimiter=delim)
                if not file_exists:
                    writer.writeheader()
                writer.writerows(data)
            else:
                writer = csv.writer(f, delimiter=delim)
                writer.writerows(data)

        logger.info("Appended %d rows to %s", len(data), path)
