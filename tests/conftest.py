import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coach.profile import load_athlete, load_library  # noqa: E402

FIXTURES = ROOT / "evals" / "fixtures"


@pytest.fixture
def raw():
    return lambda name="ready_to_progress": json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def athlete():
    return load_athlete()


@pytest.fixture
def library():
    return load_library()
