"""Tests for config loading and CLI override logic."""

import re
from pathlib import Path

import pytest

from linksanity.config import Config, ConfigError, load_config, url_is_skipped

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


class TestWronglyTypedValuesRaise:
    """A wrongly-typed value for a key must raise ConfigError naming the key
    AND the expected type, not silently fall back to the default
    (linksanity-ap7). Covers both the container keys
    (ignore_domains/js_domains/skip_urls) and the scalar helpers
    (_int/_bool/_str/_bool_or_none)."""

    def test_ignore_domains_non_list_string(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text('ignore_domains = "a-string"\n')
        with pytest.raises(ConfigError, match=r"ignore_domains.*expected a list of strings"):
            load_config(toml_path=p)

    def test_js_domains_non_list_table(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("js_domains = {a = 1}\n")
        with pytest.raises(ConfigError, match=r"js_domains.*expected a list of strings"):
            load_config(toml_path=p)

    def test_skip_urls_non_list_int(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("skip_urls = 42\n")
        with pytest.raises(ConfigError, match=r"skip_urls.*expected a list of strings"):
            load_config(toml_path=p)

    def test_int_key_given_a_list(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("workers = [1, 2]\n")
        with pytest.raises(ConfigError, match=r"workers.*expected an integer"):
            load_config(toml_path=p)

    def test_int_key_given_a_table(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("[workers]\nn = 1\n")
        with pytest.raises(ConfigError, match=r"workers.*expected an integer"):
            load_config(toml_path=p)

    def test_str_key_given_a_list(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("link_style = [1, 2]\n")
        with pytest.raises(ConfigError, match=r"link_style.*expected a string"):
            load_config(toml_path=p)

    def test_bool_key_given_a_string(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text('check_anchors = "yes"\n')
        with pytest.raises(ConfigError, match=r"check_anchors.*expected a boolean"):
            load_config(toml_path=p)

    def test_annotations_given_a_string(self, tmp_path: Path) -> None:
        """annotations goes through _bool_or_none, not _bool -- exercise it
        directly rather than relying on _bool's coverage to stand in for it."""
        p = tmp_path / "linksanity.toml"
        p.write_text('annotations = "not-a-bool"\n')
        with pytest.raises(ConfigError, match=r"annotations.*expected a boolean"):
            load_config(toml_path=p)

    def test_int_key_given_a_bare_toml_date(self, tmp_path: Path) -> None:
        """A bare TOML date (no quotes) parses to datetime.date, which is
        neither int/float/str -- _int must reject it and report the actual
        type as 'date', not silently stringify it."""
        p = tmp_path / "linksanity.toml"
        p.write_text("workers = 2026-07-31\n")
        with pytest.raises(ConfigError, match=r"workers.*expected an integer.*got date"):
            load_config(toml_path=p)

    def test_error_names_the_file(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("skip_urls = 42\n")
        with pytest.raises(ConfigError, match=str(p)):
            load_config(toml_path=p)


class TestAllKeysAbsentStillLoads:
    """A config file (or no config file at all) with every key absent must
    load defaults without error -- the type check must never fire on the
    fallback default itself."""

    def test_no_file_loads_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "nonexistent.toml")
        assert cfg == Config()

    def test_empty_file_loads_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("")
        cfg = load_config(toml_path=p)
        assert cfg == Config()

    def test_unrelated_key_present_still_loads_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("timeout = 30\n")
        cfg = load_config(toml_path=p)
        assert cfg.workers == Config.workers
        assert cfg.annotations is None


class TestAcceptedCoercionsStillWork:
    """The type-check tightening must not narrow what was already accepted --
    only close the silent-fallback hole."""

    def test_int_key_accepts_numeric_string(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text('workers = "8"\n')
        cfg = load_config(toml_path=p)
        assert cfg.workers == 8

    def test_int_key_accepts_float(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("workers = 8.0\n")
        cfg = load_config(toml_path=p)
        assert cfg.workers == 8

    def test_bool_key_accepts_int_one(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("check_anchors = 1\n")
        cfg = load_config(toml_path=p)
        assert cfg.check_anchors is True


class TestNumericRangeValidation:
    """A negative or zero value for a numeric key must raise ConfigError at
    load time instead of surfacing as a traceback deep in the run (e.g.
    Semaphore(-5)) -- see linksanity-6lm. Runs on the *effective* config, so
    it must catch both a file value and a CLI override (which bypasses the
    _int helper via a direct setattr)."""

    @pytest.mark.parametrize("key", ["workers", "playwright_workers", "timeout", "max_pages"])
    @pytest.mark.parametrize("bad_value", [0, -5])
    def test_floor_of_one_rejects_zero_and_negative(
        self, tmp_path: Path, key: str, bad_value: int
    ) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text(f"{key} = {bad_value}\n")
        with pytest.raises(ConfigError, match=rf"{key}.*must be >= 1, got {bad_value}"):
            load_config(toml_path=p)

    @pytest.mark.parametrize("key", ["retry", "max_redirects", "cache_ttl"])
    def test_floor_of_zero_rejects_negative(self, tmp_path: Path, key: str) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text(f"{key} = -1\n")
        with pytest.raises(ConfigError, match=rf"{key}.*must be >= 0, got -1"):
            load_config(toml_path=p)

    @pytest.mark.parametrize("key", ["retry", "max_redirects", "cache_ttl"])
    def test_floor_of_zero_accepts_zero(self, tmp_path: Path, key: str) -> None:
        """Regression guard: 0 is a legitimate setting for these three keys
        (no retries / don't follow redirects / always expired) -- must not
        be over-tightened to reject it."""
        p = tmp_path / "linksanity.toml"
        p.write_text(f"{key} = 0\n")
        cfg = load_config(toml_path=p)
        assert getattr(cfg, key) == 0

    def test_valid_values_still_load_unchanged(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("workers = 8\nplaywright_workers = 3\ntimeout = 15\nmax_pages = 100\n")
        cfg = load_config(toml_path=p)
        assert cfg.workers == 8
        assert cfg.playwright_workers == 3
        assert cfg.timeout == 15
        assert cfg.max_pages == 100

    def test_keys_absent_still_load_defaults(self, tmp_path: Path) -> None:
        cfg = load_config(toml_path=tmp_path / "nonexistent.toml")
        assert cfg == Config()

    def test_file_supplied_out_of_range_names_the_file(self, tmp_path: Path) -> None:
        p = tmp_path / "linksanity.toml"
        p.write_text("workers = -5\n")
        with pytest.raises(ConfigError, match=re.escape(str(p))):
            load_config(toml_path=p)

    def test_cli_supplied_out_of_range_does_not_name_a_file(self, tmp_path: Path) -> None:
        """The value came from a CLI override, not the (nonexistent) file
        load_config was pointed at -- the error must not claim a location
        that did not actually supply the value."""
        p = tmp_path / "linksanity.toml"
        with pytest.raises(ConfigError) as exc_info:
            load_config(toml_path=p, workers=-5)
        assert str(p) not in str(exc_info.value)
        assert "workers" in str(exc_info.value)
        assert "must be >= 1, got -5" in str(exc_info.value)

    def test_cli_override_wins_over_file_for_location_attribution(self, tmp_path: Path) -> None:
        """workers is invalid in the file too, but the CLI override takes
        precedence over it (existing setattr semantics) -- the effective
        value came from the CLI, so the error must not name the file even
        though the file also set this key."""
        p = tmp_path / "linksanity.toml"
        p.write_text("workers = -1\n")
        with pytest.raises(ConfigError) as exc_info:
            load_config(toml_path=p, workers=-5)
        assert str(p) not in str(exc_info.value)
        assert "got -5" in str(exc_info.value)


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
