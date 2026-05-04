"""End-to-end scenarios covering realistic RPA workflows.

All tests use MockDriver (no real browser needed) and in-memory SQLite.
Each scenario is a complete pipeline — from data extraction through
processing to final output.
"""

import os
import tempfile
from pathlib import Path

import pytest

from mocharpa import *
from mocharpa.plugins.base import PluginManager
from mocharpa.drivers.mock_driver import MockDriver, MockNativeElement
from mocharpa.builder.find_builder import FindBuilder
from mocharpa.pipeline.actions import (
    find_click, send_keys, extract_text, extract_all_texts,
    http_get, http_post,
    db_insert, db_query, db_execute,
    file_read_text, file_write_text, file_copy, file_exists, file_glob, file_mkdir,
    csv_write, csv_read,
    excel_write, excel_read,
    queue_push, queue_pop, queue_ack,
    wait_for, map_each, transform,
)
from mocharpa.plugins.database.plugin import DatabasePlugin
from mocharpa.plugins.file.plugin import FilePlugin
from mocharpa.plugins.csv.plugin import CSVPlugin
from mocharpa.plugins.queue.plugin import QueuePlugin
from mocharpa.events import (
    PipelineStartEvent, PipelineEndEvent,
    StepStartEvent, StepEndEvent, StepErrorEvent, StepSkippedEvent,
    ElementFoundEvent, ElementNotFoundEvent,
)

# ======================================================================
# Helpers
# ======================================================================

def _build_login_page(driver: MockDriver):
    """Build a mock web page with login form + data table."""
    root = driver.root_native
    page = root.add_child(MockNativeElement(
        name="LoginPage", automation_id="page", control_type="Pane",
    ))
    page.add_child(MockNativeElement(
        name="Username", automation_id="input_user", control_type="Edit",
    ))
    page.add_child(MockNativeElement(
        name="Password", automation_id="input_pass", control_type="Edit",
    ))
    page.add_child(MockNativeElement(
        name="LoginButton", automation_id="btn_login", control_type="Button",
    ))
    # Data table rows
    table = page.add_child(MockNativeElement(
        name="DataTable", automation_id="tbl_data", control_type="Table",
    ))
    for i, (name, val) in enumerate([("Alice", "100"), ("Bob", "200"), ("Eve", "300")]):
        row = table.add_child(MockNativeElement(
            name=f"Row_{i}", automation_id=f"row_{i}", control_type="DataItem",
        ))
        row.add_child(MockNativeElement(
            name=name, automation_id=f"row_{i}_name", control_type="Text",
        ))
        row.add_child(MockNativeElement(
            name=val, automation_id=f"row_{i}_val", control_type="Text",
        ))


def _make_ctx(driver=None, plugins=None):
    """Create a PipelineContext with connected MockDriver."""
    d = driver or MockDriver()
    d.connect()
    ctx = AutomationContext(driver=d)
    pctx = PipelineContext(
        driver=d, timeout=10,
        plugin_manager=plugins,
        event_bus=ctx.event_bus,
    )
    return pctx


class TestE2EScenarios:
    """Full end-to-end RPA workflow tests."""

    # ==================================================================
    # Scenario 1: Browser → Extract → Transform
    # ==================================================================

    def test_browser_extract_and_transform(self):
        """Simulate: open page → find table → extract all names → uppercase."""
        driver = MockDriver()
        _build_login_page(driver)

        pl = Pipeline("extract_transform")
        pl.step("get_names",
            lambda ctx: [el.get_text()
                         for el in FindBuilder(context=ctx)
                         .type("Text")
                         .name("Alice", exact=False)  # won't match row cells
                         .all().get_all()],
            continue_on_error=True,
        )

        # Better approach: extract by type and filter
        pl2 = Pipeline("extract_v2")
        def extract_data(ctx):
            elements = FindBuilder(context=ctx).type("DataItem").all().get_all()
            names = []
            for el in elements:
                row_children = []
                for child in el.native_element._children:
                    row_children.append(child.Name)
                names.append(row_children)
            return names

        pl2.step("extract_rows", extract_data)

        result = pl2.run(context=_make_ctx(driver))
        driver.disconnect()
        assert result.success
        rows = result.step_results["extract_rows"]
        assert len(rows) == 3
        assert rows[0] == ["Alice", "100"]

    # ==================================================================
    # Scenario 2: Multi-step login flow
    # ==================================================================

    def test_browser_login_flow(self):
        """Simulate: login → type username → type password → click login."""
        driver = MockDriver()
        _build_login_page(driver)
        ctx = _make_ctx(driver)

        pl = Pipeline("login_flow")
        pl.step("click_user", lambda c: FindBuilder(context=c)
                .id("input_user").do(lambda e: e.click()))
        pl.step("type_user", lambda c: FindBuilder(context=c)
                .id("input_user").do(lambda e: e.send_keys("admin")))
        pl.step("type_pass", lambda c: FindBuilder(context=c)
                .id("input_pass").do(lambda e: e.send_keys("secret")))
        pl.step("click_login", lambda c: FindBuilder(context=c)
                .id("btn_login").do(lambda e: e.click()))

        result = pl.run(context=ctx)
        driver.disconnect()
        assert result.success
        assert len(result.step_results) == 4

    # ==================================================================
    # Scenario 3: Browser → Database
    # ==================================================================

    def test_browser_to_database(self):
        """Simulate: scrape table → insert rows into SQLite → query back."""
        driver = MockDriver()
        _build_login_page(driver)

        db = DatabasePlugin("sqlite:///:memory:")
        mgr = PluginManager()
        mgr.register(db)
        mgr.start_all()

        # Create table
        db.execute("CREATE TABLE scraped (name TEXT, value TEXT)")

        pl = Pipeline("browser_to_db")
        # Step 1: extract rows from mock page
        def scrape_rows(ctx):
            rows = []
            for i in range(3):
                name = FindBuilder(context=ctx).name(f"Row_{i}").get()
                if name:
                    children = name.native_element._children
                    rows.append({
                        "name": children[0].Name if children else "",
                        "value": children[1].Name if len(children) > 1 else "",
                    })
            return rows

        pl.step("scrape", scrape_rows)
        # Step 2: insert each row
        def insert_rows(ctx):
            for row in ctx.previous:
                db.insert("scraped", row)
            return len(ctx.previous)
        pl.step("insert", insert_rows)
        # Step 3: query back
        pl.step("query", lambda ctx: db.fetch_all("SELECT * FROM scraped"))

        ctx = _make_ctx(driver, mgr)
        result = pl.run(context=ctx)
        driver.disconnect()

        assert result.success
        assert result.step_results["insert"] == 3
        rows = result.step_results["query"]
        assert len(rows) == 3
        assert rows[0]["name"] == "Alice"

    # ==================================================================
    # Scenario 4: Browser → File (CSV + JSON)
    # ==================================================================

    def test_browser_to_file(self):
        """Simulate: scrape data → write CSV → read back → verify."""
        driver = MockDriver()
        _build_login_page(driver)
        tmp = tempfile.mkdtemp()
        csv_path = os.path.join(tmp, "output.csv")

        fs = FilePlugin(base_dir=tmp)
        csv_pl = CSVPlugin()
        mgr = PluginManager()
        mgr.register(fs)
        mgr.register(csv_pl)
        mgr.start_all()

        pl = Pipeline("browser_to_file")
        # Step 1: scrape structured data
        def scrape(ctx):
            return [
                {"name": "Alice", "value": "100"},
                {"name": "Bob", "value": "200"},
                {"name": "Eve", "value": "300"},
            ]
        pl.step("scrape", scrape)
        # Step 2: write CSV
        pl.step("write_csv", csv_write(path=csv_path))
        # Step 3: read back
        pl.step("read_csv", csv_read(path=csv_path))
        # Step 4: verify count
        pl.step("verify", lambda ctx: len(ctx.previous))

        ctx = _make_ctx(driver, mgr)
        result = pl.run(context=ctx)
        driver.disconnect()
        mgr.shutdown_all()

        assert result.success
        assert result.step_results["verify"] == 3

    # ==================================================================
    # Scenario 5: Full pipeline (multi-plugin)
    # ==================================================================

    def test_full_pipeline_multi_plugin(self):
        """Simulate end-to-end: browser → transform → file → queue.

        Flow:
        1. Scrape rows from mock page
        2. Transform (uppercase names)
        3. Write to temp file
        4. Push results to queue
        5. Pop from queue
        6. Verify round-trip
        """
        driver = MockDriver()
        _build_login_page(driver)
        tmp = tempfile.mkdtemp()

        fs = FilePlugin(base_dir=tmp)
        q = QueuePlugin(os.path.join(tmp, "pipeline.db"))
        mgr = PluginManager()
        mgr.register(fs)
        mgr.register(q)
        mgr.start_all()

        out_path = os.path.join(tmp, "result.txt")

        pl = Pipeline("full_flow")
        # 1. Scrape
        def scrape(ctx):
            return [{"name": "Alice", "val": "100"}, {"name": "Bob", "val": "200"}]
        pl.step("scrape", scrape)
        # 2. Transform — uppercase names
        pl.step("uppercase", lambda ctx: [
            {"name": r["name"].upper(), "val": r["val"]}
            for r in ctx.previous
        ])
        # 3. Write JSON to file
        pl.step("save", lambda ctx: (
            fs.write_text(out_path, str(ctx.previous)), out_path
        )[1])
        # 4. Push each row to queue
        def push_rows(ctx):
            ids = []
            for row in ctx.step_results["uppercase"]:
                ids.append(q.push("rows", row))
            return ids
        pl.step("enqueue", push_rows)
        # 5. Pop all from queue
        def pop_all(ctx):
            results = []
            while True:
                msg = q.pop("rows")
                if msg is None:
                    break
                results.append(msg[1])
                q.ack(msg[0])
            return results
        pl.step("dequeue", pop_all)
        # 6. Verify
        pl.step("verify",
            lambda ctx: len(ctx.previous) == 3 and ctx.previous[0]["name"] == "ALICE"
        )

        ctx = _make_ctx(driver, mgr)
        result = pl.run(context=ctx)
        driver.disconnect()
        mgr.shutdown_all()

        assert result.success
        assert result.step_results["verify"] is True
        assert os.path.exists(out_path)

    # ==================================================================
    # Scenario 6: Error handling — continue_on_error + retry
    # ==================================================================

    def test_error_handling_continue_and_retry(self):
        """Test step-level and pipeline-level error strategies."""
        pl = Pipeline("error_handling")
        counter = {"attempts": 0}

        # Step 1: succeeds
        pl.step("ok_step", lambda ctx: "all good")
        # Step 2: fails but continue_on_error
        def flaky(ctx):
            counter["attempts"] += 1
            if counter["attempts"] < 3:
                raise RuntimeError("transient error")
            return "recovered"
        pl.step("flaky", flaky, max_retries=2, continue_on_error=False)
        # Step 3: should still run if step 2 recovered
        pl.step("after_flaky", lambda ctx: "done")

        result = pl.run()
        assert result.success
        assert result.step_results["after_flaky"] == "done"

    # ==================================================================
    # Scenario 7: Flow control — if/for_each in pipeline
    # ==================================================================

    def test_flow_control_branching(self):
        """Test conditional branching and loops within pipeline steps."""
        pl = Pipeline("flow_control")
        pl.step("data", lambda ctx: ["a", "b", "c", "d", "e"])
        # Filter items > 'b'
        pl.step("filtered",
            lambda ctx: [x for x in ctx.previous if x > "b"],
            condition=lambda: True,
        )
        # Map to uppercase
        pl.step("mapped", lambda ctx: [x.upper() for x in ctx.previous])

        result = pl.run()
        assert result.success
        assert result.step_results["mapped"] == ["C", "D", "E"]

    # ==================================================================
    # Scenario 8: Event capture across pipeline lifecycle
    # ==================================================================

    def test_event_capture_full_lifecycle(self):
        """Capture all events emitted during a pipeline run and verify order."""
        driver = MockDriver()
        driver.connect()
        ctx = AutomationContext(driver=driver)

        events = []
        bus = ctx.event_bus
        bus.subscribe(PipelineStartEvent, lambda e: events.append(("pipeline_start", e.pipeline_name)))
        bus.subscribe(PipelineEndEvent, lambda e: events.append(("pipeline_end", e.success)))
        bus.subscribe(StepStartEvent, lambda e: events.append(("step_start", e.step_name)))
        bus.subscribe(StepEndEvent, lambda e: events.append(("step_end", e.step_name)))
        bus.subscribe(ElementFoundEvent, lambda e: events.append(("element_found",)))
        bus.subscribe(ElementNotFoundEvent, lambda e: events.append(("element_not_found",)))

        pl = Pipeline("event_test")
        pl.step("s1", lambda c: "hello")
        pl.step("s2", lambda c: {
            "found": FindBuilder(context=c).name("Nonexistent").get(),
            "prev": c.previous,
        })

        result = pl.run(context=ctx)
        driver.disconnect()

        assert result.success
        # Verify event sequence
        assert events[0] == ("pipeline_start", "event_test")
        assert events[1] == ("step_start", "s1")
        assert events[2] == ("step_end", "s1")
        assert events[3] == ("step_start", "s2")
        assert events[4] == ("element_not_found",)
        assert events[5] == ("step_end", "s2")
        assert events[6] == ("pipeline_end", True)

    # ==================================================================
    # Scenario 9: Audit recording
    # ==================================================================

    def test_audit_recording(self):
        """Verify audit records capture step-level details."""
        pl = Pipeline("audit_test")
        pl.step("ok", lambda ctx: 42)
        pl.step("skip", lambda ctx: "nope",
                condition=lambda: False)
        pl.step("err", lambda ctx: 1 / 0,
                continue_on_error=True)

        result = pl.run(audit=True)
        assert not result.success
        audit = result.audit
        assert audit.pipeline_name == "audit_test"
        assert len(audit.step_records) == 3
        assert audit.step_records[0].status == "ok"
        assert audit.step_records[0].output == 42
        assert audit.step_records[1].status == "skipped"
        assert audit.step_records[2].status == "error"
        json_str = audit.to_json()
        assert "audit_test" in json_str

    # ==================================================================
    # Scenario 10: Large data via Ref
    # ==================================================================

    def test_large_data_ref_handoff(self):
        """Pass large data between steps using ref instead of in-memory copy."""
        pl = Pipeline("large_data")
        huge = "x" * 50_000  # 50KB string (simulate larger payload)

        # Step 1: store as ref
        def produce(ctx):
            return ctx.put_large("dataset", huge)
        pl.step("produce", produce)
        # Step 2: read from ref
        def consume(ctx):
            ref = ctx.previous
            data = ref.read_text()
            return len(data)
        pl.step("consume", consume)

        result = pl.run()
        assert result.success
        assert result.step_results["consume"] == 50_000

    # ==================================================================
    # Scenario 11: File plugin operations
    # ==================================================================

    def test_file_plugin_operations(self):
        """Test copy, move, glob, mkdir through file plugin."""
        tmp = tempfile.mkdtemp()

        fs = FilePlugin(base_dir=tmp)
        fs.initialize(None)
        mgr = PluginManager()
        mgr.register(fs)
        mgr.start_all()

        pl = Pipeline("file_ops")
        pl.step("mkdir", file_mkdir(path="subdir"))
        pl.step("write1", file_write_text(path="subdir/a.txt", content="alpha"))
        pl.step("write2", file_write_text(path="subdir/b.txt", content="beta"))
        pl.step("copy", file_copy(src="subdir/a.txt", dst="subdir/a_copy.txt"))
        pl.step("glob", file_glob(pattern="subdir/*.txt"))
        pl.step("exists", file_exists(path="subdir/a_copy.txt"))

        ctx = _make_ctx(plugins=mgr)
        result = pl.run(context=ctx)
        ctx.driver.disconnect()
        mgr.shutdown_all()

        assert result.success
        assert len(result.step_results["glob"]) == 3
        assert result.step_results["exists"] is True

    # ==================================================================
    # Scenario 12: Queue producer-consumer
    # ==================================================================

    def test_queue_producer_consumer(self):
        """Two pipelines: one produces tasks, another consumes them."""
        tmp = tempfile.mkdtemp()
        qpath = os.path.join(tmp, "work.db")
        q = QueuePlugin(qpath)
        mgr = PluginManager()
        mgr.register(q)
        mgr.start_all()

        # Producer pipeline
        producer = Pipeline("producer")
        producer.step("push_tasks", lambda ctx: [
            q.push("work", {"task": f"job_{i}", "data": i * 10})
            for i in range(5)
        ])

        # Consumer pipeline
        consumer = Pipeline("consumer")
        def consume_all(ctx):
            results = []
            while True:
                msg = q.pop("work")
                if msg is None:
                    break
                results.append(msg[1])
                q.ack(msg[0])
            return results
        consumer.step("pop_all", consume_all)

        ctx = _make_ctx(plugins=mgr)
        r1 = producer.run(context=ctx)
        r2 = consumer.run(context=ctx)
        ctx.driver.disconnect()
        mgr.shutdown_all()

        assert r1.success and r2.success
        tasks = r2.step_results["pop_all"]
        assert len(tasks) == 5
        assert tasks[0]["task"] == "job_0"
        assert tasks[4]["data"] == 40
