"""Comprehensive tests for Canonical Gujarati Village Names (Section 8 requirements 1-9)."""
from __future__ import annotations

import copy
import csv
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / "ai_backend"))
sys.path.insert(0, str(ROOT))

import location_master  # noqa: E402
import gujarat_toponym_resolver as resolver  # noqa: E402
import mukadam_service as ms  # noqa: E402
import admin_service as adm  # noqa: E402
from apply_village_name_corrections import apply_corrections_to_data  # noqa: E402


class GujaratiVillageNameEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.android_path = ROOT / "app/src/main/assets/gujarat_locations.json"
        cls.backend_path = ROOT / "ai_backend/gujarat_locations.json"
        cls.corrections_path = TOOLS / "village_name_corrections.csv"
        cls.master = json.loads(cls.backend_path.read_text(encoding="utf-8"))

    def _villages(self, data=None):
        for district in (data or self.master)["districts"]:
            for taluka in district["talukas"]:
                for village in taluka["villages"]:
                    yield district, taluka, village

    def test_android_and_backend_masters_are_identical_and_lgd_counts_stay_fixed(self):
        self.assertEqual(self.android_path.read_bytes(), self.backend_path.read_bytes())
        counts = location_master.validate_master_data(self.master)
        self.assertEqual((counts["districts"], counts["talukas"], counts["villages"]), (34, 301, 19199))
        self.assertEqual(self.master["source"]["state_code"], "24")

    def test_all_village_names_are_either_source_backed_or_explicitly_pending(self):
        official = curated = morph = pending = 0
        for district, taluka, village in self._villages():
            status = village.get("name_gu_status")
            self.assertEqual(village["district_code"], district["code"])
            self.assertEqual(village["taluka_code"], taluka["code"])
            self.assertIn(village["name_en"], village["aliases"])
            if status == "official_document":
                official += 1
                self.assertTrue(village["name_gu"].strip())
            elif status == "curated_toponym_dictionary":
                curated += 1
                self.assertTrue(village["name_gu"].strip())
            elif status == "verified_toponym_morphology":
                morph += 1
                self.assertTrue(village["name_gu"].strip())
            elif status == "pending":
                pending += 1
            else:
                self.fail(f"unexpected status {status!r} for village {village['code']}")
        self.assertEqual(official, 254)
        self.assertEqual(official + curated + morph, 19199)
        self.assertEqual(pending, 0)

    def test_01_sandhanidhar_resolves_to_canonical_sandhanidhar_gujarati(self):
        """Test 1: SANDHANIDHAR -> સાંઢણીધાર (never સનધનીધર or સનધનિધર)."""
        rec = location_master.canonical_village_record("515101", master=self.master)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["village_code"], "515101")
        self.assertEqual(rec["name_en"], "Sandhnidhar")
        self.assertEqual(rec["name_gu"], "સાંઢણીધાર")
        self.assertNotEqual(rec["name_gu"], "સનધનીધર")
        self.assertNotEqual(rec["name_gu"], "સનધનિધર")
        self.assertEqual(rec["district_gu"], "ગીર સોમનાથ")
        self.assertEqual(rec["taluka_gu"], "કોડીનાર")

    def test_02_and_03_mukadam_dashboard_and_find_labour_show_identical_canonical_gujarati_name(self):
        """Tests 2, 3 & 7: Mukadam Dashboard, Admin Dashboard, and Find Labour all return 'સાંઢણીધાર' and migrate legacy records safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_mukadam.db"
            snap_path = Path(tmpdir) / "test_snap.json"
            old_db, old_snap, old_init = ms.DB_PATH, ms.BACKUP_JSON_PATH, ms._CACHE_INITIALIZED
            try:
                ms.DB_PATH = str(db_path)
                ms.BACKUP_JSON_PATH = str(snap_path)
                ms._CACHE_INITIALIZED = False
                ms.init_mukadam_db()

                # Insert a legacy Mukadam row that had broken Gujarati 'સનધનીધર' or English 'Sandhnidhar'
                conn = sqlite3.connect(ms.DB_PATH)
                conn.execute(
                    """INSERT INTO mukadams (
                        name, mobile, pin_hash, district, taluka, village,
                        district_code, taluka_code, village_code, available_status, total_labors
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', 15)""",
                    ("રાજુભાઈ", "9876543210", ms._hash_pin("1234"), "Gir Somnath", "Kodinar", "સનધનીધર", "675", "3837", "515101"),
                )
                conn.commit()
                conn.close()

                # Run migration / backfill
                ms._backfill_location_codes()
                ms._refresh_ram_cache()

                # 1. Check Find Labour (મજૂર શોધો) search response
                search_res = ms.search_nearby_mukadams(district_code="675", taluka_code="3837", village_code="515101")
                self.assertTrue(search_res["ok"])
                self.assertEqual(search_res["count"], 1)
                labour_card = search_res["mukadams"][0]
                self.assertEqual(labour_card["village"], "સાંઢણીધાર")
                self.assertEqual(labour_card["village_en"], "Sandhnidhar")
                self.assertEqual(labour_card["taluka"], "કોડીનાર")
                self.assertEqual(labour_card["district"], "ગીર સોમનાથ")

                # 2. Check Mukadam Dashboard (Quick Status profile response)
                status_res = ms.update_mukadam_quick_status({"mobile": "9876543210", "pin": "1234", "available_status": "available"})
                self.assertTrue(status_res["ok"])
                dash_profile = status_res["profile"]
                self.assertEqual(dash_profile["village"], "સાંઢણીધાર")
                self.assertEqual(dash_profile["village_en"], "Sandhnidhar")
                self.assertEqual(dash_profile["village"], labour_card["village"])

                # 3. Check Admin Mukadam Dashboard response
                admin_list = adm.list_mukadams_for_admin({"username": "admin", "role": "SUPER_ADMIN"}, village="SANDHANIDHAR")
                self.assertTrue(admin_list["ok"])
                self.assertEqual(admin_list["total"], 1)
                self.assertEqual(admin_list["mukadams"][0]["village"], "સાંઢણીધાર")
                self.assertEqual(admin_list["mukadams"][0]["village_en"], "Sandhnidhar")
            finally:
                ms.DB_PATH = old_db
                ms.BACKUP_JSON_PATH = old_snap
                ms._CACHE_INITIALIZED = old_init

    def test_04_and_05_search_works_by_both_gujarati_and_english_names(self):
        """Tests 4 & 5: Search works by Gujarati ('સાંઢણીધાર') and English ('SANDHANIDHAR', 'Sandhnidhar')."""
        hits_gu = location_master.search_villages(self.master, "સાંઢણીધાર", district_code="675")
        hits_en1 = location_master.search_villages(self.master, "SANDHANIDHAR", district_code="675")
        hits_en2 = location_master.search_villages(self.master, "Sandhnidhar", district_code="675")
        self.assertTrue(hits_gu and hits_gu[0]["village_code"] == "515101")
        self.assertTrue(hits_en1 and hits_en1[0]["village_code"] == "515101")
        self.assertTrue(hits_en2 and hits_en2[0]["village_code"] == "515101")
        self.assertEqual(hits_gu[0]["name_gu"], "સાંઢણીધાર")

    def test_06_duplicate_village_names_disambiguated_by_district_taluka_and_lgd_code(self):
        """Test 6: Identical village names in same/different talukas are distinguished by LGD code and parent."""
        # Same taluka duplicate: Umrethi in Talala (514971 and 908774)
        umrethi_hits = location_master.search_villages(self.master, "ઉમરેઠી", district_code="675", taluka_code="3834")
        self.assertEqual(len(umrethi_hits), 2)
        self.assertTrue(all(h["needs_disambiguation"] for h in umrethi_hits))
        self.assertNotEqual(umrethi_hits[0]["label"], umrethi_hits[1]["label"])
        # Different taluka duplicate: Jasadhar in Gir Gadhda (515381) vs Talala (514985)
        j1 = location_master.validate_location_codes("675", "6199", "515381", master=self.master)
        j2 = location_master.validate_location_codes("675", "3834", "514985", master=self.master)
        self.assertEqual(j1["village"], "જશાધાર")
        self.assertEqual(j2["village"], "જશાધાર")
        self.assertNotEqual(j1["taluka_code"], j2["taluka_code"])

    def test_08_already_gujarati_not_retransliterated_and_unknown_pending_falls_back_to_english(self):
        """Test 8: Already Gujarati names are not re-transliterated; unknown pending records fall back to English."""
        gu_val, st = resolver.resolve_village_name_gu("સાંઢણીધાર")
        self.assertEqual(gu_val, "સાંઢણીધાર")
        self.assertEqual(st, "official_document")
        # Synthetic pending village with blank name_gu falls back to English name_en
        sample = {
            "schema_version": 1,
            "source": {"source_url": "https://lgdirectory.gov.in/demo/downloadDirectory.do", "state_code": "24"},
            "districts": [{
                "code": "675", "name_en": "Gir Somnath", "name_gu": "ગીર સોમનાથ", "aliases": ["Gir Somnath", "ગીર સોમનાથ"],
                "talukas": [{
                    "code": "3837", "district_code": "675", "name_en": "Kodinar", "name_gu": "કોડીનાર", "aliases": ["Kodinar", "કોડીનાર"],
                    "villages": [{
                        "code": "999999", "district_code": "675", "taluka_code": "3837",
                        "name_en": "UnverifiedTestVillage", "name_gu": "", "name_gu_status": "pending",
                        "aliases": ["UnverifiedTestVillage"],
                    }],
                }],
            }],
        }
        val = location_master.validate_location_codes("675", "3837", "999999", master=sample)
        self.assertIsNotNone(val)
        self.assertEqual(val["village"], "UnverifiedTestVillage")

    def test_approved_correction_cannot_change_official_english_name_or_parent_code(self):
        data = copy.deepcopy(self.master)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "village_code", "district_code", "taluka_code", "district_name_en",
                    "taluka_name_en", "village_name_en", "legacy_name_gu", "legacy_name_gu_source",
                    "proposed_name_gu", "aliases_gu_verified", "status", "evidence_tier",
                    "evidence_source_type", "evidence_ref", "reviewer_ids", "verified_at", "notes"
                ])
                writer.writeheader()
                writer.writerow({
                    "village_code": "515101", "district_code": "999", "taluka_code": "3837",
                    "district_name_en": "Gir Somnath", "taluka_name_en": "Kodinar",
                    "village_name_en": "Sandhnidhar", "proposed_name_gu": "સાંઢણીધાર",
                    "status": "official_document", "evidence_ref": "test"
                })
            with self.assertRaises(ValueError):
                apply_corrections_to_data(data, path)


if __name__ == "__main__":
    unittest.main()
