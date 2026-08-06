from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.config import DEFAULT_CHAT_MODEL, get_settings
from app.models.config import AgentModelHealth, ModelHealthResponse
from app.models.enums import AgentId
from app.utils.time import utc_now_iso

from .settings_types import (
    AGENT_CREDENTIAL_SLOT,
    AGENT_MODEL_IDS,
    EMBEDDING_CREDENTIAL_SLOT,
    LEGACY_AGENT_MODEL_IDS,
    LEGACY_AGENT_MODEL_MIGRATIONS,
    MODEL_CREDENTIAL_SLOT,
    AgentModelSettings,
    ConfigurationError,
    CredentialSlot,
    CredentialStore,
    EmbeddingConfig,
    ModelConfig,
    ModelKeyStatus,
    credential_status,
    model_config_matches,
    normalize_agent_id,
    normalize_model_provider,
    read_credential,
    write_credential,
)


@dataclass(frozen=True, slots=True)
class ProviderConfigSlot:
    table: str
    includes_dimensions: bool = False


MODEL_CONFIG_SLOT = ProviderConfigSlot("model_config")
EMBEDDING_CONFIG_SLOT = ProviderConfigSlot("embedding_config", includes_dimensions=True)


class SettingsModelsMixin:
    """Model, embedding, and per-agent configuration persistence."""

    conn: sqlite3.Connection
    credentials: CredentialStore

    def _migrate_legacy_retrieval_agent_configs(self) -> None:
        for legacy_agent_id, target_agent_ids in LEGACY_AGENT_MODEL_MIGRATIONS:
            self._copy_legacy_agent_config(legacy_agent_id, target_agent_ids)
        placeholders = ",".join("?" for _agent_id in LEGACY_AGENT_MODEL_IDS)
        self.conn.execute(
            f"DELETE FROM agent_model_configs WHERE agent_id IN ({placeholders})",
            LEGACY_AGENT_MODEL_IDS,
        )

    def _copy_legacy_agent_config(
        self,
        legacy_agent_id: str,
        target_agent_ids: tuple[str, ...],
    ) -> None:
        legacy = self.conn.execute(
            """
            SELECT provider, base_url, model, credential_ref, enabled, created_at, updated_at
            FROM agent_model_configs WHERE agent_id = ?
            """,
            (legacy_agent_id,),
        ).fetchone()
        if legacy is None:
            return
        for target_agent_id in target_agent_ids:
            existing = self.conn.execute(
                "SELECT 1 FROM agent_model_configs WHERE agent_id = ?",
                (target_agent_id,),
            ).fetchone()
            if existing is not None:
                continue
            self.conn.execute(
                """
                INSERT INTO agent_model_configs
                    (agent_id, provider, base_url, model, masked, credential_ref,
                     enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    target_agent_id,
                    legacy["provider"],
                    legacy["base_url"],
                    legacy["model"],
                    legacy["credential_ref"],
                    legacy["enabled"],
                    legacy["created_at"],
                    legacy["updated_at"],
                ),
            )

    def _set_provider_credential(
        self,
        slot: CredentialSlot,
        provider: str,
        api_key: str,
    ) -> ModelKeyStatus:
        if slot not in {MODEL_CREDENTIAL_SLOT, EMBEDDING_CREDENTIAL_SLOT}:
            raise ValueError(f"unsupported provider credential slot: {slot.table}")
        normalized, credential_ref, status = write_credential(
            self.credentials,
            slot,
            provider,
            api_key,
        )
        now = utc_now_iso()
        self.conn.execute(
            f"""
            INSERT INTO {slot.table}
                ({slot.key_column}, masked, credential_ref, created_at, updated_at)
            VALUES (?, NULL, ?, ?, ?)
            ON CONFLICT({slot.key_column}) DO UPDATE SET
                masked = NULL,
                credential_ref = excluded.credential_ref,
                updated_at = excluded.updated_at
            """,
            (normalized, credential_ref, now, now),
        )
        self.conn.commit()
        return status

    def _get_provider_credential_status(self, slot: CredentialSlot) -> ModelKeyStatus:
        row = self.conn.execute(
            f"""
            SELECT {slot.key_column} AS provider, credential_ref
            FROM {slot.table}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return ModelKeyStatus(provider=None, configured=False)
        provider = str(row["provider"])
        return credential_status(
            self.credentials,
            slot,
            provider,
            str(row["credential_ref"]),
            provider=provider,
        )

    def _get_provider_credential(self, slot: CredentialSlot, provider: str) -> str | None:
        normalized = slot.normalize(provider)
        row = self.conn.execute(
            f"SELECT credential_ref FROM {slot.table} WHERE lower({slot.key_column}) = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        return read_credential(
            self.credentials,
            slot,
            normalized,
            str(row["credential_ref"]),
        )

    def set_model_key(self, provider: str, api_key: str) -> ModelKeyStatus:
        return self._set_provider_credential(MODEL_CREDENTIAL_SLOT, provider, api_key)

    def get_model_key_status(self) -> ModelKeyStatus:
        return self._get_provider_credential_status(MODEL_CREDENTIAL_SLOT)

    def get_model_key(self, provider: str) -> str | None:
        return self._get_provider_credential(MODEL_CREDENTIAL_SLOT, provider)

    def set_embedding_key(self, provider: str, api_key: str) -> ModelKeyStatus:
        return self._set_provider_credential(EMBEDDING_CREDENTIAL_SLOT, provider, api_key)

    def get_embedding_key_status(self) -> ModelKeyStatus:
        return self._get_provider_credential_status(EMBEDDING_CREDENTIAL_SLOT)

    def get_embedding_key(self, provider: str) -> str | None:
        return self._get_provider_credential(EMBEDDING_CREDENTIAL_SLOT, provider)

    def _set_provider_config(
        self,
        slot: ProviderConfigSlot,
        *,
        provider: str,
        base_url: str,
        model: str,
        dimensions: int | None = None,
    ) -> ModelConfig | EmbeddingConfig:
        normalized_provider = normalize_model_provider(provider)
        normalized_base_url = base_url.strip().rstrip("/")
        normalized_model = model.strip()
        now = utc_now_iso()
        values: tuple[object, ...]
        if slot.includes_dimensions:
            config: ModelConfig | EmbeddingConfig = EmbeddingConfig(
                provider=normalized_provider,
                base_url=normalized_base_url,
                model=normalized_model,
                dimensions=dimensions,
            )
            columns, values, updates = (
                "provider, base_url, model, dimensions",
                (normalized_provider, normalized_base_url, normalized_model, dimensions),
                "provider=excluded.provider, base_url=excluded.base_url, "
                "model=excluded.model, dimensions=excluded.dimensions",
            )
        else:
            config = ModelConfig(normalized_provider, normalized_base_url, normalized_model)
            columns, values, updates = (
                "provider, base_url, model",
                (normalized_provider, normalized_base_url, normalized_model),
                "provider=excluded.provider, base_url=excluded.base_url, model=excluded.model",
            )
        placeholders = ", ".join("?" for _value in values)
        with self.conn:
            self.conn.execute(
                f"""
                INSERT INTO {slot.table} (id, {columns}, created_at, updated_at)
                VALUES (1, {placeholders}, ?, ?)
                ON CONFLICT(id) DO UPDATE SET {updates}, updated_at=excluded.updated_at
                """,
                (*values, now, now),
            )
        return config

    def _get_provider_config(
        self,
        slot: ProviderConfigSlot,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
        default_dimensions: int | None = None,
    ) -> ModelConfig | EmbeddingConfig:
        dimension_column = ", dimensions" if slot.includes_dimensions else ""
        row = self.conn.execute(
            f"SELECT provider, base_url, model{dimension_column} FROM {slot.table} WHERE id = 1"
        ).fetchone()
        values = (
            (default_provider, default_base_url.rstrip("/"), default_model, default_dimensions)
            if row is None
            else (row["provider"], row["base_url"], row["model"], row["dimensions"] if slot.includes_dimensions else None)
        )
        if slot.includes_dimensions:
            return EmbeddingConfig(*values)
        return ModelConfig(*values[:3])

    def set_embedding_config(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        dimensions: int | None = None,
    ) -> EmbeddingConfig:
        config = self._set_provider_config(
            EMBEDDING_CONFIG_SLOT,
            provider=provider,
            base_url=base_url,
            model=model,
            dimensions=dimensions,
        )
        assert isinstance(config, EmbeddingConfig)
        return config

    def get_embedding_config(
        self,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
        default_dimensions: int | None = None,
    ) -> EmbeddingConfig:
        config = self._get_provider_config(
            EMBEDDING_CONFIG_SLOT,
            default_provider=default_provider,
            default_base_url=default_base_url,
            default_model=default_model,
            default_dimensions=default_dimensions,
        )
        assert isinstance(config, EmbeddingConfig)
        return config

    def set_model_config(self, *, provider: str, base_url: str, model: str) -> ModelConfig:
        config = self._set_provider_config(
            MODEL_CONFIG_SLOT,
            provider=provider,
            base_url=base_url,
            model=model,
        )
        assert isinstance(config, ModelConfig)
        return config

    def get_model_config(
        self,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
    ) -> ModelConfig:
        config = self._get_provider_config(
            MODEL_CONFIG_SLOT,
            default_provider=default_provider,
            default_base_url=default_base_url,
            default_model=default_model,
        )
        assert isinstance(config, ModelConfig)
        return config

    def set_agent_model_key(
        self,
        *,
        agent_id: str,
        provider: str,
        api_key: str,
    ) -> ModelKeyStatus:
        normalized_agent_id = normalize_agent_id(agent_id)
        normalized_provider = normalize_model_provider(provider)
        current = self.conn.execute(
            "SELECT base_url, model, enabled FROM agent_model_configs WHERE agent_id = ?",
            (normalized_agent_id,),
        ).fetchone()
        global_config = self.conn.execute(
            "SELECT base_url, model FROM model_config WHERE id = 1"
        ).fetchone()
        base_url = (
            str(current["base_url"])
            if current is not None
            else str(global_config["base_url"])
            if global_config is not None
            else ""
        )
        if api_key and not base_url.strip():
            raise ConfigurationError(
                "已配置 API Key 但未配置 Base URL，无法安全路由请求。"
                "请在设置中填写对应的 Base URL。"
            )
        model = (
            str(current["model"])
            if current is not None
            else str(global_config["model"])
            if global_config is not None
            else DEFAULT_CHAT_MODEL
        )
        enabled = int(current["enabled"]) if current is not None else 1
        _, credential_ref, written = write_credential(
            self.credentials,
            AGENT_CREDENTIAL_SLOT,
            normalized_agent_id,
            api_key,
        )
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO agent_model_configs
                    (agent_id, provider, base_url, model, masked, credential_ref,
                     enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    provider=excluded.provider, masked=NULL,
                    credential_ref=excluded.credential_ref, updated_at=excluded.updated_at
                """,
                (
                    normalized_agent_id,
                    normalized_provider,
                    base_url,
                    model,
                    credential_ref,
                    enabled,
                    now,
                    now,
                ),
            )
        return ModelKeyStatus(
            provider=normalized_provider,
            configured=written.configured,
            masked=written.masked,
        )

    def _agent_credential_row(self, agent_id: str, provider: str | None = None):
        normalized_agent_id = normalize_agent_id(agent_id)
        if provider is None:
            return self.conn.execute(
                """
                SELECT provider, credential_ref FROM agent_model_configs
                WHERE agent_id = ? ORDER BY updated_at DESC, created_at DESC LIMIT 1
                """,
                (normalized_agent_id,),
            ).fetchone()
        return self.conn.execute(
            """
            SELECT provider, credential_ref FROM agent_model_configs
            WHERE agent_id = ? AND lower(provider) = ?
            """,
            (normalized_agent_id, normalize_model_provider(provider).lower()),
        ).fetchone()

    def get_agent_model_key_status(
        self,
        agent_id: str,
        *,
        provider: str | None = None,
    ) -> ModelKeyStatus:
        normalized_agent_id = normalize_agent_id(agent_id)
        row = self._agent_credential_row(normalized_agent_id, provider)
        if row is None:
            return ModelKeyStatus(provider=None, configured=False)
        return credential_status(
            self.credentials,
            AGENT_CREDENTIAL_SLOT,
            normalized_agent_id,
            str(row["credential_ref"]),
            provider=str(row["provider"]),
        )

    def get_agent_model_key(self, *, agent_id: str, provider: str) -> str | None:
        normalized_agent_id = normalize_agent_id(agent_id)
        row = self._agent_credential_row(normalized_agent_id, provider)
        if row is None:
            return None
        return read_credential(
            self.credentials,
            AGENT_CREDENTIAL_SLOT,
            normalized_agent_id,
            str(row["credential_ref"]),
        )

    def set_agent_model_config(
        self,
        *,
        agent_id: str,
        provider: str,
        base_url: str,
        model: str,
        enabled: bool = True,
    ) -> ModelConfig:
        normalized_agent_id = normalize_agent_id(agent_id)
        normalized = ModelConfig(
            provider=normalize_model_provider(provider),
            base_url=base_url.strip().rstrip("/"),
            model=model.strip(),
        )
        current = self.conn.execute(
            "SELECT credential_ref FROM agent_model_configs WHERE agent_id = ?",
            (normalized_agent_id,),
        ).fetchone()
        credential_ref = (
            str(current["credential_ref"])
            if current is not None
            else AGENT_CREDENTIAL_SLOT.ref(normalized_agent_id)
        )
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO agent_model_configs
                    (agent_id, provider, base_url, model, masked, credential_ref,
                     enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    provider=excluded.provider, base_url=excluded.base_url,
                    model=excluded.model, enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    normalized_agent_id,
                    normalized.provider,
                    normalized.base_url,
                    normalized.model,
                    credential_ref,
                    int(enabled),
                    now,
                    now,
                ),
            )
        return normalized

    def get_agent_model_config(
        self,
        agent_id: str,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
    ) -> ModelConfig | None:
        del default_provider, default_base_url, default_model
        row = self.conn.execute(
            "SELECT provider, base_url, model FROM agent_model_configs WHERE agent_id = ?",
            (normalize_agent_id(agent_id),),
        ).fetchone()
        if row is None:
            return None
        return ModelConfig(row["provider"], row["base_url"], row["model"])

    def is_agent_model_enabled(self, agent_id: str) -> bool:
        row = self.conn.execute(
            "SELECT enabled FROM agent_model_configs WHERE agent_id = ?",
            (normalize_agent_id(agent_id),),
        ).fetchone()
        return bool(row["enabled"]) if row is not None else False

    def list_agent_model_settings(
        self,
        *,
        default_provider: str,
        default_base_url: str,
        default_model: str,
    ) -> list[AgentModelSettings]:
        agents = []
        for agent_id in AGENT_MODEL_IDS:
            key_status = self.get_agent_model_key_status(agent_id)
            config = self.get_agent_model_config(
                agent_id,
                default_provider=key_status.provider or default_provider,
                default_base_url=default_base_url,
                default_model=default_model,
            )
            enabled = self.is_agent_model_enabled(agent_id)
            provider_status = ModelKeyStatus(provider=None, configured=False)
            if config is not None:
                provider_status = self.get_agent_model_key_status(agent_id, provider=config.provider)
                if not provider_status.configured and key_status.configured:
                    provider_status = key_status
            agents.append(
                AgentModelSettings(
                    agent_id=agent_id,
                    provider=config.provider if config is not None else None,
                    base_url=config.base_url if config is not None else None,
                    model=config.model if config is not None else None,
                    enabled=enabled,
                    configured=bool(config is not None and enabled and provider_status.configured),
                    masked=provider_status.masked,
                )
            )
        return agents

    def get_model_health_status(self) -> ModelHealthResponse:
        defaults = get_settings()
        default_config = ModelConfig(
            provider="openai-compatible",
            base_url=defaults.model_base_url.rstrip("/"),
            model=defaults.chat_model,
        )
        global_status = self.get_model_key_status()
        row = self.conn.execute(
            "SELECT provider, base_url, model FROM model_config WHERE id = 1"
        ).fetchone()
        global_configured = row is not None and global_status.configured
        global_config = (
            ModelConfig(row["provider"], row["base_url"], row["model"])
            if row is not None
            else default_config
        )
        counts = {"agent_specific": 0, "global_fallback": 0, "hardcoded_default": 0}
        details: list[AgentModelHealth] = []
        for agent_id in AGENT_MODEL_IDS:
            agent_row = self.conn.execute(
                "SELECT provider, base_url, model, enabled FROM agent_model_configs WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            agent_config = (
                ModelConfig(agent_row["provider"], agent_row["base_url"], agent_row["model"])
                if agent_row is not None
                else None
            )
            has_override = bool(
                agent_row is not None
                and agent_row["enabled"]
                and agent_config is not None
                and not model_config_matches(
                    agent_config,
                    global_config if global_configured else default_config,
                )
            )
            if has_override and agent_config is not None:
                source, selected_model = "agent_specific", agent_config.model
            elif global_configured:
                source, selected_model = "global_fallback", global_config.model
            else:
                source, selected_model = "hardcoded_default", default_config.model
            counts[source] += 1
            details.append(
                AgentModelHealth(
                    agent_id=AgentId(agent_id),
                    source=source,
                    model=selected_model,
                )
            )
        return ModelHealthResponse(
            global_configured=global_configured,
            agents_configured=counts["agent_specific"],
            agents_fallback_to_global=counts["global_fallback"],
            agents_fallback_to_default=counts["hardcoded_default"],
            agent_details=details,
        )
