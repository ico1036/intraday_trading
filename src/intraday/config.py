"""
Configuration utilities for intraday_trading.

This module centralizes environment/config loading so runtime scripts and tests do
not rely on hardcoded absolute paths.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable
import os

try:
    # Optional dependency, loaded in project runtime.
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - fallback when dependency is unavailable
    load_dotenv = None


@lru_cache(maxsize=1)
def load_environment(dotenv_path: str | None = None) -> None:
    """Load .env once if available.

    Returns silently even when dotenv is not installed. This keeps import-time usage
    deterministic across environments.
    """
    if dotenv_path:
        path = Path(dotenv_path)
        if path.exists() and load_dotenv:
            load_dotenv(path)
        return

    # 기본 위치: 프로젝트 루트(.env)
    default_dotenv = Path(__file__).resolve().parents[2] / ".env"
    if default_dotenv.exists() and load_dotenv:
        load_dotenv(default_dotenv)


def get_project_root() -> Path:
    """Return repository root for this package."""
    # intraday_trading/src/intraday/config.py -> project root two levels up
    return Path(__file__).resolve().parents[2]


def env_path(name: str, *, default: str | None = None) -> Path | None:
    """Get a path-style env value.

    Expands user home and environment variables.
    """
    load_environment()
    value = os.getenv(name)
    if value is None:
        value = default
    if value is None:
        return None

    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        expanded = get_project_root() / expanded
    return expanded


def env_list(name: str, *, default: Iterable[str] | None = None) -> list[str]:
    """Get a comma separated env list."""
    load_environment()
    value = os.getenv(name)
    if value is None:
        value = ",".join(default) if default else ""
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def get_default_config_path() -> Path:
    """Path to timeframe config YAML (env override first)."""
    env = env_path("INTRADAY_CONFIG_PATH")
    if env is not None:
        return env
    return get_project_root() / "config" / "timeframes.yaml"


def get_default_data_dir() -> Path:
    """Base data directory for historical data.

    Priority:
      1) INTRADAY_DATA_DIR env
      2) project_root/data
    """
    data_dir = env_path("INTRADAY_DATA_DIR")
    if data_dir is not None:
        return data_dir

    return get_project_root() / "data"
