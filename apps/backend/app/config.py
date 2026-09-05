import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CHAT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_BASE_URL = "https://api.openai.com/v1"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def _default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / "AgentPet"
    return Path.home() / ".agent-pet"


class Settings(BaseSettings):
    app_name: str = "Agent Pet Backend"
    app_version: str = "0.0.1-alpha"
    environment: str = "development"
    session_token: str | None = Field(default=None, alias="AGENT_PET_SESSION_TOKEN")
    data_dir: Path = Field(default_factory=_default_data_dir, alias="AGENT_PET_DATA_DIR")
    database_path: Path | None = Field(default=None, alias="AGENT_PET_SQLITE_PATH")
    model_base_url: str = Field(
        default=DEFAULT_CHAT_BASE_URL,
        alias="AGENT_PET_MODEL_BASE_URL",
    )
    chat_model: str = Field(default=DEFAULT_CHAT_MODEL, alias="AGENT_PET_CHAT_MODEL")
    embedding_base_url: str = Field(
        default=DEFAULT_EMBEDDING_BASE_URL,
        alias="AGENT_PET_EMBEDDING_BASE_URL",
    )
    embedding_model: str = Field(default=DEFAULT_EMBEDDING_MODEL, alias="AGENT_PET_EMBEDDING_MODEL")
    embedding_dimensions: int | None = Field(default=None, alias="AGENT_PET_EMBEDDING_DIMENSIONS")
    embedding_local_model_dir: Path | None = Field(
        default=None,
        alias="AGENT_PET_EMBEDDING_LOCAL_DIR",
    )
    model_timeout_seconds: float = Field(
        default=30.0,
        alias="AGENT_PET_MODEL_TIMEOUT_SECONDS",
    )
    tts_timeout_seconds: float = Field(
        default=8.0,
        alias="AGENT_PET_TTS_TIMEOUT_SECONDS",
    )

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def sqlite_path(self) -> Path:
        return self.database_path or self.data_dir / "agent_pet.sqlite3"

    @property
    def local_embedding_dir(self) -> Path:
        # 源树：apps/backend/models/embedding；打包：sidecar exe 同级的 models/embedding。
        # 用 __file__/sys.executable 锚定而非 cwd，避免 pytest 从仓库根运行时解析错位。
        if self.embedding_local_model_dir is not None:
            return self.embedding_local_model_dir
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "models" / "embedding"
        return Path(__file__).resolve().parents[1] / "models" / "embedding"


@lru_cache
def get_settings() -> Settings:
    return Settings()
