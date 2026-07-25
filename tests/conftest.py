"""Shared fixtures for govmem tests."""

import pytest

from govmem import GovernedMemoryStore, Scope


@pytest.fixture
def store() -> GovernedMemoryStore:
    return GovernedMemoryStore()


@pytest.fixture
def travel_scope() -> Scope:
    return Scope(user="user_123", task="travel", namespace="research")


@pytest.fixture
def registered_store(store: GovernedMemoryStore, travel_scope: Scope) -> GovernedMemoryStore:
    store.register_agent(
        "researcher",
        write_kinds=["fact", "hypothesis"],
        scopes=["research"],
    )
    store.register_agent(
        "planner",
        write_kinds=["plan"],
        scopes=["planning"],
    )
    return store
