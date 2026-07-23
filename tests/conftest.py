"""Shared pytest fixtures for the kit test suite.

The suite is run by the kit-only pixi environment (`pixi run -e kit test`);
targets never run it (they have neither pytest nor a `test` task). This file
also puts the repo root on sys.path so `import kitconfig` (and the other
root-level kit modules) resolves when tests live under tests/.
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Prepend the repo root so root-level modules (kitconfig, build, ...) import
# from tests/ without an installed package.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def repo_root() -> Path:
    """Absolute path to the guide-template repo root."""
    return REPO_ROOT
