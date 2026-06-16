"""Tests for config loading and CLI override logic."""

from pathlib import Path

import pytest

from linksanity.config import Config, load_config

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestConfigDefaults:
    def test_defaults_without_file(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "nonexistent.toml")
        assert cfg.workers == 5
        assert cfg.timeout == 10
        assert cfg.retry == 2
        assert cfg.check_anchors is False
        assert cfg.max_pages == 500
        assert cfg.ignore_domains == set()
        assert cfg.js_domains == set()
        assert cfg.format == "console"

    def test_missing_file_does_not_raise(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "missing.toml")
        assert isinstance(cfg, Config)


class TestTomlLoading:
    def test_loads_workers_and_timeout(self) -> None:
        cfg = load_config(toml_path=FIXTURES / "linksanity.toml")
        assert cfg.workers == 8
        assert cfg.timeout == 15

    def test_loads_ignore_domains_as_set(self) -> None:
        cfg = load_config(toml_path=FIXTURES / "linksanity.toml")
        assert "linkedin.com" in cfg.ignore_domains
        assert "twitter.com" in cfg.ignore_domains

    def test_loads_js_domains_as_set(self) -> None:
        cfg = load_config(toml_path=FIXTURES / "linksanity.toml")
        assert "docs.example.com" in cfg.js_domains


class TestCliOverrides:
    def test_override_replaces_file_value(self) -> None:
        cfg = load_config(toml_path=FIXTURES / "linksanity.toml", workers=2)
        assert cfg.workers == 2

    def test_none_override_does_not_replace(self) -> None:
        cfg = load_config(toml_path=FIXTURES / "linksanity.toml", workers=None)
        assert cfg.workers == 8  # file value preserved

    def test_override_on_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml", check_anchors=True)
        assert cfg.check_anchors is True

    @pytest.mark.parametrize("fmt", ["json", "csv", "console"])
    def test_format_override(self, fmt: str) -> None:
        cfg = load_config(format=fmt)
        assert cfg.format == fmt
