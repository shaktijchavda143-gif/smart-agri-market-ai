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
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from google import genai
from google.genai import types

APP_VERSION = "12.1 Official Mandi + Verified CEDA Freshness Fallback"
MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip() or "llama-3.3-70b-versatile"
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


def groq_client():
    key = os.getenv("GROQ_API_KEY", "").strip()
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1") if key else None


def norm(text: str) -> str:
    return " ".join((text or "").strip().lower().replace("-", " ").split())


def rule_based_answer(question: str, context: dict | None) -> str:
    """Use the supplied agent's crop knowledge even when OpenAI is not configured."""
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
        "groq_configured": bool(os.getenv("GROQ_API_KEY", "").strip()),
        "gemini_vision_configured": bool(GEMINI_API_KEY),
        "gemini_vision_model": GEMINI_VISION_MODEL,
        "mandi_api_configured": bool(os.getenv("DATA_GOV_API_KEY", "").strip()),
        "mandi_rate_limit_cooldown_seconds": MANDI_RATE_LIMIT_COOLDOWN_SECONDS,
        "news_service": "google-news-rss",
        "model": MODEL,
    }


NEWS_DEFAULT_MAX_AGE_HOURS = 48
NEWS_FALLBACK_MAX_AGE_HOURS = 168

def _news_max_age_hours() -> int:
    try:
        value = int(os.getenv("NEWS_MAX_AGE_HOURS", str(NEWS_DEFAULT_MAX_AGE_HOURS)))
        return max(1, min(value, 168))
    except Exception:
        return NEWS_DEFAULT_MAX_AGE_HOURS

def _parse_news_date(value: str):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

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

# News business contract:
# - 48h is the primary window.
# - 168h is a fallback window only when the same request has no valid 48h item.
# - Publication timestamps are normalized to UTC before comparison.
# - Gujarati is detected from article text, not from a publisher allow-list.
# - Category/crop intent is preserved during fallback.
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


def _is_gujarati_news_source(source: str) -> bool:
    # Source is a quality/diagnostic signal only, never a language gate.
    low = " ".join((source or "").casefold().split())
    return any(name in low for name in (
        "tv9 gujarati", "tv9gujarati", "abp asmita", "abp gujarati",
        "sandesh", "divya bhaskar", "divyabhaskar", "gujarat samachar",
        "gujarat first", "vtv gujarati", "zee 24 kalak", "news18 gujarati",
        "gstv", "gujarat mitra", "aajkaal", "aaj kaal",
    ))


def _is_gujarati_article(item: dict) -> bool:
    title = str(item.get("original_title") or item.get("title") or "")
    description = str(item.get("description") or "")
    # Title is the strongest signal; description can rescue a genuine mixed
    # headline. Source can only boost confidence, never override English text.
    return _has_gujarati_text(title) or (
        _gujarati_score(title, description) >= 0.12 and
        sum("\u0a80" <= ch <= "\u0aff" for ch in (title + description)) >= 8
    )


def _news_query_for_category(crop: str, category: str) -> str:
    crop = crop.strip()
    category = (category or "agriculture").strip().lower()
    crop_en = NEWS_CROP_ENGLISH.get(crop, crop)
    if category == "subsidy":
        base = "Gujarat farmer subsidy scheme agriculture"
    elif category == "methods":
        base = "Gujarat farming method technology agriculture"
    elif category == "market":
        base = "Gujarat APMC market price farmer agriculture"
    else:
        base = "Gujarat agriculture farmer crop news"
    return f"{base} {crop_en}".strip() if crop else base


def _category_relevant(item: dict, category: str) -> bool:
    category = (category or "agriculture").strip().lower()
    if category not in NEWS_CATEGORY_TERMS:
        category = "agriculture"
    text = " ".join([
        str(item.get("original_title") or item.get("title") or ""),
        str(item.get("description") or ""),
        str(item.get("source") or ""),
    ]).casefold()
    return any(term.casefold() in text for term in NEWS_CATEGORY_TERMS[category])


def _crop_relevant(item: dict, crop: str) -> bool:
    if not crop:
        return True
    aliases = NEWS_CROP_SYNONYMS.get(crop, (crop,))
    text = " ".join([
        str(item.get("original_title") or item.get("title") or ""),
        str(item.get("description") or ""),
    ]).casefold()
    return any(alias.casefold() in text for alias in aliases)


def _news_relevance(item: dict, crop: str = "", require_crop: bool = False, category: str = "agriculture") -> bool:
    text = " ".join([
        str(item.get("original_title") or item.get("title") or ""),
        str(item.get("description") or ""),
        str(item.get("source") or ""),
    ]).casefold()
    if not any(term.casefold() in text for term in GUJARAT_TERMS):
        return False
    if not any(term.casefold() in text for term in NEWS_CATEGORY_TERMS["agriculture"]):
        return False
    if not _category_relevant(item, category):
        return False
    return not require_crop or _crop_relevant(item, crop)


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
        "duplicate_rejected": 0,
    }
    base = re.sub(r"\s+when:\d+d\b", "", (query or "").strip(), flags=re.IGNORECASE).strip()
    if not base:
        base = "Gujarat agriculture farmer news"
    now = datetime.now(timezone.utc)
    effective_max_age = max_age_hours if max_age_hours is not None else _news_max_age_hours()
    effective_max_age = max(1, min(int(effective_max_age), NEWS_FALLBACK_MAX_AGE_HOURS))
    cutoff = now - timedelta(hours=effective_max_age)
    time_operator = "when:2d" if effective_max_age <= 48 else "when:7d"
    candidates = [f"{base} {time_operator}".strip()]
    if relevance_crop:
        crop_en = NEWS_CROP_ENGLISH.get(relevance_crop, relevance_crop)
        alternate = f"{base} {relevance_crop} {crop_en} {time_operator}".strip()
        if alternate not in candidates:
            candidates.append(alternate)
    india_tz = timezone(timedelta(hours=5, minutes=30))
    items, seen = [], set()

    for effective_query in candidates[:4]:
        if len(items) >= limit:
            break
        _LAST_NEWS_FETCH_DIAGNOSTICS["queries_tried"] += 1
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
            source = (rss_item.findtext("source") or "").strip()
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
            }
            if not _is_gujarati_article(candidate):
                _LAST_NEWS_FETCH_DIAGNOSTICS["non_gujarati_headline_rejected"] += 1
                continue
            _LAST_NEWS_FETCH_DIAGNOSTICS["gujarati_items"] += 1

            if not _category_relevant(candidate, category):
                _LAST_NEWS_FETCH_DIAGNOSTICS["category_irrelevant"] += 1
                _LAST_NEWS_FETCH_DIAGNOSTICS["irrelevant_items_rejected"] += 1
                continue
            if require_crop and not _crop_relevant(candidate, relevance_crop):
                _LAST_NEWS_FETCH_DIAGNOSTICS["crop_irrelevant"] += 1
                _LAST_NEWS_FETCH_DIAGNOSTICS["irrelevant_items_rejected"] += 1
                continue
            # Gujarat context may be in title/summary or publisher identity.
            combined = " ".join((title, candidate["description"], source)).casefold()
            if not any(term.casefold() in combined for term in GUJARAT_TERMS):
                _LAST_NEWS_FETCH_DIAGNOSTICS["irrelevant_items_rejected"] += 1
                continue

            item = {
                "title": title, "display_title": title, "original_title": title,
                "link": link, "published_at": published.isoformat(),
                "published_text": published.astimezone(india_tz).strftime("%d-%m-%Y %I:%M %p"),
                "source": source or "સમાચાર સ્ત્રોત",
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

    items.sort(key=lambda x: x["published_at"], reverse=True)
    if include_article_text:
        selected = items[:min(limit, 18)]
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
    return items[:limit]


@app.get("/api/v1/news")
def news(crop: str = "", category: str = "agriculture"):
    crop_name = crop.strip()
    category_name = (category or "agriculture").strip().lower()
    if category_name not in NEWS_CATEGORY_TERMS:
        category_name = "agriculture"

    base_query = _news_query_for_category(crop_name, category_name)
    primary = _fetch_news_items(
        base_query + " " + NEWS_QUERY_SUFFIX,
        12,
        category=category_name,
        relevance_crop=crop_name,
        require_crop=bool(crop_name),
        max_age_hours=48,
    )
    primary_diag = dict(_LAST_NEWS_FETCH_DIAGNOSTICS)
    fallback_used = False
    fallback_reason = ""

    if primary:
        items = primary
        final_window = "48h"
    else:
        # Only the time window broadens. Category, crop and Gujarati/article
        # relevance are kept identical to the original request.
        fallback = _fetch_news_items(
            base_query,
            12,
            category=category_name,
            relevance_crop=crop_name,
            require_crop=bool(crop_name),
            max_age_hours=168,
        )
        fallback_diag = dict(_LAST_NEWS_FETCH_DIAGNOSTICS)
        items = fallback
        fallback_used = bool(fallback)
        final_window = "7d_fallback" if fallback else "none"
        fallback_reason = (
            "no valid 48-hour result; same category/crop query broadened to 7 days"
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
    diagnostics["crop_relevant_48h"] = len(primary) if crop_name else len(primary)
    diagnostics["final_48h_results"] = len(primary)
    diagnostics["STARTING_7_DAY_FALLBACK"] = bool(not primary)
    diagnostics["fallback_used"] = fallback_used
    diagnostics["fallback_reason"] = fallback_reason
    diagnostics["final_window"] = final_window
    diagnostics["final_results"] = len(items)
    diagnostics["newest_selected"] = items[0]["published_at"] if items else None
    diagnostics["oldest_selected"] = items[-1]["published_at"] if items else None
    if not primary:
        diagnostics["fallback_diagnostics"] = fallback_diag
        diagnostics["gujarati_7d"] = fallback_diag.get("gujarati_items", 0)
        diagnostics["category_relevant_7d"] = len(items)
        diagnostics["crop_relevant_7d"] = len(items) if crop_name else len(items)

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
    try:
        client = groq_client()
        if client is None:
            return {"answer": rule_based_answer(req.question, req.context), "mode": "agent"}
        ctx = req.context or {}
        prompt = f"ખેડૂત પ્રશ્ન: {req.question.strip()}\nખેડૂત સંદર્ભ: {ctx}"
        response = client.responses.create(model=MODEL, instructions=SYSTEM, input=prompt)
        answer = (response.output_text or "").strip()
        if not answer:
            answer = rule_based_answer(req.question, req.context)
        return {"answer": answer, "mode": "groq", "model": MODEL}
    except Exception as exc:
        # Never make the Android button fail just because the external AI service failed.
        return {
            "answer": rule_based_answer(req.question, req.context),
            "mode": "agent_fallback",
            "warning": str(exc),
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
MANDI_API_TIMEOUT_SECONDS = _mandi_env_seconds("MANDI_TIMEOUT_SECONDS", 20, 5, 60)
MANDI_RATE_LIMIT_COOLDOWN_SECONDS = _mandi_env_seconds("MANDI_RATE_LIMIT_COOLDOWN_SECONDS", 900, 60, 86400)
# Optional secondary Agmarknet-derived source. It is NEVER used unless a real
# CEDA response is received and every returned row passes the freshness and
# price/provenance checks below. No sample/mock values are permitted.
CEDA_API_KEY = os.getenv("CEDA_API_KEY", "").strip()
CEDA_API_BASE = os.getenv("CEDA_API_BASE", "https://api.ceda.ashoka.edu.in/v1").strip().rstrip("/")
MANDI_FALLBACK_MAX_AGE_HOURS = _mandi_env_seconds("MANDI_FALLBACK_MAX_AGE_HOURS", 48, 1, 168)
MANDI_CEDA_TIMEOUT_SECONDS = _mandi_env_seconds("MANDI_CEDA_TIMEOUT_SECONDS", 20, 5, 60)
_mandi_rate_limit_until: dict[str, float] = {}
_mandi_global_rate_limit_until: float = 0.0
_ceda_global_rate_limit_until: float = 0.0
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


def _mandi_api_get(state: str, district: str, commodity: str):
    """Fetch exclusively from the official data.gov.in Mandi API.

    No cache, stale snapshot, news price, article extraction, calculated price,
    or alternate market data source is permitted here.
    """
    global _mandi_global_rate_limit_until

    state = (state or "").strip() or "Gujarat"
    district = (district or "").strip()
    normalized_commodity = (commodity or "ALL").strip() or "ALL"
    api_commodity = GUJARATI_CROP_ALIASES.get(normalized_commodity, normalized_commodity)
    if api_commodity.upper() == "ALL":
        api_commodity = ""

    print(
        "[MANDI_DEBUG] request_received "
        f"state={state!r} district={district!r} commodity={normalized_commodity!r}"
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
    rate_key = "|".join((state.lower(), district.lower(), api_commodity.lower()))
    now = time.monotonic()
    with _mandi_lock:
        cooldown_until = max(_mandi_rate_limit_until.get(rate_key, 0.0), _mandi_global_rate_limit_until)
        if cooldown_until > now:
            print(
                "[MANDI_DEBUG] official_api_rate_limit_cooldown "
                f"state={state!r} district={district!r} commodity={normalized_commodity!r}"
            )
            return None, "Live Mandi API limit પર છે; થોડા સમય પછી ફરી પ્રયાસ કરો."

        params = {
            "api-key": MANDI_API_KEY,
            "format": "json",
            "limit": "100",
            "offset": "0",
        }
        if state:
            params["filters[state]"] = state
        if district:
            params["filters[district]"] = district
        if api_commodity:
            params["filters[commodity]"] = api_commodity

        path = "/resource/" + MANDI_RESOURCE_ID
        url = f"{MANDI_API_SCHEME}://{MANDI_API_HOST}{path}?" + urllib.parse.urlencode(params)
        print(
            "[MANDI_DEBUG] official_api_request "
            f"scheme={MANDI_API_SCHEME!r} host={MANDI_API_HOST!r} path={path!r} "
            f"state={state!r} district={district!r} commodity={normalized_commodity!r} "
            f"timeout_seconds={MANDI_API_TIMEOUT_SECONDS}"
        )

        last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
        last_status = 0
        for attempt in range(2):
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "SmartAgriMarketAI/3.0",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=MANDI_API_TIMEOUT_SECONDS) as response:
                    status = int(getattr(response, "status", 200) or 200)
                    content_type = str((getattr(response, "headers", None) or {}).get("Content-Type", ""))
                    body = response.read()
                    print(
                        "[MANDI_DEBUG] official_api_response "
                        f"http_status={status} content_type={content_type!r} response_bytes={len(body)}"
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
                    normalized = _mandi_normalized_result(payload, normalized_commodity, fallback_used=False)
                    normalized["_diagnostics"]["http_status"] = status
                    normalized["_diagnostics"]["attempt"] = attempt + 1
                    _mandi_rate_limit_until.pop(rate_key, None)
                    _mandi_global_rate_limit_until = 0.0
                    return normalized, "", 0, status
            except urllib.error.HTTPError as exc:
                last_status = int(exc.code or 0)
                print(
                    "[MANDI_DEBUG] official_api_http_error "
                    f"http_status={last_status} attempt={attempt + 1}"
                )
                if last_status == 429:
                    cooldown = _mandi_retry_after_seconds(exc)
                    _mandi_rate_limit_until[rate_key] = time.monotonic() + cooldown
                    _mandi_global_rate_limit_until = time.monotonic() + cooldown
                    return None, f"Live Mandi API limit પર છે; server cooldown {cooldown} સેકન્ડ માટે સક્રિય છે.", cooldown, last_status
                if last_status in (401, 403):
                    return None, "Live Mandi API authentication/permission error.", 0, last_status
                last_error = f"Live Mandi HTTP error {last_status}."
                if last_status not in (502, 503, 504):
                    return None, last_error, 0, last_status
            except urllib.error.URLError as exc:
                last_status = 0
                _mandi_log_exception(exc, http_status=0)
                last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
            except TimeoutError as exc:
                last_status = 0
                _mandi_log_exception(exc, http_status=0)
                last_error = "Live Mandi API timeout થયો."
            except Exception as exc:
                last_status = 0
                _mandi_log_exception(exc, http_status=0)
                last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."

            if attempt < 1:
                time.sleep(1.0)

        print(
            "[MANDI_DEBUG] official_api_final_failure "
            f"http_status={last_status} error={last_error!r}"
        )
        return None, last_error, 0, last_status

async def _fetch_ceda_fresh_mandi(state: str, district: str, commodity: str) -> tuple[list[dict[str, Any]], str]:
    """Fetch real Agmarknet-derived data through CEDA when configured.

    CEDA is id-based. This fallback resolves the requested commodity/state and,
    when no district is supplied, queries Gujarat districts concurrently. Only
    rows whose date is <= MANDI_FALLBACK_MAX_AGE_HOURS are accepted. CEDA's
    documented historical coverage can lag, so stale rows are deliberately
    rejected instead of being shown as live prices.
    """
    if not CEDA_API_KEY:
        return [], "CEDA_API_KEY not configured"
    state = (state or "Gujarat").strip()
    requested = (commodity or "ALL").strip() or "ALL"
    api_commodity = GUJARATI_CROP_ALIASES.get(requested, requested)
    if api_commodity.upper() == "ALL":
        return [], "CEDA fallback requires a specific commodity"

    global _ceda_global_rate_limit_until

    now_monotonic = time.monotonic()
    with _mandi_lock:
        if _ceda_global_rate_limit_until > now_monotonic:
            remaining = max(1, int(_ceda_global_rate_limit_until - now_monotonic))
            return [], f"CEDA API rate-limit cooldown active ({remaining}s remaining)"

    timeout = httpx.Timeout(MANDI_CEDA_TIMEOUT_SECONDS, connect=min(8.0, MANDI_CEDA_TIMEOUT_SECONDS))
    headers = {"Authorization": f"Bearer {CEDA_API_KEY}", "Accept": "application/json", "User-Agent": "SmartAgriMarketAI/CEDA/1.0"}
    now_ist = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    from_date = (now_ist.date() - timedelta(days=MANDI_FALLBACK_MAX_AGE_HOURS // 24 + 2)).isoformat()
    to_date = now_ist.date().isoformat()

    async with httpx.AsyncClient(base_url=CEDA_API_BASE, headers=headers, timeout=timeout) as client:
        async def call(method: str, path: str, payload: dict | None = None):
            global _ceda_global_rate_limit_until
            for attempt in range(2):
                try:
                    response = await client.request(method, path, json=payload)
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After", "").strip()
                        cooldown = 900
                        if retry_after:
                            try:
                                cooldown = max(60, min(int(retry_after), 86400))
                            except ValueError:
                                try:
                                    retry_at = parsedate_to_datetime(retry_after)
                                    if retry_at.tzinfo is None:
                                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                                    cooldown = max(60, min(int((retry_at - datetime.now(timezone.utc)).total_seconds()), 86400))
                                except Exception:
                                    pass
                        with _mandi_lock:
                            _ceda_global_rate_limit_until = max(_ceda_global_rate_limit_until, time.monotonic() + cooldown)
                        print(f"[MANDI_DEBUG] ceda_rate_limited path={path!r} retry_after_seconds={cooldown} attempt={attempt + 1}")
                        if attempt == 0 and cooldown <= 60:
                            await asyncio.sleep(cooldown)
                            continue
                        return None, f"HTTP 429; Retry-After={cooldown}s"
                    if response.status_code != 200:
                        return None, f"HTTP {response.status_code}"
                    body = response.json()
                    output = body.get("output", {}) if isinstance(body, dict) else {}
                    if output.get("type") != "success":
                        return None, str(output.get("message") or "CEDA API error")[:240]
                    return output.get("data") or [], ""
                except Exception as exc:
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    return None, f"{type(exc).__name__}: {str(exc)[:180]}"
            return None, "CEDA API request failed"

        commodities, err = await call("GET", "/agmarknet/commodities")
        if commodities is None:
            return [], f"CEDA commodities failed: {err}"
        matches = [c for c in commodities if isinstance(c, dict) and norm(str(c.get("commodity_name", ""))) == norm(api_commodity)]
        if not matches:
            matches = [c for c in commodities if isinstance(c, dict) and norm(api_commodity) in norm(str(c.get("commodity_name", "")))]
        if len(matches) != 1:
            return [], "CEDA commodity resolution failed"
        commodity_id = matches[0].get("commodity_id")

        geographies, err = await call("GET", "/agmarknet/geographies")
        if geographies is None:
            return [], f"CEDA geographies failed: {err}"
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
                rows, call_err = await call("POST", "/agmarknet/prices", {
                    "commodity_id": commodity_id,
                    "state_id": state_id,
                    "district_id": [did],
                    "from_date": from_date,
                    "to_date": to_date,
                })
                if rows is None:
                    return []
                market_rows, _ = await call("POST", "/agmarknet/markets", {
                    "commodity_id": commodity_id,
                    "state_id": state_id,
                    "district_id": did,
                    "indicator": "price",
                })
                market_names = {m.get("market_id"): m.get("market_name", "") for m in (market_rows or []) if isinstance(m, dict)}
                out = []
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    raw_date = r.get("date", "")
                    parsed = _parse_mandi_date(raw_date)
                    if not parsed:
                        continue
                    age_hours = (now_ist - parsed.astimezone(now_ist.tzinfo)).total_seconds() / 3600.0
                    if age_hours < -1/60 or age_hours > MANDI_FALLBACK_MAX_AGE_HOURS:
                        continue
                    min_p, max_p, modal_p = r.get("min_price"), r.get("max_price"), r.get("modal_price")
                    try:
                        min_f, max_f, modal_f = float(min_p), float(max_p), float(modal_p)
                    except (TypeError, ValueError):
                        continue
                    if not (min_f > 0 and min_f <= modal_f <= max_f):
                        continue
                    out.append({
                        "state": state,
                        "district": dname,
                        "market": market_names.get(r.get("market_id"), ""),
                        "commodity": str(matches[0].get("commodity_name") or api_commodity),
                        "arrival_date": parsed.astimezone(now_ist.tzinfo).strftime("%d/%m/%Y"),
                        "min_price": min_f,
                        "max_price": max_f,
                        "modal_price": modal_f,
                        "source": "CEDA Agmarknet API",
                        "source_url": "https://api.ceda.ashoka.edu.in/",
                        "_source_age_hours": round(age_hours, 2),
                    })
                return out

        batches = await asyncio.gather(*(district_prices(did, dname) for did, dname in districts.items()))
        rows = [r for batch in batches for r in batch]
        if not rows:
            return [], "CEDA returned no fresh records"
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
            "min_price": min_price,
            "modal_price": modal_price,
            "max_price": max_price,
            # Official data.gov.in values are ₹/quintal. These derived fields
            # are only for presentation; the original source values are kept.
            "min_price_20kg": _price_per_20kg(min_price),
            "modal_price_20kg": _price_per_20kg(modal_price),
            "max_price_20kg": _price_per_20kg(max_price),
            "price_unit_source": "₹/quintal",
            "display_price_unit": "₹/20kg",
            "source": pick(row, "source"),
            "source_url": pick(row, "source_url"),
        })
    return normalized

@app.get("/api/v1/mandi")
def mandi(state: str = "Gujarat", district: str = "", commodity: str = "ALL"):
    """Official API-only Live Mandi endpoint.

    Source chain:
        Android -> this endpoint -> data.gov.in API-key request -> actual records

    News/RSS/article prices and stale cache are intentionally not part of this
    endpoint. If the official API has no usable records, records is [].
    """
    checked_at = datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime("%d-%m-%Y %H:%M")

    requested_commodity = (commodity or "ALL").strip() or "ALL"
    result = _mandi_api_get(state, district, requested_commodity)
    if len(result) == 4:
        data, error, _cooldown, upstream_status = result
    else:
        data, error = result
        upstream_status = 0

    if isinstance(data, dict):
        records = data.get("records") or []
        if not isinstance(records, list):
            records = []

        raw_diag = data.get("_diagnostics", {}) if isinstance(data, dict) else {}
        raw_count = int(raw_diag.get("raw_record_count", len(records)) or len(records))
        http_status = int(raw_diag.get("http_status", upstream_status or 200) or 200)

        print(
            "[MANDI_DEBUG] final_result "
            f"state={state!r} district={district!r} commodity={requested_commodity!r} "
            f"http_status={http_status} records={len(records)} source=official_api"
        )

        return {
            "ok": True,
            "live_available": bool(records),
            "live_api_configured": bool(MANDI_API_KEY),
            "source": "official_api",
            "checked_at": checked_at,
            "price_unit_source": "₹/quintal (data.gov.in / AGMARKNET)",
            "display_price_unit": "₹/20kg",
            "records": records[:100],
            "message": "Live Mandi ભાવ મળ્યા." if records else "હાલમાં પસંદ કરેલા પાક માટે મંડી ભાવ ઉપલબ્ધ નથી.",
            "diagnostics": {
                "api": {
                    "request_ok": True,
                    "http_status": http_status,
                    "records": len(records),
                    "raw_records": raw_count,
                    "source": "official_api",
                    "attempt": raw_diag.get("attempt", 1),
                    "fallback_used": bool(raw_diag.get("fallback_used", False)),
                    "latest_date": raw_diag.get("latest_date", ""),
                }
            },
        }

    # Secondary live-source attempt: CEDA Agmarknet. It is only accepted when
    # the actual API returns records that are no older than the configured
    # freshness window. No hardcoded/sample/cache/news prices are permitted.
    try:
        ceda_records, ceda_error = asyncio.run(_fetch_ceda_fresh_mandi(state, district, requested_commodity))
    except RuntimeError:
        # If this endpoint is called from an already-running event loop, execute
        # the async fallback in a short-lived worker thread.
        def _runner():
            return asyncio.run(_fetch_ceda_fresh_mandi(state, district, requested_commodity))
        with ThreadPoolExecutor(max_workers=1) as pool:
            ceda_records, ceda_error = pool.submit(_runner).result(timeout=MANDI_CEDA_TIMEOUT_SECONDS + 5)
    except Exception as exc:
        ceda_records, ceda_error = [], f"{type(exc).__name__}: {str(exc)[:180]}"

    if ceda_records:
        normalized = _normalise_mandi_records(ceda_records)
        if normalized:
            print(f"[MANDI_DEBUG] ceda_fallback_success records={len(normalized)}")
            return {
                "ok": True,
                "live_available": True,
                "live_api_configured": bool(MANDI_API_KEY),
                "source": "ceda_agmarknet_fallback",
                "checked_at": checked_at,
                "price_unit_source": "₹/quintal (Agmarknet via CEDA)",
                "display_price_unit": "₹/20kg",
                "records": normalized[:100],
                "message": "Live Agmarknet ભાવ મળ્યા.",
                "diagnostics": {
                    "api": {"request_ok": False, "http_status": int(upstream_status or 0), "records": 0, "source": "official_api"},
                    "fallback": {"request_ok": True, "records": len(normalized), "source": "ceda_agmarknet_fallback", "max_age_hours": MANDI_FALLBACK_MAX_AGE_HOURS},
                },
            }

    print(
        "[MANDI_DEBUG] final_result "
        f"state={state!r} district={district!r} commodity={requested_commodity!r} "
        f"http_status={int(upstream_status or 0)} records=0 source=official_api "
        f"ceda_fallback={bool(CEDA_API_KEY)} ceda_error={ceda_error!r} error={error or ''!r}"
    )
    return {
        "ok": True,
        "live_available": False,
        "live_api_configured": bool(MANDI_API_KEY),
        "source": "official_api",
        "checked_at": checked_at,
        "price_unit_source": "₹/quintal (data.gov.in / AGMARKNET)",
        "display_price_unit": "₹/20kg",
        "records": [],
        "message": "હાલમાં પસંદ કરેલા પાક માટે મંડી ભાવ ઉપલબ્ધ નથી.",
        "live_error": error or "no_records",
        "diagnostics": {
            "api": {
                "request_ok": False,
                "http_status": int(upstream_status or 0),
                "records": 0,
                "source": "official_api",
                "error": error or "no_records",
                "host": MANDI_API_HOST,
                "resource_id": MANDI_RESOURCE_ID,
                "timeout_seconds": MANDI_API_TIMEOUT_SECONDS,
            }
        },
    }
