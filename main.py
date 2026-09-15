# -*- coding: utf-8 -*-
"""Smart Agri-Market AI HTTP backend with optional Groq/OpenAI AI providers."""
import os
import base64
import importlib.util
from typing import Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

APP_VERSION = "10.0 Android API Bridge - Groq"
GROQ_TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-20b").strip() or "openai/gpt-oss-20b"
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b").strip() or "qwen/qwen3.6-27b"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"

app = FastAPI(title="Smart Agri Market AI Backend", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

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
    "જવાબ સરળ, વ્યવહારુ અને પાક/ખેડૂતના સંદર્ભ મુજબ ગુજરાતી ભાષામાં આપો. "
    "પાક, સિંચાઈ, પોષણ, રોગ-જીવાત, હવામાન અને બજાર અંગે માર્ગદર્શન આપો. "
    "ચોક્કસ pesticide dose અથવા નિશ્ચિત રોગનિદાન માટે સ્થાનિક કૃષિ નિષ્ણાત/KVK/લેબ ચકાસણી જરૂરી હોવાનું જણાવો."
)

class Ask(BaseModel):
    question: str
    context: dict | None = None


def groq_client():
    key = os.getenv("GROQ_API_KEY", "").strip()
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1") if key else None


def openai_client():
    key = os.getenv("OPENAI_API_KEY", "").strip()
    return OpenAI(api_key=key) if key else None


def norm(text: str) -> str:
    return " ".join((text or "").strip().lower().replace("-", " ").split())


def rule_based_answer(question: str, context: dict | None) -> str:
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


def ai_text_answer(question: str, context: dict | None) -> tuple[str, str, str]:
    """Prefer Groq, then optional OpenAI, then the supplied local agent."""
    ctx = context or {}
    prompt = f"ખેડૂત પ્રશ્ન: {question.strip()}\nખેડૂત સંદર્ભ: {ctx}"

    client = groq_client()
    if client:
        try:
            response = client.responses.create(
                model=GROQ_TEXT_MODEL,
                instructions=SYSTEM,
                input=prompt,
            )
            answer = (response.output_text or "").strip()
            if answer:
                return answer, "groq", GROQ_TEXT_MODEL
        except Exception as exc:
            print(f"Groq text warning: {exc}")

    client = openai_client()
    if client:
        try:
            response = client.responses.create(model=OPENAI_MODEL, instructions=SYSTEM, input=prompt)
            answer = (response.output_text or "").strip()
            if answer:
                return answer, "openai", OPENAI_MODEL
        except Exception as exc:
            print(f"OpenAI text warning: {exc}")

    return rule_based_answer(question, context), "agent_fallback", "local"


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
        "openai_configured": bool(os.getenv("OPENAI_API_KEY", "").strip()),
        "text_model": GROQ_TEXT_MODEL,
        "vision_model": GROQ_VISION_MODEL,
    }


@app.post("/api/v1/ai/ask")
def ask(req: Ask):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="પ્રશ્ન ખાલી છે.")
    answer, mode, model = ai_text_answer(req.question, req.context)
    return {"answer": answer, "mode": mode, "model": model}


@app.post("/api/v1/ai/diagnose")
async def diagnose(image: UploadFile = File(...), crop: str = Form(""), context: str = Form("")):
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="ફોટો ખાલી છે.")

    mime = image.content_type or "image/jpeg"
    b64 = base64.b64encode(data).decode("ascii")
    prompt = (
        f"આ ખેતીના પાકનો ફોટો છે. પાક: {crop or 'અજ્ઞાત'}. સંદર્ભ: {context}. "
        "ફોટામાં દેખાતા લક્ષણોનું નિરીક્ષણ કરો. 1-3 સંભવિત કારણો, દેખાતા લક્ષણો અને તરત કરી શકાય તેવી IPM/સલામતી સલાહ આપો. "
        "ફોટા પરથી નિશ્ચિત નિદાન ન કરો અને ચોક્કસ pesticide dose ન આપો. જવાબ સરળ ગુજરાતી ભાષામાં આપો."
    )

    client = groq_client()
    if client:
        try:
            response = client.responses.create(
                model=GROQ_VISION_MODEL,
                instructions=SYSTEM,
                input=[{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
                    ],
                }],
            )
            answer = (response.output_text or "").strip()
            if answer:
                return {"answer": answer, "mode": "groq_vision", "model": GROQ_VISION_MODEL}
        except Exception as exc:
            print(f"Groq vision warning: {exc}")

    client = openai_client()
    if client:
        try:
            response = client.responses.create(
                model=OPENAI_MODEL,
                instructions=SYSTEM,
                input=[{"role": "user", "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
                ]}],
            )
            return {"answer": response.output_text, "mode": "openai_vision", "model": OPENAI_MODEL}
        except Exception as exc:
            print(f"OpenAI vision warning: {exc}")

    return {
        "answer": "📷 ફોટો મળ્યો છે. હાલમાં Vision AI service ઉપલબ્ધ નથી; ફોટા પરથી નિશ્ચિત રોગનિદાન અથવા દવા/ડોઝ આપવો યોગ્ય નથી. કૃપા કરીને પાકનું નામ, ઉંમર અને લક્ષણો લખો.",
        "mode": "agent_unavailable",
    }
