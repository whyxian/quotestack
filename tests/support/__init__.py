"""Helpers shared by the test suite.

Not tests themselves: pytest only collects ``test_*.py``, so anything here is
invisible to collection and safe to import from any test module.
"""

from __future__ import annotations

import pathlib

__all__ = ["ROOT"]

#: Repository root. Tests used to compute this with ``parents[1]``, which breaks
#: the moment a file moves into a subdirectory - and this suite has six of them.
ROOT = pathlib.Path(__file__).resolve().parents[2]
