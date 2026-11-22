"""Pytest configuration for the whole suite.

Shared *fixtures* live here; shared *constants and helpers* live in
``tests/support/`` because a fixture cannot be used at module import time, and
several contract tests need the repository root while defining constants.
"""

from __future__ import annotations

import pathlib

import pytest
from tests.support import ROOT


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    """Absolute path to the repository root."""
    return ROOT
