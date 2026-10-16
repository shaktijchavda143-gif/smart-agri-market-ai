# -*- coding: utf-8 -*-
"""Smart Agri-Market AI HTTP backend.
Wraps the supplied Smart Agri-Market Agent so the Android app can call it.
"""
import os
import asyncio
import base64
import importlib.util
import socket
import ssl
import http.client
import urllib.parse
import urllib.request
import urllib.error
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

APP_VERSION = "14.2 AI VISION QUOTA FALLBACK FIX"
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.7").strip() or "grok-4.7"
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip() or "openai/gpt-oss-120b"
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.6-flash").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# Separate vision models are used for fallback so the text-only Smart Guide model
# configured in GROQ_MODEL is never mistakenly used for image diagnosis.
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip() or "qwen/qwen3.8-27b"
XAI_VISION_MODEL = os.getenv("XAI_VISION_MODEL", os.getenv("XAI_MODEL", "grok-4.7")).strip() or "grok-4.7"

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
        "groq_vision_configured": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "groq_vision_model": GROQ_VISION_MODEL,
        "xai_vision_configured": bool(os.getenv("XAI_API_KEY", "").strip()),
        "xai_vision_model": XAI_VISION_MODEL,
        "mandi_api_configured": bool(MANDI_API_KEY),
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
    """Return canonical publisher name only for the approved publishers."""
    host = _hostname_from_url(source_url)
    if host:
        for name, domains in APPROVED_NEWS_SOURCES.items():
            if any(host == domain or host.endswith("." + domain) for domain in domains):
                return name
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
    title_text = (title or "").casefold()
    body_text = (description or "").casefold()
    text = title_text + " " + body_text
    if not text.strip():
        return 0.0
    title_hits = sum(1 for term in NEWS_FARMER_TERMS if term.casefold() in title_text)
    body_hits = sum(1 for term in NEWS_FARMER_TERMS if term.casefold() in body_text)
    score = min(1.0, title_hits * 0.22 + min(body_hits, 5) * 0.08)
    return round(score, 3)


def _news_query_for_category(crop: str, category: str) -> str:
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
    return True


def _crop_relevant(item: dict, crop: str) -> bool:
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
    crop_name = ""
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
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="પ્રશ્ન ખાલી છે.")

    ctx = req.context or {}
    prompt = f"ખેડૂત પ્રશ્ન: {req.question.strip()}\nખેડૂત સંદર્ભ: {ctx}"

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
    """Diagnose a crop photo with Gemini first, then configured vision fallbacks.

    Quota/rate-limit errors are not retried four times: the request immediately
    proceeds to configured fallback providers, avoiding wasted calls and delay.
    """
    crop = crop.strip()
    if not crop:
        raise HTTPException(status_code=400, detail="Please select a crop before diagnosis")

    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Image is empty")
    if len(data) > 7 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be under 7 MB")

    mime_type = (image.content_type or "image/jpeg").split(";", 1)[0].strip().lower()
    data_url = f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"

    prompt = f"""
તમે Smart Agri-Market AI ના ગુજરાતી કૃષિ ફોટો નિષ્ણાત છો.
પાક: {crop}
સંદર્ભ: {context or 'ઉપલબ્ધ નથી'}

ફોટાનું વિશ્લેષણ કરીને સંપૂર્ણ ગુજરાતીમાં જવાબ આપો.
વિભાગો: ફોટામાં શું દેખાય છે, સંભવિત સમસ્યા, કારણ, શું કરવું, નિયંત્રણ માર્ગદર્શન, સાવચેતી.
ફોટામાં ન દેખાતી બાબતોની કલ્પના ન કરો. ચોક્કસ દવા/ડોઝ અંગે સાવચેતી રાખો.
જો ફોટા પરથી રોગ અથવા જીવાત ખાતરીપૂર્વક ઓળખી ન શકાય, તો તે સ્પષ્ટ જણાવો.
"""

    gemini_error = ""
    quota_exhausted = False

    def _safe_error(exc: Exception) -> str:
        message = str(exc)[:600]
        # Never emit API credentials to Render logs.
        for secret in (
            GEMINI_API_KEY,
            os.getenv("GROQ_API_KEY", "").strip(),
            os.getenv("XAI_API_KEY", "").strip(),
        ):
            if secret:
                message = message.replace(secret, "[REDACTED_API_KEY]")
        return message

    def _is_quota_error(exc: Exception) -> bool:
        body = f"{type(exc).__name__} {exc}".lower()
        return any(marker in body for marker in (
            "resource_exhausted", "quota exceeded", "free_tier_requests",
            "rate limit", "429 too many requests", "status_code=429",
        )) or getattr(exc, "code", None) == 429

    def _text_from_content(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            bits = []
            for item in content:
                if isinstance(item, dict):
                    value = item.get("text")
                    if value:
                        bits.append(str(value))
                else:
                    value = getattr(item, "text", None)
                    if value:
                        bits.append(str(value))
            return "\n".join(bits).strip()
        return ""

    def _success(answer: str, provider: str, model: str, mode: str, warning: str | None = None):
        result = {
            "success": True,
            "answer": answer,
            "mode": mode,
            "provider": provider,
            "model": model,
        }
        if warning:
            result["warning"] = warning
        return result

    # Primary provider: Gemini. Make one app-level request. A 429 quota error
    # is handled as a provider failure and falls through immediately.
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            part = types.Part.from_bytes(data=data, mime_type=mime_type)
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
            if answer:
                print(
                    f"[AI_DIAGNOSE] provider=gemini model={GEMINI_VISION_MODEL!r} status=success image_bytes={len(data)}",
                    flush=True,
                )
                return _success(answer, "gemini", GEMINI_VISION_MODEL, "gemini_vision")
            raise RuntimeError("Gemini returned an empty response")
        except Exception as exc:
            gemini_error = _safe_error(exc)
            quota_exhausted = _is_quota_error(exc)
            print(
                "[AI_DIAGNOSE] "
                f"provider=gemini model={GEMINI_VISION_MODEL!r} "
                f"exception_type={type(exc).__name__} quota_or_rate_limit={quota_exhausted} "
                f"image_bytes={len(data)} error={gemini_error!r}",
                flush=True,
            )
    else:
        gemini_error = "GEMINI_API_KEY is not configured"
        print("[AI_DIAGNOSE] provider=gemini status=skipped reason=missing_api_key", flush=True)

    # Fallback 1: Groq Qwen vision model (do not use GROQ_MODEL here; it may
    # be text-only). Enabled only when GROQ_API_KEY is configured.
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            client = OpenAI(
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
                timeout=90.0,
                max_retries=0,
            )
            completion = await asyncio.to_thread(
                client.chat.completions.create,
                model=GROQ_VISION_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                temperature=0.2,
                max_tokens=4096,
            )
            message = completion.choices[0].message.content if completion.choices else ""
            answer = _text_from_content(message)
            if answer:
                print(
                    f"[AI_DIAGNOSE] provider=groq model={GROQ_VISION_MODEL!r} status=success image_bytes={len(data)}",
                    flush=True,
                )
                return _success(
                    answer, "groq", GROQ_VISION_MODEL, "groq_vision_fallback",
                    "Gemini unavailable; Groq vision fallback used.",
                )
            raise RuntimeError("Groq vision returned an empty response")
        except Exception as exc:
            print(
                "[AI_DIAGNOSE] "
                f"provider=groq model={GROQ_VISION_MODEL!r} "
                f"exception_type={type(exc).__name__} error={_safe_error(exc)!r}",
                flush=True,
            )
    else:
        print("[AI_DIAGNOSE] provider=groq status=skipped reason=missing_api_key", flush=True)

    # Fallback 2: xAI Grok vision, enabled only when XAI_API_KEY exists.
    xai_key = os.getenv("XAI_API_KEY", "").strip()
    if xai_key:
        try:
            client = OpenAI(
                api_key=xai_key,
                base_url="https://api.x.ai/v1",
                timeout=120.0,
                max_retries=0,
            )
            response = await asyncio.to_thread(
                client.responses.create,
                model=XAI_VISION_MODEL,
                instructions=SYSTEM,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_image", "image_url": data_url, "detail": "high"},
                            {"type": "input_text", "text": prompt},
                        ],
                    }
                ],
            )
            answer = (getattr(response, "output_text", "") or "").strip()
            if answer:
                print(
                    f"[AI_DIAGNOSE] provider=xai model={XAI_VISION_MODEL!r} status=success image_bytes={len(data)}",
                    flush=True,
                )
                return _success(
                    answer, "xai", XAI_VISION_MODEL, "xai_vision_fallback",
                    "Gemini unavailable; xAI vision fallback used.",
                )
            raise RuntimeError("xAI vision returned an empty response")
        except Exception as exc:
            print(
                "[AI_DIAGNOSE] "
                f"provider=xai model={XAI_VISION_MODEL!r} "
                f"exception_type={type(exc).__name__} error={_safe_error(exc)!r}",
                flush=True,
            )
    else:
        print("[AI_DIAGNOSE] provider=xai status=skipped reason=missing_api_key", flush=True)

    # Use client-safe Gujarati errors. Detailed causes stay in server logs.
    if quota_exhausted:
        raise HTTPException(
            status_code=503,
            detail=(
                "હાલમાં Gemini APIની ક્વોટા મર્યાદા પૂરી થઈ છે અને કોઈ વૈકલ્પિક "
                "ફોટો-નિદાન સેવા સફળ થઈ નથી. કૃપા કરીને AI પ્રોવાઇડરની ક્વોટા/બિલિંગ "
                "તપાસો અથવા થોડા સમય પછી ફરી પ્રયાસ કરો."
            ),
        )

    configured = bool(GEMINI_API_KEY or groq_key or xai_key)
    if not configured:
        raise HTTPException(
            status_code=503,
            detail="AI ફોટો નિદાન માટે કોઈ API પ્રોવાઇડરની કી ગોઠવેલી નથી.",
        )
    raise HTTPException(
        status_code=502,
        detail=(
            "AI ફોટો નિદાનની સેવાઓ હાલમાં જવાબ આપી રહી નથી. કૃપા કરીને થોડા સમય પછી ફરી પ્રયાસ કરો."
        ),
    )


# ---------------- Secure Mandi price bridge ----------------
def _mandi_env_seconds(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except Exception:
        return default

MANDI_RESOURCE_ID = os.getenv("DATA_GOV_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070").strip()
MANDI_API_KEY = (os.getenv("DATA_GOV_API_KEY") or os.getenv("MANDI_API_KEY") or "").strip()
DATA_GOV_BASE_URL = os.getenv("DATA_GOV_BASE_URL", "https://api.data.gov.in").strip().rstrip("/")
_parsed_dg = urllib.parse.urlsplit(DATA_GOV_BASE_URL if "://" in DATA_GOV_BASE_URL else f"https://{DATA_GOV_BASE_URL}")
MANDI_API_SCHEME = _parsed_dg.scheme or "https"
MANDI_API_HOST = _parsed_dg.netloc or "api.data.gov.in"
MANDI_API_BASE_PATH = _parsed_dg.path.rstrip("/")

MANDI_API_TIMEOUT_SECONDS = _mandi_env_seconds("MANDI_TIMEOUT_SECONDS", 10, 5, 30)
MANDI_RATE_LIMIT_COOLDOWN_SECONDS = _mandi_env_seconds("MANDI_RATE_LIMIT_COOLDOWN_SECONDS", 15, 5, 60)
MANDI_PAGE_SIZE = _mandi_env_seconds("MANDI_PAGE_SIZE", 500, 100, 1000)
MANDI_MAX_PAGES = _mandi_env_seconds("MANDI_MAX_PAGES", 5, 1, 20)
MANDI_SUMMARY_CROPS = ("મગફળી", "કપાસ", "જીરું", "એરંડા", "ડુંગળી")
CEDA_API_KEY = os.getenv("CEDA_API_KEY", "").strip()
CEDA_API_BASE = os.getenv("CEDA_API_BASE", "https://api.ceda.ashoka.edu.in/v1").strip().rstrip("/")
MANDI_FALLBACK_MAX_AGE_HOURS = _mandi_env_seconds("MANDI_FALLBACK_MAX_AGE_HOURS", 96, 1, 168)
MANDI_MAX_LOOKBACK_DAYS = 3
MANDI_AGMARKNET_DAILY_TIMEOUT_SECONDS = _mandi_env_seconds("MANDI_AGMARKNET_DAILY_TIMEOUT_SECONDS", 3, 1, 8)
MANDI_AGMARKNET_STATE_TIMEOUT_SECONDS = _mandi_env_seconds("MANDI_AGMARKNET_STATE_TIMEOUT_SECONDS", 3, 1, 8)
MANDI_CEDA_TIMEOUT_SECONDS = _mandi_env_seconds("MANDI_CEDA_TIMEOUT_SECONDS", 8, 3, 30)
MANDI_TOTAL_BUDGET_SECONDS = _mandi_env_seconds("MANDI_TOTAL_BUDGET_SECONDS", 30, 10, 45)
_mandi_rate_limit_until: dict[str, float] = {}
_mandi_global_rate_limit_until: float = 0.0
_mandi_lock = threading.RLock()

MANDI_SHARED_CACHE_FILE = "/tmp/playstore_shared_mandi_cache.json"
MANDI_SHARED_FRESH_TTL_SECONDS = 1800
_mandi_shared_pool: dict[str, dict[str, Any]] = {}


def _load_mandi_shared_pool() -> None:
    global _mandi_shared_pool
    if _mandi_shared_pool:
        return
    if os.path.exists(MANDI_SHARED_CACHE_FILE):
        try:
            with open(MANDI_SHARED_CACHE_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    _mandi_shared_pool = data
        except Exception:
            pass


def _save_mandi_shared_pool() -> None:
    try:
        with open(MANDI_SHARED_CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(_mandi_shared_pool, fh, ensure_ascii=False)
    except Exception:
        pass


def _store_in_shared_pool(state: str, market: str, commodity: str, payload: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if not records:
        return
    with _mandi_lock:
        _load_mandi_shared_pool()
        now_ts = time.time()
        c_key = _norm_mandi_text(GUJARATI_CROP_ALIASES.get(commodity.strip(), commodity.strip()))
        s_key = _norm_mandi_text(state or "Gujarat")
        m_key = _mandi_market_match_key(market) if market.strip() else "ALL"

        exact_key = f"{s_key}|{m_key}|{c_key}"
        _mandi_shared_pool[exact_key] = {"saved_at": now_ts, "payload": payload}

        by_yard: dict[str, list[dict[str, Any]]] = {}
        for r in records:
            r_mkt = _mandi_market_match_key(_mandi_row_market(r))
            if r_mkt:
                by_yard.setdefault(r_mkt, []).append(r)

        for y_key, y_rows in by_yard.items():
            yard_pool_key = f"{s_key}|{y_key}|{c_key}"
            yard_payload = dict(payload)
            yard_payload["records"] = y_rows
            _mandi_shared_pool[yard_pool_key] = {"saved_at": now_ts, "payload": yard_payload}

        _save_mandi_shared_pool()


def _get_from_shared_pool(state: str, market: str, commodity: str, max_age_seconds: float) -> dict[str, Any] | None:
    with _mandi_lock:
        _load_mandi_shared_pool()
        c_key = _norm_mandi_text(GUJARATI_CROP_ALIASES.get(commodity.strip(), commodity.strip()))
        s_key = _norm_mandi_text(state or "Gujarat")
        m_key = _mandi_market_match_key(market) if market.strip() else "ALL"
        exact_key = f"{s_key}|{m_key}|{c_key}"

        entry = _mandi_shared_pool.get(exact_key)
        if isinstance(entry, dict):
            saved_at = float(entry.get("saved_at", 0.0) or 0.0)
            payload = entry.get("payload")
            if isinstance(payload, dict) and payload.get("records") and (time.time() - saved_at <= max_age_seconds):
                return payload

        state_all_key = f"{s_key}|ALL|{c_key}"
        state_entry = _mandi_shared_pool.get(state_all_key)
        if m_key != "ALL" and isinstance(state_entry, dict):
            saved_at = float(state_entry.get("saved_at", 0.0) or 0.0)
            state_payload = state_entry.get("payload")
            if isinstance(state_payload, dict) and (time.time() - saved_at <= max_age_seconds):
                all_rows = state_payload.get("records") or []
                matched_rows = [r for r in all_rows if _mandi_markets_match(_mandi_row_market(r), market)]
                if matched_rows:
                    filtered_payload = dict(state_payload)
                    filtered_payload["records"] = matched_rows
                    return filtered_payload
    return None

GUJARATI_CROP_ALIASES = {
    "કપાસ": "Cotton", "મગફળી": "Groundnut", "ઘઉં": "Wheat", "બાજરી": "Bajra",
    "મકાઈ": "Maize", "જીરું": "Jeera", "ધાણા": "Dhaniya", "તલ": "Sesamum",
    "એરંડા": "Castor Seed", "ચણા": "Gram", "તુવેર": "Arhar", "મગ": "Moong",
    "અડદ": "Black Gram", "ડુંગળી": "Onion", "બટાકા": "Potato", "ટામેટા": "Tomato",
    "મરચાં": "Chilli", "લસણ": "Garlic", "શેરડી": "Sugarcane", "કેરી": "Mango",
    "કેળા": "Banana", "દાડમ": "Pomegranate"
}


# Scoped IPv4-only HTTPS opener used ONLY as a per-request fallback when default
# socket resolution fails with Errno 113 (IPv6 No route to host). Does NOT monkey-patch socket.getaddrinfo.
class _ScopedIPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        infos = socket.getaddrinfo(self.host, self.port or 443, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise OSError(f"No IPv4 address resolved for {self.host}")
        last_exc = None
        for fam, socktype, proto, _, sockaddr in infos:
            sock = None
            try:
                sock = socket.socket(fam, socktype, proto)
                if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(self.timeout)
                sock.connect(sockaddr)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except Exception as exc:
                last_exc = exc
                if sock is not None:
                    try:
                        sock.close()
                    except Exception:
                        pass
        if last_exc:
            raise last_exc


class _ScopedIPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_ScopedIPv4HTTPSConnection, req, context=self._context)


_SCOPED_IPV4_OPENER = urllib.request.build_opener(_ScopedIPv4HTTPSHandler(context=ssl.create_default_context()))


@app.get("/api/v1/mandi/network-test-1")
def mandi_network_test_1():
    """TEST 1: Read-only default network & DNS/TCP/TLS/HTTP diagnostic for api.data.gov.in.
    - No global socket monkey-patching.
    - Never logs or returns API keys.
    - Separates DNS, TCP, TLS, HTTP status, and bounded safe response body.
    """
    host = MANDI_API_HOST
    port = 443
    timeout_s = 8.0
    path_only = f"{MANDI_API_BASE_PATH}/resource/{MANDI_RESOURCE_ID}"

    # Stage 1: DNS Resolution
    dns_result: dict[str, Any] = {"status": "FAIL", "default_order": [], "ipv4": [], "ipv6": [], "error": ""}
    raw_order: list[tuple[str, str]] = []
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for fam, _, _, _, sockaddr in infos:
            ip = str(sockaddr[0])
            fam_label = "IPv4" if fam == socket.AF_INET else ("IPv6" if fam == socket.AF_INET6 else str(fam))
            if (fam_label, ip) not in raw_order:
                raw_order.append((fam_label, ip))
            if fam == socket.AF_INET and ip not in dns_result["ipv4"]:
                dns_result["ipv4"].append(ip)
            elif fam == socket.AF_INET6 and ip not in dns_result["ipv6"]:
                dns_result["ipv6"].append(ip)
        dns_result["default_order"] = [{"family": f, "ip": ip} for f, ip in raw_order]
        dns_result["status"] = "PASS" if raw_order else "FAIL"
    except Exception as exc:
        dns_result["error"] = _mandi_safe_error(exc)

    # Stage 2 & 3: Per-IP TCP & TLS Handshake
    tcp_results = []
    tls_results = []
    ssl_ctx = ssl.create_default_context()
    for fam_label, ip in raw_order:
        fam = socket.AF_INET if fam_label == "IPv4" else socket.AF_INET6
        sock = socket.socket(fam, socket.SOCK_STREAM)
        sock.settimeout(timeout_s)
        try:
            sock.connect((ip, port))
            tcp_results.append({"family": fam_label, "ip": ip, "status": "PASS", "error": ""})
            try:
                with ssl_ctx.wrap_socket(sock, server_hostname=host) as tls_sock:
                    cipher = tls_sock.cipher()
                    tls_results.append({
                        "family": fam_label,
                        "ip": ip,
                        "status": "PASS",
                        "protocol": tls_sock.version() or "",
                        "cipher": cipher[0] if cipher else "",
                        "error": "",
                    })
            except Exception as tls_exc:
                tls_results.append({
                    "family": fam_label,
                    "ip": ip,
                    "status": "FAIL",
                    "error": _mandi_safe_error(tls_exc),
                })
        except Exception as tcp_exc:
            errno_val = getattr(tcp_exc, "errno", None)
            tcp_results.append({
                "family": fam_label,
                "ip": ip,
                "status": "FAIL",
                "errno": errno_val,
                "error": _mandi_safe_error(tcp_exc),
            })
            tls_results.append({
                "family": fam_label,
                "ip": ip,
                "status": "SKIPPED_TCP_FAILED",
                "error": "TCP connection did not succeed",
            })
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def _probe_http(url: str, use_scoped_ipv4: bool = False) -> dict[str, Any]:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "SmartAgriMarketAI-Test1/1.0",
        })
        try:
            opener = _SCOPED_IPV4_OPENER.open if use_scoped_ipv4 else urllib.request.urlopen
            with opener(req, timeout=timeout_s) as resp:
                code = int(getattr(resp, "status", 200) or 200)
                raw_bytes = resp.read(4096)
                text = raw_bytes.decode("utf-8", "replace")
                safe_summary: dict[str, Any] = {}
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        safe_summary = {
                            "top_keys": list(parsed.keys())[:15],
                            "status": parsed.get("status"),
                            "total": parsed.get("total"),
                            "count": parsed.get("count"),
                            "records_len": len(parsed.get("records") or []),
                            "message": str(parsed.get("message") or parsed.get("error") or "")[:160],
                        }
                except Exception:
                    safe_summary = {"raw_snippet": _mandi_safe_error(Exception(text[:180]))}
                return {
                    "status": "PASS",
                    "http_status": code,
                    "safe_body": safe_summary,
                    "error": "",
                }
        except urllib.error.HTTPError as he:
            raw_err = ""
            try:
                raw_err = he.read(512).decode("utf-8", "replace")
            except Exception:
                pass
            return {
                "status": "REACHED_SERVER_HTTP_ERROR",
                "http_status": int(he.code or 0),
                "safe_body": _mandi_safe_error(Exception(raw_err[:200])),
                "note": "Unauthenticated HTTP error is expected when no key is sent; not proof of invalid API key." if he.code in (400, 401, 403) else "",
                "error": f"HTTP {he.code}",
            }
        except Exception as exc:
            return {
                "status": "FAIL",
                "http_status": 0,
                "safe_body": "",
                "error": _mandi_safe_error(exc),
            }

    # Stage 4 & 5: HTTP Status & Safe Body (Default opener vs Scoped IPv4 opener)
    unauth_url = f"{MANDI_API_SCHEME}://{host}{path_only}?format=json&limit=1"
    http_no_key_default = _probe_http(unauth_url, use_scoped_ipv4=False)
    http_no_key_ipv4 = _probe_http(unauth_url, use_scoped_ipv4=True)

    http_with_key_default = {"status": "SKIPPED_NO_KEY_CONFIGURED"}
    http_with_key_ipv4 = {"status": "SKIPPED_NO_KEY_CONFIGURED"}
    if MANDI_API_KEY:
        auth_params = urllib.parse.urlencode({
            "api-key": MANDI_API_KEY,
            "format": "json",
            "filters[state]": "Gujarat",
            "limit": "2",
        })
        auth_url = f"{MANDI_API_SCHEME}://{host}{path_only}?{auth_params}"
        http_with_key_default = _probe_http(auth_url, use_scoped_ipv4=False)
        http_with_key_ipv4 = _probe_http(auth_url, use_scoped_ipv4=True)

    return {
        "ok": True,
        "test": "TEST_1_DEFAULT_NETWORK_DIAGNOSTIC",
        "target_host": host,
        "resource_id": MANDI_RESOURCE_ID,
        "api_key_configured_in_env": bool(MANDI_API_KEY),
        "stage_1_dns_resolution": dns_result,
        "stage_2_tcp_connection": tcp_results,
        "stage_3_tls_handshake": tls_results,
        "stage_4_and_5_http_default_urllib": {
            "without_api_key": http_no_key_default,
            "with_configured_api_key": http_with_key_default,
        },
        "stage_4_and_5_http_scoped_ipv4": {
            "without_api_key": http_no_key_ipv4,
            "with_configured_api_key": http_with_key_ipv4,
        },
    }


def _norm_mandi_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", " ").replace("_", " ").split())


def _norm_mandi_market(value: Any) -> str:
    text = _norm_mandi_text(value)
    text = re.sub(r"^apmc\s+", "", text)
    text = re.sub(r"\s+apmc$", "", text)
    return text.strip()


def _mandi_market_match_key(value: Any) -> str:
    """Canonical key for strict market equality, ignoring APMC/Yard suffixes and punctuation."""
    text = _norm_mandi_market(value)
    for remove_word in (
        "કૃષિ ઉત્પન્ન બજાર સમિતિ યાર્ડ ",
        "કૃષિ ઉત્પન્ન બજાર સમિતિ",
        "માર્કેટ યાર્ડ ",
        "યાર્ડ ",
        "agricultural produce market committee",
        "market yard",
        "apmc",
        "yard",
        "market",
    ):
        text = text.replace(remove_word, " ")
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def _mandi_row_market(row: dict[str, Any]) -> str:
    """Read the raw market/APMC field from known data.gov.in row shapes."""
    for key in ("market", "Market", "market_name", "marketName", "market_name_en", "marketNameEn", "apmc_name", "apmcName"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _commodity_matches(row: dict[str, Any], requested: str) -> bool:
    """Keep only rows belonging to the requested commodity."""
    if not requested or requested.strip().upper() == "ALL":
        return True
    wanted = _norm_mandi_text(GUJARATI_CROP_ALIASES.get(requested.strip(), requested))
    aliases = {
        "groundnut": {"groundnut", "ground nuts", "peanut", "peanuts", "મગફળી"},
        "cotton": {"cotton", "kapas", "કપાસ"},
        "wheat": {"wheat", "ઘઉં"},
        "bajra": {"bajra", "pearl millet", "millet", "બાજરી"},
        "maize": {"maize", "corn", "મકાઈ"},
        "jeera": {"jeera", "cumin", "cummin", "cummin seed", "જીરું"},
        "dhaniya": {"dhania", "dhaniya", "coriander", "corriander", "ધાણા"},
        "sesamum": {"sesamum", "sesame", "til", "તલ"},
        "castor seed": {"castor seed", "castor", "એરંડા", "એરંડ"},
        "gram": {"gram", "chana", "bengal gram", "चना", "ચણા"},
        "arhar": {"arhar", "tur", "pigeon pea", "તુવેર"},
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
    """Keep every row from the newest report *date*, not just one timestamp."""
    dated = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        arrival = row.get("arrival_date") or row.get("Arrival_Date") or row.get("arrival date") or row.get("date") or row.get("Date")
        parsed = _parse_mandi_date(arrival)
        dated.append((row, parsed))
    valid = [parsed for _, parsed in dated if parsed]
    if not valid:
        return rows, ""
    latest_day = max(parsed.date() for parsed in valid)
    return [row for row, parsed in dated if parsed and parsed.date() == latest_day], latest_day.strftime("%d-%m-%Y")


def _mandi_normalized_result(
    payload: dict[str, Any],
    requested_commodity: str,
    fallback_used: bool = False,
    requested_market: str = "",
):
    """Normalize fresh rows and fail closed on rows from a different market."""
    raw_records = payload.get("records") or []
    if not isinstance(raw_records, list):
        raw_records = []
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    today_ist = now_ist.date()
    earliest_day = today_ist - timedelta(days=MANDI_MAX_LOOKBACK_DAYS)
    dated_records = []
    rejected_undated_or_stale = 0
    for row in raw_records:
        if not isinstance(row, dict):
            continue
        arrival = row.get("arrival_date") or row.get("Arrival_Date") or row.get("arrival date") or row.get("date") or row.get("Date")
        parsed = _parse_mandi_date(arrival)
        if not parsed:
            rejected_undated_or_stale += 1
            continue
        parsed_ist = parsed.astimezone(now_ist.tzinfo)
        # Check calendar day bounds first so midnight (00:00) timestamps on D-2/D-3
        # are not falsely discarded when MANDI_FALLBACK_MAX_AGE_HOURS is 48.
        if parsed_ist > now_ist + timedelta(minutes=5) or parsed_ist.date() < earliest_day or parsed_ist.date() > today_ist:
            rejected_undated_or_stale += 1
            continue
        enriched_row = dict(row)
        enriched_row.setdefault("source", "official_api")
        enriched_row.setdefault("source_url", "https://data.gov.in/")
        dated_records.append(enriched_row)
    raw_records = dated_records
    if requested_commodity and requested_commodity.strip().upper() != "ALL":
        raw_records = [r for r in raw_records if _commodity_matches(r, requested_commodity)]

    # Never trust an upstream market filter by itself. Enforce the selected
    # market again on actual rows before any prices are returned to the app.
    rejected_market_mismatch = 0
    observed_markets: list[str] = []
    if requested_market.strip():
        wanted_market_key = _mandi_market_match_key(requested_market)
        market_filtered = []
        for row in raw_records:
            row_market = _mandi_row_market(row)
            if row_market and row_market not in observed_markets and len(observed_markets) < 12:
                observed_markets.append(row_market)
            if row_market and _mandi_markets_match(row_market, requested_market):
                market_filtered.append(row)
            else:
                rejected_market_mismatch += 1
        raw_records = market_filtered
        print(
            "[MANDI_DEBUG] official_api_market_filter "
            f"requested_market={requested_market!r} accepted={len(raw_records)} "
            f"rejected_market_mismatch={rejected_market_mismatch} "
            f"observed_markets={observed_markets!r}",
            flush=True,
        )

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
            "requested_market": requested_market,
            "rejected_market_mismatch": rejected_market_mismatch,
            "observed_markets": observed_markets,
            "rejected_undated_or_outside_lookback": rejected_undated_or_stale,
            "fallback_used": fallback_used,
        },
    }

def _mandi_retry_after_seconds(exc: urllib.error.HTTPError) -> int:
    value = ""
    try:
        value = str(exc.headers.get("Retry-After", "")).strip()
    except Exception:
        value = ""
    if value:
        try:
            return max(10, min(int(value), 30))
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
    """Fetch exclusively from the official data.gov.in Mandi API."""
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
        print("[MANDI_DEBUG] official_api_exception exception_type='ConfigurationError' http_status=0 error='DATA_GOV_API_KEY is missing' ")
        return None, "Live Mandi API key server પર configure નથી. Renderમાં DATA_GOV_API_KEY ઉમેરો."

    rate_key = "|".join((state.lower(), market.lower(), api_commodity.lower()))
    now = time.monotonic()
    with _mandi_lock:
        cooldown_until = max(_mandi_rate_limit_until.get(rate_key, 0.0), _mandi_global_rate_limit_until)
    if cooldown_until > now:
        print(
            "[MANDI_DEBUG] official_api_rate_limit_cooldown "
            f"state={state!r} market={market!r} commodity={normalized_commodity!r}"
        )
        return None, "Live Mandi API limit પર છે; થોડા સમય પછી ફરી પ્રયાસ કરો."

    path = f"{MANDI_API_BASE_PATH}/resource/{MANDI_RESOURCE_ID}"
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
    aggregated = []
    use_ipv4_fallback = False

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
                opener = _SCOPED_IPV4_OPENER.open if use_ipv4_fallback else urllib.request.urlopen
                with opener(req, timeout=remaining) as response:
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
                    if not isinstance(page_rows, list):
                        page_rows = []
                    for row in page_rows:
                        if isinstance(row, dict):
                            row.setdefault("source", "official_api")
                            row.setdefault("source_url", "https://data.gov.in/")
                            aggregated.append(row)
                    print(f"[MANDI_DEBUG] official_api_page rows={len(page_rows)} aggregated={len(aggregated)}")
                    if len(page_rows) < MANDI_PAGE_SIZE:
                        normalized = _mandi_normalized_result({"records": aggregated}, normalized_commodity, fallback_used=False, requested_market=market)
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
                        normalized = _mandi_normalized_result({"records": aggregated}, normalized_commodity, fallback_used=False, requested_market=market)
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
                if last_status not in (500, 502, 503, 504, 520, 521, 522, 523, 524):
                    return None, last_error, 0, last_status
            except urllib.error.URLError as exc:
                last_status = 0
                _mandi_log_exception(exc, http_status=0)
                last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
                reason = getattr(exc, "reason", None)
                reason_errno = getattr(reason, "errno", None)
                # If default resolution hit IPv6 Errno 113 (No route to host), switch
                # the next attempt to the scoped IPv4 opener without global monkey-patching.
                if reason_errno == 113 and not use_ipv4_fallback:
                    use_ipv4_fallback = True
                    continue
                connection_refused = isinstance(reason, ConnectionRefusedError) or reason_errno in (111, 10061)
                if connection_refused:
                    print("[MANDI_DEBUG] official_api_retry_skipped reason='connection_refused'")
                    return None, last_error, 0, last_status
            except TimeoutError as exc:
                last_status = 0; _mandi_log_exception(exc, http_status=0); last_error = "Live Mandi API timeout થયો."
            except Exception as exc:
                last_status = 0; _mandi_log_exception(exc, http_status=0); last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
            if attempt < 1:
                sleep_for = 1.0 if deadline is None else min(1.0, max(0.0, deadline - time.monotonic()))
                if sleep_for > 0:
                    time.sleep(sleep_for)
    if market and not aggregated:
        broad_result = _mandi_api_get(state, "", commodity, request_deadline=deadline)
        if isinstance(broad_result, tuple) and len(broad_result) >= 1:
            broad_payload = broad_result[0]
            broad_status = int(broad_result[3] if len(broad_result) >= 4 else 0 or 0)
            if isinstance(broad_payload, dict):
                broad_records = broad_payload.get("records") or []
                if isinstance(broad_records, list):
                    matched_rows = [r for r in broad_records if isinstance(r, dict) and _mandi_markets_match(_mandi_row_market(r), market)]
                    if matched_rows:
                        normalized = _mandi_normalized_result({"records": matched_rows}, normalized_commodity, fallback_used=False, requested_market=market)
                        normalized["_diagnostics"]["fallback_market_filter"] = True
                        normalized["_diagnostics"]["fallback_http_status"] = broad_status
                        with _mandi_lock:
                            _mandi_rate_limit_until.pop(rate_key, None)
                            _mandi_global_rate_limit_until = 0.0
                        return normalized, "", 0, broad_status

    print(f"[MANDI_DEBUG] official_api_final_failure http_status={last_status} error={last_error!r}")
    return None, last_error, 0, last_status


_ceda_commodity_cache: dict[str, tuple[Any, float]] = {}
_ceda_geography_cache: tuple[Any, float] | None = None
_CEDA_METADATA_CACHE_SECONDS = 6 * 60 * 60
_CEDA_PUBLIC_BASE = "https://agmarknet.ceda.ashoka.edu.in/api"
_ceda_rate_limit_until: float = 0.0
_ceda_rate_limit_seconds: int = 0
_ceda_rate_limit_source: str = ""
_CEDA_RATE_LIMIT_MAX_SECONDS = 7 * 24 * 60 * 60

# Official Agmarknet/CEDA static commodity & Gujarat district IDs used only as a
# metadata fallback when CEDA's /commodities or /geographies endpoint returns 401.
# Never invents prices or dates; only supplies IDs to query real /api/prices.
_CEDA_STATIC_COMMODITIES = [
    {"commodity_id": 10, "commodity_name": "Groundnut"},
    {"commodity_id": 15, "commodity_name": "Cotton"},
    {"commodity_id": 1, "commodity_name": "Wheat"},
    {"commodity_id": 28, "commodity_name": "Bajra"},
    {"commodity_id": 4, "commodity_name": "Maize"},
    {"commodity_id": 42, "commodity_name": "Jeera"},
    {"commodity_id": 43, "commodity_name": "Dhaniya"},
    {"commodity_id": 11, "commodity_name": "Sesamum"},
    {"commodity_id": 123, "commodity_name": "Castor Seed"},
    {"commodity_id": 6, "commodity_name": "Gram"},
    {"commodity_id": 49, "commodity_name": "Arhar"},
    {"commodity_id": 9, "commodity_name": "Moong"},
    {"commodity_id": 8, "commodity_name": "Black Gram"},
    {"commodity_id": 23, "commodity_name": "Onion"},
    {"commodity_id": 24, "commodity_name": "Potato"},
    {"commodity_id": 78, "commodity_name": "Tomato"},
    {"commodity_id": 26, "commodity_name": "Chilli"},
    {"commodity_id": 25, "commodity_name": "Garlic"},
]

_CEDA_STATIC_GUJARAT_GEOGRAPHIES = [
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 474, "census_district_name": "Ahmedabad"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 480, "census_district_name": "Amreli"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 469, "census_district_name": "Banaskantha"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 481, "census_district_name": "Bhavnagar"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 477, "census_district_name": "Jamnagar"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 479, "census_district_name": "Junagadh"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 468, "census_district_name": "Kachchh"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 471, "census_district_name": "Mehsana"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 470, "census_district_name": "Patan"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 476, "census_district_name": "Rajkot"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 472, "census_district_name": "Sabarkantha"},
    {"census_state_id": 24, "census_state_name": "Gujarat", "census_district_id": 475, "census_district_name": "Surendranagar"},
]


def _ceda_retry_after_seconds(value: Any) -> int:
    raw = str(value or "").strip()
    if raw:
        try:
            return max(60, min(int(raw), _CEDA_RATE_LIMIT_MAX_SECONDS))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                seconds = int((retry_at - datetime.now(timezone.utc)).total_seconds())
                return max(60, min(seconds, _CEDA_RATE_LIMIT_MAX_SECONDS))
            except Exception:
                pass
    return max(60, min(MANDI_RATE_LIMIT_COOLDOWN_SECONDS, _CEDA_RATE_LIMIT_MAX_SECONDS))


def _ceda_note_rate_limit(retry_after: Any, source: str) -> int:
    global _ceda_rate_limit_until, _ceda_rate_limit_seconds, _ceda_rate_limit_source
    seconds = _ceda_retry_after_seconds(retry_after)
    until = time.monotonic() + seconds
    if until >= _ceda_rate_limit_until:
        _ceda_rate_limit_until = until
        _ceda_rate_limit_seconds = seconds
        _ceda_rate_limit_source = str(source or "CEDA")[:80]
    print(
        f"[MANDI_DEBUG] ceda_circuit_open source={_ceda_rate_limit_source!r} "
        f"cooldown_seconds={max(0, int(_ceda_rate_limit_until-time.monotonic()))}"
    )
    return seconds


def _ceda_circuit_remaining() -> int:
    return max(0, int(_ceda_rate_limit_until - time.monotonic()))


AGMARKNET_PUBLIC_BASE = os.getenv("AGMARKNET_PUBLIC_BASE", "https://api.agmarknet.gov.in/v1").strip().rstrip("/")
AGMARKNET_PUBLIC_TIMEOUT_SECONDS = _mandi_env_seconds("AGMARKNET_PUBLIC_TIMEOUT_SECONDS", 20, 5, 60)
_agmarknet_state_cache: dict[str, tuple[Any, float]] = {}
_agmarknet_commodity_cache: dict[str, tuple[Any, float]] = {}
_agmarknet_commodity_context_cache: dict[int, tuple[Any, float]] = {}
_AGMARKNET_METADATA_CACHE_SECONDS = 6 * 60 * 60
AGMARKNET_CAPTCHA_COOLDOWN_SECONDS = _mandi_env_seconds(
    "AGMARKNET_CAPTCHA_COOLDOWN_SECONDS", 21600, 60, 86400
)
_agmarknet_captcha_required_until: float = 0.0
_agmarknet_datewise_captcha_required_until: float = 0.0


def _ceda_metadata_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _ceda_find_commodity_matches(metadata: Any, requested_name: str) -> list[dict[str, Any]]:
    rows = _ceda_metadata_rows(metadata)
    wanted = _norm_mandi_text(requested_name)
    exact = [row for row in rows if _norm_mandi_text(
        row.get("commodity_name") or row.get("commodity") or row.get("name") or
        row.get("cmdty") or row.get("commodityName") or ""
    ) == wanted]
    if exact:
        return exact
    return [row for row in rows if wanted and wanted in _norm_mandi_text(
        row.get("commodity_name") or row.get("commodity") or row.get("name") or
        row.get("cmdty") or row.get("commodityName") or ""
    )]

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
    return (_ag_pick(row,"min_price","minPrice","minimumPrice","Min Price","Min_Price","min") is not None and
            _ag_pick(row,"modal_price","modalPrice","Modal Price","Modal_Price","model_price","modelPrice","Model Price","modal","model") is not None and
            _ag_pick(row,"max_price","maxPrice","maximumPrice","Max Price","Max_Price","max") is not None)

def _ag_report_rows(body: Any) -> list[dict[str, Any]]:
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
    return _ag_report_rows(body)

def _ag_response_shape(body: Any) -> dict[str, Any]:
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
    global _agmarknet_captcha_required_until, _agmarknet_datewise_captcha_required_until
    requested = (commodity or "ALL").strip() or "ALL"
    wanted = GUJARATI_CROP_ALIASES.get(requested, requested)
    if wanted.upper() != "ALL":
        datewise_captcha_remaining = max(0, int(_agmarknet_datewise_captcha_required_until - time.monotonic()))
        if datewise_captcha_remaining > 0:
            print("[MANDI_DEBUG] agmarknet_datewise_skipped reason='captcha_required_circuit_open' "
                  f"retry_after_seconds={datewise_captcha_remaining}")
            return [], f"AGMARKNET date-wise report CAPTCHA required; retry suppressed for {datewise_captcha_remaining}s"
    state_name = (state or "Gujarat").strip() or "Gujarat"
    market_filter = (market or "").strip()
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist)
    today = now.date()
    timeout = httpx.Timeout(AGMARKNET_PUBLIC_TIMEOUT_SECONDS, connect=min(8.0, AGMARKNET_PUBLIC_TIMEOUT_SECONDS))
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://agmarknet.gov.in",
        "Referer": "https://agmarknet.gov.in/",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/135 Safari/537.36",
    }

    async with httpx.AsyncClient(base_url=AGMARKNET_PUBLIC_BASE, headers=headers, timeout=timeout) as client:
        async def get(path, params=None, max_timeout=None):
            try:
                if request_deadline is not None and time.monotonic() >= request_deadline:
                    return None, "mandi_total_budget_exceeded"
                timeout_cap = float(max_timeout if max_timeout is not None else AGMARKNET_PUBLIC_TIMEOUT_SECONDS)
                remaining = timeout_cap if request_deadline is None else max(
                    0.5, min(timeout_cap, request_deadline - time.monotonic())
                )
                response = await client.get(path, params=params, timeout=remaining)
                if response.status_code != 200:
                    detail = " ".join((response.text or "").split())[:180]
                    return None, (f"HTTP {response.status_code}: {detail}" if detail else f"HTTP {response.status_code}")
                try:
                    return response.json(), ""
                except Exception as exc:
                    return None, f"JSON parse {type(exc).__name__}: {str(exc)[:100]}"
            except Exception as exc:
                return None, f"{type(exc).__name__}: {str(exc)[:180]}"

        state_key = _norm_mandi_text(state_name)
        cached_state = _agmarknet_state_cache.get(state_key)
        state_id = cached_state[0] if cached_state and time.monotonic() - cached_state[1] < _AGMARKNET_METADATA_CACHE_SECONDS else None
        if state_id is None:
            body, err = await get(
                "/location/state", {"page": 1, "search": state_name},
                max_timeout=MANDI_AGMARKNET_STATE_TIMEOUT_SECONDS,
            )
            for row in _ag_deep_rows(body):
                name = str(_ag_pick(row, "name", "state_name", "stateName", "State", "state") or "").strip()
                sid = _ag_pick(row, "id", "state_id", "stateId", "stateCode")
                if sid is not None and name and _norm_mandi_text(name) == state_key:
                    try:
                        state_id = int(sid)
                        break
                    except (TypeError, ValueError):
                        continue
            if state_id is None:
                return [], f"AGMARKNET state resolution failed: {err}"
            _agmarknet_state_cache[state_key] = (state_id, time.monotonic())
        print(f"[MANDI_DEBUG] agmarknet2_state_resolved state={state_name!r} id={state_id}")

        last_error = "AGMARKNET 2.0માં છેલ્લા 3 દિવસના માન્ય ભાવ મળ્યા નથી."

        if wanted.upper() != "ALL":
            ckey = _norm_mandi_text(wanted)
            cached_commodity = _agmarknet_commodity_cache.get(ckey)
            commodity_id = (
                cached_commodity[0]
                if cached_commodity and time.monotonic() - cached_commodity[1] < _AGMARKNET_METADATA_CACHE_SECONDS
                else None
            )
            if commodity_id is None:
                filters_body, filters_err = await get(
                    "/daily-price-arrival/filters", {},
                    max_timeout=MANDI_AGMARKNET_STATE_TIMEOUT_SECONDS,
                )
                matches = []
                for row in _ag_deep_rows(filters_body):
                    name = str(_ag_pick(
                        row, "cmdt_name", "cmdtName", "commodity_name", "commodityName",
                        "commodity", "name", "commodity_name_en",
                    ) or "").strip()
                    cid = _ag_pick(
                        row, "cmdt_id", "cmdtId", "commodity_id", "commodityId",
                        "commodityCode", "id", "code",
                    )
                    if cid is not None and name and (
                        _norm_mandi_text(name) == ckey or ckey in _norm_mandi_text(name)
                    ):
                        matches.append((name, cid))
                exact = [item for item in matches if _norm_mandi_text(item[0]) == ckey]
                chosen = exact[0] if exact else (matches[0] if len(matches) == 1 else None)
                if not chosen:
                    print(
                        f"[MANDI_DEBUG] agmarknet2_commodity_resolution_failed requested={wanted!r} "
                        f"candidate_count={len(matches)} error={filters_err!r}"
                    )
                    return [], f"AGMARKNET commodity resolution failed: {filters_err or 'no matching commodity'}"
                try:
                    commodity_id = int(chosen[1])
                except (TypeError, ValueError):
                    return [], "AGMARKNET commodity id invalid"
                _agmarknet_commodity_cache[ckey] = (commodity_id, time.monotonic())
            print(f"[MANDI_DEBUG] agmarknet2_commodity_resolved commodity={wanted!r} id={commodity_id}")

            month_keys = []
            for day_offset in range(MANDI_MAX_LOOKBACK_DAYS + 1):
                date_key = today - timedelta(days=day_offset)
                month_key = (date_key.year, date_key.month)
                if month_key not in month_keys:
                    month_keys.append(month_key)

            candidates = []
            for year, month_num in month_keys:
                body, err = await get(
                    "/prices-and-arrivals/date-wise/specific-commodity",
                    {
                        "year": str(year), "month": str(month_num),
                        "stateId": str(state_id), "commodityId": str(commodity_id),
                        "includeExcel": "false",
                    },
                    max_timeout=MANDI_AGMARKNET_DAILY_TIMEOUT_SECONDS,
                )
                if body is None:
                    print(
                        f"[MANDI_DEBUG] agmarknet2_datewise_failed year={year} month={month_num} error={err!r}"
                    )
                    if "TOKEN_OR_CAPTCHA_REQUIRED" in err or "Captcha key and captcha value are required" in err:
                        _agmarknet_datewise_captcha_required_until = time.monotonic() + AGMARKNET_CAPTCHA_COOLDOWN_SECONDS
                        print("[MANDI_DEBUG] agmarknet_datewise_captcha_circuit_open "
                              f"cooldown_seconds={AGMARKNET_CAPTCHA_COOLDOWN_SECONDS} endpoint='date-wise/specific-commodity'")
                        return [], f"AGMARKNET date-wise report CAPTCHA required: {err}"
                    if any(marker in err for marker in (
                        "HTTP 400", "HTTP 401", "HTTP 403", "HTTP 429",
                        "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504",
                        "ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutException",
                        "NetworkError", "Temporary failure in name resolution", "Connection refused",
                    )):
                        return [], f"AGMARKNET date-wise report failed: {err}"
                    continue
                rows = _ag_report_rows(body)
                for row in rows:
                    item = dict(row)
                    if not _ag_pick(item, "commodity", "cmdt_name", "cmdtName", "commodity_name", "commodityName"):
                        item["commodity"] = wanted
                    candidates.append(item)
                print(
                    f"[MANDI_DEBUG] agmarknet2_datewise_response year={year} month={month_num} "
                    f"raw_records={len(rows)} shape={_ag_response_shape(body)!r}"
                )

            lower_date = today - timedelta(days=MANDI_MAX_LOOKBACK_DAYS)
            accepted = []
            rejected = {"commodity": 0, "market": 0, "date_invalid": 0, "outside_window": 0, "future": 0, "price": 0}
            seen = set()
            for row in candidates:
                row_commodity = str(_ag_pick(
                    row, "cmdt_name", "cmdtName", "commodity", "Commodity", "commodity_name", "commodityName"
                ) or wanted).strip()
                if not _commodity_matches({"commodity": row_commodity}, wanted):
                    rejected["commodity"] += 1
                    continue
                market_name = str(_ag_pick(row, "market_name", "marketName", "market", "Market") or "").strip()
                if market_filter and (not market_name or _mandi_market_match_key(market_filter) != _mandi_market_match_key(market_name)):
                    rejected["market"] += 1
                    continue
                raw_date = _ag_pick(row, "arrival_date", "arrivalDate", "date", "Date", "reportedDate", "reported_date")
                parsed = _parse_mandi_date(raw_date)
                if not parsed:
                    rejected["date_invalid"] += 1
                    continue
                report_day = parsed.astimezone(ist).date()
                if report_day > today:
                    rejected["future"] += 1
                    continue
                if report_day < lower_date:
                    rejected["outside_window"] += 1
                    continue
                min_value = _normalise_price(_ag_pick(row, "min_price", "minPrice", "minimumPrice", "Min Price", "Min_Price", "min"))
                modal_value = _normalise_price(_ag_pick(row, "modal_price", "modalPrice", "Modal Price", "Modal_Price", "model_price", "modelPrice", "Model Price", "modal", "model"))
                max_value = _normalise_price(_ag_pick(row, "max_price", "maxPrice", "maximumPrice", "Max Price", "Max_Price", "max"))
                min_float, modal_float, max_float = _price_float(min_value), _price_float(modal_value), _price_float(max_value)
                if min_float is None or modal_float is None or max_float is None or not (
                    min_float > 0 and modal_float > 0 and max_float > 0 and min_float <= modal_float <= max_float
                ):
                    rejected["price"] += 1
                    continue
                row_key = (
                    _norm_mandi_market(market_name), report_day.isoformat(), row_commodity,
                    min_float, modal_float, max_float,
                    str(_ag_pick(row, "variety_name", "varietyName", "variety", "Variety") or ""),
                )
                if row_key in seen:
                    continue
                seen.add(row_key)
                age_hours = max(0.0, (now - parsed.astimezone(ist)).total_seconds() / 3600.0)
                accepted.append({
                    "state": str(_ag_pick(row, "state_name", "stateName", "state", "State") or state_name).strip(),
                    "district": str(_ag_pick(row, "district_name", "districtName", "district", "District") or "").strip(),
                    "market": market_name,
                    "commodity": row_commodity,
                    "variety": str(_ag_pick(row, "variety_name", "varietyName", "variety", "Variety") or "").strip(),
                    "grade": str(_ag_pick(row, "grade_name", "gradeName", "grade", "Grade") or "").strip(),
                    "arrival_date": parsed.strftime("%d/%m/%Y"),
                    "report_date": report_day.isoformat(),
                    "min_price": min_float, "max_price": max_float, "modal_price": modal_float,
                    "source": "AGMARKNET 2.0 (Government of India)",
                    "source_url": "https://agmarknet.gov.in/home",
                    "_source_age_hours": round(age_hours, 2),
                })
            if not accepted:
                print(
                    f"[MANDI_DEBUG] agmarknet2_datewise_validation raw={len(candidates)} accepted=0 "
                    f"rejected={rejected!r} requested_dates={[(today - timedelta(days=n)).isoformat() for n in range(MANDI_MAX_LOOKBACK_DAYS + 1)]!r}"
                )
                return [], "AGMARKNET 2.0 returned no fresh date-stamped records for the requested commodity/market"
            latest_day = max(row["report_date"] for row in accepted)
            latest = [row for row in accepted if row["report_date"] == latest_day]
            print(
                f"[MANDI_DEBUG] agmarknet2_daily_selected_date date={latest_day!r} "
                f"records={len(latest)} path='date-wise/specific-commodity' rejected={rejected!r}"
            )
            return latest, ""

        captcha_remaining = max(0, int(_agmarknet_captcha_required_until - time.monotonic()))
        if captcha_remaining > 0:
            print(f"[MANDI_DEBUG] agmarknet_daily_skipped reason='captcha_required_circuit_open' retry_after_seconds={captcha_remaining}")
            return [], f"AGMARKNET daily report CAPTCHA required; retry suppressed for {captcha_remaining}s"

        for delta in range(MANDI_MAX_LOOKBACK_DAYS + 1):
            if request_deadline is not None and time.monotonic() >= request_deadline:
                return [], "mandi_total_budget_exceeded"
            report_day = today - timedelta(days=delta)
            report_date = report_day.isoformat()
            body, err = await get("/prices-and-arrivals/commodity-market/daily-report-state", {
                "date": report_date,
                "state": state_id,
                "includeExcel": "false",
            }, max_timeout=MANDI_AGMARKNET_DAILY_TIMEOUT_SECONDS)
            if body is None:
                last_error = f"AGMARKNET daily report {report_date} failed: {err}"
                print(f"[MANDI_DEBUG] agmarknet2_daily_failed date={report_date!r} error={err!r}")
                if "TOKEN_OR_CAPTCHA_REQUIRED" in err or (
                    "Captcha key and captcha value are required" in err
                ):
                    _agmarknet_captcha_required_until = time.monotonic() + AGMARKNET_CAPTCHA_COOLDOWN_SECONDS
                    print(
                        "[MANDI_DEBUG] agmarknet_captcha_circuit_open "
                        f"cooldown_seconds={AGMARKNET_CAPTCHA_COOLDOWN_SECONDS}"
                    )
                    return [], last_error
                provider_wide_failures = (
                    "HTTP 400", "HTTP 401", "HTTP 403", "HTTP 429",
                    "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504",
                    "ConnectError", "ConnectTimeout", "ReadTimeout",
                    "TimeoutException", "NetworkError", "Name or service not known",
                    "Temporary failure in name resolution", "Connection refused",
                )
                if any(marker in err for marker in provider_wide_failures):
                    return [], last_error
                continue

            candidates = _ag_daily_commodity_rows(body)
            shape = _ag_response_shape(body)
            print(
                f"[MANDI_DEBUG] agmarknet2_daily_response date={report_date!r} "
                f"raw_records={len(candidates)} shape={shape!r}"
            )
            accepted: list[dict[str, Any]] = []
            rejected = {"commodity": 0, "market": 0, "date_invalid": 0, "date_mismatch": 0,
                        "future": 0, "stale": 0, "price": 0, "accepted": 0}

            for row in candidates:
                row_commodity = str(_ag_pick(
                    row, "cmdt_name", "cmdtName", "commodity", "Commodity", "commodity_name", "commodityName"
                ) or "").strip()
                if wanted.upper() != "ALL" and (not row_commodity or not _commodity_matches({"commodity": row_commodity}, wanted)):
                    rejected["commodity"] += 1
                    continue
                if wanted.upper() == "ALL" and not row_commodity:
                    rejected["commodity"] += 1
                    continue

                market_name = str(_ag_pick(row, "market_name", "marketName", "market", "Market") or "").strip()
                if market_filter and (not market_name or _mandi_market_match_key(market_filter) != _mandi_market_match_key(market_name)):
                    rejected["market"] += 1
                    continue

                raw_date = _ag_pick(row, "arrival_date", "arrivalDate", "date", "Date", "reportedDate", "reported_date")
                if raw_date not in (None, ""):
                    parsed_date = _parse_mandi_date(raw_date)
                    if not parsed_date:
                        rejected["date_invalid"] += 1
                        continue
                    if parsed_date.date() != report_day:
                        rejected["date_mismatch"] += 1
                        continue
                else:
                    parsed_date = datetime.combine(report_day, datetime.min.time(), tzinfo=ist)

                age_days = (today - parsed_date.date()).days
                if age_days < 0:
                    rejected["future"] += 1
                    continue
                if age_days > MANDI_MAX_LOOKBACK_DAYS:
                    rejected["stale"] += 1
                    continue

                min_price = _normalise_price(_ag_pick(row, "min_price", "minPrice", "minimumPrice", "Min Price", "Min_Price", "min"))
                modal_price = _normalise_price(_ag_pick(row, "modal_price", "modalPrice", "Modal Price", "Modal_Price", "model_price", "modelPrice", "Model Price", "modal", "model"))
                max_price = _normalise_price(_ag_pick(row, "max_price", "maxPrice", "maximumPrice", "Max Price", "Max_Price", "max"))
                min_value, modal_value, max_value = _price_float(min_price), _price_float(modal_price), _price_float(max_price)
                if min_value is None or modal_value is None or max_value is None or not (
                    min_value > 0 and modal_value > 0 and max_value > 0 and min_value <= modal_value <= max_value
                ):
                    rejected["price"] += 1
                    continue

                accepted.append({
                    "state": str(_ag_pick(row, "state_name", "stateName", "state", "State") or state_name).strip(),
                    "district": str(_ag_pick(row, "district_name", "districtName", "district", "District") or "").strip(),
                    "market": market_name,
                    "commodity": row_commodity,
                    "variety": str(_ag_pick(row, "variety_name", "varietyName", "variety", "Variety") or "").strip(),
                    "grade": str(_ag_pick(row, "grade_name", "gradeName", "grade", "Grade") or "").strip(),
                    "arrival_date": parsed_date.strftime("%d/%m/%Y"),
                    "report_date": report_date,
                    "min_price": min_value,
                    "max_price": max_value,
                    "modal_price": modal_value,
                    "source": "AGMARKNET 2.0 (Government of India)",
                    "source_url": "https://agmarknet.gov.in/home",
                    "_source_age_days": age_days,
                })

            rejected["accepted"] = len(accepted)
            print(
                f"[MANDI_DEBUG] agmarknet2_daily_validation date={report_date!r} raw={len(candidates)} "
                f"accepted={len(accepted)} rejected_commodity={rejected['commodity']} "
                f"rejected_market={rejected['market']} rejected_date_invalid={rejected['date_invalid']} "
                f"rejected_date_mismatch={rejected['date_mismatch']} rejected_future={rejected['future']} "
                f"rejected_stale={rejected['stale']} rejected_price={rejected['price']}"
            )
            if accepted:
                print(f"[MANDI_DEBUG] agmarknet2_daily_selected_date date={report_date!r} records={len(accepted)} age_days={delta}")
                return accepted, ""
            last_error = f"AGMARKNETમાં {report_date} માટે મેળ ખાતા માન્ય ભાવ નથી."

        return [], last_error

async def _fetch_ceda_fresh_mandi(state: str, district: str, commodity: str) -> tuple[list[dict[str, Any]], str]:
    """Fetch real Agmarknet-derived data through CEDA."""
    global _ceda_geography_cache

    circuit_remaining = _ceda_circuit_remaining()
    if circuit_remaining > 0:
        error = f"CEDA rate limited; circuit open for about {circuit_remaining}s"
        print(f"[MANDI_DEBUG] ceda_request_skipped reason='rate_limit_circuit_open' retry_after_seconds={circuit_remaining}")
        return [], error
    state = (state or "Gujarat").strip()
    requested = (commodity or "ALL").strip() or "ALL"
    api_commodity = GUJARATI_CROP_ALIASES.get(requested, requested)
    if api_commodity.upper() == "ALL":
        return [], "CEDA fallback requires a specific commodity"

    timeout = httpx.Timeout(MANDI_CEDA_TIMEOUT_SECONDS, connect=min(8.0, MANDI_CEDA_TIMEOUT_SECONDS))
    headers = {"Accept": "application/json"}
    if CEDA_API_KEY:
        headers["Authorization"] = f"Bearer {CEDA_API_KEY}"
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    from_date = (now_ist.date() - timedelta(days=MANDI_MAX_LOOKBACK_DAYS)).isoformat()
    to_date = now_ist.date().isoformat()

    async with httpx.AsyncClient(base_url=CEDA_API_BASE, headers=headers, timeout=timeout) as client:
        async def call(method: str, path: str, payload: dict | None = None):
            if not CEDA_API_KEY:
                return None, "CEDA_API_KEY not configured"
            try:
                response = await client.request(method, path, json=payload)
                retry_after = response.headers.get("Retry-After", "")
                if response.status_code == 429:
                    _ceda_note_rate_limit(retry_after, f"authenticated:{path}")
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

        def _commodity_id(row: dict[str, Any]):
            for key in ("commodity_id", "id", "cmdty_id", "commodityId"):
                if row.get(key) is not None:
                    return row.get(key)
            return None

        async def public_commodity_metadata() -> list[dict[str, Any]]:
            public_client = httpx.AsyncClient(
                base_url=_CEDA_PUBLIC_BASE,
                headers={"Accept": "application/json", "User-Agent": "SmartAgriMarketAI/Mandi/12.1"},
                timeout=timeout,
            )
            try:
                response = await public_client.get("/commodities")
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    _ceda_note_rate_limit(retry_after, "public:/commodities")
                if response.status_code != 200:
                    return []
                return _extract_public_data(response.json())
            except Exception:
                return []
            finally:
                await public_client.aclose()

        # ---------- Commodity id: cached -> authenticated -> public -> static official IDs ----------
        cache_key = norm(api_commodity)
        cached = _ceda_commodity_cache.get(cache_key)
        cached_is_fresh = bool(cached and (time.monotonic() - cached[1] < _CEDA_METADATA_CACHE_SECONDS))
        commodity_meta = _ceda_metadata_rows(cached[0]) if cached_is_fresh else None
        commodity_meta_source = "cache" if commodity_meta else ""

        if not commodity_meta:
            commodities, err = await call("GET", "/agmarknet/commodities")
            if commodities is not None:
                commodity_meta = commodities
                commodity_meta_source = "ceda_v1"
            else:
                print(f"[MANDI_DEBUG] ceda_commodities_failed error={err!r}")
                if _ceda_circuit_remaining() > 0:
                    return [], f"CEDA rate limit circuit open after metadata request: {err}"
                public_rows = await public_commodity_metadata()
                if public_rows:
                    commodity_meta = public_rows
                    commodity_meta_source = "ceda_public_metadata"
                else:
                    commodity_meta = _CEDA_STATIC_COMMODITIES
                    commodity_meta_source = "ceda_static_official_ids"

        matches = _ceda_find_commodity_matches(commodity_meta, api_commodity)
        if not matches:
            matches = _ceda_find_commodity_matches(_CEDA_STATIC_COMMODITIES, api_commodity)
            if matches:
                commodity_meta_source = "ceda_static_official_ids"
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
            if geographies is not None:
                _ceda_geography_cache = (geographies, time.monotonic())
                geo_source = "ceda_v1"
            else:
                geographies = _CEDA_STATIC_GUJARAT_GEOGRAPHIES
                geo_source = "ceda_static_gujarat_ids"

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
                circuit_remaining = _ceda_circuit_remaining()
                if circuit_remaining > 0:
                    return []
                payload_v1 = {
                    "commodity_id": commodity_id,
                    "state_id": state_id,
                    "district_id": [did],
                    "from_date": from_date,
                    "to_date": to_date,
                }

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
                        if pr.status_code == 429:
                            _ceda_note_rate_limit(retry_after, f"public:/prices:{dname}")
                        if pr.status_code == 200:
                            rows = _extract_public_data(pr.json())
                            print(f"[MANDI_DEBUG] ceda_public_prices_response district={dname!r} status=200 raw_records={len(rows)} chart_type='datadownload'")
                        else:
                            suffix = f"; Retry-After={retry_after}" if retry_after else ""
                            call_err = f"HTTP {pr.status_code}{suffix}"
                except Exception as exc:
                    call_err = f"{type(exc).__name__}: {str(exc)[:180]}"

                if rows is None and CEDA_API_KEY:
                    if _ceda_circuit_remaining() > 0:
                        return []
                    rows, v1_err = await call("POST", "/agmarknet/prices", payload_v1)
                    if rows is not None:
                        call_err = ""
                    else:
                        call_err = v1_err or call_err
                if rows is None:
                    return []

                market_names = {}
                out = []
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    raw_date = r.get("date") or r.get("t") or r.get("arrival_date") or r.get("Date")
                    parsed = _parse_mandi_date(raw_date)
                    if not parsed:
                        continue
                    parsed_ist = parsed.astimezone(now_ist.tzinfo)
                    age_hours = (now_ist - parsed_ist).total_seconds() / 3600.0
                    age_days = (now_ist.date() - parsed_ist.date()).days
                    if (parsed_ist > now_ist + timedelta(minutes=5) or age_days < 0 or
                            age_days > MANDI_MAX_LOOKBACK_DAYS):
                        continue
                    min_p = r.get("min_price", r.get("p_min"))
                    max_p = r.get("max_price", r.get("p_max"))
                    modal_p = r.get("modal_price", r.get("p_modal"))
                    try:
                        min_f, max_f, modal_f = float(min_p), float(max_p), float(modal_p)
                    except (TypeError, ValueError):
                        continue
                    if not (min_f > 0 and max_f > 0 and modal_f > 0 and min_f <= modal_f <= max_f):
                        continue
                    row_district = str(r.get("district") or r.get("district_name") or r.get("District") or "").strip()
                    if district and row_district and norm(row_district) != norm(district) and norm(district) not in norm(row_district):
                        continue
                    if district and not row_district:
                        continue
                    market_id = r.get("market_id", r.get("marketId"))
                    market_name = (
                        r.get("market_name") or r.get("market") or r.get("Market") or
                        market_names.get(market_id, "") or dname
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
                        "_source_age_days": age_days,
                    })
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
        src_val = pick(row, "source") or "official_api"
        src_url_val = pick(row, "source_url") or "https://data.gov.in/"
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
            "min_price_20kg": _price_per_20kg(min_price),
            "modal_price_20kg": _price_per_20kg(modal_price),
            "max_price_20kg": _price_per_20kg(max_price),
            "price_unit_source": "₹/quintal",
            "display_price_unit": "₹/20kg",
            "source": src_val,
            "source_url": src_url_val,
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
    "sidhpur":"સિદ્ધપુર", "unja":"ઊંઝા", "unjha":"ઊંઝા", "visavadar":"વિસાવદર", "bantwa":"બાંટવા",
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
    cleaned=re.sub(r"\bAPMC\b", "", clean, flags=re.I)
    cleaned=re.sub(r"\bAgricultural Produce Market Committee\b", "", cleaned, flags=re.I)
    cleaned=re.sub(r"\bMarket Yard\b|\bYard\b|\bMarket\b", "", cleaned, flags=re.I)
    cleaned=" ".join(cleaned.split()).strip(" -,")
    return f"{cleaned} યાર્ડ" if cleaned else "કૃષિ બજાર યાર્ડ"

@app.get("/api/v1/mandi/markets")
def mandi_markets(state: str = "Gujarat", commodity: str = "ALL"):
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

    market_keys=("market_name","marketName","market_name_en","marketNameEn","mkt_name","mktName","market","Market","apmc_name","apmcName","apmc","APMC")
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
            return
        tables={}
        def register_table(key, value):
            rows=[]
            if isinstance(value,list):
                rows=[x for x in value if isinstance(x,dict)]
            elif isinstance(value,dict):
                for child_key, child in value.items():
                    if isinstance(child,list):
                        child_rows=[x for x in child if isinstance(x,dict)]
                        tables[f"{key}.{child_key}"]=child_rows
                        rows.extend(child_rows)
            if rows:
                tables[key]=rows

        for key,value in data_obj.items():
            register_table(key,value)

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

        for table_name,rows in tables.items():
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
            if state_id is None: return

            try:
                r=await client.get("/daily-price-arrival/filters")
                if r.status_code==200:
                    body=r.json()
                    data_obj=body.get("data") if isinstance(body,dict) else None
                    extract_filter_tables(data_obj,state_id)
                else:
                    errors.append(f"filters HTTP {r.status_code}")
            except Exception as exc:
                errors.append(f"filters {type(exc).__name__}: {str(exc)[:160]}")

            if not names:
                ist = timezone(timedelta(hours=5, minutes=30))
                today = datetime.now(ist).date()
                for delta in range(MANDI_MAX_LOOKBACK_DAYS + 1):
                    report_date = (today - timedelta(days=delta)).isoformat()
                    try:
                        response = await client.get(
                            "/prices-and-arrivals/commodity-market/daily-report-state",
                            params={"date": report_date, "state": state_id, "includeExcel": "false"},
                        )
                        if response.status_code != 200:
                            errors.append(f"daily-market-discovery {report_date} HTTP {response.status_code}")
                            continue
                        body = response.json()
                        for row in _ag_report_rows(body):
                            add_name(_ag_pick(row, "market_name", "marketName", "market", "Market"))
                        if names:
                            break
                    except Exception as exc:
                        errors.append(f"daily-market-discovery {report_date} {type(exc).__name__}: {str(exc)[:160]}")

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
        "source_policy": "data.gov.in official API (primary) → AGMARKNET 2.0 public API → CEDA/Agmarknet daily fallback; no fabricated prices",
        "request_budget_seconds": MANDI_TOTAL_BUDGET_SECONDS,
        "elapsed_seconds": elapsed,
    }

@app.get("/api/v1/mandi/today-summary")
def mandi_today_summary(state: str = "Gujarat", market: str = ""):
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
    return {"ok":True,"state":(state or "Gujarat").strip() or "Gujarat","market":(market or "").strip(),"checked_at":checked_at,"items":items,"available_crops":available,"total_crops":len(items),"source_policy":"data.gov.in official API (primary) → AGMARKNET 2.0 public API → CEDA/Agmarknet daily fallback; no fabricated prices"}

def _mandi_source_log(source: str, event: str, *, elapsed_ms: int | None = None,
                      status: str = "", http_status: int | None = None,
                      records: int | None = None, state: str = "", market: str = "",
                      commodity: str = "", error: str = "") -> None:
    """Consistent, secret-safe log line for each live mandi source attempt."""
    fields = [f"source={source!r}", f"event={event!r}"]
    if status:
        fields.append(f"result={status!r}")
    if elapsed_ms is not None:
        fields.append(f"elapsed_ms={int(elapsed_ms)}")
    if http_status is not None:
        fields.append(f"http_status={int(http_status)}")
    if records is not None:
        fields.append(f"usable_records={int(records)}")
    if state:
        fields.append(f"state={state!r}")
    if market:
        fields.append(f"market={market!r}")
    if commodity:
        fields.append(f"commodity={commodity!r}")
    if error:
        # Do not log credentials or full response bodies.
        safe = re.sub(r"(?i)(api[-_ ]?key|authorization|bearer)\s*[:= ]\s*[^ ,;]+", r"\1=[REDACTED]", " ".join(str(error).split()))[:240]
        if MANDI_API_KEY:
            safe = safe.replace(MANDI_API_KEY, "[REDACTED]")
        if CEDA_API_KEY:
            safe = safe.replace(CEDA_API_KEY, "[REDACTED]")
        fields.append(f"error={safe!r}")
    print("[MANDI_SOURCE_TEST] " + " ".join(fields), flush=True)


@app.get("/api/v1/mandi/source-test")
async def mandi_source_test(state: str = "Gujarat", market: str = "", commodity: str = "કપાસ"):
    """Independently probe all three live sources for diagnostics; enable explicitly in Render."""
    if os.getenv("MANDI_SOURCE_TEST_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="Mandi source diagnostic is disabled")

    state_name = (state or "Gujarat").strip() or "Gujarat"
    market_name = (market or "").strip()
    commodity_name = (commodity or "કપાસ").strip() or "કપાસ"
    # Diagnostic calls are sequential and capped; this endpoint tests every source,
    # even if an earlier source succeeds. It is not the normal production fallback path.
    results: dict[str, Any] = {}

    # 1. data.gov.in
    source = "data.gov.in"
    started = time.monotonic()
    _mandi_source_log(source, "START", state=state_name, market=market_name, commodity=commodity_name)
    try:
        dg_deadline = time.monotonic() + min(12, MANDI_API_TIMEOUT_SECONDS)
        dg_result = _mandi_api_get(state_name, market_name, commodity_name, request_deadline=dg_deadline)
        dg_data = dg_result[0] if isinstance(dg_result, tuple) and len(dg_result) >= 1 else None
        dg_error = str(dg_result[1] or "") if isinstance(dg_result, tuple) and len(dg_result) >= 2 else "unexpected_data_gov_response"
        dg_status = int(dg_result[3] or 0) if isinstance(dg_result, tuple) and len(dg_result) >= 4 else 0
        dg_rows = dg_data.get("records", []) if isinstance(dg_data, dict) else []
        dg_rows = dg_rows if isinstance(dg_rows, list) else []
        dg_count = len(dg_rows)
        dg_ok = dg_count > 0
        dg_result_status = "SUCCESS" if dg_ok else ("FAILED" if dg_error else "NO_USABLE_DATA")
        results[source] = {"result": dg_result_status, "http_status": dg_status, "usable_records": dg_count,
                           "error": _mandi_safe_error(Exception(dg_error)) if dg_error else ""}
        _mandi_source_log(source, "RESULT", status=dg_result_status, elapsed_ms=int((time.monotonic()-started)*1000),
                          http_status=dg_status, records=dg_count, state=state_name, market=market_name,
                          commodity=commodity_name, error=dg_error)
    except Exception as exc:
        dg_error = _mandi_safe_error(exc)
        results[source] = {"result": "FAILED", "http_status": 0, "usable_records": 0, "error": dg_error}
        _mandi_source_log(source, "RESULT", status="FAILED", elapsed_ms=int((time.monotonic()-started)*1000),
                          http_status=0, records=0, state=state_name, market=market_name,
                          commodity=commodity_name, error=dg_error)

    # 2. Public AGMARKNET source
    source = "agmarknet_2_public"
    started = time.monotonic()
    _mandi_source_log(source, "START", state=state_name, market=market_name, commodity=commodity_name)
    try:
        ag_deadline = time.monotonic() + min(15, AGMARKNET_PUBLIC_TIMEOUT_SECONDS)
        ag_rows, ag_error = await asyncio.wait_for(
            _fetch_agmarknet_2_live(state_name, market_name, commodity_name, request_deadline=ag_deadline),
            timeout=max(0.5, ag_deadline-time.monotonic()),
        )
        ag_normalized = _normalise_mandi_records(ag_rows) if ag_rows else []
        ag_latest, ag_date = _mandi_latest_rows(ag_normalized) if ag_normalized else ([], "")
        ag_count = len(ag_latest)
        ag_result_status = "SUCCESS" if ag_count else ("FAILED" if ag_error else "NO_USABLE_DATA")
        results[source] = {"result": ag_result_status, "http_status": 0, "usable_records": ag_count,
                           "latest_date": ag_date, "error": str(ag_error or "")[:240]}
        _mandi_source_log(source, "RESULT", status=ag_result_status, elapsed_ms=int((time.monotonic()-started)*1000),
                          http_status=0, records=ag_count, state=state_name, market=market_name,
                          commodity=commodity_name, error=ag_error)
    except Exception as exc:
        ag_error = _mandi_safe_error(exc)
        results[source] = {"result": "FAILED", "http_status": 0, "usable_records": 0, "error": ag_error}
        _mandi_source_log(source, "RESULT", status="FAILED", elapsed_ms=int((time.monotonic()-started)*1000),
                          http_status=0, records=0, state=state_name, market=market_name,
                          commodity=commodity_name, error=ag_error)

    # 3. CEDA-hosted Agmarknet-derived source
    source = "ceda_agmarknet_fallback"
    started = time.monotonic()
    _mandi_source_log(source, "START", state=state_name, market=market_name, commodity=commodity_name)
    try:
        if market_name:
            ceda_rows, ceda_error = [], "CEDA fallback does not support exact market filter"
        else:
            ceda_deadline = time.monotonic() + min(12, MANDI_CEDA_TIMEOUT_SECONDS)
            ceda_rows, ceda_error = await asyncio.wait_for(
                _fetch_ceda_fresh_mandi(state_name, "", commodity_name),
                timeout=max(0.5, ceda_deadline-time.monotonic()),
            )
        ceda_normalized = _normalise_mandi_records(ceda_rows) if ceda_rows else []
        ceda_latest, ceda_date = _mandi_latest_rows(ceda_normalized) if ceda_normalized else ([], "")
        ceda_count = len(ceda_latest)
        ceda_result_status = "SUCCESS" if ceda_count else ("FAILED" if ceda_error else "NO_USABLE_DATA")
        results[source] = {"result": ceda_result_status, "http_status": 0, "usable_records": ceda_count,
                           "latest_date": ceda_date, "error": str(ceda_error or "")[:240]}
        _mandi_source_log(source, "RESULT", status=ceda_result_status, elapsed_ms=int((time.monotonic()-started)*1000),
                          http_status=0, records=ceda_count, state=state_name, market=market_name,
                          commodity=commodity_name, error=ceda_error)
    except Exception as exc:
        ceda_error = _mandi_safe_error(exc)
        results[source] = {"result": "FAILED", "http_status": 0, "usable_records": 0, "error": ceda_error}
        _mandi_source_log(source, "RESULT", status="FAILED", elapsed_ms=int((time.monotonic()-started)*1000),
                          http_status=0, records=0, state=state_name, market=market_name,
                          commodity=commodity_name, error=ceda_error)

    success_sources = [name for name, result in results.items() if result.get("result") == "SUCCESS"]
    overall = "SUCCESS" if success_sources else "ALL_FAILED_OR_NO_DATA"
    print(f"[MANDI_SOURCE_TEST] SUMMARY result={overall!r} successful_sources={success_sources!r} tested_sources={list(results.keys())!r}", flush=True)
    return {"ok": True, "test_mode": True, "state": state_name, "market": market_name,
            "commodity": commodity_name, "overall": overall, "successful_sources": success_sources,
            "results": results,
            "note": "This diagnostic endpoint independently probes all sources; production /api/v1/mandi still follows priority order and stops at first usable source."}


@app.get("/api/v1/mandi")
def mandi(state: str = "Gujarat", market: str = "", commodity: str = "ALL", request_deadline: float | None = None):
    """Fetch mandi prices in the required source priority: data.gov.in, Agmarknet, then CEDA."""
    ist = timezone(timedelta(hours=5, minutes=30))
    checked_at = datetime.now(timezone.utc).astimezone(ist).strftime("%d-%m-%Y %H:%M")
    requested_commodity = (commodity or "ALL").strip() or "ALL"
    state_name = (state or "Gujarat").strip() or "Gujarat"
    market_name = (market or "").strip()
    deadline = request_deadline if request_deadline is not None else (time.monotonic() + MANDI_TOTAL_BUDGET_SECONDS)
    source_policy = "data.gov.in official API (primary) → AGMARKNET 2.0 public API → CEDA/Agmarknet daily fallback; no fabricated prices"

    cached_fresh = _get_from_shared_pool(state_name, market_name, requested_commodity, max_age_seconds=MANDI_SHARED_FRESH_TTL_SECONDS)
    if cached_fresh:
        cached_out = dict(cached_fresh)
        cached_out["checked_at"] = checked_at
        return cached_out

    def unavailable(message: str, live_error: str, diagnostics: dict[str, Any] | None = None):
        cached_backup = _get_from_shared_pool(state_name, market_name, requested_commodity, max_age_seconds=72 * 3600)
        if cached_backup:
            backup_out = dict(cached_backup)
            backup_out["checked_at"] = checked_at
            return backup_out
        return {
            "ok": True,
            "live_available": False,
            "live_api_configured": bool(MANDI_API_KEY),
            "source": "none",
            "checked_at": checked_at,
            "price_unit_source": "₹/quintal",
            "display_price_unit": "₹/20kg",
            "records": [],
            "message": message,
            "live_error": live_error,
            "source_policy": source_policy,
            "official_dashboard_url": "https://www.enam.gov.in/web/dashboard/agmarknet",
            "diagnostics": diagnostics or {},
        }

    if time.monotonic() >= deadline:
        return unavailable("Live Mandi માટે સમય મર્યાદા પૂરી થઈ ગઈ.", "mandi_total_budget_exceeded")

    # 1) PRIMARY: Government of India data.gov.in API.
    _mandi_source_log("data.gov.in", "START", state=state_name, market=market_name, commodity=requested_commodity)
    _dg_started = time.monotonic()
    data_error = ""
    upstream_status = 0
    data = None
    try:
        result = _mandi_api_get(state_name, market_name, requested_commodity, request_deadline=deadline)
        if isinstance(result, tuple) and len(result) == 4:
            data, data_error, _cooldown, upstream_status = result
        elif isinstance(result, tuple) and len(result) >= 2:
            data, data_error = result[0], result[1]
        else:
            data_error = "unexpected_data_gov_response"
    except Exception as exc:
        data_error = f"{type(exc).__name__}: {str(exc)[:180]}"
        print(f"[MANDI_DEBUG] data_gov_primary_exception error={data_error!r}")

    if isinstance(data, dict):
        records = data.get("records") or []
        if not isinstance(records, list):
            records = []
        raw_diag = data.get("_diagnostics", {}) if isinstance(data.get("_diagnostics", {}), dict) else {}
        raw_count = int(raw_diag.get("raw_record_count", len(records)) or len(records))
        http_status = int(raw_diag.get("http_status", upstream_status or 200) or 200)

        if market_name and not records and time.monotonic() < deadline:
            broad_res = _mandi_api_get(state_name, "", requested_commodity, request_deadline=deadline)
            broad_data = broad_res[0] if isinstance(broad_res, tuple) and len(broad_res) >= 1 else None
            if isinstance(broad_data, dict):
                all_state_rows = broad_data.get("records") or []
                if isinstance(all_state_rows, list) and all_state_rows:
                    _store_in_shared_pool(state_name, "", requested_commodity, {
                        "ok": True, "live_available": True, "live_api_configured": bool(MANDI_API_KEY),
                        "source": "official_api", "checked_at": checked_at,
                        "price_unit_source": "₹/quintal (data.gov.in)", "display_price_unit": "₹/20kg",
                        "records": all_state_rows, "source_policy": source_policy,
                    }, all_state_rows)
                    matched_rows = [r for r in all_state_rows if _mandi_markets_match(_mandi_row_market(r), market_name)]
                    if matched_rows:
                        data = dict(broad_data)
                        data["records"] = matched_rows
                        records = matched_rows

        if records:
            latest_rows, latest_date = _mandi_latest_rows(records)
            if latest_rows:
                print(f"[MANDI_DEBUG] source_success priority=1 source='data.gov.in' latest_date={latest_date!r} records={len(latest_rows)}")
                _mandi_source_log("data.gov.in", "RESULT", status="SUCCESS", elapsed_ms=int((time.monotonic()-_dg_started)*1000), http_status=http_status, records=len(latest_rows), state=state_name, market=market_name, commodity=requested_commodity)
                response_payload = {
                    "ok": True,
                    "live_available": True,
                    "live_api_configured": bool(MANDI_API_KEY),
                    "source": "official_api",
                    "checked_at": checked_at,
                    "price_unit_source": "₹/quintal (data.gov.in)",
                    "display_price_unit": "₹/20kg",
                    "records": latest_rows[:100],
                    "message": f"ભારત સરકારના data.gov.in ડેટામાંથી {latest_date}નો ભાવ મળ્યો.",
                    "latest_arrival_date": latest_rows[0].get("arrival_date", "") if latest_rows else latest_date,
                    "source_policy": source_policy,
                    "diagnostics": {
                        "primary": {"request_ok": True, "http_status": http_status, "records": len(latest_rows), "source": "data.gov.in", "raw_records": raw_count, "latest_date": latest_date}
                    },
                }
                _store_in_shared_pool(state_name, market_name, requested_commodity, response_payload, latest_rows)
                return response_payload
    _mandi_source_log("data.gov.in", "RESULT", status="FAILED" if data_error else "NO_USABLE_DATA", elapsed_ms=int((time.monotonic()-_dg_started)*1000), http_status=upstream_status, records=0, state=state_name, market=market_name, commodity=requested_commodity, error=data_error or "no_fresh_records")
    print(f"[MANDI_DEBUG] primary_failed source='data.gov.in' error={data_error or 'no_fresh_records'!r} http_status={upstream_status}")

    # 2) SECONDARY: AGMARKNET 2.0 public API, only after data.gov.in fails or has no usable records.
    ag_error = ""
    _ag_started = time.monotonic()
    _mandi_source_log("agmarknet_2_public", "START", state=state_name, market=market_name, commodity=requested_commodity)
    if time.monotonic() < deadline:
        try:
            remaining = max(0.5, deadline - time.monotonic())
            async def _ag_bounded():
                return await asyncio.wait_for(
                    _fetch_agmarknet_2_live(state_name, market_name, requested_commodity, request_deadline=deadline),
                    timeout=remaining,
                )
            ag_records, ag_error = asyncio.run(_ag_bounded())
        except Exception as exc:
            ag_records, ag_error = [], f"{type(exc).__name__}: {str(exc)[:180]}"
    else:
        ag_records, ag_error = [], "mandi_total_budget_exceeded_before_agmarknet"

    if ag_records:
        normalized = _normalise_mandi_records(ag_records)
        if normalized:
            latest_rows, latest_date = _mandi_latest_rows(normalized)
            normalized = latest_rows
            print(f"[MANDI_DEBUG] source_success priority=2 source='agmarknet_2_public' latest_date={latest_date!r} records={len(normalized)}")
            _mandi_source_log("agmarknet_2_public", "RESULT", status="SUCCESS", elapsed_ms=int((time.monotonic()-_ag_started)*1000), http_status=0, records=len(normalized), state=state_name, market=market_name, commodity=requested_commodity)
            response_payload = {
                "ok": True,
                "live_available": True,
                "live_api_configured": True,
                "source": "agmarknet_2_public",
                "checked_at": checked_at,
                "price_unit_source": "₹/quintal (AGMARKNET 2.0)",
                "display_price_unit": "₹/20kg",
                "records": normalized[:100],
                "message": f"AGMARKNETના {latest_date}ના ડેટામાંથી અધિકૃત ભાવ મળ્યો.",
                "latest_arrival_date": normalized[0].get("arrival_date", "") if normalized else latest_date,
                "source_policy": source_policy,
                "diagnostics": {
                    "primary": {"request_ok": False, "records": 0, "source": "data.gov.in", "error": data_error or "no_fresh_records", "http_status": int(upstream_status or 0)},
                    "secondary": {"request_ok": True, "records": len(normalized), "source": "agmarknet_2_public", "latest_date": latest_date},
                },
            }
            _store_in_shared_pool(state_name, market_name, requested_commodity, response_payload, normalized)
            return response_payload
    _mandi_source_log("agmarknet_2_public", "RESULT", status="FAILED" if ag_error else "NO_USABLE_DATA", elapsed_ms=int((time.monotonic()-_ag_started)*1000), http_status=0, records=0, state=state_name, market=market_name, commodity=requested_commodity, error=ag_error or "no_fresh_records")
    print(f"[MANDI_DEBUG] secondary_failed source='agmarknet_2_public' error={ag_error or 'no_fresh_records'!r}")

    # 3) THIRD: CEDA-hosted Agmarknet daily data, only after the first two sources fail.
    ceda_error = ""
    ceda_records = []
    _ceda_started = time.monotonic()
    _mandi_source_log("ceda_agmarknet_fallback", "START", state=state_name, market=market_name, commodity=requested_commodity)
    if time.monotonic() < deadline and market_name:
        ceda_error = "CEDA skipped because the request specifies an exact market"
    elif time.monotonic() < deadline:
        try:
            remaining = max(0.5, deadline - time.monotonic())
            async def _ceda_bounded():
                return await asyncio.wait_for(
                    _fetch_ceda_fresh_mandi(state_name, "", requested_commodity),
                    timeout=min(float(MANDI_CEDA_TIMEOUT_SECONDS), remaining),
                )
            ceda_records, ceda_error = asyncio.run(_ceda_bounded())
        except Exception as exc:
            ceda_records, ceda_error = [], f"{type(exc).__name__}: {str(exc)[:180]}"
    else:
        ceda_error = "mandi_total_budget_exceeded_before_ceda"

    if ceda_records:
        latest_rows, latest_date = _mandi_latest_rows(ceda_records)
        normalized = _normalise_mandi_records(latest_rows)
        if normalized:
            print(f"[MANDI_DEBUG] source_success priority=3 source='ceda_agmarknet_fallback' latest_date={latest_date!r} records={len(normalized)}")
            _mandi_source_log("ceda_agmarknet_fallback", "RESULT", status="SUCCESS", elapsed_ms=int((time.monotonic()-_ceda_started)*1000), http_status=0, records=len(normalized), state=state_name, market=market_name, commodity=requested_commodity)
            response_payload = {
                "ok": True,
                "live_available": True,
                "live_api_configured": True,
                "source": "ceda_agmarknet_fallback",
                "checked_at": checked_at,
                "price_unit_source": "₹/quintal (Agmarknet via CEDA)",
                "display_price_unit": "₹/20kg",
                "records": normalized[:100],
                "latest_arrival_date": normalized[0].get("arrival_date", "") if normalized else latest_date,
                "message": f"CEDAના Agmarknet ડેટામાંથી {latest_date}નો ભાવ મળ્યો.",
                "source_policy": source_policy,
                "diagnostics": {
                    "primary": {"request_ok": False, "records": 0, "source": "data.gov.in", "error": data_error or "no_fresh_records", "http_status": int(upstream_status or 0)},
                    "secondary": {"request_ok": False, "records": 0, "source": "agmarknet_2_public", "error": ag_error or "no_fresh_records"},
                    "third": {"request_ok": True, "records": len(normalized), "source": "ceda_agmarknet_fallback", "latest_date": latest_date},
                },
            }
            _store_in_shared_pool(state_name, market_name, requested_commodity, response_payload, normalized)
            return response_payload

    _mandi_source_log("ceda_agmarknet_fallback", "RESULT", status="FAILED" if ceda_error else "NO_USABLE_DATA", elapsed_ms=int((time.monotonic()-_ceda_started)*1000), http_status=0, records=0, state=state_name, market=market_name, commodity=requested_commodity, error=ceda_error or "no_fresh_records")
    print(
        f"[MANDI_DEBUG] all_sources_failed state={state_name!r} market={market_name!r} commodity={requested_commodity!r} "
        f"data_gov_error={data_error or 'no_fresh_records'!r} agmarknet_error={ag_error or 'no_fresh_records'!r} "
        f"ceda_error={ceda_error or 'no_fresh_records'!r}"
    )
    return unavailable(
        "આજનો, ગઈકાલનો કે છેલ્લા 3 દિવસનો માન્ય બજાર ભાવ કોઈપણ ઉપલબ્ધ સ્રોતમાંથી મળ્યો નથી.",
        data_error or ag_error or ceda_error or "no_fresh_data_in_last_3_days",
        {
            "primary": {"request_ok": False, "records": 0, "source": "data.gov.in", "http_status": int(upstream_status or 0), "error": data_error or "no_fresh_records"},
            "secondary": {"request_ok": False, "records": 0, "source": "agmarknet_2_public", "error": ag_error or "no_fresh_records"},
            "third": {"request_ok": False, "records": 0, "source": "ceda_agmarknet_fallback", "error": ceda_error or "no_fresh_records"},
        },
    )


# Phase 1: Mukadam marketplace API (appended; existing backend code preserved)
from fastapi.responses import Response
from typing import Optional
from mukadam_service import (
    init_mukadam_db,
    register_or_update_mukadam,
    update_mukadam_quick_status,
    search_nearby_mukadams,
    record_rating_or_contact,
    export_mukadams_csv,
)

init_mukadam_db()


class MukadamRegisterRequest(BaseModel):
    name: str
    mobile: str
    pin: str
    district: str = ""
    taluka: str = ""
    village: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    available_status: str = "available"
    available_from_date: str = ""
    total_labors: int = 0
    male_labors: int = 0
    female_labors: int = 0
    wage_type: str = "daily"
    daily_wage_rate: float = 0.0
    contract_rate_details: str = ""
    rickshaw_fare_type: str = "per_km"
    rickshaw_fare_rate: float = 0.0
    mukadami_type: str = "per_labor"
    mukadami_rate: float = 0.0
    skills: str = ""
    notes: str = ""


class MukadamStatusRequest(BaseModel):
    mobile: str
    pin: str
    available_status: str = "unavailable"
    available_from_date: str = ""
    total_labors: Optional[int] = None


class MukadamActionRequest(BaseModel):
    mobile: str
    action: str = "contact"
    stars: Optional[float] = None


@app.post("/api/mukadam/register")
async def api_mukadam_register(req: MukadamRegisterRequest):
    return register_or_update_mukadam(req.dict())


@app.post("/api/mukadam/status")
async def api_mukadam_status(req: MukadamStatusRequest):
    return update_mukadam_quick_status(req.dict())


@app.get("/api/mukadam/search")
async def api_mukadam_search(
    district: str = "",
    taluka: str = "",
    village: str = "",
    skill: str = "",
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    max_km: float = 60.0,
    required_labors: int = 0,
    include_unavailable: bool = False,
):
    return search_nearby_mukadams(
        district=district,
        taluka=taluka,
        village=village,
        skill=skill,
        farmer_lat=lat,
        farmer_lon=lon,
        max_km=max_km,
        required_labors=required_labors,
        include_unavailable=include_unavailable,
    )


@app.post("/api/mukadam/action")
async def api_mukadam_action(req: MukadamActionRequest):
    return record_rating_or_contact(req.dict())


@app.get("/api/mukadam/export_csv")
async def api_mukadam_export_csv():
    csv_data = export_mukadams_csv()
    bom_csv = "\ufeff" + csv_data
    return Response(
        content=bom_csv.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=gujarat_mukadam_list.csv"},
    )
