"""Minimal OpenAI-compatible chat client (llama.cpp server, vLLM, Ollama, ...)."""

from __future__ import annotations

import json
import logging
import re

import httpx

from ..config import LlmConfig

log = logging.getLogger(__name__)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LlmError(RuntimeError):
    pass


class LlmClient:
    def __init__(self, cfg: LlmConfig, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self._http = httpx.Client(
            base_url=cfg.base_url.rstrip("/"),
            timeout=httpx.Timeout(cfg.timeout_s, connect=10.0),
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            transport=transport,
        )

    def chat(self, system: str, user: str, schema: dict | None = None, max_tokens: int | None = None) -> str:
        body: dict = {
            "model": self.cfg.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.cfg.temperature,
            "max_tokens": max_tokens or self.cfg.max_output_tokens,
            # Qwen3.x / hybrid reasoning models: answer directly (llama.cpp honours this).
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if schema is not None and self.cfg.use_json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "minutes", "strict": True, "schema": schema},
            }
        response = self._http.post("/chat/completions", json=body)
        if response.status_code == 400 and "response_format" in body:
            log.warning("LLM rejected response_format; retrying without grammar constraint")
            body.pop("response_format")
            response = self._http.post("/chat/completions", json=body)
        if response.status_code >= 400:
            raise LlmError(f"LLM HTTP {response.status_code}: {response.text[:500]}")
        content = response.json()["choices"][0]["message"].get("content") or ""
        return _THINK.sub("", content).strip()

    def chat_json(self, system: str, user: str, schema: dict, max_tokens: int | None = None) -> dict:
        last_error: Exception | None = None
        for attempt in range(2):
            raw = self.chat(system, user if attempt == 0 else user + "\n\nفقط یک شیء JSON معتبر برگردان.",
                            schema, max_tokens)
            try:
                return parse_json_object(raw)
            except ValueError as exc:
                last_error = exc
                log.warning("LLM returned invalid JSON (attempt %d): %s", attempt + 1, exc)
        raise LlmError(f"LLM did not return valid JSON: {last_error}")

    def health(self) -> bool:
        try:
            root = self.cfg.base_url.rstrip("/").removesuffix("/v1")
            return httpx.get(root + "/health", timeout=5.0).status_code == 200
        except httpx.HTTPError:
            return False


def parse_json_object(raw: str) -> dict:
    text = _FENCE.sub("", _THINK.sub("", raw)).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object found") from None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(str(exc)) from None
    if not isinstance(value, dict):
        raise ValueError("top-level JSON is not an object")
    return value
