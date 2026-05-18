from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_openai_endpoint: str = Field(default="")
    azure_openai_api_key: str = Field(default="")
    azure_openai_deployment: str = Field(default="gpt-4o")
    azure_openai_api_version: str = Field(default="2024-10-21")

    doc_intel_endpoint: str = Field(default="")
    doc_intel_api_key: str = Field(default="")

    data_dir: str = Field(default="./data")
    cors_origins: str = Field(default="http://localhost:5173")
    max_upload_mb: int = Field(default=50)

    tile_threshold_px: int = Field(default=2400)
    tile_size_px: int = Field(default=2048)
    tile_overlap_px: int = Field(default=256)

    llm_temperature: float = Field(default=0.0)
    llm_top_p: float = Field(default=1.0)
    llm_seed: int = Field(default=42)
    llm_max_tokens: int = Field(default=4096)

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).resolve()

    @property
    def analyses_dir(self) -> Path:
        p = self.data_path / "analyses"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads_dir(self) -> Path:
        p = self.data_path / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_available(self) -> bool:
        return bool(self.azure_openai_api_key and self.azure_openai_endpoint)

    @property
    def doc_intel_available(self) -> bool:
        return bool(self.doc_intel_api_key and self.doc_intel_endpoint)


@lru_cache
def get_settings() -> Settings:
    return Settings()
