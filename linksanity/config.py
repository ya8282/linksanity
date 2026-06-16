"""Configuration loading from linksanity.toml and CLI flags."""

from __future__ import annotations

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
    max_pages: int = 500
    ignore_domains: set[str] = field(default_factory=set)
    js_domains: set[str] = field(default_factory=set)
    output: str | None = None
    report: str | None = None
    github_issue: bool = False
    github_repo: str | None = None
    format: str = "console"


def _load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _int(data: dict[str, object], key: str, default: int) -> int:
    v = data.get(key, default)
    return int(v) if isinstance(v, (int, float, str)) else default


def _bool(data: dict[str, object], key: str, default: bool) -> bool:
    v = data.get(key, default)
    return bool(v) if isinstance(v, (bool, int)) else default


def _str(data: dict[str, object], key: str, default: str) -> str:
    v = data.get(key, default)
    return str(v) if isinstance(v, str) else default


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

    cfg = Config(
        workers=_int(data, "workers", Config.workers),
        playwright_workers=_int(data, "playwright_workers", Config.playwright_workers),
        timeout=_int(data, "timeout", Config.timeout),
        retry=_int(data, "retry", Config.retry),
        check_anchors=_bool(data, "check_anchors", Config.check_anchors),
        max_pages=_int(data, "max_pages", Config.max_pages),
        ignore_domains=_domain_set("ignore_domains"),
        js_domains=_domain_set("js_domains"),
        format=_str(data, "format", Config.format),
    )

    # CLI overrides replace file values when explicitly provided
    for key, value in overrides.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)

    return cfg
