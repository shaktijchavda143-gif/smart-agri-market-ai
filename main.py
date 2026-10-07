# -*- coding: utf-8 -*-
"""Smart Agri-Market AI HTTP backend.
Wraps the supplied Smart Agri-Market Agent so the Android app can call it.
"""
import os
import asyncio
import base64
import importlib.util
import urllib.parse
import urllib.request
import httpx
import re
import time
import json
import threading
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

try:
    from panchang_service import get_panchang
except Exception as _panchang_import_error:
    get_panchang = None
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from google import genai
from google.genai import types

APP_VERSION = "13.4 GROQ GPT-OSS PRIMARY SMART GUIDE + AGMARKNET 2.0"
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.7").strip() or "grok-4.7"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.6-flash").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

app = FastAPI(title="Smart Agri Market AI Backend", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

# Load the user's supplied agent file without executing its CLI main().
_agent = None
try:
    _path = os.path.join(os.path.dirname(__file__), "smart_agri_agent.py")
    _spec = importlib.util.spec_from_file_location("smart_agri_agent", _path)
    if _spec and _spec.loader:
        _agent = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_agent)
except Exception as exc:
    _agent = None
    print(f"Agent import warning: {exc}")

SYSTEM = (
    "તમે Smart Agri-Market AI ગુજરાતી ખેડૂત સહાયક છો. "
    "જવાબ સરળ, વ્યવહારુ અને પાક/ખેડૂતના સંદર્ભ મુજબ આપો. "
    "પાક, સિંચાઈ, પોષણ, રોગ-જીવાત, હવામાન અને બજાર અંગે માર્ગદર્શન આપો. "
    "ફોટો આધારિત જવાબમાં માત્ર ટૂંકું નિદાન ન આપો; ખેડૂતને કામ લાગે એટલી વિગત આપો. "
    "દવા અંગે માત્ર ફોટાના લક્ષણો અને પાકને અનુરૂપ સંભવિત નિયંત્રણ વિકલ્પો જણાવો; ચોક્કસ દવા/ડોઝ ત્યારે જ લખો જ્યારે પાક-સમસ્યા પૂરતી વિશ્વસનીય રીતે ઓળખાય અને નોંધાયેલ લેબલ/સ્થાનિક કૃષિ ભલામણ સાથે મેળ ખાતી હોય. "
    "નિશ્ચિત રોગનિદાન અથવા અનિશ્ચિત pesticide doseને તથ્ય તરીકે રજૂ ન કરો; જરૂર પડે ત્યારે સ્થાનિક કૃષિ નિષ્ણાત/KVK/લેબ ચકાસણી જરૂરી હોવાનું સ્પષ્ટ જણાવો."
)

class Ask(BaseModel):
    question: str
    context: dict | None = None


def xai_client():
    """Primary Smart Guide provider: xAI Grok via the OpenAI-compatible API."""
    key = os.getenv("XAI_API_KEY", "").strip()
    return OpenAI(api_key=key, base_url="https://api.x.ai/v1") if key else None


def groq_client():
    """Primary Smart Guide provider: Groq using the OpenAI-compatible API."""
    key = os.getenv("GROQ_API_KEY", "").strip()
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1") if key else None


def norm(text: str) -> str:
    return " ".join((text or "").strip().lower().replace("-", " ").split())


def rule_based_answer(question: str, context: dict | None) -> str:
    """Use the supplied crop knowledge when no configured AI provider returns a response."""
    q = norm(question)
    ctx = context or {}
    selected = ctx.get("selected_crop") or {}
    crop = str(selected.get("name") or "").strip()
    if not crop and _agent:
        aliases = getattr(_agent, "ROMAN_ALIASES", {})
        crops = getattr(_agent, "CROPS", {})
        for key, name in crops.items():
            if norm(name) in q or norm(key) == q:
                crop = name
                break
        if not crop:
            for alias, name in aliases.items():
                if alias and alias in q:
                    crop = name
                    break

    data = getattr(_agent, "CROP_DATA", {}) if _agent else {}
    profile = data.get(crop, {}) if crop else {}

    if any(x in q for x in ("સિંચાઈ", "પાણી", "પિયત", "irrigation", "water")):
        return (
            f"💧 {crop or 'પાક'} માટે સિંચાઈ સલાહ:\n"
            f"{profile.get('પાણી', 'પાકની અવસ્થા, જમીનનો ભેજ અને વરસાદ પ્રમાણે સિંચાઈ કરો; પાણી ભરાવું ટાળો.')}\n"
            "છેલ્લો વરસાદ, જમીનનો પ્રકાર અને પાકની હાલની અવસ્થા જણાવશો તો સલાહ વધુ ચોક્કસ કરી શકું."
        )
    if any(x in q for x in ("ખાતર", "પોષણ", "fertilizer", "npk")):
        return (
            f"🧪 {crop or 'પાક'} માટે પોષણ:\n"
            "માટી પરીક્ષણ આધારિત N-P-K અને સૂક્ષ્મ તત્ત્વો નક્કી કરો. પાકની અવસ્થા પ્રમાણે ખાતર વહેંચીને આપવું વધુ યોગ્ય રહે છે. "
            "માટી રિપોર્ટ વગર ચોક્કસ ડોઝ નક્કી ન કરવો."
        )
    if any(x in q for x in ("રોગ", "જીવાત", "ઈયળ", "ઇયળ", "પાન પીળ", "disease", "pest")):
        disease = getattr(_agent, "_DISEASES", {}).get(crop, []) if _agent else []
        extra = "\n".join(f"• {x}" for x in disease[:3])
        return (
            f"🔎 {crop or 'પાક'} માટે રોગ/જીવાત તપાસ:\n"
            f"{extra or 'પાન, ડાંઠ, મૂળ અને ફળનું નજીકથી નિરીક્ષણ કરો અને પાણી/પોષણની સ્થિતિ તપાસો.'}\n"
            "ફોટો, પાકની ઉંમર અને નુકસાનનું પ્રમાણ આપશો તો વધુ મદદ કરી શકું. દવા/માત્રા સ્થાનિક નોંધાયેલ ભલામણ મુજબ જ નક્કી કરો."
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
        "🤖 ખેડૂત સહાયક: પ્રશ્નનો વધુ ચોક્કસ જવાબ આપવા પાકનું નામ, પાકની ઉંમર/વાવણી તારીખ, "
        "જમીનનો પ્રકાર, છેલ્લું સિંચાઈ/વરસાદ અને સમસ્યાના લક્ષણો લખો. ફોટો હોય તો મોકલી શકો."
    )


@app.get("/")
def root():
    return {"ok": True, "service": "smart-agri-ai", "version": APP_VERSION}


@app.get("/api/v1/health")
def health():
    return {
        "ok": True,
        "service": "smart-agri-ai",
        "version": APP_VERSION,
        "agent_loaded": _agent is not None,
        "xai_configured": bool(os.getenv("XAI_API_KEY", "").strip()),
        "xai_model": XAI_MODEL,
        "primary_ai_provider": "groq_gpt_oss",
        "groq_configured": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "groq_model": GROQ_MODEL,
        "gemini_vision_configured": bool(GEMINI_API_KEY),
        "gemini_vision_model": GEMINI_VISION_MODEL,
        "mandi_api_configured": bool(os.getenv("DATA_GOV_API_KEY", "").strip()),
        "mandi_rate_limit_cooldown_seconds": MANDI_RATE_LIMIT_COOLDOWN_SECONDS,
        "news_service": "google-news-rss",
        "model": GROQ_MODEL,
    }


@app.get("/api/v1/farmer-services/panchang/today")
def farmer_services_panchang_today(date_str: str | None = None, lat: float = 23.0225, lon: float = 72.5714):
    """Gujarati Gujarat-Kartikadi panchang backed by the local audited engine."""
    if get_panchang is None:
        raise HTTPException(status_code=503, detail="Panchang service is not installed")
    from datetime import date as _date
    try:
        day = _date.fromisoformat(date_str) if date_str else _date.today()
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid coordinates")
        return get_panchang(day, float(lat), float(lon))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Panchang service હાલમાં ઉપલબ્ધ નથી. ફરી પ્રયાસ કરો.") from exc


NEWS_DEFAULT_MAX_AGE_HOURS = 48
NEWS_FALLBACK_MAX_AGE_HOURS = 168

class _VisibleTextParser(HTMLParser):
    """Convert publisher HTML to readable text while preserving table/row boundaries."""
    SKIP_TAGS = {"script", "style", "noscript", "svg"}
    BLOCK_TAGS = {"tr", "p", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"}
    CELL_TAGS = {"td", "th"}
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
        elif not self.skip_depth:
            if tag in self.BLOCK_TAGS:
                self.parts.append("\n")
            elif tag in self.CELL_TAGS:
                # Keep table column boundaries. Without this delimiter an HTML row
                # such as <td>કપાસ</td><td>1171</td><td>1921</td> becomes
                # "કપાસ 1171 1921" and the price-row extractor cannot reliably
                # distinguish crop, low price and high price.
                self.parts.append(" | ")
    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth:
            if tag in self.BLOCK_TAGS:
                self.parts.append("\n")
            elif tag in self.CELL_TAGS:
                self.parts.append(" | ")
    def handle_data(self, data):
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip())
    def text(self):
        text = " ".join(self.parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n+ *", "\n", text)
        return text.strip()


def _html_to_text(html: str) -> str:
    parser = _VisibleTextParser()
    try:
        parser.feed(html or "")
        parser.close()
        return parser.text()
    except Exception:
        return ""


def _fetch_article_text(link: str, max_chars: int = 60000, timeout_seconds: int = 8) -> str:
    """Fetch one publisher page with a hard per-article timeout."""
    if not link:
        return ""
    try:
        req = urllib.request.Request(link, headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 Mobile Safari/537.36 SmartAgriMarketAI/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read(1200000)
            charset = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, "ignore")
        return _html_to_text(html)[:max_chars]
    except Exception:
        return ""


_LAST_NEWS_FETCH_DIAGNOSTICS = {"rss_search_failed": 0, "rss_items_seen": 0, "fresh_items_kept": 0}

NEWS_QUERY_SUFFIX = "when:2d"

# News source contract: only these named Gujarati publishers are allowed in the
# main News screen. Google News is only the transport/index; it is NOT itself
# treated as a publisher. This prevents Facebook/social posts from becoming
# News cards.
APPROVED_NEWS_SOURCES = {
    "TV9 Gujarati": ("tv9gujarati.com",),
    "ABP Asmita": ("gujarati.abplive.com", "abplive.com"),
    "Sandesh": ("sandesh.com",),
    "Gujarat Samachar": ("gujaratsamachar.com",),
    "Mumbai Samachar": ("bombaysamachar.com",),
    "Gujarat First": ("gujaratfirst.com",),
    "VTV Gujarati": ("vtvgujarati.com",),
    "GSTV": ("gstv.in",),
    "News18 Gujarati": ("gujarati.news18.com", "news18.com"),
    "Zee 24 Kalak": ("zee24kalak.in", "zee24kalak.com", "zeenews.india.com"),
    "Jamavat": ("jamawat.com",),
}

# Each publisher gets its own farmer-focused Google News query. Google News is
# only the transport/index; the final article URL must still belong to the
# publisher domain above. The list is intentionally broader than the original
# five-source contract so one publisher cannot monopolise the News screen.
NEWS_PUBLISHER_QUERIES = {
    "TV9 Gujarati": 'site:tv9gujarati.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "ABP Asmita": 'site:gujarati.abplive.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "Sandesh": 'site:sandesh.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "Gujarat Samachar": 'site:gujaratsamachar.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "Mumbai Samachar": 'site:bombaysamachar.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "Gujarat First": 'site:gujaratfirst.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "VTV Gujarati": 'site:vtvgujarati.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "GSTV": 'site:gstv.in (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "News18 Gujarati": 'site:gujarati.news18.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "Zee 24 Kalak": 'site:zee24kalak.in (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
    "Jamavat": 'site:jamawat.com (ખેડૂત OR ખેડૂતો OR ખેતી OR કૃષિ OR પાક OR APMC OR MSP OR સહાય OR સબસિડી)',
}


APPROVED_NEWS_SOURCE_NAMES = {
    "tv9 gujarati": "TV9 Gujarati",
    "tv9gujarati": "TV9 Gujarati",
    "abp asmita": "ABP Asmita",
    "abp gujarati": "ABP Asmita",
    "jamavat": "Jamavat",
    "જમાવટ": "Jamavat",
    "mumbai samachar": "Mumbai Samachar",
    "bombay samachar": "Mumbai Samachar",
    "મુંબઈ સમાચાર": "Mumbai Samachar",
    "gujarat first": "Gujarat First",
    "gujaratfirst": "Gujarat First",
    "sandesh": "Sandesh",
    "gujarat samachar": "Gujarat Samachar",
    "gujaratsamachar": "Gujarat Samachar",
    "vtv": "VTV Gujarati",
    "vtv gujarati": "VTV Gujarati",
    "gstv": "GSTV",
    "news18 gujarati": "News18 Gujarati",
    "news18": "News18 Gujarati",
    "zee 24 kalak": "Zee 24 Kalak",
    "zee24kalak": "Zee 24 Kalak",
}

# News business contract:
# - 48h is the primary window.
# - 168h is a fallback window only when the same request has no valid 48h item.
# - Publication timestamps are normalized to UTC before comparison.
# - Gujarati is detected from article text, not from a publisher allow-list.
# - Crop/category are not hard inclusion filters.
NEWS_DEFAULT_MAX_AGE_HOURS = 48
NEWS_FALLBACK_MAX_AGE_HOURS = 168

NEWS_CROP_SYNONYMS = {
    "મગફળી": ("મગફળી", "groundnut", "peanut"),
    "કપાસ": ("કપાસ", "cotton"),
    "જીરું": ("જીરું", "cumin", "jeera"),
    "એરંડા": ("એરંડા", "castor", "castor seed"),
    "ડુંગળી": ("ડુંગળી", "onion"),
    "ઘઉં": ("ઘઉં", "wheat"),
    "બાજરી": ("બાજરી", "bajra", "pearl millet"),
    "મકાઈ": ("મકાઈ", "maize", "corn"),
    "ધાણા": ("ધાણા", "coriander"),
    "તલ": ("તલ", "sesame"),
    "ચણા": ("ચણા", "gram", "chickpea"),
    "તુવેર": ("તુવેર", "tur", "arhar", "pigeon pea"),
    "મગ": ("મગ", "moong", "green gram"),
    "અડદ": ("અડદ", "urad", "black gram"),
    "બટાકા": ("બટાકા", "potato"),
    "ટામેટા": ("ટામેટા", "tomato"),
    "મરચાં": ("મરચાં", "chilli", "chili"),
    "લસણ": ("લસણ", "garlic"),
    "શેરડી": ("શેરડી", "sugarcane"),
}

NEWS_CROP_ENGLISH = {key: " ".join(v[1:]) for key, v in NEWS_CROP_SYNONYMS.items()}

NEWS_CATEGORY_TERMS = {
    "all": (),
    "agriculture": (
        "કૃષિ", "ખેડૂત", "ખેડૂતો", "ખેતી", "પાક", "agriculture", "agricultural",
        "farmer", "farmers", "farming", "crop", "crops", "cultivation", "harvest",
        "irrigation", "agri", "organic farming", "natural farming",
    ),
    "subsidy": (
        "સબસીડી", "સબસિડી", "સહાય", "યોજના", "ખેડૂત સહાય", "નાણાકીય સહાય",
        "subsidy", "scheme", "financial assistance", "support",
    ),
    "methods": (
        "કૃષિ પદ્ધતિ", "ખેતી પદ્ધતિ", "સિંચાઈ", "ટપક", "ડ્રિપ", "સજીવ", "પ્રાકૃતિક ખેતી",
        "ટેકનોલોજી", "બિયારણ", "ખાતર", "farming method", "irrigation", "drip",
        "technology", "cultivation technique", "yield improvement",
    ),
    "market": (
        "બજાર ભાવ", "મંડી", "મંડી ભાવ", "બજાર", "ભાવ", "એપીએમસી", "ટેકાના ભાવ",
        "apmc", "mandi", "market", "market rate", "price", "commodity", "msp",
        "support price", "buying", "selling",
    ),
}

GUJARAT_TERMS = (
    "ગુજરાત", "ગુજરાતના", "ગુજરાતમાં", "gujarat", "ahmedabad", "rajkot", "surat",
    "vadodara", "gandhinagar",
)

def _news_max_age_hours() -> int:
    # Environment may tighten the window but can never exceed the 7-day contract.
    try:
        value = int(os.getenv("NEWS_MAX_AGE_HOURS", str(NEWS_DEFAULT_MAX_AGE_HOURS)))
        return max(1, min(value, 48))
    except Exception:
        return NEWS_DEFAULT_MAX_AGE_HOURS


def _parse_news_date(value: str):
    """Parse an RSS date into an aware UTC datetime; never invent a date."""
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            # RSS dates without an offset are treated explicitly as UTC rather
            # than depending on the Render/server local timezone.
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _has_gujarati_text(text: str) -> bool:
    """Require genuine Gujarati Unicode content, while allowing mixed text."""
    value = text or ""
    gujarati = sum("\u0a80" <= ch <= "\u0aff" for ch in value)
    letters = sum(ch.isalpha() for ch in value)
    return gujarati >= 3 and (letters == 0 or gujarati / max(letters, 1) >= 0.12)


def _gujarati_score(title: str, description: str = "") -> float:
    text = " ".join(x for x in (title, description) if x).strip()
    letters = sum(ch.isalpha() for ch in text)
    gujarati = sum("\u0a80" <= ch <= "\u0aff" for ch in text)
    if letters == 0:
        return 0.0
    return gujarati / letters


def _hostname_from_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit((value or "").strip())
        return (parsed.hostname or "").casefold()
    except Exception:
        return ""


def _approved_news_source(source: str, source_url: str = "") -> str | None:
    """Return canonical publisher name only for the five approved publishers."""
    host = _hostname_from_url(source_url)
    if host:
        for name, domains in APPROVED_NEWS_SOURCES.items():
            if any(host == domain or host.endswith("." + domain) for domain in domains):
                return name
        # A concrete publisher URL exists but is not one of the approved
        # publishers. Never rescue it by its display name.
        return None

    low = " ".join((source or "").casefold().split())
    for alias, canonical in APPROVED_NEWS_SOURCE_NAMES.items():
        if alias in low:
            return canonical
    return None


def _is_gujarati_article(item: dict) -> bool:
    title = str(item.get("original_title") or item.get("title") or "")
    description = str(item.get("description") or "")
    return _has_gujarati_text(title) or (
        _gujarati_score(title, description) >= 0.12 and
        sum("\u0a80" <= ch <= "\u0aff" for ch in (title + description)) >= 8
    )


NEWS_FARMER_TERMS = (
    "ખેડૂત", "ખેડૂતો", "કિસાન", "કૃષક", "ખેતી", "કૃષિ", "પાક", "વાવેતર",
    "વાવણી", "લણણી", "સિંચાઈ", "ખાતર", "બિયારણ", "જંતુનાશક", "પાક નુકસાન",
    "સહાય", "સબસીડી", "યોજના", "પાક વીમો", "વળતર", "ikhedut", "આઇ ખેડૂત",
    "મંડી", "માર્કેટ", "બજાર ભાવ", "એપીએમસી", "apmc", "msp", "ટેકાના ભાવ",
    "ટેકાના ભાવે", "ખરીદી", "વેચાણ", "ભાવ", "વરસાદ", "માવઠું", "વાવાઝોડું",
    "હવામાન", "પશુપાલન", "ડેરી", "દૂધ", "કૃષિ સાધન", "ટ્રેક્ટર", "ડ્રિપ",
    "પ્રાકૃતિક ખેતી", "સજીવ ખેતી", "soil", "fertilizer", "farmer", "farmers",
    "farming", "agriculture", "crop", "crops", "irrigation", "subsidy", "scheme",
    "msp", "mandi", "apmc", "harvest",
)

def _farmer_relevance_score(title: str, description: str = "") -> float:
    """Score farmer usefulness; crop name is deliberately not part of the gate."""
    title_text = (title or "").casefold()
    body_text = (description or "").casefold()
    text = title_text + " " + body_text
    if not text.strip():
        return 0.0
    title_hits = sum(1 for term in NEWS_FARMER_TERMS if term.casefold() in title_text)
    body_hits = sum(1 for term in NEWS_FARMER_TERMS if term.casefold() in body_text)
    # Title relevance is intentionally weighted more heavily. Multiple related
    # terms increase confidence but the score remains bounded to [0, 1].
    score = min(1.0, title_hits * 0.22 + min(body_hits, 5) * 0.08)
    return round(score, 3)


def _news_query_for_category(crop: str, category: str) -> str:
    # Crop is intentionally ignored. The News screen is publisher/current-news
    # based, not personalized by the selected crop.
    category = (category or "agriculture").strip().lower()
    if category == "all":
        return "Gujarat latest Gujarati news"
    if category == "subsidy":
        return "Gujarat farmer subsidy scheme agriculture"
    if category == "methods":
        return "Gujarat farming method technology agriculture"
    if category == "market":
        return "Gujarat APMC market price farmer agriculture"
    return "Gujarat agriculture farmer latest Gujarati news"


def _category_relevant(item: dict, category: str) -> bool:
    # Keep category as a soft signal only. Publisher/source + Gujarati + date
    # are the hard News contract; a valid publisher story must not disappear
    # just because its headline lacks one category keyword.
    return True


def _crop_relevant(item: dict, crop: str) -> bool:
    # Retained only for backward compatibility with old callers. Never used as
    # a News inclusion gate.
    return True


def _news_relevance(item: dict, crop: str = "", require_crop: bool = False, category: str = "agriculture") -> bool:
    return True

def _canonical_news_url(link: str) -> str:
    raw = (link or "").strip()
    try:
        parsed = urllib.parse.urlsplit(raw)
        if not parsed.scheme or not parsed.netloc:
            return raw.casefold()
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if k.lower() not in {
            "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"
        }]
        return urllib.parse.urlunsplit((
            parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"),
            urllib.parse.urlencode(query), ""
        )).casefold()
    except Exception:
        return raw.casefold()


def _news_identity(item: dict) -> str:
    """Prefer canonical URL; fall back to title/source/day when RSS wraps URLs."""
    link = _canonical_news_url(str(item.get("link") or ""))
    if link and "news.google.com" not in link:
        return "url:" + link
    title = re.sub(r"\s+", " ", str(item.get("original_title") or item.get("title") or "")).strip().casefold()
    source = re.sub(r"\s+", " ", str(item.get("source") or "")).strip().casefold()
    published = str(item.get("published_at") or "")[:10]
    return f"story:{title}|{source}|{published}"


def _fetch_news_items(
    query: str,
    limit: int = 24,
    include_article_text: bool = False,
    category: str = "agriculture",
    max_age_hours: int | None = None,
    allow_older_fallback: bool = False,
    relevance_crop: str = "",
    require_crop: bool = False,
):
    """Fetch, validate and select real Gujarati agricultural articles."""
    global _LAST_NEWS_FETCH_DIAGNOSTICS
    _LAST_NEWS_FETCH_DIAGNOSTICS = {
        "rss_search_failed": 0, "rss_items_seen": 0, "valid_dates": 0,
        "fresh_items_kept": 0, "queries_tried": 0, "empty_feeds": 0,
        "date_parse_failed": 0, "older_than_window": 0, "future_date_rejected": 0,
        "gujarati_items": 0, "non_gujarati_headline_rejected": 0,
        "category_irrelevant": 0, "crop_irrelevant": 0, "irrelevant_items_rejected": 0,
        "duplicate_rejected": 0, "source_rejected": 0,
    }
    base = re.sub(r"\s+when:\d+d\b", "", (query or "").strip(), flags=re.IGNORECASE).strip()
    if not base:
        base = "Gujarat agriculture farmer news"
    now = datetime.now(timezone.utc)
    effective_max_age = max_age_hours if max_age_hours is not None else _news_max_age_hours()
    effective_max_age = max(1, min(int(effective_max_age), NEWS_FALLBACK_MAX_AGE_HOURS))
    cutoff = now - timedelta(hours=effective_max_age)
    time_operator = "when:2d" if effective_max_age <= 48 else "when:7d"
    # One farmer-focused query per approved publisher. The old implementation
    # accidentally iterated only [:4], so the fifth source was never queried;
    # more importantly, generic queries let one publisher dominate.
    candidates = list(NEWS_PUBLISHER_QUERIES.items())
    india_tz = timezone(timedelta(hours=5, minutes=30))
    items, seen = [], set()
    per_source_counts = {}

    for source_name, source_query in candidates:
        if len(items) >= max(limit * 4, 32):
            break
        _LAST_NEWS_FETCH_DIAGNOSTICS["queries_tried"] += 1
        effective_query = f"{source_query} {time_operator}".strip()
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
            "q": effective_query, "hl": "gu", "gl": "IN", "ceid": "IN:gu"
        })
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 SmartAgriMarketAI/News/2.0",
            "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8",
        })
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = response.read(700000)
            if not raw.strip():
                _LAST_NEWS_FETCH_DIAGNOSTICS["empty_feeds"] += 1
                continue
            root = ET.fromstring(raw)
        except Exception:
            _LAST_NEWS_FETCH_DIAGNOSTICS["rss_search_failed"] += 1
            continue

        rss_items = root.findall(".//item")
        if not rss_items:
            _LAST_NEWS_FETCH_DIAGNOSTICS["empty_feeds"] += 1
            continue

        for rss_item in rss_items:
            _LAST_NEWS_FETCH_DIAGNOSTICS["rss_items_seen"] += 1
            title = (rss_item.findtext("title") or "").strip()
            link = (rss_item.findtext("link") or "").strip()
            date_text = (rss_item.findtext("pubDate") or "").strip()
            source_el = rss_item.find("source")
            source = (source_el.text or "").strip() if source_el is not None else ""
            source_url = (source_el.attrib.get("url") or "").strip() if source_el is not None else ""
            description = (rss_item.findtext("description") or "").strip()
            published = _parse_news_date(date_text)
            if not title or not link:
                continue
            if published is None:
                _LAST_NEWS_FETCH_DIAGNOSTICS["date_parse_failed"] += 1
                continue
            _LAST_NEWS_FETCH_DIAGNOSTICS["valid_dates"] += 1
            if published > now:
                _LAST_NEWS_FETCH_DIAGNOSTICS["future_date_rejected"] += 1
                continue
            if published < cutoff:
                _LAST_NEWS_FETCH_DIAGNOSTICS["older_than_window"] += 1
                continue

            candidate = {
                "original_title": title,
                "title": title,
                "description": _html_to_text(description),
                "source": source,
                "source_url": source_url,
            }
            approved_source = _approved_news_source(source, source_url)
            if not approved_source:
                _LAST_NEWS_FETCH_DIAGNOSTICS["source_rejected"] = _LAST_NEWS_FETCH_DIAGNOSTICS.get("source_rejected", 0) + 1
                continue
            if not _is_gujarati_article(candidate):
                _LAST_NEWS_FETCH_DIAGNOSTICS["non_gujarati_headline_rejected"] += 1
                continue
            _LAST_NEWS_FETCH_DIAGNOSTICS["gujarati_items"] += 1

            farmer_score = _farmer_relevance_score(title, candidate["description"])
            if farmer_score < 0.22:
                _LAST_NEWS_FETCH_DIAGNOSTICS["farmer_irrelevant_rejected"] = _LAST_NEWS_FETCH_DIAGNOSTICS.get("farmer_irrelevant_rejected", 0) + 1
                continue

            item = {
                "title": title, "display_title": title, "original_title": title,
                "link": link, "published_at": published.isoformat(),
                "published_text": published.astimezone(india_tz).strftime("%d-%m-%Y %I:%M %p"),
                "source": approved_source,
                "source_url": source_url,
                "farmer_relevance": farmer_score,
                "description": candidate["description"],
                "_rss_description_present": bool(candidate["description"]),
                "_article_text_fetched": False,
                "category": category or "agriculture",
                "is_fresh": (now - published).total_seconds() <= 48 * 3600,
                "age_hours": round(max(0.0, (now - published).total_seconds() / 3600.0), 1),
                "news_age_type": "fresh" if (now - published).total_seconds() <= 48 * 3600 else "important_older",
                "news_window": "48h" if effective_max_age <= 48 else "7d",
            }
            key = _news_identity(item)
            if key in seen:
                _LAST_NEWS_FETCH_DIAGNOSTICS["duplicate_rejected"] += 1
                continue
            seen.add(key)
            items.append(item)
            _LAST_NEWS_FETCH_DIAGNOSTICS["fresh_items_kept"] += 1
            if len(items) >= limit:
                break

    # Source-diverse ranking: score first, then freshness, but do not let one
    # publisher fill the entire list. At most 3 articles per publisher are used
    # for a normal response, with round-robin selection across publishers.
    grouped = {}
    for item in items:
        grouped.setdefault(item["source"], []).append(item)
    for group in grouped.values():
        group.sort(key=lambda x: (x.get("farmer_relevance", 0.0), x.get("published_at", "")), reverse=True)
    selected = []
    source_names = list(grouped.keys())
    for round_index in range(3):
        for source_name in source_names:
            group = grouped[source_name]
            if round_index < len(group):
                selected.append(group[round_index])
                if len(selected) >= limit:
                    break
        if len(selected) >= limit:
            break
    selected.sort(key=lambda x: (x.get("farmer_relevance", 0.0), x.get("published_at", "")), reverse=True)
    per_source_counts = {}
    for item in selected:
        per_source_counts[item["source"]] = per_source_counts.get(item["source"], 0) + 1
    _LAST_NEWS_FETCH_DIAGNOSTICS["source_counts"] = per_source_counts
    _LAST_NEWS_FETCH_DIAGNOSTICS["sources_returned"] = sorted(per_source_counts.keys())
    _LAST_NEWS_FETCH_DIAGNOSTICS["farmer_relevant_kept"] = len(selected)
    if include_article_text:
        selected = selected[:min(limit, 18)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_fetch_article_text, item["link"]): item for item in selected}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    fetched = future.result(timeout=9)
                except Exception:
                    fetched = ""
                if fetched:
                    item["description"] = (item.get("description", "") + "\n" + fetched).strip()[:60000]
                    item["_article_text_fetched"] = True
        return selected
    return selected[:limit]


@app.get("/api/v1/news")
def news(crop: str = "", category: str = "all"):
    crop_name = ""  # Crop-based News filtering is intentionally disabled.
    category_name = (category or "agriculture").strip().lower()
    if category_name not in NEWS_CATEGORY_TERMS:
        category_name = "all"

    base_query = _news_query_for_category(crop_name, category_name)
    primary = _fetch_news_items(
        base_query + " " + NEWS_QUERY_SUFFIX,
        12,
        category=category_name,
        relevance_crop="",
        require_crop=False,
        max_age_hours=48,
    )
    primary_diag = dict(_LAST_NEWS_FETCH_DIAGNOSTICS)
    fallback_used = False
    fallback_reason = ""

    if primary:
        items = primary
        final_window = "48h"
    else:
        # Only the time window broadens; publisher/Gujarati validation stays identical.
        fallback = _fetch_news_items(
            base_query,
            12,
            category=category_name,
            relevance_crop="",
            require_crop=False,
            max_age_hours=168,
        )
        fallback_diag = dict(_LAST_NEWS_FETCH_DIAGNOSTICS)
        items = fallback
        fallback_used = bool(fallback)
        final_window = "7d_fallback" if fallback else "none"
        fallback_reason = (
            "no valid 48-hour result; same approved-publisher queries broadened to 7 days"
            if fallback else
            "no valid Gujarati relevant result within 7 days"
        )

    # Final invariant: newest first; no synthetic titles/dates/sources/URLs.
    items.sort(key=lambda x: x["published_at"], reverse=True)
    diagnostics = dict(primary_diag)
    diagnostics["raw_candidates"] = primary_diag.get("rss_items_seen", 0)
    diagnostics["valid_dates"] = primary_diag.get("valid_dates", 0)
    diagnostics["within_7d"] = sum(
        1 for x in primary if x.get("age_hours", 9999) <= 168
    )
    diagnostics["within_48h"] = sum(
        1 for x in primary if x.get("age_hours", 9999) <= 48
    )
    diagnostics["gujarati_48h"] = sum(
        1 for x in primary if x.get("is_fresh")
    )
    diagnostics["category_relevant_48h"] = len(primary)
    diagnostics["crop_filter_disabled"] = True
    diagnostics["final_48h_results"] = len(primary)
    diagnostics["STARTING_7_DAY_FALLBACK"] = bool(not primary)
    diagnostics["fallback_used"] = fallback_used
    diagnostics["fallback_reason"] = fallback_reason
    diagnostics["final_window"] = final_window
    diagnostics["final_results"] = len(items)
    diagnostics["sources_returned"] = sorted({x.get("source", "") for x in items if x.get("source")})
    diagnostics["source_counts"] = {src: sum(1 for x in items if x.get("source") == src) for src in diagnostics["sources_returned"]}
    diagnostics["farmer_relevance_gate"] = "score>=0.22; crop-independent"
    diagnostics["newest_selected"] = items[0]["published_at"] if items else None
    diagnostics["oldest_selected"] = items[-1]["published_at"] if items else None
    if not primary:
        diagnostics["fallback_diagnostics"] = fallback_diag
        diagnostics["gujarati_7d"] = fallback_diag.get("gujarati_items", 0)
        diagnostics["category_relevant_7d"] = len(items)

    return {
        "ok": True,
        "crop": crop_name,
        "category": category_name,
        "max_age_hours": 48,
        "fallback_max_age_hours": 168,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "diagnostics": diagnostics,
        "message": (
            "તાજા ગુજરાતી કૃષિ સમાચાર"
            if final_window == "48h" else
            "મહત્વના તાજેતરના ગુજરાતી કૃષિ સમાચાર (7 દિવસ સુધી)"
            if final_window == "7d_fallback" else
            "હાલમાં સંબંધિત તાજા કૃષિ સમાચાર ઉપલબ્ધ નથી."
        ),
    }


@app.post("/api/v1/ai/ask")
def ask(req: Ask):
    """
    Smart Guide provider chain:
      1) Groq + OpenAI GPT-OSS 120B (PRIMARY)
      2) xAI Grok (OPTIONAL fallback only if configured)
      3) deterministic crop-knowledge fallback (not an AI model)

    The response explicitly reports provider/model so the Android client and
    forensic logs can distinguish a real LLM response from a local fallback.
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="પ્રશ્ન ખાલી છે.")

    ctx = req.context or {}
    prompt = f"ખેડૂત પ્રશ્ન: {req.question.strip()}\nખેડૂત સંદર્ભ: {ctx}"

    # PRIMARY: Groq + OpenAI GPT-OSS 120B
    groq = groq_client()
    if groq is not None:
        try:
            response = groq.responses.create(
                model=GROQ_MODEL,
                instructions=SYSTEM,
                input=prompt,
            )
            answer = (response.output_text or "").strip()
            if answer:
                print(f"[AI_DEBUG] provider=groq model={GROQ_MODEL} mode=llm_primary")
                return {
                    "answer": answer,
                    "mode": "groq_gpt_oss_primary",
                    "provider": "groq",
                    "model": GROQ_MODEL,
                }
            print(f"[AI_DEBUG] provider=groq model={GROQ_MODEL} mode=empty_response")
        except Exception as exc:
            print(
                f"[AI_DEBUG] provider=groq model={GROQ_MODEL} "
                f"mode=error error_type={type(exc).__name__} error={str(exc)[:300]}"
            )
    else:
        print("[AI_DEBUG] provider=groq mode=not_configured")

    # OPTIONAL AI FALLBACK: xAI Grok only if XAI_API_KEY is configured.
    xai = xai_client()
    if xai is not None:
        try:
            response = xai.responses.create(
                model=XAI_MODEL,
                instructions=SYSTEM,
                input=prompt,
            )
            answer = (response.output_text or "").strip()
            if answer:
                print(f"[AI_DEBUG] provider=xai model={XAI_MODEL} mode=llm_fallback")
                return {
                    "answer": answer,
                    "mode": "xai_grok_fallback",
                    "provider": "xai",
                    "model": XAI_MODEL,
                    "warning": "Primary Groq GPT-OSS unavailable; xAI Grok fallback used.",
                }
        except Exception as exc:
            print(
                f"[AI_DEBUG] provider=xai model={XAI_MODEL} "
                f"mode=error error_type={type(exc).__name__} error={str(exc)[:300]}"
            )

    # FINAL FALLBACK: this is NOT an AI model.
    answer = rule_based_answer(req.question, req.context)
    print("[AI_DEBUG] provider=rule_based mode=non_ai_fallback")
    return {
        "answer": answer,
        "mode": "rule_based_fallback",
        "provider": "local",
        "model": "rule-based-crop-knowledge",
        "warning": "No configured AI model returned a response.",
    }


@app.post("/api/v1/ai/diagnose")
async def diagnose(image: UploadFile = File(...), crop: str = Form(""), context: str = Form("")):
    crop = crop.strip()
    if not crop:
        raise HTTPException(status_code=400, detail="Please select a crop before diagnosis")
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Image is empty")
    if len(data) > 7 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be under 7 MB")
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is missing")

    prompt = f"""
તમે Smart Agri-Market AI ના ગુજરાતી કૃષિ ફોટો નિષ્ણાત છો.
પાક: {crop}
સંદર્ભ: {context or 'ઉપલબ્ધ નથી'}

ફોટાનું વિશ્લેષણ કરીને સંપૂર્ણ ગુજરાતીમાં જવાબ આપો.
વિભાગો: ફોટામાં શું દેખાય છે, સંભવિત સમસ્યા, કારણ, શું કરવું, નિયંત્રણ માર્ગદર્શન, સાવચેતી.
ફોટામાં ન દેખાતી બાબતોની કલ્પના ન કરો. ચોક્કસ દવા/ડોઝ અંગે સાવચેતી રાખો.
"""

    last_error = "Gemini Vision service unavailable"
    for attempt in range(4):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            part = types.Part.from_bytes(data=data, mime_type=image.content_type or "image/jpeg")
            response = await client.aio.models.generate_content(
                model=GEMINI_VISION_MODEL,
                contents=[part, prompt],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM,
                    temperature=0.2,
                    max_output_tokens=8192,
                ),
            )
            answer = (getattr(response, "text", "") or "").strip()
            if not answer:
                raise RuntimeError("Empty Gemini response")
            return {
                "success": True,
                "answer": answer,
                "mode": "gemini_vision",
                "model": GEMINI_VISION_MODEL,
            }
        except Exception as exc:
            last_error = str(exc)[:500]
            if attempt < 3:
                await asyncio.sleep(float(2 ** attempt))

    raise HTTPException(status_code=502, detail=f"Gemini Vision error after 3 retries: {last_error}")

# ---------------- Secure Mandi price bridge ----------------
# Mandi requests are official-API only. No cache/news/estimated price is used
# anywhere in this Live Mandi path. Rate-limit cooldown only suppresses repeated
# upstream calls; it never substitutes data.
def _mandi_env_seconds(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except Exception:
        return default

MANDI_RESOURCE_ID = os.getenv("DATA_GOV_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070").strip()
MANDI_API_KEY = os.getenv("DATA_GOV_API_KEY", "").strip()
MANDI_API_HOST = "api.data.gov.in"
MANDI_API_SCHEME = "https"
MANDI_API_TIMEOUT_SECONDS = _mandi_env_seconds("MANDI_TIMEOUT_SECONDS", 10, 5, 30)
MANDI_RATE_LIMIT_COOLDOWN_SECONDS = _mandi_env_seconds("MANDI_RATE_LIMIT_COOLDOWN_SECONDS", 900, 60, 86400)
MANDI_PAGE_SIZE = _mandi_env_seconds("MANDI_PAGE_SIZE", 100, 25, 500)
MANDI_MAX_PAGES = _mandi_env_seconds("MANDI_MAX_PAGES", 5, 1, 20)
MANDI_SUMMARY_CROPS = ("મગફળી", "કપાસ", "જીરું", "એરંડા", "ડુંગળી")
# Optional secondary Agmarknet-derived source. It is NEVER used unless a real
# CEDA response is received and every returned row passes the freshness and
# price/provenance checks below. No sample/mock values are permitted.
CEDA_API_KEY = os.getenv("CEDA_API_KEY", "").strip()
CEDA_API_BASE = os.getenv("CEDA_API_BASE", "https://api.ceda.ashoka.edu.in/v1").strip().rstrip("/")
MANDI_FALLBACK_MAX_AGE_HOURS = _mandi_env_seconds("MANDI_FALLBACK_MAX_AGE_HOURS", 48, 1, 168)
MANDI_CEDA_TIMEOUT_SECONDS = _mandi_env_seconds("MANDI_CEDA_TIMEOUT_SECONDS", 8, 3, 30)
# Hard wall-clock budget for one Live Mandi crop request, including primary
# source + official fallback. This keeps Android retries predictable.
MANDI_TOTAL_BUDGET_SECONDS = _mandi_env_seconds("MANDI_TOTAL_BUDGET_SECONDS", 30, 10, 45)
_mandi_rate_limit_until: dict[str, float] = {}
_mandi_global_rate_limit_until: float = 0.0
_mandi_lock = threading.RLock()

GUJARATI_CROP_ALIASES = {
    "કપાસ": "Cotton", "મગફળી": "Groundnut", "ઘઉં": "Wheat", "બાજરી": "Bajra",
    "મકાઈ": "Maize", "જીરું": "Jeera", "ધાણા": "Dhaniya", "તલ": "Sesamum",
    "એરંડા": "Castor Seed", "ચણા": "Gram", "તુવેર": "Arhar", "મગ": "Moong",
    "અડદ": "Black Gram", "ડુંગળી": "Onion", "બટાકા": "Potato", "ટામેટા": "Tomato",
    "મરચાં": "Chilli", "લસણ": "Garlic", "શેરડી": "Sugarcane", "કેરી": "Mango",
    "કેળા": "Banana", "દાડમ": "Pomegranate"
}


def _norm_mandi_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", " ").replace("_", " ").split())


def _norm_mandi_market(value: Any) -> str:
    """Normalize market identity without changing the official display name.

    AGMARKNET may return labels such as ``APMC Bagasara`` while the app may
    submit ``Bagasara``.  Only the common APMC prefix/suffix is ignored for
    matching; the canonical upstream market name is always retained.
    """
    text = _norm_mandi_text(value)
    text = re.sub(r"^apmc\s+", "", text)
    text = re.sub(r"\s+apmc$", "", text)
    return text.strip()


def _commodity_matches(row: dict[str, Any], requested: str) -> bool:
    """Keep only rows belonging to the requested commodity."""
    if not requested or requested.strip().upper() == "ALL":
        return True
    wanted = _norm_mandi_text(GUJARATI_CROP_ALIASES.get(requested.strip(), requested))
    aliases = {
        "groundnut": {"groundnut", "ground nuts", "peanut", "peanuts", "મગફળી"},
        "cotton": {"cotton", "કપાસ"},
        "wheat": {"wheat", "ઘઉં"},
        "bajra": {"bajra", "pearl millet", "millet", "બાજરી"},
        "maize": {"maize", "corn", "મકાઈ"},
        "jeera": {"jeera", "cumin", "જીરું"},
        "dhaniya": {"dhania", "dhaniya", "coriander", "ધાણા"},
        "sesamum": {"sesamum", "sesame", "તલ"},
        "castor seed": {"castor seed", "castor", "એરંડા", "એરંડ"},
        "gram": {"gram", "chana", "चना", "ચણા"},
        "arhar": {"arhar", "tur", "તુવેર"},
        "moong": {"moong", "green gram", "મગ"},
        "black gram": {"black gram", "urad", "અડદ"},
        "onion": {"onion", "ડુંગળી"},
        "potato": {"potato", "બટાકા"},
        "tomato": {"tomato", "ટામેટા"},
        "chilli": {"chilli", "chillies", "green chilli", "મરચાં"},
        "garlic": {"garlic", "લસણ"},
    }
    accepted = {_norm_mandi_text(x) for x in aliases.get(wanted, {requested})}
    values = []
    for key in ("commodity", "Commodity", "crop", "Crop", "commodity_name", "Commodity Name"):
        if row.get(key):
            values.append(_norm_mandi_text(row.get(key)))
    if not values:
        return False
    return any(v in accepted or wanted in v or v in wanted for v in values)


def _mandi_latest_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Return rows from the latest available arrival date."""
    dated = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        arrival = row.get("arrival_date") or row.get("Arrival_Date") or row.get("arrival date") or row.get("date") or row.get("Date")
        parsed = _parse_mandi_date(arrival)
        dated.append((row, parsed))
    valid = [d for _, d in dated if d]
    if not valid:
        return rows, ""
    latest = max(valid)
    return [row for row, parsed in dated if parsed == latest], latest.strftime("%d-%m-%Y")


def _mandi_normalized_result(payload: dict[str, Any], requested_commodity: str, fallback_used: bool = False):
    raw_records = payload.get("records") or []
    if not isinstance(raw_records, list):
        raw_records = []
    if requested_commodity and requested_commodity.strip().upper() != "ALL":
        raw_records = [r for r in raw_records if isinstance(r, dict) and _commodity_matches(r, requested_commodity)]
    latest_rows, latest_date = _mandi_latest_rows(raw_records)
    normalized = _normalise_mandi_records(latest_rows)
    raw_keys = sorted(list(raw_records[0].keys())) if raw_records and isinstance(raw_records[0], dict) else []
    return {
        **payload,
        "records": normalized,
        "latest_arrival_date": normalized[0].get("arrival_date", "") if normalized else latest_date,
        "latest_arrival_date_iso": normalized[0].get("arrival_date_iso", "") if normalized else "",
        "_diagnostics": {
            "raw_record_count": len(raw_records),
            "raw_sample_keys": raw_keys[:30],
            "latest_date": latest_date,
            "fallback_used": fallback_used,
        },
    }


def _mandi_retry_after_seconds(exc: urllib.error.HTTPError) -> int:
    """Read Retry-After safely; fall back to the configured cooldown."""
    value = ""
    try:
        value = str(exc.headers.get("Retry-After", "")).strip()
    except Exception:
        value = ""
    if value:
        try:
            return max(60, min(int(value), 86400))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                seconds = int((retry_at - datetime.now(timezone.utc)).total_seconds())
                return max(60, min(seconds, 86400))
            except Exception:
                pass
    return MANDI_RATE_LIMIT_COOLDOWN_SECONDS


def _mandi_safe_error(exc: BaseException) -> str:
    """Return bounded diagnostic text with secrets/credential query params redacted."""
    raw = " ".join(str(exc or "").split())
    if MANDI_API_KEY:
        raw = raw.replace(MANDI_API_KEY, "[REDACTED]")
    raw = re.sub(r"([?&](?:api-key|api_key|apikey|access[_-]?token|token|key)=)[^&\s]+", r"\1[REDACTED]", raw, flags=re.IGNORECASE)
    return raw[:320] or type(exc).__name__


def _mandi_log_exception(exc: BaseException, *, http_status: int = 0) -> None:
    print(
        "[MANDI_DEBUG] official_api_exception "
        f"exception_type={type(exc).__name__!r} http_status={int(http_status or 0)} "
        f"error={_mandi_safe_error(exc)!r}"
    )


def _mandi_api_get(state: str, market: str, commodity: str, request_deadline: float | None = None):
    """Fetch exclusively from the official data.gov.in Mandi API.

    No cache, stale snapshot, news price, article extraction, calculated price,
    or alternate market data source is permitted here.
    """
    global _mandi_global_rate_limit_until

    state = (state or "").strip() or "Gujarat"
    market = (market or "").strip()
    normalized_commodity = (commodity or "ALL").strip() or "ALL"
    api_commodity = GUJARATI_CROP_ALIASES.get(normalized_commodity, normalized_commodity)
    if api_commodity.upper() == "ALL":
        api_commodity = ""

    print(
        "[MANDI_DEBUG] request_received "
        f"state={state!r} market={market!r} commodity={normalized_commodity!r}"
    )
    print(
        "[MANDI_DEBUG] official_api_config "
        f"scheme={MANDI_API_SCHEME!r} host={MANDI_API_HOST!r} "
        f"resource_id={MANDI_RESOURCE_ID!r} timeout_seconds={MANDI_API_TIMEOUT_SECONDS} "
        f"api_key_present={bool(MANDI_API_KEY)} api_key_length={len(MANDI_API_KEY)}"
    )

    if not MANDI_API_KEY:
        err = "DATA_GOV_API_KEY is missing from the running backend environment."
        print("[MANDI_DEBUG] official_api_exception exception_type='ConfigurationError' http_status=0 error='DATA_GOV_API_KEY is missing' ")
        return None, "Live Mandi API key server પર configure નથી. Renderમાં DATA_GOV_API_KEY ઉમેરો."

    # Keep Live Mandi a single exact official request. A 200 + empty records
    # is an honest official empty result; it must not trigger another query.
    rate_key = "|".join((state.lower(), market.lower(), api_commodity.lower()))
    now = time.monotonic()
    # The lock protects only shared cooldown state. Never hold it while doing
    # upstream network I/O, otherwise one slow farmer request can block every
    # other farmer's Mandi request in the same backend process.
    with _mandi_lock:
        cooldown_until = max(_mandi_rate_limit_until.get(rate_key, 0.0), _mandi_global_rate_limit_until)
    if cooldown_until > now:
        print(
            "[MANDI_DEBUG] official_api_rate_limit_cooldown "
            f"state={state!r} market={market!r} commodity={normalized_commodity!r}"
        )
        return None, "Live Mandi API limit પર છે; થોડા સમય પછી ફરી પ્રયાસ કરો."

    path = "/resource/" + MANDI_RESOURCE_ID
    print(
        "[MANDI_DEBUG] official_api_request "
        f"scheme={MANDI_API_SCHEME!r} host={MANDI_API_HOST!r} path={path!r} "
        f"state={state!r} market={market!r} commodity={normalized_commodity!r} "
        f"page_size={MANDI_PAGE_SIZE} max_pages={MANDI_MAX_PAGES} "
        f"timeout_seconds={MANDI_API_TIMEOUT_SECONDS}"
    )

    last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
    last_status = 0
    deadline = request_deadline
    aggregated=[]
    last_normalized=None
    for page in range(MANDI_MAX_PAGES):
        if deadline is not None and time.monotonic() >= deadline:
            return None, "Live Mandi માટે સમય મર્યાદા પૂરી થઈ ગઈ.", 0, last_status
        offset = page * MANDI_PAGE_SIZE
        params = {
            "api-key": MANDI_API_KEY,
            "format": "json",
            "limit": str(MANDI_PAGE_SIZE),
            "offset": str(offset),
        }
        if state:
            params["filters[state]"] = state
        if market:
            params["filters[market]"] = market
        if api_commodity:
            params["filters[commodity]"] = api_commodity
        url = f"{MANDI_API_SCHEME}://{MANDI_API_HOST}{path}?" + urllib.parse.urlencode(params)
        for attempt in range(2):
            if deadline is not None and time.monotonic() >= deadline:
                return None, "Live Mandi માટે સમય મર્યાદા પૂરી થઈ ગઈ.", 0, last_status
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "SmartAgriMarketAI/3.0",
                },
            )
            try:
                remaining = MANDI_API_TIMEOUT_SECONDS if deadline is None else max(0.5, min(float(MANDI_API_TIMEOUT_SECONDS), deadline - time.monotonic()))
                with urllib.request.urlopen(req, timeout=remaining) as response:
                    status = int(getattr(response, "status", 200) or 200)
                    content_type = str((getattr(response, "headers", None) or {}).get("Content-Type", ""))
                    body = response.read()
                    print(
                        "[MANDI_DEBUG] official_api_response "
                        f"page={page + 1} offset={offset} http_status={status} "
                        f"content_type={content_type!r} response_bytes={len(body)}"
                    )
                    try:
                        payload = json.loads(body.decode("utf-8", "ignore"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        _mandi_log_exception(exc, http_status=status)
                        return None, "Live Mandi API response parse error.", 0, status
                    if not isinstance(payload, dict):
                        exc = TypeError(f"Expected JSON object, got {type(payload).__name__}")
                        _mandi_log_exception(exc, http_status=status)
                        return None, "Live Mandi API response format error.", 0, status
                    page_rows = payload.get("records") or []
                    if not isinstance(page_rows, list): page_rows=[]
                    aggregated.extend(page_rows)
                    print(f"[MANDI_DEBUG] official_api_page rows={len(page_rows)} aggregated={len(aggregated)}")
                    # A short page proves there is no next page.  A full page
                    # means another page may exist, so continue until a short
                    # page is received or MANDI_MAX_PAGES is reached.
                    if len(page_rows) < MANDI_PAGE_SIZE:
                        # Pagination is complete; normalize after all fetched
                        # pages have been aggregated so latest-date selection
                        # sees the complete bounded result set.
                        normalized = _mandi_normalized_result({"records": aggregated}, normalized_commodity, fallback_used=False)
                        normalized["_diagnostics"]["pagination_complete"] = True
                        normalized["_diagnostics"]["pagination_reason"] = "short_page"
                        normalized["_diagnostics"]["http_status"] = status
                        normalized["_diagnostics"]["pages_fetched"] = page + 1
                        normalized["_diagnostics"]["page_size"] = MANDI_PAGE_SIZE
                        normalized["_diagnostics"]["raw_record_count"] = len(aggregated)
                        with _mandi_lock:
                            _mandi_rate_limit_until.pop(rate_key, None)
                            _mandi_global_rate_limit_until = 0.0
                        return normalized, "", 0, status

                    if page + 1 >= MANDI_MAX_PAGES:
                        normalized = _mandi_normalized_result({"records": aggregated}, normalized_commodity, fallback_used=False)
                        normalized["_diagnostics"]["pagination_complete"] = False
                        normalized["_diagnostics"]["pagination_reason"] = "max_pages_reached"
                        normalized["_diagnostics"]["http_status"] = status
                        normalized["_diagnostics"]["pages_fetched"] = page + 1
                        normalized["_diagnostics"]["page_size"] = MANDI_PAGE_SIZE
                        normalized["_diagnostics"]["raw_record_count"] = len(aggregated)
                        with _mandi_lock:
                            _mandi_rate_limit_until.pop(rate_key, None)
                            _mandi_global_rate_limit_until = 0.0
                        return normalized, "", 0, status

                    # Full page and another page remains: continue the bounded
                    # pagination loop.
            except urllib.error.HTTPError as exc:
                last_status = int(exc.code or 0)
                print(f"[MANDI_DEBUG] official_api_http_error page={page + 1} http_status={last_status} attempt={attempt + 1}")
                if last_status == 429:
                    cooldown = _mandi_retry_after_seconds(exc)
                    with _mandi_lock:
                        _mandi_rate_limit_until[rate_key] = time.monotonic() + cooldown
                        _mandi_global_rate_limit_until = time.monotonic() + cooldown
                    return None, f"Live Mandi API limit પર છે; server cooldown {cooldown} સેકન્ડ માટે સક્રિય છે.", cooldown, last_status
                if last_status in (401, 403):
                    return None, "Live Mandi API authentication/permission error.", 0, last_status
                last_error = f"Live Mandi HTTP error {last_status}."
                if last_status not in (502, 503, 504):
                    return None, last_error, 0, last_status
            except urllib.error.URLError as exc:
                last_status = 0; _mandi_log_exception(exc, http_status=0); last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
            except TimeoutError as exc:
                last_status = 0; _mandi_log_exception(exc, http_status=0); last_error = "Live Mandi API timeout થયો."
            except Exception as exc:
                last_status = 0; _mandi_log_exception(exc, http_status=0); last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
            if attempt < 1:
                sleep_for = 1.0 if deadline is None else min(1.0, max(0.0, deadline - time.monotonic()))
                if sleep_for > 0: time.sleep(sleep_for)
    print(f"[MANDI_DEBUG] official_api_final_failure http_status={last_status} error={last_error!r}")
    return None, last_error, 0, last_status
# CEDA metadata is auxiliary only. A rate limit on /agmarknet/commodities must
# never be allowed to masquerade as a price-endpoint failure. Keep a small
# process-local cache so repeated farmer requests do not hammer metadata.
_ceda_commodity_cache: dict[str, tuple[Any, float]] = {}
_ceda_geography_cache: tuple[Any, float] | None = None
_CEDA_METADATA_CACHE_SECONDS = 6 * 60 * 60
_CEDA_PUBLIC_BASE = "https://agmarknet.ceda.ashoka.edu.in/api"


# AGMARKNET 2.0 public live fallback. This is the official farmer-facing
# market-report backend; it is attempted before CEDA and never uses cached,
# estimated, News or AI prices.
AGMARKNET_PUBLIC_BASE = os.getenv("AGMARKNET_PUBLIC_BASE", "https://api.agmarknet.gov.in/v1").strip().rstrip("/")
AGMARKNET_PUBLIC_TIMEOUT_SECONDS = _mandi_env_seconds("AGMARKNET_PUBLIC_TIMEOUT_SECONDS", 20, 5, 60)
_agmarknet_state_cache: dict[str, tuple[Any, float]] = {}
_agmarknet_commodity_cache: dict[str, tuple[Any, float]] = {}
_agmarknet_commodity_context_cache: dict[int, tuple[Any, float]] = {}
_AGMARKNET_METADATA_CACHE_SECONDS = 6 * 60 * 60

def _ag_deep_rows(value: Any) -> list[dict[str, Any]]:
    out=[]; seen=set()
    def walk(x):
        if isinstance(x, dict):
            if id(x) in seen: return
            seen.add(id(x)); out.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(value); return out

def _ag_pick(row: dict[str, Any], *keys):
    for k in keys:
        if k in row and row[k] not in (None, ""): return row[k]
    normalized={str(k).lower().replace("_","").replace(" ",""):v for k,v in row.items()}
    for k in keys:
        v=normalized.get(str(k).lower().replace("_","").replace(" ",""))
        if v not in (None, ""): return v
    return None

def _ag_price_row(row):
    # AGMARKNET 2.0 has used snake_case/camelCase names and, in the
    # date-wise specific-commodity payload, minimumPrice/maximumPrice.
    return (_ag_pick(row,"min_price","minPrice","minimumPrice","Min Price","Min_Price","min") is not None and
            _ag_pick(row,"modal_price","modalPrice","Modal Price","Modal_Price","model_price","modelPrice","Model Price","modal","model") is not None and
            _ag_pick(row,"max_price","maxPrice","maximumPrice","Max Price","Max_Price","max") is not None)

def _ag_report_rows(body: Any) -> list[dict[str, Any]]:
    """Flatten AGMARKNET 2.0 daily-report payloads with inherited context.

    Current AGMARKNET 2.0 responses can use either ``markets -> dates -> data``
    or ``commodityGroups -> commodities -> ...``.  Price rows must inherit
    commodity/market/date context from their parents, but no date is invented.
    """
    out: list[dict[str, Any]] = []
    seen_price: set[int] = set()

    def walk(value: Any, commodity_ctx=None, market_ctx=None,
             district_ctx=None, state_ctx=None, date_ctx=None,
             group_ctx=None):
        if isinstance(value, dict):
            commodity_here = _ag_pick(value,
                "cmdt_name", "cmdtName", "commodity_name", "commodityName",
                "commodity", "Commodity") or commodity_ctx
            market_here = _ag_pick(value,
                "market_name", "marketName", "market", "Market") or market_ctx
            district_here = _ag_pick(value,
                "district_name", "districtName", "district", "District") or district_ctx
            state_here = _ag_pick(value,
                "state_name", "stateName", "state", "State") or state_ctx
            date_here = _ag_pick(value,
                "arrival_date", "arrivalDate", "date", "Date",
                "reportedDate", "reported_date") or date_ctx
            group_here = _ag_pick(value,
                "commodityGroup", "commodity_group", "CommodityGroup",
                "cmdt_grp_name", "cmdtGrpName") or group_ctx

            if _ag_price_row(value):
                oid = id(value)
                if oid not in seen_price:
                    seen_price.add(oid)
                    merged = dict(value)
                    if commodity_here is not None: merged.setdefault("commodity", commodity_here)
                    if market_here is not None: merged.setdefault("market_name", market_here)
                    if district_here is not None: merged.setdefault("district_name", district_here)
                    if state_here is not None: merged.setdefault("state_name", state_here)
                    if date_here is not None: merged.setdefault("arrival_date", date_here)
                    if group_here is not None: merged.setdefault("commodity_group", group_here)
                    out.append(merged)

            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child, commodity_here, market_here, district_here,
                         state_here, date_here, group_here)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    walk(child, commodity_ctx, market_ctx, district_ctx,
                         state_ctx, date_ctx, group_ctx)

    walk(body)
    return out


def _ag_daily_commodity_rows(body: Any) -> list[dict[str, Any]]:
    """Flatten AGMARKNET daily commodity/state responses without inventing dates."""
    return _ag_report_rows(body)

def _ag_response_shape(body: Any) -> dict[str, Any]:
    """Return safe structural diagnostics; never include values/prices/secrets."""
    info={"type":type(body).__name__}
    if isinstance(body,dict):
        info["top_keys"]=list(body.keys())[:30]
        data=body.get("data")
        if isinstance(data,dict):
            info["data_keys"]=list(data.keys())[:30]
        groups=body.get("commodityGroups")
        if isinstance(groups,list):
            info["commodity_groups_count"]=len(groups)
            if groups and isinstance(groups[0],dict):
                info["first_commodity_group_keys"]=list(groups[0].keys())[:30]
        markets=body.get("markets")
        if isinstance(markets,list):
            info["markets_count"]=len(markets)
            if markets and isinstance(markets[0],dict):
                info["market_keys"]=list(markets[0].keys())[:30]
                dates=markets[0].get("dates")
                if isinstance(dates,list):
                    info["first_market_dates_count"]=len(dates)
                    if dates and isinstance(dates[0],dict):
                        info["date_keys"]=list(dates[0].keys())[:30]
                        rows=dates[0].get("data")
                        if isinstance(rows,list):
                            info["first_date_data_count"]=len(rows)
                            if rows and isinstance(rows[0],dict):
                                info["price_row_keys"]=list(rows[0].keys())[:30]
    elif isinstance(body,list):
        info["list_count"]=len(body)
        if body and isinstance(body[0],dict):
            info["first_item_keys"]=list(body[0].keys())[:30]
    return info

async def _fetch_agmarknet_2_live(state: str, market: str, commodity: str, request_deadline: float | None = None) -> tuple[list[dict[str, Any]], str]:
    requested=(commodity or "ALL").strip() or "ALL"
    wanted=GUJARATI_CROP_ALIASES.get(requested, requested)
    state_name=(state or "Gujarat").strip()
    timeout=httpx.Timeout(AGMARKNET_PUBLIC_TIMEOUT_SECONDS, connect=min(8.0,AGMARKNET_PUBLIC_TIMEOUT_SECONDS))
    headers={"Accept":"application/json, text/plain, */*","Origin":"https://agmarknet.gov.in","Referer":"https://agmarknet.gov.in/","User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/135 Safari/537.36"}
    async with httpx.AsyncClient(base_url=AGMARKNET_PUBLIC_BASE,headers=headers,timeout=timeout) as client:
        async def get(path,params=None):
            try:
                if request_deadline is not None and time.monotonic() >= request_deadline:
                    return None,"mandi_total_budget_exceeded"
                remaining = AGMARKNET_PUBLIC_TIMEOUT_SECONDS if request_deadline is None else max(0.5, min(float(AGMARKNET_PUBLIC_TIMEOUT_SECONDS), request_deadline - time.monotonic()))
                r=await client.get(path,params=params,timeout=remaining)
                if r.status_code!=200: return None,f"HTTP {r.status_code}"
                return r.json(),""
            except Exception as exc: return None,f"{type(exc).__name__}: {str(exc)[:180]}"
        skey=_norm_mandi_text(state_name); cached=_agmarknet_state_cache.get(skey)
        state_id=cached[0] if cached and time.monotonic()-cached[1]<_AGMARKNET_METADATA_CACHE_SECONDS else None
        if state_id is None:
            body,err=await get("/location/state",{"page":1,"search":state_name})
            for row in _ag_deep_rows(body):
                nm=str(_ag_pick(row,"name","state_name","stateName","State","state") or "").strip(); sid=_ag_pick(row,"id","state_id","stateId","stateCode")
                if sid is not None and nm and _norm_mandi_text(nm)==skey:
                    try: state_id=int(sid); break
                    except (TypeError,ValueError): pass
            if state_id is None: return [],f"AGMARKNET state resolution failed: {err}"
            _agmarknet_state_cache[skey]=(state_id,time.monotonic())
        print(f"[MANDI_DEBUG] agmarknet2_state_resolved state={state_name!r} id={state_id}")
        commodity_id=None
        if wanted.upper()!="ALL":
            ckey=_norm_mandi_text(wanted); cc=_agmarknet_commodity_cache.get(ckey)
            commodity_id=cc[0] if cc and time.monotonic()-cc[1]<_AGMARKNET_METADATA_CACHE_SECONDS else None
            if commodity_id is None:
                body,err=await get("/daily-price-arrival/filters")
                matches=[]
                # Current AGMARKNET 2.0 filter payload exposes the commodity
                # lookup table as data.cmdt_data. Rows use cmdt_id/cmdt_name
                # (and may vary slightly by backend release). Do not assume
                # generic commodity_id/commodity_name keys only.
                for row in _ag_deep_rows(body):
                    nm=str(_ag_pick(
                        row,
                        "cmdt_name","cmdtName",
                        "commodity_name","commodityName",
                        "commodity","name","commodity_name_en",
                    ) or "").strip()
                    cid=_ag_pick(
                        row,
                        "cmdt_id","cmdtId",
                        "commodity_id","commodityId","commodityCode",
                        "id","code",
                    )
                    if cid is not None and nm and (_norm_mandi_text(nm)==ckey or ckey in _norm_mandi_text(nm)):
                        matches.append((nm,cid))
                exact=[m for m in matches if _norm_mandi_text(m[0])==ckey]
                chosen=exact[0] if exact else (matches[0] if len(matches)==1 else None)
                print(
                    f"[MANDI_DEBUG] agmarknet2_filter_resolution requested={wanted!r} "
                    f"matches={len(matches)} exact={len(exact)} "
                    f"chosen={chosen!r}"
                )
                if not chosen:
                    # Safe contract diagnostics only: no prices, secrets or full payload.
                    if isinstance(body,dict):
                        print(f"[MANDI_DEBUG] agmarknet2_filters_shape top_keys={list(body.keys())[:20]!r}")
                        data=body.get("data")
                        if isinstance(data,dict):
                            print(f"[MANDI_DEBUG] agmarknet2_filters_data_keys={list(data.keys())[:30]!r}")
                            rows=data.get("cmdt_data")
                            if isinstance(rows,list):
                                first_keys=list(rows[0].keys())[:30] if rows and isinstance(rows[0],dict) else []
                                print(f"[MANDI_DEBUG] agmarknet2_cmdt_data rows={len(rows)} first_keys={first_keys!r}")
                    return [],f"AGMARKNET commodity resolution failed: {err or 'no matching commodity in cmdt_data'}"
                try: commodity_id=int(chosen[1])
                except (TypeError,ValueError): return [],"AGMARKNET commodity id invalid"
                _agmarknet_commodity_cache[ckey]=(commodity_id,time.monotonic())
            print(f"[MANDI_DEBUG] agmarknet2_commodity_resolved commodity={wanted!r} id={commodity_id}")

        # IMPORTANT: the public ``commodity-wise/daily-report-state`` response
        # currently observed in production contains the requested report scope
        # but does NOT expose an official arrivalDate on its nested price rows.
        # We therefore cannot accept those rows as live records under our
        # provenance rule.  For a selected commodity, use the verified
        # date-wise/specific-commodity endpoint instead: it is month-scoped,
        # but its nested ``dates[].arrivalDate`` is an explicit upstream field.
        # We fetch the current and previous month as needed, then filter by the
        # OFFICIAL arrivalDate.  The requested day is never copied into
        # arrival_date.
        now=datetime.now(timezone(timedelta(hours=5,minutes=30)))
        month_keys=[]
        for delta in range(3):
            d=now.date()-timedelta(days=delta)
            key=(d.year,d.month)
            if key not in month_keys: month_keys.append(key)

        if wanted.upper() != "ALL":
            monthly_rows=[]
            for year,month_num in month_keys:
                body,err=await get("/prices-and-arrivals/date-wise/specific-commodity",{
                    "year":str(year),
                    "month":str(month_num),
                    "stateId":str(state_id),
                    "commodityId":str(commodity_id),
                    "includeExcel":"false"
                })
                endpoint_label="date-wise/specific-commodity"
                if body is None:
                    print(f"[MANDI_DEBUG] agmarknet2_monthly_failed endpoint={endpoint_label!r} year={year} month={month_num} error={err!r}")
                    continue
                rows=_ag_report_rows(body)
                # This endpoint is explicitly scoped to the requested
                # commodity/state, so a missing commodity field is filled from
                # that upstream request scope (never from a guessed value).
                scoped=[]
                for rr in rows:
                    x=dict(rr)
                    if not _ag_pick(x,"commodity","cmdt_name","cmdtName","commodity_name","commodityName"):
                        x["commodity"]=wanted
                    scoped.append(x)
                monthly_rows.extend(scoped)
                print(f"[MANDI_DEBUG] agmarknet2_monthly_response endpoint={endpoint_label!r} year={year} month={month_num} raw_records={len(scoped)} shape={_ag_response_shape(body)!r}")

            # Deduplicate rows returned from overlapping month calls.
            candidates=[]; seen_candidate=set()
            for r in monthly_rows:
                raw_date=_ag_pick(r,"arrival_date","arrivalDate","date","Date","reportedDate","reported_date")
                parsed=_parse_mandi_date(raw_date)
                if not parsed: continue
                key=(
                    _norm_mandi_text(str(_ag_pick(r,"market_name","marketName","market","Market") or "")),
                    parsed.date().isoformat(),
                    str(_ag_pick(r,"variety_name","varietyName","variety","Variety") or ""),
                    str(_ag_pick(r,"min_price","minPrice","minimumPrice","Min Price","Min_Price","min") or ""),
                    str(_ag_pick(r,"modal_price","modalPrice","Modal Price","Modal_Price","model_price","modelPrice","Model Price","modal","model") or ""),
                    str(_ag_pick(r,"max_price","maxPrice","maximumPrice","Max Price","Max_Price","max") or ""),
                )
                if key not in seen_candidate:
                    seen_candidate.add(key); candidates.append(r)

            print(f"[MANDI_DEBUG] agmarknet2_specific_commodity_candidates commodity={wanted!r} raw_records={len(candidates)}")
            if candidates:
                sample=[]
                for sr in candidates[:3]:
                    sample.append({
                        "commodity":str(_ag_pick(sr,"commodity","cmdt_name","cmdtName","commodity_name","commodityName") or wanted),
                        "arrival_date":str(_ag_pick(sr,"arrival_date","arrivalDate","date","Date") or ""),
                        "district":str(_ag_pick(sr,"district_name","districtName","district","District") or ""),
                        "market":str(_ag_pick(sr,"market_name","marketName","market","Market") or ""),
                        "min_price":_ag_pick(sr,"min_price","minPrice","minimumPrice","Min Price","Min_Price","min"),
                        "max_price":_ag_pick(sr,"max_price","maxPrice","maximumPrice","Max Price","Max_Price","max"),
                        "modal_price":_ag_pick(sr,"modal_price","modalPrice","Modal Price","Modal_Price","model_price","modelPrice","Model Price","modal","model"),
                    })
                print(f"[MANDI_DEBUG] agmarknet2_specific_sample first3={sample!r}")

            accepted=[]
            rejected={"commodity":0,"market":0,"date_invalid":0,"future":0,"stale":0,"price":0,"accepted":0}
            for r in candidates:
                rc=str(_ag_pick(r,"cmdt_name","cmdtName","commodity","Commodity","commodity_name","commodityName") or wanted).strip()
                if not _commodity_matches({"commodity":rc},wanted):
                    rejected["commodity"] += 1; continue
                market_name_value=str(_ag_pick(r,"market_name","marketName","market","Market") or "").strip()
                if market and (not market_name_value or _norm_mandi_market(market) != _norm_mandi_market(market_name_value)):
                    rejected["market"] += 1; continue

                # Only an explicit upstream arrivalDate/arrival_date/date field
                # from the monthly report can become arrival_date.
                raw_date=_ag_pick(r,"arrival_date","arrivalDate","date","Date","reportedDate","reported_date")
                parsed=_parse_mandi_date(raw_date)
                if not parsed:
                    rejected["date_invalid"] += 1; continue
                age=(now-parsed.astimezone(now.tzinfo)).total_seconds()/3600
                if age < -1/60:
                    rejected["future"] += 1; continue
                if age > MANDI_FALLBACK_MAX_AGE_HOURS:
                    rejected["stale"] += 1; continue

                mn=_normalise_price(_ag_pick(r,"min_price","minPrice","minimumPrice","Min Price","Min_Price","min"))
                mo=_normalise_price(_ag_pick(r,"modal_price","modalPrice","Modal Price","Modal_Price","model_price","modelPrice","Model Price","modal","model"))
                mx=_normalise_price(_ag_pick(r,"max_price","maxPrice","maximumPrice","Max Price","Max_Price","max"))
                mf,mof,xf=_price_float(mn),_price_float(mo),_price_float(mx)
                if mf is None or mof is None or xf is None or not(mf>0 and mof>0 and xf>0 and mf<=mof<=xf):
                    rejected["price"] += 1; continue
                accepted.append({
                    "state":state_name,
                    "district":str(_ag_pick(r,"district_name","districtName","district","District") or "").strip(),
                    "market":market_name_value,
                    "commodity":rc,
                    "variety":str(_ag_pick(r,"variety_name","varietyName","variety","Variety") or "").strip(),
                    "grade":str(_ag_pick(r,"grade_name","gradeName","grade","Grade") or "").strip(),
                    "arrival_date":parsed.strftime("%d/%m/%Y"),
                    "report_date":parsed.strftime("%Y-%m-%d"),
                    "min_price":mf,"max_price":xf,"modal_price":mof,
                    "source":"AGMARKNET 2.0 (Government of India)",
                    "source_url":"https://agmarknet.gov.in/home",
                    "_source_age_hours":round(age,2)
                })
            rejected["accepted"]=len(accepted)
            print(f"[MANDI_DEBUG] agmarknet2_specific_validation raw={len(candidates)} accepted={rejected['accepted']} rejected_commodity={rejected['commodity']} rejected_market={rejected['market']} rejected_date_invalid={rejected['date_invalid']} rejected_future={rejected['future']} rejected_stale={rejected['stale']} rejected_price={rejected['price']}")
            if accepted: return accepted,""
            return [],"AGMARKNET 2.0 returned no fresh date-stamped records for the requested commodity/market"

        # ALL-commodity mode remains on the daily state report.  If its rows do
        # not contain an explicit arrival date, they are intentionally rejected
        # rather than promoted with the request date.
        for delta in range(3):
            day=now.date()-timedelta(days=delta); date_iso=day.isoformat()
            body,err=await get("/prices-and-arrivals/commodity-market/daily-report-state",{
                "date":date_iso,"state":state_id,"includeExcel":"false"
            })
            endpoint_label="commodity-market/daily-report-state"
            candidates=_ag_report_rows(body) if body is not None else []
            if body is None:
                print(f"[MANDI_DEBUG] agmarknet2_daily_failed endpoint={endpoint_label!r} date={date_iso!r} error={err!r}")
                continue
            shape=_ag_response_shape(body)
            print(f"[MANDI_DEBUG] agmarknet2_daily_response endpoint={endpoint_label!r} date={date_iso!r} raw_records={len(candidates)} shape={shape!r}")
            accepted=[]
            rejected={"commodity":0,"market":0,"date_invalid":0,"future":0,"stale":0,"price":0,"accepted":0}
            for r in candidates:
                rc=str(_ag_pick(r,"cmdt_name","cmdtName","commodity","Commodity","commodity_name","commodityName") or "").strip()
                market_name_value=str(_ag_pick(r,"market_name","marketName","market","Market") or "").strip()
                if market and (not market_name_value or _norm_mandi_market(market) != _norm_mandi_market(market_name_value)):
                    rejected["market"] += 1; continue
                raw_date=_ag_pick(r,"arrival_date","arrivalDate","date","Date","reportedDate","reported_date")
                parsed=_parse_mandi_date(raw_date)
                if not parsed:
                    rejected["date_invalid"] += 1; continue
                # Remaining validation mirrors the specific-commodity branch.
                if wanted.upper()!="ALL" and (not rc or not _commodity_matches({"commodity":rc},wanted)):
                    rejected["commodity"] += 1; continue
                age=(now-parsed.astimezone(now.tzinfo)).total_seconds()/3600
                if age < -1/60: rejected["future"] += 1; continue
                if age > MANDI_FALLBACK_MAX_AGE_HOURS: rejected["stale"] += 1; continue
                mn=_normalise_price(_ag_pick(r,"min_price","minPrice","minimumPrice","Min Price","Min_Price","min"))
                mo=_normalise_price(_ag_pick(r,"modal_price","modalPrice","Modal Price","Modal_Price","model_price","modelPrice","Model Price","modal","model"))
                mx=_normalise_price(_ag_pick(r,"max_price","maxPrice","maximumPrice","Max Price","Max_Price","max"))
                mf,mof,xf=_price_float(mn),_price_float(mo),_price_float(mx)
                if mf is None or mof is None or xf is None or not(mf>0 and mof>0 and xf>0 and mf<=mof<=xf):
                    rejected["price"] += 1; continue
                accepted.append({
                    "state":state_name,"district":str(_ag_pick(r,"district_name","districtName","district","District") or "").strip(),
                    "market":market_name_value,"commodity":rc,"variety":str(_ag_pick(r,"variety_name","varietyName","variety","Variety") or "").strip(),
                    "grade":str(_ag_pick(r,"grade_name","gradeName","grade","Grade") or "").strip(),
                    "arrival_date":parsed.strftime("%d/%m/%Y"),"report_date":date_iso,
                    "min_price":mf,"max_price":xf,"modal_price":mof,
                    "source":"AGMARKNET 2.0 (Government of India)","source_url":"https://agmarknet.gov.in/home","_source_age_hours":round(age,2)
                })
            rejected["accepted"]=len(accepted)
            print(f"[MANDI_DEBUG] agmarknet2_row_validation date={date_iso!r} raw={len(candidates)} accepted={rejected['accepted']} rejected_commodity={rejected['commodity']} rejected_market={rejected['market']} rejected_date_invalid={rejected['date_invalid']} rejected_future={rejected['future']} rejected_stale={rejected['stale']} rejected_price={rejected['price']}")
            if accepted: return accepted,""
        return [],"AGMARKNET 2.0 returned no fresh records"

async def _fetch_ceda_fresh_mandi(state: str, district: str, commodity: str) -> tuple[list[dict[str, Any]], str]:
    """Fetch real Agmarknet-derived data through CEDA.

    Surgical fallback fix:
    - /agmarknet/commodities is metadata, not the price source. Its HTTP 429
      must not terminate the fallback before /agmarknet/prices is attempted.
    - When the authenticated metadata endpoint is rate-limited, resolve the
      commodity id from CEDA's public Agmarknet interface endpoint instead.
    - Commodity/state/district ids are still resolved from upstream data; no
      price, date, market or id is hardcoded.
    - Only actual /agmarknet/prices rows inside the configured freshness window
      are returned. No News/AI/demo/cache values are introduced.
    """
    global _ceda_geography_cache

    if not CEDA_API_KEY:
        return [], "CEDA_API_KEY not configured"
    state = (state or "Gujarat").strip()
    requested = (commodity or "ALL").strip() or "ALL"
    api_commodity = GUJARATI_CROP_ALIASES.get(requested, requested)
    if api_commodity.upper() == "ALL":
        return [], "CEDA fallback requires a specific commodity"

    timeout = httpx.Timeout(MANDI_CEDA_TIMEOUT_SECONDS, connect=min(8.0, MANDI_CEDA_TIMEOUT_SECONDS))
    headers = {"Authorization": f"Bearer {CEDA_API_KEY}", "Accept": "application/json"}
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    from_date = (now_ist.date() - timedelta(days=max(2, MANDI_FALLBACK_MAX_AGE_HOURS // 24 + 2))).isoformat()
    to_date = now_ist.date().isoformat()

    async with httpx.AsyncClient(base_url=CEDA_API_BASE, headers=headers, timeout=timeout) as client:
        async def call(method: str, path: str, payload: dict | None = None):
            try:
                response = await client.request(method, path, json=payload)
                retry_after = response.headers.get("Retry-After", "")
                if response.status_code != 200:
                    suffix = f"; Retry-After={retry_after}" if retry_after else ""
                    return None, f"HTTP {response.status_code}{suffix}"
                body = response.json()
                output = body.get("output", {}) if isinstance(body, dict) else {}
                if output.get("type") != "success":
                    return None, str(output.get("message") or "CEDA API error")[:240]
                return output.get("data") or [], ""
            except Exception as exc:
                return None, f"{type(exc).__name__}: {str(exc)[:180]}"

        def _extract_public_data(body: Any) -> list[dict[str, Any]]:
            if isinstance(body, list):
                return [x for x in body if isinstance(x, dict)]
            if isinstance(body, dict):
                for key in ("data", "commodities", "results", "items", "rows"):
                    value = body.get(key)
                    if isinstance(value, list):
                        return [x for x in value if isinstance(x, dict)]
                    if isinstance(value, dict):
                        nested = _extract_public_data(value)
                        if nested:
                            return nested
            return []

        def _commodity_name(row: dict[str, Any]) -> str:
            return str(row.get("commodity_name") or row.get("commodity") or row.get("name") or row.get("cmdty") or row.get("commodityName") or "").strip()

        def _commodity_id(row: dict[str, Any]):
            for key in ("commodity_id", "id", "cmdty_id", "commodityId"):
                if row.get(key) is not None:
                    return row.get(key)
            return None

        async def public_commodity_metadata() -> list[dict[str, Any]]:
            """Best-effort metadata resolver; never supplies prices."""
            public_client = httpx.AsyncClient(
                base_url=_CEDA_PUBLIC_BASE,
                headers={"Accept": "application/json", "User-Agent": "SmartAgriMarketAI/Mandi/12.1"},
                timeout=timeout,
            )
            try:
                response = await public_client.get("/commodities")
                if response.status_code != 200:
                    print(f"[MANDI_DEBUG] ceda_public_commodities_http_error status={response.status_code}")
                    return []
                return _extract_public_data(response.json())
            except Exception as exc:
                print(f"[MANDI_DEBUG] ceda_public_commodities_exception type={type(exc).__name__!r} error={str(exc)[:180]!r}")
                return []
            finally:
                await public_client.aclose()

        # ---------- Commodity id: cached -> authenticated metadata -> public metadata ----------
        cache_key = norm(api_commodity)
        cached = _ceda_commodity_cache.get(cache_key)
        commodity_meta = cached[0] if cached and (time.monotonic() - cached[1] < _CEDA_METADATA_CACHE_SECONDS) else None
        commodity_meta_source = "cache" if commodity_meta else ""

        if not commodity_meta:
            commodities, err = await call("GET", "/agmarknet/commodities")
            if commodities is not None:
                commodity_meta = commodities
                commodity_meta_source = "ceda_v1"
            else:
                print(f"[MANDI_DEBUG] ceda_commodities_failed error={err!r}")
                # Do not make authenticated metadata 429 a blocker. CEDA's
                # public Agmarknet interface exposes the same commodity list.
                public_rows = await public_commodity_metadata()
                if public_rows:
                    commodity_meta = public_rows
                    commodity_meta_source = "ceda_public_metadata"
                else:
                    return [], f"CEDA commodity metadata unavailable: {err}"

        matches = [c for c in commodity_meta if isinstance(c, dict) and norm(_commodity_name(c)) == norm(api_commodity)]
        if not matches:
            matches = [c for c in commodity_meta if isinstance(c, dict) and norm(api_commodity) in norm(_commodity_name(c))]
        if len(matches) != 1:
            print(f"[MANDI_DEBUG] ceda_commodity_resolution_failed requested={api_commodity!r} candidates={len(matches)} source={commodity_meta_source!r}")
            return [], "CEDA commodity resolution failed"
        commodity_id = _commodity_id(matches[0])
        if commodity_id is None:
            return [], "CEDA commodity id missing"
        _ceda_commodity_cache[cache_key] = (matches[0], time.monotonic())
        print(f"[MANDI_DEBUG] ceda_commodity_resolved commodity={api_commodity!r} id={commodity_id!r} source={commodity_meta_source!r}")

        # ---------- Geography metadata ----------
        geographies = None
        geo_source = ""
        if _ceda_geography_cache and (time.monotonic() - _ceda_geography_cache[1] < _CEDA_METADATA_CACHE_SECONDS):
            geographies = _ceda_geography_cache[0]
            geo_source = "cache"
        else:
            geographies, err = await call("GET", "/agmarknet/geographies")
            if geographies is None:
                return [], f"CEDA geographies failed: {err}"
            _ceda_geography_cache = (geographies, time.monotonic())
            geo_source = "ceda_v1"

        state_rows = [g for g in geographies if isinstance(g, dict) and norm(str(g.get("census_state_name", ""))) == norm(state)]
        if not state_rows:
            state_rows = [g for g in geographies if isinstance(g, dict) and norm(state) in norm(str(g.get("census_state_name", "")))]
        if not state_rows:
            return [], "CEDA state resolution failed"
        state_id = state_rows[0].get("census_state_id")
        districts = {}
        for g in state_rows:
            did = g.get("census_district_id")
            dname = str(g.get("census_district_name") or "").strip()
            if did is not None and dname:
                districts[int(did)] = dname
        if district:
            districts = {did: name for did, name in districts.items() if norm(name) == norm(district) or norm(district) in norm(name)}
        if not districts:
            return [], "CEDA district resolution failed"

        sem = asyncio.Semaphore(5)
        async def district_prices(did: int, dname: str):
            async with sem:
                payload_v1 = {
                    "commodity_id": commodity_id,
                    "state_id": state_id,
                    "district_id": [did],
                    "from_date": from_date,
                    "to_date": to_date,
                }

                # IMPORTANT: The public CEDA price endpoint is attempted first.
                # The v1 /agmarknet/prices response is an aggregate series and
                # may not contain mandi/district fields; using it as the primary
                # path for a Rajkot request can therefore produce zero accepted
                # rows even when prices exist. The public endpoint is also the
                # path that does not depend on the rate-limited /markets metadata.
                rows = None
                call_err = ""
                try:
                    public_payload = {
                        "state_id": int(state_id),
                        "commodity_id": int(commodity_id),
                        "district_id": int(did),
                        "calculation_type": "d",
                        "chart_type": "datadownload",
                        "start_date": from_date + "T00:00:00Z",
                        "end_date": to_date + "T23:59:59Z",
                    }
                    async with httpx.AsyncClient(
                        base_url=_CEDA_PUBLIC_BASE,
                        headers={
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/135 Safari/537.36",
                            "Origin": "https://agmarknet.ceda.ashoka.edu.in",
                            "Referer": "https://agmarknet.ceda.ashoka.edu.in/",
                        },
                        timeout=timeout,
                    ) as public_client:
                        pr = await public_client.post("/prices", json=public_payload)
                        retry_after = pr.headers.get("Retry-After", "")
                        if pr.status_code == 200:
                            rows = _extract_public_data(pr.json())
                            print(f"[MANDI_DEBUG] ceda_public_prices_response district={dname!r} status=200 raw_records={len(rows)} chart_type='datadownload'")
                        else:
                            suffix = f"; Retry-After={retry_after}" if retry_after else ""
                            call_err = f"HTTP {pr.status_code}{suffix}"
                            print(f"[MANDI_DEBUG] ceda_public_prices_failed district={dname!r} error={call_err!r}")
                except Exception as exc:
                    call_err = f"{type(exc).__name__}: {str(exc)[:180]}"
                    print(f"[MANDI_DEBUG] ceda_public_prices_exception district={dname!r} error={call_err!r}")

                # Only if the public endpoint itself failed, try the authenticated
                # CEDA price endpoint. Never call /agmarknet/markets merely to make
                # a price response usable: market metadata is optional.
                if rows is None:
                    rows, v1_err = await call("POST", "/agmarknet/prices", payload_v1)
                    if rows is not None:
                        call_err = ""
                        print(f"[MANDI_DEBUG] ceda_v1_prices_response district={dname!r} raw_records={len(rows)}")
                    else:
                        call_err = v1_err or call_err
                if rows is None:
                    print(f"[MANDI_DEBUG] ceda_prices_failed district={dname!r} error={call_err!r}")
                    return []

                market_names = {}
                out = []
                rejected_date = rejected_stale = rejected_price = rejected_district = 0
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    # Support the documented CEDA v1 shape used by the current
                    # adapter and the public interface's equivalent names.
                    raw_date = r.get("date") or r.get("t") or r.get("arrival_date") or r.get("Date")
                    parsed = _parse_mandi_date(raw_date)
                    if not parsed:
                        rejected_date += 1
                        continue
                    age_hours = (now_ist - parsed.astimezone(now_ist.tzinfo)).total_seconds() / 3600.0
                    if age_hours < -1/60 or age_hours > MANDI_FALLBACK_MAX_AGE_HOURS:
                        rejected_stale += 1
                        continue
                    min_p = r.get("min_price", r.get("p_min"))
                    max_p = r.get("max_price", r.get("p_max"))
                    modal_p = r.get("modal_price", r.get("p_modal"))
                    try:
                        min_f, max_f, modal_f = float(min_p), float(max_p), float(modal_p)
                    except (TypeError, ValueError):
                        rejected_price += 1
                        continue
                    if not (min_f > 0 and max_f > 0 and modal_f > 0 and min_f <= modal_f <= max_f):
                        rejected_price += 1
                        continue
                    row_district = str(r.get("district") or r.get("district_name") or r.get("District") or "").strip()
                    if district and row_district and norm(row_district) != norm(district) and norm(district) not in norm(row_district):
                        rejected_district += 1
                        continue
                    if district and not row_district:
                        rejected_district += 1
                        # Public CEDA /api/prices with district_id=0 is a
                        # state-level series; never relabel it as Rajkot/etc.
                        continue
                    market_id = r.get("market_id", r.get("marketId"))
                    market_name = (
                        r.get("market_name") or r.get("market") or r.get("Market") or
                        market_names.get(market_id, "")
                    )
                    out.append({
                        "state": state,
                        "district": dname,
                        "market": str(market_name or "").strip(),
                        "commodity": str(
                            r.get("commodity_name") or r.get("commodity") or
                            matches[0].get("commodity_name") or matches[0].get("name") or api_commodity
                        ),
                        "arrival_date": parsed.astimezone(now_ist.tzinfo).strftime("%d/%m/%Y"),
                        "min_price": min_f,
                        "max_price": max_f,
                        "modal_price": modal_f,
                        "source": "CEDA Agmarknet API",
                        "source_url": "https://api.ceda.ashoka.edu.in/",
                        "_source_age_hours": round(age_hours, 2),
                    })
                print(
                    f"[MANDI_DEBUG] ceda_row_validation district={dname!r} raw={len(rows)} accepted={len(out)} "
                    f"rejected_date={rejected_date} rejected_stale={rejected_stale} "
                    f"rejected_price={rejected_price} rejected_district={rejected_district}"
                )
                return out

        batches = await asyncio.gather(*(district_prices(did, dname) for did, dname in districts.items()))
        rows = [r for batch in batches for r in batch]
        if not rows:
            return [], "CEDA returned no fresh records"
        print(f"[MANDI_DEBUG] ceda_prices_success records={len(rows)} commodity_source={commodity_meta_source!r} geography_source={geo_source!r}")
        return rows, ""

def _parse_mandi_date(value: str):
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("T", " ").replace("Z", "").strip()
    formats = (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
        "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
        "%d %b %Y", "%d %B %Y"
    )
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        except ValueError:
            continue
    return None


def _normalise_price(value: str):
    if value is None:
        return ""
    text = str(value).strip().replace(",", "").replace("₹", "").replace("રૂ.", "").replace("રૂ", "").strip()
    text = text.translate(str.maketrans("૦૧૨૩૪૫૬૭૮૯", "0123456789"))
    m = re.search(r"(?<!\d)(\d+(?:\.\d+)?)", text)
    if not m:
        return ""
    try:
        number = float(m.group(1))
    except ValueError:
        return ""
    if not (0 < number < 10000000):
        return ""
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def _price_float(value: str):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _price_per_20kg(value: str) -> str:
    """Convert official mandi price from ₹/quintal to ₹/20 kg."""
    number = _price_float(value)
    if number is None:
        return ""
    value20 = number / 5.0
    if abs(value20 - round(value20)) < 1e-9:
        return str(int(round(value20)))
    return f"{value20:.2f}".rstrip("0").rstrip(".")


def _normalise_mandi_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def pick(row, *keys):
        for key in keys:
            value = row.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    normalized = []
    for row in records:
        if not isinstance(row, dict):
            continue
        arrival = pick(row, "arrival_date", "Arrival_Date", "arrival date", "date", "Date")
        parsed = _parse_mandi_date(arrival)
        min_price = _normalise_price(pick(row, "min_price", "Min Price", "min price", "Min_Price", "Min_x0020_Price"))
        modal_price = _normalise_price(pick(row, "modal_price", "Modal Price", "modal price", "Modal_Price", "Modal_x0020_Price"))
        max_price = _normalise_price(pick(row, "max_price", "Max Price", "max price", "Max_Price", "Max_x0020_Price"))
        if not parsed or parsed > datetime.now(timezone(timedelta(hours=5, minutes=30))) + timedelta(minutes=5):
            continue
        min_f, modal_f, max_f = _price_float(min_price), _price_float(modal_price), _price_float(max_price)
        if min_f is None or modal_f is None or max_f is None or not (min_f > 0 and min_f <= modal_f <= max_f):
            continue
        if not pick(row, "source") or not pick(row, "source_url"):
            continue
        normalized.append({
            "state": pick(row, "state", "State"),
            "district": pick(row, "district", "District"),
            "market": pick(row, "market", "Market", "market_name"),
            "commodity": pick(row, "commodity", "Commodity"),
            "variety": pick(row, "variety", "Variety"),
            "arrival_date": arrival,
            "arrival_date_iso": parsed.isoformat() if parsed else "",
            "report_date": pick(row, "report_date", "reportDate", "requested_report_date"),
            "min_price": min_price,
            "modal_price": modal_price,
            "max_price": max_price,
            # Official source values are ₹/quintal. These display fields only
            # convert the official values to ₹/20kg; no derived average is created.
            "min_price_20kg": _price_per_20kg(min_price),
            "modal_price_20kg": _price_per_20kg(modal_price),
            "max_price_20kg": _price_per_20kg(max_price),
            "price_unit_source": "₹/quintal",
            "display_price_unit": "₹/20kg",
            "source": pick(row, "source"),
            "source_url": pick(row, "source_url"),
        })
    normalized.sort(key=lambda row: (
        row.get("arrival_date_iso", ""),
        _price_float(row.get("modal_price")) or -1.0,
        _norm_mandi_market(row.get("market", "")),
    ), reverse=True)
    now_date = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    for row in normalized:
        try:
            row_date = datetime.fromisoformat(row.get("arrival_date_iso", "")).date()
            age_days = max(0, (now_date - row_date).days)
        except Exception:
            age_days = None
        row["age_days"] = age_days
        if age_days == 0:
            row["freshness_status"] = "today"
            row["freshness_label_gu"] = "આજનો અધિકૃત ભાવ"
        elif age_days == 1:
            row["freshness_status"] = "recent"
            row["freshness_label_gu"] = "ગઈકાલનો અધિકૃત ભાવ"
        elif isinstance(age_days, int):
            row["freshness_status"] = "recent"
            row["freshness_label_gu"] = f"{age_days} દિવસ જૂનો અધિકૃત ભાવ"
        else:
            row["freshness_status"] = "unknown"
            row["freshness_label_gu"] = "તારીખ ચકાસો"
    return normalized

_GUJARATI_MARKET_NAME_MAP = {
    "rajkot":"રાજકોટ", "gondal":"ગોંડલ", "jetpur":"જેતપુર", "morbi":"મોરબી",
    "jamnagar":"જામનગર", "junagadh":"જુનાગઢ", "amreli":"અમરેલી", "bhavnagar":"ભાવનગર",
    "surendranagar":"સુરેન્દ્રનગર", "mehsana":"મહેસાણા", "patan":"પાટણ", "palanpur":"પાલનપુર",
    "deesa":"ડીસા", "visnagar":"વિસનગર", "himmatnagar":"હિંમતનગર", "anand":"આણંદ",
    "nadiad":"નડિયાદ", "bharuch":"ભરૂચ", "ankleshwar":"અંકલેશ્વર", "surat":"સુરત",
    "navsari":"નવસારી", "valsad":"વલસાડ", "vadodara":"વડોદરા", "ahmedabad":"અમદાવાદ",
    "botad":"બોટાદ", "bhuj":"ભુજ", "gandhidham":"ગાંધીધામ", "dahod":"દાહોદ",
    "godhra":"ગોધરા", "panchmahal":"પંચમહાલ", "dhoraji":"ધોરાજી", "upleta":"ઉપલેટા",
    "manavadar":"માણાવદર", "mangrol":"માંગરોળ", "porbandar":"પોરબંદર", "dwarka":"દ્વારકા",
    "kalavad":"કાલાવડ", "jamjodhpur":"જામજોધપુર", "lalpur":"લાલપુર", "tankara":"ટંકારા",
    "halvad":"હળવદ", "wankaner":"વાંકાનેર", "maliya":"માળિયા", "chotila":"ચોટીલા",
    "limbdi":"લીંબડી", "dhrangadhra":"ધ્રાંગધ્રા", "sayla":"સાયલા", "viramgam":"વિરમગામ",
    "dholka":"ધોળકા", "bavla":"બાવળા", "sanand":"સાણંદ", "kalol":"કલોલ", "kadi":"કડી",
    "sidhpur":"સિદ્ધપુર", "unja":"ઊંઝા", "visavadar":"વિસાવદર", "bantwa":"બાંટવા",
    "bagasara":"બગસરા", "savarkundla":"સાવરકુંડલા", "dhari":"ધારી", "rajula":"રાજુલા",
    "mahuva":"મહુવા", "talaja":"તળાજા", "palitana":"પાલીતાણા", "gariadhar":"ગારીયાધાર",
    "babra":"બાબરા", "jasdan":"જસદણ", "dhrol":"ધ્રોલ", "keshod":"કેશોદ",
    "kodinar":"કોડીનાર", "mendarda":"મેંદરડા", "talala":"તાલાલા", "una":"ઉના",
    "maliya hatina":"માળિયા હાટીના", "anjar":"અંજાર", "mandvi":"માંડવી", "mundra":"મુંદ્રા",
    "rapar":"રાપર", "mansa":"માણસા", "vijapur":"વિજાપુર", "kheralu":"ખેરાલુ",
    "vadnagar":"વડનગર", "modasa":"મોડાસા", "bayad":"બાયડ", "kapadvanj":"કપડવંજ",
    "petlad":"પેટલાદ", "borsad":"બોરસદ", "khambhat":"ખંભાત", "jambusar":"જંબુસર",
    "vagra":"વાગરા", "bardoli":"બારડોલી", "kamrej":"કામરેજ", "chikhli":"ચીખલી",
    "dharampur":"ધરમપુર", "umbergaon":"ઉમરગામ", "dabhoi":"ડભોઈ", "padra":"પાદરા",
    "karjan":"કરજણ", "savli":"સાવલી", "halol":"હાલોલ", "lunawada":"લુણાવાડા",
    "jhalod":"ઝાલોદ", "limkheda":"લીમખેડા", "devgadh baria":"દેવગઢ બારિયા",
    "santrampur":"સંતરામપુર", "mandvi kutch":"માંડવી", "mundra apmc":"મુંદ્રા"
}

def _mandi_market_display_gu(raw: str) -> str:
    clean=str(raw or "").strip()
    if not clean: return "યાર્ડ"
    key=_norm_mandi_market(clean)
    base=_GUJARATI_MARKET_NAME_MAP.get(key)
    if base: return f"{base} યાર્ડ"
    # Safe generic display: preserve official name separately, but make the UI
    # immediately understandable even for a newly added market.
    cleaned=re.sub(r"\bAPMC\b", "", clean, flags=re.I)
    cleaned=re.sub(r"\bAgricultural Produce Market Committee\b", "", cleaned, flags=re.I)
    cleaned=re.sub(r"\bMarket Yard\b|\bYard\b|\bMarket\b", "", cleaned, flags=re.I)
    cleaned=" ".join(cleaned.split()).strip(" -,")
    return f"{cleaned} યાર્ડ" if cleaned else "કૃષિ બજાર યાર્ડ"

@app.get("/api/v1/mandi/markets")
def mandi_markets(state: str = "Gujarat", commodity: str = "ALL"):
    """Return official AGMARKNET market names for a state.

    Source of truth is AGMARKNET 2.0.  The filters payload is treated as a
    relational master-data document: state/district/market tables are linked
    by ids when the market row itself does not carry state_id.  No APMC names
    are hardcoded and no price records are used to invent a master list.
    """
    state_name=(state or "Gujarat").strip() or "Gujarat"
    state_key=_norm_mandi_text(state_name)
    names=[]; seen=set(); errors=[]
    headers={
        "Accept":"application/json, text/plain, */*",
        "Origin":"https://agmarknet.gov.in",
        "Referer":"https://agmarknet.gov.in/",
        "User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/135 Safari/537.36",
    }
    timeout=httpx.Timeout(AGMARKNET_PUBLIC_TIMEOUT_SECONDS, connect=min(8.0,AGMARKNET_PUBLIC_TIMEOUT_SECONDS))

    def clean(v):
        return str(v or "").strip()

    market_keys=("market_name","marketName","market_name_en","marketNameEn","market","Market","apmc_name","apmcName","apmc","APMC")
    state_id_keys=("state_id","stateId","stateID","state_code","stateCode","stateid")
    state_name_keys=("state_name","stateName","state","State")
    district_id_keys=("district_id","districtId","districtID","district_code","districtCode","districtid")
    district_name_keys=("district_name","districtName","district","District")

    def add_name(name):
        text=clean(name)
        if not text: return False
        key=_norm_mandi_market(text)
        if key and key not in seen:
            seen.add(key); names.append(text); return True
        return False

    def row_field(row, keys):
        return _ag_pick(row,*keys) if isinstance(row,dict) else None

    def extract_filter_tables(data_obj, expected_state_id):
        if not isinstance(data_obj,dict):
            print(f"[MANDI_DEBUG] agmarknet_market_filters_data_type type={type(data_obj).__name__}")
            return
        print(f"[MANDI_DEBUG] agmarknet_market_filters_data_keys keys={list(data_obj.keys())!r}")

        tables={}
        def register_table(key, value):
            rows=[]
            if isinstance(value,list):
                rows=[x for x in value if isinstance(x,dict)]
            elif isinstance(value,dict):
                # A table may be wrapped one level deeper. Keep only immediate
                # list children so diagnostics remain bounded and readable.
                for child_key, child in value.items():
                    if isinstance(child,list):
                        child_rows=[x for x in child if isinstance(x,dict)]
                        print(f"[MANDI_DEBUG] agmarknet_market_filter_container parent={key!r} child={child_key!r} type=list rows={len(child_rows)}")
                        if child_rows:
                            print(f"[MANDI_DEBUG] agmarknet_market_filter_row_keys parent={key!r} child={child_key!r} keys={list(child_rows[0].keys())!r}")
                        tables[f"{key}.{child_key}"]=child_rows
                        rows.extend(child_rows)
            if isinstance(value,(list,dict)):
                print(f"[MANDI_DEBUG] agmarknet_market_filter_container key={key!r} type={type(value).__name__} rows={len(rows)}")
                if rows:
                    print(f"[MANDI_DEBUG] agmarknet_market_filter_row_keys key={key!r} keys={list(rows[0].keys())!r}")
            if rows:
                tables[key]=rows

        for key,value in data_obj.items():
            register_table(key,value)

        # Build state/district lookup tables first. This fixes the real failure
        # where market rows can contain district_id but not state_id.
        state_by_id={}
        district_by_id={}
        for table_name,rows in tables.items():
            for row in rows:
                sid=row_field(row,state_id_keys)
                sn=clean(row_field(row,state_name_keys))
                if sid is not None and sn:
                    try: state_by_id[int(sid)]=sn
                    except (TypeError,ValueError): pass
                did=row_field(row,district_id_keys)
                dn=clean(row_field(row,district_name_keys))
                dsid=row_field(row,state_id_keys)
                if did is not None and dn:
                    try: district_by_id[int(did)]={"name":dn,"state_id":dsid}
                    except (TypeError,ValueError): pass

        # Determine which tables are market-bearing and resolve state through
        # explicit state_id, state name, or district -> state relationship.
        before_total=len(names)
        for table_name,rows in tables.items():
            before=len(names)
            for row in rows:
                market_value=row_field(row,market_keys)
                if not market_value: continue

                sid=row_field(row,state_id_keys)
                sname=clean(row_field(row,state_name_keys))
                did=row_field(row,district_id_keys)
                if sid is None and did is not None:
                    try:
                        dmeta=district_by_id.get(int(did),{})
                        sid=dmeta.get("state_id")
                        if not sname: sname=dmeta.get("state_name","")
                    except (TypeError,ValueError):
                        pass
                if sid is not None and not sname:
                    try: sname=state_by_id.get(int(sid),"")
                    except (TypeError,ValueError): pass

                matches_state=False
                if sid is not None:
                    try: matches_state=int(sid)==int(expected_state_id)
                    except (TypeError,ValueError): matches_state=False
                if not matches_state and sname:
                    matches_state=_norm_mandi_text(sname)==state_key
                if matches_state:
                    add_name(market_value)
            if len(names)>before:
                print(f"[MANDI_DEBUG] agmarknet_market_filter_market_extract key={table_name!r} candidates_added={len(names)-before}")

        print(f"[MANDI_DEBUG] agmarknet_market_filter_total_added={len(names)-before_total}")

    async def fetch_state_id(client):
        try:
            r=await client.get("/location/state",params={"page":1,"search":state_name})
            if r.status_code!=200: return None,f"HTTP {r.status_code}"
            body=r.json()
            for row in _ag_deep_rows(body):
                nm=clean(_ag_pick(row,"name","state_name","stateName","State","state"))
                sid=_ag_pick(row,"id","state_id","stateId","stateCode")
                if nm and sid is not None and _norm_mandi_text(nm)==state_key:
                    try: return int(sid),""
                    except (TypeError,ValueError): pass
            return None,"AGMARKNET state resolution failed"
        except Exception as exc:
            return None,f"{type(exc).__name__}: {str(exc)[:160]}"

    async def fetch_all():
        async with httpx.AsyncClient(base_url=AGMARKNET_PUBLIC_BASE,headers=headers,timeout=timeout) as client:
            state_id,state_err=await fetch_state_id(client)
            if state_err: errors.append(state_err)
            print(f"[MANDI_DEBUG] agmarknet_market_state_resolved state={state_name!r} id={state_id!r}")
            if state_id is None: return

            try:
                r=await client.get("/daily-price-arrival/filters")
                if r.status_code==200:
                    body=r.json()
                    print(f"[MANDI_DEBUG] agmarknet_market_filters_shape top_keys={list(body.keys())[:20]!r}" if isinstance(body,dict) else f"[MANDI_DEBUG] agmarknet_market_filters_shape type={type(body).__name__}")
                    data_obj=body.get("data") if isinstance(body,dict) else None
                    extract_filter_tables(data_obj,state_id)
                else:
                    errors.append(f"filters HTTP {r.status_code}")
            except Exception as exc:
                errors.append(f"filters {type(exc).__name__}: {str(exc)[:160]}")

            # If the master filters table has no market rows, use the verified
            # commodity-specific report as a secondary discovery source. It
            # exposes an explicit `markets[].marketName`. We intentionally use
            # it only to discover names, never as a price fallback here.
            if not names:
                discovery_commodity=(commodity or "ALL").strip() or "ALL"
                if discovery_commodity.upper()=="ALL": discovery_commodity="Groundnut"
                ckey=_norm_mandi_text(discovery_commodity)
                try:
                    # Resolve commodity id using the same public filter data.
                    commodity_id=None
                    if isinstance(data_obj,dict):
                        for rows in [v for v in data_obj.values() if isinstance(v,list)]:
                            for row in rows:
                                nm=clean(_ag_pick(row,"commodity_name","commodityName","cmdt_name","cmdtName","commodity","name"))
                                cid=_ag_pick(row,"cmdt_id","cmdtId","commodity_id","commodityId","commodityCode","id","code")
                                if nm and cid is not None and _norm_mandi_text(nm)==ckey:
                                    commodity_id=int(cid); break
                            if commodity_id is not None: break
                    if commodity_id is not None:
                        now=datetime.now(timezone(timedelta(hours=5,minutes=30)))
                        r=await client.get("/prices-and-arrivals/date-wise/specific-commodity",params={"year":str(now.year),"month":str(now.month),"stateId":str(state_id),"commodityId":str(commodity_id),"includeExcel":"false"})
                        if r.status_code==200:
                            body=r.json(); markets=body.get("markets") if isinstance(body,dict) else None
                            if isinstance(markets,list):
                                before=len(names)
                                for m in markets:
                                    if isinstance(m,dict): add_name(m.get("marketName"))
                                print(f"[MANDI_DEBUG] agmarknet_market_specific_discovery commodity={discovery_commodity!r} markets={len(markets)} added={len(names)-before}")
                    else:
                        print(f"[MANDI_DEBUG] agmarknet_market_specific_discovery skipped commodity_id_unresolved commodity={discovery_commodity!r}")
                except Exception as exc:
                    errors.append(f"specific-market-discovery {type(exc).__name__}: {str(exc)[:160]}")

    try:
        asyncio.run(fetch_all())
    except RuntimeError:
        def _runner(): return asyncio.run(fetch_all())
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_runner).result(timeout=AGMARKNET_PUBLIC_TIMEOUT_SECONDS*4+5)

    names=sorted(names,key=lambda x:_norm_mandi_market(x))
    print(f"[MANDI_DEBUG] agmarknet_market_master state={state_name!r} count={len(names)}")
    options=[{"official_name":name,"display_name_gu":_mandi_market_display_gu(name)} for name in names[:2000]]
    return {"ok":bool(names),"state":state_name,"commodity":"ALL","markets":names[:2000],"market_options":options,"count":len(names),"source":"AGMARKNET 2.0","source_url":"https://agmarknet.gov.in/home","errors":errors[:10]}

@app.get("/api/v1/mandi/today-summary/crop")
def mandi_today_summary_crop(state: str = "Gujarat", market: str = "", commodity: str = ""):
    """Fetch one approved crop with a bounded total wall-clock budget."""
    requested = (commodity or "").strip()
    allowed_crops = set(MANDI_SUMMARY_CROPS) | set(GUJARATI_CROP_ALIASES.keys()) | set(GUJARATI_CROP_ALIASES.values())
    if requested not in allowed_crops:
        return {
            "ok": False, "live_available": False, "crop": requested or "પાક",
            "records": [], "message": "આ પાક માટે Live ભાવ તપાસવાની મંજૂરી નથી.",
            "live_error": "unsupported_summary_crop"
        }
    started = time.monotonic()
    checked_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%m-%Y %H:%M")
    try:
        payload = mandi(
            state=state, market=market, commodity=requested,
            request_deadline=started + MANDI_TOTAL_BUDGET_SECONDS,
        )
    except Exception as exc:
        payload = {"ok": False, "live_available": False, "source": "none", "records": [],
                   "message": "આ પાક માટે બજાર ભાવ તપાસી શકાયા નથી.",
                   "live_error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    records = payload.get("records") if isinstance(payload, dict) else []
    if not isinstance(records, list): records = []
    elapsed = round(time.monotonic() - started, 2)
    return {
        "ok": bool(payload.get("ok", False)) if isinstance(payload, dict) else False,
        "crop": requested,
        "live_available": bool(payload.get("live_available", False)) if isinstance(payload, dict) else False,
        "source": str(payload.get("source", "") or "") if isinstance(payload, dict) else "",
        "checked_at": str(payload.get("checked_at", checked_at) or checked_at) if isinstance(payload, dict) else checked_at,
        "message": str(payload.get("message", "") or "") if isinstance(payload, dict) else "",
        "live_error": str(payload.get("live_error", "") or "") if isinstance(payload, dict) else "",
        "records": records[:100],
        "latest_arrival_date": payload.get("latest_arrival_date", "") if isinstance(payload, dict) else "",
        "source_policy": "AGMARKNET 2.0 primary + official data.gov.in fallback + validated CEDA fallback",
        "request_budget_seconds": MANDI_TOTAL_BUDGET_SECONDS,
        "elapsed_seconds": elapsed,
    }

@app.get("/api/v1/mandi/today-summary")
def mandi_today_summary(state: str = "Gujarat", market: str = ""):
    """Sequential farmer summary for the five primary Gujarat crops.

    Each crop is fetched independently through the existing verified /mandi
    flow, so one crop's API limit/error cannot suppress the others. The Android
    client can use the crop endpoint above for progressive rendering, while
    this endpoint remains the compact all-crops compatibility API.
    """
    checked_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%m-%Y %H:%M")
    items=[]
    for crop in MANDI_SUMMARY_CROPS:
        try:
            payload=mandi(state=state, market=market, commodity=crop)
        except Exception as exc:
            payload={"ok":False,"live_available":False,"source":"none","records":[],"message":"આ પાક માટે બજાર ભાવ તપાસી શકાયા નથી.","live_error":f"{type(exc).__name__}: {str(exc)[:160]}"}
        records=payload.get("records") if isinstance(payload,dict) else []
        if not isinstance(records,list): records=[]
        items.append({
            "crop":crop,
            "live_available":bool(payload.get("live_available",False)) if isinstance(payload,dict) else False,
            "source":str(payload.get("source","") or "") if isinstance(payload,dict) else "",
            "checked_at":str(payload.get("checked_at",checked_at) or checked_at) if isinstance(payload,dict) else checked_at,
            "message":str(payload.get("message","") or "") if isinstance(payload,dict) else "",
            "live_error":str(payload.get("live_error","") or "") if isinstance(payload,dict) else "",
            "records":records[:100]
        })
    available=sum(1 for x in items if x["live_available"] and x["records"])
    return {"ok":True,"state":(state or "Gujarat").strip() or "Gujarat","market":(market or "").strip(),"checked_at":checked_at,"items":items,"available_crops":available,"total_crops":len(items),"source_policy":"AGMARKNET 2.0 primary + official data.gov.in fallback + validated CEDA fallback"}

@app.get("/api/v1/mandi")
def mandi(state: str = "Gujarat", market: str = "", commodity: str = "ALL", request_deadline: float | None = None):
    """Official live Mandi endpoint.

    Fast path: AGMARKNET 2.0 public backend, because it is the currently
    verified working live source and exposes official arrivalDate/min/max/modal.
    Secondary official fallback: data.gov.in resource.  No cache/news/AI price
    is ever returned as live data.
    """
    checked_at = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime("%d-%m-%Y %H:%M")
    requested_commodity=(commodity or "ALL").strip() or "ALL"
    deadline = request_deadline if request_deadline is not None else (time.monotonic() + MANDI_TOTAL_BUDGET_SECONDS)
    if time.monotonic() >= deadline:
        return {"ok": True, "live_available": False, "live_api_configured": bool(MANDI_API_KEY), "source": "none", "checked_at": checked_at, "records": [], "message": "Live Mandi માટે સમય મર્યાદા પૂરી થઈ ગઈ.", "live_error": "mandi_total_budget_exceeded"}

    # 1) FAST PRIMARY: verified AGMARKNET 2.0 live path.
    try:
        remaining = max(0.5, deadline - time.monotonic())
        async def _ag_bounded():
            return await asyncio.wait_for(
                _fetch_agmarknet_2_live(state, market, requested_commodity, request_deadline=deadline),
                timeout=remaining,
            )
        ag_records, ag_error = asyncio.run(_ag_bounded())
    except Exception as exc:
        ag_records, ag_error = [], f"{type(exc).__name__}: {str(exc)[:180]}"

    if ag_records:
        normalized=_normalise_mandi_records(ag_records)
        if normalized:
            print(f"[MANDI_DEBUG] fast_primary_success source='agmarknet_2_public' records={len(normalized)}")
            return {
                "ok":True,
                "live_available":True,
                "live_api_configured":True,
                "source":"agmarknet_2_public",
                "checked_at":checked_at,
                "price_unit_source":"₹/quintal (AGMARKNET 2.0)",
                "display_price_unit":"₹/20kg",
                "records":normalized[:100],
                "message":"Live AGMARKNET ભાવ મળ્યા.",
                "latest_arrival_date": (normalized[0].get("arrival_date") if normalized else ""),
                "diagnostics":{"primary":{"request_ok":True,"records":len(normalized),"source":"agmarknet_2_public"},"fallback":{"attempted":False,"source":"data.gov.in"}}
            }
    print(f"[MANDI_DEBUG] fast_primary_failed source='agmarknet_2_public' error={ag_error!r}")

    # 2) SECONDARY OFFICIAL FALLBACK: data.gov.in.
    if time.monotonic() >= deadline:
        return {"ok": True, "live_available": False, "live_api_configured": bool(MANDI_API_KEY), "source": "none", "checked_at": checked_at, "records": [], "message": "Live Mandi માટે સમય મર્યાદા પૂરી થઈ ગઈ.", "live_error": "mandi_total_budget_exceeded"}
    # AGMARKNET so a known-working request is never delayed by a blocked
    # data.gov.in connection.
    result=_mandi_api_get(state,market,requested_commodity,request_deadline=deadline)
    if len(result)==4:
        data,error,_cooldown,upstream_status=result
    else:
        data,error=result
        upstream_status=0

    if isinstance(data,dict):
        records=data.get("records") or []
        if not isinstance(records,list): records=[]
        raw_diag=data.get("_diagnostics",{}) if isinstance(data,dict) else {}
        raw_count=int(raw_diag.get("raw_record_count",len(records)) or len(records))
        http_status=int(raw_diag.get("http_status",upstream_status or 200) or 200)
        if records:
            print(f"[MANDI_DEBUG] data_gov_fallback_success records={len(records)}")
            return {
                "ok":True,"live_available":True,"live_api_configured":bool(MANDI_API_KEY),
                "source":"official_api","checked_at":checked_at,
                "price_unit_source":"₹/quintal (data.gov.in)","display_price_unit":"₹/20kg",
                "records":records[:100],"message":"Live Government Mandi ભાવ મળ્યા.",
                "latest_arrival_date": (records[0].get("arrival_date") if records else ""),
                "diagnostics":{"primary":{"request_ok":False,"records":0,"source":"agmarknet_2_public","error":ag_error or "no_records"},"fallback":{"request_ok":True,"http_status":http_status,"records":len(records),"source":"data.gov.in","raw_records":raw_count}}
            }

    # 3) Optional CEDA fallback remains only after both official paths fail.
    if time.monotonic() >= deadline:
        return {"ok": True, "live_available": False, "live_api_configured": bool(MANDI_API_KEY), "source": "none", "checked_at": checked_at, "records": [], "message": "Live Mandi માટે સમય મર્યાદા પૂરી થઈ ગઈ.", "live_error": "mandi_total_budget_exceeded"}
    if market:
        ceda_records,ceda_error=[],"CEDA skipped because requested market requires direct market-level provenance"
    else:
        try:
            remaining = max(0.5, deadline - time.monotonic())
            async def _ceda_bounded():
                return await asyncio.wait_for(
                    _fetch_ceda_fresh_mandi(state,"",requested_commodity),
                    timeout=min(float(MANDI_CEDA_TIMEOUT_SECONDS), remaining),
                )
            ceda_records,ceda_error=asyncio.run(_ceda_bounded())
        except Exception as exc:
            ceda_records,ceda_error=[],f"{type(exc).__name__}: {str(exc)[:180]}"
    if ceda_records:
        normalized=_normalise_mandi_records(ceda_records)
        if normalized:
            print(f"[MANDI_DEBUG] ceda_fallback_success records={len(normalized)}")
            return {"ok":True,"live_available":True,"live_api_configured":bool(MANDI_API_KEY),"source":"ceda_agmarknet_fallback","checked_at":checked_at,"price_unit_source":"₹/quintal (Agmarknet via CEDA)","display_price_unit":"₹/20kg","records":normalized[:100],"latest_arrival_date": (normalized[0].get("arrival_date") if normalized else ""),"message":"Live Agmarknet ભાવ મળ્યા.","diagnostics":{"primary":{"request_ok":False,"records":0,"source":"agmarknet_2_public","error":ag_error or "no_records"},"data_gov":{"request_ok":False,"source":"data.gov.in","error":error or "no_records"},"fallback":{"request_ok":True,"records":len(normalized),"source":"ceda_agmarknet_fallback"}}}

    print(f"[MANDI_DEBUG] final_result state={state!r} market={market!r} commodity={requested_commodity!r} records=0 source=none agmarknet_error={ag_error!r} data_gov_error={error or ''!r} ceda_error={ceda_error!r}")
    return {
        "ok":True,"live_available":False,"live_api_configured":bool(MANDI_API_KEY),
        "source":"none","checked_at":checked_at,"price_unit_source":"₹/quintal","display_price_unit":"₹/20kg",
        "records":[],"message":"હાલમાં Live Mandi ભાવ ઉપલબ્ધ નથી.","live_error":error or ag_error or ceda_error or "no_live_data",
        "diagnostics":{"primary":{"request_ok":False,"records":0,"source":"agmarknet_2_public","error":ag_error or "no_records"},"data_gov":{"request_ok":False,"http_status":int(upstream_status or 0),"records":0,"source":"data.gov.in","error":error or "no_records"},"ceda":{"request_ok":False,"records":0,"error":ceda_error or "no_records"}}
    }

