from __future__ import annotations

import json
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import AnthropicConfig


class AnthropicError(RuntimeError):
    pass


class AnthropicClient:
    """Minimal Anthropic Messages API client with JSON output.

    Implements the same ``chat_json()`` interface as ``OpenAIClient`` so it
    can be used as a drop-in replacement for spec parsing.
    """

    _BASE_URL = "https://api.anthropic.com"
    _API_VERSION = "2023-06-01"

    def __init__(self, cfg: AnthropicConfig) -> None:
        self.cfg = cfg
        self._client = httpx.Client(
            base_url=self._BASE_URL,
            timeout=cfg.timeout_s,
            headers={
                "x-api-key": cfg.api_key or "",
                "anthropic-version": self._API_VERSION,
                "Content-Type": "application/json",
            },
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    )
    def chat_json(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> dict[str, Any]:
        if not self.cfg.api_key:
            raise AnthropicError("ANTHROPIC_API_KEY is not set.")

        # Anthropic separates the system prompt from the message list
        system_parts: list[str] = []
        user_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                user_messages.append(msg)

        system_prompt = "\n\n".join(system_parts) if system_parts else ""
        system_prompt = (system_prompt + "\n\nRespond with valid JSON only. No markdown fences.").strip()

        payload: dict[str, Any] = {
            "model": model or self.cfg.model,
            "max_tokens": 1024,
            "temperature": temperature,
            "system": system_prompt,
            "messages": user_messages,
        }

        r = self._client.post("/v1/messages", json=payload)
        if r.status_code >= 400:
            raise AnthropicError(f"Anthropic API error {r.status_code}: {r.text}")

        out = r.json()
        try:
            content: str = out["content"][0]["text"]
        except Exception as exc:
            raise AnthropicError(f"Unexpected Anthropic response: {out}") from exc

        # Strip accidental markdown code fences
        content = content.strip()
        if content.startswith("```"):
            _, _, rest = content.partition("\n")
            content = rest.rsplit("```", 1)[0]

        return json.loads(content.strip())
