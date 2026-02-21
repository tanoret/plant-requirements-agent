from __future__ import annotations

from .openai_client import OpenAIClient, OpenAIError
from .anthropic_client import AnthropicClient, AnthropicError


def make_llm_client(cfg):
    """Return an LLM client based on whichever API key is configured.

    Priority: Anthropic → OpenAI → ``None`` (regex-only spec parsing).

    Parameters
    ----------
    cfg:
        An ``AgentConfig`` instance.
    """
    if cfg.anthropic.api_key:
        return AnthropicClient(cfg.anthropic)
    if cfg.openai.api_key:
        return OpenAIClient(cfg.openai)
    return None


__all__ = [
    "OpenAIClient",
    "OpenAIError",
    "AnthropicClient",
    "AnthropicError",
    "make_llm_client",
]
