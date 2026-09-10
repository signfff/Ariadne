"""Configuration - env vars and defaults."""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv():
    """Load .env from cwd, walking up to home dir. No-op if python-dotenv missing."""
    try:
        from dotenv import load_dotenv
        # search cwd first, then parent dirs up to ~
        env_path = Path(".env")
        if not env_path.exists():
            cur = Path.cwd()
            home = Path.home()
            while cur != home and cur != cur.parent:
                candidate = cur / ".env"
                if candidate.exists():
                    env_path = candidate
                    break
                cur = cur.parent
        load_dotenv(env_path, override=False)
    except ImportError:
        pass  # python-dotenv not installed, silently skip


@dataclass
class Config:
    model: str = "gpt-5.5"
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    max_context_tokens: int = 128_000
    provider: str = "openai"

    @classmethod
    def from_env(cls) -> "Config":
        # load .env if present (won't override existing env vars)
        _load_dotenv()
        # pick up common env vars automatically
        api_key = (
            os.getenv("ARIADNE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("ANTHROPIC_AUTH_TOKEN")
            or os.getenv("ANTHROPIC_API_KEY")
            or ""
        )
        base_url = (
            os.getenv("OPENAI_BASE_URL")
            or os.getenv("ARIADNE_BASE_URL")
            or _openai_compatible_base_url(os.getenv("ANTHROPIC_BASE_URL"))
        )
        return cls(
            model=os.getenv("ARIADNE_MODEL") or os.getenv("ANTHROPIC_MODEL") or "gpt-5.5",
            api_key=api_key,
            base_url=base_url,
            max_tokens=int(os.getenv("ARIADNE_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("ARIADNE_TEMPERATURE", "0")),
            max_context_tokens=int(os.getenv("ARIADNE_MAX_CONTEXT", "128000")),
            provider=os.getenv("ARIADNE_PROVIDER", "openai"),
        )


def _openai_compatible_base_url(base_url: str | None) -> str | None:
    """Accept Claude/Anthropic-style env vars when the host also speaks OpenAI.

    Ariadne's default LLM backend uses OpenAI-compatible Chat Completions.
    Some users already have Claude Code style variables such as
    ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic. DeepSeek exposes the
    same account through an OpenAI-compatible root URL, so remove the Anthropic
    suffix before passing the URL to the OpenAI SDK.
    """
    if not base_url:
        return None
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/anthropic"):
        return trimmed[: -len("/anthropic")]
    return trimmed
