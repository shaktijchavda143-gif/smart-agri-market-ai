# -*- coding: utf-8 -*-
"""Smart Agri-Market AI HTTP backend.
Wraps the supplied Smart Agri-Market Agent so the Android app can call it.
"""

import os
import base64
import importlib.util
import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from google import genai
from google.genai import types


APP_VERSION = "9.0 Android API Bridge"


# ============================================================
# GROQ TEXT MODEL
# ============================================================

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
).strip() or "openai/gpt-oss-20b"


# ============================================================
# GEMINI VISION MODEL
# ============================================================

VISION_MODEL = os.getenv(
    "VISION_MODEL",
    "gemini-2.5-flash"
).strip() or "gemini-2.5-flash"


app = FastAPI(
    title="Smart Agri Market AI Backend",
    version=APP_VERSION
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# LOAD SUPPLIED SMART AGRI AGENT
# ============================================================

_agent = None

try:
    _path = os.path.join(
        os.path.dirname(__file__),
        "smart_agri_agent.py"
    )

    _spec = importlib.util.spec_from_file_location(
        "smart_agri_agent",
        _path
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
    "જવાબ સરળ, વ્યવહારુ અને પાક/ખેડૂતના સંદર્ભ મુજબ આપો. "
    "પાક, સિંચાઈ, પોષણ, રોગ-જીવાત, હવામાન અને બજાર અંગે માર્ગદર્શન આપો. "
    "ચોક્કસ pesticide dose અથવા નિશ્ચિત રોગનિદાન માટે સ્થાનિક કૃષિ નિષ્ણાત/KVK/લેબ ચકાસણી જરૂરી હોવાનું જણાવો."
)


# ============================================================
# REQUEST MODEL
# ============================================================

class Ask(BaseModel):
    question: str
    context: dict | None = None


# ============================================================
# GROQ TEXT AI CLIENT
# ============================================================

def groq_client():
    key = os.getenv("GROQ_API_KEY", "").strip()

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
    key = os.getenv("GEMINI_API_KEY", "").strip()

    return genai.Client(api_key=key) if key else None


# ============================================================
# NORMALIZE TEXT
# ============================================================

def norm(text: str) -> str:
    return " ".join(
        (text or "").strip().lower().replace("-", " ").split()
    )


# ============================================================
# RULE-BASED ANSWER
# ============================================================

def rule_based_answer(question: str, context: dict | None) -> str:
    """Use the supplied agent's crop knowledge when needed."""

    q = norm(question)
    ctx = context or {}
    selected = ctx.get("selected_crop") or {}

    crop = str(
        selected.get("name") or ""
    ).strip()

    if not crop and _agent:
        aliases = getattr(
            _agent,
            "ROMAN_ALIASES",
            {}
        )

        crops = getattr(
            _agent,
            "CROPS",
            {}
        )

        for key, name in crops.items():
            if norm(name) in q or norm(key) == q:
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

    profile = data.get(
        crop,
        {}
    ) if crop else {}

    if any(
        x in q
        for x in (
            "સિંચાઈ",
            "પા છણી",
            "પિયત",
            "irrigation",
            "water"
        )
    ):
        return (
            f"💧 {crop or 'પાક'} માટે સિંચાઈ સલાહ:\n"
            f"{profile.get('પાણી', 'પાકની અવસ્થા, જમીનનો ભેજ અને વરસાદ પ્રમાણે સિંચાઈ કરો; પાણી ભરાવું ટાળો.')}\n"
            "છેલ્લો વરસાદ, જમીનનો પ્રકાર અને પાકની હાલની અવસ્થા જણાવશો તો સલાહ વધુ ચોક્કસ કરી શકું."
        )

    if any(
        x in q
        for x in (
            "ખાતર",
            "પોષણ",
            "fertilizer",
            "npk"
        )
    ):
        return (
            f"🧪 {crop or 'પાક'} માટે પોષણ:\n"
            "માટી પરીક્ષણ આધારિત N-P-K અને સૂક્ષ્મ તત્ત્વો નક્કી કરો. "
            "પાકની અવસ્થા પ્રમાણે ખાતર વહેંચીને આપવું વધુ યોગ્ય રહે છે. "
            "માટી રિપોર્ટ વગર ચોક્કસ ડોઝ નક્કી ન કરવો."
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
            "pest"
        )
    ):
        disease = getattr(
            _agent,
            "_DISEASES",
            {}
        ).get(
            crop,
            []
        ) if _agent else []

        extra = "\n".join(
            f"• {x}"
            for x in disease[:3]
        )

        return (
            f"🔎 {crop or 'પાક'} માટે રોગ/જીવાત તપાસ:\n"
            f"{extra or 'પાન, ડાંઠ, મૂળ અને ફળનું નજીકથી નિરીક્ષણ કરો અને પાણી/પોષણની સ્થિતિ તપાસો.'}\n"
            "ફોટો, પાકની ઉંમર અને નુકસાનનું પ્રમાણ આપશો તો વધુ મદદ કરી શકું. "
            "દવા/માત્રા સ્થાનિક નોંધાયેલ ભલામણ મુજબ જ નક્કી કરો."
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
        "🤖 ખેડૂત સહાયક: પ્રશ્નનો વધુ ચોક્કસ જવાબ આપવા પાકનું નામ, "
        "પાકની ઉંમર/વાવણી તારીખ, જમીનનો પ્રકાર, છેલ્લું સિંચાઈ/વરસાદ "
        "અને સમસ્યાના લક્ષણો લખો. ફોટો હોય તો મોકલી શકો."
    )


# ============================================================
# LIVE GUJARAT WEATHER NEWS
# ============================================================

NEWS_FEEDS = [
    (
        "🌧️ ગુજરાત મોસમ વિભાગ / IMD",
        "IMD Gujarat weather",
        "IMD Gujarat"
    ),
    (
        "☀️ આંબાલાલ પટેલ",
        "આંબાલાલ પટેલ હવામાન ગુજરાત",
        "આંબાલાલ પટેલ"
    ),
    (
        "🌦️ પરેશ ગૌસ્વામી",
        "પરેશ ગૌસ્વામી હવામાન ગુજરાત",
        "પરેશ ગૌસ્વામી"
    ),
    (
        "📰 અન્ય મહત્વપૂર્ણ ગુજરાત હવામાન સમાચાર",
        "ગુજરાત હવામાન વરસાદ આગાહી",
        "ગુજરાત હવામાન સમાચાર"
    ),
]


def _clean_html_text(value: str) -> str:
    text = html.unescape(
        re.sub(
            r"<[^>]+>",
            " ",
            value or ""
        )
    )

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def _rss_datetime(value: str) -> str:
    if not value:
        return "સમય ઉપલબ્ધ નથી"

    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(value)

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone().strftime(
            "%d-%m-%Y %H:%M"
        )

    except Exception:
        return value[:32]


def _fetch_news_feed(
    category: str,
    query: str,
    fallback_source: str
):
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

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "SmartAgriMarketAI/1.0"
        }
    )

    with urllib.request.urlopen(
        req,
        timeout=8
    ) as response:

        root = ET.fromstring(
            response.read()
        )

    items = []

    for item in root.findall(
        "./channel/item"
    )[:5]:

        title = _clean_html_text(
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

        description = _clean_html_text(
            item.findtext(
                "description",
                ""
            )
        )

        source_el = item.find(
            "source"
        )

        source = (
            _clean_html_text(
                source_el.text
                if source_el is not None
                else ""
            )
            or fallback_source
        )

        pub = _rss_datetime(
            item.findtext(
                "pubDate",
                ""
            )
        )

        if not title or not link:
            continue

        summary = description

        if (
            not summary
            or summary.lower() == title.lower()
        ):
            summary = (
                f"{source} તરફથી ગુજરાતના "
                "હવામાન અંગેનો તાજો અહેવાલ."
            )

        if len(summary) > 280:
            summary = (
                summary[:277]
                .rsplit(" ", 1)[0]
                + "..."
            )

        items.append(
            {
                "category": category,
                "headline": title,
                "summary": summary,
                "published": pub,
                "source": source,
                "url": link,
            }
        )

    return items


# ============================================================
# WEATHER NEWS ENDPOINT
# ============================================================

@app.get("/api/v1/weather/news")
def weather_news():

    items = []
    errors = []

    for category, query, fallback in NEWS_FEEDS:

        try:
            items.extend(
                _fetch_news_feed(
                    category,
                    query,
                    fallback
                )[:4]
            )

        except Exception as exc:
            errors.append(
                f"{category}: {exc}"
            )

    # De-duplicate headlines and keep a balanced feed
    # from all requested categories.
    seen = set()
    unique = []

    for item in items:

        key = norm(
            item["headline"]
        )

        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    unique.sort(
        key=lambda x: x.get(
            "published",
            ""
        ),
        reverse=True
    )

    return {
        "ok": True,
        "updated_at": datetime.now().astimezone().strftime(
            "%d-%m-%Y %H:%M"
        ),
        "items": unique[:16],
        "live": bool(unique),
        "source": "Google News RSS / original publishers",
        "errors": errors[:4],
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "ok": True,
        "service": "smart-agri-ai",
        "version": APP_VERSION
    }


# ============================================================
# HEALTH CHECK
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
                ""
            ).strip()
        ),

        "gemini_configured": bool(
            os.getenv(
                "GEMINI_API_KEY",
                ""
            ).strip()
        ),

        "text_provider": "groq",
        "text_model": GROQ_MODEL,

        "vision_provider": "gemini",
        "vision_model": VISION_MODEL,
    }


# ============================================================
# GROQ TEXT AI
# ============================================================

@app.post("/api/v1/ai/ask")
def ask(req: Ask):

    if not req.question.strip():
        raise HTTPException(
            status_code=400,
            detail="પ્રશ્ન ખાલી છે."
        )

    client = groq_client()

    if client is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Groq AI configured નથી. "
                "Render Environment Variables માં "
                "GROQ_API_KEY સેટ કરો."
            )
        )

    ctx = req.context or {}

    prompt = (
        f"ખેડૂત પ્રશ્ન: {req.question.strip()}\n"
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
            response.choices[0].message.content
            or ""
        ).strip()

        if not answer:
            raise HTTPException(
                status_code=502,
                detail="Groq તરફથી ખાલી જવાબ મળ્યો."
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
            detail=f"Groq AI error: {exc}"
        )


# ============================================================
# GEMINI VISION AI
# ============================================================

@app.post("/api/v1/ai/diagnose")
async def diagnose(
    image: UploadFile = File(...),
    crop: str = Form(""),
    context: str = Form("")
):

    data = await image.read()

    if not data:
        raise HTTPException(
            status_code=400,
            detail="ફોટો ખાલી છે."
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

    prompt = (
        f"આ ખેતીના પાકનો ફોટો છે. "
        f"પાક: {crop or 'અજ્ઞાત'}. "
        f"સંદર્ભ: {context}.\n"

        "ફોટામાં દેખાતા લક્ષણોનું ધ્યાનપૂર્વક "
        "નિરીક્ષણ કરો. જવાબ ગુજરાતી ભાષામાં આપો.\n"

        "આ ક્રમમાં જવાબ આપો:\n"

        "1) દેખાતા લક્ષણો\n"

        "2) 1-3 સંભવિત કારણો અથવા રોગ/જીવાત\n"

        "3) તરત કરી શકાય તેવી IPM/સલામતી સલાહ\n"

        "4) ક્યારે સ્થાનિક કૃષિ નિષ્ણાત/KVK/લેબની "
        "ચકાસણી લેવી\n"

        "ફોટા પરથી નિશ્ચિત નિદાન ન કરો અને "
        "ચોક્કસ pesticide dose, concentration "
        "અથવા brand ન આપો. "

        "જો ફોટો અસ્પષ્ટ હોય અથવા પાક/લક્ષણો "
        "પૂરતા દેખાતા ન હોય તો તે સ્પષ્ટ જણાવો."
    )

    try:

        response = client.models.generate_content(
            model=VISION_MODEL,
            contents=[
                types.Part.from_bytes(
                    data=data,
                    mime_type=mime
                ),
                prompt,
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                temperature=0.2,
                max_output_tokens=700,
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
            detail=f"Vision AI error: {exc}"
        )
