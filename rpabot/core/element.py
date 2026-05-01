"""Element abstraction for UI automation.

Provides a high-level wrapper around native UI elements with lazy property loading
and a comprehensive set of interaction methods.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from rpabot.core.locator import Locator


# ---------------------------------------------------------------------------
# Rectangle
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Rectangle:
    """Immutable rectangle representing a region on screen.

    Attributes:
        left: Leftmost x-coordinate.
        top: Topmost y-coordinate.
        width: Width in pixels.
        height: Height in pixels.
    """

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        """Rightmost x-coordinate (exclusive)."""
        return self.left + self.width

    @property
    def bottom(self) -> int:
        """Bottommost y-coordinate (exclusive)."""
        return self.top + self.height

    @property
    def center(self) -> tuple[int, int]:
        """Center point as (x, y)."""
        return (
            self.left + self.width // 2,
            self.top + self.height // 2,
        )

    @property
    def area(self) -> int:
        """Area in square pixels."""
        return self.width * self.height

    def contains(self, x: int, y: int) -> bool:
        """Check whether a point (x, y) lies inside this rectangle."""
        return self.left <= x < self.right and self.top <= y < self.bottom

    def overlaps(self, other: Rectangle) -> bool:
        """Check whether two rectangles overlap."""
        return (
            self.left < other.right
            and self.right > other.left
            and self.top < other.bottom
            and self.bottom > other.top
        )

    def __repr__(self) -> str:
        return (
            f"Rectangle(left={self.left}, top={self.top}, "
            f"width={self.width}, height={self.height})"
        )


# ---------------------------------------------------------------------------
# Element
# ---------------------------------------------------------------------------

class Element:
    """High-level wrapper around a native UI element.

    Provides lazy property resolution and a fluent set of interaction methods.
    The wrapped *native_element* is driver-specific (e.g. a uiautomation Control,
    a Selenium WebElement, etc.).

    All interaction methods delegate to the native element and handle common
    error translation into framework exceptions.
    """

    __slots__ = (
        "_native",
        "_locator",
        "_name",
        "_automation_id",
        "_control_type",
        "_bounding_rectangle",
        "_cached",
    )

    def __init__(
        self,
        native_element: Any,
        locator: Optional[Locator] = None,
    ) -> None:
        self._native = native_element
        self._locator = locator
        self._cached: dict[str, Any] = {}

    # -- public read-only properties via lazy resolution --------------------

    @property
    def native_element(self) -> Any:
        """The underlying driver-specific element."""
        return self._native

    @property
    def locator(self) -> Optional[Locator]:
        """Locator used to find this element (if any)."""
        return self._locator

    @property
    def name(self) -> str:
        """Human-readable name of the element."""
        return self._resolve("name", "Name", "")

    @property
    def automation_id(self) -> str:
        """Automation / accessibility identifier."""
        return self._resolve("automation_id", "AutomationId", "")

    @property
    def control_type(self) -> str:
        """Control type name (e.g. 'Button', 'Edit')."""
        return self._resolve("control_type", "ControlTypeName", "")

    @property
    def bounding_rectangle(self) -> Rectangle:
        """On-screen bounding rectangle of the element."""
        if "bounding_rectangle" not in self._cached:
            try:
                r = self._native.BoundingRectangle
                rect = Rectangle(
                    left=r.left,
                    top=r.top,
                    width=r.width,
                    height=r.height,
                )
            except AttributeError:
                rect = Rectangle(0, 0, 0, 0)
            self._cached["bounding_rectangle"] = rect
        return self._cached["bounding_rectangle"]

    # -- status checks ------------------------------------------------------

    def is_visible(self) -> bool:
        """Check whether the element is visible."""
        return self._resolve("is_visible", "IsVisible", True)

    def is_enabled(self) -> bool:
        """Check whether the element is enabled for interaction."""
        return self._resolve("is_enabled", "IsEnabled", True)

    def is_selected(self) -> bool:
        """Check whether the element is in a selected / checked state."""
        return self._resolve("is_selected", "IsSelected", False)

    # -- interaction methods ------------------------------------------------

    def click(self, *, delay: float = 0.0) -> Element:
        """Left-click the element.

        Args:
            delay: Seconds to wait after the click.
        """
        self._native.Click()
        if delay > 0:
            time.sleep(delay)
        return self

    def double_click(self, *, delay: float = 0.0) -> Element:
        """Double-click the element."""
        self._native.DoubleClick()
        if delay > 0:
            time.sleep(delay)
        return self

    def right_click(self, *, delay: float = 0.0) -> Element:
        """Right-click the element."""
        self._native.RightClick()
        if delay > 0:
            time.sleep(delay)
        return self

    def send_keys(self, text: str, *, clear_first: bool = True) -> Element:
        """Send text input to the element.

        Args:
            text: Text to send.
            clear_first: If True, clear existing content before typing.
        """
        if clear_first:
            self._native.SetValue("")
        self._native.SendKeys(text)
        return self

    def get_text(self) -> str:
        """Retrieve the text content of the element."""
        return self._resolve("text", "Name", "")

    def set_focus(self) -> Element:
        """Set keyboard focus to this element."""
        self._native.SetFocus()
        return self

    def get_property(self, name: str) -> Any:
        """Get a named property from the native element."""
        return getattr(self._native, name, None)

    # -- helpers ------------------------------------------------------------

    def _resolve(self, cache_key: str, attr_name: str, default: Any) -> Any:
        """Resolve a lazy property with caching."""
        if cache_key not in self._cached:
            try:
                self._cached[cache_key] = getattr(self._native, attr_name)
            except (AttributeError, Exception):
                self._cached[cache_key] = default
        return self._cached[cache_key]

    def invalidate_cache(self) -> None:
        """Clear the internal property cache so values are re-read."""
        self._cached.clear()

    def __repr__(self) -> str:
        return (
            f"<Element name={self.name!r} type={self.control_type!r} "
            f"id={self.automation_id!r} rect={self.bounding_rectangle}>"
        )
