"""Tests for config loading and CLI override logic."""

from pathlib import Path

import pytest

from linksanity.config import Config, load_config, url_is_skipped

FIXTURES = Path(__file__).parent.parent / "fixtures"


class TestConfigDefaults:
    def test_defaults_without_file(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "nonexistent.toml")
        assert cfg.workers == 5
        assert cfg.timeout == 10
        assert cfg.retry == 2
        assert cfg.check_anchors is False
        assert cfg.check_images is False
        assert cfg.link_style is None
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

    def test_check_images_override(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml", check_images=True)
        assert cfg.check_images is True

    def test_link_style_override(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml", link_style="mkdocs")
        assert cfg.link_style == "mkdocs"

    @pytest.mark.parametrize("fmt", ["json", "csv", "console"])
    def test_format_override(self, fmt: str) -> None:
        cfg = load_config(format=fmt)
        assert cfg.format == fmt


class TestSkipUrls:
    def test_skip_urls_default_empty(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml")
        assert cfg.skip_urls == set()

    def test_skip_urls_override_with_set(self) -> None:
        patterns = {"https://example.com/auth/*", "https://staging.example.com/*"}
        cfg = load_config(skip_urls=patterns)
        assert cfg.skip_urls == patterns

    def test_skip_urls_patterns_preserved_case(self) -> None:
        patterns = {"https://Example.com/Auth/*"}
        cfg = load_config(skip_urls=patterns)
        assert "https://Example.com/Auth/*" in cfg.skip_urls


class TestBlockAnalytics:
    def test_block_analytics_default_false(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml")
        assert cfg.block_analytics is False

    def test_block_analytics_override_true(self) -> None:
        cfg = load_config(block_analytics=True)
        assert cfg.block_analytics is True

    def test_block_analytics_loads_from_toml(self) -> None:
        cfg = load_config(toml_path=FIXTURES / "linksanity.toml")
        assert cfg.block_analytics is True


class TestAnnotationsField:
    def test_defaults_to_none(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml")
        assert cfg.annotations is None

    def test_toml_true(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("annotations = true\n")
        cfg = load_config(toml_path=p)
        assert cfg.annotations is True

    def test_toml_false(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("annotations = false\n")
        cfg = load_config(toml_path=p)
        assert cfg.annotations is False

    def test_toml_absent_stays_none(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("workers = 3\n")
        cfg = load_config(toml_path=p)
        assert cfg.annotations is None

    def test_override_true(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml", annotations=True)
        assert cfg.annotations is True

    def test_override_false(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml", annotations=False)
        assert cfg.annotations is False

    def test_none_override_does_not_replace_toml_value(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("annotations = true\n")
        cfg = load_config(toml_path=p, annotations=None)
        assert cfg.annotations is True

    def test_override_replaces_toml_value(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("annotations = true\n")
        cfg = load_config(toml_path=p, annotations=False)
        assert cfg.annotations is False


class TestOfflineField:
    def test_defaults_to_false(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml")
        assert cfg.offline is False

    def test_toml_true(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("offline = true\n")
        cfg = load_config(toml_path=p)
        assert cfg.offline is True

    def test_toml_absent_stays_false(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("workers = 3\n")
        cfg = load_config(toml_path=p)
        assert cfg.offline is False

    def test_override_true(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "none.toml", offline=True)
        assert cfg.offline is True

    def test_none_override_does_not_replace_toml_value(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("offline = true\n")
        cfg = load_config(toml_path=p, offline=None)
        assert cfg.offline is True


class TestUrlIsSkipped:
    def test_exact_url_match(self) -> None:
        patterns = {"https://example.com/login", "https://example.com/admin"}
        assert url_is_skipped("https://example.com/login", patterns) is True
        assert url_is_skipped("https://example.com/admin", patterns) is True

    def test_wildcard_match(self) -> None:
        patterns = {"https://staging.example.com/*", "https://example.com/private/*"}
        assert url_is_skipped("https://staging.example.com/page", patterns) is True
        assert url_is_skipped("https://staging.example.com/a/b/c", patterns) is True
        assert url_is_skipped("https://example.com/private/api", patterns) is True

    def test_no_match(self) -> None:
        patterns = {"https://example.com/admin/*"}
        assert url_is_skipped("https://example.com/public", patterns) is False
        assert url_is_skipped("https://other.com/admin/page", patterns) is False

    def test_empty_patterns(self) -> None:
        assert url_is_skipped("https://example.com/anything", set()) is False

    def test_case_sensitive_match(self) -> None:
        patterns = {"https://Example.com/Login"}
        assert url_is_skipped("https://Example.com/Login", patterns) is True
        assert url_is_skipped("https://example.com/login", patterns) is False
