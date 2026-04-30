from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = base_dir / "data"
    upload_dir: Path = base_dir / "uploads"
    template_dir: Path = base_dir / "weiren" / "templates"
    static_dir: Path = base_dir / "weiren" / "static"
    database_path: Path = data_dir / "weiren.db"
    app_title: str = "伪人"
    max_upload_size: int = 50 * 1024 * 1024  # 50 MB per file


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
