"""Compatibility import for the settings store implementation.

The historical module is kept as the public import path. Replacing the module
object preserves existing monkeypatch and plugin hooks that target private
credential helpers while allowing the implementation to live in a focused
module.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from . import settings_store as _implementation

if TYPE_CHECKING:
    from .settings_store import initialize_settings_store as initialize_settings_store

sys.modules[__name__] = _implementation
