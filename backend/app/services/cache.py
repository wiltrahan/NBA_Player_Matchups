from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import pickle
import threading
from typing import Any, Dict


@dataclass
class CacheEntry:
    value: Any
    expires_at: datetime


class InMemoryCache:
    def __init__(self, ttl_minutes: int = 20, persist_path: str | None = None) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._store: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path:
            self._load_persisted()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at = self._normalize_datetime(entry.expires_at)
            if datetime.now(UTC) >= expires_at:
                self._store.pop(key, None)
                self._persist()
                return None
            return entry.value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = CacheEntry(value=value, expires_at=datetime.now(UTC) + self._ttl)
            self._persist()

    def invalidate_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [key for key in self._store if key.startswith(prefix)]
            for key in keys:
                self._store.pop(key, None)
            if keys:
                self._persist()
            return len(keys)

    def _load_persisted(self) -> None:
        path = self._persist_path
        if path is None or not path.exists():
            return
        try:
            with path.open("rb") as handle:
                loaded = pickle.load(handle)
            if not isinstance(loaded, dict):
                return
            now = datetime.now(UTC)
            for key, entry in loaded.items():
                if not isinstance(key, str) or not isinstance(entry, CacheEntry):
                    continue
                expires_at = self._normalize_datetime(entry.expires_at)
                if expires_at > now:
                    self._store[key] = entry
        except Exception:
            # Corrupt cache files are ignored.
            self._store = {}

    def _persist(self) -> None:
        path = self._persist_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as handle:
                pickle.dump(self._store, handle)
        except Exception:
            # Cache persistence failures should not break request flow.
            return

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
