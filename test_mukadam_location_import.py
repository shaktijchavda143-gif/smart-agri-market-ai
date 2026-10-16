"""Tests for strict import of LGD rows into the shared JSON hierarchy."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from import_lgd_gujarat import _open_rows, build_master  # noqa: E402
from location_master import LocationMasterError, validate_location_codes  # noqa: E402


def lgd_row(*, state_code="24", state_name="GUJARAT", district_code="449",
            district_name="KACHCHH", taluka_code="3728", taluka_name="Abdasa",
            village_code="523647", village_name="Achchhari", local="અછારી"):
    return {
        "State Code": state_code,
        "State Name (In English)": state_name,
        "District Code": district_code,
        "District Name (In English)": district_name,
        "District Name (In Local)": "કચ્છ",
        "Sub-District Code": taluka_code,
        "Sub-District Name (In English)": taluka_name,
        "Sub-District Name(In Local)": "અબડાસા",
        "Village Code": village_code,
        "Village Name (In Englsih)": village_name,
        "Village Name (In Local)": local,
        "Village Status": "Inhabitant",
    }


class MukadamLocationImportTests(unittest.TestCase):
    def build_test_master(self, rows):
        return build_master(
            rows,
            "2026-10-16",
            minimum_villages=1,
            minimum_districts=1,
            minimum_talukas=1,
        )

    def test_real_lgd_codes_and_local_names_are_preserved(self):
        master = self.build_test_master([lgd_row()])
        village = master["districts"][0]["talukas"][0]["villages"][0]
        self.assertEqual(village["code"], "523647")
        self.assertEqual(village["name_gu"], "અછારી")
        self.assertEqual(village["taluka_code"], "3728")
        result = validate_location_codes("449", "3728", "523647", master=master)
        self.assertEqual(result["village_code"], "523647")

    def test_same_village_name_keeps_separate_codes_in_separate_talukas(self):
        rows = [
            lgd_row(village_code="700001", village_name="Same Name", taluka_code="3728", taluka_name="Abdasa"),
            lgd_row(village_code="700002", village_name="Same Name", taluka_code="3729", taluka_name="Nakhatrana"),
        ]
        master = self.build_test_master(rows)
        codes = {v["code"] for d in master["districts"] for t in d["talukas"] for v in t["villages"]}
        self.assertEqual(codes, {"700001", "700002"})
        self.assertIsNone(validate_location_codes("449", "3729", "700001", master=master))

    def test_other_states_are_filtered_out(self):
        master = self.build_test_master([
            lgd_row(village_code="523647"),
            lgd_row(state_code="27", state_name="MAHARASHTRA", district_code="1", taluka_code="2", village_code="900001"),
        ])
        self.assertEqual(master["source"]["counts"]["villages"], 1)

    def test_missing_state_code_is_rejected_not_silently_assigned_to_gujarat(self):
        row = lgd_row()
        row["State Code"] = ""
        with self.assertRaisesRegex(RuntimeError, "required LGD column/value missing: state_code"):
            self.build_test_master([row])

    def test_duplicate_village_code_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate Village Code 523647"):
            self.build_test_master([lgd_row(), lgd_row(taluka_code="3729", village_code="523647")])

    def test_csv_reader_finds_realistic_lgd_header_and_englsih_typo(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "lgd.csv"
            headers = list(lgd_row().keys())
            with path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerow(lgd_row())
            rows = _open_rows(path)
            self.assertEqual(len(rows), 1)
            master = self.build_test_master(rows)
            village = master["districts"][0]["talukas"][0]["villages"][0]
            self.assertEqual(village["name_en"], "Achchhari")

    def test_partial_export_cannot_lower_default_completeness_gate(self):
        with self.assertRaisesRegex(RuntimeError, "partial/sample export"):
            build_master([lgd_row()], "2026-10-16")


if __name__ == "__main__":
    unittest.main(verbosity=2)
