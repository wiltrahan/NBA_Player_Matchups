from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.cache import InMemoryCache


class InMemoryCacheTests(unittest.TestCase):
    def test_persists_entries_across_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "cache.pkl"

            cache_a = InMemoryCache(ttl_minutes=30, persist_path=str(cache_file))
            cache_a.set("alpha", {"value": 1})

            cache_b = InMemoryCache(ttl_minutes=30, persist_path=str(cache_file))
            self.assertEqual(cache_b.get("alpha"), {"value": 1})

    def test_invalidate_prefix_persists_removal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "cache.pkl"

            cache_a = InMemoryCache(ttl_minutes=30, persist_path=str(cache_file))
            cache_a.set("matchups:2026-02-11:season", "x")
            cache_a.set("matchups:2026-02-11:last10", "y")

            removed = cache_a.invalidate_prefix("matchups:2026-02-11:")
            self.assertEqual(removed, 2)

            cache_b = InMemoryCache(ttl_minutes=30, persist_path=str(cache_file))
            self.assertIsNone(cache_b.get("matchups:2026-02-11:season"))
            self.assertIsNone(cache_b.get("matchups:2026-02-11:last10"))


if __name__ == "__main__":
    unittest.main()
