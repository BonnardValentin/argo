from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    github_token: str | None
    anthropic_api_key: str | None
    extraction_model: str
    data_dir: Path
    redis_url: str
    redis_index_name: str

    @classmethod
    def load(cls) -> "Settings":
        raw_data_dir = os.getenv("ARGOS_DATA_DIR", "./data/knowledge")
        data_dir = Path(raw_data_dir)
        if not data_dir.is_absolute():
            data_dir = (PROJECT_ROOT / data_dir).resolve()
        data_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            github_token=os.getenv("GITHUB_TOKEN") or None,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            extraction_model=os.getenv(
                "ARGOS_EXTRACTION_MODEL", "claude-haiku-4-5-20251001"
            ),
            data_dir=data_dir,
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            redis_index_name=os.getenv("ARGOS_REDIS_INDEX", "argos-nodes"),
        )


settings = Settings.load()
