"""Tests for RPA plugins (Excel, Word, HTTP, Database)."""

import os
import tempfile

import pytest

from mocharpa.core.context import AutomationContext
from mocharpa.plugin.base import PluginManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


# ===========================================================================
# Excel
# ===========================================================================

try:
    from mocharpa.plugins.excel.plugin import ExcelPlugin

    class TestExcelPlugin:
        def test_lifecycle(self):
            excel = ExcelPlugin()
            assert excel.name == "excel"

            ctx = AutomationContext()
            excel.initialize(ctx)
            assert len(excel.list_workbooks()) == 0
            excel.cleanup()

        def test_create_save_close(self, tmp_dir):
            excel = ExcelPlugin()
            excel.initialize(AutomationContext())

            path = os.path.join(tmp_dir, "test.xlsx")
            wb = excel.create(path)
            assert len(excel.list_workbooks()) == 1

            excel.write_cell(wb, "Sheet", 1, 1, "Hello")
            excel.write_cell(wb, "Sheet", 1, 2, "World")
            excel.save(excel._key_from_path(path), path)

            excel.close(excel._key_from_path(path))
            assert len(excel.list_workbooks()) == 0

            excel.cleanup()

        def test_read_write_range(self, tmp_dir):
            excel = ExcelPlugin()
            excel.initialize(AutomationContext())

            path = os.path.join(tmp_dir, "data.xlsx")
            wb = excel.create(path)
            data = [["A1", "B1"], ["A2", "B2"]]
            excel.write_range(wb, "Sheet", 1, 1, data)
            result = excel.read_range(wb, "Sheet", (1, 1), (2, 2))
            assert result == data

            excel.close(excel._key_from_path(path))
            excel.cleanup()

except ImportError:
    pass


# ===========================================================================
# Word
# ===========================================================================

try:
    from mocharpa.plugins.word.plugin import WordPlugin

    class TestWordPlugin:
        def test_lifecycle(self):
            word = WordPlugin()
            assert word.name == "word"

            ctx = AutomationContext()
            word.initialize(ctx)
            word.cleanup()

        def test_create_and_write(self, tmp_dir):
            word = WordPlugin()
            word.initialize(AutomationContext())

            path = os.path.join(tmp_dir, "doc.docx")
            doc = word.create(path)
            word.add_heading(doc, "Test", level=1)
            word.add_paragraph(doc, "Hello world")

            text = word.get_text(doc)
            assert "Test" in text
            assert "Hello world" in text

            word.close(word._key_from_path(path))
            word.cleanup()

        def test_find_and_replace(self, tmp_dir):
            word = WordPlugin()
            word.initialize(AutomationContext())

            doc = word.create()
            word.add_paragraph(doc, "Hello {name}, welcome!")
            count = word.find_and_replace(doc, "{name}", "Alice")
            assert count > 0

            word.cleanup()

except ImportError:
    pass


# ===========================================================================
# HTTP
# ===========================================================================

try:
    from mocharpa.plugins.http.client import HTTPPlugin

    class TestHTTPPlugin:
        def test_lifecycle(self):
            http = HTTPPlugin(base_url="https://httpbin.org")
            assert http.name == "http"

            ctx = AutomationContext()
            http.initialize(ctx)
            assert http.session is not None
            http.cleanup()

        def test_url_resolution(self):
            http = HTTPPlugin(base_url="https://httpbin.org")
            assert http._url("/get") == "https://httpbin.org/get"
            assert http._url("https://other.com/api") == "https://other.com/api"

        def test_base_url_none(self):
            http = HTTPPlugin()
            assert http._url("/get") == "/get"

except ImportError:
    pass


# ===========================================================================
# Database
# ===========================================================================

try:
    from mocharpa.plugins.database.plugin import DatabasePlugin

    class TestDatabasePlugin:
        def test_lifecycle_sqlite(self, tmp_dir):
            db_path = os.path.join(tmp_dir, "test.db")
            db = DatabasePlugin(f"sqlite:///{db_path}")
            assert db.name == "database"

            ctx = AutomationContext()
            db.initialize(ctx)
            assert db.engine is not None
            assert db.session is not None

            # Create table and insert
            db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
            db.commit()
            db.insert("users", {"name": "Alice"})
            rows = db.fetch_all("SELECT * FROM users")
            assert len(rows) == 1
            assert rows[0]["name"] == "Alice"

            db.cleanup()

        def test_insert_update_delete(self, tmp_dir):
            db_path = os.path.join(tmp_dir, "test2.db")
            db = DatabasePlugin(f"sqlite:///{db_path}")
            db.initialize(AutomationContext())

            db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
            db.commit()

            # Insert
            row = db.insert("items", {"value": "foo"})
            assert row["value"] == "foo"

            # Update
            affected = db.update("items", {"id": 1}, {"value": "bar"})
            assert affected == 1

            # Query
            rows = db.query("items", id=1)
            assert rows[0]["value"] == "bar"

            # Delete
            db.delete("items", id=1)
            assert len(db.query("items")) == 0

            db.cleanup()

        def test_transaction(self, tmp_dir):
            db_path = os.path.join(tmp_dir, "test3.db")
            db = DatabasePlugin(f"sqlite:///{db_path}")
            db.initialize(AutomationContext())

            db.execute("CREATE TABLE logs (id INTEGER PRIMARY KEY, msg TEXT)")
            db.commit()

            with db.transaction():
                db.insert("logs", {"msg": "txn1"})
                db.insert("logs", {"msg": "txn2"})

            assert len(db.query("logs")) == 2

            # Rollback on error
            try:
                with db.transaction():
                    db.insert("logs", {"msg": "txn3"})
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass

            assert len(db.query("logs")) == 2  # txn3 not committed

            # Explicit disconnect + gc to release file handle before tmp_dir cleanup
            db.disconnect()
            import gc; gc.collect()

        def test_list_tables(self, tmp_dir):
            db_path = os.path.join(tmp_dir, "test4.db")
            db = DatabasePlugin(f"sqlite:///{db_path}")
            db.initialize(AutomationContext())

            db.execute("CREATE TABLE foo (id INTEGER)")
            db.execute("CREATE TABLE bar (id INTEGER)")
            db.commit()

            tables = db.list_tables()
            assert "foo" in tables
            assert "bar" in tables

            db.cleanup()

except ImportError:
    pass
