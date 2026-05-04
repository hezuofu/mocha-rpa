"""Tests for CSV plugin."""

import tempfile
import os
from pathlib import Path
from mocharpa.plugins.csv.plugin import CSVPlugin


class TestCSVPlugin:
    def setup_method(self):
        self.plugin = CSVPlugin()
        self.tmpdir = tempfile.mkdtemp()

    def test_write_and_read_dicts(self):
        path = os.path.join(self.tmpdir, "test.csv")
        data = [
            {"name": "Alice", "age": "30"},
            {"name": "Bob", "age": "25"},
        ]
        self.plugin.write(path, data)
        rows = self.plugin.read(path)
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"
        assert rows[1]["age"] == "25"

    def test_write_and_read_lists(self):
        path = os.path.join(self.tmpdir, "test2.csv")
        data = [["a", "b"], ["c", "d"]]
        self.plugin.write(path, data, fieldnames=["col1", "col2"])
        rows = self.plugin.read(path, as_dicts=True)
        assert len(rows) == 2
        assert rows[0]["col1"] == "a"

    def test_append(self):
        path = os.path.join(self.tmpdir, "append.csv")
        self.plugin.write(path, [{"x": "1"}])
        self.plugin.append(path, [{"x": "2"}])
        rows = self.plugin.read(path)
        assert len(rows) == 2

    def test_empty_write(self):
        path = os.path.join(self.tmpdir, "empty.csv")
        self.plugin.write(path, [], fieldnames=["a", "b"])
        assert os.path.exists(path)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
