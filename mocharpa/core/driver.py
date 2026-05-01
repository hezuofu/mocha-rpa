"""Driver adapter interface — abstraction over UI automation backends.

All concrete drivers (Windows UIA, Selenium, Playwright, etc.) must implement
this interface so the core framework can operate independently of any
specific automation technology.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from mocharpa.core.element import Element
from mocharpa.core.locator import Locator
from mocharpa.core.exceptions import ElementNotFound, TimeoutError, DriverNotConnectedError


class DriverAdapter(ABC):
    """Abstract driver interface for UI automation backends.

    Lifecycle:
        driver = ConcreteDriver()
        driver.connect()
        # ... use driver ...
        driver.disconnect()

    Subclasses must implement all abstract methods.
    """

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable driver name (e.g. 'Windows UIA', 'Selenium')."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """Establish a connection to the automation backend."""

    @abstractmethod
    def disconnect(self) -> None:
        """Gracefully tear down the connection."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the driver is currently connected."""

    # ------------------------------------------------------------------
    # Element discovery
    # ------------------------------------------------------------------

    @abstractmethod
    def find_element(
        self,
        locator: Locator,
        timeout: float = 10.0,
    ) -> Optional[Element]:
        """Locate a single element matching *locator*.

        Args:
            locator: The locator to match.
            timeout: Maximum time to wait (seconds).

        Returns:
            An :class:`Element` or ``None`` if not found within *timeout*.

        Raises:
            DriverNotConnectedError: If the driver is not connected.
        """

    @abstractmethod
    def find_elements(
        self,
        locator: Locator,
        timeout: float = 10.0,
    ) -> List[Element]:
        """Locate all elements matching *locator*.

        Args:
            locator: The locator to match.
            timeout: Maximum time to wait (seconds).

        Returns:
            A list of :class:`Element` instances (may be empty).
        """

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @abstractmethod
    def capture_screenshot(self, path: Optional[str] = None) -> str:
        """Capture a screenshot.

        Args:
            path: File path to save the screenshot.  If ``None``, a
                temporary file is created.

        Returns:
            Absolute path to the screenshot file.
        """

    @abstractmethod
    def get_root_element(self) -> Element:
        """Return the desktop / page root element."""

    # ------------------------------------------------------------------
    # Convenience: polling-based wait
    # ------------------------------------------------------------------

    def wait_for_element(
        self,
        locator: Locator,
        timeout: float = 10.0,
        interval: float = 0.3,
        condition: Optional[str] = None,
    ) -> Element:
        """Poll until an element matching *locator* appears.

        Args:
            locator: The locator.
            timeout: Maximum wait time (seconds).
            interval: Polling interval (seconds).
            condition: Optional visibility condition (ignored in base impl).

        Returns:
            The found :class:`Element`.

        Raises:
            ElementNotFound: If the element does not appear within *timeout*.
        """
        if not self.is_connected:
            raise DriverNotConnectedError(self.name)

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            element = self.find_element(locator, timeout=interval)
            if element is not None:
                return element
            time.sleep(interval)

        raise ElementNotFound(
            f"Element matching {locator} not found",
            locator=locator,
            timeout=timeout,
        )


def _ensure_connected(driver: DriverAdapter) -> None:
    """Guard: raise if driver is not connected."""
    if not driver.is_connected:
        raise DriverNotConnectedError(driver.name)
