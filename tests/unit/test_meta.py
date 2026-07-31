"""Tests for linksanity/_meta.py — the package identity constants."""

from __future__ import annotations

import tomllib
from pathlib import Path

from linksanity._meta import HOMEPAGE_URL


def test_homepage_constant_matches_pyproject() -> None:
    pyproject_path = Path(__file__).parents[2] / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)
    homepage = data["project"]["urls"]["Homepage"]
    assert homepage == HOMEPAGE_URL
