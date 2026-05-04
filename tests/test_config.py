"""Tests for config/profile system."""

import tempfile
from pathlib import Path
from mocharpa.config import MocharpaConfig, ProfileConfig, load_config, get_config


class TestProfileConfig:
    def test_defaults(self):
        p = ProfileConfig(name="test")
        assert p.name == "test"
        assert p.driver == "mock"
        assert p.timeout == 30.0


class TestMocharpaConfig:
    def test_get_default_profile_when_empty(self):
        cfg = MocharpaConfig()
        p = cfg.get_profile()
        assert p.name == "default"
        assert p.driver == "mock"

    def test_get_named_profile(self):
        cfg = MocharpaConfig()
        cfg.profiles["default"] = ProfileConfig(name="default", driver="mock")
        cfg.profiles["prod"] = ProfileConfig(name="prod", driver="playwright", timeout=60.0)
        p = cfg.get_profile("prod")
        assert p.driver == "playwright"
        assert p.timeout == 60.0

    def test_get_missing_profile_raises(self):
        cfg = MocharpaConfig()
        import pytest
        with pytest.raises(KeyError):
            cfg.get_profile("nonexistent")

    def test_create_mock_context(self):
        cfg = MocharpaConfig()
        cfg.profiles["default"] = ProfileConfig(name="default", driver="mock", timeout=5.0)
        ctx = cfg.create_context("default")
        assert ctx.timeout == 5.0
        assert ctx.driver is not None
        assert ctx.driver.is_connected
        ctx.driver.disconnect()


class TestLoadConfig:
    def test_no_file_returns_defaults(self):
        cfg = load_config("/nonexistent/path.yaml")
        assert cfg.default_profile == "default"

    def test_load_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
default_profile: prod
profiles:
  default:
    driver: mock
    timeout: 10
  prod:
    driver: playwright
    timeout: 60
    headless: true
""")
            f.flush()
            cfg = load_config(f.name)
            Path(f.name).unlink()

        assert cfg.default_profile == "prod"
        assert "default" in cfg.profiles
        assert "prod" in cfg.profiles
        assert cfg.profiles["prod"].timeout == 60
        assert cfg.profiles["prod"].headless is True

    def test_load_top_level_as_default(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
driver: mock
timeout: 20
retry_count: 5
""")
            f.flush()
            cfg = load_config(f.name)
            Path(f.name).unlink()

        p = cfg.get_profile("default")
        assert p.driver == "mock"
        assert p.timeout == 20
        assert p.retry_count == 5
