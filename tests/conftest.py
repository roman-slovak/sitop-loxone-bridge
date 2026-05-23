import os
from pathlib import Path

import pytest


@pytest.fixture
def chdir_tmp(tmp_path: Path) -> Path:
    """Run a test inside an empty tmp dir so Settings() does not pick up a real .env."""
    prev = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(prev)
