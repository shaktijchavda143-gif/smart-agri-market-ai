"""Small end-to-end test for LGD's XML SpreadsheetML files with a .xls extension."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from import_lgd_gujarat import _open_rows, build_master  # noqa: E402


class LgdSpreadsheetMlImporterTests(unittest.TestCase):
    def test_official_spreadsheetml_title_headers_and_code_chain(self):
        xml = '''<?xml version="1.0"?>
        <Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">
          <Worksheet ss:Name="Village" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Table>
            <Row><Cell><Data>All villages of Gujarat (State code : 24)</Data></Cell></Row>
            <Row>
              <Cell><Data>S.No.</Data></Cell><Cell><Data>District Code</Data></Cell><Cell><Data>District Name</Data></Cell>
              <Cell><Data>Sub-District Code</Data></Cell><Cell><Data>Sub-District Name</Data></Cell>
              <Cell><Data>Village Code</Data></Cell><Cell><Data>Village Version</Data></Cell>
              <Cell><Data>Village Name</Data></Cell><Cell><Data>Village Name</Data></Cell><Cell><Data>Village Status</Data></Cell>
            </Row>
            <Row>
              <Cell/><Cell/><Cell><Data>(In English)</Data></Cell><Cell/><Cell><Data>(In English)</Data></Cell>
              <Cell/><Cell/><Cell><Data>(In English)</Data></Cell><Cell><Data>(In Local)</Data></Cell><Cell/>
            </Row>
            <Row><Cell><Data>1</Data></Cell><Cell><Data>675</Data></Cell><Cell><Data>Gir Somnath</Data></Cell><Cell><Data>6199</Data></Cell><Cell><Data>Gir Gadhda</Data></Cell><Cell><Data>515249</Data></Cell><Cell><Data>2</Data></Cell><Cell><Data>Kodiya</Data></Cell><Cell><Data>કોદિયા</Data></Cell><Cell><Data>Inhabitant</Data></Cell></Row>
          </Table></Worksheet>
        </Workbook>'''.replace('ss:Name', 'ss:Name')
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "villages.xls"
            path.write_text(xml, encoding="utf-8")
            rows = _open_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["State Code"], "24")
            master = build_master(rows, "2026-10-16", minimum_villages=1, minimum_districts=1, minimum_talukas=1)
            village = master["districts"][0]["talukas"][0]["villages"][0]
            self.assertEqual(village["code"], "515249")
            self.assertEqual(village["district_code"], "675")
            self.assertEqual(village["taluka_code"], "6199")
            self.assertEqual(village["name_gu"], "કોદિયા")


if __name__ == "__main__":
    unittest.main(verbosity=2)
