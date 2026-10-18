# -*- coding: utf-8 -*-
"""Regression tests for Gujarat LGD master parity and Phase 0 cleanup utility."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.phase0_village_name_cleanup import (  # noqa: E402
    cleanup_document,
    code_identity_snapshot,
    validate_master,
)

BACKEND_JSON = PROJECT_ROOT / "ai_backend" / "gujarat_locations.json"
ANDROID_JSON = PROJECT_ROOT / "app" / "src" / "main" / "assets" / "gujarat_locations.json"


class TestPhase0AndMasterParity(unittest.TestCase):
    def test_current_lgd_master_counts_codes_and_parent_hierarchy(self):
        data = json.loads(BACKEND_JSON.read_text(encoding="utf-8"))
        counts = validate_master(data)
        self.assertEqual(counts, {"districts": 34, "talukas": 301, "villages": 19199})

    def test_android_and_backend_json_are_byte_for_byte_identical(self):
        backend_bytes = BACKEND_JSON.read_bytes()
        android_bytes = ANDROID_JSON.read_bytes()
        self.assertEqual(hashlib.sha256(backend_bytes).digest(), hashlib.sha256(android_bytes).digest())
        self.assertEqual(backend_bytes, android_bytes)

    def test_unverified_label_is_archived_and_removed_from_active_search_aliases(self):
        sample = {
            "districts": [{
                "code": "D1", "talukas": [{
                    "code": "T1", "district_code": "D1", "villages": [{
                        "code": "V1", "district_code": "D1", "taluka_code": "T1",
                        "name_en": "Example Village", "name_gu": "એક્ઝામ્પલ વિલેજ",
                        "name_gu_status": "phonetic_transliteration", "name_gu_source_ref": "",
                        "aliases": ["Example Village", "એક્ઝામ્પલ વિલેજ"],
                        "aliases_gu_verified": [],
                    }]
                }]
            }]
        }
        output, _ = cleanup_document(sample)
        village = output["districts"][0]["talukas"][0]["villages"][0]
        self.assertEqual(village["legacy_auto_gu"], "એક્ઝામ્પલ વિલેજ")
        self.assertEqual(village["name_gu"], "")
        self.assertEqual(village["name_gu_status"], "pending")


if __name__ == "__main__":
    unittest.main()
