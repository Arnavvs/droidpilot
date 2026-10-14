"""Shared test setup: import from src/, and give every test a fresh policy config.

The write gate keeps its per-run configuration in a module-level CONFIG, so a
test that enables a write for itself must not leak it into the next one.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


@pytest.fixture(autouse=True)
def _fresh_policy(monkeypatch):
    from droidpilot.policy import writes as wr
    monkeypatch.delenv("DROIDPILOT_WRITES", raising=False)
    monkeypatch.delenv("DROIDPILOT_ALLOW_RULES", raising=False)
    wr.configure(mode="auto")
    yield
    wr.configure(mode="auto")
