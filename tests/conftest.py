"""Suite-wide guards. pydantic-ai's network path must fail loudly."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session", autouse=True)
def _disallow_model_requests() -> None:
    from pydantic_ai import models

    models.ALLOW_MODEL_REQUESTS = False
