```python
# -*- coding: utf-8 -*-
"""Smart Agri-Market AI HTTP backend.
Wraps the supplied Smart Agri-Market Agent so the Android app can call it.
"""
import os
import re
import logging
import base64
import importlib.util
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

APP_VERSION = "9.0 Android API Bridge"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"
logger = logging.getLogger("smart_agri_news")

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
NEWS_FETCH_TIMEOUT_SECONDS = 15


def _news_max_age_hours() -> int:
    try:
        value = int(os.getenv("NEWS_MAX_AGE_HOURS", str(NEWS_DEFAULT_MAX_AGE_HOURS)))
        return max(1, min(value, 168))
    except Exception:
        return NEWS_DEFAULT_MAX_AGE_HOURS


def _parse_news_date(value: str):
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    # A few publishers/feeds emit ISO-8601 dates rather than RFC-822 pubDate.
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _feed_queries(query: str):
    base = [
        "ગુજરાત ખેડૂત ખેતી કૃષિ",
        "ગુજરાત APMC બજાર ભાવ ખેડૂત",
        "ગુજરાત કૃષિ યોજના સહાય ખેડૂત",
        "ગુજરાત હવામાન વરસાદ ખેડૂતો",
    ]
    if query.strip():
        base.insert(0, query.strip())
    # Keep queries narrow enough that Google's recent-window search is useful.
    return list(dict.fromkeys(base))


def _fetch_news_items(query: str, limit: int = 20):
    queries = _feed_queries(query)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=_news_max_age_hours())
    india_tz = timezone(timedelta(hours=5, minutes=30))
    items = []
    seen = set()
    diagnostics = {
        "feeds_scanned": 0, "feed_items": 0, "dated_items": 0,
        "fresh_items": 0, "returned_items": 0, "fetch_errors": 0,
        "parse_errors": 0, "queries": [],
    }

    for search_query in queries:
        diagnostics["feeds_scanned"] += 1
        recent_query = f"{search_query} when:2d"
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
            "q": recent_query, "hl": "gu", "gl": "IN", "ceid": "IN:gu"
        })
        diagnostics["queries"].append(search_query)
        request = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Linux; Android 15) SmartAgriMarketAI/1.0"
        })
        try:
            with urllib.request.urlopen(request, timeout=NEWS_FETCH_TIMEOUT_SECONDS) as response:
                payload = response.read()
            root = ET.fromstring(payload)
        except Exception as exc:
            # Fallback: fetch the same query without Google's undocumented time operator;
            # the server-side timestamp filter below remains authoritative.
            logger.warning("News RSS recent query failed query=%r error=%s; trying plain RSS", search_query, exc)
            try:
                fallback_url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
                    "q": search_query, "hl": "gu", "gl": "IN", "ceid": "IN:gu"
                })
                fallback_request = urllib.request.Request(fallback_url, headers={
                    "User-Agent": "Mozilla/5.0 (Linux; Android 15) SmartAgriMarketAI/1.0"
                })
                with urllib.request.urlopen(fallback_request, timeout=NEWS_FETCH_TIMEOUT_SECONDS) as response:
                    payload = response.read()
                root = ET.fromstring(payload)
            except Exception as fallback_exc:
                diagnostics["fetch_errors"] += 1
                logger.warning("News RSS fallback failed query=%r error=%s", search_query, fallback_exc)
                continue

        for item in root.findall(".//item")[:100]:
            diagnostics["feed_items"] += 1
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date_text = (item.findtext("pubDate") or item.findtext("date") or "").strip()
            source_node = item.find("source")
            source = (source_node.text if source_node is not None else "") or ""
            source = source.strip()
            published = _parse_news_date(date_text)
            if not title or not link:
                continue
            if published is None:
                diagnostics["parse_errors"] += 1
                continue
            diagnostics["dated_items"] += 1
            if published < cutoff or published > now + timedelta(minutes=10):
                continue
            diagnostics["fresh_items"] += 1
            # Title + publisher is more stable than the Google redirect URL.
            key = re.sub(r"\s+", " ", title.casefold()) + "|" + source.casefold()
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "title": title,
                "link": link,
                "published_at": published.isoformat(),
                "published_text": published.astimezone(india_tz).strftime("%d-%m-%Y %I:%M %p"),
                "source": source or "સમાચાર સ્ત્રોત",
            })

    items.sort(key=lambda x: x["published_at"], reverse=True)
    final = items[:limit]
    diagnostics["returned_items"] = len(final)
    logger.info(
        "NEWS_DIAGNOSTICS feeds=%s feed_items=%s dated=%s fresh=%s returned=%s fetch_errors=%s parse_errors=%s",
        diagnostics["feeds_scanned"], diagnostics["feed_items"], diagnostics["dated_items"],
        diagnostics["fresh_items"], diagnostics["returned_items"], diagnostics["fetch_errors"],
        diagnostics["parse_errors"],
    )
    return final, diagnostics


@app.get("/api/v1/news")
def news(crop: str = ""):
    crop_name = crop.strip()
    query = f"{crop_name} ગુજરાત ખેડૂત ખેતી કૃષિ બજાર" if crop_name else "ગુજરાત ખેડૂત ખેતી કૃષિ બજાર"
    items, diagnostics = _fetch_news_items(query, 12)
    return {
        "ok": True,
        "crop": crop_name,
        "max_age_hours": _news_max_age_hours(),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "diagnostics": diagnostics,
        "items": items,
        "message": "આજના પ્રકાશિત થયેલા સમાચાર" if items else "હાલમાં તાજા સમાચાર મળ્યા નથી.",
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
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="ફોટો ખાલી છે.")
    client = openai_client()
    if client is None:
        return {
            "answer": "📷 ફોટો મળ્યો છે, પરંતુ ફોટો આધારિત AI વિશ્લેષણ સેવા હાલમાં ઉપલબ્ધ નથી. થોડા સમય પછી ફરી પ્રયાસ કરો. હાલમાં ફોટા પરથી નિશ્ચિત રોગનિદાન અથવા દવા/ડોઝ આપવો યોગ્ય નથી.",
            "mode": "agent_unavailable",
        }
    mime = image.content_type or "image/jpeg"
    b64 = base64.b64encode(data).decode("ascii")
    prompt = f"""
આ ખેતીના પાકનો ફોટો છે. પાક: {crop or 'અજ્ઞાત'}. સંદર્ભ: {context}.

ફોટો ખૂબ ધ્યાનથી જુઓ: પાનની ઉપર અને નીચેની સપાટી, ડાઘ, છિદ્રો, વળાંક, ચાંદી જેવા નિશાન, કીડા/ઈંડા/લાર્વા, જાળું, સૂકાવું, સડવું, રંગ બદલાવ અને અન્ય દેખાતા લક્ષણો અલગથી નોંધો.

ખેડૂતને ઉપયોગી થાય એવો વિગતવાર ગુજરાતી જવાબ આપો. જવાબ ઓછામાં ઓછા 8 સ્પષ્ટ વિભાગમાં આપો અને દરેક વિભાગમાં જરૂર મુજબ બુલેટ આપો:
1) 📷 ફોટામાં ખરેખર શું દેખાય છે — માત્ર દેખાતી બાબતો, અનુમાન નહીં.
2) 🔎 સૌથી સંભવિત સમસ્યા — રોગ/જીવાત/પોષણ/હવામાન વગેરેમાંથી શું લાગે છે અને કેમ. 1 થી 3 સંભાવનાઓ આપો અને વિશ્વાસનું સ્તર જણાવો.
3) 🌱 પાકને થતી સંભવિત અસર — પાન, વૃદ્ધિ, ફૂલ/ફળ અને ઉપજ પર શું અસર થઈ શકે.
4) 🐛 કઈ જીવાત અથવા રોગની વધુ તપાસ કરવી — ઓળખ માટે પાન/ડાંઠ/ફળના કયા ભાગો ફરી જોવાના.
5) 💊 દવા/નિયંત્રણ — જો ફોટાના લક્ષણોથી કોઈ ચોક્કસ જીવાત/રોગની સંભાવના પૂરતી મજબૂત હોય તો યોગ્ય pesticide/દવા માટે સક્રિય ઘટક (active ingredient), દવાનો પ્રકાર અને સામાન્ય ઉપયોગનો હેતુ જણાવો. શક્ય હોય તો ભારતમાં નોંધાયેલ લેબલ/સ્થાનિક કૃષિ ભલામણ ચકાસવાની જરૂરિયાત લખો. ચોક્કસ બ્રાન્ડને અનિવાર્ય ન બનાવો. ખોટી ઓળખ હોય તો દવા ન છાંટવાની ચેતવણી આપો.
6) 🧑‍🌾 હમણાં શું કરવું — IPM, અસરગ્રસ્ત પાન/ભાગ દૂર કરવો, સફાઈ, સિંચાઈ/નાઇટ્રોજન જેવી બાબતોમાં યોગ્ય પગલાં.
7) ⚠️ સલામતી — દવા વાપરવી પડે તો લેબલ મુજબ માત્રા, PPE, waiting period અને સ્થાનિક નિયમોનું પાલન કરવાની સ્પષ્ટ સલાહ. ફોટાથી ખાતરી ન હોય તો ડોઝ ન બનાવો.
8) 📸 આગળની તપાસ — વધુ ચોક્કસ જવાબ માટે કયો નજીકનો ફોટો, પાનની પાછળની બાજુ, જીવાતનો ફોટો, પાકની ઉંમર અને નુકસાનનું પ્રમાણ જોઈએ.

ફક્ત 1-2 લીટીનો જવાબ ન આપો. સામાન્ય રીતે 500-900 ગુજરાતી શબ્દો જેટલો વિગતવાર જવાબ આપો, પરંતુ બિનજરૂરી વાતો ન ઉમેરો. ફોટામાં જે દેખાતું નથી તે જોયું હોવાનું ન કહો. ફોટા પરથી નિશ્ચિત રોગનિદાન ન કરો. ચોક્કસ pesticide dose માત્ર વિશ્વસનીય રીતે ઓળખાય અને યોગ્ય નોંધાયેલ ભલામણ ઉપલબ્ધ હોય ત્યારે જ આપો; નહીં તો સક્રિય ઘટક/નિયંત્રણ વિકલ્પ જણાવો અને સ્થાનિક કૃષિ નિષ્ણાત/KVK પાસેથી ડોઝ ચકાસવા કહો.
"""
    try:
        response = client.responses.create(
            model=MODEL,
            instructions=SYSTEM,
            max_output_tokens=3000,
            input=[{"role": "user", "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
            ]}],
        )
        return {"answer": response.output_text, "mode": "openai_vision", "model": MODEL}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Vision AI error: {exc}")
```
