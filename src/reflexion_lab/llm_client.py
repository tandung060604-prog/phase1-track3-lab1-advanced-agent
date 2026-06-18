from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv

_LAST_REQUEST_AT = 0.0


@dataclass
class LLMResponse:
    text: str
    total_tokens: int
    latency_ms: int


def _throttle() -> None:
    global _LAST_REQUEST_AT
    delay = float(os.getenv("REFLEXION_REQUEST_DELAY_SECONDS", "0") or "0")
    if delay <= 0:
        return
    now = time.perf_counter()
    wait_for = delay - (now - _LAST_REQUEST_AT)
    if wait_for > 0:
        time.sleep(wait_for)
    _LAST_REQUEST_AT = time.perf_counter()


def _role_model(provider: str, model_env: str | None, default_env: str, default_model: str) -> str:
    candidates: list[str] = []
    if model_env:
        candidates.extend([f"{provider}_{model_env}", model_env])
    candidates.append(default_env)
    for name in candidates:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default_model


def _openai_config(model_env: str | None = None) -> tuple[str, str, str]:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
    model = _role_model("OPENAI", model_env, "OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        raise RuntimeError(
            "Missing OPENAI_API_KEY. Add it to .env, or run with --mode mock for offline grading."
        )
    return api_key, base_url, model


def _anthropic_config(model_env: str | None = None) -> tuple[str, str, str]:
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com").strip().rstrip("/")
    model = _role_model("ANTHROPIC", model_env, "ANTHROPIC_MODEL", "claude-opus-4-6")
    if not api_key:
        raise RuntimeError(
            "Missing LLM API key. Add OPENAI_API_KEY or ANTHROPIC_API_KEY to .env, or run with --mode mock."
        )
    return api_key, base_url, model


def chat_completion(system_prompt: str, user_prompt: str, *, response_format: str = "text", model_env: str | None = None) -> LLMResponse:
    load_dotenv()
    if os.getenv("OPENAI_API_KEY", "").strip():
        return _openai_chat_completion(system_prompt, user_prompt, response_format=response_format, model_env=model_env)
    return _anthropic_chat_completion(system_prompt, user_prompt, response_format=response_format, model_env=model_env)


def _openai_chat_completion(system_prompt: str, user_prompt: str, *, response_format: str = "text", model_env: str | None = None) -> LLMResponse:
    api_key, base_url, model = _openai_config(model_env=model_env)
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    if response_format == "json":
        payload["response_format"] = {"type": "json_object"}

    _throttle()
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM request failed: {exc.reason}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    data = json.loads(raw)
    text = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage", {})
    total_tokens = int(usage.get("total_tokens") or 0)
    return LLMResponse(text=text, total_tokens=total_tokens, latency_ms=latency_ms)


def _anthropic_chat_completion(system_prompt: str, user_prompt: str, *, response_format: str = "text", model_env: str | None = None) -> LLMResponse:
    api_key, base_url, model = _anthropic_config(model_env=model_env)
    auth_token = os.getenv("ANTHROPIC_AUTH_TOKEN", "").strip()
    if response_format == "json":
        user_prompt = f"{user_prompt}\n\nReturn one valid JSON object only. Do not include markdown fences."
    try:
        import anthropic
    except ImportError:
        anthropic = None

    if anthropic is not None:
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
        client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            default_headers=headers,
        )
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                _throttle()
                message = client.messages.create(
                    model=model,
                    max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "1000")),
                    temperature=0,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                break
            except Exception as exc:
                last_error = exc
                if exc.__class__.__name__ != "RateLimitError" or attempt == 3:
                    raise
                time.sleep(float(os.getenv("REFLEXION_RATE_LIMIT_BACKOFF_SECONDS", "65") or "65"))
        else:
            raise last_error or RuntimeError("Anthropic request failed")
        latency_ms = int((time.perf_counter() - started) * 1000)
        text = "\n".join(part.text for part in message.content if getattr(part, "type", "") == "text").strip()
        usage = getattr(message, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return LLMResponse(text=text, total_tokens=input_tokens + output_tokens, latency_ms=latency_ms)

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": int(os.getenv("ANTHROPIC_MAX_TOKENS", "1000")),
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
        "Content-Type": "application/json",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    _throttle()
    request = urllib.request.Request(
        f"{base_url}/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic request failed with HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Anthropic request failed: {exc.reason}") from exc

    latency_ms = int((time.perf_counter() - started) * 1000)
    data = json.loads(raw)
    parts = data.get("content", [])
    text = "\n".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
    usage = data.get("usage", {})
    total_tokens = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
    return LLMResponse(text=text, total_tokens=total_tokens, latency_ms=latency_ms)


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])
