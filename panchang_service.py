# -*- coding: utf-8 -*-
"""Local Panchang engine adapter for SMART AGRI-MARKET AI.

The astronomical calculations come from the audited MIT-licensed panchang
engine bundled under ai_backend/panchang_engine. This adapter only adds
Gujarat Kartikadi naming/localization; it does not scrape third-party sites.
"""
import json
import os
import subprocess
from datetime import date, datetime, timedelta
from typing import Any

ENGINE = os.path.join(os.path.dirname(__file__), "panchang_engine_bin")

GU_MONTHS = ["ચૈત્ર", "વૈશાખ", "જેઠ", "અષાઢ", "શ્રાવણ", "ભાદરવો", "આસો", "કારતક", "માગશર", "પોષ", "મહા", "ફાગણ"]
GU_TITHI = ["પડવો", "બીજ", "ત્રીજ", "ચોથ", "પાંચમ", "છઠ", "સાતમ", "આઠમ", "નોમ", "દશમ", "અગિયારસ", "બારસ", "તેરસ", "ચૌદસ", "પૂનમ"]
GU_NAK = ["અશ્વિની", "ભરણી", "કૃતિકા", "રોહિણી", "મૃગશીર્ષ", "આર્દ્રા", "પુનર્વસુ", "પુષ્ય", "આશ્લેષા", "મઘા", "પૂર્વાફાલ્ગુની", "ઉત્તરાફાલ્ગુની", "હસ્ત", "ચિત્રા", "સ્વાતિ", "વિશાખા", "અનુરાધા", "જ્યેષ્ઠા", "મૂળ", "પૂર્વાષાઢા", "ઉત્તરાષાઢા", "શ્રવણ", "ધનિષ્ઠા", "શતભિષા", "પૂર્વાભાદ્રપદ", "ઉત્તરાભાદ્રપદ", "રેવતી"]
GU_WEEK = ["રવિવાર", "સોમવાર", "મંગળવાર", "બુધવાર", "ગુરુવાર", "શુક્રવાર", "શનિવાર"]
GU_YOGA = ["વિષ્કંભ", "પ્રીતિ", "આયુષ્માન", "સૌભાગ્ય", "શોભન", "અતિગંડ", "સુકર્મા", "ધૃતિ", "શૂલ", "ગંડ", "વૃદ્ધિ", "ધ્રુવ", "વ્યાઘાત", "હર્ષણ", "વજ્ર", "સિદ્ધિ", "વ્યતિપાત", "વરીયાન", "પરિઘ", "શિવ", "સિદ્ધ", "સાધ્ય", "શુભ", "શુક્લ", "બ્રહ્મ", "ઇન્દ્ર", "વૈધૃતિ"]
GU_KARANA = ["કિંસ્તુઘ્ન", "બવ", "બાલવ", "કૌલવ", "તૈતિલ", "ગર", "વણિજ", "વિષ્ટિ", "શકુનિ", "ચતુષ્પાદ", "નાગ", "કિંસ્તુઘ્ન"]
GU_RASHI = ["મેષ", "વૃષભ", "મિથુન", "કર્ક", "સિંહ", "કન્યા", "તુલા", "વૃશ્ચિક", "ધન", "મકર", "કુંભ", "મીન"]


def _engine(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not os.path.exists(ENGINE):
        raise RuntimeError("Panchang engine binary not installed")
    proc = subprocess.run(
        [ENGINE], input="".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        text=True, capture_output=True, timeout=12,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "Panchang engine failed")
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def _gu_tithi(index: int) -> str:
    n = index + 1 if index < 15 else index - 14
    paksha = "સુદ" if index < 15 else "વદ"
    if n == 15:
        name = "પૂનમ" if index < 15 else "અમાસ"
    else:
        name = GU_TITHI[n - 1]
    return f"{paksha} {name}"


def _gu_year(gregorian: date, kartik_start: bool) -> int:
    # Gujarat/Kartikadi Vikram year changes at Kartika Shukla Pratipada.
    return gregorian.year + 57 if kartik_start else gregorian.year + 56


def _is_kartikadi_year_start(current: dict[str, Any]) -> bool:
    return current["amantaIndex"] == 7 and not current["isAdhika"] and any(
        x.get("index") == 0 and x.get("paksha") == "Shukla" for x in current.get("tithi", [])
    )



CHOGHADIYA_DAY = {
    0: ["ઉદ્વેગ", "ચલ", "લાભ", "અમૃત", "કાળ", "શુભ", "રોગ", "ઉદ્વેગ"],
    1: ["અમૃત", "કાળ", "શુભ", "રોગ", "ઉદ્વેગ", "ચલ", "લાભ", "અમૃત"],
    2: ["રોગ", "ઉદ્વેગ", "ચલ", "લાભ", "અમૃત", "કાળ", "શુભ", "રોગ"],
    3: ["લાભ", "અમૃત", "કાળ", "શુભ", "રોગ", "ઉદ્વેગ", "ચલ", "લાભ"],
    4: ["શુભ", "રોગ", "ઉદ્વેગ", "ચલ", "લાભ", "અમૃત", "કાળ", "શુભ"],
    5: ["ચલ", "લાભ", "અમૃત", "કાળ", "શુભ", "રોગ", "ઉદ્વેગ", "ચલ"],
    6: ["કાળ", "શુભ", "રોગ", "ઉદ્વેગ", "ચલ", "લાભ", "અમૃત", "કાળ"],
}
CHOGHADIYA_NIGHT = {
    0: ["શુભ", "અમૃત", "ચલ", "રોગ", "કાળ", "લાભ", "ઉદ્વેગ", "શુભ"],
    1: ["રોગ", "કાળ", "લાભ", "ઉદ્વેગ", "શુભ", "અમૃત", "ચલ", "રોગ"],
    2: ["કાળ", "લાભ", "ઉદ્વેગ", "શુભ", "અમૃત", "ચલ", "રોગ", "કાળ"],
    3: ["લાભ", "ઉદ્વેગ", "શુભ", "અમૃત", "ચલ", "રોગ", "કાળ", "લાભ"],
    4: ["ઉદ્વેગ", "શુભ", "અમૃત", "ચલ", "રોગ", "કાળ", "લાભ", "ઉદ્વેગ"],
    5: ["ચલ", "રોગ", "કાળ", "લાભ", "ઉદ્વેગ", "શુભ", "અમૃત", "ચલ"],
    6: ["અમૃત", "ચલ", "રોગ", "કાળ", "લાભ", "ઉદ્વેગ", "શુભ", "અમૃત"],
}
CHOGHADIYA_QUALITY = {"અમૃત": ("શુભ", "good"), "શુભ": ("શુભ", "good"), "લાભ": ("શુભ", "good"), "ચલ": ("તટસ્થ", "neutral"), "કાળ": ("અશુભ", "bad"), "રોગ": ("અશુભ", "bad"), "ઉદ્વેગ": ("અશુભ", "bad")}
RAHU_INDEX = [8,2,7,5,6,4,3]
YAMA_INDEX = [5,4,3,2,1,7,6]
GULIKA_INDEX = [7,6,5,4,3,2,1]

def _split_interval(start: str, end: str, names: list[str]) -> list[dict[str, Any]]:
    a, b = datetime.fromisoformat(start), datetime.fromisoformat(end)
    step = (b-a)/8
    out=[]
    for i,name in enumerate(names):
        quality, code = CHOGHADIYA_QUALITY[name]
        x=a+step*i; y=a+step*(i+1)
        out.append({"name":name,"start":x.isoformat(),"end":y.isoformat(),"quality":quality,"quality_code":code})
    return out

def _muhurta(day_sunrise: str, day_sunset: str, next_sunrise: str, vara: int) -> dict[str, Any]:
    sr=datetime.fromisoformat(day_sunrise); ss=datetime.fromisoformat(day_sunset); ns=datetime.fromisoformat(next_sunrise)
    day_part=(ss-sr)/8
    night_part=(ns-ss)/8
    rahu=RAHU_INDEX[vara]-1; yama=YAMA_INDEX[vara]-1; gulika=GULIKA_INDEX[vara]-1
    abh_start=sr+(ss-sr)*7/15; abh_end=sr+(ss-sr)*8/15
    return {
        "abhijit":{"start":abh_start.isoformat(),"end":abh_end.isoformat()},
        "rahukalam":{"start":(sr+day_part*rahu).isoformat(),"end":(sr+day_part*(rahu+1)).isoformat()},
        "yamaganda":{"start":(sr+day_part*yama).isoformat(),"end":(sr+day_part*(yama+1)).isoformat()},
        "gulika":{"start":(sr+day_part*gulika).isoformat(),"end":(sr+day_part*(gulika+1)).isoformat()},
    }

def get_panchang(day: date, lat: float, lon: float) -> dict[str, Any]:
    prev20 = day - timedelta(days=20)
    prev40 = day - timedelta(days=40)
    rows = _engine([
        {"date": day.isoformat(), "lat": lat, "lon": lon},
        {"date": prev20.isoformat(), "lat": lat, "lon": lon},
        {"date": prev40.isoformat(), "lat": lat, "lon": lon},
    ])
    if len(rows) < 3 or not rows[0].get("ok"):
        raise RuntimeError(rows[0].get("error", "Panchang unavailable") if rows else "Panchang unavailable")
    cur, prev20_row, prev40_row = rows[0], rows[1], rows[2]
    idx = int(cur["amantaIndex"])
    adhika = bool(cur["isAdhika"])
    nija = (not adhika and any(r.get("isAdhika") and int(r.get("amantaIndex", -1)) == idx for r in (prev20_row, prev40_row)))

    # Gujarati Samvat is Kartikadi: before Kartik Shukla Pratipada use Gregorian+56;
    # from Kartik Shukla onward use Gregorian+57.
    kartikadi_year = day.year + 56
    if idx > 7 or (idx == 7 and not adhika):
        kartikadi_year = day.year + 57

    month = GU_MONTHS[idx]
    month_type = "મલ માસ (અધિક)" if adhika else ("નિજ માસ" if nija else "સામાન્ય માસ")

    return {
        "ok": True,
        "date": day.isoformat(),
        "location": {"lat": lat, "lon": lon},
        "gujarati_date": f"{month} {month_type}",
        "month": month,
        "month_type": month_type,
        "vikram_samvat": kartikadi_year,
        "sunrise": cur["sunrise"],
        "sunset": cur["sunset"],
        "next_sunrise": cur["nextSunrise"],
        "vara": GU_WEEK[int(cur["vara"]["index"])],
        "rashi": {"index": int(cur.get("moonRashi", {}).get("index", -1)), "name": GU_RASHI[int(cur["moonRashi"]["index"])] if 0 <= int(cur.get("moonRashi", {}).get("index", -1)) < 12 else cur.get("moonRashi", {}).get("name", "")},
        "tithi": [dict(x, gujarati=_gu_tithi(int(x["index"]))) for x in cur.get("tithi", [])],
        "nakshatra": [dict(x, gujarati=GU_NAK[int(x["index"])]) for x in cur.get("nakshatra", [])],
        "yoga": [dict(x, gujarati=GU_YOGA[int(x["index"])]) for x in cur.get("yoga", [])],
        "karana": [dict(x, gujarati=GU_KARANA[0] if int(x["index"]) == 0 else GU_KARANA[1 + ((int(x["index"]) - 1) % 7)] if int(x["index"]) <= 56 else GU_KARANA[8 + (int(x["index"]) - 57)]) for x in cur.get("karana", [])],
        "choghadiya_day": _split_interval(cur["sunrise"], cur["sunset"], CHOGHADIYA_DAY[int(cur["vara"]["index"])]),
        "choghadiya_night": _split_interval(cur["sunset"], cur["nextSunrise"], CHOGHADIYA_NIGHT[int(cur["vara"]["index"])]),
        "muhurta": _muhurta(cur["sunrise"], cur["sunset"], cur["nextSunrise"], int(cur["vara"]["index"])),
        "engine": "ishankgupta95/panchang v5.4.0 MIT; audited local engine",
    }
