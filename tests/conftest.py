from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def disable_external_company_identity_calls(monkeypatch):
    """Unit and contract tests must never consume a real OpenDART quota."""

    monkeypatch.setenv("TRZIP_DISABLE_EXTERNAL_COMPANY_IDENTITY", "1")
