"""Loader for recorded payloads.

Returns bytes rather than text because some sources answer in GBK and decoding
here would hide the encoding from the adapter under test.
"""

from __future__ import annotations

import pathlib

__all__ = ["load"]

_ROOT = pathlib.Path(__file__).parent


def load(relative: str) -> bytes:
    """Read a recorded payload.

    Args:
        relative: Path inside ``tests/fixtures``, e.g. ``eastmoney/quote.json``.

    Returns:
        The raw bytes exactly as recorded.

    Raises:
        FileNotFoundError: The fixture is missing, which is a test bug.
    """
    return (_ROOT / relative).read_bytes()
