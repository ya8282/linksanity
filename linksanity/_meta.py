"""Package identity constants — a dependency-free leaf module.

Deliberately imports nothing from ``linksanity`` itself. Modules that would
otherwise need to import from ``linksanity/__init__.py`` (and risk a circular
import, since ``__init__.py`` transitively imports most of the package) can
import from here instead.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

HOMEPAGE_URL = "https://github.com/ya8282/linksanity"

try:
    # Read from installed metadata rather than a literal: a hand-maintained
    # literal here silently drifted from pyproject.toml and shipped "0.1.0" in
    # both the 0.1.1 and 0.2.0 artifacts. PyPI uploads are immutable, so that
    # is not fixable after the fact.
    VERSION = _distribution_version("linksanity")
except PackageNotFoundError:  # imported from a source tree that was never installed
    VERSION = "0.0.0+unknown"
