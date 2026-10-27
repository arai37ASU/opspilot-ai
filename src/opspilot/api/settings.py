"""API configuration, read from environment variables (and .env when present)."""

import os
from dataclasses import dataclass
from pathlib import Path

from opspilot.db.connection import database_url


@dataclass(frozen=True)
class Settings:
    database_url: str
    model_dir: Path  # fitted pipeline and its metadata, from opspilot.modeling.train
    reports_dir: Path  # saved evaluation results, from the modeling commands
    pool_max_size: int = 5

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=database_url(),
            model_dir=Path(os.environ.get("OPSPILOT_MODEL_DIR", "models")),
            reports_dir=Path(os.environ.get("OPSPILOT_REPORTS_DIR", "reports/modeling")),
            pool_max_size=int(os.environ.get("OPSPILOT_POOL_MAX_SIZE", "5")),
        )
