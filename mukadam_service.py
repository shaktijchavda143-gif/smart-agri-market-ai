import os
import math
import time
import json
import base64
import hashlib
import sqlite3
import threading
import csv
import io
import urllib.request
from typing import List, Optional, Dict, Any

DB_PATH = os.environ.get("MUKADAM_DB_PATH", "/tmp/mukadam_marketplace.db")
BACKUP_JSON_PATH = "/tmp/mukadam_backup_snapshot.json"
_MUKADAM_LOCK = threading.RLock()
_MUKADAM_RAM_CACHE: List[Dict[str, Any]] = []
_CACHE_INITIALIZED = False
AUTO_EXPIRY_SECONDS = 72 * 3600


def _hash_pin(pin: str) -> str:
    clean_pin = str(pin).strip()
    return hashlib.sha256(f"smart_agri_mukadam_{clean_pin}".encode("utf-8")).hexdigest()


def _clean_mobile(mobile: str) -> str:
    digits = "".join(ch for ch in str(mobile) if ch.isdigit())
    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[-10:]
    return digits


def _haversine_km(
    lat1: Optional[float],
    lon1: Optional[float],
    lat2: Optional[float],
    lon2: Optional[float],
) -> Optional[float]:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    if lat1 == 0.0 or lon1 == 0.0 or lat2 == 0.0 or lon2 == 0.0:
        return None
    try:
        radius_km = 6371.0
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        d_phi = math.radians(float(lat2) - float(lat1))
        d_lambda = math.radians(float(lon2) - float(lon1))
        a = (
            math.sin(d_phi / 2.0) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(radius_km * c, 1)
    except Exception:
        return None


def init_mukadam_db() -> None:
    global _CACHE_INITIALIZED
    with _MUKADAM_LOCK:
        db_dir = os.path.dirname(DB_PATH)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mukadams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    mobile TEXT UNIQUE NOT NULL,
                    pin_hash TEXT NOT NULL,
                    district TEXT DEFAULT '',
                    taluka TEXT DEFAULT '',
                    village TEXT DEFAULT '',
                    latitude REAL DEFAULT 0.0,
                    longitude REAL DEFAULT 0.0,
                    available_status TEXT DEFAULT 'available',
                    available_from_date TEXT DEFAULT '',
                    total_labors INTEGER DEFAULT 0,
                    male_labors INTEGER DEFAULT 0,
                    female_labors INTEGER DEFAULT 0,
                    wage_type TEXT DEFAULT 'daily',
                    daily_wage_rate REAL DEFAULT 0.0,
                    contract_rate_details TEXT DEFAULT '',
                    rickshaw_fare_type TEXT DEFAULT 'per_km',
                    rickshaw_fare_rate REAL DEFAULT 0.0,
                    mukadami_type TEXT DEFAULT 'per_labor',
                    mukadami_rate REAL DEFAULT 0.0,
                    skills TEXT DEFAULT '',
                    notes TEXT DEFAULT '',
                    rating_sum REAL DEFAULT 5.0,
                    rating_count INTEGER DEFAULT 1,
                    contact_clicks INTEGER DEFAULT 0,
                    updated_at REAL DEFAULT 0.0
                )
                """
            )
            conn.commit()
        finally:
            conn.close()
        _restore_from_github_if_empty()
        _refresh_ram_cache()
        _CACHE_INITIALIZED = True


def _refresh_ram_cache() -> None:
    global _MUKADAM_RAM_CACHE
    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM mukadams ORDER BY updated_at DESC").fetchall()
            _MUKADAM_RAM_CACHE = [dict(row) for row in rows]
        finally:
            conn.close()


def _trigger_github_backup_async() -> None:
    github_token = os.environ.get("GITHUB_BACKUP_TOKEN", "").strip()
    github_repo = os.environ.get("GITHUB_BACKUP_REPO", "").strip()
    github_file_path = os.environ.get(
        "GITHUB_BACKUP_PATH", "backups/mukadam_data.json"
    ).strip()
    if not github_token or not github_repo:
        return

    def _backup_worker() -> None:
        try:
            with _MUKADAM_LOCK:
                snapshot = list(_MUKADAM_RAM_CACHE)
            content_bytes = json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")
            b64_content = base64.b64encode(content_bytes).decode("utf-8")
            api_url = f"https://api.github.com/repos/{github_repo}/contents/{github_file_path}"
            headers = {
                "Authorization": f"Bearer {github_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "SmartAgriMarket-MukadamBackup",
            }
            sha = None
            try:
                req_get = urllib.request.Request(api_url, headers=headers, method="GET")
                with urllib.request.urlopen(req_get, timeout=10) as resp:
                    existing = json.loads(resp.read().decode("utf-8"))
                sha = existing.get("sha")
            except Exception:
                sha = None
            payload = {
                "message": f"Auto-backup Mukadam data ({len(snapshot)} records)",
                "content": b64_content,
            }
            if sha:
                payload["sha"] = sha
            req_put = urllib.request.Request(
                api_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={**headers, "Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(req_put, timeout=15):
                pass
        except Exception:
            pass

    threading.Thread(target=_backup_worker, daemon=True).start()


def _restore_from_github_if_empty() -> None:
    github_token = os.environ.get("GITHUB_BACKUP_TOKEN", "").strip()
    github_repo = os.environ.get("GITHUB_BACKUP_REPO", "").strip()
    github_file_path = os.environ.get(
        "GITHUB_BACKUP_PATH", "backups/mukadam_data.json"
    ).strip()
    if not github_token or not github_repo:
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        count = conn.execute("SELECT COUNT(*) FROM mukadams").fetchone()[0]
        if count > 0:
            return
        api_url = f"https://api.github.com/repos/{github_repo}/contents/{github_file_path}"
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "SmartAgriMarket-MukadamBackup",
        }
        req = urllib.request.Request(api_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw_json = base64.b64decode(data["content"]).decode("utf-8")
        records = json.loads(raw_json)
        for rec in records:
            conn.execute(
                """
                INSERT OR IGNORE INTO mukadams (
                    name, mobile, pin_hash, district, taluka, village,
                    latitude, longitude, available_status, available_from_date,
                    total_labors, male_labors, female_labors,
                    wage_type, daily_wage_rate, contract_rate_details,
                    rickshaw_fare_type, rickshaw_fare_rate,
                    mukadami_type, mukadami_rate,
                    skills, notes, rating_sum, rating_count, contact_clicks, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.get("name", ""),
                    rec.get("mobile", ""),
                    rec.get("pin_hash", ""),
                    rec.get("district", ""),
                    rec.get("taluka", ""),
                    rec.get("village", ""),
                    float(rec.get("latitude", 0.0)),
                    float(rec.get("longitude", 0.0)),
                    rec.get("available_status", "available"),
                    rec.get("available_from_date", ""),
                    int(rec.get("total_labors", 0)),
                    int(rec.get("male_labors", 0)),
                    int(rec.get("female_labors", 0)),
                    rec.get("wage_type", "daily"),
                    float(rec.get("daily_wage_rate", 0.0)),
                    rec.get("contract_rate_details", ""),
                    rec.get("rickshaw_fare_type", "per_km"),
                    float(rec.get("rickshaw_fare_rate", 0.0)),
                    rec.get("mukadami_type", "per_labor"),
                    float(rec.get("mukadami_rate", 0.0)),
                    rec.get("skills", ""),
                    rec.get("notes", ""),
                    float(rec.get("rating_sum", 5.0)),
                    int(rec.get("rating_count", 1)),
                    int(rec.get("contact_clicks", 0)),
                    float(rec.get("updated_at", time.time())),
                ),
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def register_or_update_mukadam(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    name = str(payload.get("name", "")).strip()
    mobile = _clean_mobile(payload.get("mobile", ""))
    pin = str(payload.get("pin", "")).strip()
    if not name:
        return {"ok": False, "message_gu": "કૃપા કરીને મુકાદમનું નામ લખો."}
    if len(mobile) != 10:
        return {"ok": False, "message_gu": "કૃપા કરીને સાચો ૧૦ આંકડાનો મોબાઇલ નંબર લખો."}
    if len(pin) != 4 or not pin.isdigit():
        return {
            "ok": False,
            "message_gu": "સુરક્ષા માટે ૪ આંકડાનો સિક્રેટ પિન (દા.ત. 1234) રાખવો ફરજિયાત છે.",
        }

    pin_hash = _hash_pin(pin)
    now = time.time()
    male_labors = max(0, int(payload.get("male_labors", 0) or 0))
    female_labors = max(0, int(payload.get("female_labors", 0) or 0))
    total_labors = max(0, int(payload.get("total_labors", 0) or 0))
    if total_labors == 0 and (male_labors + female_labors) > 0:
        total_labors = male_labors + female_labors
    skills_raw = payload.get("skills", "")
    if isinstance(skills_raw, list):
        skills_str = ", ".join(str(skill).strip() for skill in skills_raw if str(skill).strip())
    else:
        skills_str = str(skills_raw).strip()

    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            existing = conn.execute(
                "SELECT * FROM mukadams WHERE mobile = ?", (mobile,)
            ).fetchone()
            if existing:
                if existing["pin_hash"] != pin_hash:
                    return {
                        "ok": False,
                        "message_gu": "આ મોબાઇલ નંબર પહેલેથી રજીસ્ટર છે. વિગત બદલવા માટે તમારો સાચો ૪ આંકડાનો પિન નાખો.",
                    }
                conn.execute(
                    """
                    UPDATE mukadams SET
                        name = ?, district = ?, taluka = ?, village = ?,
                        latitude = ?, longitude = ?,
                        available_status = ?, available_from_date = ?,
                        total_labors = ?, male_labors = ?, female_labors = ?,
                        wage_type = ?, daily_wage_rate = ?, contract_rate_details = ?,
                        rickshaw_fare_type = ?, rickshaw_fare_rate = ?,
                        mukadami_type = ?, mukadami_rate = ?,
                        skills = ?, notes = ?, updated_at = ?
                    WHERE mobile = ?
                    """,
                    (
                        name,
                        str(payload.get("district", "")).strip(),
                        str(payload.get("taluka", "")).strip(),
                        str(payload.get("village", "")).strip(),
                        float(payload.get("latitude", 0.0) or 0.0),
                        float(payload.get("longitude", 0.0) or 0.0),
                        str(payload.get("available_status", "available")).strip(),
                        str(payload.get("available_from_date", "")).strip(),
                        total_labors,
                        male_labors,
                        female_labors,
                        str(payload.get("wage_type", "daily")).strip(),
                        float(payload.get("daily_wage_rate", 0.0) or 0.0),
                        str(payload.get("contract_rate_details", "")).strip(),
                        str(payload.get("rickshaw_fare_type", "per_km")).strip(),
                        float(payload.get("rickshaw_fare_rate", 0.0) or 0.0),
                        str(payload.get("mukadami_type", "per_labor")).strip(),
                        float(payload.get("mukadami_rate", 0.0) or 0.0),
                        skills_str,
                        str(payload.get("notes", "")).strip(),
                        now,
                        mobile,
                    ),
                )
                action_msg = "તમારી મુકાદમ પ્રોફાઇલ અને મજૂરની વિગતો સફળતાપૂર્વક અપડેટ થઈ ગઈ છે!"
            else:
                conn.execute(
                    """
                    INSERT INTO mukadams (
                        name, mobile, pin_hash, district, taluka, village,
                        latitude, longitude, available_status, available_from_date,
                        total_labors, male_labors, female_labors,
                        wage_type, daily_wage_rate, contract_rate_details,
                        rickshaw_fare_type, rickshaw_fare_rate,
                        mukadami_type, mukadami_rate,
                        skills, notes, rating_sum, rating_count, contact_clicks, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 5.0, 1, 0, ?)
                    """,
                    (
                        name,
                        mobile,
                        pin_hash,
                        str(payload.get("district", "")).strip(),
                        str(payload.get("taluka", "")).strip(),
                        str(payload.get("village", "")).strip(),
                        float(payload.get("latitude", 0.0) or 0.0),
                        float(payload.get("longitude", 0.0) or 0.0),
                        str(payload.get("available_status", "available")).strip(),
                        str(payload.get("available_from_date", "")).strip(),
                        total_labors,
                        male_labors,
                        female_labors,
                        str(payload.get("wage_type", "daily")).strip(),
                        float(payload.get("daily_wage_rate", 0.0) or 0.0),
                        str(payload.get("contract_rate_details", "")).strip(),
                        str(payload.get("rickshaw_fare_type", "per_km")).strip(),
                        float(payload.get("rickshaw_fare_rate", 0.0) or 0.0),
                        str(payload.get("mukadami_type", "per_labor")).strip(),
                        float(payload.get("mukadami_rate", 0.0) or 0.0),
                        skills_str,
                        str(payload.get("notes", "")).strip(),
                        now,
                    ),
                )
                action_msg = "મુકાદમ તરીકે તમારી નોંધણી સફળતાપૂર્વક થઈ ગઈ છે! હવે નજીકના ખેડૂતો તમારો સંપર્ક કરી શકશે."
            conn.commit()
        finally:
            conn.close()

    _refresh_ram_cache()
    _trigger_github_backup_async()
    return {"ok": True, "message_gu": action_msg, "mobile": mobile}


def update_mukadam_quick_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    mobile = _clean_mobile(payload.get("mobile", ""))
    pin = str(payload.get("pin", "")).strip()
    new_status = str(payload.get("available_status", "unavailable")).strip()
    available_from_date = str(payload.get("available_from_date", "")).strip()
    total_labors = payload.get("total_labors", None)
    if len(mobile) != 10 or len(pin) != 4:
        return {
            "ok": False,
            "message_gu": "સાચો ૧૦ આંકડાનો મોબાઇલ નંબર અને ૪ આંકડાનો પિન નાખો.",
        }

    pin_hash = _hash_pin(pin)
    now = time.time()
    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            existing = conn.execute(
                "SELECT * FROM mukadams WHERE mobile = ?", (mobile,)
            ).fetchone()
            if not existing:
                return {
                    "ok": False,
                    "message_gu": "આ મોબાઇલ નંબરથી કોઈ મુકાદમ રજીસ્ટર નથી. પહેલા નોંધણી કરો.",
                }
            if existing["pin_hash"] != pin_hash:
                return {"ok": False, "message_gu": "તમારો ૪ આંકડાનો સિક્રેટ પિન ખોટો છે."}
            if total_labors is not None:
                conn.execute(
                    """
                    UPDATE mukadams
                    SET available_status = ?, available_from_date = ?, total_labors = ?, updated_at = ?
                    WHERE mobile = ?
                    """,
                    (new_status, available_from_date, max(0, int(total_labors)), now, mobile),
                )
            else:
                conn.execute(
                    """
                    UPDATE mukadams
                    SET available_status = ?, available_from_date = ?, updated_at = ?
                    WHERE mobile = ?
                    """,
                    (new_status, available_from_date, now, mobile),
                )
            conn.commit()
        finally:
            conn.close()

    _refresh_ram_cache()
    _trigger_github_backup_async()
    status_gu = {
        "available": "🟢 હાલ મજૂર ઉપલબ્ધ છે",
        "future": f"🟡 {available_from_date} પછી મજૂર ઉપલબ્ધ થશે",
        "unavailable": "🔴 હાલ મજૂર ઉપલબ્ધ નથી",
    }.get(new_status, "અપડેટ થયું")
    return {
        "ok": True,
        "message_gu": f"તમારું સ્ટેટસ બદલાઈ ગયું છે: {status_gu}",
        "available_status": new_status,
    }


def _calculate_estimated_cost(
    item: Dict[str, Any], required_labors: int, distance_km: Optional[float]
) -> Dict[str, Any]:
    labors = max(
        1,
        required_labors if required_labors > 0 else int(item.get("total_labors", 1) or 1),
    )
    distance = distance_km if (distance_km is not None and distance_km > 0) else 10.0
    daily_rate = float(item.get("daily_wage_rate", 0.0) or 0.0)
    labor_cost = round(daily_rate * labors, 0)
    rickshaw_type = item.get("rickshaw_fare_type", "per_km")
    rickshaw_rate = float(item.get("rickshaw_fare_rate", 0.0) or 0.0)
    rickshaw_cost = (
        round(rickshaw_rate * distance, 0)
        if rickshaw_type == "per_km"
        else round(rickshaw_rate, 0)
    )
    mukadami_type = item.get("mukadami_type", "per_labor")
    mukadami_rate = float(item.get("mukadami_rate", 0.0) or 0.0)
    mukadami_cost = (
        round(mukadami_rate * labors, 0)
        if mukadami_type == "per_labor"
        else round(mukadami_rate, 0)
    )
    total_cost = labor_cost + rickshaw_cost + mukadami_cost
    return {
        "calculated_for_labors": labors,
        "assumed_distance_km": round(distance, 1),
        "labor_cost": int(labor_cost),
        "rickshaw_cost": int(rickshaw_cost),
        "mukadami_cost": int(mukadami_cost),
        "total_estimated_cost": int(total_cost),
    }


def search_nearby_mukadams(
    district: str = "",
    taluka: str = "",
    skill: str = "",
    farmer_lat: Optional[float] = None,
    farmer_lon: Optional[float] = None,
    max_km: float = 60.0,
    required_labors: int = 0,
    include_unavailable: bool = True,
) -> Dict[str, Any]:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    now = time.time()
    district_filter = district.strip().lower()
    taluka_filter = taluka.strip().lower()
    skill_filter = skill.strip().lower()
    results = []

    with _MUKADAM_LOCK:
        cached_list = list(_MUKADAM_RAM_CACHE)
    for raw in cached_list:
        item = dict(raw)
        item.pop("pin_hash", None)
        age_seconds = max(0.0, now - float(item.get("updated_at", now)))
        hours_ago = int(age_seconds // 3600)
        is_stale = age_seconds > AUTO_EXPIRY_SECONDS
        status = item.get("available_status", "available")
        if not include_unavailable and status == "unavailable":
            continue
        if skill_filter and skill_filter not in ("all", "બધા", "તમામ", "બધા કામ"):
            if skill_filter not in str(item.get("skills", "")).lower():
                continue
        distance_km = _haversine_km(
            farmer_lat, farmer_lon, item.get("latitude"), item.get("longitude")
        )
        same_taluka = bool(
            taluka_filter and taluka_filter in str(item.get("taluka", "")).lower()
        )
        same_district = bool(
            district_filter and district_filter in str(item.get("district", "")).lower()
        )
        if distance_km is not None:
            if max_km > 0 and distance_km > max_km and not same_district:
                continue
        elif district_filter and not same_district:
            continue

        rating_count = max(1, int(item.get("rating_count", 1) or 1))
        rating_sum = float(item.get("rating_sum", 5.0) or 5.0)
        average_rating = round(rating_sum / rating_count, 1)
        cost_breakdown = _calculate_estimated_cost(item, required_labors, distance_km)
        if hours_ago < 1:
            updated_text_gu = "હમણાં જ અપડેટ કર્યું"
        elif hours_ago < 24:
            updated_text_gu = f"{hours_ago} કલાક પહેલાં અપડેટ કર્યું"
        else:
            days = hours_ago // 24
            updated_text_gu = f"{days} દિવસ પહેલાં અપડેટ કર્યું"

        item["distance_km"] = distance_km
        item["avg_rating"] = average_rating
        item["is_stale"] = is_stale
        item["updated_text_gu"] = updated_text_gu
        item["cost_breakdown"] = cost_breakdown
        status_rank = 0 if (status == "available" and not is_stale) else (1 if status == "future" else 2)
        locality_rank = 0 if same_taluka else (1 if same_district else 2)
        distance_sort = distance_km if distance_km is not None else (
            15.0 if same_taluka else (35.0 if same_district else 999.0)
        )
        results.append(
            (
                status_rank,
                locality_rank,
                distance_sort,
                -float(item.get("updated_at", 0)),
                item,
            )
        )

    results.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    final_items = [row[4] for row in results]
    return {"ok": True, "count": len(final_items), "mukadams": final_items}


def record_rating_or_contact(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    mobile = _clean_mobile(payload.get("mobile", ""))
    action = str(payload.get("action", "contact")).strip()
    stars = payload.get("stars", None)
    if len(mobile) != 10:
        return {"ok": False, "message_gu": "અમાન્ય મોબાઇલ નંબર."}

    with _MUKADAM_LOCK:
        conn = sqlite3.connect(DB_PATH)
        try:
            if action == "rate" and stars is not None:
                rating = max(1.0, min(5.0, float(stars)))
                conn.execute(
                    """
                    UPDATE mukadams
                    SET rating_sum = rating_sum + ?, rating_count = rating_count + 1
                    WHERE mobile = ?
                    """,
                    (rating, mobile),
                )
                message = "તમારું રેટિંગ નોંધાઈ ગયું છે. આભાર!"
            else:
                conn.execute(
                    "UPDATE mukadams SET contact_clicks = contact_clicks + 1 WHERE mobile = ?",
                    (mobile,),
                )
                message = "સંપર્ક નોંધાયો."
            conn.commit()
        finally:
            conn.close()

    _refresh_ram_cache()
    return {"ok": True, "message_gu": message}


def export_mukadams_csv() -> str:
    if not _CACHE_INITIALIZED:
        init_mukadam_db()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "મુકાદમનું નામ",
            "મોબાઇલ નંબર",
            "જિલ્લો",
            "તાલુકો",
            "ગામ",
            "સ્ટેટસ",
            "ઉપલબ્ધ તારીખ",
            "કુલ મજૂર",
            "પુરુષ",
            "સ્ત્રી",
            "મજૂરી પ્રકાર",
            "રોજિંદો ભાવ (₹)",
            "ઉચ્ચક ભાવ વિગત",
            "રીક્ષા ભાડું પ્રકાર",
            "રીક્ષા ભાડું (₹)",
            "મુકાદમી પ્રકાર",
            "મુકાદમી (₹)",
            "કામની કુશળતા",
            "રેટિંગ",
            "ખેડૂત સંપર્ક સંખ્યા",
        ]
    )
    with _MUKADAM_LOCK:
        for item in _MUKADAM_RAM_CACHE:
            rating_count = max(1, int(item.get("rating_count", 1) or 1))
            average_rating = round(
                float(item.get("rating_sum", 5.0) or 5.0) / rating_count, 1
            )
            writer.writerow(
                [
                    item.get("id", ""),
                    item.get("name", ""),
                    item.get("mobile", ""),
                    item.get("district", ""),
                    item.get("taluka", ""),
                    item.get("village", ""),
                    item.get("available_status", ""),
                    item.get("available_from_date", ""),
                    item.get("total_labors", 0),
                    item.get("male_labors", 0),
                    item.get("female_labors", 0),
                    item.get("wage_type", ""),
                    item.get("daily_wage_rate", 0),
                    item.get("contract_rate_details", ""),
                    item.get("rickshaw_fare_type", ""),
                    item.get("rickshaw_fare_rate", 0),
                    item.get("mukadami_type", ""),
                    item.get("mukadami_rate", 0),
                    item.get("skills", ""),
                    average_rating,
                    item.get("contact_clicks", 0),
                ]
            )
    return output.getvalue()
