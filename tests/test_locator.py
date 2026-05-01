"""Tests for the locator system."""

import pytest
from rpabot.core.locator import (
    Locator,
    ById,
    ByName,
    ByType,
    ByClass,
    ByRegion,
    ByImage,
    LocatorChain,
    LocatorFactory,
)
from rpabot.core.element import Rectangle


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _FakeElement:
    def __init__(self, **attrs):
        for k, v in attrs.items():
            setattr(self, k, v)


# ===========================================================================
# Concrete locators
# ===========================================================================

class TestById:
    def test_matches(self):
        el = _FakeElement(AutomationId="btn_ok")
        assert ById("btn_ok").matches(el)
        assert not ById("btn_cancel").matches(el)

    def test_serde(self):
        d = ById("x").to_dict()
        assert LocatorFactory.create(d) == ById("x")


class TestByName:
    def test_exact_match(self):
        el = _FakeElement(Name="Submit")
        assert ByName("Submit").matches(el)
        assert not ByName("submit").matches(el)

    def test_substring_match(self):
        el = _FakeElement(Name="Submit Button")
        assert ByName("submit", exact=False).matches(el)
        assert not ByName("cancel", exact=False).matches(el)

    def test_serde(self):
        d = ByName("OK", exact=False).to_dict()
        loc = LocatorFactory.create(d)
        assert isinstance(loc, ByName)
        assert loc.value == "OK"
        assert not loc.exact


class TestByType:
    def test_matches(self):
        el = _FakeElement(ControlTypeName="Button")
        assert ByType("Button").matches(el)
        assert ByType("button").matches(el)
        assert not ByType("Edit").matches(el)

    def test_string_create(self):
        loc = LocatorFactory.create("type:Button")
        assert isinstance(loc, ByType)
        assert loc.value == "Button"


class TestByClass:
    def test_matches(self):
        el = _FakeElement(ClassName="Chrome_WidgetWin_1")
        assert ByClass("Chrome_WidgetWin_1").matches(el)

    def test_serde(self):
        d = ByClass("Foo").to_dict()
        assert LocatorFactory.create(d) == ByClass("Foo")


class TestByRegion:
    def test_matches(self):
        inner = _FakeElement(
            BoundingRectangle=_FakeElement(left=10, top=10, width=50, height=50)
        )
        region = ByRegion(Rectangle(0, 0, 100, 100))
        assert region.matches(inner)

        outside = _FakeElement(
            BoundingRectangle=_FakeElement(left=200, top=200, width=10, height=10)
        )
        assert not region.matches(outside)


class TestByImage:
    def test_serde(self):
        loc = ByImage(path="/tmp/template.png", confidence=0.9)
        d = loc.to_dict()
        restored = LocatorFactory.create(d)
        assert isinstance(restored, ByImage)
        assert restored.path == "/tmp/template.png"
        assert restored.confidence == 0.9


# ===========================================================================
# LocatorChain
# ===========================================================================

class TestLocatorChain:
    def test_and_operator(self):
        c = ByName("OK") & ByType("Button")
        assert isinstance(c, LocatorChain)
        assert len(c.locators) == 2

    def test_all_match(self):
        c = ByName("OK") & ByType("Button")
        el = _FakeElement(Name="OK", ControlTypeName="Button")
        assert c.matches(el)

    def test_partial_fail(self):
        c = ByName("OK") & ByType("Edit")
        el = _FakeElement(Name="OK", ControlTypeName="Button")
        assert not c.matches(el)

    def test_min_length(self):
        with pytest.raises(ValueError):
            LocatorChain((ByName("a"),))


# ===========================================================================
# Factory
# ===========================================================================

class TestLocatorFactory:
    def test_pass_through(self):
        loc = ByName("test")
        assert LocatorFactory.create(loc) is loc

    def test_default_string_is_by_name(self):
        loc = LocatorFactory.create("OK")
        assert isinstance(loc, ByName)
        assert loc.value == "OK"

    def test_chain_string(self):
        loc = LocatorFactory.create("name:Login > type:Window")
        assert isinstance(loc, LocatorChain)
        assert len(loc.locators) == 2

    def test_dict(self):
        loc = LocatorFactory.create({"type": "id", "value": "btn1"})
        assert isinstance(loc, ById)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError):
            LocatorFactory.create("unknown:foo")

    def test_register_custom(self):
        # Register a dummy locator
        import dataclasses

        @dataclasses.dataclass(frozen=True)
        class Dummy(Locator):
            val: str = "z"

            def matches(self, el):
                return True

            def to_dict(self):
                return {"type": "dummy", "val": self.val}

            @classmethod
            def from_dict(cls, d):
                # _parse_str sends {"type": "dummy", "value": "..."}
                # to be compatible with both, check "value" first, then "val"
                return cls(val=d.get("value", d.get("val", "z")))

        LocatorFactory.register("dummy", Dummy)
        loc = LocatorFactory.create("dummy:hello")
        assert isinstance(loc, Dummy)
        assert loc.val == "hello"

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError):
            LocatorFactory.create(123)
