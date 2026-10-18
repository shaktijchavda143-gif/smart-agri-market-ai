# -*- coding: utf-8 -*-
"""
Secure Admin Panel, RBAC, Moderation, Complaint Verification, Backup/Restore,
and Immutable Hash-Chained Audit Log Service for Smart Agri-Market AI.
"""
import sys as _sys, os as _os
_BACKEND_DIR = _os.path.dirname(_os.path.abspath(__file__))
if _BACKEND_DIR not in _sys.path:
    _sys.path.insert(0, _BACKEND_DIR)

import os
import re
import json
import time
import uuid
import shutil
import base64
import hashlib
import hmac
import secrets
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

try:
    import mukadam_service as ms
except ImportError:
    from . import mukadam_service as ms

# ---------------------------------------------------------------------------
# Security Constants & Role Definitions
# ---------------------------------------------------------------------------
ROLE_SUPER_ADMIN = "SUPER_ADMIN"
ROLE_MODERATOR = "MODERATOR"
ROLE_VIEWER = "VIEWER"
VALID_ROLES = {ROLE_SUPER_ADMIN, ROLE_MODERATOR, ROLE_VIEWER}

DEFAULT_ROLE_PERMISSIONS = {
    ROLE_SUPER_ADMIN: [
        "dashboard:view",
        "mukadam:view",
        "mukadam:view_sensitive",
        "mukadam:block",
        "mukadam:unblock",
        "mukadam:soft_delete",
        "mukadam:restore",
        "mukadam:permanent_delete",
        "mukadam:export",
        "reports:view",
        "reports:review",
        "audit:view",
        "admins:manage",
        "backup:manage",
    ],
    ROLE_MODERATOR: [
        "dashboard:view",
        "mukadam:view",
        "mukadam:view_sensitive",
        "mukadam:block",
        "mukadam:unblock",
        "mukadam:export",
        "reports:view",
        "reports:review",
    ],
    ROLE_VIEWER: [
        "dashboard:view",
        "mukadam:view",
    ],
}

ADMIN_PBKDF2_ITERATIONS = 310_000
ADMIN_HASH_PREFIX = "pbkdf2_sha256"

ADMIN_LOGIN_USER_FAIL_LIMIT = 5
ADMIN_LOGIN_IP_FAIL_LIMIT = 15
ADMIN_LOGIN_LOCKOUT_SECONDS = 15 * 60

ADMIN_SESSION_TTL_SECONDS = int(os.environ.get("ADMIN_SESSION_TTL_SECONDS", str(8 * 3600)) or (8 * 3600))
ADMIN_SESSION_IDLE_SECONDS = int(os.environ.get("ADMIN_SESSION_IDLE_SECONDS", str(2 * 3600)) or (2 * 3600))

REPORT_STATUSES = {"PENDING", "UNDER_REVIEW", "VERIFIED", "REJECTED", "RESOLVED"}
VALID_REPORT_TYPES = {
    "સમયસર મજૂર ન મોકલ્યા",
    "ખોટો ભાવ / છેતરપિંડી",
    "ગેરવર્તન",
    "ખોટી માહિતી",
    "અન્ય",
}
REPORT_IP_LIMIT_PER_HOUR = 5
ALLOWED_EVIDENCE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MAX_EVIDENCE_BYTES = 2 * 1024 * 1024  # 2 MB max

SENSITIVE_AUDIT_KEYS = {
    "password", "new_password", "old_password", "confirm_password",
    "pin", "pin_hash", "password_hash", "token", "access_token",
    "session_token", "csrf_token", "secret", "reset_token", "master_secret",
    "mobile", "reporter_mobile",
}


def _db_path() -> str:
    return ms.DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def hash_admin_password(password: str) -> str:
    pwd = str(password or "")
    if len(pwd) < 10:
        raise ValueError("Admin password must be at least 10 characters long.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, ADMIN_PBKDF2_ITERATIONS)
    return f"{ADMIN_HASH_PREFIX}${ADMIN_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_admin_password(stored_hash: str, password: str) -> bool:
    pwd = str(password or "")
    stored = str(stored_hash or "")
    if not pwd or not stored.startswith(ADMIN_HASH_PREFIX + "$"):
        return False
    try:
        prefix, iter_str, salt_hex, digest_hex = stored.split("$", 3)
        iterations = int(iter_str)
        if prefix != ADMIN_HASH_PREFIX or iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _mask_mobile(mobile: str) -> str:
    clean = ms._clean_mobile(mobile)
    if len(clean) != 10:
        return "**********"
    return f"{clean[:2]}******{clean[-2:]}"


def _sanitize_text(value: Any, max_len: int = 500) -> str:
    text = str(value or "").strip()
    text = "".join(ch for ch in text if ch in ("\n", "\t") or ord(ch) >= 32)
    return text[:max_len]


def _scrub_audit_metadata(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    cleaned: Dict[str, Any] = {}
    for k, v in meta.items():
        key_str = str(k).strip()
        key_lower = key_str.lower()
        if any(s in key_lower for s in SENSITIVE_AUDIT_KEYS):
            if "mobile" in key_lower and isinstance(v, str):
                cleaned["mobile_masked"] = _mask_mobile(v)
            continue
        if isinstance(v, dict):
            cleaned[key_str] = _scrub_audit_metadata(v)
        elif isinstance(v, (list, tuple)):
            cleaned[key_str] = [
                _scrub_audit_metadata(x) if isinstance(x, dict) else _sanitize_text(x, 200)
                for x in v[:25]
            ]
        elif isinstance(v, (int, float, bool)) or v is None:
            cleaned[key_str] = v
        else:
            val_str = _sanitize_text(v, 300)
            val_str = re.sub(r"\b([6-9][0-9])([0-9]{6})([0-9]{2})\b", r"\1******\3", val_str)
            cleaned[key_str] = val_str
    return cleaned


def init_admin_schema(conn: Optional[sqlite3.Connection] = None) -> None:
    owns_conn = conn is None
    if owns_conn:
        conn = _connect()
    try:
        existing_cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(mukadams)").fetchall()}
        migrations = [
            ("created_at", "REAL NOT NULL DEFAULT 0.0"),
            ("account_status", "TEXT NOT NULL DEFAULT 'ACTIVE'"),
            ("is_blocked", "INTEGER NOT NULL DEFAULT 0"),
            ("blocked_at", "REAL DEFAULT NULL"),
            ("blocked_by", "TEXT NOT NULL DEFAULT ''"),
            ("block_reason", "TEXT NOT NULL DEFAULT ''"),
            ("block_admin_note", "TEXT NOT NULL DEFAULT ''"),
            ("block_expires_at", "REAL DEFAULT NULL"),
            ("deleted_at", "REAL DEFAULT NULL"),
            ("deleted_by", "TEXT NOT NULL DEFAULT ''"),
            ("deletion_reason", "TEXT NOT NULL DEFAULT ''"),
            ("previous_status", "TEXT NOT NULL DEFAULT ''"),
        ]
        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE mukadams ADD COLUMN {col_name} {col_def}")

        conn.execute("UPDATE mukadams SET created_at = updated_at WHERE created_at <= 0 AND updated_at > 0")
        conn.execute("UPDATE mukadams SET created_at = ? WHERE created_at <= 0", (time.time(),))

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mukadam_deleted_tombstones (
                mobile TEXT PRIMARY KEY,
                mukadam_id INTEGER NOT NULL DEFAULT 0,
                deleted_at REAL NOT NULL,
                deleted_by TEXT NOT NULL DEFAULT '',
                reason_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'VIEWER',
                permissions_json TEXT NOT NULL DEFAULT '[]',
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_login_at REAL DEFAULT NULL,
                password_reset_token_hash TEXT NOT NULL DEFAULT '',
                password_reset_expires_at REAL DEFAULT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_sessions (
                session_id_hash TEXT PRIMARY KEY,
                admin_id INTEGER NOT NULL,
                csrf_token TEXT NOT NULL,
                client_ip TEXT NOT NULL DEFAULT '',
                user_agent TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                last_seen_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                revoked_at REAL DEFAULT NULL,
                revoked_reason TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(admin_id) REFERENCES admin_users(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL DEFAULT '',
                client_ip TEXT NOT NULL DEFAULT '',
                success INTEGER NOT NULL DEFAULT 0,
                attempted_at REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_login_user_time ON admin_login_attempts(username, attempted_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_login_ip_time ON admin_login_attempts(client_ip, attempted_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mukadam_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mukadam_id INTEGER NOT NULL,
                mukadam_mobile_masked TEXT NOT NULL DEFAULT '',
                report_type TEXT NOT NULL,
                description TEXT NOT NULL,
                reporter_name TEXT NOT NULL DEFAULT '',
                reporter_mobile_hash TEXT NOT NULL DEFAULT '',
                reporter_mobile_masked TEXT NOT NULL DEFAULT '',
                client_ip TEXT NOT NULL DEFAULT '',
                evidence_meta_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'PENDING',
                assigned_moderator TEXT NOT NULL DEFAULT '',
                admin_notes TEXT NOT NULL DEFAULT '',
                resolution_details TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mukadam_reports_mukadam_id ON mukadam_reports(mukadam_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mukadam_reports_status ON mukadam_reports(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mukadam_reports_ip_time ON mukadam_reports(client_ip, created_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mukadam_public_action_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mobile TEXT NOT NULL DEFAULT '',
                client_ip TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT '',
                attempted_at REAL NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_public_action_ip_time ON mukadam_public_action_attempts(client_ip, attempted_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                admin_id INTEGER DEFAULT NULL,
                admin_username TEXT NOT NULL DEFAULT '',
                admin_role TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT '',
                target_id TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                request_id TEXT NOT NULL DEFAULT '',
                client_ip TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                prev_hash TEXT NOT NULL DEFAULT '',
                entry_hash TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_time ON admin_audit_logs(timestamp DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_target ON admin_audit_logs(target_type, target_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON admin_audit_logs(action)")

        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_admin_audit_logs_no_update
            BEFORE UPDATE ON admin_audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'SECURITY_VIOLATION: admin_audit_logs is append-only and cannot be updated');
            END;
            """
        )
        conn.execute(
            """
            CREATE TRIGGER IF NOT EXISTS trg_admin_audit_logs_no_delete
            BEFORE DELETE ON admin_audit_logs
            BEGIN
                SELECT RAISE(ABORT, 'SECURITY_VIOLATION: admin_audit_logs is append-only and cannot be deleted');
            END;
            """
        )

        if owns_conn:
            conn.commit()
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _compute_audit_hash(
    prev_hash: str,
    timestamp: float,
    admin_id: Optional[int],
    admin_username: str,
    admin_role: str,
    action: str,
    target_type: str,
    target_id: str,
    result: str,
    reason: str,
    request_id: str,
    client_ip: str,
    metadata_json: str,
) -> str:
    canonical = "|".join([
        str(prev_hash or "GENESIS"),
        f"{float(timestamp):.6f}",
        str(admin_id if admin_id is not None else ""),
        str(admin_username or ""),
        str(admin_role or ""),
        str(action or ""),
        str(target_type or ""),
        str(target_id or ""),
        str(result or ""),
        str(reason or ""),
        str(request_id or ""),
        str(client_ip or ""),
        str(metadata_json or "{}"),
    ])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_audit_log(
    conn: sqlite3.Connection,
    *,
    admin_id: Optional[int],
    admin_username: str,
    admin_role: str,
    action: str,
    target_type: str = "",
    target_id: str = "",
    result: str = "SUCCESS",
    reason: str = "",
    request_id: str = "",
    client_ip: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    now: Optional[float] = None,
) -> int:
    stamp = round(float(now if now is not None else time.time()), 6)
    req_id = _sanitize_text(request_id or uuid.uuid4().hex, 64)
    clean_reason = _sanitize_text(reason, 400)
    clean_ip = ms._client_ip_key(client_ip)
    safe_meta = _scrub_audit_metadata(metadata)
    meta_json = json.dumps(safe_meta, ensure_ascii=False, sort_keys=True)

    last_row = conn.execute(
        "SELECT entry_hash FROM admin_audit_logs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    prev_hash = str(last_row[0]) if last_row else "GENESIS"
    entry_hash = _compute_audit_hash(
        prev_hash=prev_hash,
        timestamp=stamp,
        admin_id=admin_id,
        admin_username=admin_username,
        admin_role=admin_role,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        result=result,
        reason=clean_reason,
        request_id=req_id,
        client_ip=clean_ip,
        metadata_json=meta_json,
    )
    cursor = conn.execute(
        """
        INSERT INTO admin_audit_logs (
            timestamp, admin_id, admin_username, admin_role, action,
            target_type, target_id, result, reason, request_id,
            client_ip, metadata_json, prev_hash, entry_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stamp,
            admin_id,
            _sanitize_text(admin_username, 80),
            _sanitize_text(admin_role, 40),
            _sanitize_text(action, 80),
            _sanitize_text(target_type, 50),
            _sanitize_text(target_id, 80),
            _sanitize_text(result, 30),
            clean_reason,
            req_id,
            clean_ip,
            meta_json,
            prev_hash,
            entry_hash,
        ),
    )
    return int(cursor.lastrowid or 0)


def verify_audit_log_chain() -> Dict[str, Any]:
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            rows = conn.execute("SELECT * FROM admin_audit_logs ORDER BY id ASC").fetchall()
            prev_hash = "GENESIS"
            for row in rows:
                expected = _compute_audit_hash(
                    prev_hash=prev_hash,
                    timestamp=float(row["timestamp"]),
                    admin_id=row["admin_id"],
                    admin_username=str(row["admin_username"]),
                    admin_role=str(row["admin_role"]),
                    action=str(row["action"]),
                    target_type=str(row["target_type"]),
                    target_id=str(row["target_id"]),
                    result=str(row["result"]),
                    reason=str(row["reason"]),
                    request_id=str(row["request_id"]),
                    client_ip=str(row["client_ip"]),
                    metadata_json=str(row["metadata_json"]),
                )
                if str(row["prev_hash"]) != prev_hash or not hmac.compare_digest(str(row["entry_hash"]), expected):
                    return {
                        "ok": False,
                        "verified": False,
                        "total_entries": len(rows),
                        "broken_at_id": int(row["id"]),
                    }
                prev_hash = str(row["entry_hash"])
            return {
                "ok": True,
                "verified": True,
                "total_entries": len(rows),
                "head_hash": prev_hash,
            }
        finally:
            conn.close()


def bootstrap_admin_from_env() -> bool:
    username = os.environ.get("ADMIN_BOOTSTRAP_USERNAME", "").strip()
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "").strip()
    display_name = os.environ.get("ADMIN_BOOTSTRAP_DISPLAY_NAME", "મુખ્ય એડમિન (Super Admin)").strip()
    if not username or not password:
        return False
    if len(password) < 10:
        return False

    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            init_admin_schema(conn)
            existing = conn.execute(
                "SELECT id, role FROM admin_users WHERE lower(username) = lower(?)",
                (username,),
            ).fetchone()
            now = time.time()
            if existing:
                conn.commit()
                return True
            pwd_hash = hash_admin_password(password)
            perms = json.dumps(DEFAULT_ROLE_PERMISSIONS[ROLE_SUPER_ADMIN])
            cursor = conn.execute(
                """
                INSERT INTO admin_users (
                    username, display_name, role, permissions_json, password_hash,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (username, display_name, ROLE_SUPER_ADMIN, perms, pwd_hash, now, now),
            )
            admin_id = int(cursor.lastrowid or 0)
            append_audit_log(
                conn,
                admin_id=admin_id,
                admin_username=username,
                admin_role=ROLE_SUPER_ADMIN,
                action="ADMIN_BOOTSTRAP",
                target_type="admin_user",
                target_id=str(admin_id),
                result="SUCCESS",
                reason="Initial SUPER_ADMIN bootstrapped via environment variables",
                metadata={"username": username, "role": ROLE_SUPER_ADMIN},
                now=now,
            )
            conn.commit()
            return True
        finally:
            conn.close()


def _is_login_rate_limited(conn: sqlite3.Connection, username: str, client_ip: str, now: float) -> bool:
    cutoff = now - ADMIN_LOGIN_LOCKOUT_SECONDS
    user_key = username.strip().lower()
    ip_key = ms._client_ip_key(client_ip)
    if user_key:
        user_fails = int(conn.execute(
            "SELECT COUNT(*) FROM admin_login_attempts WHERE lower(username) = ? AND success = 0 AND attempted_at >= ?",
            (user_key, cutoff),
        ).fetchone()[0] or 0)
        if user_fails >= ADMIN_LOGIN_USER_FAIL_LIMIT:
            return True
    if ip_key:
        ip_fails = int(conn.execute(
            "SELECT COUNT(*) FROM admin_login_attempts WHERE client_ip = ? AND success = 0 AND attempted_at >= ?",
            (ip_key, cutoff),
        ).fetchone()[0] or 0)
        if ip_fails >= ADMIN_LOGIN_IP_FAIL_LIMIT:
            return True
    return False


def _record_login_attempt(conn: sqlite3.Connection, username: str, client_ip: str, success: bool, now: float) -> None:
    conn.execute(
        "INSERT INTO admin_login_attempts (username, client_ip, success, attempted_at) VALUES (?, ?, ?, ?)",
        (username.strip().lower()[:80], ms._client_ip_key(client_ip), 1 if success else 0, now),
    )
    conn.execute("DELETE FROM admin_login_attempts WHERE attempted_at < ?", (now - 24 * 3600,))


def admin_login(
    username: str,
    password: str,
    client_ip: str = "unknown",
    user_agent: str = "",
    request_id: str = "",
    now: Optional[float] = None,
) -> Dict[str, Any]:
    now_ts = float(now if now is not None else time.time())
    clean_user = _sanitize_text(username, 80)
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            if _is_login_rate_limited(conn, clean_user, client_ip, now_ts):
                append_audit_log(
                    conn,
                    admin_id=None,
                    admin_username=clean_user,
                    admin_role="UNAUTHENTICATED",
                    action="ADMIN_LOGIN",
                    target_type="auth",
                    target_id=clean_user,
                    result="DENIED",
                    reason="Rate limit exceeded (brute-force protection)",
                    request_id=request_id,
                    client_ip=client_ip,
                    now=now_ts,
                )
                conn.commit()
                return {
                    "ok": False,
                    "http_status": 429,
                    "message_gu": "ઘણા ખોટા લોગિન પ્રયાસ થયા છે. સુરક્ષા માટે ૧૫ મિનિટ પછી ફરી પ્રયાસ કરો.",
                }

            row = conn.execute(
                "SELECT * FROM admin_users WHERE lower(username) = lower(?)",
                (clean_user,),
            ).fetchone()

            if not row or int(row["is_active"] or 0) != 1 or not verify_admin_password(str(row["password_hash"]), password):
                _record_login_attempt(conn, clean_user, client_ip, False, now_ts)
                append_audit_log(
                    conn,
                    admin_id=int(row["id"]) if row else None,
                    admin_username=clean_user,
                    admin_role=str(row["role"]) if row else "UNAUTHENTICATED",
                    action="ADMIN_LOGIN",
                    target_type="auth",
                    target_id=clean_user,
                    result="FAILURE",
                    reason="Invalid credentials or inactive account",
                    request_id=request_id,
                    client_ip=client_ip,
                    now=now_ts,
                )
                conn.commit()
                return {
                    "ok": False,
                    "http_status": 401,
                    "message_gu": "યુઝરનેમ અથવા પાસવર્ડ ખોટો છે.",
                }

            _record_login_attempt(conn, clean_user, client_ip, True, now_ts)
            raw_session_token = secrets.token_urlsafe(32)
            session_id_hash = _sha256_hex(raw_session_token)
            csrf_token = secrets.token_hex(24)
            expires_at = now_ts + ADMIN_SESSION_TTL_SECONDS

            conn.execute(
                """
                INSERT INTO admin_sessions (
                    session_id_hash, admin_id, csrf_token, client_ip, user_agent,
                    created_at, last_seen_at, expires_at, revoked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    session_id_hash,
                    int(row["id"]),
                    csrf_token,
                    ms._client_ip_key(client_ip),
                    _sanitize_text(user_agent, 180),
                    now_ts,
                    now_ts,
                    expires_at,
                ),
            )
            conn.execute(
                "UPDATE admin_users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (now_ts, now_ts, int(row["id"])),
            )
            append_audit_log(
                conn,
                admin_id=int(row["id"]),
                admin_username=str(row["username"]),
                admin_role=str(row["role"]),
                action="ADMIN_LOGIN",
                target_type="admin_user",
                target_id=str(row["id"]),
                result="SUCCESS",
                reason="Admin login successful",
                request_id=request_id,
                client_ip=client_ip,
                now=now_ts,
            )
            conn.commit()

            perms = _effective_permissions(str(row["role"]), str(row["permissions_json"]))
            return {
                "ok": True,
                "http_status": 200,
                "message_gu": "સફળતાપૂર્વક લોગિન થયું છે.",
                "session_token": raw_session_token,
                "csrf_token": csrf_token,
                "expires_at": expires_at,
                "admin": {
                    "id": int(row["id"]),
                    "username": str(row["username"]),
                    "display_name": str(row["display_name"]),
                    "role": str(row["role"]),
                    "permissions": perms,
                },
            }
        finally:
            conn.close()


def _effective_permissions(role: str, permissions_json: str) -> List[str]:
    role_clean = str(role or "").strip().upper()
    if role_clean == ROLE_SUPER_ADMIN:
        return list(DEFAULT_ROLE_PERMISSIONS[ROLE_SUPER_ADMIN])
    if role_clean == ROLE_VIEWER:
        return list(DEFAULT_ROLE_PERMISSIONS[ROLE_VIEWER])
    allowed_for_mod = set(DEFAULT_ROLE_PERMISSIONS[ROLE_MODERATOR])
    try:
        custom = json.loads(permissions_json or "[]")
        if isinstance(custom, list) and custom:
            filtered = [str(p) for p in custom if str(p) in allowed_for_mod]
            if filtered:
                return filtered
    except Exception:
        pass
    return list(DEFAULT_ROLE_PERMISSIONS[ROLE_MODERATOR])


def validate_admin_session(
    session_token: str,
    *,
    csrf_token: Optional[str] = None,
    require_csrf: bool = False,
    required_permission: Optional[str] = None,
    allowed_roles: Optional[set] = None,
    client_ip: str = "unknown",
    request_id: str = "",
    now: Optional[float] = None,
) -> Dict[str, Any]:
    now_ts = float(now if now is not None else time.time())
    raw_token = str(session_token or "").strip()
    if not raw_token:
        return {"ok": False, "http_status": 401, "message_gu": "Admin લોગિન જરૂરી છે."}

    session_hash = _sha256_hex(raw_token)
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT s.*, u.username, u.display_name, u.role, u.permissions_json, u.is_active
                FROM admin_sessions s
                JOIN admin_users u ON u.id = s.admin_id
                WHERE s.session_id_hash = ?
                """,
                (session_hash,),
            ).fetchone()

            if not row:
                return {"ok": False, "http_status": 401, "message_gu": "અમાન્ય અથવા સમાપ્ત થયેલ સેશન. ફરીથી લોગિન કરો."}

            if int(row["revoked"] or 0) == 1 or int(row["is_active"] or 0) != 1:
                return {"ok": False, "http_status": 401, "message_gu": "તમારું સેશન રદ કરવામાં આવ્યું છે. ફરીથી લોગિન કરો."}

            if now_ts >= float(row["expires_at"]) or (now_ts - float(row["last_seen_at"])) > ADMIN_SESSION_IDLE_SECONDS:
                conn.execute(
                    "UPDATE admin_sessions SET revoked = 1, revoked_at = ?, revoked_reason = 'expired' WHERE session_id_hash = ?",
                    (now_ts, session_hash),
                )
                conn.commit()
                return {"ok": False, "http_status": 401, "message_gu": "સેશનનો સમય પૂરો થયો છે. ફરીથી લોગિન કરો."}

            if require_csrf:
                provided_csrf = str(csrf_token or "").strip()
                if not provided_csrf or not hmac.compare_digest(provided_csrf, str(row["csrf_token"])):
                    append_audit_log(
                        conn,
                        admin_id=int(row["admin_id"]),
                        admin_username=str(row["username"]),
                        admin_role=str(row["role"]),
                        action="CSRF_CHECK",
                        target_type="session",
                        target_id=str(row["admin_id"]),
                        result="DENIED",
                        reason="Missing or invalid CSRF token",
                        request_id=request_id,
                        client_ip=client_ip,
                        now=now_ts,
                    )
                    conn.commit()
                    return {"ok": False, "http_status": 403, "message_gu": "સુરક્ષા ચકાસણી (CSRF Token) નિષ્ફળ ગઈ."}

            role = str(row["role"]).upper()
            perms = _effective_permissions(role, str(row["permissions_json"]))

            if allowed_roles and role not in allowed_roles:
                append_audit_log(
                    conn,
                    admin_id=int(row["admin_id"]),
                    admin_username=str(row["username"]),
                    admin_role=role,
                    action="RBAC_CHECK",
                    target_type="role",
                    target_id=",".join(sorted(allowed_roles)),
                    result="DENIED",
                    reason=f"Role {role} is not permitted for this operation",
                    request_id=request_id,
                    client_ip=client_ip,
                    now=now_ts,
                )
                conn.commit()
                return {"ok": False, "http_status": 403, "message_gu": "આ કામગીરી માટે તમારી પાસે પરવાનગી (Role Permission) નથી."}

            if required_permission and required_permission not in perms:
                append_audit_log(
                    conn,
                    admin_id=int(row["admin_id"]),
                    admin_username=str(row["username"]),
                    admin_role=role,
                    action="RBAC_CHECK",
                    target_type="permission",
                    target_id=required_permission,
                    result="DENIED",
                    reason=f"Permission '{required_permission}' missing for role {role}",
                    request_id=request_id,
                    client_ip=client_ip,
                    now=now_ts,
                )
                conn.commit()
                return {"ok": False, "http_status": 403, "message_gu": "આ કામગીરી માટે તમારી પાસે પૂરતી પરવાનગી નથી."}

            conn.execute(
                "UPDATE admin_sessions SET last_seen_at = ? WHERE session_id_hash = ?",
                (now_ts, session_hash),
            )
            conn.commit()

            return {
                "ok": True,
                "http_status": 200,
                "session_id_hash": session_hash,
                "csrf_token": str(row["csrf_token"]),
                "admin": {
                    "id": int(row["admin_id"]),
                    "username": str(row["username"]),
                    "display_name": str(row["display_name"]),
                    "role": role,
                    "permissions": perms,
                },
            }
        finally:
            conn.close()


def admin_logout(session_token: str, client_ip: str = "unknown", request_id: str = "") -> Dict[str, Any]:
    raw_token = str(session_token or "").strip()
    if not raw_token:
        return {"ok": True, "message_gu": "લોગઆઉટ પૂર્ણ થયું."}
    session_hash = _sha256_hex(raw_token)
    now = time.time()
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                """
                SELECT s.admin_id, u.username, u.role
                FROM admin_sessions s
                JOIN admin_users u ON u.id = s.admin_id
                WHERE s.session_id_hash = ?
                """,
                (session_hash,),
            ).fetchone()
            conn.execute(
                "UPDATE admin_sessions SET revoked = 1, revoked_at = ?, revoked_reason = 'logout' WHERE session_id_hash = ?",
                (now, session_hash),
            )
            if row:
                append_audit_log(
                    conn,
                    admin_id=int(row["admin_id"]),
                    admin_username=str(row["username"]),
                    admin_role=str(row["role"]),
                    action="ADMIN_LOGOUT",
                    target_type="admin_user",
                    target_id=str(row["admin_id"]),
                    result="SUCCESS",
                    reason="Admin logged out",
                    request_id=request_id,
                    client_ip=client_ip,
                    now=now,
                )
            conn.commit()
            return {"ok": True, "message_gu": "સફળતાપૂર્વક લોગઆઉટ થયું છે."}
        finally:
            conn.close()


def reset_admin_password_with_master_secret(
    username: str,
    new_password: str,
    provided_master_secret: str,
    client_ip: str = "unknown",
    request_id: str = "",
) -> Dict[str, Any]:
    configured_secret = os.environ.get("ADMIN_RESET_MASTER_SECRET", "").strip()
    if not configured_secret or len(configured_secret) < 16:
        return {
            "ok": False,
            "http_status": 403,
            "message_gu": "પાસવર્ડ રીસેટ સિક્રેટ સર્વર પર સેટ કરેલ નથી.",
        }
    if not hmac.compare_digest(configured_secret, str(provided_master_secret or "").strip()):
        with ms._MUKADAM_LOCK:
            conn = _connect()
            try:
                append_audit_log(
                    conn,
                    admin_id=None,
                    admin_username=_sanitize_text(username, 80),
                    admin_role="UNAUTHENTICATED",
                    action="ADMIN_PASSWORD_RESET",
                    target_type="admin_user",
                    target_id=_sanitize_text(username, 80),
                    result="DENIED",
                    reason="Invalid ADMIN_RESET_MASTER_SECRET",
                    request_id=request_id,
                    client_ip=client_ip,
                )
                conn.commit()
            finally:
                conn.close()
        return {"ok": False, "http_status": 403, "message_gu": "અમાન્ય માસ્ટર રીસેટ સિક્રેટ."}

    if len(str(new_password or "")) < 10:
        return {"ok": False, "http_status": 400, "message_gu": "નવો પાસવર્ડ ઓછામાં ઓછો ૧૦ અક્ષરનો હોવો જોઈએ."}

    now = time.time()
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, username, role FROM admin_users WHERE lower(username) = lower(?)",
                (_sanitize_text(username, 80),),
            ).fetchone()
            if not row:
                return {"ok": False, "http_status": 404, "message_gu": "આ નામનું Admin એકાઉન્ટ મળ્યું નથી."}
            new_hash = hash_admin_password(new_password)
            conn.execute(
                "UPDATE admin_users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (new_hash, now, int(row["id"])),
            )
            conn.execute(
                "UPDATE admin_sessions SET revoked = 1, revoked_at = ?, revoked_reason = 'password_reset' WHERE admin_id = ?",
                (now, int(row["id"])),
            )
            append_audit_log(
                conn,
                admin_id=int(row["id"]),
                admin_username=str(row["username"]),
                admin_role=str(row["role"]),
                action="ADMIN_PASSWORD_RESET",
                target_type="admin_user",
                target_id=str(row["id"]),
                result="SUCCESS",
                reason="Password reset via verified master secret; all active sessions revoked",
                request_id=request_id,
                client_ip=client_ip,
                now=now,
            )
            conn.commit()
            return {"ok": True, "http_status": 200, "message_gu": "પાસવર્ડ બદલાઈ ગયો છે અને જૂના બધા સેશન બંધ કરવામાં આવ્યા છે."}
        finally:
            conn.close()


def create_or_update_admin_user(
    actor: Dict[str, Any],
    *,
    username: str,
    display_name: str,
    role: str,
    password: Optional[str] = None,
    permissions: Optional[List[str]] = None,
    is_active: bool = True,
    client_ip: str = "unknown",
    request_id: str = "",
) -> Dict[str, Any]:
    if actor.get("role") != ROLE_SUPER_ADMIN:
        return {"ok": False, "http_status": 403, "message_gu": "ફક્ત SUPER_ADMIN જ અન્ય એડમિનના રોલ બનાવી કે બદલી શકે છે."}

    clean_user = _sanitize_text(username, 60)
    clean_name = _sanitize_text(display_name or clean_user, 80)
    clean_role = str(role or "").strip().upper()
    if not clean_user or not re.match(r"^[A-Za-z0-9_.\-@]{3,60}$", clean_user):
        return {"ok": False, "http_status": 400, "message_gu": "માન્ય યુઝરનેમ (3-60 અક્ષર) દાખલ કરો."}
    if clean_role not in VALID_ROLES:
        return {"ok": False, "http_status": 400, "message_gu": "અમાન્ય રોલ. SUPER_ADMIN, MODERATOR અથવા VIEWER પસંદ કરો."}

    eff_perms = _effective_permissions(clean_role, json.dumps(permissions or []))
    now = time.time()
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT * FROM admin_users WHERE lower(username) = lower(?)",
                (clean_user,),
            ).fetchone()
            if existing:
                if int(existing["id"]) == int(actor["id"]) and (not is_active or clean_role != ROLE_SUPER_ADMIN):
                    return {"ok": False, "http_status": 400, "message_gu": "પોતાના SUPER_ADMIN એકાઉન્ટનો રોલ ઘટાડી કે બંધ કરી શકાતો નથી."}
                pwd_hash = hash_admin_password(password) if password else str(existing["password_hash"])
                conn.execute(
                    """
                    UPDATE admin_users
                    SET display_name = ?, role = ?, permissions_json = ?, password_hash = ?, is_active = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (clean_name, clean_role, json.dumps(eff_perms), pwd_hash, 1 if is_active else 0, now, int(existing["id"])),
                )
                if not is_active or clean_role != str(existing["role"]):
                    conn.execute(
                        "UPDATE admin_sessions SET revoked = 1, revoked_at = ?, revoked_reason = 'role_or_status_changed' WHERE admin_id = ?",
                        (now, int(existing["id"])),
                    )
                target_id = int(existing["id"])
                action_name = "ADMIN_ROLE_UPDATED"
            else:
                if not password or len(str(password)) < 10:
                    return {"ok": False, "http_status": 400, "message_gu": "નવા એડમિન માટે ઓછામાં ઓછો ૧૦ અક્ષરનો પાસવર્ડ રાખવો ફરજિયાત છે."}
                pwd_hash = hash_admin_password(password)
                cursor = conn.execute(
                    """
                    INSERT INTO admin_users (
                        username, display_name, role, permissions_json, password_hash,
                        is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (clean_user, clean_name, clean_role, json.dumps(eff_perms), pwd_hash, 1 if is_active else 0, now, now),
                )
                target_id = int(cursor.lastrowid or 0)
                action_name = "ADMIN_USER_CREATED"

            append_audit_log(
                conn,
                admin_id=int(actor["id"]),
                admin_username=str(actor["username"]),
                admin_role=str(actor["role"]),
                action=action_name,
                target_type="admin_user",
                target_id=str(target_id),
                result="SUCCESS",
                reason=f"Set role={clean_role}, active={is_active}",
                request_id=request_id,
                client_ip=client_ip,
                metadata={"target_username": clean_user, "role": clean_role, "permissions": eff_perms, "is_active": is_active},
                now=now,
            )
            conn.commit()
            return {
                "ok": True,
                "http_status": 200,
                "message_gu": f"એડમિન '{clean_user}' ({clean_role}) સફળતાપૂર્વક સેવ થયું.",
                "admin_user_id": target_id,
            }
        finally:
            conn.close()


def list_admin_users(actor: Dict[str, Any]) -> Dict[str, Any]:
    if actor.get("role") != ROLE_SUPER_ADMIN:
        return {"ok": False, "http_status": 403, "message_gu": "ફક્ત SUPER_ADMIN જ એડમિન યાદી જોઈ શકે છે."}
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, username, display_name, role, permissions_json, is_active, created_at, updated_at, last_login_at FROM admin_users ORDER BY id ASC"
            ).fetchall()
            items = []
            for r in rows:
                items.append({
                    "id": int(r["id"]),
                    "username": str(r["username"]),
                    "display_name": str(r["display_name"]),
                    "role": str(r["role"]),
                    "permissions": _effective_permissions(str(r["role"]), str(r["permissions_json"])),
                    "is_active": bool(r["is_active"]),
                    "created_at": float(r["created_at"] or 0.0),
                    "updated_at": float(r["updated_at"] or 0.0),
                    "last_login_at": float(r["last_login_at"]) if r["last_login_at"] else None,
                })
            return {"ok": True, "http_status": 200, "admins": items}
        finally:
            conn.close()


def _auto_expire_blocks(conn: sqlite3.Connection, now: Optional[float] = None) -> bool:
    now_ts = float(now if now is not None else time.time())
    cursor = conn.execute(
        """
        UPDATE mukadams
        SET is_blocked = 0,
            account_status = 'ACTIVE',
            blocked_at = NULL,
            blocked_by = '',
            block_reason = '',
            block_admin_note = '',
            block_expires_at = NULL,
            updated_at = ?
        WHERE is_blocked = 1
          AND account_status = 'BLOCKED'
          AND block_expires_at IS NOT NULL
          AND block_expires_at > 0
          AND block_expires_at <= ?
        """,
        (now_ts, now_ts),
    )
    if cursor.rowcount and cursor.rowcount > 0:
        conn.commit()
        return True
    return False


def _format_mukadam_for_admin(row: Dict[str, Any], actor_role: str) -> Dict[str, Any]:
    item = dict(row)
    item.pop("pin_hash", None)
    item.pop("phone_verified", None)
    item.pop("phone_verified_at", None)
    rating_count = max(1, int(item.get("rating_count", 1) or 1))
    rating_sum = float(item.get("rating_sum", 5.0) or 5.0)
    item["avg_rating"] = round(rating_sum / rating_count, 1)

    if actor_role == ROLE_VIEWER:
        item["mobile"] = _mask_mobile(str(item.get("mobile", "")))
        item["block_admin_note"] = ""
        item["notes"] = _sanitize_text(item.get("notes", ""), 120)
    return item


def get_dashboard_overview(actor: Dict[str, Any]) -> Dict[str, Any]:
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            if _auto_expire_blocks(conn):
                ms._refresh_ram_cache()

            total_mukadams = int(conn.execute("SELECT COUNT(*) FROM mukadams").fetchone()[0] or 0)
            active_mukadams = int(conn.execute(
                "SELECT COUNT(*) FROM mukadams WHERE account_status = 'ACTIVE' AND is_blocked = 0 AND deleted_at IS NULL"
            ).fetchone()[0] or 0)
            blocked_mukadams = int(conn.execute(
                "SELECT COUNT(*) FROM mukadams WHERE account_status = 'BLOCKED' OR is_blocked = 1"
            ).fetchone()[0] or 0)
            soft_deleted_mukadams = int(conn.execute(
                "SELECT COUNT(*) FROM mukadams WHERE account_status = 'SOFT_DELETED' OR deleted_at IS NOT NULL"
            ).fetchone()[0] or 0)

            pending_reports = int(conn.execute(
                "SELECT COUNT(*) FROM mukadam_reports WHERE status IN ('PENDING', 'UNDER_REVIEW')"
            ).fetchone()[0] or 0)
            resolved_reports = int(conn.execute(
                "SELECT COUNT(*) FROM mukadam_reports WHERE status IN ('VERIFIED', 'RESOLVED', 'REJECTED')"
            ).fetchone()[0] or 0)

            return {
                "ok": True,
                "http_status": 200,
                "overview": {
                    "total_mukadams": total_mukadams,
                    "active_mukadams": active_mukadams,
                    "blocked_mukadams": blocked_mukadams,
                    "soft_deleted_mukadams": soft_deleted_mukadams,
                    "pending_reports": pending_reports,
                    "resolved_reports": resolved_reports,
                },
            }
        finally:
            conn.close()


def list_mukadams_for_admin(
    actor: Dict[str, Any],
    *,
    q: str = "",
    mobile: str = "",
    district: str = "",
    village: str = "",
    status_filter: str = "ALL",
    registered_from: Optional[float] = None,
    registered_to: Optional[float] = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    offset = (page - 1) * page_size

    allowed_sort = {
        "id": "id",
        "name": "name",
        "district": "district",
        "total_labors": "total_labors",
        "created_at": "created_at",
        "updated_at": "updated_at",
    }
    order_col = allowed_sort.get(str(sort_by or "updated_at"), "updated_at")
    order_dir = "ASC" if str(sort_dir or "desc").lower() == "asc" else "DESC"

    where_clauses: List[str] = []
    params: List[Any] = []

    status_key = str(status_filter or "ALL").strip().upper()
    if status_key == "ACTIVE":
        where_clauses.append("(account_status = 'ACTIVE' AND is_blocked = 0 AND deleted_at IS NULL)")
    elif status_key == "BLOCKED":
        where_clauses.append("(account_status = 'BLOCKED' OR is_blocked = 1)")
    elif status_key in ("DELETED", "SOFT_DELETED"):
        where_clauses.append("(account_status = 'SOFT_DELETED' OR deleted_at IS NOT NULL)")

    if q.strip():
        q_like = f"%{_sanitize_text(q, 80)}%"
        where_clauses.append("(name LIKE ? OR mobile LIKE ? OR village LIKE ? OR taluka LIKE ? OR district LIKE ?)")
        params.extend([q_like, q_like, q_like, q_like, q_like])

    if mobile.strip():
        m_clean = ms._clean_mobile(mobile) or _sanitize_text(mobile, 15)
        where_clauses.append("mobile LIKE ?")
        params.append(f"%{m_clean}%")

    if district.strip():
        where_clauses.append("district LIKE ?")
        params.append(f"%{_sanitize_text(district, 60)}%")

    if village.strip():
        where_clauses.append("(village LIKE ? OR taluka LIKE ?)")
        v_like = f"%{_sanitize_text(village, 60)}%"
        params.extend([v_like, v_like])

    if registered_from is not None and float(registered_from) > 0:
        where_clauses.append("created_at >= ?")
        params.append(float(registered_from))

    if registered_to is not None and float(registered_to) > 0:
        where_clauses.append("created_at <= ?")
        params.append(float(registered_to))

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            if _auto_expire_blocks(conn):
                ms._refresh_ram_cache()

            total = int(conn.execute(
                f"SELECT COUNT(*) FROM mukadams {where_sql}",
                tuple(params),
            ).fetchone()[0] or 0)

            rows = conn.execute(
                f"SELECT * FROM mukadams {where_sql} ORDER BY {order_col} {order_dir} LIMIT ? OFFSET ?",
                tuple(params + [page_size, offset]),
            ).fetchall()

            actor_role = str(actor.get("role", ROLE_VIEWER))
            items = [_format_mukadam_for_admin(dict(r), actor_role) for r in rows]
            return {
                "ok": True,
                "http_status": 200,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size),
                "mukadams": items,
            }
        finally:
            conn.close()


def get_mukadam_profile_for_admin(actor: Dict[str, Any], mukadam_id: int) -> Dict[str, Any]:
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM mukadams WHERE id = ?", (int(mukadam_id),)).fetchone()
            if not row:
                return {"ok": False, "http_status": 404, "message_gu": "મુકાદમ પ્રોફાઇલ મળી નથી."}

            actor_role = str(actor.get("role", ROLE_VIEWER))
            profile = _format_mukadam_for_admin(dict(row), actor_role)

            reports = []
            if actor_role in (ROLE_SUPER_ADMIN, ROLE_MODERATOR):
                rep_rows = conn.execute(
                    "SELECT * FROM mukadam_reports WHERE mukadam_id = ? ORDER BY created_at DESC LIMIT 50",
                    (int(mukadam_id),),
                ).fetchall()
                reports = [dict(r) for r in rep_rows]

            audit_history = []
            if actor_role in (ROLE_SUPER_ADMIN, ROLE_MODERATOR):
                aud_rows = conn.execute(
                    """
                    SELECT id, timestamp, admin_username, admin_role, action, result, reason, metadata_json
                    FROM admin_audit_logs
                    WHERE target_type = 'mukadam' AND target_id = ?
                    ORDER BY id DESC LIMIT 50
                    """,
                    (str(mukadam_id),),
                ).fetchall()
                for ar in aud_rows:
                    item = dict(ar)
                    try:
                        item["metadata"] = json.loads(item.pop("metadata_json", "{}") or "{}")
                    except Exception:
                        item["metadata"] = {}
                    audit_history.append(item)

            return {
                "ok": True,
                "http_status": 200,
                "profile": profile,
                "reports": reports,
                "admin_action_history": audit_history,
            }
        finally:
            conn.close()


def block_mukadam(
    actor: Dict[str, Any],
    mukadam_id: int,
    *,
    reason: str,
    admin_note: str = "",
    expires_at: Optional[float] = None,
    client_ip: str = "unknown",
    request_id: str = "",
) -> Dict[str, Any]:
    perms = actor.get("permissions", [])
    if "mukadam:block" not in perms:
        return {"ok": False, "http_status": 403, "message_gu": "મુકાદમ બ્લોક કરવાની પરવાનગી નથી."}

    clean_reason = _sanitize_text(reason, 300)
    clean_note = _sanitize_text(admin_note, 500)
    if len(clean_reason) < 3:
        return {"ok": False, "http_status": 400, "message_gu": "બ્લોક કરવાનું સ્પષ્ટ કારણ લખવું ફરજિયાત છે."}

    now = time.time()
    exp_val: Optional[float] = None
    if expires_at is not None and float(expires_at) > 0:
        exp_val = float(expires_at)
        if exp_val <= now:
            return {"ok": False, "http_status": 400, "message_gu": "બ્લોક સમાપ્તિ સમય ભવિષ્યનો હોવો જોઈએ."}

    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM mukadams WHERE id = ?", (int(mukadam_id),)).fetchone()
            if not row:
                return {"ok": False, "http_status": 404, "message_gu": "મુકાદમ પ્રોફાઇલ મળી નથી."}
            if str(row["account_status"]) == "SOFT_DELETED" or row["deleted_at"] is not None:
                return {"ok": False, "http_status": 409, "message_gu": "આ પ્રોફાઇલ Soft-Deleted છે. પહેલાં Restore કરો."}

            conn.execute(
                """
                UPDATE mukadams
                SET account_status = 'BLOCKED',
                    is_blocked = 1,
                    blocked_at = ?,
                    blocked_by = ?,
                    block_reason = ?,
                    block_admin_note = ?,
                    block_expires_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, str(actor["username"]), clean_reason, clean_note, exp_val, now, int(mukadam_id)),
            )
            append_audit_log(
                conn,
                admin_id=int(actor["id"]),
                admin_username=str(actor["username"]),
                admin_role=str(actor["role"]),
                action="MUKADAM_BLOCK",
                target_type="mukadam",
                target_id=str(mukadam_id),
                result="SUCCESS",
                reason=clean_reason,
                request_id=request_id,
                client_ip=client_ip,
                metadata={
                    "mukadam_id": int(mukadam_id),
                    "mukadam_name": str(row["name"]),
                    "block_expires_at": exp_val,
                },
                now=now,
            )
            conn.commit()
        finally:
            conn.close()

    ms._refresh_ram_cache()
    ms._trigger_github_backup_async()
    return {
        "ok": True,
        "http_status": 200,
        "message_gu": f"મુકાદમ '{row['name']}' ને બ્લોક કરવામાં આવ્યા છે. હવે તેઓ Public Search માં દેખાશે નહીં.",
    }


def unblock_mukadam(
    actor: Dict[str, Any],
    mukadam_id: int,
    *,
    reason: str = "એડમિન દ્વારા અનબ્લોક કરવામાં આવ્યા",
    admin_note: str = "",
    client_ip: str = "unknown",
    request_id: str = "",
) -> Dict[str, Any]:
    perms = actor.get("permissions", [])
    if "mukadam:unblock" not in perms:
        return {"ok": False, "http_status": 403, "message_gu": "મુકાદમ અનબ્લોક કરવાની પરવાનગી નથી."}

    clean_reason = _sanitize_text(reason or "એડમિન દ્વારા અનબ્લોક", 300)
    clean_note = _sanitize_text(admin_note, 500)
    now = time.time()

    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM mukadams WHERE id = ?", (int(mukadam_id),)).fetchone()
            if not row:
                return {"ok": False, "http_status": 404, "message_gu": "મુકાદમ પ્રોફાઇલ મળી નથી."}
            if str(row["account_status"]) == "SOFT_DELETED" or row["deleted_at"] is not None:
                return {"ok": False, "http_status": 409, "message_gu": "આ પ્રોફાઇલ Soft-Deleted છે. પહેલાં Restore કરો."}

            conn.execute(
                """
                UPDATE mukadams
                SET account_status = 'ACTIVE',
                    is_blocked = 0,
                    blocked_at = NULL,
                    blocked_by = '',
                    block_reason = '',
                    block_admin_note = ?,
                    block_expires_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (clean_note, now, int(mukadam_id)),
            )
            append_audit_log(
                conn,
                admin_id=int(actor["id"]),
                admin_username=str(actor["username"]),
                admin_role=str(actor["role"]),
                action="MUKADAM_UNBLOCK",
                target_type="mukadam",
                target_id=str(mukadam_id),
                result="SUCCESS",
                reason=clean_reason,
                request_id=request_id,
                client_ip=client_ip,
                metadata={"mukadam_id": int(mukadam_id), "mukadam_name": str(row["name"])},
                now=now,
            )
            conn.commit()
        finally:
            conn.close()

    ms._refresh_ram_cache()
    ms._trigger_github_backup_async()
    return {
        "ok": True,
        "http_status": 200,
        "message_gu": f"મુકાદમ '{row['name']}' ને અનબ્લોક કરીને ફરી સક્રિય કરવામાં આવ્યા છે.",
    }


def soft_delete_mukadam(
    actor: Dict[str, Any],
    mukadam_id: int,
    *,
    reason: str,
    client_ip: str = "unknown",
    request_id: str = "",
) -> Dict[str, Any]:
    if actor.get("role") != ROLE_SUPER_ADMIN and "mukadam:soft_delete" not in actor.get("permissions", []):
        return {"ok": False, "http_status": 403, "message_gu": "Soft Delete કરવાની પરવાનગી ફક્ત અધિકૃત Admin પાસે જ છે."}

    clean_reason = _sanitize_text(reason, 300)
    if len(clean_reason) < 3:
        return {"ok": False, "http_status": 400, "message_gu": "Soft Delete કરવાનું કારણ લખવું ફરજિયાત છે."}

    now = time.time()
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM mukadams WHERE id = ?", (int(mukadam_id),)).fetchone()
            if not row:
                return {"ok": False, "http_status": 404, "message_gu": "મુકાદમ પ્રોફાઇલ મળી નથી."}
            if str(row["account_status"]) == "SOFT_DELETED" or row["deleted_at"] is not None:
                return {"ok": False, "http_status": 409, "message_gu": "આ પ્રોફાઇલ પહેલેથી જ Soft-Deleted છે."}

            prev_status = "BLOCKED" if int(row["is_blocked"] or 0) == 1 else str(row["account_status"] or "ACTIVE")
            conn.execute(
                """
                UPDATE mukadams
                SET account_status = 'SOFT_DELETED',
                    deleted_at = ?,
                    deleted_by = ?,
                    deletion_reason = ?,
                    previous_status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, str(actor["username"]), clean_reason, prev_status, now, int(mukadam_id)),
            )
            append_audit_log(
                conn,
                admin_id=int(actor["id"]),
                admin_username=str(actor["username"]),
                admin_role=str(actor["role"]),
                action="MUKADAM_SOFT_DELETE",
                target_type="mukadam",
                target_id=str(mukadam_id),
                result="SUCCESS",
                reason=clean_reason,
                request_id=request_id,
                client_ip=client_ip,
                metadata={
                    "mukadam_id": int(mukadam_id),
                    "mukadam_name": str(row["name"]),
                    "previous_status": prev_status,
                },
                now=now,
            )
            conn.commit()
        finally:
            conn.close()

    ms._refresh_ram_cache()
    ms._trigger_github_backup_async()
    return {
        "ok": True,
        "http_status": 200,
        "message_gu": f"મુકાદમ '{row['name']}' ને Soft Delete કરવામાં આવ્યા છે. જરૂર પડે ત્યારે Restore કરી શકાશે.",
    }


def restore_mukadam(
    actor: Dict[str, Any],
    mukadam_id: int,
    *,
    reason: str = "એડમિન દ્વારા Restore કરવામાં આવ્યા",
    client_ip: str = "unknown",
    request_id: str = "",
) -> Dict[str, Any]:
    if actor.get("role") != ROLE_SUPER_ADMIN and "mukadam:restore" not in actor.get("permissions", []):
        return {"ok": False, "http_status": 403, "message_gu": "Restore કરવાની પરવાનગી ફક્ત અધિકૃત Admin પાસે જ છે."}

    clean_reason = _sanitize_text(reason or "એડમિન દ્વારા Restore", 300)
    now = time.time()
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM mukadams WHERE id = ?", (int(mukadam_id),)).fetchone()
            if not row:
                return {"ok": False, "http_status": 404, "message_gu": "મુકાદમ પ્રોફાઇલ મળી નથી."}
            if str(row["account_status"]) != "SOFT_DELETED" and row["deleted_at"] is None:
                return {"ok": False, "http_status": 409, "message_gu": "આ પ્રોફાઇલ Soft-Deleted નથી."}

            restored_status = str(row["previous_status"] or "ACTIVE")
            if restored_status not in ("ACTIVE", "BLOCKED"):
                restored_status = "ACTIVE"
            is_blocked = 1 if restored_status == "BLOCKED" else 0

            conn.execute(
                """
                UPDATE mukadams
                SET account_status = ?,
                    is_blocked = ?,
                    deleted_at = NULL,
                    deleted_by = '',
                    deletion_reason = '',
                    previous_status = '',
                    updated_at = ?
                WHERE id = ?
                """,
                (restored_status, is_blocked, now, int(mukadam_id)),
            )
            append_audit_log(
                conn,
                admin_id=int(actor["id"]),
                admin_username=str(actor["username"]),
                admin_role=str(actor["role"]),
                action="MUKADAM_RESTORE",
                target_type="mukadam",
                target_id=str(mukadam_id),
                result="SUCCESS",
                reason=clean_reason,
                request_id=request_id,
                client_ip=client_ip,
                metadata={
                    "mukadam_id": int(mukadam_id),
                    "mukadam_name": str(row["name"]),
                    "restored_status": restored_status,
                },
                now=now,
            )
            conn.commit()
        finally:
            conn.close()

    ms._refresh_ram_cache()
    ms._trigger_github_backup_async()
    return {
        "ok": True,
        "http_status": 200,
        "message_gu": f"મુકાદમ '{row['name']}' ની પ્રોફાઇલ સફળતાપૂર્વક Restore કરવામાં આવી છે.",
    }


def permanent_delete_mukadam(
    actor: Dict[str, Any],
    mukadam_id: int,
    *,
    admin_password: str,
    confirm_mobile_or_name: str,
    reason: str,
    client_ip: str = "unknown",
    request_id: str = "",
) -> Dict[str, Any]:
    now = time.time()
    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            if actor.get("role") != ROLE_SUPER_ADMIN:
                append_audit_log(
                    conn,
                    admin_id=int(actor.get("id") or 0),
                    admin_username=str(actor.get("username", "")),
                    admin_role=str(actor.get("role", "")),
                    action="MUKADAM_PERMANENT_DELETE",
                    target_type="mukadam",
                    target_id=str(mukadam_id),
                    result="DENIED",
                    reason="Non-SUPER_ADMIN attempted permanent delete",
                    request_id=request_id,
                    client_ip=client_ip,
                    now=now,
                )
                conn.commit()
                return {"ok": False, "http_status": 403, "message_gu": "કાયમી ડિલીટ (Permanent Delete) કરવાની પરવાનગી ફક્ત SUPER_ADMIN પાસે જ છે."}

            admin_row = conn.execute("SELECT password_hash FROM admin_users WHERE id = ?", (int(actor["id"]),)).fetchone()
            if not admin_row or not verify_admin_password(str(admin_row["password_hash"]), admin_password):
                append_audit_log(
                    conn,
                    admin_id=int(actor["id"]),
                    admin_username=str(actor["username"]),
                    admin_role=str(actor["role"]),
                    action="MUKADAM_PERMANENT_DELETE",
                    target_type="mukadam",
                    target_id=str(mukadam_id),
                    result="DENIED",
                    reason="Admin re-authentication failed",
                    request_id=request_id,
                    client_ip=client_ip,
                    now=now,
                )
                conn.commit()
                return {"ok": False, "http_status": 401, "message_gu": "કાયમી ડિલીટ માટે તમારો Admin પાસવર્ડ સાચો હોવો જરૂરી છે."}

            clean_reason = _sanitize_text(reason, 300)
            if len(clean_reason) < 5:
                return {"ok": False, "http_status": 400, "message_gu": "કાયમી ડિલીટ કરવાનું સ્પષ્ટ કારણ (ઓછામાં ઓછા ૫ અક્ષર) લખવું ફરજિયાત છે."}

            row = conn.execute("SELECT * FROM mukadams WHERE id = ?", (int(mukadam_id),)).fetchone()
            if not row:
                return {"ok": False, "http_status": 404, "message_gu": "મુકાદમ પ્રોફાઇલ મળી નથી."}

            if str(row["account_status"]) != "SOFT_DELETED" and row["deleted_at"] is None:
                return {
                    "ok": False,
                    "http_status": 409,
                    "message_gu": "સુરક્ષા નિયમ મુજબ કાયમી ડિલીટ કરતાં પહેલાં પ્રોફાઇલને Soft Delete કરવી ફરજિયાત છે.",
                }

            confirm_val = str(confirm_mobile_or_name or "").strip()
            target_mobile = ms._clean_mobile(str(row["mobile"]))
            target_name = str(row["name"]).strip()
            if ms._clean_mobile(confirm_val) != target_mobile and confirm_val != target_name:
                return {
                    "ok": False,
                    "http_status": 400,
                    "message_gu": "ડિલીટ કરવાના મુકાદમની ઓળખ ચકાસણી (મોબાઇલ નંબર અથવા નામ) મેળ ખાતી નથી.",
                }

            active_reports = int(conn.execute(
                "SELECT COUNT(*) FROM mukadam_reports WHERE mukadam_id = ? AND status IN ('PENDING', 'UNDER_REVIEW')",
                (int(mukadam_id),),
            ).fetchone()[0] or 0)
            if active_reports > 0:
                return {
                    "ok": False,
                    "http_status": 409,
                    "message_gu": f"આ મુકાદમ સામે {active_reports} ફરિયાદ હજુ તપાસ હેઠળ (PENDING/UNDER_REVIEW) છે. પહેલાં તેનો નિકાલ કરો.",
                }

            try:
                create_sqlite_backup(tag=f"pre_perm_delete_{mukadam_id}")
            except Exception as exc:
                print(f"[Admin] Pre-delete backup warning: {exc}")

            conn.execute(
                """
                INSERT OR REPLACE INTO mukadam_deleted_tombstones (mobile, mukadam_id, deleted_at, deleted_by, reason_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (target_mobile, int(mukadam_id), now, str(actor["username"]), _sha256_hex(clean_reason)),
            )
            conn.execute("DELETE FROM mukadams WHERE id = ?", (int(mukadam_id),))

            append_audit_log(
                conn,
                admin_id=int(actor["id"]),
                admin_username=str(actor["username"]),
                admin_role=str(actor["role"]),
                action="MUKADAM_PERMANENT_DELETE",
                target_type="mukadam",
                target_id=str(mukadam_id),
                result="SUCCESS",
                reason=clean_reason,
                request_id=request_id,
                client_ip=client_ip,
                metadata={
                    "deleted_mukadam_id": int(mukadam_id),
                    "district": str(row["district"]),
                    "taluka": str(row["taluka"]),
                    "mobile_masked": _mask_mobile(target_mobile),
                },
                now=now,
            )
            conn.commit()
        finally:
            conn.close()

    ms._refresh_ram_cache()
    ms._trigger_github_backup_async()
    return {
        "ok": True,
        "http_status": 200,
        "message_gu": f"મુકાદમ ID #{mukadam_id} કાયમી રીતે ડિલીટ કરવામાં આવ્યા છે અને તેની સુરક્ષિત Audit નોંધ રાખવામાં આવી છે.",
    }


def submit_farmer_report(
    payload: Dict[str, Any],
    client_ip: str = "unknown",
) -> Dict[str, Any]:
    if not ms._CACHE_INITIALIZED:
        ms.init_mukadam_db()

    mukadam_id = int(payload.get("mukadam_id", 0) or 0)
    mukadam_mobile = ms._clean_mobile(payload.get("mukadam_mobile", ""))
    report_type = _sanitize_text(payload.get("report_type", "અન્ય"), 80)
    description = _sanitize_text(payload.get("description", ""), 600)
    reporter_name = _sanitize_text(payload.get("reporter_name", ""), 80)
    reporter_mobile = ms._clean_mobile(payload.get("reporter_mobile", ""))

    if report_type not in VALID_REPORT_TYPES:
        report_type = "અન્ય"
    if len(description) < 5:
        return {"ok": False, "http_status": 400, "message_gu": "કૃપા કરીને ફરિયાદની વિગત (ઓછામાં ઓછા ૫ અક્ષર) લખો."}

    evidence_raw = payload.get("evidence_meta", {})
    evidence_clean: Dict[str, Any] = {}
    if isinstance(evidence_raw, dict) and evidence_raw:
        mime = str(evidence_raw.get("mime_type", "")).strip().lower()
        size_bytes = int(evidence_raw.get("size_bytes", 0) or 0)
        filename = _sanitize_text(evidence_raw.get("filename", ""), 100)
        if any(filename.lower().endswith(ext) for ext in (".exe", ".sh", ".bat", ".py", ".js", ".php", ".apk", ".html", ".svg")):
            return {"ok": False, "http_status": 400, "message_gu": "આ પ્રકારની ફાઇલ સુરક્ષા કારણોસર સ્વીકાર્ય નથી."}
        if mime and mime not in ALLOWED_EVIDENCE_MIME_TYPES:
            return {"ok": False, "http_status": 400, "message_gu": "પુરાવા તરીકે માત્ર JPG, PNG, WEBP અથવા PDF ફાઇલ જ માન્ય છે."}
        if size_bytes > MAX_EVIDENCE_BYTES:
            return {"ok": False, "http_status": 400, "message_gu": "પુરાવાની ફાઇલ ૨ MB થી નાની હોવી જોઈએ."}
        evidence_clean = {"filename": filename, "mime_type": mime, "size_bytes": size_bytes}

    now = time.time()
    ip_key = ms._client_ip_key(client_ip)
    reporter_hash = _sha256_hex(reporter_mobile) if len(reporter_mobile) == 10 else _sha256_hex(ip_key or "anon")

    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            row = None
            if mukadam_id > 0:
                row = conn.execute("SELECT id, name, mobile FROM mukadams WHERE id = ?", (mukadam_id,)).fetchone()
            if not row and len(mukadam_mobile) == 10:
                row = conn.execute("SELECT id, name, mobile FROM mukadams WHERE mobile = ?", (mukadam_mobile,)).fetchone()
            if not row:
                return {"ok": False, "http_status": 404, "message_gu": "આ મુકાદમ પ્રોફાઇલ મળી નથી."}

            target_id = int(row["id"])
            target_mobile_masked = _mask_mobile(str(row["mobile"]))

            if ip_key:
                recent_ip_count = int(conn.execute(
                    "SELECT COUNT(*) FROM mukadam_reports WHERE client_ip = ? AND created_at >= ?",
                    (ip_key, now - 3600),
                ).fetchone()[0] or 0)
                if recent_ip_count >= REPORT_IP_LIMIT_PER_HOUR:
                    return {
                        "ok": False,
                        "http_status": 429,
                        "message_gu": "તમે ઘણી ફરિયાદો મોકલી છે. કૃપા કરીને થોડા સમય પછી પ્રયાસ કરો.",
                    }

            dup = conn.execute(
                """
                SELECT id FROM mukadam_reports
                WHERE mukadam_id = ? AND reporter_mobile_hash = ? AND created_at >= ?
                """,
                (target_id, reporter_hash, now - 12 * 3600),
            ).fetchone()
            if dup:
                return {
                    "ok": False,
                    "http_status": 429,
                    "message_gu": "આ મુકાદમ સામે તમારી ફરિયાદ પહેલેથી નોંધાયેલી છે અને તપાસ હેઠળ છે.",
                }

            cursor = conn.execute(
                """
                INSERT INTO mukadam_reports (
                    mukadam_id, mukadam_mobile_masked, report_type, description,
                    reporter_name, reporter_mobile_hash, reporter_mobile_masked,
                    client_ip, evidence_meta_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                """,
                (
                    target_id,
                    target_mobile_masked,
                    report_type,
                    description,
                    reporter_name,
                    reporter_hash,
                    _mask_mobile(reporter_mobile) if reporter_mobile else "",
                    ip_key,
                    json.dumps(evidence_clean, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            report_id = int(cursor.lastrowid or 0)
            conn.commit()
            return {
                "ok": True,
                "http_status": 201,
                "report_id": report_id,
                "message_gu": "તમારી ફરિયાદ સફળતાપૂર્વક નોંધાઈ ગઈ છે. એડમિન તપાસ કરીને યોગ્ય પગલાં લેશે.",
            }
        finally:
            conn.close()


def list_reports_for_admin(
    actor: Dict[str, Any],
    *,
    status_filter: str = "ALL",
    mukadam_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    if "reports:view" not in actor.get("permissions", []):
        return {"ok": False, "http_status": 403, "message_gu": "ફરિયાદો જોવાની પરવાનગી નથી."}

    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    offset = (page - 1) * page_size

    where_clauses: List[str] = []
    params: List[Any] = []
    st = str(status_filter or "ALL").strip().upper()
    if st in REPORT_STATUSES:
        where_clauses.append("r.status = ?")
        params.append(st)
    if mukadam_id is not None and int(mukadam_id) > 0:
        where_clauses.append("r.mukadam_id = ?")
        params.append(int(mukadam_id))

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            total = int(conn.execute(
                f"SELECT COUNT(*) FROM mukadam_reports r {where_sql}",
                tuple(params),
            ).fetchone()[0] or 0)

            rows = conn.execute(
                f"""
                SELECT r.*, m.name AS mukadam_name, m.district AS mukadam_district,
                       m.village AS mukadam_village, m.account_status AS mukadam_account_status
                FROM mukadam_reports r
                LEFT JOIN mukadams m ON m.id = r.mukadam_id
                {where_sql}
                ORDER BY r.created_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params + [page_size, offset]),
            ).fetchall()

            items = []
            for r in rows:
                d = dict(r)
                d.pop("reporter_mobile_hash", None)
                d.pop("client_ip", None)
                items.append(d)

            return {
                "ok": True,
                "http_status": 200,
                "total": total,
                "page": page,
                "page_size": page_size,
                "reports": items,
            }
        finally:
            conn.close()


def review_report(
    actor: Dict[str, Any],
    report_id: int,
    *,
    new_status: str,
    admin_notes: str = "",
    resolution_details: str = "",
    assigned_moderator: str = "",
    also_block_mukadam: bool = False,
    block_expiry_hours: Optional[float] = None,
    client_ip: str = "unknown",
    request_id: str = "",
) -> Dict[str, Any]:
    perms = actor.get("permissions", [])
    if "reports:review" not in perms:
        return {"ok": False, "http_status": 403, "message_gu": "ફરિયાદની સમીક્ષા કરવાની પરવાનગી નથી."}

    clean_status = str(new_status or "").strip().upper()
    if clean_status not in REPORT_STATUSES:
        return {"ok": False, "http_status": 400, "message_gu": "અમાન્ય ફરિયાદ સ્ટેટસ."}

    clean_notes = _sanitize_text(admin_notes, 500)
    clean_resolution = _sanitize_text(resolution_details, 500)
    clean_mod = _sanitize_text(assigned_moderator or str(actor["username"]), 80)
    now = time.time()

    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            rep = conn.execute("SELECT * FROM mukadam_reports WHERE id = ?", (int(report_id),)).fetchone()
            if not rep:
                return {"ok": False, "http_status": 404, "message_gu": "ફરિયાદ રેકોર્ડ મળ્યો નથી."}

            conn.execute(
                """
                UPDATE mukadam_reports
                SET status = ?,
                    assigned_moderator = ?,
                    admin_notes = ?,
                    resolution_details = ?,
                    reviewed_by = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (clean_status, clean_mod, clean_notes, clean_resolution, str(actor["username"]), now, int(report_id)),
            )

            append_audit_log(
                conn,
                admin_id=int(actor["id"]),
                admin_username=str(actor["username"]),
                admin_role=str(actor["role"]),
                action=f"REPORT_{clean_status}",
                target_type="report",
                target_id=str(report_id),
                result="SUCCESS",
                reason=clean_resolution or clean_notes or f"Report status updated to {clean_status}",
                request_id=request_id,
                client_ip=client_ip,
                metadata={
                    "report_id": int(report_id),
                    "mukadam_id": int(rep["mukadam_id"]),
                    "new_status": clean_status,
                    "also_block_mukadam": bool(also_block_mukadam),
                },
                now=now,
            )
            conn.commit()
        finally:
            conn.close()

    if also_block_mukadam and "mukadam:block" in perms:
        exp_ts = (now + float(block_expiry_hours) * 3600.0) if (block_expiry_hours and float(block_expiry_hours) > 0) else None
        block_mukadam(
            actor,
            int(rep["mukadam_id"]),
            reason=f"ફરિયાદ #{report_id} ({rep['report_type']}) ચકાસણી બાદ બ્લોક",
            admin_note=clean_notes,
            expires_at=exp_ts,
            client_ip=client_ip,
            request_id=request_id,
        )

    return {
        "ok": True,
        "http_status": 200,
        "message_gu": f"ફરિયાદ #{report_id} નું સ્ટેટસ '{clean_status}' તરીકે અપડેટ થયું છે.",
    }


def list_audit_logs(
    actor: Dict[str, Any],
    *,
    action_filter: str = "",
    target_type: str = "",
    page: int = 1,
    page_size: int = 30,
) -> Dict[str, Any]:
    if "audit:view" not in actor.get("permissions", []):
        return {"ok": False, "http_status": 403, "message_gu": "Audit Logs જોવાની પરવાનગી ફક્ત SUPER_ADMIN પાસે જ છે."}

    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 30)))
    offset = (page - 1) * page_size

    where_clauses: List[str] = []
    params: List[Any] = []
    if action_filter.strip():
        where_clauses.append("action LIKE ?")
        params.append(f"%{_sanitize_text(action_filter, 60)}%")
    if target_type.strip():
        where_clauses.append("target_type = ?")
        params.append(_sanitize_text(target_type, 40))

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    with ms._MUKADAM_LOCK:
        conn = _connect()
        try:
            total = int(conn.execute(f"SELECT COUNT(*) FROM admin_audit_logs {where_sql}", tuple(params)).fetchone()[0] or 0)
            rows = conn.execute(
                f"SELECT * FROM admin_audit_logs {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
                tuple(params + [page_size, offset]),
            ).fetchall()
            items = []
            for r in rows:
                d = dict(r)
                try:
                    d["metadata"] = json.loads(d.pop("metadata_json", "{}") or "{}")
                except Exception:
                    d["metadata"] = {}
                items.append(d)
        finally:
            conn.close()

    chain_status = verify_audit_log_chain()
    return {
        "ok": True,
        "http_status": 200,
        "total": total,
        "page": page,
        "page_size": page_size,
        "chain_verified": chain_status.get("verified", False),
        "head_hash": chain_status.get("head_hash", ""),
        "logs": items,
    }


def create_sqlite_backup(tag: str = "manual") -> Dict[str, Any]:
    clean_tag = re.sub(r"[^A-Za-z0-9_\-]", "_", str(tag or "backup"))[:40]
    backup_dir = os.path.join(os.path.dirname(_db_path()) or ".", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = int(time.time())
    backup_file = os.path.join(backup_dir, f"mukadam_backup_{clean_tag}_{stamp}.db")

    with ms._MUKADAM_LOCK:
        src = sqlite3.connect(_db_path())
        dst = sqlite3.connect(backup_file)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

    return {
        "ok": True,
        "backup_path": backup_file,
        "size_bytes": os.path.getsize(backup_file),
        "created_at": stamp,
    }


def restore_sqlite_backup(backup_file: str) -> Dict[str, Any]:
    if not os.path.isfile(backup_file):
        return {"ok": False, "message_gu": "બેકઅપ ફાઇલ મળી નથી."}
    check_conn = sqlite3.connect(backup_file)
    try:
        tables = {str(r[0]) for r in check_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "mukadams" not in tables:
            return {"ok": False, "message_gu": "અમાન્ય બેકઅપ ફાઇલ: mukadams ટેબલ મળ્યું નથી."}
    finally:
        check_conn.close()

    with ms._MUKADAM_LOCK:
        src = sqlite3.connect(backup_file)
        dst = sqlite3.connect(_db_path())
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        init_admin_schema()
        ms._refresh_ram_cache()

    return {"ok": True, "message_gu": "ડેટાબેઝ બેકઅપ સફળતાપૂર્વક રીસ્ટોર કરવામાં આવ્યો છે."}
