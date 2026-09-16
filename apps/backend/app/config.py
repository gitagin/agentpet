import os
import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
    reranker_local_model_dir: Path | None = Field(
        default=None,
        alias="AGENT_PET_RERANKER_LOCAL_DIR",
    )
    model_timeout_seconds: float = Field(
        default=30.0,
        alias="AGENT_PET_MODEL_TIMEOUT_SECONDS",
    )
    # ---- 调参面：此前散落为各模块魔数，收敛到此以便 env/后续 UI 覆盖 ----
    tuning_rrf_k: int = Field(default=60, alias="AGENT_PET_TUNING_RRF_K")
    tuning_fts_exact_weight: float = Field(default=3.0, alias="AGENT_PET_TUNING_FTS_EXACT_WEIGHT")
    # 知识候选在场时,聊天日记回声的融合分数乘数(<1 让位知识,>0 保留
    # 历史作为唯一答案来源的能力)。scripts/tune-retrieval-params.py 的实测:
    # 排序指标上看不出收益(1.0/0.7/0.6/0.5 同分,0.3 才开始伤 hit@5 与连续性);
    # 但同一脚本的回答层面探针(证据门 → 引用 → 提示词的答案上下文,跟踪被回放的
    # 那条日记块)显示:没有上一轮时降权把"日记作为答案上下文"的查询数从 13 条
    # 降到 7(0.6)、0(0.3),而知识上下文在 0.6 仍为 13/13、到 0.3 才掉到 12 且
    # 连续性守卫归零。0.6 的依据是"回声注入面减半、知识与连续性不受影响"。
    # 逐字剔除回声另有更精确的一道(events_helpers._echoes_recent_turn):有上一轮
    # 时它把该块从 13 条降到 5 条(1.0)/ 7 降到 1(0.6)。
    tuning_daily_echo_weight: float = Field(default=0.6, alias="AGENT_PET_TUNING_DAILY_ECHO_WEIGHT")
    tuning_habit_quiet_start_hour: int = Field(default=22, alias="AGENT_PET_TUNING_HABIT_QUIET_START_HOUR")
    tuning_habit_quiet_end_hour: int = Field(default=8, alias="AGENT_PET_TUNING_HABIT_QUIET_END_HOUR")
    tuning_habit_daily_limit: int | None = Field(default=None, alias="AGENT_PET_TUNING_HABIT_DAILY_LIMIT")
    tuning_habit_cooldown_minutes: int | None = Field(default=None, alias="AGENT_PET_TUNING_HABIT_COOLDOWN_MINUTES")
    tuning_chat_retry_attempts: int = Field(default=1, alias="AGENT_PET_TUNING_CHAT_RETRY_ATTEMPTS")
    tuning_chat_retry_backoff_seconds: float = Field(default=1.0, alias="AGENT_PET_TUNING_CHAT_RETRY_BACKOFF_SECONDS")
    tuning_post_reply_max_attempts: int = Field(default=3, alias="AGENT_PET_TUNING_POST_REPLY_MAX_ATTEMPTS")
    tuning_post_reply_lease_seconds: int = Field(default=300, alias="AGENT_PET_TUNING_POST_REPLY_LEASE_SECONDS")
    tts_timeout_seconds: float = Field(
        default=8.0,
        alias="AGENT_PET_TTS_TIMEOUT_SECONDS",
    )

    model_config = SettingsConfigDict(extra="ignore")

    @field_validator("embedding_local_model_dir", "reranker_local_model_dir", "database_path", mode="before")
    @classmethod
    def _empty_path_env_to_none(cls, value):
        # 空字符串环境变量（如 AGENT_PET_EMBEDDING_LOCAL_DIR=""）会被解析成
        # Path(".")（当前目录）而不是"未设置"，导致模型目录解析错位。
        if isinstance(value, str) and not value.strip():
            return None
        return value

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

    @property
    def local_reranker_dir(self) -> Path:
        if self.reranker_local_model_dir is not None:
            return self.reranker_local_model_dir
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "models" / "reranker"
        return Path(__file__).resolve().parents[1] / "models" / "reranker"


@lru_cache
def get_settings() -> Settings:
    return Settings()
