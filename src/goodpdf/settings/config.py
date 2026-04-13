from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppConfig:
    workspace_dir: Path
    default_llm_api_base: str = "https://api.openai.com/v1"
    default_llm_model: str = "gpt-4o-mini"
    settings_organization: str = "GoodPDF"
    settings_application: str = "GoodPDF"
    keyring_service: str = "GoodPDF"
    keyring_username: str = "llm_api_key"

    @classmethod
    def default(cls) -> "AppConfig":
        documents_dir = Path.home() / "Documents"
        base_dir = documents_dir if documents_dir.exists() else Path.home()
        return cls(workspace_dir=base_dir / "GoodPDF")
