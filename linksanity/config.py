"""Configuration loading from linksanity.toml and CLI flags."""

from __future__ import annotations

import datetime
import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    workers: int = 5
    playwright_workers: int = 2
    timeout: int = 10
    retry: int = 2
    check_anchors: bool = False
    check_images: bool = False
    myst: bool = False
    link_style: str | None = None
    max_pages: int = 500
    ignore_domains: set[str] = field(default_factory=set)
    js_domains: set[str] = field(default_factory=set)
    skip_urls: set[str] = field(default_factory=set)
    block_analytics: bool = False
    output: str | None = None
    report: str | None = None
    github_issue: bool = False
    github_repo: str | None = None
    format: str = "console"
    max_redirects: int = 10
    cache_file: str | None = None
    cache_ttl: int = 86400
    incremental: bool = False
    since: str | None = None
    baseline: str | None = None
    annotations: bool | None = None
    offline: bool = False


class ConfigError(ValueError):
    """Raised when linksanity.toml cannot be parsed or holds an invalid value.

    Distinct from a genuine linksanity defect: this signals bad user input
    (malformed TOML syntax, a file that isn't valid UTF-8, a file that can't
    be opened, or a scalar that cannot be coerced to the type a key expects)
    so callers can report it cleanly and exit 2, rather than letting a raw
    traceback surface for what is really an invocation error.

    Subclasses ValueError for backward compatibility: load_config previously
    let tomllib.TOMLDecodeError (itself a ValueError subclass) or a plain
    ValueError escape uncaught, so an existing ``except ValueError`` around a
    library call still catches this.
    """


def url_is_skipped(url: str, patterns: set[str]) -> bool:
    """Return True if url matches any pattern in the skip_urls allowlist.

    Patterns support fnmatch wildcards: * matches any sequence of characters.
    Examples:
      https://example.com/private/page   — exact match
      https://example.com/private/*      — all pages under /private/
      https://staging.example.com/*      — entire staging site
    """
    return any(fnmatch.fnmatch(url, pattern) for pattern in patterns)


def _load_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML syntax in {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        # tomllib decodes the raw bytes itself; this fires for anything not
        # valid UTF-8 (a cp1252/latin-1 save, UTF-16, a stray non-UTF-8 byte
        # in a comment, ...). No line/column is available for this one --
        # unlike TOMLDecodeError, it's a byte-level failure, not a grammar
        # position.
        raise ConfigError(f"{path} is not valid UTF-8: {exc}") from exc
    except OSError as exc:
        # path.open() failing: permission denied, path is a directory, or a
        # (rare, racy) disappearance between the existence check and here.
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def _location(path: Path | None) -> str:
    return f" in {path}" if path is not None else ""


def _type_name(v: object) -> str:
    """Render a value's type for an error message: a short, user-legible
    label (str, int, list, table, date, ...) rather than a raw repr, which
    could dump an entire table or list into the user's terminal.
    """
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "table"
    if isinstance(v, (datetime.date, datetime.time)):
        # covers date, datetime, and time -- tomllib's three date/time types
        return "date"
    return type(v).__name__


def _int(data: dict[str, object], key: str, default: int, path: Path | None = None) -> int:
    if key not in data:
        return default
    v = data[key]
    if not isinstance(v, (int, float, str)):
        raise ConfigError(
            f"invalid value for '{key}'{_location(path)}: expected an integer, got {_type_name(v)}"
        )
    try:
        return int(v)
    except ConfigError:
        raise
    except (ValueError, OverflowError) as exc:
        location = _location(path)
        raise ConfigError(f"invalid value for '{key}'{location}: {v!r} is not a valid integer") from exc


def _bool(data: dict[str, object], key: str, default: bool, path: Path | None = None) -> bool:
    if key not in data:
        return default
    v = data[key]
    if not isinstance(v, (bool, int)):
        raise ConfigError(
            f"invalid value for '{key}'{_location(path)}: expected a boolean, got {_type_name(v)}"
        )
    return bool(v)


def _str(data: dict[str, object], key: str, default: str, path: Path | None = None) -> str:
    if key not in data:
        return default
    v = data[key]
    if not isinstance(v, str):
        raise ConfigError(
            f"invalid value for '{key}'{_location(path)}: expected a string, got {_type_name(v)}"
        )
    return v


def _bool_or_none(data: dict[str, object], key: str, path: Path | None = None) -> bool | None:
    if key not in data:
        return None
    v = data[key]
    if not isinstance(v, (bool, int)):
        raise ConfigError(
            f"invalid value for '{key}'{_location(path)}: expected a boolean, got {_type_name(v)}"
        )
    return bool(v)


def load_config(
    toml_path: Path | None = None,
    **overrides: object,
) -> Config:
    """Load config from linksanity.toml (if found) and apply CLI overrides."""
    data: dict[str, object] = {}

    search_path = toml_path or Path("linksanity.toml")
    if search_path.exists():
        data = _load_toml(search_path)

    def _domain_set(key: str) -> set[str]:
        if key not in data:
            return set()
        raw = data[key]
        if not isinstance(raw, list):
            raise ConfigError(
                f"invalid value for '{key}'{_location(search_path)}: "
                f"expected a list of strings, got {_type_name(raw)}"
            )
        return {str(d).lower() for d in raw}

    def _url_set(key: str) -> set[str]:
        if key not in data:
            return set()
        raw = data[key]
        if not isinstance(raw, list):
            raise ConfigError(
                f"invalid value for '{key}'{_location(search_path)}: "
                f"expected a list of strings, got {_type_name(raw)}"
            )
        return {str(u) for u in raw}

    cfg = Config(
        workers=_int(data, "workers", Config.workers, search_path),
        playwright_workers=_int(
            data, "playwright_workers", Config.playwright_workers, search_path
        ),
        timeout=_int(data, "timeout", Config.timeout, search_path),
        retry=_int(data, "retry", Config.retry, search_path),
        check_anchors=_bool(data, "check_anchors", Config.check_anchors, search_path),
        check_images=_bool(data, "check_images", Config.check_images, search_path),
        myst=_bool(data, "myst", Config.myst, search_path),
        link_style=_str(data, "link_style", "", search_path) or None,
        max_pages=_int(data, "max_pages", Config.max_pages, search_path),
        ignore_domains=_domain_set("ignore_domains"),
        js_domains=_domain_set("js_domains"),
        skip_urls=_url_set("skip_urls"),
        block_analytics=_bool(data, "block_analytics", Config.block_analytics, search_path),
        format=_str(data, "format", Config.format, search_path),
        max_redirects=_int(data, "max_redirects", Config.max_redirects, search_path),
        cache_file=_str(data, "cache_file", "", search_path) or None,
        cache_ttl=_int(data, "cache_ttl", Config.cache_ttl, search_path),
        incremental=_bool(data, "incremental", Config.incremental, search_path),
        since=_str(data, "since", "", search_path) or None,
        baseline=_str(data, "baseline", "", search_path) or None,
        annotations=_bool_or_none(data, "annotations", search_path),
        offline=_bool(data, "offline", Config.offline, search_path),
    )

    # CLI overrides replace file values when explicitly provided
    for key, value in overrides.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)

    return cfg
