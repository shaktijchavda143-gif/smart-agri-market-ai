import os
import re
import html
import base64
import importlib.util
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from openai import OpenAI

from google import genai
from google.genai import types

# ============================================================
# APP CONFIG
# ============================================================

APP_VERSION = "10.3 Android API Bridge - VISION & NEWS FIXED"

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b",
)

VISION_MODEL = os.getenv(
    "GEMINI_VISION_MODEL",
    "gemini-2.5-flash",
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

MANDI_API_URL = os.getenv("MANDI_API_URL", "")
MANDI_API_KEY = os.getenv("MANDI_API_KEY", "")


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Smart Agri-Market AI",
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
# SMART AGRI AGENT
# ============================================================

AGENT = None

try:
    agent_path = os.path.join(
        os.path.dirname(__file__),
        "smart_agri_agent.py",
    )

    if os.path.exists(agent_path):
        spec = importlib.util.spec_from_file_location(
            "smart_agri_agent",
            agent_path,
        )

        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            AGENT = module

except Exception as e:
    # પ્રોડક્શન સિસ્ટમ માટે લોગિંગ અત્યંત આવશ્યક છે
    print(f"Failed to load smart_agri_agent: {e}")
    AGENT = None


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM = """
તમે Smart Agri-Market AI ના ગુજરાતી કૃષિ સહાયક છો.

જવાબ સરળ, સ્પષ્ટ અને ખેડૂત માટે ઉપયોગી ગુજરાતીમાં આપો.

જ્યારે પાક, રોગ, જીવાત, દવા, ખાતર અથવા ખેતી વિશે પૂછવામાં આવે:
- પાકનું નામ સ્પષ્ટ કરો.
- સમસ્યા/લક્ષણ સમજાવો.
- શક્ય કારણ જણાવો.
- વ્યવહારુ ઉપાય આપો.
- દવા/કૃષિ રસાયણની સલાહ આપતી વખતે label મુજબ ઉપયોગ અને સ્થાનિક કૃષિ અધિકારીની સલાહ લેવાની નોંધ આપો.
- ખોટી ખાતરી ન આપો.
- ફોટો પરથી diagnosis હોય તો શું દેખાય છે અને શું ખાતરીથી કહી શકાય નહીં તે સ્પષ્ટ કરો.

જવાબ અધૂરો ન રાખો.
પૂર્ણ અને વાંચી શકાય તેવો જવાબ આપો.
"""

# ============================================================
# MODELS
# ============================================================

class Ask(BaseModel):
    question: str
    context: Optional[dict] = None


# ============================================================
# COMMON HELPERS
# ============================================================

def now_local_string() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%d-%m-%Y %H:%M")

def norm(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())

def clean_html(value: Any) -> str:
    if not value:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<script.*?>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ============================================================
# RSS DATE PARSER
# ============================================================

def parse_rss_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None

    try:
        dt = parsedate_to_datetime(raw)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        iso = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M %z",
        "%d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M %z",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue

    return None

def rss_datetime(value: Any) -> str:
    dt = parse_rss_datetime(value)
    if dt is None:
        return ""
    return dt.strftime("%d-%m-%Y %H:%M")


# ============================================================
# NEWS FILTERS
# ============================================================

def filter_recent_news(items: list[dict], hours: int = 168) -> list[dict]:
    """
    અગાઉની 48 કલાકની કડક મર્યાદા દૂર કરી, અહીં 168 કલાક (7 દિવસ) નો સમયગાળો 
    વ્યાખ્યાયિત કરવામાં આવ્યો છે. આનાથી પ્રાદેશિક સમાચાર ફીડમાં ખાલી પરિણામો 
    મળવાની શક્યતા નહિવત્ થઈ જશે.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    result: list[dict] = []

    for item in items:
        dt = item.get("_published_dt")
        if not isinstance(dt, datetime):
            continue
        if cutoff <= dt <= now + timedelta(minutes=10):
            result.append(item)

    return result

def remove_duplicates(items: list[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()

    for item in items:
        title = norm(item.get("title"))
        link = norm(item.get("link"))
        key = title or link
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result

def sort_latest(items: list[dict]) -> list[dict]:
    return sorted(
        items,
        key=lambda item: (
            item.get("_published_dt")
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )

def public_news_item(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "source": item.get("source", ""),
        "published_at": item.get("published_at", ""),
        "link": item.get("link", ""),
        "category": item.get("category", ""),
    }


# ============================================================
# HTTP FETCH
# ============================================================

def _fetch_url(url: str, timeout: int = 15, retries: int = 2) -> bytes:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Linux; Android 10) "
            "AppleWebKit/537.36 "
            "Chrome/120 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Language": "gu-IN,gu;q=0.9,en-IN;q=0.8,en;q=0.7",
    }
    last_error = None
    for _ in range(max(1, retries)):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"RSS fetch failed: {last_error}")


# ============================================================
# GOOGLE NEWS RSS
# ============================================================

def build_google_news_url(query: str) -> str:
    """
    અહીંથી 'when:2d' પેરામીટર દૂર કરવામાં આવ્યું છે, કારણ કે Google News 
    પ્રાદેશિક ભાષાઓમાં કડક સમય મર્યાદા (operator) માટે ખાલી ફીડ પરત કરતું હતું.
    આનાથી ડેટા સ્ટારવેશનની સમસ્યા કાયમ માટે ઉકેલાશે.
    """
    params = {
        "q": query,
        "hl": "gu",
        "gl": "IN",
        "ceid": "IN:gu",
    }
    return (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    )

def fetch_google_news(query: str, category: str = "", timeout: int = 15) -> tuple[list[dict], Optional[str]]:
    url = build_google_news_url(query)
    try:
        data = _fetch_url(url, timeout=timeout, retries=2)
        root = ET.fromstring(data)
    except Exception as exc:
        return [], str(exc)

    items: list[dict] = []
    for xml_item in root.findall(".//item"):
        title = clean_html(xml_item.findtext("title"))
        link = (xml_item.findtext("link") or "").strip()
        description = clean_html(xml_item.findtext("description"))
        pub_raw = (xml_item.findtext("pubDate") or "").strip()
        source_node = xml_item.find("source")
        source = ""

        if source_node is not None:
            source = clean_html(source_node.text or "")

        if not source and " - " in title:
            source = title.rsplit(" - ", 1)[-1].strip()

        clean_title = title
        if source and clean_title.endswith(f" - {source}"):
            clean_title = clean_title[: -(len(source) + 3)].strip()

        published_dt = parse_rss_datetime(pub_raw)

        if not clean_title or not link:
            continue

        items.append(
            {
                "title": clean_title,
                "source": source or "Google News",
                "published_at": rss_datetime(pub_raw),
                "link": link,
                "description": description,
                "category": category,
                "_published_dt": published_dt,
            }
        )
    return items, None


# ============================================================
# MULTI-QUERY NEWS ENGINE
# ============================================================

def fetch_news_from_queries(queries: list[str], category: str, max_items: int = 20) -> tuple[list[dict], list[str]]:
    all_items: list[dict] = []
    errors: list[str] = []

    for query in queries:
        items, error = fetch_google_news(query=query, category=category)
        if error:
            errors.append(f"{query}: {error}")
        all_items.extend(items)

    all_items = remove_duplicates(all_items)
    
    # સમય મર્યાદા વધારીને 168 કલાક કરી છે, જેથી તાજા સમાચાર હંમેશા ઉપલબ્ધ રહે
    all_items = filter_recent_news(all_items, hours=168) 
    all_items = sort_latest(all_items)

    return all_items[:max_items], errors


# ============================================================
# NEWS RESPONSE
# ============================================================

def build_news_response(items: list[dict], errors: Optional[list[str]] = None, crop: str = "") -> dict:
    errors = errors or []
    public_items = [public_news_item(item) for item in items]
    return {
        "ok": True,
        "updated_at": now_local_string(),
        "items": public_items,
        "live": False,
        "source": "Google News RSS / original publishers",
        "errors": errors,
        "crop": crop,
    }


# ============================================================
# AGRICULTURE NEWS QUERIES
# ============================================================

AGRI_GENERAL_QUERIES = [
    "કૃષિ સમાચાર ગુજરાત",
    "ખેડૂત સમાચાર ગુજરાત",
    "ખેડૂત યોજના ગુજરાત",
    "ખેડૂત સહાય ગુજરાત",
    "કૃષિ યોજના ગુજરાત",
    "agriculture Gujarat farmers",
    "Gujarat farmers agriculture",
]


# ============================================================
# WEATHER NEWS
# ============================================================

WEATHER_QUERIES = [
    ("🌧️ IMD Gujarat", ["IMD Gujarat weather", "હવામાન વિભાગ ગુજરાત વરસાદ આગાહી"]),
    ("☀️ Ambalal Patel", ["આંબાલાલ પટેલ હવામાન ગુજરાત"]),
    ("🌦️ Paresh Goswami", ["પરેશ ગૌસ્વામી હવામાન ગુજરાત"]),
    ("📰 Gujarat Weather", ["ગુજરાત હવામાન વરસાદ આગાહી", "Gujarat rainfall forecast"]),
]

# ============================================================
# AGRICULTURE CATEGORIES
# ============================================================

AGRI_CATEGORIES = [
    ("🌱 કૃષિ સમાચાર", ["કૃષિ સમાચાર ગુજરાત", "ખેડૂત સમાચાર ગુજરાત"]),
    ("🦠 રોગ-જીવાત એલર્ટ", ["પાક રોગ જીવાત ગુજરાત", "કપાસ રોગ જીવાત ગુજરાત", "મગફળી રોગ જીવાત ગુજરાત"]),
    ("🏛 સરકારની કૃષિ યોજનાઓ", ["ખેડૂત યોજના ગુજરાત", "ખેડૂત સહાય ગુજરાત", "કૃષિ યોજના ગુજરાત સરકાર"]),
    ("🚜 કૃષિ ટેક્નોલોજી", ["કૃષિ ટેક્નોલોજી ગુજરાત", "ખેતી આધુનિક ટેક્નોલોજી"]),
]


# ============================================================
# ENDPOINTS
# ============================================================

@app.get("/api/v1/news")
def legacy_news(crop: str = ""):
    crop = crop.strip()
    queries: list[str] = []
    if crop:
        queries.extend([
            f"{crop} ગુજરાત ખેતી",
            f"{crop} ખેડૂત ગુજરાત",
            f"{crop} બજાર ભાવ ગુજરાત",
        ])
    queries.extend(AGRI_GENERAL_QUERIES)

    items, errors = fetch_news_from_queries(queries=queries, category="કૃષિ સમાચાર", max_items=20)
    response = build_news_response(items=items, errors=errors, crop=crop)
    response["category"] = "કૃષિ સમાચાર"
    return response

@app.get("/api/v1/weather/news")
def weather_news():
    all_items: list[dict] = []
    errors: list[str] = []
    for category, queries in WEATHER_QUERIES:
        items, query_errors = fetch_news_from_queries(queries=queries, category=category, max_items=10)
        all_items.extend(items)
        errors.extend(query_errors)

    all_items = remove_duplicates(all_items)
    all_items = sort_latest(all_items)[:30]
    return build_news_response(items=all_items, errors=errors)

@app.get("/api/v1/agri/news")
def agriculture_news():
    all_items: list[dict] = []
    errors: list[str] = []
    for category, queries in AGRI_CATEGORIES:
        items, query_errors = fetch_news_from_queries(queries=queries, category=category, max_items=10)
        all_items.extend(items)
        errors.extend(query_errors)

    all_items = remove_duplicates(all_items)
    all_items = sort_latest(all_items)[:40]
    return build_news_response(items=all_items, errors=errors)


# ============================================================
# MARKET PRICE PARSER & LIVE MANDI
# ============================================================
PRICE_NUMBER = r"(?:₹\s*)?\d+(?:,\d+)*(?:\.\d+)?"
PRICE_RANGE_PATTERNS = [
    re.compile(rf"({PRICE_NUMBER})\s*[-–—]\s*({PRICE_NUMBER})"),
    re.compile(rf"({PRICE_NUMBER})\s*(?:થી|to)\s*({PRICE_NUMBER})", re.I),
]

def _price_to_string(value: str) -> str:
    value = value.replace("₹", "").replace(",", "").strip()
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else str(number)
    except Exception:
        return value

def _extract_price_range(text: str) -> Optional[tuple[str, str]]:
    for pattern in PRICE_RANGE_PATTERNS:
        match = pattern.search(text)
        if match:
            return (_price_to_string(match.group(1)), _price_to_string(match.group(2)))
    rupees = re.findall(r"₹\s*(\d[\d,]*(?:\.\d+)?)", text)
    if len(rupees) >= 2:
        return (_price_to_string(rupees[0]), _price_to_string(rupees[1]))
    return None

def _extract_single_prices(text: str) -> Optional[tuple[str, str]]:
    min_patterns = [rf"(?:min|minimum|ન્યૂનતમ|લઘુતમ)\s*[:\-]?\s*{PRICE_NUMBER}", rf"(?:મિનિમમ)\s*[:\-]?\s*{PRICE_NUMBER}"]
    max_patterns = [rf"(?:max|maximum|મહત્તમ)\s*[:\-]?\s*{PRICE_NUMBER}", rf"(?:મેક્સિમમ)\s*[:\-]?\s*{PRICE_NUMBER}"]

    min_value = max_value = None
    for pattern in min_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            number = re.search(PRICE_NUMBER, match.group(0))
            if number:
                min_value = _price_to_string(number.group(0))
                break
    for pattern in max_patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            number = re.search(PRICE_NUMBER, match.group(0))
            if number:
                max_value = _price_to_string(number.group(0))
                break

    if min_value and max_value:
        return min_value, max_value
    return None

def _detect_crop(text: str) -> str:
    crops = {
        "મગફળી": ["મગફળી", "groundnut", "peanut"],
        "કપાસ": ["કપાસ", "cotton"],
        "જીરૂ": ["જીરૂ", "જીરું", "cumin"],
        "ડુંગળી": ["ડુંગળી", "onion"],
        "બટાકા": ["બટાકા", "potato"],
        "ટામેટા": ["ટામેટા", "tomato"],
        "પપૈયા": ["પપૈયા", "papaya"],
        "લીંબુ": ["લીંબુ", "lemon"],
    }
    normalized = norm(text)
    for crop, aliases in crops.items():
        if any(norm(alias) in normalized for alias in aliases):
            return crop
    return ""

def _detect_apmc(text: str) -> str:
    apmcs = [
        "રાજકોટ APMC", "જામનગર APMC", "જુનાગઢ APMC", "જૂનાગઢ APMC",
        "ગોંડલ APMC", "મહુવા APMC", "ગોંડલ માર્કેટ", "રાજકોટ માર્કેટ"
    ]
    for apmc in apmcs:
        if norm(apmc) in norm(text):
            return apmc
    match = re.search(r"([A-Za-zÀ-ÿ\u0900-\u097F\u0A80-\u0AFF\s]+APMC)", text, flags=re.I)
    if match:
        return match.group(1).strip()
    return ""

def parse_market_prices(item: dict) -> list[dict]:
    text = clean_html(" ".join([item.get("title", ""), item.get("description", "")]))
    price_range = _extract_price_range(text) or _extract_single_prices(text)
    if not price_range:
        return []

    min_price, max_price = price_range
    crop = _detect_crop(text)
    apmc = _detect_apmc(text)

    if not crop or not apmc:
        return []

    return [{
        "date": item.get("published_at", ""),
        "apmc_name": apmc,
        "crop": crop,
        "min_price": min_price,
        "max_price": max_price,
        "source": item.get("source", ""),
        "title": item.get("title", ""),
        "link": item.get("link", "")
    }]

def fetch_live_mandi() -> list[dict]:
    if not MANDI_API_URL:
        return []
    try:
        headers = {"User-Agent": "Smart-Agri-Market-AI/10.3"}
        if MANDI_API_KEY:
            headers["X-API-Key"] = MANDI_API_KEY
        request = urllib.request.Request(MANDI_API_URL, headers=headers)
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read().decode("utf-8", errors="replace")
        
        import json
        payload = json.loads(raw)
        rows = []
        if isinstance(payload, dict):
            for key in ("data", "records", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    rows = value
                    break
        elif isinstance(payload, list):
            rows = payload

        return [row for row in rows if isinstance(row, dict)]
    except Exception:
        return []

@app.get("/api/v1/market/news")
def market_news():
    live_items = fetch_live_mandi()
    queries = [
        "APMC Gujarat market price",
        "Rajkot APMC market price",
        "groundnut market price Gujarat",
        "cotton market price Gujarat",
    ]
    news_items, errors = fetch_news_from_queries(queries=queries, category="બજાર ભાવ સમાચાર", max_items=40)

    market_table: list[dict] = []
    for item in news_items:
        market_table.extend(parse_market_prices(item))

    return {
        "ok": True,
        "updated_at": now_local_string(),
        "items": [public_news_item(item) for item in news_items],
        "market_table": market_table,
        "live": bool(live_items),
        "source": "Live APMC API + Google News RSS / original publishers",
        "errors": errors,
    }

# ============================================================
# ROOT & HEALTH
# ============================================================

@app.get("/")
def root():
    return {"ok": True, "service": "Smart Agri-Market AI", "version": APP_VERSION, "status": "running"}

@app.head("/")
def root_head():
    return None

@app.get("/api/v1/health")
def health():
    return {"ok": True, "status": "healthy", "service": "smart-agri-market-ai", "version": APP_VERSION}


# ============================================================
# AI INTEGRATIONS
# ============================================================

def rule_based_answer(question: str) -> Optional[str]:
    if AGENT is None:
        return None
    try:
        aliases = getattr(AGENT, "ROMAN_ALIASES", {})
        crops = getattr(AGENT, "CROPS", {})
        crop_data = getattr(AGENT, "CROP_DATA", {})
        q = norm(question)
        detected_crop = None

        for crop_name, data in (crops.items() if isinstance(crops, dict) else []):
            if norm(crop_name) in q:
                detected_crop = crop_name
                break
            if isinstance(aliases, dict):
                for alias, mapped in aliases.items():
                    if norm(alias) in q and (mapped == crop_name or norm(str(mapped)) == norm(crop_name)):
                        detected_crop = crop_name
                        break
            if detected_crop:
                break

        if not detected_crop:
            return None

        data = crop_data.get(detected_crop)
        if not data:
            return None

        if isinstance(data, dict):
            parts = [f"પાક: {detected_crop}"]
            for key, value in data.items():
                if value not in (None, "", [], {}):
                    parts.append(f"{key}: {value}")
            return "\n".join(parts)
        return str(data)
    except Exception:
        return None

def groq_client() -> OpenAI:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY is not configured")
    return OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

def gemini_client() -> genai.Client:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured")
    return genai.Client(api_key=GEMINI_API_KEY)

@app.post("/api/v1/ai/ask")
def ai_ask(payload: Ask):
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    try:
        rule_answer = rule_based_answer(question)
        if rule_answer:
            return {"answer": rule_answer, "mode": "rule_based", "model": "local-rule-engine"}
    except Exception:
        pass

    client = groq_client()
    context_text = f"\n\nContext:\n{payload.context}" if payload.context else ""

    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question + context_text},
            ],
            temperature=0.2,
        )
        answer = (completion.choices[0].message.content or "").strip()
        return {"answer": answer, "mode": "groq", "model": GROQ_MODEL}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI request failed: {exc}")


@app.post("/api/v1/ai/diagnose")
async def ai_diagnose(
    image: UploadFile = File(...),
    crop: Optional[str] = Form(default=None),
    context: Optional[str] = Form(default=None),
):
    """
    અપડેટ: Form() ને બદલે Form(default=None) નો ઉપયોગ જેથી પાયડેન્ટિક 
    ક્લાયન્ટના પેલોડને કડક રીતે નકારીને 422 એરર જનરેટ ન કરે.
    """
    image_bytes = await image.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Image is empty")

    if len(image_bytes) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image too large")

    client = gemini_client()
    mime_type = image.content_type or "image/jpeg"
    
    safe_crop = crop.strip() if crop else "માહિતી આપવામાં આવી નથી"
    safe_context = context.strip() if context else "કોઈ માહિતી નથી"

    prompt = f"""
આ ફોટો ખેડૂત દ્વારા મોકલવામાં આવ્યો છે.

પાક: {safe_crop}
વધારાની માહિતી: {safe_context}

ફોટાનું ધ્યાનપૂર્વક નિરીક્ષણ કરો.
જવાબ સંપૂર્ણ ગુજરાતીમાં આપો.
જવાબમાં આ મુદ્દાઓ શક્ય હોય ત્યાં સુધી આપો:
1. ફોટામાં શું દેખાય છે
2. પાક/છોડની સંભવિત સમસ્યા
3. સંભવિત રોગ અથવા જીવાત
4. શા માટે આવું થઈ શકે
5. શું કરવું
6. દવા/ઉપચારની સામાન્ય સલાહ
7. સાવચેતી
"""

    try:
        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type,
        )

        # અપડેટ: અગાઉના કોડમાંથી thinking_config સંપૂર્ણપણે દૂર કરવામાં આવ્યું છે.
        # આનાથી મોડેલને અનુકૂળ ન હોય તેવા કન્ફિગરેશન પેરામીટર્સના કારણે આવતી 
        # 400 Bad Request એરર ટાળી શકાશે.
        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[image_part, prompt],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                temperature=0.2,
                max_output_tokens=4096,
            ),
        )

        answer = (getattr(response, "text", None) or "").strip()
        if not answer:
            answer = "ફોટામાંથી પૂરતી માહિતી મળી નથી. કૃપા કરીને પાકનો થોડો વધુ સ્પષ્ટ ફોટો મોકલો."

        return {
            "answer": answer,
            "mode": "gemini_vision",
            "model": VISION_MODEL,
        }

    except Exception as exc:
        print(f"Gemini API Error: {exc}") # વ્યવસ્થિત એક્સેપ્શન હેન્ડલિંગ માટે
        raise HTTPException(status_code=502, detail=f"Gemini Vision request failed: {exc}")

# ============================================================
# STARTUP LOG
# ============================================================

@app.on_event("startup")
def startup_log():
    print(f"Smart Agri-Market AI started: {APP_VERSION}")
