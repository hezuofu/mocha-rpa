"""Integration tests using MockDriver and FindBuilder."""

import pytest
from mocharpa.core.locator import ByName, ByType, LocatorFactory
from mocharpa.core.context import AutomationContext
from mocharpa.builder.find_builder import FindBuilder, Find
from mocharpa.drivers.mock_driver import MockDriver, MockNativeElement


@pytest.fixture
def ctx():
    """Return a connected AutomationContext with MockDriver."""
    driver = MockDriver()
    driver.connect()
    context = AutomationContext(driver=driver, timeout=5)
    return context


class TestMockDriver:
    def test_connect_disconnect(self):
        d = MockDriver()
        assert not d.is_connected
        d.connect()
        assert d.is_connected
        d.disconnect()
        assert not d.is_connected

    def test_find_element(self):
        d = MockDriver()
        d.connect()
        d.inject(MockNativeElement(name="OK", automation_id="btn1"))
        d.inject(MockNativeElement(name="Cancel", automation_id="btn2"))

        el = d.find_element(ByName("OK"))
        assert el is not None
        assert el.name == "OK"

        el2 = d.find_element(ByName("NotFound"))
        assert el2 is None

    def test_find_elements(self):
        d = MockDriver()
        d.connect()
        d.inject(MockNativeElement(name="Item", automation_id="i1"))
        d.inject(MockNativeElement(name="Item", automation_id="i2"))

        results = d.find_elements(ByName("Item"))
        assert len(results) == 2


class TestFindBuilderWithMock:
    def test_basic_do(self, ctx):
        driver = ctx.driver
        driver.inject(MockNativeElement(name="Submit", control_type="Button"))

        called = []
        Find().with_context(ctx).name("Submit").do(
            lambda e: called.append(e.name)
        )
        assert called == ["Submit"]

    def test_element_not_found(self, ctx):
        with pytest.raises(Exception):
            Find().with_context(ctx).name("NoSuchThing").within(0.5).do(
                lambda e: e.click()
            )

    def test_get(self, ctx):
        driver = ctx.driver
        driver.inject(MockNativeElement(name="Target"))

        el = Find().with_context(ctx).name("Target").get()
        assert el is not None
        assert el.name == "Target"

    def test_get_all(self, ctx):
        driver = ctx.driver
        driver.inject(MockNativeElement(name="Btn"))
        driver.inject(MockNativeElement(name="Btn"))

        results = Find().with_context(ctx).name("Btn").get_all()
        assert len(results) == 2

    def test_exists(self, ctx):
        driver = ctx.driver
        driver.inject(MockNativeElement(name="Real"))
        assert Find().with_context(ctx).name("Real").exists()
        assert not Find().with_context(ctx).name("Fake").exists()

    def test_chain_locators(self, ctx):
        driver = ctx.driver
        driver.inject(
            MockNativeElement(name="OK", control_type="Button")
        )

        el = Find().with_context(ctx).name("OK").type("Button").get()
        assert el is not None

    def test_describe(self, ctx):
        desc = Find().name("X").type("Button").describe()
        assert "ByName" in desc
        assert "ByType" in desc

    def test_then_separator(self, ctx):
        """Verify .then creates a fresh builder."""
        builder = Find().name("A")
        fresh = builder.then
        # fresh should have no locators
        assert fresh._locators == ()
