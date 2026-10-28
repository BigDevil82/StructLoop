"""Small OpenAI-compatible university gateway client using only the stdlib."""
from __future__ import annotations

import json
from functools import partial
import os
from pathlib import Path
import time
import traceback
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request

from pydantic import Field, SecretStr, model_validator
from struct_agent.io.artifacts import write_json
from struct_agent.schemas.base import Contract


class ChatConfig(Contract):
    base_url: str = "https://agi.tongji.edu.cn/v1"
    model: str = "DeepSeek-V4.1-Flash"
    api_key_env: str = "apikey"
    timeout_s: float = Field(default=45., gt=0., le=60.)
    max_tokens: int = Field(default=1024, ge=32, le=8192)
    max_attempts: int = Field(default=2, ge=1, le=3)
    temperature: float = Field(default=0., ge=0., le=2.)
    use_system_proxy: bool = False

    @model_validator(mode="after")
    def secure_url(self) -> ChatConfig:
        url = urllib.parse.urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Gateway must be a credential-free HTTPS base URL")
        return self


def read_api_key(path: Path, name: str) -> SecretStr:
    """Read one literal dotenv field; no interpolation, shell execution or env mutation."""
    value = os.environ.get(name)
    if value is None and path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, candidate = line.removeprefix("export ").partition("=")
            if sep and key.strip() == name:
                candidate = candidate.strip()
                if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in "\"'":
                    candidate = candidate[1:-1]
                value = candidate
    if not value or any(c.isspace() for c in value):
        raise ValueError(f"Missing/invalid credential field {name}; values are never displayed")
    return SecretStr(value)


class GatewayError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, error_type: str = "GatewayError") -> None:
        super().__init__(message)
        self.status, self.error_type = status, error_type


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None  # Never forward an Authorization header to a redirected host.


Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def http_chat(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float,
              *, use_system_proxy: bool = False) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        handlers = [NoRedirect()] if use_system_proxy else [urllib.request.ProxyHandler({}), NoRedirect()]
        with urllib.request.build_opener(*handlers).open(request, timeout=timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise GatewayError("Gateway response exceeds audit size limit")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise GatewayError("Gateway did not return an object")
        return result
    except urllib.error.HTTPError as exc:
        excerpt = exc.read(2048).decode("utf-8", errors="replace")
        raise GatewayError(f"HTTP {exc.code}: {excerpt}", status=exc.code, error_type="HTTPError") from exc


class ChatClient:
    def __init__(self, config: ChatConfig, key: SecretStr, directory: Path, *, transport: Transport | None = None) -> None:
        directory.mkdir(parents=True, exist_ok=False)
        self.config, self._key, self.directory = config, key, directory
        self.transport = transport or partial(http_chat, use_system_proxy=config.use_system_proxy)
        self.calls = 0
        self.total_tokens = 0
        self.usage_missing_calls = 0

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(self._key.get_secret_value(), "[REDACTED]")
        if isinstance(value, dict):
            return {self.redact(str(k)): self.redact(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [self.redact(v) for v in value]
        return value

    def complete(self, messages: list[dict[str, str]]) -> str:
        payload = {"model": self.config.model, "messages": messages, "temperature": self.config.temperature,
                   "max_tokens": self.config.max_tokens, "stream": False}
        for attempt in range(1, self.config.max_attempts + 1):
            self.calls += 1
            started = time.perf_counter()
            audit: dict[str, Any] = {"request": payload, "attempt": attempt, "endpoint": self.config.base_url,
                                     "use_system_proxy": self.config.use_system_proxy}
            try:
                response = self.transport(self.config.base_url.rstrip("/") + "/chat/completions",
                    {"Authorization": "Bearer " + self._key.get_secret_value(), "Content-Type": "application/json",
                     "User-Agent": "StructLoop/0.1"}, payload, self.config.timeout_s)
                content = response["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise GatewayError("Gateway message content is not text")
                usage = response.get("usage", {})
                tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
                if type(tokens) is int and tokens >= 0:
                    self.total_tokens += tokens
                else:
                    self.usage_missing_calls += 1
                audit["response"] = {"content": content, "usage": usage, "model": response.get("model"),
                    "id": response.get("id"), "finish_reason": response["choices"][0].get("finish_reason")}
            except Exception as exc:
                status = exc.status if isinstance(exc, GatewayError) else None
                audit["error"] = {"type": getattr(exc, "error_type", type(exc).__name__), "message": str(exc),
                                  "status": status, "traceback": traceback.format_exc()}
                audit["elapsed_s"] = time.perf_counter() - started
                write_json(self.directory / f"call_{self.calls:05d}.json", self.redact(audit))
                retryable = status in (429, 500, 502, 503, 504) or isinstance(exc, (TimeoutError, urllib.error.URLError))
                if retryable and attempt < self.config.max_attempts:
                    continue
                raise GatewayError(self.redact(str(exc)), status=status,
                                   error_type=getattr(exc, "error_type", type(exc).__name__)) from None
            audit["elapsed_s"] = time.perf_counter() - started
            write_json(self.directory / f"call_{self.calls:05d}.json", self.redact(audit))
            return self.redact(content)
        raise AssertionError("Unreachable retry branch")
