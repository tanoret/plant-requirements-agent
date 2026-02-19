from __future__ import annotations
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import Any
from ..config import OpenAIConfig

class OpenAIError(RuntimeError):
    pass

class OpenAIClient:
    """Minimal OpenAI Chat Completions client with JSON output.

    This keeps OpenAI usage limited to *parsing/spec extraction*. All sizing and
    optimization remains deterministic (no LLM arithmetic).
    """

    def __init__(self, cfg: OpenAIConfig):
        self.cfg = cfg
        self._client = httpx.Client(
            base_url=cfg.base_url,
            timeout=cfg.timeout_s,
            headers={
                "Authorization": f"Bearer {cfg.api_key}" if cfg.api_key else "",
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
            raise OpenAIError("OPENAI_API_KEY is not set.")
        payload = {
            "model": model or self.cfg.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        r = self._client.post("/chat/completions", json=payload)
        if r.status_code >= 400:
            raise OpenAIError(f"OpenAI API error {r.status_code}: {r.text}")
        out = r.json()
        try:
            content = out["choices"][0]["message"]["content"]
        except Exception as e:
            raise OpenAIError(f"Unexpected OpenAI response: {out}") from e
        import json as _json
        return _json.loads(content)
