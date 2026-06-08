"""
Configuration loader — reads config.yaml then applies .env overrides.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# Load .env once at import time
load_dotenv(override=False)

_PROJECT_ROOT = Path(__file__).parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic models for config.yaml schema
# ─────────────────────────────────────────────────────────────────────────────

class EndpointConfig(BaseModel):
    category: str
    endpoint: str
    enabled: bool = True


class FilterConfig(BaseModel):
    min_classification: str = ""
    keywords: list[str] = Field(default_factory=list)
    states: list[str] = Field(default_factory=list)


class EmailConfig(BaseModel):
    enabled: bool = False
    to: list[str] = Field(default_factory=list)


class SlackConfig(BaseModel):
    enabled: bool = False


class WebhookConfig(BaseModel):
    enabled: bool = False


class NotificationConfig(BaseModel):
    notify_all: bool = False
    notify_class_i: bool = True
    notify_class_ii: bool = False
    email: EmailConfig = Field(default_factory=EmailConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)


class AgentSection(BaseModel):
    schedule_cron: str = "0 */6 * * *"
    initial_lookback_days: int = 30
    max_records_per_poll: int = 500
    db_path: str = "data/recalls.db"
    log_path: str = "data/recalls.ndjson"
    report_path: str = "data/report.html"


class LoggingSection(BaseModel):
    level: str = "INFO"
    format: str = "rich"


class RawConfig(BaseModel):
    agent: AgentSection = Field(default_factory=AgentSection)
    endpoints: list[EndpointConfig] = Field(default_factory=list)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    logging: LoggingSection = Field(default_factory=LoggingSection)


# ─────────────────────────────────────────────────────────────────────────────
# AgentConfig — the public interface
# ─────────────────────────────────────────────────────────────────────────────

class AgentConfig:
    """Loads config.yaml and resolves environment variable overrides."""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        cfg_file = config_path or (_PROJECT_ROOT / "config.yaml")
        if cfg_file.exists():
            with open(cfg_file, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = {}

        self._raw = RawConfig.model_validate(raw)
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Allow env vars to override config.yaml values."""
        if v := os.getenv("FDA_MONITOR_SCHEDULE_CRON"):
            self._raw.agent.schedule_cron = v
        if v := os.getenv("FDA_MONITOR_DB_PATH"):
            self._raw.agent.db_path = v
        if v := os.getenv("FDA_MONITOR_LOG_LEVEL"):
            self._raw.logging.level = v

    # ── Convenience accessors ─────────────────────────────────────────────────

    @property
    def schedule_cron(self) -> str:
        return self._raw.agent.schedule_cron

    @property
    def initial_lookback_days(self) -> int:
        return self._raw.agent.initial_lookback_days

    @property
    def max_records_per_poll(self) -> int:
        return self._raw.agent.max_records_per_poll

    @property
    def db_path(self) -> Path:
        p = Path(self._raw.agent.db_path)
        return p if p.is_absolute() else _PROJECT_ROOT / p

    @property
    def log_path(self) -> Path:
        p = Path(self._raw.agent.log_path)
        return p if p.is_absolute() else _PROJECT_ROOT / p

    @property
    def report_path(self) -> Path:
        p = Path(self._raw.agent.report_path)
        return p if p.is_absolute() else _PROJECT_ROOT / p

    @property
    def active_endpoints(self) -> list[EndpointConfig]:
        return [e for e in self._raw.endpoints if e.enabled]

    @property
    def filters(self) -> FilterConfig:
        return self._raw.filters

    @property
    def notifications(self) -> NotificationConfig:
        return self._raw.notifications

    @property
    def log_level(self) -> str:
        return self._raw.logging.level.upper()

    @property
    def fda_api_key(self) -> Optional[str]:
        return os.getenv("FDA_API_KEY") or None

    @property
    def smtp_host(self) -> str:
        return os.getenv("SMTP_HOST", "smtp.gmail.com")

    @property
    def smtp_port(self) -> int:
        return int(os.getenv("SMTP_PORT", "587"))

    @property
    def smtp_user(self) -> Optional[str]:
        return os.getenv("SMTP_USER")

    @property
    def smtp_password(self) -> Optional[str]:
        return os.getenv("SMTP_PASSWORD")

    @property
    def email_from(self) -> str:
        return os.getenv("EMAIL_FROM", "FDA Recall Monitor")

    @property
    def email_to(self) -> list[str]:
        raw = os.getenv("EMAIL_TO", "")
        env_list = [x.strip() for x in raw.split(",") if x.strip()]
        return env_list or self._raw.notifications.email.to

    @property
    def slack_webhook_url(self) -> Optional[str]:
        return os.getenv("SLACK_WEBHOOK_URL") or None

    @property
    def webhook_url(self) -> Optional[str]:
        return os.getenv("WEBHOOK_URL") or None
