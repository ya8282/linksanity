"""Configuration loading from linksanity.toml and CLI flags."""

from __future__ import annotations

import datetime
import fnmatch
import math
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn, cast


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
    stealth: bool = False
    paths: list[str] = field(default_factory=list)


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


def _error_suffix(path: Path | None) -> str:
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


def _raise_type_error(key: str, path: Path | None, expected: str, actual: str) -> NoReturn:
    raise ConfigError(
        f"invalid value for '{key}'{_error_suffix(path)}: expected {expected}, got {actual}"
    )


def _check_type(
    v: object, key: str, path: Path | None, types: tuple[type, ...], expected: str
) -> None:
    if not isinstance(v, types):
        _raise_type_error(key, path, expected, _type_name(v))


def _int(data: dict[str, object], key: str, default: int, path: Path | None) -> int:
    if key not in data:
        return default
    v = data[key]
    # bool is a subclass of int, so it passes isinstance(v, int) before the
    # type gate below ever runs -- workers = true would silently become 1.
    # Reject it explicitly, ahead of the (int, float, str) gate, so every
    # integer key gets the same clear ConfigError a wrong type would produce.
    if isinstance(v, bool):
        _raise_type_error(key, path, "an integer", _type_name(v))
    _check_type(v, key, path, (int, float, str), "an integer")
    if isinstance(v, float):
        # NaN/inf would otherwise reach int() below, which does raise on
        # them (ValueError / OverflowError) rather than crash -- but check
        # explicitly so the non-integral-float check below (v != int(v))
        # never has to evaluate int() on a NaN itself.
        if math.isnan(v) or math.isinf(v):
            raise ConfigError(
                f"invalid value for '{key}'{_error_suffix(path)}: {v!r} is not a valid integer"
            )
        if v != int(v):
            # Truncating toward zero here would silently turn 2.5 into 2 --
            # report the value the user actually wrote instead.
            raise ConfigError(
                f"invalid value for '{key}'{_error_suffix(path)}: "
                f"{v!r} is not a whole number"
            )
    try:
        return int(cast("int | float | str", v))
    except (ValueError, OverflowError) as exc:
        raise ConfigError(
            f"invalid value for '{key}'{_error_suffix(path)}: {v!r} is not a valid integer"
        ) from exc


def _bool(data: dict[str, object], key: str, default: bool, path: Path | None) -> bool:
    if key not in data:
        return default
    v = data[key]
    _check_type(v, key, path, (bool, int), "a boolean")
    return bool(v)


def _str(data: dict[str, object], key: str, default: str, path: Path | None) -> str:
    if key not in data:
        return default
    v = data[key]
    _check_type(v, key, path, (str,), "a string")
    return cast(str, v)


# Minimum accepted value for each numeric key that has a meaningful floor.
# workers/playwright_workers/timeout/max_pages must be >= 1 (0 or negative
# either deadlocks a Semaphore, times out every request instantly, or
# crawls nothing). retry/max_redirects/cache_ttl may legitimately be 0
# ("no retries" / "don't follow redirects" / "always expired"); only
# negative values are invalid for those.
_MINIMUMS: dict[str, int] = {
    "workers": 1,
    "playwright_workers": 1,
    "timeout": 1,
    "max_pages": 1,
    "retry": 0,
    "max_redirects": 0,
    "cache_ttl": 0,
}


def _validate_ranges(
    cfg: Config,
    data: dict[str, object],
    overrides: dict[str, object],
    path: Path | None,
) -> None:
    """Reject an out-of-range effective value at load time (linksanity-6lm).

    Runs after CLI overrides have been applied to cfg, so it validates the
    *effective* value regardless of whether it came from linksanity.toml or
    a CLI flag (e.g. ``--workers -5`` bypasses the ``_int`` helper entirely
    via a direct ``setattr``, so it must be checked here too).

    The ``in <path>`` location suffix is only added when the value actually
    came from the config file. A CLI-supplied override takes precedence
    over the same key in the file (see the setattr loop in load_config), so
    checking `key in overrides` first correctly identifies that case even
    when the file also set the key.
    """
    for key, minimum in _MINIMUMS.items():
        value = getattr(cfg, key)
        if value >= minimum:
            continue
        from_cli = key in overrides and overrides[key] is not None
        location = "" if from_cli else _error_suffix(path if key in data else None)
        raise ConfigError(
            f"invalid value for '{key}'{location}: must be >= {minimum}, got {value}"
        )


def _bool_or_none(data: dict[str, object], key: str, path: Path | None) -> bool | None:
    if key not in data:
        return None
    return _bool(data, key, False, path)


def _string_list(data: dict[str, object], key: str, path: Path | None) -> list[str]:
    """Like `_string_set` but order-preserving and strict: every item must
    already be a string. `paths` is user-visible order (scan order, YAML
    rendering order), unlike a domain/pattern set where order never matters
    -- so, unlike `_string_set`, this does not str()-coerce non-string items;
    a stray `paths = ["docs", 1]` is a config error, not a silent int(1)."""
    if key not in data:
        return []
    raw = data[key]
    if not isinstance(raw, list):
        _raise_type_error(key, path, "a list of strings", _type_name(raw))
    for item in raw:
        if not isinstance(item, str):
            _raise_type_error(key, path, "a list of strings", _type_name(item))
    return cast("list[str]", raw)


def _resolve_paths(raw: list[str], search_path: Path) -> list[str]:
    """Resolve each `paths` entry against the directory holding the loaded
    toml, then re-express it relative to the cwd, so scan output looks like
    a CLI-typed path (spec section 8). Absolute entries and glob characters
    pass through untouched -- this never calls resolve()/glob, only plain
    string path-joining, so a pattern like "docs/**/*.md" survives intact.
    """
    base = search_path.parent
    cwd = Path.cwd()
    resolved: list[str] = []
    for entry in raw:
        if os.path.isabs(entry):
            resolved.append(entry)
            continue
        joined = os.path.join(str(base), entry)
        try:
            rel = os.path.relpath(joined, cwd)
        except ValueError:
            # Different drives on Windows: relpath can't express a relative
            # path across them, so fall back to the absolute joined path.
            rel = joined
        if entry.endswith("/") and not rel.endswith("/"):
            # relpath strips a trailing slash; restore it if the user wrote one.
            rel += "/"
        resolved.append(rel)
    return resolved


# Every top-level linksanity.toml key load_config actually reads. Keep in
# sync with the string literals passed to _int/_bool/_str/_string_set/
# _string_list/_bool_or_none below -- add a key here whenever one is added
# there, or it will be reported as unrecognised (linksanity-1lc).
_CONSUMED_KEYS = frozenset(
    {
        "workers",
        "playwright_workers",
        "timeout",
        "retry",
        "check_anchors",
        "check_images",
        "myst",
        "link_style",
        "max_pages",
        "ignore_domains",
        "js_domains",
        "skip_urls",
        "block_analytics",
        "format",
        "max_redirects",
        "cache_file",
        "cache_ttl",
        "incremental",
        "since",
        "baseline",
        "annotations",
        "offline",
        "stealth",
        "paths",
    }
)


def _unconsumed_keys(data: dict[str, object], consumed: frozenset[str]) -> list[str]:
    """Return dotted-path names for every key in `data` that `load_config`
    never read.

    A key whose value is a non-empty table is expanded into one entry per
    leaf key nested inside it (e.g. ``tool.linksanity.workers``) rather than
    reported once as just ``tool``. load_config only ever reads top-level
    scalar/list keys, so any table -- most commonly a pyproject-style
    ``[tool.linksanity]`` section -- is unconsumed in its entirety; naming
    the actual leaf keys tells the user exactly which settings were ignored
    instead of just which table.
    """
    names: list[str] = []
    for key, value in data.items():
        if key in consumed:
            continue
        if isinstance(value, dict) and value:
            names.extend(f"{key}.{nested}" for nested in _unconsumed_keys(value, frozenset()))
        else:
            names.append(key)
    return names


def _warn_unconsumed_keys(data: dict[str, object], path: Path) -> None:
    unconsumed = _unconsumed_keys(data, _CONSUMED_KEYS)
    if not unconsumed:
        return
    names = ", ".join(sorted(unconsumed))
    print(
        f"[linksanity] warning: unrecognised config key(s) in {path}: {names} "
        "-- check the spelling against the Configuration docs; linksanity "
        "only reads top-level keys, so a [table.name] section (e.g. "
        "[tool.linksanity]) is ignored",
        file=sys.stderr,
    )


def load_config(
    toml_path: Path | None = None,
    **overrides: object,
) -> Config:
    """Load config from linksanity.toml (if found) and apply CLI overrides."""
    data: dict[str, object] = {}

    search_path = toml_path or Path("linksanity.toml")
    if search_path.exists():
        data = _load_toml(search_path)

    def _string_set(key: str, *, lower: bool = False) -> set[str]:
        if key not in data:
            return set()
        raw = data[key]
        if not isinstance(raw, list):
            raise ConfigError(
                f"invalid value for '{key}'{_error_suffix(search_path)}: "
                f"expected a list of strings, got {_type_name(raw)}"
            )
        return {str(v).lower() if lower else str(v) for v in raw}

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
        ignore_domains=_string_set("ignore_domains", lower=True),
        js_domains=_string_set("js_domains", lower=True),
        skip_urls=_string_set("skip_urls"),
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
        stealth=_bool(data, "stealth", Config.stealth, search_path),
        paths=_resolve_paths(_string_list(data, "paths", search_path), search_path),
    )

    # CLI overrides replace file values when explicitly provided
    for key, value in overrides.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)

    _validate_ranges(cfg, data, overrides, search_path)

    if data:
        _warn_unconsumed_keys(data, search_path)

    return cfg
