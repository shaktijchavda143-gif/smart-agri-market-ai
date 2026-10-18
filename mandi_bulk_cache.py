"""Model 3: Statewide Bulk Fetch + Server-Side Persistent Shared Cache (SQLite + JSON).

This module provides durable server-side storage for official data.gov.in
(`9ef84268-d588-465a-a308-a864a43d0070`) Gujarat APMC mandi records so that:
1. The first farmer request triggers a single statewide bulk fetch (`filters[state]=Gujarat`).
2. Every crop and APMC yard in the statewide dataset is normalized, indexed, and stored
   in SQLite (WAL mode) + in-memory shared cache.
3. Subsequent requests from 10,000+ farmers across any crop or yard are served
   directly from the shared cache with zero additional upstream API calls.
4. Empty or failed upstream responses never overwrite valid cached data.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_DB_LOCK = threading.RLock()


def resolve_mandi_cache_db_path() -> str:
    """Resolve persistent SQLite path on Render (/var/data) with local/tmp fallback."""
    explicit = os.getenv("MANDI_CACHE_DB_PATH", "").strip()
    if explicit:
        return explicit
    candidates = [
        os.getenv("MUKADAM_DATA_DIR", "").strip(),
        "/var/data/mukadam_store",
        "/tmp",
    ]
    for folder in candidates:
        if not folder:
            continue
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            test_path = Path(folder) / "mandi_shared_cache.db"
            return str(test_path)
        except Exception:
            continue
    return "/tmp/mandi_shared_cache.db"


DB_PATH = resolve_mandi_cache_db_path()


def init_mandi_cache_db(db_path: str | None = None) -> str:
    """Initialize the persistent SQLite schema for Model 3 Mandi Shared Cache."""
    target = db_path or DB_PATH
    with _DB_LOCK:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target, timeout=10.0)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mandi_state_sync_meta (
                    state_key TEXT PRIMARY KEY,
                    synced_at REAL NOT NULL,
                    latest_arrival_date TEXT NOT NULL DEFAULT '',
                    total_raw_records INTEGER NOT NULL DEFAULT 0,
                    total_valid_records INTEGER NOT NULL DEFAULT 0,
                    pagination_complete INTEGER NOT NULL DEFAULT 0,
                    pages_fetched INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'official_api'
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mandi_shared_pool_kv (
                    pool_key TEXT PRIMARY KEY,
                    saved_at REAL NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mandi_cached_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    state_key TEXT NOT NULL,
                    market_key TEXT NOT NULL,
                    commodity_key TEXT NOT NULL,
                    variety TEXT NOT NULL DEFAULT '',
                    arrival_date_iso TEXT NOT NULL,
                    arrival_date TEXT NOT NULL,
                    market TEXT NOT NULL,
                    district TEXT NOT NULL DEFAULT '',
                    commodity TEXT NOT NULL,
                    min_price REAL NOT NULL,
                    modal_price REAL NOT NULL,
                    max_price REAL NOT NULL,
                    record_json TEXT NOT NULL,
                    saved_at REAL NOT NULL,
                    UNIQUE(state_key, market_key, commodity_key, variety, arrival_date_iso)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mandi_records_state_crop "
                "ON mandi_cached_records(state_key, commodity_key, arrival_date_iso DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mandi_records_state_mkt_crop "
                "ON mandi_cached_records(state_key, market_key, commodity_key, arrival_date_iso DESC)"
            )
            conn.commit()
        finally:
            conn.close()
    return target


def load_pool_from_sqlite(db_path: str | None = None) -> dict[str, dict[str, Any]]:
    """Load the persisted shared pool dictionary from SQLite on server startup/restart."""
    target = db_path or DB_PATH
    if not os.path.exists(target):
        return {}
    out: dict[str, dict[str, Any]] = {}
    with _DB_LOCK:
        try:
            init_mandi_cache_db(target)
            conn = sqlite3.connect(target, timeout=10.0)
            try:
                cur = conn.execute("SELECT pool_key, saved_at, payload_json FROM mandi_shared_pool_kv")
                for pool_key, saved_at, payload_json in cur.fetchall():
                    try:
                        payload = json.loads(payload_json)
                        if isinstance(payload, dict):
                            out[str(pool_key)] = {"saved_at": float(saved_at), "payload": payload}
                    except Exception:
                        continue
            finally:
                conn.close()
        except Exception:
            return {}
    return out


def save_pool_to_sqlite(pool: dict[str, dict[str, Any]], db_path: str | None = None) -> None:
    """Persist the shared pool entries to SQLite atomically without losing valid records."""
    if not pool:
        return
    target = db_path or DB_PATH
    with _DB_LOCK:
        try:
            init_mandi_cache_db(target)
            conn = sqlite3.connect(target, timeout=10.0)
            try:
                rows_to_upsert = []
                for pool_key, entry in list(pool.items()):
                    if not isinstance(entry, dict):
                        continue
                    saved_at = float(entry.get("saved_at", 0.0) or 0.0)
                    payload = entry.get("payload")
                    if not isinstance(payload, dict):
                        continue
                    # Never persist empty record lists over valid cache entries
                    if not payload.get("records") and not pool_key.startswith("__meta__|"):
                        continue
                    rows_to_upsert.append(
                        (str(pool_key), saved_at, json.dumps(payload, ensure_ascii=False))
                    )
                if rows_to_upsert:
                    conn.executemany(
                        """
                        INSERT INTO mandi_shared_pool_kv (pool_key, saved_at, payload_json)
                        VALUES (?, ?, ?)
                        ON CONFLICT(pool_key) DO UPDATE SET
                            saved_at = excluded.saved_at,
                            payload_json = excluded.payload_json
                        """,
                        rows_to_upsert,
                    )
                    conn.commit()
            finally:
                conn.close()
        except Exception:
            pass


def save_statewide_records_to_sqlite(
    state_key: str,
    records: list[dict[str, Any]],
    *,
    market_key_fn,
    commodity_key_fn,
    meta: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> int:
    """Persist normalized statewide records and sync metadata into SQLite."""
    if not records:
        return 0
    target = db_path or DB_PATH
    now_ts = time.time()
    meta = meta or {}
    saved_count = 0
    with _DB_LOCK:
        try:
            init_mandi_cache_db(target)
            conn = sqlite3.connect(target, timeout=10.0)
            try:
                batch = []
                for row in records:
                    if not isinstance(row, dict):
                        continue
                    mkt = str(row.get("market") or "").strip()
                    cmdt = str(row.get("commodity") or "").strip()
                    if not mkt or not cmdt:
                        continue
                    m_key = str(market_key_fn(mkt) or "").strip()
                    c_key = str(commodity_key_fn(cmdt) or "").strip()
                    if not m_key or not c_key:
                        continue
                    variety = str(row.get("variety") or "").strip()
                    arr_iso = str(row.get("arrival_date_iso") or row.get("report_date") or "").strip()
                    arr_disp = str(row.get("arrival_date") or "").strip()
                    district = str(row.get("district") or "").strip()
                    try:
                        min_f = float(row.get("min_price") or 0.0)
                        modal_f = float(row.get("modal_price") or 0.0)
                        max_f = float(row.get("max_price") or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if not (min_f > 0 and min_f <= modal_f <= max_f):
                        continue
                    batch.append(
                        (
                            state_key,
                            m_key,
                            c_key,
                            variety,
                            arr_iso,
                            arr_disp,
                            mkt,
                            district,
                            cmdt,
                            min_f,
                            modal_f,
                            max_f,
                            json.dumps(row, ensure_ascii=False),
                            now_ts,
                        )
                    )
                if batch:
                    conn.executemany(
                        """
                        INSERT INTO mandi_cached_records (
                            state_key, market_key, commodity_key, variety,
                            arrival_date_iso, arrival_date, market, district,
                            commodity, min_price, modal_price, max_price,
                            record_json, saved_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(state_key, market_key, commodity_key, variety, arrival_date_iso)
                        DO UPDATE SET
                            min_price = excluded.min_price,
                            modal_price = excluded.modal_price,
                            max_price = excluded.max_price,
                            record_json = excluded.record_json,
                            saved_at = excluded.saved_at
                        """,
                        batch,
                    )
                    saved_count = len(batch)
                conn.execute(
                    """
                    INSERT INTO mandi_state_sync_meta (
                        state_key, synced_at, latest_arrival_date,
                        total_raw_records, total_valid_records,
                        pagination_complete, pages_fetched, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(state_key) DO UPDATE SET
                        synced_at = excluded.synced_at,
                        latest_arrival_date = excluded.latest_arrival_date,
                        total_raw_records = excluded.total_raw_records,
                        total_valid_records = excluded.total_valid_records,
                        pagination_complete = excluded.pagination_complete,
                        pages_fetched = excluded.pages_fetched,
                        source = excluded.source
                    """,
                    (
                        state_key,
                        now_ts,
                        str(meta.get("latest_date") or ""),
                        int(meta.get("raw_record_count") or len(records)),
                        saved_count,
                        1 if meta.get("pagination_complete") else 0,
                        int(meta.get("pages_fetched") or 1),
                        str(meta.get("source") or "official_api"),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            return 0
    return saved_count


def get_mandi_cache_stats(db_path: str | None = None) -> dict[str, Any]:
    """Return diagnostic statistics about the persistent SQLite Mandi cache."""
    target = db_path or DB_PATH
    stats: dict[str, Any] = {
        "db_path": target,
        "db_exists": os.path.exists(target),
        "total_cached_records": 0,
        "distinct_markets": 0,
        "distinct_commodities": 0,
        "pool_keys_count": 0,
        "state_sync_meta": {},
    }
    if not os.path.exists(target):
        return stats
    with _DB_LOCK:
        try:
            init_mandi_cache_db(target)
            conn = sqlite3.connect(target, timeout=5.0)
            try:
                row = conn.execute(
                    "SELECT COUNT(*), COUNT(DISTINCT market_key), COUNT(DISTINCT commodity_key) FROM mandi_cached_records"
                ).fetchone()
                if row:
                    stats["total_cached_records"] = int(row[0] or 0)
                    stats["distinct_markets"] = int(row[1] or 0)
                    stats["distinct_commodities"] = int(row[2] or 0)
                kv_row = conn.execute("SELECT COUNT(*) FROM mandi_shared_pool_kv").fetchone()
                if kv_row:
                    stats["pool_keys_count"] = int(kv_row[0] or 0)
                for s_row in conn.execute(
                    "SELECT state_key, synced_at, latest_arrival_date, total_raw_records, "
                    "total_valid_records, pagination_complete, pages_fetched, source "
                    "FROM mandi_state_sync_meta"
                ).fetchall():
                    stats["state_sync_meta"][str(s_row[0])] = {
                        "synced_at": float(s_row[1] or 0.0),
                        "age_seconds": round(max(0.0, time.time() - float(s_row[1] or 0.0)), 1),
                        "latest_arrival_date": str(s_row[2] or ""),
                        "total_raw_records": int(s_row[3] or 0),
                        "total_valid_records": int(s_row[4] or 0),
                        "pagination_complete": bool(s_row[5]),
                        "pages_fetched": int(s_row[6] or 0),
                        "source": str(s_row[7] or ""),
                    }
            finally:
                conn.close()
        except Exception:
            pass
    return stats


def get_recent_records_stepwise(
    state_key: str,
    market_key: str,
    commodity_key: str,
    *,
    max_lookback_days: int = 7,
    today_iso: str = "",
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Step-by-step 7-day lookback in SQLite mandi_cached_records:
    Checks Today (day 0), then Yesterday (day 1), then day 2 ... up to max_lookback_days (7 days).
    Returns all records for the newest available day within the 7-day window.
    """
    from datetime import datetime, timedelta, timezone
    target = db_path or DB_PATH
    if not os.path.exists(target):
        return []
    ist = timezone(timedelta(hours=5, minutes=30))
    if today_iso:
        try:
            today_dt = datetime.fromisoformat(today_iso).date()
        except Exception:
            today_dt = datetime.now(ist).date()
    else:
        today_dt = datetime.now(ist).date()

    with _DB_LOCK:
        try:
            init_mandi_cache_db(target)
            conn = sqlite3.connect(target, timeout=5.0)
            try:
                if market_key and market_key != "ALL":
                    cur = conn.execute(
                        """
                        SELECT arrival_date_iso, arrival_date, record_json
                        FROM mandi_cached_records
                        WHERE state_key = ? AND market_key = ? AND commodity_key = ?
                        ORDER BY arrival_date_iso DESC
                        """,
                        (state_key, market_key, commodity_key),
                    )
                else:
                    cur = conn.execute(
                        """
                        SELECT arrival_date_iso, arrival_date, record_json
                        FROM mandi_cached_records
                        WHERE state_key = ? AND commodity_key = ?
                        ORDER BY arrival_date_iso DESC
                        """,
                        (state_key, commodity_key),
                    )
                rows_by_day: dict[str, list[dict[str, Any]]] = {}
                for arr_iso, arr_disp, rec_json in cur.fetchall():
                    day_str = str(arr_iso or "")[:10]
                    if not day_str and arr_disp:
                        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
                            try:
                                day_str = datetime.strptime(str(arr_disp).strip(), fmt).date().isoformat()
                                break
                            except ValueError:
                                continue
                    if not day_str:
                        continue
                    try:
                        rec = json.loads(rec_json)
                        if isinstance(rec, dict):
                            rows_by_day.setdefault(day_str, []).append(rec)
                    except Exception:
                        continue

                # Step-by-step lookback: Day 0 (Today) -> Day 1 (Yesterday) -> Day 2 ... -> Day max_lookback_days
                for offset in range(max(0, int(max_lookback_days)) + 1):
                    candidate_day = (today_dt - timedelta(days=offset)).isoformat()
                    if candidate_day in rows_by_day and rows_by_day[candidate_day]:
                        return rows_by_day[candidate_day]
            finally:
                conn.close()
        except Exception:
            return []
    return []
