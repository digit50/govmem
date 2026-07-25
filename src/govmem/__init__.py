"""Governed shared memory for multi-agent LLM systems."""

__version__ = "0.1.0"

from govmem.exceptions import (
    AgentAlreadyRegisteredError,
    AgentNotRegisteredError,
    EntryNotFoundError,
    LockedEntryError,
    SupersedeOnlyError,
    UnauthorizedWriteError,
)
from govmem.models import (
    Authority,
    Entry,
    EntryState,
    Mutability,
    Provenance,
    Scope,
)
from govmem.store import GovernedMemoryStore

__all__ = [
    "AgentAlreadyRegisteredError",
    "AgentNotRegisteredError",
    "Authority",
    "Entry",
    "EntryNotFoundError",
    "EntryState",
    "GovernedMemoryStore",
    "LockedEntryError",
    "Mutability",
    "Provenance",
    "Scope",
    "SupersedeOnlyError",
    "UnauthorizedWriteError",
    "__version__",
]
