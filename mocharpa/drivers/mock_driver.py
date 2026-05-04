"""Mock driver for testing and development.

Provides an in-memory control tree that implements the full
:class:`~rpa.core.driver.DriverAdapter` interface without requiring
a real UI automation backend.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from mocharpa.core.driver import DriverAdapter
from mocharpa.core.element import Element, Rectangle
from mocharpa.core.locator import Locator, LocatorChain, ById, ByName, ByType, ByClass
from mocharpa.core.exceptions import ElementNotFound

logger = logging.getLogger("rpa.mock_driver")


# ======================================================================
# MockNativeElement
# ======================================================================

class MockNativeElement:
    """Lightweight, mutable object that mimics a native UI element.

    Each instance can be populated with arbitrary attributes so that
    :class:`Element` works transparently.
    """

    __slots__ = (
        "Name",
        "AutomationId",
        "ControlTypeName",
        "ClassName",
        "BoundingRectangle",
        "IsVisible",
        "IsEnabled",
        "IsSelected",
        "_children",
        "_parent",
    )

    def __init__(
        self,
        *,
        name: str = "",
        automation_id: str = "",
        control_type: str = "Custom",
        class_name: str = "",
        rect: Optional[Rectangle] = None,
        visible: bool = True,
        enabled: bool = True,
        selected: bool = False,
    ) -> None:
        self.Name = name
        self.AutomationId = automation_id
        self.ControlTypeName = control_type
        self.ClassName = class_name
        self.BoundingRectangle = rect or Rectangle(0, 0, 100, 30)
        self.IsVisible = visible
        self.IsEnabled = enabled
        self.IsSelected = selected
        self._children: List[MockNativeElement] = []
        self._parent: Optional[MockNativeElement] = None

    # -- Action stubs ------------------------------------------------------

    def Click(self) -> None:
        logger.debug("Click: name=%r id=%r", self.Name, self.AutomationId)

    def DoubleClick(self) -> None:
        logger.debug("DoubleClick: name=%r id=%r", self.Name, self.AutomationId)

    def RightClick(self) -> None:
        logger.debug("RightClick: name=%r id=%r", self.Name, self.AutomationId)

    def SendKeys(self, text: str) -> None:
        logger.debug("SendKeys(%r) to name=%r", text, self.Name)

    def SetValue(self, value: str) -> None:
        logger.debug("SetValue(%r) on name=%r", value, self.Name)

    def SetFocus(self) -> None:
        logger.debug("SetFocus: name=%r", self.Name)

    # -- Tree helpers ------------------------------------------------------

    def add_child(self, child: MockNativeElement) -> MockNativeElement:
        child._parent = self
        self._children.append(child)
        return child

    def iter_children(self, *, recursive: bool = True):
        for child in self._children:
            if recursive:
                yield from child.iter_children(recursive=True)
            yield child

    def __repr__(self) -> str:
        return f"<MockNative name={self.Name!r} id={self.AutomationId!r} type={self.ControlTypeName!r}>"


# ======================================================================
# MockDriver
# ======================================================================

class MockDriver(DriverAdapter):
    """Fully in-memory driver for testing.

    Usage::

        driver = MockDriver()
        driver.connect()

        # Build a control tree
        root = driver.root_native
        btn = root.add_child(MockNativeElement(
            name="OK", automation_id="btn_ok", control_type="Button",
        ))

        elem = driver.find_element(ByName("OK"))
        elem.click()
        driver.disconnect()
    """

    def __init__(self) -> None:
        super().__init__()
        self._connected = False
        self._root: Optional[MockNativeElement] = None

    # ------------------------------------------------------------------
    # Identity / lifecycle
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "MockDriver"

    def connect(self) -> None:
        self._connected = True
        self._root = MockNativeElement(
            name="Desktop",
            automation_id="root",
            control_type="Pane",
            rect=Rectangle(0, 0, 1920, 1080),
        )
        from mocharpa.events import DriverConnectEvent
        self._emit(DriverConnectEvent(driver_name=self.name))
        logger.info("MockDriver connected")

    def disconnect(self) -> None:
        from mocharpa.events import DriverDisconnectEvent
        self._emit(DriverDisconnectEvent(driver_name=self.name))
        self._connected = False
        self._root = None
        logger.info("MockDriver disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._root is not None

    @property
    def root_native(self) -> MockNativeElement:
        """Access the in-memory root element."""
        if not self.is_connected:
            raise RuntimeError("Driver not connected")
        return self._root  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Element discovery
    # ------------------------------------------------------------------

    def find_element(
        self,
        locator: Locator,
        timeout: float = 10.0,
    ) -> Optional[Element]:
        if not self.is_connected:
            return None
        return self._search_one(locator)

    def find_elements(
        self,
        locator: Locator,
        timeout: float = 10.0,
    ) -> List[Element]:
        if not self.is_connected:
            return []
        return self._search_all(locator)

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    def capture_screenshot(self, path: Optional[str] = None) -> str:
        dst = path or f"mock_screenshot_{uuid.uuid4().hex[:8]}.png"
        logger.debug("Mock screenshot saved to %s", dst)
        return dst

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_root_element(self) -> Element:
        if not self.is_connected:
            raise RuntimeError("Driver not connected")
        return Element(self._root)

    def inject(self, element: MockNativeElement) -> MockNativeElement:
        """Add a mock element to the tree for testing."""
        return self.root_native.add_child(element)

    def _search_one(self, locator: Locator) -> Optional[Element]:
        """Return the first matching element."""
        root = self._root
        if root is None:
            return None
        # Also check root itself
        if locator.matches(root):
            return Element(root, locator=locator)
        for child in root.iter_children(recursive=True):
            if locator.matches(child):
                return Element(child, locator=locator)
        return None

    def _search_all(self, locator: Locator) -> List[Element]:
        """Return all matching elements."""
        root = self._root
        if root is None:
            return []
        results: List[Element] = []
        if locator.matches(root):
            results.append(Element(root, locator=locator))
        for child in root.iter_children(recursive=True):
            if locator.matches(child):
                results.append(Element(child, locator=locator))
        return results
