"""Мульти-провайдерный LLM-слой: GLM (Z.AI), Claude (Anthropic/прокси), ChatGPT (OpenAI).

Ключи и настройки — из окружения или ~/profi/.env (в git не попадает):

  LLM_PROVIDER       = glm | anthropic | openai     (по умолчанию glm)
  LLM_MODEL          — модель (по умолчанию — дефолт провайдера)
  GLM_API_KEY / ZAI_API_KEY        + GLM_BASE_URL   (api.z.ai, OpenAI-протокол)
  ANTHROPIC_AUTH_TOKEN / ANTHROPIC_API_KEY + ANTHROPIC_BASE_URL
    — работает и с настоящим Anthropic, и с Anthropic-совместимыми
      прокси GLM (например claude-buffet)
  OPENAI_API_KEY     + OPENAI_BASE_URL              (OpenAI-протокол)

Использование: llm.chat(system="...", user="...") -> str
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

_TIMEOUT_S = 90


def _load_env_file() -> dict:
    env: dict = {}
    path = Path(__file__).resolve().parent / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip("'\"")
    return env


_ENV = {**_load_env_file(), **{k: v for k, v in os.environ.items() if v}}


def _cfg(name: str, default: str | None = None) -> str | None:
    return _ENV.get(name, default)


def provider() -> str:
    return (_cfg("LLM_PROVIDER") or "glm").lower()


def status() -> dict:
    """Что настроено сейчас (ключи маскируются)."""
    p = provider()
    info: dict = {"provider": p, "model": _model(p), "base": _base(p)}
    key, kname = _key(p)
    info["key_var"] = kname
    info["key_masked"] = (key[:10] + "…" + key[-4:]) if key else None
    return info


def _key(p: str) -> tuple[str | None, str]:
    if p == "glm":
        for n in ("GLM_API_KEY", "ZAI_API_KEY"):
            if _cfg(n):
                return _cfg(n), n
        return None, "GLM_API_KEY"
    if p == "anthropic":
        for n in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"):
            if _cfg(n):
                return _cfg(n), n
        return None, "ANTHROPIC_AUTH_TOKEN"
    if p == "openai":
        return _cfg("OPENAI_API_KEY"), "OPENAI_API_KEY"
    raise ValueError(f"неизвестный провайдер: {p}")


def _base(p: str) -> str:
    if p == "glm":
        return (_cfg("GLM_BASE_URL") or "https://api.z.ai/api/paas/v4").rstrip("/")
    if p == "anthropic":
        return (_cfg("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
    if p == "openai":
        return (_cfg("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    raise ValueError(p)


def _model(p: str) -> str:
    if _cfg("LLM_MODEL"):
        return _cfg("LLM_MODEL")
    return {
        "glm": "glm-4.6",
        "anthropic": "claude-sonnet-4-5",
        "openai": "gpt-4o",
    }[p]


def models_chain() -> list[str]:
    """Цепочка моделей: основная (дешёвая) → фолбэк (LLM_FALLBACK_MODEL)."""
    primary = _model(provider())
    fb = _cfg("LLM_FALLBACK_MODEL")
    chain = [primary]
    if fb and fb != primary:
        chain.append(fb)
    return chain


def _post(url: str, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"HTTP {e.code} от {url}: {body}") from e


def _chat_openai_style(system: str, user: str, temperature: float, max_tokens: int, model: str) -> str:
    """OpenAI-совместимый протокол (glm, openai)."""
    key, _ = _key(provider())
    if not key:
        raise RuntimeError("API-ключ не задан")
    data = _post(
        _base(provider()) + "/chat/completions",
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )
    return data["choices"][0]["message"]["content"]


def _chat_anthropic(system: str, user: str, temperature: float, max_tokens: int, model: str) -> str:
    """Anthropic Messages API; совместимо и с прокси GLM (claude-buffet и др.)."""
    key, kname = _key("anthropic")
    if not key:
        raise RuntimeError("ANTHROPIC_AUTH_TOKEN/ANTHROPIC_API_KEY не задан")
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
        # AUTH_TOKEN идёт как Bearer, API_KEY — как x-api-key; шлём оба для прокси
        "Authorization": f"Bearer {key}",
    }
    if kname == "ANTHROPIC_API_KEY":
        headers["x-api-key"] = key
    data = _post(
        _base("anthropic") + "/v1/messages",
        headers,
        {
            "model": model,
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user}],
        },
    )
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts)


def chat(system: str, user: str, temperature: float = 0.7, max_tokens: int = 900,
         model: str | None = None) -> str:
    """Один вызов выбранного провайдера. Исключение — при ошибке сети/API."""
    p = provider()
    m = model or _model(p)
    if p == "anthropic":
        return _chat_anthropic(system, user, temperature, max_tokens, m)
    return _chat_openai_style(system, user, temperature, max_tokens, m)  # glm, openai
