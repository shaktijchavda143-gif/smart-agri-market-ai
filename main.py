# -*- coding: utf-8 -*-
"""
Smart Agri-Market AI Backend
Version 10

FastAPI backend for:
- Groq Text AI
- Gemini Vision AI
- Rule Based Crop Agent
- Weather News
- Agriculture News
- Market News
- Optional Live APMC / Mandi data

Render Deploy Ready
Android API Compatible
"""

import os
import base64
import importlib.util
import html
import re
import time
import json
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from google import genai
from google.genai import types


# ============================================================
# APPLICATION
# ============================================================

APP_VERSION = "10.0 Android API Bridge"

app = FastAPI(
    title="Smart Agri Market AI Backend",
    version=APP_VERSION,
    description="Smart Agri-Market AI backend for Android farmers app.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# MODEL CONFIGURATION
# ============================================================

GROQ_MODEL = (
    os.getenv(
        "GROQ_MODEL",
        "openai/gpt-oss-20b",
    ).strip()
    or "openai/gpt-oss-20b"
)

VISION_MODEL = (
    os.getenv(
        "VISION_MODEL",
        "gemini-2.5-flash",
    ).strip()
    or "gemini-2.5-flash"
)


# ============================================================
# COMMON CONFIGURATION
# ============================================================

NEWS_TIMEOUT = max(
    3,
    int(os.getenv("NEWS_TIMEOUT", "8")),
)

NEWS_RETRIES = max(
    0,
    min(
        int(os.getenv("NEWS_RETRIES", "1")),
        3,
    ),
)

NEWS_MAX_AGE_HOURS = 48

NEWS_USER_AGENT = (
    "Mozilla/5.0 "
    "(Linux; Android 15) "
    "SmartAgriMarketAI/10.0"
)


# ============================================================
# OPTIONAL LIVE APMC CONFIGURATION
#
# Existing Android app remains compatible because these are
# optional. If configured, market/news will attempt live data.
# ============================================================

MANDI_API_URL = os.getenv(
    "MANDI_API_URL",
    "",
).strip()

MANDI_API_KEY = os.getenv(
    "MANDI_API_KEY",
    "",
).strip()


# ============================================================
# LOAD SUPPLIED SMART AGRI AGENT
# ============================================================

_agent = None

try:
    _agent_path = os.path.join(
        os.path.dirname(__file__),
        "smart_agri_agent.py",
    )

    _spec = importlib.util.spec_from_file_location(
        "smart_agri_agent",
        _agent_path,
    )

    if _spec and _spec.loader:
        _agent = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_agent)

except Exception as exc:
    _agent = None
    print(f"Agent import warning: {exc}")


# ============================================================
# SYSTEM INSTRUCTION
# ============================================================

SYSTEM = (
    "તમે Smart Agri-Market AI ગુજરાતી ખેડૂત સહાયક છો. "
    "જવાબ સરળ, વ્યવહારુ અને ખેડૂતના સંદર્ભ મુજબ આપો. "
    "પાક, સિંચાઈ, પોષણ, રોગ-જીવાત, હવામાન અને બજાર અંગે "
    "માર્ગદર્શન આપો. "
    "ચોક્કસ pesticide dose અથવા નિશ્ચિત રોગનિદાન માટે "
    "સ્થાનિક કૃષિ નિષ્ણાત, KVK અથવા લેબ ચકાસણી જરૂરી "
    "હોવાનું જણાવો."
)


# ============================================================
# REQUEST MODEL
# ============================================================

class Ask(BaseModel):
    question: str
    context: dict | None = None


# ============================================================
# BASIC UTILITIES
# ============================================================

def now_local_string() -> str:
    return datetime.now().astimezone().strftime(
        "%d-%m-%Y %H:%M"
    )


def norm(text: str) -> str:
    return " ".join(
        (text or "")
        .strip()
        .lower()
        .replace("-", " ")
        .split()
    )


def clean_html(value: str) -> str:
    """
    Remove HTML tags/entities and normalize whitespace.
    """
    text = html.unescape(
        re.sub(
            r"<[^>]+>",
            " ",
            value or "",
        )
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


# ============================================================
# RSS DATE UTILITIES
# ============================================================

def parse_rss_datetime(value: str) -> Optional[datetime]:
    """
    Convert common RSS dates into timezone-aware UTC datetime.
    """
    if not value:
        return None

    value = value.strip()

    try:
        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc,
            )

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

    # ISO 8601 fallback
    try:
        iso_value = value.replace(
            "Z",
            "+00:00",
        )

        dt = datetime.fromisoformat(
            iso_value,
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc,
            )

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def rss_datetime(value: str) -> str:
    """
    Public-format RSS datetime.
    """
    dt = parse_rss_datetime(value)

    if dt is None:
        return "સમય ઉપલબ્ધ નથી"

    return dt.astimezone().strftime(
        "%d-%m-%Y %H:%M"
    )


# ============================================================
# NEWS FILTERING
# ============================================================

def filter_last_48_hours(
    items: list[dict[str, Any]],
    hours: int = NEWS_MAX_AGE_HOURS,
) -> list[dict[str, Any]]:
    """
    Keep only news published during the requested period.

    Items without a valid publication datetime are excluded.
    This is intentional so old/unknown-date news cannot enter
    the fresh-news feed.
    """
    cutoff = datetime.now(
        timezone.utc
    ) - timedelta(
        hours=hours,
    )

    result = []

    for item in items:
        published_dt = item.get("_published_dt")

        if not isinstance(
            published_dt,
            datetime,
        ):
            continue

        if published_dt >= cutoff:
            result.append(item)

    return result


def remove_duplicates(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Remove duplicate news by:
    - link
    - headline
    - category + headline
    """

    seen_links: set[str] = set()
    seen_headlines: set[str] = set()
    seen_category_headlines: set[str] = set()

    result = []

    for item in items:
        link = norm(
            str(item.get("url", "")),
        )

        headline = norm(
            str(item.get("headline", "")),
        )

        category = norm(
            str(item.get("category", "")),
        )

        category_headline = (
            f"{category}|{headline}"
        )

        if link and link in seen_links:
            continue

        if headline and headline in seen_headlines:
            continue

        if (
            category_headline
            and category_headline
            in seen_category_headlines
        ):
            continue

        if link:
            seen_links.add(link)

        if headline:
            seen_headlines.add(headline)

        seen_category_headlines.add(
            category_headline,
        )

        result.append(item)

    return result


def sort_latest(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Sort newest first.
    """
    return sorted(
        items,
        key=lambda item: item.get(
            "_published_dt",
            datetime.min.replace(
                tzinfo=timezone.utc,
            ),
        ),
        reverse=True,
    )


def _public_news_item(
    item: dict[str, Any],
) -> dict[str, Any]:
    """
    Remove internal fields before returning JSON.
    """
    return {
        key: value
        for key, value in item.items()
        if not key.startswith("_")
    }


# ============================================================
# GOOGLE NEWS RSS ENGINE
# ============================================================

def _google_news_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode(
            {
                "q": query,
                "hl": "gu",
                "gl": "IN",
                "ceid": "IN:gu",
            }
        )
    )


def _fetch_url(
    url: str,
    timeout: int = NEWS_TIMEOUT,
    retries: int = NEWS_RETRIES,
) -> bytes:
    """
    Small dependency-free HTTP helper with retry.
    """

    last_error: Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": NEWS_USER_AGENT,
                    "Accept": (
                        "application/rss+xml, "
                        "application/xml, text/xml, */*"
                    ),
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                return response.read()

        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            OSError,
        ) as exc:

            last_error = exc

            if attempt < retries:
                time.sleep(
                    0.35 * (attempt + 1)
                )

    raise RuntimeError(
        f"RSS request failed: {last_error}"
    )


def fetch_google_news(
    category: str,
    query: str,
    fallback_source: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Common Google News RSS engine.

    Used by:
    - Weather
    - Agriculture
    - Market

    Only valid RSS publication dates are retained.
    """

    url = _google_news_url(query)

    raw = _fetch_url(url)

    try:
        root = ET.fromstring(raw)

    except ET.ParseError as exc:
        raise RuntimeError(
            f"Invalid RSS XML: {exc}"
        ) from exc

    items: list[dict[str, Any]] = []

    rss_items = root.findall(
        "./channel/item"
    )

    for item in rss_items[:limit]:

        title = clean_html(
            item.findtext(
                "title",
                "",
            )
        )

        link = (
            item.findtext(
                "link",
                "",
            )
            or ""
        ).strip()

        description = clean_html(
            item.findtext(
                "description",
                "",
            )
        )

        pub_raw = (
            item.findtext(
                "pubDate",
                "",
            )
            or ""
        ).strip()

        published_dt = parse_rss_datetime(
            pub_raw,
        )

        if not title or not link:
            continue

        # Do not return news with unknown date.
        if published_dt is None:
            continue

        source_el = item.find("source")

        source = ""

        if source_el is not None:
            source = clean_html(
                source_el.text or ""
            )

        source = (
            source
            or fallback_source
        )

        summary = description

        if (
            not summary
            or norm(summary) == norm(title)
        ):
            summary = (
                f"{source} તરફથી "
                "સંબંધિત તાજો અહેવાલ."
            )

        if len(summary) > 400:
            summary = (
                summary[:397]
                .rsplit(" ", 1)[0]
                + "..."
            )

        items.append(
            {
                "category": category,
                "headline": title,
                "summary": summary,
                "published": published_dt.astimezone().strftime(
                    "%d-%m-%Y %H:%M"
                ),
                "source": source,
                "url": link,
                "_published_dt": published_dt,
            }
        )

    return items


# ============================================================
# WEATHER NEWS
# ============================================================

WEATHER_FEEDS = [
    (
        "🌧️ IMD Gujarat",
        "IMD Gujarat weather",
        "IMD Gujarat",
    ),
    (
        "☀️ Ambalal Patel",
        "આંબાલાલ પટેલ હવામાન ગુજરાત",
        "આંબાલાલ પટેલ",
    ),
    (
        "🌦️ Paresh Goswami",
        "પરેશ ગૌસ્વામી હવામાન ગુજરાત",
        "પરેશ ગૌસ્વામી",
    ),
    (
        "📰 Gujarat Weather",
        "ગુજરાત હવામાન વરસાદ આગાહી",
        "ગુજરાત હવામાન સમાચાર",
    ),
]


@app.get("/api/v1/weather/news")
def weather_news():
    """
    Fresh Gujarat weather news.

    Only last 48 hours.
    """

    items: list[dict[str, Any]] = []
    errors: list[str] = []

    for category, query, fallback in WEATHER_FEEDS:

        try:
            feed_items = fetch_google_news(
                category=category,
                query=query,
                fallback_source=fallback,
                limit=10,
            )

            items.extend(feed_items)

        except Exception as exc:
            errors.append(
                f"{category}: {str(exc)[:180]}"
            )

    items = filter_last_48_hours(
        items,
        NEWS_MAX_AGE_HOURS,
    )

    items = remove_duplicates(items)

    items = sort_latest(items)

    public_items = [
        _public_news_item(item)
        for item in items[:20]
    ]

    return {
        "ok": True,
        "updated_at": now_local_string(),
        "items": public_items,
        "live": bool(public_items),
        "source": (
            "Google News RSS / "
            "original publishers"
        ),
        "errors": errors[:4],
    }


# ============================================================
# AGRICULTURE NEWS
# ============================================================

AGRI_FEEDS = [
    (
        "🌱 કૃષિ સમાચાર",
        (
            "કૃષિ સમાચાર ગુજરાત ખેડૂત "
            "ખેતી પાક"
        ),
        "કૃષિ સમાચાર",
    ),
    (
        "🦠 રોગ-જીવાત એલર્ટ",
        (
            "ગુજરાત પાક રોગ જીવાત "
            "ખેડૂત એલર્ટ"
        ),
        "કૃષિ રોગ જીવાત સમાચાર",
    ),
    (
        "🏛 સરકારની કૃષિ યોજનાઓ",
        (
            "ગુજરાત સરકાર ખેડૂત યોજના "
            "સબસિડી સહાય કૃષિ"
        ),
        "સરકારની કૃષિ યોજના",
    ),
    (
        "🚜 કૃષિ ટેક્નોલોજી",
        (
            "ગુજરાત કૃષિ ટેક્નોલોજી "
            "ખેડૂત નવી ટેકનોલોજી"
        ),
        "કૃષિ ટેક્નોલોજી",
    ),
]


@app.get("/api/v1/agri/news")
def agriculture_news():
    """
    Agriculture news.

    Intentionally does NOT provide crop-specific
    news categories.
    """

    items: list[dict[str, Any]] = []
    errors: list[str] = []

    for category, query, fallback in AGRI_FEEDS:

        try:
            feed_items = fetch_google_news(
                category=category,
                query=query,
                fallback_source=fallback,
                limit=10,
            )

            items.extend(feed_items)

        except Exception as exc:
            errors.append(
                f"{category}: {str(exc)[:180]}"
            )

    items = filter_last_48_hours(
        items,
        NEWS_MAX_AGE_HOURS,
    )

    items = remove_duplicates(items)

    items = sort_latest(items)

    public_items = [
        _public_news_item(item)
        for item in items[:24]
    ]

    return {
        "ok": True,
        "updated_at": now_local_string(),
        "items": public_items,
        "live": bool(public_items),
        "source": (
            "Google News RSS / "
            "original publishers"
        ),
        "errors": errors[:4],
    }


# ============================================================
# MARKET NEWS QUERIES
# ============================================================

MARKET_FEEDS = [
    (
        "APMC Gujarat",
        "APMC Gujarat બજાર ભાવ",
        "APMC Gujarat",
    ),
    (
        "Rajkot APMC",
        "રાજકોટ APMC બજાર ભાવ",
        "Rajkot APMC",
    ),
    (
        "Gujarat Market Prices",
        "ગુજરાત બજાર ભાવ",
        "ગુજરાત બજાર ભાવ",
    ),
    (
        "Groundnut Market Prices",
        "મગફળી બજાર ભાવ",
        "મગફળી બજાર ભાવ",
    ),
    (
        "Cotton Market Prices",
        "કપાસ બજાર ભાવ",
        "કપાસ બજાર ભાવ",
    ),
    (
        "Cumin Market Prices",
        "જીરૂ બજાર ભાવ",
        "જીરૂ બજાર ભાવ",
    ),
    (
        "Onion Market Prices",
        "ડુંગળી બજાર ભાવ",
        "ડુંગળી બજાર ભાવ",
    ),
    (
        "Agricultural Market",
        "કૃષિ બજાર ભાવ ગુજરાત",
        "કૃષિ બજાર",
    ),
]


# ============================================================
# MARKET PRICE PARSER
# ============================================================

PRICE_NUMBER = r"(?:₹\s*)?\d{2,7}(?:[.,]\d{1,2})?"


def _price_to_string(value: str) -> str:
    value = (
        value.replace(
            "₹",
            "",
        )
        .replace(
            ",",
            "",
        )
        .strip()
    )

    # Preserve decimal only if actually present.
    if "." in value:
        try:
            number = float(value)

            if number.is_integer():
                return str(int(number))

            return str(number)
        except Exception:
            return value

    return value


def _extract_price_range(
    text: str,
) -> Optional[tuple[str, str]]:
    """
    Supports:
      ₹1180 ₹1410
      1180-1410
      1180 થી 1410
      1180 to 1410
      1180–1410
      1180 — 1410
    """

    if not text:
        return None

    patterns = [
        rf"({PRICE_NUMBER})\s*[-–—]\s*({PRICE_NUMBER})",
        rf"({PRICE_NUMBER})\s*(?:થી|to)\s*({PRICE_NUMBER})",
        rf"₹?\s*({PRICE_NUMBER})\s+₹?\s*({PRICE_NUMBER})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if not match:
            continue

        minimum = _price_to_string(
            match.group(1)
        )

        maximum = _price_to_string(
            match.group(2)
        )

        try:
            min_value = float(
                minimum.replace(",", "")
            )

            max_value = float(
                maximum.replace(",", "")
            )

            if min_value > max_value:
                minimum, maximum = (
                    maximum,
                    minimum,
                )

        except Exception:
            pass

        return minimum, maximum

    return None


def _extract_single_prices(
    text: str,
) -> Optional[tuple[str, str]]:
    """
    Fallback for:
      Minimum ₹1180 Maximum ₹1410
      min 1180 max 1410
      લઘુત્તમ 1180 મહત્તમ 1410
    """

    patterns = [
        rf"(?:minimum|min|લઘુત્તમ|ન્યૂનતમ)\s*[:\-]?\s*₹?\s*({PRICE_NUMBER}).*?"
        rf"(?:maximum|max|મહત્તમ)\s*[:\-]?\s*₹?\s*({PRICE_NUMBER})",

        rf"(?:minimum|min|લઘુત્તમ|ન્યૂનતમ)\s*[:\-]?\s*₹?\s*({PRICE_NUMBER}).*?"
        rf"(?:maximum|max|મહત્તમ)\s*[:\-]?\s*₹?\s*({PRICE_NUMBER})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if match:
            return (
                _price_to_string(
                    match.group(1)
                ),
                _price_to_string(
                    match.group(2)
                ),
            )

    return None


def _detect_crop(text: str) -> Optional[str]:
    """
    Detect common Gujarat market crops.
    """

    crop_aliases = [
        (
            "મગફળી",
            [
                "મગફળી",
                "groundnut",
                "peanut",
            ],
        ),
        (
            "કપાસ",
            [
                "કપાસ",
                "cotton",
            ],
        ),
        (
            "જીરૂ",
            [
                "જીરૂ",
                "જીરું",
                "cumin",
            ],
        ),
        (
            "ડુંગળી",
            [
                "ડુંગળી",
                "onion",
            ],
        ),
        (
            "બટાકા",
            [
                "બટાકા",
                "potato",
            ],
        ),
        (
            "લીંબુ",
            [
                "લીંબુ",
                "lemon",
            ],
        ),
        (
            "પપૈયા",
            [
                "પપૈયા",
                "papaya",
            ],
        ),
        (
            "ઘઉં",
            [
                "ઘઉં",
                "wheat",
            ],
        ),
        (
            "બાજરી",
            [
                "બાજરી",
                "pearl millet",
                "bajra",
            ],
        ),
        (
            "ચણા",
            [
                "ચણા",
                "gram",
                "chickpea",
            ],
        ),
        (
            "ધાણા",
            [
                "ધાણા",
                "coriander",
            ],
        ),
        (
            "તલ",
            [
                "તલ",
                "sesame",
            ],
        ),
    ]

    lower = text.lower()

    for crop, aliases in crop_aliases:

        for alias in aliases:

            if alias.lower() in lower:
                return crop

    return None


def _detect_apmc(text: str) -> Optional[str]:
    """
    Detect APMC/market name from headline/description.
    """

    patterns = [
        r"([A-Za-z][A-Za-z\s]{2,40})\s*APMC",
        r"APMC\s*([A-Za-z][A-Za-z\s]{2,40})",
        r"([^\s,.;]{2,30})\s*માર્કેટ",
        r"([^\s,.;]{2,30})\s*બજાર",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE,
        )

        if match:

            value = clean_html(
                match.group(1)
            )

            if value:
                return value.strip()

    # Known Gujarat markets fallback.
    known_markets = [
        "રાજકોટ",
        "ગોંડલ",
        "જામનગર",
        "જૂનાગઢ",
        "ગોંડલ",
        "મોરબી",
        "અમદાવાદ",
        "મહેસાણા",
        "ઉંઝા",
        "વિસનગર",
        "ધોરાજી",
        "ધ્રોલ",
        "ભાવનગર",
        "સુરત",
        "નવસારી",
        "વડોદરા",
        "ગાંધીનગર",
        "પોરબંદર",
        "અમરેલી",
        "ધ્રાંગધ્રા",
    ]

    for market in known_markets:

        if market in text:
            return market

    return None


def _extract_news_date(
    item: dict[str, Any],
) -> str:
    published_dt = item.get(
        "_published_dt"
    )

    if isinstance(
        published_dt,
        datetime,
    ):
        return published_dt.astimezone().strftime(
            "%d-%m-%Y"
        )

    return datetime.now().astimezone().strftime(
        "%d-%m-%Y"
    )


def parse_market_prices(
    items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """
    Parse market prices from news headline/description.

    A row is returned only if:
    - A crop is detected
    - A minimum/maximum price pair is detected

    This prevents unrelated news from entering the
    market table.
    """

    table: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for item in items:

        headline = str(
            item.get(
                "headline",
                "",
            )
        )

        summary = str(
            item.get(
                "summary",
                "",
            )
        )

        source_text = (
            f"{headline} {summary}"
        )

        crop = _detect_crop(
            source_text
        )

        if not crop:
            continue

        prices = _extract_price_range(
            source_text
        )

        if not prices:
            prices = _extract_single_prices(
                source_text
            )

        if not prices:
            continue

        minimum, maximum = prices

        apmc = _detect_apmc(
            source_text
        )

        if not apmc:
            # Without an identifiable market/APMC,
            # do not create a misleading table row.
            continue

        date = _extract_news_date(
            item
        )

        row = {
            "date": date,
            "apmc": apmc,
            "crop": crop,
            "min_price": minimum,
            "max_price": maximum,
        }

        key = (
            row["date"],
            norm(row["apmc"]),
            norm(row["crop"]),
            row["min_price"],
            row["max_price"],
        )

        if key in seen:
            continue

        seen.add(key)
        table.append(row)

    return table


# ============================================================
# OPTIONAL LIVE APMC / MANDI DATA
# ============================================================

def _find_first_value(
    data: dict[str, Any],
    keys: tuple[str, ...],
) -> Any:
    for key in keys:

        if key in data:
            return data[key]

    return None


def _normalize_live_market_row(
    row: dict[str, Any],
) -> Optional[dict[str, str]]:
    """
    Normalize common APMC/data.gov.in style field names.

    This function is deliberately tolerant because different
    mandi providers use different JSON field names.
    """

    date_value = _find_first_value(
        row,
        (
            "date",
            "arrival_date",
            "arrivalDate",
            "trade_date",
            "tradeDate",
        ),
    )

    apmc_value = _find_first_value(
        row,
        (
            "apmc",
            "market",
            "market_name",
            "marketName",
            "market_center",
            "market_center_name",
        ),
    )

    crop_value = _find_first_value(
        row,
        (
            "crop",
            "commodity",
            "commodity_name",
            "commodityName",
        ),
    )

    minimum = _find_first_value(
        row,
        (
            "min_price",
            "minPrice",
            "minimum_price",
            "min_price_rs",
            "min_price_per_quintal",
        ),
    )

    maximum = _find_first_value(
        row,
        (
            "max_price",
            "maxPrice",
            "maximum_price",
            "max_price_rs",
            "max_price_per_quintal",
        ),
    )

    if (
        apmc_value is None
        or crop_value is None
        or minimum is None
        or maximum is None
    ):
        return None

    date_text = (
        str(date_value)
        if date_value is not None
        else datetime.now().astimezone().strftime(
            "%d-%m-%Y"
        )
    )

    return {
        "date": date_text,
        "apmc": str(apmc_value),
        "crop": str(crop_value),
        "min_price": str(minimum),
        "max_price": str(maximum),
    }


def fetch_live_apmc_data() -> list[dict[str, str]]:
    """
    Optional live APMC connector.

    It activates only when MANDI_API_URL is configured.

    Supported response shapes:
      {"records": [...]}
      {"data": [...]}
      [...]
    """

    if not MANDI_API_URL:
        return []

    url = MANDI_API_URL

    if MANDI_API_KEY:
        separator = (
            "&"
            if "?" in url
            else "?"
        )

        url = (
            f"{url}"
            f"{separator}"
            f"api_key="
            f"{urllib.parse.quote(MANDI_API_KEY)}"
        )

    raw = _fetch_url(
        url,
        timeout=max(
            NEWS_TIMEOUT,
            10,
        ),
        retries=1,
    )

    try:
        payload = json.loads(
            raw.decode(
                "utf-8",
                errors="replace",
            )
        )

    except Exception as exc:
        raise RuntimeError(
            f"Live APMC JSON parse failed: {exc}"
        ) from exc

    if isinstance(payload, dict):

        records = (
            payload.get("records")
            or payload.get("data")
            or payload.get("results")
            or []
        )

    elif isinstance(payload, list):
        records = payload

    else:
        records = []

    result: list[dict[str, str]] = []

    for record in records:

        if not isinstance(record, dict):
            continue

        normalized = _normalize_live_market_row(
            record
        )

        if normalized:
            result.append(
                normalized
            )

    return result


# ============================================================
# MARKET NEWS ENDPOINT
# ============================================================

@app.get("/api/v1/market/news")
def market_news():
    """
    Market endpoint.

    Part A:
      Optional live APMC data.

    Part B:
      Fresh Google News market reports.

    Failure of either source does not crash the endpoint.
    """

    errors: list[str] = []

    live_market: list[dict[str, str]] = []

    # --------------------------------------------------------
    # PART A - LIVE APMC
    # --------------------------------------------------------

    if MANDI_API_URL:

        try:
            live_market = fetch_live_apmc_data()

        except Exception as exc:
            errors.append(
                f"Live APMC: {str(exc)[:180]}"
            )

    # --------------------------------------------------------
    # PART B - MARKET NEWS
    # --------------------------------------------------------

    news_items: list[dict[str, Any]] = []

    for category, query, fallback in MARKET_FEEDS:

        try:
            feed_items = fetch_google_news(
                category=category,
                query=query,
                fallback_source=fallback,
                limit=10,
            )

            news_items.extend(
                feed_items
            )

        except Exception as exc:
            errors.append(
                f"{category}: {str(exc)[:180]}"
            )

    news_items = filter_last_48_hours(
        news_items,
        NEWS_MAX_AGE_HOURS,
    )

    news_items = remove_duplicates(
        news_items
    )

    news_items = sort_latest(
        news_items
    )

    market_table = parse_market_prices(
        news_items
    )

    # --------------------------------------------------------
    # Combine live table + news table without duplicates.
    # --------------------------------------------------------

    combined_table: list[dict[str, str]] = []

    seen_rows: set[tuple[str, ...]] = set()

    for row in (
        live_market
        + market_table
    ):

        key = (
            str(row.get("date", "")),
            norm(
                str(row.get("apmc", ""))
            ),
            norm(
                str(row.get("crop", ""))
            ),
            str(
                row.get(
                    "min_price",
                    "",
                )
            ),
            str(
                row.get(
                    "max_price",
                    "",
                )
            ),
        )

        if key in seen_rows:
            continue

        seen_rows.add(key)

        combined_table.append(
            {
                "date": str(
                    row.get(
                        "date",
                        "",
                    )
                ),
                "apmc": str(
                    row.get(
                        "apmc",
                        "",
                    )
                ),
                "crop": str(
                    row.get(
                        "crop",
                        "",
                    )
                ),
                "min_price": str(
                    row.get(
                        "min_price",
                        "",
                    )
                ),
                "max_price": str(
                    row.get(
                        "max_price",
                        "",
                    )
                ),
            }
        )

    public_items = [
        _public_news_item(item)
        for item in news_items[:24]
    ]

    return {
        "ok": True,
        "updated_at": now_local_string(),

        # Android/news compatibility
        "items": public_items,

        # Market-specific table
        "market_table": combined_table[:100],

        # Source indicators
        "live": bool(
            live_market
            or public_items
        ),

        "live_apmc": bool(
            live_market
        ),

        "news_available": bool(
            public_items
        ),

        "source": (
            "Live APMC + Google News RSS"
            if live_market
            else "Google News RSS"
        ),

        "errors": errors[:6],
    }


# ============================================================
# ROOT ENDPOINT
# ============================================================

@app.get("/")
def root():
    return {
        "ok": True,
        "service": "smart-agri-ai",
        "version": APP_VERSION,
    }


# ============================================================
# HEALTH ENDPOINT
# ============================================================

@app.get("/api/v1/health")
def health():

    return {
        "ok": True,
        "service": "smart-agri-ai",
        "version": APP_VERSION,

        "agent_loaded": _agent is not None,

        "groq_configured": bool(
            os.getenv(
                "GROQ_API_KEY",
                "",
            ).strip()
        ),

        "gemini_configured": bool(
            os.getenv(
                "GEMINI_API_KEY",
                "",
            ).strip()
        ),

        "mandi_configured": bool(
            MANDI_API_URL
        ),

        "text_provider": "groq",
        "text_model": GROQ_MODEL,

        "vision_provider": "gemini",
        "vision_model": VISION_MODEL,
    }


# ============================================================
# GROQ TEXT AI CLIENT
# ============================================================

def groq_client():
    key = os.getenv(
        "GROQ_API_KEY",
        "",
    ).strip()

    if not key:
        return None

    return OpenAI(
        api_key=key,
        base_url="https://api.groq.com/openai/v1",
    )


# ============================================================
# GEMINI VISION CLIENT
# ============================================================

def gemini_client():
    key = os.getenv(
        "GEMINI_API_KEY",
        "",
    ).strip()

    if not key:
        return None

    return genai.Client(
        api_key=key
    )


# ============================================================
# RULE-BASED ANSWER
# ============================================================

def rule_based_answer(
    question: str,
    context: dict | None,
) -> str:
    """
    Use supplied crop agent knowledge.
    """

    q = norm(question)

    ctx = context or {}

    selected = (
        ctx.get(
            "selected_crop"
        )
        or {}
    )

    crop = str(
        selected.get(
            "name",
            "",
        )
    ).strip()

    if not crop and _agent:

        aliases = getattr(
            _agent,
            "ROMAN_ALIASES",
            {},
        )

        crops = getattr(
            _agent,
            "CROPS",
            {},
        )

        for key, name in crops.items():

            if (
                norm(name) in q
                or norm(key) == q
            ):
                crop = name
                break

        if not crop:

            for alias, name in aliases.items():

                if alias and alias in q:
                    crop = name
                    break

    data = (
        getattr(
            _agent,
            "CROP_DATA",
            {},
        )
        if _agent
        else {}
    )

    profile = (
        data.get(
            crop,
            {},
        )
        if crop
        else {}
    )

    if any(
        x in q
        for x in (
            "સિંચાઈ",
            "પા છણી",
            "પિયત",
            "irrigation",
            "water",
        )
    ):
        return (
            f"💧 {crop or 'પાક'} માટે સિંચાઈ સલાહ:\n"
            f"{profile.get('પાણી', 'પાકની અવસ્થા, જમીનનો ભેજ અને વરસાદ પ્રમાણે સિંચાઈ કરો; પાણી ભરાવું ટાળો.')}\n"
            "છેલ્લો વરસાદ, જમીનનો પ્રકાર અને પાકની હાલની અવસ્થા "
            "જણાવશો તો સલાહ વધુ ચોક્કસ કરી શકું."
        )

    if any(
        x in q
        for x in (
            "ખાતર",
            "પોષણ",
            "fertilizer",
            "npk",
        )
    ):
        return (
            f"🧪 {crop or 'પાક'} માટે પોષણ:\n"
            "માટી પરીક્ષણ આધારિત N-P-K અને સૂક્ષ્મ તત્ત્વો "
            "નક્કી કરો. પાકની અવસ્થા પ્રમાણે ખાતર વહેંચીને "
            "આપવું વધુ યોગ્ય રહે છે. માટી રિપોર્ટ વગર "
            "ચોક્કસ ડોઝ નક્કી ન કરવો."
        )

    if any(
        x in q
        for x in (
            "રોગ",
            "જીવાત",
            "ઈયળ",
            "ઇયળ",
            "પાન પીળ",
            "disease",
            "pest",
        )
    ):
        disease = (
            getattr(
                _agent,
                "_DISEASES",
                {},
            ).get(
                crop,
                [],
            )
            if _agent
            else []
        )

        extra = "\n".join(
            f"• {x}"
            for x in disease[:3]
        )

        return (
            f"🔎 {crop or 'પાક'} માટે રોગ/જીવાત તપાસ:\n"
            f"{extra or 'પાન, ડાંઠ, મૂળ અને ફળનું નજીકથી નિરીક્ષણ કરો અને પાણી/પોષણની સ્થિતિ તપાસો.'}\n"
            "ફોટો, પાકની ઉંમર અને નુકસાનનું પ્રમાણ આપશો તો "
            "વધુ મદદ કરી શકું. દવા/માત્રા સ્થાનિક નોંધાયેલ "
            "ભલામણ મુજબ જ નક્કી કરો."
        )

    if crop and profile:
        return (
            f"🌱 {crop} અંગે ઉપયોગી માહિતી:\n"
            f"• જમીન: {profile.get('જમીન', 'માટી પરીક્ષણ મુજબ')}\n"
            f"• વાવણી: {profile.get('વાવણી', 'સ્થાનિક ભલામણ મુજબ')}\n"
            f"• પાણી: {profile.get('પાણી', 'પાકની અવસ્થા અને જમીનના ભેજ મુજબ')}\n"
            f"• સાવચેતી: {profile.get('સાવચેતી', 'નિયમિત નિરીક્ષણ કરો')}"
        )

    return (
        "🤖 ખેડૂત સહાયક: પ્રશ્નનો વધુ ચોક્કસ જવાબ આપવા "
        "પાકનું નામ, પાકની ઉંમર/વાવણી તારીખ, જમીનનો પ્રકાર, "
        "છેલ્લું સિંચાઈ/વરસાદ અને સમસ્યાના લક્ષણો લખો. "
        "ફોટો હોય તો મોકલી શકો."
    )


# ============================================================
# GROQ TEXT AI ENDPOINT
# ============================================================

@app.post("/api/v1/ai/ask")
def ask(req: Ask):

    question = (
        req.question or ""
    ).strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="પ્રશ્ન ખાલી છે.",
        )

    client = groq_client()

    if client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Groq AI configured નથી. "
                "Render Environment Variables માં "
                "GROQ_API_KEY સેટ કરો."
            ),
        )

    ctx = req.context or {}

    prompt = (
        f"ખેડૂત પ્રશ્ન: {question}\n"
        f"ખેડૂત સંદર્ભ: {ctx}\n\n"
        "આ પ્રશ્નનો સીધો, ઉપયોગી અને વ્યવહારુ જવાબ "
        "ગુજરાતી ભાષામાં આપો. "
        "પાક, પાકની અવસ્થા, જમીન, સિંચાઈ, હવામાન "
        "અને ઉપલબ્ધ સંદર્ભને ધ્યાનમાં લો. "
        "પ્રશ્ન જે પૂછે છે તેનો જ જવાબ આપો. "
        "જો માહિતી અધૂરી હોય તો જરૂરી માહિતી પૂછો. "
        "એક જ fixed જવાબ વારંવાર ન આપો."
    )

    try:

        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        answer = (
            response.choices[0]
            .message.content
            or ""
        ).strip()

        if not answer:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Groq તરફથી ખાલી જવાબ મળ્યો."
                ),
            )

        return {
            "answer": answer,
            "mode": "groq",
            "model": GROQ_MODEL,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Groq AI error: {exc}"
            ),
        )


# ============================================================
# GEMINI VISION ENDPOINT
# ============================================================

@app.post("/api/v1/ai/diagnose")
async def diagnose(
    image: UploadFile = File(...),
    crop: str = Form(""),
    context: str = Form(""),
):
    """
    Gemini Vision endpoint.

    Existing Android multipart fields are preserved:
    - image
    - crop
    - context
    """

    data = await image.read()

    if not data:
        raise HTTPException(
            status_code=400,
            detail="ફોટો ખાલી છે.",
        )

    client = gemini_client()

    if client is None:
        return {
            "answer": (
                "📷 ફોટો મળ્યો છે. "
                "Vision AI માટે Renderમાં GEMINI_API_KEY "
                "સેટ કરો અને VISION_MODEL ચકાસો. "
                "હાલમાં ફોટા પરથી નિશ્ચિત રોગનિદાન "
                "અથવા દવા/ડોઝ આપવો યોગ્ય નથી."
            ),
            "mode": "agent_unavailable",
        }

    mime = (
        image.content_type
        or "image/jpeg"
    )

    # Guard against invalid/empty MIME values.
    if "/" not in mime:
        mime = "image/jpeg"

    prompt = (
        f"આ ખેતીના પાકનો ફોટો છે. "
        f"પાક: {crop or 'અજ્ઞાત'}. "
        f"સંદર્ભ: {context}.\n\n"

        "ફોટામાં દેખાતા લક્ષણોનું ધ્યાનપૂર્વક "
        "નિરીક્ષણ કરો. જવાબ ગુજરાતી ભાષામાં આપો.\n\n"

        "આ ક્રમમાં જવાબ આપો:\n"

        "1) દેખાતા લક્ષણો\n"

        "2) 1-3 સંભવિત કારણો અથવા રોગ/જીવાત\n"

        "3) તરત કરી શકાય તેવી IPM/સલામતી સલાહ\n"

        "4) ક્યારે સ્થાનિક કૃષિ નિષ્ણાત/KVK/લેબની "
        "ચકાસણી લેવી\n\n"

        "ફોટા પરથી નિશ્ચિત નિદાન ન કરો અને "
        "ચોક્કસ pesticide dose, concentration "
        "અથવા brand ન આપો.\n\n"

        "જો ફોટો અસ્પષ્ટ હોય અથવા પાક/લક્ષણો "
        "પૂરતા દેખાતા ન હોય તો તે સ્પષ્ટ જણાવો.\n\n"

        "જવાબ સંપૂર્ણ આપો. "
        "જવાબને 1-3 લાઇનમાં કાપશો નહીં."
    )

    try:

        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[
                types.Part.from_bytes(
                    data=data,
                    mime_type=mime,
                ),
                prompt,
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                temperature=0.2,
                max_output_tokens=4096,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=0,
                ),
            ),
        )

        answer = (
            response.text
            or ""
        ).strip()

        return {
            "answer": (
                answer
                or "ફોટામાંથી પૂરતો જવાબ મળ્યો નથી."
            ),
            "mode": "gemini_vision",
            "model": VISION_MODEL,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                f"Vision AI error: {exc}"
            ),
        )
