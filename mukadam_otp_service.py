"""Server-side phone verification for Mukadam registration.

Uses Twilio Verify so the backend never needs to store or log the OTP itself.
Fail-closed by design: if provider or the hashing secret is not configured, OTP
request/verification and new registrations cannot proceed.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

import mukadam_service as _ms

_OTP_LOCK = threading.RLock()
OTP_TTL_SECONDS = 5 * 60
REGISTRATION_TOKEN_TTL_SECONDS = 5 * 60
MOBILE_RESEND_COOLDOWN_SECONDS = 60
MOBILE_REQUEST_LIMIT_PER_HOUR = 5
IP_REQUEST_LIMIT_PER_HOUR = 20
VERIFY_ATTEMPT_LIMIT = 5
VERIFY_LOCKOUT_SECONDS = 10 * 60
HTTP_TIMEOUT_SECONDS = 12


def _credentials() -> Optional[Tuple[str, str, str, str]]:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    service_sid = os.environ.get("TWILIO_VERIFY_SERVICE_SID", "").strip()
    hash_secret = os.environ.get("MUKADAM_OTP_HASH_SECRET", "").strip()
    if not all((account_sid, auth_token, service_sid, hash_secret)) or len(hash_secret.encode("utf-8")) < 32:
        return None
    return account_sid, auth_token, service_sid, hash_secret


def _normalise_mobile(mobile: str) -> str:
    return _ms._clean_mobile(mobile)


def _mobile_hash(mobile: str, hash_secret: str) -> str:
    return hmac.new(hash_secret.encode("utf-8"), mobile.encode("ascii"), hashlib.sha256).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ensure_tables() -> None:
    if not getattr(_ms, "_CACHE_INITIALIZED", False):
        _ms.init_mukadam_db()
    conn = sqlite3.connect(_ms.DB_PATH, timeout=10)
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS mukadam_otp_control (
                mobile_hash TEXT PRIMARY KEY,
                last_request_at REAL NOT NULL DEFAULT 0,
                request_window_start REAL NOT NULL DEFAULT 0,
                request_count INTEGER NOT NULL DEFAULT 0,
                verify_attempts INTEGER NOT NULL DEFAULT 0,
                blocked_until REAL NOT NULL DEFAULT 0,
                verified_at REAL NOT NULL DEFAULT 0
            )"""
        )
        control_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(mukadam_otp_control)").fetchall()}
        if "verified_at" not in control_columns:
            conn.execute("ALTER TABLE mukadam_otp_control ADD COLUMN verified_at REAL NOT NULL DEFAULT 0")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS mukadam_otp_ip_control (
                ip_hash TEXT PRIMARY KEY,
                window_start REAL NOT NULL DEFAULT 0,
                request_count INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS mukadam_registration_verifications (
                token_hash TEXT PRIMARY KEY,
                mobile_hash TEXT NOT NULL,
                issued_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                used_at REAL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mukadam_verification_mobile ON mukadam_registration_verifications(mobile_hash)")
        conn.commit()
    finally:
        conn.close()


def init_mukadam_otp_db() -> None:
    """Create OTP guard tables during backend startup."""
    _ensure_tables()


def _twilio_post(service_sid: str, auth_user: str, auth_password: str, action: str, fields: Dict[str, str]) -> Tuple[int, Dict[str, Any]]:
    url = f"https://verify.twilio.com/v2/Services/{urllib.parse.quote(service_sid, safe='')}/{action}"
    body = urllib.parse.urlencode(fields).encode("utf-8")
    auth_value = base64.b64encode(f"{auth_user}:{auth_password}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Basic {auth_value}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "SmartFarmerDiary-MukadamOTP/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {}
            return int(response.status), payload if isinstance(payload, dict) else {}
    except urllib.error.HTTPError as exc:
        # Do not propagate provider response bodies: they can include PII/provider details.
        try:
            exc.read()
        except Exception:
            pass
        return int(exc.code), {}
    except Exception:
        return 0, {}


def _check_and_reserve_request(mobile_hash: str, ip_hash: str, now: float) -> Tuple[bool, int, str]:
    """Atomically enforce cooldown and per-mobile/per-IP request caps."""
    conn = sqlite3.connect(_ms.DB_PATH, timeout=10)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT last_request_at, request_window_start, request_count, verify_attempts, blocked_until FROM mukadam_otp_control WHERE mobile_hash = ?",
            (mobile_hash,),
        ).fetchone()
        if row is None:
            last_request_at, mobile_window_start, mobile_count, verify_attempts, blocked_until = 0.0, now, 0, 0, 0.0
            conn.execute(
                "INSERT INTO mukadam_otp_control(mobile_hash, request_window_start) VALUES(?, ?)",
                (mobile_hash, now),
            )
        else:
            last_request_at, mobile_window_start, mobile_count, verify_attempts, blocked_until = row
        if float(blocked_until or 0) > now:
            conn.commit()
            return False, 429, "OTP માટે બહુ પ્રયાસ થયા છે. થોડા સમય પછી ફરી પ્રયાસ કરો."
        if float(last_request_at or 0) and now - float(last_request_at) < MOBILE_RESEND_COOLDOWN_SECONDS:
            conn.commit()
            return False, 429, "ફરી OTP મોકલવા માટે ૬૦ સેકન્ડ રાહ જુઓ."
        if now - float(mobile_window_start or 0) >= 3600:
            mobile_window_start, mobile_count = now, 0
        if int(mobile_count or 0) >= MOBILE_REQUEST_LIMIT_PER_HOUR:
            conn.commit()
            return False, 429, "આ મોબાઇલ નંબર પર કલાકની OTP મર્યાદા પૂરી થઈ છે. પછી પ્રયાસ કરો."

        ip_row = conn.execute(
            "SELECT window_start, request_count FROM mukadam_otp_ip_control WHERE ip_hash = ?", (ip_hash,)
        ).fetchone()
        if ip_row is None:
            ip_window_start, ip_count = now, 0
            conn.execute(
                "INSERT INTO mukadam_otp_ip_control(ip_hash, window_start, request_count) VALUES(?, ?, 0)",
                (ip_hash, now),
            )
        else:
            ip_window_start, ip_count = ip_row
        if now - float(ip_window_start or 0) >= 3600:
            ip_window_start, ip_count = now, 0
        if int(ip_count or 0) >= IP_REQUEST_LIMIT_PER_HOUR:
            conn.commit()
            return False, 429, "ઘણી OTP વિનંતીઓ થઈ છે. થોડા સમય પછી ફરી પ્રયાસ કરો."

        conn.execute(
            """UPDATE mukadam_otp_control SET last_request_at=?, request_window_start=?, request_count=?, verify_attempts=0, verified_at=0
               WHERE mobile_hash=?""",
            (now, mobile_window_start, int(mobile_count or 0) + 1, mobile_hash),
        )
        conn.execute(
            "UPDATE mukadam_otp_ip_control SET window_start=?, request_count=? WHERE ip_hash=?",
            (ip_window_start, int(ip_count or 0) + 1, ip_hash),
        )
        conn.commit()
        return True, 200, ""
    except Exception:
        conn.rollback()
        return False, 503, "OTP સેવા હાલમાં ઉપલબ્ધ નથી. કૃપા કરીને પછી પ્રયાસ કરો."
    finally:
        conn.close()


def request_mukadam_otp(mobile: str, client_ip: str = "unknown") -> Dict[str, Any]:
    credentials = _credentials()
    if credentials is None:
        return {"ok": False, "http_status": 503, "message_gu": "મોબાઇલ OTP સેવા હજી ગોઠવાઈ નથી. OTP ગોઠવાય ત્યાં સુધી નવી મુકાદમ નોંધણી બંધ રહેશે."}
    account_sid, auth_token, service_sid, hash_secret = credentials
    clean_mobile = _normalise_mobile(mobile)
    if len(clean_mobile) != 10 or not clean_mobile.isascii() or not clean_mobile.isdigit() or clean_mobile[0] not in "6789":
        return {"ok": False, "http_status": 400, "message_gu": "કૃપા કરીને ૬, ૭, ૮ અથવા ૯થી શરૂ થતો સાચો ૧૦ અંકનો ભારતીય મોબાઇલ નંબર લખો."}

    _ensure_tables()
    mobile_hash = _mobile_hash(clean_mobile, hash_secret)
    # A separate UTF-8 HMAC is used for IP keys; the stored value is still not an IP.
    ip_hash = hmac.new(hash_secret.encode("utf-8"), (client_ip or "unknown")[:128].encode("utf-8"), hashlib.sha256).hexdigest()
    now = time.time()
    with _OTP_LOCK:
        allowed, status, message = _check_and_reserve_request(mobile_hash, ip_hash, now)
    if not allowed:
        return {"ok": False, "http_status": status, "message_gu": message}

    status_code, body = _twilio_post(
        service_sid,
        account_sid,
        auth_token,
        "Verifications",
        {"To": "+91" + clean_mobile, "Channel": "sms"},
    )
    if status_code not in (200, 201) or str(body.get("status", "")).lower() not in ("pending", "queued", "approved"):
        return {"ok": False, "http_status": 503, "message_gu": "OTP SMS મોકલી શકાયો નથી. નંબર અને SMS સેવા તપાસીને ફરી પ્રયાસ કરો."}
    return {"ok": True, "message_gu": "તમારા મોબાઇલ પર OTP મોકલ્યો છે. OTP ૫ મિનિટમાં ચકાસો."}


def _record_failed_verification(mobile_hash: str, now: float) -> int:
    conn = sqlite3.connect(_ms.DB_PATH, timeout=10)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT verify_attempts, blocked_until FROM mukadam_otp_control WHERE mobile_hash=?", (mobile_hash,)
        ).fetchone()
        if row is None:
            conn.commit()
            return 0
        attempts = int(row[0] or 0) + 1
        blocked_until = float(row[1] or 0)
        if attempts >= VERIFY_ATTEMPT_LIMIT:
            blocked_until = now + VERIFY_LOCKOUT_SECONDS
        conn.execute(
            "UPDATE mukadam_otp_control SET verify_attempts=?, blocked_until=? WHERE mobile_hash=?",
            (attempts, blocked_until, mobile_hash),
        )
        conn.commit()
        return attempts
    except Exception:
        conn.rollback()
        return VERIFY_ATTEMPT_LIMIT
    finally:
        conn.close()


def _issue_registration_token(mobile_hash: str, now: float) -> str:
    token = secrets.token_urlsafe(32)
    conn = sqlite3.connect(_ms.DB_PATH, timeout=10)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM mukadam_registration_verifications WHERE expires_at <= ? OR used_at IS NOT NULL", (now,))
        conn.execute(
            "INSERT INTO mukadam_registration_verifications(token_hash, mobile_hash, issued_at, expires_at, used_at) VALUES (?, ?, ?, ?, NULL)",
            (_token_hash(token), mobile_hash, now, now + REGISTRATION_TOKEN_TTL_SECONDS),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return token


def verify_mukadam_otp(mobile: str, otp: str) -> Dict[str, Any]:
    credentials = _credentials()
    if credentials is None:
        return {"ok": False, "http_status": 503, "message_gu": "મોબાઇલ OTP સેવા હજી ગોઠવાઈ નથી. નવી મુકાદમ નોંધણી ઉપલબ્ધ નથી."}
    account_sid, auth_token, service_sid, hash_secret = credentials
    clean_mobile = _normalise_mobile(mobile)
    raw_otp = str(otp or "").strip()
    try:
        clean_otp = "".join(str(unicodedata.digit(ch)) for ch in raw_otp)
    except (TypeError, ValueError):
        clean_otp = ""
    if (len(clean_mobile) != 10 or not clean_mobile.isascii() or not clean_mobile.isdigit()
            or clean_mobile[0] not in "6789" or len(clean_otp) != 6 or not clean_otp.isascii() or not clean_otp.isdigit()):
        return {"ok": False, "http_status": 400, "message_gu": "૧૦ અંકનો ભારતીય મોબાઇલ અને ૬ અંકનો OTP સાચો દાખલ કરો."}
    _ensure_tables()
    mobile_hash = _mobile_hash(clean_mobile, hash_secret)
    now = time.time()
    with _OTP_LOCK:
        conn = sqlite3.connect(_ms.DB_PATH, timeout=10)
        try:
            row = conn.execute(
                "SELECT last_request_at, verify_attempts, blocked_until, verified_at FROM mukadam_otp_control WHERE mobile_hash=?", (mobile_hash,)
            ).fetchone()
        finally:
            conn.close()
    if row is None or float(row[0] or 0) <= 0:
        return {"ok": False, "http_status": 400, "message_gu": "પહેલા OTP મોકલો."}
    if float(row[3] or 0) > 0:
        return {"ok": False, "http_status": 409, "message_gu": "આ OTP પહેલેથી verify થઈ ગયો છે. નવો OTP મોકલીને ફરી verify કરો."}
    if float(row[2] or 0) > now:
        return {"ok": False, "http_status": 429, "message_gu": "OTP માટે બહુ ખોટા પ્રયાસ થયા છે. થોડા સમય પછી ફરી પ્રયાસ કરો."}
    if now - float(row[0]) > OTP_TTL_SECONDS:
        return {"ok": False, "http_status": 400, "message_gu": "OTPનો સમય પૂરો થયો છે. નવો OTP મોકલો."}
    if int(row[1] or 0) >= VERIFY_ATTEMPT_LIMIT:
        return {"ok": False, "http_status": 429, "message_gu": "OTP માટે બહુ ખોટા પ્રયાસ થયા છે. થોડા સમય પછી ફરી પ્રયાસ કરો."}

    status_code, body = _twilio_post(
        service_sid,
        account_sid,
        auth_token,
        "VerificationCheck",
        {"To": "+91" + clean_mobile, "Code": clean_otp},
    )
    if status_code not in (200, 201) or str(body.get("status", "")).lower() != "approved":
        attempts = _record_failed_verification(mobile_hash, now)
        if attempts >= VERIFY_ATTEMPT_LIMIT:
            return {"ok": False, "http_status": 429, "message_gu": "૫ ખોટા OTP પ્રયાસ પછી સુરક્ષા માટે નોંધણી થોડા સમય માટે બંધ છે."}
        return {"ok": False, "http_status": 400, "message_gu": "OTP ખોટો છે અથવા તેની સમયમર્યાદા પૂરી થઈ છે."}

    # Claim this OTP request as verified exactly once. This blocks concurrent/replayed
    # VerificationCheck calls from minting more than one registration token per SMS code.
    conn = sqlite3.connect(_ms.DB_PATH, timeout=10)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE mukadam_otp_control SET verified_at=?, verify_attempts=0 WHERE mobile_hash=? AND last_request_at=? AND verified_at=0 AND blocked_until<=?",
            (now, mobile_hash, float(row[0]), now),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return {"ok": False, "http_status": 409, "message_gu": "આ OTP પહેલેથી વપરાયો છે અથવા નવી વિનંતીથી બદલાયો છે. નવો OTP મોકલો."}
        conn.commit()
    except Exception:
        conn.rollback()
        return {"ok": False, "http_status": 503, "message_gu": "OTP ચકાસણી સ્થિતિ સુરક્ષિત રીતે સાચવી શકાયી નથી. ફરી પ્રયાસ કરો."}
    finally:
        conn.close()
    try:
        token = _issue_registration_token(mobile_hash, now)
    except Exception:
        return {"ok": False, "http_status": 503, "message_gu": "OTP ચકાસાયો, પરંતુ સુરક્ષિત નોંધણી token બનાવી શકાયો નથી. નવો OTP મોકલીને ફરી પ્રયાસ કરો."}
    return {"ok": True, "message_gu": "મોબાઇલ OTP સફળતાપૂર્વક ચકાસાયો.", "verification_token": token}


def consume_registration_token(token: str, mobile: str) -> bool:
    """Atomically consume a short-lived, mobile-bound, single-use verification token."""
    credentials = _credentials()
    raw_token = str(token or "").strip()
    clean_mobile = _normalise_mobile(mobile)
    if (credentials is None or not raw_token or len(clean_mobile) != 10
            or not clean_mobile.isascii() or not clean_mobile.isdigit() or clean_mobile[0] not in "6789"):
        return False
    _ensure_tables()
    mobile_hash = _mobile_hash(clean_mobile, credentials[3])
    now = time.time()
    conn = sqlite3.connect(_ms.DB_PATH, timeout=10)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT mobile_hash, expires_at, used_at FROM mukadam_registration_verifications WHERE token_hash=?",
            (_token_hash(raw_token),),
        ).fetchone()
        if row is None or not hmac.compare_digest(str(row[0]), mobile_hash) or float(row[1] or 0) <= now or row[2] is not None:
            conn.rollback()
            return False
        cursor = conn.execute(
            "UPDATE mukadam_registration_verifications SET used_at=? WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
            (now, _token_hash(raw_token), now),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return False
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()
