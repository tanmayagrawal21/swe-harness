from pathlib import Path

import pytest

from swe_harness import spec

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def reference():
    return spec.load(ROOT / "workflows" / "reference.yaml")
