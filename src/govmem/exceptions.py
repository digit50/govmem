"""Governed memory store exceptions."""


class GovMemError(Exception):
    """Base exception for govmem."""


class AgentNotRegisteredError(GovMemError):
    """Raised when an unregistered agent performs an operation."""


class AgentAlreadyRegisteredError(GovMemError):
    """Raised when register_agent is called for an existing agent_id."""


class UnauthorizedWriteError(GovMemError):
    """Raised when an agent lacks authority for a write."""


class EntryNotFoundError(GovMemError):
    """Raised when a referenced entry does not exist."""


class LockedEntryError(GovMemError):
    """Raised when mutating a locked entry."""


class SupersedeOnlyError(GovMemError):
    """Raised when direct revision is attempted on supersede-only entries."""
