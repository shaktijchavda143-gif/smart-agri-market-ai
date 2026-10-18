"""Regression tests for Live Mandi fallback failures seen in Render logs.

Run from this folder with: python -m unittest test_mandi_regression.py
The stubs below are only for a minimal audit environment where optional AI
SDKs are not installed; production requirements provide the real SDKs.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import os
import sys
import time
import types
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

# Ensure tests use a non-production placeholder key and never make real upstream requests.
os.environ.setdefault("DATA_GOV_API_KEY", "not-a-real-test-key")
os.environ.setdefault("CEDA_API_KEY", "not-a-real-test-ceda-key")

# Allow the Mandi-only helpers to be tested in a thin local audit environment.
# Normal backend deployments have these installed from requirements.txt.
try:
    import openai  # noqa: F401
except ImportError:
    _openai = types.ModuleType("openai")
    _openai.OpenAI = type("OpenAI", (), {})
    sys.modules["openai"] = _openai
try:
    from google import genai  # noqa: F401
    from google.genai import types as _genai_types  # noqa: F401
except ImportError:
    _google = types.ModuleType("google")
    _google.__path__ = []
    _genai = types.ModuleType("google.genai")
    _genai.Client = type("Client", (), {})
    _genai_types_mod = types.ModuleType("google.genai.types")
    _google.genai = _genai
    _genai.types = _genai_types_mod
    sys.modules["google"] = _google
    sys.modules["google.genai"] = _genai
    sys.modules["google.genai.types"] = _genai_types_mod

import main  # noqa: E402


class _Response:
    def __init__(self, status_code: int, body, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text
        self.headers = {}

    def json(self):
        return self._body


class _AgmarknetClient:
    calls = []
    timeouts = []
    responses_by_date = {}
    status_by_date = {}
    responses_by_month = {}
    status_by_month = {}
    state_response = {"data": {"states": [{"id": 11, "name": "Gujarat"}]}}
    filters_response = {"status": "success", "data": {"cmdt_data": [
        {"cmdt_id": 10, "cmdt_name": "Groundnut"},
        {"cmdt_id": 15, "cmdt_name": "Cotton"},
        {"cmdt_id": 22, "cmdt_name": "Jeera"},
        {"cmdt_id": 23, "cmdt_name": "Castor Seed"},
        {"cmdt_id": 24, "cmdt_name": "Onion"},
    ]}}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, path, params=None, timeout=None):
        params = dict(params or {})
        self.calls.append((path, params))
        self.timeouts.append((path, timeout))
        if path == "/location/state":
            return _Response(200, self.state_response)
        if path == "/daily-price-arrival/filters":
            return _Response(200, self.filters_response)
        if path == "/prices-and-arrivals/date-wise/specific-commodity":
            month_key = (int(params.get("year", 0)), int(params.get("month", 0)))
            if month_key in self.status_by_month:
                simulated = self.status_by_month[month_key]
                if isinstance(simulated, tuple):
                    status, body, text = simulated
                    return _Response(status, body, text=text)
                return _Response(simulated, {"message": "simulated upstream rejection"}, text="simulated upstream rejection")
            return _Response(200, self.responses_by_month.get(month_key, {"markets": []}))
        if path == "/prices-and-arrivals/commodity-market/daily-report-state":
            report_date = params.get("date", "")
            if report_date in self.status_by_date:
                simulated = self.status_by_date[report_date]
                if isinstance(simulated, tuple):
                    status, body, text = simulated
                    return _Response(status, body, text=text)
                return _Response(simulated, {"message": "simulated upstream rejection"}, text="simulated upstream rejection")
            return _Response(200, self.responses_by_date.get(report_date, {"markets": []}))
        raise AssertionError(f"Unexpected AGMARKNET path: {path}")


def _agmarknet_month_body(entries):
    """Build a realistic date-wise response with explicit parent arrivalDate fields."""
    markets = {}
    for entry in entries:
        market = entry.get("market", "Rajkot APMC")
        group = markets.setdefault(market, {"marketName": market, "districtName": entry.get("district", "Rajkot"), "dates": []})
        if entry.get("date"):
            group["dates"].append({"arrivalDate": entry["date"], "data": [{
                "commodityName": entry.get("commodity", "Cotton"),
                "minPrice": entry.get("min", 5000), "modalPrice": entry.get("modal", 6000),
                "maxPrice": entry.get("max", 7000),
            }]})
        else:
            group.setdefault("data", []).append({
                "commodityName": entry.get("commodity", "Cotton"),
                "minPrice": entry.get("min", 5000), "modalPrice": entry.get("modal", 6000),
                "maxPrice": entry.get("max", 7000),
            })
    return {"markets": list(markets.values())}

class MandiRegressionTests(unittest.TestCase):
    def test_datewise_request_has_bounded_timeout_and_never_uses_daily_report_for_crop(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        month_key = (today.year, today.month)
        _AgmarknetClient.calls = []
        _AgmarknetClient.timeouts = []
        _AgmarknetClient.responses_by_month = {month_key: _agmarknet_month_body([
            {"market": "Rajkot APMC", "date": today.strftime("%d/%m/%Y"), "commodity": "Cotton"},
        ])}
        _AgmarknetClient.status_by_month = {}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["cotton"] = (15, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Cotton", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(error, "")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["report_date"], today.isoformat())
            source_calls = [(path, params) for path, params in _AgmarknetClient.calls
                            if path.startswith("/prices-and-arrivals/")]
            self.assertEqual(len(source_calls), 1)
            self.assertEqual(source_calls[0][0], "/prices-and-arrivals/date-wise/specific-commodity")
            self.assertEqual(source_calls[0][1]["year"], str(today.year))
            self.assertEqual(source_calls[0][1]["month"], str(today.month))
            self.assertFalse(any(path == "/prices-and-arrivals/commodity-market/daily-report-state"
                                 for path, _ in _AgmarknetClient.calls))
            timeouts = [timeout for path, timeout in _AgmarknetClient.timeouts
                        if path == "/prices-and-arrivals/date-wise/specific-commodity"]
            self.assertEqual(len(timeouts), 1)
            self.assertLessEqual(float(timeouts[0]), main.MANDI_AGMARKNET_DAILY_TIMEOUT_SECONDS)
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_datewise_http_400_short_circuits_invalid_endpoint_call(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        _AgmarknetClient.calls = []
        _AgmarknetClient.status_by_month = {(today.year, today.month): 400}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["cotton"] = (15, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Cotton", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(rows, [])
            self.assertIn("HTTP 400", error)
            month_calls = [params for path, params in _AgmarknetClient.calls
                           if path == "/prices-and-arrivals/date-wise/specific-commodity"]
            self.assertEqual(len(month_calls), 1)
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)
            _AgmarknetClient.status_by_month = {}

    def test_cached_ceda_dict_resolves_as_one_candidate(self):
        for name, commodity_id in (("Groundnut", 99), ("Cotton", 15)):
            with self.subTest(commodity=name):
                cached_row = {"commodity_name": name, "commodity_id": commodity_id}
                rows = main._ceda_metadata_rows(cached_row)
                matches = main._ceda_find_commodity_matches(rows, name)
                self.assertEqual(len(rows), 1)
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["commodity_name"], name)

    def test_today_is_selected_and_monthly_average_is_never_returned(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        yesterday = today - timedelta(days=1)
        _AgmarknetClient.calls = []
        _AgmarknetClient.responses_by_month = {(today.year, today.month): _agmarknet_month_body([
            {"market": "Rajkot APMC", "date": yesterday.strftime("%d/%m/%Y"), "commodity": "Cotton", "min": 4900, "modal": 5900, "max": 6900},
            {"market": "Rajkot APMC", "date": today.strftime("%d/%m/%Y"), "commodity": "Cotton", "min": 5000, "modal": 6000, "max": 7000},
        ])}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["cotton"] = (15, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "કપાસ", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(error, "")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["report_date"], today.isoformat())
            self.assertEqual(rows[0]["modal_price"], 6000.0)
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_if_today_missing_yesterday_is_returned(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        yesterday = today - timedelta(days=1)
        two_days = today - timedelta(days=2)
        _AgmarknetClient.calls = []
        _AgmarknetClient.responses_by_month = {(today.year, today.month): _agmarknet_month_body([
            {"market": "Gondal APMC", "date": two_days.strftime("%d/%m/%Y"), "commodity": "Cotton", "min": 4700, "modal": 5700, "max": 6700},
            {"market": "Gondal APMC", "date": yesterday.strftime("%d/%m/%Y"), "commodity": "Cotton", "min": 4800, "modal": 5800, "max": 6800},
        ])}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["cotton"] = (15, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Cotton", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(error, "")
            self.assertEqual({row["report_date"] for row in rows}, {yesterday.isoformat()})
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_three_days_old_is_included_but_only_if_no_newer_date_exists(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        fallback_day = today - timedelta(days=3)
        _AgmarknetClient.calls = []
        _AgmarknetClient.responses_by_month = {(today.year, today.month): _agmarknet_month_body([
            {"market": "Rajkot APMC", "date": fallback_day.strftime("%d/%m/%Y"), "commodity": "Groundnut", "min": 1000, "modal": 1200, "max": 1400},
        ])}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["groundnut"] = (10, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Groundnut", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(error, "")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["report_date"], fallback_day.isoformat())
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_future_and_four_days_old_prices_are_rejected(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        future = today + timedelta(days=1)
        stale = today - timedelta(days=4)
        _AgmarknetClient.responses_by_month = {(today.year, today.month): _agmarknet_month_body([
            {"market": "Rajkot APMC", "date": future.strftime("%d/%m/%Y"), "commodity": "Cotton"},
            {"market": "Rajkot APMC", "date": stale.strftime("%d/%m/%Y"), "commodity": "Cotton"},
        ])}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["cotton"] = (15, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Cotton", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(rows, [])
            self.assertIn("no fresh date-stamped records", error)
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_undated_rows_are_not_promoted_to_current_date(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        _AgmarknetClient.responses_by_month = {(today.year, today.month): _agmarknet_month_body([
            {"market": "Rajkot APMC", "date": None, "commodity": "Cotton"},
        ])}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["cotton"] = (15, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Cotton", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(rows, [])
            self.assertIn("no fresh date-stamped records", error)
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_selected_market_filters_newer_other_market_and_falls_back_one_day(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        yesterday = today - timedelta(days=1)
        _AgmarknetClient.responses_by_month = {(today.year, today.month): _agmarknet_month_body([
            {"market": "Rajkot APMC", "date": today.strftime("%d/%m/%Y"), "commodity": "Groundnut", "min": 5000, "modal": 6000, "max": 7000},
            {"market": "Kodinar APMC", "date": yesterday.strftime("%d/%m/%Y"), "commodity": "Groundnut", "min": 5100, "modal": 6100, "max": 7100},
        ])}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["groundnut"] = (10, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "Kodinar APMC", "Groundnut", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(error, "")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["market"], "Kodinar APMC")
            self.assertEqual(rows[0]["report_date"], yesterday.isoformat())
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_government_fallback_rejects_rows_outside_three_day_window_and_keeps_latest_date(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        yesterday = today - timedelta(days=1)
        old_day = today - timedelta(days=4)
        result = main._mandi_normalized_result({"records": [
            {"commodity": "Cotton", "arrival_date": old_day.strftime("%d/%m/%Y"), "market": "Old", "min_price": 1000, "modal_price": 1200, "max_price": 1400, "source": "test", "source_url": "https://example.test"},
            {"commodity": "Cotton", "arrival_date": yesterday.strftime("%d/%m/%Y"), "market": "Fresh", "min_price": 1000, "modal_price": 1200, "max_price": 1400, "source": "test", "source_url": "https://example.test"},
            {"commodity": "Cotton", "arrival_date": today.strftime("%d/%m/%Y"), "market": "Today", "min_price": 1100, "modal_price": 1300, "max_price": 1500, "source": "test", "source_url": "https://example.test"},
        ]}, "Cotton")
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["market"], "Today")
        self.assertEqual(result["_diagnostics"]["latest_date"], today.strftime("%d-%m-%Y"))
        self.assertEqual(result["_diagnostics"]["rejected_undated_or_outside_lookback"], 1)

    def test_ceda_warm_cache_reaches_fresh_price_endpoint(self):
        now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
        today_iso = now.strftime("%Y-%m-%d")
        price_calls = []

        class _CedaClient:
            def __init__(self, *args, **kwargs):
                self.base_url = str(kwargs.get("base_url", ""))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, path, params=None, timeout=None):
                raise AssertionError(f"Unexpected GET on warm-cache test: {self.base_url}{path}")

            async def post(self, path, json=None, timeout=None):
                price_calls.append((self.base_url, path, json or {}))
                return _Response(200, {"data": [{
                    "date": today_iso,
                    "min_price": 1000,
                    "modal_price": 1100,
                    "max_price": 1200,
                    "district": "Rajkot",
                    "market": "Rajkot",
                }]})

        old_client = main.httpx.AsyncClient
        old_key = main.CEDA_API_KEY
        old_commodity = main._ceda_commodity_cache.get("cotton")
        old_geo = main._ceda_geography_cache
        main.httpx.AsyncClient = _CedaClient
        main.CEDA_API_KEY = "mock-key"
        main._ceda_commodity_cache["cotton"] = (
            {"commodity_name": "Cotton", "commodity_id": 15}, time.monotonic()
        )
        main._ceda_geography_cache = ([{
            "census_state_name": "Gujarat",
            "census_state_id": 24,
            "census_district_id": 99,
            "census_district_name": "Rajkot",
        }], time.monotonic())
        try:
            log = io.StringIO()
            with contextlib.redirect_stdout(log):
                rows, error = asyncio.run(main._fetch_ceda_fresh_mandi("Gujarat", "", "કપાસ"))
            self.assertEqual(error, "")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["commodity"], "Cotton")
            self.assertEqual(rows[0]["arrival_date"], now.strftime("%d/%m/%Y"))
            self.assertEqual(rows[0]["modal_price"], 1100.0)
            self.assertTrue(any(path == "/prices" for _, path, _ in price_calls))
            self.assertIn("ceda_commodity_resolved commodity='Cotton'", log.getvalue())
            self.assertNotIn("ceda_commodity_resolution_failed", log.getvalue())
        finally:
            main.httpx.AsyncClient = old_client
            main.CEDA_API_KEY = old_key
            if old_commodity is None:
                main._ceda_commodity_cache.pop("cotton", None)
            else:
                main._ceda_commodity_cache["cotton"] = old_commodity
            main._ceda_geography_cache = old_geo

    def test_mandi_falls_back_to_ceda_after_primary_and_secondary_fail_and_returns_only_newest_date(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        yesterday = today - timedelta(days=1)
        primary_calls = []
        ceda_calls = []
        data_gov_calls = []

        async def no_agmarknet(state, market, commodity, request_deadline=None):
            primary_calls.append((state, market, commodity))
            return [], "simulated_daily_reports_empty"

        async def ceda_rows(state, district, commodity):
            ceda_calls.append((state, district, commodity))
            # Intentionally unordered and mixed dates: route must keep all
            # rows from the newest available date only, never blend dates.
            return [
                {"state": "Gujarat", "district": "Rajkot", "market": "Gondal",
                 "commodity": "Groundnut", "arrival_date": yesterday.strftime("%d/%m/%Y"),
                 "min_price": 5000, "modal_price": 5500, "max_price": 6000,
                 "source": "CEDA Agmarknet API", "source_url": "https://api.ceda.ashoka.edu.in/"},
                {"state": "Gujarat", "district": "Rajkot", "market": "Rajkot",
                 "commodity": "Groundnut", "arrival_date": today.strftime("%d/%m/%Y"),
                 "min_price": 5100, "modal_price": 5600, "max_price": 6100,
                 "source": "CEDA Agmarknet API", "source_url": "https://api.ceda.ashoka.edu.in/"},
                {"state": "Gujarat", "district": "Amreli", "market": "Amreli",
                 "commodity": "Groundnut", "arrival_date": today.strftime("%d/%m/%Y"),
                 "min_price": 5200, "modal_price": 5700, "max_price": 6200,
                 "source": "CEDA Agmarknet API", "source_url": "https://api.ceda.ashoka.edu.in/"},
            ], ""

        def empty_data_gov(*args, **kwargs):
            # Production source order is data.gov.in -> AGMARKNET 2.0 -> CEDA.
            # Simulate an unusable primary response so the test reaches the CEDA fallback.
            data_gov_calls.append((args, kwargs))
            return {"records": [], "_diagnostics": {"http_status": 200, "raw_record_count": 0}}, "", 0, 200

        old_primary = main._fetch_agmarknet_2_live
        old_ceda = main._fetch_ceda_fresh_mandi
        old_data_gov = main._mandi_api_get
        old_pool = main._mandi_shared_pool
        old_load_pool = main._load_mandi_shared_pool
        old_save_pool = main._save_mandi_shared_pool
        try:
            # Isolate this test from developer /tmp cache and prior tests.
            main._mandi_shared_pool = {}
            main._load_mandi_shared_pool = lambda: None
            main._save_mandi_shared_pool = lambda: None
            main._fetch_agmarknet_2_live = no_agmarknet
            main._fetch_ceda_fresh_mandi = ceda_rows
            main._mandi_api_get = empty_data_gov
            result = main.mandi(
                state="Gujarat", market="", commodity="મગફળી",
                request_deadline=time.monotonic() + 25,
            )
            self.assertTrue(result["live_available"])
            self.assertEqual(result["source"], "ceda_agmarknet_fallback")
            self.assertEqual(len(primary_calls), 1)
            self.assertEqual(len(ceda_calls), 1)
            self.assertEqual(len(data_gov_calls), 1)
            self.assertEqual({row["arrival_date"] for row in result["records"]}, {today.strftime("%d/%m/%Y")})
            self.assertEqual({row["market"] for row in result["records"]}, {"Rajkot", "Amreli"})
        finally:
            main._fetch_agmarknet_2_live = old_primary
            main._fetch_ceda_fresh_mandi = old_ceda
            main._mandi_api_get = old_data_gov
            main._mandi_shared_pool = old_pool
            main._load_mandi_shared_pool = old_load_pool
            main._save_mandi_shared_pool = old_save_pool

    def test_datewise_captcha_failure_opens_endpoint_scoped_circuit(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        old_client = main.httpx.AsyncClient
        old_datewise_until = main._agmarknet_datewise_captcha_required_until
        old_daily_until = main._agmarknet_captcha_required_until
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        _AgmarknetClient.calls = []
        _AgmarknetClient.status_by_month = {
            (today.year, today.month): (400,
                {"detail": "Captcha key and captcha value are required.", "code": "TOKEN_OR_CAPTCHA_REQUIRED"},
                '{"detail":"Captcha key and captcha value are required.","code":"TOKEN_OR_CAPTCHA_REQUIRED"}')
        }
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["groundnut"] = (10, time.monotonic())
        main._agmarknet_datewise_captcha_required_until = 0.0
        main._agmarknet_captcha_required_until = 0.0
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Groundnut", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(rows, [])
            self.assertIn("TOKEN_OR_CAPTCHA_REQUIRED", error)
            monthly_calls = [params for path, params in _AgmarknetClient.calls
                             if path == "/prices-and-arrivals/date-wise/specific-commodity"]
            self.assertEqual(len(monthly_calls), 1)
            self.assertGreater(main._agmarknet_datewise_captcha_required_until, time.monotonic())
            class _ForbiddenClient:
                def __init__(self, *args, **kwargs):
                    raise AssertionError("CAPTCHA circuit must suppress repeated date-wise API requests")
            main.httpx.AsyncClient = _ForbiddenClient
            rows2, error2 = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Cotton", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(rows2, [])
            self.assertIn("CAPTCHA required", error2)
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_datewise_captcha_required_until = old_datewise_until
            main._agmarknet_captcha_required_until = old_daily_until
            _AgmarknetClient.status_by_month = {}
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_ceda_retry_after_opens_circuit_for_full_provider_cooldown(self):
        old_until = main._ceda_rate_limit_until
        old_seconds = main._ceda_rate_limit_seconds
        old_source = main._ceda_rate_limit_source
        try:
            seconds = main._ceda_retry_after_seconds("331283")
            self.assertEqual(seconds, 331283)
            applied = main._ceda_note_rate_limit("331283", "test:/prices")
            self.assertEqual(applied, 331283)
            self.assertGreaterEqual(main._ceda_circuit_remaining(), 331280)
            self.assertEqual(main._ceda_rate_limit_source, "test:/prices")
        finally:
            main._ceda_rate_limit_until = old_until
            main._ceda_rate_limit_seconds = old_seconds
            main._ceda_rate_limit_source = old_source

    def test_ceda_http_429_skips_authenticated_retry_and_queued_districts(self):
        old_client = main.httpx.AsyncClient
        old_key = main.CEDA_API_KEY
        old_commodity = main._ceda_commodity_cache.get("cotton")
        old_geo = main._ceda_geography_cache
        old_until = main._ceda_rate_limit_until
        old_seconds = main._ceda_rate_limit_seconds
        old_source = main._ceda_rate_limit_source
        public_price_calls = []
        authenticated_price_calls = []
        class _CedaResponse:
            def __init__(self, status, headers=None, body=None):
                self.status_code = status
                self.headers = headers or {}
                self._body = body or {}
                self.text = "rate limited"
            def json(self):
                return self._body
        class _Ceda429Client:
            def __init__(self, *args, **kwargs):
                self.base_url = str(kwargs.get("base_url", ""))
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, path, params=None, timeout=None):
                raise AssertionError(f"Expected warmed metadata cache, got {self.base_url}{path}")
            async def post(self, path, json=None, timeout=None):
                public_price_calls.append((self.base_url, path))
                return _CedaResponse(429, {"Retry-After": "3600"})
            async def request(self, method, path, json=None):
                authenticated_price_calls.append((method, path))
                raise AssertionError("Do not retry authenticated CEDA API after public HTTP 429")
        main.httpx.AsyncClient = _Ceda429Client
        main.CEDA_API_KEY = "mock-key"
        main._ceda_commodity_cache["cotton"] = ({"commodity_name": "Cotton", "commodity_id": 15}, time.monotonic())
        main._ceda_geography_cache = ([{
            "census_state_name": "Gujarat", "census_state_id": 24,
            "census_district_id": i, "census_district_name": f"District {i}"
        } for i in range(1, 18)], time.monotonic())
        main._ceda_rate_limit_until = 0.0
        main._ceda_rate_limit_seconds = 0
        main._ceda_rate_limit_source = ""
        try:
            rows, error = asyncio.run(main._fetch_ceda_fresh_mandi("Gujarat", "", "કપાસ"))
            self.assertEqual(rows, [])
            self.assertIn("no fresh records", error.lower())
            self.assertGreaterEqual(main._ceda_circuit_remaining(), 3598)
            self.assertGreaterEqual(len(public_price_calls), 1)
            self.assertLessEqual(len(public_price_calls), 5,
                                 "one wave of max five in-flight checks; queued districts should observe circuit")
            self.assertEqual(authenticated_price_calls, [], "A 429 must not be followed by per-district CEDA retries")
        finally:
            main.httpx.AsyncClient = old_client
            main.CEDA_API_KEY = old_key
            if old_commodity is None:
                main._ceda_commodity_cache.pop("cotton", None)
            else:
                main._ceda_commodity_cache["cotton"] = old_commodity
            main._ceda_geography_cache = old_geo
            main._ceda_rate_limit_until = old_until
            main._ceda_rate_limit_seconds = old_seconds
            main._ceda_rate_limit_source = old_source

    def test_ceda_circuit_skips_followup_requests_during_retry_after(self):
        old_until = main._ceda_rate_limit_until
        old_seconds = main._ceda_rate_limit_seconds
        old_source = main._ceda_rate_limit_source
        old_key = main.CEDA_API_KEY
        old_client = main.httpx.AsyncClient
        class _ForbiddenClient:
            def __init__(self, *args, **kwargs):
                raise AssertionError("CEDA must not be called while Retry-After circuit is open")
        try:
            main.CEDA_API_KEY = "mock-key"
            main._ceda_rate_limit_until = time.monotonic() + 3600
            main._ceda_rate_limit_seconds = 3600
            main._ceda_rate_limit_source = "test"
            main.httpx.AsyncClient = _ForbiddenClient
            rows, error = asyncio.run(main._fetch_ceda_fresh_mandi("Gujarat", "", "કપાસ"))
            self.assertEqual(rows, [])
            self.assertIn("rate limited", error.lower())
        finally:
            main.CEDA_API_KEY = old_key
            main.httpx.AsyncClient = old_client
            main._ceda_rate_limit_until = old_until
            main._ceda_rate_limit_seconds = old_seconds
            main._ceda_rate_limit_source = old_source

    def test_market_master_parses_actual_agmarknet_mkt_name_field(self):
        old_client = main.httpx.AsyncClient
        class _MarketResponse:
            def __init__(self, body):
                self.status_code = 200
                self._body = body
                self.headers = {}
                self.text = ""
            def json(self):
                return self._body
        class _MarketClient:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, path, params=None):
                if path == "/location/state":
                    return _MarketResponse({"data": {"states": [{"id": 11, "name": "Gujarat"}]}})
                if path == "/daily-price-arrival/filters":
                    return _MarketResponse({"status": "success", "data": {
                        "state_data": [{"state_id": 11, "state_name": "Gujarat"}],
                        "district_data": [{"id": 33, "state_id": 11, "district_name": "Rajkot"}],
                        "market_data": [{"id": 4176, "mkt_name": "Rajkot APMC", "state_id": 11, "district_id": 33}],
                    }})
                raise AssertionError(f"Unexpected market-master endpoint: {path}")
        main.httpx.AsyncClient = _MarketClient
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = main.mandi_markets(state="Gujarat", commodity="ALL")
            self.assertEqual(result["count"], 1)
            self.assertIn("Rajkot APMC", result["markets"])
            self.assertTrue(result["ok"])
        finally:
            main.httpx.AsyncClient = old_client

    def test_crop_fetch_does_not_call_captcha_prone_daily_report_endpoint(self):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        _AgmarknetClient.calls = []
        _AgmarknetClient.responses_by_month = {(today.year, today.month): _agmarknet_month_body([
            {"market": "Rajkot APMC", "date": today.strftime("%d/%m/%Y"), "commodity": "Cotton"},
        ])}
        old_client = main.httpx.AsyncClient
        old_state_cache = dict(main._agmarknet_state_cache)
        old_commodity_cache = dict(main._agmarknet_commodity_cache)
        main.httpx.AsyncClient = _AgmarknetClient
        main._agmarknet_state_cache["gujarat"] = (11, time.monotonic())
        main._agmarknet_commodity_cache["cotton"] = (15, time.monotonic())
        try:
            rows, error = asyncio.run(main._fetch_agmarknet_2_live(
                "Gujarat", "", "Cotton", request_deadline=time.monotonic() + 20
            ))
            self.assertEqual(error, "")
            self.assertTrue(rows)
            paths = [path for path, _ in _AgmarknetClient.calls]
            self.assertIn("/prices-and-arrivals/date-wise/specific-commodity", paths)
            self.assertNotIn("/prices-and-arrivals/commodity-market/daily-report-state", paths)
        finally:
            main.httpx.AsyncClient = old_client
            main._agmarknet_state_cache.clear(); main._agmarknet_state_cache.update(old_state_cache)
            main._agmarknet_commodity_cache.clear(); main._agmarknet_commodity_cache.update(old_commodity_cache)

    def test_connection_refused_does_not_repeat_same_official_request(self):
        old_key = main.MANDI_API_KEY
        old_urlopen = main.urllib.request.urlopen
        calls = {"count": 0}

        def refused(*args, **kwargs):
            calls["count"] += 1
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

        main.MANDI_API_KEY = "not-a-real-test-key"
        main.urllib.request.urlopen = refused
        try:
            result = main._mandi_api_get("Gujarat", "", "કપાસ")
            self.assertIsNone(result[0])
            self.assertEqual(result[3], 0)
            self.assertEqual(calls["count"], 1)
        finally:
            main.MANDI_API_KEY = old_key
            main.urllib.request.urlopen = old_urlopen



    def test_mandi_crops_catalogue_returns_all_51_gujarat_crops(self):
        body = main.mandi_crops_catalogue()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("count"), 51)
        crops = body.get("crops") or []
        gu_names = {c.get("crop_gu") for c in crops}
        for expected in ["મગફળી", "કપાસ", "જીરું", "એરંડા", "ડુંગળી", "ઘઉં", "તલ", "ચણા", "રાઈ (સરસવ)", "વરિયાળી", "ઈસબગુલ", "હળદર"]:
            self.assertIn(expected, gu_names)

    def test_mandi_markets_match_handles_gujarati_and_subyards(self):
        self.assertTrue(main._mandi_markets_match("Rajkot", "રાજકોટ યાર્ડ"))
        self.assertTrue(main._mandi_markets_match("Rajkot(Ghee Peeth)", "રાજકોટ"))
        self.assertTrue(main._mandi_markets_match("Gondal APMC", "ગોંડલ"))
        self.assertTrue(main._mandi_markets_match("Unjha", "ઊંઝા"))
        self.assertTrue(main._mandi_markets_match("Unjha", "ઉંઝા"))
        self.assertFalse(main._mandi_markets_match("Junagadh", "રાજકોટ"))

    def test_ceda_fallback_is_not_skipped_when_exact_market_requested(self):
        from unittest import mock
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        ceda_calls = []

        async def no_agmarknet(state, market, commodity, request_deadline=None):
            return [], "simulated_captcha_required"

        async def ceda_rows(state, district, commodity):
            ceda_calls.append((state, district, commodity))
            return [
                {"state": "Gujarat", "district": "Rajkot", "market": "Rajkot(Ghee Peeth)",
                 "commodity": "Groundnut", "arrival_date": today.strftime("%d/%m/%Y"),
                 "min_price": 5100, "modal_price": 5600, "max_price": 6100,
                 "source": "CEDA Agmarknet API", "source_url": "https://api.ceda.ashoka.edu.in/"},
                {"state": "Gujarat", "district": "Rajkot", "market": "Gondal",
                 "commodity": "Groundnut", "arrival_date": today.strftime("%d/%m/%Y"),
                 "min_price": 5000, "modal_price": 5500, "max_price": 6000,
                 "source": "CEDA Agmarknet API", "source_url": "https://api.ceda.ashoka.edu.in/"},
            ], ""

        def empty_data_gov(*args, **kwargs):
            return {"records": [], "_diagnostics": {"http_status": 200, "raw_record_count": 0}}, "", 0, 200

        with mock.patch.object(main, "_mandi_api_get", side_effect=empty_data_gov), \
             mock.patch.object(main, "_fetch_agmarknet_2_live", side_effect=no_agmarknet), \
             mock.patch.object(main, "_fetch_ceda_fresh_mandi", side_effect=ceda_rows), \
             mock.patch.object(main, "_mandi_shared_pool", {}), \
             mock.patch.object(main, "_load_mandi_shared_pool", lambda: None), \
             mock.patch.object(main, "_save_mandi_shared_pool", lambda: None):
            body = main.mandi(state="Gujarat", market="રાજકોટ", commodity="મગફળી")
        self.assertTrue(body["ok"])
        self.assertTrue(body["live_available"])
        self.assertFalse(body.get("is_cached_data", False))
        self.assertEqual(body["source"], "ceda_agmarknet_fallback")
        self.assertTrue(len(ceda_calls) >= 1)
        self.assertEqual(ceda_calls[0][1], "Rajkot")
        self.assertEqual(len(body["records"]), 1)
        self.assertIn("Rajkot", body["records"][0]["market"])

    def test_admin_mandi_diagnostics_requires_auth_and_hides_api_keys(self):
        import json
        from unittest import mock
        class DummyReq:
            headers = {}
            cookies = {}
            client = types.SimpleNamespace(host="127.0.0.1")
            url = types.SimpleNamespace(path="/api/v1/admin/mandi-diagnostics", scheme="https")

        with mock.patch.object(main, "_require_admin", return_value={"username": "admin", "role": "SUPER_ADMIN"}), \
             mock.patch.object(main, "MANDI_API_KEY", "SUPER_SECRET_DATA_GOV_KEY_999"), \
             mock.patch.object(main, "CEDA_API_KEY", "SUPER_SECRET_CEDA_KEY_888"):
            resp = asyncio.run(main.api_admin_mandi_diagnostics(DummyReq(), probe_live=False))
        raw_text = json.dumps(resp)
        self.assertNotIn("SUPER_SECRET_DATA_GOV_KEY_999", raw_text)
        self.assertNotIn("SUPER_SECRET_CEDA_KEY_888", raw_text)
        self.assertTrue(resp["ok"])
        self.assertIn("data.gov.in", resp["providers"])
        self.assertIn("agmarknet_2_public", resp["providers"])
        self.assertIn("ceda_agmarknet_fallback", resp["providers"])
        self.assertTrue(resp["providers"]["data.gov.in"]["api_key_present"])


if __name__ == "__main__":
    unittest.main()
