"""Test-suite-wide setup.

Pygame is not installed in CI / dev environments; tests that import
``espyresso.display`` (transitively or directly) need a stand-in. We
inject a MagicMock into ``sys.modules`` before any test module imports
pygame. Tests that don't touch pygame are unaffected.

pigpio is already mocked in ``espyresso.config`` whenever DEBUG is true
(i.e. on macOS), so we don't need to handle it here.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

if "pygame" not in sys.modules:
    sys.modules["pygame"] = MagicMock()
