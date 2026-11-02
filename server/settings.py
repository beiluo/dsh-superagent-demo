"""Server-side configuration.

The LLM key is read from the process environment (or a local, git-ignored
``.env`` file for development).  It is never sent to the browser, never
embedded in a prompt and never included in an API response.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ALLOWED_ORIGINS = (
    "https://beiluo.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def _load_dotenv(path: Path) -> None:
    """Load a minimal ``.env`` without overriding real environment values.

    This intentionally does not implement shell interpolation.  Keep the
    format boring: ``KEY=value``, one pair per line, optional quotes.
    """

    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value.strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = float(value.strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None:
        return default
    items = tuple(item.strip().rstrip("/") for item in value.split(",") if item.strip())
    return items or default


@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    llm_api_key: str = field(default="", repr=False)
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_enabled: bool = True
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 900
    llm_temperature: float = 0.2
    agent_max_steps: int = 4
    agent_max_tool_calls: int = 6
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    rate_limit_per_minute: int = 6
    rate_limit_per_hour: int = 40
    daily_request_budget: int = 300
    max_question_chars: int = 500
    max_history_items: int = 4
    max_history_chars: int = 2400
    max_request_bytes: int = 24_000
    max_concurrency: int = 4
    trust_proxy: bool = False
    serve_static: bool = True
    market_data_enabled: bool = True
    market_data_timeout_seconds: float = 8.0
    market_data_quote_ttl_seconds: int = 60
    market_data_financial_ttl_seconds: int = 21_600

    @property
    def configured(self) -> bool:
        """True when the server should attempt to call the LLM."""

        return bool(self.llm_enabled and self.llm_api_key.strip())

    @property
    def chat_completions_url(self) -> str:
        return f"{self.llm_base_url.rstrip('/')}/chat/completions"

    @property
    def provider(self) -> str:
        host = (urlparse(self.llm_base_url).hostname or "").lower()
        if "deepseek" in host:
            return "deepseek"
        if "openai" in host:
            return "openai"
        if "moonshot" in host:
            return "moonshot"
        if "dashscope" in host or "aliyun" in host:
            return "dashscope"
        return host or "custom"

    @classmethod
    def from_env(cls, root: Path | None = None) -> "Settings":
        base = root or ROOT
        _load_dotenv(base / ".env")
        return cls(
            root=base,
            llm_api_key=os.environ.get("LLM_API_KEY", "").strip(),
            llm_base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").strip(),
            llm_model=os.environ.get("LLM_MODEL", "deepseek-chat").strip(),
            llm_enabled=_env_bool("LLM_ENABLED", True),
            llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 60.0, minimum=5.0),
            llm_max_output_tokens=_env_int("LLM_MAX_OUTPUT_TOKENS", 900, minimum=128),
            llm_temperature=_env_float("LLM_TEMPERATURE", 0.2, minimum=0.0),
            agent_max_steps=_env_int("AGENT_MAX_STEPS", 4, minimum=1),
            agent_max_tool_calls=_env_int("AGENT_MAX_TOOL_CALLS", 6, minimum=1),
            allowed_origins=_env_csv("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS),
            rate_limit_per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 6, minimum=1),
            rate_limit_per_hour=_env_int("RATE_LIMIT_PER_HOUR", 40, minimum=1),
            daily_request_budget=_env_int("DAILY_REQUEST_BUDGET", 300, minimum=1),
            max_question_chars=_env_int("MAX_QUESTION_CHARS", 500, minimum=20),
            max_history_items=_env_int("MAX_HISTORY_ITEMS", 4, minimum=0),
            max_history_chars=_env_int("MAX_HISTORY_CHARS", 2400, minimum=0),
            max_request_bytes=_env_int("MAX_REQUEST_BYTES", 24_000, minimum=1_000),
            max_concurrency=_env_int("MAX_CONCURRENCY", 4, minimum=1),
            trust_proxy=_env_bool("TRUST_PROXY", False),
            serve_static=_env_bool("SERVE_STATIC", True),
            market_data_enabled=_env_bool("MARKET_DATA_ENABLED", True),
            market_data_timeout_seconds=_env_float("MARKET_DATA_TIMEOUT_SECONDS", 8.0, minimum=2.0),
            market_data_quote_ttl_seconds=_env_int("MARKET_DATA_QUOTE_TTL_SECONDS", 60, minimum=0),
            market_data_financial_ttl_seconds=_env_int(
                "MARKET_DATA_FINANCIAL_TTL_SECONDS", 21_600, minimum=300
            ),
        )
