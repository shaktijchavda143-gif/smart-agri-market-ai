# -*- coding: utf-8 -*-
"""Smart Agri-Market AI HTTP backend.
Wraps the supplied Smart Agri-Market Agent so the Android app can call it.
"""
import os
import base64
import importlib.util
import urllib.parse
import urllib.request
import re
import json
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

APP_VERSION = "11.0 Gemini Vision Stable"
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


_LAST_NEWS_FETCH_DIAGNOSTICS = {"rss_search_failed": 0}

def _fetch_news_items(query: str, limit: int = 24, include_article_text: bool = False):
    """Collect a small, fresh, de-duplicated candidate set.

    RSS calls are bounded and article retrieval is concurrent with a small worker
    pool. This prevents the old dozens-of-sequential-pages latency problem.
    """
    queries = [query.strip()] if query.strip() else []
    queries.extend([
        "ગુજરાત APMC બજાર ભાવ આજે પાક નીચો ઊંચો ભાવ",
        "ગુજરાત માર્કેટ યાર્ડ બજાર ભાવ આજે કપાસ મગફળી ઘઉં",
    ])
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_news_max_age_hours())
    india_tz = timezone(timedelta(hours=5, minutes=30))
    items, seen = [], set()
    for search_query in queries[:3]:
        if len(items) >= limit:
            break
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": search_query, "hl": "gu", "gl": "IN", "ceid": "IN:gu"}
        )
        request = urllib.request.Request(url, headers={"User-Agent": "SmartAgriMarketAI/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                root = ET.fromstring(response.read(700000))
        except Exception:
            _LAST_NEWS_FETCH_DIAGNOSTICS["rss_search_failed"] += 1
            continue
        for item in root.findall(".//item")[:30]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date_text = (item.findtext("pubDate") or "").strip()
            source = (item.findtext("source") or "").strip()
            description = (item.findtext("description") or "").strip()
            published = _parse_news_date(date_text)
            if not title or not link or published is None or published < cutoff or published > now + timedelta(minutes=10):
                continue
            key = link.split("?", 1)[0].casefold()
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "title": title, "link": link, "published_at": published.isoformat(),
                "published_text": published.astimezone(india_tz).strftime("%d-%m-%Y %I:%M %p"),
                "source": source or "સમાચાર સ્ત્રોત",
                "description": _html_to_text(description),
            })
            if len(items) >= limit:
                break

    items.sort(key=lambda x: x["published_at"], reverse=True)
    if not include_article_text:
        return items[:limit]

    # Fetch only a bounded subset, concurrently.
    candidates = items[:min(limit, 18)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_article_text, item["link"]): item for item in candidates}
        for future in as_completed(futures):
            item = futures[future]
            try:
                fetched = future.result(timeout=9)
            except Exception:
                fetched = ""
            if fetched:
                item["description"] = (item.get("description", "") + "\n" + fetched).strip()[:60000]
    return candidates

@app.get("/api/v1/news")
def news(crop: str = ""):
    crop_name = crop.strip()
    if crop_name:
        query = f"{crop_name} ગુજરાત ખેડૂત ખેતી કૃષિ બજાર"
    else:
        query = "ગુજરાત ખેડૂત ખેતી કૃષિ બજાર"
    items = _fetch_news_items(query, 12)
    return {
        "ok": True,
        "crop": crop_name,
        "max_age_hours": _news_max_age_hours(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "message": "આજના પ્રકાશિત થયેલા સમાચાર" if items else "આજે નવા સમાચાર મળ્યા નથી."
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
        raise HTTPException(status_code=502, detail=f"Gemini Vision error: {exc}")

# ---------------- Secure Mandi price bridge ----------------
MANDI_RESOURCE_ID = os.getenv("DATA_GOV_RESOURCE_ID", "9ef84268-d588-465a-a308-a864a43d0070").strip()
MANDI_API_KEY = os.getenv("DATA_GOV_API_KEY", "").strip()

GUJARATI_CROP_ALIASES = {
    "કપાસ": "Cotton", "મગફળી": "Groundnut", "ઘઉં": "Wheat", "બાજરી": "Bajra",
    "મકાઈ": "Maize", "જીરું": "Jeera", "ધાણા": "Dhaniya", "તલ": "Sesamum",
    "એરંડા": "Castor Seed", "ચણા": "Gram", "તુવેર": "Arhar", "મગ": "Moong",
    "અડદ": "Black Gram", "ડુંગળી": "Onion", "બટાકા": "Potato", "ટામેટા": "Tomato",
    "મરચાં": "Chilli", "લસણ": "Garlic", "શેરડી": "Sugarcane", "કેરી": "Mango",
    "કેળા": "Banana", "દાડમ": "Pomegranate"
}


def _mandi_api_get(state: str, district: str, commodity: str):
    if not MANDI_API_KEY:
        return None, "Live Mandi API server પર configure થયેલી નથી."
    params = {"api-key": MANDI_API_KEY, "format": "json", "limit": "100"}
    if state.strip():
        params["filters[state]"] = state.strip()
    if district.strip():
        params["filters[district]"] = district.strip()
    if commodity.strip():
        params["filters[commodity]"] = GUJARATI_CROP_ALIASES.get(commodity.strip(), commodity.strip())
    url = "https://api.data.gov.in/resource/" + MANDI_RESOURCE_ID + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SmartAgriMarketAI/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            body = response.read().decode("utf-8", "ignore")
            return json.loads(body), ""
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return None, "Live Mandi API limit પર છે."
        if exc.code in (401, 403):
            return None, "Live Mandi API authentication/permission error."
        return None, f"Live Mandi HTTP error {exc.code}."
    except Exception:
        return None, "Live Mandi service હાલમાં ઉપલબ્ધ નથી."


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
def mandi(state: str = "Gujarat", district: str = "", commodity: str = ""):
    checked_at = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%m-%Y %H:%M")

    # Keep the legacy combined response too, but the Android client no longer
    # depends on this endpoint for news prices.
    try:
        news_prices = _news_market_prices(commodity, 20)
    except Exception:
        news_prices = []

    data, error = _mandi_api_get(state, district, commodity)
    records = []
    if isinstance(data, dict):
        records = data.get("records") or []

    live_available = bool(records)
    if live_available:
        message = "Live Mandi ભાવ મળ્યા. સાથે છેલ્લા 2 દિવસના સમાચાર આધારિત ભાવ પણ ઉપલબ્ધ છે."
    else:
        live_error = error or "Live Mandi APIમાંથી હાલ કોઈ record મળ્યો નથી."
        message = live_error + ("\n\nછેલ્લા 2 દિવસના સમાચાર આધારિત ભાવ બતાવ્યા છે." if news_prices else "\n\nછેલ્લા 2 દિવસમાં વિશ્વસનીય સમાચાર ભાવ મળ્યો નથી.")

    return {
        "ok": True,
        "live_available": live_available,
        "live_api_configured": bool(MANDI_API_KEY),
        "live_error": "" if live_available else (error or "no_records"),
        "source": "data.gov.in Live Mandi API" if live_available else "news",
        "checked_at": checked_at,
        "news_window_hours": _news_max_age_hours(),
        "records": records[:50],
        "news_prices": news_prices,
        "message": message,
    }
