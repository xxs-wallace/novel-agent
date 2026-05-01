from __future__ import annotations

import os
from pathlib import Path

from .constants import DEFAULT_DB_PATH


def repo_root_default() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_repo_root(repo_root: str | None = None) -> Path:
    if repo_root:
        return Path(repo_root).expanduser().resolve()
    env_value = os.getenv('NOVEL_AGENT_REPO_ROOT')
    if env_value:
        return Path(env_value).expanduser().resolve()
    return repo_root_default()


def resolve_db_path(repo_root: Path, db_path: str | None = None) -> Path:
    if db_path:
        return Path(db_path).expanduser().resolve()
    env_value = os.getenv('NOVEL_AGENT_INDEX_DB')
    if env_value:
        return Path(env_value).expanduser().resolve()
    return (repo_root / DEFAULT_DB_PATH).resolve()


def read_api_key(api_key: str | None = None, api_key_file: str | None = None, env_name: str | None = None) -> str | None:
    if api_key:
        return api_key.strip()
    if api_key_file:
        path = Path(api_key_file).expanduser().resolve()
        if path.exists():
            return path.read_text(encoding='utf-8', errors='replace').strip()
    if env_name and os.getenv(env_name):
        return str(os.getenv(env_name)).strip()
    return None
