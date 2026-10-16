"""Focused regression tests for phone ownership verification and legacy migration."""
import os
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("TWILIO_ACCOUNT_SID", "AC_TEST_ONLY")
os.environ.setdefault("TWILIO_AUTH_TOKEN", "test-auth-token-not-a-real-secret")
os.environ.setdefault("TWILIO_VERIFY_SERVICE_SID", "VA_TEST_ONLY")
os.environ.setdefault("MUKADAM_OTP_HASH_SECRET", "test-hash-secret-for-unit-tests-only")
os.environ.pop("GITHUB_BACKUP_TOKEN", None)
os.environ.pop("GITHUB_BACKUP_REPO", None)

import mukadam_service as service
import mukadam_otp_service as otp_service


class MukadamOtpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mukadam_otp_test_")
        self.old_db_path = service.DB_PATH
        self.old_backup_path = service.BACKUP_JSON_PATH
        service.DB_PATH = os.path.join(self.temp.name, "mukadam_test.db")
        service.BACKUP_JSON_PATH = os.path.join(self.temp.name, "snapshot.json")
        service._CACHE_INITIALIZED = False
        service._MUKADAM_RAM_CACHE = []
        service.init_mukadam_db()
        otp_service.init_mukadam_otp_db()

    def tearDown(self):
        service.DB_PATH = self.old_db_path
        service.BACKUP_JSON_PATH = self.old_backup_path
        service._CACHE_INITIALIZED = False
        service._MUKADAM_RAM_CACHE = []
        self.temp.cleanup()

    def _payload(self, mobile="9876543210", token=""):
        return {
            "name": "Test Mukadam", "mobile": mobile, "pin": "1234",
            "verification_token": token, "district": "ગીર સોમનાથ",
            "taluka": "ગીર ગઢડા", "village": "કોદિયા", "total_labors": 10,
            "skills": "કપાસ વીણવા",
        }

    def _verified_token(self, mobile="9876543210"):
        mobile_hash = otp_service._mobile_hash(mobile, os.environ["MUKADAM_OTP_HASH_SECRET"])
        return otp_service._issue_registration_token(mobile_hash, time.time())

    def test_direct_registration_without_token_is_rejected_and_creates_no_record(self):
        result = service.register_or_update_mukadam(self._payload(token=""))
        self.assertFalse(result["ok"])
        self.assertIn("OTP", result["message_gu"])
        conn = sqlite3.connect(service.DB_PATH)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM mukadams").fetchone()[0], 0)
        finally:
            conn.close()

    def test_gujarati_numerals_normalize_to_ascii_for_otp_hash(self):
        self.assertEqual(service._clean_mobile("૯૮૭૬૫૪૩૨૧૦"), "9876543210")
        self.assertEqual(otp_service._normalise_mobile("+૯૧ ૯૮૭૬૫૪૩૨૧૦"), "9876543210")

    def test_valid_token_registers_verified_profile_once(self):
        token = self._verified_token()
        result = service.register_or_update_mukadam(self._payload(token=token))
        self.assertTrue(result["ok"], result)
        conn = sqlite3.connect(service.DB_PATH)
        try:
            row = conn.execute("SELECT phone_verified, phone_verified_at FROM mukadams WHERE mobile=?", ("9876543210",)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 1)
            self.assertGreater(row[1], 0)
        finally:
            conn.close()
        # Verified entries remain searchable; the new gate only excludes unverified rows.
        service._refresh_ram_cache()
        nearby = service.search_nearby_mukadams(district="ગીર સોમનાથ", taluka="ગીર ગઢડા", village="કોદિયા")
        self.assertEqual(nearby["count"], 1, nearby)
        self.assertEqual(nearby["mukadams"][0]["name"], "Test Mukadam")
        reused = service.register_or_update_mukadam(self._payload(token=token))
        self.assertFalse(reused["ok"])

    def test_expired_registration_token_is_rejected(self):
        mobile_hash = otp_service._mobile_hash("9876543210", os.environ["MUKADAM_OTP_HASH_SECRET"])
        old_token = otp_service._issue_registration_token(
            mobile_hash, time.time() - otp_service.REGISTRATION_TOKEN_TTL_SECONDS - 1
        )
        self.assertFalse(otp_service.consume_registration_token(old_token, "9876543210"))

    def test_token_is_bound_to_exact_mobile(self):
        token = self._verified_token("9876543210")
        other = otp_service.consume_registration_token(token, "9876500000")
        self.assertFalse(other)
        correct = otp_service.consume_registration_token(token, "9876543210")
        self.assertTrue(correct)
        reused = otp_service.consume_registration_token(token, "9876543210")
        self.assertFalse(reused)

    def test_verified_token_reactivates_existing_legacy_profile_only_with_correct_pin(self):
        conn = sqlite3.connect(service.DB_PATH)
        try:
            conn.execute(
                "INSERT INTO mukadams(name,mobile,pin_hash,district,taluka,village,phone_verified) VALUES(?,?,?,?,?,?,0)",
                ("Legacy owner", "9876543210", service._hash_pin("1234"), "ગીર સોમનાથ", "ગીર ગઢડા", "કોદિયા"),
            )
            conn.commit()
        finally:
            conn.close()
        service._refresh_ram_cache()
        result = service.register_or_update_mukadam(self._payload(token=self._verified_token()))
        self.assertTrue(result["ok"], result)
        conn = sqlite3.connect(service.DB_PATH)
        try:
            row = conn.execute("SELECT phone_verified, phone_verified_at FROM mukadams WHERE mobile=?", ("9876543210",)).fetchone()
            self.assertEqual(row[0], 1)
            self.assertGreater(row[1], 0)
        finally:
            conn.close()

    def test_one_successful_otp_check_issues_only_one_registration_token(self):
        with patch.object(otp_service, "_twilio_post", return_value=(201, {"status": "pending"})):
            self.assertTrue(otp_service.request_mukadam_otp("9876543210", "127.0.0.1")["ok"])
        with patch.object(otp_service, "_twilio_post", return_value=(200, {"status": "approved"})) as provider:
            first = otp_service.verify_mukadam_otp("9876543210", "123456")
            second = otp_service.verify_mukadam_otp("9876543210", "123456")
        self.assertTrue(first["ok"], first)
        self.assertFalse(second["ok"])
        self.assertEqual(second["http_status"], 409)
        self.assertEqual(provider.call_count, 1)

    def test_five_failed_otp_attempts_lock_mobile_and_block_new_request(self):
        with patch.object(otp_service, "_twilio_post", return_value=(201, {"status": "pending"})):
            requested = otp_service.request_mukadam_otp("9876543210", "127.0.0.1")
        self.assertTrue(requested["ok"], requested)
        with patch.object(otp_service, "_twilio_post", return_value=(400, {"status": "pending"})):
            results = [otp_service.verify_mukadam_otp("9876543210", "111111") for _ in range(5)]
        self.assertEqual(results[-1]["http_status"], 429)
        blocked = otp_service.request_mukadam_otp("9876543210", "127.0.0.1")
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["http_status"], 429)

    def test_old_json_backup_restores_profiles_as_unverified(self):
        snapshot_path = os.path.join(self.temp.name, "old-snapshot.json")
        with open(snapshot_path, "w", encoding="utf-8") as handle:
            import json
            json.dump([{
                "name": "Backup legacy", "mobile": "9876543210", "pin_hash": "old-pin-hash",
                "district": "ગીર સોમનાથ", "taluka": "ગીર ગઢડા", "village": "કોદિયા"
            }], handle)
        fresh_db = os.path.join(self.temp.name, "backup-restore.db")
        service.DB_PATH = fresh_db
        service.BACKUP_JSON_PATH = snapshot_path
        service._CACHE_INITIALIZED = False
        service._MUKADAM_RAM_CACHE = []
        service.init_mukadam_db()
        conn = sqlite3.connect(fresh_db)
        try:
            row = conn.execute("SELECT phone_verified, phone_verified_at FROM mukadams WHERE mobile=?", ("9876543210",)).fetchone()
            self.assertEqual(row, (0, 0.0))
        finally:
            conn.close()

    def test_provider_unconfigured_fails_closed(self):
        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "", "TWILIO_AUTH_TOKEN": "",
            "TWILIO_VERIFY_SERVICE_SID": "", "MUKADAM_OTP_HASH_SECRET": "",
        }, clear=False):
            result = otp_service.request_mukadam_otp("9876543210", "127.0.0.1")
        self.assertFalse(result["ok"])
        self.assertEqual(result["http_status"], 503)

    def test_twilio_request_and_verify_mock_flow_returns_token_without_logging_otp(self):
        with patch.object(otp_service, "_twilio_post", return_value=(201, {"status": "pending"})) as mocked:
            requested = otp_service.request_mukadam_otp("9876543210", "127.0.0.1")
        self.assertTrue(requested["ok"], requested)
        self.assertNotIn("123456", str(requested))
        self.assertEqual(mocked.call_args.args[3], "Verifications")
        # Clear only the server-side resend clock to simulate the test provider completing
        # a valid verification without waiting 60 seconds; production limits are unchanged.
        mobile_hash = otp_service._mobile_hash("9876543210", os.environ["MUKADAM_OTP_HASH_SECRET"])
        conn = sqlite3.connect(service.DB_PATH)
        try:
            conn.execute("UPDATE mukadam_otp_control SET last_request_at=? WHERE mobile_hash=?", (time.time(), mobile_hash))
            conn.commit()
        finally:
            conn.close()
        with patch.object(otp_service, "_twilio_post", return_value=(200, {"status": "approved"})) as mocked:
            verified = otp_service.verify_mukadam_otp("9876543210", "123456")
        self.assertTrue(verified["ok"], verified)
        self.assertTrue(verified["verification_token"])
        self.assertEqual(mocked.call_args.args[3], "VerificationCheck")

    def test_legacy_database_rows_migrate_as_unverified(self):
        legacy_path = os.path.join(self.temp.name, "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute("""CREATE TABLE mukadams (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, mobile TEXT UNIQUE NOT NULL,
            pin_hash TEXT NOT NULL, district TEXT DEFAULT '', taluka TEXT DEFAULT '', village TEXT DEFAULT '',
            latitude REAL DEFAULT 0.0, longitude REAL DEFAULT 0.0, available_status TEXT DEFAULT 'available',
            available_from_date TEXT DEFAULT '', total_labors INTEGER DEFAULT 0, male_labors INTEGER DEFAULT 0,
            female_labors INTEGER DEFAULT 0, wage_type TEXT DEFAULT 'daily', daily_wage_rate REAL DEFAULT 0.0,
            contract_rate_details TEXT DEFAULT '', rickshaw_fare_type TEXT DEFAULT 'per_km', rickshaw_fare_rate REAL DEFAULT 0.0,
            mukadami_type TEXT DEFAULT 'per_labor', mukadami_rate REAL DEFAULT 0.0, skills TEXT DEFAULT '', notes TEXT DEFAULT '',
            rating_sum REAL DEFAULT 5.0, rating_count INTEGER DEFAULT 1, contact_clicks INTEGER DEFAULT 0, updated_at REAL DEFAULT 0.0
        )""")
        conn.execute("INSERT INTO mukadams(name,mobile,pin_hash) VALUES('Old','9876543210','x')")
        conn.commit(); conn.close()
        service.DB_PATH = legacy_path
        service.BACKUP_JSON_PATH = os.path.join(self.temp.name, "legacy-snapshot.json")
        service._CACHE_INITIALIZED = False
        service.init_mukadam_db()
        conn = sqlite3.connect(legacy_path)
        try:
            self.assertEqual(conn.execute("SELECT phone_verified FROM mukadams WHERE mobile='9876543210'").fetchone()[0], 0)
        finally:
            conn.close()

    def test_unverified_legacy_profile_cannot_use_quick_status(self):
        conn = sqlite3.connect(service.DB_PATH)
        try:
            conn.execute(
                "INSERT INTO mukadams(name,mobile,pin_hash,available_status,phone_verified) VALUES(?,?,?,?,0)",
                ("Legacy", "9999999999", service._hash_pin("1234"), "available"),
            )
            conn.commit()
        finally:
            conn.close()
        result = service.update_mukadam_quick_status({
            "mobile": "9999999999", "pin": "1234", "available_status": "unavailable"
        })
        self.assertFalse(result["ok"])
        self.assertIn("OTP", result["message_gu"])
        conn = sqlite3.connect(service.DB_PATH)
        try:
            self.assertEqual(conn.execute("SELECT available_status FROM mukadams WHERE mobile=?", ("9999999999",)).fetchone()[0], "available")
        finally:
            conn.close()

    def test_unverified_legacy_profiles_are_not_returned_by_search(self):
        conn = sqlite3.connect(service.DB_PATH)
        try:
            conn.execute("INSERT INTO mukadams(name,mobile,pin_hash,district,taluka,village,phone_verified) VALUES(?,?,?,?,?,?,0)",
                         ("Legacy", "9999999999", "x", "ગીર સોમનાથ", "ગીર ગઢડા", "કોદિયા"))
            conn.commit()
        finally:
            conn.close()
        service._refresh_ram_cache()
        result = service.search_nearby_mukadams(district="ગીર સોમનાથ", taluka="ગીર ગઢડા", village="કોદિયા")
        self.assertEqual(result["count"], 0)
        self.assertNotIn("Legacy", str(result["mukadams"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
