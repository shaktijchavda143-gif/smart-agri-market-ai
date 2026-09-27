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

APP_VERSION = "11.2 Gemini Vision + Mandi Cache Guard"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
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


def openai_client():
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return OpenAI(api_key=key) if key else None


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
        "openai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "gemini_vision_configured": bool(GEMINI_API_KEY),
        "gemini_vision_model": GEMINI_VISION_MODEL,
        "mandi_api_configured": bool(os.getenv("DATA_GOV_API_KEY", "").strip()),
        "mandi_cache_ttl_seconds": MANDI_CACHE_TTL_SECONDS,
        "mandi_rate_limit_cooldown_seconds": MANDI_RATE_LIMIT_COOLDOWN_SECONDS,
        "mandi_stale_max_seconds": MANDI_STALE_MAX_SECONDS,
        "news_service": "google-news-rss",
        "model": MODEL,
    }


NEWS_DEFAULT_MAX_AGE_HOURS = 48

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

# Google News RSS can return an empty feed for some Gujarati + when:2d
# combinations even when the same topic has RSS results without that operator.
# Freshness is therefore enforced locally from pubDate; the search operator is
# only an optional accelerator, never the sole freshness mechanism.
# Google News RSS reliably accepts the English/ASCII Gujarat queries below.
# Gujarati output is handled separately so a Gujarati-only RSS query cannot
# turn into HTTP 400 and leave the app empty.
NEWS_CROP_ENGLISH = {
    "કપાસ": "cotton", "મગફળી": "groundnut peanut", "ઘઉં": "wheat",
    "બાજરી": "bajra millet", "મકાઈ": "maize corn", "જીરું": "cumin jeera",
    "ધાણા": "coriander", "તલ": "sesame", "એરંડા": "castor",
    "ચણા": "gram chana", "તુવેર": "tur arhar", "મગ": "moong",
    "અડદ": "urad black gram", "ડુંગળી": "onion", "બટાકા": "potato",
    "ટામેટા": "tomato", "મરચાં": "chilli", "લસણ": "garlic",
    "શેરડી": "sugarcane", "કેરી": "mango", "કેળા": "banana",
    "દાડમ": "pomegranate",
}


# Sources allowed for the 7-day fallback. The fallback must show Gujarati
# news-channel/news-paper sources, not an English agriculture publication.
GUJARATI_NEWS_SOURCE_NAMES = (
    "tv9 gujarati", "tv9gujarati", "abp asmita", "abp gujarati",
    "sandesh", "divya bhaskar", "divyabhaskar", "gujarat samachar",
    "gujarat first", "vtv gujarati", "zee 24 kalak", "news18 gujarati",
    "gstv", "gujarat mitra", "aajkaal", "aaj kaal",
)

def _is_gujarati_news_source(source: str) -> bool:
    low = " ".join((source or "").casefold().split())
    return any(name in low for name in GUJARATI_NEWS_SOURCE_NAMES)

def _has_gujarati_text(text: str) -> bool:
    # Require actual Gujarati Unicode characters so an English headline is
    # never accepted merely because its display title was replaced.
    return any("\u0a80" <= ch <= "\u0aff" for ch in (text or ""))

def _is_approved_gujarati_news_item(source: str, title: str) -> bool:
    # This is a hard gate for BOTH the 48-hour feed and the 7-day fallback.
    # An English article must never be displayed with an artificial Gujarati
    # title. The source itself must be a known Gujarati news publisher and the
    # RSS headline must contain real Gujarati Unicode text.
    return _is_gujarati_news_source(source) and _has_gujarati_text(title)

NEWS_QUERY_VARIANTS = (
    "Gujarat agriculture farmer news",
    "Gujarat agriculture farmers crop news",
    "Gujarat farming farmers government agriculture news",
)

def _news_query_for_category(crop: str, category: str) -> str:
    crop = crop.strip()
    category = (category or "all").strip().lower()
    crop_en = NEWS_CROP_ENGLISH.get(crop, crop)
    if category == "agriculture":
        return f"Gujarat {crop_en} farmer agriculture news" if crop else "Gujarat agriculture farmer news"
    if category == "subsidy":
        return "Gujarat farmer subsidy scheme iKhedut agriculture"
    if category == "methods":
        return f"Gujarat {crop_en} farming method technology" if crop else "Gujarat agriculture farming technology"
    if category == "market":
        return f"Gujarat {crop_en} APMC market price farmer" if crop else "Gujarat APMC market price farmer"
    return "Gujarat farmer agriculture scheme technology crop news"


NEWS_TITLE_PHRASES = (
    ("Gujarat's natural farming push", "ગુજરાતમાં પ્રાકૃતિક ખેતીને પ્રોત્સાહન"),
    ("Natural farming more than doubles", "પ્રાકૃતિક ખેતીથી ઉપજમાં મોટો વધારો"),
    ("Natural farming doubles", "પ્રાકૃતિક ખેતીથી ઉપજ બમણી"),
    ("Farmer Registry", "ખેડૂત રજિસ્ટ્રી અંગે મહત્વના સમાચાર"),
    ("farmer registry", "ખેડૂત રજિસ્ટ્રી અંગે મહત્વના સમાચાર"),
    ("subsidy", "ખેડૂત સબસિડી અંગે મહત્વના સમાચાર"),
    ("scheme", "ખેડૂત યોજના અંગે મહત્વના સમાચાર"),
    ("agriculture", "ગુજરાત કૃષિ અંગે મહત્વના સમાચાર"),
    ("farmer", "ગુજરાતના ખેડૂતો માટે મહત્વના સમાચાર"),
)

def _gujarati_news_title(title: str, crop: str = "", category: str = "agriculture") -> str:
    """Create a safe Gujarati display title without pretending to translate unknown text."""
    raw = " ".join((title or "").split())
    low = raw.casefold()
    for phrase, translated in NEWS_TITLE_PHRASES:
        if phrase.casefold() in low:
            prefix = f"{crop}: " if crop else ""
            return prefix + translated
    if crop:
        return f"{crop}: ગુજરાતમાં ખેતી અને ખેડૂતો અંગે મહત્વના સમાચાર"
    category_titles = {
        "subsidy": "ગુજરાતમાં ખેડૂત સહાય અને યોજનાઓ અંગે મહત્વના સમાચાર",
        "methods": "ગુજરાતમાં ખેતી પદ્ધતિ અને ટેકનોલોજી અંગે મહત્વના સમાચાર",
        "market": "ગુજરાતના બજાર અને ખેડૂતો અંગે મહત્વના સમાચાર",
        "agriculture": "ગુજરાતમાં ખેતી અને ખેડૂતો અંગે મહત્વના સમાચાર",
    }
    return category_titles.get(category, "ગુજરાતમાં કૃષિ અને ખેડૂતો અંગે મહત્વના સમાચાર")


def _news_relevance(item: dict, crop: str = "", require_crop: bool = False) -> bool:
    """Return True only for Gujarat agriculture/farmer news.

    The RSS query is a discovery mechanism only. This gate prevents unrelated
    stories from being shown and, for a crop-specific request, prevents a
    generic Gujarat agriculture story from occupying the crop result.
    """
    text = " ".join([
        str(item.get("original_title") or item.get("title") or ""),
        str(item.get("description") or ""),
        str(item.get("source") or ""),
    ]).casefold()
    gujarat_terms = ("gujarat", "ગુજરાત", "ahmedabad", "rajkot", "surat", "vadodara", "gandhinagar")
    agriculture_terms = (
        "agriculture", "agricultural", "farmer", "farmers", "farming", "crop", "crops",
        "cultivation", "harvest", "harvesting", "irrigation", "natural farming", "organic farming",
        "apmc", "mandi", "agri", "કૃષિ", "ખેડૂત", "ખેડૂતો", "ખેતી", "પાક", "બજાર", "સિંચાઈ",
        "પ્રાકૃતિક ખેતી", "ખાતર", "રોગ", "જંતુ", "બિયારણ", "સબસિડી", "યોજના",
    )
    if not any(term in text for term in gujarat_terms):
        return False
    if not any(term in text for term in agriculture_terms):
        return False
    if require_crop and crop:
        crop_terms = NEWS_CROP_ENGLISH.get(crop, crop).casefold().split()
        # Gujarati crop name is also accepted.
        if crop.casefold() not in text and not any(term in text for term in crop_terms if len(term) >= 4):
            return False
    return True


def _fetch_news_items(query: str, limit: int = 24, include_article_text: bool = False, category: str = "agriculture", max_age_hours: int | None = None, allow_older_fallback: bool = False, relevance_crop: str = "", require_crop: bool = False):
    """Fetch fresh Google News RSS items with resilient query fallbacks.

    We do NOT trust the Google `when:2d` search operator as the freshness
    mechanism because some localized feeds return an empty RSS document for
    that operator. Every accepted item is still required to have a valid
    publication timestamp inside NEWS_MAX_AGE_HOURS.
    """
    global _LAST_NEWS_FETCH_DIAGNOSTICS
    _LAST_NEWS_FETCH_DIAGNOSTICS = {
        "rss_search_failed": 0,
        "rss_items_seen": 0,
        "fresh_items_kept": 0,
        "queries_tried": 0,
        "empty_feeds": 0,
        "date_parse_failed": 0,
        "older_than_window": 0,
        "irrelevant_items_rejected": 0,
        "non_gujarati_source_rejected": 0,
        "non_gujarati_headline_rejected": 0,
    }
    candidates = []
    # Never send a Gujarati-only query to Google News RSS: the endpoint can
    # respond with HTTP 400 for Gujarati query text. Use ASCII/English search
    # terms and localize the displayed title separately.
    if allow_older_fallback:
        # Dedicated fallback pipeline. Do not depend on the crop-specific
        # Gujarati query or the primary query list. These are known-good ASCII
        # Google News searches for relevant Gujarat agriculture/farmer news.
        fallback_queries = (
            "Gujarat agriculture farmer news",
            "Gujarat farmers agriculture farming news",
            "Gujarat natural farming farmers news",
            "Gujarat agriculture crop farmers news",
            "Gujarat government agriculture farmer news",
        )
        for value in fallback_queries:
            value = value.strip()
            if value and value not in candidates:
                candidates.append(value)
    else:
        for value in [query.strip(), *NEWS_QUERY_VARIANTS]:
            value = value.strip()
            if value and value not in candidates:
                candidates.append(value)
    now = datetime.now(timezone.utc)
    effective_max_age = max_age_hours if max_age_hours is not None else _news_max_age_hours()
    cutoff = now - timedelta(hours=effective_max_age)
    india_tz = timezone(timedelta(hours=5, minutes=30))
    items, seen = [], set()

    # Keep the number of RSS calls bounded. The publication timestamp below is
    # the authoritative freshness check, so there is no need to issue a second
    # `when:2d` request for every query.
    max_queries = 5 if allow_older_fallback else 4
    for effective_query in candidates[:max_queries]:
        if len(items) >= limit:
            break
        # The fallback is deliberately NOT constrained by Google's when:2d
        # operator; local max_age_hours=168 is the authoritative 7-day rule.
        effective_query = effective_query.replace(" when:2d", "").replace(" when:1d", "")
        _LAST_NEWS_FETCH_DIAGNOSTICS["queries_tried"] += 1
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": effective_query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126.0 SmartAgriMarketAI/1.4",
                "Accept": "application/rss+xml,application/xml,text/xml,*/*;q=0.8",
            },
        )
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
        for item in rss_items:
            _LAST_NEWS_FETCH_DIAGNOSTICS["rss_items_seen"] += 1
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date_text = (item.findtext("pubDate") or "").strip()
            source = (item.findtext("source") or "").strip()
            description = (item.findtext("description") or "").strip()
            published = _parse_news_date(date_text)
            if not title or not link:
                continue
            if published is None:
                _LAST_NEWS_FETCH_DIAGNOSTICS["date_parse_failed"] += 1
                continue
            if published < cutoff:
                _LAST_NEWS_FETCH_DIAGNOSTICS["older_than_window"] += 1
                continue
            if published > now + timedelta(minutes=10):
                continue
            candidate_item = {"original_title": title, "description": _html_to_text(description), "source": source}
            # Hard Gujarati-only gate for EVERY accepted article, including
            # the normal 48-hour feed. Previously this check existed only in
            # the 7-day fallback, which allowed English publications to pass
            # through and then receive a fake/generated Gujarati title.
            if not _is_gujarati_news_source(source):
                _LAST_NEWS_FETCH_DIAGNOSTICS["non_gujarati_source_rejected"] = _LAST_NEWS_FETCH_DIAGNOSTICS.get("non_gujarati_source_rejected", 0) + 1
                continue
            if not _has_gujarati_text(title):
                _LAST_NEWS_FETCH_DIAGNOSTICS["non_gujarati_headline_rejected"] = _LAST_NEWS_FETCH_DIAGNOSTICS.get("non_gujarati_headline_rejected", 0) + 1
                continue
            if not _news_relevance(candidate_item, relevance_crop, require_crop=require_crop):
                _LAST_NEWS_FETCH_DIAGNOSTICS["irrelevant_items_rejected"] = _LAST_NEWS_FETCH_DIAGNOSTICS.get("irrelevant_items_rejected", 0) + 1
                continue
            key = link.split("?", 1)[0].casefold()
            if key in seen:
                continue
            seen.add(key)
            _LAST_NEWS_FETCH_DIAGNOSTICS["fresh_items_kept"] += 1
            item_age_hours = max(0.0, (now - published).total_seconds() / 3600.0)
            items.append({
                "title": title,
                # Preserve the publisher's real Gujarati headline. Never
                # translate or synthesize an English headline for display.
                "display_title": title,
                "original_title": title,
                "link": link,
                "published_at": published.isoformat(),
                "published_text": published.astimezone(india_tz).strftime("%d-%m-%Y %I:%M %p"),
                "source": source or "સમાચાર સ્ત્રોત",
                "description": _html_to_text(description),
                "category": category or "agriculture",
                "is_fresh": item_age_hours <= _news_max_age_hours(),
                "age_hours": round(item_age_hours, 1),
                "news_age_type": "fresh" if item_age_hours <= _news_max_age_hours() else "important_older",
            })
            if len(items) >= limit:
                break

    items.sort(key=lambda x: x["published_at"], reverse=True)
    if not include_article_text:
        return items[:limit]
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
    return selected


@app.get("/api/v1/news")
def news(crop: str = "", category: str = "agriculture"):
    crop_name = crop.strip()
    category_name = (category or "agriculture").strip().lower()
    query = _news_query_for_category(crop_name, category_name) + " " + NEWS_QUERY_SUFFIX
    items = _fetch_news_items(query, 12, category=category_name, relevance_crop=crop_name, require_crop=bool(crop_name))
    diagnostics = dict(_LAST_NEWS_FETCH_DIAGNOSTICS)

    # If the crop-specific feed has no fresh item, deliberately run the
    # important Gujarat agriculture/farmer fallback. This is still subject to
    # the same local publication-date freshness check; nothing stale is shown.
    fallback_used = False
    fallback_reason = ""
    if not items:
        # Important fallback is intentionally separate from the primary 48-hour
        # freshness rule. If no fresh article exists, show relevant recent
        # Gujarat agriculture/farmer news up to 7 days old, explicitly marked
        # as older. This prevents an empty News screen without pretending an
        # older article is a fresh/today article.
        fallback_query = "Gujarat agriculture farmer news " + NEWS_QUERY_SUFFIX
        fallback_items = _fetch_news_items(
            fallback_query, 12, category=category_name,
            max_age_hours=168, allow_older_fallback=True, relevance_crop="", require_crop=False,
        )
        fallback_diag = dict(_LAST_NEWS_FETCH_DIAGNOSTICS)
        if fallback_items:
            fallback_used = True
            fallback_reason = "no fresh 48-hour article; relevant Gujarat agriculture/farmer news up to 7 days old used"
            items = fallback_items
        else:
            fallback_reason = "no fresh 48-hour article and no relevant fallback news within 7 days"
        for key in ("rss_search_failed", "rss_items_seen", "fresh_items_kept", "queries_tried", "empty_feeds", "date_parse_failed", "older_than_window", "irrelevant_items_rejected"):
            diagnostics[key] = diagnostics.get(key, 0) + fallback_diag.get(key, 0)

    for item in items:
        # Both the fresh feed and the 7-day fallback are already hard-gated to
        # Gujarati publisher + real Gujarati headline. Preserve that exact
        # headline; never generate a Gujarati title from an English article.
        original_title = item.get("original_title") or item.get("title", "")
        item["display_title"] = original_title
        item["title"] = original_title

    diagnostics["max_age_hours"] = _news_max_age_hours()
    diagnostics["fallback_used"] = fallback_used
    diagnostics["fallback_reason"] = fallback_reason
    diagnostics["english_headlines_rejected"] = diagnostics.get("non_gujarati_headline_rejected", 0)
    diagnostics["irrelevant_items_rejected"] = diagnostics.get("irrelevant_items_rejected", 0)
    diagnostics["fresh_48h_items"] = sum(1 for item in items if item.get("is_fresh"))
    diagnostics["important_older_items"] = sum(1 for item in items if item.get("news_age_type") == "important_older")
    diagnostics["fallback_window_hours"] = 168 if fallback_used else 0
    return {
        "ok": True,
        "crop": crop_name,
        "category": category_name,
        "max_age_hours": _news_max_age_hours(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "diagnostics": diagnostics,
        "message": ("તાજા ગુજરાતી કૃષિ સમાચાર" if diagnostics.get("fresh_48h_items", 0) else ("મહત્વના તાજેતરના ગુજરાતી કૃષિ સમાચાર (7 દિવસ સુધી)" if items else "છેલ્લા 48 કલાકમાં તાજા સમાચાર મળ્યા નથી અને 7 દિવસમાં સંબંધિત fallback સમાચાર મળ્યા નથી.")),
    }

@app.post("/api/v1/ai/ask")
def ask(req: Ask):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="પ્રશ્ન ખાલી છે.")
    try:
        client = openai_client()
        if client is None:
            return {"answer": rule_based_answer(req.question, req.context), "mode": "agent"}
        ctx = req.context or {}
        prompt = f"ખેડૂત પ્રશ્ન: {req.question.strip()}\nખેડૂત સંદર્ભ: {ctx}"
        response = client.responses.create(model=MODEL, instructions=SYSTEM, input=prompt)
        answer = (response.output_text or "").strip()
        if not answer:
            answer = rule_based_answer(req.question, req.context)
        return {"answer": answer, "mode": "openai", "model": MODEL}
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
MANDI_RESOURCE_ID = os.getenv("DATA_GOV_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070").strip()
MANDI_API_KEY = os.getenv("DATA_GOV_API_KEY", "").strip()

# Mandi protection is intentionally server-side so repeated Android requests do
# not repeatedly consume the upstream data.gov.in quota.
def _mandi_env_seconds(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(int(os.getenv(name, str(default))), maximum))
    except Exception:
        return default

MANDI_CACHE_TTL_SECONDS = _mandi_env_seconds("MANDI_CACHE_TTL_SECONDS", 600, 30, 3600)
MANDI_RATE_LIMIT_COOLDOWN_SECONDS = _mandi_env_seconds("MANDI_RATE_LIMIT_COOLDOWN_SECONDS", 900, 60, 86400)
MANDI_STALE_MAX_SECONDS = _mandi_env_seconds("MANDI_STALE_MAX_SECONDS", 86400, 300, 7 * 86400)
MANDI_UPSTREAM_FAILURE_COOLDOWN_SECONDS = _mandi_env_seconds("MANDI_UPSTREAM_FAILURE_COOLDOWN_SECONDS", 300, 30, 3600)
_mandi_cache: dict[str, dict[str, Any]] = {}
_mandi_rate_limit_until: dict[str, float] = {}
_mandi_global_rate_limit_until: float = 0.0
_mandi_upstream_failure_until: float = 0.0
_mandi_lock = threading.RLock()

GUJARATI_CROP_ALIASES = {
    "કપાસ": "Cotton", "મગફળી": "Groundnut", "ઘઉં": "Wheat", "બાજરી": "Bajra",
    "મકાઈ": "Maize", "જીરું": "Jeera", "ધાણા": "Dhaniya", "તલ": "Sesamum",
    "એરંડા": "Castor Seed", "ચણા": "Gram", "તુવેર": "Arhar", "મગ": "Moong",
    "અડદ": "Black Gram", "ડુંગળી": "Onion", "બટાકા": "Potato", "ટામેટા": "Tomato",
    "મરચાં": "Chilli", "લસણ": "Garlic", "શેરડી": "Sugarcane", "કેરી": "Mango",
    "કેળા": "Banana", "દાડમ": "Pomegranate"
}


def _mandi_cache_key(state: str, district: str, commodity: str) -> str:
    normalized = GUJARATI_CROP_ALIASES.get((commodity or "").strip(), (commodity or "").strip())
    return "|".join(((state or "").strip().lower(), (district or "").strip().lower(), normalized.lower()))


def _mandi_cached_result(key: str, now: float, allow_stale: bool = False):
    item = _mandi_cache.get(key)
    if not item:
        return None
    age = max(0.0, now - float(item.get("saved_at", now)))
    if age <= MANDI_CACHE_TTL_SECONDS or (allow_stale and age <= MANDI_STALE_MAX_SECONDS):
        return item.get("data"), age
    return None


def _mandi_retry_after_seconds(exc: urllib.error.HTTPError) -> int:
    raw = ""
    try:
        raw = str(exc.headers.get("Retry-After", "")).strip()
    except Exception:
        raw = ""
    try:
        value = int(raw)
        return max(60, min(value, 86400))
    except Exception:
        return MANDI_RATE_LIMIT_COOLDOWN_SECONDS


def _mandi_cache_response(key: str, data: dict[str, Any], now: float):
    # Keep only JSON-safe response data and normalized records; never store the API key.
    _mandi_cache[key] = {"saved_at": now, "data": data}


def _mandi_cached_payload(data: dict[str, Any], age: float, reason: str):
    cached = dict(data)
    cached["live_available"] = False
    cached["source"] = "data.gov.in cached"
    cached["cache_age_seconds"] = int(max(0, age))
    cached["cache_status"] = "stale" if age > MANDI_CACHE_TTL_SECONDS else "fresh"
    cached["live_error"] = reason
    cached["message"] = "છેલ્લો સફળ Mandi data બતાવવામાં આવી રહ્યો છે. " + reason
    return cached


def _norm_mandi_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("-", " ").replace("_", " ").split())


def _commodity_matches(row: dict[str, Any], requested: str) -> bool:
    """Keep only rows belonging to the requested commodity during broad fallbacks."""
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
    """Return rows from the latest available arrival date, matching the old working agent."""
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


def _mandi_api_get(state: str, district: str, commodity: str):
    global _mandi_global_rate_limit_until, _mandi_upstream_failure_until
    """Hybrid live Mandi fetch: old working fallbacks + current cache/429 protection."""
    if not MANDI_API_KEY:
        return None, "Live Mandi API key server પર configure નથી. Renderમાં DATA_GOV_API_KEY ઉમેરો."

    state = (state or "").strip() or "Gujarat"
    district = (district or "").strip()
    normalized_commodity = (commodity or "ALL").strip() or "ALL"
    api_commodity = GUJARATI_CROP_ALIASES.get(normalized_commodity, normalized_commodity)
    if api_commodity.upper() == "ALL":
        api_commodity = ""
    key = _mandi_cache_key(state, district, normalized_commodity)
    now = time.monotonic()

    with _mandi_lock:
        cached = _mandi_cached_result(key, now, allow_stale=False)
        if cached:
            data, age = cached
            return _mandi_cached_payload(data, age, "server cacheમાંથી મળ્યું."), ""

        if _mandi_upstream_failure_until > now:
            stale = _mandi_cached_result(key, now, allow_stale=True)
            reason = "data.gov.in upstream 502/503/504 પછી server cooldown ચાલુ છે."
            if stale:
                data, age = stale
                return _mandi_cached_payload(data, age, reason), ""
            return None, reason

        cooldown_until = max(_mandi_rate_limit_until.get(key, 0.0), _mandi_global_rate_limit_until)
        if cooldown_until > now:
            stale = _mandi_cached_result(key, now, allow_stale=True)
            reason = "data.gov.in API limit પછી server cooldown ચાલુ છે."
            if stale:
                data, age = stale
                return _mandi_cached_payload(data, age, reason), ""
            return None, "Live Mandi API limit પર છે; server cooldown ચાલુ છે. થોડા સમય પછી ફરી પ્રયાસ કરો."

        def request_once(*, use_state: bool, use_district: bool, use_commodity: bool):
            global _mandi_global_rate_limit_until, _mandi_upstream_failure_until
            params = {"api-key": MANDI_API_KEY, "format": "json", "limit": "25", "offset": "0"}
            if use_state and state:
                params["filters[state]"] = state
            if use_district and district:
                params["filters[district]"] = district
            if use_commodity and api_commodity:
                params["filters[commodity]"] = api_commodity
            url = "https://api.data.gov.in/resource/" + MANDI_RESOURCE_ID + "?" + urllib.parse.urlencode(params)
            last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
            for attempt in range(2):
                req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SmartAgriMarketAI/1.2"})
                try:
                    with urllib.request.urlopen(req, timeout=10) as response:
                        body = response.read().decode("utf-8", "ignore")
                        payload = json.loads(body)
                        return payload, "", 0
                except urllib.error.HTTPError as exc:
                    if exc.code == 429:
                        cooldown = _mandi_retry_after_seconds(exc)
                        _mandi_rate_limit_until[key] = time.monotonic() + cooldown
                        _mandi_global_rate_limit_until = time.monotonic() + cooldown
                        return None, f"Live Mandi API limit પર છે; server cooldown {cooldown} સેકન્ડ માટે સક્રિય છે.", cooldown
                    if exc.code in (401, 403):
                        return None, "Live Mandi API authentication/permission error.", 0
                    last_error = f"Live Mandi HTTP error {exc.code}."
                    # 502/503 can be transient; retry this exact query briefly.
                    if exc.code not in (502, 503, 504):
                        return None, last_error, 0
                except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                    last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
                except Exception as exc:
                    last_error = f"Live Mandi request error: {str(exc)[:180]}"
                if attempt < 2:
                    time.sleep(float(2 ** attempt))
            if "HTTP error 502" in last_error or "HTTP error 503" in last_error or "HTTP error 504" in last_error or "service હાલમાં ઉપલબ્ધ નથી" in last_error:
                _mandi_upstream_failure_until = time.monotonic() + MANDI_UPSTREAM_FAILURE_COOLDOWN_SECONDS
            return None, last_error, 0

        # Preserve the old working order. District-specific first; if it has no usable
        # rows, broaden gradually instead of repeatedly asking the same failing query.
        attempts = []
        if district:
            attempts.append((True, True, bool(api_commodity)))
        if state and api_commodity:
            attempts.append((True, False, True))
        if api_commodity:
            attempts.append((False, False, True))
        # For ALL, explicitly broaden from Gujarat-filtered to an unfiltered
        # resource query. The previous code only made the state query, so a
        # 502/504 there could never reach a broader fallback.
        if state:
            attempts.append((True, False, False))
        if not api_commodity:
            attempts.append((False, False, False))
        if not attempts:
            attempts.append((False, False, False))

        last_error = "Live Mandi service હાલમાં ઉપલબ્ધ નથી."
        fallback_used = False
        for index, (use_state, use_district, use_commodity) in enumerate(attempts):
            data, error, cooldown = request_once(use_state=use_state, use_district=use_district, use_commodity=use_commodity)
            if cooldown:
                stale = _mandi_cached_result(key, time.monotonic(), allow_stale=True)
                if stale:
                    cached_data, age = stale
                    return _mandi_cached_payload(cached_data, age, error), ""
                return None, error

            last_error = error or last_error
            if isinstance(data, dict):
                result = _mandi_normalized_result(data, normalized_commodity, fallback_used=(index > 0))
                if result.get("records"):
                    result["_diagnostics"]["attempt"] = index + 1
                    result["_diagnostics"]["fallback_used"] = index > 0
                    _mandi_cache_response(key, result, time.monotonic())
                    _mandi_rate_limit_until.pop(key, None)
                    _mandi_global_rate_limit_until = 0.0
                    _mandi_upstream_failure_until = 0.0
                    return result, ""
            fallback_used = True

        stale = _mandi_cached_result(key, time.monotonic(), allow_stale=True)
        if stale:
            cached_data, age = stale
            return _mandi_cached_payload(cached_data, age, last_error), ""
        return None, last_error


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
        if not any((min_price, modal_price, max_price)):
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
        })
    return normalized

def _news_price_number(text: str):
    if not text:
        return None
    cleaned = str(text).replace(",", "").replace("₹", " ").replace("રૂ.", " ").replace("રૂ", " ")
    trans = str.maketrans("૦૧૨૩૪૫૬૭૮૯", "0123456789")
    cleaned = cleaned.translate(trans)
    m = re.search(r"(?<!\d)(\d{2,7}(?:\.\d+)?)", cleaned)
    return float(m.group(1)) if m else None


def _normalise_for_match(text: str) -> str:
    trans = str.maketrans("૦૧૨૩૪૫૬૭૮૯", "0123456789")
    return re.sub(r"\s+", " ", (text or "").translate(trans).casefold()).strip()


# Common Gujarati/English crop names found in Gujarati market-price articles.
NEWS_CROP_ALIASES = {
    "કપાસ": ["કપાસ", "cotton", "kapas"],
    "મગફળી": ["મગફળી", "સિંગ", "groundnut", "peanut"],
    "ઘઉં": ["ઘઉં", "wheat"],
    "બાજરી": ["બાજરી", "બાજરો", "bajra", "pearl millet"],
    "મકાઈ": ["મકાઈ", "મકાઇ", "maize", "corn"],
    "જીરું": ["જીરું", "જીરૂ", "jeera", "cumin"],
    "ધાણા": ["ધાણા", "dhaniya", "coriander"],
    "તલ": ["તલ", "sesamum", "sesame"],
    "એરંડા": ["એરંડા", "એરંડી", "castor"],
    "ચણા": ["ચણા", "ચણ", "gram", "chana"],
    "તુવેર": ["તુવેર", "તુવર", "arhar", "tur"],
    "મગ": ["મગ", "moong"],
    "અડદ": ["અડદ", "અડદ દાળ", "black gram", "urad"],
    "ડુંગળી": ["ડુંગળી", "onion"],
    "બટાકા": ["બટાકા", "બટેટા", "potato"],
    "ટામેટા": ["ટામેટા", "ટમેટા", "tomato"],
    "મરચાં": ["મરચાં", "મરચા", "chilli", "chili"],
    "લસણ": ["લસણ", "garlic"],
    "શેરડી": ["શેરડી", "sugarcane"],
    "કેરી": ["કેરી", "mango"],
    "કેળા": ["કેળા", "કેળું", "banana"],
    "દાડમ": ["દાડમ", "pomegranate"],
}


def _detect_crop(text: str, requested_crop: str = "") -> str:
    hay = _normalise_for_match(text)
    if requested_crop.strip():
        requested = requested_crop.strip()
        aliases = NEWS_CROP_ALIASES.get(requested)
        if aliases is None:
            canonical = GUJARATI_CROP_ALIASES.get(requested, requested)
            aliases = NEWS_CROP_ALIASES.get(canonical, [requested, canonical])
            requested = canonical if canonical in NEWS_CROP_ALIASES else requested_crop.strip()
        if any(a and _normalise_for_match(a) in hay for a in aliases):
            return requested
        return ""
    for crop, aliases in NEWS_CROP_ALIASES.items():
        if any(_normalise_for_match(a) in hay for a in aliases):
            return crop
    return ""


_LOCATION_BAD_WORDS = {
    "આજ", "આજના", "આજે", "ગુજરાત", "gujarat", "market", "market yard",
    "prices", "price", "today", "ભાવ", "બજાર", "કપાસ", "મગફળી", "groundnut",
    "cotton", "wheat", "ઘઉં", "યાર્ડ", "apmc", "એપીએમસી", "સમાચાર"
}

def _clean_location_candidate(value: str) -> str:
    candidate = " ".join((value or "").split()).strip(" -,:;.|")
    if not candidate or len(candidate) > 60:
        return ""
    words = _normalise_for_match(candidate).split()
    if not words or all(w in _LOCATION_BAD_WORDS for w in words):
        return ""
    if any(w in _LOCATION_BAD_WORDS for w in words):
        # Reject phrases such as "cotton prices today APMC"; do not guess.
        return ""
    return candidate


def _extract_location(text: str) -> str:
    """Return only an explicit market/APMC/taluka/district name; never guess."""
    patterns = [
        r"(?:APMC|એપીએમસી)\s*(?:માર્કેટ\s*યાર્ડ|market\s*yard|યાર્ડ)?\s*[:\-]?\s*([A-Za-z\u0A80-\u0AFF][A-Za-z\u0A80-\u0AFF .'-]{1,50}?)(?=\s*(?:માં|માટે|ના|નુ|નો|ની|ભાવ|prices?|price|rate|,|\.|$))",
        r"([A-Za-z\u0A80-\u0AFF][A-Za-z\u0A80-\u0AFF .'-]{1,50}?)\s*(?:APMC|એપીએમસી)\b",
        r"([A-Za-z\u0A80-\u0AFF][A-Za-z\u0A80-\u0AFF .'-]{1,50}?)\s*(?:માર્કેટ\s*યાર્ડ|market\s*yard|યાર્ડ)\b",
        r"([A-Za-z\u0A80-\u0AFF][A-Za-z\u0A80-\u0AFF .'-]{1,50}?)\s*(?:તાલુકા|taluka)\b",
        r"([A-Za-z\u0A80-\u0AFF][A-Za-z\u0A80-\u0AFF .'-]{1,50}?)\s*(?:જિલ્લા|district)\b",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            candidate = _clean_location_candidate(m.group(1))
            if candidate:
                return candidate
    return "Location not mentioned"


def _price_pairs(text: str):
    """Extract price ranges from prose and pipe-delimited HTML table rows."""
    trans = str.maketrans("૦૧૨૩૪૫૬૭૮૯", "0123456789")
    t = (text or "").translate(trans)
    pairs = []

    # HTML table rows: | Crop | 1171 | 1921 | (currency symbols may be present).
    for line in t.splitlines():
        cells = [c.strip(" |:;\t") for c in line.split("|")]
        cells = [c for c in cells if c]
        if len(cells) < 3:
            continue
        numeric = []
        for idx, cell in enumerate(cells):
            m = re.fullmatch(r"(?:₹|રૂ\.?|Rs\.?|INR)?\s*([\d,]{2,7}(?:\.\d+)?)\s*(?:₹|રૂ\.?|Rs\.?|INR)?", cell, re.IGNORECASE)
            if m:
                value = float(m.group(1).replace(",", ""))
                numeric.append((idx, value))
        if len(numeric) >= 2:
            first_idx, first_value = numeric[0]
            second_idx, second_value = numeric[1]
            context = " | ".join(cells[:first_idx]).strip(" |-:;")
            if not context:
                context = " | ".join(cells[:second_idx]).strip(" |-:;")
            if 1 <= first_value <= 1000000 and 1 <= second_value <= 1000000:
                pairs.append((context, min(first_value, second_value), max(first_value, second_value), True))

    # Prose: ₹1171 to ₹1921; Rs. 1171 to Rs. 1921; રૂ. 1171 થી રૂ. 1921;
    # and plain 1171 થી 1921. Currency may appear before either number.
    currency = r"(?:₹|રૂ\.?|Rs\.?|INR)?"
    number = r"[\d,]{2,7}(?:\.\d+)?"
    range_pattern = re.compile(
        rf"{currency}\s*({number})\s*"
        rf"(?:થી|to|[-–—])\s*{currency}\s*({number})",
        re.IGNORECASE,
    )
    for m in range_pattern.finditer(t):
        a = float(m.group(1).replace(",", ""))
        b = float(m.group(2).replace(",", ""))
        if 1 <= a <= 1000000 and 1 <= b <= 1000000:
            context = t[max(0, m.start()-140):min(len(t), m.end()+140)]
            pairs.append((context, min(a, b), max(a, b), False))
    return pairs


def _extract_news_prices(item: dict, requested_crop: str):
    title = str(item.get("title") or "").strip()
    body = str(item.get("description") or "").strip()
    hay = f"{title}\n{body}".strip()
    if not hay:
        return []
    location = _extract_location(hay)
    out, seen = [], set()
    for context, min_price, max_price, is_row in _price_pairs(hay):
        crop = _detect_crop(context, requested_crop)
        if not crop:
            crop = _detect_crop(hay, requested_crop)
        if not crop:
            continue
        nearby = _normalise_for_match(context)
        if (not is_row) and not re.search(
            r"₹|રૂ|રૂપિયા|ભાવ|rate|price|prices|rs\.?|inr|to|થી|ક્વિન્ટલ|મણ|yard|યાર્ડ|apmc|એપીએમસી",
            nearby, re.IGNORECASE
        ):
            continue
        key = (location.casefold(), crop.casefold(), int(min_price), int(max_price), item.get("published_at", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "date": item.get("published_at") or item.get("published_text") or "",
            "location": location,
            "commodity": crop,
            "min_price": str(int(min_price)),
            "max_price": str(int(max_price)),
            "source": item.get("source") or "સમાચાર સ્ત્રોત",
            "title": title,
            "link": item.get("link") or "",
            "published_at": item.get("published_at") or "",
            "published_text": item.get("published_text") or "",
            "price_source": "News / Article",
        })
    return out

def _news_market_prices_detailed(crop: str, limit: int = 20):
    if crop.strip():
        query = f'"{crop.strip()}" ગુજરાત APMC બજાર ભાવ યાર્ડ નીચો ઊંચો'
    else:
        query = "ગુજરાત APMC માર્કેટ યાર્ડ બજાર ભાવ આજે નીચો ઊંચો પાક"
    global _LAST_NEWS_FETCH_DIAGNOSTICS
    _LAST_NEWS_FETCH_DIAGNOSTICS = {"rss_search_failed": 0}
    diagnostics = {"rss_search_failed": 0, "fresh_articles": 0, "article_text_unavailable": 0,
                   "recognizable_prices": 0, "matching_crop": 0, "valid_locations": 0,
                   "backend_exception": ""}
    try:
        items = _fetch_news_items(query, 24, include_article_text=True)
    except Exception as exc:
        diagnostics["backend_exception"] = str(exc)[:300]
        return [], diagnostics
    diagnostics["fresh_articles"] = len(items)
    diagnostics["rss_search_failed"] = _LAST_NEWS_FETCH_DIAGNOSTICS.get("rss_search_failed", 0)
    prices, seen = [], set()
    for item in items:
        if not item.get("description", "").strip():
            diagnostics["article_text_unavailable"] += 1
        pairs = _price_pairs(f"{item.get('title','')}\n{item.get('description','')}")
        if pairs:
            diagnostics["recognizable_prices"] += 1
        extracted = _extract_news_prices(item, crop)
        if extracted:
            diagnostics["matching_crop"] += len(extracted)
        for parsed in extracted:
            if parsed["location"] != "Location not mentioned":
                diagnostics["valid_locations"] += 1
            key = (parsed["location"].casefold(), parsed["commodity"].casefold(),
                   parsed["min_price"], parsed["max_price"], parsed["published_at"][:10])
            if key in seen:
                continue
            seen.add(key)
            prices.append(parsed)
            if len(prices) >= limit:
                break
        if len(prices) >= limit:
            break

    if not items:
        diagnostics["message"] = "No fresh articles"
    elif diagnostics["recognizable_prices"] == 0:
        diagnostics["message"] = "No recognizable prices"
    elif not prices:
        diagnostics["message"] = "No matching crop"
    else:
        diagnostics["message"] = "Prices extracted"
    return prices, diagnostics


def _news_market_prices(crop: str, limit: int = 30):
    return _news_market_prices_detailed(crop, limit)[0]


def _news_price_response(commodity: str = ""):
    checked_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%m-%Y %H:%M")
    prices, diagnostics = _news_market_prices_detailed(commodity, 20)
    return {
        "ok": True,
        "source": "news",
        "checked_at": checked_at,
        "news_window_hours": _news_max_age_hours(),
        "news_prices": prices,
        "diagnostics": diagnostics,
        "message": diagnostics.get("message", ""),
    }

@app.get("/api/v1/mandi/news")
def mandi_news(commodity: str = ""):
    # Separate endpoint: Android can render the news table even when the Live
    # data.gov.in request is unavailable, times out, or is rate-limited.
    try:
        return _news_price_response(commodity)
    except Exception as exc:
        return {
            "ok": False,
            "source": "news",
            "checked_at": datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%m-%Y %H:%M"),
            "news_window_hours": _news_max_age_hours(),
            "news_prices": [],
            "error": str(exc)[:300],
        }


@app.get("/api/v1/mandi")
def mandi(state: str = "Gujarat", district: str = "", commodity: str = "ALL"):
    checked_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%m-%Y %H:%M")

    # Live Mandi is deliberately isolated from general/news price content.
    data, error = _mandi_api_get(state, district, commodity)
    records = []
    if isinstance(data, dict):
        records = data.get("records") or []
        if district and data.get("district_filter_miss"):
            records = []
            error = error or "આ જિલ્લો માટે Live Mandi record મળ્યો નથી."

    live_available = bool(records)
    if live_available:
        message = "Live Mandi ભાવ મળ્યા."
    else:
        message = error or "Live Mandi APIમાંથી હાલ કોઈ usable price record મળ્યો નથી."

    raw_diag = data.get("_diagnostics", {}) if isinstance(data, dict) else {}
    raw_count = int(raw_diag.get("raw_record_count", 0) or 0)
    sample_keys = list(raw_diag.get("raw_sample_keys", []) or [])
    diagnostics = {
        "raw_record_count": raw_count,
        "normalized_record_count": len(records),
        "sample_record_keys": sample_keys[:30],
        "summary": f"API configured={bool(MANDI_API_KEY)}; raw={raw_count}; usable_price_rows={len(records)}" + (f"; sample keys={', '.join(sample_keys[:8])}" if sample_keys else "")
    }

    cache_status = data.get("cache_status", "") if isinstance(data, dict) else ""
    cache_age_seconds = data.get("cache_age_seconds", 0) if isinstance(data, dict) else 0
    source = data.get("source", "") if isinstance(data, dict) else ""
    if live_available:
        source = "data.gov.in Live Mandi API"
    elif not source:
        source = "none"
    diagnostics["cache_status"] = cache_status
    diagnostics["cache_age_seconds"] = int(cache_age_seconds or 0)
    diagnostics["fallback_used"] = bool(raw_diag.get("fallback_used", False))
    diagnostics["latest_date"] = raw_diag.get("latest_date", "")
    return {
        "ok": True,
        "live_available": live_available,
        "live_api_configured": bool(MANDI_API_KEY),
        "live_error": "" if live_available else (error or (data.get("live_error", "") if isinstance(data, dict) else "") or "no_records"),
        "source": source,
        "cache_status": cache_status,
        "cache_age_seconds": int(cache_age_seconds or 0),
        "checked_at": checked_at,
        "records": records[:50],
        "message": message,
        "diagnostics": diagnostics,
    }
