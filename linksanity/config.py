"""Configuration loading from linksanity.toml and CLI flags."""

from __future__ import annotations

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


def _int(data: dict[str, object], key: str, default: int, path: Path | None = None) -> int:
    v = data.get(key, default)
    if not isinstance(v, (int, float, str)):
        return default
    try:
        return int(v)
    except ConfigError:
        raise
    except (ValueError, OverflowError) as exc:
        location = f" in {path}" if path is not None else ""
        raise ConfigError(f"invalid value for '{key}'{location}: {v!r} is not a valid integer") from exc


def _bool(data: dict[str, object], key: str, default: bool) -> bool:
    v = data.get(key, default)
    return bool(v) if isinstance(v, (bool, int)) else default


def _str(data: dict[str, object], key: str, default: str) -> str:
    v = data.get(key, default)
    return str(v) if isinstance(v, str) else default


def _bool_or_none(data: dict[str, object], key: str) -> bool | None:
    v = data.get(key)
    return bool(v) if isinstance(v, (bool, int)) else None


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
        raw = data.get(key, [])
        if isinstance(raw, list):
            return {str(d).lower() for d in raw}
        return set()

    def _url_set(key: str) -> set[str]:
        raw = data.get(key, [])
        if isinstance(raw, list):
            return {str(u) for u in raw}
        return set()

    cfg = Config(
        workers=_int(data, "workers", Config.workers, search_path),
        playwright_workers=_int(
            data, "playwright_workers", Config.playwright_workers, search_path
        ),
        timeout=_int(data, "timeout", Config.timeout, search_path),
        retry=_int(data, "retry", Config.retry, search_path),
        check_anchors=_bool(data, "check_anchors", Config.check_anchors),
        check_images=_bool(data, "check_images", Config.check_images),
        myst=_bool(data, "myst", Config.myst),
        link_style=_str(data, "link_style", "") or None,
        max_pages=_int(data, "max_pages", Config.max_pages, search_path),
        ignore_domains=_domain_set("ignore_domains"),
        js_domains=_domain_set("js_domains"),
        skip_urls=_url_set("skip_urls"),
        block_analytics=_bool(data, "block_analytics", Config.block_analytics),
        format=_str(data, "format", Config.format),
        max_redirects=_int(data, "max_redirects", Config.max_redirects, search_path),
        cache_file=_str(data, "cache_file", "") or None,
        cache_ttl=_int(data, "cache_ttl", Config.cache_ttl, search_path),
        incremental=_bool(data, "incremental", Config.incremental),
        since=_str(data, "since", "") or None,
        baseline=_str(data, "baseline", "") or None,
        annotations=_bool_or_none(data, "annotations"),
        offline=_bool(data, "offline", Config.offline),
    )

    # CLI overrides replace file values when explicitly provided
    for key, value in overrides.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)

    return cfg
