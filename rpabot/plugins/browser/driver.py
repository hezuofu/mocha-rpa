"""Playwright-based browser driver for the RPA framework.

Implements :class:`~rpa.core.driver.DriverAdapter` using Playwright as the
automation backend.  Supports Chromium (default), Firefox, and WebKit.

Usage::

    driver = PlaywrightDriver(headless=False, browser_type="chromium")
    driver.connect()
    driver.navigate("https://example.com")
    Find().name("Login").do(lambda e: e.click())
    driver.disconnect()
"""

from __future__ import annotations

import logging
import time
from typing import Any, List, Optional, Union

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
    TimeoutError as PlaywrightTimeout,
)

from rpabot.core.driver import DriverAdapter
from rpabot.core.element import Element, Rectangle
from rpabot.core.locator import (
    Locator,
    LocatorChain,
    ById,
    ByName,
    ByType,
    ByClass,
)
from rpabot.core.exceptions import (
    ElementNotFound,
    DriverError,
    DriverNotConnectedError,
)

logger = logging.getLogger("rpa.browser")

# Supported browser types
BrowserType = Union["chromium", "firefox", "webkit"]


# ======================================================================
# Selector builder
# ======================================================================

def _locator_to_selector(locator: Locator) -> str:
    """Convert an RPA locator to a Playwright selector string.

    Supported conversions:
        ById       → ``#value``
        ByName     → ``text=value`` or ``:has-text("value")``
        ByType     → tag name (e.g. ``button``, ``input``)
        ByClass    → ``.classname``
        LocatorChain → multiple selectors joined with `` >> ``

    Unknown locators fall back to ``*`` (match-all).
    """
    if isinstance(locator, LocatorChain):
        parts = [_locator_to_selector(l) for l in locator.locators]
        return " >> ".join(parts)

    if isinstance(locator, ById):
        return f"#{locator.value}"

    if isinstance(locator, ByName):
        if locator.exact:
            return f"text={locator.value}"
        return f':has-text("{locator.value}")'

    if isinstance(locator, ByType):
        return locator.value.lower()

    if isinstance(locator, ByClass):
        return f".{locator.value}"

    # Unknown — fall back to matching anything
    return "*"


# ======================================================================
# Element wrapper that delegates to Playwright locator
# ======================================================================

class _PlaywrightNative:
    """Thin wrapper around a Playwright Locator so that :class:`Element`
    can interact with it transparently."""

    __slots__ = ("_locator", "_page", "_attrs")

    def __init__(self, pw_locator, page: Page) -> None:
        self._locator = pw_locator
        self._page = page
        self._attrs: Optional[dict] = None

    def _ensure_attrs(self) -> dict:
        if self._attrs is None:
            try:
                el = self._locator.first
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                name = el.text_content() or ""
                aid = el.get_attribute("id") or el.get_attribute("data-automation-id") or ""
                class_name = el.get_attribute("class") or ""
                box = el.bounding_box()
                visible = el.is_visible()
                enabled = el.is_enabled()
            except PlaywrightTimeout:
                tag = "unknown"
                name = ""
                aid = ""
                class_name = ""
                box = None
                visible = False
                enabled = False

            self._attrs = {
                "ControlTypeName": tag,
                "Name": name,
                "AutomationId": aid,
                "ClassName": class_name,
                "BoundingRectangle": (
                    _BoxRect(box) if box else _BoxRect({"x": 0, "y": 0, "width": 0, "height": 0})
                ),
                "IsVisible": visible,
                "IsEnabled": enabled,
                "IsSelected": False,
            }
        return self._attrs

    def __getattr__(self, name: str) -> Any:
        # Action methods
        if name == "Click":
            def _click():
                self._locator.first.click()
            return _click
        if name == "DoubleClick":
            def _dblclick():
                self._locator.first.dblclick()
            return _dblclick
        if name == "RightClick":
            def _rclick():
                self._locator.first.click(button="right")
            return _rclick
        if name == "SendKeys":
            def _send(text: str):
                self._locator.first.fill(text)
            return _send
        if name == "SetValue":
            def _set(v: str):
                self._locator.first.fill(v)
            return _set
        if name == "SetFocus":
            def _focus():
                self._locator.first.focus()
            return _focus

        # Attribute access — delegate to cached attrs
        attrs = self._ensure_attrs()
        if name in attrs:
            return attrs[name]

        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")


class _BoxRect:
    """Mimic a bounding-rectangle object with left/top/width/height."""

    def __init__(self, box: dict) -> None:
        self.left = int(box.get("x", 0))
        self.top = int(box.get("y", 0))
        self.width = int(box.get("width", 0))
        self.height = int(box.get("height", 0))


# ======================================================================
# PlaywrightDriver
# ======================================================================

class PlaywrightDriver(DriverAdapter):
    """Browser automation driver backed by Playwright.

    Args:
        headless: Run browser without a visible UI.
        browser_type: ``"chromium"``, ``"firefox"``, or ``"webkit"``.
        viewport: Browser viewport size ``{"width": 1280, "height": 720}``.
        user_data_dir: Optional path for persistent browser profile.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        browser_type: str = "chromium",
        viewport: Optional[dict] = None,
        user_data_dir: Optional[str] = None,
    ) -> None:
        self._headless = headless
        self._browser_type = browser_type
        self._viewport = viewport or {"width": 1280, "height": 720}
        self._user_data_dir = user_data_dir

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return f"Playwright/{self._browser_type}"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        logger.info("Starting Playwright browser (%s, headless=%s)", self._browser_type, self._headless)
        self._playwright = sync_playwright().start()

        launcher = getattr(self._playwright, self._browser_type)
        if self._user_data_dir:
            self._context = launcher.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                headless=self._headless,
                viewport=self._viewport,
            )
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        else:
            self._browser = launcher.launch(headless=self._headless)
            self._context = self._browser.new_context(viewport=self._viewport)
            self._page = self._context.new_page()

    def disconnect(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        logger.info("Playwright browser disconnected")

    @property
    def is_connected(self) -> bool:
        return self._page is not None and not self._page.is_closed()

    # ------------------------------------------------------------------
    # Browser-specific navigation
    # ------------------------------------------------------------------

    def navigate(self, url: str, *, wait_until: str = "domcontentloaded") -> None:
        """Navigate the current page to *url*.

        Args:
            url: Target URL.
            wait_until: ``"load"``, ``"domcontentloaded"``, or ``"networkidle"``.
        """
        self._ensure_page()
        self._page.goto(url, wait_until=wait_until)

    def execute_js(self, code: str, *args: Any) -> Any:
        """Execute JavaScript in the page context."""
        self._ensure_page()
        return self._page.evaluate(code, *args)

    @property
    def current_url(self) -> str:
        """Return the current page URL."""
        self._ensure_page()
        return self._page.url

    @property
    def title(self) -> str:
        """Return the current page title."""
        self._ensure_page()
        return self._page.title()

    # ------------------------------------------------------------------
    # Exposed Playwright objects for advanced usage
    # ------------------------------------------------------------------

    @property
    def page(self) -> Page:
        """The raw Playwright :class:`Page` instance."""
        self._ensure_page()
        return self._page

    @property
    def context(self) -> BrowserContext:
        """The raw Playwright :class:`BrowserContext`."""
        if not self._context:
            raise DriverNotConnectedError(self.name)
        return self._context

    # ------------------------------------------------------------------
    # DriverAdapter — element discovery
    # ------------------------------------------------------------------

    def find_element(
        self,
        locator: Locator,
        timeout: float = 10.0,
    ) -> Optional[Element]:
        self._ensure_page()
        selector = _locator_to_selector(locator)
        try:
            pw_loc = self._page.locator(selector)
            count = pw_loc.count()
            if count == 0:
                return None
            native = _PlaywrightNative(pw_loc, self._page)
            return Element(native, locator=locator)
        except PlaywrightTimeout:
            return None
        except Exception as exc:
            logger.debug("find_element failed: %s", exc)
            return None

    def find_elements(
        self,
        locator: Locator,
        timeout: float = 10.0,
    ) -> List[Element]:
        self._ensure_page()
        selector = _locator_to_selector(locator)
        try:
            pw_loc = self._page.locator(selector)
            count = pw_loc.count()
            results: List[Element] = []
            for i in range(count):
                single = pw_loc.nth(i)
                native = _PlaywrightNative(single, self._page)
                results.append(Element(native, locator=locator))
            return results
        except PlaywrightTimeout:
            return []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    def capture_screenshot(self, path: Optional[str] = None) -> str:
        self._ensure_page()
        import uuid

        dst = path or f"screenshot_{uuid.uuid4().hex[:8]}.png"
        self._page.screenshot(path=dst, full_page=False)
        return dst

    # ------------------------------------------------------------------
    # Root element
    # ------------------------------------------------------------------

    def get_root_element(self) -> Element:
        self._ensure_page()
        native = _PlaywrightNative(self._page.locator("body"), self._page)
        return Element(native)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_page(self) -> None:
        if not self.is_connected:
            raise DriverNotConnectedError(self.name)
