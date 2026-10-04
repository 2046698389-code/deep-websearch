import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml

SOURCE_NAMES = ("youtube", "reddit", "x", "bilibili", "douyin", "brave", "searxng",
                "exa", "tavily", "serper", "serpapi")


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Literal["auto"] | bool = "auto"
    options: dict = Field(default_factory=dict)


class SearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rounds: int = Field(default=2, ge=1, le=4)
    max_queries: int = Field(default=48, ge=1, le=100)
    max_results: int = Field(default=200, ge=1, le=1000)
    per_query_limit: int = Field(default=10, ge=1, le=50)
    concurrency: int = Field(default=4, ge=1, le=16)
    timeout_seconds: float = Field(default=20, ge=1, le=120)
    max_requests: int = Field(default=200, ge=1, le=1000)
    retries: int = Field(default=1, ge=0, le=3)


class NotificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    desktop: Literal["auto"] | bool = "auto"


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: dict[str, SourceConfig] = Field(
        default_factory=lambda: {name: SourceConfig() for name in SOURCE_NAMES})
    search: SearchConfig = Field(default_factory=SearchConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    env: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)

    @field_validator("sources")
    @classmethod
    def complete_sources(cls, value):
        unknown = set(value) - set(SOURCE_NAMES)
        if unknown:
            raise ValueError("Unknown sources: " + ", ".join(sorted(unknown)))
        return {name: value.get(name, SourceConfig()) for name in SOURCE_NAMES}


def load_settings(config_path: str | Path | None = None, env_file: str | Path | None = None) -> Settings:
    home = Path(os.environ.get("DEEP_WEBSEARCH_HOME", Path.cwd())).resolve()
    explicit_config = config_path or os.environ.get("DEEP_WEBSEARCH_CONFIG")
    path = Path(explicit_config) if explicit_config else home / "config.yaml"
    data = {}
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or "env" in data:
            raise ValueError("Configuration must be a YAML mapping; store credentials in .env")
    elif explicit_config:
        raise ValueError("Configured YAML file does not exist")
    explicit_env = env_file or os.environ.get("DEEP_WEBSEARCH_ENV_FILE")
    env_path = Path(explicit_env) if explicit_env else home / ".env"
    if explicit_env and not env_path.is_file():
        raise ValueError("Configured env file does not exist")
    # Existing process environment wins; credentials never enter model_dump or reports.
    values = {k: v for k, v in dotenv_values(env_path).items() if v is not None} if env_path.is_file() else {}
    values.update(os.environ)
    return Settings(**data, env=values)
