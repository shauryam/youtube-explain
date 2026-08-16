"""Minimal OpenRouter chat client with retries, disk caching and cost tracking."""

from __future__ import annotations

import json
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Self

import httpx

from .cache import Cache
from .config import OPENROUTER_ENDPOINT

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class LLMError(RuntimeError):
    pass


def _loads(text: str) -> dict:
    """Parse model JSON, tolerating the literal newlines models put in strings."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(text, strict=False)


@dataclass(slots=True)
class Usage:
    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        cache: Cache | None = None,
        timeout: float = 300.0,
        max_retries: int = 4,
    ) -> None:
        self.model = model
        self.cache = cache
        self.max_retries = max_retries
        self.usage = Usage()
        self._lock = threading.Lock()
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/shauryam/youtube-explain",
                "X-Title": "ytexplain",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.3,
        max_tokens: int = 16000,
        json_object: bool = False,
    ) -> str:
        key = Cache.key(self.model, system, user, temperature, max_tokens, json_object)
        if self.cache and (hit := self.cache.get("completions", key)):
            with self._lock:
                self.usage.cached_calls += 1
            return hit["text"]

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        if json_object:
            body["response_format"] = {"type": "json_object"}

        payload = self._post(body)
        text, finish_reason = self._extract_text(payload)
        self._record_usage(payload.get("usage") or {})

        truncated = finish_reason == "length"
        if truncated and json_object:
            raise LLMError(
                f"Response hit the {max_tokens} token limit, so the JSON is incomplete"
            )
        if self.cache and not truncated:
            self.cache.set("completions", key, {"text": text})
        return text

    def complete_json(
        self, *, system: str, user: str, require_key: str | None = None, **kwargs
    ) -> dict:
        raw = self.complete(system=system, user=user, json_object=True, **kwargs)
        try:
            payload = _loads(JSON_FENCE.sub("", raw))
        except json.JSONDecodeError as exc:
            payload = self._first_json_object(raw)
            if payload is None:
                raise LLMError(f"Model did not return valid JSON: {exc}\n{raw[:500]}") from exc

        # Recovery can latch onto a nested object, so verify the shape we expect.
        if require_key and require_key not in payload:
            raise LLMError(f"JSON response is missing the {require_key!r} key")
        return payload

    def _post(self, body: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(OPENROUTER_ENDPOINT, json=body)
                if response.status_code in RETRY_STATUS:
                    raise LLMError(f"HTTP {response.status_code}: {response.text[:300]}")
                if response.status_code >= 400:
                    raise LLMError(f"HTTP {response.status_code}: {response.text[:500]}")
                return response.json()
            except (httpx.HTTPError, LLMError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(min(2**attempt + random.uniform(0, 0.75), 30))
        raise LLMError(f"OpenRouter request failed after {self.max_retries + 1} attempts: {last_error}")

    @staticmethod
    def _extract_text(payload: dict) -> tuple[str, str]:
        choices = payload.get("choices") or []
        if not choices:
            raise LLMError(f"No choices in response: {json.dumps(payload)[:400]}")
        finish_reason = str(choices[0].get("finish_reason") or "")
        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            raise LLMError(f"Empty completion (finish_reason={finish_reason})")
        return text, finish_reason

    def _record_usage(self, usage: dict) -> None:
        with self._lock:
            self.usage.calls += 1
            self.usage.prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.usage.completion_tokens += int(usage.get("completion_tokens") or 0)
            self.usage.cost_usd += float(usage.get("cost") or 0.0)

    @staticmethod
    def _first_json_object(raw: str) -> dict | None:
        start = raw.find("{")
        while start != -1:
            depth = 0
            for index in range(start, len(raw)):
                if raw[index] == "{":
                    depth += 1
                elif raw[index] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return _loads(raw[start : index + 1])
                        except json.JSONDecodeError:
                            break
            start = raw.find("{", start + 1)
        return None
