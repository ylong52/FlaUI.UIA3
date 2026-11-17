from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def fixture_html() -> str:
    return (Path(__file__).parent / "fixtures" / "survey.html").read_text(
        encoding="utf-8"
    )


@pytest.fixture()
def profile() -> dict:
    return {
        "age": 29,
        "country": "CN",
        "products": ["Pumps"],
        "years": 5,
    }
