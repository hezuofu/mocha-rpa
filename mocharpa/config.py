"""Framework configuration — profiles, defaults, and config-file loading.

Configuration is read from a ``mocharpa.yaml`` file (or ``pyproject.toml``
``[tool.mocharpa]`` section) in the current working directory.  Profiles allow
switching between environments (e.g. ``dev``, ``prod``) with different driver /
timeout / plugin settings.

Usage::

    from mocharpa.config import load_config, get_config

    cfg = load_config("mocharpa.yaml")
    ctx = cfg.create_context(profile="prod")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ProfileConfig:
    """Per-environment settings."""

    name: str = ""
    driver: str = "mock"
    headless: bool = True
    timeout: float = 30.0
    retry_count: int = 3
    retry_delay: float = 0.5
    browser_type: str = "chromium"
    viewport_width: int = 1280
    viewport_height: int = 720
    # Plugin connection strings
    database_url: str = ""
    http_base_url: str = ""
    http_default_headers: Dict[str, str] = field(default_factory=dict)
    # Arbitrary extra data passed into pipeline as data
    env: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MocharpaConfig:
    """Top-level configuration object.

    Contains a list of named profiles and a default profile name.
    If no config file is present, sensible defaults are used.
    """

    default_profile: str = "default"
    profiles: Dict[str, ProfileConfig] = field(default_factory=dict)
    _filepath: Optional[Path] = None

    def get_profile(self, name: Optional[str] = None) -> ProfileConfig:
        """Return the named profile, or the default if *name* is None."""
        key = name or self.default_profile
        if key in self.profiles:
            return self.profiles[key]
        if key == "default" and not self.profiles:
            return ProfileConfig(name="default")
        raise KeyError(f"Profile '{key}' not found. Available: {list(self.profiles.keys())}")

    def create_context(self, profile: Optional[str] = None):
        """Build an :class:`AutomationContext` from a profile.

        Args:
            profile: Profile name (uses default if None).

        Returns:
            A ready-to-use :class:`AutomationContext` with driver connected.
        """
        from mocharpa.core.context import AutomationContext

        p = self.get_profile(profile)

        if p.driver == "mock":
            from mocharpa.drivers.mock_driver import MockDriver
            driver = MockDriver()
        elif p.driver == "playwright":
            from mocharpa.drivers.playwright_driver import PlaywrightDriver
            driver = PlaywrightDriver(
                headless=p.headless,
                browser_type=p.browser_type,
                viewport={"width": p.viewport_width, "height": p.viewport_height},
            )
        else:
            raise ValueError(f"Unknown driver: {p.driver}")

        driver.connect()
        return AutomationContext(
            timeout=p.timeout,
            retry_count=p.retry_count,
            retry_delay=p.retry_delay,
            driver=driver,
        )

    def create_plugin_manager(self, profile: Optional[str] = None):
        """Build a :class:`PluginManager` pre-loaded with configured plugins.

        Args:
            profile: Profile name.

        Returns:
            A :class:`PluginManager` with HTTP / Database plugins started.
        """
        from mocharpa.plugins.base import PluginManager

        p = self.get_profile(profile)
        mgr = PluginManager()

        if p.database_url:
            from mocharpa.plugins.database.plugin import DatabasePlugin
            db = DatabasePlugin(url=p.database_url)
            mgr.register(db)
            db.initialize(None)

        if p.http_base_url:
            from mocharpa.plugins.http.client import HTTPPlugin
            http = HTTPPlugin(
                base_url=p.http_base_url,
                default_headers=p.http_default_headers,
            )
            mgr.register(http)
            http.initialize(None)

        return mgr


# ======================================================================
# Loading
# ======================================================================

def load_config(path: Optional[str] = None) -> MocharpaConfig:
    """Load configuration from a ``mocharpa.yaml`` file.

    Search order:
        1. Explicit *path* argument.
        2. ``MOCHARPA_CONFIG`` environment variable.
        3. ``mocharpa.yaml`` in the current working directory.
        4. ``mocharpa.yml`` in the current working directory.

    Returns:
        A :class:`MocharpaConfig` (with defaults if no file is found).
    """
    try:
        import yaml
    except ImportError:
        return MocharpaConfig()

    filepath = _resolve_path(path)
    if filepath is None:
        return MocharpaConfig()

    try:
        data = yaml.safe_load(filepath.read_text(encoding="utf-8"))
    except Exception:
        return MocharpaConfig()

    if not isinstance(data, dict):
        return MocharpaConfig()

    cfg = MocharpaConfig(_filepath=filepath)
    cfg.default_profile = data.get("default_profile", "default")

    profiles_raw = data.get("profiles", {})
    for name, pdata in profiles_raw.items():
        cfg.profiles[name] = _parse_profile(name, pdata)

    # If no profiles defined, create a default from top-level keys
    if not cfg.profiles:
        cfg.profiles["default"] = _parse_profile("default", data)

    return cfg


def get_config() -> MocharpaConfig:
    """Return the cached global config, loading it if necessary.

    This is the simplest entry point for scripts::

        cfg = get_config()
        ctx = cfg.create_context("prod")
    """
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = load_config()
    return _CONFIG_CACHE


_CONFIG_CACHE: Optional[MocharpaConfig] = None


# ======================================================================
# Helpers
# ======================================================================

def _resolve_path(path: Optional[str]) -> Optional[Path]:
    if path:
        p = Path(path)
        if p.exists():
            return p
    env_path = os.environ.get("MOCHARPA_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    for name in ("mocharpa.yaml", "mocharpa.yml"):
        p = Path.cwd() / name
        if p.exists():
            return p
    return None


def _parse_profile(name: str, data: dict) -> ProfileConfig:
    """Parse a single profile from a raw dict."""
    driver_data = data.get("driver", {}) if isinstance(data.get("driver"), dict) else {}
    http_data = data.get("http", {}) if isinstance(data.get("http"), dict) else {}
    db_data = data.get("database", {}) if isinstance(data.get("database"), dict) else {}
    viewport = data.get("viewport", {}) if isinstance(data.get("viewport"), dict) else {}

    return ProfileConfig(
        name=name,
        driver=data.get("driver", "mock") if not isinstance(data.get("driver"), dict) else "mock",
        headless=data.get("headless", True) if "headless" not in driver_data else driver_data.get("headless", True),
        timeout=float(data.get("timeout", driver_data.get("timeout", 30.0))),
        retry_count=int(data.get("retry_count", 3)),
        retry_delay=float(data.get("retry_delay", 0.5)),
        browser_type=driver_data.get("browser", "chromium"),
        viewport_width=int(viewport.get("width", 1280)),
        viewport_height=int(viewport.get("height", 720)),
        database_url=db_data.get("url", data.get("database_url", "")),
        http_base_url=http_data.get("base_url", data.get("http_base_url", "")),
        http_default_headers=http_data.get("headers", {}),
        env=data.get("env", {}),
    )
