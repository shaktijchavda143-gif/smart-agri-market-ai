# -*- coding: utf-8 -*-
"""Smart Agri-Market AI Backend - Version 10."""

import os
import html
import json
import re
import time
import importlib.util
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
# APP CONFIG
# ============================================================

APP_VERSION = "10.1 Android API Bridge"

GROQ_MODEL = (
    os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
    or "openai/gpt-oss-20b"
)

VISION_MODEL = (
    os.getenv("VISION_MODEL", "gemini-2.5-flash").strip()
    or "gemini-2.5-flash"
)

NEWS_TIMEOUT = max(3, int(os.getenv("NEWS_TIMEOUT", "8")))
NEWS_RETRIES = max(0, min(int(os.getenv("NEWS_RETRIES", "1")), 3))
NEWS_MAX_AGE_HOURS = 48

NEWS_USER_AGENT = "SmartAgriMarketAI/10.1"


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="Smart Agri Market AI Backend",
    version=APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# SMART AGRI AGENT IMPORT
# ============================================================

_agent = None

try:
    agent_path = os.path.join(
        os.path.dirname(__file__),
        "smart_agri_agent.py"
    )

    spec = importlib.util.spec_from_file_location(
        "smart_agri_agent",
        agent_path
    )

    if spec and spec.loader:
        _agent = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_agent)

except Exception as exc:
    print(f"Agent import warning: {exc}")


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM = (
    "તમે Smart Agri-Market AI ગુજરાતી ખેડૂત સહાયક છો. "
    "જવાબ સરળ, વ્યવહારુ અને ખેડૂતના સંદર્ભ મુજબ આપો. "
    "પાક, સિંચાઈ, પોષણ, રોગ-જીવાત, હવામાન અને બજાર અંગે માર્ગદર્શન આપો. "
    "ચોક્કસ pesticide dose અથવા નિશ્ચિત રોગનિદાન માટે સ્થાનિક કૃષિ "
    "નિષ્ણાત/KVK/લેબ ચકાસણી જરૂરી હોવાનું જણાવો."
)


# ============================================================
# REQUEST MODEL
# ============================================================

class Ask(BaseModel):
    question: str
    context: dict | None = None


# ============================================================
# GENERAL HELPERS
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
    text = html.unescape(
        re.sub(r"<[^>]+>", " ", value or "")
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def parse_rss_datetime(value: str) -> Optional[datetime]:

    if not value:
        return None

    try:
        dt = parsedate_to_datetime(value.strip())

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

    try:
        dt = datetime.fromisoformat(
            value.strip().replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def rss_datetime(value: str) -> str:

    dt = parse_rss_datetime(value)

    if not dt:
        return "સમય ઉપલબ્ધ નથી"

    return dt.astimezone().strftime(
        "%d-%m-%Y %H:%M"
    )


def filter_last_48_hours(
    items: list[dict[str, Any]],
    hours: int = NEWS_MAX_AGE_HOURS,
) -> list[dict[str, Any]]:

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(hours=hours)
    )

    return [
        item
        for item in items
        if isinstance(
            item.get("_published_dt"),
            datetime
        )
        and item["_published_dt"] >= cutoff
    ]


def remove_duplicates(
    items: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    links = set()
    headlines = set()
    category_headlines = set()

    result = []

    for item in items:

        link = norm(
            str(item.get("url", ""))
        )

        headline = norm(
            str(item.get("headline", ""))
        )

        category = norm(
            str(item.get("category", ""))
        )

        category_headline = (
            f"{category}|{headline}"
        )

        if link and link in links:
            continue

        if headline and headline in headlines:
            continue

        if category_headline in category_headlines:
            continue

        if link:
            links.add(link)

        if headline:
            headlines.add(headline)

        category_headlines.add(
            category_headline
        )

        result.append(item)

    return result


def sort_latest(
    items: list[dict[str, Any]]
) -> list[dict[str, Any]]:

    minimum = datetime.min.replace(
        tzinfo=timezone.utc
    )

    return sorted(
        items,
        key=lambda x: x.get(
            "_published_dt",
            minimum
        ),
        reverse=True,
    )


def public_news_item(
    item: dict[str, Any]
) -> dict[str, Any]:

    return {
        key: value
        for key, value in item.items()
        if not key.startswith("_")
    }


# ============================================================
# NETWORK FETCH
# ============================================================

def _fetch_url(
    url: str,
    timeout: int = NEWS_TIMEOUT,
    retries: int = NEWS_RETRIES,
) -> bytes:

    last_error = None

    for attempt in range(retries + 1):

        try:

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": NEWS_USER_AGENT,
                    "Accept": (
                        "application/rss+xml, "
                        "application/xml, "
                        "text/xml, */*"
                    ),
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=timeout
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


# ============================================================
# GOOGLE NEWS RSS ENGINE
# ============================================================

def fetch_google_news(
    category: str,
    query: str,
    fallback_source: str,
    limit: int = 10,
) -> list[dict[str, Any]]:

    url = (
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

    raw = _fetch_url(url)

    try:
        root = ET.fromstring(raw)

    except ET.ParseError as exc:
        raise RuntimeError(
            f"Invalid RSS XML: {exc}"
        ) from exc

    result = []

    channel = root.find("channel")

    if channel is None:
        return result

    rss_items = channel.findall("item")

    for item in rss_items[:limit]:

        title = clean_html(
            item.findtext(
                "title",
                ""
            )
        )

        link = (
            item.findtext(
                "link",
                ""
            )
            or ""
        ).strip()

        description = clean_html(
            item.findtext(
                "description",
                ""
            )
        )

        pub_raw = (
            item.findtext(
                "pubDate",
                ""
            )
            or ""
        ).strip()

        published_dt = parse_rss_datetime(
            pub_raw
        )

        if not title or not link:
            continue

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

        summary = (
            description
            or f"{source} તરફથી સંબંધિત તાજો અહેવાલ."
        )

        if len(summary) > 400:
            summary = (
                summary[:397]
                .rsplit(" ", 1)[0]
                + "..."
            )

        result.append(
            {
                "category": category,
                "headline": title,
                "summary": summary,
                "published": (
                    published_dt
                    .astimezone()
                    .strftime(
                        "%d-%m-%Y %H:%M"
                    )
                ),
                "source": source,
                "url": link,
                "_published_dt": published_dt,
            }
        )

    return result


def build_news_response(
    items: list[dict[str, Any]],
    errors: list[str],
    limit: int = 24,
) -> dict[str, Any]:

    items = sort_latest(
        remove_duplicates(
            filter_last_48_hours(items)
        )
    )

    public_items = [
        public_news_item(item)
        for item in items[:limit]
    ]

    return {
        "ok": True,
        "updated_at": now_local_string(),
        "items": public_items,
        "live": bool(public_items),
        "source": (
            "Google News RSS / original publishers"
        ),
        "errors": errors[:6],
    }


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


def _collect_news(
    feeds: list[tuple[str, str, str]],
    limit_each: int = 10,
):

    items = []
    errors = []

    for category, query, fallback in feeds:

        try:

            items.extend(
                fetch_google_news(
                    category,
                    query,
                    fallback,
                    limit_each,
                )
            )

        except Exception as exc:

            errors.append(
                f"{category}: {str(exc)[:180]}"
            )

    return items, errors


@app.get("/api/v1/weather/news")
def weather_news():

    items, errors = _collect_news(
        WEATHER_FEEDS
    )

    return build_news_response(
        items,
        errors,
        20,
    )


# ============================================================
# AGRICULTURE NEWS
# ============================================================

AGRI_FEEDS = [

    (
        "🌱 કૃષિ સમાચાર",
        "કૃષિ સમાચાર ગુજરાત ખેડૂત ખેતી પાક",
        "કૃષિ સમાચાર",
    ),

    (
        "🦠 રોગ-જીવાત એલર્ટ",
        "ગુજરાત પાક રોગ જીવાત ખેડૂત એલર્ટ",
        "કૃષિ રોગ જીવાત સમાચાર",
    ),

    (
        "🏛 સરકારની કૃષિ યોજનાઓ",
        "ગુજરાત સરકાર ખેડૂત યોજના સબસિડી સહાય કૃષિ",
        "સરકારની કૃષિ યોજના",
    ),

    (
        "🚜 કૃષિ ટેક્નોલોજી",
        "ગુજરાત કૃષિ ટેક્નોલોજી ખેડૂત નવી ટેકનોલોજી",
        "કૃષિ ટેક્નોલોજી",
    ),
]


@app.get("/api/v1/agri/news")
def agriculture_news():

    items, errors = _collect_news(
        AGRI_FEEDS
    )

    return build_news_response(
        items,
        errors,
        24,
    )


# ============================================================
# LEGACY /api/v1/news
# ============================================================
#
# IMPORTANT:
# Existing Android application is calling:
#
# GET /api/v1/news?crop=મગફળી
#
# Version 10 accidentally removed this route.
# Therefore Android received HTTP 404.
#
# This endpoint is retained for backward compatibility.
# ============================================================

@app.get("/api/v1/news")
def legacy_news(
    crop: str = ""
):

    crop = (crop or "").strip()

    if crop:

        feeds = [

            (
                f"🌱 {crop} સમાચાર",
                f"{crop} ગુજરાત કૃષિ સમાચાર ખેડૂત",
                "Google News / કૃષિ સમાચાર",
            ),

            (
                "🌱 કૃષિ સમાચાર",
                "કૃષિ સમાચાર ગુજરાત ખેડૂત ખેતી પાક",
                "કૃષિ સમાચાર",
            ),

            (
                "🏛 સરકારની કૃષિ યોજનાઓ",
                "ગુજરાત સરકાર ખેડૂત યોજના સબસિડી સહાય કૃષિ",
                "સરકારની કૃષિ યોજના",
            ),
        ]

    else:

        feeds = AGRI_FEEDS

    items, errors = _collect_news(
        feeds
    )

    response = build_news_response(
        items,
        errors,
        20,
    )

    # Android compatibility fields
    response["crop"] = crop
    response["category"] = "કૃષિ સમાચાર"

    return response


# ============================================================
# MARKET PRICE HELPERS
# ============================================================

PRICE_NUMBER = (
    r"(?:₹\s*)?"
    r"\d{2,7}"
    r"(?:[.,]\d{1,2})?"
)


def _price_to_string(
    value: str
) -> str:

    value = (
        value
        .replace("₹", "")
        .replace(",", "")
        .strip()
    )

    try:

        number = float(value)

        if number.is_integer():
            return str(int(number))

        return str(number)

    except Exception:

        return value


def _extract_price_range(
    text: str
) -> Optional[tuple[str, str]]:

    patterns = [

        rf"({PRICE_NUMBER})\s*[-–—]\s*({PRICE_NUMBER})",

        rf"({PRICE_NUMBER})\s*(?:થી|to)\s*({PRICE_NUMBER})",

        rf"₹?\s*({PRICE_NUMBER})\s+₹?\s*({PRICE_NUMBER})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            first = _price_to_string(
                match.group(1)
            )

            second = _price_to_string(
                match.group(2)
            )

            try:

                if float(first) > float(second):
                    first, second = second, first

            except Exception:
                pass

            return first, second

    return None


def _extract_single_prices(
    text: str
) -> Optional[tuple[str, str]]:

    pattern = (
        rf"(?:minimum|min|લઘુત્તમ|ન્યૂનતમ)"
        rf"\s*[:\-]?\s*₹?\s*({PRICE_NUMBER})"
        rf".*?"
        rf"(?:maximum|max|મહત્તમ)"
        rf"\s*[:\-]?\s*₹?\s*({PRICE_NUMBER})"
    )

    match = re.search(
        pattern,
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return None

    return (
        _price_to_string(
            match.group(1)
        ),
        _price_to_string(
            match.group(2)
        ),
    )


def _detect_crop(
    text: str
) -> Optional[str]:

    crops = {

        "મગફળી": [
            "મગફળી",
            "groundnut",
            "peanut",
        ],

        "કપાસ": [
            "કપાસ",
            "cotton",
        ],

        "જીરૂ": [
            "જીરૂ",
            "જીરું",
            "cumin",
        ],

        "ડુંગળી": [
            "ડુંગળી",
            "onion",
        ],

        "બટાકા": [
            "બટાકા",
            "potato",
        ],

        "લીંબુ": [
            "લીંબુ",
            "lemon",
        ],

        "પપૈયા": [
            "પપૈયા",
            "papaya",
        ],

        "ઘઉં": [
            "ઘઉં",
            "wheat",
        ],

        "બાજરી": [
            "બાજરી",
            "bajra",
            "pearl millet",
        ],

        "ચણા": [
            "ચણા",
            "gram",
            "chickpea",
        ],

        "ધાણા": [
            "ધાણા",
            "coriander",
        ],

        "તલ": [
            "તલ",
            "sesame",
        ],
    }

    lower = text.lower()

    for crop, aliases in crops.items():

        if any(
            alias.lower() in lower
            for alias in aliases
        ):
            return crop

    return None


def _detect_apmc(
    text: str
) -> Optional[str]:

    known = [
        "રાજકોટ",
        "ગોંડલ",
        "જામનગર",
        "જૂનાગઢ",
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

    for market in known:

        if market in text:
            return market

    patterns = [

        r"([A-Za-z][A-Za-z\s]{2,40})\s*APMC",

        r"APMC\s*([A-Za-z][A-Za-z\s]{2,40})",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE,
        )

        if match:

            value = clean_html(
                match.group(1)
            ).strip()

            if value:
                return value

    return None


def parse_market_prices(
    items: list[dict[str, Any]]
) -> list[dict[str, str]]:

    result = []
    seen = set()

    for item in items:

        text = (
            f"{item.get('headline', '')} "
            f"{item.get('summary', '')}"
        )

        crop = _detect_crop(text)

        if not crop:
            continue

        prices = (
            _extract_price_range(text)
            or _extract_single_prices(text)
        )

        if not prices:
            continue

        apmc = _detect_apmc(text)

        if not apmc:
            continue

        published_dt = item.get(
            "_published_dt"
        )

        if isinstance(
            published_dt,
            datetime
        ):

            date = (
                published_dt
                .astimezone()
                .strftime("%d-%m-%Y")
            )

        else:

            date = datetime.now().astimezone().strftime(
                "%d-%m-%Y"
            )

        row = {

            "date": date,

            "apmc": apmc,

            "crop": crop,

            "min_price": prices[0],

            "max_price": prices[1],
        }

        key = tuple(
            row.values()
        )

        if key in seen:
            continue

        seen.add(key)

        result.append(row)

    return result


# ============================================================
# OPTIONAL LIVE APMC
# ============================================================

MANDI_API_URL = (
    os.getenv(
        "MANDI_API_URL",
        ""
    ).strip()
)

MANDI_API_KEY = (
    os.getenv(
        "MANDI_API_KEY",
        ""
    ).strip()
)


def _first(
    data: dict[str, Any],
    keys: tuple[str, ...],
):

    for key in keys:

        if key in data:
            return data[key]

    return None


def fetch_live_apmc_data():

    if not MANDI_API_URL:
        return []

    url = MANDI_API_URL

    if MANDI_API_KEY:

        url += (
            "&"
            if "?" in url
            else "?"
        )

        url += (
            "api_key="
            + urllib.parse.quote(
                MANDI_API_KEY
            )
        )

    raw = _fetch_url(
        url,
        timeout=10,
        retries=1,
    )

    payload = json.loads(
        raw.decode(
            "utf-8",
            errors="replace",
        )
    )

    records = []

    if isinstance(payload, dict):

        records = (
            payload.get("records")
            or payload.get("data")
            or payload.get("results")
            or []
        )

    elif isinstance(payload, list):

        records = payload

    if not isinstance(
        records,
        list
    ):
        return []

    result = []

    for row in records:

        if not isinstance(
            row,
            dict
        ):
            continue

        apmc = _first(
            row,
            (
                "apmc",
                "market",
                "market_name",
                "marketName",
            ),
        )

        crop = _first(
            row,
            (
                "crop",
                "commodity",
                "commodity_name",
                "commodityName",
            ),
        )

        minimum = _first(
            row,
            (
                "min_price",
                "minPrice",
                "minimum_price",
            ),
        )

        maximum = _first(
            row,
            (
                "max_price",
                "maxPrice",
                "maximum_price",
            ),
        )

        date = _first(
            row,
            (
                "date",
                "arrival_date",
                "arrivalDate",
                "trade_date",
            ),
        )

        if (
            apmc is None
            or crop is None
            or minimum is None
            or maximum is None
        ):
            continue

        result.append(
            {
                "date": str(
                    date
                    or datetime.now()
                    .astimezone()
                    .strftime(
                        "%d-%m-%Y"
                    )
                ),

                "apmc": str(apmc),

                "crop": str(crop),

                "min_price": str(minimum),

                "max_price": str(maximum),
            }
        )

    return result


# ============================================================
# MARKET NEWS
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


@app.get("/api/v1/market/news")
def market_news():

    errors = []

    live_market = []

    # --------------------------------------------------------
    # PART A - LIVE APMC
    # --------------------------------------------------------

    if MANDI_API_URL:

        try:

            live_market = fetch_live_apmc_data()

        except Exception as exc:

            errors.append(
                "Live APMC: "
                + str(exc)[:180]
            )

    # --------------------------------------------------------
    # PART B - NEWS MARKET DATA
    # --------------------------------------------------------

    news_items, news_errors = _collect_news(
        MARKET_FEEDS
    )

    errors.extend(
        news_errors
    )

    news_items = sort_latest(
        remove_duplicates(
            filter_last_48_hours(
                news_items
            )
        )
    )

    news_table = parse_market_prices(
        news_items
    )

    combined = []

    seen = set()

    for row in live_market + news_table:

        key = tuple(
            str(
                row.get(
                    field,
                    ""
                )
            )
            for field in (
                "date",
                "apmc",
                "crop",
                "min_price",
                "max_price",
            )
        )

        if key in seen:
            continue

        seen.add(key)

        combined.append(
            {
                "date": str(
                    row.get(
                        "date",
                        ""
                    )
                ),

                "apmc": str(
                    row.get(
                        "apmc",
                        ""
                    )
                ),

                "crop": str(
                    row.get(
                        "crop",
                        ""
                    )
                ),

                "min_price": str(
                    row.get(
                        "min_price",
                        ""
                    )
                ),

                "max_price": str(
                    row.get(
                        "max_price",
                        ""
                    )
                ),
            }
        )

    return {

        "ok": True,

        "updated_at":
            now_local_string(),

        "items": [
            public_news_item(item)
            for item in news_items[:24]
        ],

        "market_table":
            combined[:100],

        "live":
            bool(
                live_market
                or news_items
            ),

        "live_apmc":
            bool(live_market),

        "news_available":
            bool(news_items),

        "source":
            (
                "Live APMC + Google News RSS"
                if live_market
                else "Google News RSS"
            ),

        "errors":
            errors[:6],
    }


# ============================================================
# ROOT
# ============================================================

def _root_response():

    return {

        "ok": True,

        "service":
            "smart-agri-ai",

        "version":
            APP_VERSION,
    }


@app.get("/")
def root():

    return _root_response()


# Render / monitoring માટે HEAD પણ
@app.head("/")
def root_head():

    return None


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/v1/health")
def health():

    return {

        "ok": True,

        "service":
            "smart-agri-ai",

        "version":
            APP_VERSION,

        "agent_loaded":
            _agent is not None,

        "groq_configured":
            bool(
                os.getenv(
                    "GROQ_API_KEY",
                    ""
                ).strip()
            ),

        "gemini_configured":
            bool(
                os.getenv(
                    "GEMINI_API_KEY",
                    ""
                ).strip()
            ),

        "mandi_configured":
            bool(MANDI_API_URL),

        "text_provider":
            "groq",

        "text_model":
            GROQ_MODEL,

        "vision_provider":
            "gemini",

        "vision_model":
            VISION_MODEL,
    }


# ============================================================
# RULE BASED ANSWER
# ============================================================

def rule_based_answer(
    question: str,
    context: dict | None,
) -> str:

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
            ""
        )
        or ""
    ).strip()

    if not crop and _agent:

        crops = getattr(
            _agent,
            "CROPS",
            {}
        )

        aliases = getattr(
            _agent,
            "ROMAN_ALIASES",
            {}
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

    data = getattr(
        _agent,
        "CROP_DATA",
        {}
    ) if _agent else {}

    profile = (
        data.get(
            crop,
            {}
        )
        if crop
        else {}
    )

    # --------------------------------------------------------
    # WATER
    # --------------------------------------------------------

    if any(
        word in q
        for word in (
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
            "છેલ્લો વરસાદ, જમીનનો પ્રકાર અને પાકની હાલની અવસ્થા જણાવશો તો સલાહ વધુ ચોક્કસ કરી શકું."
        )

    # --------------------------------------------------------
    # FERTILIZER
    # --------------------------------------------------------

    if any(
        word in q
        for word in (
            "ખાતર",
            "પોષણ",
            "fertilizer",
            "npk",
        )
    ):

        return (
            f"🧪 {crop or 'પાક'} માટે પોષણ:\n"
            "માટી પરીક્ષણ આધારિત N-P-K અને સૂક્ષ્મ તત્ત્વો નક્કી કરો. "
            "પાકની અવસ્થા પ્રમાણે ખાતર વહેંચીને આપવું યોગ્ય રહે છે. "
            "માટી રિપોર્ટ વગર ચોક્કસ ડોઝ નક્કી ન કરવો."
        )

    # --------------------------------------------------------
    # DISEASE / PEST
    # --------------------------------------------------------

    if any(
        word in q
        for word in (
            "રોગ",
            "જીવાત",
            "ઈયળ",
            "ઇયળ",
            "પાન પીળ",
            "disease",
            "pest",
        )
    ):

        diseases = (
            getattr(
                _agent,
                "_DISEASES",
                {}
            ).get(
                crop,
                []
            )
            if _agent
            else []
        )

        extra = "\n".join(
            f"• {item}"
            for item in diseases[:3]
        )

        return (
            f"🔎 {crop or 'પાક'} માટે રોગ/જીવાત તપાસ:\n"
            f"{extra or 'પાન, ડાંઠ, મૂળ અને ફળનું નજીકથી નિરીક્ષણ કરો અને પાણી/પોષણની સ્થિતિ તપાસો.'}\n"
            "ફોટો, પાકની ઉંમર અને નુકસાનનું પ્રમાણ આપશો તો વધુ મદદ કરી શકું."
        )

    # --------------------------------------------------------
    # CROP PROFILE
    # --------------------------------------------------------

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
# GROQ CHAT
# ============================================================

def groq_client():

    key = (
        os.getenv(
            "GROQ_API_KEY",
            ""
        ).strip()
    )

    if not key:
        return None

    return OpenAI(
        api_key=key,
        base_url="https://api.groq.com/openai/v1",
    )


@app.post("/api/v1/ai/ask")
def ask(req: Ask):

    question = (
        req.question
        or ""
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

    context = req.context or {}

    prompt = (
        f"ખેડૂત પ્રશ્ન: {question}\n"
        f"ખેડૂત સંદર્ભ: {context}\n\n"
        "આ પ્રશ્નનો સીધો, ઉપયોગી અને વ્યવહારુ જવાબ "
        "ગુજરાતી ભાષામાં આપો. "
        "પાક, પાકની અવસ્થા, જમીન, સિંચાઈ, હવામાન "
        "અને ઉપલબ્ધ સંદર્ભને ધ્યાનમાં લો. "
        "પ્રશ્ન જે પૂછે છે તેનો જ જવાબ આપો. "
        "માહિતી અધૂરી હોય તો જરૂરી માહિતી પૂછો. "
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
            response
            .choices[0]
            .message
            .content
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
            detail=f"Groq AI error: {exc}",
        )


# ============================================================
# GEMINI VISION
# ============================================================

def gemini_client():

    key = (
        os.getenv(
            "GEMINI_API_KEY",
            ""
        ).strip()
    )

    if not key:
        return None

    return genai.Client(
        api_key=key
    )


@app.post("/api/v1/ai/diagnose")
async def diagnose(

    image: UploadFile = File(...),

    crop: str = Form(""),

    context: str = Form(""),
):

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
                "Vision AI માટે Renderમાં "
                "GEMINI_API_KEY સેટ કરો અને "
                "VISION_MODEL ચકાસો."
            ),

            "mode":
                "agent_unavailable",
        }

    mime = (
        image.content_type
        or "image/jpeg"
    )

    if "/" not in mime:
        mime = "image/jpeg"

    prompt = (
        f"આ ખેતીના પાકનો ફોટો છે. "
        f"પાક: {crop or 'અજ્ઞાત'}. "
        f"સંદર્ભ: {context}.\n\n"

        "ફોટામાં દેખાતા લક્ષણોનું ધ્યાનપૂર્વક "
        "નિરીક્ષણ કરો. જવાબ ગુજરાતી ભાષામાં આપો.\n"

        "આ ક્રમમાં જવાબ આપો:\n"

        "1) દેખાતા લક્ષણો\n"

        "2) 1-3 સંભવિત કારણો અથવા રોગ/જીવાત\n"

        "3) તરત કરી શકાય તેવી IPM/સલામતી સલાહ\n"

        "4) ક્યારે સ્થાનિક કૃષિ નિષ્ણાત/KVK/લેબની "
        "ચકાસણી લેવી\n\n"

        "ફોટા પરથી નિશ્ચિત નિદાન ન કરો અને "
        "ચોક્કસ pesticide dose, concentration "
        "અથવા brand ન આપો. "

        "ફોટો અસ્પષ્ટ હોય તો તે સ્પષ્ટ જણાવો. "

        "જવાબ સંપૂર્ણ આપો."
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

                thinking_config=(
                    types.ThinkingConfig(
                        thinking_budget=0
                    )
                ),
            ),
        )

        answer = (
            response.text
            or ""
        ).strip()

        return {

            "answer":
                answer
                or "ફોટામાંથી પૂરતો જવાબ મળ્યો નથી.",

            "mode":
                "gemini_vision",

            "model":
                VISION_MODEL,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=502,
            detail=(
                f"Vision AI error: {exc}"
            ),
        )
