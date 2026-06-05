from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path


CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class TtsCachedAudio:
    cache_key: str
    mime_type: str
    audio: bytes
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class TtsCacheClearResult:
    cleared_entries: int
    cleared_bytes: int


class TtsAudioCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def key_for(
        self,
        *,
        provider: str,
        voice_id: str | None,
        speed: float,
        text: str,
    ) -> str:
        payload = {
            "provider": provider.strip().lower(),
            "voice": (voice_id or "default").strip(),
            "speed": round(float(speed), 3),
            "text": normalize_tts_cache_text(text),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return sha256(encoded).hexdigest()

    def get(self, cache_key: str) -> TtsCachedAudio | None:
        metadata_path, audio_path = self._entry_paths(cache_key)
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            audio = audio_path.read_bytes()
        except (OSError, ValueError):
            self._remove_entry(metadata_path, audio_path)
            return None

        mime_type = str(metadata.get("mime_type") or "")
        if metadata.get("version") != CACHE_VERSION or not mime_type.startswith("audio/") or not audio:
            self._remove_entry(metadata_path, audio_path)
            return None

        duration = metadata.get("duration_ms")
        return TtsCachedAudio(
            cache_key=cache_key,
            mime_type=mime_type,
            audio=audio,
            duration_ms=duration if isinstance(duration, int) else None,
        )

    def put(
        self,
        cache_key: str,
        *,
        provider: str,
        mime_type: str,
        audio: bytes,
        duration_ms: int | None,
    ) -> None:
        if not audio or not mime_type.startswith("audio/"):
            return

        metadata_path, audio_path = self._entry_paths(cache_key)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {
            "version": CACHE_VERSION,
            "provider": provider,
            "mime_type": mime_type,
            "duration_ms": duration_ms,
            "created_at": time.time(),
        }
        audio_tmp = audio_path.with_suffix(".audio.tmp")
        metadata_tmp = metadata_path.with_suffix(".json.tmp")
        audio_tmp.write_bytes(audio)
        metadata_tmp.write_text(json.dumps(metadata, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(audio_tmp, audio_path)
        os.replace(metadata_tmp, metadata_path)

    def clear(self) -> TtsCacheClearResult:
        if not self.root.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            return TtsCacheClearResult(cleared_entries=0, cleared_bytes=0)

        cleared_entries = 0
        cleared_bytes = 0
        for path in self.root.rglob("*"):
            if path.is_file():
                cleared_entries += 1
                try:
                    cleared_bytes += path.stat().st_size
                except OSError:
                    pass

        for child in list(self.root.iterdir()):
            try:
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                pass
        self.root.mkdir(parents=True, exist_ok=True)
        return TtsCacheClearResult(cleared_entries=cleared_entries, cleared_bytes=cleared_bytes)

    def _entry_paths(self, cache_key: str) -> tuple[Path, Path]:
        safe_key = cache_key.strip().lower()
        if len(safe_key) != 64 or any(char not in "0123456789abcdef" for char in safe_key):
            raise ValueError("invalid TTS cache key")
        entry_dir = self.root / safe_key[:2]
        return entry_dir / f"{safe_key}.json", entry_dir / f"{safe_key}.audio"

    @staticmethod
    def _remove_entry(metadata_path: Path, audio_path: Path) -> None:
        for path in (metadata_path, audio_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def normalize_tts_cache_text(text: str) -> str:
    return " ".join(text.strip().split())
