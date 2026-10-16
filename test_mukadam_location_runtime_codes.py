"""End-to-end runtime checks against the imported official Gujarat LGD master."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import location_master
import mukadam_service as service


class GujaratLgdRuntimeCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master, cls.counts = location_master.load_location_master()

    def test_imported_master_has_expected_export_counts_and_code_chains(self):
        self.assertEqual(self.counts["districts"], 34)
        self.assertEqual(self.counts["talukas"], 301)
        self.assertEqual(self.counts["villages"], 19199)
        self.assertEqual(self.master["source"]["state_code"], "24")
        gir = location_master.find_district(self.master, "ગીર સોમનાથ")
        self.assertIsNotNone(gir)
        self.assertEqual(gir["code"], "675")
        taluka = location_master.find_taluka(self.master, "675", "ગીર ગઢડા")
        self.assertIsNotNone(taluka)
        self.assertEqual(taluka["code"], "6199")
        kodiya = location_master.find_village(self.master, "675", "6199", "કોદિયા")
        self.assertIsNotNone(kodiya)
        self.assertEqual(kodiya["code"], "515249")
        self.assertEqual(kodiya["district_code"], "675")
        self.assertEqual(kodiya["taluka_code"], "6199")

    def test_every_record_has_english_search_alias_and_gujarati_display(self):
        for district in self.master["districts"]:
            self.assertIn(district["name_en"], district["aliases"])
            self.assertTrue(district["name_gu"].strip())
            for taluka in district["talukas"]:
                self.assertEqual(taluka["district_code"], district["code"])
                self.assertIn(taluka["name_en"], taluka["aliases"])
                self.assertTrue(taluka["name_gu"].strip())
                for village in taluka["villages"]:
                    self.assertEqual(village["district_code"], district["code"])
                    self.assertEqual(village["taluka_code"], taluka["code"])
                    self.assertIn(village["name_en"], village["aliases"])
                    self.assertTrue(village["name_gu"].strip())

    def test_wrong_parent_and_partial_code_chains_fail_closed(self):
        self.assertIsNone(location_master.validate_location_codes("675", "6199", "900001", master=self.master))
        self.assertIsNone(location_master.validate_location_filter_codes("675", "", "515249", master=self.master))
        valid = location_master.validate_location_codes("675", "6199", "515249", master=self.master)
        self.assertEqual(valid["village_code"], "515249")

    def test_duplicate_village_names_are_code_addressable_with_entity_scoped_label_checks(self):
        district = next(d for d in self.master["districts"] if d["name_en"] == "Arvalli")
        taluka = next(t for t in district["talukas"] if t["name_en"] == "Bayad")
        duplicates = [v for v in taluka["villages"] if v["name_en"] == "Fatepur"]
        self.assertEqual({v["code"] for v in duplicates}, {"511005", "961522"})
        for village in duplicates:
            selected = location_master.validate_location_codes(
                district["code"], taluka["code"], village["code"], master=self.master
            )
            self.assertTrue(location_master.location_labels_match_codes(
                selected, district=district["name_gu"], taluka=taluka["name_gu"],
                village=village["name_gu"], master=self.master,
            ))
            self.assertFalse(location_master.location_labels_match_codes(
                selected, district="Junagadh", taluka=taluka["name_gu"],
                village=village["name_gu"], master=self.master,
            ))

    def test_name_resolution_requires_unique_parented_chain(self):
        result = location_master.resolve_location_selection(
            district="Gir Somnath", taluka="Gir Gadhda", village="Kodiya", master=self.master
        )
        self.assertEqual((result["district_code"], result["taluka_code"], result["village_code"]), ("675", "6199", "515249"))
        self.assertIsNone(location_master.resolve_location_selection(
            district="Junagadh", taluka="Gir Gadhda", village="Kodiya", master=self.master
        ))

    def test_search_uses_lgd_codes_and_rejects_mismatched_codes(self):
        temp = tempfile.TemporaryDirectory(prefix="mukadam_lgd_codes_test_")
        old_db, old_backup = service.DB_PATH, service.BACKUP_JSON_PATH
        old_init, old_cache = service._CACHE_INITIALIZED, service._MUKADAM_RAM_CACHE
        try:
            service.DB_PATH = os.path.join(temp.name, "mukadam.db")
            service.BACKUP_JSON_PATH = os.path.join(temp.name, "snapshot.json")
            service._CACHE_INITIALIZED = False
            service._MUKADAM_RAM_CACHE = []
            service.init_mukadam_db()
            conn = sqlite3.connect(service.DB_PATH)
            try:
                conn.execute("""
                    INSERT INTO mukadams (name,mobile,pin_hash,district,taluka,village,
                        district_code,taluka_code,village_code,available_status,updated_at,
                        phone_verified_at,phone_verified)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, ("LGD Test", "9876543210", service._hash_pin("1234"),
                      "ગીર સોમનાથ", "ગીર ગઢડા", "કોદિયા", "675", "6199", "515249",
                      "available", 9999999999.0, 9999999999.0, 1))
                conn.commit()
            finally:
                conn.close()
            service._refresh_ram_cache()
            result = service.search_nearby_mukadams(
                district="ગીર સોમનાથ", taluka="ગીર ગઢડા", village="કોદિયા",
                district_code="675", taluka_code="6199", village_code="515249",
            )
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["count"], 1, result)
            self.assertEqual(result["mukadams"][0]["village_code"], "515249")
            invalid = service.search_nearby_mukadams(
                district="ગીર સોમનાથ", taluka="ગીર ગઢડા", village="કોદિયા",
                district_code="675", taluka_code="6199", village_code="900001",
            )
            self.assertFalse(invalid["ok"], invalid)
        finally:
            service.DB_PATH = old_db
            service.BACKUP_JSON_PATH = old_backup
            service._CACHE_INITIALIZED = old_init
            service._MUKADAM_RAM_CACHE = old_cache
            temp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
