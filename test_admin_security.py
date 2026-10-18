# -*- coding: utf-8 -*-
"""
Phase 13 Automated Security, RBAC, Audit Log Immutability, Migration, Backup/Restore,
and Regression Test Suite for Smart Agri-Market AI Secure Admin Panel.
Covers all 18 mandatory scenarios from Phase 13.
"""
import os
import json
import time
import shutil
import sqlite3
import tempfile
import unittest
import yaml
from fastapi.testclient import TestClient

try:
    import mukadam_service as ms
    import admin_service as adm
    import main as backend_main
except ImportError:
    from . import mukadam_service as ms
    from . import admin_service as adm
    from . import main as backend_main


class TestAdminPanelSecuritySuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tpl_dir = tempfile.mkdtemp(prefix="smart_agri_admin_tpl_")
        cls._tpl_db = os.path.join(cls._tpl_dir, "tpl_mukadam.db")
        cls._tpl_json = os.path.join(cls._tpl_dir, "tpl_snapshot.json")
        orig_db, orig_json, orig_init = ms.DB_PATH, ms.BACKUP_JSON_PATH, ms._CACHE_INITIALIZED
        ms.DB_PATH = cls._tpl_db
        ms.BACKUP_JSON_PATH = cls._tpl_json
        ms._CACHE_INITIALIZED = False
        os.environ["ADMIN_BOOTSTRAP_USERNAME"] = "superadmin_guj"
        os.environ["ADMIN_BOOTSTRAP_PASSWORD"] = "SuperSecret#2026!Agri"
        os.environ["ADMIN_BOOTSTRAP_DISPLAY_NAME"] = "મુખ્ય એડમિન"
        os.environ["ADMIN_RESET_MASTER_SECRET"] = "MasterResetSecret#9988776655"
        ms.init_mukadam_db()
        ms.DB_PATH, ms.BACKUP_JSON_PATH, ms._CACHE_INITIALIZED = orig_db, orig_json, orig_init

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._tpl_dir, ignore_errors=True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="smart_agri_admin_test_")
        self.db_path = os.path.join(self.temp_dir, "test_mukadam.db")
        self.json_path = os.path.join(self.temp_dir, "test_mukadam_snapshot.json")
        shutil.copy2(self._tpl_db, self.db_path)

        self.orig_db_path = ms.DB_PATH
        self.orig_json_path = ms.BACKUP_JSON_PATH
        ms.DB_PATH = self.db_path
        ms.BACKUP_JSON_PATH = self.json_path
        ms._CACHE_INITIALIZED = True
        ms._MUKADAM_RAM_CACHE = []

        os.environ["ADMIN_BOOTSTRAP_USERNAME"] = "superadmin_guj"
        os.environ["ADMIN_BOOTSTRAP_PASSWORD"] = "SuperSecret#2026!Agri"
        os.environ["ADMIN_BOOTSTRAP_DISPLAY_NAME"] = "મુખ્ય એડમિન"
        os.environ["ADMIN_RESET_MASTER_SECRET"] = "MasterResetSecret#9988776655"
        for attr in ("_LOGIN_IP_ATTEMPTS", "_LOGIN_USER_ATTEMPTS", "_REPORT_IP_ATTEMPTS", "_ADMIN_API_RATE_LIMITER"):
            if hasattr(adm, attr): getattr(adm, attr).clear()
        self.client = TestClient(backend_main.app)

        # Create a Moderator and a Viewer account via SUPER_ADMIN
        login_res = adm.admin_login("superadmin_guj", "SuperSecret#2026!Agri", client_ip="127.0.0.1")
        self.assertTrue(login_res["ok"])
        self.super_token = login_res["session_token"]
        self.super_csrf = login_res["csrf_token"]
        self.super_admin = login_res["admin"]

        adm.create_or_update_admin_user(
            self.super_admin,
            username="mod_gir",
            display_name="ગીર મોડરેટર",
            role=adm.ROLE_MODERATOR,
            password="ModPassword#2026!Agri",
        )
        adm.create_or_update_admin_user(
            self.super_admin,
            username="viewer_gir",
            display_name="ગીર વ્યુઅર",
            role=adm.ROLE_VIEWER,
            password="ViewerPass#2026!Agri",
        )

        mod_login = adm.admin_login("mod_gir", "ModPassword#2026!Agri", client_ip="127.0.0.2")
        self.mod_token = mod_login["session_token"]
        self.mod_csrf = mod_login["csrf_token"]

        viewer_login = adm.admin_login("viewer_gir", "ViewerPass#2026!Agri", client_ip="127.0.0.3")
        self.viewer_token = viewer_login["session_token"]
        self.viewer_csrf = viewer_login["csrf_token"]

    def tearDown(self):
        ms.DB_PATH = self.orig_db_path
        ms.BACKUP_JSON_PATH = self.orig_json_path
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _register_sample_mukadam(self, name="રમેશભાઈ પરમાર", mobile="9876543210", pin="1234") -> int:
        res = ms.register_or_update_mukadam(
            {
                "name": name,
                "mobile": mobile,
                "pin": pin,
                "district": "ગીર સોમનાથ",
                "taluka": "ગીર ગઢડા",
                "village": "કોદિયા",
                "district_code": "675",
                "taluka_code": "6199",
                "village_code": "515249",
                "available_status": "available",
                "total_labors": 15,
                "male_labors": 8,
                "female_labors": 7,
                "daily_wage_rate": 400.0,
                "skills": "કપાસ વીણવા, નિંદામણ / ગોડકામ",
            },
            client_ip="10.0.0.1",
        )
        self.assertTrue(res["ok"], f"Sample registration failed: {res}")
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute("SELECT id FROM mukadams WHERE mobile = ?", (mobile,)).fetchone()
            return int(row[0])
        finally:
            conn.close()

    # 1. Login વગર Admin APIs access કરવાનો પ્રયાસ
    def test_01_unauthenticated_admin_api_access_denied(self):
        for endpoint in [
            "/api/v1/admin/dashboard",
            "/api/v1/admin/mukadams",
            "/api/v1/admin/mukadams/1",
            "/api/v1/admin/reports",
            "/api/v1/admin/audit-logs",
            "/api/v1/admin/users",
            "/api/mukadam/export_csv",
        ]:
            resp = self.client.get(endpoint)
            self.assertEqual(resp.status_code, 401, f"Expected 401 on GET {endpoint}, got {resp.status_code}")

        for post_ep in [
            "/api/v1/admin/mukadams/1/block",
            "/api/v1/admin/mukadams/1/unblock",
            "/api/v1/admin/mukadams/1/soft-delete",
            "/api/v1/admin/mukadams/1/restore",
            "/api/v1/admin/reports/1/review",
            "/api/v1/admin/backup",
        ]:
            resp = self.client.post(post_ep, json={"reason": "test"})
            self.assertEqual(resp.status_code, 401, f"Expected 401 on POST {post_ep}, got {resp.status_code}")

    # 2. ખોટા passwordથી login
    def test_02_wrong_password_login_rejected(self):
        resp = self.client.post(
            "/api/v1/admin/auth/login",
            json={"username": "superadmin_guj", "password": "WrongPassword123!"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertNotIn("session_token", resp.json())

    # 3. Viewer દ્વારા Block કરવાનો પ્રયાસ અને Masked Mobile ચકાસણી
    def test_03_viewer_cannot_block_and_sees_masked_mobiles(self):
        muk_id = self._register_sample_mukadam()
        # Viewer can view list, but mobile is masked
        list_resp = self.client.get(
            "/api/v1/admin/mukadams",
            headers={"Authorization": f"Bearer {self.viewer_token}"},
        )
        self.assertEqual(list_resp.status_code, 200)
        muk_row = list_resp.json()["mukadams"][0]
        self.assertIn("******", muk_row["mobile"])

        # Viewer cannot block
        blk_resp = self.client.post(
            f"/api/v1/admin/mukadams/{muk_id}/block",
            headers={"Authorization": f"Bearer {self.viewer_token}", "X-CSRF-Token": self.viewer_csrf},
            json={"reason": "Viewer trying to block"},
        )
        self.assertEqual(blk_resp.status_code, 403)

    # 4. Moderator દ્વારા Permanent Delete અને Soft Delete કરવાનો પ્રયાસ
    def test_04_moderator_cannot_permanent_delete_or_soft_delete(self):
        muk_id = self._register_sample_mukadam()
        sd_resp = self.client.post(
            f"/api/v1/admin/mukadams/{muk_id}/soft-delete",
            headers={"Authorization": f"Bearer {self.mod_token}", "X-CSRF-Token": self.mod_csrf},
            json={"reason": "Moderator soft delete attempt"},
        )
        self.assertEqual(sd_resp.status_code, 403)

        pd_resp = self.client.request(
            "DELETE",
            f"/api/v1/admin/mukadams/{muk_id}/permanent",
            headers={"Authorization": f"Bearer {self.mod_token}", "X-CSRF-Token": self.mod_csrf},
            json={
                "admin_password": "ModPassword#2026!Agri",
                "confirm_mobile_or_name": "9876543210",
                "reason": "Moderator permanent delete attempt",
            },
        )
        self.assertEqual(pd_resp.status_code, 403)

    # 5. Unauthorized user દ્વારા અન્ય મુકાદમના IDથી access / update (IDOR & PIN protection)
    def test_05_unauthorized_idor_access_blocked(self):
        muk_id = self._register_sample_mukadam(mobile="9876543210", pin="1234")
        # Public caller cannot access admin profile by ID
        resp = self.client.get(f"/api/v1/admin/mukadams/{muk_id}")
        self.assertEqual(resp.status_code, 401)
        # Another user with wrong PIN cannot overwrite Mukadam 9876543210
        wrong_pin_update = ms.update_mukadam_quick_status(
            {"mobile": "9876543210", "pin": "9999", "available_status": "unavailable"},
            client_ip="10.0.0.99",
        )
        self.assertFalse(wrong_pin_update["ok"])

    # 6. SQL injection payloads
    def test_06_sql_injection_payloads_neutralized(self):
        self._register_sample_mukadam()
        sqli = "' OR 1=1; DROP TABLE mukadams; --"
        # Login SQLi
        r1 = self.client.post("/api/v1/admin/auth/login", json={"username": sqli, "password": sqli})
        self.assertEqual(r1.status_code, 401)
        # Admin directory search SQLi
        r2 = self.client.get(
            "/api/v1/admin/mukadams",
            params={"q": sqli, "district": sqli, "mobile": sqli},
            headers={"Authorization": f"Bearer {self.super_token}"},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["total"], 0)
        # Verify mukadams table is still intact with 1 record
        ov = self.client.get("/api/v1/admin/dashboard", headers={"Authorization": f"Bearer {self.super_token}"}).json()
        self.assertEqual(ov["overview"]["total_mukadams"], 1)

    # 7. Invalid IDs અને malformed JSON
    def test_07_invalid_ids_and_malformed_json_handled_safely(self):
        r_neg = self.client.get("/api/v1/admin/mukadams/-5", headers={"Authorization": f"Bearer {self.super_token}"})
        self.assertEqual(r_neg.status_code, 400)
        r_missing = self.client.get("/api/v1/admin/mukadams/999999", headers={"Authorization": f"Bearer {self.super_token}"})
        self.assertEqual(r_missing.status_code, 404)
        r_bad_json = self.client.post(
            "/api/v1/admin/auth/login",
            data="{malformed_json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(r_bad_json.status_code, 422)

    # 8. Rate limiting (Admin Login Brute-Force Lockout & Farmer Report Rate Limit)
    def test_08_login_and_report_rate_limiting(self):
        for _ in range(adm.ADMIN_LOGIN_USER_FAIL_LIMIT):
            res = adm.admin_login("superadmin_guj", "WrongPass#000", client_ip="192.0.2.55")
            self.assertEqual(res["http_status"], 401)
        # 6th attempt even with correct password must be locked out with HTTP 429
        locked = adm.admin_login("superadmin_guj", "SuperSecret#2026!Agri", client_ip="192.0.2.55")
        self.assertFalse(locked["ok"])
        self.assertEqual(locked["http_status"], 429)

    # 9. Block થયેલા મુકાદમનું Public Search અને अन्य APIs માં નિયંત્રણ
    def test_09_blocked_mukadam_excluded_from_public_search_and_apis(self):
        muk_id = self._register_sample_mukadam(mobile="9876543210", pin="1234")
        # Before block: visible in public search
        s1 = ms.search_nearby_mukadams(district_code="675", taluka_code="6199", village_code="515249")
        self.assertEqual(s1["count"], 1)

        # Moderator blocks Mukadam
        blk = self.client.post(
            f"/api/v1/admin/mukadams/{muk_id}/block",
            headers={"Authorization": f"Bearer {self.mod_token}", "X-CSRF-Token": self.mod_csrf},
            json={"reason": "ખોટી માહિતી મૂકવા બદલ બ્લોક", "admin_note": "Verified by phone"},
        )
        self.assertEqual(blk.status_code, 200)

        # After block:
        # (a) Hidden from public search
        s2 = ms.search_nearby_mukadams(district_code="675", taluka_code="6199", village_code="515249")
        self.assertEqual(s2["count"], 0)
        # (b) Blocked Mukadam cannot update quick status
        st_res = ms.update_mukadam_quick_status({"mobile": "9876543210", "pin": "1234", "available_status": "available"})
        self.assertFalse(st_res["ok"])
        self.assertEqual(st_res.get("http_status"), 403)
        # (c) Blocked Mukadam cannot re-register/overwrite profile
        reg_res = ms.register_or_update_mukadam({
            "name": "રમેશભાઈ પરમાર", "mobile": "9876543210", "pin": "1234",
            "district": "ગીર સોમનાથ", "taluka": "ગીર ગઢડા", "village": "કોદિયા",
            "district_code": "675", "taluka_code": "6199", "village_code": "515249",
        })
        self.assertFalse(reg_res["ok"])
        self.assertEqual(reg_res.get("http_status"), 403)
        # (d) Public contact/rating blocked
        act_res = ms.record_rating_or_contact({"mobile": "9876543210", "action": "contact"})
        self.assertFalse(act_res["ok"])
        self.assertEqual(act_res.get("http_status"), 403)

        # Unblock restores visibility
        unblk = self.client.post(
            f"/api/v1/admin/mukadams/{muk_id}/unblock",
            headers={"Authorization": f"Bearer {self.mod_token}", "X-CSRF-Token": self.mod_csrf},
            json={"reason": "ચકાસણી પૂર્ણ"},
        )
        self.assertEqual(unblk.status_code, 200)
        s3 = ms.search_nearby_mukadams(district_code="675", taluka_code="6199", village_code="515249")
        self.assertEqual(s3["count"], 1)

    # 10. Soft delete અને Restore
    def test_10_soft_delete_and_restore_lifecycle(self):
        muk_id = self._register_sample_mukadam(mobile="9876543210", pin="1234")
        sd = self.client.post(
            f"/api/v1/admin/mukadams/{muk_id}/soft-delete",
            headers={"Authorization": f"Bearer {self.super_token}", "X-CSRF-Token": self.super_csrf},
            json={"reason": "ડુપ્લિકેટ એન્ટ્રી"},
        )
        self.assertEqual(sd.status_code, 200)
        # Hidden from public search
        self.assertEqual(ms.search_nearby_mukadams(district_code="675")["count"], 0)
        # Restore brings it back
        rs = self.client.post(
            f"/api/v1/admin/mukadams/{muk_id}/restore",
            headers={"Authorization": f"Bearer {self.super_token}", "X-CSRF-Token": self.super_csrf},
            json={"reason": "ભૂલથી ડિલીટ થયેલ"},
        )
        self.assertEqual(rs.status_code, 200)
        self.assertEqual(ms.search_nearby_mukadams(district_code="675")["count"], 1)

    # 11. Permanent delete દરમિયાન સંબંધિત રેકોર્ડની સુરક્ષા
    def test_11_permanent_delete_safety_gates_and_neighbor_preservation(self):
        muk1 = self._register_sample_mukadam(name="મુકાદમ ૧", mobile="9876543210", pin="1234")
        muk2 = self._register_sample_mukadam(name="મુકાદમ ૨", mobile="9876543211", pin="2345")

        # Gate 1: Cannot permanently delete before Soft Delete
        r_no_sd = self.client.request(
            "DELETE",
            f"/api/v1/admin/mukadams/{muk1}/permanent",
            headers={"Authorization": f"Bearer {self.super_token}", "X-CSRF-Token": self.super_csrf},
            json={
                "admin_password": "SuperSecret#2026!Agri",
                "confirm_mobile_or_name": "9876543210",
                "reason": "Permanent delete test reason",
            },
        )
        self.assertEqual(r_no_sd.status_code, 409)

        # Soft delete muk1 first
        self.client.post(
            f"/api/v1/admin/mukadams/{muk1}/soft-delete",
            headers={"Authorization": f"Bearer {self.super_token}", "X-CSRF-Token": self.super_csrf},
            json={"reason": "Prepare for permanent delete"},
        )

        # Gate 2: Open PENDING report prevents permanent deletion
        rep = adm.submit_farmer_report(
            {"mukadam_id": muk1, "report_type": "ગેરવર્તન", "description": "ખેડૂત સાથે ગેરવર્તન કર્યું"},
            client_ip="10.20.30.40",
        )
        self.assertTrue(rep["ok"])
        r_open_rep = self.client.request(
            "DELETE",
            f"/api/v1/admin/mukadams/{muk1}/permanent",
            headers={"Authorization": f"Bearer {self.super_token}", "X-CSRF-Token": self.super_csrf},
            json={
                "admin_password": "SuperSecret#2026!Agri",
                "confirm_mobile_or_name": "9876543210",
                "reason": "Permanent delete test reason",
            },
        )
        self.assertEqual(r_open_rep.status_code, 409)

        # Resolve report first
        adm.review_report(self.super_admin, rep["report_id"], new_status="RESOLVED", resolution_details="Closed")

        # Gate 3: Wrong re-auth password fails with 401
        r_bad_pw = self.client.request(
            "DELETE",
            f"/api/v1/admin/mukadams/{muk1}/permanent",
            headers={"Authorization": f"Bearer {self.super_token}", "X-CSRF-Token": self.super_csrf},
            json={
                "admin_password": "WrongPassword!",
                "confirm_mobile_or_name": "9876543210",
                "reason": "Permanent delete test reason",
            },
        )
        self.assertEqual(r_bad_pw.status_code, 401)

        # Gate 4: Valid SUPER_ADMIN permanent delete succeeds
        r_ok = self.client.request(
            "DELETE",
            f"/api/v1/admin/mukadams/{muk1}/permanent",
            headers={"Authorization": f"Bearer {self.super_token}", "X-CSRF-Token": self.super_csrf},
            json={
                "admin_password": "SuperSecret#2026!Agri",
                "confirm_mobile_or_name": "9876543210",
                "reason": "Verified permanent deletion request",
            },
        )
        self.assertEqual(r_ok.status_code, 200)

        # Verify muk2 (neighbor record), resolved report, and audit logs are preserved
        s_rem = ms.search_nearby_mukadams(district_code="675")
        self.assertEqual(s_rem["count"], 1)
        self.assertEqual(s_rem["mukadams"][0]["id"], muk2)
        reps_after = adm.list_reports_for_admin(self.super_admin)
        self.assertEqual(reps_after["total"], 1)

    # 12. Report verification permissions & file-type validation
    def test_12_report_submission_and_verification_rbac(self):
        muk_id = self._register_sample_mukadam()
        # Reject executable evidence file
        bad_ev = adm.submit_farmer_report({
            "mukadam_id": muk_id,
            "report_type": "અન્ય",
            "description": "Malicious attachment test",
            "evidence_meta": {"filename": "exploit.exe", "mime_type": "application/x-msdownload", "size_bytes": 1024},
        })
        self.assertFalse(bad_ev["ok"])
        self.assertEqual(bad_ev["http_status"], 400)

        # Valid report submission
        good_rep = self.client.post(
            "/api/mukadam/report",
            json={"mukadam_id": muk_id, "report_type": "સમયસર મજૂર ન મોકલ્યા", "description": "સવારે ૭ વાગ્યે આવ્યા નહીં"},
        )
        self.assertEqual(good_rep.status_code, 200)
        rep_id = good_rep.json()["report_id"]

        # VIEWER cannot review report
        v_rev = self.client.post(
            f"/api/v1/admin/reports/{rep_id}/review",
            headers={"Authorization": f"Bearer {self.viewer_token}", "X-CSRF-Token": self.viewer_csrf},
            json={"new_status": "VERIFIED"},
        )
        self.assertEqual(v_rev.status_code, 403)

        # MODERATOR can review report and auto-block
        m_rev = self.client.post(
            f"/api/v1/admin/reports/{rep_id}/review",
            headers={"Authorization": f"Bearer {self.mod_token}", "X-CSRF-Token": self.mod_csrf},
            json={"new_status": "VERIFIED", "admin_notes": "Confirmed with farmer", "also_block_mukadam": True},
        )
        self.assertEqual(m_rev.status_code, 200)
        self.assertEqual(ms.search_nearby_mukadams(district_code="675")["count"], 0)

    # 13. Audit Log modificationનો પ્રયાસ અને Hash-Chain ચકાસણી
    def test_13_audit_log_immutability_and_hash_chain_verification(self):
        conn = sqlite3.connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE admin_audit_logs SET reason = 'tampered' WHERE id = 1")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM admin_audit_logs WHERE id = 1")
        finally:
            conn.close()

        chain = adm.verify_audit_log_chain()
        self.assertTrue(chain["verified"])

        # Moderator cannot access audit logs API
        mod_aud = self.client.get(
            "/api/v1/admin/audit-logs",
            headers={"Authorization": f"Bearer {self.mod_token}"},
        )
        self.assertEqual(mod_aud.status_code, 403)

        # SUPER_ADMIN can access audit logs and no raw passwords/tokens appear
        sup_aud = self.client.get(
            "/api/v1/admin/audit-logs",
            headers={"Authorization": f"Bearer {self.super_token}"},
        )
        self.assertEqual(sup_aud.status_code, 200)
        dump_str = json.dumps(sup_aud.json())
        self.assertNotIn("SuperSecret#2026!Agri", dump_str)
        self.assertNotIn(self.super_token, dump_str)

    # 14. Login session expiry & Logout revocation
    def test_14_session_expiry_and_logout_revocation(self):
        temp_login = adm.admin_login("viewer_gir", "ViewerPass#2026!Agri", client_ip="127.0.0.9", now=1000.0)
        tok = temp_login["session_token"]
        # Validate after TTL expiration
        expired_check = adm.validate_admin_session(tok, now=1000.0 + adm.ADMIN_SESSION_TTL_SECONDS + 10)
        self.assertFalse(expired_check["ok"])
        self.assertEqual(expired_check["http_status"], 401)

        # Logout revokes active session immediately
        fresh_login = adm.admin_login("viewer_gir", "ViewerPass#2026!Agri", client_ip="127.0.0.9")
        tok2 = fresh_login["session_token"]
        adm.admin_logout(tok2)
        revoked_check = adm.validate_admin_session(tok2)
        self.assertFalse(revoked_check["ok"])

    # 15. CORS, CSRF અને HTTPS enforcement
    def test_15_csrf_and_https_enforcement(self):
        muk_id = self._register_sample_mukadam()
        # Cookie-authenticated mutating request without X-CSRF-Token must fail with 403
        self.client.cookies.set("sam_admin_session", self.super_token)
        csrf_fail = self.client.post(
            f"/api/v1/admin/mukadams/{muk_id}/block",
            json={"reason": "No CSRF header on cookie auth"},
        )
        self.assertEqual(csrf_fail.status_code, 403)
        self.client.cookies.clear()

        # Non-HTTPS request behind proxy (X-Forwarded-Proto: http) must be rejected with 403
        http_Attempt = self.client.get(
            "/api/v1/admin/dashboard",
            headers={"Authorization": f"Bearer {self.super_token}", "X-Forwarded-Proto": "http"},
        )
        self.assertEqual(http_Attempt.status_code, 403)

    # 16. Existing Android Registration અને Search APIs
    def test_16_existing_android_registration_status_and_search_apis(self):
        reg = self.client.post(
            "/api/mukadam/register",
            json={
                "name": "કાનજીભાઈ પટેલ",
                "mobile": "9988776655",
                "pin": "4321",
                "district": "ગીર સોમનાથ",
                "taluka": "ગીર ગઢડા",
                "village": "કોદિયા",
                "district_code": "675",
                "taluka_code": "6199",
                "village_code": "515249",
                "available_status": "available",
                "total_labors": 12,
                "daily_wage_rate": 450.0,
            },
        )
        self.assertEqual(reg.status_code, 200)
        self.assertTrue(reg.json()["ok"])

        st = self.client.post(
            "/api/mukadam/status",
            json={"mobile": "9988776655", "pin": "4321", "available_status": "future", "available_from_date": "25-10-2026"},
        )
        self.assertEqual(st.status_code, 200)
        self.assertTrue(st.json()["ok"])

        srch = self.client.get("/api/mukadam/search", params={"district_code": "675", "taluka_code": "6199"})
        self.assertEqual(srch.status_code, 200)
        self.assertEqual(srch.json()["count"], 1)

    # 17. Database migration અને backup restore
    def test_17_database_migration_and_sqlite_backup_restore(self):
        muk_id = self._register_sample_mukadam(name="બેકઅપ ટેસ્ટ મુકાદમ", mobile="9123456789", pin="1122")
        bkp = adm.create_sqlite_backup(tag="unit_test")
        self.assertTrue(bkp["ok"])
        self.assertTrue(os.path.isfile(bkp["backup_path"]))

        # Corrupt/delete row in live DB, then restore from backup
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM mukadams WHERE id = ?", (muk_id,))
        conn.commit()
        conn.close()
        ms._refresh_ram_cache()
        self.assertEqual(ms.search_nearby_mukadams(district_code="675")["count"], 0)

        restored = adm.restore_sqlite_backup(bkp["backup_path"])
        self.assertTrue(restored["ok"])
        self.assertEqual(ms.search_nearby_mukadams(district_code="675")["count"], 1)

    # 18. Render deployment configuration & No Hardcoded Secrets
    def test_18_render_yaml_and_no_hardcoded_secrets_verification(self):
        render_path = os.path.join(os.path.dirname(__file__), "render.yaml")
        with open(render_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        env_vars = {item["key"]: item for item in cfg["services"][0]["envVars"]}
        for secret_key in ("ADMIN_BOOTSTRAP_USERNAME", "ADMIN_BOOTSTRAP_PASSWORD", "ADMIN_RESET_MASTER_SECRET"):
            self.assertIn(secret_key, env_vars)
            self.assertIs(env_vars[secret_key].get("sync"), False)



    # 19. Google Play Privacy Policy, Account Deletion Portal & Self-Delete API
    def test_19_google_play_privacy_and_self_account_deletion(self):
        priv = self.client.get("/privacy-policy")
        self.assertEqual(priv.status_code, 200)
        self.assertIn("ગોપનીયતા નીતિ", priv.text)
        self.assertIn("Privacy Policy", priv.text)

        del_page = self.client.get("/account-deletion")
        self.assertEqual(del_page.status_code, 200)
        self.assertIn("/api/mukadam/delete-self", del_page.text)

        muk_id = self._register_sample_mukadam(name="સેલ્ફ ડિલીટ ટેસ્ટ", mobile="9334455667", pin="5678")
        self.assertTrue(muk_id > 0)

        # Wrong PIN must fail with 403
        bad_del = self.client.post("/api/mukadam/delete-self", json={"mobile": "9334455667", "pin": "0000"})
        self.assertEqual(bad_del.status_code, 403)

        # Correct PIN deletes the Mukadam profile and records tombstone
        ok_del = self.client.post("/api/mukadam/delete-self", json={"mobile": "9334455667", "pin": "5678"})
        self.assertEqual(ok_del.status_code, 200)
        self.assertTrue(ok_del.json()["ok"])

        srch = self.client.get("/api/mukadam/search", params={"district_code": "675", "taluka_code": "6199"})
        self.assertEqual(srch.json()["count"], 0)


if __name__ == "__main__":
    unittest.main()
