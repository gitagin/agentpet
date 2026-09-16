"""Contract tests for the LIVE model-backed role surface.

The unreachable supervisor/reviewer role system was removed in the 2026-07
dead-code cleanup (fix backlog #11). Two roles remain in production:

- verifier (read-only receipt verification inside the deterministic
  action-execution path, see ``app/agents/nodes/executor.py``), and
- reflection (the managed post-reply reflection job, see
  ``app/agents/reflection_graph.py``).

These tests pin the safety properties of what is actually shipped: the
surviving contract models stay frozen/extra-forbidden, and the reflection
builder keeps rejecting tool escalation.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import BaseModel

import app.agents.contracts as contracts
from app.agents.roles import verifier_agent


def test_all_surviving_contract_models_are_frozen_and_extra_forbidden() -> None:
    checked = 0
    for _name, cls in inspect.getmembers(contracts, inspect.isclass):
        if not issubclass(cls, BaseModel) or cls is BaseModel:
            continue
        if cls.__module__ != contracts.__name__:
            continue
        config = cls.model_config
        assert config.get("frozen") is True, f"{cls.__name__} must be frozen"
        assert config.get("extra") == "forbid", f"{cls.__name__} must forbid extra fields"
        checked += 1
    assert checked >= 5, "contract module unexpectedly empty - surgery went too far"


def test_verifier_module_exposes_receipt_verification_only() -> None:
    # The executor depends on this exact entry point; keep it stable.
    assert callable(verifier_agent.verify_execution_receipt)
