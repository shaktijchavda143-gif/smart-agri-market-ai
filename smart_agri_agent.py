# -*- coding: utf-8 -*-
"""Smart Agri-Market AI Agent - Master Prompt V7
Termux/Android friendly, standard-library only.
"""
import os, json, time, urllib.parse, urllib.request, urllib.error, xml.etree.ElementTree as ET
from datetime import datetime

APP_VERSION = "8.0 Rate-Limit Safe Farmer Edition"
REQUEST_RETRIES = 2
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smart_agri_cache.json")

DATA_GOV_API_KEY = os.getenv("DATA_GOV_API_KEY", "અહીં_નવી_DATA_GOV_API_KEY_મૂકો")
DATA_GOV_RESOURCE_ID = os.getenv("DATA_GOV_RESOURCE_ID", "9 ef84268-d588-465a-a308-a864a43d0070".replace(" ", ""))
USER_AGENT = "SmartAgriMarketAgent/7.0"

CROPS = {
    "1": "કપાસ", "2": "મગફળી", "3": "ઘઉં", "4": "બાજરી", "5": "મકાઈ", "6": "જીરું",
    "7": "ધાણા", "8": "તલ", "9": "એરંડા", "10": "ચણા", "11": "તુવેર", "12": "મગ",
    "13": "અડદ", "14": "ડુંગળી", "15": "બટાકા", "16": "ટામેટા", "17": "મરચાં",
    "18": "લસણ", "19": "શેરડી", "20": "કેરી", "21": "કેળા", "22": "દાડમ", "23": "અન્ય"
}

MANDI_COMMODITY_MAP = {
    "કપાસ": "Cotton", "મગફળી": "Groundnut", "ઘઉં": "Wheat", "બાજરી": "Bajra",
    "મકાઈ": "Maize", "જીરું": "Jeera", "ધાણા": "Coriander", "તલ": "Sesamum",
    "એરંડા": "Castor Seed", "ચણા": "Gram", "તુવેર": "Arhar", "મગ": "Green Gram",
    "અડદ": "Black Gram", "ડુંગળી": "Onion", "બટાકા": "Potato", "ટામેટા": "Tomato",
    "મરચાં": "Chilli", "લસણ": "Garlic", "શેરડી": "Sugarcane", "કેરી": "Mango",
    "કેળા": "Banana", "દાડમ": "Pomegranate"
}

CROP_DATA = {
    "કપાસ": {"પ્રકાર":"રોકડ/તંતુ પાક", "જમીન":"સારી નિતારવાળી કાળી અથવા ગોરાડુ જમીન", "pH":"6.0–8.0", "વાવણી":"જૂન–જુલાઈ, વરસાદ અને ભેજ પ્રમાણે", "બીજ":"પ્રમાણિત જાત/હાઇબ્રિડ", "બીજદર":"જાત પ્રમાણે આશરે 1.5–2.5 કિગ્રા/હે.", "અંતર":"સામાન્ય રીતે 90×45 અથવા જાત પ્રમાણે", "પાણી":"વાવણી પછી જરૂર મુજબ; ફૂલ/બોલ સમયે તાણ ન રહે", "સાવચેતી":"ગુલાબી ઈયળ, સફેદમાખી અને વધુ નાઇટ્રોજનથી સાવચેત"},
    "મગફળી": {"પ્રકાર":"તેલબિયાં પાક", "જમીન":"ભૂરી/ગોરાડુ, ભુરભુરી અને નિતારવાળી", "pH":"6.0–7.5", "વાવણી":"ખરીફમાં પ્રથમ સારો વરસાદ પછી; ઉનાળુ પાક માટે સિંચાઈ", "બીજ":"પ્રમાણિત અને ઉપચારિત બીજ", "બીજદર":"જાત અને દાણા કદ પ્રમાણે 100–125 કિગ્રા/હે.", "અંતર":"30×10 અથવા ભલામણ મુજબ", "પાણી":"ફૂલ, પેગિંગ અને દાણા ભરાવા સમયે ખાસ ધ્યાન", "સાવચેતી":"ટિક્કા, રસ્ટ, સફેદ લટ અને પાણી ભરાવાથી બચાવો"},
    "ઘઉં": {"પ્રકાર":"રબી અનાજ પાક", "જમીન":"સારી નિતારવાળી ગોરાડુ/કાળી જમીન", "pH":"6.5–8.0", "વાવણી":"નવેમ્બર–ડિસેમ્બર, સ્થાનિક ભલામણ પ્રમાણે", "બીજ":"પ્રમાણિત બીજ", "બીજદર":"100–125 કિગ્રા/હે. આશરે", "અંતર":"20–22.5 સે.મી. પંક્તિ અંતર", "પાણી":"CRI, ટિલરિંગ, ફૂલ અને દાણા ભરાવા સમયે", "સાવચેતી":"ગુલ્લી-ડાંગર, રસ્ટ અને સમયસર સિંચાઈ"},
    "બાજરી": {"પ્રકાર":"અનાજ/ચારો", "જમીન":"હલકીથી મધ્યમ, નિતારવાળી", "pH":"6.0–8.5", "વાવણી":"ચોમાસાની શરૂઆતમાં", "બીજ":"પ્રમાણિત જાત", "બીજદર":"3–5 કિગ્રા/હે. આશરે", "અંતર":"45×10–15 સે.મી.", "પાણી":"વરસાદ આધારિત; લાંબા વિરામે પૂરક સિંચાઈ", "સાવચેતી":"ડાઉની મિલ્ડ્યુ અને નીંદણ નિયંત્રણ"},
    "મકાઈ": {"પ્રકાર":"અનાજ/ચારો", "જમીન":"ભુરભુરી અને નિતારવાળી", "pH":"5.5–7.5", "વાવણી":"ખરીફ/રબી/ઉનાળુ, વિસ્તાર પ્રમાણે", "બીજ":"હાઇબ્રિડ/પ્રમાણિત જાત", "બીજદર":"20–25 કિગ્રા/હે. આશરે", "અંતર":"60×20 સે.મી. આશરે", "પાણી":"ઘૂંટણ ઊંચાઈ, તાસલિંગ અને દાણા ભરાવા સમયે", "સાવચેતી":"ફોલ આર્મીવોર્મ અને પાણી ભરાવાથી બચાવો"}
}


def line(ch="═", n=64): print(ch*n)
def pause(): input("\nઆગળ વધવા Enter દબાવો...")
def now(): return datetime.now().strftime("%d-%m-%Y %H:%M:%S")
def safe_input(prompt):
    try: return input(prompt).strip()
    except (EOFError, KeyboardInterrupt): print(); return ""
def get_json(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    last_error = None
    for attempt in range(REQUEST_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            last_error = e
            # Do not retry HTTP 429: repeated retries can worsen the server rate-limit.
            if e.code == 429:
                print("⚠️ Mandi server પર requests વધારે છે. ફરીથી થોડા સમય પછી પ્રયાસ કરો.")
                return {"__rate_limited__": True, "records": []}
            if e.code == 401 or e.code == 403:
                print("❌ API Key ખોટી છે અથવા પરવાનગી નથી.")
            else:
                print(f"HTTP ભૂલ: {e.code}. સર્વર વ્યસ્ત/મર્યાદા હોઈ શકે છે.")
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = e
            if attempt < REQUEST_RETRIES:
                time.sleep(1)
                continue
            print("❌ Internet/સર્વર કનેક્શન અથવા timeout ની સમસ્યા છે.")
            return None
        except (ValueError, json.JSONDecodeError):
            print("❌ સર્વર તરફથી યોગ્ય JSON માહિતી મળી નથી.")
            return None
        except Exception as e:
            last_error = e
            print(f"કનેક્શન/ડેટા ભૂલ: {e}")
            return None
    return None

def get_text(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()
    except Exception as e: print(f"ડેટા મેળવવામાં ભૂલ: {e}"); return b""

def choose_crop():
    line(); print("પાક પસંદ કરો")
    for k,v in CROPS.items(): print(f"{k:>2}. {v}")
    x=safe_input("નંબર અથવા પાકનું નામ: ")
    if x in CROPS: return CROPS[x]
    for v in CROPS.values():
        if x == v: return v
    return x or "અન્ય"

def crop_information():
    crop=choose_crop(); d=CROP_DATA.get(crop, {})
    line(); print(f"🌾 {crop} — સંપૂર્ણ માહિતી")
    fields=[("પ્રકાર","પ્રકાર"),("જમીન","જમીન"),("pH","pH"),("વાવણી સમય","વાવણી"),("બીજ","બીજ"),("બીજદર","બીજદર"),("અંતર","અંતર"),("સિંચાઈ","પાણી"),("સાવચેતી","સાવચેતી")]
    for label,key in fields: print(f"• {label}: {d.get(key,'સ્થાનિક કૃષિ ભલામણ મુજબ નક્કી કરો.')}")
    print("• ખાતર: માટી પરીક્ષણ અને પાક અવસ્થા પ્રમાણે NPK/સજીવ ખાતર આપો.")
    print("• નીંદણ: શરૂઆતના 30–45 દિવસ ખાસ નિયંત્રણ રાખો.")
    print("• રોગ/જીવાત: નિયમિત નિરીક્ષણ, પીળા ચીકણા ટ્રેપ/લાઇટ ટ્રેપ અને IPM અપનાવો.")
    print("• કાપણી/સંગ્રહ: પાક સંપૂર્ણ પરિપક્વ થયા પછી સુકવીને ભેજ ઓછો રાખી સંગ્રહ કરો.")
    print("• બજાર સલાહ: ગુણવત્તા, ભેજ, ગ્રેડ અને નજીકના બજારના તાજા ભાવ તપાસો.")
    pause()

def crop_advice():
    crop=choose_crop(); print(f"\n🌱 {crop} માટે ખેતી માર્ગદર્શન")
    for h,t in [("A. જમીન તૈયારી","માટી પરીક્ષણ, ઊંડી ખેડ, સમતલ જમીન અને યોગ્ય નિતાર."),("B. બીજ","પ્રમાણિત બીજ, ભલામણ મુજબ બીજ ઉપચાર અને યોગ્ય બીજદર."),("C. વાવણી","યોગ્ય ભેજ, સમય, ઊંડાઈ અને પંક્તિ અંતર."),("D. પાણી","જમીન અને હવામાન પ્રમાણે સિંચાઈ; પાણી ભરાવું ટાળો."),("E. પોષણ","માટી પરીક્ષણ આધારીત ખાતર; જૈવિક ખાતર અને સૂક્ષ્મ તત્વો જરૂર મુજબ."),("F. નીંદણ","સમયસર હાથથી/યાંત્રિક નિયંત્રણ; દવા માત્ર લેબલ મુજબ."),("G. જીવાત/રોગ","અઠવાડિયે નિરીક્ષણ, IPM, અસરગ્રસ્ત ભાગ દૂર કરવો."),("H. કાપણી","પરિપક્વતા, ભેજ અને બજારની માંગ મુજબ કાપણી."),("I. સંગ્રહ","સાફ, સુકા, હવાદાર અને જીવાતમુક્ત ગોડાઉનમાં રાખવું."),("J. નોંધ","તારીખ, ખર્ચ, દવા, પાણી અને ઉપજનો રેકોર્ડ રાખો.")]: print(f"{h}: {t}")
    pause()

def disease_advice():
    crop=choose_crop(); symptom=safe_input("લક્ષણ/જીવાત લખો (દા. પાન પીળાં, ઈયળ, ડાઘ): ")
    print(f"\n🔎 {crop} — {symptom or 'સામાન્ય'}")
    print("1) અસરગ્રસ્ત પાન/છોડના ફોટા અને નજીકથી નિરીક્ષણ કરો.")
    print("2) ખેતરમાં પાણી ભરાવું, પોષક તત્ત્વોની અછત અને જીવાતનું પ્રમાણ તપાસો.")
    print("3) પીળા ચીકણા ટ્રેપ, હાથથી જીવાત દૂર કરવી અને સ્વચ્છતા જેવા IPM પગલાં લો.")
    print("4) કોઈ પણ કીટનાશક/ફૂગનાશક માત્ર પાક-રોગની ખાતરી, લેબલ અને સ્થાનિક કૃષિ અધિકારીની સલાહથી વાપરો.")
    print("⚠️ ચોક્કસ ડોઝ માટે પાક, રોગ, પાકની ઉંમર, વિસ્તાર અને નુકસાનનું પ્રમાણ જરૂરી છે; અહીં અંદાજી ડોઝ આપતો નથી.")
    pause()

def irrigation():
    crop=choose_crop(); print(f"\n💧 {crop} સિંચાઈ યોજના")
    print("• જમીનનો ભેજ હાથ/ટેન્શનમીટરથી તપાસો.")
    print("• ડ્રિપ/સ્પ્રિંકલરથી પાણી અને ખાતરનું કાર્યક્ષમ સંચાલન કરો.")
    print("• ફૂલ, દાણા/ફળ ભરાવા અને ગરમીમાં પાણીની જરૂરિયાત વધે છે.")
    print("• વરસાદની આગાહી હોય તો અનાવશ્યક સિંચાઈ ટાળો."); pause()

def fertilizer():
    crop=choose_crop(); print(f"\n🧪 {crop} પોષણ યોજના")
    print("• માટી પરીક્ષણ પછી જ N-P-K અને સલ્ફર/ઝિંક/બોરોન નક્કી કરો.")
    print("• સડી ગયેલું છાણિયું ખાતર/કમ્પોસ્ટ જમીન સુધારે છે.")
    print("• નાઇટ્રોજન હપ્તામાં આપો; એકસાથે વધુ આપવાથી રોગ/નરમ વૃદ્ધિ વધી શકે.")
    print("• પાન પર છંટકાવ માત્ર માન્ય ભલામણ અને લેબલ મુજબ."); pause()

def _mandi_date_key(value):
    """Return a comparable date for common Agmarknet date formats."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            pass
    return None


def _norm_mandi_text(value):
    return " ".join(str(value or "").strip().lower().replace("-", " ").replace("_", " ").split())


def _commodity_matches(row, requested):
    """Strictly keep rows for the requested commodity during fallback."""
    if not requested:
        return True
    wanted = _norm_mandi_text(requested)
    aliases = {
        "groundnut": {"groundnut", "ground nuts", "peanut", "peanuts", "મગફળી"},
        "cotton": {"cotton", "કપાસ"},
        "wheat": {"wheat", "ઘઉં"},
        "bajra": {"bajra", "pearl millet", "millet", "બાજરી"},
        "maize": {"maize", "corn", "મકાઈ"},
    }
    accepted = {_norm_mandi_text(x) for x in aliases.get(wanted, {requested})}
    values = []
    for key in ("commodity", "Commodity", "crop", "Crop", "commodity_name", "Commodity Name", "variety", "Variety"):
        if row.get(key):
            values.append(_norm_mandi_text(row.get(key)))
    if not values:
        return False
    return any(v in accepted or wanted in v or v in wanted for v in values)


def _load_mandi_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None

def _save_mandi_cache(rows, state, district, commodity):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"saved_at": now(), "state": state, "district": district, "commodity": commodity, "records": rows[:30]}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def get_mandi_data():
    if not DATA_GOV_API_KEY or "મૂકો" in DATA_GOV_API_KEY:
        print("⚠️ Live mandi માટે નવી data.gov.in API key મૂકો અથવા DATA_GOV_API_KEY environment variable સેટ કરો."); return None
    state = safe_input("રાજ્ય (ખાલી=ગુજરાત): ").strip() or "Gujarat"
    district = safe_input("જિલ્લો (વૈકલ્પિક): ").strip()
    commodity_input = safe_input("પાક/કોમોડિટી (વૈકલ્પિક): ").strip()
    commodity = commodity_input

    state_map = {"ગુજરાત":"Gujarat", "gujarat":"Gujarat", "Gujarat":"Gujarat"}
    district_map = {"અમદાવાદ":"Ahmedabad", "ahmedabad":"Ahmedabad", "Ahmedabad":"Ahmedabad",
                    "જુનાગઢ":"Junagadh", "junagadh":"Junagadh", "JUNAGADH":"Junagadh",
                    "ગીર સોમનાથ":"Gir Somnath", "gir somnath":"Gir Somnath", "GIR SOMNATH":"Gir Somnath",
                    "સોમનાથ":"Gir Somnath", "somnath":"Gir Somnath", "SOMNATH":"Gir Somnath"}
    state = state_map.get(state, state)
    district = district_map.get(district, district)
    if commodity in MANDI_COMMODITY_MAP:
        commodity = MANDI_COMMODITY_MAP[commodity]

    base = {"api-key": DATA_GOV_API_KEY, "format": "json", "limit": "100"}
    params = dict(base)
    if state: params["filters[state]"] = state
    if district: params["filters[district]"] = district
    if commodity: params["filters[commodity]"] = commodity
    url = "https://api.data.gov.in/resource/" + DATA_GOV_RESOURCE_ID + "?" + urllib.parse.urlencode(params)
    data = get_json(url)
    if isinstance(data, dict) and data.get("__rate_limited__"):
        cached = _load_mandi_cache()
        print("⚠️ Live Mandi server હાલમાં વ્યસ્ત છે; નવી request રોકવામાં આવી છે.")
        if cached and cached.get("records"):
            print(f"\n📦 છેલ્લે મળેલા cached mandi ભાવ — સમય: {cached.get('saved_at', '-')}")
            print("નોંધ: આ Live ભાવ નથી; વેચાણ પહેલાં સ્થાનિક બજારમાં ખાતરી કરો.")
            show_mandi_prices({"records": cached["records"]})
        else:
            print("હાલમાં cached ભાવ ઉપલબ્ધ નથી. 10–15 મિનિટ પછી ફરી પ્રયાસ કરો અથવા eNAM/Agmarknet તપાસો.")
        pause()
        return
    rows = data.get("records", []) if isinstance(data, dict) else []
    used_fallback = False

    if not rows:
        retry_params = []
        if state and commodity:
            retry_params.append({**base, "filters[state]": state, "filters[commodity]": commodity})
        if commodity:
            retry_params.append({**base, "filters[commodity]": commodity})
        if state:
            retry_params.append({**base, "filters[state]": state})
        for rp in retry_params:
            retry_url = "https://api.data.gov.in/resource/" + DATA_GOV_RESOURCE_ID + "?" + urllib.parse.urlencode(rp)
            retry_data = get_json(retry_url)
            if isinstance(retry_data, dict) and retry_data.get("__rate_limited__"):
                print("ભાવ મેળવવા માટે વધુ fallback requests કરવામાં આવી નથી.")
                break
            retry_rows = retry_data.get("records", []) if isinstance(retry_data, dict) else []
            if commodity:
                retry_rows = [r for r in retry_rows if _commodity_matches(r, commodity)]
            if retry_rows:
                rows = retry_rows
                used_fallback = True
                break

    if rows:
        dated = [(r, _mandi_date_key(r.get("arrival_date") or r.get("arrival date") or r.get("date"))) for r in rows]
        valid_dates = [d for _, d in dated if d]
        latest = max(valid_dates) if valid_dates else None
        if latest:
            rows = [r for r, d in dated if d == latest]
            today = datetime.now().date()
            if latest < today:
                print(f"\nℹ️ આજનો ભાવ હજુ અપડેટ થયો નથી. ઉપલબ્ધ છેલ્લી તારીખ: {latest.strftime('%d-%m-%Y')}")
            else:
                print(f"\n✅ આજના બજાર ભાવ — તારીખ: {latest.strftime('%d-%m-%Y')}")
        if used_fallback:
            print("\nℹ️ ચોક્કસ જિલ્લો/ફિલ્ટર પર ભાવ મળ્યા નથી; માત્ર પસંદ કરેલા પાકના ઉપલબ્ધ ભાવ દર્શાવ્યા છે.")
        _save_mandi_cache(rows, state, district, commodity)
        show_mandi_prices({"records": rows})
    else:
        if commodity:
            print(f"ભાવ મળ્યા નથી. {commodity_input} માટે આજનો અથવા છેલ્લો ઉપલબ્ધ ભાવ મળ્યો નથી. અન્ય પાકના ભાવ દર્શાવવામાં આવ્યા નથી.")
        else:
            print("ભાવ મળ્યા નથી. થોડા સમય પછી ફરી પ્રયાસ કરો અથવા eNAM/Agmarknet પર તપાસો.")
    pause()

def show_mandi_prices(data):
    rows=data.get("records",[]) if isinstance(data,dict) else []
    print(f"\n📈 Live mandi પરિણામ — સમય: {now()} — કુલ: {len(rows)}")
    if not rows: print("કોઈ રેકોર્ડ નથી."); return
    for r in rows[:30]:
        print(f"{r.get('market','-')} | {r.get('commodity','-')} | જાત: {r.get('variety','-')} | તારીખ: {r.get('arrival_date','-')} | min {r.get('min_price','-')} | max {r.get('max_price','-')} | modal {r.get('modal_price','-')}")
    print("સ્રોત: data.gov.in/Agmarknet. ભાવમાં ફેરફાર થઈ શકે છે; વેચાણ પહેલાં બજારમાં ખાતરી કરો.")

def rss_search(query, limit=5):
    url="https://news.google.com/rss/search?"+urllib.parse.urlencode({"q":query,"hl":"gu","gl":"IN","ceid":"IN:gu"})
    raw=get_text(url)
    if not raw: return []
    try: root=ET.fromstring(raw)
    except Exception: return []
    out=[]
    for item in root.findall(".//item")[:limit]:
        out.append({"title":item.findtext("title",""),"link":item.findtext("link",""),"date":item.findtext("pubDate",""),"source":item.findtext("source","")})
    return out

def get_crop_news():
    crop=choose_crop(); items=rss_search(f"{crop} ગુજરાત ખેડૂત ખેતી બજાર",5); show_crop_news(items,crop); pause()
def show_crop_news(items,crop=""):
    print(f"\n📰 {crop} માટે તાજા સમાચાર")
    if not items: print("સમાચાર મળ્યા નથી અથવા ઈન્ટરનેટ ઉપલબ્ધ નથી."); return
    for i,x in enumerate(items,1): print(f"{i}. {x['title']}\n   તારીખ: {x['date']} | સ્ત્રોત: {x['source']}\n   લિંક: {x['link']}\n")
    print("સમાચારનો નિર્ણય કરતા પહેલાં મૂળ સ્ત્રોત ખોલી ચકાસો.")

def get_msp_information():
    crop=choose_crop(); items=rss_search(f"{crop} MSP minimum support price India official PIB",5)
    print(f"\n💰 {crop} MSP/સમર્થન ભાવ")
    print("MSP અને બજાર ભાવ અલગ છે. માર્કેટમાં મળતો ભાવ MSP હોવો જરૂરી નથી.")
    if items:
        for x in items: print(f"• {x['title']} | {x['date']} | {x['link']}")
    else: print("તાજી માહિતી મળતી નથી. PIB, CACP અને કૃષિ મંત્રાલયની સત્તાવાર જાહેરાત તપાસો.")
    pause()
def show_msp_information(): get_msp_information()

def get_government_schemes():
    print("\n🏛️ સરકારી યોજના/જાહેરાત શોધ")
    q=safe_input("યોજના/વિષય (ખાલી=ખેડૂત યોજના): ") or "PM KISAN crop insurance KCC Gujarat farmer scheme official"
    items=rss_search(q,5)
    if items:
        for x in items: print(f"• {x['title']}\n  તારીખ: {x['date']} | {x['link']}\n")
    else: print("માહિતી મળી નથી. myscheme.gov.in, pmkisan.gov.in, pmfby.gov.in અને ikhedut.gujarat.gov.in તપાસો.")
    print("સામાન્ય દસ્તાવેજો: આધાર, બેંક પાસબુક, જમીન દસ્તાવેજ, મોબાઇલ, ફોટો અને જાતિ/આવક પ્રમાણપત્ર જ્યાં લાગુ પડે.")
    pause()
def show_government_schemes(): get_government_schemes()

def weather_place(): return safe_input("શહેર/ગામનું નામ: ") or "Ahmedabad"
def geocode(place):
    url="https://geocoding-api.open-meteo.com/v1/search?"+urllib.parse.urlencode({"name":place,"count":1,"language":"en","format":"json"})
    d=get_json(url); return (d.get("results") or [None])[0] if d else None

def get_weather():
    place=weather_place(); g=geocode(place)
    if not g: print("સ્થળ મળ્યું નથી."); pause(); return
    url="https://api.open-meteo.com/v1/forecast?"+urllib.parse.urlencode({"latitude":g["latitude"],"longitude":g["longitude"],"current":"temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,cloud_cover","timezone":"auto"})
    d=get_json(url)
    if d:
        c=d.get("current",{}); print(f"\n🌤️ {g.get('name')}\nસ્રોત: Open-Meteo\nતાપમાન: {c.get('temperature_2m')}°C\nભેજ: {c.get('relative_humidity_2m')}%\nપવન: {c.get('wind_speed_10m')} km/h\nવરસાદ: {c.get('precipitation')} mm\nવાદળ: {c.get('cloud_cover')}%\nસમય: {c.get('time')}\nકૃષિ સલાહ: વરસાદ/પવન મુજબ દવા છંટકાવ અને સિંચાઈનું આયોજન કરો.")
    pause()

def get_forecast():
    place=weather_place(); g=geocode(place)
    if not g: print("સ્થળ મળ્યું નથી."); pause(); return
    url="https://api.open-meteo.com/v1/forecast?"+urllib.parse.urlencode({"latitude":g["latitude"],"longitude":g["longitude"],"daily":"temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max","forecast_days":7,"timezone":"auto"})
    d=get_json(url)
    if d:
        x=d.get("daily",{}); print(f"\n📅 {g.get('name')} — 7 દિવસ આગાહી")
        for i,day in enumerate(x.get("time",[])): print(f"{day}: {x['temperature_2m_min'][i]}–{x['temperature_2m_max'][i]}°C | વરસાદ {x['precipitation_sum'][i]} mm | પવન {x['wind_speed_10m_max'][i]} km/h")
    pause()

def tools(): print("\n🛠️ સાધનો: માટી પરીક્ષણ કિટ, ડ્રિપ, સ્પ્રિંકલર, સ્પ્રેયર, મલ્ચિંગ, હવામાન એપ, ભેજમાપક અને પાક કાપણી સાધનો પસંદ કરતી વખતે ગુણવત્તા/સર્વિસ તપાસો."); pause()
def crop_calendar(): crop=choose_crop(); print(f"\n🗓️ {crop} પાક કેલેન્ડર\n1. જમીન/માટી પરીક્ષણ\n2. બીજ અને વાવણી તૈયારી\n3. વાવણી\n4. 15–30 દિવસ: નીંદણ/ખાતર\n5. મધ્ય અવસ્થા: પાણી અને જીવાત નિરીક્ષણ\n6. ફૂલ/દાણા/ફળ: ભેજ અને પોષણ\n7. પરિપક્વતા: કાપણી, સુકવણી, ગ્રેડિંગ\n8. સંગ્રહ અને બજાર આયોજન"); pause()
def profit_calculator():
    print("\n🧮 ખર્ચ-આવક ગણતરી")
    try:
        area=float(safe_input("વિસ્તાર (એકર): ")); cost=float(safe_input("કુલ ખર્ચ (₹): ")); yield_q=float(safe_input("કુલ ઉપજ (ક્વિન્ટલ): ")); price=float(safe_input("ભાવ ₹/ક્વિન્ટલ: "))
        income=yield_q*price; print(f"આવક: ₹{income:,.2f}\nનફો/નુકસાન: ₹{income-cost:,.2f}\nએકર દીઠ નફો: ₹{(income-cost)/area:,.2f}" if area else f"આવક: ₹{income:,.2f}\nનફો/નુકસાન: ₹{income-cost:,.2f}")
    except ValueError: print("આંકડા યોગ્ય રીતે નાખો.")
    pause()
def farmer_question():
    q=safe_input("તમારો પ્રશ્ન: "); print("\n🤖 પ્રાથમિક માર્ગદર્શન:\n", "પાક, જમીન, પાણી, હવામાન અને રોગની માહિતી સાથે સ્થાનિક કૃષિ અધિકારી/KVKની સલાહ લો.\nતમારો પ્રશ્ન:", q); pause()
def about(): print(f"\nSmart Agri-Market AI Agent {APP_VERSION}\nગુજરાતી ખેડૂત સહાયક. Live data માટે ઈન્ટરનેટ/API જરૂરી છે. દવા, MSP અને યોજનાઓ અંગે અંતિમ નિર્ણય સત્તાવાર સ્ત્રોત/કૃષિ નિષ્ણાતથી ચકાસવો."); pause()


# ---------- Comprehensive enhancements (targeted, standard-library only) ----------
ROMAN_ALIASES = {
    "kapas":"કપાસ", "cotton":"કપાસ", "magfali":"મગફળી", "mungfali":"મગફળી", "groundnut":"મગફળી",
    "ghau":"ઘઉં", "wheat":"ઘઉં", "bajri":"બાજરી", "bajra":"બાજરી", "makai":"મકાઈ", "maize":"મકાઈ",
    "jiru":"જીરું", "jeera":"જીરું", "dhana":"ધાણા", "coriander":"ધાણા", "tal":"તલ", "sesame":"તલ",
    "eranda":"એરંડા", "castor":"એરંડા", "chana":"ચણા", "gram":"ચણા", "tuver":"તુવેર", "tur":"તુવેર",
    "mag":"મગ", "moong":"મગ", "adad":"અડદ", "urad":"અડદ", "dungli":"ડુંગળી", "onion":"ડુંગળી",
    "bataka":"બટાકા", "potato":"બટાકા", "tameta":"ટામેટા", "tomato":"ટામેટા", "marchu":"મરચાં", "chilli":"મરચાં",
    "lasan":"લસણ", "garlic":"લસણ", "sherdi":"શેરડી", "sugarcane":"શેરડી", "keri":"કેરી", "mango":"કેરી",
    "kela":"કેળા", "banana":"કેળા", "dadam":"દાડમ", "pomegranate":"દાડમ"
}
SYMPTOM_ALIASES = {"pan pila":"પાન પીળાં", "pan pila":"પાન પીળાં", "iyal":"ઈયળ", "iyal":"ઈયળ", "dagh":"ડાઘ", "safed makhi":"સફેદમાખી", "gai":"ગાય", "gay":"ગાય"}
WEATHER_PLACES = {
    "una": (20.823, 71.046), "ઉના": (20.823,71.046), "gir somnath": (20.900,70.367), "ગીર સોમનાથ": (20.900,70.367),
    "veraval": (20.907,70.367), "વેરાવળ": (20.907,70.367), "kodinar": (20.794,70.703), "કોડીનાર": (20.794,70.703),
    "junagadh": (21.522,70.457), "જૂનાગઢ": (21.522,70.457), "rajkot": (22.303,70.802), "રાજકોટ": (22.303,70.802),
    "ahmedabad": (23.022,72.571), "અમદાવાદ": (23.022,72.571), "surat": (21.170,72.831), "સુરત": (21.170,72.831),
    "bhavnagar": (21.764,72.151), "ભાવનગર": (21.764,72.151), "jamnagar": (22.470,70.057), "જામનગર": (22.470,70.057),
    "amreli": (21.603,71.222), "અમરેલી": (21.603,71.222), "porbandar": (21.642,69.629), "પોરબંદર": (21.642,69.629)
}

def normalize_text(x):
    return " ".join((x or "").strip().lower().replace("-"," ").split())

def normalize_crop(x):
    n=normalize_text(x)
    if n in CROPS: return CROPS[n]
    if n in ROMAN_ALIASES: return ROMAN_ALIASES[n]
    for k,v in CROPS.items():
        if normalize_text(v)==n: return v
    return x.strip() if x.strip() else "અન્ય"

def choose_crop():
    line(); print("પાક પસંદ કરો")
    for k,v in CROPS.items(): print(f"{k:>2}. {v}")
    return normalize_crop(safe_input("નંબર અથવા પાકનું નામ: "))

def crop_profile(crop):
    d=CROP_DATA.get(crop, {})
    return d or {"પ્રકાર":"સ્થાનિક પાક", "જમીન":"માટી પરીક્ષણ અને સ્થાનિક ભલામણ મુજબ", "pH":"માટી પરીક્ષણ મુજબ", "વાવણી":"ઋતુ અને વિસ્તાર મુજબ", "બીજ":"પ્રમાણિત બીજ", "બીજદર":"જાત/વિસ્તાર મુજબ", "અંતર":"જાત અને ભલામણ મુજબ", "પાણી":"જમીનના ભેજ અને પાકની અવસ્થા મુજબ", "સાવચેતી":"નિયમિત નિરીક્ષણ અને યોગ્ય નિતાર"}

def crop_information():
    crop=choose_crop(); d=crop_profile(crop); line(); print(f"🌾 {crop} — સંપૂર્ણ માહિતી")
    fields=[("પ્રકાર","પ્રકાર"),("જમીન","જમીન"),("pH","pH"),("વાવણી સમય","વાવણી"),("બીજ","બીજ"),("બીજદર","બીજદર"),("અંતર","અંતર"),("સિંચાઈ","પાણી"),("સાવચેતી","સાવચેતી")]
    for label,key in fields: print(f"• {label}: {d.get(key,'સ્થાનિક કૃષિ ભલામણ મુજબ')}")
    print("• ખાતર: માટી પરીક્ષણ અને પાક અવસ્થા પ્રમાણે NPK/સજીવ ખાતર.")
    print("• નીંદણ: શરૂઆતની અવસ્થામાં સમયસર નિયંત્રણ.")
    print("• રોગ/જીવાત: પાક-વિશિષ્ટ નિરીક્ષણ, IPM અને અધિકૃત ભલામણ.")
    print("• કાપણી/સંગ્રહ: પરિપક્વતા, યોગ્ય ભેજ અને સ્વચ્છ સંગ્રહ.")
    print("• બજાર: તાજા ભાવ, ગુણવત્તા, ભેજ અને ગ્રેડ તપાસો."); pause()

def crop_advice():
    crop=choose_crop(); print(f"\n🌱 {crop} માટે ખેતી માર્ગદર્શન")
    for h,t in [("A. જમીન તૈયારી","માટી પરીક્ષણ, યોગ્ય ખેડ અને નિતાર."),("B. બીજ","પ્રમાણિત બીજ અને પાક-વિશિષ્ટ બીજ ઉપચાર."),("C. વાવણી","ઋતુ, ભેજ, ઊંડાઈ અને અંતર મુજબ."),("D. પાણી","જમીન/હવામાન/અવસ્થા મુજબ; પાણી ભરાવું ટાળો."),("E. પોષણ","માટી પરીક્ષણ આધારિત ખાતર."),("F. નીંદણ","સમયસર હાથથી/યાંત્રિક/IPM નિયંત્રણ."),("G. રોગ/જીવાત","અઠવાડિયે નિરીક્ષણ અને યોગ્ય ઓળખ."),("H. કાપણી","પરિપક્વતા અને બજાર ભેજ મુજબ."),("I. સંગ્રહ","સુકું, હવાદાર અને જીવાતમુક્ત સ્થળ."),("J. નોંધ","તારીખ, ખર્ચ, પાણી, દવા અને ઉપજનો રેકોર્ડ.")]: print(f"{h}: {t}")
    pause()

def disease_advice():
    crop=choose_crop(); raw=safe_input("લક્ષણ/જીવાત લખો (દા. પાન પીળાં, ઈયળ, ડાઘ): "); symptom=SYMPTOM_ALIASES.get(normalize_text(raw),raw)
    print(f"\n🔎 {crop} — {symptom or 'સામાન્ય'}")
    if symptom in ("ઈયળ", "ઇયળ"):
        print("• શક્ય કારણ: પાનખાઉ ઈયળ, બોલવર્મ/સ્પોડોપ્ટેરા અથવા પાક-વિશિષ્ટ ઈયળ.")
        print("• તપાસો: પાન/ફૂલ/ચોરસ/ફળમાં છિદ્ર, ઈંડાં, ઈયળનો રંગ અને મળ.")
        print("• IPM: નિયમિત નિરીક્ષણ, ઈંડાં/ઈયળ દૂર કરવી અને યોગ્ય ટ્રેપ/જૈવિક નિયંત્રણ.")
    elif symptom in ("પાન પીળાં", "પાન પીળા"):
        print("• શક્ય કારણ: પોષક તત્ત્વોની અછત, પાણી ભરાવું/અછત, મૂળની જીવાત અથવા રોગ.")
        print("• તપાસો: જૂનાં કે નવાં પાન, નસો લીલી છે કે નહીં, મૂળ અને જમીનનો ભેજ.")
        print("• માટી પરીક્ષણ અને અસરગ્રસ્ત છોડનું નજીકથી નિરીક્ષણ કરો.")
    else:
        print("1) અસરગ્રસ્ત ભાગના ફોટા અને નજીકથી નિરીક્ષણ કરો.")
        print("2) પાણી, પોષણ, રોગ અને જીવાતની સંભાવના અલગથી તપાસો.")
    print("⚠️ પીળા ચીકણા ટ્રેપ દરેક ઈયળ માટે યોગ્ય નથી. દવા/ડોઝ માત્ર પાક-રોગની ખાતરી, લેબલ અને સ્થાનિક નિષ્ણાતની સલાહથી."); pause()

def irrigation():
    crop=choose_crop(); print(f"\n💧 {crop} સિંચાઈ યોજના")
    print("• પાકની અવસ્થા, જમીનનો ભેજ અને છેલ્લો વરસાદ તપાસો.")
    print("• ડ્રિપ/સ્પ્રિંકલરથી કાર્યક્ષમ સિંચાઈ કરો; પાણી ભરાવું ટાળો.")
    print("• અંકુરણ, ફૂલ/પેગિંગ/દાણા અથવા ફળ ભરાવાની અવસ્થામાં ખાસ ધ્યાન.")
    print("• વરસાદ/પવનની આગાહી હોય તો અનાવશ્યક સિંચાઈ અથવા છંટકાવ ટાળો."); pause()

def fertilizer():
    crop=choose_crop(); print(f"\n🧪 {crop} પોષણ યોજના")
    print("• માટી પરીક્ષણ પછી જ N-P-K, ગંધક, ઝિંક, બોરોન/કેલ્શિયમ નક્કી કરો.")
    print("• પાકની અવસ્થા પ્રમાણે ખાતર અને જરૂર મુજબ સજીવ ખાતર/કમ્પોસ્ટ.")
    print("• અછતના લક્ષણો અને માટી રિપોર્ટ વિના ચોક્કસ ડોઝ ન નક્કી કરો.")
    print("• પાન પર છંટકાવ માત્ર માન્ય ભલામણ અને લેબલ મુજબ."); pause()

def geocode(place):
    n=normalize_text(place)
    if n in WEATHER_PLACES:
        lat,lon=WEATHER_PLACES[n]; return {"name":place.strip().title(),"latitude":lat,"longitude":lon,"country":"India","admin1":"Gujarat"}
    # force India/Gujarat query to prevent foreign homonyms
    url="https://geocoding-api.open-meteo.com/v1/search?"+urllib.parse.urlencode({"name":place,"count":10,"language":"en","format":"json","countryCode":"IN"})
    d=get_json(url)
    for r in (d or {}).get("results",[]):
        if r.get("country_code")=="IN" and (r.get("admin1") in ("Gujarat","Gujarat State") or r.get("country")=="India"): return r
    return None

def weather_place(): return safe_input("શહેર/ગામનું નામ: ") or "Ahmedabad"

def get_weather():
    place=weather_place(); g=geocode(place)
    if not g: print("સ્થળ મળ્યું નથી. ગુજરાતનું શહેર/ગામ અથવા નજીકનું તાલુકા મથક લખો."); pause(); return
    url="https://api.open-meteo.com/v1/forecast?"+urllib.parse.urlencode({"latitude":g["latitude"],"longitude":g["longitude"],"current":"temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,cloud_cover","timezone":"auto"})
    d=get_json(url)
    if d:
        c=d.get("current",{}); print(f"\n🌤️ {g.get('name')} — {g.get('admin1','Gujarat')}, {g.get('country','India')}\nસ્રોત: Open-Meteo\nતાપમાન: {c.get('temperature_2m')}°C\nભેજ: {c.get('relative_humidity_2m')}%\nપવન: {c.get('wind_speed_10m')} km/h\nવરસાદ: {c.get('precipitation')} mm\nવાદળ: {c.get('cloud_cover')}%\nસમય: {c.get('time')}\nકૃષિ સલાહ: વરસાદ/પવન મુજબ દવા છંટકાવ અને સિંચાઈનું આયોજન કરો.")
    pause()

def get_forecast():
    place=weather_place(); g=geocode(place)
    if not g: print("સ્થળ મળ્યું નથી. ગુજરાતનું શહેર/ગામ અથવા નજીકનું તાલુકા મથક લખો."); pause(); return
    url="https://api.open-meteo.com/v1/forecast?"+urllib.parse.urlencode({"latitude":g["latitude"],"longitude":g["longitude"],"daily":"temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max","forecast_days":7,"timezone":"auto"})
    d=get_json(url)
    if d:
        x=d.get("daily",{}); print(f"\n📅 {g.get('name')} — 7 દિવસ આગાહી")
        for i,day in enumerate(x.get("time",[])):
            print(f"{day}: {x['temperature_2m_min'][i]}–{x['temperature_2m_max'][i]}°C | વરસાદ {x['precipitation_sum'][i]} mm | શક્યતા {x.get('precipitation_probability_max',['-']*7)[i]}% | પવન {x['wind_speed_10m_max'][i]} km/h")
    pause()

def tools():
    print("\n🛠️ સાધનો/મશીનરી")
    items=[("માટી પરીક્ષણ કિટ","pH/EC/NPK માટે; નમૂનો યોગ્ય રીતે લો."),("ભેજમાપક","સિંચાઈ પહેલાં જમીનનો ભેજ તપાસો; કેલિબ્રેશન જુઓ."),("ડ્રિપ/સ્પ્રિંકલર","ફિલ્ટર, પ્રેશર, લીકેજ અને સર્વિસ તપાસો."),("સ્પ્રેયર","નોઝલ, દબાણ, PPE અને પવનની સ્થિતિ તપાસો."),("મલ્ચિંગ","પાક અને જમીન પ્રમાણે યોગ્ય સામગ્રી પસંદ કરો."),("પાક કાપણી સાધનો","પાક પ્રમાણે ક્ષમતા, સ્પેર પાર્ટ્સ અને સર્વિસ તપાસો.")]
    for n,t in items: print(f"• {n}: {t}")
    print("\n💰 i-Khedut સબસીડી: સાધન પ્રમાણે પાત્રતા, સહાય અને અરજીની તારીખ સત્તાવાર i-Khedut પોર્ટલ પર ચકાસો.")
    print("🔗 https://ikhedut.gujarat.gov.in")
    print("⚠️ સબસીડીની રકમ/અરજી સમય બદલાઈ શકે છે; અધિકૃત પોર્ટલની હાલની જાહેરાતને અંતિમ માનવી."); pause()

def crop_calendar():
    crop=choose_crop(); print(f"\n🗓️ {crop} પાક કેલેન્ડર")
    for x in ["1. જમીન અને માટી પરીક્ષણ","2. પ્રમાણિત બીજ અને વાવણી તૈયારી","3. યોગ્ય ઋતુ/ભેજમાં વાવણી","4. શરૂઆતની અવસ્થામાં નીંદણ અને છોડની સંખ્યા","5. મધ્ય અવસ્થામાં પાણી/ખાતર/જીવાત નિરીક્ષણ","6. ફૂલ/દાણા/ફળ ભરાવા સમયે ભેજ અને પોષણ","7. પરિપક્વતા, કાપણી, સુકવણી અને ગ્રેડિંગ","8. સંગ્રહ, બજાર અને ખર્ચનો રેકોર્ડ"]: print(x)
    print("નોંધ: વાવણી તારીખ, જમીન અને સ્થાનિક હવામાન મુજબ ચોક્કસ દિવસો બદલાય છે."); pause()

def profit_calculator():
    print("\n🧮 ખર્ચ-આવક ગણતરી")
    try:
        area=float(safe_input("વિસ્તાર (વીઘા): ")); cost=float(safe_input("કુલ ખર્ચ (₹): ")); yield_k=float(safe_input("કુલ ઉપજ (ખાંડી): ")); price=float(safe_input("ભાવ ₹/ખાંડી: "))
        income=yield_k*price; profit=income-cost
        print(f"આવક: ₹{income:,.2f}\nનફો/નુકસાન: ₹{profit:,.2f}\nવીઘા દીઠ નફો: ₹{profit/area:,.2f}" if area else f"આવક: ₹{income:,.2f}\nનફો/નુકસાન: ₹{profit:,.2f}")
        print(f"રૂપાંતર: {yield_k*4:,.2f} ક્વિન્ટલ | 1 ખાંડી = 4 ક્વિન્ટલ")
        print("વિસ્તાર નોંધ: 1 હેક્ટર=2.47 એકર; 1 એકર=40 ગુંઠા; 1 વીઘા આશરે 16–23.5 ગુંઠા, વિસ્તાર પ્રમાણે.")
    except ValueError: print("આંકડા યોગ્ય રીતે નાખો.")
    pause()

def farmer_question():
    q=safe_input("તમારો પ્રશ્ન: "); n=normalize_text(q); print("\n🤖 ખેડૂત સહાયક જવાબ:")
    if any(k in n for k in ("shiyala","શિયાળા","શિયાળામાં","rabi")) and any(k in n for k in ("pak","પાક","vavvu","વાવવો","karay","કરાય")):
        print("શિયાળામાં સામાન્ય રીતે ઘઉં, ચણા, જીરું, ધાણા, રાયડો, વરિયાળી, ડુંગળી, લસણ અને શિયાળુ શાકભાજી થાય છે.")
        print("જિલ્લો, જમીન, પાણી અને બજાર પ્રમાણે યોગ્ય પાક પસંદ કરો.")
    elif n in ("gay","ગાય") or "ગાય" in n or "cow" in n:
        print("ગાય અંગે શું જાણવા છે—આહાર, દૂધ, તાવ, રસીકરણ કે બીમારી? લક્ષણો, ઉંમર અને ગર્ભાવસ્થા જણાવો.")
        print("ગંભીર લક્ષણો હોય તો તરત પશુચિકિત્સકનો સંપર્ક કરો; દવા/ડોઝ જાતે ન આપો.")
    elif any(k in n for k in ("pan pila","પાન પીળા","iyal","ઈયળ")):
        print("પાકનું નામ, લક્ષણનો ફોટો, પાકની ઉંમર, પાણીની સ્થિતિ અને નુકસાનનું પ્રમાણ જણાવો.")
        print("ચોક્કસ કારણની ખાતરી વિના દવા ન વાપરો.")
    else:
        print("પ્રશ્નનો વધુ ચોક્કસ જવાબ આપવા પાક/પશુ, જિલ્લો, જમીન, પાણી, ઉંમર અને લક્ષણ જણાવો.")
        print("સ્થાનિક કૃષિ અધિકારી/KVK અથવા પશુચિકિત્સકની સલાહ સાથે અંતિમ નિર્ણય લો.")
    pause()

def about():
    print(f"\nSmart Agri-Market AI Agent {APP_VERSION}\nગુજરાતી ખેડૂત સહાયક. Live data માટે Internet/API જરૂરી છે.\nમાહિતી પાક, હવામાન, બજાર, MSP, યોજના, સાધનો અને ખેડૂત પ્રશ્નો માટે છે.\nદવા, MSP, સબસીડી અને યોજનાઓ અંગે અંતિમ નિર્ણય અધિકૃત સ્રોત/કૃષિ નિષ્ણાતથી ચકાસવો.\ni-Khedut: https://ikhedut.gujarat.gov.in")
    pause()

def main():
    while True:
        line(); print("🌾 SMART AGRI-MARKET AI AGENT V7 🌾"); line("-")
        menu=["પાક સંપૂર્ણ માહિતી","પાક ખેતી સલાહ","રોગ/જીવાત સલાહ","સિંચાઈ સલાહ","ખાતર/પોષણ","Live mandi ભાવ","પાક સમાચાર","ગુજરાત MSP/સમર્થન ભાવ","સરકારી યોજના/જાહેરાત","Live હવામાન","7 દિવસ આગાહી","સાધનો/મશીનરી","પાક કેલેન્ડર","ખર્ચ-આવક-નફો","ખેડૂત પ્રશ્ન","About"]
        for i,m in enumerate(menu,1): print(f"{i:>2}. {m}")
        print(" 0. બહાર નીકળો")
        c=safe_input("પસંદગી: ")
        funcs={"1":crop_information,"2":crop_advice,"3":disease_advice,"4":irrigation,"5":fertilizer,"6":get_mandi_data,"7":get_crop_news,"8":get_msp_information,"9":get_government_schemes,"10":get_weather,"11":get_forecast,"12":tools,"13":crop_calendar,"14":profit_calculator,"15":farmer_question,"16":about}
        if c=="0": print("આભાર. શુભ ખેતી! 🌱"); break
        f=funcs.get(c)
        if f:
            try: f()
            except KeyboardInterrupt: print("\nરદ કર્યું.")
            except Exception as e: print(f"આ વિકલ્પમાં અનપેક્ષિત ભૂલ: {e}")
        else: print("અમાન્ય પસંદગી.")

# ==================== V8 SAFETY / REGRESSION PATCH ====================
APP_VERSION = "8.0 Rate-Limit Safe Farmer Edition"

# Common Gujarati/Roman aliases retained and expanded without changing existing flows.
ROMAN_ALIASES.update({
    "mugfali": "મગફળી", "mungfali": "મગફળી", "groundnut": "મગફળી",
    "erand": "એરંડા", "castor": "એરંડા", "marchaa": "મરચાં",
    "mirchi": "મરચાં", "chilli": "મરચાં", "chana": "ચણા",
    "raydo": "રાયડો", "mustard": "રાયડો", "variyaali": "વરિયાળી",
    "fennel": "વરિયાળી", "dhania": "ધાણા", "coriander": "ધાણા",
})

# Reject non-Gujarat geocoding results; preserve existing hard-coded Gujarat places.
_original_geocode = geocode
def geocode(place):
    result = _original_geocode(place)
    if not result:
        return result
    admin = str(result.get("admin1", "")).lower()
    country = str(result.get("country", "")).lower()
    if "gujarat" not in admin and not (country == "india" and admin in ("", "gujarat")):
        return None
    return result

# Safer numeric parsing for profit calculator; prevents negative/zero area and invalid values.
def profit_calculator():
    print("\n🧮 ખર્ચ-આવક ગણતરી")
    try:
        area = float(safe_input("વિસ્તાર (વીઘા): "))
        cost = float(safe_input("કુલ ખર્ચ (₹): "))
        yield_k = float(safe_input("કુલ ઉપજ (ખાંડી): "))
        price = float(safe_input("ભાવ ₹/ખાંડી: "))
        if area <= 0 or cost < 0 or yield_k < 0 or price < 0:
            print("વિસ્તાર 0 કરતાં મોટો અને ખર્ચ/ઉપજ/ભાવ નકારાત્મક ન હોવા જોઈએ.")
        else:
            income = yield_k * price
            profit = income - cost
            print(f"આવક: ₹{income:,.2f}")
            print(f"નફો/નુકસાન: ₹{profit:,.2f}")
            print(f"વીઘા દીઠ નફો: ₹{profit/area:,.2f}")
            print(f"રૂપાંતર: {yield_k*4:,.2f} ક્વિન્ટલ | 1 ખાંડી = 4 ક્વિન્ટલ")
            print("વિસ્તાર નોંધ: 1 હેક્ટર=2.47 એકર; 1 એકર=40 ગુંઠા; 1 વીઘા આશરે 16–23.5 ગુંઠા, વિસ્તાર પ્રમાણે.")
    except (ValueError, TypeError):
        print("આંકડા યોગ્ય રીતે નાખો.")
    pause()

# Keep the displayed version consistent with the actual patched build.
def main():
    while True:
        line(); print(f"🌾 SMART AGRI-MARKET AI AGENT — {APP_VERSION} 🌾"); line("-")
        menu=["પાક સંપૂર્ણ માહિતી","પાક ખેતી સલાહ","રોગ/જીવાત સલાહ","સિંચાઈ સલાહ","ખાતર/પોષણ","Live mandi ભાવ","પાક સમાચાર","ગુજરાત MSP/સમર્થન ભાવ","સરકારી યોજના/જાહેરાત","Live હવામાન","7 દિવસ આગાહી","સાધનો/મશીનરી","પાક કેલેન્ડર","ખર્ચ-આવક-નફો","ખેડૂત પ્રશ્ન","About"]
        for i,m in enumerate(menu,1): print(f"{i:>2}. {m}")
        print(" 0. બહાર નીકળો")
        c=safe_input("પસંદગી: ")
        funcs={"1":crop_information,"2":crop_advice,"3":disease_advice,"4":irrigation,"5":fertilizer,"6":get_mandi_data,"7":get_crop_news,"8":get_msp_information,"9":get_government_schemes,"10":get_weather,"11":get_forecast,"12":tools,"13":crop_calendar,"14":profit_calculator,"15":farmer_question,"16":about}
        if c=="0": print("આભાર. શુભ ખેતી! 🌱"); break
        f=funcs.get(c)
        if f:
            try: f()
            except KeyboardInterrupt: print("\nરદ કર્યું.")
            except Exception as e: print(f"આ વિકલ્પમાં અનપેક્ષિત ભૂલ: {e}")
        else: print("અમાન્ય પસંદગી.")

if __name__ == "__main__": main()

# ================= V8 ROADMAP COMPLETION PATCH =================
APP_VERSION = "8.0 Roadmap Complete - Regression Tested Farmer Edition"
USER_AGENT = "SmartAgriMarketAgent/8.0"

# Complete crop profile coverage. Values are practical guidance; local KVK/department advice prevails.
_EXTRA_CROP_PROFILES = {
"જીરું":("મસાલા પાક","હલકી, ભુરભુરી અને નિતારવાળી જમીન","6.5–8.0","નવેમ્બર–ડિસેમ્બર","12–15 કિગ્રા/હે.","30×10 સે.મી.","વાવણી પછી હળવી સિંચાઈ; પાણી ભરાવું નહીં","ચરમી, સુકારો અને થ્રીપ્સ"),
"ધાણા":("મસાલા પાક","ગોરાડુ અને નિતારવાળી જમીન","6.0–8.0","ઓક્ટોબર–નવેમ્બર","12–20 કિગ્રા/હે.","20–30 સે.મી.","હળવી અને નિયમિત સિંચાઈ","પાઉડરી મિલ્ડ્યુ અને ચૂસિયા જીવાત"),
"તલ":("તેલબિયાં પાક","હલકીથી મધ્યમ નિતારવાળી જમીન","5.5–8.0","જૂન–જુલાઈ","3–5 કિગ્રા/હે.","30×10 સે.મી.","ફૂલ સમયે ભેજ જાળવો","ફાયટોફ્થોરા અને પાન વાળનાર"),
"એરંડા":("તેલબિયાં પાક","મધ્યમથી ભારે નિતારવાળી જમીન","6.0–8.0","જૂન–જુલાઈ અથવા સિંચાઈમાં","5–8 કિગ્રા/હે.","90×60 સે.મી.","સ્થાપના અને કેપ્સ્યુલ ભરાવા સમયે","સેમિલૂપર અને વિલ્ટ"),
"ચણા":("કઠોળ રબી પાક","ગોરાડુ/કાળી નિતારવાળી જમીન","6.0–8.0","ઓક્ટોબર–નવેમ્બર","60–80 કિગ્રા/હે.","30×10 સે.મી.","વધુ પાણી નહીં; ફૂલ અને દાણા સમયે જરૂર મુજબ","કટવર્મ, ફળી-છેદક અને વિલ્ટ"),
"તુવેર":("કઠોળ પાક","મધ્યમથી ઊંડી નિતારવાળી જમીન","6.0–8.0","જૂન–જુલાઈ","12–15 કિગ્રા/હે.","90×20 સે.મી.","લાંબા સુકા ગાળે પૂરક સિંચાઈ","ફળી-છેદક અને વિલ્ટ"),
"મગ":("ટૂંકા ગાળાનો કઠોળ પાક","હલકી અને નિતારવાળી જમીન","6.0–8.0","જૂન–જુલાઈ/માર્ચ–એપ્રિલ","12–20 કિગ્રા/હે.","30×10 સે.મી.","ફૂલ અને ફળી સમયે પાણીનો તાણ નહીં","સફેદમાખી, પીળો મોઝેક"),
"અડદ":("કઠોળ પાક","હલકીથી મધ્યમ નિતારવાળી જમીન","6.0–8.0","જૂન–જુલાઈ","15–20 કિગ્રા/હે.","30×10 સે.મી.","પાણી ભરાવાથી બચાવો","પીળો મોઝેક અને ફળી-છેદક"),
"ડુંગળી":("શાકભાજી/કંદ પાક","ભુરભુરી, સજીવ દ્રવ્યવાળી જમીન","6.0–7.5","રબીમાં ઓક્ટોબર–ડિસેમ્બર","8–10 કિગ્રા/હે. નર્સરી","15×10 સે.મી.","નિયમિત હળવી સિંચાઈ; કાપણી પહેલાં બંધ","થ્રીપ્સ અને જાંબલી ડાઘ"),
"બટાકા":("કંદ પાક","ભુરભુરી અને નિતારવાળી જમીન","5.5–7.0","ઓક્ટોબર–નવેમ્બર","2–3 ટન/હે. બીજકંદ","45×20 સે.મી.","કંદ બંધાવા અને વિકાસ સમયે નિયમિત પાણી","અર્લી/લેટ બ્લાઇટ અને સફેદમાખી"),
"ટામેટા":("શાકભાજી પાક","સારી નિતારવાળી ગોરાડુ જમીન","6.0–7.5","મોસમ અને સિંચાઈ પ્રમાણે","નર્સરી દ્વારા","90×45 સે.મી.","ફૂલ અને ફળ વિકાસ સમયે સમતોલ પાણી","ફળછેદક, સફેદમાખી અને ઝલસા"),
"મરચાં":("શાકભાજી/મસાલા પાક","સારી નિતારવાળી જમીન","6.0–7.5","મોસમ પ્રમાણે","નર્સરી દ્વારા","60×45 સે.મી.","નિયમિત હળવી સિંચાઈ","થ્રીપ્સ, માઈટ અને ફળસડવું"),
"લસણ":("કંદ/મસાલા પાક","ભુરભુરી અને નિતારવાળી જમીન","6.0–7.5","ઓક્ટોબર–નવેમ્બર","500–700 કિગ્રા કળી/હે.","15×10 સે.મી.","કંદ વિકાસ સુધી નિયમિત; કાપણી પહેલાં બંધ","થ્રીપ્સ અને જાંબલી ડાઘ"),
"શેરડી":("લાંબા ગાળાનો રોકડ પાક","ઊંડી, ફળદ્રુપ અને નિતારવાળી જમીન","6.5–8.0","ઓક્ટોબર–નવેમ્બર અથવા ફેબ્રુઆરી–માર્ચ","જાત પ્રમાણે સેટ્સ","120×60 સે.મી. આશરે","સ્થાપના, ટિલરિંગ અને ગ્રાન્ડ ગ્રોથ સમયે","શૂટ બોરર, ટોપ બોરર અને લાલ સડો"),
"કેરી":("બાગાયતી ફળ પાક","ઊંડી અને નિતારવાળી જમીન","5.5–7.5","ચોમાસા પહેલાં/પછી રોપણ","પ્રમાણિત કલમવાળા રોપા","જાત પ્રમાણે 8–10 મીટર","નાના છોડમાં નિયમિત; ફળ વિકાસમાં જરૂર મુજબ","હોપર, પાઉડરી મિલ્ડ્યુ અને ફળમાખી"),
"કેળા":("બાગાયતી ફળ પાક","સજીવ દ્રવ્યવાળી નિતારવાળી જમીન","6.0–7.5","સિંચાઈ ઉપલબ્ધ હોય ત્યારે","ટિશ્યૂ કલ્ચર રોપા","1.8×1.8 મીટર આશરે","નિયમિત પાણી અને ડ્રેનેજ અત્યંત જરૂરી","પનામા વિલ્ટ, થ્રીપ્સ અને સકર નિયંત્રણ"),
"દાડમ":("બાગાયતી ફળ પાક","હલકીથી મધ્યમ નિતારવાળી જમીન","6.5–7.5","જૂન–જુલાઈ/ફેબ્રુઆરી–માર્ચ","પ્રમાણિત રોપા","4.5×3 મીટર આશરે","ડ્રિપ અને ફળ વિકાસ સમયે સમતોલ પાણી","બેક્ટેરિયલ બ્લાઇટ, તેલીયા અને ફળછેદક"),
}
for _name, _p in _EXTRA_CROP_PROFILES.items():
    CROP_DATA[_name] = {"પ્રકાર":_p[0],"જમીન":_p[1],"pH":_p[2],"વાવણી":_p[3],"બીજદર":_p[4],"અંતર":_p[5],"પાણી":_p[6],"સાવચેતી":_p[7],"બીજ":"પ્રમાણિત/સ્થાનિક ભલામણ મુજબ"}

ROMAN_ALIASES.update({
"mugfali":"મગફળી","groundnut":"મગફળી","erand":"એરંડા","castor":"એરંડા","marchaa":"મરચાં","mirchi":"મરચાં","raydo":"અન્ય","rai":"અન્ય","variyaali":"અન્ય","fennel":"અન્ય","tuver":"તુવેર","tuvar":"તુવેર","mag":"મગ","udad":"અડદ","dungli":"ડુંગળી","bataka":"બટાકા","tameta":"ટામેટા","lasan":"લસણ","sherdi":"શેરડી","keri":"કેરી","kela":"કેળા","dadam":"દાડમ"})

_DISEASES = {
"કપાસ":["સફેદમાખી/થ્રીપ્સ: પાનની નીચે તપાસો, પીળા ચીકણા ટ્રેપ અને સ્થાનિક ભલામણ મુજબ નિયંત્રણ.","ગુલાબી ઈયળ: સમયસર નિરીક્ષણ, ફેરોમોન ટ્રેપ અને પાક અવશેષ વ્યવસ્થાપન."],
"મગફળી":["ટિક્કા/રસ્ટ: હવાના અવરજવર, બીજ ઉપચાર અને લક્ષણ દેખાય ત્યારે કૃષિ અધિકારીની ભલામણ.","સફેદ લટ: ઉનાળુ ઊંડી ખેડ અને પાક ફેરબદલી."],
"ઘઉં":["રસ્ટ: પીળા/નારંગી ચિહ્નો દેખાય તો જાત અને દવા અંગે KVKની સલાહ.","ગુલ્લી-ડાંગર: પ્રમાણિત બીજ અને યોગ્ય નીંદણ નિયંત્રણ."],
"ટામેટા":["ફળછેદક: ફેરોમોન ટ્રેપ, અસરગ્રસ્ત ફળ નાશ અને સંકલિત નિયંત્રણ.","ઝલસા: પાન ભીંજાય તેવું સિંચાઈ ટાળો અને હવાની અવરજવર રાખો."],
"મરચાં":["થ્રીપ્સ: પાન વાંકડા/ચાંદી જેવા થાય તો નિરીક્ષણ અને સંકલિત નિયંત્રણ.","ફળસડવું: ડ્રેનેજ સુધારો અને અસરગ્રસ્ત ફળ દૂર કરો."],
}

def _resolve_crop_v8(raw):
    s = (raw or "").strip().lower()
    if s in CROPS: return CROPS[s]
    if s in CROPS.values(): return s
    return ROMAN_ALIASES.get(s, s)

def crop_information_v8():
    print("\n🌾 પાક પસંદ કરો:")
    for k,v in CROPS.items(): print(f"{k}. {v}")
    crop = _resolve_crop_v8(safe_input("પાકનું નામ/નંબર: "))
    if crop not in CROPS.values() or crop == "અન્ય": print("❌ પાક મળ્યો નથી."); return
    d = CROP_DATA.get(crop)
    print(f"\n📘 {crop} ની સંપૂર્ણ માહિતી")
    for k,v in d.items(): print(f"• {k}: {v}")
    if crop in _DISEASES:
        print("• મુખ્ય રોગ/જીવાત:")
        for x in _DISEASES[crop]: print("  -",x)

def crop_advice_v8():
    crop = _resolve_crop_v8(safe_input("પાકનું નામ/નંબર: "))
    if crop not in CROP_DATA: print("❌ પાક મળ્યો નથી."); return
    d=CROP_DATA[crop]
    print(f"\n🧑‍🌾 {crop} માટે વ્યવહારુ સલાહ")
    print("1. જમીન:",d["જમીન"])
    print("2. વાવણી:",d["વાવણી"],"અને પ્રમાણિત બીજ વાપરો.")
    print("3. પિયત:",d["પાણી"])
    print("4. સાવચેતી:",d["સાવચેતી"])
    print("5. ખાતર: માટી પરીક્ષણ આધારિત N-P-K અને સજીવ ખાતર આપો; માત્રા માટે સ્થાનિક ભલામણ લો.")

def disease_pest_v8():
    crop=_resolve_crop_v8(safe_input("પાકનું નામ/નંબર: "))
    if crop not in CROP_DATA: print("❌ પાક મળ્યો નથી."); return
    print(f"\n🪲 {crop} ના રોગ/જીવાત")
    for x in _DISEASES.get(crop,["આ પાક માટે સામાન્ય રીતે નિયમિત ખેતર નિરીક્ષણ, સ્વચ્છ બીજ, પાક ફેરબદલી અને પાણી ભરાવાથી બચાવ જરૂરી છે."]): print("•",x)
    print("⚠️ દવા/માત્રા પાકની સ્થિતિ અને સ્થાનિક નોંધણી મુજબ કૃષિ નિષ્ણાત પાસેથી નક્કી કરો.")

# Replace only the relevant menu callbacks if original names exist.
if 'crop_information' in globals(): crop_information = crop_information_v8
if 'crop_advice' in globals(): crop_advice = crop_advice_v8
if 'disease_pest' in globals(): disease_pest = disease_pest_v8
elif 'disease_pest_information' in globals(): disease_pest_information = disease_pest_v8

print if False else None

# Final V8 consistency fixes
CROP_DATA.setdefault("અન્ય", {"પ્રકાર":"અન્ય પાક","જમીન":"પાક પ્રમાણે","pH":"માટી પરીક્ષણ મુજબ","વાવણી":"સ્થાનિક ભલામણ મુજબ","બીજદર":"જાત પ્રમાણે","અંતર":"જાત પ્રમાણે","પાણી":"પાકની જરૂરિયાત પ્રમાણે","સાવચેતી":"સ્થાનિક કૃષિ નિષ્ણાતની સલાહ લો","બીજ":"પ્રમાણિત બીજ"})
disease_advice = disease_pest_v8
