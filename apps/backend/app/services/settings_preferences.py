from __future__ import annotations

import json
import sqlite3

from app.models.config import (
    AutomationSettingsRequest,
    AutomationSettingsResponse,
    TtsSettingsRequest,
    TtsSettingsResponse,
)
from app.models.config import normalize_proactive_trigger_frequency
from app.utils.time import utc_now_iso

from .settings_types import (
    CredentialStore,
    LOCAL_PRIVACY_MODE_STATE_KEY,
    WIKI_SHADOW_ENABLED_STATE_KEY,
    ModelKeyStatus,
    PROACTIVE_TRIGGER_FREQUENCY_STATE_KEY,
    TTS_CREDENTIAL_SLOT,
    TTS_SETTINGS_STATE_KEY,
    credential_status,
    normalize_tts_preset_settings,
    normalize_tts_provider,
    read_credential,
    tts_key_state_key,
    tts_settings_response,
    write_credential,
)


class SettingsPreferencesMixin:
    """Automation and speech preferences stored in app_state."""

    conn: sqlite3.Connection
    credentials: CredentialStore

    def _set_app_state(self, key: str, value: object, updated_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO app_state(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), updated_at),
        )

    def get_automation_settings(self) -> AutomationSettingsResponse:
        row = self.conn.execute("SELECT * FROM automation_settings WHERE id = 1").fetchone()
        local_privacy_mode = self._get_bool_state(LOCAL_PRIVACY_MODE_STATE_KEY)
        wiki_shadow_enabled = self._get_bool_state(WIKI_SHADOW_ENABLED_STATE_KEY, strict=True)
        proactive_trigger_frequency = self._get_proactive_trigger_frequency()
        if row is None:
            return AutomationSettingsResponse(
                local_privacy_mode=local_privacy_mode,
                wiki_shadow_enabled=wiki_shadow_enabled,
                proactive_trigger_frequency=proactive_trigger_frequency,
            )
        return AutomationSettingsResponse(
            auto_chat_diary=bool(row["auto_chat_diary"]),
            auto_structured_memory=bool(row["auto_structured_memory"]),
            auto_long_term_memory=bool(row["auto_long_term_memory"]),
            auto_wiki_organize=bool(row["auto_wiki_organize"]),
            wiki_shadow_enabled=wiki_shadow_enabled,
            local_privacy_mode=local_privacy_mode,
            proactive_trigger_frequency=proactive_trigger_frequency,
            use_negotiation=bool(row["use_negotiation"]),
            max_rounds=int(row["max_rounds"]),
            high_risk_confirmation_required=bool(row["high_risk_confirmation_required"]),
            updated_at=str(row["updated_at"]),
        )

    def set_automation_settings(
        self,
        settings: AutomationSettingsRequest,
    ) -> AutomationSettingsResponse:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO automation_settings (
                    id, auto_chat_diary, auto_structured_memory, auto_long_term_memory,
                    auto_wiki_organize, use_negotiation, max_rounds,
                    high_risk_confirmation_required, created_at, updated_at
                )
                VALUES (1, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    auto_chat_diary = excluded.auto_chat_diary,
                    auto_structured_memory = excluded.auto_structured_memory,
                    auto_long_term_memory = excluded.auto_long_term_memory,
                    auto_wiki_organize = excluded.auto_wiki_organize,
                    use_negotiation = excluded.use_negotiation,
                    max_rounds = excluded.max_rounds,
                    high_risk_confirmation_required = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    int(settings.auto_chat_diary),
                    int(settings.auto_structured_memory),
                    int(settings.auto_long_term_memory),
                    int(settings.auto_wiki_organize),
                    int(settings.use_negotiation),
                    settings.max_rounds,
                    now,
                    now,
                ),
            )
            self._set_app_state(
                LOCAL_PRIVACY_MODE_STATE_KEY,
                bool(settings.local_privacy_mode),
                now,
            )
            # Older clients do not own the new opt-in setting.
            if "wiki_shadow_enabled" in settings.model_fields_set:
                self._set_app_state(
                    WIKI_SHADOW_ENABLED_STATE_KEY,
                    settings.wiki_shadow_enabled,
                    now,
                )
            self._set_app_state(
                PROACTIVE_TRIGGER_FREQUENCY_STATE_KEY,
                normalize_proactive_trigger_frequency(settings.proactive_trigger_frequency),
                now,
            )
        return self.get_automation_settings()

    def _get_proactive_trigger_frequency(self):
        row = self.conn.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (PROACTIVE_TRIGGER_FREQUENCY_STATE_KEY,),
        ).fetchone()
        if row is None:
            return normalize_proactive_trigger_frequency(None)
        try:
            value = json.loads(str(row["value"]))
        except (TypeError, ValueError):
            value = str(row["value"])
        return normalize_proactive_trigger_frequency(value)

    def _get_bool_state(self, key: str, default: bool = False, *, strict: bool = False) -> bool:
        row = self.conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            value = json.loads(str(row["value"]))
        except (TypeError, ValueError):
            value = str(row["value"]).strip().lower()
        if isinstance(value, bool):
            return value
        if strict:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value in {"1", "true", "yes", "on", "enabled"}
        return default

    def get_tts_settings(self) -> TtsSettingsResponse:
        row = self.conn.execute(
            "SELECT value, updated_at FROM app_state WHERE key = ?",
            (TTS_SETTINGS_STATE_KEY,),
        ).fetchone()
        if row is None:
            settings = TtsSettingsRequest()
            return tts_settings_response(
                settings,
                updated_at=None,
                key_status=self.get_tts_key_status(settings.provider),
            )
        try:
            settings = TtsSettingsRequest.model_validate(json.loads(str(row["value"])))
        except (TypeError, ValueError):
            settings = TtsSettingsRequest()
        return tts_settings_response(
            settings,
            updated_at=str(row["updated_at"]),
            key_status=self.get_tts_key_status(settings.provider),
        )

    def set_tts_settings(self, settings: TtsSettingsRequest) -> TtsSettingsResponse:
        raw_settings = settings.model_dump(mode="json") if hasattr(settings, "model_dump") else settings
        if isinstance(raw_settings, dict):
            provider = normalize_tts_provider(str(raw_settings.get("provider") or "system"))
            raw_settings = normalize_tts_preset_settings(
                {
                    **raw_settings,
                    "provider": provider,
                    "base_url": str(raw_settings.get("base_url") or "").strip() or None,
                    "model": str(raw_settings.get("model") or "").strip() or None,
                    "response_format": str(raw_settings.get("response_format") or "mp3").strip().lower()
                    or "mp3",
                    "api_style": str(raw_settings.get("api_style") or "generic").strip().lower()
                    or "generic",
                    "auth_header_name": str(raw_settings.get("auth_header_name") or "").strip()
                    or None,
                    "audio_json_path": str(raw_settings.get("audio_json_path") or "").strip()
                    or None,
                    "audio_encoding": str(raw_settings.get("audio_encoding") or "base64").strip().lower()
                    or "base64",
                    "mime_type": str(raw_settings.get("mime_type") or "").strip() or None,
                }
            )
        normalized = TtsSettingsRequest.model_validate(raw_settings)
        now = utc_now_iso()
        with self.conn:
            self._set_app_state(TTS_SETTINGS_STATE_KEY, normalized.model_dump(mode="json"), now)
        return self.get_tts_settings()

    def set_tts_key(self, provider: str, api_key: str) -> ModelKeyStatus:
        normalized, credential_ref, status = write_credential(
            self.credentials,
            TTS_CREDENTIAL_SLOT,
            provider,
            api_key,
        )
        with self.conn:
            self._set_app_state(
                tts_key_state_key(normalized),
                {"provider": normalized, "credential_ref": credential_ref},
                utc_now_iso(),
            )
        return status

    def _tts_credential_ref(self, provider: str) -> tuple[str, str | None]:
        normalized = TTS_CREDENTIAL_SLOT.normalize(provider)
        row = self.conn.execute(
            "SELECT value FROM app_state WHERE key = ?",
            (tts_key_state_key(normalized),),
        ).fetchone()
        if row is None:
            return normalized, None
        try:
            raw = json.loads(str(row["value"]))
        except (TypeError, ValueError):
            raw = {}
        return normalized, str(raw.get("credential_ref") or "") or None

    def get_tts_key_status(self, provider: str) -> ModelKeyStatus:
        normalized, credential_ref = self._tts_credential_ref(provider)
        return credential_status(
            self.credentials,
            TTS_CREDENTIAL_SLOT,
            normalized,
            credential_ref,
        )

    def get_tts_key(self, provider: str) -> str | None:
        normalized, credential_ref = self._tts_credential_ref(provider)
        return read_credential(
            self.credentials,
            TTS_CREDENTIAL_SLOT,
            normalized,
            credential_ref,
        )
