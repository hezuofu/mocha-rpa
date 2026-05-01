"""Custom exception hierarchy for the RPA framework."""

from typing import Optional


class RPABaseError(Exception):
    """Base exception for all RPA framework errors."""

    def __init__(self, message: str = "", *, cause: Optional[Exception] = None):
        super().__init__(message)
        self.cause = cause

    def __str__(self) -> str:
        base = super().__str__()
        if self.cause:
            return f"{base} [Caused by: {type(self.cause).__name__}: {self.cause}]"
        return base


class ElementNotFound(RPABaseError):
    """Raised when a UI element cannot be found within the given timeout."""

    def __init__(
        self,
        message: str = "Element not found",
        *,
        locator: Optional[object] = None,
        timeout: Optional[float] = None,
        cause: Optional[Exception] = None,
    ):
        if locator is not None:
            message = f"{message}: {locator}"
        if timeout is not None:
            message = f"{message} (timeout: {timeout}s)"
        super().__init__(message, cause=cause)


class ActionNotPossible(RPABaseError):
    """Raised when a requested action cannot be performed on an element."""

    def __init__(
        self,
        message: str = "Action not possible",
        *,
        action: Optional[str] = None,
        element: Optional[object] = None,
        cause: Optional[Exception] = None,
    ):
        if action is not None:
            message = f"{message}: {action}"
        if element is not None:
            message = f"{message} on {element}"
        super().__init__(message, cause=cause)


class TimeoutError(RPABaseError):
    """Raised when a wait condition times out."""

    def __init__(
        self,
        message: str = "Operation timed out",
        *,
        timeout: Optional[float] = None,
        cause: Optional[Exception] = None,
    ):
        if timeout is not None:
            message = f"{message} (timeout: {timeout}s)"
        super().__init__(message, cause=cause)


class DriverError(RPABaseError):
    """Raised when the underlying automation driver encounters an error."""

    def __init__(
        self,
        message: str = "Driver error",
        *,
        driver_name: Optional[str] = None,
        cause: Optional[Exception] = None,
    ):
        if driver_name is not None:
            message = f"[{driver_name}] {message}"
        super().__init__(message, cause=cause)


class DriverNotConnectedError(DriverError):
    """Raised when attempting to use a driver that is not connected."""

    def __init__(self, driver_name: str = "unknown"):
        super().__init__(
            f"Driver '{driver_name}' is not connected. Call connect() first.",
            driver_name=driver_name,
        )


class ConfigurationError(RPABaseError):
    """Raised for invalid framework configuration."""

    pass
