"""Tests for Element and Rectangle."""

import pytest
from mocharpa.core.element import Element, Rectangle


class TestRectangle:
    def test_basic(self):
        r = Rectangle(10, 20, 100, 50)
        assert r.left == 10
        assert r.top == 20
        assert r.width == 100
        assert r.height == 50
        assert r.right == 110
        assert r.bottom == 70
        assert r.center == (60, 45)
        assert r.area == 5000

    def test_immutable(self):
        r = Rectangle(0, 0, 10, 10)
        with pytest.raises(Exception):
            r.left = 5

    def test_contains(self):
        r = Rectangle(0, 0, 100, 100)
        assert r.contains(50, 50)
        assert not r.contains(150, 50)

    def test_overlaps(self):
        a = Rectangle(0, 0, 100, 100)
        b = Rectangle(50, 50, 100, 100)
        assert a.overlaps(b)
        c = Rectangle(200, 200, 50, 50)
        assert not a.overlaps(c)

    def test_equality(self):
        assert Rectangle(1, 2, 3, 4) == Rectangle(1, 2, 3, 4)
        assert Rectangle(1, 2, 3, 4) != Rectangle(1, 2, 3, 5)


class _FakeNative:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestElement:
    def test_basic_wrap(self):
        native = _FakeNative(
            Name="OK",
            AutomationId="btn_ok",
            ControlTypeName="Button",
            BoundingRectangle=_FakeNative(left=10, top=20, width=80, height=30),
            IsVisible=True,
            IsEnabled=True,
            IsSelected=False,
        )
        el = Element(native)

        assert el.name == "OK"
        assert el.automation_id == "btn_ok"
        assert el.control_type == "Button"
        assert el.is_visible() is True
        assert el.is_enabled() is True
        assert el.is_selected() is False

    def test_rectangle_property(self):
        native = _FakeNative(
            BoundingRectangle=_FakeNative(left=5, top=10, width=200, height=100),
        )
        el = Element(native)
        r = el.bounding_rectangle
        assert isinstance(r, Rectangle)
        assert r.left == 5
        assert r.top == 10
        assert r.width == 200
        assert r.height == 100

    def test_cache_invalidation(self):
        native = _FakeNative(Name="A", ControlTypeName="X")
        el = Element(native)
        assert el.name == "A"
        el.invalidate_cache()
        # Re-resolve
        assert el.name == "A"

    def test_methods_return_self(self):
        actions = []
        native = _FakeNative(
            Click=lambda: actions.append("click"),
            SendKeys=lambda t: actions.append(f"keys:{t}"),
            SetValue=lambda v: actions.append(f"set:{v}"),
            SetFocus=lambda: actions.append("focus"),
        )
        el = Element(native)
        result = el.click()
        assert result is el
        assert "click" in actions

        result = el.send_keys("hello")
        assert result is el
        assert "keys:hello" in actions

    def test_locator_reference(self):
        from mocharpa.core.locator import ByName

        native = _FakeNative(Name="X")
        loc = ByName("X")
        el = Element(native, locator=loc)
        assert el.locator is loc

    def test_repr(self):
        native = _FakeNative(
            Name="TestBtn",
            AutomationId="t1",
            ControlTypeName="Button",
            BoundingRectangle=_FakeNative(left=0, top=0, width=50, height=20),
        )
        el = Element(native)
        r = repr(el)
        assert "TestBtn" in r
        assert "Button" in r
