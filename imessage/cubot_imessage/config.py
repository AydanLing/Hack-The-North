"""Bridge settings, all from the environment (see ../.env.example).

Nothing here talks to the network or imports numpy: `Settings.load()` is cheap enough to call from
the CLI's argument parsing so `--help` stays instant.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_BASE_URL = "https://api.linqapp.com/api/partner/v3"
DEFAULT_HANDOFF = os.path.join(REPO_ROOT, "cubot-v2", "handoff")
DEFAULT_DATA = os.path.join(REPO_ROOT, "imessage", "data")
DEFAULT_HEAD = os.path.join(DEFAULT_DATA, "intent_head.npz")
DEFAULT_CORPUS = os.path.join(DEFAULT_DATA, "utterances.jsonl")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_float(name: str, default: Optional[float]) -> Optional[float]:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_list(name: str) -> list[str]:
    return [p.strip() for p in _env(name).split(",") if p.strip()]


def load_dotenv(path: str = "") -> None:
    """Minimal KEY=VALUE loader. Real environment variables always win, so exporting overrides the file."""
    path = path or os.path.join(os.path.dirname(REPO_ROOT), ".env")
    for candidate in (path, os.path.join(REPO_ROOT, "imessage", ".env"), os.path.join(REPO_ROOT, ".env")):
        if not os.path.isfile(candidate):
            continue
        with open(candidate, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value
        return


@dataclass
class Settings:
    """Everything the bridge needs to run. `api_key` is only required for the paths that send."""

    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    from_number: str = ""
    webhook_token: str = ""
    webhook_secret: str = ""
    webhook_path: str = "/linq/webhook"
    allowed_senders: list[str] = field(default_factory=list)
    handoff_dir: str = DEFAULT_HANDOFF
    head_path: str = DEFAULT_HEAD
    corpus_path: str = DEFAULT_CORPUS
    host: str = "127.0.0.1"
    port: int = 8787
    executor: str = "dryrun"
    auto_reply: bool = True
    react_on_receive: bool = True
    viewer_base: str = ""
    min_margin: Optional[float] = None
    min_confidence: Optional[float] = None
    rate_limit_per_minute: int = 6
    timeout_s: float = 15.0

    @classmethod
    def load(cls, use_dotenv: bool = True) -> "Settings":
        if use_dotenv:
            load_dotenv()
        return cls(
            api_key=_env("LINQ_API_KEY"),
            base_url=_env("LINQ_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            from_number=_env("LINQ_FROM"),
            webhook_token=_env("LINQ_WEBHOOK_TOKEN"),
            webhook_secret=_env("LINQ_WEBHOOK_SECRET"),
            webhook_path=_env("BRIDGE_WEBHOOK_PATH", "/linq/webhook"),
            allowed_senders=_env_list("LINQ_ALLOWED_SENDERS"),
            handoff_dir=_env("CUBOT_HANDOFF_DIR", DEFAULT_HANDOFF),
            head_path=_env("CUBOT_INTENT_HEAD", DEFAULT_HEAD),
            corpus_path=_env("CUBOT_INTENT_CORPUS", DEFAULT_CORPUS),
            host=_env("BRIDGE_HOST", "127.0.0.1"),
            port=int(_env("BRIDGE_PORT", "8787")),
            executor=_env("BRIDGE_EXECUTOR", "dryrun"),
            auto_reply=_env_bool("BRIDGE_AUTO_REPLY", True),
            react_on_receive=_env_bool("BRIDGE_REACT_ON_RECEIVE", True),
            viewer_base=_env("BRIDGE_VIEWER_BASE", ""),
            min_margin=_env_float("BRIDGE_MIN_MARGIN", None),
            min_confidence=_env_float("BRIDGE_MIN_CONFIDENCE", None),
            rate_limit_per_minute=int(_env("BRIDGE_RATE_LIMIT_PER_MINUTE", "6")),
            timeout_s=float(_env("LINQ_TIMEOUT_S", "15")),
        )

    def describe(self) -> list[tuple[str, str]]:
        """(label, value) rows for `cubot-imessage doctor`; the API key is never printed in full."""
        key = f"set ({len(self.api_key)} chars, ...{self.api_key[-4:]})" if self.api_key else "MISSING"
        return [
            ("Linq API key", key),
            ("Linq base URL", self.base_url),
            ("sending number", self.from_number or "(let Linq choose)"),
            ("webhook signing secret", "set (signatures verified)" if self.webhook_secret
             else "MISSING (falls back to the URL token alone)"),
            ("webhook token", "set" if self.webhook_token
             else ("not set (fine, signatures are verified)" if self.webhook_secret
                   else "MISSING (endpoint would be open)")),
            ("webhook path", self.webhook_path),
            ("allowed senders", ", ".join(self.allowed_senders) or "(any)"),
            ("handoff dir", self.handoff_dir),
            ("intent head", self.head_path if os.path.exists(self.head_path)
             else f"{self.head_path} (MISSING — run python3 -m cubot_imessage.model.train)"),
            ("corpus", self.corpus_path),
            ("listen", f"{self.host}:{self.port}"),
            ("executor", self.executor),
            ("auto-reply", "on" if self.auto_reply else "off"),
            ("react on receive", "👍 like" if self.react_on_receive else "off"),
            ("rate limit", f"{self.rate_limit_per_minute}/min per sender"),
        ]
