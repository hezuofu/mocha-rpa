"""HTTP client plugin for the RPA framework.

Provides a `requests`-based HTTP client that integrates with the framework's
plugin lifecycle and context caching.

Usage::

    from mocharpa.plugins.http.client import HTTPPlugin
    from mocharpa.plugins.base import PluginManager

    mgr = PluginManager(context)
    http = HTTPPlugin(base_url="https://api.example.com", default_headers={"Authorization": "Bearer ..."})
    mgr.register(http)
    mgr.start_all()

    resp = http.get("/users")
    data = http.post("/users", json={"name": "Alice"})
    mgr.shutdown_all()
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import requests

from mocharpa.plugins.base import Plugin

logger = logging.getLogger("rpa.http")

DEFAULT_TIMEOUT = 30.0


class HTTPPlugin:
    """Plugin providing HTTP request capabilities via the ``requests`` library.

    Attributes:
        name: Plugin identifier (``"http"``).
        base_url: Optional base URL prepended to all request paths.
        default_headers: Headers sent with every request.
        auth: Optional ``(username, password)`` tuple for Basic Auth.
        timeout: Default request timeout in seconds.
    """

    name = "http"

    def __init__(
        self,
        *,
        base_url: str = "",
        default_headers: Optional[Dict[str, str]] = None,
        auth: Optional[tuple[str, str]] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_count: int = 0,
        retry_backoff: float = 1.0,
        retry_on_status: Optional[tuple[int, ...]] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._default_headers = default_headers or {}
        self._auth = auth
        self._timeout = timeout
        self._retry_count = retry_count
        self._retry_backoff = retry_backoff
        self._retry_on_status = retry_on_status or (429, 500, 502, 503, 504)
        self._session: Optional[requests.Session] = None
        self._context: Any = None

    # ------------------------------------------------------------------
    # Plugin lifecycle
    # ------------------------------------------------------------------

    def initialize(self, context: Any) -> None:
        self._context = context
        self._session = requests.Session()
        if self._default_headers:
            self._session.headers.update(self._default_headers)
        if self._auth:
            self._session.auth = self._auth
        # Store in context cache for scripts to access directly
        if hasattr(context, "cache_set"):
            context.cache_set("http_session", self._session)
        logger.info("HTTPPlugin initialized (base_url=%s)", self._base_url or "/")

    def cleanup(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
        logger.info("HTTPPlugin cleaned up")

    # ------------------------------------------------------------------
    # Property
    # ------------------------------------------------------------------

    @property
    def session(self) -> requests.Session:
        """The underlying :class:`requests.Session`, for advanced usage."""
        if self._session is None:
            raise RuntimeError("HTTPPlugin not initialized")
        return self._session

    # ------------------------------------------------------------------
    # Request methods
    # ------------------------------------------------------------------

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self._base_url}{path}" if self._base_url else path

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict] = None,
        data: Any = None,
        json: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        url = self._url(path)
        t = timeout if timeout is not None else self._timeout

        last_exc: Optional[Exception] = None
        for attempt in range(self._retry_count + 1):
            try:
                resp = self.session.request(
                    method=method, url=url, params=params,
                    data=data, json=json, headers=headers, timeout=t,
                )
                logger.debug("%s %s → %d (%.2fs)", method, url, resp.status_code, resp.elapsed.total_seconds())

                if resp.status_code in self._retry_on_status and attempt < self._retry_count:
                    import time as _time
                    wait = self._retry_backoff * (2 ** attempt)
                    logger.debug("HTTP %d — retry %d/%d after %.1fs", resp.status_code, attempt + 1, self._retry_count, wait)
                    _time.sleep(wait)
                    continue

                return resp
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < self._retry_count:
                    import time as _time
                    wait = self._retry_backoff * (2 ** attempt)
                    logger.debug("HTTP %s — retry %d/%d after %.1fs", type(exc).__name__, attempt + 1, self._retry_count, wait)
                    _time.sleep(wait)
                else:
                    raise

        raise last_exc  # type: ignore[misc]

    # -- convenience wrappers -------------------------------------------------

    def get(
        self,
        path: str,
        *,
        params: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        """Send a GET request."""
        return self._request("GET", path, params=params, headers=headers, timeout=timeout)

    def post(
        self,
        path: str,
        *,
        data: Any = None,
        json: Any = None,
        params: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        """Send a POST request."""
        return self._request("POST", path, params=params, data=data, json=json, headers=headers, timeout=timeout)

    def put(
        self,
        path: str,
        *,
        data: Any = None,
        json: Any = None,
        params: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        """Send a PUT request."""
        return self._request("PUT", path, params=params, data=data, json=json, headers=headers, timeout=timeout)

    def patch(
        self,
        path: str,
        *,
        data: Any = None,
        json: Any = None,
        params: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        """Send a PATCH request."""
        return self._request("PATCH", path, params=params, data=data, json=json, headers=headers, timeout=timeout)

    def delete(
        self,
        path: str,
        *,
        params: Optional[Dict] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> requests.Response:
        """Send a DELETE request."""
        return self._request("DELETE", path, params=params, headers=headers, timeout=timeout)

    # -- JSON shortcuts -------------------------------------------------------

    def get_json(self, path: str, **kwargs: Any) -> Any:
        """GET and return parsed JSON body."""
        return self.get(path, **kwargs).json()

    def post_json(self, path: str, **kwargs: Any) -> Any:
        """POST and return parsed JSON body."""
        return self.post(path, **kwargs).json()

    # -- Session-level configuration -----------------------------------------

    def set_header(self, key: str, value: str) -> None:
        """Set a default header on the session."""
        self.session.headers[key] = value

    def set_auth(self, username: str, password: str) -> None:
        """Set Basic Auth credentials."""
        self.session.auth = (username, password)
