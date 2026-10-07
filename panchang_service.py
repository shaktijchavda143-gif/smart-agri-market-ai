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
        "tithi": [dict(x, gujarati=_gu_tithi(int(x["index"]))) for x in cur.get("tithi", [])],
        "nakshatra": [dict(x, gujarati=GU_NAK[int(x["index"])]) for x in cur.get("nakshatra", [])],
        "yoga": [dict(x, gujarati=GU_YOGA[int(x["index"])]) for x in cur.get("yoga", [])],
        "karana": [dict(x, gujarati=GU_KARANA[0] if int(x["index"]) == 0 else GU_KARANA[1 + ((int(x["index"]) - 1) % 7)] if int(x["index"]) <= 56 else GU_KARANA[8 + (int(x["index"]) - 57)]) for x in cur.get("karana", [])],
        "engine": "ishankgupta95/panchang v5.4.0 MIT; audited local engine",
    }
