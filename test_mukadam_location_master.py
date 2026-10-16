"""Automated checks for LGD parent/code integrity, separate from OTP tests."""
import tempfile
import unittest
from pathlib import Path
from location_master import LocationMasterError, load_location_master, validate_location_codes, validate_master_data


def sample_master():
    return {
        "schema_version": 1,
        "source": {"source_url": "https://lgdirectory.gov.in/demo/downloadDirectory.do", "state_code": "24"},
        "districts": [
            {"code": "449", "name_en": "KACHCHH", "name_gu": "કચ્છ", "talukas": [
                {"code": "3728", "district_code": "449", "name_en": "Abdasa", "name_gu": "અબડાસા", "villages": [
                    {"code": "900001", "district_code": "449", "taluka_code": "3728", "name_en": "Sample", "name_gu": "નમૂનો"},
                ]},
                {"code": "3729", "district_code": "449", "name_en": "Nakhatrana", "name_gu": "નખત્રાણા", "villages": [
                    {"code": "900002", "district_code": "449", "taluka_code": "3729", "name_en": "Sample", "name_gu": "નમૂનો"},
                ]},
            ]},
        ],
    }


class MukadamLocationMasterTests(unittest.TestCase):
    def test_complete_record_hierarchy_validates_with_test_threshold(self):
        counts = validate_master_data(sample_master(), minimum_villages=1, minimum_districts=1, minimum_talukas=1)
        self.assertEqual(counts["districts"], 1)
        self.assertEqual(counts["talukas"], 2)
        self.assertEqual(counts["villages"], 2)

    def test_same_village_name_can_exist_in_different_talukas_by_distinct_codes(self):
        master = sample_master()
        first = validate_location_codes("449", "3728", "900001", master=master)
        second = validate_location_codes("449", "3729", "900002", master=master)
        self.assertEqual(first["taluka_code"], "3728")
        self.assertEqual(second["taluka_code"], "3729")
        self.assertEqual(first["village"], second["village"])

    def test_missing_code_is_rejected(self):
        self.assertIsNone(validate_location_codes("449", "3728", "", master=sample_master()))

    def test_wrong_taluka_village_chain_is_rejected(self):
        # Village 900001 belongs to taluka 3728, not taluka 3729.
        self.assertIsNone(validate_location_codes("449", "3729", "900001", master=sample_master()))

    def test_wrong_district_parent_is_rejected(self):
        master = sample_master()
        master["districts"][0]["talukas"][0]["district_code"] = "999"
        with self.assertRaisesRegex(LocationMasterError, "invalid district parent"):
            validate_master_data(master, minimum_villages=1, minimum_districts=1, minimum_talukas=1)

    def test_duplicate_village_lgd_code_is_rejected(self):
        master = sample_master()
        duplicate = dict(master["districts"][0]["talukas"][0]["villages"][0])
        duplicate["taluka_code"] = "3729"
        master["districts"][0]["talukas"][1]["villages"].append(duplicate)
        with self.assertRaisesRegex(LocationMasterError, "duplicate village LGD code"):
            validate_master_data(master, minimum_villages=1, minimum_districts=1, minimum_talukas=1)

    def test_partial_export_fails_completeness_guard(self):
        with self.assertRaisesRegex(LocationMasterError, "partial Gujarat export"):
            validate_master_data(sample_master(), minimum_villages=10_000, minimum_districts=1, minimum_talukas=1)

    def test_missing_runtime_master_fails_closed_instead_of_fabricating_locations(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "gujarat_locations.json"
            with self.assertRaisesRegex(FileNotFoundError, "Official location master not installed"):
                load_location_master(missing)

    def test_non_gujarat_state_is_rejected(self):
        master = sample_master()
        master["source"]["state_code"] = "27"
        with self.assertRaisesRegex(LocationMasterError, "state code 24"):
            validate_master_data(master, minimum_villages=1, minimum_districts=1, minimum_talukas=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
