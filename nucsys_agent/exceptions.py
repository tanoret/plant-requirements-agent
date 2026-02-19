from __future__ import annotations

class AgentError(RuntimeError):
    """Base exception for nucsys-agent."""

class SpecError(AgentError):
    """Design spec is missing required information."""

class CardError(AgentError):
    """Pattern card is invalid or not applicable."""

class SizingError(AgentError):
    """Sizing or optimization failed."""

class ExportError(AgentError):
    """Export/serialization failed."""
